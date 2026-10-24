"""TASK-025: runtime contract and AppDatabase behaviour without PostgreSQL.

Checks CHK-M2-030 to CHK-M2-032, CHK-M2-035 (closed port part) and CHK-M2-037
of tests/m2/test-plan.md. The PostgreSQL half is tests/test_db_pool_pg.py.
"""

import logging
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import PoolClosed, PoolTimeout
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase, DatabaseUnavailable
from bitscan_manager.runtime import (
    Clock,
    Database,
    Runtime,
    SystemClock,
    Tx,
    get_runtime,
)

CANARY = "CANARY-pw-5e1c0b7d93a24f68"
DSN = (
    "host=127.0.0.1 port=1 dbname=bitscan user=bitscan_app"
    f" password={CANARY} sslmode=require"
)


# ------------------------------------------------ CHK-M2-030 typed fakes


class FakeClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


class FakeTx:
    def __init__(self) -> None:
        self.hooks: list[Callable[[], None]] = []

    @property
    def conn(self) -> psycopg.Connection[Any]:
        raise NotImplementedError

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


class FakeDb:
    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        yield FakeTx()

    def ping(self) -> bool:
        return True


class FakeCipher:
    def encrypt(self, seed: bytes) -> str:
        return "vault:v1:" + seed.hex()

    def decrypt(self, ciphertext: str) -> bytes:
        return bytes.fromhex(ciphertext.removeprefix("vault:v1:"))


class FakeGate:
    def refusing(self) -> bool:
        return False

    def wake(self) -> None:
        return None


class FakeLimits:
    def allow_login(self, ip: str) -> bool:
        return True

    def allow_user(self, user_id: int) -> bool:
        return True

    def failed_check_blocked(self, ip: str) -> bool:
        return False

    def record_failed_check(self, ip: str) -> None:
        return None

    # M3 (TASK-057): the agent-route limits; this fake never refuses.
    def allow_agent(self, agent_id: UUID) -> bool:
        return True

    def allow_enrol(self, ip: str) -> bool:
        return True

    def allow_unscheduled_inventory(self, agent_id: UUID) -> bool:
        return True

    def unscheduled_inventory_retry_after(self, agent_id: UUID) -> int:
        return 1


def fake_runtime() -> Runtime:
    clock: Clock = FakeClock(datetime(2026, 10, 21, tzinfo=UTC))
    db: Database = FakeDb()
    return Runtime(
        clock=clock,
        db=db,
        totp_cipher=FakeCipher(),
        sink_gate=FakeGate(),
        limits=FakeLimits(),
    )


def test_runtime_from_fakes_is_frozen_and_lifecycle_defaults_to_none() -> None:
    rt = fake_runtime()
    assert rt.lifecycle is None
    assert rt.clock.now() == datetime(2026, 10, 21, tzinfo=UTC)
    with pytest.raises(AttributeError):
        rt.clock = SystemClock()  # type: ignore[misc]


def test_get_runtime_returns_the_app_runtime_or_503() -> None:
    app = FastAPI()

    @app.get("/r")
    def route(rt: Runtime = Depends(get_runtime)) -> dict[str, str]:  # noqa: B008
        return {"same": str(rt is app.state.runtime)}

    with TestClient(app) as c:
        assert c.get("/r").status_code == 503
        app.state.runtime = object()
        assert c.get("/r").status_code == 503
        app.state.runtime = fake_runtime()
        resp = c.get("/r")
    assert resp.status_code == 200
    assert resp.json() == {"same": "True"}


# --------------------------------------------------- CHK-M2-032 clock


def test_system_clock_is_aware_utc() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= after


# ------------------------------- CHK-M2-031, -037 AppDatabase with a fake pool


class Events(list[str]):
    pass


class FakeConn:
    def __init__(self, events: Events, commit_error: BaseException | None = None):
        self.events = events
        self.commit_error = commit_error
        self.executed: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        if self.commit_error is not None:
            self.events.append("commit-failed")
            raise self.commit_error
        self.events.append("commit")

    def execute(self, query: str) -> None:
        self.executed.append(query)


class FakePool:
    def __init__(self, conn: FakeConn | None, error: BaseException | None = None):
        self.conn = conn
        self.error = error
        self.timeouts: list[float | None] = []

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[FakeConn]:
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        assert self.conn is not None
        yield self.conn


def with_pool(
    monkeypatch: pytest.MonkeyPatch, pool: FakePool, timeout: float = 3.0
) -> AppDatabase:
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=timeout)
    monkeypatch.setattr(db, "_pool", pool)
    return db


