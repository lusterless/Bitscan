"""TASK-112: the built web UI served from the manager's own origin (TP-M5-05).

Checks CHK-M5-100 to CHK-M5-112 of tests/m5/test-plan.md. Expected values:
REQ-118 (1)-(6); #6 (M5 half) as approved 2026-10-24 (GET / and GET
/assets/<file> without a token, only files present when the app is created,
content type fixed by extension, no catch-all, no CORS, TS §6.3 headers on
every response, not in the OpenAPI document; a recorded deviation from TS
§2.3 L118); TS §6.3 L1140 (headers, no CORS); work/plans/TASK-112.md (the
extension map).

In-process probes send a raw ASGI scope built the way uvicorn builds it
(``path`` = percent-decoded ``raw_path``), because the test HTTP client would
normalise ``..`` before sending. The real ``serve`` checks (Linux) send the
same paths unnormalised with ``http.client`` over TLS.
"""

import asyncio
import json
import logging
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi import FastAPI

from bitscan_manager.api.webui import WebUi, load
from bitscan_manager.app import create_app

from .certs import Pki, make_pki
from .conftest import PgServer, own_migrated_server
from .fake_sink import https_sink, server_context

# The real-serve helpers; that module skips itself (and so this one) off Linux.
from .test_serve_linux import Serve, env_for, free_port, https_get, wait_ready

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "manager" / "openapi.json"

HSTS = "max-age=31536000"
CSP = (
    "default-src 'self'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'"
)
HEADERS = {
    "strict-transport-security": HSTS,
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
TYPES = {
    "app-1a2b.js": "text/javascript; charset=utf-8",
    "app-1a2b.css": "text/css; charset=utf-8",
    "logo.svg": "image/svg+xml",
    "img.png": "image/png",
    "favicon.ico": "image/x-icon",
    "font.woff2": "font/woff2",
}
MARK = "FIXTURE-" + secrets.token_hex(6)


def body_of(name: str) -> bytes:
    return f"{MARK}:{name}:".encode() + bytes(range(256))


INDEX = (
    b'<!doctype html><html><head><script type="module" src="/assets/app-1a2b.js">'
    b'</script><link rel="stylesheet" href="/assets/app-1a2b.css"></head>'
    b"<body>" + MARK.encode() + b":index</body></html>"
)
LONG_OK = "a" * 125 + ".js"  # 128 characters
LONG_BAD = "a" * 126 + ".js"  # 129 characters


@dataclass(frozen=True)
class Build:
    folder: Path
    outside: Path


def make_build(root: Path) -> Build:
    folder = root / "webui"
    assets = folder / "assets"
    assets.mkdir(parents=True)
    (folder / "index.html").write_bytes(INDEX)
    for name in TYPES:
        (assets / name).write_bytes(body_of(name))
    for name in (
        "x.map",
        "x.txt",
        "x.html",
        "x.json",
        ".hidden.js",
        "-dash.js",
        "_under.js",
        LONG_BAD,
        "sp ace.js",
        "app.JS",
    ):
        (assets / name).write_bytes(body_of(name))
    (assets / LONG_OK).write_bytes(body_of(LONG_OK))
    (assets / "sub").mkdir()
    (assets / "sub" / "x.js").write_bytes(body_of("sub/x.js"))
    (folder / "app.py").write_bytes(body_of("app.py"))  # next to index.html
    outside = root / "secret.js"
    outside.write_bytes(body_of("outside"))
    if hasattr(os, "symlink"):
        try:
            os.symlink(outside, assets / "link.js")
        except OSError:
            pass
    return Build(folder, outside)


@pytest.fixture
def build(tmp_path: Path) -> Build:
    return make_build(tmp_path)


@pytest.fixture
def app(build: Build) -> FastAPI:
    return create_app(webui=load(build.folder))


@dataclass
class Resp:
    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name: str) -> list[str]:
        return [v for k, v in self.headers if k == name]

    @property
    def content_type(self) -> str:
        values = self.header("content-type")
        return values[0] if values else ""


