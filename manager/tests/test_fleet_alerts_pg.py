"""TASK-068: fleet threshold alerts on PostgreSQL as bitscan_app (TP-M3-22, G33).

Checks CHK-M3-210 to CHK-M3-214 of tests/m3/test-plan.md through
FleetAlerts.run() with the real repositories, audit chain and alert counter.
Expected values come from the spec and the answers, not from the code: TS §8.4
L1291 (more than 5 % of agents offline; job queue age over 1 hour), TS §3.4
L242 (a host that still heartbeats with last_inventory_at older than twice the
interval), TS §5.3 L1047 and #44 (rows in the default scan_result partition,
raised by the manager's alert code), #65 (b) (denominator: agents not
decommissioned or awaiting approval; again only after the share was at or
below 5 %), (c) (once per agent until its next upload; base enrolled_at or the
approval when it never uploaded), (g) (once when rows appear, again only after
the partition was empty), #66 (the oldest queued job whose agent is online, at
most once per hour), #71 (one entry per event, alert.<kind>, actor system),
REQ-079 (1)-(5), and the 2026-10-23 ruling (a window is marked only after its
alert committed, so a rolled-back alert fires on the next run).

The checks are fleet-wide, so every test runs inside one bitscan_app
transaction that first marks every pre-existing agent decommissioned (outside
the denominator) and is rolled back at the end; each check is a savepoint
there, and the on-commit hooks run when it is released. The default-partition
rows are planted as owner in their own committed transactions and removed.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest

from bitscan_manager.runtime import Tx
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.scheduler.fleet_alerts import (
    FleetAlerts,
    FleetStores,
    pg_fleet_stores,
)

from .conftest import PgServer
from .test_db_maintain import result_at

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2027, 3, 1, 8, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
KINDS = ("agents_offline", "job_queue_age", "inventory_stale", "default_partition_rows")
CHECK_INDEX = {k: i for i, k in enumerate(KINDS)}  # run() order, one tx each


def counted(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


class Boom(RuntimeError):
    pass


@dataclass
class SpDb:
    """Each transaction is a savepoint of the test's rolled-back transaction;
    hooks run on release. fail_at holds transaction numbers (0-based, counted
    across runs) that raise after their body, i.e. a commit that fails."""

    conn: Conn
    fail_at: set[int] = field(default_factory=set)
    seen: int = 0
    before_commit: list[dict[str, float]] = field(default_factory=list)

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        hooks: list[Callable[[], None]] = []
        number = self.seen
        self.seen += 1
        conn = self.conn

        class _T:
            @property
            def conn(self) -> Conn:
                return conn

            def on_commit(self, hook: Callable[[], None]) -> None:
                hooks.append(hook)

        with self.conn.transaction():
            yield _T()
            self.before_commit.append({k: counted(k) for k in KINDS})
            if number in self.fail_at:
                raise Boom("commit failed")
        for hook in hooks:
            hook()

    def ping(self, timeout_s: float = 2.0) -> bool:
        return True


class Fleet:
    def __init__(self, conn: Conn, server: PgServer) -> None:
        self.conn, self.server = conn, server
        self.clock = Clock()
        self.alerts = FleetAlerts(self.clock)
        self.db = SpDb(conn)

    def agent(
        self,
        status: str,
        *,
        heartbeat: datetime | None = None,
        inventory: datetime | None = None,
        enrolled: datetime | None = None,
    ) -> UUID:
        enrolled = enrolled or self.clock.at - 30 * DAY
        row = self.conn.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, last_heartbeat_at,"
            " last_inventory_at, enrolled_at) SELECT md5(random()::text),"
            " 'fleet', '1', md5(random()::text) || md5(random()::text), %s, %s,"
            " CAST(%s AS agent_status), %s, %s, %s RETURNING agent_id",
            (enrolled, enrolled + 365 * DAY, status, heartbeat, inventory, enrolled),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def agents(self, status: str, n: int) -> list[UUID]:
        return [self.agent(status, inventory=self.clock.at) for _ in range(n)]

    def set_status(self, ids: list[UUID], status: str) -> None:
        self.conn.execute(
            "UPDATE agent SET status = CAST(%s AS agent_status)"
            " WHERE agent_id = ANY(%s)",
            (status, ids),
        )

    def queued(self, agent: UUID, created: datetime) -> UUID:
        row = self.conn.execute(
            "INSERT INTO scan_job (kind, agent_id, payload, created_at, pickup_by)"
            " VALUES ('inventory', %s, '{}', %s, %s) RETURNING job_id",
            (agent, created, created + DAY),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def run(self, at: datetime | None = None, **kw: Any) -> list[str]:
        if at is not None:
            self.clock.at = at
        return self.alerts.run(self.db, self.clock.at, **kw)

    def entries(self, kind: str) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            "SELECT actor, action, target, detail FROM audit_log"
            " WHERE detail->>'alert_kind' = %s AND audit_id > %s ORDER BY audit_id",
            (kind, self.start_id),
        ).fetchall()

    start_id = 0


@pytest.fixture
def fleet(migrated_db: PgServer) -> Iterator[Fleet]:
    with psycopg.connect(migrated_db.dsn("bitscan_app")) as conn:  # not autocommit
        assert conn.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        with conn.transaction(force_rollback=True):
            conn.execute(
                "UPDATE agent SET status = 'decommissioned'"
                " WHERE status <> 'decommissioned'"
            )
            f = Fleet(conn, migrated_db)
            row = conn.execute(
                "SELECT coalesce(max(audit_id), 0) FROM audit_log"
            ).fetchone()
            assert row is not None
            f.start_id = int(row[0])
            yield f


# ------------------------------------------------------------ CHK-M3-210


def test_offline_share_above_five_percent_and_rearm(fleet: Fleet) -> None:
    online = fleet.agents("online", 95)
    offline = fleet.agents("offline", 5)
    assert fleet.run() == []
    assert fleet.entries("agents_offline") == []  # 5 of 100: not above 5 %
    fleet.set_status(online[:1], "offline")  # 6 of 100
    fleet.run(fleet.clock.at + MIN)
    [entry] = fleet.entries("agents_offline")
    actor, action, target, detail = entry
    assert (actor, action) == ("system", "alert.agents_offline")
    assert detail["alert"] is True and detail["alert_kind"] == "agents_offline"
    assert (detail["offline"], detail["eligible"]) == (6, 100)
    fleet.run(fleet.clock.at + MIN)  # still 6
    fleet.set_status(online[1:3], "offline")  # 8: still above, no repeat
    fleet.run(fleet.clock.at + 2 * HOUR)
    assert len(fleet.entries("agents_offline")) == 1
    fleet.set_status(online[:3], "online")  # back to exactly 5: re-armed
    fleet.run(fleet.clock.at + MIN)
    assert len(fleet.entries("agents_offline")) == 1
    fleet.set_status(online[:1], "offline")  # 6 again
    fleet.run(fleet.clock.at + MIN)
    assert len(fleet.entries("agents_offline")) == 2
    assert len(offline) == 5


def test_denominator_excludes_decommissioned_and_awaiting(fleet: Fleet) -> None:
    for status, n in (("online", 40), ("enrolled", 30), ("stale", 24)):
        fleet.agents(status, n)
    fleet.agents("offline", 6)  # 6 of 100 eligible
    fleet.agents("decommissioned", 60)
    fleet.agents("awaiting_approval", 60)  # counted, 6 / 220 would be 2.7 %
    fleet.run()
    [entry] = fleet.entries("agents_offline")
    assert (entry[3]["offline"], entry[3]["eligible"]) == (6, 100)


def test_no_eligible_agents_raise_nothing(fleet: Fleet) -> None:
    fleet.agents("decommissioned", 3)
    fleet.agents("awaiting_approval", 3)
    assert fleet.run() == []
    assert fleet.entries("agents_offline") == []


def test_one_offline_agent_alone_is_above_five_percent(fleet: Fleet) -> None:
    fleet.agents("offline", 1)
    fleet.run()
    assert len(fleet.entries("agents_offline")) == 1


# ------------------------------------------------------------ CHK-M3-211


def test_queue_age_of_online_agents(fleet: Fleet) -> None:
    now = fleet.clock.at
    on = fleet.agent("online", heartbeat=now, inventory=now)
    off = fleet.agent("offline", heartbeat=now - DAY, inventory=now)
    fleet.queued(off, now - 23 * HOUR)  # an offline agent's old job: not counted
    fleet.queued(on, now - HOUR)  # exactly 1 h: not over
    fleet.run()
    assert fleet.entries("job_queue_age") == []
    fleet.run(now + SEC)  # now 1 h + 1 s
    [entry] = fleet.entries("job_queue_age")
    actor, action, target, detail = entry
    assert (actor, action, target) == ("system", "alert.job_queue_age", "fleet")
    assert detail["alert_kind"] == "job_queue_age" and detail["alert"] is True
    assert detail["oldest_age_s"] == 3601
    fleet.run(now + SEC + 59 * MIN + 59 * SEC)  # within the hour: none
    assert len(fleet.entries("job_queue_age")) == 1
    fleet.run(now + SEC + HOUR)  # an hour after the alert: again
    assert len(fleet.entries("job_queue_age")) == 2


def test_queue_age_ignores_dispatched_and_held_agents(fleet: Fleet) -> None:
    now = fleet.clock.at
    on = fleet.agent("online", heartbeat=now, inventory=now)
    job = fleet.queued(on, now - 5 * HOUR)
    fleet.conn.execute(
        "UPDATE scan_job SET state = 'dispatched', dispatched_at = %s"
        " WHERE job_id = %s",
        (now, job),
    )
    for status in ("stale", "enrolled", "awaiting_approval"):
        fleet.queued(fleet.agent(status, inventory=now), now - 5 * HOUR)
    fleet.run()
    assert fleet.entries("job_queue_age") == []


# ------------------------------------------------------------ CHK-M3-212


def test_inventory_stale_boundaries_and_rearm(fleet: Fleet) -> None:
    now = fleet.clock.at
    twice = 2 * timedelta(seconds=21_600)  # the seeded inventory interval
    edge = fleet.agent("online", heartbeat=now, inventory=now - twice)
    over = fleet.agent("online", heartbeat=now, inventory=now - twice - SEC)
    off = fleet.agent("offline", heartbeat=now - DAY, inventory=now - 10 * twice)
    stale = fleet.agent("stale", heartbeat=now - 15 * MIN, inventory=now - 10 * twice)
    fleet.run()
    entries = fleet.entries("inventory_stale")
    assert [e[2] for e in entries] == [f"agent:{over}"]
    actor, action, _, detail = entries[0]
    assert (actor, action) == ("system", "alert.inventory_stale")
    assert detail["alert"] is True

    def count(agent: UUID) -> int:
        return [e[2] for e in fleet.entries("inventory_stale")].count(f"agent:{agent}")

    fleet.run(now + MIN)  # over still stale: once until its next upload
    assert count(over) == 1
    assert count(edge) == 1  # 2 x interval + 1 min old now: over the limit
    fleet.conn.execute(
        "UPDATE agent SET last_inventory_at = %s WHERE agent_id = %s", (now + MIN, over)
    )
    fleet.run(now + 2 * MIN)  # over uploaded: re-armed, nothing new
    assert (count(over), count(edge)) == (1, 1)
    later = now + MIN + twice + SEC  # over stale again after that upload
    fleet.conn.execute(
        "UPDATE agent SET last_heartbeat_at = %s WHERE agent_id = ANY(%s)",
        (later, [edge, over]),
    )
    fleet.run(later)
    assert (count(over), count(edge)) == (2, 1)  # edge never left the stale set
    assert count(off) == 0 and count(stale) == 0  # only hosts that are online


def test_never_uploaded_is_aged_from_enrolment(fleet: Fleet) -> None:
    now = fleet.clock.at
    twice = timedelta(seconds=43_200)
    young = fleet.agent("online", heartbeat=now, enrolled=now - twice)
    old = fleet.agent("online", heartbeat=now, enrolled=now - twice - SEC)
    fleet.run()
    assert [e[2] for e in fleet.entries("inventory_stale")] == [f"agent:{old}"]
    assert young != old


def test_inventory_stale_follows_the_interval_setting(fleet: Fleet) -> None:
    now = fleet.clock.at
    fleet.conn.execute(
        "UPDATE system_schedule SET interval_s = 3600 WHERE job_kind = 'inventory'"
    )
    a = fleet.agent("online", heartbeat=now, inventory=now - 2 * HOUR - SEC)
    b = fleet.agent("online", heartbeat=now, inventory=now - 2 * HOUR)
    fleet.run()
    assert [e[2] for e in fleet.entries("inventory_stale")] == [f"agent:{a}"]
    assert b != a


# ------------------------------------------------------------ CHK-M3-213


@contextmanager
def planted_default_row(server: PgServer) -> Iterator[None]:
    with server.connect("bitscan_migrate") as owner:
        owner.execute("SET ROLE bitscan_owner")
        before = owner.execute("SELECT count(*) FROM scan_result_default").fetchone()
        assert before == (0,)
        result_at(owner, datetime(2099, 6, 1, tzinfo=UTC))  # beyond every partition
        assert owner.execute("SELECT count(*) FROM scan_result_default").fetchone() == (
            1,
        )
    try:
        yield
    finally:
        with server.connect("bitscan_migrate") as owner:
            owner.execute("SET ROLE bitscan_owner")
            owner.execute(
                "DELETE FROM scan_result WHERE job_created_at >= '2099-01-01'"
            )


def test_default_partition_rows(fleet: Fleet) -> None:
    fleet.run()
    assert fleet.entries("default_partition_rows") == []
    with planted_default_row(fleet.server):
        fleet.run(fleet.clock.at + MIN)
        [entry] = fleet.entries("default_partition_rows")
        actor, action, target, detail = entry
        assert (actor, action) == ("system", "alert.default_partition_rows")
        assert detail["alert"] is True
        assert detail["alert_kind"] == "default_partition_rows"
        fleet.run(fleet.clock.at + DAY)  # still rows: none
        assert len(fleet.entries("default_partition_rows")) == 1
    fleet.run(fleet.clock.at + MIN)  # emptied: re-armed
    assert len(fleet.entries("default_partition_rows")) == 1
    with planted_default_row(fleet.server):
        fleet.run(fleet.clock.at + MIN)
    assert len(fleet.entries("default_partition_rows")) == 2


# ------------------------------------------------------------ CHK-M3-214


def _all_four(fleet: Fleet) -> None:
    now = fleet.clock.at
    fleet.agents("offline", 1)
    on = fleet.agent("online", heartbeat=now, inventory=now - 13 * HOUR)
    fleet.queued(on, now - 2 * HOUR)


def test_each_alert_is_one_entry_counted_only_after_commit(fleet: Fleet) -> None:
    _all_four(fleet)
    before = {k: counted(k) for k in KINDS}
    with planted_default_row(fleet.server):
        assert fleet.run() == []
        for kind in KINDS:
            got = fleet.entries(kind)
            assert len(got) == 1, kind
            assert got[0][1] == f"alert.{kind}" and got[0][0] == "system"
            assert got[0][3]["alert"] is True and got[0][3]["alert_kind"] == kind
            # inside its own transaction, before the commit: not yet counted
            assert fleet.db.before_commit[CHECK_INDEX[kind]][kind] == before[kind]
            assert counted(kind) == before[kind] + 1, kind


@pytest.mark.parametrize("kind", KINDS)
def test_a_failed_commit_leaves_the_window_unmarked(
    fleet: Fleet, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Ruling 2026-10-23: the alert rolled back, so the next run alerts."""
    _all_four(fleet)
    before = {k: counted(k) for k in KINDS}
    fleet.db.fail_at = {CHECK_INDEX[kind]}
    caplog.set_level(logging.ERROR)
    with planted_default_row(fleet.server):
        assert fleet.run() == [kind]
        assert fleet.entries(kind) == []
        assert counted(kind) == before[kind]
        for other in KINDS:
            if other != kind:  # the other checks still ran and committed
                assert len(fleet.entries(other)) == 1, other
        [record] = [
            r for r in caplog.records if r.getMessage() == "fleet alert check failed"
        ]
        assert getattr(record, "data", None) == {"check": kind, "exc_type": "Boom"}
        assert fleet.run(fleet.clock.at + MIN) == []
        assert len(fleet.entries(kind)) == 1
        assert counted(kind) == before[kind] + 1
        for other in KINDS:
            if other != kind:  # no repeat of the committed ones
                assert len(fleet.entries(other)) == 1, other


def test_a_check_that_raises_does_not_stop_the_others(fleet: Fleet) -> None:
    _all_four(fleet)

    def broken(tx: Tx) -> FleetStores:
        real = pg_fleet_stores(tx)

        class Agents:
            def count_by_status(self) -> Any:
                raise Boom("CANARY-0a1b2c3d4e5f6071")

            def stale_inventory(self, *a: Any) -> list[UUID]:
                return real.agents.stale_inventory(*a)

        return replace(real, agents=Agents())

    assert fleet.run(stores=broken) == ["agents_offline"]
    assert fleet.entries("agents_offline") == []
    assert len(fleet.entries("job_queue_age")) == 1
    assert len(fleet.entries("inventory_stale")) == 1
    assert fleet.run(fleet.clock.at + MIN) == []
    assert len(fleet.entries("agents_offline")) == 1
