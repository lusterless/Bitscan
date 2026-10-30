"""TASK-071: the scheduler inside the real `bitscan-manager serve` on Linux
(TP-M3-25; G27; also run as the non-root user bstester).

Checks CHK-M3-230 to CHK-M3-234 of tests/m3/test-plan.md. Expected values:
REQ-080 (1)-(3), (5) (inventory run and offline_sweep inside serve, intervals
from system_schedule, at most one instance of each, a failing run logged by
error type only and the next run happens, SIGTERM exits 0 after the scheduler
stopped, no run after the pool closed), #67 (one inventory run at start-up;
an interval change through PATCH /settings restarts the timer within one
sweep), TS §3.3 L218 (status from heartbeat age, so a sweep is observable).

system_schedule's CHECKs refuse an offline_sweep interval under 60 s and an
inventory interval under 3,600 s, even as owner, so the plan's "2 s interval
set as owner" is not possible. The serve process is started through a small
launcher instead, which (test hook, as CHK-M3-231 allows) shortens the
intervals SchedulerRunner reads, wraps the sweep and inventory functions to
trace start and end (and to fail or be slow when asked), and traces the pool's
close. Everything else is the real serve: TLS, the real pool as bitscan_app,
the real sweep and inventory SQL.
"""

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import SystemClock
from bitscan_manager.services.scheduler.runner import SchedulerRunner

from . import test_users_api_pg as users_api
from .canary import new_canary
from .certs import Pki, make_pki
from .conftest import PgServer
from .fake_sink import https_sink, server_context
from .test_serve_linux import env_for, free_port, wait_ready
from .test_users_api_pg import Env

if not hasattr(signal, "SIGHUP"):
    pytest.skip("not run: Linux only (serve uses SIGHUP)", allow_module_level=True)

pytestmark = pytest.mark.pg

env = users_api.env  # the M2 users-API environment, for PATCH /settings

LAUNCHER = r"""
import json, os, pathlib, sys, threading, time
from bitscan_manager.db import pool
from bitscan_manager.services.scheduler import runner as r
from bitscan_manager.cli.serve import serve_main

hooks = json.loads(os.environ["T071_HOOKS"])
trace = open(hooks["trace"], "a", buffering=1)
lock = threading.Lock()


def note(text):
    with lock:
        trace.write(f"{time.monotonic():.4f} {text}\n")


real_interval = r.SchedulerRunner._interval


def interval(self, kind):
    value = real_interval(self, kind)  # the real system_schedule read
    return hooks.get(kind + "_s") or value


r.SchedulerRunner._interval = interval
counts = {"sweep": 0, "inventory": 0, "schedules": 0}


def wrap(kind, real):
    def run(*args, **kwargs):
        with lock:
            counts[kind] += 1
            n = counts[kind]
        note(f"start {kind} {n}")
        try:
            if n in hooks.get("fail_" + kind, []):
                raise ValueError(hooks["canary"])
            time.sleep(hooks.get("slow_" + kind + "_s", 0))
            return real(*args, **kwargs)
        finally:
            note(f"end {kind} {n}")

    return run


r.run_sweep = wrap("sweep", r.run_sweep)
r.run_inventory = wrap("inventory", r.run_inventory)
# M9 (REQ-225): the 30 s scan_schedules tick is traced too, so a run of it in
# flight at SIGTERM can be told apart from one that should not have failed.
r.run_due_schedules = wrap("schedules", r.run_due_schedules)
real_close = pool.AppDatabase.close


def close(self):
    note("pool closed")
    return real_close(self)


pool.AppDatabase.close = close
sys.exit(serve_main(os.environ, queue_dir=pathlib.Path(hooks["queue"])))
"""


