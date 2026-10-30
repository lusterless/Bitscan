"""TASK-202 TEST: the offline_sweep compliance steps and the scan state
refresh on PostgreSQL as bitscan_app, with clock control (TP-M9-15;
CHK-M9-204 to -214, -216; mutation rows CHK-M9-339 to -346, -363, -377).

Expected values: TS §3.3 L218 (offline_sweep applies job timeouts and
creates retries), §4.4 L575 (deadline; a dispatched job that never starts
fails 24 h after dispatch and gets the same single retry), L577 (one retry
holding only the plugins with no result; a retry is never retried), L579–L580
(scan finished and state), L582; §4.1 L530 (queued jobs keep their commands);
#18 (a disabled policy still gets the retry), #126 (a)–(e), #127 (a)–(f);
REQ-078 (5) (a failing step leaves the others applied), REQ-210, REQ-218,
REQ-219, REQ-228. Every sweep runs on a database of this module's own, so
its global steps see only this module's rows. Time is the ``now`` argument.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.jobs.intake import accept_results
from bitscan_manager.services.scheduler import sweep as sw
from bitscan_manager.services.scheduler.fleet_alerts import FleetAlerts

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

T = f.T0
DAY = timedelta(hours=24)
SEC = timedelta(seconds=1)
US = timedelta(microseconds=1)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sweepc")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


def agent(server: PgServer, status: str = "online", at: datetime = T) -> UUID:
    with f.app(server) as c:
        return f.make_agent(c, status, at=at).agent_id


def retries_of(server: PgServer, job_id: UUID) -> list[dict[str, Any]]:
    with f.app(server) as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT job_id FROM scan_job WHERE retry_of = %s", (job_id,)
            ).fetchall()
        ]
        return [f.job_state(c, j) | {"job_id": j} for j in ids]


def state(server: PgServer, job_id: UUID) -> dict[str, Any]:
    with f.app(server) as c:
        return f.job_state(c, job_id)


def expect_retry(
    r: dict[str, Any],
    orig: f.JobRow,
    pol: f.Pol,
    missing: list[f.PluginDef],
    now: datetime,
    patterns: list[str],
) -> None:
    """REQ-210, #126 (a), (b): the TS §6.5 body of the original's missing
    plugins, in the original order, with the original's commands and
    patterns, job_id = the row id, pickup_by = now + 24 h, the matching
    eval_spec entries of the original, retry_of = the original."""
    want = f.payload_of(r["job_id"], orig.agent_id, now, missing, patterns)
    assert r["payload"] == want
    assert r["eval_spec"] == {
        "plugins": [
            e
            for e in orig.eval_spec["plugins"]
            if e["plugin_uuid"] in {str(p.plugin_uuid) for p in missing}
        ]
    }
    assert (r["retry_of"], r["scan_id"], r["agent_id"], r["kind"]) == (
        orig.job_id,
        orig.scan_id,
        orig.agent_id,
        "compliance",
    )
    assert (r["state"], r["created_at"], r["pickup_by"]) == ("queued", now, now + DAY)
    assert r["dispatched_at"] is None


# ------------------------------------------------------------ CHK-M9-204


def test_deadline_passed_with_some_results_is_partial_with_one_retry(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (1), #127 (b): 2 of 5 results → partial, finished_at = now,
    and one retry with plugins 1, 3, 5; with no result → failed and a retry
    with all 5. At the deadline exactly nothing happens (CHK-M9-339)."""
    pol = cat.policy(5)
    p = pol.plugins
    pats = [r"token=\S+"]
    a, b = agent(server), agent(server)
    dl = T + timedelta(hours=1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        half = f.owner_job(o, s, a, pol, state="running", deadline_at=dl, patterns=pats)
        f.owner_result(o, half, pol, p[1])
        f.owner_result(o, half, pol, p[3])
        none = f.owner_job(o, s, b, pol, state="running", deadline_at=dl, patterns=pats)
    at_dl = sw.run_sweep(db, dl)
    assert (at_dl.deadline_ended, at_dl.retries, at_dl.failed_steps) == (0, 0, [])
    assert state(server, half.job_id)["state"] == "running"
    now = dl + US
    out = sw.run_sweep(db, now)
    assert (out.deadline_ended, out.retries, out.failed_steps) == (2, 2, [])
    h, n = state(server, half.job_id), state(server, none.job_id)
    assert (h["state"], h["finished_at"]) == ("partial", now)
    assert (n["state"], n["finished_at"]) == ("failed", now)
    (rh,) = retries_of(server, half.job_id)
    (rn,) = retries_of(server, none.job_id)
    expect_retry(rh, half, pol, [p[0], p[2], p[4]], now, pats)
    expect_retry(rn, none, pol, list(p), now, pats)
    again = sw.run_sweep(db, now + timedelta(minutes=1))
    assert (again.deadline_ended, again.retries) == (0, 0)
    assert len(retries_of(server, half.job_id)) == 1


def test_deadline_passed_with_every_result_is_completed_without_retry(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """#127 (b): at the deadline a job whose unit holds every result is
    completed; no retry."""
    pol = cat.policy(2)
    a = agent(server)
    dl = T + timedelta(hours=2)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a, pol, state="running", deadline_at=dl)
        for p in pol.plugins:
            f.owner_result(o, j, pol, p)
    sw.run_sweep(db, dl + SEC)
    assert state(server, j.job_id)["state"] == "completed"
    assert retries_of(server, j.job_id) == []


# ------------------------------------------------------------ CHK-M9-205


def test_never_started_fails_24_hours_after_dispatch_and_retries(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (2), TS §4.4 L575, CHK-M9-340: dispatched at D, never started:
    at D + 24 h nothing changes; 1 s later → failed and a retry with every
    plugin; a job created long before but dispatched at D is measured from D."""
    pol = cat.policy(3)
    a = agent(server)
    d = T + timedelta(hours=3)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(
            o,
            s,
            a,
            pol,
            state="dispatched",
            created_at=d - timedelta(hours=20),
            dispatched_at=d,
        )
    first = sw.run_sweep(db, d + DAY)
    assert (first.never_started_failed, state(server, j.job_id)["state"]) == (
        0,
        "dispatched",
    )
    now = d + DAY + SEC
    out = sw.run_sweep(db, now)
    assert (out.never_started_failed, out.retries) == (1, 1)
    st = state(server, j.job_id)
    assert (st["state"], st["finished_at"], st["started_at"]) == ("failed", now, None)
    (r,) = retries_of(server, j.job_id)
    expect_retry(r, j, pol, list(pol.plugins), now, [])


# ------------------------------------------------------------ CHK-M9-206


def test_a_retry_is_never_retried_and_a_partial_by_final_batch_is_not(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (3), (4), TS §4.4 L577, #126 (c), CHK-M9-341, -342: a retry past
    its deadline ends failed (or partial with a result), with no retry of it;
    a retry dispatched and never started fails with none; an original that
    ended partial by a final batch is not a candidate and gets no retry."""
    pol = cat.policy(3)
    a, b, c_ = agent(server), agent(server), agent(server)
    dl = T + timedelta(hours=4)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        o1 = f.owner_job(o, s, a, pol, state="failed")
        r1 = f.owner_job(
            o, s, a, pol, state="running", retry_of=o1.job_id, deadline_at=dl
        )
        o2 = f.owner_job(o, s, b, pol, state="partial")
        r2 = f.owner_job(
            o,
            s,
            b,
            pol,
            pol.plugins[1:],
            state="running",
            retry_of=o2.job_id,
            deadline_at=dl,
        )
        f.owner_result(o, r2, pol, pol.plugins[1])
        o3 = f.owner_job(o, s, c_, pol, state="failed")
        r3 = f.owner_job(
            o,
            s,
            c_,
            pol,
            state="dispatched",
            retry_of=o3.job_id,
            dispatched_at=dl - 2 * DAY,
        )
        fin = f.owner_job(o, s, agent(server), pol, state="partial", deadline_at=dl)
    out = sw.run_sweep(db, dl + SEC)
    assert out.retries == 0
    assert state(server, r1.job_id)["state"] == "failed"
    assert state(server, r2.job_id)["state"] == "partial"
    assert state(server, r3.job_id)["state"] == "failed"
    for j in (r1, r2, r3, fin):
        assert retries_of(server, j.job_id) == []
    assert state(server, fin.job_id)["state"] == "partial"


# ------------------------------------------------------------ CHK-M9-207


def test_two_sweeps_at_once_make_one_retry(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (5), #126 (c), CHK-M9-346: two sweeps released by one barrier
    over 10 jobs past their deadline make exactly one retry per job."""
    pol = cat.policy(2)
    dl = T + timedelta(hours=5)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        jobs = [
            f.owner_job(o, s, agent(server), pol, state="running", deadline_at=dl)
            for _ in range(10)
        ]
    barrier = threading.Barrier(2, timeout=30)

    def one() -> sw.SweepResult:
        barrier.wait()
        return sw.run_sweep(db, dl + SEC)

    outs = f.run_threads([one, one])
    assert [o.error for o in outs] == [None, None]
    assert sum(o.value.retries for o in outs) == 10
    assert all(o.value.failed_steps == [] for o in outs)
    for j in jobs:
        assert len(retries_of(server, j.job_id)) == 1


def test_a_sweep_and_a_result_post_on_one_unit_never_deadlock(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (5), REQ-216 (4): 20 rounds of a sweep and a post to the same
    retry (and its original as root) at one barrier: no error, no failed
    step; the post's result is stored once; at most one retry per original;
    a retry past its deadline ends by the unit's results."""
    pol = cat.policy(2)
    p1, p2 = pol.plugins
    for n in range(20):
        dl = T + timedelta(hours=6, minutes=n)
        with f.owner(server) as o:
            s = f.owner_scan(o, pol, state="running")
            orig = f.owner_job(o, s, agent(server), pol, state="partial")
            f.owner_result(o, orig, pol, p1)
            retry = f.owner_job(
                o,
                s,
                orig.agent_id,
                pol,
                [p2],
                state="running",
                retry_of=orig.job_id,
                deadline_at=dl,
            )
        batch = schemas.ResultsRequest.model_validate(
            {
                "results": [
                    {
                        "plugin_uuid": str(p2.plugin_uuid),
                        "exit_code": 0,
                        "stdout": "ok",
                        "stderr": "",
                        "started_at": f.iso(dl),
                        "finished_at": f.iso(dl),
                        "timed_out": False,
                        "truncated": False,
                        "error": None,
                    }
                ],
                "final": True,
            }
        )
        barrier = threading.Barrier(2, timeout=30)

        def do_sweep(barrier: threading.Barrier = barrier, dl: datetime = dl) -> Any:
            barrier.wait()
            return sw.run_sweep(db, dl + SEC)

        def do_post(
            barrier: threading.Barrier = barrier,
            retry: f.JobRow = retry,
            dl: datetime = dl,
            batch: schemas.ResultsRequest = batch,
        ) -> Any:
            barrier.wait()
            return accept_results(
                db,
                agent_id=retry.agent_id,
                job_id=retry.job_id,
                batch=batch,
                now=dl + SEC,
            )

        outs = f.run_threads([do_sweep, do_post])
        assert [o.error for o in outs] == [None, None], n
        assert outs[0].value.failed_steps == [], n
        with f.app(server) as c:
            rows = f.results_of(c, [orig.job_id, retry.job_id])
        assert sorted(r["plugin_uuid"] for r in rows) == sorted(
            [p1.plugin_uuid, p2.plugin_uuid]
        )
        assert retries_of(server, retry.job_id) == []
        assert state(server, retry.job_id)["state"] == "completed"


# ------------------------------------------------------------ CHK-M9-208


def test_no_retry_for_a_deleted_policy_or_decommissioned_agent_but_for_disabled(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-218 (6), #126 (d), #18: a deleted policy and a decommissioned agent
    end the job failed with no retry; a policy that is only disabled still
    gets its retry."""
    gone, off, live = cat.policy(1), cat.policy(1), cat.policy(1)
    dl = T + timedelta(hours=7)
    with f.owner(server) as o:
        jg = f.owner_job(
            o,
            f.owner_scan(o, gone, state="running"),
            agent(server),
            gone,
            state="running",
            deadline_at=dl,
        )
        jd = f.owner_job(
            o,
            f.owner_scan(o, live, state="running"),
            agent(server, "decommissioned"),
            live,
            state="running",
            deadline_at=dl,
        )
        jo = f.owner_job(
            o,
            f.owner_scan(o, off, state="running"),
            agent(server),
            off,
            state="running",
            deadline_at=dl,
        )
    cat.delete(gone)
    cat.reimport(off, status="disabled")
    out = sw.run_sweep(db, dl + SEC)
    assert out.failed_steps == []
    for j in (jg, jd, jo):
        assert state(server, j.job_id)["state"] == "failed"
    assert retries_of(server, jg.job_id) == [] and retries_of(server, jd.job_id) == []
    assert len(retries_of(server, jo.job_id)) == 1


# ------------------------------------------------------------ CHK-M9-209


def test_a_retry_keeps_the_originals_commands_after_an_import_and_a_setting_change(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-210 (1), (2), TS §4.1 L530, #126 (a), CHK-M9-344: a 5-plugin original
    with results for plugins 2 and 4; an import then changes plugin 3's
    Execute and the redaction setting changes; the retry still holds 1, 3, 5
    with the original's commands, timeouts and patterns, and the original's
    three eval_spec entries."""
    pol = cat.policy(5)
    p = pol.plugins
    pats = ["orig-pattern-[0-9]+"]
    dl = T + timedelta(hours=8)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(
            o, s, agent(server), pol, state="running", deadline_at=dl, patterns=pats
        )
        f.owner_result(o, j, pol, p[1])
        f.owner_result(o, j, pol, p[3])
    changed = f.PluginDef(
        p[2].plugin_uuid,
        p[2].name,
        "echo new-command",
        p[2].operator,
        p[2].expected,
        99,
    )
    cat.reimport(pol, [p[0], p[1], changed, p[3], p[4]])
    now = dl + SEC
    with f.setting(server, "redaction_patterns", ["new-pattern"]):
        sw.run_sweep(db, now)
    (r,) = retries_of(server, j.job_id)
    expect_retry(r, j, pol, [p[0], p[2], p[4]], now, pats)
    assert r["payload"]["plugins"][1]["execute"] == p[2].execute != "echo new-command"


# ------------------------------------------------------------ CHK-M9-210


def test_a_fault_before_the_retry_insert_rolls_the_ending_back(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#126 (c), CHK-M9-345: the ending and its retry are one unit of work: a
    fault in insert_retry rolls the ending back too (r1: the job's own
    savepoint), so the job is still running with no retry, never failed
    without one; the next sweep ends it and makes the retry."""
    pol = cat.policy(2)
    dl = T + timedelta(hours=9)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, agent(server), pol, state="running", deadline_at=dl)
    real = sw.ComplianceRepos.insert_retry

    def boom(self: Any, *a: Any, **k: Any) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(sw.ComplianceRepos, "insert_retry", boom)
    sw.run_sweep(db, dl + SEC)
    assert state(server, j.job_id)["state"] == "running"
    assert retries_of(server, j.job_id) == []
    monkeypatch.setattr(sw.ComplianceRepos, "insert_retry", real)
    out = sw.run_sweep(db, dl + 2 * SEC)
    assert out.failed_steps == [] and out.retries == 1
    assert state(server, j.job_id)["state"] == "failed"


# ------------------------------------------------------------ CHK-M9-211


def test_the_m3_steps_still_apply_and_stand_alone(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-218 (7), (8), REQ-078 (5), TS §3.4 L244: an inventory job
    dispatched 31 min ago without an upload fails and is never retried; a
    queued compliance job past pickup_by expires and bitscan_jobs_expired
    grows by the expired count after commit; with the new deadline step failing, the M3
    steps and the scan refresh still apply."""
    pol = cat.policy(1)
    now = T + timedelta(days=4)
    a = agent(server, at=now)
    with f.owner(server) as o:
        inv = f.owner_inventory_job(
            o,
            a,
            state="dispatched",
            created_at=now - timedelta(minutes=40),
            dispatched_at=now - timedelta(minutes=31),
        )
        s = f.owner_scan(o, pol, created_at=now - 2 * DAY)
        q = f.owner_job(o, s, a, pol, created_at=now - 2 * DAY)
    before = REGISTRY.get_sample_value("bitscan_jobs_expired_total") or 0.0

    def boom(self: Any, now: datetime) -> list[UUID]:
        raise RuntimeError("injected")

    monkeypatch.setattr(sw.ComplianceRepos, "past_deadline", boom)
    out = sw.run_sweep(db, now)
    assert out.failed_steps == ["compliance_deadline"]
    assert state(server, inv)["state"] == "failed"
    assert retries_of(server, inv) == []
    assert state(server, q.job_id)["state"] == "expired" and out.expired >= 1
    after = REGISTRY.get_sample_value("bitscan_jobs_expired_total") or 0.0
    assert after == before + out.expired  # earlier tests' retries expire too
    with f.app(server) as c:
        row = f.scan_row(c, s)
    assert (row["state"], row["finished_at"]) == ("failed", now)  # all expired


# ------------------------------------------------------------ CHK-M9-212


def test_scan_refresh_follows_the_units(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-219 (1), (2), (5), #127 (d), (e): after a sweep, a scan whose jobs
    all completed is completed with finished_at; completed + expired is
    partial; all expired is failed; a finished partial scan whose failed job
    then gets its missing results is completed at the next sweep with
    finished_at unchanged; no scan is ever dispatched or expired."""
    pol = cat.policy(1)
    p = pol.plugins[0]
    now = T + timedelta(days=1, hours=1)
    with f.owner(server) as o:
        s_done = f.owner_scan(o, pol, state="running")
        for _ in range(2):
            j = f.owner_job(o, s_done, agent(server, at=now), pol, state="completed")
            f.owner_result(o, j, pol, p)
        s_part = f.owner_scan(o, pol, state="running")
        jc = f.owner_job(o, s_part, agent(server, at=now), pol, state="completed")
        f.owner_result(o, jc, pol, p)
        f.owner_job(o, s_part, agent(server, at=now), pol, state="expired")
        s_fail = f.owner_scan(o, pol, state="running")
        f.owner_job(o, s_fail, agent(server, at=now), pol, state="expired")
        s_late = f.owner_scan(o, pol, state="running")
        jl = f.owner_job(o, s_late, agent(server, at=now), pol, state="completed")
        f.owner_result(o, jl, pol, p)
        late = f.owner_job(
            o,
            s_late,
            agent(server, at=now),
            pol,
            state="failed",
            dispatched_at=now - timedelta(hours=2),
        )
    sw.run_sweep(db, now)
    with f.app(server) as c:
        got = {s: f.scan_row(c, s) for s in (s_done, s_part, s_fail, s_late)}
    assert (got[s_done]["state"], got[s_done]["finished_at"]) == ("completed", now)
    assert (got[s_part]["state"], got[s_part]["finished_at"]) == ("partial", now)
    assert (got[s_fail]["state"], got[s_fail]["finished_at"]) == ("failed", now)
    assert (got[s_late]["state"], got[s_late]["finished_at"]) == ("partial", now)
    batch = schemas.ResultsRequest.model_validate(
        {
            "results": [
                {
                    "plugin_uuid": str(p.plugin_uuid),
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                    "started_at": f.iso(now),
                    "finished_at": f.iso(now),
                    "timed_out": False,
                    "truncated": False,
                    "error": None,
                }
            ],
            "final": True,
        }
    )
    later = now + timedelta(hours=1)
    accept_results(
        db, agent_id=late.agent_id, job_id=late.job_id, batch=batch, now=later
    )
    sw.run_sweep(db, later + timedelta(minutes=1))
    with f.app(server) as c:
        row = f.scan_row(c, s_late)
        bad = f.one(
            c, "SELECT count(*) FROM scan WHERE state IN ('dispatched', 'expired')"
        )
    assert (row["state"], row["finished_at"]) == ("completed", now)
    assert bad == 0


def test_a_policy_delete_cancelling_the_last_queued_jobs_finishes_the_scan(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-219 (3), TS §4.3 L550: M7's delete cancels the scan's queued jobs
    (without touching the scan); the next sweep gives it cancelled (no
    results) or partial (some results), with finished_at."""
    a_pol, b_pol = cat.policy(2), cat.policy(2)
    now = T + timedelta(days=1, hours=2)
    with f.owner(server) as o:
        sa_ = f.owner_scan(o, a_pol)
        f.owner_job(o, sa_, agent(server, at=now), a_pol)
        sb = f.owner_scan(o, b_pol, state="running")
        done = f.owner_job(o, sb, agent(server, at=now), b_pol, state="completed")
        for p in b_pol.plugins:
            f.owner_result(o, done, b_pol, p)
        f.owner_job(o, sb, agent(server, at=now), b_pol)
    cat.delete(a_pol)
    cat.delete(b_pol)
    sw.run_sweep(db, now)
    with f.app(server) as c:
        ra, rb = f.scan_row(c, sa_), f.scan_row(c, sb)
    assert (ra["state"], ra["finished_at"]) == ("cancelled", now)
    assert (rb["state"], rb["finished_at"]) == ("partial", now)


# ------------------------------------------------------------ CHK-M9-213


def test_refresh_reads_scan_job_once_and_writes_only_changed_scans(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-219 (4), #127 (f): the refresh step reads scan_job in one statement
    for all candidates; an unchanged scan is not updated; a completed scan
    and a finished scan older than 8 days are not among the ids read."""
    pol = cat.policy(1)
    now = T + timedelta(days=12)
    with f.owner(server) as o:
        old = f.owner_scan(
            o,
            pol,
            state="partial",
            created_at=now - timedelta(days=9),
            finished_at=now - timedelta(days=8),
        )
        f.owner_job(o, old, agent(server, at=now), pol, state="failed")
        comp = f.owner_scan(
            o, pol, state="completed", created_at=now - DAY, finished_at=now
        )
        f.owner_job(o, comp, agent(server, at=now), pol, state="completed")
        same = f.owner_scan(o, pol, state="queued", created_at=now - timedelta(hours=1))
        f.owner_job(
            o, same, agent(server, at=now), pol, created_at=now - timedelta(hours=1)
        )
        moving = f.owner_scan(
            o, pol, state="queued", created_at=now - timedelta(hours=1)
        )
        f.owner_job(
            o,
            moving,
            agent(server, at=now),
            pol,
            state="dispatched",
            created_at=now - timedelta(hours=1),
        )
    seen: list[list[UUID]] = []
    real = sw.ComplianceRepos.unit_facts

    def spy_facts(self: Any, ids: Any) -> Any:
        seen.append(list(ids))
        return real(self, ids)

    written: list[UUID] = []
    real_set = sw.ComplianceRepos.set_scan_state

    def spy_set(self: Any, scan_id: UUID, st: str, fin: Any) -> bool:
        written.append(scan_id)
        return real_set(self, scan_id, st, fin)

    monkeypatch.setattr(sw.ComplianceRepos, "unit_facts", spy_facts)
    monkeypatch.setattr(sw.ComplianceRepos, "set_scan_state", spy_set)
    spy = f.StatementSpy()
    with db.transaction() as tx:
        spy.install(monkeypatch)
        out = sw.SweepResult()
        sw._scan_states(sw.pg_stores(tx), now, out)
        sts = list(spy.statements)
    reads = [
        s
        for s in sts
        if "scan_job" in s and s.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    updates = [s for s in sts if s.lstrip().upper().startswith("UPDATE SCAN ")]
    assert len(seen) == 1 and len(reads) == 1
    assert old not in seen[0] and comp not in seen[0]
    assert {same, moving} <= set(seen[0])
    assert moving in written and same not in written  # unchanged: not written
    assert out.scans_refreshed == len(updates) == len(written)
    with f.app(server) as c:
        assert f.scan_row(c, moving)["state"] == "running"
        assert f.scan_row(c, same)["state"] == "queued"


# ------------------------------------------------------------ CHK-M9-214


def test_queue_age_counts_compliance_jobs_of_online_agents_only(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-228 (1), #66, TS §8.4 L1291: a compliance job queued for more than
    1 h for an online agent raises job_queue_age once in the hour; for an
    offline agent it does not."""
    pol = cat.policy(1)
    now = T + timedelta(days=13)
    with f.app(server) as c:
        c.execute(
            "UPDATE scan_job SET state = 'cancelled', finished_at = %s"
            " WHERE state = 'queued'",
            (now,),
        )
        off = f.make_agent(c, "offline", at=now).agent_id
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, created_at=now - timedelta(hours=2))
        f.owner_job(
            o, s, off, pol, created_at=now - timedelta(hours=2), pickup_by=now + DAY
        )
    clock = f.Clock(now)
    fleet = FleetAlerts(clock)
    with f.app(server) as c:
        mark = f.last_audit(c)
    fleet.run(db, now)
    with f.app(server) as c:
        kinds = [e["detail"].get("alert_kind") for e in f.audit_after(c, mark)]
    assert "job_queue_age" not in kinds
    with f.app(server) as c:
        on = f.make_agent(c, "online", at=now).agent_id
    with f.owner(server) as o:
        f.owner_job(
            o, s, on, pol, created_at=now - timedelta(hours=2), pickup_by=now + DAY
        )
    fleet.run(db, now)
    fleet.run(db, now + timedelta(minutes=10))
    with f.app(server) as c:
        kinds = [e["detail"].get("alert_kind") for e in f.audit_after(c, mark)]
    assert kinds.count("job_queue_age") == 1


# ------------------------------------------------------------ CHK-M9-216


def test_the_sweep_never_rewrites_an_existing_jobs_payload_or_spec(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-230 (2), TS §5.2 L1011, CHK-M9-377: across a sweep that ends,
    retries and refreshes, every pre-existing job keeps payload, eval_spec,
    agent_id, scan_id and retry_of byte for byte."""
    pol = cat.policy(3)
    dl = T + timedelta(days=14)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(
            o, s, agent(server, at=dl), pol, state="running", deadline_at=dl
        )
        f.owner_result(o, j, pol, pol.plugins[0])
    q = (
        "SELECT md5(string_agg(job_id::text || payload::text"
        " || coalesce(eval_spec::text, '') || agent_id::text"
        " || coalesce(scan_id::text, '') || coalesce(retry_of::text, ''),"
        " '|' ORDER BY job_id)) FROM scan_job WHERE created_at <= %s"
    )
    with f.app(server) as c:
        before = f.one(c, q, (dl,))
    out = sw.run_sweep(db, dl + SEC)
    assert out.retries >= 1
    with f.app(server) as c:
        assert f.one(c, q, (dl,)) == before


# ------------------------------------------------------------ r1: a bad row alone


@pytest.mark.parametrize("bad", ["eval_spec", "payload"])
def test_one_bad_job_fails_closed_alone_and_the_others_still_end(
    server: PgServer,
    db: AppDatabase,
    cat: f.Catalog,
    bad: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TASK-202 r1 (decisions "PD-39 second look applied to TASK-198", review
    of TASK-202): per-job savepoints. One past-deadline job whose stored
    eval_spec does not parse (or whose payload has no plugins), written as
    owner, next to normal past-deadline and never-started jobs: the sweep
    raises nothing out, the normal jobs still end and get their retries in
    this same sweep, and the bad job gets no retry."""
    pol = cat.policy(2)
    dl = T + timedelta(days=15)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        good = f.owner_job(
            o, s, agent(server, at=dl), pol, state="running", deadline_at=dl
        )
        never = f.owner_job(
            o,
            s,
            agent(server, at=dl),
            pol,
            state="dispatched",
            dispatched_at=dl - 2 * DAY,
        )
        broken = f.owner_job(
            o,
            s,
            agent(server, at=dl),
            pol,
            state="running",
            deadline_at=dl,
            eval_spec={"plugins": "not a list"} if bad == "eval_spec" else None,
        )
        if bad == "payload":
            o.execute(
                "UPDATE scan_job SET payload = payload - 'plugins' WHERE job_id = %s",
                (broken.job_id,),
            )
    caplog.set_level(logging.DEBUG)
    before = state(server, broken.job_id)
    out = sw.run_sweep(db, dl + SEC)
    assert out.failed_steps == []
    assert state(server, broken.job_id) == before  # rolled back alone, still running
    mine = [
        getattr(r, "data", {})
        for r in caplog.records
        if r.getMessage() == "sweep job failed"
        and getattr(r, "data", {}).get("job_id") == str(broken.job_id)
    ]
    assert len(mine) == 1 and set(mine[0]) == {"step", "job_id", "exc_type"}
    assert mine[0]["step"] == "compliance_deadline"
    # (earlier tests' poison rows are still due and logged again: by design)
    assert state(server, good.job_id)["state"] == "failed"
    assert state(server, never.job_id)["state"] == "failed"
    assert len(retries_of(server, good.job_id)) == 1
    assert len(retries_of(server, never.job_id)) == 1
    assert retries_of(server, broken.job_id) == []
    assert out.retries >= 2


# ------------------------------------------------------------ REQ-228 (2)


def test_offline_share_and_stale_inventory_with_compliance_rows_present(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-228 (2), TS §8.4 L1291, #65 (b), (c): with compliance jobs and
    results present for the fleet, agents_offline still follows "more than
    5 % of the eligible agents offline" (1 of 10 → alert), and
    inventory_stale names exactly the heartbeating agent whose
    last_inventory_at is older than twice the inventory interval; compliance
    results do not count as inventory."""
    now = T + timedelta(days=16)
    with f.app(server) as c:
        c.execute(
            "UPDATE agent SET status = 'decommissioned'"
        )  # this module's fleet only
        interval = int(
            f.one(
                c, "SELECT interval_s FROM system_schedule WHERE job_kind = 'inventory'"
            )
        )
        fresh = now - timedelta(seconds=interval)
        ids = [
            f.make_agent(c, "online", at=now, last_inventory_at=fresh).agent_id
            for _ in range(8)
        ]
        stale = f.make_agent(
            c,
            "online",
            at=now,
            last_inventory_at=now - timedelta(seconds=2 * interval + 60),
        ).agent_id
        off = f.make_agent(c, "offline", at=now, last_inventory_at=fresh).agent_id
    pol = cat.policy(1)
    with f.owner(server) as o:
        s = f.owner_scan(o, pol, state="running")
        for a in [*ids, stale, off]:
            j = f.owner_job(
                o, s, a, pol, state="completed", created_at=now - timedelta(hours=1)
            )
            f.owner_result(o, j, pol, pol.plugins[0], at=now)
    with f.app(server) as c:
        mark = f.last_audit(c)
    FleetAlerts(f.Clock(now)).run(db, now)
    with f.app(server) as c:
        es = [e for e in f.audit_after(c, mark) if e["detail"].get("alert")]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for e in es:
        by_kind.setdefault(e["detail"]["alert_kind"], []).append(e)
    (offline_alert,) = by_kind["agents_offline"]
    assert (
        offline_alert["detail"]["offline"],
        offline_alert["detail"]["eligible"],
    ) == (1, 10)
    assert [e["target"] for e in by_kind["inventory_stale"]] == [f"agent:{stale}"]
