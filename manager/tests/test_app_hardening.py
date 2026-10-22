"""REQ-035, REQ-036, REQ-037: create_app() hardening (TASK-024).

Checks CHK-M2-010 to CHK-M2-020 of tests/m2/test-plan.md. Expected values come
from TS §6.3 L1138 and L1140, #57 (HSTS one year, MB = 1,048,576 bytes), #34
and the decisions row on FastAPI telemetry (2026-10-20), not from the code.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

import bitscan_manager.app as app_module
from bitscan_manager.app import create_app

MIB = 1_048_576
CAP = MIB
HSTS = "max-age=31536000"
CSP = (
    "default-src 'self'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'"
)
EXPECTED_HEADERS = {
    "strict-transport-security": HSTS,
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
# TS §6.3 L1138 caps, in bytes (#57 (b)).
SPEC_CLASS_CAPS = {
    "json": MIB,
    "result_batch": 3 * MIB // 2,
    "bit": 5 * MIB,
    "inventory": 10 * MIB,
}
OTEL_ENV_KEYS = (
    "FASTAPI_OTEL_AUTO_CONFIGURE",
    "OTEL_TRACES_EXPORTER",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SDK_DISABLED",
)
TELEMETRY_KEYS = ("tracing", "metrics", "logs", "operation_spans", "auto_configure")


@dataclass
class Seen:
    bodies: list[int] = field(default_factory=list)


def make_app(seen: Seen | None = None) -> FastAPI:
    """create_app() plus test-only routes that provoke each status."""
    app = create_app()
    record = seen if seen is not None else Seen()

    @app.get("/t/ok")
    def ok() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/t/nocontent", status_code=204)
    def nocontent() -> Response:
        return Response(status_code=204)

    @app.get("/t/status/{code}")
    def status(code: int) -> None:
        raise HTTPException(status_code=code)

    @app.get("/t/boom")
    def boom() -> None:
        raise RuntimeError("CANARY-boom")

    @app.post("/t/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        record.bodies.append(len(body))
        return {"len": len(body)}

    @app.get("/t/own-headers")
    def own_headers() -> Response:
        resp = Response("x")
        resp.headers["Content-Security-Policy"] = "default-src *"
        resp.headers.append("Referrer-Policy", "unsafe-url")
        resp.headers.append("Referrer-Policy", "origin")
        resp.headers["Strict-Transport-Security"] = "max-age=0"
        resp.headers["X-Content-Type-Options"] = "sniff"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(make_app(), raise_server_exceptions=False) as c:
        yield c


def assert_security_headers(resp: Any) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert resp.headers.get_list(name) == [value], (resp.status_code, name)
    assert [
        k for k in resp.headers if k.lower().startswith("access-control-allow-")
    ] == []


# ---------------------------------------------------------------- REQ-036


def _provoke(c: TestClient, status: int) -> Any:
    if status == 200:
        return c.get("/t/ok")
    if status == 204:
        return c.get("/t/nocontent")
    if status == 404:
        return c.get("/no/such/path")
    if status == 405:
        return c.post("/t/ok")
    if status == 413:
        return c.post("/t/echo", content=b"x" * (CAP + 1))
    if status == 500:
        return c.get("/t/boom")
    return c.get(f"/t/status/{status}")


@pytest.mark.parametrize(
    "status", [200, 204, 401, 403, 404, 405, 409, 413, 422, 429, 500, 503]
)
def test_every_status_carries_the_four_headers_once(
    client: TestClient, status: int
) -> None:
    """CHK-M2-014: REQ-036 (1), (2)."""
    resp = _provoke(client, status)
    assert resp.status_code == status
    assert_security_headers(resp)


def test_hsts_and_csp_are_the_spec_bytes(client: TestClient) -> None:
    """CHK-M2-014: #57 (a) and TS §6.3 L1140, byte for byte."""
    raw = dict(client.get("/t/ok").headers.raw)
    assert raw[b"strict-transport-security"] == HSTS.encode()
    assert raw[b"content-security-policy"] == CSP.encode()


def test_handler_headers_are_replaced_not_kept(client: TestClient) -> None:
    """CHK-M2-015: REQ-036 (3), (4)."""
    resp = client.get("/t/own-headers")
    assert resp.status_code == 200
    assert_security_headers(resp)


@pytest.mark.parametrize(
    "path", ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]
)
def test_docs_routes_are_404_with_headers(client: TestClient, path: str) -> None:
    """CHK-M2-012: REQ-035 (3), #34."""
    resp = client.get(path)
    assert resp.status_code == 404
    assert_security_headers(resp)


