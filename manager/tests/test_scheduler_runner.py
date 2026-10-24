"""TASK-071: SchedulerRunner and the serve lifecycle order, without PostgreSQL.

Checks CHK-M3-230 to CHK-M3-234 at unit level (the Linux serve process and the
database are in test_serve_scheduler_linux.py). Expected values: REQ-080 (1)
to (5) (inventory run and offline_sweep inside serve, intervals from
system_schedule, at most one instance of each, a failing run logged by error
type only and the next run happens, SIGTERM stops the scheduler before the
pool closes, no network client), #67 (one inventory run at start-up, then
every interval; an interval change picked up within one offline_sweep run and
the timer restarted), TS §5.2 L832 (seeded intervals 21,600 and 60 s), the
TASK-068 carry-over (FleetAlerts built once, run after run_sweep) and the
TASK-065 nit (each job transaction wakes the shipper on commit).
"""

import ast
import asyncio
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)

from bitscan_manager.cli import serve as serve_mod
from bitscan_manager.services.scheduler import runner as runner_mod
from bitscan_manager.services.scheduler.runner import SchedulerRunner

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
CANARY = "CANARY-071a2b3c4d5e6f70"
RUNNER_FILE = Path(runner_mod.__file__)


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def now(self) -> datetime:
        return self.at


@dataclass
class FakeTx:
    conn: object = field(default_factory=object)
    hooks: list[Callable[[], None]] = field(default_factory=list)

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


@dataclass
class FakeDb:
    opened: int = 0
    commits: int = 0
    rollbacks: int = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        tx = FakeTx()
        try:
            yield tx
        except BaseException:
            self.rollbacks += 1
            raise
        self.commits += 1
        for hook in tx.hooks:
            hook()


@dataclass
class FakeScheduler:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    rescheduled: list[tuple[str, str, int]] = field(default_factory=list)
    started: int = 0
    shutdowns: list[bool] = field(default_factory=list)
    running: bool = False

    def add_job(self, func: Any, trigger: str, **kw: Any) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kw})

    def start(self) -> None:
        self.started += 1
        self.running = True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdowns.append(wait)
        self.running = False

    def reschedule_job(self, job_id: str, trigger: str, seconds: int) -> None:
        self.rescheduled.append((job_id, trigger, seconds))


class Intervals:
    """Stands in for SettingsRepo(conn).schedule_interval (system_schedule)."""

    values: dict[str, int | None] = {}
    error: Exception | None = None

    def __init__(self, conn: object) -> None:
        self.conn = conn

    def schedule_interval(self, job_kind: str) -> int | None:
        if Intervals.error is not None:
            raise Intervals.error
        return Intervals.values.get(job_kind)


@dataclass
class Calls:
    order: list[tuple[str, datetime]] = field(default_factory=list)
    fleets: list[Any] = field(default_factory=list)
    sweep_error: list[Exception] = field(default_factory=list)
    inventory_error: list[Exception] = field(default_factory=list)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    c = Calls()
    Intervals.values = {"inventory": 21_600, "offline_sweep": 60}
    Intervals.error = None
    monkeypatch.setattr(runner_mod, "SettingsRepo", Intervals)

    def run_inventory(jobs: Any, now: datetime) -> list[Any]:
        c.order.append(("inventory", now))
        if c.inventory_error:
            raise c.inventory_error.pop(0)
        return []

    def run_sweep(db: Any, now: datetime, stores: Callable[[Any], Any]) -> None:
        c.order.append(("sweep", now))
        if c.sweep_error:
            raise c.sweep_error.pop(0)
        with db.transaction() as tx:  # one sweep step's transaction
            stores(tx)

    class FakeFleet:
        def __init__(self, clock: Any) -> None:
            c.fleets.append(self)

        def run(
            self, db: Any, now: datetime, stores: Callable[[Any], Any]
        ) -> list[str]:
            c.order.append(("fleet", now))
            with db.transaction() as tx:
                stores(tx)
            return []

    monkeypatch.setattr(runner_mod, "run_inventory", run_inventory)
    monkeypatch.setattr(runner_mod, "run_sweep", run_sweep)
    monkeypatch.setattr(runner_mod, "FleetAlerts", FakeFleet)
    return c


