"""TASK-245 TEST: retention inside the real `bitscan-manager serve` on Linux
(TP-M11-13; CHK-M11-196, -197, -198, -453, -454).

Expected values: TS §2.1 L103, §5.2 L829-L835, §5.3 L1051, §8.6 L1309;
REQ-277 (1)-(4); REQ-275 (2); the lead's rows (a)-(e) of the TASK-245 brief:
the started scheduler has exactly the four jobs `inventory`, `offline_sweep`,
`scan_schedules` and `retention`; retention first runs start + 10 min, then
every interval_s of its row; no variable can drop it; serve opens a pool named
bitscan_retention from BITSCAN_RETENTION_DSN_FILE after the app pool and
closes it straight after the scheduler stopped (so two "pool closed" events,
retention then app, PD-51); a missing file still fails start-up with the M2
message and no DSN content.

The process is the real serve, started through a launcher that (test hook)
traces the job set after start(), the pool opens and closes by pool name, the
scheduler stop, and each retention run (start, end, its step results, and on
request the login role of a transaction on the pool it was given); it can
also move the first retention run to a few seconds after start and slow a
run down. Everything else is real: TLS, both pools, the shipper, the
retention SQL as bitscan_retention.
"""

from __future__ import annotations

import json
import secrets
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bitscan_manager.services.retention import rules

from . import m11_pg_fixtures as m
from .canary import new_canary, sweep
from .certs import Pki, make_pki
from .conftest import PgServer, own_migrated_server
from .fake_sink import https_sink, server_context
from .test_serve_linux import env_for, free_port, start, wait_ready

if not hasattr(signal, "SIGHUP"):
    pytest.skip("not run: Linux only (serve uses SIGHUP)", allow_module_level=True)

pytestmark = pytest.mark.pg

FOUR = {"inventory", "offline_sweep", "scan_schedules", "retention"}
CANARY = new_canary("srvret")
RETENTION_LOGGER = "bitscan_manager.services.retention.task"
RETENTION_MESSAGES = {
    "retention step done",
    "retention step failed",
    "retention refused: clock_doubt",
}
BASE = {"time", "level", "logger", "message", "request_id", "agent_id", "job_id"}

