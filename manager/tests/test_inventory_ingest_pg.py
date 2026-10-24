"""TASK-064: inventory ingestion on PostgreSQL as bitscan_app (TP-M3-18).

Checks CHK-M3-170 to CHK-M3-175 of tests/m3/test-plan.md through ingest() in
real AppDatabase transactions (the way TASK-074 will call it) with the real
TASK-053 repository, TASK-051 agent repository, audit chain and the #65 (e)
window. Expected values: TS §3.4 L241-L242, TS §5.2 L780-L825 (grants: no
UPDATE on package), REQ-075 (1)-(7), #60 (empty source stored as NULL), #65
(e), #69, #71; carry-over: an agent revoked since its token check writes
nothing. Every test uses its own agents and package-name prefix, so committed
rows of one test never meet another's.
"""

import json
import secrets
import threading
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.inventory import InventoryRepo, PackageIds, PackageRow
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.inventory.ingest import (
    NEW_PACKAGES_PER_DAY,
    AgentGone,
    IngestResult,
    ingest,
)
from bitscan_manager.services.users.accounts import TxAudit

from .conftest import PgServer
from .test_inventory_ingest import (
    DAY,
    HOUR,
    SEC,
    T0,
    Clock,
    Pkg,
    decoded,
    line,
    oracle_sha256,
    pkg,
)

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
JOIN_S = 60


def alerts_counted() -> float:
    return (
        REGISTRY.get_sample_value(
            "bitscan_alerts_total", {"kind": "new_packages_burst"}
        )
        or 0.0
    )


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    d.open()
    yield d
    d.close()


@pytest.fixture
def conn(migrated_db: PgServer) -> Iterator[Conn]:
    with migrated_db.connect("bitscan_app") as c:
        yield c


class Env:
    def __init__(self, db: AppDatabase, conn: Conn) -> None:
        self.db, self.conn = db, conn
        self.clock = Clock()
        self.burst: SlidingCount[object] = SlidingCount(
            self.clock, DAY, DAY, NEW_PACKAGES_PER_DAY
        )
        self.prefix = f"ing-{secrets.token_hex(4)}-"

    def agent(self) -> UUID:
        row = self.conn.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, enrolled_at)"
            " VALUES (%s, 'h', '1', %s, %s, %s, 'online', %s) RETURNING agent_id",
            (
                secrets.token_hex(16),
                secrets.token_hex(32),
                T0 - DAY,
                T0 + 300 * DAY,
                T0 - DAY,
            ),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def p(self, name: str, **kw: Any) -> Pkg:
        return pkg(self.prefix + name, **kw)

    def many(self, tag: str, n: int) -> list[Pkg]:
        return [self.p(f"{tag}{i:05d}") for i in range(n)]

    def upload(
        self,
        a: UUID,
        pkgs: Sequence[Pkg],
        repo: type[InventoryRepo] = InventoryRepo,
        **os_over: Any,
    ) -> IngestResult:
        dec = decoded(pkgs, **os_over)
        with self.db.transaction() as tx:
            assert tx.conn.execute("SELECT session_user::text").fetchone() == (
                "bitscan_app",
            )
            return ingest(
                repo(tx.conn),
                AgentRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                self.burst,
                tx.on_commit,
                agent_id=a,
                decoded=dec,
                now=self.clock.at,
            )

    # ---- state readers (bitscan_app, autocommit)

    def state(self, a: UUID) -> dict[str, Any]:
        c = self.conn
        return {
            "os": c.execute(
                "SELECT os_pretty_name, uptime_s, collected_at, raw::text,"
                " array_to_string(ip_addresses, ',') FROM os_info WHERE agent_id = %s",
                (a,),
            ).fetchall(),
            "last_inventory_at": c.execute(
                "SELECT last_inventory_at FROM agent WHERE agent_id = %s", (a,)
            ).fetchone(),
            "ap": c.execute(
                "SELECT p.name, p.version, p.architecture, ap.status,"
                " ap.installed_size_kb, ap.first_seen_at, ap.last_seen_at"
                " FROM agent_package ap JOIN package p USING (package_id)"
                " WHERE ap.agent_id = %s ORDER BY 1, 2, 3",
                (a,),
            ).fetchall(),
            "snaps": self.snaps(a),
        }

    def snaps(self, a: UUID) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            "SELECT list_sha256, package_count, added, removed, collected_at"
            " FROM inventory_snapshot WHERE agent_id = %s ORDER BY snapshot_id",
            (a,),
        ).fetchall()

    def package_rows(self, like: str = "") -> list[tuple[Any, ...]]:
        return self.conn.execute(
            "SELECT name, version, architecture, source_name FROM package"
            " WHERE name LIKE %s ORDER BY 1, 2, 3",
            (self.prefix + like + "%",),
        ).fetchall()

    def burst_alerts(self, a: UUID) -> list[tuple[Any, ...]]:
        rows = self.conn.execute(
            "SELECT actor, action, target, detail::text FROM audit_log"
            " WHERE action = 'alert.new_packages_burst' AND target = %s"
            " ORDER BY audit_id",
            (f"agent:{a}",),
        ).fetchall()
        return [(r[0], r[1], r[2], json.loads(r[3])) for r in rows]


