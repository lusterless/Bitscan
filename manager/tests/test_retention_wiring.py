"""TASK-245 TEST: the retention job in SchedulerRunner, serve's build_runtime and
the shipper's cursor (TP-M11-13; CHK-M11-196, -197, -199, -450 to -453).

Expected values, from the spec and the criteria before the code was read:
TS §2.1 L103 (the scheduler runs retention), §5.2 L829-L835 (the seeded
`('retention', 86400)` row; interval_s 60 to 86,400), §5.3 L1051 (retention
connects only as bitscan_retention), §8.6 L1309 (BITSCAN_RETENTION_DSN_FILE);
REQ-277 (1)-(4): a fourth job `retention`, at most one at a time, first run
start + 10 min, then every interval_s of the row (86,400 when it cannot be
read), behind the same stop flag; a failing step logged by name and type, the
later steps and the next run still happen; stop() waits for a running run;
REQ-275 (2): every retention statement as bitscan_retention, never the app
pool; #150 (d), (h); the lead's rows (a)-(e) of the TASK-245 brief. Then bound
to the implementation's names (`retention_db=`, `shipped_through=`,
`RETENTION_DELAY`, `Shipper.shipped_through()`).

The serve process rows (a real `bitscan-manager serve`) are in
test_serve_retention_linux.py.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr, ValidationError

from bitscan_manager.api.user.settings import SettingsBody, SettingsPatch
from bitscan_manager.cli import serve as serve_mod
from bitscan_manager.config import load_serve_config
from bitscan_manager.config import startup as startup_mod
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import retention as rt
from bitscan_manager.runtime import SystemClock
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.shipper import PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import DeliveryError
from bitscan_manager.services.audit.verify import verify_chain
from bitscan_manager.services.retention import rules, task
from bitscan_manager.services.scheduler import runner as runner_mod
from bitscan_manager.services.scheduler.runner import (
    SchedulerRunner,
    SchedulerStopping,
)

from . import m11_pg_fixtures as m
from . import test_users_api_pg as users_api
from .canary import new_canary
from .certs import Pki, make_pki
from .conftest import PgServer, own_migrated_server
from .test_serve_linux import env_for, free_port
from .test_shipper import World, make_records
from .test_users_api_pg import Env

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
CANARY = new_canary("ret245")
FOUR = {"inventory", "offline_sweep", "scan_schedules", "retention"}
RUNNER_FILE = Path(runner_mod.__file__)
SERVE_FILE = Path(serve_mod.__file__)
STARTUP_FILE = Path(startup_mod.__file__)
REPO = Path(__file__).resolve().parents[2]

env = users_api.env  # the M2 users-API environment, for /settings


class Clock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


class WallClock(Clock):
    """A real APScheduler compares next_run_time with the wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeTx:
    conn: object = field(default_factory=object)
    hooks: list[Callable[[], None]] = field(default_factory=list)

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


@dataclass
class FakeDb:
    name: str
    opened: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        with self.lock:
            self.opened += 1
        tx = FakeTx(conn=self.name)
        yield tx
        for hook in tx.hooks:
            hook()

    def ping(self) -> bool:
        return True


@dataclass
class FakeScheduler:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    started: int = 0
    running: bool = False

    def add_job(self, func: Any, trigger: str, **kw: Any) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kw})

    def start(self) -> None:
        self.started += 1
        self.running = True

    def shutdown(self, wait: bool = True) -> None:
        self.running = False

    def by_id(self) -> dict[str, dict[str, Any]]:
        return {j["id"]: j for j in self.jobs}


class Intervals:
    """Stands in for SettingsRepo(conn).schedule_interval (system_schedule);
    records which pool each read ran on (FakeTx.conn is the pool's name)."""

    values: dict[str, int | None] = {}
    error: Exception | None = None
    reads: list[tuple[object, str]] = []

    def __init__(self, conn: object) -> None:
        self.conn = conn

    def schedule_interval(self, job_kind: str) -> int | None:
        Intervals.reads.append((self.conn, job_kind))
        if Intervals.error is not None:
            raise Intervals.error
        return Intervals.values.get(job_kind)


@pytest.fixture
def intervals(monkeypatch: pytest.MonkeyPatch) -> type[Intervals]:
    Intervals.values = {"inventory": 7_200, "offline_sweep": 90, "retention": 3_600}
    Intervals.error = None
    Intervals.reads = []
    monkeypatch.setattr(runner_mod, "SettingsRepo", Intervals)
    return Intervals


@dataclass
class RetentionCalls:
    calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)
    body: Callable[[Any], None] | None = None