LAUNCHER = r"""
import json, os, pathlib, sys, threading, time
from datetime import timedelta
from bitscan_manager.db import pool
from bitscan_manager.services.scheduler import runner as r
from bitscan_manager.cli.serve import serve_main

hooks = json.loads(os.environ["T245_HOOKS"])
trace = open(hooks["trace"], "a", buffering=1)
lock = threading.Lock()


def note(text):
    with lock:
        trace.write(f"{time.monotonic():.4f} {text}\n")


if "retention_delay_s" in hooks:
    r.RETENTION_DELAY = timedelta(seconds=hooks["retention_delay_s"])

real_start = r.SchedulerRunner.start


def start(self):
    t0 = self._clock.now()
    real_start(self)
    jobs = [
        {
            "id": j.id,
            "interval_s": j.trigger.interval.total_seconds(),
            "max_instances": j.max_instances,
            "coalesce": j.coalesce,
            "misfire_s": j.misfire_grace_time,
            "offset_s": (j.next_run_time - t0).total_seconds(),
        }
        for j in self._scheduler.get_jobs()
    ]
    note("jobs " + json.dumps(jobs))


r.SchedulerRunner.start = start
real_run = r.retention_task.run_retention
runs = {"n": 0}


def run_retention(db, now, **kw):
    with lock:
        runs["n"] += 1
        n = runs["n"]
    note(f"start retention {n}")
    try:
        inner = getattr(db, "_db", None)
        note(f"retention pool {getattr(getattr(inner, '_pool', None), 'name', None)}")
        time.sleep(hooks.get("slow_retention_s", 0))
        if hooks.get("whoami"):
            with db.transaction() as tx:
                user = tx.conn.execute("SELECT current_user::text").fetchone()[0]
            note(f"retention user {user}")
        out = real_run(db, now, **kw)
        steps = [[s.step, s.deleted, s.skipped] for s in out]
        note("retention result " + json.dumps(steps))
        return out
    finally:
        note(f"end retention {n}")


r.retention_task.run_retention = run_retention
real_open, real_close = pool.AppDatabase.open, pool.AppDatabase.close


def open_(self):
    note(f"pool opened {self._pool.name}")
    return real_open(self)


def close(self):
    note(f"pool closed {self._pool.name}")
    return real_close(self)


pool.AppDatabase.open = open_
pool.AppDatabase.close = close
real_stop = r.SchedulerRunner.stop


def stop(self):
    note("scheduler stopping")
    real_stop(self)
    note("scheduler stopped")


r.SchedulerRunner.stop = stop
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

    def texts(self, prefix: str) -> list[str]:
        return [t[len(prefix) :] for _, t in self.events() if t.startswith(prefix)]

    def at(self, text: str) -> list[float]:
        return [a for a, t in self.events() if t == text]

    def jobs(self) -> list[dict[str, Any]]:
        (line,) = self.texts("jobs ")
        out: list[dict[str, Any]] = json.loads(line)
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
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("serve-retention")) as s:
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


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("ret-pki"))


@pytest.fixture
def sink(pki: Pki) -> Iterator[Any]:
    leaf = pki.leaf("sink-ret")
    with https_sink(server_context(leaf.cert, leaf.key)) as s:
        yield s


@pytest.fixture
def launch(
    fresh: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> Iterator[Callable[..., Traced]]:
    started: list[Traced] = []

    def go(extra_env: dict[str, str] | None = None, **hooks: Any) -> Traced:
        leaf = pki.leaf(f"ret-{secrets.token_hex(4)}")
        port = free_port()
        e = env_for(
            fresh, tmp_path, pki, leaf, f"https://localhost:{sink.port}/a", port
        )
        e.update(extra_env or {})
        n = len(started)
        trace = tmp_path / f"trace-{n}.txt"
        log = tmp_path / f"serve-{n}.log"
        e["T245_HOOKS"] = json.dumps(
            {"trace": str(trace), "queue": str(tmp_path / f"queue-{n}"), **hooks}
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


def until(check: Callable[[], Any], timeout: float = 30, step: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return bool(check())


def failures(t: Traced) -> list[dict[str, Any]]:
    return [r for r in t.records() if r.get("message") == "scheduler run failed"]


def retention_sessions(server: PgServer) -> int:
    with m.owner(server) as c:
        row = c.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE usename = 'bitscan_retention'"
        ).fetchone()
    assert row is not None
    return int(row[0])


def assert_pool_order(t: Traced) -> None:
    """Opened: app, then retention (both before the job set is traced).
    Closed (PD-51): retention, then app, both after the scheduler stopped;
    nothing is traced after the last. Compared by trace order (one writer,
    lines appended under a lock), as two lines can share a timestamp."""
    texts = [x for _, x in t.events()]
    opened = [i for i, x in enumerate(texts) if x.startswith("pool opened ")]
    assert [texts[i] for i in opened] == [
        "pool opened bitscan_app",
        "pool opened bitscan_retention",
    ]
    jobs_at = [i for i, x in enumerate(texts) if x.startswith("jobs ")]
    assert len(jobs_at) == 1 and opened[-1] < jobs_at[0]
    closed = [i for i, x in enumerate(texts) if x.startswith("pool closed ")]
    assert [texts[i] for i in closed] == [
        "pool closed bitscan_retention",
        "pool closed bitscan_app",
    ]
    assert texts.count("scheduler stopping") == 1
    assert texts.count("scheduler stopped") == 1
    stopping = texts.index("scheduler stopping")
    stopped = texts.index("scheduler stopped")
    assert stopping < stopped < closed[0] < closed[1]
    assert closed[1] == len(texts) - 1  # nothing after the last close


# ------------------------------------------------------------ CHK-M11-196 (a), (b)


@pytest.mark.parametrize(
    "extra_env",
    [
        {},
        {
            "BITSCAN_RETENTION_DISABLED": "1",
            "BITSCAN_RETENTION": "off",
            "BITSCAN_RETENTION_INTERVAL_S": "60",
            "BITSCAN_SCHEDULER_JOBS": "inventory,offline_sweep,scan_schedules",
        },
    ],
    ids=["plain", "toggles"],
)
def test_serve_schedules_four_jobs_with_retention_from_its_row(
    launch: Callable[..., Traced], fresh: PgServer, extra_env: dict[str, str]
) -> None:
    """The lead's rows (a), (b), (e) through the real serve: exactly the four
    jobs, each at most one instance; retention every interval_s of the row
    (changed to 43,200 as owner before start-up), first run start + 10 min, so
    it does not run during the test; made-up environment switches change
    nothing; the pools open app first and close retention first (PD-51)."""
    with m.owner(fresh) as c:
        c.execute(
            "UPDATE system_schedule SET interval_s = 43200 WHERE job_kind = 'retention'"
        )
    try:
        t = launch(extra_env)
        jobs = {j["id"]: j for j in t.jobs()}
        assert len(t.jobs()) == 4 and set(jobs) == FOUR
        ret = jobs["retention"]
        assert ret["interval_s"] == 43_200 and ret["misfire_s"] == 43_200
        assert ret["max_instances"] == 1 and ret["coalesce"] is True
        assert 600 <= ret["offset_s"] <= 630, ret
        assert all(j["max_instances"] == 1 for j in jobs.values())
        time.sleep(2)
        assert t.stop() == 0, t.output()[-2000:]
    finally:
        with m.owner(fresh) as c:
            c.execute(
                "UPDATE system_schedule SET interval_s = 86400"
                " WHERE job_kind = 'retention'"
            )
    assert t.texts("start retention") == []
    assert_pool_order(t)
    assert [r for r in failures(t) if r.get("job") == "retention"] == []


# ------------------------------------------------------------ CHK-M11-198 (d)


def test_serve_runs_retention_as_bitscan_retention(
    launch: Callable[..., Traced], fresh: PgServer
) -> None:
    """REQ-275 (2), REQ-277 (3), (4), the lead's row (d): serve's retention
    run gets the pool named bitscan_retention and logs in as
    bitscan_retention (the run's own transaction and the database's view of
    the session); it deletes the expired rows and keeps the younger ones; the
    audit prefix goes up to the shipper's cursor with a checkpoint; its log
    lines carry step names, counts and exception types only, and no row
    content. The pool's session ends when serve stops."""
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())
    old = m.audit_chain(fresh, [rules.minus_years(w.now, 3) - timedelta(days=5)] * 3)
    assert until(lambda: retention_sessions(fresh) == 0, timeout=15)
    t = launch(retention_delay_s=6, whoami=True)
    assert until(lambda: t.texts("end retention 1"), timeout=90), t.output()[-2000:]
    assert t.texts("retention pool ") == ["bitscan_retention"]
    assert t.texts("retention user ") == ["bitscan_retention"]
    (result,) = t.texts("retention result ")
    steps = {s: (deleted, skipped) for s, deleted, skipped in json.loads(result)}
    assert [skipped for _, skipped in steps.values()] == [None] * 7, steps
    assert retention_sessions(fresh) >= 1
    with m.owner(fresh) as c:
        p = m.present(c, w)
        ids = m.audit_ids(c)
        cps = m.checkpoints(c)
    for rule in ("scan", "inventory_job", "snapshot", "request", "token"):
        assert not p[(rule, "old")] and p[(rule, "inside")], rule
    assert not p[("package", "unreferenced")] and p[("package", "referenced")]
    assert not set(old) & set(ids)
    assert [cp["detail"]["last_deleted_id"] for cp in cps] == [old[-1]]
    assert t.stop() == 0, t.output()[-2000:]
    assert_pool_order(t)
    assert until(lambda: retention_sessions(fresh) == 0, timeout=15)
    recs = [r for r in t.records() if r.get("logger") == RETENTION_LOGGER]
    assert len(recs) == 7
    for rec in recs:
        assert rec["message"] in RETENTION_MESSAGES, rec
        assert set(rec) - BASE <= {"step", "deleted", "chunks", "skipped", "exc_type"}
    out = t.output()
    assert m.hits([out]) == []
    assert "Traceback" not in out


