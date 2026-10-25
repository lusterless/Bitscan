"""M5 security and invariants suite (TP-M5-22, G46): CHK-M5-300, -301, -303,
-304 of tests/m5/test-plan.md.

Expected values: TS §2.2/§3.3 (no route queues a command, the agent opens
every connection), §3.4/§6.2 (nothing disables inventory), §6 (user routes
take bsu_ and bsk_ only; agent tokens refused there), §6.2 L1117 (both package
routes viewer), §6.3 L1140 (the four headers on every response), §8.1/§8.4
and the security invariants (no token, plugin output or other secret in a
log line), REQ-113 to REQ-119; decisions 2026-10-24 "M5 breakdown approved"
(#6 M5 half: `/` and `/assets/<file>` without a token, GET only, no query
input) and 2026-10-25 "Trailing-slash redirects turned off app-wide".

CHK-M5-303 and -304 run against a real `serve` (HTTPS, PostgreSQL, fake OpenBao
and audit sink) that serves the real UI build in
manager/bitscan_manager/webui/ (`npm run build`); CI=true requires the build.
"""

import gzip
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token

from .canary import new_canary, sweep
from .certs import make_pki
from .conftest import PgServer, own_migrated_server
from .contract import loader
from .fake_sink import https_sink, server_context
from .fake_vault import fake_vault
from .test_auth_dependencies import api_routes
from .test_cli_users_pg import run as run_users
from .test_invariants_m3 import (
    PACKAGE_PATHS,
    SEARCH_PARAMS,
    STATIC_OPS,
    operations,
    spec_violations,
)
from .test_inventory_ingest import oracle_sha256, os_info
from .test_serve_linux import CANARY_VAULT, Serve, env_for, free_port, https_get

pytestmark = pytest.mark.pg

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "manager" / "bitscan_manager" / "webui"
FIX = loader.FIXTURES
V1 = "/api/v1"
HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "content-security-policy": "default-src 'self'; frame-ancestors 'none';"
    " object-src 'none'; base-uri 'none'; form-action 'self'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
LAUNCHER = (
    "import os, sys, pathlib\n"
    "import bitscan_manager.api.webui as w\n"
    "w.DEFAULT_WEBUI_DIR = pathlib.Path(sys.argv[1])\n"
    "from bitscan_manager.cli.serve import serve_main\n"
    "sys.exit(serve_main(os.environ, queue_dir=pathlib.Path(sys.argv[2])))\n"
)
# tests/m5/test-plan.md "Static UI" (plan TASK-112), not the code's own map.
TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
LINUX = pytest.mark.skipif(sys.platform == "win32", reason="not run: Linux only")


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    """A database of this module's own: its host must be the only one listed
    (the session database holds every other test's hosts)."""
    with own_migrated_server(tmp_path_factory.mktemp("sec5-db")) as server:
        yield server


# ------------------------------------------------------------ CHK-M5-300


def test_the_route_walk_holds_with_the_package_and_static_routes() -> None:
    """Every operation is a spec route (the M3 allow-list extended for M5),
    both package routes are GET, and the static routes are GET only."""
    app = create_app()
    ops = operations(app)
    assert spec_violations(ops) == []
    assert {("GET", p) for p in PACKAGE_PATHS} <= ops
    assert {m for m, p in ops if p in PACKAGE_PATHS} == {"GET"}
    assert STATIC_OPS <= ops
    static_methods = {m for m, p in ops if p in {"/", "/assets/{}"}}
    assert static_methods == {"GET"}


def test_no_package_or_static_route_takes_a_command_or_inventory_switch() -> None:
    """The package routes read exactly the TS §7.1 parameters (plus limit and
    cursor on the JSON route); no parameter can name a command or switch
    inventory; the static routes read no query parameter at all."""
    switch = re2.compile(
        r"(?i)inventor|disable|enable|skip|pause|cmd|command|exec|script"
    )
    for route in api_routes(create_app().routes):
        path = getattr(route, "path", "")
        if path in PACKAGE_PATHS:
            names = {p.alias or p.name for p in route.dependant.query_params}
            for dep in route.dependant.dependencies:
                names |= {p.alias or p.name for p in dep.query_params}
            extra = {"limit", "cursor"} if path.endswith("/search") else set()
            assert names == SEARCH_PARAMS | extra, (path, names)
            assert not [n for n in names if switch.search(n)]
        if path in {"/", "/assets/{name}"}:
            q = list(route.dependant.query_params)
            for dep in route.dependant.dependencies:
                q += dep.query_params
            assert q == [], path


def test_the_static_routes_are_not_documented() -> None:
    doc = create_app().openapi()
    assert "/" not in doc["paths"] and "/assets/{name}" not in doc["paths"]


# ------------------------------------------------------------ fixtures


def built() -> Path:
    if not (BUILD / "index.html").is_file():
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("the web UI build is missing: run `npm run build` in web/")
        pytest.skip("not run: no web UI build")
    return BUILD


