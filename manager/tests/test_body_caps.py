"""REQ-066, REQ-037 (5): body caps by path template and the after-auth mode (TASK-049).

Checks CHK-M3-030 to CHK-M3-035 of tests/m3/test-plan.md (TP-M3-03). Values
from TS §6.3 L1138 and #57 (b): 1 MiB = 1,048,576 bytes; inventory 10 MiB as
sent, result batch 1.5 MiB, other JSON bodies 1 MiB. Test routes are added in
the test only and are called on concrete paths built from random UUIDs. Bytes
pulled from the client are counted with a raw ASGI ``receive`` as in CHK-M2-017.

The real PUT /api/v1/agent/{id}/inventory route (TASK-074) matches before a test
route at that template, so the inventory cases use a test-only template of the
same shape registered with the inventory class and cap in the monkeypatched
ROUTE_BODY_CAPS (as for heartbeat in TASK-072). The real route's own 10 MiB cap
and after-auth mode are checked on PostgreSQL in test_inventory_api_pg.py.
The results template stays real: its route is POST only, so a PUT reaches the
test route.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from bitscan_manager import app as app_module
from bitscan_manager.app import (
    BODY_CAP_SCOPE_KEY,
    BodyCap,
    BodyTooLarge,
    RouteCap,
    create_app,
)

MIB = 1_048_576
JSON_CAP = MIB
RESULTS_CAP = 3 * MIB // 2  # 1,572,864
INVENTORY_CAP = 10 * MIB  # 10,485,760
INVENTORY_T = "/api/v1/agent/{id}/inventory-probe"  # test-only, see the docstring
RESULTS_T = "/api/v1/agent/{id}/jobs/{job_id}/results"
HEARTBEAT_T = "/api/v1/agent/{id}/heartbeat"
# A test-only agent path with no registered cap: the real heartbeat route
# (TASK-072) shadows a test route at HEARTBEAT_T; its own 1 MiB check runs
# on PostgreSQL in test_heartbeat_api_pg.py::test_body_cap_on_the_real_route.
PLAIN_T = "/api/v1/agent/{id}/plain-probe"
CHUNK = 64 * 1024
PROBLEM_KEYS = {"type", "title", "status", "detail", "instance"}


def inv_path() -> str:
    return f"/api/v1/agent/{uuid.uuid4()}/inventory-probe"


def res_path() -> str:
    return f"/api/v1/agent/{uuid.uuid4()}/jobs/{uuid.uuid4()}/results"


def hb_path() -> str:
    return f"/api/v1/agent/{uuid.uuid4()}/plain-probe"


@dataclass
class Seen:
    ran: list[str] = field(default_factory=list)
    caps: list[BodyCap | None] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def check_token(request: Request) -> None:
    """Stands in for the agent token dependency (TASK-063)."""
    if request.headers.get("x-test-auth") == "no":
        raise HTTPException(status_code=401)


def make_app(caps: list[Any], monkeypatch: pytest.MonkeyPatch, seen: Seen) -> FastAPI:
    monkeypatch.setattr(app_module, "ROUTE_BODY_CAPS", caps)
    app = create_app()

    async def handler(request: Request) -> dict[str, Any]:
        seen.ran.append(request.url.path)
        cap = request.scope.get(BODY_CAP_SCOPE_KEY)
        seen.caps.append(cap)
        if (
            cap is not None
            and cap.content_length is not None
            and cap.content_length > cap.limit
        ):
            seen.refused.append("declared")
            return {"refused": "declared"}
        n = 0
        try:
            async for chunk in request.stream():
                n += len(chunk)
        except BodyTooLarge:
            seen.refused.append("stream")
            seen.lengths.append(n)
            return {"refused": "stream", "len": n}
        seen.lengths.append(n)
        return {"len": n}

    for template in (INVENTORY_T, RESULTS_T, PLAIN_T):
        app.add_api_route(
            template,
            handler,
            methods=["POST", "PUT"],
            dependencies=[Depends(check_token)],
        )
    return app


@dataclass
class Feed:
    """An ASGI receive() that hands out chunks and counts what was pulled."""

    chunks: list[bytes]
    pulled: int = 0
    calls: int = 0

    async def receive(self) -> dict[str, Any]:
        self.calls += 1
        if not self.chunks:
            return {"type": "http.disconnect"}
        chunk = self.chunks.pop(0)
        self.pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self.chunks)}


def drive(
    app: FastAPI,
    path: str,
    headers: list[tuple[bytes, bytes]],
    feed: Feed,
    method: str = "PUT",
) -> tuple[int | None, bytes]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("192.0.2.10", 50000),
        "server": ("testserver", 443),
    }
    status: list[int] = []
    body: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body":
            body.append(message.get("body", b""))

    asyncio.run(app(scope, feed.receive, send))  # type: ignore[arg-type]
    return (status[0] if status else None), b"".join(body)


def chunks_of(total: int, size: int = CHUNK) -> list[bytes]:
    full, rest = divmod(total, size)
    return [b"a" * size] * full + ([b"a" * rest] if rest else [])


def byte_tail(cap: int) -> list[bytes]:
    """Up to the cap in 64 KiB chunks, then one-byte chunks well past it."""
    return chunks_of(cap) + [b"b"] * 4096


NORMAL = [
    RouteCap(INVENTORY_T, "inventory", INVENTORY_CAP),
    RouteCap(RESULTS_T, "result_batch", RESULTS_CAP),
]
AFTER_AUTH = [
    RouteCap(INVENTORY_T, "inventory", INVENTORY_CAP, True),
    RouteCap(RESULTS_T, "result_batch", RESULTS_CAP, True),
]
CASES: list[tuple[str, Callable[[], str], int]] = [
    ("inventory", inv_path, INVENTORY_CAP),
    ("results", res_path, RESULTS_CAP),
]


def assert_too_large(status: int | None, body: bytes, path: str) -> None:
    assert status == 413
    problem = json.loads(body)
    assert set(problem) == PROBLEM_KEYS
    assert problem["type"] == "too_large"
    assert problem["status"] == 413
    assert problem["instance"] == path


# ------------------------------------------------------------ CHK-M3-030


@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_normal_mode_template_caps(
    monkeypatch: pytest.MonkeyPatch, name: str, path_of: Callable[[], str], cap: int
) -> None:
    """REQ-066 (1): a concrete path gets its template's cap, exactly."""
    seen = Seen()
    app = make_app(NORMAL, monkeypatch, seen)
    with TestClient(app) as c:
        p = path_of()
        ok = c.put(p, content=b"a" * cap)
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"len": cap}
        p2 = path_of()
        over = c.put(p2, content=b"a" * (cap + 1))
        assert_too_large(over.status_code, over.content, p2)
    assert seen.lengths == [cap]
    assert seen.ran == [p]


