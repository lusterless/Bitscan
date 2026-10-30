"""TASK-200 TEST: ``cancel_scan()`` on PostgreSQL as bitscan_app (TP-M9-13;
CHK-M9-182 to -185; mutation rows CHK-M9-359, -360).

Expected values: TS §4.4 L573 (cancelled by an operator), L581 (cancel is
manager-side only: queued jobs become cancelled and are never returned by a
pull; dispatched or running jobs become cancelled and later posts get 409
job_not_acceptable and are not stored), L579–L580 (scan finished and
state); #122 (g) ({scan_id, state, cancelled_jobs}; a repeat answers 0),
#127 (d) (cancelled after some results → partial, or completed when every
unit is complete; never cancelled), #129 (a) (one scan.cancel entry,
detail {cancelled_jobs}); decisions "M9 builder rulings" (one entry per
call, including cancelled_jobs 0); REQ-220, REQ-229 (2).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.services.audit.verify import verify_chain
from bitscan_manager.services.jobs.cancel import ScanNotFound, cancel_scan
from bitscan_manager.services.jobs.intake import Accepted, Refused, accept_results

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=3)
STATES = (
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "expired",
    "cancelled",
)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("cancel")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


def agents(server: PgServer, n: int) -> list[UUID]:
    with f.app(server) as c:
        return [f.make_agent(c).agent_id for _ in range(n)]


def cancel(
    db: AppDatabase, scan_id: UUID, actor: str = "user:7", now: object = NOW
) -> object:
    with db.transaction() as tx:
        return cancel_scan(tx, scan_id=scan_id, actor=actor, now=now)  # type: ignore[arg-type]


def item(p: f.PluginDef) -> dict[str, object]:
    return {
        "plugin_uuid": str(p.plugin_uuid),
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "started_at": f.iso(NOW),
        "finished_at": f.iso(NOW),
        "timed_out": False,
        "truncated": False,
        "error": None,
    }


# ------------------------------------------------------------ CHK-M9-182


def test_only_queued_dispatched_and_running_jobs_are_cancelled(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-220 (1), TS §4.4 L581, CHK-M9-359: of one job in each state plus a
    queued retry, the queued, dispatched, running jobs and the retry become
    cancelled with finished_at = now; the others are byte-identical; nothing
    else (another scan, inventory) changes; the answer counts 4."""
    pol = cat.policy(2)
    ag = agents(server, len(STATES) + 1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        jobs = {
            st: f.owner_job(o, s, a, pol, state=st)
            for st, a in zip(STATES, ag, strict=False)
        }
        f.owner_result(o, jobs["partial"], pol, pol.plugins[0])
        retry = f.owner_job(
            o, s, ag[5], pol, state="queued", retry_of=jobs["failed"].job_id
        )
        other = f.owner_scan(o, pol)
        keep_other = f.owner_job(o, other, ag[8], pol)
        inv = [f.owner_inventory_job(o, a) for a in ag[:3]]
    with f.app(server) as c:
        keep = [jobs[st].job_id for st in STATES[3:]] + [keep_other.job_id, *inv]
        before = {j: f.job_state(c, j) for j in keep}
    out = cancel(db, s)
    assert out.cancelled_jobs == 4  # type: ignore[attr-defined]
    with f.app(server) as c:
        for j in (jobs["queued"], jobs["dispatched"], jobs["running"], retry):
            st = f.job_state(c, j.job_id)
            assert (st["state"], st["finished_at"]) == ("cancelled", NOW)
        for jid, row in before.items():
            assert f.job_state(c, jid) == row


# ------------------------------------------------------------ CHK-M9-183


def test_cancel_before_any_result_is_cancelled_and_derived_at_once(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-220 (3), REQ-219, #127 (d), (e): no result in the scan → the scan
    is cancelled with finished_at = now, in the cancel's own transaction."""
    pol = cat.policy(2)
    ag = agents(server, 2)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol)
        f.owner_job(o, s, ag[0], pol)
        f.owner_job(o, s, ag[1], pol, state="dispatched")
    out = cancel(db, s)
    assert (out.state, out.cancelled_jobs) == ("cancelled", 2)  # type: ignore[attr-defined]
    with f.app(server) as c:
        row = f.scan_row(c, s)
    assert (row["state"], row["finished_at"]) == ("cancelled", NOW)


def test_cancel_after_some_results_is_partial_never_cancelled(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """#127 (d) (answers jobs-and-scans.md:40), CHK-M9-360: a scan with one
    completed unit and one running unit with a result is partial after the
    cancel, not cancelled."""
    pol = cat.policy(2)
    ag = agents(server, 2)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        done = f.owner_job(o, s, ag[0], pol, state="completed")
        for p in pol.plugins:
            f.owner_result(o, done, pol, p)
        run = f.owner_job(o, s, ag[1], pol, state="running")
        f.owner_result(o, run, pol, pol.plugins[0])
    out = cancel(db, s)
    assert (out.state, out.cancelled_jobs) == ("partial", 1)  # type: ignore[attr-defined]
    with f.app(server) as c:
        assert f.scan_row(c, s)["state"] == "partial"


def test_cancel_when_every_unit_is_complete_is_completed(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """#127 (d): the original filled every plugin by late results while its
    retry was still queued; cancelling the retry leaves every unit complete,
    so the scan is completed."""
    pol = cat.policy(2)
    (a,) = agents(server, 1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state="completed")
        for p in pol.plugins:
            f.owner_result(o, orig, pol, p)
        f.owner_job(o, s, a, pol, pol.plugins[1:], state="queued", retry_of=orig.job_id)
    out = cancel(db, s)
    assert (out.state, out.cancelled_jobs) == ("completed", 1)  # type: ignore[attr-defined]


# ------------------------------------------------------------ CHK-M9-184


def test_a_repeat_cancels_nothing_and_each_call_writes_one_entry(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-220 (4), (5), #122 (g), #129 (a), ruling "one entry per call":
    the second cancel answers cancelled_jobs 0 with the same state; each call
    writes exactly one scan.cancel entry (actor, target scan:<id>, detail
    {cancelled_jobs}); the chain verifies; an unknown scan raises
    ScanNotFound and writes nothing."""
    pol = cat.policy(1)
    (a,) = agents(server, 1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol)
        f.owner_job(o, s, a, pol)
    with f.app(server) as c:
        mark = f.last_audit(c)
    first = cancel(db, s, actor="user:41")
    second = cancel(db, s, actor="user:42", now=NOW + timedelta(minutes=1))
    assert (first.cancelled_jobs, second.cancelled_jobs) == (1, 0)  # type: ignore[attr-defined]
    assert first.state == second.state == "cancelled"  # type: ignore[attr-defined]
    with f.app(server) as c:
        entries = f.audit_after(c, mark)
        assert f.scan_row(c, s)["finished_at"] == NOW  # not moved by the repeat
    assert [(e["actor"], e["action"], e["target"], e["detail"]) for e in entries] == [
        ("user:41", "scan.cancel", f"scan:{s}", {"cancelled_jobs": 1}),
        ("user:42", "scan.cancel", f"scan:{s}", {"cancelled_jobs": 0}),
    ]
    with f.app(server) as c:
        mark = f.last_audit(c)
    with pytest.raises(ScanNotFound):
        cancel(db, uuid4())
    with f.app(server) as c:
        assert f.audit_after(c, mark) == []
        assert verify_chain(c).ok


# ------------------------------------------------------------ CHK-M9-185 / REQ-220 (2)


def test_cancelled_jobs_are_never_pulled_and_posts_are_refused(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-220 (2), REQ-229 (2), TS §4.4 L581: after the cancel, a pull
    returns only the agent's inventory job (never the cancelled queued job),
    whose state the cancel left alone; posts for the cancelled dispatched and
    running jobs are refused (own_cancelled) and store nothing."""
    pol = cat.policy(1)
    a, b, c_ = agents(server, 3)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        q = f.owner_job(o, s, a, pol, created_at=NOW - timedelta(hours=1))
        d = f.owner_job(o, s, b, pol, state="dispatched")
        r = f.owner_job(o, s, c_, pol, state="running")
        inv = f.owner_inventory_job(o, a, created_at=NOW - timedelta(minutes=30))
    with f.app(server) as conn:
        inv_before = f.job_state(conn, inv)
    cancel(db, s)
    with f.app(server) as conn:
        assert f.job_state(conn, inv) == inv_before
    with db.transaction() as tx:
        pulled = JobRepo(tx.conn).pull(a, NOW)
    assert [j["job_id"] for j in pulled] == [str(inv)]
    batch = schemas.ResultsRequest.model_validate(
        {"results": [item(pol.plugins[0])], "final": True}
    )
    for job in (d, r):
        got = accept_results(
            db, agent_id=job.agent_id, job_id=job.job_id, batch=batch, now=NOW
        )
        assert got == Refused("job_not_acceptable", True)
    with f.app(server) as conn:
        assert f.results_of(conn, [q.job_id, d.job_id, r.job_id]) == []


def test_cancel_and_a_result_post_on_one_job_serialise(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """Lock order (scan row, then open jobs; intake: root, then job): a cancel
    and a post racing on one running job (barrier, 20 rounds) never deadlock
    or error; either the post stored its row before the cancel, or it was
    refused after it; the job ends cancelled."""
    pol = cat.policy(2)  # one result leaves the job running
    batch = schemas.ResultsRequest.model_validate(
        {"results": [item(pol.plugins[0])], "final": False}
    )
    for n in range(20):
        (a,) = agents(server, 1)
        with f.owner(server) as o:
            s = f.owner_scan(o, pol, state="running")
            j = f.owner_job(o, s, a, pol, state="running")
        barrier = threading.Barrier(2, timeout=30)
        outs: dict[str, object] = {}

        def do_post(
            j: f.JobRow = j,
            outs: dict[str, object] = outs,
            barrier: threading.Barrier = barrier,
        ) -> None:
            barrier.wait()
            outs["post"] = accept_results(
                db, agent_id=j.agent_id, job_id=j.job_id, batch=batch, now=NOW
            )

        def do_cancel(
            s: UUID = s,
            outs: dict[str, object] = outs,
            barrier: threading.Barrier = barrier,
        ) -> None:
            barrier.wait()
            outs["cancel"] = cancel(db, s)

        runs = f.run_threads([do_post, do_cancel])
        assert [r.error for r in runs] == [None, None], (n, runs)
        with f.app(server) as conn:
            rows = f.results_of(conn, [j.job_id])
            assert f.job_state(conn, j.job_id)["state"] == "cancelled"
        if isinstance(outs["post"], Accepted):
            assert len(rows) == 1 and outs["post"] == Accepted(1, 0)
        else:
            assert rows == [] and outs["post"] == Refused("job_not_acceptable", True)
