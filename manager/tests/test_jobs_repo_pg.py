"""TASK-054: scan_job repository for inventory jobs, on PostgreSQL as bitscan_app.

Checks CHK-M3-080 to CHK-M3-086 of tests/m3/test-plan.md (TP-M3-08). Every
repository call runs as bitscan_app on a freshly migrated database, so a missing
grant fails with 42501. A compliance row (which the app cannot build without a
scan) is planted as owner. Expected values: TS §6.5 L1182 (inventory payload,
exactly four keys), TS §6.1 L1064 and §3.3 L214 (at most 10 per pull), §4.4
L566, L572, L575 (pickup_by, expired), §3.4 L230 (eligible agents, open
states), L244 and REQ-078 (3) (failed after more than 30 minutes, no retry
row), #66 (queue age of online agents only), TS §5.2 L1011 (progress columns).

Tests that touch fleet-wide queries (queue run, oldest age, counts) run inside
a transaction that is rolled back, so other test files see no extra rows.
"""

import json
import secrets
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from psycopg import errors, sql
from psycopg.types.json import Jsonb

from bitscan_manager.repositories.jobs import PULL_LIMIT, JobRepo

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
PROGRESS = {"state", "dispatched_at", "started_at", "deadline_at", "finished_at"}
SET_CLAUSE = re2.compile(
    r"(?is)\bUPDATE\s+scan_job\b.*?\bSET\s+(.*?)\s+(?:FROM|WHERE)\b"
)


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def new_agent(conn: Conn, status: str = "online") -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status) VALUES (%s, %s, '1.0.0', %s, %s,"
        " %s, CAST(%s AS agent_status)) RETURNING agent_id",
        (
            secrets.token_hex(16),
            f"h-{secrets.token_hex(4)}",
            secrets.token_hex(32),
            T0 - timedelta(days=1),
            T0 + timedelta(days=364),
            status,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def add_job(
    conn: Conn,
    agent: UUID,
    *,
    created: datetime,
    pickup_by: datetime | None = None,
    state: str = "queued",
    dispatched_at: datetime | None = None,
) -> UUID:
    """An inventory row as the app can insert it (the job route of TASK-054 is
    queue_inventory; this builds exact states for the pull and sweep tests)."""
    jid = uuid4()
    pb = pickup_by if pickup_by is not None else created + timedelta(hours=24)
    payload = {
        "job_id": str(jid),
        "agent_id": str(agent),
        "kind": "inventory",
        "pickup_by": pb.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
        " pickup_by, dispatched_at) VALUES (%s, 'inventory', %s,"
        " CAST(%s AS scan_state), %s, %s, %s, %s)",
        (jid, agent, state, Jsonb(payload), created, pb, dispatched_at),
    )
    return jid


def plant_compliance(
    db: PgServer,
    agent: UUID,
    *,
    created: datetime,
    state: str = "queued",
    dispatched_at: datetime | None = None,
) -> UUID:
    """A compliance job with an eval_spec, as owner (no scan exists in M3)."""
    with db.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        fam = oc.execute(
            "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
            (f"F{secrets.token_hex(4)}",),
        ).fetchone()
        assert fam is not None
        pol = oc.execute(
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256) VALUES (%s, 'enabled', 'enabled', %s, %s, %s)"
            " RETURNING policy_id",
            (secrets.token_hex(4), fam[0], secrets.token_hex(4), "a" * 64),
        ).fetchone()
        assert pol is not None
        scan = oc.execute(
            "INSERT INTO scan (policy_id, policy_version, trigger, target)"
            " VALUES (%s, 1, 'manual', %s) RETURNING scan_id",
            (pol[0], Jsonb({"all": True})),
        ).fetchone()
        assert scan is not None
        jid = uuid4()
        payload = {
            "job_id": str(jid),
            "agent_id": str(agent),
            "kind": "compliance",
            "pickup_by": "2099-01-01T00:00:00Z",
            "plugins": [
                {"plugin_uuid": str(uuid4()), "execute": "true", "timeout_s": 5}
            ],
            "redaction_patterns": [],
        }
        oc.execute(
            "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, state, payload,"
            " eval_spec, created_at, pickup_by, dispatched_at)"
            " VALUES (%s, 'compliance', %s, %s, CAST(%s AS scan_state),"
            " %s, %s, %s, %s, %s)",
            (
                jid,
                scan[0],
                agent,
                state,
                Jsonb(payload),
                Jsonb([{"operator": "equals", "expected": "x"}]),
                created,
                created + timedelta(hours=24),
                dispatched_at,
            ),
        )
        oc.commit()
    return jid


def job(conn: Conn, jid: UUID) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT job_id, kind, agent_id, state::text AS state, payload, created_at,"
        " pickup_by, dispatched_at, finished_at, eval_spec FROM scan_job"
        " WHERE job_id = %s",
        (jid,),
    )
    row = cur.fetchone()
    assert row is not None
    assert cur.description is not None
    return dict(zip([d.name for d in cur.description], row, strict=True))