# ------------------------------------------------------------ CHK-M11-197 (serve)


def test_sigterm_during_a_retention_run_waits_then_closes_the_retention_pool(
    launch: Callable[..., Traced],
) -> None:
    """REQ-277 (2): SIGTERM while a retention run is in progress: the run's
    next transaction raises SchedulerStopping (logged once, job and type
    only), serve waits for the run to end, then closes the retention pool and
    then the app pool, and exits 0; no run starts after the signal."""
    t = launch(retention_delay_s=1, slow_retention_s=4)
    assert until(lambda: t.texts("start retention 1"), timeout=30)
    signalled = time.monotonic()
    t.proc.send_signal(signal.SIGTERM)
    assert t.proc.wait(30) == 0, t.output()[-2000:]
    (end,) = t.at("end retention 1")
    (closed_ret,) = t.at("pool closed bitscan_retention")
    assert signalled < end < closed_ret
    assert_pool_order(t)
    mine = [r for r in failures(t) if r.get("job") == "retention"]
    assert [r["exc_type"] for r in mine] == ["SchedulerStopping"], mine
    assert all(set(r) - BASE == {"job", "exc_type"} for r in mine), mine
    assert t.texts("retention result ") == []  # it gave up before any step
    assert not [x for a, x in t.events() if x.startswith("start ") and a > signalled]
    assert "PoolClosed" not in t.output()