def call(
    app: Any,
    target: bytes,
    method: str = "GET",
    headers: Sequence[tuple[bytes, bytes]] = (),
    host: bytes = b"manager.example",
) -> Resp:
    """One HTTP request through the ASGI app, with the scope uvicorn builds."""
    raw_path, _, query = target.partition(b"?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": unquote(raw_path.decode("ascii")),
        "raw_path": raw_path,
        "query_string": query,
        "root_path": "",
        "headers": [(b"host", host), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("manager.example", 443),
        "state": {},
    }
    out: dict[str, Any] = {"body": b""}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = [
                (k.decode("latin-1").lower(), v.decode("latin-1"))
                for k, v in message["headers"]
            ]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return Resp(out["status"], out["headers"], out["body"])


def assert_security_headers(r: Resp) -> None:
    for name, value in HEADERS.items():
        assert r.header(name) == [value], (name, r.header(name))


def assert_no_cors(r: Resp) -> None:
    assert [k for k, _ in r.headers if k.startswith("access-control-")] == []


def assert_problem_404(r: Resp) -> None:
    assert r.status == 404, (r.status, r.body[:200])
    assert r.content_type.startswith("application/problem+json")
    doc = json.loads(r.body)
    assert doc["status"] == 404
    assert MARK.encode() not in r.body
    assert b"<html" not in r.body
    assert_security_headers(r)


# ------------------------------------------------------------ CHK-M5-100


def test_index_is_served_with_its_type(app: FastAPI) -> None:
    r = call(app, b"/")
    assert r.status == 200
    assert r.body == INDEX
    assert r.content_type == "text/html; charset=utf-8"


@pytest.mark.parametrize("name", sorted(TYPES))
def test_each_asset_is_served_with_its_fixed_type(app: FastAPI, name: str) -> None:
    r = call(app, b"/assets/" + name.encode())
    assert r.status == 200
    assert r.body == body_of(name)
    assert r.content_type == TYPES[name]


def test_a_128_character_name_is_served(app: FastAPI) -> None:
    r = call(app, b"/assets/" + LONG_OK.encode())
    assert (r.status, r.body) == (200, body_of(LONG_OK))


def test_the_extension_map_is_exactly_the_plan(build: Build) -> None:
    ui = load(build.folder)
    assert ui.index == INDEX
    assert {n: a.content_type for n, a in ui.assets.items()} == {
        **TYPES,
        LONG_OK: "text/javascript; charset=utf-8",
    }


# ------------------------------------------------------------ CHK-M5-101


@pytest.mark.parametrize(
    "target",
    [
        b"/",
        b"/assets/app-1a2b.js",
        b"/assets/app-1a2b.css",
        b"/assets/nope.js",
        b"/index.html",
        b"/assets/../app.py",
    ],
)
def test_every_static_response_has_exactly_the_spec_headers(
    app: FastAPI, target: bytes
) -> None:
    r = call(app, target)
    assert_security_headers(r)
    assert_no_cors(r)


# ------------------------------------------------------------ CHK-M5-102

TRAVERSAL = [
    b"/assets/../app.py",
    b"/assets/..%2Fapp.py",
    b"/assets/..%2fapp.py",
    b"/assets/%2e%2e%2fapp.py",
    b"/assets/%2E%2E%2Fapp.py",
    b"/assets/%2e%2e/app.py",
    b"/assets/..%5Capp.py",
    b"/assets/..\\app.py",
    b"/assets/%2Fetc%2Fpasswd",
    b"/assets//etc/passwd",
    b"/assets/%252e%252e%252fapp.py",
    b"/assets/a%5Cb.js",
    b"/assets/sub/x.js",
    b"/assets/sub%2Fx.js",
    b"/assets/sub%5Cx.js",
    b"/assets/",
    b"/assets",
    b"/assets/.",
    b"/assets/..",
    b"/index.html",
    b"/app.py",
    b"/../app.py",
    b"/%2e%2e/app.py",
    b"/webui/index.html",
    b"/favicon.ico",
    b"/assets/x.map",
    b"/assets/x.txt",
    b"/assets/x.html",
    b"/assets/x.json",
    b"/assets/.hidden.js",
    b"/assets/-dash.js",
    b"/assets/_under.js",
    b"/assets/sp%20ace.js",
    b"/assets/app.JS",
    b"/assets/APP-1A2B.JS",
    b"/assets/app-1a2b.js%00",
    b"/assets/app-1a2b.js%00.png",
    b"/assets/app-1a2b.js;x",
    b"/assets/" + LONG_BAD.encode(),
    b"/assets/link.js",
    b"/assets/secret.js",
    b"/assets/%2E%2E%2Fsecret.js",
    b"/assets/..%2F..%2Fsecret.js",
    # Paths that resolve to a real asset if anything joins or normalises them.
    b"/assets/sub/../app-1a2b.js",
    b"/assets/sub%2F..%2Fapp-1a2b.js",
    b"/assets/..%2Fassets%2Fapp-1a2b.js",
    b"/assets/.%2Fapp-1a2b.js",
    b"/assets/./app-1a2b.js",
    b"/./assets/app-1a2b.js",
    b"//assets/app-1a2b.js",
    b"/x/../assets/app-1a2b.js",
]


@pytest.mark.parametrize("target", TRAVERSAL, ids=lambda t: t.decode("latin-1"))
def test_everything_else_is_the_problem_404_with_no_file_content(
    app: FastAPI, target: bytes
) -> None:
    """TASK-112 r1 (user ruling 2026-10-25, redirect_slashes off app-wide):
    every one of them is the problem 404, never a redirect."""
    r = call(app, target)
    assert_problem_404(r)
    assert r.header("location") == []


AGENT = "0f8fad5b-d9cb-469f-a165-70867728950e"
SLASHED = [
    ("GET", b"/assets/app-1a2b.js/"),
    ("GET", b"/assets/app-1a2b.css/"),
    ("GET", b"/assets/"),
    ("GET", b"//"),
    ("GET", b"/healthz/"),
    ("GET", b"/readyz/"),
    ("GET", b"/api/v1/agents/"),
    ("GET", b"/api/v1/agents/?limit=1"),
    ("GET", b"/api/v1/packages/search/"),
    ("GET", b"/api/v1/packages/search.csv/"),
    ("GET", b"/api/v1/enrollment-tokens/"),
    ("GET", b"/api/v1/audit-log/"),
    ("POST", b"/api/v1/auth/login/"),
    ("POST", b"/api/v1/agent/enroll/"),
    ("GET", b"/api/v1/agent/" + AGENT.encode() + b"/jobs/"),
    ("POST", b"/api/v1/agent/" + AGENT.encode() + b"/heartbeat/"),
    ("PUT", b"/api/v1/agent/" + AGENT.encode() + b"/inventory/"),
]


@pytest.mark.parametrize(
    ("method", "target"), SLASHED, ids=[f"{m} {t.decode()}" for m, t in SLASHED]
)
def test_a_trailing_slash_is_the_problem_404_with_no_location(
    app: FastAPI, method: str, target: bytes
) -> None:
    """TASK-112 r1, user ruling 2026-10-25: redirect_slashes is off for the
    whole manager, so a slashed path that matches no route gets the standard
    problem+json 404 with the TS §6.3 headers, and no Location is ever built
    from the Host header (REQ-118)."""
    r = call(app, target, method=method, host=b"evil.example")
    assert_problem_404(r)
    assert r.header("location") == []
    assert b"evil.example" not in r.body
    assert_no_cors(r)


def test_the_slash_less_paths_still_answer(app: FastAPI) -> None:
    """Control for the test above: the same paths without the slash match."""
    assert call(app, b"/assets/app-1a2b.js").body == body_of("app-1a2b.js")
    assert call(app, b"/healthz").status == 200
    # The route matches (this app has no runtime, so it is not ready): not 404.
    assert call(app, b"/api/v1/agents").status == 503
    assert call(app, b"/api/v1/agents/").status == 404


# ------------------------------------------------------------ CHK-M5-103


def test_files_added_or_changed_after_creation_are_not_served(
    build: Build, app: FastAPI
) -> None:
    assets = build.folder / "assets"
    (assets / "late.js").write_bytes(body_of("late"))
    (assets / "app-1a2b.js").write_bytes(b"CHANGED")
    (build.folder / "index.html").write_bytes(b"CHANGED")
    assert_problem_404(call(app, b"/assets/late.js"))
    assert call(app, b"/assets/app-1a2b.js").body == body_of("app-1a2b.js")
    assert call(app, b"/").body == INDEX


def test_a_deleted_folder_does_not_change_answers(build: Build, app: FastAPI) -> None:
    for p in sorted(build.folder.rglob("*"), reverse=True):
        if p.is_symlink() or p.is_file():
            p.unlink()
        else:
            p.rmdir()
    assert call(app, b"/").body == INDEX
    assert call(app, b"/assets/app-1a2b.css").body == body_of("app-1a2b.css")


# ------------------------------------------------------------ CHK-M5-104


@pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only (symlinks)")
def test_a_symlinked_asset_is_never_served(build: Build) -> None:
    assets = build.folder / "assets"
    assert (assets / "link.js").is_symlink()
    ui = load(build.folder)
    assert "link.js" not in ui.assets
    assert_problem_404(call(create_app(webui=ui), b"/assets/link.js"))


@pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only (symlinks)")
def test_a_symlinked_index_or_assets_folder_is_not_loaded(tmp_path: Path) -> None:
    real = make_build(tmp_path / "real")
    linked = tmp_path / "linked"
    linked.mkdir()
    os.symlink(real.folder / "index.html", linked / "index.html")
    assert load(linked).index is None
    other = tmp_path / "other"
    other.mkdir()
    (other / "index.html").write_bytes(INDEX)
    os.symlink(real.folder / "assets", other / "assets")
    ui = load(other)
    assert ui.index == INDEX
    assert dict(ui.assets) == {}


@pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only (FIFO)")
def test_a_fifo_in_assets_does_not_block_or_load(tmp_path: Path) -> None:
    b = make_build(tmp_path)
    mkfifo = getattr(os, "mkfifo", None)
    assert mkfifo is not None
    mkfifo(b.folder / "assets" / "pipe.js")
    ui = load(b.folder)
    assert "pipe.js" not in ui.assets
    assert "app-1a2b.js" in ui.assets


# ------------------------------------------------------------ CHK-M5-105


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("GET", b"/"),
        ("GET", b"/assets/app-1a2b.js"),
        ("GET", b"/assets/nope.js"),
        ("OPTIONS", b"/"),
        ("OPTIONS", b"/assets/app-1a2b.js"),
        ("OPTIONS", b"/api/v1/agents"),
    ],
)
def test_no_cors_headers_even_for_a_preflight(
    app: FastAPI, method: str, target: bytes
) -> None:
    r = call(
        app,
        target,
        method,
        [
            (b"origin", b"https://evil.example"),
            (b"access-control-request-method", b"GET"),
            (b"access-control-request-headers", b"authorization"),
        ],
    )
    assert_no_cors(r)
    assert_security_headers(r)
    if method == "OPTIONS":
        assert r.status in (404, 405)
        assert MARK.encode() not in r.body


