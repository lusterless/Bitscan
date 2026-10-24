"""TASK-065: offline_sweep core on PostgreSQL as bitscan_app (TP-M3-19, G33).

Checks CHK-M3-180 to CHK-M3-188 of tests/m3/test-plan.md through run_sweep()
with a fake clock (the `now` argument) and real AppDatabase transactions, so
each step really commits on its own. Expected values come from the spec and
the rulings, not from the code: TS §3.3 L218 (online < 10 min, stale 10-30
min, offline > 30 min), L220 (decommission after decommission_after_days, 0 =
never, token revoked), TS §3.4 L244 (inventory dispatched and not uploaded
within 30 minutes fails; never retried), TS §4.4 (queued jobs past pickup_by
expire), REQ-078 (1)-(6), #25 (never-heartbeat age from enrolled_at), #73 (b)
(decommission measured from the last heartbeat or the #25 base), #73 (d) (one
audit entry per decommission, actor system; status changes not audited),
REQ-086 (2) (jobs-expired metric after commit), decisions 2026-10-23 (the
GREATEST age base with the latest approved decided_at; online needs a
heartbeat since that base). The sweep is fleet-wide, so every assertion is on
this file's own agents and jobs; counts from the SweepResult are compared only
where other files' rows cannot change them.
"""

import logging
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.enrolment import EnrolmentRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Tx
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.enrolment.token_check import (
    AgentTokenRefused,
    check_agent_token,
)
from bitscan_manager.services.scheduler.sweep import (
    Stores,
    SweepResult,
    pg_stores,
    run_sweep,
)
from bitscan_manager.services.users.accounts import TxAudit

from .conftest import PgServer
from .test_jobs_repo_pg import plant_compliance

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
MIN = timedelta(minutes=1)
DAY = timedelta(days=1)
HOUR_ = timedelta(hours=1)
CANARY = "CANARY-5a0e1f2d3c4b6978"


@dataclass(frozen=True)
class Agent:
    agent_id: UUID
    token: str
    machine_id: str


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    d.open()
    yield d
    d.close()


@pytest.fixture
def conn(migrated_db: PgServer) -> Iterator[Conn]:
    with migrated_db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def set_setting(db: AppDatabase, key: str, value: object) -> None:
    with db.transaction() as tx:
        assert SettingsRepo(tx.conn).write_value(key, value, None, T0)


@pytest.fixture
def decommission_days(db: AppDatabase) -> Iterator[Callable[[int], None]]:
    """Sets decommission_after_days for one test; the seeded 7 is restored."""
    yield lambda days: set_setting(db, "decommission_after_days", days)
    set_setting(db, "decommission_after_days", 7)


def new_agent(
    conn: Conn,
    status: str,
    *,
    heartbeat: datetime | None,
    enrolled: datetime,
    revoked: datetime | None = None,
) -> Agent:
    tok = new_agent_token(AgentTokenKind.AGENT)
    machine = secrets.token_hex(16)
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, token_revoked_at, status,"
        " last_heartbeat_at, enrolled_at) VALUES (%s, %s, '1.0.0', %s, %s, %s, %s,"
        " CAST(%s AS agent_status), %s, %s) RETURNING agent_id",
        (
            machine,
            f"h-{secrets.token_hex(3)}",
            token_hash(tok),
            enrolled,
            enrolled + 365 * DAY,
            revoked,
            status,
            heartbeat,
            enrolled,
        ),
    ).fetchone()
    assert row is not None
    return Agent(UUID(str(row[0])), tok, machine)


def decided_request(conn: Conn, a: Agent, decision: str, decided: datetime) -> None:
    tid = conn.execute(
        "INSERT INTO enrollment_token (token_hash, max_uses, expires_at, created_by)"
        " VALUES (%s, 10, %s, 1) RETURNING token_id",
        (token_hash(new_agent_token(AgentTokenKind.ENROLMENT)), decided + DAY),
    ).fetchone()
    assert tid is not None
    conn.execute(
        "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id,"
        " hostname, machine_id, agent_version, new_token_hash, token_expires_at,"
        " source_ip, requested_at, decision, decided_at) VALUES ('reenrol', %s, %s,"
        " 'h', %s, '1', %s, %s, '10.0.0.1', %s, %s, %s)",
        (
            a.agent_id,
            tid[0],
            a.machine_id,
            token_hash(new_agent_token(AgentTokenKind.AGENT)),
            decided + 365 * DAY,
            decided - MIN,
            decision,
            decided,
        ),
    )


