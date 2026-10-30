"""TASK-195 TEST: the intake repository on PostgreSQL as bitscan_app
(TP-M9-10; CHK-M9-117 to -119; mutation rows CHK-M9-320, -321, -322 repo
side, -334).

Expected values: TS §4.4 L578 (first result wins: lock COALESCE(retry_of,
job_id) FOR UPDATE while inserting; skip plugins that already have a
result in the original job or its retry; job_created_at copied from
scan_job.created_at, a trigger rejects any other value), L575 (deadline_at
set once, on dispatched → running), L577 (a retry is a new row with
retry_of), L582 (final states never change), §4.5 L587 (result and verdict
in one insert), §5.2 L892–L913 (scan_result columns; result is generated),
L1011 (scan_job UPDATE only of the progress columns); #124 (c), #127 (a).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import job_intake as ji
from bitscan_manager.services.jobs.intake_plan import ResultRow

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=2)
PROGRESS = ("state", "dispatched_at", "started_at", "deadline_at", "finished_at")


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("ji")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    with f.app_database(server) as db:
        yield f.make_catalog(db, f.Clock(), tmp_path)


def agent(server: PgServer) -> UUID:
    with f.app(server) as c:
        return f.make_agent(c).agent_id


def unit(
    server: PgServer,
    cat: f.Catalog,
    *,
    orig_state: str = "failed",
    retry_state: str | None = "running",
    n: int = 3,
) -> tuple[f.Pol, f.JobRow, f.JobRow | None]:
    pol = cat.policy(n)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state=orig_state)
        retry = (
            None
            if retry_state is None
            else f.owner_job(
                o,
                s,
                a,
                pol,
                pol.plugins[1:],
                state=retry_state,
                retry_of=orig.job_id,
                created_at=f.T0 + timedelta(minutes=40),
            )
        )
    return pol, orig, retry


def held_in_thread(
    server: PgServer, fn: Callable[[psycopg.Connection[Any]], Any]
) -> tuple[threading.Thread, threading.Event, psycopg.Connection[Any], int]:
    """Runs ``fn`` in a second session's open transaction on a thread;
    returns (thread, done, conn, pid). The caller rolls back ``conn``."""
    conn = psycopg.connect(server.dsn("bitscan_app"))  # autocommit off
    pid = f.backend_pid(conn)
    done = threading.Event()

    def run() -> None:
        fn(conn)
        done.set()

    t = threading.Thread(target=run)
    t.start()
    return t, done, conn, pid


def result_row(p: f.PluginDef, pol: f.Pol, **over: Any) -> ResultRow:
    base: dict[str, Any] = {
        "plugin_uuid": p.plugin_uuid,
        "eval_code": 0,
        "eval_detail": None,
        "exit_code": 0,
        "stdout": "out " + f.CANARY,
        "stderr": "",
        "timed_out": False,
        "truncated": False,
        "plugin_name_snap": pol.display(p),
        "execute_snap": p.execute,
        "operator_snap": p.operator,
        "expected_snap": p.expected,
        "started_at": f.T0 + timedelta(seconds=1),
        "finished_at": f.T0 + timedelta(seconds=2),
    }
    return ResultRow(**(base | over))


# ------------------------------------------------------------ CHK-M9-117


def test_lock_unit_returns_the_posted_job_with_payload_and_spec(
    server: PgServer, cat: f.Catalog
) -> None:
    pol, orig, retry = unit(server, cat)
    assert retry is not None
    with f.app(server, autocommit=False) as conn:
        got = ji.lock_unit(conn, retry.job_id)
        assert ji.lock_unit(conn, uuid4()) is None
        conn.rollback()
    assert got is not None
    assert (got.job_id, got.kind, got.agent_id, got.retry_of) == (
        retry.job_id,
        "compliance",
        retry.agent_id,
        orig.job_id,
    )
    assert (got.scan_id, got.state, got.created_at) == (
        retry.scan_id,
        "running",
        retry.created_at,
    )
    assert got.payload == retry.payload and got.eval_spec == retry.eval_spec
    assert got.dispatched_at is not None and got.started_at is not None


@pytest.mark.parametrize(
    ("first", "second"),
    [("orig", "retry"), ("retry", "orig"), ("retry", "retry"), ("orig", "orig")],
)
def test_two_posts_to_one_unit_serialise_on_the_root(
    server: PgServer, cat: f.Catalog, first: str, second: str
) -> None:
    """TS §4.4 L578, #124 (c), CHK-M9-320, -321: whichever job of the unit
    the first session locks, a second session locking either job of the same
    unit waits until the first transaction ends (the root is the shared
    lock); a job of another unit does not wait."""
    pol, orig, retry = unit(server, cat)
    assert retry is not None
    ids = {"orig": orig.job_id, "retry": retry.job_id}
    _, other, _ = unit(server, cat, orig_state="running", retry_state=None)
    with f.app(server, autocommit=False) as a:
        assert ji.lock_unit(a, ids[first]) is not None
        with f.app(server, autocommit=False) as c:  # another unit: no wait
            assert ji.lock_unit(c, other.job_id) is not None
            c.rollback()
        t, done, b, pid = held_in_thread(
            server, lambda conn: ji.lock_unit(conn, ids[second])
        )
        try:
            f.wait_until_lock_waiting(server, pid)
            assert not done.is_set()
        finally:
            a.rollback()
            t.join(10)
            b.rollback()
            b.close()
        assert done.is_set()


# ------------------------------------------------------------ CHK-M9-118


def test_insert_results_is_one_statement_accepted_by_the_trigger(
    server: PgServer, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS §4.5 L587, §5.2 trigger, CHK-M9-118: three rows in ONE INSERT; each
    stored exactly as given, with job_created_at = the job's created_at,
    received_at = the argument (not the item times), operator_snap cast to
    plugin_operator, result generated from eval_code. No rows → 0, no SQL."""
    pol, orig, _ = unit(server, cat, orig_state="running", retry_state=None)
    p1, p2, p3 = pol.plugins
    rows = [
        result_row(p1, pol),
        result_row(p2, pol, eval_code=1, exit_code=1, stdout="", stderr="e"),
        result_row(
            p3,
            pol,
            eval_code=2,
            eval_detail="oversize",
            stdout="",
            exit_code=None,
            timed_out=True,
            truncated=True,
        ),
    ]
    with f.app(server, autocommit=False) as conn:
        job = ji.lock_unit(conn, orig.job_id)
        assert job is not None
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        assert ji.insert_results(conn, job, [], NOW) == 0
        assert spy.statements == []
        assert ji.insert_results(conn, job, rows, NOW) == 3
        assert [s.split(None, 1)[0].upper() for s in spy.statements] == ["INSERT"]
        monkeypatch.undo()
        conn.commit()
    with f.app(server) as conn:
        stored = {r["plugin_uuid"]: r for r in f.results_of(conn, [orig.job_id])}
    for row in rows:
        s = stored[row.plugin_uuid]
        assert s["job_created_at"] == orig.created_at and s["received_at"] == NOW
        assert s["result"] == {0: "PASS", 1: "FAIL", 2: "ERROR"}[row.eval_code]
        for name in (
            "eval_code",
            "eval_detail",
            "exit_code",
            "stdout",
            "stderr",
            "timed_out",
            "truncated",
            "plugin_name_snap",
            "execute_snap",
            "operator_snap",
            "expected_snap",
            "started_at",
            "finished_at",
        ):
            assert s[name] == getattr(row, name), name