@pytest.fixture
def retention_calls(monkeypatch: pytest.MonkeyPatch) -> RetentionCalls:
    rc = RetentionCalls()

    def run_retention(
        db: Any,
        now: datetime,
        *,
        shipped_through: Callable[[], int | None],
        wake: Callable[[], None] | None = None,
    ) -> list[task.StepResult]:
        rc.calls.append(
            {"db": db, "now": now, "shipped_through": shipped_through, "wake": wake}
        )
        if rc.errors:
            raise rc.errors.pop(0)
        if rc.body is not None:
            rc.body(db)
        return []

    monkeypatch.setattr(task, "run_retention", run_retention)
    return rc


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three M9 jobs do nothing (their own suites cover them)."""

    class Fleet:
        def __init__(self, clock: Any) -> None:
            pass

        def run(self, db: Any, now: datetime, stores: Any) -> list[str]:
            return []

    monkeypatch.setattr(runner_mod, "run_inventory", lambda jobs, now: [])
    monkeypatch.setattr(runner_mod, "run_sweep", lambda db, now, stores: None)
    monkeypatch.setattr(runner_mod, "run_due_schedules", lambda db, now, wake: None)
    monkeypatch.setattr(runner_mod, "FleetAlerts", Fleet)


def cursor_41() -> int | None:
    return 41


@dataclass
class Made:
    runner: SchedulerRunner
    app: FakeDb
    ret: FakeDb
    clock: Clock
    woken: list[int]


def make(
    scheduler: Any = None, clock: Clock | None = None, *, retention: bool = True
) -> Made:
    app, ret, woken = FakeDb("app"), FakeDb("retention"), [0]
    clock = clock or Clock()

    def wake() -> None:
        woken[0] += 1

    app_any: Any = app
    ret_any: Any = ret
    if retention:
        runner = SchedulerRunner(
            app_any,
            clock,
            wake,
            scheduler,
            retention_db=ret_any,
            shipped_through=cursor_41,
        )
    else:
        runner = SchedulerRunner(app_any, clock, wake, scheduler)
    return Made(runner, app, ret, clock, woken)


def failures(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        dict(getattr(r, "data", {}))
        for r in caplog.records
        if r.getMessage() == "scheduler run failed"
    ]


def step_records(caplog: pytest.LogCaptureFixture, msg: str) -> list[dict[str, Any]]:
    return [
        dict(getattr(r, "data", {}))
        for r in caplog.records
        if r.name == task.__name__ and r.getMessage() == msg
    ]


def until(check: Callable[[], bool], timeout: float = 15, step: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return check()


# ------------------------------------------------------------ CHK-M11-196


def test_four_jobs_and_retention_ten_minutes_after_start_on_its_row(
    intervals: type[Intervals],
) -> None:
    """REQ-277 (1), #150 (h): exactly four jobs; retention every interval_s of
    its row (3,600 here, not the seeded 86,400), at most one instance, first
    run start + 10 min while the other three run at start; the read is done
    once, at start-up, through the app pool (the retention pool is left for
    the retention run)."""
    fake = FakeScheduler()
    made = make(fake)
    made.runner.start()
    assert fake.started == 1
    assert len(fake.jobs) == 4
    by_id = fake.by_id()
    assert set(by_id) == FOUR
    ret = by_id["retention"]
    assert ret["func"] == made.runner.run_retention
    assert ret["trigger"] == "interval"
    assert ret["seconds"] == 3_600
    assert ret["max_instances"] == 1
    assert ret["coalesce"] is True
    assert ret["misfire_grace_time"] == 3_600
    assert ret["next_run_time"] == NOW + timedelta(minutes=10)
    for job_id in ("inventory", "offline_sweep", "scan_schedules"):
        assert by_id[job_id]["next_run_time"] == NOW
        assert by_id[job_id]["max_instances"] == 1
    assert (by_id["inventory"]["seconds"], by_id["offline_sweep"]["seconds"]) == (
        7_200,
        90,
    )
    assert by_id["scan_schedules"]["seconds"] == 30
    assert ("app", "retention") in intervals.reads
    assert [k for _, k in intervals.reads].count("retention") == 1
    assert made.ret.opened == 0


@pytest.mark.parametrize("value", [60, 43_200, 86_400])
def test_a_changed_retention_row_is_the_interval(
    intervals: type[Intervals], value: int
) -> None:
    """REQ-277 (1): the interval equals the row, at both ends of its CHECK
    (60 to 86,400, TS §5.2) and between them."""
    intervals.values["retention"] = value
    fake = FakeScheduler()
    make(fake).runner.start()
    ret = fake.by_id()["retention"]
    assert (ret["seconds"], ret["misfire_grace_time"]) == (value, value)
    assert ret["next_run_time"] == NOW + timedelta(minutes=10)


def test_a_missing_retention_row_gives_86400(intervals: type[Intervals]) -> None:
    """The row cannot be read (absent): the seeded 86,400 s; the other two
    intervals still come from their rows."""
    del intervals.values["retention"]
    fake = FakeScheduler()
    make(fake).runner.start()
    by_id = {j["id"]: j["seconds"] for j in fake.jobs}
    assert by_id == {
        "inventory": 7_200,
        "offline_sweep": 90,
        "scan_schedules": 30,
        "retention": 86_400,
    }


def test_an_unreadable_database_gives_86400_and_logs_the_type_only(
    intervals: type[Intervals], caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-277 (1): the read fails (database down at start-up): retention
    still scheduled, every 86,400 s, first at start + 10 min; logged by
    exception type, never its message."""
    intervals.error = ConnectionError(f"db down {CANARY}")
    fake = FakeScheduler()
    with caplog.at_level(logging.DEBUG):
        make(fake).runner.start()
    by_id = fake.by_id()
    assert set(by_id) == FOUR
    assert by_id["retention"]["seconds"] == 86_400
    assert by_id["retention"]["next_run_time"] == NOW + timedelta(minutes=10)
    assert CANARY not in caplog.text
    recs = [r for r in caplog.records if r.name == "bitscan_manager.scheduler"]
    assert recs and all(r.exc_info is None for r in recs)
    assert all(getattr(r, "data", {}) == {"exc_type": "ConnectionError"} for r in recs)