def inventory_job(
    conn: Conn,
    a: Agent,
    state: str,
    *,
    created: datetime,
    pickup_by: datetime,
    dispatched: datetime | None = None,
) -> UUID:
    jid = uuid4()
    payload = {
        "job_id": str(jid),
        "agent_id": str(a.agent_id),
        "kind": "inventory",
        "pickup_by": pickup_by.isoformat(),
    }
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
        " pickup_by, dispatched_at) VALUES (%s, 'inventory', %s,"
        " CAST(%s AS scan_state), %s, %s, %s, %s)",
        (jid, a.agent_id, state, Jsonb(payload), created, pickup_by, dispatched),
    )
    return jid


def status(conn: Conn, a: Agent) -> str:
    row = conn.execute(
        "SELECT status::text FROM agent WHERE agent_id = %s", (a.agent_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def revoked_at(conn: Conn, a: Agent) -> datetime | None:
    row = conn.execute(
        "SELECT token_revoked_at FROM agent WHERE agent_id = %s", (a.agent_id,)
    ).fetchone()
    assert row is not None
    value: datetime | None = row[0]
    return value


def job_state(conn: Conn, jid: UUID) -> tuple[str, datetime | None]:
    row = conn.execute(
        "SELECT state::text, finished_at FROM scan_job WHERE job_id = %s", (jid,)
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1]


def jobs_of(conn: Conn, agents: list[Agent]) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT job_id, retry_of FROM scan_job WHERE agent_id = ANY(%s)"
        " ORDER BY job_id",
        ([a.agent_id for a in agents],),
    ).fetchall()


def audit_for(conn: Conn, agents: list[Agent]) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT actor, action, target, detail::text FROM audit_log"
        " WHERE target = ANY(%s) ORDER BY audit_id",
        ([f"agent:{a.agent_id}" for a in agents],),
    ).fetchall()


def jobs_expired_counted() -> float:
    return REGISTRY.get_sample_value("bitscan_jobs_expired_total") or 0.0


def sweep(db: AppDatabase, now: datetime, **kw: Any) -> SweepResult:
    got = run_sweep(db, now, **kw)
    assert isinstance(got, SweepResult)
    return got


# ------------------------------------------------------------ CHK-M3-180


@pytest.mark.parametrize("start", ["online", "stale", "offline", "enrolled"])
def test_status_boundaries_from_the_last_heartbeat(
    db: AppDatabase, conn: Conn, start: str
) -> None:
    now = T0
    cases = {
        9 * MIN + 59 * SEC: "online",
        10 * MIN: "stale",
        29 * MIN + 59 * SEC: "stale",
        30 * MIN: "stale",
        30 * MIN + SEC: "offline",
    }
    agents = {
        age: new_agent(conn, start, heartbeat=now - age, enrolled=now - DAY)
        for age in cases
    }
    got = sweep(db, now)
    assert got.failed_steps == []
    assert {age: status(conn, a) for age, a in agents.items()} == cases


def test_status_moves_on_as_the_clock_moves(db: AppDatabase, conn: Conn) -> None:
    a = new_agent(conn, "online", heartbeat=T0, enrolled=T0 - DAY)
    seen = []
    for at in (T0 + 5 * MIN, T0 + 10 * MIN, T0 + 30 * MIN, T0 + 31 * MIN):
        sweep(db, at)
        seen.append(status(conn, a))
    assert seen == ["online", "stale", "stale", "offline"]


# ------------------------------------------------------------ CHK-M3-181


def test_never_heartbeat_agent_is_aged_from_enrolled_at(
    db: AppDatabase, conn: Conn
) -> None:
    now = T0 + 2 * DAY
    young = new_agent(conn, "enrolled", heartbeat=None, enrolled=now - 9 * MIN)
    stale = new_agent(conn, "enrolled", heartbeat=None, enrolled=now - 10 * MIN)
    late = new_agent(conn, "enrolled", heartbeat=None, enrolled=now - 30 * MIN - SEC)
    sweep(db, now)
    # no heartbeat, so never online (TS §3.3 L218, ruling 2026-10-23)
    assert [status(conn, a) for a in (young, stale, late)] == [
        "enrolled",
        "stale",
        "offline",
    ]


