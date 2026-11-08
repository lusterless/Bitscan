"""The bitscan_app connection pool (TS §5.3 L1049; TASK-025 plan), also used,
under its own name and DSN, for the bitscan_retention pool (TASK-245).

Transactions are READ COMMITTED and never autocommit, as the audit chain
needs (PgAuditRepo). On-commit hooks run only after COMMIT. No part of a DSN
(host, port, user, database, password) appears in an error or in any psycopg
or psycopg_pool log record.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final

import psycopg
from psycopg import IsolationLevel
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout
from pydantic import SecretStr

log = logging.getLogger(__name__)
# Every logger psycopg and psycopg_pool use (logger filters do not apply to
# child loggers, so each is listed).
DRIVER_LOGGERS: Final = (
    "psycopg",
    "psycopg.pool",
    "psycopg.pq",
    "psycopg.debug",
    "psycopg.transaction",
    "psycopg.waiting",
    "psycopg_pool",
    "psycopg_pool.sched",
    "psycopg_pool.sched_async",
)
PING_TIMEOUT_S: Final = 2.0


class DatabaseUnavailable(Exception):
    """The database could not be reached; the message holds no DSN."""


class DriverLogFilter(logging.Filter):
    """No part of a DSN reaches a log (user decision 2026-10-22): a driver
    record keeps its fixed text, every argument is replaced by its type name
    (libpq messages name the host, port, user and database; connection reprs
    too), and any exception is dropped."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else (record.args,)
        names = tuple(type(a).__name__ for a in args) if record.args else ()
        try:
            record.msg = str(record.msg) % names if names else str(record.msg)
        except (TypeError, ValueError):
            record.msg = str(record.msg)
        record.args = None
        record.exc_info = None
        record.exc_text = None
        return True


_DRIVER_FILTER: Final = DriverLogFilter()
for _name in DRIVER_LOGGERS:
    logging.getLogger(_name).addFilter(_DRIVER_FILTER)


class _Tx:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn
        self.hooks: list[Callable[[], None]] = []

    @property
    def conn(self) -> psycopg.Connection[Any]:
        return self._conn

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


def _configure(conn: psycopg.Connection[Any]) -> None:
    conn.isolation_level = IsolationLevel.READ_COMMITTED


def _unavailable(exc: BaseException) -> DatabaseUnavailable:
    return DatabaseUnavailable(
        f"database unavailable: {type(exc).__name__}"  # never the libpq text
    )


def _run_hooks(tx: _Tx | None) -> None:
    for hook in tx.hooks if tx is not None else []:
        try:
            hook()
        except Exception as exc:  # the commit stands; report the type only
            log.error("on-commit hook failed: %s", type(exc).__name__)


class _Session:
    """One pooled connection pinned for several transactions, so that a
    session-level advisory lock spans them (TS §4.1 "Locking"; design note
    D4). Outside transaction() the connection is in autocommit; that is
    where catalog_lock() takes and releases the lock. Inside it, autocommit
    is off and the transaction is READ COMMITTED, like transaction()."""

    def __init__(self, conn: psycopg.Connection[Any], local: threading.local):
        self._conn = conn
        self._local = local
        self._tx: _Tx | None = None

    @property
    def conn(self) -> psycopg.Connection[Any]:
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[_Tx]:
        if self._tx is not None or getattr(self._local, "open", False):
            raise RuntimeError("nested transactions on a session are not supported")
        error: DatabaseUnavailable | None = None
        tx: _Tx | None = None
        in_body = False
        self._local.open = True
        try:
            # A real transaction, never autocommit, as the audit chain needs
            # (PgAuditRepo refuses autocommit); autocommit returns afterwards
            # for catalog_lock().
            self._conn.autocommit = False
            with self._conn.transaction():
                tx = self._tx = _Tx(self._conn)
                in_body = True
                yield tx
                in_body = False
        except psycopg.OperationalError as exc:
            if in_body:
                raise  # the caller's own statement failed; keep its error
            error = _unavailable(exc)
        finally:
            self._tx = None
            self._local.open = False
            self._restore_autocommit()
        if error is not None:
            raise error
        _run_hooks(tx)

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        tx = self._tx
        if tx is None:
            raise RuntimeError("savepoint() needs an open session transaction")
        mark = len(tx.hooks)
        try:
            with self._conn.transaction():
                yield
        except BaseException:
            del tx.hooks[mark:]  # a rolled-back savepoint's hooks never run
            raise

    def _restore_autocommit(self) -> None:
        """After COMMIT or ROLLBACK the connection is idle again; if it is
        not (or is broken), close it, which also ends its session locks."""
        try:
            self._conn.autocommit = True
        except Exception as exc:
            log.warning("session autocommit restore failed: %s", type(exc).__name__)
            self._conn.close()

    def release(self) -> None:
        """Before the connection goes back to the pool: drop every
        session-level lock and leave autocommit. If that fails, close the
        connection; that ends its locks and makes the pool discard it."""
        try:
            self._conn.execute("SELECT pg_advisory_unlock_all()")
            self._conn.autocommit = False
        except Exception as exc:
            log.warning("session release failed: %s", type(exc).__name__)
            self._conn.close()