def test_the_real_scheduler_holds_the_retention_job(
    intervals: type[Intervals], quiet: None
) -> None:
    """The same four jobs in a real BackgroundScheduler (it accepts the job
    as built): interval = the row, next run = start + 10 min, one instance."""
    at = datetime.now(UTC).replace(microsecond=0)
    made = make(clock=Clock(at))
    made.runner.start()
    try:
        sched = made.runner._scheduler
        assert isinstance(sched, BackgroundScheduler)
        assert {j.id for j in sched.get_jobs()} == FOUR
        job = sched.get_job("retention")
        assert job.trigger.interval == timedelta(seconds=3_600)
        assert job.next_run_time == at + timedelta(minutes=10)
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.misfire_grace_time == 3_600
    finally:
        made.runner.stop()


def test_without_the_retention_pool_three_jobs_and_no_retention_read(
    intervals: type[Intervals],
) -> None:
    """PD-51: CHK-M9-218 is unchanged for a runner built without retention
    (the M9 suites): three jobs, and the retention row is not read."""
    fake = FakeScheduler()
    made = make(fake, retention=False)
    made.runner.start()
    assert set(fake.by_id()) == {"inventory", "offline_sweep", "scan_schedules"}
    assert "retention" not in [k for _, k in intervals.reads]


def test_unconfigured_run_retention_does_nothing(
    retention_calls: RetentionCalls,
) -> None:
    made = make(FakeScheduler(), retention=False)
    made.runner.run_retention()
    assert retention_calls.calls == []


# ------------------------------------------------------------ CHK-M11-452 (c)


@pytest.mark.parametrize("which", ["retention_db", "shipped_through"])
def test_one_retention_argument_without_the_other_raises(which: str) -> None:
    db: Any = FakeDb("x")
    kw: dict[str, Any] = (
        {"retention_db": db}
        if which == "retention_db"
        else {"shipped_through": cursor_41}
    )
    with pytest.raises(ValueError, match="together"):
        SchedulerRunner(db, Clock(), lambda: None, FakeScheduler(), **kw)


# ------------------------------------------------------------ CHK-M11-196 wiring


def test_run_retention_gets_the_retention_pool_the_clock_cursor_and_wake(
    intervals: type[Intervals], retention_calls: RetentionCalls
) -> None:
    """REQ-275 (2), #150 (d): the run gets the retention pool (its
    transactions open on that pool, never the app pool), the manager clock's
    now, the shipper's cursor function itself, and the shipper's wake."""
    made = make(FakeScheduler())

    def body(db: Any) -> None:
        with db.transaction():
            pass

    retention_calls.body = body
    made.clock.at = NOW + timedelta(hours=3)
    made.runner.run_retention()
    (call,) = retention_calls.calls
    assert (made.ret.opened, made.app.opened) == (1, 0)
    assert call["now"] == NOW + timedelta(hours=3)
    assert call["shipped_through"] is cursor_41
    assert call["wake"] is not None
    call["wake"]()
    assert made.woken[0] == 1