def test_age_base_is_the_latest_approval(db: AppDatabase, conn: Conn) -> None:
    """Decisions 2026-10-23 (4) and TASK-051 r1: an approved re-enrolment of a
    host with an old heartbeat is aged from the approval and is not online
    until it heartbeats again; a rejected request does not move the base."""
    now = T0 + 3 * DAY
    old_hb, old_enrol = now - 20 * DAY, now - 30 * DAY
    fresh = new_agent(conn, "offline", heartbeat=old_hb, enrolled=old_enrol)
    decided_request(conn, fresh, "approved", now - 5 * MIN)
    aged = new_agent(conn, "offline", heartbeat=old_hb, enrolled=old_enrol)
    decided_request(conn, aged, "approved", now - 30 * MIN - SEC)
    beat = new_agent(conn, "offline", heartbeat=now - 2 * MIN, enrolled=old_enrol)
    decided_request(conn, beat, "approved", now - 5 * MIN)
    rejected = new_agent(conn, "offline", heartbeat=old_hb, enrolled=old_enrol)
    decided_request(conn, rejected, "rejected", now - 5 * MIN)
    older = new_agent(conn, "offline", heartbeat=old_hb, enrolled=old_enrol)
    decided_request(conn, older, "approved", now - 25 * DAY)  # before the heartbeat
    decided_request(conn, older, "approved", now - 12 * MIN)  # the latest counts
    sweep(db, now)
    assert status(conn, fresh) == "enrolled"
    assert status(conn, aged) == "offline"
    assert status(conn, beat) == "online"
    assert status(conn, older) == "stale"
    # the 20-day-old heartbeat is the base of the rejected one: decommissioned
    assert status(conn, rejected) == "decommissioned"
    for a in (fresh, aged, beat, older):
        assert revoked_at(conn, a) is None


# ------------------------------------------------------------ CHK-M3-182


def test_decommission_after_seven_days(db: AppDatabase, conn: Conn) -> None:
    now = T0 + 10 * DAY
    edge = new_agent(conn, "offline", heartbeat=now - 7 * DAY, enrolled=now - 9 * DAY)
    over = new_agent(
        conn, "offline", heartbeat=now - 7 * DAY - SEC, enrolled=now - 9 * DAY
    )
    # still marked online: the status step runs first in the same sweep
    lagging = new_agent(conn, "online", heartbeat=now - 8 * DAY, enrolled=now - 9 * DAY)
    never = new_agent(conn, "enrolled", heartbeat=None, enrolled=now - 7 * DAY - SEC)
    gone = [over, lagging, never]
    got = sweep(db, now)
    assert got.failed_steps == []
    assert got.decommissioned >= 3
    assert status(conn, edge) == "offline" and revoked_at(conn, edge) is None
    for a in gone:
        assert status(conn, a) == "decommissioned"
        assert revoked_at(conn, a) == now
    entries = audit_for(conn, [edge, *gone])
    assert sorted(e[:3] for e in entries) == sorted(
        ("system", "agent.decommission", f"agent:{a.agent_id}") for a in gone
    )
    for e in entries:
        assert '"alert"' not in e[3]  # an audit entry, not an alert (#71)
        for a in gone:
            assert a.token not in e[3] and token_hash(a.token) not in e[3]
    # the token is now refused as revoked (REQ-078 (2))
    for a in gone:
        with db.transaction() as tx:
            with pytest.raises(AgentTokenRefused) as refused:
                check_agent_token(
                    AgentRepo(tx.conn),
                    EnrolmentRepo(tx.conn),
                    TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                    raw=a.token,
                    machine_id_header=a.machine_id,
                    now=now + MIN,
                )
        assert (refused.value.status, refused.value.type) == (401, "token_revoked")
    # a later sweep neither repeats the entry nor touches the decommissioned
    sweep(db, now + DAY)
    assert len(audit_for(conn, gone)) == 3
    assert all(revoked_at(conn, a) == now for a in gone)


def test_decommission_zero_means_never(
    db: AppDatabase, conn: Conn, decommission_days: Callable[[int], None]
) -> None:
    now = T0 + 500 * DAY
    a = new_agent(conn, "offline", heartbeat=now - 400 * DAY, enrolled=now - 401 * DAY)
    n = new_agent(conn, "enrolled", heartbeat=None, enrolled=now - 400 * DAY)
    decommission_days(0)
    got = sweep(db, now)
    assert got.failed_steps == [] and got.decommissioned == 0
    assert [status(conn, x) for x in (a, n)] == ["offline", "offline"]
    assert revoked_at(conn, a) is None and revoked_at(conn, n) is None
    assert audit_for(conn, [a, n]) == []