@pytest.fixture
def env(db: AppDatabase, conn: Conn) -> Env:
    return Env(db, conn)


# ------------------------------------------------------------ CHK-M3-170


def test_first_upload_rows(env: Env) -> None:
    a = env.agent()
    pkgs = [
        env.p("libc6", version="2.39-0ubuntu8", source="glibc", kb=13000),
        env.p("libc6", version="2.39-0ubuntu8", arch="i386", source="glibc"),
        env.p("adduser", version="3.137", arch="all", source="", kb=None),
    ]
    got = env.upload(a, pkgs)
    assert got == IngestResult(True, 3, 0, 3)
    st = env.state(a)
    assert st["os"] == [
        (
            "Ubuntu 24.04.1 LTS",
            12345,
            T0,
            json.dumps({"nproc": 4, "os-release": {"ID": "ubuntu"}}),
            "10.0.0.5,fe80::1",
        )
    ]
    assert st["last_inventory_at"] == (T0,)
    assert sorted(st["ap"]) == sorted(
        (p[0], p[1], p[2], p[3], p[5], T0, T0) for p in pkgs
    )
    [(sha, count, added, removed, collected)] = st["snaps"]
    assert (sha, count, removed, collected) == (oracle_sha256(pkgs), 3, [], T0)
    assert sorted(added, key=json.dumps) == sorted(map(line, pkgs), key=json.dumps)
    # #60: "" stored as NULL; a real source kept
    assert sorted(env.package_rows()) == [
        (env.prefix + "adduser", "3.137", "all", None),
        (env.prefix + "libc6", "2.39-0ubuntu8", "amd64", "glibc"),
        (env.prefix + "libc6", "2.39-0ubuntu8", "i386", "glibc"),
    ]


# ------------------------------------------------------------ CHK-M3-171


def test_same_list_again(env: Env) -> None:
    a = env.agent()
    pkgs = [env.p("a"), env.p("b")]
    env.upload(a, pkgs)
    before = env.state(a)
    env.clock.at = T0 + HOUR
    got = env.upload(a, list(reversed(pkgs)), os_pretty_name="Ubuntu 24.04.2 LTS")
    assert got == IngestResult(False, 0, 0, 0)
    after = env.state(a)
    assert after["os"][0][0] == "Ubuntu 24.04.2 LTS"
    assert after["os"][0][2] == T0 + HOUR
    assert len(after["os"]) == 1
    assert after["last_inventory_at"] == (T0 + HOUR,)
    assert after["ap"] == before["ap"]  # last_seen_at not moved either
    assert after["snaps"] == before["snaps"]


# ------------------------------------------------------------ CHK-M3-172


def test_upgrade_removal_and_status_change(env: Env) -> None:
    a = env.agent()
    keep, old, gone = env.p("keep"), env.p("up", version="1"), env.p("gone")
    flip = env.p("flip")
    env.upload(a, [keep, old, gone, flip])
    env.clock.at = T0 + HOUR
    new = env.p("up", version="2")
    flipped = env.p("flip", status="deinstall ok config-files")
    got = env.upload(a, [keep, new, flipped])
    assert got == IngestResult(True, 2, 3, 1)
    snaps = env.snaps(a)
    assert len(snaps) == 2
    _, count, added, removed, collected = snaps[-1]
    assert (count, collected) == (3, T0 + HOUR)
    key = json.dumps
    assert sorted(added, key=key) == sorted([line(new), line(flipped)], key=key)
    assert sorted(removed, key=key) == sorted(
        [line(old), line(gone), line(flip)], key=key
    )
    ap = {(r[0], r[1]): r for r in env.state(a)["ap"]}
    assert set(ap) == {(keep[0], "1.0-1"), (new[0], "2"), (flipped[0], "1.0-1")}
    assert ap[(flipped[0], "1.0-1")][3] == "deinstall ok config-files"
    assert ap[(keep[0], "1.0-1")][5:] == (T0, T0 + HOUR)  # first kept, last moved
    # removed and superseded package rows remain (retention prunes them)
    names = {(r[0], r[1]) for r in env.package_rows()}
    assert {(gone[0], "1.0-1"), (old[0], "1")} <= names