def jobs_of(conn: Conn, agent: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT job_id FROM scan_job WHERE agent_id = %s ORDER BY created_at", (agent,)
    ).fetchall()
    return [job(conn, r[0]) for r in rows]


def in_rollback(conn: Conn) -> Any:
    """A transaction that is always rolled back (fleet-wide statements)."""
    return conn.transaction(force_rollback=True)


# ------------------------------------------------------------ CHK-M3-080


def test_queue_payload_is_exactly_the_inventory_job(conn: Conn) -> None:
    """REQ-077 (5), TS §6.5 L1182: payload.job_id is the row id, four keys only."""
    with conn.transaction():
        agent = new_agent(conn, "enrolled")
    pickup = T0 + timedelta(hours=24, microseconds=999_999)
    with conn.transaction():
        ids = JobRepo(conn).queue_inventory(T0, pickup, agent)
    assert len(ids) == 1
    j = job(conn, ids[0])
    assert j["kind"] == "inventory"
    assert j["state"] == "queued"
    assert j["agent_id"] == agent
    assert j["created_at"] == T0
    assert j["pickup_by"] == pickup
    assert j["eval_spec"] is None
    p = j["payload"]
    assert set(p) == {"job_id", "agent_id", "kind", "pickup_by"}
    assert p["job_id"] == str(ids[0]) and UUID(p["job_id"]) == j["job_id"]
    assert p["agent_id"] == str(agent)
    assert p["kind"] == "inventory"
    text = p["pickup_by"]
    assert re2.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", text
    )
    shown = datetime.fromisoformat(text)
    # to the second, never later than the stored bound
    assert shown <= pickup < shown + timedelta(seconds=1)


def test_queue_global_run_takes_every_eligible_status(conn: Conn) -> None:
    """REQ-077 (1) at the repository level (rolled back: the run is fleet-wide)."""
    with in_rollback(conn):
        agents = {
            s: new_agent(conn, s)
            for s in (
                "enrolled",
                "online",
                "stale",
                "offline",
                "decommissioned",
                "awaiting_approval",
            )
        }
        ids = set(JobRepo(conn).queue_inventory(T0, T0 + timedelta(hours=24)))
        for status, agent in agents.items():
            mine = jobs_of(conn, agent)
            if status in {"decommissioned", "awaiting_approval"}:
                assert mine == [], status
            else:
                assert len(mine) == 1, status
                assert mine[0]["job_id"] in ids
        # a second run adds nothing while they are open
        again = JobRepo(conn).queue_inventory(T0 + MIN, T0 + timedelta(hours=25))
        assert not set(again) & {
            j["job_id"] for a in agents.values() for j in jobs_of(conn, a)
        }
        for status, agent in agents.items():
            assert len(jobs_of(conn, agent)) == (
                0 if status in {"decommissioned", "awaiting_approval"} else 1
            )


@pytest.mark.parametrize("state", ["queued", "dispatched", "running"])
def test_open_job_blocks_a_new_one(conn: Conn, state: str) -> None:
    """REQ-077 (2), CHK-M3-085: queued, dispatched and running count as open."""
    with conn.transaction():
        agent = new_agent(conn)
        add_job(
            conn,
            agent,
            created=T0 - MIN,
            state=state,
            dispatched_at=T0 - MIN if state != "queued" else None,
        )
    repo = JobRepo(conn)
    assert repo.has_open_inventory(agent) is True
    with conn.transaction():
        assert repo.queue_inventory(T0, T0 + timedelta(hours=24), agent) == []
    assert len(jobs_of(conn, agent)) == 1


