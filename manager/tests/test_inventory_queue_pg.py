"""TASK-061: inventory queueing on PostgreSQL as bitscan_app (G33 part).

Checks CHK-M3-140 to CHK-M3-144 of tests/m3/test-plan.md (TP-M3-15), through
the service entry points with the real TASK-054 repository. Expected values:
TS §3.4 L230 (one inventory job for every agent not decommissioned or awaiting
approval with no inventory job queued, dispatched or running), TS §4.4 L566
(pickup_by = creation + 24 h), TS §6.5 L1182 (payload exactly four keys),
#36 (first job when an agent becomes enrolled), REQ-077 (3) (two runs at once:
one job per agent). Single runs are rolled back; the concurrency check commits
(its jobs stay queued and belong to agents no other file looks at).
"""

import secrets
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest

from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.services.scheduler import queue_first_inventory, run_inventory

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ELIGIBLE = ("enrolled", "online", "stale", "offline")
HELD = ("decommissioned", "awaiting_approval")


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def agent(conn: Conn, status: str) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status) VALUES (%s, 'h', '1', %s, %s, %s,"
        " CAST(%s AS agent_status)) RETURNING agent_id",
        (
            secrets.token_hex(16),
            secrets.token_hex(32),
            T0,
            T0 + timedelta(days=365),
            status,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def jobs_of(conn: Conn, a: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT job_id, kind, state::text, payload, created_at, pickup_by FROM scan_job"
        " WHERE agent_id = %s ORDER BY created_at, job_id",
        (a,),
    ).fetchall()


def set_state(conn: Conn, job_id: UUID, state: str) -> None:
    conn.execute(
        "UPDATE scan_job SET state = CAST(%s AS scan_state) WHERE job_id = %s",
        (state, job_id),
    )


# ------------------------------------------------------------ CHK-M3-140, -143


def test_one_run_one_job_per_eligible_agent(conn: Conn) -> None:
    with conn.transaction(force_rollback=True):
        agents = {s: agent(conn, s) for s in ELIGIBLE + HELD}
        queued = set(run_inventory(JobRepo(conn), T0))
        for status, a in agents.items():
            mine = jobs_of(conn, a)
            if status in HELD:
                assert mine == [], status
                continue
            assert len(mine) == 1, status
            job_id, kind, state, payload, created, pickup = mine[0]
            assert job_id in queued
            assert (kind, state, created) == ("inventory", "queued", T0)
            assert pickup == created + timedelta(hours=24)  # REQ-077 (5)
            assert set(payload) == {"job_id", "agent_id", "kind", "pickup_by"}
            assert payload == {
                "job_id": str(job_id),
                "agent_id": str(a),
                "kind": "inventory",
                "pickup_by": "2026-10-24T12:00:00Z",
            }


# ------------------------------------------------------------ CHK-M3-141


@pytest.mark.parametrize("open_state", ["queued", "dispatched", "running"])
@pytest.mark.parametrize(
    "closed_state", ["completed", "failed", "expired", "cancelled"]
)
def test_open_job_blocks_the_next_run_until_it_closes(
    conn: Conn, open_state: str, closed_state: str
) -> None:
    with conn.transaction(force_rollback=True):
        a = agent(conn, "online")
        repo = JobRepo(conn)
        run_inventory(repo, T0)
        (first,) = [r[0] for r in jobs_of(conn, a)]
        set_state(conn, first, open_state)
        run_inventory(repo, T0 + timedelta(hours=6))
        assert len(jobs_of(conn, a)) == 1  # still open: nothing new
        set_state(conn, first, closed_state)
        run_inventory(repo, T0 + timedelta(hours=12))
        rows = jobs_of(conn, a)
        assert [r[2] for r in rows] == [closed_state, "queued"]
        assert rows[1][4] == T0 + timedelta(hours=12)


# ------------------------------------------------------------ CHK-M3-142


def _race(db: PgServer, first_job: bool) -> None:
    with db.connect("bitscan_app") as c, c.transaction():
        mine = [agent(c, s) for s in ELIGIBLE]
    barrier = threading.Barrier(2)
    errs: list[BaseException] = []

    def run(kind: str) -> None:
        try:
            with db.connect("bitscan_app") as cx:
                barrier.wait(15)
                with cx.transaction():
                    repo = JobRepo(cx)
                    if kind == "first":
                        queue_first_inventory(repo, mine[0], T0)
                    else:
                        run_inventory(repo, T0)
        except BaseException as e:  # noqa: BLE001 - reported below
            errs.append(e)

    kinds = ["run", "first" if first_job else "run"]
    ts = [threading.Thread(target=run, args=(k,)) for k in kinds]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert not errs, errs
    with db.connect("bitscan_app") as c:
        for a in mine:
            assert len(jobs_of(c, a)) == 1, a


def test_two_runs_at_once_give_one_job_per_agent(db: PgServer) -> None:
    """REQ-077 (3), repeated."""
    for _ in range(5):
        _race(db, first_job=False)


def test_run_and_first_job_at_once_give_one_job(db: PgServer) -> None:
    for _ in range(5):
        _race(db, first_job=True)


# ------------------------------------------------------------ CHK-M3-144


def test_first_inventory_queues_one_unless_open(conn: Conn) -> None:
    """#36: one job when the agent becomes enrolled; none while one is open."""
    with conn.transaction(force_rollback=True):
        repo = JobRepo(conn)
        a = agent(conn, "enrolled")
        other = agent(conn, "enrolled")
        jid = queue_first_inventory(repo, a, T0)
        assert jid is not None
        assert [r[0] for r in jobs_of(conn, a)] == [jid]
        assert jobs_of(conn, other) == []  # limited to that agent
        assert queue_first_inventory(repo, a, T0 + timedelta(minutes=1)) is None
        set_state(conn, jid, "completed")
        again = queue_first_inventory(repo, a, T0 + timedelta(minutes=2))
        assert again is not None and again != jid


@pytest.mark.parametrize("status", HELD)
def test_first_inventory_refuses_held_and_decommissioned(
    conn: Conn, status: str
) -> None:
    with conn.transaction(force_rollback=True):
        a = agent(conn, status)
        assert queue_first_inventory(JobRepo(conn), a, T0) is None
        assert jobs_of(conn, a) == []
