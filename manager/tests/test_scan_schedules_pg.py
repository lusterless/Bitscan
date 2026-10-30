"""TASK-203 TEST (and r1): scheduled runs with clock control on PostgreSQL
as bitscan_app (TP-M9-14; CHK-M9-195 to -202; mutation rows CHK-M9-370 to
-373; decisions "First result wins includes completed originals" and "M9
builder rulings": the tick never waits for a policy while holding its row).

Expected values: TS §4.4 L557 (cron in the schedule's timezone; missed runs
are not back-filled; a run is skipped and logged if the previous scan of the
schedule is unfinished or the policy is disabled), §4.3 L550 (a delete
disables the policy's schedules), §2.1 L103; #3 (zero agents: skipped),
#128 (d)–(g) (30 s tick; due = enabled and next_run_at ≤ now; a due time
more than 2 minutes old is missed; skip words; trigger 'scheduled',
requested_by NULL, actor system, never the API-token alert); REQ-225.
``now`` is passed to the tick; nothing waits on the wall clock except the
SchedulerRunner stop test, which uses a real BackgroundScheduler.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import schedules as sched_repo
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.jobs import queue as queue_mod
from bitscan_manager.services.scheduler import runner as runner_mod
from bitscan_manager.services.scheduler import scan_schedules as ss
from bitscan_manager.services.scheduler import schedules_admin as sa
from bitscan_manager.services.scheduler.runner import SchedulerRunner

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

DAY0 = f.T0.replace(hour=0)  # day 15, 00:00 UTC


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("ticks")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server, max_size=8) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


@pytest.fixture(autouse=True)
def only_mine(server: PgServer) -> None:
    """Each test starts with no enabled schedule in this module's database."""
    with f.app(server) as c:
        c.execute("UPDATE scan_schedule SET enabled = false")


def tick(db: AppDatabase, now: datetime) -> ss.TickResult:
    woken: list[int] = []
    out = ss.run_due_schedules(db, now, lambda: woken.append(1))
    return out


def create(db: AppDatabase, pol: f.Pol, now: datetime, **kw: Any) -> Any:
    args: dict[str, Any] = {
        "name": "s",
        "policy_id": pol.policy_id,
        "target": {"all": True},
        "cron": "0 3 * * *",
        "user_id": 5,
        "now": now,
    } | kw
    with db.transaction() as tx:
        return sa.create(tx, **args)


def scans_of(server: PgServer, sid: int) -> list[dict[str, Any]]:
    with f.app(server) as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT scan_id FROM scan WHERE schedule_id = %s ORDER BY created_at",
                (sid,),
            ).fetchall()
        ]
        return [f.scan_row(c, s) for s in ids]


def row(db: AppDatabase, sid: int) -> Any:
    with db.transaction() as tx:
        return sched_repo.get(tx.conn, sid)


def skipped(caplog: pytest.LogCaptureFixture, sid: int) -> list[str]:
    return [
        r.data["reason"]  # type: ignore[attr-defined]
        for r in caplog.records
        if r.getMessage() == "scheduled run skipped"
        and getattr(r, "data", {}).get("schedule_id") == sid
    ]


def online(server: PgServer, at: datetime, **kw: Any) -> Any:
    with f.app(server) as c:
        return f.make_agent(c, "online", at=at, **kw)


# ------------------------------------------------------------ CHK-M9-195, -202


def test_a_due_schedule_queues_one_scheduled_scan(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-225 (1), #128 (d), (g), CHK-M9-202: at 03:00 the schedule queues one
    scan with trigger scheduled, its schedule_id, requested_by NULL and one
    scan.create entry by actor system (no alert, even for {"all": true});
    last_run_at = now; next_run_at = the next day's 03:00."""
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0)
    at = DAY0.replace(hour=3)
    assert s.next_run_at == at
    with f.app(server) as c:
        mark = f.last_audit(c)
    base = (
        REGISTRY.get_sample_value(
            "bitscan_alerts_total", {"kind": "all_hosts_scan_api_token"}
        )
        or 0.0
    )
    out = tick(db, at)
    assert (out.queued, out.failed, out.busy) == (1, 0, 0)
    (scan,) = scans_of(server, s.schedule_id)
    assert (scan["trigger"], scan["requested_by"], scan["state"]) == (
        "scheduled",
        None,
        "queued",
    )
    assert scan["created_at"] == at and scan["policy_version"] == pol.version
    r = row(db, s.schedule_id)
    assert (r.last_run_at, r.next_run_at) == (at, at + timedelta(days=1))
    with f.app(server) as c:
        es = f.audit_after(c, mark)
        n_jobs = len(f.jobs_of_scan(c, scan["scan_id"]))
    assert [(e["actor"], e["action"]) for e in es] == [("system", "scan.create")]
    assert es[0]["detail"]["trigger"] == "scheduled"
    assert es[0]["detail"]["schedule_id"] == s.schedule_id
    assert es[0]["detail"].get("alert") is None
    assert (
        REGISTRY.get_sample_value(
            "bitscan_alerts_total", {"kind": "all_hosts_scan_api_token"}
        )
        or 0.0
    ) == base
    assert n_jobs >= 1
    assert tick(db, at + timedelta(seconds=30)).queued == 0  # not due again