class AppDatabase:
    def __init__(
        self,
        dsn: SecretStr,
        *,
        min_size: int = 1,
        max_size: int = 10,
        connect_timeout_s: float = 5.0,
        name: str = "bitscan_app",  # the pool's name only; the DSN picks the role
    ) -> None:
        secret = dsn.get_secret_value()
        self._dsn = dsn
        self._timeout = connect_timeout_s
        self._local = threading.local()
        # Per instance and per context (thread or asyncio task).
        self._session_open: ContextVar[bool] = ContextVar(
            f"bitscan_session_open_{id(self)}", default=False
        )
        self._ping_lock = threading.Lock()
        self._ping_thread: threading.Thread | None = None
        self._pool: ConnectionPool[psycopg.Connection[Any]] = ConnectionPool(
            secret,
            kwargs={
                "autocommit": False,
                "connect_timeout": max(1, int(connect_timeout_s)),
            },
            min_size=min_size,
            max_size=max_size,
            open=False,
            configure=_configure,
            timeout=connect_timeout_s,
            name=name,
        )

    def open(self) -> None:
        """Start the pool; does not wait for (or fail on) the database."""
        self._pool.open(wait=False)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def session(self) -> Iterator[_Session]:
        """Pin one connection for several transactions (see _Session)."""
        if getattr(self._local, "open", False):
            raise RuntimeError("AppDatabase.session() inside a transaction")
        # A nested session taking catalog_lock while the outer one holds it
        # would wait on itself for ever, so refuse nesting outright.
        if self._session_open.get():
            raise RuntimeError("nested AppDatabase.session() is not supported")
        token = self._session_open.set(True)
        error: DatabaseUnavailable | None = None
        in_body = False
        try:
            with self._pool.connection(timeout=self._timeout) as conn:
                conn.autocommit = True
                session = _Session(conn, self._local)
                try:
                    in_body = True
                    yield session
                    in_body = False
                finally:
                    session.release()
        except (PoolTimeout, PoolClosed, psycopg.OperationalError) as exc:
            if in_body:
                raise
            error = _unavailable(exc)
        finally:
            self._session_open.reset(token)
        if error is not None:
            raise error  # outside the except block, so no driver text chains

    @contextmanager
    def transaction(self) -> Iterator[_Tx]:
        if getattr(self._local, "open", False):
            raise RuntimeError("nested AppDatabase.transaction() is not supported")
        error: DatabaseUnavailable | None = None
        tx: _Tx | None = None
        in_body = False
        self._local.open = True
        try:
            with self._pool.connection(timeout=self._timeout) as conn:
                with conn.transaction():
                    tx = _Tx(conn)
                    in_body = True
                    yield tx
                    in_body = False
        except (PoolTimeout, PoolClosed, psycopg.OperationalError) as exc:
            if in_body:
                raise  # the caller's own statement failed; keep its error
            error = _unavailable(exc)
        finally:
            self._local.open = False
        if error is not None:
            # Raised outside the except block, so the driver error (which may
            # name the host) is not chained.
            raise error
        _run_hooks(tx)

    def ping(self, timeout_s: float = PING_TIMEOUT_S) -> bool:
        """True if a fresh bitscan_app connection answers SELECT 1 within
        timeout_s. Never raises and never blocks longer: a server that stops
        answering (statement_timeout is server-side) leaves the probe thread
        waiting, and later pings return False until it ends."""
        with self._ping_lock:
            if self._ping_thread is not None and self._ping_thread.is_alive():
                return False
            result: list[bool] = []
            thread = threading.Thread(
                target=self._probe, args=(result,), name="db-ping", daemon=True
            )
            self._ping_thread = thread
            thread.start()
        thread.join(timeout_s)
        return result == [True]

    def _probe(self, result: list[bool]) -> None:
        # Its own connection, outside the pool, so a stuck probe holds no
        # pooled connection.
        try:
            with psycopg.connect(
                self._dsn.get_secret_value(),
                autocommit=True,
                connect_timeout=max(1, int(PING_TIMEOUT_S)),
                options="-c statement_timeout=2000",
            ) as conn:
                conn.execute("SELECT 1")
            result.append(True)
        except Exception:
            result.append(False)