def test_a_job_created_at_that_is_not_the_jobs_is_refused_by_the_trigger(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L578: the trigger rejects any other job_created_at, so the
    insert must copy it from the job row (here an IntakeJob with a shifted
    created_at is refused, and nothing is stored)."""
    pol, orig, _ = unit(server, cat, orig_state="running", retry_state=None)
    with f.app(server, autocommit=False) as conn:
        job = ji.lock_unit(conn, orig.job_id)
        assert job is not None
        from dataclasses import replace

        wrong = replace(job, created_at=job.created_at + timedelta(microseconds=1))
        with pytest.raises(psycopg.Error):
            ji.insert_results(conn, wrong, [result_row(pol.plugins[0], pol)], NOW)
        conn.rollback()
    with f.app(server) as conn:
        assert f.results_of(conn, [orig.job_id]) == []


def test_result_uuids_cover_the_given_jobs_only(
    server: PgServer, cat: f.Catalog
) -> None:
    pol, orig, retry = unit(server, cat)
    assert retry is not None
    with f.owner(server) as o:
        f.owner_result(o, orig, pol, pol.plugins[0])
        f.owner_result(o, retry, pol, pol.plugins[2])
    with f.app(server) as conn:
        both = ji.result_uuids(
            conn, [(orig.job_id, orig.created_at), (retry.job_id, retry.created_at)]
        )
        only = ji.result_uuids(conn, [(retry.job_id, retry.created_at)])
        assert ji.result_uuids(conn, []) == set()
    assert both == {pol.uuids[0], pol.uuids[2]} and only == {pol.uuids[2]}


# ------------------------------------------------------------ CHK-M9-119


def test_start_writes_started_and_deadline_once(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L575, §3.3 L222, REQ-217 (1), CHK-M9-334: dispatched →
    running with started_at and deadline_at; a second start changes nothing;
    a job that already ended (never-started → failed by the sweep) and a
    running job are not started again."""
    pol, orig, _ = unit(server, cat, orig_state="dispatched", retry_state=None)
    _, failed, _ = unit(server, cat, orig_state="failed", retry_state=None)
    d1 = NOW + timedelta(minutes=12)
    with f.app(server) as conn:
        assert ji.start(conn, orig.job_id, NOW, d1) is True
        st = f.job_state(conn, orig.job_id)
        assert (st["state"], st["started_at"], st["deadline_at"]) == (
            "running",
            NOW,
            d1,
        )
        later = NOW + timedelta(minutes=5)
        assert ji.start(conn, orig.job_id, later, later + timedelta(hours=1)) is False
        assert f.job_state(conn, orig.job_id) == st
        before = f.job_state(conn, failed.job_id)
        assert ji.start(conn, failed.job_id, NOW, d1) is False
        assert f.job_state(conn, failed.job_id) == before


def test_set_state_moves_only_open_or_late_jobs_and_only_progress_columns(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L582, #127 (c), REQ-217 (5), (6): running → completed sets
    finished_at; failed and partial may move (late results); completed,
    expired and cancelled never change; intake never sets failed, queued,
    cancelled or expired; payload, eval_spec and ids are never written."""
    pol = cat.policy(1)
    a = agent(server)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        jobs = {
            st: f.owner_job(o, s, a, pol, state=st)
            for st in (
                "running",
                "failed",
                "partial",
                "completed",
                "expired",
                "cancelled",
            )
        }
    with f.app(server) as conn:
        before = {k: f.job_state(conn, j.job_id) for k, j in jobs.items()}
        assert ji.set_state(conn, jobs["running"].job_id, "completed", NOW) is True
        assert ji.set_state(conn, jobs["failed"].job_id, "partial", NOW) is True
        assert ji.set_state(conn, jobs["partial"].job_id, "completed", NOW) is True
        for k in ("completed", "expired", "cancelled"):
            assert ji.set_state(conn, jobs[k].job_id, "partial", NOW) is False
            assert f.job_state(conn, jobs[k].job_id) == before[k]
        for bad in ("failed", "queued", "cancelled", "expired", "dispatched"):
            with pytest.raises(ValueError):
                ji.set_state(conn, jobs["partial"].job_id, bad, NOW)
        for k, want in (
            ("running", "completed"),
            ("failed", "partial"),
            ("partial", "completed"),
        ):
            after = f.job_state(conn, jobs[k].job_id)
            assert (after["state"], after["finished_at"]) == (want, NOW)
            for col in after:
                if col not in PROGRESS:
                    assert after[col] == before[k][col], (k, col)


@pytest.mark.parametrize(
    ("orig_state", "retry_state", "posted", "want"),
    [
        ("failed", "running", "retry", "orig"),
        ("partial", "queued", "retry", "orig"),
        ("failed", "running", "orig", "retry"),
        ("partial", "completed", "orig", "retry"),
        # an original that a late batch completed after its retry was made
        # (TS §4.4 L577, L578): its retry is still its sibling
        ("completed", "running", "orig", "retry"),
        ("completed", "completed", "orig", "retry"),
        ("dispatched", None, "orig", None),
        ("running", None, "orig", None),
        ("failed", None, "orig", None),
        ("completed", None, "orig", None),
    ],
)
def test_sibling_is_the_other_job_of_the_unit(
    server: PgServer,
    cat: f.Catalog,
    orig_state: str,
    retry_state: str | None,
    posted: str,
    want: str | None,
) -> None:
    """#127 (a), TS §4.4 L578, CHK-M9-322: the sibling (with its created_at,
    for partition pruning) of a retry is its original, and of an original
    is its retry whenever one exists. A retry is made only when the original
    ends failed or partial, but a late batch can then move that original to
    completed (L577, L582), so a completed original can have a retry too."""
    pol, orig, retry = unit(server, cat, orig_state=orig_state, retry_state=retry_state)
    rows = {"orig": orig, "retry": retry}
    target = rows[posted]
    assert target is not None
    with f.app(server, autocommit=False) as conn:
        job = ji.lock_unit(conn, target.job_id)
        assert job is not None
        got = ji.sibling(conn, job)
        conn.rollback()
    exp = None if want is None else rows[want]
    assert got == (None if exp is None else (exp.job_id, exp.created_at))