class WallClock(Clock):
    """A real APScheduler compares next_run_time with the wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def make(
    scheduler: Any = None, clock: Clock | None = None
) -> tuple[SchedulerRunner, FakeDb, Clock, list[int]]:
    db, woken = FakeDb(), [0]
    clock = clock or Clock()

    def wake() -> None:
        woken[0] += 1

    db_any: Any = db
    return SchedulerRunner(db_any, clock, wake, scheduler), db, clock, woken


# ------------------------------------------------------------ CHK-M3-230


def test_start_adds_both_jobs_from_system_schedule_running_now(calls: Calls) -> None:
    """REQ-080 (1), (2), #67: intervals read from system_schedule; both jobs
    run at once (an inventory run at start-up) and are limited to one
    instance each; no other job (retention is M11)."""
    Intervals.values = {"inventory": 7_200, "offline_sweep": 90}
    fake = FakeScheduler()
    runner, _, clock, _ = make(fake)
    runner.start()
    assert fake.started == 1
    by_id = {j["id"]: j for j in fake.jobs}
    assert set(by_id) == {"inventory", "offline_sweep"}
    assert (by_id["inventory"]["seconds"], by_id["offline_sweep"]["seconds"]) == (
        7_200,
        90,
    )
    for job in by_id.values():
        assert job["trigger"] == "interval"
        assert job["max_instances"] == 1
        assert job["next_run_time"] == clock.now()
    assert by_id["inventory"]["func"] == runner.run_inventory
    assert by_id["offline_sweep"]["func"] == runner.run_sweep


def test_start_uses_the_seeded_intervals_when_the_database_is_unreadable(
    calls: Calls, caplog: pytest.LogCaptureFixture
) -> None:
    """TS §5.2 L832 seeds: 21,600 and 60 s; logged by type, no message."""
    Intervals.error = ConnectionError(f"db down {CANARY}")
    fake = FakeScheduler()
    runner, _, _, _ = make(fake)
    with caplog.at_level(logging.DEBUG):
        runner.start()
    by_id = {j["id"]: j["seconds"] for j in fake.jobs}
    assert by_id == {"inventory": 21_600, "offline_sweep": 60}
    assert fake.started == 1
    assert CANARY not in caplog.text
    recs = [r for r in caplog.records if r.name == "bitscan_manager.scheduler"]
    assert recs and all(getattr(r, "data", {}).get("exc_type") for r in recs)
    assert all(r.exc_info is None for r in recs)


# ------------------------------------------------------------ CHK-M3-231


@pytest.mark.parametrize("job", ["inventory", "offline_sweep"])
def test_a_failing_run_is_logged_by_type_and_the_next_run_happens(
    calls: Calls, caplog: pytest.LogCaptureFixture, job: str
) -> None:
    """REQ-080 (1): one record, job name and exception type only (no message,
    no traceback); the run does not raise into APScheduler; the next run
    happens and does its work."""
    runner, _, _, _ = make(FakeScheduler())
    run = runner.run_inventory if job == "inventory" else runner.run_sweep
    errors = calls.inventory_error if job == "inventory" else calls.sweep_error
    errors.append(ValueError(f"secret {CANARY}"))
    with caplog.at_level(logging.DEBUG):
        run()  # must not raise
        run()
    failed = [r for r in caplog.records if r.getMessage() == "scheduler run failed"]
    assert len(failed) == 1
    assert failed[0].data == {"job": job, "exc_type": "ValueError"}  # type: ignore[attr-defined]
    assert failed[0].exc_info is None and failed[0].levelno >= logging.ERROR
    assert CANARY not in caplog.text
    kind = "inventory" if job == "inventory" else "sweep"
    assert [n for n, _ in calls.order].count(kind) == 2
    if job == "offline_sweep":
        assert [n for n, _ in calls.order].count("fleet") == 1  # the good run


def test_sweep_then_fleet_alerts_with_one_now_and_one_fleet_instance(
    calls: Calls,
) -> None:
    """TASK-068 carry-over: FleetAlerts is built once per process (its windows
    persist) and runs after run_sweep, with the same now."""
    runner, _, clock, _ = make(FakeScheduler())
    runner.run_sweep()
    clock.at = NOW + timedelta(minutes=1)
    runner.run_sweep()
    assert calls.order == [
        ("sweep", NOW),
        ("fleet", NOW),
        ("sweep", NOW + timedelta(minutes=1)),
        ("fleet", NOW + timedelta(minutes=1)),
    ]
    assert len(calls.fleets) == 1


def test_every_job_transaction_wakes_the_shipper_on_commit(calls: Calls) -> None:
    """TASK-065 nit: audit entries the jobs write reach the sink promptly."""
    runner, db, _, woken = make(FakeScheduler())
    runner.run_inventory()
    assert woken[0] == 1
    runner.run_sweep()  # one sweep step, one fleet check (fakes), one re-read
    assert woken[0] == 3
    assert db.rollbacks == 0


# ------------------------------------------------------------ CHK-M3-234


def test_an_interval_change_restarts_the_inventory_timer(calls: Calls) -> None:
    """#67: each sweep re-reads the inventory interval; a change reschedules
    the job (restarting its timer); no change, no reschedule."""
    fake = FakeScheduler()
    runner, _, _, _ = make(fake)
    runner.start()
    runner.run_sweep()
    assert fake.rescheduled == []
    Intervals.values["inventory"] = 3_600
    runner.run_sweep()
    assert fake.rescheduled == [("inventory", "interval", 3_600)]
    runner.run_sweep()
    assert len(fake.rescheduled) == 1
    Intervals.values["inventory"] = 86_400
    runner.run_sweep()
    assert fake.rescheduled[-1] == ("inventory", "interval", 86_400)
    assert all(r[0] == "inventory" for r in fake.rescheduled)  # never the sweep


# ------------------------------------------------------------ CHK-M3-232/233
# A real APScheduler, fast intervals, fake work: concurrency and shutdown.


@dataclass
class Probe:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: dict[str, int] = field(default_factory=lambda: {"sweep": 0, "inventory": 0})
    peak: dict[str, int] = field(default_factory=lambda: {"sweep": 0, "inventory": 0})
    runs: dict[str, int] = field(default_factory=lambda: {"sweep": 0, "inventory": 0})
    ends: list[float] = field(default_factory=list)
    starts: list[float] = field(default_factory=list)

    def work(self, kind: str, seconds: float) -> None:
        with self.lock:
            self.active[kind] += 1
            self.runs[kind] += 1
            self.peak[kind] = max(self.peak[kind], self.active[kind])
            self.starts.append(time.monotonic())
        time.sleep(seconds)
        with self.lock:
            self.active[kind] -= 1
            self.ends.append(time.monotonic())


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch, calls: Calls) -> Probe:
    p = Probe()
    Intervals.values = {"inventory": 1, "offline_sweep": 1}
    monkeypatch.setattr(
        runner_mod, "run_inventory", lambda jobs, now: p.work("inventory", 1.6)
    )
    monkeypatch.setattr(
        runner_mod, "run_sweep", lambda db, now, stores: p.work("sweep", 1.6)
    )
    return p


def test_slow_runs_never_overlap_and_both_jobs_repeat(probe: Probe) -> None:
    """REQ-080 (2): runs longer than the interval never execute twice at once
    (max_instances 1); each job runs at start-up and repeatedly."""
    runner, _, _, _ = make(clock=WallClock())
    runner.start()
    try:
        time.sleep(6)
    finally:
        runner.stop()
    assert probe.peak == {"sweep": 1, "inventory": 1}, probe.peak
    assert probe.runs["sweep"] >= 2 and probe.runs["inventory"] >= 2, probe.runs


def test_stop_waits_for_a_running_job_and_nothing_runs_after(probe: Probe) -> None:
    """REQ-080 (3): stop() returns only after the running job ended, and no run
    starts afterwards (so none can start once serve closes the pool)."""
    runner, _, _, _ = make(clock=WallClock())
    runner.start()
    deadline = time.monotonic() + 10
    while not any(probe.active.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert any(probe.active.values())  # a run is in progress
    runner.stop()
    stopped = time.monotonic()
    assert not any(probe.active.values())
    assert max(probe.ends) <= stopped
    runs = dict(probe.runs)
    time.sleep(2.5)
    assert probe.runs == runs
    assert not [t for t in probe.starts if t > stopped]
    runner.stop()  # a second stop is harmless


@dataclass
class RefusingDb:
    """Every transaction waits `wait` seconds (the pool timeout) and then
    refuses, as PostgreSQL down does; records when each one began."""

    wait: float
    began: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        with self.lock:
            self.began.append(time.monotonic())
        time.sleep(self.wait)
        raise psycopg.OperationalError("refused")
        yield FakeTx()  # pragma: no cover - never reached


def test_stop_with_the_database_refusing_gives_up_at_the_next_step(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, caplog: pytest.LogCaptureFixture
) -> None:
    """TASK-071 r1 (lead ruling 2026-10-23, CHK-M3-233-db): a run waiting on an
    unavailable pool gives up at its next transaction once stop() was called;
    stop() still waits for the transaction in flight, then returns well before
    the run's remaining steps would have taken, and no transaction starts after
    stop() was called. Six sweep steps (each its own transaction, a failing
    step does not stop the next, as run_sweep does), the fleet check and the
    interval re-read would take 8 waits without the flag."""
    wait = 1.0

    def run_sweep(db: Any, now: datetime, stores: Callable[[Any], Any]) -> None:
        for _ in range(6):
            try:
                with db.transaction() as tx:
                    stores(tx)
            except psycopg.OperationalError:
                continue

    monkeypatch.setattr(runner_mod, "run_sweep", run_sweep)
    db = RefusingDb(wait)
    db_any: Any = db
    runner = SchedulerRunner(db_any, WallClock(), lambda: None)
    caplog.set_level(logging.ERROR, logger="bitscan_manager.scheduler")
    runner.start()  # reads both intervals: two waits, then the seeded values
    time.sleep(wait * 1.5)  # both runs are now waiting on a transaction
    assert len(db.began) >= 3
    called = time.monotonic()
    runner.stop()
    elapsed = time.monotonic() - called
    assert elapsed <= wait + 0.75, f"stop took {elapsed:.2f} s"
    assert not [t for t in db.began if t > called], "a transaction began after stop"
    seen = len(db.began)
    time.sleep(wait * 1.5)
    assert len(db.began) == seen  # nothing runs once stopped
    for rec in caplog.records:  # given-up runs: job and type only
        data = getattr(rec, "data", {})
        assert set(data) <= {"job", "exc_type"}, data
        assert "refused" not in rec.getMessage()


def test_stop_before_start_is_harmless(calls: Calls) -> None:
    fake = FakeScheduler()
    runner, _, _, _ = make(fake)
    runner.stop()
    assert fake.shutdowns == []
    runner.start()
    runner.stop()
    assert fake.shutdowns == [True]


def test_the_default_scheduler_is_a_background_scheduler(calls: Calls) -> None:
    runner, _, _, _ = make()
    assert isinstance(runner._scheduler, BackgroundScheduler)


# ------------------------------------------------------------ lifecycle order


@dataclass
class Recorder:
    events: list[str] = field(default_factory=list)

    def part(self, name: str, *methods: str) -> Any:
        rec = self

        class Part:
            def __getattr__(self, attr: str) -> Callable[[], None]:
                if attr not in methods:
                    raise AttributeError(attr)
                return lambda *a, **kw: rec.events.append(f"{name}.{attr}")

        return Part()


def test_serve_lifecycle_starts_the_scheduler_after_the_pool_and_stops_it_first() -> (
    None
):
    """REQ-080 (3), G27: the pool opens before the scheduler starts (it reads
    system_schedule); on SIGTERM the scheduler stops before anything else
    closes, in particular before the pool."""
    rec = Recorder()
    lifecycle = serve_mod.ServeLifecycle(
        rec.part("db", "open", "close"),
        rec.part("shipper", "start", "stop"),
        rec.part("flusher", "start", "stop"),
        rec.part("cipher", "close"),
        (None, Path("c"), Path("k")),  # type: ignore[arg-type]
        rec.part("scheduler", "start", "stop"),
    )

    async def cycle() -> None:
        await lifecycle.start()
        rec.events.append("--")
        await lifecycle.stop()

    asyncio.run(cycle())
    started, stopped = (
        rec.events[: rec.events.index("--")],
        rec.events[rec.events.index("--") + 1 :],
    )
    assert started.index("db.open") < started.index("scheduler.start")
    assert stopped[0] == "scheduler.stop"
    assert stopped.index("scheduler.stop") < stopped.index("db.close")
    assert stopped[-1] == "db.close"
    assert sorted(stopped) == sorted(
        ["scheduler.stop", "flusher.stop", "shipper.stop", "cipher.close", "db.close"]
    )


def test_build_runtime_wires_one_scheduler_runner() -> None:
    """serve's build_runtime gives the lifecycle a SchedulerRunner on the same
    pool and clock (read from the source: building it needs TLS and a sink)."""
    tree = ast.parse(Path(serve_mod.__file__).read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_runtime"
    )
    made = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "SchedulerRunner"
    ]
    assert len(made) == 1
    args = [a.id for a in made[0].args if isinstance(a, ast.Name)]
    assert args[:2] == ["db", "clock"]


# ------------------------------------------------------------ REQ-080 (5)

BANNED = {
    "httpx",
    "requests",
    "urllib.request",
    "http.client",
    "socket",
    "aiohttp",
    "ssl",
    "smtplib",
    "ftplib",
}


def test_the_scheduler_opens_no_network_connection() -> None:
    """REQ-080 (5), REQ-088 (3): no HTTP or raw-socket client in the runner
    (CHK-M3-305 covers the rest of services/scheduler at the gate)."""
    tree = ast.parse(RUNNER_FILE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {m for m in imported if m in BANNED or m.split(".")[0] in BANNED}
    assert "apscheduler.schedulers.background" in imported