@pytest.mark.parametrize("state", ["completed", "failed", "expired", "cancelled"])
def test_closed_job_allows_a_new_one(conn: Conn, state: str) -> None:
    with conn.transaction():
        agent = new_agent(conn)
        add_job(conn, agent, created=T0 - MIN, state=state)
    repo = JobRepo(conn)
    assert repo.has_open_inventory(agent) is False
    with conn.transaction():
        assert len(repo.queue_inventory(T0, T0 + timedelta(hours=24), agent)) == 1
    assert [j["state"] for j in jobs_of(conn, agent)] == [state, "queued"]


def test_open_compliance_job_does_not_block_inventory(conn: Conn, db: PgServer) -> None:
    with conn.transaction():
        agent = new_agent(conn)
    plant_compliance(db, agent, created=T0 - MIN)
    repo = JobRepo(conn)
    assert repo.has_open_inventory(agent) is False
    with conn.transaction():
        assert len(repo.queue_inventory(T0, T0 + timedelta(hours=24), agent)) == 1


def _one_queue_race(db: PgServer) -> None:
    with db.connect("bitscan_app") as c, c.transaction():
        agent = new_agent(c, "enrolled")
    barrier = threading.Barrier(2)
    out: list[list[UUID]] = []
    errs: list[BaseException] = []

    def run() -> None:
        try:
            with db.connect("bitscan_app") as c2:
                barrier.wait(10)
                with c2.transaction():
                    repo = JobRepo(c2)
                    out.append(
                        repo.queue_inventory(T0, T0 + timedelta(hours=24), agent)
                    )
        except BaseException as e:  # noqa: BLE001 - reported below
            errs.append(e)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errs, errs
    assert sorted(len(o) for o in out) == [0, 1]
    with db.connect("bitscan_app") as c:
        assert len(jobs_of(c, agent)) == 1


def test_concurrent_queue_calls_give_one_open_job(db: PgServer) -> None:
    """REQ-077 (3) at the repository level: two calls at once, repeated."""
    for _ in range(10):
        _one_queue_race(db)


# ------------------------------------------------------------ CHK-M3-081


def test_pull_ten_oldest_then_the_rest(conn: Conn, db: PgServer) -> None:
    """REQ-072 (1), (3), (4): own, queued, before pickup_by, inventory, at most 10."""
    with conn.transaction():
        a = new_agent(conn)
        b = new_agent(conn)
        mine = [
            add_job(conn, a, created=T0 - timedelta(hours=1) + i * MIN)
            for i in range(12)
        ]
        other = add_job(conn, b, created=T0 - timedelta(hours=2))
        dispatched = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=3),
            state="dispatched",
            dispatched_at=T0 - timedelta(hours=3),
        )
        completed = add_job(conn, a, created=T0 - timedelta(hours=3), state="completed")
        at_bound = add_job(conn, a, created=T0 - timedelta(hours=24), pickup_by=T0)
        past = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=25),
            pickup_by=T0 - timedelta(seconds=1),
        )
    comp = plant_compliance(db, a, created=T0 - timedelta(hours=4))
    repo = JobRepo(conn)
    assert PULL_LIMIT == 10
    with conn.transaction():
        first = repo.pull(a, T0)
    assert [UUID(p["job_id"]) for p in first] == mine[:10]
    for p in first:
        assert set(p) == {"job_id", "agent_id", "kind", "pickup_by"}
        assert p["agent_id"] == str(a)
    with conn.transaction():
        second = repo.pull(a, T0)
    assert [UUID(p["job_id"]) for p in second] == mine[10:]
    with conn.transaction():
        assert repo.pull(a, T0) == []
    for jid in mine:
        j = job(conn, jid)
        assert j["state"] == "dispatched" and j["dispatched_at"] == T0
    for jid in (other, at_bound, past, comp):
        assert job(conn, jid)["state"] == "queued"
    assert job(conn, dispatched)["dispatched_at"] == T0 - timedelta(hours=3)
    assert job(conn, completed)["state"] == "completed"
    # the other agent's job is its own to pull
    with conn.transaction():
        assert [UUID(p["job_id"]) for p in repo.pull(b, T0)] == [other]