def test_hooks_run_in_order_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events = Events()
    db = with_pool(monkeypatch, FakePool(FakeConn(events)), timeout=3.0)
    with db.transaction() as tx:
        tx.on_commit(lambda: events.append("hook1"))
        tx.on_commit(lambda: events.append("hook2"))
        events.append("body")
        assert events == ["begin", "body"]
    assert events == ["begin", "body", "commit", "hook1", "hook2"]


def test_connection_timeout_is_the_configured_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FakePool(FakeConn(Events()))
    db = with_pool(monkeypatch, pool, timeout=1.5)
    with db.transaction():
        pass
    assert pool.timeouts == [1.5]


def test_no_hook_after_a_body_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    events = Events()
    db = with_pool(monkeypatch, FakePool(FakeConn(events)))
    boom = ValueError("body")
    with pytest.raises(ValueError) as info:
        with db.transaction() as tx:
            tx.on_commit(lambda: events.append("hook"))
            raise boom
    assert info.value is boom
    assert events == ["begin", "rollback"]


def test_body_operational_error_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = Events()
    db = with_pool(monkeypatch, FakePool(FakeConn(events)))
    err = psycopg.OperationalError("statement failed")
    with pytest.raises(psycopg.OperationalError) as info:
        with db.transaction() as tx:
            tx.on_commit(lambda: events.append("hook"))
            raise err
    assert info.value is err
    assert "hook" not in events


def test_failed_commit_is_unavailable_and_runs_no_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = Events()
    failure = psycopg.OperationalError(f"server closed the connection {DSN}")
    db = with_pool(monkeypatch, FakePool(FakeConn(events, commit_error=failure)))
    with pytest.raises(DatabaseUnavailable) as info:
        with db.transaction() as tx:
            tx.on_commit(lambda: events.append("hook"))
    assert "hook" not in events
    assert_clean(info.value)


def test_raising_hook_is_logged_by_type_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    events = Events()
    db = with_pool(monkeypatch, FakePool(FakeConn(events)))

    def bad() -> None:
        raise RuntimeError(f"hook text {CANARY}")

    with caplog.at_level(logging.DEBUG):
        with db.transaction() as tx:
            tx.on_commit(bad)
            tx.on_commit(lambda: events.append("hook2"))
    assert events == ["begin", "commit", "hook2"]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert errors[0].exc_info is None
    assert CANARY not in caplog.text
    assert "hook text" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        PoolTimeout(f"couldn't get a connection {DSN}"),
        PoolClosed(f"the pool is closed {CANARY}"),
        psycopg.OperationalError(f'connection to server failed: password "{CANARY}"'),
    ],
    ids=["timeout", "closed", "operational"],
)
def test_unreachable_database_is_scrubbed_and_unchained(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    db = with_pool(monkeypatch, FakePool(None, error))
    with pytest.raises(DatabaseUnavailable) as info:
        with db.transaction():
            pytest.fail("body must not run")
    assert_clean(info.value)
    assert type(error).__name__ in str(info.value)


def assert_clean(exc: BaseException) -> None:
    assert exc.__cause__ is None
    assert exc.__context__ is None
    text = "".join(traceback.format_exception(exc))
    for part in (str(exc), repr(exc), text, *map(str, exc.args)):
        assert CANARY not in part
        assert DSN not in part


def test_nested_transaction_raises_and_the_outer_still_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHK-M2-037."""
    events = Events()
    db = with_pool(monkeypatch, FakePool(FakeConn(events)))
    with db.transaction() as tx:
        tx.on_commit(lambda: events.append("hook"))
        with pytest.raises(RuntimeError):
            with db.transaction():
                pytest.fail("nested body must not run")
    assert events == ["begin", "commit", "hook"]
    with db.transaction():
        pass
    assert events[-2:] == ["begin", "commit"]


def test_transactions_on_two_threads_are_not_nested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = with_pool(monkeypatch, FakePool(FakeConn(Events())))
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold() -> None:
        with db.transaction():
            inside.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    assert inside.wait(5)
    try:
        with db.transaction():
            pass
    except BaseException as exc:  # noqa: BLE001
        errors.append(exc)
    release.set()
    t.join(5)
    assert errors == []


class ProbeConn:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def __enter__(self) -> "ProbeConn":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("closed")

    def execute(self, query: str) -> None:
        self.calls.append(query)


def test_ping_probes_a_fresh_bounded_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHK-M2-036 (unit): own connection, client-side bound, never raises."""
    calls: list[str] = []
    kwargs: list[dict[str, Any]] = []

    def connect(dsn: str, **kw: Any) -> ProbeConn:
        assert dsn == DSN
        kwargs.append(kw)
        return ProbeConn(calls)

    monkeypatch.setattr("bitscan_manager.db.pool.psycopg.connect", connect)
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=1)
    assert db.ping() is True
    assert calls == ["SELECT 1", "closed"]
    assert kwargs[0]["autocommit"] is True
    assert 1 <= kwargs[0]["connect_timeout"] <= 2
    assert "statement_timeout" in kwargs[0].get("options", "")


