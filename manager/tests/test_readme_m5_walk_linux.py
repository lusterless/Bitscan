"""TASK-128 TEST (TP-M5-21, REQ-135): walk the M5 README sections ("Web UI",
"Package search", the M5 lines of "API" and "Enrolling agents") against a
real `serve` over HTTPS that serves a real UI build, on PostgreSQL, with the
fake OpenBao and audit sink and the real clock.

Expected answers come from README.md, not from the code. Every documented
request and its answer is recorded as one row; a row that differs from the
README is a deviation, the run collects them all, and the test fails if there
is any. With WALK_OUT set, the rows are written there as JSON lines.

The UI build is the real `npm run build` output when it is present in the
copy (`manager/bitscan_manager/webui/`, the README's build folder); the test
requires it under CI=true. The browser steps of the "Web UI" section (forms,
buttons) are covered by the Vitest suites and by the user's walk-through
(CHK-M5-305); here the HTTP side of each step is walked: the same requests the
UI sends, with the same answers.
"""

import base64
import csv
import gzip
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.auth.totp import code_at, step_at

from .certs import make_pki
from .conftest import PgServer, own_migrated_server
from .contract import loader
from .fake_sink import https_sink, server_context
from .fake_vault import fake_vault
from .test_cli_users_pg import run as run_users
from .test_inventory_ingest import oracle_sha256, os_info
from .test_serve_linux import CANARY_VAULT, Serve, env_for, free_port, https_get

pytestmark = pytest.mark.pg

