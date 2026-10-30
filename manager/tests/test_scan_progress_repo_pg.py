"""TASK-194 TEST: the scan progress repository on PostgreSQL as bitscan_app
(TP-M9-10; CHK-M9-114 to -116; mutation rows CHK-M9-359, -361, -363).

Expected values: TS §4.4 L573, L579–L581 (scan finished; cancel moves
queued, dispatched and running jobs); #127 (d) (units: an original and its
retry; open, complete, has results), (e) (scan finished_at set once, kept),
(f) (refresh candidates: every scan with finished_at NULL, plus every scan
not completed created in the last 8 days); TS §5.2 L1012 (bitscan_app may
UPDATE only scan.state and scan.finished_at). The expected Unit values are
written by hand from the fixture each test builds.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories import scan_progress as sp
from bitscan_manager.services.jobs.scan_state import Unit

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(days=1)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sp")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    with f.app_database(server) as db:
        yield f.make_catalog(db, f.Clock(), tmp_path)


def agents(server: PgServer, n: int) -> list[UUID]:
    with f.app(server) as c:
        return [f.make_agent(c).agent_id for _ in range(n)]


def U(  # noqa: N802 - reads as a constructor in the tables below
    open: bool, complete: bool, has: bool, cancelled: bool, queued: bool
) -> Unit:
    return Unit(
        open=open,
        complete=complete,
        has_results=has,
        any_cancelled=cancelled,
        all_queued=queued,
    )


def key(u: Unit) -> tuple[bool, ...]:
    return (u.open, u.complete, u.has_results, u.any_cancelled, u.all_queued)


# ------------------------------------------------------------ CHK-M9-114


def test_unit_facts_follow_units_not_jobs(
    server: PgServer, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#127 (d), REQ-207 (1), CHK-M9-361: facts are per unit (original +
    retry). A partial original whose retry stored the missing plugins is one
    complete, closed unit; a failed original with a queued retry is one open
    unit that is not all-queued; results in the retry count for the unit; a
    scan of only queued jobs is all-queued; three scans are one statement."""
    pol = cat.policy(3)
    p1, p2, p3 = pol.plugins
    ag = agents(server, 6)
    with f.owner(server) as o:
        sa = f.owner_scan(o, pol, state="running")
        done = f.owner_job(o, sa, ag[0], pol, state="completed")
        for p in pol.plugins:
            f.owner_result(o, done, pol, p)
        part = f.owner_job(o, sa, ag[1], pol, state="partial")
        f.owner_result(o, part, pol, p1)
        fill = f.owner_job(
            o, sa, ag[1], pol, [p2, p3], state="completed", retry_of=part.job_id
        )
        f.owner_result(o, fill, pol, p2)
        f.owner_result(o, fill, pol, p3)
        failed = f.owner_job(o, sa, ag[2], pol, state="failed")
        f.owner_job(o, sa, ag[2], pol, state="queued", retry_of=failed.job_id)
        f.owner_job(o, sa, ag[3], pol, state="cancelled")
        f.owner_job(o, sa, ag[4], pol, state="expired")
        half = f.owner_job(o, sa, ag[5], pol, state="partial")
        f.owner_result(o, half, pol, p1)
        half_retry = f.owner_job(
            o, sa, ag[5], pol, [p2, p3], state="failed", retry_of=half.job_id
        )
        f.owner_result(o, half_retry, pol, p2)  # p3 never arrives
        sb = f.owner_scan(o, pol)
        f.owner_job(o, sb, ag[0], pol)
        f.owner_job(o, sb, ag[1], pol)
        sc = f.owner_scan(o, pol, state="running")
        run = f.owner_job(o, sc, ag[0], pol, state="running")
        f.owner_result(o, run, pol, p2)
        f.owner_inventory_job(o, ag[0])
    with f.app(server) as conn:
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        facts = sp.unit_facts(conn, [sa, sb, sc, uuid4()])
        n_statements = len(spy.statements)
        monkeypatch.undo()
        assert sp.unit_facts(conn, []) == {}
    assert n_statements == 1
    assert set(facts) == {sa, sb, sc}
    want_a = [
        U(False, True, True, False, False),  # completed
        U(False, True, True, False, False),  # partial + retry filled
        U(True, False, False, False, False),  # failed + queued retry
        U(False, False, False, True, False),  # cancelled
        U(False, False, False, False, False),  # expired
        U(False, False, True, False, False),  # partial + failed retry, p3 missing
    ]
    assert sorted(map(key, facts[sa])) == sorted(map(key, want_a))
    assert len(facts[sa]) == 6
    assert [key(u) for u in facts[sb]] == [key(U(True, False, False, False, True))] * 2
    assert [key(u) for u in facts[sc]] == [key(U(True, False, True, False, False))]


