"""TP-M8-12: re-evaluation races and size (TASK-185 with TASK-183; REQ-201).

#118 (h): re-evaluations of one scan run one at a time (the latest row is the
last run's); definitions and the recorded version come from one snapshot even
while an import commits; a result intake stores mid-run keeps its verdict until
the next run; memory is bounded by chunks of at most 1,000. Races are driven by
threads, events and a lock-wait probe on ``pg_locks`` (bounded polling), never
by sleeps for ordering (decisions 2026-10-26). CHK-M8-210 to -214.
"""

from __future__ import annotations

import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import reeval, results
from bitscan_manager.services.evaluator.reevaluate import ReevalResult, reevaluate_scan

from . import evaluator_pg_fixtures as fx
from .conftest import PgServer

pytestmark = pytest.mark.pg


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@dataclass
class Scan:
    policy: fx.Policy
    scan: UUID
    jobs: list[fx.Job]


def fail_scan(server: PgServer, n_jobs: int = 3) -> Scan:
    """One `equals x` plugin and n jobs whose stdout `y` FAILs; an import that
    changes the expected value to `y` makes them PASS."""
    with fx.owner(server) as conn:
        pol = fx.make_policy(conn, [("equals", "x"), ("equals", "x")])
        scan = fx.make_scan(conn, pol)
        jobs = []
        for _ in range(n_jobs):
            job = fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins)
            for p in pol.plugins:
                fx.add_result(conn, job, pol, p, code=1, stdout="y")
            jobs.append(job)
    return Scan(pol, scan, jobs)


def bump(server: PgServer, s: Scan) -> int:
    with fx.owner(server) as conn:
        return fx.import_change(
            conn, s.policy, expected={p.plugin_uuid: "y" for p in s.policy.plugins}
        )


def rows_of(server: PgServer, s: Scan) -> list[tuple[Any, ...]]:
    with fx.owner(server) as conn:
        return fx.reevals_of(conn, [j.job_id for j in s.jobs])


def consistent(rows: list[tuple[Any, ...]]) -> None:
    """Version 1 has `equals x` (stdout y: FAIL), version 2 `equals y` (PASS):
    a row's code must match the version it records."""
    for r in rows:
        version, code = r[3], r[4]
        assert (version, code) in ((1, 1), (2, 0)), r


def waiting_advisory(server: PgServer) -> bool:
    with fx.owner(server) as probe:
        row = probe.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        ).fetchone()
    return row is not None and int(row[0]) > 0