@pytest.mark.parametrize(
    "path", ["/", "/t/ok", "/t/echo", "/healthz", "/api/v1/auth/login"]
)
def test_cors_preflight_gets_no_allow_header(client: TestClient, path: str) -> None:
    """CHK-M2-013: REQ-035 (4), REQ-036 (4)."""
    resp = client.options(
        path,
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert_security_headers(resp)
    simple = client.get(path, headers={"Origin": "https://evil.example"})
    assert_security_headers(simple)


# ---------------------------------------------------------------- REQ-037


def test_body_of_exactly_the_cap_is_passed_on() -> None:
    """CHK-M2-016: REQ-037 (1)."""
    seen = Seen()
    with TestClient(make_app(seen)) as c:
        resp = c.post("/t/echo", content=b"a" * CAP)
    assert resp.status_code == 200
    assert resp.json() == {"len": CAP}
    assert seen.bodies == [CAP]


def test_one_byte_over_the_cap_is_413() -> None:
    """CHK-M2-016: REQ-037 (1), #57 (b): the cap is 1,048,576, not 1,000,000."""
    seen = Seen()
    with TestClient(make_app(seen)) as c:
        resp = c.post("/t/echo", content=b"a" * (CAP + 1))
        under_decimal_mb = c.post("/t/echo", content=b"a" * 1_000_001)
    assert resp.status_code == 413
    assert under_decimal_mb.status_code == 200
    assert seen.bodies == [1_000_001]


def test_413_body_is_problem_details(client: TestClient) -> None:
    """CHK-M2-019: REQ-037 (4): five keys, status 413, instance without query."""
    resp = client.post("/t/echo?q=CANARY-query", content=b"a" * (CAP + 1))
    assert resp.status_code == 413
    assert resp.headers["content-type"].split(";")[0] == "application/problem+json"
    body = resp.json()
    assert set(body) == {"type", "title", "status", "detail", "instance"}
    assert body["status"] == 413
    assert body["type"] == "too_large"  # lead ruling 2026-10-21 for user routes
    assert body["instance"] == "/t/echo"
    assert "CANARY" not in resp.text
    assert_security_headers(resp)


@dataclass
class Feed:
    """An ASGI receive() that hands out chunks and counts what was pulled."""

    chunks: list[bytes]
    pulled: int = 0
    calls: int = 0
    calls_after_cap: int = 0
    disconnect_at: int | None = None

    async def receive(self) -> dict[str, Any]:
        self.calls += 1
        if self.pulled > CAP:
            self.calls_after_cap += 1
        if self.disconnect_at is not None and self.calls > self.disconnect_at:
            return {"type": "http.disconnect"}
        if not self.chunks:
            return {"type": "http.disconnect"}
        chunk = self.chunks.pop(0)
        self.pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self.chunks)}


def drive(
    path: str, headers: list[tuple[bytes, bytes]], feed: Feed
) -> tuple[int | None, bytes, Seen, list[tuple[bytes, bytes]]]:
    seen = Seen()
    app = make_app(seen)
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
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
    resp_headers: list[tuple[bytes, bytes]] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
            resp_headers.extend(message.get("headers", []))
        elif message["type"] == "http.response.body":
            body.append(message.get("body", b""))

    asyncio.run(app(scope, feed.receive, send))  # type: ignore[arg-type]
    return (status[0] if status else None), b"".join(body), seen, resp_headers


CHUNK = 64 * 1024


def test_content_length_over_cap_reads_no_body() -> None:
    """CHK-M2-017: REQ-037 (2): 413 before any body byte is pulled."""
    feed = Feed([b"a" * CHUNK for _ in range(80)])
    status, body, seen, headers = drive(
        "/t/echo", [(b"content-length", b"5000000")], feed
    )
    assert status == 413
    assert seen.bodies == []
    assert feed.pulled <= CAP + 1
    assert feed.pulled == 0
    assert json.loads(body)["status"] == 413
    assert (b"content-security-policy", CSP.encode()) in headers


def test_content_length_of_exactly_cap_plus_one_is_413() -> None:
    """CHK-M2-017: REQ-037 (2) at the boundary."""
    feed = Feed([b"a" * (CAP + 1)])
    status, _, seen, _ = drive(
        "/t/echo", [(b"content-length", str(CAP + 1).encode())], feed
    )
    assert status == 413
    assert seen.bodies == []