def start_serve(
    env: dict[str, str],
    run: Path,
    folder: Path,
    port: int,
    ca: Path,
    cert: Path,
    key: Path,
) -> Serve:
    log = run / "serve.log"
    proc = subprocess.Popen(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", LAUNCHER, str(folder), str(run / "queue")],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )
    s = Serve(proc, port, cert, key, ca, run / "queue", log)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(
                f"serve exited {proc.returncode}: {s.output()[-2000:]}"
            )
        try:
            if https_get(port, ca, "/readyz")[0] == 200:
                return s
        except OSError:
            pass
        time.sleep(0.2)
    raise AssertionError("serve not ready: " + s.output()[-2000:])


class Live:
    def __init__(self, s: Serve, dsn: Path) -> None:
        self.s = s
        self.dsn = dsn

    def req(
        self,
        method: str,
        path: str,
        token: str | None = None,
        body: Any = None,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        h = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        return https_get(self.s.port, self.s.ca, path, h, data, method)


@pytest.fixture(scope="module")
def live(
    migrated_db: PgServer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Live]:
    if sys.platform == "win32":
        pytest.skip("not run: Linux only (serve)")
    folder = built()
    tmp = tmp_path_factory.mktemp("sec-m5")
    pki = make_pki(tmp / "pki")
    sink_leaf, vault_leaf, leaf = pki.leaf("sink"), pki.leaf("vault"), pki.leaf("srv")
    with (
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as v,
    ):
        port = free_port()
        run = tmp / "run"
        run.mkdir()
        env = env_for(
            migrated_db,
            run,
            pki,
            leaf,
            f"https://localhost:{sink.port}/audit",
            port,
            BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{v.port}",
        )
        s = start_serve(env, run, folder, port, pki.ca, leaf.cert, leaf.key)
        try:
            yield Live(s, run / "creds" / "app_dsn")
        finally:
            if s.proc.poll() is None:
                s.stop()


def sign_in_viewer(live: Live) -> str:
    """A viewer through the API (an admin made by the CLI enrols TOTP first)."""
    import base64
    from datetime import UTC, datetime

    from bitscan_manager.auth.totp import code_at, step_at

    admin, pw = f"sec5-{secrets.token_hex(3)}", "sec5 pass " + secrets.token_hex(6)
    assert run_users(["create-admin", admin], live.dsn, stdin=pw + "\n").returncode == 0
    login = V1 + "/auth/login"
    st, _, out = live.req("POST", login, body={"username": admin, "password": pw})
    assert st == 200
    s0 = json.loads(out)["token"]
    st, _, out = live.req("POST", V1 + "/auth/totp/enrol", token=s0, body={})
    secret = json.loads(out)["secret"]
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    step = step_at(datetime.now(UTC))
    st, _, out = live.req(
        "POST",
        V1 + "/auth/totp/enrol",
        token=s0,
        body={"totp_code": code_at(seed, step)},
    )
    assert st == 200, out
    admin_s = json.loads(out)["token"]
    vname, vpw = f"sec5v-{secrets.token_hex(3)}", "sec5 viewer " + secrets.token_hex(6)
    assert (
        live.req(
            "POST",
            V1 + "/users",
            token=admin_s,
            body={"username": vname, "password": vpw},
        )[0]
        == 201
    )
    st, _, out = live.req("POST", login, body={"username": vname, "password": vpw})
    assert st == 200
    live.admin = admin_s  # type: ignore[attr-defined]
    live.secrets = [pw, vpw, s0, admin_s, secret]  # type: ignore[attr-defined]
    token = json.loads(out)["token"]
    live.secrets.append(token)  # type: ignore[attr-defined]
    return str(token)


# ------------------------------------------------------------ CHK-M5-301


@LINUX
def test_token_groups_on_both_package_routes(live: Live) -> None:
    viewer = sign_in_viewer(live)
    st, _, out = live.req("POST", V1 + "/api-tokens", token=viewer, body={"name": "k"})
    assert st == 201
    bsk = json.loads(out)["token"]
    live.secrets.append(bsk)  # type: ignore[attr-defined]
    for path in sorted(PACKAGE_PATHS):
        url = path + "?name=openssl"
        for tok in (
            None,
            new_agent_token(AgentTokenKind.AGENT),
            new_agent_token(AgentTokenKind.ENROLMENT),
            "bsu_" + "A" * 43,
        ):
            st, h, out = live.req("GET", url, token=tok)
            assert st == 401, (path, tok and tok[:4], st)
            assert json.loads(out)["type"] == "unauthorized"
            assert all(h.get(k) == v for k, v in HEADERS.items())
        for tok in (viewer, bsk):
            st, h, _ = live.req("GET", url, token=tok)
            assert st == 200, (path, tok[:4], st)
            assert all(h.get(k) == v for k, v in HEADERS.items())


# ------------------------------------------------------------ CHK-M5-304


@LINUX
def test_the_served_bundle_answers_with_headers_and_types(live: Live) -> None:
    folder = built()
    index = (folder / "index.html").read_bytes()
    st, h, out = live.req("GET", "/")
    assert (st, out) == (200, index)
    assert h["content-type"] == "text/html; charset=utf-8"
    assert all(h.get(k) == v for k, v in HEADERS.items())
    assert not [k for k in h if k.startswith("access-control-")]
    refs = re2.findall(r'(?:src|href)="(/[^"]*)"', index.decode("utf-8"))
    assert refs, "index.html references no file"
    for ref in refs:
        st, h, out = live.req("GET", ref)
        assert st == 200, ref
        assert out == (folder / ref.lstrip("/")).read_bytes()
        assert h["content-type"] == TYPES[Path(ref).suffix], ref
        assert all(h.get(k) == v for k, v in HEADERS.items()), ref
    for name in sorted(p.name for p in (folder / "assets").iterdir()):
        st, _, _ = live.req("GET", "/assets/" + name)
        assert st == 200, name
    for bad in (
        "/assets/../index.html",
        "/assets/%2e%2e/index.html",
        "/index.html",
        "/assets/" + refs[0].rsplit("/", 1)[-1] + "/",
        "/favicon.ico",
    ):
        st, h, out = live.req("GET", bad)
        assert st == 404, bad
        assert "location" not in h and index not in out


# ------------------------------------------------------------ CHK-M5-303


@LINUX
def test_canary_sweep_over_package_search_and_csv(
    live: Live, migrated_db: PgServer
) -> None:
    """Hostile and canary package names, a canary hostname, formula CSV cells
    and every token used reach no line of serve's log."""
    viewer = sign_in_viewer(live)
    admin = live.admin  # type: ignore[attr-defined]
    pkg_canary = new_canary("pkg")
    host_canary = new_canary("host")
    formula = '=HYPERLINK("http://' + new_canary("csv") + '")'
    st, _, out = live.req(
        "POST", V1 + "/enrollment-tokens", token=admin, body={"auto_approve": True}
    )
    assert st == 201
    bse = json.loads(out)["token"]
    base = json.loads((FIX / "enrol" / "request_valid_full.json").read_text("utf-8"))
    mid = secrets.token_hex(16)
    st, _, out = live.req(
        "POST",
        V1 + "/agent/enroll",
        token=bse,
        body=base | {"hostname": host_canary, "machine_id": mid},
    )
    assert st == 200, out
    agent, bsa = json.loads(out)["agent_id"], json.loads(out)["agent_token"]
    ah = {"X-Bitscan-Machine-Id": mid}
    st, _, out = live.req("GET", f"{V1}/agent/{agent}/jobs", token=bsa, headers=ah)
    job = json.loads(out)["jobs"][0]["job_id"]
    pkgs = [
        (pkg_canary, "1.0", "amd64", "install ok installed", "", 1),
        (formula, "1.0", "all", "install ok installed", "", 1),
        (
            "<script>" + pkg_canary + "</script>",
            "2.0",
            "all",
            "install ok installed",
            "",
            None,
        ),
    ]
    inv = {
        "os_info": os_info(),
        "packages": [
            {
                "name": n,
                "version": v,
                "architecture": a,
                "status": s_,
                "source": src or None,
                "installed_size_kb": kb,
            }
            for n, v, a, s_, src, kb in pkgs
        ],
        "list_sha256": oracle_sha256(pkgs),
    }
    st, _, out = live.req(
        "PUT",
        f"{V1}/agent/{agent}/inventory?job_id={job}",
        token=bsa,
        raw=gzip.compress(json.dumps(inv).encode()),
        headers=ah | {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert st == 204, out
    seen_rows = 0
    for path in sorted(PACKAGE_PATHS):
        for params in (
            {"q": pkg_canary[:20]},
            {"name": formula},
            {"host": host_canary, "group_by": "host"},
            {"agent_id": agent, "status": "any"},
            {"q": "ab"},
            {"name": pkg_canary, "version": "1.0 " + pkg_canary},
        ):
            st, _, out = live.req("GET", path + "?" + urlencode(params), token=viewer)
            assert st in (200, 400)
            seen_rows += out.count(pkg_canary.encode())
    assert seen_rows > 0, "the canaries were not found by the searches"
    st, _, out = live.req(
        "GET",
        V1 + "/packages/search.csv?" + urlencode({"agent_id": agent}),
        token=viewer,
    )
    assert st == 200 and b"\"'=HYPERLINK(" in out
    log = live.s.output()
    canaries = [
        pkg_canary,
        host_canary,
        formula,
        formula[1:],
        bse,
        bse[4:],
        bsa,
        bsa[4:],
        viewer,
        viewer[4:],
        admin,
        *live.secrets,  # type: ignore[attr-defined]
    ]
    assert sweep(canaries, log) == []
    for line in log.splitlines():
        if line.strip():
            json.loads(line)  # every line is one JSON record
    access = [
        json.loads(ln)
        for ln in log.splitlines()
        if ln.strip() and "packages/search" in ln
    ]
    assert access, "no access record for the package routes"
    assert all("?" not in str(r.get("path", "")) for r in access)