def poll(cond: Callable[[], bool], timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Run(threading.Thread):
    def __init__(self, name: str, db: AppDatabase, scan: UUID, user: int) -> None:
        super().__init__(name=name, daemon=True)
        self.db, self.scan, self.user = db, scan, user
        self.result: ReevalResult | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = reevaluate_scan(self.db, self.scan, user_id=self.user)
        except BaseException as exc:  # reported by the test
            self.error = exc


def pause_after(
    monkeypatch: pytest.MonkeyPatch, name: str, thread: str
) -> tuple[threading.Event, threading.Event]:
    """Wrap reeval.<name>: in `thread`, after the real call, signal and wait."""
    real = getattr(reeval, name)
    reached, go = threading.Event(), threading.Event()

    def wrapper(*a: Any, **k: Any) -> Any:
        out = real(*a, **k)
        if threading.current_thread().name == thread:
            reached.set()
            assert go.wait(30), "never released"
        return out

    monkeypatch.setattr(reeval, name, wrapper)
    return reached, go


# CHK-M8-210: REQ-201 (1)
def test_two_runs_of_one_scan_serialise_and_the_second_wins(
    migrated_db: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = fail_scan(migrated_db)
    reached, go = pause_after(monkeypatch, "current_definitions", "A")
    a = Run("A", db, s.scan, 1)
    a.start()
    assert reached.wait(10), a.error
    assert bump(migrated_db, s) == 2  # commits while A holds the lock
    b = Run("B", db, s.scan, 2)
    b.start()
    assert poll(lambda: waiting_advisory(migrated_db)), "B is not waiting on the lock"
    assert b.is_alive() and b.result is None
    go.set()
    a.join(30)
    b.join(30)
    assert a.error is None and b.error is None
    assert a.result is not None and b.result is not None
    assert (a.result.policy_version, b.result.policy_version) == (1, 2)
    rows = rows_of(migrated_db, s)
    consistent(rows)
    a_ids = {r[0] for r in rows if r[6] == 1}
    b_ids = {r[0] for r in rows if r[6] == 2}
    assert len(a_ids) == len(b_ids) == 6
    assert min(b_ids) > max(a_ids)
    with fx.app(migrated_db) as conn:
        eff = results.effective_results(conn, s.scan)
    assert {(r.code, r.reevaluated_by, r.reeval_policy_version) for r in eff} == {
        (0, 2, 2)
    }


# CHK-M8-211: REQ-201 (2), an import committing at each step
@pytest.mark.parametrize(
    ("step", "version"), [("lock_scan", 2), ("current_definitions", 1)]
)
def test_import_between_steps_never_mixes_versions(
    migrated_db: PgServer,
    db: AppDatabase,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
    version: int,
) -> None:
    s = fail_scan(migrated_db)
    reached, go = pause_after(monkeypatch, step, "A")
    a = Run("A", db, s.scan, 1)
    a.start()
    assert reached.wait(10), a.error
    bump(migrated_db, s)
    go.set()
    a.join(30)
    assert a.error is None and a.result is not None
    assert a.result.policy_version == version
    rows = rows_of(migrated_db, s)
    assert len(rows) == 6
    consistent(rows)
    assert {r[3] for r in rows} == {version}


def test_import_inside_the_definitions_read_never_mixes_versions(
    migrated_db: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pause after the first statement that reads `policy` (a plant that reads
    the version and the definitions in separate statements goes red here)."""
    s = fail_scan(migrated_db)
    real = psycopg.Cursor.execute
    reached, go = threading.Event(), threading.Event()

    def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
        out = real(cur, query, params, **kw)
        text = query if isinstance(query, str) else query.as_string(cur.connection)
        if (
            threading.current_thread().name == "A"
            and not reached.is_set()
            and "FROM policy" in text
        ):
            reached.set()
            assert go.wait(30)
        return out

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    a = Run("A", db, s.scan, 1)
    a.start()
    assert reached.wait(10), a.error
    bump(migrated_db, s)
    go.set()
    a.join(30)
    assert a.error is None
    rows = rows_of(migrated_db, s)
    assert len(rows) == 6
    consistent(rows)


# CHK-M8-212: REQ-201 (3), a result inserted mid-run
def test_result_stored_mid_run_waits_for_the_next_run(
    migrated_db: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x"), ("equals", "x")])
        scan = fx.make_scan(conn, pol)
        job = fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins)
        fx.add_result(conn, job, pol, pol.plugins[0], code=0, stdout="x")
    real = reeval.insert_reevals
    done: list[int] = []

    def insert(conn: Any, rows: Any, **kw: Any) -> int:
        if not done:  # after the first chunk was read, before the commit
            with fx.owner(migrated_db) as other:
                fx.add_result(other, job, pol, pol.plugins[1], code=1, stdout="y")
            done.append(1)
        return int(real(conn, rows, **kw))

    monkeypatch.setattr(reeval, "insert_reevals", insert)
    first = reevaluate_scan(db, scan, user_id=1)
    assert first.rows_added == 1
    with fx.owner(migrated_db) as conn:
        rows = fx.reevals_of(conn, [job.job_id])
    assert [r[2] for r in rows] == [pol.plugins[0].plugin_uuid]
    monkeypatch.undo()
    second = reevaluate_scan(db, scan, user_id=1)
    assert second.rows_added == 2
    with fx.owner(migrated_db) as conn:
        late = [
            r
            for r in fx.reevals_of(conn, [job.job_id])
            if r[2] == pol.plugins[1].plugin_uuid
        ]
    assert [(r[4], r[5]) for r in late] == [(1, None)]  # `equals x` on stdout y


# CHK-M8-213: REQ-201 (4), 20,000 results under 64 MiB of traced memory
def test_twenty_thousand_results_stay_under_64_mib(
    migrated_db: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")] * 1_000)
        scan = fx.make_scan(conn, pol)
        jobs = []
        for _ in range(20):
            job = fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins)
            jobs.append(job)
            # 4,000-byte stdout each: 80 MB if every result were held at once
            conn.execute(
                "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid,"
                " eval_code, exit_code, stdout, stderr, plugin_name_snap,"
                " execute_snap, operator_snap, expected_snap, started_at,"
                " finished_at) SELECT %s, %s, pp.plugin_uuid, 1, 0,"
                " repeat('y', 4000), '', 'F - p', 'printf y', 'equals', 'x',"
                " now(), now() FROM policy_plugin pp WHERE pp.policy_id = %s",
                (job.job_id, job.created_at, pol.policy_id),
            )
    sizes: list[int] = []
    real = reeval.insert_reevals

    def insert(conn: Any, rows: Any, **kw: Any) -> int:
        sizes.append(len(rows))
        return int(real(conn, rows, **kw))

    monkeypatch.setattr(reeval, "insert_reevals", insert)
    tracemalloc.start()
    try:
        out = reevaluate_scan(db, scan, user_id=1)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert out.rows_added == 20_000
    assert max(sizes) <= 1_000 and sum(sizes) == 20_000
    assert peak < 64 * 1024 * 1024, peak


# CHK-M8-214: REQ-201 (5), two scans do not wait for each other
def test_two_scans_do_not_wait(
    migrated_db: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    s1, s2 = fail_scan(migrated_db), fail_scan(migrated_db)
    reached, go = pause_after(monkeypatch, "current_definitions", "A")
    a = Run("A", db, s1.scan, 1)
    a.start()
    assert reached.wait(10), a.error
    b = Run("B", db, s2.scan, 2)
    b.start()
    b.join(20)  # finishes while A still holds its scan's lock
    assert not b.is_alive() and b.error is None, b.error
    assert b.result is not None and b.result.rows_added == 6
    assert a.is_alive()
    go.set()
    a.join(30)
    assert a.error is None and a.result is not None and a.result.rows_added == 6