def test_decommission_reads_the_setting(
    db: AppDatabase, conn: Conn, decommission_days: Callable[[int], None]
) -> None:
    now = T0 + 600 * DAY
    a = new_agent(conn, "offline", heartbeat=now - DAY - SEC, enrolled=now - 2 * DAY)
    b = new_agent(conn, "offline", heartbeat=now - DAY, enrolled=now - 2 * DAY)
    decommission_days(1)
    sweep(db, now)
    assert status(conn, a) == "decommissioned" and revoked_at(conn, a) == now
    assert status(conn, b) == "offline" and revoked_at(conn, b) is None
    assert [e[3] for e in audit_for(conn, [a])] == ['{"after_days": 1}']


# ------------------------------------------------------------ CHK-M3-183


def test_expiry_and_inventory_timeout(
    db: AppDatabase, conn: Conn, migrated_db: PgServer
) -> None:
    now = T0 + 20 * DAY
    a = new_agent(conn, "online", heartbeat=now - MIN, enrolled=now - DAY)
    created = now - 2 * HOUR_
    past = inventory_job(conn, a, "queued", created=created, pickup_by=now - SEC)
    ahead = inventory_job(conn, a, "queued", created=created, pickup_by=now + SEC)

    def dispatched(age: timedelta, state: str = "dispatched") -> UUID:
        return inventory_job(
            conn, a, state, created=created, pickup_by=now + DAY, dispatched=now - age
        )

    late = dispatched(30 * MIN + SEC)
    at_30 = dispatched(30 * MIN)
    young = dispatched(29 * MIN + 59 * SEC)
    done = dispatched(31 * MIN, "completed")
    compliance = plant_compliance(
        migrated_db,
        a.agent_id,
        created=created,
        state="dispatched",
        dispatched_at=now - 31 * MIN,
    )
    before_jobs = jobs_of(conn, [a])
    got = sweep(db, now)
    assert got.failed_steps == []
    assert job_state(conn, past) == ("expired", now)
    assert job_state(conn, ahead) == ("queued", None)
    assert job_state(conn, late) == ("failed", now)
    assert job_state(conn, at_30) == ("dispatched", None)
    assert job_state(conn, young) == ("dispatched", None)
    assert job_state(conn, done)[0] == "completed"
    assert job_state(conn, compliance) == ("dispatched", None)  # M9's rules
    # inventory jobs are never retried: no row created, no retry_of anywhere
    assert jobs_of(conn, [a]) == before_jobs
    assert all(r[1] is None for r in before_jobs)
    # a second sweep leaves the failed and expired jobs as they are
    sweep(db, now + HOUR_)
    assert job_state(conn, late) == ("failed", now)
    assert job_state(conn, past) == ("expired", now)
    assert jobs_of(conn, [a]) == before_jobs


# ------------------------------------------------------------ CHK-M3-184


def test_held_agents_are_not_touched(db: AppDatabase, conn: Conn) -> None:
    now = T0 + 30 * DAY
    waiting = new_agent(
        conn, "awaiting_approval", heartbeat=None, enrolled=now - 40 * DAY
    )
    revoked = now - 20 * DAY
    old = new_agent(
        conn,
        "decommissioned",
        heartbeat=now - 31 * MIN,
        enrolled=now - 40 * DAY,
        revoked=revoked,
    )
    fresh = new_agent(
        conn,
        "decommissioned",
        heartbeat=now - MIN,
        enrolled=now - 40 * DAY,
        revoked=revoked,
    )
    sweep(db, now)
    assert status(conn, waiting) == "awaiting_approval"
    assert revoked_at(conn, waiting) is None
    assert status(conn, old) == "decommissioned" and revoked_at(conn, old) == revoked
    assert status(conn, fresh) == "decommissioned"
    assert audit_for(conn, [waiting, old, fresh]) == []


# ------------------------------------------------------------ CHK-M3-185


class _Boom(RuntimeError):
    pass