def test_snapshots_deleted_by_retention_means_compare_with_none(
    env: Env, migrated_db: PgServer
) -> None:
    """REQ-075: 'differs from the agent's last snapshot (or there is none)'."""
    a = env.agent()
    pkgs = [env.p("a")]
    env.upload(a, pkgs)
    with migrated_db.connect("bitscan_retention") as r:
        r.execute("DELETE FROM inventory_snapshot WHERE agent_id = %s", (a,))
    got = env.upload(a, pkgs)
    assert got.snapshot_written is True
    assert [s[:2] for s in env.snaps(a)] == [(oracle_sha256(pkgs), 1)]


# ------------------------------------------------------------ CHK-M3-173


class FailAfterPackages(InventoryRepo):
    def upsert_agent_packages(self, *args: Any, **kw: Any) -> None:
        raise RuntimeError("forced after the package insert")


class FailAtSnapshot(InventoryRepo):
    def insert_snapshot(self, *args: Any, **kw: Any) -> int:
        super().insert_snapshot(*args, **kw)
        raise RuntimeError("forced after the snapshot insert")


@pytest.mark.parametrize("repo", [FailAfterPackages, FailAtSnapshot])
def test_forced_failure_rolls_back_everything(
    env: Env, repo: type[InventoryRepo]
) -> None:
    a = env.agent()
    env.upload(a, [env.p("a"), env.p("b")])
    before = env.state(a)
    before_pkgs = env.package_rows()
    env.clock.at = T0 + HOUR
    with pytest.raises(RuntimeError, match="forced"):
        env.upload(
            a,
            [env.p("a", version="9"), env.p("c")] + env.many("burst", 1001),
            repo=repo,
            os_pretty_name="changed",
        )
    assert env.state(a) == before
    assert env.package_rows() == before_pkgs  # the attempt's package rows too
    assert env.burst_alerts(a) == []


def test_forced_failure_on_a_first_upload_leaves_no_trace(env: Env) -> None:
    a = env.agent()
    with pytest.raises(RuntimeError, match="forced"):
        env.upload(a, [env.p("x")], repo=FailAfterPackages)
    assert env.state(a) == {
        "os": [],
        "last_inventory_at": (None,),
        "ap": [],
        "snaps": [],
    }
    assert env.package_rows() == []


# ------------------------------------------------------------ CHK-M3-174