def test_a_result_only_in_the_retry_makes_the_unit_have_results(
    server: PgServer, cat: f.Catalog
) -> None:
    """#127 (a), (d): has_results and complete look at the whole unit."""
    pol = cat.policy(2)
    (a,) = agents(server, 1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a, pol, state="failed")
        retry = f.owner_job(o, s, a, pol, state="running", retry_of=orig.job_id)
        f.owner_result(o, retry, pol, pol.plugins[0])
    with f.app(server) as conn:
        (u,) = sp.unit_facts(conn, [s])[s]
    assert key(u) == key(U(True, False, True, False, False))


# ------------------------------------------------------------ CHK-M9-115


def test_refresh_candidates_follow_the_eight_day_rule(
    server: PgServer, cat: f.Catalog
) -> None:
    """#127 (f), CHK-M9-363: included: any scan with finished_at NULL (even 30
    days old), a finished partial/failed/cancelled scan created within 8
    days (late results can still move it); excluded: a completed scan, and a
    finished non-completed scan created 9 days ago."""
    pol = cat.policy(1)
    with f.owner(server) as o:
        old_open = f.owner_scan(
            o, pol, state="running", created_at=NOW - timedelta(days=30)
        )
        recent_partial = f.owner_scan(
            o,
            pol,
            state="partial",
            created_at=NOW - timedelta(days=7),
            finished_at=NOW - timedelta(days=6),
        )
        recent_failed = f.owner_scan(
            o,
            pol,
            state="failed",
            created_at=NOW - timedelta(days=7, hours=23),
            finished_at=NOW - timedelta(days=7),
        )
        recent_cancelled = f.owner_scan(
            o,
            pol,
            state="cancelled",
            created_at=NOW - timedelta(hours=1),
            finished_at=NOW,
        )
        completed = f.owner_scan(
            o,
            pol,
            state="completed",
            created_at=NOW - timedelta(hours=1),
            finished_at=NOW,
        )
        old_partial = f.owner_scan(
            o,
            pol,
            state="partial",
            created_at=NOW - timedelta(days=9),
            finished_at=NOW - timedelta(days=8, hours=12),
        )
        queued = f.owner_scan(o, pol, created_at=NOW)
    with f.app(server) as conn:
        got = set(sp.refresh_candidates(conn, NOW))
    assert {old_open, recent_partial, recent_failed, recent_cancelled, queued} <= got
    assert not {completed, old_partial} & got


# ------------------------------------------------------------ CHK-M9-116


