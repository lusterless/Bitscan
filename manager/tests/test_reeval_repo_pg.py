"""TP-M8-10: re-evaluation repository on PostgreSQL (TASK-183 r1; REQ-200,
REQ-201, REQ-204 (1)).

As ``bitscan_app`` with only the TS §5.2 grants. Expected behaviour: TS §4.5
L601 (re-evaluation adds rows only), §5.2 L1005-L1006 (the app never changes
``scan_result`` or ``scan_result_reeval``), #118 (f) definitions and version in
one statement, (h) one re-evaluation of a scan at a time (transaction-level
advisory lock; two scans independent), REQ-201 (4) chunks of at most 1,000.
Races use threads, a lock-wait probe on ``pg_locks`` and bounded polling,
never sleeps for ordering. CHK-M8-170 to -175, -225.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import reeval
from bitscan_manager.repositories.reeval import (
    Definitions,
    ReevalInsert,
    ScanRef,
    StoredResult,
)

from . import evaluator_pg_fixtures as fx
from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]


@pytest.fixture
def tx_conn(migrated_db: PgServer) -> Iterator[Conn]:
    """bitscan_app, autocommit off (as AppDatabase.transaction() hands out)."""
    with fx.app(migrated_db, autocommit=False) as conn:
        yield conn
        conn.rollback()


def _scan_with_results(
    server: PgServer, n: int, *, null_stdout: bool = False
) -> tuple[fx.Policy, UUID, list[fx.Job]]:
    with fx.owner(server) as conn:
        pol = fx.make_policy(conn, [("equals", "x"), ("eq", "1")])
        scan = fx.make_scan(conn, pol)
        jobs = []
        # n results spread over jobs of 2 plugins each (one agent per job)
        for i in range((n + 1) // 2):
            job = fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins)
            jobs.append(job)
            for k, plugin in enumerate(pol.plugins):
                if 2 * i + k >= n:
                    break
                fx.add_result(
                    conn,
                    job,
                    pol,
                    plugin,
                    code=2 if k else 0,
                    detail="stdout not numeric" if k else None,
                    stdout=None if (null_stdout and k) else f"out{i}",
                    exit_code=None if k else 0,
                    timed_out=bool(k),
                    truncated=False,
                )
    return pol, scan, jobs


# CHK-M8-170: lock_scan
def test_lock_scan_returns_the_scan_ref(migrated_db: PgServer, tx_conn: Conn) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")], version=4)
        scan = fx.make_scan(conn, pol, version=3)
    ref = reeval.lock_scan(tx_conn, scan)
    assert ref == ScanRef(scan_id=scan, policy_id=pol.policy_id, policy_version=3)
    assert reeval.lock_scan(tx_conn, uuid4()) is None


def test_lock_scan_refuses_autocommit(migrated_db: PgServer) -> None:
    with fx.app(migrated_db) as conn, pytest.raises(RuntimeError):
        reeval.lock_scan(conn, uuid4())


# CHK-M8-171: current_definitions in one statement
def test_current_definitions(migrated_db: PgServer, tx_conn: Conn) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "a"), ("regex", "^b$"), ("empty", "")])
        p = pol.plugins
        new_version = fx.import_change(
            conn,
            pol,
            expected={p[0].plugin_uuid: "a2"},
            operator={p[1].plugin_uuid: "not_regex"},
            drop=[p[2].plugin_uuid],
        )
    d = reeval.current_definitions(tx_conn, pol.policy_id)
    assert isinstance(d, Definitions)
    assert d.policy_version == new_version == 2
    assert d.deleted is False
    assert dict(d.plugins) == {
        p[0].plugin_uuid: ("equals", "a2"),
        p[1].plugin_uuid: ("not_regex", "^b$"),
    }
    with pytest.raises(TypeError):
        d.plugins[p[2].plugin_uuid] = ("x", "y")  # type: ignore[index]


def test_current_definitions_deleted_empty_and_unknown(
    migrated_db: PgServer, tx_conn: Conn
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "a")])
        fx.soft_delete(conn, pol)
        empty = fx.make_policy(conn, [("equals", "a")])
        fx.import_change(conn, empty, drop=[empty.plugins[0].plugin_uuid])
    d = reeval.current_definitions(tx_conn, pol.policy_id)
    assert d is not None and d.deleted is True
    e = reeval.current_definitions(tx_conn, empty.policy_id)
    assert e is not None and dict(e.plugins) == {} and e.policy_version == 2
    assert reeval.current_definitions(tx_conn, 9_999_999_999) is None


def test_current_definitions_is_one_statement(
    migrated_db: PgServer, tx_conn: Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "a")] * 7)
    spy = fx.StatementSpy()
    spy.install(monkeypatch)
    d = reeval.current_definitions(tx_conn, pol.policy_id)
    assert d is not None and len(d.plugins) == 7
    assert len(spy.statements) == 1
    assert spy.verbs() == ["SELECT"]


# CHK-M8-172: chunks never exceed the size and cover each result once
@pytest.mark.parametrize(("n", "chunk"), [(2_500, 1_000), (2_500, 3), (50, 1)])
def test_stored_results_chunks(
    migrated_db: PgServer, tx_conn: Conn, n: int, chunk: int
) -> None:
    pol, scan, jobs = _scan_with_results(migrated_db, n)
    seen: list[tuple[UUID, UUID]] = []
    sizes: list[int] = []
    cursors: list[str] = []
    for i, batch in enumerate(reeval.stored_results(tx_conn, scan, chunk=chunk)):
        assert all(isinstance(r, StoredResult) for r in batch)
        sizes.append(len(batch))
        seen.extend((r.job_id, r.plugin_uuid) for r in batch)
        if i == 0:
            cursors = [
                str(r[0])
                for r in tx_conn.execute("SELECT name FROM pg_cursors").fetchall()
            ]
    assert max(sizes) <= chunk
    assert sum(sizes) == n
    assert len(seen) == len(set(seen)) == n
    assert all(s == chunk for s in sizes[:-1])  # only the last may be short
    assert cursors, "no server-side cursor during iteration"


def test_stored_results_values(migrated_db: PgServer, tx_conn: Conn) -> None:
    pol, scan, jobs = _scan_with_results(migrated_db, 2, null_stdout=True)
    batches = list(reeval.stored_results(tx_conn, scan))
    assert len(batches) == 1
    rows = {r.plugin_uuid: r for r in batches[0]}
    a = rows[pol.plugins[0].plugin_uuid]
    assert (a.job_id, a.stdout, a.exit_code, a.timed_out, a.truncated) == (
        jobs[0].job_id,
        "out0",
        0,
        False,
        False,
    )
    assert (a.eval_code, a.eval_detail) == (0, None)
    b = rows[pol.plugins[1].plugin_uuid]
    assert b.stdout is None  # NULL kept, not COALESCEd (TASK-183 r1)
    assert (b.exit_code, b.timed_out, b.eval_code, b.eval_detail) == (
        None,
        True,
        2,
        "stdout not numeric",
    )


def test_stored_results_covers_retries_and_skips_other_scans(
    migrated_db: PgServer, tx_conn: Conn
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")] * 3)
        p = pol.plugins
        scan = fx.make_scan(conn, pol)
        agent = fx.make_agent(conn)
        orig = fx.make_job(conn, scan, agent, pol, p)
        retry = fx.make_job(
            conn, scan, agent, pol, p[1:], retry_of=orig.job_id,
            created_at=fx.next_month_start(),
        )  # fmt: skip
        fx.add_result(conn, orig, pol, p[0], code=0)
        fx.add_result(conn, retry, pol, p[1], code=1)
        other = fx.make_scan(conn, pol)
        oj = fx.make_job(conn, other, agent, pol, p)
        fx.add_result(conn, oj, pol, p[2], code=0)
        fx.make_inventory_job(conn, agent)
    got = [
        (r.job_id, r.plugin_uuid)
        for b in reeval.stored_results(tx_conn, scan)
        for r in b
    ]
    assert sorted(got) == sorted(
        [(orig.job_id, p[0].plugin_uuid), (retry.job_id, p[1].plugin_uuid)]
    )


def test_stored_results_unknown_scan_and_bad_chunk(tx_conn: Conn) -> None:
    assert list(reeval.stored_results(tx_conn, uuid4())) == []
    with pytest.raises(ValueError):
        list(reeval.stored_results(tx_conn, uuid4(), chunk=0))


# CHK-M8-173: inserting N rows adds exactly N
@pytest.mark.parametrize("n", [0, 1, 7, 1_000])
def test_insert_reevals_adds_exactly_n(
    migrated_db: PgServer, tx_conn: Conn, n: int
) -> None:
    pol, scan, jobs = _scan_with_results(migrated_db, max(2, n))
    pairs = [(j.job_id, u) for j in jobs for u in j.plugins][:n]
    rows = [
        ReevalInsert(j, u, i % 3, None if i % 3 < 2 else "cannot evaluate")
        for i, (j, u) in enumerate(pairs)
    ]
    ids = [j.job_id for j in jobs]
    before = len(fx.reevals_of(tx_conn, ids))
    added = reeval.insert_reevals(tx_conn, rows, policy_version=42, reevaluated_by=77)
    assert added == n
    after = fx.reevals_of(tx_conn, ids)
    assert len(after) - before == n
    got = sorted((r[1], r[2], r[3], r[4], r[5], r[6]) for r in after)
    want = sorted(
        (r.job_id, r.plugin_uuid, 42, r.eval_code, r.eval_detail, 77) for r in rows
    )
    assert got == want
    if n:
        stamp = tx_conn.execute(
            "SELECT bool_and(reevaluated_at = now()) FROM scan_result_reeval"
            " WHERE job_id = ANY(%s)",
            (ids,),
        ).fetchone()
        assert stamp == (True,)  # the column default, inside this transaction


# CHK-M8-175: no UPDATE, DELETE or row lock in any function
def test_no_update_delete_or_row_lock(
    migrated_db: PgServer, tx_conn: Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    pol, scan, jobs = _scan_with_results(migrated_db, 4)
    spy = fx.StatementSpy()
    spy.install(monkeypatch)
    ref = reeval.lock_scan(tx_conn, scan)
    assert ref is not None
    reeval.current_definitions(tx_conn, ref.policy_id)
    batches = list(reeval.stored_results(tx_conn, scan, chunk=2))
    reeval.insert_reevals(
        tx_conn,
        [ReevalInsert(r.job_id, r.plugin_uuid, 0, None) for b in batches for r in b],
        policy_version=1,
        reevaluated_by=1,
    )
    text = " ".join(spy.statements).upper()
    words = text.replace(",", " ").replace("(", " ").replace(")", " ").split()
    for bad in ("UPDATE", "DELETE", "TRUNCATE", "MERGE"):
        assert bad not in words, bad  # whole words: `truncated` is a column
    for phrase in ("FOR UPDATE", "FOR SHARE", "FOR NO KEY", "FOR KEY SHARE"):
        assert phrase not in " ".join(words), phrase
    assert set(spy.verbs()) <= {"SELECT", "INSERT"}
    # lock 2 + definitions 1 + cursor 1 + insert 1
    assert len(spy.statements) == 5


# CHK-M8-174: two sessions on one scan serialise; two scans do not
def _waiting_advisory(server: PgServer, pid: int) -> bool:
    with fx.owner(server) as probe:
        row = probe.execute(
            "SELECT count(*) FROM pg_locks WHERE pid = %s AND locktype = 'advisory'"
            " AND NOT granted",
            (pid,),
        ).fetchone()
    return row is not None and int(row[0]) > 0


def _poll(cond: Any, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Locker(threading.Thread):
    def __init__(self, server: PgServer, scan_id: UUID) -> None:
        super().__init__(daemon=True)
        self.server = server
        self.scan_id = scan_id
        self.pid = 0
        self.ready = threading.Event()
        self.locked = threading.Event()
        self.release = threading.Event()
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            with fx.app(self.server, autocommit=False) as conn:
                row = conn.execute("SELECT pg_backend_pid()").fetchone()
                assert row is not None
                self.pid = int(row[0])
                self.ready.set()
                reeval.lock_scan(conn, self.scan_id)
                self.locked.set()
                self.release.wait(30)
                conn.commit()
        except BaseException as exc:  # reported by the test
            self.error = exc
            self.ready.set()


def test_two_sessions_on_one_scan_serialise(migrated_db: PgServer) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")])
        scan = fx.make_scan(conn, pol)
    first = Locker(migrated_db, scan)
    first.start()
    assert first.locked.wait(10), first.error
    second = Locker(migrated_db, scan)
    second.start()
    assert second.ready.wait(10)
    assert _poll(lambda: _waiting_advisory(migrated_db, second.pid)), "not waiting"
    assert not second.locked.is_set()
    first.release.set()
    first.join(10)
    assert second.locked.wait(10), second.error
    second.release.set()
    second.join(10)
    assert first.error is None and second.error is None


def test_two_scans_do_not_wait(migrated_db: PgServer) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")])
        s1, s2 = fx.make_scan(conn, pol), fx.make_scan(conn, pol)
    a, b = Locker(migrated_db, s1), Locker(migrated_db, s2)
    a.start()
    assert a.locked.wait(10), a.error
    b.start()
    assert b.locked.wait(10), b.error  # while a still holds its lock
    assert a.is_alive()
    a.release.set()
    b.release.set()
    a.join(10)
    b.join(10)
    assert a.error is None and b.error is None


def test_lock_is_released_at_rollback(migrated_db: PgServer) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")])
        scan = fx.make_scan(conn, pol)
    with fx.app(migrated_db, autocommit=False) as conn:
        reeval.lock_scan(conn, scan)
        conn.rollback()
        other = Locker(migrated_db, scan)
        other.start()
        assert other.locked.wait(10), other.error
        other.release.set()
        other.join(10)


# CHK-M8-225: REQ-204 (1) grant probes as bitscan_app
def _current_partition(conn: Conn) -> str:
    row = conn.execute(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
        " JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'scan_result'"
        " AND pg_get_expr(c.relpartbound, c.oid) LIKE"
        " '%%' || to_char(now(), 'YYYY-MM') || '-01%%' ORDER BY 1 LIMIT 1"
    ).fetchone()
    assert row is not None, "no partition for the current month"
    return str(row[0])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {t} SET eval_code = 0",
        "UPDATE {t} SET eval_detail = NULL WHERE false",
        "DELETE FROM {t}",
        "DELETE FROM {t} WHERE false",
        "TRUNCATE {t}",
    ],
)
@pytest.mark.parametrize(
    "table", ["scan_result", "current", "scan_result_default", "scan_result_reeval"]
)
def test_app_cannot_change_results(
    migrated_db: PgServer, statement: str, table: str
) -> None:
    with fx.app(migrated_db) as conn:
        name = _current_partition(conn) if table == "current" else table
        assert name.startswith("scan_result")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement.format(t=name))


def test_app_can_insert_reevals_and_select(migrated_db: PgServer) -> None:
    with fx.app(migrated_db) as conn:
        for t in ("scan", "scan_job", "scan_result", "scan_result_reeval", "policy",
                  "policy_plugin", "plugin"):  # fmt: skip
            row = conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT')", (t,)
            ).fetchone()
            assert row == (True,), t
        row = conn.execute(
            "SELECT has_table_privilege(current_user, 'scan_result_reeval', 'INSERT'),"
            " has_table_privilege(current_user, 'scan_result_reeval', 'UPDATE'),"
            " has_table_privilege(current_user, 'scan_result_reeval', 'DELETE'),"
            " has_table_privilege(current_user, 'scan_result', 'UPDATE')"
        ).fetchone()
        assert row == (True, False, False, False)