def test_other_agent_routes_keep_one_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-066 (1): an agent route with no registered cap refuses 1 MiB + 1."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    with TestClient(app) as c:
        p = hb_path()
        assert c.post(p, content=b"a" * JSON_CAP).json() == {"len": JSON_CAP}
        p2 = hb_path()
        over = c.post(p2, content=b"a" * (JSON_CAP + 1))
        assert_too_large(over.status_code, over.content, p2)
    assert seen.caps == [None]  # no BodyCap on a normal-mode route


def test_two_mib_inventory_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """CHK-M3-360 at the unit level: a valid 2 MiB upload is not held to 1 MiB."""
    for caps in (NORMAL, AFTER_AUTH):
        seen = Seen()
        app = make_app(caps, monkeypatch, seen)
        with TestClient(app) as c:
            r = c.put(inv_path(), content=b"a" * (2 * MIB))
        assert r.status_code == 200
        assert r.json() == {"len": 2 * MIB}


# ------------------------------------------------------------ CHK-M3-031


@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_normal_mode_content_length_over_cap_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, name: str, path_of: Callable[[], str], cap: int
) -> None:
    seen = Seen()
    app = make_app(NORMAL, monkeypatch, seen)
    feed = Feed(chunks_of(cap + CHUNK))
    p = path_of()
    status, body = drive(app, p, [(b"content-length", str(cap + 1).encode())], feed)
    assert_too_large(status, body, p)
    assert feed.pulled == 0
    assert seen.ran == []


