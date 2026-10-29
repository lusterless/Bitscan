"""TP-M7-20 (TASK-160): the catalog service, its #102 (d) start-up gate, the
rebuild worker and the `serve` lifecycle wiring.

CHK-M7-242 (tests/m7/test-plan.md). Expected values come from the spec and
the approved answers, not from the code: TS §4.1 L526, L528 (start-up before
anything else; the watcher), §4.2 L540 (a task still `running` at start-up is
failed); REQ-164, REQ-165 (5) (catalog routes refused until start-up ends;
the 503 itself is TASK-162–164's, so the CatalogStarting gate is tested here),
REQ-172; #102 (d) (start-up on a background thread, retried while the
database is down; until it ends upload, delete and rebuild are refused; the
watcher starts after the reconcile, which covers changes made meanwhile),
(e); the TASK-160 row (fakes: refused before, succeeds after; a rebuild on the
worker ends `succeeded`; `ServeLifecycle.stop` stops the watcher and waits for
the worker, bounded).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.cli.serve import ServeLifecycle
from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.services.importer import rebuild as rb_mod
from bitscan_manager.services.importer import service as svc
from bitscan_manager.services.importer import startup as su
from bitscan_manager.services.importer import uploads as up_mod
from bitscan_manager.services.importer.folders import reconcile as real_reconcile
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.service import (
    STOP_WAIT_S,
    CatalogService,
    CatalogStarting,
)
from bitscan_manager.services.importer.watcher import Watcher

from .catalog_rows import T2, app, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, doc, make_env, plug

pytestmark = pytest.mark.pg

ADMIN = Actor("user:51", 51)


class FakeWatcher:
    def __init__(self, log: list[str], opens: bool = True) -> None:
        self.log, self.opens = log, opens

    def open(self) -> bool:
        self.log.append("watcher.open")
        return self.opens

    def run(self, stop: threading.Event, poll: float = 1.0) -> None:
        self.log.append("watcher.run")
        stop.wait()
        self.log.append("watcher.run returned")


class Fake:
    """startup.run blocked until released; the three operations recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.log: list[str] = []
        self.release = threading.Event()
        self.calls: list[tuple[Any, ...]] = []
        self.wakes = 0

        def startup_run(db: Any, clock: Any, bits: Path, stop: threading.Event) -> Any:
            self.log.append("startup.run")
            while not self.release.wait(0.02):
                if stop.is_set():
                    return None
            self.log.append("startup.done")
            return object()

        monkeypatch.setattr(su, "run", startup_run)
        monkeypatch.setattr(up_mod, "upload", lambda *a: self.called("upload", *a))
        monkeypatch.setattr(
            svc, "delete_policy", lambda *a, **k: self.called("delete", *a, k)
        )
        monkeypatch.setattr(rb_mod, "start_task", lambda *a: self.task(*a))
        monkeypatch.setattr(rb_mod, "run", lambda *a: self.called("run", *a))

    def called(self, name: str, *a: Any) -> str:
        self.calls.append((name, threading.current_thread().name, *a))
        return f"{name}-result"

    def task(self, *a: Any) -> UUID:
        self.calls.append(("start_task", threading.current_thread().name, *a))
        return UUID(int=7)

    def wake(self) -> None:
        self.wakes += 1


def until(pred: Callable[[], Any], bound: float = 5.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < bound:
        if pred():
            return
        time.sleep(0.02)
    pytest.fail(f"not within {bound} s")


@pytest.fixture
def fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[Fake, CatalogService]]:
    f = Fake(monkeypatch)
    s = CatalogService(object(), object(), tmp_path, wake=f.wake,  # type: ignore[arg-type]
                       watcher=FakeWatcher(f.log))  # type: ignore[arg-type]  # fmt: skip
    s.start()
    yield f, s
    f.release.set()
    s.stop(wait_s=5)


def every_operation(s: CatalogService) -> list[Callable[[], Any]]:
    return [
        lambda: s.upload(b"data", b"name.bit", ADMIN),
        lambda: s.delete(5, "user:51"),
        lambda: s.start_rebuild(51, ADMIN),
    ]


# The #102 (d) gate (REQ-165 (5)) ------------------------------------------------------