def test_a_failing_retention_run_is_logged_by_type_and_the_next_run_happens(
    retention_calls: RetentionCalls, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-277 (1), (4): a run that raises (outside a step, for example the
    clock check) does not raise into APScheduler; one record with the job name
    and the exception type only; the next run happens."""
    made = make(FakeScheduler())
    retention_calls.errors.append(ValueError(f"secret {CANARY}"))
    with caplog.at_level(logging.DEBUG):
        made.runner.run_retention()
        made.runner.run_retention()
    assert len(retention_calls.calls) == 2
    assert failures(caplog) == [{"job": "retention", "exc_type": "ValueError"}]
    rec = next(r for r in caplog.records if r.getMessage() == "scheduler run failed")
    assert rec.exc_info is None and rec.levelno >= logging.ERROR
    assert CANARY not in caplog.text


def test_slow_retention_runs_never_overlap(
    monkeypatch: pytest.MonkeyPatch,
    intervals: type[Intervals],
    retention_calls: RetentionCalls,
    quiet: None,
) -> None:
    """REQ-277: at most one retention run at a time, in a real scheduler, with
    a 1 s interval and 1.6 s runs (first run moved to start for the test)."""
    monkeypatch.setattr(runner_mod, "RETENTION_DELAY", timedelta(0))
    intervals.values["retention"] = 1
    lock = threading.Lock()
    state = {"active": 0, "peak": 0, "runs": 0}

    def body(db: Any) -> None:
        with lock:
            state["active"] += 1
            state["runs"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(1.6)
        with lock:
            state["active"] -= 1

    retention_calls.body = body
    made = make(clock=WallClock())
    made.runner.start()
    try:
        time.sleep(5.5)
    finally:
        made.runner.stop()
    assert state["peak"] == 1, state
    assert state["runs"] >= 2, state


# ------------------------------------------------------------ CHK-M11-197


def test_stop_during_a_retention_run_gives_up_at_its_next_transaction(
    monkeypatch: pytest.MonkeyPatch,
    intervals: type[Intervals],
    retention_calls: RetentionCalls,
    quiet: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-277 (2): stop() while a retention run is between two transactions:
    the next one raises SchedulerStopping before it reaches the retention
    pool, stop() waits for the run to end and returns, and nothing runs
    afterwards. The retention pool is behind the same stop flag."""
    monkeypatch.setattr(runner_mod, "RETENTION_DELAY", timedelta(0))
    in_run, proceed = threading.Event(), threading.Event()
    seen: list[str] = []
    ended: list[float] = []

    def body(db: Any) -> None:
        with db.transaction():
            pass  # the first chunk
        in_run.set()
        proceed.wait(10)
        try:
            with db.transaction():
                seen.append("second transaction opened")
        except SchedulerStopping:
            seen.append("SchedulerStopping")
            raise
        finally:
            ended.append(time.monotonic())

    retention_calls.body = body
    made = make(clock=WallClock())
    caplog.set_level(logging.ERROR, logger="bitscan_manager.scheduler")
    made.runner.start()
    assert in_run.wait(10)
    returned: list[float] = []

    def stop_now() -> None:
        made.runner.stop()
        returned.append(time.monotonic())

    stopper = threading.Thread(target=stop_now)
    stopper.start()
    # The flag is set at once; stop() then waits for the run (white box: the
    # flag itself, so the run can be released only after it is set).
    assert until(made.runner._stopping.is_set, timeout=5)
    time.sleep(0.2)
    assert returned == []  # stop() is waiting for the run
    proceed.set()
    stopper.join(10)
    assert not stopper.is_alive()
    assert seen == ["SchedulerStopping"]
    assert made.ret.opened == 1  # the second transaction never reached the pool
    assert ended and returned and ended[0] <= returned[0]
    assert failures(caplog) == [{"job": "retention", "exc_type": "SchedulerStopping"}]
    runs = len(retention_calls.calls)
    time.sleep(1.5)
    assert len(retention_calls.calls) == runs == 1


# ------------------------------------------------------------ lifecycle order


@dataclass
class Recorder:
    events: list[str] = field(default_factory=list)

    def part(self, name: str, *methods: str) -> Any:
        rec = self

        class Part:
            def __getattr__(self, attr: str) -> Callable[..., None]:
                if attr not in methods:
                    raise AttributeError(attr)
                return lambda *a, **kw: rec.events.append(f"{name}.{attr}")

        return Part()


def test_lifecycle_opens_the_retention_pool_after_the_app_pool_and_closes_it_after_the_scheduler() -> (  # noqa: E501
    None
):
    """REQ-277 (3), the lead's row (d): the retention pool opens after the app
    pool and before the scheduler starts; it closes straight after the
    scheduler stopped (no job can use it afterwards) and before the app pool,
    which closes last."""
    rec = Recorder()
    lifecycle = serve_mod.ServeLifecycle(
        rec.part("db", "open", "close"),
        rec.part("shipper", "start", "stop"),
        rec.part("flusher", "start", "stop"),
        rec.part("cipher", "close"),
        (None, Path("c"), Path("k")),  # type: ignore[arg-type]
        rec.part("scheduler", "start", "stop"),
        retention_db=rec.part("rdb", "open", "close"),
    )

    async def cycle() -> None:
        await lifecycle.start()
        rec.events.append("--")
        await lifecycle.stop()

    asyncio.run(cycle())
    cut = rec.events.index("--")
    started, stopped = rec.events[:cut], rec.events[cut + 1 :]
    assert started.index("db.open") < started.index("rdb.open")
    assert started.index("rdb.open") < started.index("scheduler.start")
    assert stopped[0] == "scheduler.stop"
    assert stopped[1] == "rdb.close"
    assert stopped[-1] == "db.close"
    assert stopped.count("rdb.close") == 1


# ------------------------------------------------------------ CHK-M11-450 (b)


def _build_runtime() -> ast.FunctionDef:
    tree = ast.parse(SERVE_FILE.read_text(encoding="utf-8"))
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_runtime"
    )


def _calls(fn: ast.AST, name: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == name
    ]