def test_pull_never_returns_eval_spec_or_compliance(conn: Conn, db: PgServer) -> None:
    with conn.transaction():
        a = new_agent(conn)
    plant_compliance(db, a, created=T0 - MIN)
    with conn.transaction():
        got = JobRepo(conn).pull(a, T0)
    assert got == []
    text = json.dumps(got)
    for key in ("eval_spec", "operator", "expected"):
        assert key not in text


def test_empty_pull_changes_nothing(conn: Conn) -> None:
    with conn.transaction():
        a = new_agent(conn)
        jid = add_job(conn, a, created=T0, pickup_by=T0)  # at its bound: not pullable
    before = job(conn, jid)
    with conn.transaction():
        assert JobRepo(conn).pull(a, T0) == []
    assert job(conn, jid) == before


# ------------------------------------------------------------ CHK-M3-082


def _one_pull_race(db: PgServer) -> None:
    with db.connect("bitscan_app") as c, c.transaction():
        a = new_agent(c)
        ids = {
            add_job(c, a, created=T0 - timedelta(hours=1) + i * MIN) for i in range(20)
        }
    got_b: list[list[dict[str, Any]]] = []
    errs: list[BaseException] = []

    def pull_b() -> None:
        try:
            with db.connect("bitscan_app") as cb, cb.transaction():
                got_b.append(JobRepo(cb).pull(a, T0))
        except BaseException as e:  # noqa: BLE001
            errs.append(e)

    with db.connect("bitscan_app") as ca:
        with ca.transaction():
            got_a = JobRepo(ca).pull(a, T0)
            t = threading.Thread(target=pull_b)
            t.start()
            t.join(3)  # B either finishes (rows skipped) or waits on A's locks
        t.join(30)
    assert not errs, errs
    a_ids = {UUID(p["job_id"]) for p in got_a}
    b_ids = {UUID(p["job_id"]) for p in got_b[0]}
    assert len(a_ids) == len(got_a) == 10
    assert not a_ids & b_ids
    assert a_ids | b_ids <= ids
    with db.connect("bitscan_app") as c:
        states = [j["state"] for j in jobs_of(c, a)]
    assert states.count("dispatched") == len(a_ids | b_ids)


def test_concurrent_pulls_never_share_a_job(db: PgServer) -> None:
    """REQ-072 (2): A holds its pull open; B pulls meanwhile; then A commits."""
    for _ in range(5):
        _one_pull_race(db)