# ------------------------------------------------------------ CHK-M5-106


@pytest.mark.parametrize(
    "auth",
    [b"Bearer bsa_" + b"A" * 43, b"Bearer garbage", b"Basic Zm9vOmJhcg==", b""],
)
def test_no_token_is_needed_and_a_bad_one_changes_nothing(
    app: FastAPI, auth: bytes
) -> None:
    headers = [(b"authorization", auth)] if auth else []
    for _ in range(25):  # more than the 20 failed checks per minute per IP
        r = call(app, b"/", headers=headers)
        assert (r.status, r.body) == (200, INDEX)
    r = call(app, b"/assets/app-1a2b.js", headers=headers)
    assert r.status == 200


# ------------------------------------------------------------ CHK-M5-107


@pytest.mark.parametrize(
    "target",
    [
        b"/api/v1/unknown",
        b"/api/v1/",
        b"/api/v1",
        b"/unknown",
        b"/hosts",
        b"/hosts/0f8fad5b-d9cb-469f-a165-70867728950e",
        b"/packages",
    ],
)
def test_unknown_paths_never_get_the_index(app: FastAPI, target: bytes) -> None:
    r = call(app, target)
    assert r.status == 404
    assert r.body != INDEX
    assert_problem_404(r)


def test_api_routes_still_need_their_token(app: FastAPI) -> None:
    r = call(app, b"/api/v1/agents")
    assert r.status in (401, 503)  # 401 with a runtime; no runtime here
    assert MARK.encode() not in r.body