def test_build_runtime_always_gives_the_runner_the_retention_pool_and_cursor() -> None:
    """The lead's row (b): serve's wiring has no branch that could leave the
    job out: build_runtime has no if, conditional expression or try; its one
    SchedulerRunner gets retention_db (an AppDatabase on
    config.retention_dsn named bitscan_retention) and the shipper's
    shipped_through; the lifecycle gets the same pool to open and close."""
    fn = _build_runtime()
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.If | ast.IfExp | ast.Try)]
    (made,) = _calls(fn, "SchedulerRunner")
    kw = {k.arg: k.value for k in made.keywords}
    assert isinstance(kw["retention_db"], ast.Name)
    assert kw["retention_db"].id == "retention_db"
    st = kw["shipped_through"]
    assert isinstance(st, ast.Attribute) and st.attr == "shipped_through"
    assert isinstance(st.value, ast.Name) and st.value.id == "shipper"
    (pool,) = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "retention_db" for t in n.targets)
    ]
    assert isinstance(pool.value, ast.Call)
    assert ast.unparse(pool.value.func) == "AppDatabase"
    assert ast.unparse(pool.value.args[0]) == "bounded_dsn(config.retention_dsn)"
    pkw = {k.arg: ast.unparse(k.value) for k in pool.value.keywords}
    assert pkw["name"] == "'bitscan_retention'"
    (life,) = _calls(fn, "ServeLifecycle")
    lkw = {k.arg: ast.unparse(k.value) for k in life.keywords}
    assert lkw["retention_db"] == "retention_db"


def test_no_variable_toggles_the_retention_job() -> None:
    """The lead's row (b): the runner and serve read no environment of their
    own; the start-up configuration reads exactly the TS §8.6 variables (the
    retention one is its DSN file, never an on/off switch)."""
    for path in (RUNNER_FILE, SERVE_FILE):
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text, path.name
    assert "environ" not in RUNNER_FILE.read_text(encoding="utf-8")
    tree = ast.parse(STARTUP_FILE.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "load_serve_config"
    )
    names = {
        n.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.startswith("BITSCAN_")
    }
    assert names == {
        "BITSCAN_DB_DSN_FILE",
        "BITSCAN_RETENTION_DSN_FILE",
        "BITSCAN_VAULT_ADDR",
        "BITSCAN_TOTP_KEY_REF",
        "BITSCAN_VAULT_TOKEN_FILE",
        "BITSCAN_TLS_CERT_FILE",
        "BITSCAN_TLS_KEY_FILE",
        "BITSCAN_AUDIT_SINK",
        "BITSCAN_LISTEN",
        "BITSCAN_BITS_DIR",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"retention_interval_s": 60},
        {"retention_enabled": False},
        {"retention": "off"},
        {"scheduler_jobs": ["inventory"]},
    ],
)
def test_no_setting_toggles_the_retention_job(body: dict[str, Any]) -> None:
    """The lead's row (b): the settings model has no retention field and its
    patch refuses one (extra fields forbidden)."""
    assert not [f for f in SettingsBody.model_fields if "retention" in f]
    assert not [f for f in SettingsPatch.model_fields if "retention" in f]
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate(body)


def test_no_route_touches_retention_or_the_scheduler() -> None:
    """The lead's row (b): the exported API (G6 keeps it equal to the app)
    has no path or operation about retention or the scheduler's jobs."""
    text = (REPO / "manager" / "openapi.json").read_text(encoding="utf-8").lower()
    doc = json.loads(text)
    for path, ops in doc["paths"].items():
        assert "retention" not in path and "scheduler" not in path, path
        for op in ops.values():
            if isinstance(op, dict):
                assert "retention" not in str(op.get("operationId", "")), path


@pytest.mark.pg
def test_patch_settings_refuses_a_retention_field(env: Env) -> None:
    """The lead's row (b), through the API: GET /settings shows no retention
    key; PATCH with one is 400 invalid_request and changes nothing."""
    _, tok = env.admin()
    before = env.call("GET", tok, "/api/v1/settings")
    assert before.status_code == 200, before.text
    assert not [k for k in before.json() if "retention" in k]
    for body in ({"retention_interval_s": 60}, {"retention_enabled": False}):
        r = env.call("PATCH", tok, "/api/v1/settings", json=body)
        assert r.status_code == 400, r.text
        assert r.json()["type"].endswith("invalid_request"), r.text
    assert env.call("GET", tok, "/api/v1/settings").json() == before.json()


# ------------------------------------------------------------ CHK-M11-199 units


def test_shipped_through_is_none_before_anything_is_queued(w: World) -> None:
    """#150 (d): None on a fresh install, after an empty read, and while the
    database cannot be read."""
    assert w.shipper.shipped_through() is None
    w.shipper.run_once()
    assert w.shipper.shipped_through() is None
    w.tail.commit(make_records([1, 2]))
    w.tail.fail = True
    w.cycle(2)
    assert w.shipper.shipped_through() is None


def test_shipped_through_is_the_last_id_written_to_the_disk_queue(w: World) -> None:
    """Queued, not delivered: with the sink down the cursor is already 3;
    delivery does not move it; new entries move it to their last id."""
    w.sink.up = False
    w.tail.commit(make_records([1, 2, 3]))
    w.shipper.run_once()
    assert w.sink.received == []
    assert w.shipper.shipped_through() == 3
    w.sink.up = True
    w.cycle(2)
    assert [r.audit_id for r in w.sink.received] == [1, 2, 3]
    assert w.shipper.shipped_through() == 3
    w.tail.rows = make_records([1, 2, 3, 4, 5])
    w.cycle(1)
    assert w.shipper.shipped_through() == 5