def test_many_concurrent_pulls(db: PgServer) -> None:
    """Ten pullers, 40 jobs: every job dispatched once, none twice."""
    with db.connect("bitscan_app") as c, c.transaction():
        a = new_agent(c)
        ids = {
            add_job(c, a, created=T0 - timedelta(hours=1) + i * MIN) for i in range(40)
        }
    barrier = threading.Barrier(10)
    seen: list[UUID] = []
    lock = threading.Lock()
    errs: list[BaseException] = []

    def puller() -> None:
        try:
            with db.connect("bitscan_app") as cx:
                barrier.wait(10)
                for _ in range(3):
                    with cx.transaction():
                        got = JobRepo(cx).pull(a, T0)
                    with lock:
                        seen.extend(UUID(p["job_id"]) for p in got)
        except BaseException as e:  # noqa: BLE001
            errs.append(e)

    threads = [threading.Thread(target=puller) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errs, errs
    assert len(seen) == len(set(seen)) == 40
    assert set(seen) == ids


# ------------------------------------------------------------ CHK-M3-083


@pytest.mark.parametrize(
    "assignment",
    [
        "agent_id = gen_random_uuid()",
        "payload = '{}'::jsonb",
        "kind = 'compliance'",
        "scan_id = gen_random_uuid()",
        "eval_spec = '[]'::jsonb",
        "created_at = now()",
        "pickup_by = now()",
        "retry_of = job_id",
    ],
)
def test_app_cannot_change_job_identity(conn: Conn, assignment: str) -> None:
    with conn.transaction():
        a = new_agent(conn)
        jid = add_job(conn, a, created=T0)
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute(
            sql.SQL("UPDATE scan_job SET {} WHERE job_id = %s").format(
                sql.SQL(assignment)
            ),
            (jid,),
        )


def test_app_cannot_delete_jobs(conn: Conn) -> None:
    with conn.transaction():
        a = new_agent(conn)
        jid = add_job(conn, a, created=T0)
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute("DELETE FROM scan_job WHERE job_id = %s", (jid,))


class Capture:
    """Wraps a connection and records every statement the repository runs."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self.statements: list[str] = []

    def execute(self, query: Any, params: Any = None) -> Any:
        text = query if isinstance(query, str) else query.as_string(self.conn)
        self.statements.append(text)
        return self.conn.execute(query, params)


def test_every_repository_update_writes_progress_columns_only(conn: Conn) -> None:
    cap = Capture(conn)
    repo = JobRepo(cap)  # type: ignore[arg-type]
    with in_rollback(conn):
        a = new_agent(conn)
        b = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=2),
            state="dispatched",
            dispatched_at=T0 - timedelta(hours=1),
        )
        add_job(conn, a, created=T0 - timedelta(hours=30), pickup_by=T0 - MIN)
        c = add_job(conn, a, created=T0 - timedelta(hours=1))
        repo.queue_inventory(T0, T0 + timedelta(hours=24), a)
        repo.pull(a, T0)
        repo.get_for_agent(c, a, lock=True)
        repo.complete(c, T0)
        repo.fail(b, T0)
        repo.expire_past_pickup(T0)
        repo.fail_dispatched_inventory(T0 - timedelta(minutes=30), T0)
        repo.has_open_inventory(a)
        repo.oldest_queued_for_online()
        repo.count_queued()
    updates = [s for s in cap.statements if re2.search(r"(?i)\bUPDATE\s+scan_job\b", s)]
    assert len(updates) >= 5
    for stmt in updates:
        m = SET_CLAUSE.search(stmt)
        assert m is not None, stmt
        cols = {
            part.split("=")[0].strip().split(".")[-1] for part in m.group(1).split(",")
        }
        assert cols <= PROGRESS, (cols, stmt)
    for stmt in cap.statements:
        assert not re2.search(r"(?i)\bDELETE\b", stmt), stmt
        assert "eval_spec" not in stmt, stmt


# ------------------------------------------------------------ CHK-M3-084


def test_expire_exactly_past_pickup(conn: Conn, db: PgServer) -> None:
    """REQ-078 (3), TS §4.4 L572: pickup_by <= now → expired; nothing created."""
    with conn.transaction():
        a = new_agent(conn, "offline")
        at = add_job(conn, a, created=T0 - timedelta(hours=24), pickup_by=T0)
        before = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=25),
            pickup_by=T0 - timedelta(seconds=1),
        )
        after = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=23),
            pickup_by=T0 + timedelta(seconds=1),
        )
        disp = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=25),
            pickup_by=T0 - MIN,
            state="dispatched",
            dispatched_at=T0 - timedelta(minutes=5),
        )
    comp = plant_compliance(db, a, created=T0 - timedelta(hours=25))
    with db.connect("bitscan_migrate") as oc:  # its pickup_by into the past, as owner
        oc.execute("SET ROLE bitscan_owner")
        oc.execute("UPDATE scan_job SET pickup_by = %s WHERE job_id = %s", (T0, comp))
        oc.commit()
    count_before = len(jobs_of(conn, a))
    with conn.transaction():
        n = JobRepo(conn).expire_past_pickup(T0)
    assert n >= 3  # fleet-wide: other files' rows may also be past their bound
    for jid in (at, before, comp):
        j = job(conn, jid)
        assert j["state"] == "expired" and j["finished_at"] == T0
    assert job(conn, after)["state"] == "queued"
    assert job(conn, disp)["state"] == "dispatched"
    assert len(jobs_of(conn, a)) == count_before


def test_fail_dispatched_inventory_boundaries(conn: Conn, db: PgServer) -> None:
    """REQ-078 (3): more than 30 minutes → failed with finished_at; no retry row."""
    with conn.transaction():
        a = new_agent(conn)
        over = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=1),
            state="dispatched",
            dispatched_at=T0 - timedelta(minutes=30, seconds=1),
        )
        exact = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=1),
            state="dispatched",
            dispatched_at=T0 - timedelta(minutes=30),
        )
        under = add_job(
            conn,
            a,
            created=T0 - timedelta(hours=1),
            state="dispatched",
            dispatched_at=T0 - timedelta(minutes=29, seconds=59),
        )
        queued = add_job(conn, a, created=T0 - timedelta(hours=2))
    comp = plant_compliance(
        db,
        a,
        created=T0 - timedelta(hours=2),
        state="dispatched",
        dispatched_at=T0 - timedelta(hours=1),
    )
    count_before = len(jobs_of(conn, a))
    with conn.transaction():
        n = JobRepo(conn).fail_dispatched_inventory(T0 - timedelta(minutes=30), T0)
    assert n >= 1
    j = job(conn, over)
    assert j["state"] == "failed" and j["finished_at"] == T0
    assert job(conn, exact)["state"] == "dispatched"  # "more than 30 minutes"
    assert job(conn, under)["state"] == "dispatched"
    assert job(conn, queued)["state"] == "queued"
    assert job(conn, comp)["state"] == "dispatched"  # inventory only
    assert len(jobs_of(conn, a)) == count_before  # no retry row


# ------------------------------------------------------------ CHK-M3-085


def test_oldest_queued_counts_online_agents_only(conn: Conn) -> None:
    """#66: the queue-age input ignores jobs of agents that are not online."""
    old = datetime(1990, 1, 1, tzinfo=UTC)
    with in_rollback(conn):
        online = new_agent(conn, "online")
        offline = new_agent(conn, "offline")
        stale = new_agent(conn, "stale")
        add_job(
            conn,
            offline,
            created=datetime(1980, 1, 1, tzinfo=UTC),
            pickup_by=datetime(2999, 1, 1, tzinfo=UTC),
        )
        add_job(
            conn,
            stale,
            created=datetime(1985, 1, 1, tzinfo=UTC),
            pickup_by=datetime(2999, 1, 1, tzinfo=UTC),
        )
        add_job(conn, online, created=old, pickup_by=datetime(2999, 1, 1, tzinfo=UTC))
        add_job(
            conn,
            online,
            created=datetime(1970, 1, 1, tzinfo=UTC),
            state="dispatched",
            pickup_by=datetime(2999, 1, 1, tzinfo=UTC),
            dispatched_at=old,
        )
        assert JobRepo(conn).oldest_queued_for_online() == old


def test_count_queued_counts_queued_only(conn: Conn) -> None:
    with in_rollback(conn):
        repo = JobRepo(conn)
        base = repo.count_queued()
        a = new_agent(conn)
        for _ in range(3):
            add_job(conn, a, created=T0)
        add_job(conn, a, created=T0, state="dispatched", dispatched_at=T0)
        add_job(conn, a, created=T0, state="completed")
        assert repo.count_queued() == base + 3


# ------------------------------------------------------------ CHK-M3-086


def test_get_for_agent_only_the_owner(conn: Conn) -> None:
    with conn.transaction():
        a = new_agent(conn)
        b = new_agent(conn)
        jid = add_job(conn, a, created=T0)
    repo = JobRepo(conn)
    got = repo.get_for_agent(jid, a)
    assert got is not None and got.job_id == jid and got.agent_id == a
    assert got.state == "queued" and got.kind == "inventory"
    assert repo.get_for_agent(jid, b) is None
    assert repo.get_for_agent(uuid4(), a) is None
    with conn.transaction():
        locked = repo.get_for_agent(jid, a, lock=True)
    assert locked is not None


def test_complete_and_fail_only_from_dispatched(conn: Conn) -> None:
    with conn.transaction():
        a = new_agent(conn)
        d1 = add_job(conn, a, created=T0, state="dispatched", dispatched_at=T0)
        d2 = add_job(conn, a, created=T0, state="dispatched", dispatched_at=T0)
        q = add_job(conn, a, created=T0)
        f = add_job(conn, a, created=T0, state="failed")
    repo = JobRepo(conn)
    later = T0 + timedelta(minutes=3)
    with conn.transaction():
        assert repo.complete(d1, later) is True
        assert repo.fail(d2, later) is True
        assert repo.complete(q, later) is False
        assert repo.fail(q, later) is False
        assert repo.complete(f, later) is False
        assert repo.complete(d1, later) is False  # already completed
    assert (job(conn, d1)["state"], job(conn, d1)["finished_at"]) == (
        "completed",
        later,
    )
    assert (job(conn, d2)["state"], job(conn, d2)["finished_at"]) == ("failed", later)
    assert job(conn, q)["state"] == "queued" and job(conn, q)["finished_at"] is None
    assert job(conn, f)["state"] == "failed" and job(conn, f)["finished_at"] is None
