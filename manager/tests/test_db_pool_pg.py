"""TASK-025: the bitscan_app pool on PostgreSQL.

Checks CHK-M2-033 to CHK-M2-036 of tests/m2/test-plan.md (TP-M2-03).
TS §5.3 L1049 (bitscan_app), L1051 (the audit lock needs a real transaction).
"""

import logging
import threading
import time
import traceback
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase, DatabaseUnavailable
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.audit.chain import append_entry

from .conftest import PgServer

pytestmark = pytest.mark.pg

CANARY = "CANARY-pgpw-9d2e4c71a0b3f586"


def bounded_ping(db: AppDatabase, limit_s: float = 10.0) -> bool | None:
    """Call db.ping() on a daemon thread and give up after limit_s, so an
    implementation that hangs fails the test instead of stalling the run.
    Returns None when the call did not return in time."""
    out: list[bool] = []
    worker = threading.Thread(target=lambda: out.append(db.ping()), daemon=True)
    worker.start()
    worker.join(limit_s)
    return out[0] if out else None


def bounded_close(db: AppDatabase, limit_s: float = 10.0) -> None:
    worker = threading.Thread(target=db.close, daemon=True)
    worker.start()
    worker.join(limit_s)


@pytest.fixture
def pool(migrated_db: PgServer) -> Iterator[AppDatabase]:
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    db.open()
    try:
        yield db
    finally:
        db.close()