def test_shipped_through_moves_one_batch_at_a_time(w: World) -> None:
    w.tail.commit(make_records(list(range(1, 601))))
    w.shipper.run_once()
    assert w.shipper.shipped_through() == 500
    w.cycle(2)
    assert w.shipper.shipped_through() == 600


def test_shipped_through_stays_when_the_disk_queue_refuses(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing written to the queue, so the cap does not move."""
    w.tail.commit(make_records([1, 2]))

    def full(self: DiskQueue, records: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(DiskQueue, "append", full)
    w.shipper.run_once()
    assert w.shipper.shipped_through() is None
    monkeypatch.undo()
    w.cycle(2)
    assert w.shipper.shipped_through() == 2


def test_shipped_through_after_a_restart_is_the_saved_cursor(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1, 2, 3]))
    w.shipper.run_once()
    w.restart()
    assert w.shipper.shipped_through() == 3  # before any cycle


def _folder(folder: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(folder.iterdir())
        if p.is_file()
    }


def test_shipped_through_is_read_only(w: World) -> None:
    """Calling it changes no state: the queue folder (state file and
    segments, bytes and times), the queue depth, the tail and sink calls, the
    gate and the wake are as before."""
    w.sink.up = False
    w.tail.commit(make_records([1, 2, 3]))
    w.shipper.run_once()
    before = (
        _folder(w.folder),
        w.shipper._queue.depth(),
        w.tail.reads,
        w.sink.sends,
        w.shipper.refusing(),
        w.shipper._wake.is_set(),
    )
    time.sleep(0.02)  # a write would get a later mtime
    assert [w.shipper.shipped_through() for _ in range(5)] == [3] * 5
    after = (
        _folder(w.folder),
        w.shipper._queue.depth(),
        w.tail.reads,
        w.sink.sends,
        w.shipper.refusing(),
        w.shipper._wake.is_set(),
    )
    assert after == before


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path / "audit-queue")


# ------------------------------------------------------------ PostgreSQL rows


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("retention-wiring")) as s:
        yield s


@pytest.fixture
def fresh(server: PgServer) -> PgServer:
    with m.owner(server) as c:
        c.execute(
            "TRUNCATE scan, scan_job, scan_result, scan_result_reeval,"
            " inventory_snapshot, enrollment_request, enrollment_token, user_token,"
            " package, agent_package, os_info, audit_log CASCADE"
        )
    return server


@pytest.fixture
def pools(fresh: PgServer) -> Iterator[tuple[AppDatabase, AppDatabase]]:
    app_db = AppDatabase(SecretStr(fresh.dsn("bitscan_app")), connect_timeout_s=5)
    app_db.open()
    try:
        with m.retention_database(fresh) as rdb:
            yield app_db, rdb
    finally:
        app_db.close()


def survivors(server: PgServer, w: m.AgedWorld) -> dict[str, set[str]]:
    with m.owner(server) as c:
        p = m.present(c, w)
    out: dict[str, set[str]] = {}
    for (rule, label), ok in p.items():
        out.setdefault(rule, set())
        if ok:
            out[rule].add(label)
    return out


def labels(w: m.AgedWorld) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for rule, label in w.rows:
        out.setdefault(rule, set()).add(label)
    return out


GONE = {
    "scan": {"past", "old"},
    "inventory_job": {"past", "old"},
    "snapshot": {"past", "old"},
    "request": {"past", "old"},
    "token": {"past", "old", "revoked_past"},
    "package": {"unreferenced", "unreferenced2"},
}


def old_audit_at(now: datetime) -> datetime:
    return rules.minus_years(now, 3) - timedelta(days=5)


@pytest.mark.pg
def test_the_retention_row_is_read_at_start_up_from_the_database(
    fresh: PgServer, pools: tuple[AppDatabase, AppDatabase]
) -> None:
    """REQ-277 (1) on PostgreSQL: the seeded row (86,400), a changed row
    (43,200) and a deleted row (86,400) give the retention interval."""
    app_db, rdb = pools
    got = []
    try:
        for change in (None, "UPDATE", "DELETE"):
            with m.owner(fresh) as c:
                if change == "UPDATE":
                    c.execute(
                        "UPDATE system_schedule SET interval_s = 43200"
                        " WHERE job_kind = 'retention'"
                    )
                elif change == "DELETE":
                    c.execute(
                        "DELETE FROM system_schedule WHERE job_kind = 'retention'"
                    )
            fake = FakeScheduler()
            SchedulerRunner(
                app_db,
                Clock(),
                lambda: None,
                fake,
                retention_db=rdb,
                shipped_through=m.shipped(None),
            ).start()
            got.append(fake.by_id()["retention"]["seconds"])
    finally:
        with m.owner(fresh) as c:
            c.execute(
                "INSERT INTO system_schedule (job_kind, interval_s)"
                " VALUES ('retention', 86400) ON CONFLICT (job_kind)"
                " DO UPDATE SET interval_s = 86400"
            )
    assert got == [86_400, 43_200, 86_400]


@pytest.mark.pg
def test_a_failing_step_leaves_the_later_steps_run_through_the_runner(
    fresh: PgServer,
    pools: tuple[AppDatabase, AppDatabase],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-277 (1), (4): the snapshots step raises; it is logged by name and
    exception type, its rows stay, and every later step still deletes; the
    run itself does not fail."""
    app_db, rdb = pools
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())

    def boom(conn: Any, cutoff: datetime, limit: int) -> int:
        raise RuntimeError(f"step fault {CANARY}")

    monkeypatch.setattr(rt, "delete_snapshots", boom)
    caplog.set_level(logging.INFO)
    runner = SchedulerRunner(
        app_db,
        Clock(w.now),
        lambda: None,
        FakeScheduler(),
        retention_db=rdb,
        shipped_through=m.shipped(None),
    )
    runner.run_retention()
    left = survivors(fresh, w)
    want = {
        r: labs if r == "snapshot" else labs - GONE.get(r, set())
        for r, labs in labels(w).items()
    }
    assert left == want
    assert step_records(caplog, "retention step failed") == [
        {"step": "snapshots", "exc_type": "RuntimeError"}
    ]
    done = {d["step"]: d for d in step_records(caplog, "retention step done")}
    assert [done[s]["deleted"] for s in ("requests", "tokens", "packages")] == [2, 3, 2]
    assert failures(caplog) == []
    assert CANARY not in caplog.text


