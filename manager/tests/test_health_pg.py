"""REQ-056 on PostgreSQL: /readyz on a migrated database (TASK-044).

Checks CHK-M2-241 to CHK-M2-245 and CHK-M2-249 of tests/m2/test-plan.md
(TS §8.3 Integration: /readyz fails when the inventory system_schedule row is
missing). Rows bitscan_app cannot change are changed as bitscan_owner and
restored after each case.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from bitscan_manager.app import create_app
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import sweep
from .conftest import PgServer
from .test_db_pool_pg import PausableProxy
from .test_runtime import FakeCipher, FakeClock, FakeGate, FakeLimits

pytestmark = pytest.mark.pg


def make_runtime(db: AppDatabase) -> Runtime:
    return Runtime(
        clock=FakeClock(datetime(2026, 10, 21, tzinfo=UTC)),
        db=db,
        totp_cipher=FakeCipher(),
        sink_gate=FakeGate(),
        limits=FakeLimits(),
    )


@contextmanager
def app_for(dsn: str) -> Iterator[tuple[TestClient, AppDatabase]]:
    db = AppDatabase(SecretStr(dsn), connect_timeout_s=3)
    db.open()
    try:
        with TestClient(create_app(make_runtime(db))) as client:
            yield client, db
    finally:
        closer = threading.Thread(target=db.close, daemon=True)
        closer.start()
        closer.join(10)


def bounded_get(client: TestClient, path: str, limit_s: float = 15) -> Any:
    """A request that hangs fails the test instead of stalling the run."""
    out: list[Any] = []
    worker = threading.Thread(target=lambda: out.append(client.get(path)), daemon=True)
    worker.start()
    worker.join(limit_s)
    assert out, f"GET {path} did not answer within {limit_s} s"
    return out[0]


def detail(resp: Any) -> str:
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert set(body) == {"type", "title", "status", "detail", "instance"}
    return str(body["detail"])


@pytest.fixture
def client(migrated_db: PgServer) -> Iterator[TestClient]:
    with app_for(migrated_db.dsn("bitscan_app")) as (c, _):
        yield c


Stmt = tuple[str, tuple[Any, ...]]


@contextmanager
def as_owner(server: PgServer, change: Stmt, restore: Stmt) -> Iterator[None]:
    with server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        c.execute(*change)
    try:
        yield
    finally:
        with server.connect("bitscan_migrate") as c:
            c.execute("SET ROLE bitscan_owner")
            c.execute(*restore)


# ------------------------------------------------------------ CHK-M2-241


def test_readyz_ok_on_a_freshly_migrated_database(client: TestClient) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


# ------------------------------------------------------ CHK-M2-242, -243

SCHEDULE_ROWS = {"inventory": 21600, "offline_sweep": 60, "retention": 86400}


@pytest.mark.parametrize("kind", sorted(SCHEDULE_ROWS))
def test_missing_schedule_row_is_503_system_schedule(
    migrated_db: PgServer, client: TestClient, kind: str
) -> None:
    change: Stmt = ("DELETE FROM system_schedule WHERE job_kind = %s", (kind,))
    restore: Stmt = (
        "INSERT INTO system_schedule (job_kind, interval_s) VALUES (%s, %s)",
        (kind, SCHEDULE_ROWS[kind]),
    )
    with as_owner(migrated_db, change, restore):
        assert detail(client.get("/readyz")) == "system_schedule"
    assert client.get("/readyz").status_code == 200


def test_stale_revision_is_503_migrations(
    migrated_db: PgServer, client: TestClient
) -> None:
    with migrated_db.connect("bitscan_app") as c:
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()
    assert head is not None
    with as_owner(
        migrated_db,
        ("UPDATE alembic_version SET version_num = %s", ("m0004",)),
        ("UPDATE alembic_version SET version_num = %s", (head[0],)),
    ):
        assert detail(client.get("/readyz")) == "migrations"
    assert client.get("/readyz").status_code == 200


def test_unreachable_database_is_503_db(migrated_db: PgServer) -> None:
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params["port"] = 1
    with app_for(make_conninfo("", **params)) as (c, _):
        started = time.monotonic()
        assert detail(bounded_get(c, "/readyz")) == "db"
        assert time.monotonic() - started < 6
        assert c.get("/healthz").status_code == 200


def test_503_bodies_name_only_the_check(migrated_db: PgServer) -> None:
    """CHK-M2-243: no DSN, host, port, role or driver message."""
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params["port"] = 1
    with app_for(make_conninfo("", **params)) as (c, _):
        resp = bounded_get(c, "/readyz")
    secrets = [
        str(params["password"]),
        "bitscan_app",
        "127.0.0.1",
        "port=1",
        "connection",
        "psycopg",
        "postgresql",
    ]
    assert sweep(secrets, resp.text, *resp.headers.values()) == []
    assert resp.json()["detail"] == "db"


# ------------------------------------------------------------ CHK-M2-244


def table_counters(server: PgServer) -> dict[str, tuple[int, int, int]]:
    with server.connect("bitscan_app") as c:
        c.execute("SELECT pg_stat_clear_snapshot()")
        rows = c.execute(
            "SELECT relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables"
        ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_neither_route_writes(migrated_db: PgServer, client: TestClient) -> None:
    time.sleep(1)
    before = table_counters(migrated_db)
    for _ in range(50):
        client.get("/healthz")
        client.get("/readyz")
    time.sleep(1.5)  # statistics are flushed asynchronously
    assert table_counters(migrated_db) == before


# ------------------------------------------------------------ CHK-M2-245


def test_health_routes_carry_headers_and_ignore_tokens(client: TestClient) -> None:
    for path in ("/healthz", "/readyz"):
        resp = client.get(path, headers={"Authorization": "Bearer bsu_" + "A" * 43})
        assert resp.status_code == 200
        assert resp.headers["content-security-policy"].startswith("default-src 'self'")
        assert resp.headers["strict-transport-security"] == "max-age=31536000"
    assert {client.get("/readyz").status_code for _ in range(100)} == {200}


# ------------------------------------------------------------ CHK-M2-249


def proxied(server: PgServer) -> tuple[PausableProxy, str]:
    proxy = PausableProxy(server.host, server.port)
    params: dict[str, Any] = dict(conninfo_to_dict(server.dsn("bitscan_app")))
    params.update(host="127.0.0.1", port=proxy.port)
    return proxy, make_conninfo("", **params)


def test_readyz_bounded_when_the_database_stops_answering(
    migrated_db: PgServer,
) -> None:
    proxy, dsn = proxied(migrated_db)
    try:
        with app_for(dsn) as (c, db):
            assert (
                bounded_get(c, "/readyz").status_code == 200
            )  # pooled connections open
            proxy.paused.set()
            for _ in range(3):
                started = time.monotonic()
                resp = bounded_get(c, "/readyz")
                assert time.monotonic() - started < 5, "readyz not bounded"
                assert detail(resp) == "db"
                assert bounded_get(c, "/healthz").status_code == 200
            proxy.paused.clear()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if bounded_get(c, "/readyz").status_code == 200:
                    break
                time.sleep(0.5)
            assert bounded_get(c, "/readyz").status_code == 200
    finally:
        proxy.paused.clear()
        proxy.close()


def test_readyz_bounded_when_the_stall_hits_the_later_checks(
    migrated_db: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proxy pauses only after ping() has answered, so the stall lands on
    the revision or schedule query."""
    proxy, dsn = proxied(migrated_db)
    try:
        with app_for(dsn) as (c, db):
            assert bounded_get(c, "/readyz").status_code == 200
            real_ping: Callable[[], bool] = db.ping

            def ping_then_pause() -> bool:
                ok = real_ping()
                proxy.paused.set()
                return ok

            monkeypatch.setattr(db, "ping", ping_then_pause)
            for _ in range(3):
                started = time.monotonic()
                resp = bounded_get(c, "/readyz")
                assert time.monotonic() - started < 5, "later checks not bounded"
                assert resp.status_code == 503
            monkeypatch.undo()
            proxy.paused.clear()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if bounded_get(c, "/readyz").status_code == 200:
                    break
                time.sleep(0.5)
            assert bounded_get(c, "/readyz").status_code == 200
    finally:
        proxy.paused.clear()
        proxy.close()