@pytest.mark.parametrize("declared", [None, b"10"], ids=["chunked", "lying-length"])
@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_normal_mode_stops_at_cap_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    path_of: Callable[[], str],
    cap: int,
    declared: bytes | None,
) -> None:
    """REQ-066 (2): chunked or lying Content-Length: exactly cap + 1 bytes read."""
    seen = Seen()
    app = make_app(NORMAL, monkeypatch, seen)
    feed = Feed(byte_tail(cap))
    headers = [] if declared is None else [(b"content-length", declared)]
    p = path_of()
    status, body = drive(app, p, headers, feed)
    assert_too_large(status, body, p)
    assert feed.pulled == cap + 1
    assert seen.ran == []


@pytest.mark.parametrize("declared", [None, b"10"], ids=["chunked", "lying-length"])
@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_after_auth_reader_stops_at_cap_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    path_of: Callable[[], str],
    cap: int,
    declared: bytes | None,
) -> None:
    """REQ-066 (2), (3): the route's reader refuses after exactly cap + 1 bytes."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    feed = Feed(byte_tail(cap))
    headers = [] if declared is None else [(b"content-length", declared)]
    status, body = drive(app, path_of(), headers, feed)
    assert status == 200
    assert json.loads(body)["refused"] == "stream"
    assert feed.pulled == cap + 1
    assert seen.refused == ["stream"]
    assert seen.lengths[0] <= cap  # nothing past the cap reached the route


@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_after_auth_scope_carries_limit_and_declared_length(
    monkeypatch: pytest.MonkeyPatch, name: str, path_of: Callable[[], str], cap: int
) -> None:
    """The route learns the limit and the largest Content-Length, without reading."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    feed = Feed(chunks_of(cap + CHUNK))
    headers = [(b"content-length", b"10"), (b"content-length", str(cap + 1).encode())]
    status, body = drive(app, path_of(), headers, feed)
    assert status == 200
    assert json.loads(body) == {"refused": "declared"}
    assert seen.caps == [BodyCap(cap, cap + 1)]
    assert feed.pulled == 0


# ------------------------------------------------------------ CHK-M3-032