@pytest.mark.pg
def test_every_statement_of_a_runner_run_is_bitscan_retention(
    fresh: PgServer,
    pools: tuple[AppDatabase, AppDatabase],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-275 (2), CHK-M11-342: a statement spy over a whole run through the
    runner sees only bitscan_retention connections (the app pool is never
    used by retention), and the run deleted the expired rows."""
    app_db, rdb = pools
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())
    ids = m.audit_chain(fresh, [old_audit_at(w.now)] * 3)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    SchedulerRunner(
        app_db,
        Clock(w.now),
        lambda: None,
        FakeScheduler(),
        retention_db=rdb,
        shipped_through=m.shipped(ids[-1]),
    ).run_retention()
    assert len(spy.statements) > 10
    assert set(spy.roles) == {"bitscan_retention"}
    with m.owner(fresh) as c:
        assert not set(ids) & set(m.audit_ids(c))
    assert "old" not in survivors(fresh, w)["scan"]


@dataclass
class DownSink:
    sends: int = 0

    def send(self, records: Any) -> None:
        self.sends += 1
        raise DeliveryError("ConnectionRefusedError", 0)

    def close(self) -> None:
        pass


class NoOutageAudit:
    def unreachable(self) -> None:
        pass

    def recovered(self) -> None:
        pass


@pytest.mark.pg
def test_the_shippers_cursor_caps_the_audit_delete(
    fresh: PgServer, pools: tuple[AppDatabase, AppDatabase], tmp_path: Path
) -> None:
    """CHK-M11-199, #150 (d), REQ-276 (5) through the real shipper and the
    runner: expired entries above the shipper's cursor stay until the shipper
    has queued them; the checkpoint names the cursor; the chain verifies."""
    app_db, rdb = pools
    clock = Clock(m.now_utc())
    first = m.audit_chain(fresh, [old_audit_at(clock.at)] * 3)
    shipper = Shipper(
        PgAuditTail(app_db),
        DiskQueue(tmp_path / "q"),
        DownSink(),
        clock,
        NoOutageAudit(),
    )
    shipper.run_once()
    assert shipper.shipped_through() == first[-1]
    later = m.audit_chain(fresh, [old_audit_at(clock.at)] * 2)  # above the cursor
    runner = SchedulerRunner(
        app_db,
        clock,
        shipper.wake,
        FakeScheduler(),
        retention_db=rdb,
        shipped_through=shipper.shipped_through,
    )
    runner.run_retention()
    with m.owner(fresh) as c:
        left = m.audit_ids(c)
        (cp1,) = m.checkpoints(c)
    assert left[:2] == later and len(left) == 3
    assert cp1["detail"]["last_deleted_id"] == first[-1]
    assert cp1["detail"]["deleted"] == 3
    shipper.run_once()  # queues the later entries and the checkpoint
    assert shipper.shipped_through() == cp1["audit_id"]
    runner.run_retention()
    with m.owner(fresh) as c:
        cps = m.checkpoints(c)
        assert m.audit_ids(c) == [cp["audit_id"] for cp in cps]
        assert verify_chain(c).ok
    assert cps[1]["detail"]["last_deleted_id"] == later[-1]


@pytest.mark.pg
def test_stop_during_a_real_retention_run_gives_up_at_the_next_transaction(
    fresh: PgServer,
    pools: tuple[AppDatabase, AppDatabase],
    monkeypatch: pytest.MonkeyPatch,
    quiet: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CHK-M11-197 on PostgreSQL with the real scheduler and run_retention:
    stop() while the scans step's first chunk is in flight; that chunk
    commits, every later transaction gives up (SchedulerStopping, logged once
    per step by name and type), no statement runs on the retention pool
    afterwards, and stop() returns. When that first chunk is full (the aged
    world's two expired scans fill a chunk of rules.SCAN_CHUNK = 2, TASK-261
    r1), the scans step asks for another chunk and gives up there too."""
    app_db, rdb = pools
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())
    monkeypatch.setattr(runner_mod, "RETENTION_DELAY", timedelta(0))
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    real = rt.delete_scans
    in_run = threading.Event()
    mark: list[int] = []
    runner = SchedulerRunner(
        app_db,
        Clock(w.now),
        lambda: None,
        retention_db=rdb,
        shipped_through=m.shipped(None),
    )

    def delete_scans(conn: Any, ids: Any) -> int:
        n = real(conn, ids)
        if not in_run.is_set():
            in_run.set()
            until(runner._stopping.is_set, timeout=15)
            mark.append(len(spy.statements))
        return n

    monkeypatch.setattr(rt, "delete_scans", delete_scans)
    caplog.set_level(logging.INFO)
    runner.start()
    assert in_run.wait(20)
    began = time.monotonic()
    runner.stop()
    elapsed = time.monotonic() - began
    assert elapsed < 10, elapsed
    assert mark
    assert [r for r in spy.roles[mark[0] :] if r == "bitscan_retention"] == []
    later = ("inventory_jobs", "snapshots", "requests", "tokens", "audit", "packages")
    # PD-51 (TASK-261 r1): a full first chunk makes the scans step ask for one
    # more transaction, which the stop flag refuses.
    full = len(GONE["scan"]) >= rules.SCAN_CHUNK
    stopped = ("scans", *later) if full else later
    assert step_records(caplog, "retention step failed") == [
        {"step": s, "exc_type": "SchedulerStopping"} for s in stopped
    ]
    done = {d["step"]: d for d in step_records(caplog, "retention step done")}
    assert done["scans"]["deleted"] == 2
    assert done["scans"]["skipped"] == ("failed" if full else None)
    left = survivors(fresh, w)
    want = {
        r: labs - GONE["scan"] if r == "scan" else labs for r, labs in labels(w).items()
    }
    assert left == want
    assert [f for f in failures(caplog) if f.get("job") == "retention"] == []