# ------------------------------------------------------------ CHK-M9-196


def test_skips_write_no_scan_and_no_entry_and_move_next_run_on(
    server: PgServer, db: AppDatabase, cat: f.Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-225 (2), (3), TS §4.4 L557, #3, CHK-M9-372: an unfinished previous
    scan → previous_unfinished; a disabled policy → policy_disabled; a target
    with no agent → no_target_agents. None writes a scan or an audit entry;
    each moves next_run_at to the next fire and keeps last_run_at."""
    caplog.set_level(logging.INFO)
    pol = cat.policy(1)
    online(server, DAY0)
    at = DAY0.replace(hour=3)
    busy_sched = create(db, pol, DAY0)
    with f.owner(server) as o:
        f.owner_scan(
            o,
            pol,
            schedule_id=busy_sched.schedule_id,
            trigger="scheduled",
            created_at=DAY0 - timedelta(days=1),
        )  # unfinished
    off = cat.policy(1, status="disabled")
    off_sched = create(db, off, DAY0)
    empty_sched = create(db, pol, DAY0, target={"tags": ["m9.no-agent-has-this"]})
    with f.app(server) as c:
        before = f.counts(c)
    out = tick(db, at)
    assert out.queued == 0
    assert dict(out.skipped) == {
        "previous_unfinished": 1,
        "policy_disabled": 1,
        "no_target_agents": 1,
    }
    assert skipped(caplog, busy_sched.schedule_id) == ["previous_unfinished"]
    assert skipped(caplog, off_sched.schedule_id) == ["policy_disabled"]
    assert skipped(caplog, empty_sched.schedule_id) == ["no_target_agents"]
    with f.app(server) as c:
        assert f.counts(c) == before
    for s in (busy_sched, off_sched, empty_sched):
        r = row(db, s.schedule_id)
        assert (r.last_run_at, r.next_run_at) == (None, at + timedelta(days=1))
    assert len(scans_of(server, busy_sched.schedule_id)) == 1  # only the planted one


def test_skip_log_lines_carry_the_schedule_id_and_a_fixed_word_only(
    server: PgServer, db: AppDatabase, cat: f.Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    off = cat.policy([f.plugin(execute=f"echo {f.CANARY}")], status="disabled")
    create(db, off, DAY0, name=f.CANARY[:60])
    tick(db, DAY0.replace(hour=3))
    recs = [r for r in caplog.records if r.getMessage() == "scheduled run skipped"]
    assert recs and all(set(r.data) == {"schedule_id", "reason"} for r in recs)  # type: ignore[attr-defined]
    assert f.canary_hits(f.log_texts(caplog.records)) == []


# ------------------------------------------------------------ CHK-M9-197


def test_missed_runs_are_not_back_filled(
    server: PgServer, db: AppDatabase, cat: f.Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-225 (4), TS §4.4 L557, #128 (e), CHK-M9-371: an hourly schedule due
    at 01:00; the clock jumps to 03:00:10 (two fire times passed while
    'down'): no scan, a missed line, next_run_at = 04:00 (in the future).
    A tick 1 min 59 s late still runs; 2 min 1 s late is missed."""
    caplog.set_level(logging.INFO)
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0 + timedelta(minutes=30), cron="0 * * * *")
    assert s.next_run_at == DAY0.replace(hour=1)
    jump = DAY0.replace(hour=3, second=10)
    out = tick(db, jump)
    assert (out.queued, dict(out.skipped)) == (0, {"missed": 1})
    assert skipped(caplog, s.schedule_id) == ["missed"]
    assert scans_of(server, s.schedule_id) == []
    r = row(db, s.schedule_id)
    assert r.next_run_at == DAY0.replace(hour=4) and r.next_run_at > jump
    assert r.last_run_at is None
    late_ok = DAY0.replace(hour=4) + timedelta(minutes=1, seconds=59)
    assert tick(db, late_ok).queued == 1
    with f.owner(server) as o:  # the scan finished, so the next run is not skipped
        o.execute(
            "UPDATE scan SET finished_at = %s, state = 'failed' WHERE schedule_id = %s",
            (late_ok, s.schedule_id),
        )
    late_bad = DAY0.replace(hour=5) + timedelta(minutes=2, seconds=1)
    out = tick(db, late_bad)
    assert (out.queued, dict(out.skipped)) == (0, {"missed": 1})
    assert len(scans_of(server, s.schedule_id)) == 1