@dataclass
class Traced:
    proc: subprocess.Popen[str]
    port: int
    ca: Path
    log: Path
    trace: Path

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")

    def events(self) -> list[tuple[float, str]]:
        if not self.trace.exists():
            return []
        out = []
        for line in self.trace.read_text(encoding="utf-8").splitlines():
            at, _, text = line.partition(" ")
            out.append((float(at), text))
        return out

    def runs(self, kind: str) -> dict[int, list[float]]:
        """Run number -> [start, end?] for kind."""
        out: dict[int, list[float]] = {}
        for at, text in self.events():
            parts = text.split()
            if len(parts) == 3 and parts[1] == kind:
                out.setdefault(int(parts[2]), []).append(at)
        return out

    def records(self) -> list[dict[str, Any]]:
        recs = []
        for line in self.output().splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
        return recs

    def stop(self, timeout: float = 30) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
            raise


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("sched-pki"))


@pytest.fixture
def sink(pki: Pki) -> Iterator[Any]:
    leaf = pki.leaf("sink-sched")
    with https_sink(server_context(leaf.cert, leaf.key)) as s:
        yield s


CANARY = new_canary("sched")


@pytest.fixture
def launch(migrated_db: PgServer, tmp_path: Path, pki: Pki, sink: Any) -> Iterator[Any]:
    started: list[Traced] = []

    def go(**hooks: Any) -> Traced:
        leaf = pki.leaf(f"sched-{secrets.token_hex(4)}")
        port = free_port()
        e = env_for(
            migrated_db, tmp_path, pki, leaf, f"https://localhost:{sink.port}/a", port
        )
        trace = tmp_path / f"trace-{len(started)}.txt"
        log = tmp_path / f"serve-{len(started)}.log"
        e["T071_HOOKS"] = json.dumps(
            {
                "trace": str(trace),
                "queue": str(tmp_path / f"queue-{len(started)}"),
                "canary": CANARY,
                **hooks,
            }
        )
        proc = subprocess.Popen(  # noqa: S603  # fixed argv, no untrusted input
            [sys.executable, "-c", LAUNCHER],
            env=e,
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        t = Traced(proc, port, pki.ca, log, trace)
        started.append(t)
        wait_ready(t)  # type: ignore[arg-type]  # same proc/port/ca/output shape
        return t

    yield go
    for t in started:
        if t.proc.poll() is None:
            t.stop()


def app_conn(server: PgServer) -> psycopg.Connection[Any]:
    return psycopg.connect(server.dsn("bitscan_app"), autocommit=True)


def plant_agent(server: PgServer, status: str, heartbeat_age: timedelta | None) -> UUID:
    now = datetime.now(UTC)
    with app_conn(server) as c:
        row = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, last_heartbeat_at,"
            " enrolled_at) VALUES (%s, %s, '1.0.0', %s, %s, %s, %s, %s, %s)"
            " RETURNING agent_id",
            (
                secrets.token_hex(16),
                f"s-{secrets.token_hex(3)}",
                token_hash(new_agent_token(AgentTokenKind.AGENT)),
                now - timedelta(days=1),
                now + timedelta(days=300),
                status,
                None if heartbeat_age is None else now - heartbeat_age,
                now - timedelta(days=1),
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def status_of(server: PgServer, agent_id: UUID) -> str:
    with app_conn(server) as c:
        row = c.execute(
            "SELECT status::text FROM agent WHERE agent_id = %s", (agent_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def jobs_of(server: PgServer, agent_id: UUID) -> list[tuple[Any, ...]]:
    with app_conn(server) as c:
        return c.execute(
            "SELECT kind, state::text, payload, pickup_by, created_at FROM scan_job"
            " WHERE agent_id = %s",
            (agent_id,),
        ).fetchall()


def until(check: Any, timeout: float = 20, step: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return bool(check())


def failures(t: Traced) -> list[dict[str, Any]]:
    return [r for r in t.records() if r.get("message") == "scheduler run failed"]


# ------------------------------------------------------------ CHK-M3-230


def test_serve_queues_inventory_at_startup_and_sweeps_repeatedly(
    launch: Any, migrated_db: PgServer
) -> None:
    """REQ-080 (1), #67, TS §3.3 L218: an inventory run at start-up queues one
    job for an eligible agent (none for a held one); the sweep runs at once and
    then again and again (each time marking a newly stale host offline)."""
    eligible = plant_agent(migrated_db, "enrolled", None)
    held = plant_agent(migrated_db, "awaiting_approval", None)
    old = plant_agent(migrated_db, "online", timedelta(minutes=31))
    t = launch(offline_sweep_s=1)  # inventory keeps its real (long) interval
    assert until(lambda: len(jobs_of(migrated_db, eligible)) == 1)
    ((kind, state, payload, pickup_by, created_at),) = jobs_of(migrated_db, eligible)
    assert (kind, state) == ("inventory", "queued")
    assert set(payload) == {"job_id", "agent_id", "kind", "pickup_by"}
    assert pickup_by - created_at == timedelta(hours=24)
    assert jobs_of(migrated_db, held) == []
    assert until(lambda: status_of(migrated_db, old) == "offline")
    later = plant_agent(migrated_db, "online", timedelta(minutes=31))
    assert until(lambda: status_of(migrated_db, later) == "offline", timeout=15)
    assert until(lambda: len(t.runs("sweep")) >= 4, timeout=15)
    assert len(t.runs("inventory")) == 1  # one run at start-up, then 6 h
    assert len(jobs_of(migrated_db, eligible)) == 1  # the open job blocks another
    assert failures(t) == []
    assert t.stop() == 0


# ------------------------------------------------------------ CHK-M3-231


def test_failing_runs_are_logged_by_type_and_the_next_run_happens(
    launch: Any, migrated_db: PgServer
) -> None:
    """REQ-080 (1): sweep runs 1 and 2 and inventory run 1 raise; each is
    logged as "scheduler run failed" with the job and the exception type only
    (the message, a canary, appears nowhere); later runs happen and work."""
    old = plant_agent(migrated_db, "online", timedelta(minutes=31))
    eligible = plant_agent(migrated_db, "enrolled", None)
    t = launch(
        offline_sweep_s=1,
        inventory_s=2,
        fail_sweep=[1, 2],
        fail_inventory=[1],
    )
    assert until(lambda: status_of(migrated_db, old) == "offline")  # run 3+ worked
    assert until(lambda: len(jobs_of(migrated_db, eligible)) == 1)  # inventory 2+
    assert until(lambda: len(failures(t)) >= 3)
    got = sorted((r["job"], r["exc_type"]) for r in failures(t))
    assert got == [
        ("inventory", "ValueError"),
        ("offline_sweep", "ValueError"),
        ("offline_sweep", "ValueError"),
    ]
    base = {"time", "level", "logger", "message", "request_id", "agent_id", "job_id"}
    for rec in failures(t):
        assert set(rec) - base == {"job", "exc_type"}, rec  # no message, no stack
        assert rec["level"].upper() in ("ERROR", "CRITICAL")
    assert t.stop() == 0
    out = t.output()
    assert CANARY not in out
    assert "Traceback" not in out


# ------------------------------------------------------------ CHK-M3-232


def overlaps(spans: dict[int, list[float]]) -> list[tuple[int, int]]:
    done = sorted((v[0], v[1], k) for k, v in spans.items() if len(v) == 2)
    return [(a[2], b[2]) for a, b in zip(done, done[1:], strict=False) if b[0] < a[1]]


def test_slow_runs_never_execute_twice_at_once(launch: Any) -> None:
    """REQ-080 (2): runs slower (2.5 s) than their interval (1 s) never
    overlap with another run of the same job; each job still repeats."""
    t = launch(offline_sweep_s=1, inventory_s=1, slow_sweep_s=2.5, slow_inventory_s=2.5)
    assert until(
        lambda: (
            sum(len(v) == 2 for v in t.runs("sweep").values()) >= 3
            and sum(len(v) == 2 for v in t.runs("inventory").values()) >= 3
        ),
        timeout=30,
    )
    signalled = time.monotonic()  # CLOCK_MONOTONIC is shared by processes
    assert t.stop() == 0
    # The job name a failure record carries -> its traced kind. M9 adds the
    # scan_schedules tick (REQ-225), which can be in flight at SIGTERM too
    # (CI, PR #17); each job's failures are compared with its own runs.
    traced = {
        "offline_sweep": "sweep",
        "inventory": "inventory",
        "scan_schedules": "schedules",
    }
    in_flight: dict[str, int] = {}
    for kind in traced.values():
        spans = t.runs(kind)
        assert overlaps(spans) == [], (kind, spans)
        open_runs = [k for k, v in spans.items() if len(v) != 2]
        assert open_runs == [], (kind, spans)  # stop waited for the last one
        in_flight[kind] = sum(v[0] < signalled < v[1] for v in spans.values())
    # TASK-071 r1 (lead ruling 2026-10-23), as in the G27 test below: a run
    # still in progress at SIGTERM gives up its later steps with
    # SchedulerStopping. Only such a run may log a failure; nothing else fails.
    got = failures(t)
    assert [r["exc_type"] for r in got] == ["SchedulerStopping"] * len(got), got
    for job, kind in traced.items():
        mine = [r for r in got if r.get("job") == job]
        assert len(mine) <= in_flight[kind], (job, got, in_flight)
    assert all(r.get("job") in traced for r in got), got


# ------------------------------------------------------------ CHK-M3-233 (G27)


def test_sigterm_waits_for_the_running_sweep_and_nothing_runs_after_close(
    launch: Any,
) -> None:
    """REQ-080 (3), G27: SIGTERM while a (3 s) sweep runs: serve waits for it
    to end, then closes the pool, exits 0; no run starts after the pool
    closed and no run fails because the pool was closed under it."""
    t = launch(offline_sweep_s=1, slow_sweep_s=3)

    def in_progress() -> int | None:
        spans = t.runs("sweep")
        live = [k for k, v in spans.items() if len(v) == 1 and k >= 2]
        return live[0] if live else None

    assert until(lambda: in_progress() is not None, timeout=20)
    run = in_progress()
    assert run is not None
    signalled = time.monotonic()  # CLOCK_MONOTONIC is shared by processes
    t.proc.send_signal(signal.SIGTERM)
    assert t.proc.wait(30) == 0, t.output()[-2000:]
    events = t.events()
    closed = [at for at, text in events if text == "pool closed"]
    assert len(closed) == 1
    end = t.runs("sweep")[run]
    assert len(end) == 2 and signalled < end[1] < closed[0]
    assert not [text for at, text in events if at > closed[0]]
    starts_after = [
        text for at, text in events if text.startswith("start") and at > signalled
    ]
    assert starts_after == []
    # TASK-071 r1 (lead ruling 2026-10-23): the stop flag is checked before each
    # step, so the running sweep's later steps (fleet checks, interval re-read)
    # give up after the signal; that is logged by job and type only. Nothing
    # else fails.
    for rec in failures(t):
        assert rec["exc_type"] == "SchedulerStopping", rec
        extra = set(rec) - {"time", "level", "logger", "message"}
        assert extra == {"request_id", "agent_id", "job_id", "job", "exc_type"}, rec
        # M9 (REQ-225; decisions "M9 builder rulings"): the scan_schedules tick
        # gives up the same way. Old → new: CHK-M3-233-r1's job set
        # (offline_sweep, inventory) → CHK-M9-219 (plus scan_schedules).
        assert rec["job"] in ("offline_sweep", "inventory", "scan_schedules"), rec
    assert "PoolClosed" not in t.output()


def test_serve_lifecycle_has_the_scheduler_wired(launch: Any) -> None:
    """build_runtime's SchedulerRunner is the one serve starts (the trace sees
    both jobs run without any other start-up)."""
    t = launch(offline_sweep_s=1)
    assert until(lambda: t.runs("sweep") and t.runs("inventory"))
    assert t.stop() == 0


# ------------------------------------------------------------ CHK-M3-234


def test_interval_change_through_patch_restarts_the_inventory_timer(
    env: Env, migrated_db: PgServer
) -> None:
    """#67: after PATCH /settings changes inventory_interval_s, the next sweep
    re-reads it and restarts the inventory timer (next run = that sweep +
    the new interval); a sweep with no change leaves the timer alone. A real
    SchedulerRunner on the real pool with a real BackgroundScheduler."""
    _, tok = env.admin()
    before = env.call("GET", tok, "/api/v1/settings").json()["inventory_interval_s"]
    new = 3_600 if before != 3_600 else 7_200
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=5)
    db.open()
    runner = SchedulerRunner(db, SystemClock(), lambda: None)
    try:
        runner.start()
        job = runner._scheduler.get_job("inventory")
        assert job.trigger.interval == timedelta(seconds=before)
        r = env.call(
            "PATCH", tok, "/api/v1/settings", json={"inventory_interval_s": new}
        )
        assert r.status_code == 200, r.text
        swept = datetime.now(UTC)
        runner.run_sweep()
        job = runner._scheduler.get_job("inventory")
        assert job.trigger.interval == timedelta(seconds=new)
        due = job.next_run_time - swept
        assert timedelta(seconds=new - 5) <= due <= timedelta(seconds=new + 5), due
        first_due = job.next_run_time
        runner.run_sweep()  # nothing changed: the timer is not restarted again
        assert runner._scheduler.get_job("inventory").next_run_time == first_due
    finally:
        runner.stop()
        env.call(
            "PATCH", tok, "/api/v1/settings", json={"inventory_interval_s": before}
        )
        db.close()


def test_the_runtime_lock_has_apscheduler_and_no_telemetry_exporter() -> None:
    """REQ-080 (4): the scheduler adds no OpenTelemetry SDK or exporter;
    APScheduler itself is in the hashed runtime lock (serve imports it)."""
    lock = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    )
    names = {
        line.split("==")[0].strip().lower()
        for line in lock.splitlines()
        if "==" in line and not line.startswith((" ", "#"))
    }
    assert "apscheduler" in names
    assert not {
        n
        for n in names
        if n == "opentelemetry-sdk"
        or n.startswith(("opentelemetry-exporter", "opentelemetry-instrumentation"))
    }
    assert os.environ.get("OTEL_SDK_DISABLED") in (None, "true", "false")


@pytest.mark.parametrize("down", ["wrong-password", "closed-port"])
def test_sigterm_with_the_database_refusing_exits_promptly(
    migrated_db: PgServer, tmp_path: Path, pki: Pki, sink: Any, down: str
) -> None:
    """REQ-080 (3) with M2 G27 (test_serve_linux: SIGTERM exits 0 within its
    15 s bound, also when PostgreSQL refuses the connection, as in
    test_refused_dsn_puts_no_dsn_content_on_stdout_or_stderr): waiting for a
    running scheduler job must not hold the stop while that job waits on the
    pool. TASK-071 r1 (lead ruling 2026-10-23): within the M2 bound; held here
    to CHK-M2-257's 10 s. The database refuses the login, or is down (nothing
    listens on the port). The elapsed time is measured and reported."""
    from .test_serve_linux import start

    bad = tmp_path / "refused.dsn"
    dsn = migrated_db.dsn("bitscan_app")
    if down == "wrong-password":
        bad.write_text(dsn.replace("password=", "password=wrong"))
    else:
        assert f"port={migrated_db.port}" in dsn
        bad.write_text(dsn.replace(f"port={migrated_db.port}", f"port={free_port()}"))
    leaf = pki.leaf(f"sched-refused-{secrets.token_hex(3)}")
    port = free_port()
    e = env_for(
        migrated_db,
        tmp_path,
        pki,
        leaf,
        f"https://localhost:{sink.port}/a",
        port,
        BITSCAN_DB_DSN_FILE=str(bad),
    )
    s = start(e, tmp_path, port, pki, leaf)
    try:
        wait_ready(s)
        time.sleep(2)  # the start-up inventory run and first sweep are under way
        began = time.monotonic()
        code = s.stop(timeout=180)
        elapsed = time.monotonic() - began
    finally:
        if s.proc.poll() is None:
            s.proc.kill()
    assert code == 0, s.output()[-2000:]
    out = s.output()
    assert "PoolClosed" not in out and "Traceback" not in out, out[-2000:]
    print(f"SIGTERM with the database {down}: {elapsed:.1f} s")
    assert elapsed <= 10, f"SIGTERM took {elapsed:.1f} s with the database {down}"