def test_two_agents_same_new_package_at_once(env: Env) -> None:
    a, b = env.agent(), env.agent()
    shared = [env.p("shared"), env.p("both", version="2")]
    barrier = threading.Barrier(2, timeout=JOIN_S)

    class Synced(InventoryRepo):
        def insert_packages(self, rows: Sequence[PackageRow]) -> PackageIds:
            barrier.wait()  # both transactions are open and insert together
            return super().insert_packages(rows)

    results: dict[UUID, IngestResult] = {}
    errors: list[BaseException] = []

    def run(agent: UUID, extra: str) -> None:
        try:
            results[agent] = env.upload(agent, shared + [env.p(extra)], repo=Synced)
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(a, "only-a")),
        threading.Thread(target=run, args=(b, "only-b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_S)
    assert not any(t.is_alive() for t in threads), "deadlock or hang"
    assert errors == []
    rows = env.package_rows()
    assert sorted((r[0], r[1]) for r in rows) == sorted(
        [
            (env.prefix + "both", "2"),
            (env.prefix + "only-a", "1.0-1"),
            (env.prefix + "only-b", "1.0-1"),
            (env.prefix + "shared", "1.0-1"),
        ]
    )
    # each shared row was created by exactly one of the two uploads
    assert results[a].new_packages + results[b].new_packages == 2 + 2
    assert {r[0] for r in env.state(a)["ap"]} == {
        env.prefix + "shared",
        env.prefix + "both",
        env.prefix + "only-a",
    }
    assert {r[0] for r in env.state(b)["ap"]} == {
        env.prefix + "shared",
        env.prefix + "both",
        env.prefix + "only-b",
    }


# ------------------------------------------------------------ CHK-M3-175


def test_burst_alert_committed_once_and_counted_after_commit(env: Env) -> None:
    a = env.agent()
    env.upload(a, env.many("p", 1000))
    assert env.burst_alerts(a) == []
    counted = alerts_counted()
    env.clock.at = T0 + HOUR
    seen_inside: list[float] = []

    class Peek(InventoryRepo):
        def insert_snapshot(self, *args: Any, **kw: Any) -> int:
            seen_inside.append(alerts_counted())
            return super().insert_snapshot(*args, **kw)

    env.upload(a, env.many("p", 1001), repo=Peek)
    assert seen_inside == [counted]
    assert alerts_counted() == counted + 1
    assert env.burst_alerts(a) == [
        (
            f"agent:{a}",
            "alert.new_packages_burst",
            f"agent:{a}",
            {
                "alert": True,
                "alert_kind": "new_packages_burst",
                "new_packages": 1,
                "over_per_day": 1000,
            },
        )
    ]
    env.clock.at = T0 + DAY
    env.upload(a, env.many("q", 3000))
    assert len(env.burst_alerts(a)) == 1  # within 24 h of the alert
    # another agent uploading the same (now known) packages: not fleet-new
    b = env.agent()
    got = env.upload(b, env.many("q", 3000))
    assert got.new_packages == 0
    assert env.burst_alerts(b) == []


def test_rolled_back_upload_writes_and_counts_no_alert(env: Env) -> None:
    a = env.agent()
    counted = alerts_counted()
    with pytest.raises(RuntimeError, match="forced"):
        env.upload(a, env.many("p", 1001), repo=FailAtSnapshot)
    assert env.burst_alerts(a) == []
    assert alerts_counted() == counted


def test_rolled_back_burst_alert_does_not_use_the_daily_slot(env: Env) -> None:
    """#65 (e) once per agent per 24 h: an alert that never committed is not
    the day's alert, so the retried upload (the same rows are new again)
    still alerts. Ruling 2026-10-23 (a): "fired" is marked only after commit."""

    a = env.agent()
    dec_pkgs = env.many("p", 1001)

    def failing_upload() -> None:
        dec = decoded(dec_pkgs)
        with env.db.transaction() as tx:
            ingest(
                InventoryRepo(tx.conn),
                AgentRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                env.burst,
                tx.on_commit,
                agent_id=a,
                decoded=dec,
                now=env.clock.at,
            )
            raise RuntimeError("forced: the caller's later step fails")

    with pytest.raises(RuntimeError, match="forced"):
        failing_upload()
    assert env.burst_alerts(a) == []
    env.clock.at = T0 + 10 * 60 * SEC
    got = env.upload(a, dec_pkgs)
    assert got.new_packages == 1001
    assert len(env.burst_alerts(a)) == 1


# ------------------------------------------------------------ carry-over: revoked


def test_agent_revoked_after_token_check_writes_nothing(env: Env) -> None:
    a = env.agent()
    env.upload(a, [env.p("a")])
    before, before_pkgs = env.state(a), env.package_rows()
    # the token check passed earlier; a revoke commits before the upload's tx
    with env.db.transaction() as tx:
        assert AgentRepo(tx.conn).revoke(a, T0)
    env.clock.at = T0 + HOUR
    with pytest.raises(AgentGone):
        env.upload(a, [env.p("b")] + env.many("burst", 1001))
    assert env.state(a) == before
    assert env.package_rows() == before_pkgs
    assert env.burst_alerts(a) == []


def test_upload_waits_for_a_concurrent_revoke_and_then_writes_nothing(
    env: Env,
) -> None:
    """The agent row lock: a revoke in flight when the upload starts wins."""
    a = env.agent()
    locked, release = threading.Event(), threading.Event()
    outcome: list[BaseException | IngestResult] = []

    def revoker() -> None:
        with env.db.transaction() as tx:
            AgentRepo(tx.conn).revoke(a, T0)
            locked.set()
            release.wait(JOIN_S)

    def uploader() -> None:
        try:
            outcome.append(env.upload(a, [env.p("x")]))
        except BaseException as exc:  # inspected below
            outcome.append(exc)

    r = threading.Thread(target=revoker)
    r.start()
    assert locked.wait(JOIN_S)
    u = threading.Thread(target=uploader)
    u.start()
    u.join(1.0)
    still_waiting = u.is_alive()
    release.set()
    r.join(JOIN_S)
    u.join(JOIN_S)
    assert not u.is_alive() and not r.is_alive()
    assert still_waiting, "the upload did not wait for the agent row lock"
    assert len(outcome) == 1 and isinstance(outcome[0], AgentGone)
    assert env.state(a) == {
        "os": [],
        "last_inventory_at": (None,),
        "ap": [],
        "snaps": [],
    }
    assert env.package_rows() == []