# ------------------------------------------------------------ CHK-M5-108


def test_no_build_gives_404_and_the_api_is_unchanged(
    tmp_path: Path, build: Build
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    for ui in (load(empty), load(tmp_path / "missing"), WebUi()):
        assert ui.index is None and dict(ui.assets) == {}
        bare = create_app(webui=ui)
        assert_problem_404(call(bare, b"/"))
        assert_problem_404(call(bare, b"/assets/app-1a2b.js"))
        built = create_app(webui=load(build.folder))
        for target in (b"/healthz", b"/readyz", b"/api/v1/agents", b"/api/v1/nope"):
            a, b = call(bare, target), call(built, target)
            assert (a.status, a.body) == (b.status, b.body), target


def test_assets_without_an_index_are_not_served(tmp_path: Path) -> None:
    b = make_build(tmp_path)
    (b.folder / "index.html").unlink()
    ui = load(b.folder)
    assert ui.index is None and dict(ui.assets) == {}


def test_a_build_over_32_mib_is_not_loaded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    b = make_build(tmp_path)
    total = sum(
        p.stat().st_size
        for p in [
            b.folder / "index.html",
            *(b.folder / "assets" / n for n in [*TYPES, LONG_OK]),
        ]
    )
    (b.folder / "assets" / "big.js").write_bytes(b"x" * (32 * 1_048_576 - total))
    assert load(b.folder).index == INDEX  # exactly 32 MiB in total: loaded
    (b.folder / "assets" / "big2.js").write_bytes(b"y")
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        ui = load(b.folder)
    assert ui.index is None and dict(ui.assets) == {}
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert str(tmp_path) not in errors[0].getMessage()


# ------------------------------------------------------------ CHK-M5-109


def test_static_routes_are_not_in_the_document(build: Build) -> None:
    with_ui = create_app(webui=load(build.folder)).openapi()
    without = create_app(webui=WebUi()).openapi()
    assert with_ui == without
    assert "/" not in with_ui["paths"]
    assert not [p for p in with_ui["paths"] if p.startswith("/assets")]
    assert with_ui == json.loads(DOCUMENT.read_text(encoding="utf-8"))


# ------------------------------------------------------------ CHK-M5-112


def test_query_strings_are_ignored(app: FastAPI) -> None:
    assert call(app, b"/?x=1&cursor=../../etc").body == INDEX
    r = call(app, b"/assets/app-1a2b.js?v=../../app.py")
    assert (r.status, r.body) == (200, body_of("app-1a2b.js"))


def test_head_and_post_are_not_static_routes(app: FastAPI) -> None:
    for method in ("HEAD", "POST", "PUT", "DELETE"):
        r = call(app, b"/", method)
        assert r.status == 405, (method, r.status)
        assert MARK.encode() not in r.body
        assert_security_headers(r)


# ------------------------------------------------------------ CHK-M5-110 (serve)


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("webui-db")) as server:
        yield server


