"""REQ-056, REQ-036 without PostgreSQL: health routes (TASK-044).

Checks CHK-M2-240, -246, -247 and the unit side of -245 and -249 of
tests/m2/test-plan.md. TS §8.4 L1292 (/healthz liveness; /readyz: DB
reachable, migrations current, system_schedule rows present), #5 (outside
/api/v1, no token, no rate limit, security headers; 200 {"status": "ok"};
503 problem naming db, migrations or system_schedule only).
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bitscan_manager.api import health as health_api
from bitscan_manager.app import create_app
from bitscan_manager.runtime import Runtime, Tx

from .test_runtime import FakeCipher, FakeClock, FakeGate, FakeLimits

CSP = (
    "default-src 'self'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'"
)
HEAD = health_api.packaged_head()
DSN_CANARY = "postgresql://bitscan_app:CANARY-dsn-77a1@db.internal:5432/bitscan"


class Conn:
    """Answers the three readiness queries from settable values."""

    def __init__(self, db: "Db") -> None:
        self.db = db

    def execute(self, query: str, params: Any = None) -> "Conn":
        self.db.queries.append(query)
        if self.db.stall is not None:
            self.db.stall.wait(30)
        if "alembic_version" in query:
            self._rows: list[tuple[Any, ...]] = [(r,) for r in self.db.revisions]
        elif "system_schedule" in query:
            self._rows = [(k,) for k in self.db.kinds]
        else:
            self._rows = []
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeTx:
    def __init__(self, db: "Db") -> None:
        self._conn = Conn(db)

    @property
    def conn(self) -> Any:
        return self._conn

    def on_commit(self, hook: Callable[[], None]) -> None:
        raise AssertionError("readiness must not write")


class Db:
    def __init__(self) -> None:
        self.up = True
        self.revisions: list[str] = [HEAD or "head"]
        self.kinds = {"inventory", "offline_sweep", "retention"}
        self.queries: list[str] = []
        self.pings = 0
        self.stall: threading.Event | None = None
        self.tx_fails = False
        self.ping_ok: bool | None = None

    def ping(self) -> bool:
        self.pings += 1
        return self.up if self.ping_ok is None else self.ping_ok

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        if not self.up or self.tx_fails:
            raise ConnectionError(f"connection to {DSN_CANARY} failed")
        yield FakeTx(self)


def runtime(db: Db) -> Runtime:
    return Runtime(
        clock=FakeClock(datetime(2026, 10, 21, tzinfo=UTC)),
        db=db,
        totp_cipher=FakeCipher(),
        sink_gate=FakeGate(),
        limits=FakeLimits(),
    )


@pytest.fixture
def db() -> Db:
    return Db()


@pytest.fixture
def client(db: Db) -> Iterator[TestClient]:
    with TestClient(create_app(runtime(db))) as c:
        yield c


def headers_ok(resp: Any) -> None:
    assert resp.headers.get_list("content-security-policy") == [CSP]
    assert resp.headers.get_list("strict-transport-security") == ["max-age=31536000"]
    assert resp.headers.get_list("x-content-type-options") == ["nosniff"]
    assert resp.headers.get_list("referrer-policy") == ["no-referrer"]


def problem(resp: Any, detail: str) -> None:
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert set(body) == {"type", "title", "status", "detail", "instance"}
    assert body["detail"] == detail and body["status"] == 503
    headers_ok(resp)


# ------------------------------------------------------------ CHK-M2-240


def test_healthz_is_ok_with_the_database_down(client: TestClient, db: Db) -> None:
    db.up = False
    resp = client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    headers_ok(resp)
    assert db.pings == 0 and db.queries == []


def test_healthz_works_with_no_runtime_at_all() -> None:
    with TestClient(create_app()) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        resp = c.get("/readyz")
    problem(resp, resp.json()["detail"])  # 503 problem, not a crash


# --------------------------------------------- readiness decisions (unit)


def test_readyz_ok(client: TestClient, db: Db) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    headers_ok(resp)
    assert all(q.lstrip().upper().startswith("SELECT") for q in db.queries)


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        (lambda d: setattr(d, "up", False), "db"),
        (lambda d: setattr(d, "revisions", ["0000_old"]), "migrations"),
        (lambda d: setattr(d, "revisions", []), "migrations"),
        (lambda d: setattr(d, "revisions", [HEAD, "extra"]), "migrations"),
        (lambda d: d.kinds.discard("inventory"), "system_schedule"),
        (lambda d: d.kinds.discard("offline_sweep"), "system_schedule"),
        (lambda d: d.kinds.discard("retention"), "system_schedule"),
        (lambda d: setattr(d, "kinds", set()), "system_schedule"),
    ],
)
def test_readyz_names_the_failed_check(
    client: TestClient, db: Db, change: Callable[[Db], None], detail: str
) -> None:
    change(db)
    problem(client.get("/readyz"), detail)


def test_ping_failure_skips_the_queries(client: TestClient, db: Db) -> None:
    db.up = False
    problem(client.get("/readyz"), "db")
    assert db.queries == []


def test_extra_schedule_rows_do_not_fail(client: TestClient, db: Db) -> None:
    db.kinds.add("something_else")
    assert client.get("/readyz").status_code == 200


# ------------------------------------------------- CHK-M2-249 (unit side)


def test_a_stalled_query_gives_503_db_within_the_bound(
    client: TestClient, db: Db
) -> None:
    db.stall = threading.Event()
    try:
        for _ in range(3):
            started = time.monotonic()
            problem(client.get("/readyz"), "db")
            assert time.monotonic() - started < 3.0
    finally:
        db.stall.set()
    deadline = time.monotonic() + 5
    db.stall = None
    while time.monotonic() < deadline and client.get("/readyz").status_code != 200:
        time.sleep(0.1)
    assert client.get("/readyz").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_at_most_one_check_in_flight(client: TestClient, db: Db) -> None:
    db.stall = threading.Event()
    try:
        client.get("/readyz")
        before = len(db.queries)
        for _ in range(5):
            started = time.monotonic()
            problem(client.get("/readyz"), "db")
            assert time.monotonic() - started < 0.5  # the stuck check is not rejoined
        assert len(db.queries) == before
    finally:
        db.stall.set()


# ------------------------------------------------------- CHK-M2-245 (unit)


def test_no_token_needed_and_a_bad_token_changes_nothing(client: TestClient) -> None:
    bad = {"Authorization": "Bearer bsu_" + "A" * 43}
    for path in ("/healthz", "/readyz"):
        assert client.get(path, headers=bad).status_code == 200
        assert client.get(path, headers={"Authorization": "Basic x"}).status_code == 200


def test_not_rate_limited(client: TestClient) -> None:
    codes = {
        client.get(p).status_code for p in ("/healthz", "/readyz") for _ in range(100)
    }
    assert codes == {200}


# ------------------------------------------------------------ CHK-M2-246


def test_health_routes_are_outside_api_v1(client: TestClient) -> None:
    for path in ("/api/v1/healthz", "/api/v1/readyz", "/health"):
        assert client.get(path).status_code == 404
    assert client.post("/healthz").status_code == 405


# ------------------------------------------------------------ CHK-M2-247


def test_lifespan_starts_and_stops_the_lifecycle_once(db: Db) -> None:
    events: list[str] = []

    class Life:
        async def start(self) -> None:
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")

    rt = Runtime(clock=FakeClock(datetime(2026, 10, 21, tzinfo=UTC)), db=db,
                 totp_cipher=FakeCipher(), sink_gate=FakeGate(), limits=FakeLimits(),
                 lifecycle=Life())  # fmt: skip
    app = create_app(rt)
    assert events == []
    with TestClient(app) as c:
        assert events == ["start"]
        c.get("/healthz")
    assert events == ["start", "stop"]


def test_openapi_export_needs_no_runtime() -> None:
    from bitscan_manager.app import openapi_document

    doc = openapi_document()
    assert {"/healthz", "/readyz"} <= set(doc["paths"])
    assert "422" not in str(doc["paths"]["/readyz"])


def test_query_failure_detail_is_only_db(client: TestClient, db: Db) -> None:
    """A driver error inside the checks never reaches the body (CHK-M2-243)."""
    db.tx_fails = True
    resp = client.get("/readyz")
    problem(resp, "db")
    assert "CANARY" not in resp.text and "db.internal" not in resp.text


def test_ping_failure_alone_is_503_db(client: TestClient, db: Db) -> None:
    """ping() is a check of its own: when it fails, readyz is 503 even if a
    query would still succeed (TS §8.4 "DB reachable")."""
    db.ping_ok = False
    problem(client.get("/readyz"), "db")
    db.ping_ok = None
    assert client.get("/readyz").status_code == 200