# ------------------------------------------------------------ CHK-M11-451 (d)


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("wiring-pki"))


@pytest.mark.pg
def test_serve_build_runtime_runs_retention_on_a_bitscan_retention_pool(
    fresh: PgServer, pki: Pki, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lead's rows (d), CHK-M11-342, CHK-M11-199 (the cap is the
    shipper's): serve's own build_runtime gives the runner a pool named
    bitscan_retention (0 to 1 connections, from BITSCAN_RETENTION_DSN_FILE),
    separate from the app pool and the one the lifecycle opens and closes;
    the runner's cursor is the runtime shipper's shipped_through; a run
    through that runner logs in as bitscan_retention for every statement."""
    leaf = pki.leaf("wiring")
    e = env_for(fresh, tmp_path, pki, leaf, "https://localhost:1/a", free_port())
    config = load_serve_config(e)
    tls = serve_mod.make_tls_context(leaf.cert, leaf.key)
    runtime = serve_mod.build_runtime(config, tls, tmp_path / "queue")
    lifecycle = runtime.lifecycle
    assert isinstance(lifecycle, serve_mod.ServeLifecycle)
    runner = lifecycle._scheduler
    assert isinstance(runner, SchedulerRunner)
    ret = lifecycle._retention_db
    app_db = runtime.db
    assert ret is not None and app_db is not None
    assert isinstance(ret, AppDatabase) and isinstance(app_db, AppDatabase)
    assert ret is not app_db
    assert ret._pool.name == "bitscan_retention"
    assert (ret._pool.min_size, ret._pool.max_size) == (0, 1)
    assert conninfo_to_dict(ret._dsn.get_secret_value())["user"] == "bitscan_retention"
    assert runner._retention_db is not None
    inner_ret: object = getattr(runner._retention_db, "_db", None)
    inner_app: object = getattr(runner._db, "_db", None)
    assert inner_ret is ret and inner_app is app_db
    shipper = runtime.sink_gate
    assert isinstance(shipper, Shipper)
    assert runner._shipped_through == shipper.shipped_through
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())
    app_db.open()
    ret.open()
    try:
        with ret.transaction() as tx:
            row = tx.conn.execute("SELECT current_user::text").fetchone()
        assert row == ("bitscan_retention",)
        spy = m.RoleSpy()
        spy.install(monkeypatch)
        runner.run_retention()
        monkeypatch.undo()
        assert len(spy.statements) > 10
        assert set(spy.roles) == {"bitscan_retention"}
    finally:
        ret.close()
        app_db.close()
    left = survivors(fresh, w)
    for rule in ("scan", "inventory_job", "snapshot", "request", "token"):
        assert "old" not in left[rule], rule
        assert "inside" in left[rule], rule
    assert isinstance(runtime.clock, SystemClock)