def test_every_operation_is_refused_until_start_up_ends(
    fake: tuple[Fake, CatalogService],
) -> None:
    f, s = fake
    until(lambda: "startup.run" in f.log)
    assert not s.ready
    for op in every_operation(s):
        with pytest.raises(CatalogStarting):
            op()
    assert f.calls == [] and f.wakes == 0  # nothing reached the importer
    assert (svc.STARTING_DETAIL, svc.RETRY_AFTER_S) == (
        "The catalog is starting; retry shortly.", 10,
    )  # fmt: skip
    f.release.set()
    until(lambda: s.ready)
    got: Any = s.upload(b"data", b"name.bit", ADMIN)
    assert got == "upload-result"
    got = s.delete(5, "user:51")
    assert got == "delete-result"
    assert s.start_rebuild(51, ADMIN) == UUID(int=7)
    names = [c[0] for c in f.calls]
    assert names[:3] == ["upload", "delete", "start_task"]
    until(lambda: any(c[0] == "run" for c in f.calls))
    assert f.wakes >= 3  # the shipper is woken after each


def test_the_watcher_opens_before_the_start_up_and_runs_after(
    fake: tuple[Fake, CatalogService],
) -> None:
    f, s = fake
    f.release.set()
    until(lambda: "watcher.run" in f.log)
    assert f.log[:4] == ["watcher.open", "startup.run", "startup.done", "watcher.run"]


def test_a_stop_before_start_up_ends_leaves_the_gate_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = Fake(monkeypatch)
    s = CatalogService(object(), object(), tmp_path, wake=f.wake,  # type: ignore[arg-type]
                       watcher=FakeWatcher(f.log))  # type: ignore[arg-type]  # fmt: skip
    s.start()
    until(lambda: "startup.run" in f.log)
    s.stop(wait_s=5)
    assert not s.ready and "watcher.run" not in f.log
    with pytest.raises(CatalogStarting):
        s.upload(b"x", None, ADMIN)


def test_without_a_watcher_the_gate_still_opens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = Fake(monkeypatch)
    s = CatalogService(object(), object(), tmp_path, wake=f.wake,  # type: ignore[arg-type]
                       watcher=FakeWatcher(f.log, opens=False))  # type: ignore[arg-type]  # fmt: skip
    s.start()
    f.release.set()
    until(lambda: s.ready)
    s.stop(wait_s=5)
    assert "watcher.run" not in f.log


# The rebuild worker ---------------------------------------------------------------


def test_rebuilds_run_one_at_a_time_on_the_worker(
    monkeypatch: pytest.MonkeyPatch, fake: tuple[Fake, CatalogService]
) -> None:
    f, s = fake
    running: list[int] = []
    peak: list[int] = []
    done: list[str] = []

    def slow_run(db: Any, clock: Any, bits: Path, tid: UUID, actor: Actor) -> None:
        running.append(1)
        peak.append(len(running))
        assert threading.current_thread().name == "catalog-rebuild"
        time.sleep(0.1)
        running.pop()
        done.append(str(tid))

    monkeypatch.setattr(rb_mod, "run", slow_run)
    f.release.set()
    until(lambda: s.ready)
    for _ in range(3):
        s.start_rebuild(51, ADMIN)  # returns at once (the route answers 202)
    until(lambda: len(done) == 3)
    assert max(peak) == 1  # one after another
    starts = [c for c in f.calls if c[0] == "start_task"]
    assert all(c[1] != "catalog-rebuild" for c in starts)  # the row on the caller