def count_action(server: PgServer, action: str) -> int:
    with server.connect("bitscan_app") as c:
        row = c.execute(
            "SELECT count(*) FROM audit_log WHERE action = %s", (action,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_connections_are_bitscan_app_read_committed_not_autocommit(
    pool: AppDatabase,
) -> None:
    """CHK-M2-033."""
    seen: list[tuple[Any, ...]] = []
    barrier = threading.Barrier(3)

    def worker() -> None:
        with pool.transaction() as tx:
            barrier.wait(10)  # three connections at once
            row = tx.conn.execute(
                "SELECT session_user::text, current_user::text,"
                " current_setting('transaction_isolation'), r.rolsuper"
                " FROM pg_roles r WHERE r.rolname = session_user"
            ).fetchone()
            assert row is not None
            seen.append((*row, tx.conn.autocommit, tx.conn.info.backend_pid))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(seen) == 3
    assert len({s[-1] for s in seen}) == 3
    for s in seen:
        assert s[:5] == ("bitscan_app", "bitscan_app", "read committed", False, False)


def test_audit_append_commits_and_hooks_see_the_committed_row(
    pool: AppDatabase, migrated_db: PgServer
) -> None:
    """CHK-M2-033, -034: the hook runs after COMMIT (another session sees it)."""
    action = "test.pool_commit"
    before = count_action(migrated_db, action)
    seen_in_hook: list[int] = []
    with pool.transaction() as tx:
        entry = append_entry(PgAuditRepo(tx.conn), actor="system", action=action)
        tx.on_commit(lambda: seen_in_hook.append(count_action(migrated_db, action)))
        assert count_action(migrated_db, action) == before  # not yet visible
    assert seen_in_hook == [before + 1]
    with migrated_db.connect("bitscan_app") as c:
        row = c.execute(
            "SELECT row_hash FROM audit_log WHERE audit_id = %s", (entry.audit_id,)
        ).fetchone()
    assert row == (entry.row_hash,)


def test_rollback_runs_no_hook_and_keeps_nothing(
    pool: AppDatabase, migrated_db: PgServer
) -> None:
    """CHK-M2-033, -034."""
    action = "test.pool_rollback"
    hooks: list[str] = []
    with pytest.raises(LookupError):
        with pool.transaction() as tx:
            append_entry(PgAuditRepo(tx.conn), actor="system", action=action)
            tx.on_commit(lambda: hooks.append("ran"))
            raise LookupError("rollback")
    assert hooks == []
    assert count_action(migrated_db, action) == 0


def test_sql_error_in_the_body_propagates_and_the_pool_recovers(
    pool: AppDatabase,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pool.transaction() as tx:
            tx.conn.execute("DELETE FROM audit_log")
    with pytest.raises(psycopg.OperationalError) as info:
        with pool.transaction() as tx:
            tx.conn.execute("SELECT pg_terminate_backend(pg_backend_pid())")
    assert not isinstance(info.value, DatabaseUnavailable)
    for _ in range(5):
        with pool.transaction() as tx:
            assert tx.conn.execute("SELECT 1").fetchone() == (1,)


def test_ping_true_on_the_migrated_database(migrated_db: PgServer) -> None:
    """CHK-M2-036: ping reports whether the database answers (own connection)."""
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    try:
        assert bounded_ping(db) is True
    finally:
        bounded_close(db)


def _with_password(dsn: str, password: str) -> str:
    params: dict[str, Any] = dict(conninfo_to_dict(dsn))
    params["password"] = password
    return make_conninfo("", **params)


def test_wrong_password_is_scrubbed_everywhere(
    migrated_db: PgServer, caplog: pytest.LogCaptureFixture
) -> None:
    """CHK-M2-035: the canary password never appears in errors, chains or logs."""
    dsn = _with_password(migrated_db.dsn("bitscan_app"), CANARY)
    db = AppDatabase(SecretStr(dsn), connect_timeout_s=2)
    with caplog.at_level(logging.DEBUG):
        db.open()
        try:
            with pytest.raises(DatabaseUnavailable) as info:
                with db.transaction():
                    pytest.fail("body must not run")
            assert bounded_ping(db) is False
            time.sleep(1.5)
        finally:
            db.close()
    exc = info.value
    assert exc.__cause__ is None and exc.__context__ is None
    text = "".join(traceback.format_exception(exc)) + repr(exc) + repr(db)
    assert CANARY not in text
    assert dsn not in text
    assert CANARY not in caplog.text
    for record in caplog.records:
        assert CANARY not in record.getMessage()


def test_refused_dsn_leaves_no_dsn_content_anywhere(
    migrated_db: PgServer, caplog: pytest.LogCaptureFixture
) -> None:
    """CHK-M2-035a, decisions 2026-10-22 (TASK-046 ruling (a)): no part of a DSN
    (host, port, user, database, password) in the error, its chain or any
    psycopg / psycopg_pool log record. host is a canary with the real hostaddr,
    so libpq connects and its refusal names the host and the user."""
    import socket

    canaries = {
        "host": "canary-pghost-3b7d0e91c2a4f658",
        "user": "CANARY-pguser-5e1a9c07d3b2f846",
        "dbname": "CANARY-pgdb-8f0b2d6c4e1a9357",
        "password": "CANARY-pgpw2-1c9e7a3f5b0d2468",
    }
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params.update(canaries, hostaddr=socket.gethostbyname(str(migrated_db.host)))
    db = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=2)
    with caplog.at_level(logging.DEBUG):
        db.open()
        try:
            with pytest.raises(DatabaseUnavailable) as info:
                with db.transaction():
                    pytest.fail("body must not run")
            assert bounded_ping(db) is False
            time.sleep(2.5)  # several pool reconnect attempts
        finally:
            bounded_close(db)
    exc = info.value
    prefix, _, type_name = str(exc).partition("database unavailable: ")
    assert prefix == "" and type_name.isidentifier(), str(exc)
    assert exc.__cause__ is None and exc.__context__ is None
    driver = [r for r in caplog.records if r.name.split(".")[0].startswith("psycopg")]
    assert driver, "no psycopg record captured: the refusal was not logged at all"
    texts = [
        "".join(traceback.format_exception(exc)),
        repr(exc),
        caplog.text,
        *(r.getMessage() for r in caplog.records),
        *(repr(r.args) for r in caplog.records),
        *(
            "".join(traceback.format_exception(*r.exc_info))
            for r in caplog.records
            if r.exc_info
        ),
    ]
    for name, canary in canaries.items():
        assert all(canary not in t for t in texts), name
    port_text = f"port {migrated_db.port}"
    assert all(port_text not in t for t in texts)


class PausableProxy:
    """TCP proxy to PostgreSQL that can stop forwarding while keeping every
    socket open: the client then sees a server that stops answering, as with
    a paused container, without touching the container (REQ-032 harness)."""

    def __init__(self, host: str, port: int) -> None:
        import socket

        self.upstream = (host, port)
        self.paused = threading.Event()
        self.stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port: int = self.sock.getsockname()[1]
        self.sockets: list[Any] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        import socket

        while not self.stop.is_set():
            try:
                client, _ = self.sock.accept()
            except OSError:
                continue
            server = socket.create_connection(self.upstream, timeout=5)
            self.sockets += [client, server]
            for a, b in ((client, server), (server, client)):
                threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    def _pump(self, src: Any, dst: Any) -> None:
        import select

        while not self.stop.is_set():
            if self.paused.is_set():
                time.sleep(0.05)
                continue
            ready, _, _ = select.select([src], [], [], 0.1)
            if not ready:
                continue
            try:
                data = src.recv(65536)
            except OSError:
                return
            if not data:
                return
            try:
                dst.sendall(data)
            except OSError:
                return

    def close(self) -> None:
        self.stop.set()
        for s in self.sockets:
            s.close()
        self.sock.close()


def test_ping_is_false_within_bound_when_an_open_server_stops_answering(
    migrated_db: PgServer,
) -> None:
    """CHK-M2-036: round 1 hung here for over 60 s (docker pause probe).

    Every ping and the close run under bounded_ping/bounded_close, so a ping
    that blocks fails this test in seconds (None is not False)."""
    proxy = PausableProxy(migrated_db.host, migrated_db.port)
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params.update(host="127.0.0.1", port=proxy.port)
    db = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=3)
    db.open()
    try:
        with db.transaction() as tx:  # a live pooled connection through the proxy
            assert tx.conn.execute("SELECT 1").fetchone() == (1,)
        assert bounded_ping(db) is True
        proxy.paused.set()
        for _ in range(2):
            started = time.monotonic()
            result = bounded_ping(db, limit_s=10)
            elapsed = time.monotonic() - started
            assert result is not None, f"ping() blocked for over {elapsed:.0f} s"
            assert result is False
            assert elapsed < 5
        proxy.paused.clear()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and bounded_ping(db) is not True:
            time.sleep(0.5)
        assert bounded_ping(db) is True
    finally:
        proxy.paused.clear()
        proxy.close()
        bounded_close(db)