# ------------------------------------------------------------ CHK-M11-198 (start-up)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "BITSCAN_RETENTION_DSN_FILE: cannot read the file it points to"),
        ("directory", "BITSCAN_RETENTION_DSN_FILE: cannot read the file it points to"),
        ("empty", "BITSCAN_RETENTION_DSN_FILE: file is empty"),
    ],
)
def test_an_unusable_retention_dsn_file_fails_start_up(
    fresh: PgServer, tmp_path: Path, pki: Pki, kind: str, message: str
) -> None:
    """REQ-277 (3) with M2: start-up fails (exit 2, before binding) naming the
    variable with the M2 message, and the output holds no DSN content."""
    path = tmp_path / "ret.dsn"
    if kind == "directory":
        path.mkdir()
    elif kind == "empty":
        path.write_text("")
    leaf = pki.leaf(f"retdsn-{kind}")
    port = free_port()
    e = env_for(
        fresh,
        tmp_path,
        pki,
        leaf,
        "https://localhost:1/a",
        port,
        BITSCAN_RETENTION_DSN_FILE=str(path),
    )
    s = start(e, tmp_path, port, pki, leaf)
    code = s.proc.wait(30)
    out = s.output()
    assert code == 2, out
    assert f"serve: {message}" in out.splitlines()
    secrets_ = [fresh.dsn("bitscan_app"), fresh.dsn("bitscan_retention")]
    secrets_ += [str(conninfo_to_dict(d)["password"]) for d in secrets_]
    assert sweep(secrets_, out) == []
    assert "Traceback" not in out
    probe = socket.socket()
    probe.bind(("127.0.0.1", port))  # nothing was bound
    probe.close()


# ------------------------------------------------------------ CHK-M11-454


def test_a_refused_retention_login_is_logged_by_type_only(
    launch: Callable[..., Traced], fresh: PgServer, tmp_path: Path
) -> None:
    """The retention DSN's password is wrong (a canary): serve still starts
    (the pool opens without waiting), the retention run fails and is logged by
    job and exception type only; no DSN part or the canary is output; SIGTERM
    exits 0."""
    params = conninfo_to_dict(fresh.dsn("bitscan_retention"))
    params["password"] = CANARY
    bad = tmp_path / "bad-retention.dsn"
    bad.write_text(make_conninfo(**{k: str(v) for k, v in params.items()}))
    t = launch({"BITSCAN_RETENTION_DSN_FILE": str(bad)}, retention_delay_s=1)
    assert until(
        lambda: [r for r in failures(t) if r.get("job") == "retention"], timeout=60
    ), t.output()[-2000:]
    (rec,) = [r for r in failures(t) if r.get("job") == "retention"]
    assert rec["exc_type"] == "DatabaseUnavailable"
    assert set(rec) - BASE == {"job", "exc_type"}
    assert t.stop() == 0
    out = t.output()
    assert sweep([CANARY, str(bad.read_text())], out) == []
    assert "Traceback" not in out