def failing(step: str, *, after_call: bool = False) -> Callable[[Tx], Stores]:
    """A stores factory whose `step` raises (with a canary message); with
    after_call the real repository call runs first, so the step's own
    transaction must undo it."""

    def build(tx: Tx) -> Stores:
        real = pg_stores(tx)

        class Agents:
            def apply_heartbeat_ages(self, *a: Any) -> int:
                if step == "statuses":
                    raise _Boom(CANARY)
                return real.agents.apply_heartbeat_ages(*a)

            def decommission_offline(self, *a: Any) -> list[UUID]:
                if step == "decommission":
                    if after_call:
                        real.agents.decommission_offline(*a)
                    raise _Boom(CANARY)
                return real.agents.decommission_offline(*a)

        class Jobs:
            def expire_past_pickup(self, now: datetime) -> int:
                if step == "expire":
                    if after_call:
                        real.jobs.expire_past_pickup(now)
                    raise _Boom(CANARY)
                return real.jobs.expire_past_pickup(now)

            def fail_dispatched_inventory(self, *a: Any) -> int:
                if step == "inventory_timeout":
                    raise _Boom(CANARY)
                return real.jobs.fail_dispatched_inventory(*a)

        return replace(real, agents=Agents(), jobs=Jobs())

    return build


@pytest.mark.parametrize(
    ("step", "after_call"),
    [
        ("statuses", False),
        ("decommission", True),
        ("expire", True),
        ("inventory_timeout", False),
    ],
)
def test_a_failing_step_leaves_the_others_applied(
    db: AppDatabase,
    conn: Conn,
    caplog: pytest.LogCaptureFixture,
    step: str,
    after_call: bool,
) -> None:
    now = (
        T0
        + 40 * DAY
        + {"statuses": 0, "decommission": 1, "expire": 2}.get(step, 3) * DAY
    )
    to_offline = new_agent(conn, "online", heartbeat=now - 31 * MIN, enrolled=now - DAY)
    to_decom = new_agent(
        conn, "offline", heartbeat=now - 8 * DAY, enrolled=now - 9 * DAY
    )
    q = inventory_job(
        conn, to_offline, "queued", created=now - DAY, pickup_by=now - SEC
    )
    d = inventory_job(
        conn,
        to_offline,
        "dispatched",
        created=now - DAY,
        pickup_by=now + DAY,
        dispatched=now - 31 * MIN,
    )
    counted = jobs_expired_counted()
    caplog.set_level(logging.DEBUG)
    got = sweep(db, now, stores=failing(step, after_call=after_call))
    assert got.failed_steps == [step]
    applied = {
        "statuses": status(conn, to_offline) == "offline",
        "decommission": status(conn, to_decom) == "decommissioned"
        and revoked_at(conn, to_decom) == now,
        "expire": job_state(conn, q)[0] == "expired",
        "inventory_timeout": job_state(conn, d)[0] == "failed",
    }
    assert applied == {name: name != step for name in applied}
    if step == "decommission":
        assert revoked_at(conn, to_decom) is None  # the step's own rollback
        assert audit_for(conn, [to_decom]) == []
    if step == "expire":
        assert job_state(conn, q) == ("queued", None)
        assert jobs_expired_counted() == counted  # nothing counted on rollback
    # logged by step name and exception type only, never the message
    records = [r for r in caplog.records if r.name.startswith("bitscan_manager")]
    failed = [r for r in records if r.getMessage() == "sweep step failed"]
    assert len(failed) == 1
    assert getattr(failed[0], "data", None) == {"step": step, "exc_type": "_Boom"}
    for r in caplog.records:
        assert CANARY not in r.getMessage()
        assert CANARY not in repr(vars(r))
    # the next sweep completes the failed step
    again = sweep(db, now + SEC)
    assert again.failed_steps == []
    assert status(conn, to_offline) == "offline"
    assert status(conn, to_decom) == "decommissioned"
    assert job_state(conn, q)[0] == "expired"
    assert job_state(conn, d)[0] == "failed"


# ------------------------------------------------------------ CHK-M3-186


def test_status_changes_write_no_audit_entry(db: AppDatabase, conn: Conn) -> None:
    now = T0 + 60 * DAY
    agents = [
        new_agent(conn, "enrolled", heartbeat=now - MIN, enrolled=now - DAY),
        new_agent(conn, "online", heartbeat=now - 11 * MIN, enrolled=now - DAY),
        new_agent(conn, "stale", heartbeat=now - 31 * MIN, enrolled=now - DAY),
        new_agent(conn, "offline", heartbeat=now - MIN, enrolled=now - DAY),
    ]
    got = sweep(db, now)
    assert got.statuses_changed >= 4
    assert [status(conn, a) for a in agents] == ["online", "stale", "offline", "online"]
    assert audit_for(conn, agents) == []


# ------------------------------------------------------------ CHK-M3-187