if sys.platform == "win32":  # serve, signals and openssl: Linux only
    pytest.skip("not run: Linux only (serve)", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
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
FORMULA = '=HYPERLINK("http://x")'


@dataclass
class Row:
    label: str
    request: str
    expected: str
    actual: str
    ok: bool


@dataclass
class Walk:
    port: int
    ca: Path
    rows: list[Row] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)

    def hide(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<secret>")
        return text

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
        return https_get(self.port, self.ca, path, h, data, method)

    def check(
        self, label: str, request: str, expected: str, actual: str, ok: bool
    ) -> bool:
        self.rows.append(
            Row(label, self.hide(request), expected, self.hide(actual), ok)
        )
        return ok

    def expect(
        self,
        label: str,
        method: str,
        path: str,
        want: int,
        want_type: str | None = None,
        **kw: Any,
    ) -> tuple[int, dict[str, str], bytes]:
        st, hdrs, out = self.req(method, path, **kw)
        got = None
        if hdrs.get("content-type", "").startswith("application/problem+json"):
            got = json.loads(out).get("type")
        self.check(
            label,
            f"{method} {path}",
            f"{want}" + (f" {want_type}" if want_type else ""),
            f"{st}" + (f" {got}" if got else ""),
            st == want and (want_type is None or got == want_type),
        )
        return st, hdrs, out


class Totp:
    def __init__(self) -> None:
        self.used = -1

    def code(self, seed: bytes) -> str:
        while True:
            now = step_at(datetime.now(UTC))
            for step in (now, now + 1):
                if step > self.used:
                    self.used = step
                    return code_at(seed, step)
            time.sleep(0.5)


def readme() -> str:
    return README.read_text(encoding="utf-8")


def section(title: str) -> str:
    text = readme()
    start = text.index("\n## " + title + "\n")
    end = text.find("\n## ", start + 4)
    return text[start : end if end != -1 else len(text)]


def built() -> Path:
    """The real build (README "Building"): index.html plus assets/index-<hash>.js."""
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


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    """A database of this module's own: its host must be the only one listed
    (the session database holds every other test's hosts)."""
    with own_migrated_server(tmp_path_factory.mktemp("m5walk-db")) as server:
        yield server


@pytest.fixture
def stack(migrated_db: PgServer, tmp_path: Path) -> Iterator[dict[str, Any]]:
    pki = make_pki(tmp_path / "pki")
    sink_leaf, vault_leaf = pki.leaf("sink"), pki.leaf("vault")
    with (
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as v,
    ):
        started: list[Serve] = []

        def serve(folder: Path) -> Serve:
            leaf = pki.leaf("srv-" + secrets.token_hex(3))
            port = free_port()
            run = tmp_path / ("run-" + secrets.token_hex(3))
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
            started.append(s)
            return s

        try:
            yield {"serve": serve, "creds": tmp_path}
        finally:
            for s in started:
                if s.proc.poll() is None:
                    s.stop()


def test_the_m5_readme_sections_behave_as_written(  # noqa: PLR0915
    stack: dict[str, Any], migrated_db: PgServer, tmp_path: Path
) -> None:
    folder = built()
    totp = Totp()

    # ------------------------------------------------------ Web UI: building
    ui = section("Web UI")
    index = (folder / "index.html").read_bytes()
    assets = sorted(p.name for p in (folder / "assets").iterdir())
    refs = re2.findall(rb'(?:src|href)="(/assets/[^"]+)"', index)
    s = stack["serve"](folder)
    w = Walk(s.port, s.ca)
    w.check(
        "build output",
        "manager/bitscan_manager/webui/",
        "index.html and assets/index-<hash>.js",
        f"index.html, assets {assets}",
        any(re2.fullmatch(r"index-[A-Za-z0-9_-]+\.js", a) for a in assets)
        and len(refs) >= 1,
    )

    # ------------------------------------------------------ Web UI: served
    st, h, out = w.req("GET", "/")
    w.check(
        "GET / is index.html, no token",
        "GET /",
        "200 text/html, the build's index.html, TS §6.3 headers",
        f"{st} {h.get('content-type')}",
        st == 200
        and out == index
        and h.get("content-type") == "text/html; charset=utf-8"
        and all(h.get(k) == v for k, v in HEADERS.items()),
    )
    # The index loads the script and, since the UI shell, its stylesheet; each
    # has one fixed type by extension (an unknown extension expects nothing).
    asset_types = {
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
    }
    for ref in refs:
        path = ref.decode()
        st, h, out = w.req("GET", path)
        w.check(
            "GET an asset the index loads, no token",
            "GET " + path,
            "200 with the file's bytes and its fixed type",
            f"{st} {h.get('content-type')}",
            st == 200
            and out == (folder / path.removeprefix("/")).read_bytes()
            and h.get("content-type") == asset_types.get(os.path.splitext(path)[1]),
        )
    for path in (
        "/index.html",
        "/favicon.ico",
        "/assets/",
        "/assets/sub/x.js",
        "/assets/" + assets[0] + "/",
        "/hosts",
        "/assets/x.map",
    ):
        st, h, out = w.req("GET", path)
        w.check(
            "other paths are the problem 404",
            "GET " + path,
            "404 problem+json, no Location",
            f"{st} {h.get('content-type')}",
            st == 404
            and h.get("content-type", "").startswith("application/problem+json")
            and "location" not in h
            and index not in out,
        )
    st, h, _ = w.req("GET", V1 + "/agents/")
    w.check(
        "trailing slash is not redirected",
        "GET /api/v1/agents/",
        "404",
        f"{st} location={h.get('location')}",
        st == 404 and "location" not in h,
    )
    st, _, _ = w.req("GET", V1 + "/agents")
    w.check(
        "every API call needs the session token",
        "GET /api/v1/agents (none)",
        "401",
        str(st),
        st == 401,
    )
    w.check(
        "the README says restart serve after a build",
        "Web UI > Building",
        "reads that folder once, at start-up",
        "stated" if "once, at start-up" in ui else "missing",
        "once, at start-up" in ui,
    )

    # restart behaviour: a file added after start is not served
    late = tmp_path / "late-build"
    shutil.copytree(folder, late)
    s2 = stack["serve"](late)
    (late / "assets" / "late-0000.js").write_bytes(b"late")
    st2, _, _ = https_get(s2.port, s2.ca, "/assets/late-0000.js")
    w.check(
        "a file added after start-up is not served",
        "GET /assets/late-0000.js",
        "404 until restart",
        str(st2),
        st2 == 404,
    )
    s2.stop()

    # without a build
    empty = tmp_path / "no-build"
    empty.mkdir()
    s3 = stack["serve"](empty)
    st3, _, _ = https_get(s3.port, s3.ca, "/")
    s3.stop()
    lines = [ln for ln in s3.output().splitlines() if "web ui not built" in ln]
    w.check(
        "without a build: one log line and 404",
        "serve with an empty build folder",
        "log `web ui not built; serving the API only`, / answers 404",
        f"{len(lines)} line(s), / {st3}",
        st3 == 404
        and len(lines) == 1
        and "web ui not built; serving the API only" in lines[0],
    )

    # ------------------------------------------------------ Signing in
    admin, pw = f"m5-adm-{secrets.token_hex(3)}", "m5 walk pass " + secrets.token_hex(6)
    w.secrets.append(pw)
    dsn = next(tmp_path.glob("run-*/creds/app_dsn"))
    made = run_users(["create-admin", admin], dsn, stdin=pw + "\n")
    w.check(
        "users create-admin",
        "users create-admin",
        "exit 0",
        f"exit {made.returncode}",
        made.returncode == 0,
    )
    login = V1 + "/auth/login"
    _, _, out = w.expect(
        "admin without TOTP signs in",
        "POST",
        login,
        200,
        body={"username": admin, "password": pw, "totp_code": None},
    )
    s0 = json.loads(out)["token"]
    w.secrets.append(s0)
    w.expect(
        "admin without TOTP: only the TOTP page (hosts refused)",
        "GET",
        V1 + "/agents",
        403,
        "totp_enrolment_required",
        token=s0,
    )
    _, _, out = w.expect(
        "Start", "POST", V1 + "/auth/totp/enrol", 200, token=s0, body={}
    )
    start = json.loads(out)
    secret = start["secret"]
    w.secrets.append(secret)
    w.check(
        "Start shows a secret and an otpauth URI",
        "POST /auth/totp/enrol {}",
        "secret, otpauth_uri",
        ",".join(sorted(start)),
        sorted(start) == ["otpauth_uri", "secret"]
        and start["otpauth_uri"].startswith("otpauth://"),
    )
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    bad = (
        "000000" if code_at(seed, step_at(datetime.now(UTC))) != "000000" else "111111"
    )
    w.expect(
        "a wrong code: Start again",
        "POST",
        V1 + "/auth/totp/enrol",
        403,
        token=s0,
        body={"totp_code": bad},
    )
    w.expect(
        "the old secret is gone after a wrong code",
        "POST",
        V1 + "/auth/totp/enrol",
        409,
        token=s0,
        body={"totp_code": totp.code(seed)},
    )
    _, _, out = w.expect(
        "Start again", "POST", V1 + "/auth/totp/enrol", 200, token=s0, body={}
    )
    secret = json.loads(out)["secret"]
    w.secrets.append(secret)
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    _, _, out = w.expect(
        "Confirm",
        "POST",
        V1 + "/auth/totp/enrol",
        200,
        token=s0,
        body={"totp_code": totp.code(seed)},
    )
    S = json.loads(out)["token"]
    w.secrets.append(S)
    w.check(
        "Confirm gives a TOTP-verified session",
        "confirm answer",
        "totp_verified true",
        str(json.loads(out)["totp_verified"]),
        json.loads(out)["totp_verified"] is True,
    )
    st, _, _ = w.req("GET", V1 + "/agents", token=S)
    w.check(
        "the app opens after enrolment",
        "GET /agents (new session)",
        "200",
        str(st),
        st == 200,
    )
    for wrong in (
        {"username": admin, "password": pw + "x", "totp_code": totp.code(seed)},
        {"username": admin + "x", "password": pw, "totp_code": None},
    ):
        _, _, out = w.req("POST", login, body=wrong)
        w.check(
            "a failed sign-in is always the same",
            "POST /auth/login (wrong)",
            "401 unauthorized",
            out.decode()[:80],
            json.loads(out).get("type") == "unauthorized",
        )

    viewer, vpw = (
        f"m5-vw-{secrets.token_hex(3)}",
        "m5 viewer pass " + secrets.token_hex(6),
    )
    w.secrets.append(vpw)
    w.expect(
        "create a viewer",
        "POST",
        V1 + "/users",
        201,
        token=S,
        body={"username": viewer, "password": vpw},
    )
    _, _, out = w.expect(
        "viewer without TOTP signs in",
        "POST",
        login,
        200,
        body={"username": viewer, "password": vpw, "totp_code": None},
    )
    VS = json.loads(out)["token"]
    w.secrets.append(VS)
    w.check(
        "the viewer is offered TOTP and may skip it",
        "sign-in answer",
        "totp_enrolled false; the API works without TOTP",
        f"totp_enrolled={json.loads(out)['totp_enrolled']}",
        json.loads(out)["totp_enrolled"] is False
        and w.req("GET", V1 + "/agents", token=VS)[0] == 200,
    )

    # ------------------------------------------------------ Pages by role
    for path in ("/enrollment-requests", "/enrollment-tokens"):
        w.expect("Enrolment pages: no for a viewer", "GET", V1 + path, 403, token=VS)
        w.expect("Enrolment pages: yes for an admin", "GET", V1 + path, 200, token=S)
    for path in ("/agents", "/packages/search?name=x", "/packages/search.csv?name=x"):
        w.expect(
            "Hosts and Package search: yes for a viewer",
            "GET",
            V1 + path,
            200,
            token=VS,
        )
    _, _, out = w.expect(
        "admin API token",
        "POST",
        V1 + "/api-tokens",
        201,
        token=S,
        body={"name": "m5-walk"},
    )
    K = json.loads(out)["token"]
    w.secrets.append(K)
    w.expect(
        "an enrolment action without a TOTP-verified session: Sign in again",
        "POST",
        V1 + "/enrollment-tokens",
        403,
        "totp_session_required",
        token=K,
        body={},
    )

    # ------------------------------------------------------ Enrolment tokens
    _, _, out = w.expect(
        "the form's defaults",
        "POST",
        V1 + "/enrollment-tokens",
        201,
        token=S,
        body={
            "max_uses": 1,
            "expires_in_hours": 24,
            "allowed_cidrs": None,
            "auto_approve": False,
        },
    )
    t = json.loads(out)
    E = t["token"]
    w.secrets.append(E)
    w.check(
        "defaults: single-use, 24 h, any address, no auto-approve",
        "create answer",
        "max_uses 1, allowed_cidrs null, auto_approve false, bse_ token",
        f"{t['max_uses']} {t['allowed_cidrs']} {t['auto_approve']} {E[:4]}",
        t["max_uses"] == 1
        and t["allowed_cidrs"] is None
        and t["auto_approve"] is False
        and E.startswith("bse_"),
    )
    _, _, out = w.expect("the list", "GET", V1 + "/enrollment-tokens", 200, token=S)
    w.check(
        "the token cannot be shown again",
        "GET /enrollment-tokens",
        "no bse_ value",
        "absent" if E not in out.decode() else "present",
        E not in out.decode(),
    )
    _, _, out = w.expect(
        "a token to revoke", "POST", V1 + "/enrollment-tokens", 201, token=S, body={}
    )
    rid = json.loads(out)["token_id"]
    w.secrets.append(json.loads(out)["token"])
    w.expect(
        "revoke from the list", "DELETE", f"{V1}/enrollment-tokens/{rid}", 204, token=S
    )

    # ------------------------------------------------------ Enrolment requests
    base = json.loads(
        (FIX / "enrol" / "request_valid_full.json").read_text(encoding="utf-8")
    )
    mid = secrets.token_hex(16)
    host_name = "m5-walk-" + secrets.token_hex(3)
    _, _, out = w.expect(
        "an agent enrols (held)",
        "POST",
        V1 + "/agent/enroll",
        200,
        token=E,
        body=base | {"hostname": host_name, "machine_id": mid},
    )
    A, TA = json.loads(out)["agent_id"], json.loads(out)["agent_token"]
    w.secrets.append(TA)
    _, _, out = w.expect(
        "Show: pending", "GET", V1 + "/enrollment-requests?state=pending", 200, token=S
    )
    req = [i for i in json.loads(out)["items"] if i["agent_id"] == A]
    w.check(
        "each request shows host, address, OS, version, machine-id",
        "pending item",
        "hostname, source_ip, os_pretty_name, agent_version, machine_id",
        ",".join(sorted(req[0])) if req else "missing",
        bool(req)
        and {
            "hostname",
            "source_ip",
            "os_pretty_name",
            "agent_version",
            "machine_id",
            "matches",
        }
        <= set(req[0]),
    )
    request_id = req[0]["request_id"] if req else 0
    w.expect(
        "Approve",
        "POST",
        f"{V1}/enrollment-requests/{request_id}/approve",
        200,
        token=S,
    )
    w.expect(
        "already decided",
        "POST",
        f"{V1}/enrollment-requests/{request_id}/reject",
        409,
        token=S,
    )
    _, _, out = w.expect(
        "Show: decided", "GET", V1 + "/enrollment-requests?state=decided", 200, token=S
    )
    w.check(
        "the request is now decided",
        "decided list",
        "approved",
        str([i["decision"] for i in json.loads(out)["items"] if i["agent_id"] == A]),
        [i["decision"] for i in json.loads(out)["items"] if i["agent_id"] == A]
        == ["approved"],
    )

    # inventory for the host and package pages
    ah = {"X-Bitscan-Machine-Id": mid}
    _, _, out = w.expect(
        "job pull", "GET", f"{V1}/agent/{A}/jobs", 200, token=TA, headers=ah
    )
    job = json.loads(out)["jobs"][0]["job_id"]
    pkgs = [
        ("openssl", "3.0.13-0ubuntu3.5", "amd64", "install ok installed", "openssl", 1),
        ("openssl", "3.0.13-0ubuntu3.5", "i386", "hold ok installed", "openssl", 1),
        ("libssl3", "3.0.13-0ubuntu3.5", "amd64", "deinstall ok installed", "", 2),
        ("oldpkg", "1.0", "all", "deinstall ok config-files", "", None),
        (FORMULA, "1.0", "all", "install ok installed", "", 3),
    ]
    inv = {
        "os_info": os_info(),
        "packages": [
            {
                "name": n,
                "version": v,
                "architecture": a,
                "status": st_,
                "source": src,
                "installed_size_kb": kb,
            }
            for n, v, a, st_, src, kb in pkgs
        ],
        "list_sha256": oracle_sha256(pkgs),
    }
    w.expect(
        "inventory upload",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={job}",
        204,
        token=TA,
        raw=gzip.compress(json.dumps(inv).encode()),
        headers=ah | {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )

    # ------------------------------------------------------ Hosts
    _, _, out = w.expect("Hosts", "GET", V1 + "/agents?limit=50", 200, token=VS)
    item: dict[str, Any] = next(
        (i for i in json.loads(out)["items"] if i["agent_id"] == A), {}
    )
    w.check(
        "Hosts shows status, OS, version, heartbeat, inventory, tags, helpers",
        "agent item",
        "status, os_pretty_name, agent_version, last_heartbeat_at, last_inventory_at,"
        " tags, runner_helpers",
        ",".join(sorted(item)),
        {
            "status",
            "os_pretty_name",
            "agent_version",
            "last_heartbeat_at",
            "last_inventory_at",
            "tags",
            "runner_helpers",
        }
        <= set(item),
    )
    _, _, out = w.expect("the host page", "GET", f"{V1}/agents/{A}", 200, token=VS)
    d = json.loads(out)
    w.check(
        "host page: token times, never the token; os_info; last snapshot",
        "agent detail",
        "token_issued_at, token_expires_at, os_info.raw, last_snapshot; no token",
        ",".join(sorted(d)),
        {"token_issued_at", "token_expires_at", "token_revoked_at"} <= set(d)
        and d["os_info"] is not None
        and "raw" in d["os_info"]
        and d["last_snapshot"] is not None
        and TA not in out.decode()
        and "token_hash" not in d,
    )
    _, _, out = w.expect(
        "the full package list",
        "GET",
        f"{V1}/agents/{A}/packages?limit=50",
        200,
        token=VS,
    )
    w.check(
        "package list holds every package",
        "host packages",
        str(len(pkgs)),
        str(len(json.loads(out)["items"])),
        len(json.loads(out)["items"]) == len(pkgs),
    )

    # ------------------------------------------------------ Package search
    ps = section("Package search")
    srch = V1 + "/packages/search"

    def search(**params: str) -> tuple[int, dict[str, str], Any]:
        st, h, out = w.req("GET", srch + "?" + urlencode(params), token=VS)
        return st, h, (json.loads(out) if out else None)

    st, _, b = search(agent_id=A)
    w.check(
        "status installed (default) covers the three installed states",
        "?agent_id=<A>",
        "openssl x2, libssl3, the formula name; not oldpkg",
        str(sorted(i["name"] for i in b["items"])),
        st == 200
        and sorted(i["name"] for i in b["items"])
        == sorted([FORMULA, "libssl3", "openssl", "openssl"]),
    )
    st, _, b = search(agent_id=A, status="any")
    w.check(
        "status any adds removed packages with configuration files",
        "?status=any",
        "5 rows incl. oldpkg",
        str(len(b["items"])),
        st == 200
        and len(b["items"]) == 5
        and "oldpkg" in {i["name"] for i in b["items"]},
    )
    st, _, b = search(agent_id=A, q="SSL")
    w.check(
        "q: name contains (any letter case)",
        "?q=SSL",
        "openssl, libssl3",
        str(sorted({i["name"] for i in b["items"]})),
        st == 200 and {"openssl", "libssl3"} <= {i["name"] for i in b["items"]},
    )
    st, _, b = search(agent_id=A, host=host_name.upper())
    w.check(
        "host: hostname contains (any letter case)",
        "?host=<HOST>",
        "4 rows",
        str(len(b["items"])),
        st == 200 and len(b["items"]) == 4,
    )
    st, _, b = search(agent_id=A, host="%")
    w.check(
        "% in host matches literally",
        "?host=%",
        "no rows",
        str(len(b["items"])),
        st == 200 and b["items"] == [],
    )
    st, _, b = search(agent_id=A, version="3.0.13", version_op="lt", name="openssl")
    w.check(
        "version_op compares in Debian order",
        "?name=openssl&version=3.0.13&version_op=lt",
        "no rows (3.0.13-0ubuntu3.5 > 3.0.13)",
        str(len(b["items"])),
        st == 200 and b["items"] == [],
    )
    st, _, b = search(agent_id=A, version="3.0.14", version_op="lt", name="openssl")
    w.check(
        "version_op lt 3.0.14",
        "?version=3.0.14&version_op=lt",
        "2 rows",
        str(len(b["items"])),
        st == 200 and len(b["items"]) == 2,
    )
    st, _, b = search(agent_id=A, version="3.0.13-0ubuntu3.5", arch="i386")
    w.check(
        "version alone matches exact text; arch exact",
        "?version=…&arch=i386",
        "1 row",
        str(len(b["items"])),
        st == 200 and len(b["items"]) == 1,
    )
    st, _, b = search(agent_id=A, os="ubuntu")
    st2, _, b2 = search(agent_id=A, os="ubuntu:24.04")
    st3, _, b3 = search(agent_id=A, os="ubuntu:22.04")
    w.check(
        "os with and without a version",
        "?os=ubuntu / ubuntu:24.04 / ubuntu:22.04",
        "4, 4, 0 rows",
        f"{len(b['items'])}, {len(b2['items'])}, {len(b3['items'])}",
        len(b["items"]) == len(b2["items"]) == 4 and b3["items"] == [],
    )
    st, _, b = search(agent_id=A, group_by="package")
    w.check(
        "group_by=package items",
        "?group_by=package",
        "{name, version, architecture, host_count}",
        str(sorted(b["items"][0])) if b["items"] else "none",
        st == 200
        and b["items"]
        and sorted(b["items"][0]) == ["architecture", "host_count", "name", "version"],
    )
    st, _, b = search(agent_id=A, group_by="host")
    w.check(
        "group_by=host items",
        "?group_by=host",
        "{agent_id, hostname, package_count}",
        str(b["items"]),
        st == 200
        and b["items"] == [{"agent_id": A, "hostname": host_name, "package_count": 4}],
    )
    st, _, b = search(agent_id=A)
    w.check(
        "row items and order (name, Debian version, architecture, hostname)",
        "?agent_id=<A>",
        "6 keys; sorted by name then arch",
        str([(i["name"], i["architecture"]) for i in b["items"]]),
        all(
            list(i)
            == ["name", "version", "architecture", "status", "agent_id", "hostname"]
            for i in b["items"]
        )
        and [(i["name"], i["architecture"]) for i in b["items"]]
        == sorted((i["name"], i["architecture"]) for i in b["items"]),
    )
    st, _, b = search(agent_id=A, limit="1")
    cur = b["next_cursor"]
    st2, _, b2 = search(agent_id=A, limit="1", cursor=cur)
    st3, _, b3 = search(agent_id=A, limit="1", cursor=cur, status="any")
    w.check(
        "a cursor works only with the same filters",
        "?cursor=… (+status=any)",
        "200, then 400 Invalid request: query.cursor",
        f"{st2}, {st3} {b3.get('detail') if b3 else ''}",
        st2 == 200 and st3 == 400 and b3["detail"] == "Invalid request: query.cursor",
    )
    refusals = [
        ({"q": "ab"}, "q"),
        ({"q": "abc", "name": "x"}, "name"),
        ({"version_op": "lt"}, "version"),
        ({"version_op": "ne", "version": "1"}, "version_op"),
        ({"status": "removed"}, "status"),
        ({"group_by": "name"}, "group_by"),
        ({"version": "1.0 beta"}, "version"),
        ({"agent_id": "not-a-uuid"}, "agent_id"),
        ({"name": ""}, "name"),
        ({"tag": "x" * 65}, "tag"),
    ]
    for params, named in refusals:
        st, _, b = search(**params)
        value = next(iter(params.values()))
        w.check(
            "400 names the parameter, never the value",
            "?" + urlencode(params),
            f"400 invalid_request query.{named}",
            f"{st} {b.get('type') if b else ''} {b.get('detail') if b else ''}",
            st == 400
            and b["type"] == "invalid_request"
            and f"query.{named}" in b["detail"]
            and (len(value) < 3 or value not in b["detail"]),
        )
    # the README curl example, as written
    m = re2.search(
        r"(?s)curl -s -G https://manager\.example:8443(\S+) \\\n(.*?)\n```", ps
    )
    w.check(
        "the curl example is in the README",
        "Package search",
        "present",
        "present" if m else "missing",
        m is not None,
    )
    if m:
        args = dict(re2.findall(r"--data-urlencode (\w+)=(\S+)", m.group(2)))
        st, _, b = w.req("GET", m.group(1) + "?" + urlencode(args), token=VS)
        items = json.loads(b)["items"] if st == 200 else []
        w.check(
            "the curl example answers",
            "GET " + m.group(1) + "?" + urlencode(args),
            "200 package groups of openssl < 3.0.13",
            f"{st} {len(items)} items",
            st == 200
            and all(i["name"] == "openssl" and "host_count" in i for i in items),
        )

    # ------------------------------------------------------ CSV export
    csvp = V1 + "/packages/search.csv"
    st, h, out = w.req(
        "GET",
        csvp + "?" + urlencode({"agent_id": A, "limit": "1", "cursor": "x"}),
        token=VS,
    )
    text = out.decode("utf-8")
    recs = list(csv.reader(io.StringIO(text, newline="")))
    w.check(
        "CSV: same parameters, limit and cursor ignored, whole result",
        "GET search.csv?agent_id=<A>&limit=1&cursor=x",
        "200, header + 4 rows",
        f"{st} {len(recs)} records",
        st == 200 and len(recs) == 5,
    )
    w.check(
        "CSV headers",
        "search.csv",
        'text/csv; charset=utf-8; attachment; filename="packages.csv"',
        f"{h.get('content-type')}; {h.get('content-disposition')}",
        h.get("content-type") == "text/csv; charset=utf-8"
        and h.get("content-disposition") == 'attachment; filename="packages.csv"',
    )
    w.check(
        "CSV: UTF-8 without BOM, CRLF, header = item keys",
        "search.csv",
        "name,version,architecture,status,agent_id,hostname\\r\\n",
        repr(text[:60]),
        not out.startswith(b"\xef\xbb\xbf")
        and text.startswith("name,version,architecture,status,agent_id,hostname\r\n")
        and "\n" not in text.replace("\r\n", ""),
    )
    w.check(
        "formula escaping: the README's example",
        "search.csv",
        '"\'=HYPERLINK(""http://x"")"',
        "present" if '"\'=HYPERLINK(""http://x"")"' in text else "missing",
        '"\'=HYPERLINK(""http://x"")"' in text and '"\'=HYPERLINK(""http://x"")"' in ps,
    )
    st, _, out = w.req("GET", csvp + "?q=ab", token=VS)
    w.check(
        "CSV refusals as the search",
        "search.csv?q=ab",
        "400 query.q",
        f"{st} {json.loads(out).get('detail')}",
        st == 400 and json.loads(out)["detail"] == "Invalid request: query.q",
    )
    cap_detail = "Invalid request: more than 100000 rows; narrow the filters"
    w.check(
        "the cap's 400 detail is the one the README quotes",
        "README CSV export",
        cap_detail,
        "quoted" if cap_detail in ps else "missing",
        cap_detail in ps,
    )

    # ------------------------------------------------------ Enrolling agents (M5 lines)
    en = section("Enrolling agents")
    w.check(
        "Enrolling agents names the UI pages first",
        "README",
        "Enrolment tokens page, Enrolment requests page",
        "present"
        if "**Enrolment tokens** page" in en and "**Enrolment requests** page" in en
        else "missing",
        "**Enrolment tokens** page" in en and "**Enrolment requests** page" in en,
    )

    # ------------------------------------------------------ Sign-out, password
    w.expect("sign out", "POST", V1 + "/auth/logout", 204, token=VS)
    w.expect("signed out: 401", "GET", V1 + "/agents", 401, token=VS)
    new_pw = "m5 new pass " + secrets.token_hex(6)
    w.secrets.append(new_pw)
    _, _, out = w.expect(
        "viewer signs in again",
        "POST",
        login,
        200,
        body={"username": viewer, "password": vpw, "totp_code": None},
    )
    VS2 = json.loads(out)["token"]
    w.secrets.append(VS2)
    w.expect(
        "Password (12 characters or more)",
        "POST",
        V1 + "/auth/password",
        204,
        token=VS2,
        body={"current_password": vpw, "new_password": new_pw},
    )
    w.expect("every session of the user ends", "GET", V1 + "/agents", 401, token=VS2)
    w.expect(
        "sign in again with the new password",
        "POST",
        login,
        200,
        body={"username": viewer, "password": new_pw, "totp_code": None},
    )

    # ------------------------------------------------------ README hygiene
    text = readme()
    w.check(
        "no task id, REQ id or process note",
        "README.md",
        "no TASK-, REQ-, PD- or #8x",
        "clean"
        if not re2.search(r"TASK-\d|REQ-\d|PD-\d|#8\d\b|tester|lead ruling", text)
        else "found",
        not re2.search(r"TASK-\d|REQ-\d|PD-\d|#8\d\b|tester|lead ruling", text),
    )
    w.check(
        "no real token in the README",
        "README.md",
        "no bs?_ token value",
        "clean" if not re2.search(r"bs[uake]_[A-Za-z0-9_-]{20,}", text) else "found",
        not re2.search(r"bs[uake]_[A-Za-z0-9_-]{20,}", text),
    )

    # ------------------------------------------------------ Stopping, logs
    code = s.stop()
    w.check("SIGTERM", "serve", "exit 0", f"exit {code}", code == 0)
    log = s.output()
    leaked = [x for x in w.secrets if x in log]
    w.check(
        "logs hold no token, password or secret",
        "serve log",
        "none",
        f"{len(leaked)} leaked",
        not leaked and FORMULA not in log,
    )

    out_path = os.environ.get("WALK_OUT")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for r in w.rows:
                f.write(json.dumps(r.__dict__) + "\n")
    deviations = [r for r in w.rows if not r.ok]
    assert not deviations, "\n".join(
        f"{r.label}: {r.request}: expected {r.expected}, got {r.actual}"
        for r in deviations
    )
    assert len(w.rows) > 80