def test_a_worker_error_is_logged_and_the_worker_goes_on(
    monkeypatch: pytest.MonkeyPatch,
    fake: tuple[Fake, CatalogService],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    f, s = fake
    n: list[int] = []

    def flaky(*a: Any) -> None:
        n.append(1)
        if len(n) == 1:
            raise OSError("no session")

    monkeypatch.setattr(rb_mod, "run", flaky)
    f.release.set()
    until(lambda: s.ready)
    s.start_rebuild(51, ADMIN)
    s.start_rebuild(51, ADMIN)
    until(lambda: len(n) == 2)
    assert "rebuild did not start: OSError" in caplog.text
    assert "no session" not in caplog.text


# stop: bounded, even with the worker blocked ------------------------------------------


def test_stop_is_bounded_with_a_worker_blocked_and_threads_are_daemons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    f = Fake(monkeypatch)
    blocked = threading.Event()
    never = threading.Event()

    def stuck(*a: Any) -> None:
        blocked.set()
        never.wait(60)  # e.g. waiting for the catalog lock

    monkeypatch.setattr(rb_mod, "run", stuck)
    s = CatalogService(object(), object(), tmp_path, wake=f.wake,  # type: ignore[arg-type]
                       watcher=FakeWatcher(f.log))  # type: ignore[arg-type]  # fmt: skip
    assert 0 < 2 * STOP_WAIT_S <= 5.0  # both joins well inside the 10 s SIGTERM bound
    assert all(t.daemon for t in s._threads)  # process exit frees the lock
    s.start()
    f.release.set()
    until(lambda: s.ready)
    s.start_rebuild(51, ADMIN)
    assert blocked.wait(5)
    t0 = time.monotonic()
    done = threading.Event()

    def stopper() -> None:
        s.stop(wait_s=1.0)
        done.set()

    threading.Thread(target=stopper, daemon=True).start()
    assert done.wait(10), "stop did not return"
    took = time.monotonic() - t0
    assert 0.9 <= took < 3.0  # waited for the worker, bounded
    assert "watcher.run returned" in f.log  # the watcher stopped
    assert "catalog thread still running at stop: catalog-rebuild" in caplog.text
    never.set()


def test_serve_lifecycle_stops_the_catalog_first_and_starts_it_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class Part:
        def __init__(self, name: str) -> None:
            self.name = name

        def open(self) -> None:
            order.append(f"{self.name}.open")

        def start(self) -> None:
            order.append(f"{self.name}.start")

        def stop(self, *a: Any) -> None:
            order.append(f"{self.name}.stop")

        def close(self) -> None:
            order.append(f"{self.name}.close")

    life = ServeLifecycle(
        Part("db"), Part("shipper"), Part("flusher"), Part("cipher"),  # type: ignore[arg-type]
        (None, Path("c"), Path("k")),  # type: ignore[arg-type]
        Part("scheduler"), Part("catalog"),  # type: ignore[arg-type]
    )  # fmt: skip
    monkeypatch.setattr("bitscan_manager.cli.serve.signal", object())  # no SIGHUP

    async def go() -> None:
        await life.start()
        await life.stop()

    asyncio.run(go())
    assert order == [
        "db.open", "shipper.start", "flusher.start", "scheduler.start", "catalog.start",
        "catalog.stop", "scheduler.stop", "flusher.stop", "shipper.stop",
        "cipher.close", "db.close",
    ]  # fmt: skip


# On PostgreSQL ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("catsvc")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
    yield from make_env(server, tmp_path)


def task_state(e: Env, tid: UUID) -> str | None:
    with app(e.server) as c:
        row = imports_repo.get_task(c, tid)
    return None if row is None else row.state


def test_a_started_rebuild_runs_on_the_worker_and_succeeds(env: Env) -> None:
    (env.bits / "a.bit").write_bytes(doc(f"Svc {tag()}", [plug()]))
    log: list[str] = []
    s = CatalogService(env.db, env.clock, env.bits, watcher=FakeWatcher(log))  # type: ignore[arg-type]
    s.start()
    try:
        until(lambda: s.ready, 30)  # the real start-up imported a.bit
        assert (
            env.policy_by_name(
                (env.bits / "a.bit").read_text().split("<PolicyName>")[1].split("<")[0]
            )
            is not None
        )
        tid = s.start_rebuild(51, ADMIN)
        assert task_state(env, tid) in ("running", "succeeded")
        until(lambda: task_state(env, tid) == "succeeded", 30)
        with app(env.server) as c:
            row = imports_repo.get_task(c, tid)
        assert row is not None and row.requested_by == 51
    finally:
        s.stop(wait_s=10)


def test_stop_with_the_worker_blocked_on_the_real_lock(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    log: list[str] = []
    s = CatalogService(env.db, env.clock, env.bits, watcher=FakeWatcher(log))  # type: ignore[arg-type]
    s.start()
    until(lambda: s.ready, 30)
    with app(env.server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        tid = s.start_rebuild(None, Actor("cli:root", None))
        time.sleep(0.5)  # the worker is now waiting for the lock
        t0 = time.monotonic()
        s.stop(wait_s=1.0)
        assert time.monotonic() - t0 < 3.0
        assert "catalog thread still running at stop: catalog-rebuild" in caplog.text
        assert task_state(env, tid) == "running"
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    until(lambda: task_state(env, tid) != "running", 30)  # it then finishes


def test_a_file_changed_during_the_reconcile_is_picked_up(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The watcher is opened before the start-up reconcile (#102 (d),
    # TASK-159), so a file written after the reconcile's import pass, before
    # the gate opens, is queued and imported by the watcher afterwards.
    if os.name != "posix":
        pytest.skip("inotify: Linux only")
    real = real_reconcile
    late = env.bits / "late.bit"
    name = f"Late {tag()}"

    def reconcile_then_write(session: Any, clock: Any, bits: Path) -> Any:
        out = real(session, clock, bits)
        late.write_bytes(doc(name, [plug()]))  # after its import pass
        return out

    monkeypatch.setattr(su, "reconcile", reconcile_then_write)
    s = CatalogService(
        env.db, env.clock, env.bits, watcher=Watcher(env.db, env.clock, env.bits)
    )
    s.start()
    try:
        until(lambda: s.ready, 30)
        until(lambda: env.policy_by_name(name) is not None, 10)
    finally:
        s.stop(wait_s=10)