LAUNCHER = (
    "import os, sys, pathlib\n"
    "import bitscan_manager.api.webui as w\n"
    "w.DEFAULT_WEBUI_DIR = pathlib.Path(sys.argv[1])\n"
    "from bitscan_manager.cli.serve import serve_main\n"
    "sys.exit(serve_main(os.environ, queue_dir=pathlib.Path(sys.argv[2])))\n"
)


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("webui-pki"))


@pytest.fixture
def sink(pki: Pki) -> Iterator[Any]:
    leaf = pki.leaf("sink-webui")
    with https_sink(server_context(leaf.cert, leaf.key)) as s:
        yield s


@pytest.fixture
def serve_with(migrated_db: Any, tmp_path: Path, pki: Pki, sink: Any) -> Iterator[Any]:
    started: list[Any] = []

    def start(folder: Path) -> Any:
        leaf = pki.leaf(f"webui-{secrets.token_hex(4)}")
        port = free_port()
        run = tmp_path / secrets.token_hex(4)
        run.mkdir()
        env = env_for(
            migrated_db, run, pki, leaf, f"https://localhost:{sink.port}/a", port
        )
        log = run / "serve.log"
        proc = subprocess.Popen(  # noqa: S603  # fixed argv, no untrusted input
            [sys.executable, "-c", LAUNCHER, str(folder), str(run / "queue")],
            env=env,
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        s = Serve(proc, port, leaf.cert, leaf.key, pki.ca, run / "queue", log)
        started.append(s)
        wait_ready(s)
        return s

    yield start
    for s in started:
        if s.proc.poll() is None:
            s.stop()


@pytest.mark.pg
@pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only (serve)")
def test_serve_without_a_build_logs_one_line_and_answers_404(
    serve_with: Any, tmp_path: Path
) -> None:
    empty = tmp_path / "no-build"
    empty.mkdir()
    s = serve_with(empty)
    status, headers, body = https_get(s.port, s.ca, "/")
    assert status == 404
    assert headers["content-type"].startswith("application/problem+json")
    for name, value in HEADERS.items():
        assert headers[name] == value
    assert https_get(s.port, s.ca, "/healthz")[0] == 200
    assert https_get(s.port, s.ca, "/api/v1/agents")[0] == 401
    s.stop()
    lines = [ln for ln in s.output().splitlines() if "web ui not built" in ln]
    assert len(lines) == 1, s.output()[-2000:]


@pytest.mark.pg
@pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only (serve)")
def test_serve_with_a_build_serves_it_and_refuses_raw_traversal(
    serve_with: Any, tmp_path: Path
) -> None:
    b = make_build(tmp_path / "b")
    s = serve_with(b.folder)
    status, headers, body = https_get(s.port, s.ca, "/")
    assert (status, body) == (200, INDEX)
    assert headers["content-type"] == "text/html; charset=utf-8"
    for name, value in HEADERS.items():
        assert headers[name] == value
    assert not [k for k in headers if k.startswith("access-control-")]
    for name, kind in TYPES.items():
        status, headers, body = https_get(s.port, s.ca, "/assets/" + name)
        assert (status, body, headers["content-type"]) == (200, body_of(name), kind)
    raw = [t.decode("latin-1") for t in TRAVERSAL if b"\\" not in t]
    for target in raw:
        status, headers, body = https_get(s.port, s.ca, target)
        assert status != 200, target
        assert MARK.encode() not in body, target
        assert "location" not in headers, target  # TASK-112 r1
    for target in ("/assets/app-1a2b.js/", "/api/v1/agents/", "/healthz/"):
        status, headers, body = https_get(s.port, s.ca, target)
        assert status == 404, target
        assert headers["content-type"].startswith("application/problem+json")
        assert "location" not in headers, target
    assert "web ui not built" not in s.output()