# ------------------------------------------------------------ CHK-M9-198


def test_a_disabled_schedule_never_runs(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-225 (5)."""
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0, enabled=False)
    for h in range(3, 30, 6):
        assert tick(db, DAY0 + timedelta(hours=h)).queued == 0
    assert scans_of(server, s.schedule_id) == []


def test_two_ticks_at_once_make_one_scan(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-225 (6), #128 (e), CHK-M9-373: two ticks (two sessions) released by
    one barrier, 10 rounds, each over one due schedule: exactly one scan per
    round, no error."""
    pol = cat.policy(1)
    online(server, DAY0)
    for n in range(10):
        s = create(db, pol, DAY0, cron=f"{n} 3 * * *")
        at = DAY0.replace(hour=3, minute=n)
        barrier = threading.Barrier(2, timeout=30)

        def one(at: datetime = at, barrier: threading.Barrier = barrier) -> Any:
            barrier.wait()
            return tick(db, at)

        outs = f.run_threads([one, one])
        assert [o.error for o in outs] == [None, None]
        assert sum(o.value.queued for o in outs) == 1, n
        assert len(scans_of(server, s.schedule_id)) == 1
        with f.app(server) as c:
            c.execute(
                "UPDATE scan_schedule SET enabled = false WHERE schedule_id = %s",
                (s.schedule_id,),
            )


# ------------------------------------------------------------ CHK-M9-199


def test_the_kolkata_schedule_runs_at_0330_utc(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-225 (7), REQ-223 (2), CHK-M9-370: '0 9 * * *' in Asia/Kolkata
    (UTC+05:30) is due at 03:30 UTC; a tick at 03:29:59 UTC queues nothing;
    at 03:30 UTC one scan; nothing at 09:00 UTC."""
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0, cron="0 9 * * *", timezone="Asia/Kolkata")
    due = DAY0.replace(hour=3, minute=30)
    assert s.next_run_at == due
    assert tick(db, due - timedelta(seconds=1)).queued == 0
    assert tick(db, due).queued == 1
    assert row(db, s.schedule_id).next_run_at == due + timedelta(days=1)
    with f.owner(server) as o:
        o.execute(
            "UPDATE scan SET finished_at = %s WHERE schedule_id = %s",
            (due, s.schedule_id),
        )
    assert tick(db, DAY0.replace(hour=9)).queued == 0


# ------------------------------------------------------------ CHK-M9-200


def test_a_failing_row_is_logged_by_type_and_the_next_tick_runs_it(
    server: PgServer,
    db: AppDatabase,
    cat: f.Catalog,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-225 (8): a row whose run raises is logged by schedule_id and the
    exception type only, left due, and the next tick runs it."""
    caplog.set_level(logging.DEBUG)
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0)
    at = DAY0.replace(hour=3)
    real = queue_mod.queue_scan

    def boom(*a: Any, **k: Any) -> Any:
        raise ValueError(f"injected {f.CANARY}")

    monkeypatch.setattr(queue_mod, "queue_scan", boom)
    out = tick(db, at)
    assert (out.queued, out.failed) == (0, 1)
    recs = [r for r in caplog.records if r.getMessage() == "scheduled run failed"]
    assert [r.data for r in recs] == [  # type: ignore[attr-defined]
        {"schedule_id": s.schedule_id, "exc_type": "ValueError"}
    ]
    assert f.CANARY not in caplog.text
    assert row(db, s.schedule_id).next_run_at == at  # unchanged: still due
    monkeypatch.setattr(queue_mod, "queue_scan", real)
    assert tick(db, at + timedelta(seconds=30)).queued == 1


def test_the_runner_registers_the_30_second_tick_and_stop_waits_for_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-225 (8), #128 (e): SchedulerRunner adds scan_schedules (interval
    30 s, one instance, run at start); a tick that raises is logged by job
    name and type; stop() returns only after a running tick ended, and no
    tick starts afterwards. A real BackgroundScheduler; fake work."""
    spans: list[tuple[float, float | None]] = []
    lock = threading.Lock()
    calls = {"n": 0}

    def slow(db: Any, now: datetime, wake: Any) -> None:
        with lock:
            calls["n"] += 1
            first = calls["n"] == 1
            spans.append((time.monotonic(), None))
            i = len(spans) - 1
        if first:
            raise RuntimeError(f"tick {f.CANARY}")
        time.sleep(1.5)
        with lock:
            spans[i] = (spans[i][0], time.monotonic())

    monkeypatch.setattr(runner_mod, "run_due_schedules", slow)
    monkeypatch.setattr(runner_mod, "run_inventory", lambda jobs, now: [])
    monkeypatch.setattr(runner_mod, "run_sweep", lambda db, now, stores: None)
    monkeypatch.setattr(runner_mod, "TICK_S", 1)

    class Db:
        def transaction(self) -> Any:
            raise RuntimeError("no database in this test")

    class Clock:
        def now(self) -> datetime:
            return datetime.now(UTC)

    caplog.set_level(logging.ERROR, logger="bitscan_manager.scheduler")
    runner = SchedulerRunner(Db(), Clock(), lambda: None)  # type: ignore[arg-type]
    runner.start()
    job = runner._scheduler.get_job("scan_schedules")
    assert job is not None and job.max_instances == 1
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with lock:
            running = any(end is None for _, end in spans[1:])
        if running:
            break
        time.sleep(0.05)
    assert running
    runner.stop()
    stopped = time.monotonic()
    with lock:
        assert all(end is not None and end <= stopped for _, end in spans[1:])
        n = len(spans)
    time.sleep(2.5)
    assert len(spans) == n  # nothing after stop
    failed = [
        r
        for r in caplog.records
        if r.getMessage() == "scheduler run failed"
        and getattr(r, "data", {}).get("job") == "scan_schedules"
    ]
    assert failed
    assert getattr(failed[0], "data", None) == {
        "job": "scan_schedules",
        "exc_type": "RuntimeError",
    }
    assert f.CANARY not in caplog.text


# ------------------------------------------------------------ CHK-M9-201


def test_a_stored_cron_that_no_longer_parses_is_retried_a_day_later(
    server: PgServer, db: AppDatabase, cat: f.Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    """Plan TASK-203 §5: an owner-written row whose cron no longer parses is
    logged 'invalid', is not disabled (user state is not changed silently),
    and its next_run_at moves one day on; no scan."""
    caplog.set_level(logging.INFO)
    pol = cat.policy(1)
    at = DAY0.replace(hour=3)
    with f.owner(server) as o:
        sid = f.owner_schedule(o, pol, cron="61 * * * *", next_run_at=at)
    tick(db, at)
    assert skipped(caplog, sid) == ["invalid"]
    r = row(db, sid)
    assert (r.enabled, r.next_run_at) == (True, at + timedelta(days=1))
    assert scans_of(server, sid) == []


# ------------------------------------------------------------ r1: tick vs delete


def test_a_tick_and_a_policy_delete_never_deadlock(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decisions "M9 builder rulings" (TASK-203 r1), TS §4.3 L550: the tick
    holds the due schedule row; M7's policy delete, started then, locks the
    policy and waits for that row (probe). The tick then finds the policy
    held: it returns busy without waiting and leaves the row; the delete
    completes and disables the schedule. No deadlock, no error, no scan; the
    disabled schedule is not run (or back-filled) by later ticks."""
    pol = cat.policy(1)
    online(server, DAY0)
    s = create(db, pol, DAY0)
    at = DAY0.replace(hour=3)
    gate = f.Gate()
    real = sched_repo.previous_unfinished  # the step just before the policy

    def parked(conn: Any, sid: int) -> bool:
        gate.wait()
        return real(conn, sid)

    monkeypatch.setattr(sched_repo, "previous_unfinished", parked)
    outs: dict[str, Any] = {}

    def run_tick() -> None:
        outs["tick"] = tick(db, at)

    def run_delete() -> None:
        outs["delete"] = cat.delete(pol)

    t1 = threading.Thread(target=run_tick)
    t1.start()
    assert gate.reached.wait(30)
    t2 = threading.Thread(target=run_delete)
    t2.start()
    try:
        f.wait_until_any_waiter(server)
    finally:
        gate.open()
        t1.join(30)
        t2.join(30)
    assert not t1.is_alive() and not t2.is_alive()
    assert "delete" in outs and "tick" in outs
    assert (outs["tick"].busy, outs["tick"].queued, outs["tick"].failed) == (1, 0, 0)
    monkeypatch.setattr(sched_repo, "previous_unfinished", real)
    assert row(db, s.schedule_id).enabled is False
    assert scans_of(server, s.schedule_id) == []
    for later in (at + timedelta(seconds=30), at + timedelta(days=1)):
        assert tick(db, later).queued == 0
    assert scans_of(server, s.schedule_id) == []