def test_second_content_length_header_over_cap_is_413() -> None:
    """CHK-M2-017: a small first Content-Length does not hide a large second one."""
    feed = Feed([b"a" * 10])
    status, _, seen, _ = drive(
        "/t/echo", [(b"content-length", b"10"), (b"content-length", b"5000000")], feed
    )
    assert status == 413
    assert seen.bodies == []


def test_lying_content_length_is_cut_off_after_the_crossing_chunk() -> None:
    """CHK-M2-017: declares 10 bytes, sends 2 MiB in 64 KiB chunks."""
    feed = Feed([b"a" * CHUNK for _ in range(32)])
    status, _, seen, _ = drive("/t/echo", [(b"content-length", b"10")], feed)
    assert status == 413
    assert seen.bodies == []
    assert feed.calls_after_cap == 0
    assert CAP < feed.pulled <= CAP + CHUNK


@pytest.mark.parametrize("declared", [None, b"10"])
def test_byte_granular_body_stops_at_exactly_cap_plus_one(
    declared: bytes | None,
) -> None:
    """CHK-M2-017, -018: with one-byte chunks past the cap, cap + 1 bytes are read."""
    chunks = [b"a" * CHUNK for _ in range(CAP // CHUNK)] + [b"b"] * 4096
    feed = Feed(chunks)
    headers = [] if declared is None else [(b"content-length", declared)]
    status, _, seen, _ = drive("/t/echo", headers, feed)
    assert status == 413
    assert seen.bodies == []
    assert feed.pulled == CAP + 1
    assert feed.calls_after_cap == 0


def test_chunked_body_over_cap_is_413_without_content_length() -> None:
    """CHK-M2-018: REQ-037 (3)."""
    feed = Feed([b"a" * CHUNK for _ in range(32)])
    status, body, seen, headers = drive("/t/echo", [], feed)
    assert status == 413
    assert seen.bodies == []
    assert feed.calls_after_cap == 0
    assert set(json.loads(body)) == {"type", "title", "status", "detail", "instance"}
    assert (b"strict-transport-security", HSTS.encode()) in headers


def test_chunked_body_of_exactly_the_cap_is_passed_on_whole() -> None:
    """CHK-M2-016, -018: 16 x 64 KiB = the cap reaches the handler as one body."""
    feed = Feed([b"a" * CHUNK for _ in range(CAP // CHUNK)])
    status, body, seen, _ = drive("/t/echo", [], feed)
    assert status == 200
    assert seen.bodies == [CAP]
    assert json.loads(body) == {"len": CAP}


def test_client_disconnect_mid_body_runs_nothing() -> None:
    """A disconnect before the body completes: no handler, no response."""
    feed = Feed([b"a" * CHUNK for _ in range(4)], disconnect_at=2)
    status, _, seen, _ = drive("/t/echo", [], feed)
    assert seen.bodies == []
    assert status is None


# ------------------------------------------------- REQ-037 (5) cap registry


def test_cap_classes_are_the_spec_values() -> None:
    """CHK-M2-020: TS §6.3 L1138 in bytes (#57 (b))."""
    assert dict(app_module.BODY_CAP_CLASSES) == SPEC_CLASS_CAPS


@pytest.mark.parametrize("cap_class", sorted(SPEC_CLASS_CAPS))
def test_registry_accepts_each_class_at_its_value(
    monkeypatch: pytest.MonkeyPatch, cap_class: str
) -> None:
    """CHK-M2-020: exactly the class value is accepted."""
    monkeypatch.setattr(
        app_module,
        "ROUTE_BODY_CAPS",
        [("/t/echo", cap_class, SPEC_CLASS_CAPS[cap_class])],
    )
    create_app()


@pytest.mark.parametrize(
    "entries",
    [
        [("/t/echo", "json", MIB + 1)],
        [("/t/echo", "result_batch", 3 * MIB // 2 + 1)],
        [("/t/echo", "bit", 5 * MIB + 1)],
        [("/t/echo", "inventory", 10 * MIB + 1)],
        [("/t/echo", "inventory", 64 * MIB)],
        [("/t/echo", "json", 0)],
        [("/t/echo", "json", -1)],
        [("/t/echo", "csv", 1024)],
        [("/t/echo", "bit", 1024), ("/t/echo", "json", 1024)],
    ],
    ids=[
        "json+1",
        "batch+1",
        "bit+1",
        "inventory+1",
        "inventory-64MiB",
        "zero",
        "negative",
        "unknown-class",
        "duplicate",
    ],
)
def test_registry_refuses_bad_entries_at_app_creation(
    monkeypatch: pytest.MonkeyPatch, entries: list[tuple[str, str, int]]
) -> None:
    """CHK-M2-020: REQ-037 (5): raises at create_app()."""
    monkeypatch.setattr(app_module, "ROUTE_BODY_CAPS", entries)
    with pytest.raises(ValueError):
        create_app()


def test_registered_cap_applies_to_its_exact_path_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHK-M2-020: a bit-class route may take 2 MiB; other paths keep 1 MiB."""
    monkeypatch.setattr(app_module, "ROUTE_BODY_CAPS", [("/t/echo", "bit", 2 * MIB)])
    seen = Seen()
    app = make_app(seen)

    @app.post("/t/echo2")
    async def echo2(request: Request) -> dict[str, int]:
        return {"len": len(await request.body())}

    with TestClient(app) as c:
        assert c.post("/t/echo", content=b"a" * (2 * MIB)).status_code == 200
        assert c.post("/t/echo", content=b"a" * (2 * MIB + 1)).status_code == 413
        assert c.post("/t/echo2", content=b"a" * (CAP + 1)).status_code == 413
        assert c.post("/t/echo/", content=b"a" * (CAP + 1)).status_code == 413
    assert seen.bodies == [2 * MIB]


# --------------------------------------------------------- REQ-035 telemetry

CHILD = textwrap.dedent(
    """
    import json, logging, sys, time
    from fastapi.testclient import TestClient
    from bitscan_manager.app import create_app

    attempts = []

    class Catch(logging.Handler):
        def emit(self, record):
            if "telemetry" in record.name or "telemetry" in record.getMessage().lower():
                attempts.append(record.name + ": " + record.getMessage()[:200])

    logging.getLogger().addHandler(Catch(level=logging.DEBUG))
    logging.getLogger().setLevel(logging.DEBUG)

    app = create_app()

    @app.get("/t")
    def t() -> dict:
        return {}

    with TestClient(app) as c:
        codes = [c.get("/t").status_code for _ in range(20)]
    time.sleep(5)
    loaded = sorted(sys.modules)
    print(json.dumps({
        "codes": codes,
        "sdk": [m for m in loaded if m.startswith("opentelemetry.sdk")],
        "exporter": [m for m in loaded if m.startswith("opentelemetry.exporter")],
        "attempts": attempts,
    }))
    """
)


class Listener:
    """A local TCP listener that records every connection it accepts."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port: int = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.accepted += 1
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


def _run_child(env_extra: dict[str, str]) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k not in OTEL_ENV_KEYS}
    env.update(env_extra)
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    result: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    return result


@pytest.mark.parametrize(
    "with_env", [True, False], ids=["otel-env-set", "otel-env-unset"]
)
def test_no_telemetry_egress(with_env: bool) -> None:
    """CHK-M2-010, -011: REQ-035 (1), (2), G29."""
    listener = Listener()
    try:
        env = (
            {
                "FASTAPI_OTEL_AUTO_CONFIGURE": "true",
                "OTEL_TRACES_EXPORTER": "otlp",
                "OTEL_METRICS_EXPORTER": "otlp",
                "OTEL_LOGS_EXPORTER": "otlp",
                "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{listener.port}",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            }
            if with_env
            else {}
        )
        started = time.monotonic()
        result = _run_child(env)
        assert time.monotonic() - started >= 5
        assert result["codes"] == [200] * 20
        assert result["sdk"] == []
        assert result["exporter"] == []
        # FastAPI swallows a failed auto-configure with a warning; with no SDK
        # installed that warning is the only sign export was attempted.
        assert result["attempts"] == []
        assert listener.accepted == 0
        # Control: the listener does observe a connection.
        socket.create_connection(("127.0.0.1", listener.port), timeout=2).close()
        deadline = time.monotonic() + 3
        while listener.accepted == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert listener.accepted == 1
    finally:
        listener.close()


def test_every_telemetry_signal_is_off_even_with_auto_configure_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHK-M2-010: all five settings False despite FASTAPI_OTEL_AUTO_CONFIGURE.

    Uses FastAPI's private attributes (fastapi 0.148) so a removed setting is
    caught even though no OpenTelemetry SDK is installed.
    """
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    app = create_app()
    config: dict[str, object] = dict(app._telemetry)  # noqa: SLF001
    assert {k: config[k] for k in TELEMETRY_KEYS} == dict.fromkeys(
        TELEMETRY_KEYS, False
    )
    assert app._native_telemetry.enabled() is False  # noqa: SLF001