class EdgeDb:
    """The real AppDatabase; after each step's body and before its commit it
    records the metric, and it can fail one step there (forcing a rollback
    after the step has done all its work)."""

    def __init__(self, db: AppDatabase, fail_step: int | None = None) -> None:
        self.db, self.fail_step = db, fail_step
        self.before_commit: list[float] = []

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self.db.transaction() as tx:
            yield tx
            self.before_commit.append(jobs_expired_counted())
            if len(self.before_commit) - 1 == self.fail_step:
                raise _Boom("after the step body")


EXPIRE_STEP = 2  # statuses, decommission, expire, inventory_timeout


def test_jobs_expired_metric_rises_after_commit(db: AppDatabase, conn: Conn) -> None:
    now = T0 + 70 * DAY
    a = new_agent(conn, "online", heartbeat=now - MIN, enrolled=now - DAY)
    mine = [
        inventory_job(conn, a, "queued", created=now - DAY, pickup_by=now - k * SEC)
        for k in (1, 2, 3)
    ]
    counted = jobs_expired_counted()
    edge = EdgeDb(db)
    got = sweep(edge, now)  # type: ignore[arg-type]
    assert all(job_state(conn, j)[0] == "expired" for j in mine)
    assert got.expired >= 3
    assert edge.before_commit[EXPIRE_STEP] == counted  # not before the commit
    assert jobs_expired_counted() == counted + got.expired
    # nothing left to expire: the metric does not move
    again = sweep(db, now)
    assert again.expired == 0
    assert jobs_expired_counted() == counted + got.expired


def test_jobs_expired_metric_not_raised_when_the_step_rolls_back(
    db: AppDatabase, conn: Conn
) -> None:
    now = T0 + 75 * DAY
    a = new_agent(conn, "online", heartbeat=now - MIN, enrolled=now - DAY)
    j = inventory_job(conn, a, "queued", created=now - DAY, pickup_by=now - SEC)
    counted = jobs_expired_counted()
    got = sweep(EdgeDb(db, fail_step=EXPIRE_STEP), now)  # type: ignore[arg-type]
    assert got.failed_steps == ["expire"]
    assert job_state(conn, j) == ("queued", None)
    assert jobs_expired_counted() == counted


# ------------------------------------------------------------ CHK-M3-188


class SavepointDb:
    """One connection; each sweep step is a savepoint inside the test's own
    rolled-back transaction (used only for the 10,000-agent timing)."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        hooks: list[Callable[[], None]] = []

        class _T:
            conn = self.conn

            def on_commit(self, hook: Callable[[], None]) -> None:
                hooks.append(hook)

        with self.conn.transaction():
            yield _T()
        for hook in hooks:
            hook()


def test_ten_thousand_agents_duration(
    migrated_db: PgServer, caplog: pytest.LogCaptureFixture
) -> None:
    now = T0 + 80 * DAY
    # not autocommit: the audit append refuses autocommit connections
    with (
        psycopg.connect(migrated_db.dsn("bitscan_app")) as conn,
        conn.transaction(force_rollback=True),
    ):
        conn.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, last_heartbeat_at,"
            " enrolled_at) SELECT md5(%s || i), 'load-' || i, '1', md5(%s || i) ||"
            " md5(i::text || %s), %s, %s, 'online', %s - (i %% 60) * interval '1 min',"
            " %s FROM generate_series(1, 10000) AS i",
            (
                secrets.token_hex(4),
                secrets.token_hex(4),
                secrets.token_hex(4),
                now - DAY,
                now + 300 * DAY,
                now,
                now - DAY,
            ),
        )
        started = time.perf_counter()
        got = run_sweep(SavepointDb(conn), now)  # type: ignore[arg-type]
        elapsed = time.perf_counter() - started
        assert got.failed_steps == [], [
            getattr(r, "data", None) for r in caplog.records
        ]
        counts: dict[str, int] = dict(
            conn.execute(
                "SELECT status::text, count(*) FROM agent WHERE hostname LIKE 'load-%'"
                " GROUP BY 1"
            ).fetchall()
        )
        expected: dict[str, int] = {}
        for i in range(1, 10001):
            age = i % 60  # minutes
            label = "online" if age < 10 else "stale" if age <= 30 else "offline"
            expected[label] = expected.get(label, 0) + 1
        assert counts == expected
    print(f"offline_sweep over 10,000 agents: {elapsed:.3f} s")