@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_after_auth_token_checked_before_any_byte(
    monkeypatch: pytest.MonkeyPatch, name: str, path_of: Callable[[], str], cap: int
) -> None:
    """REQ-066 (3): an over-cap body with a failing token check gets 401, unread."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    for headers in (
        [(b"x-test-auth", b"no"), (b"content-length", str(cap + 1).encode())],
        [(b"x-test-auth", b"no")],
    ):
        feed = Feed(chunks_of(cap + CHUNK))
        status, body = drive(app, path_of(), headers, feed)
        assert status == 401
        assert json.loads(body)["status"] == 401
        assert feed.pulled == 0
    assert seen.ran == []


@pytest.mark.parametrize(("name", "path_of", "cap"), CASES, ids=[c[0] for c in CASES])
def test_after_auth_exact_cap_reaches_route_whole(
    monkeypatch: pytest.MonkeyPatch, name: str, path_of: Callable[[], str], cap: int
) -> None:
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    with TestClient(app) as c:
        r = c.put(path_of(), content=b"a" * cap)
        r2 = c.put(path_of(), content=b"a" * (cap + 1))
    assert r.json() == {"len": cap}
    # the middleware never answers 413 itself: the route ran and refused
    assert r2.status_code == 200
    assert r2.json()["refused"] in {"declared", "stream"}
    assert len(seen.ran) == 2


def test_capped_receive_counts_real_bytes() -> None:
    """CappedReceive counts bytes, not headers, and pulls nothing after refusing."""
    feed = Feed([b"a" * 6, b"b" * 6, b"c" * 6])

    async def run() -> tuple[int, int]:
        rx = app_module.CappedReceive(feed.receive, 10)
        await rx()
        with pytest.raises(BodyTooLarge):
            await rx()
        with pytest.raises(BodyTooLarge):
            await rx()
        return rx.received, feed.calls

    received, calls = asyncio.run(run())
    assert received == 12
    assert calls == 2
    assert feed.pulled == 12


# ------------------------------------------------------------ CHK-M3-033


@pytest.mark.parametrize(
    "entries",
    [
        [RouteCap(INVENTORY_T, "inventory", INVENTORY_CAP + 1, True)],
        [RouteCap(RESULTS_T, "result_batch", RESULTS_CAP + 1, True)],
        [RouteCap(HEARTBEAT_T, "json", JSON_CAP + 1)],
        [RouteCap(INVENTORY_T, "inventory", 0, True)],
        [RouteCap(INVENTORY_T, "gzip", 1024, True)],
        [
            RouteCap(INVENTORY_T, "inventory", 1024),
            RouteCap(INVENTORY_T, "inventory", 2048),
        ],
        [
            RouteCap(INVENTORY_T, "inventory", INVENTORY_CAP, True),
            RouteCap(INVENTORY_T, "inventory", INVENTORY_CAP, False),
        ],
    ],
    ids=[
        "inventory+1",
        "results+1",
        "json+1",
        "zero",
        "unknown-class",
        "dup",
        "dup-modes",
    ],
)
def test_registry_refuses_bad_caps(
    monkeypatch: pytest.MonkeyPatch, entries: list[Any]
) -> None:
    """REQ-066 (5): a cap over its class, an unknown class, two caps per template."""
    monkeypatch.setattr(app_module, "ROUTE_BODY_CAPS", entries)
    with pytest.raises(ValueError):
        create_app()


def test_registry_accepts_class_maxima_and_legacy_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_module,
        "ROUTE_BODY_CAPS",
        [*AFTER_AUTH, (HEARTBEAT_T, "json", JSON_CAP)],
    )
    create_app()
    assert RouteCap(INVENTORY_T, "inventory", 1).after_auth is False  # default mode


# ------------------------------------------------------------ CHK-M3-034


def test_user_routes_keep_one_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-066 (6): with agent caps registered, a user route still refuses 1 MiB + 1."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", content=b"a" * (JSON_CAP + 1))
    assert_too_large(r.status_code, r.content, "/api/v1/auth/login")


# ------------------------------------------------------------ CHK-M3-035


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/agent/x/y/inventory-probe",
        "/api/v1/agent//inventory-probe",
        f"/api/v1/agent/{uuid.uuid4()}/inventory-probe/",
        f"/api/v1/agent/{uuid.uuid4()}/inventory-probex",
        f"/x/api/v1/agent/{uuid.uuid4()}/inventory-probe",
        f"/api/v1/agent/{uuid.uuid4()}/inventory-probe\n",
        f"/api/v1/agent/{uuid.uuid4()}/jobs/results",
        f"/api/v1/agent/{uuid.uuid4()}/jobs/a/b/results",
    ],
    ids=[
        "two-segments",
        "empty-id",
        "trailing-slash",
        "suffix",
        "prefix",
        "trailing-newline",
        "results-no-job",
        "results-two-segments",
    ],
)
def test_lookalike_paths_get_the_default_cap(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """A path that only resembles a template is held to 1 MiB, read at most cap + 1."""
    seen = Seen()
    app = make_app(AFTER_AUTH, monkeypatch, seen)
    feed = Feed(byte_tail(JSON_CAP))
    status, _ = drive(app, path, [], feed)
    assert status == 413
    assert feed.pulled == JSON_CAP + 1
    assert seen.ran == []