def test_cancel_open_jobs_moves_only_queued_dispatched_running(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L581, REQ-220 (1), CHK-M9-359: of a scan with one job in each
    state (and a queued retry of a failed original), exactly the queued,
    dispatched, running ones and the queued retry become cancelled with
    finished_at = now; every other job of this and another scan, and the
    agents' inventory jobs, are byte-identical."""
    pol = cat.policy(2)
    states = [
        "queued",
        "dispatched",
        "running",
        "completed",
        "partial",
        "failed",
        "expired",
        "cancelled",
    ]
    ag = agents(server, len(states) + 1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        jobs = {
            st: f.owner_job(o, s, a, pol, state=st)
            for st, a in zip(states, ag, strict=False)
        }
        retry = f.owner_job(
            o, s, ag[5], pol, state="queued", retry_of=jobs["failed"].job_id
        )
        other = f.owner_scan(o, pol)
        other_q = f.owner_job(o, other, ag[8], pol)
        inv = f.owner_inventory_job(o, ag[0])
        keep = [jobs[st].job_id for st in states[3:]] + [other_q.job_id, inv]
        before = {j: f.job_state(o, j) for j in keep}
        scans = f.checksum(o, "scan")
    with f.app(server, autocommit=False) as conn:
        got = sp.cancel_open_jobs(conn, s, NOW)
        conn.commit()
    want = sorted(
        [
            jobs["queued"].job_id,
            jobs["dispatched"].job_id,
            jobs["running"].job_id,
            retry.job_id,
        ]
    )
    assert got == want
    with f.owner(server) as o:
        for j in want:
            st = f.job_state(o, j)
            assert (st["state"], st["finished_at"]) == ("cancelled", NOW)
        for j, row in before.items():
            assert f.job_state(o, j) == row
        assert f.checksum(o, "scan") == scans  # cancel does not write the scan
    with f.app(server, autocommit=False) as conn:
        assert sp.cancel_open_jobs(conn, s, NOW + timedelta(seconds=1)) == []
        conn.rollback()


def test_set_scan_state_writes_state_and_finished_at_once(
    server: PgServer, cat: f.Catalog
) -> None:
    """#127 (e), TS §5.2 L1012, REQ-219 (2), (5): finished_at is set the first
    time it is given and then kept (a later state change does not move it,
    None never clears it); an unchanged state is not written (False); the
    other scan columns never change; dispatched and expired are refused."""
    pol = cat.policy(1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        first = f.scan_row(o, s)
    t1, t2 = NOW, NOW + timedelta(hours=1)
    with f.app(server) as conn:
        assert sp.set_scan_state(conn, s, "running", None) is False
        assert sp.set_scan_state(conn, s, "partial", t1) is True
        assert sp.scan_row(conn, s) == ("partial", t1)
        assert sp.set_scan_state(conn, s, "partial", t2) is False
        assert sp.set_scan_state(conn, s, "completed", t2) is True
        assert sp.scan_row(conn, s) == ("completed", t1)
        assert sp.set_scan_state(conn, s, "partial", None) is True
        assert sp.scan_row(conn, s) == ("partial", t1)
        for bad in ("dispatched", "expired", "bogus"):
            with pytest.raises(ValueError):
                sp.set_scan_state(conn, s, bad, t2)
        assert sp.scan_row(conn, uuid4()) is None
    with f.owner(server) as o:
        last = f.scan_row(o, s)
    for col in (
        "policy_id",
        "policy_version",
        "trigger",
        "schedule_id",
        "target",
        "requested_by",
        "created_at",
    ):
        assert last[col] == first[col], col


def test_scan_row_lock_blocks_a_concurrent_state_write(
    server: PgServer, cat: f.Catalog
) -> None:
    """scan_row(lock=True) holds the scan row (for cancel's derive) until the
    transaction ends: a second session's set_scan_state waits."""
    pol = cat.policy(1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
    with f.app(server, autocommit=False) as a, f.app(server) as b:
        assert sp.scan_row(a, s, lock=True) == ("running", None)
        pid = f.backend_pid(b)
        done = threading.Event()

        def write() -> None:
            sp.set_scan_state(b, s, "failed", NOW)
            done.set()

        t = threading.Thread(target=write)
        t.start()
        try:
            f.wait_until_lock_waiting(server, pid)
            assert not done.is_set()
        finally:
            a.commit()
            t.join(10)
        assert done.is_set()