@pytest.mark.parametrize(
    "error", [psycopg.OperationalError(f"pw {CANARY}"), RuntimeError(CANARY)]
)
def test_ping_failure_is_false_and_silent(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    def connect(dsn: str, **kw: Any) -> ProbeConn:
        raise error

    monkeypatch.setattr("bitscan_manager.db.pool.psycopg.connect", connect)
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=1)
    with caplog.at_level(logging.DEBUG):
        assert db.ping() is False
    assert CANARY not in caplog.text


def test_ping_is_bounded_and_one_probe_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started: list[float] = []

    def connect(dsn: str, **kw: Any) -> ProbeConn:
        started.append(time.monotonic())
        release.wait(30)
        return ProbeConn([])

    monkeypatch.setattr("bitscan_manager.db.pool.psycopg.connect", connect)
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=1)
    t0 = time.monotonic()
    assert db.ping() is False
    assert 1.5 <= time.monotonic() - t0 < 3.5
    t1 = time.monotonic()
    assert db.ping() is False  # first probe still stuck: no second thread
    assert time.monotonic() - t1 < 0.5
    assert len(started) == 1
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and db.ping() is not True:
        time.sleep(0.1)
    assert db.ping() is True


def test_ping_is_false_within_bound_on_a_silent_server() -> None:
    """CHK-M2-036: a server that accepts TCP but never answers (as a paused
    container does) gives False in about 2 s, and a second ping is not slower."""
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            held.append(conn)  # never read, never answer

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    dsn = DSN.replace("port=1", f"port={port}")
    db = AppDatabase(SecretStr(dsn), connect_timeout_s=3)
    try:
        for _ in range(2):
            started = time.monotonic()
            assert db.ping() is False
            assert time.monotonic() - started < 3.5
    finally:
        stop.set()
        t.join(2)
        for conn in held:
            conn.close()
        listener.close()


# --------------------------- CHK-M2-035 real driver against a closed port


def test_closed_port_gives_scrubbed_unavailable_and_no_canary_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=1)
    assert CANARY not in repr(db)
    with caplog.at_level(logging.DEBUG):
        db.open()
        try:
            started = time.monotonic()
            with pytest.raises(DatabaseUnavailable) as info:
                with db.transaction():
                    pytest.fail("body must not run")
            assert time.monotonic() - started < 10
            assert db.ping() is False
            time.sleep(1.5)  # let the pool's background connect attempts log
        finally:
            db.close()
    assert_clean(info.value)
    assert CANARY not in caplog.text
    for record in caplog.records:
        assert CANARY not in record.getMessage()
        assert CANARY not in str(record.args)
    assert db.ping() is False  # closed pool


def test_pool_logger_records_are_scrubbed_while_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A psycopg.pool record that quotes the DSN or password is scrubbed."""
    pool_log = logging.getLogger("psycopg.pool")
    db = AppDatabase(SecretStr(DSN), connect_timeout_s=1)
    with caplog.at_level(logging.DEBUG):
        db.open()
        try:
            pool_log.warning("conninfo was %s", DSN)
            pool_log.warning("password %s rejected", CANARY)
        finally:
            db.close()
    messages = [r.getMessage() for r in caplog.records if r.name == "psycopg.pool"]
    assert any("conninfo was" in m for m in messages)
    assert any("rejected" in m for m in messages)
    assert all(CANARY not in m and DSN not in m for m in messages)


def test_unparsable_dsn_never_shows_any_part(caplog: pytest.LogCaptureFixture) -> None:
    bad = f"host='127.0.0.1 password={CANARY}"
    db = AppDatabase(SecretStr(bad), connect_timeout_s=1)
    with caplog.at_level(logging.DEBUG):
        db.open()
        try:
            with pytest.raises(DatabaseUnavailable) as info:
                with db.transaction():
                    pytest.fail("body must not run")
        finally:
            db.close()
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert CANARY not in str(info.value)
    assert "127.0.0.1" not in str(info.value)
    assert CANARY not in caplog.text
