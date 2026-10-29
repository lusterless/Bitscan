"""TP-M7-09 (TASK-147): catalog lock on a pinned session, on PostgreSQL.

CHK-M7-140 to -145 (tests/m7/test-plan.md). Expected values: TS §4.1
"Locking" (session-level ``pg_advisory_lock(hashtext('catalog'))`` taken before
the transaction and released only after the file work), REQ-161 (1) to (3),
design note D4 (one pinned session, several transactions). Waiting is observed
through ``pg_locks`` (a granted = false row), never by sleeping for order.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg import pq
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase, DatabaseUnavailable
from bitscan_manager.repositories.catalog_lock import catalog_lock

from .conftest import PgServer

pytestmark = pytest.mark.pg

KEY_SQL = (
    "SELECT pid, granted, mode FROM pg_locks WHERE locktype = 'advisory'"
    " AND objsubid = 1 AND database = (SELECT oid FROM pg_database"
    " WHERE datname = current_database())"
    " AND ((classid::bigint << 32) | objid::bigint)"
    " = (hashtext('catalog')::bigint & x'ffffffffffffffff'::bigint)"
)


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


@pytest.fixture
def probe(migrated_db: PgServer) -> Iterator[psycopg.Connection[Any]]:
    with migrated_db.connect("bitscan_app") as c:
        yield c


def catalog_free(probe: psycopg.Connection[Any]) -> bool:
    """True if nobody holds the catalog lock (releases the probe's own take)."""
    row = probe.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
    assert row is not None
    if row[0]:
        probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    return bool(row[0])


def holders(probe: psycopg.Connection[Any]) -> list[tuple[int, bool, str]]:
    return [(int(p), bool(g), str(m)) for p, g, m in probe.execute(KEY_SQL).fetchall()]


def wait_until(cond: Callable[[], bool], limit_s: float = 10.0) -> bool:
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def pid_of(conn: psycopg.Connection[Any]) -> int:
    return int(conn.info.backend_pid)


# CHK-M7-140 ------------------------------------------------------------------


def test_second_session_waits_until_the_first_releases(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    events: list[str] = []
    a_in, go = threading.Event(), threading.Event()
    pids: dict[str, int] = {}
    errors: list[BaseException] = []

    def first() -> None:
        try:
            with db.session() as s, catalog_lock(s):
                pids["a"] = pid_of(s.conn)
                events.append("a_in")
                a_in.set()
                assert go.wait(20)
                events.append("a_out")
        except BaseException as exc:  # reported below
            errors.append(exc)

    def second() -> None:
        try:
            with db.session() as s:
                pids["b"] = pid_of(s.conn)
                with catalog_lock(s):
                    events.append("b_in")
        except BaseException as exc:
            errors.append(exc)

    ta = threading.Thread(target=first, daemon=True)
    ta.start()
    assert a_in.wait(10)
    tb = threading.Thread(target=second, daemon=True)
    tb.start()
    # b is queued on the lock: a not-granted row for its backend appears
    assert wait_until(
        lambda: "b" in pids and (pids["b"], False, "ExclusiveLock") in holders(probe)
    )
    assert (pids["a"], True, "ExclusiveLock") in holders(probe)
    assert events == ["a_in"]
    go.set()
    ta.join(10)
    tb.join(10)
    assert not errors, errors
    assert events == ["a_in", "a_out", "b_in"]
    assert catalog_free(probe)


def test_a_session_waits_for_a_holder_in_another_process(
    db: AppDatabase, migrated_db: PgServer, probe: psycopg.Connection[Any]
) -> None:
    # e.g. a CLI rebuild holding the lock (REQ-161 (1)): the key is the same.
    got = threading.Event()
    with migrated_db.connect("bitscan_app") as outsider:
        outsider.execute("SELECT pg_advisory_lock(hashtext('catalog'))")

        def take() -> None:
            with db.session() as s, catalog_lock(s):
                got.set()

        t = threading.Thread(target=take, daemon=True)
        t.start()
        assert wait_until(lambda: any(not g for _, g, _ in holders(probe)))
        assert not got.is_set()
        outsider.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        assert got.wait(10)
        t.join(10)
    assert catalog_free(probe)


# CHK-M7-141 / -143 -----------------------------------------------------------


def test_lock_spans_two_transactions_in_one_session(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s:
        assert catalog_free(probe)
        with catalog_lock(s):
            holder = pid_of(s.conn)
            with s.transaction() as tx:
                row = tx.conn.execute("SELECT pg_backend_pid()").fetchone()
                assert row == (holder,)
                assert not catalog_free(probe)
            # between the transactions: committed, still held
            assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
            assert holders(probe) == [(holder, True, "ExclusiveLock")]
            assert not catalog_free(probe)
            with s.transaction() as tx:
                assert tx.conn.execute("SELECT pg_backend_pid()").fetchone() == (
                    holder,
                )
                assert not catalog_free(probe)
            assert not catalog_free(probe)
        assert catalog_free(probe)


def test_lock_is_taken_outside_a_transaction_on_the_catalog_key(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s, catalog_lock(s):
        # session-level: held while the connection is idle (not in a transaction)
        assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
        assert holders(probe) == [(pid_of(s.conn), True, "ExclusiveLock")]
        row = probe.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = %s",
            (pid_of(s.conn),),
        ).fetchone()
        assert row == (1,)  # one lock, the catalog key only


# CHK-M7-142 ------------------------------------------------------------------


def test_released_when_the_block_raises(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s:
        with pytest.raises(ValueError, match="boom"), catalog_lock(s):
            assert not catalog_free(probe)
            raise ValueError("boom")
        assert catalog_free(probe)  # released before the session ends
        with catalog_lock(s):  # and the session can take it again
            assert not catalog_free(probe)
    assert catalog_free(probe)


def test_released_when_a_transaction_inside_raises(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s:
        with pytest.raises(RuntimeError), catalog_lock(s), s.transaction():
            raise RuntimeError("store failed")
        assert catalog_free(probe)
        with s.transaction() as tx:  # session still usable
            assert tx.conn.execute("SELECT 1").fetchone() == (1,)


def test_released_when_the_connection_closes(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s, catalog_lock(s):
        assert not catalog_free(probe)
        s.conn.close()
        assert wait_until(lambda: catalog_free(probe), 10)
    # the pool replaced the closed connection
    with db.transaction() as tx:
        assert tx.conn.execute("SELECT 1").fetchone() == (1,)


def test_released_when_the_backend_is_terminated(
    db: AppDatabase, migrated_db: PgServer, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s, catalog_lock(s):
        victim = pid_of(s.conn)
        with migrated_db.connect("bitscan_app") as killer:
            killer.execute("SELECT pg_terminate_backend(%s)", (victim,))
        assert wait_until(lambda: catalog_free(probe), 10)
    with db.transaction() as tx:
        assert tx.conn.execute("SELECT 1").fetchone() == (1,)


# CHK-M7-144 ------------------------------------------------------------------


def test_connection_goes_back_clean(migrated_db: PgServer) -> None:
    one = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=1, connect_timeout_s=3
    )
    one.open()
    try:
        with one.session() as s:
            pid = pid_of(s.conn)
            s.conn.execute("SELECT pg_advisory_lock(42)")  # a stray lock
            with catalog_lock(s):
                pass
        with one.transaction() as tx:
            assert pid_of(tx.conn) == pid  # same pooled connection (max_size=1)
            assert tx.conn.autocommit is False
            row = tx.conn.execute(
                "SELECT count(*) FROM pg_locks"
                " WHERE locktype = 'advisory' AND pid = %s",
                (pid,),
            ).fetchone()
            assert row == (0,)
    finally:
        one.close()


def test_nesting_is_refused(db: AppDatabase) -> None:
    with db.session() as s:
        with pytest.raises(RuntimeError), s.savepoint():
            pass
        with s.transaction():
            with pytest.raises(RuntimeError), s.transaction():
                pass
            with pytest.raises(RuntimeError), db.transaction():
                pass
    with db.transaction():
        with pytest.raises(RuntimeError), db.session():
            pass


def run_bounded(body: Callable[[], None], limit_s: float = 8.0) -> list[BaseException]:
    """Run body on a daemon thread; a hang (self-deadlock) fails, not stalls."""
    errors: list[BaseException] = []

    def wrapped() -> None:
        try:
            body()
        except BaseException as exc:  # reported to the test
            errors.append(exc)

    t = threading.Thread(target=wrapped, daemon=True)
    t.start()
    t.join(limit_s)
    assert not t.is_alive(), "nested session deadlocked on the catalog lock"
    return errors


def test_nested_session_is_refused_and_the_outer_one_stays_clean(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    # TASK-147 r1: a nested session would wait on its own catalog lock forever.
    seen: dict[str, Any] = {}

    def body() -> None:
        with db.session() as s, catalog_lock(s):
            seen["pid"] = pid_of(s.conn)
            try:
                with db.session() as inner, catalog_lock(inner):
                    seen["inner"] = "entered"
            except RuntimeError as exc:
                seen["refused"] = str(exc)
            with s.transaction() as tx:  # the outer session still works
                seen["outer_tx"] = tx.conn.execute("SELECT 1").fetchone()

    assert run_bounded(body) == []
    assert "inner" not in seen
    assert "nested" in seen["refused"] and "session" in seen["refused"]
    assert seen["outer_tx"] == (1,)
    assert catalog_free(probe)
    with db.transaction() as tx:  # the connection went back clean
        assert tx.conn.autocommit is False
        row = tx.conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = %s",
            (seen["pid"],),
        ).fetchone()
        assert row == (0,)


def test_nested_session_without_the_lock_is_refused_too(db: AppDatabase) -> None:
    def body() -> None:
        with db.session(), pytest.raises(RuntimeError, match="nested"), db.session():
            pass

    assert run_bounded(body) == []


def test_another_thread_can_open_a_session_while_one_is_open(
    db: AppDatabase,
) -> None:
    inside, release = threading.Event(), threading.Event()
    other: dict[str, Any] = {}

    def holder() -> None:
        with db.session():
            inside.set()
            assert release.wait(10)

    def second() -> None:
        with db.session() as s, s.transaction() as tx:
            other["row"] = tx.conn.execute("SELECT 2").fetchone()

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert inside.wait(10)
    try:
        assert run_bounded(second) == []
        assert other["row"] == (2,)
    finally:
        release.set()
        t.join(10)


def test_a_session_opens_again_after_a_normal_exit_or_an_error(
    db: AppDatabase,
) -> None:
    def body() -> None:
        with db.session():
            pass
        with pytest.raises(ZeroDivisionError), db.session():
            raise ZeroDivisionError
        with db.session() as s, catalog_lock(s), s.transaction() as tx:
            assert tx.conn.execute("SELECT 3").fetchone() == (3,)

    assert run_bounded(body) == []


def test_savepoint_rollback_drops_its_rows_and_hooks(
    db: AppDatabase, migrated_db: PgServer
) -> None:
    ran: list[str] = []
    seen_at_hook: list[int] = []
    names = [f"m7-sp-{time.monotonic_ns()}-{i}" for i in range(3)]

    def visible() -> int:
        with migrated_db.connect("bitscan_app") as c:
            row = c.execute(
                "SELECT count(*) FROM family WHERE family_name = ANY(%s)", (names,)
            ).fetchone()
            assert row is not None
            return int(row[0])

    with db.session() as s, catalog_lock(s), s.transaction() as tx:
        tx.on_commit(lambda: ran.append("outer"))
        tx.on_commit(lambda: seen_at_hook.append(visible()))
        tx.conn.execute("INSERT INTO family (family_name) VALUES (%s)", (names[0],))
        with pytest.raises(ValueError), s.savepoint():
            tx.conn.execute("INSERT INTO family (family_name) VALUES (%s)", (names[1],))
            tx.on_commit(lambda: ran.append("rejected-file"))
            raise ValueError("file rejected")
        with s.savepoint():
            tx.conn.execute("INSERT INTO family (family_name) VALUES (%s)", (names[2],))
            tx.on_commit(lambda: ran.append("kept-file"))
        assert ran == []  # nothing before COMMIT
    assert ran == ["outer", "kept-file"]
    assert seen_at_hook == [2]  # hooks run after COMMIT: rows already visible
    assert visible() == 2


def test_rolled_back_session_transaction_runs_no_hooks(db: AppDatabase) -> None:
    ran: list[str] = []
    with db.session() as s:
        with pytest.raises(KeyError), s.transaction() as tx:
            tx.on_commit(lambda: ran.append("x"))
            raise KeyError("x")
        with s.transaction() as tx:
            tx.on_commit(lambda: ran.append("y"))
    assert ran == ["y"]


CANARY = "CANARY-m7lock-5c1e9a"


def test_unreachable_database_gives_database_unavailable_without_dsn(
    migrated_db: PgServer,
) -> None:
    params = conninfo_to_dict(migrated_db.dsn("bitscan_app"))
    params.update(port=1, password=CANARY, user="u" + CANARY)
    bad = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=2)
    bad.open()
    try:
        with pytest.raises(DatabaseUnavailable) as info, bad.session():
            pass
        text = str(info.value) + repr(info.value)
        assert CANARY not in text and "127.0.0.1" not in text
        assert info.value.__cause__ is None and info.value.__context__ is None
    finally:
        bad.close()


# TASK-147 r2: session transactions are real transactions (autocommit off),
# so the audit chain can append inside them (found through TASK-152).


def _audit_count(server: PgServer, action: str) -> int:
    with server.connect("bitscan_app") as c:
        row = c.execute(
            "SELECT count(*) FROM audit_log WHERE action = %s", (action,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_audit_append_inside_a_session_transaction(
    db: AppDatabase, migrated_db: PgServer
) -> None:
    from bitscan_manager.repositories.audit_log import PgAuditRepo
    from bitscan_manager.services.audit.chain import append_entry

    action = f"test.m7.session.{time.monotonic_ns()}"
    with db.session() as s, catalog_lock(s):
        with s.transaction() as tx:
            assert tx.conn.autocommit is False
            append_entry(PgAuditRepo(tx.conn), actor="system", action=action)
            assert _audit_count(migrated_db, action) == 0  # not before COMMIT
        assert _audit_count(migrated_db, action) == 1
        with pytest.raises(RuntimeError), s.transaction() as tx:
            append_entry(PgAuditRepo(tx.conn), actor="system", action=action)
            raise RuntimeError("roll back")
        assert _audit_count(migrated_db, action) == 1  # rolled back with it


def test_between_transactions_the_session_is_autocommit_and_idle(
    db: AppDatabase, probe: psycopg.Connection[Any]
) -> None:
    with db.session() as s:
        assert s.conn.autocommit is True
        with s.transaction():
            pass
        assert s.conn.autocommit is True
        assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
        with pytest.raises(KeyError), s.transaction():
            raise KeyError("x")
        assert s.conn.autocommit is True
        assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
        with catalog_lock(s):
            # taken without an implicit transaction: still idle, held, session-level
            assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
            assert holders(probe) == [(pid_of(s.conn), True, "ExclusiveLock")]
        assert s.conn.info.transaction_status == pq.TransactionStatus.IDLE
        assert catalog_free(probe)


def test_commit_failure_closes_the_connection_and_the_pool_replaces_it(
    migrated_db: PgServer,
) -> None:
    one = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=1, connect_timeout_s=3
    )
    one.open()
    try:
        with one.session() as s:
            victim = pid_of(s.conn)
            with pytest.raises((DatabaseUnavailable, psycopg.OperationalError)):
                with s.transaction() as tx:
                    tx.conn.execute("SELECT 1")
                    with migrated_db.connect("bitscan_app") as killer:
                        killer.execute("SELECT pg_terminate_backend(%s)", (victim,))
            assert s.conn.closed or s.conn.broken
        with one.transaction() as tx:
            assert pid_of(tx.conn) != victim
            assert tx.conn.autocommit is False
            row = tx.conn.execute(
                "SELECT count(*) FROM pg_locks"
                " WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            ).fetchone()
            assert row == (0,)
    finally:
        one.close()
