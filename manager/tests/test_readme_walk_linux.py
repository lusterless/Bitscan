"""TASK-080 TEST addition (REQ-090 (1), lead ruling 2026-10-23): a live walk
through every request the README documents, against a real `serve` (HTTPS,
real PostgreSQL, fake OpenBao and audit sink, real clock).

Expected answers come from README.md ("API", "Enrolling agents", "Agent API",
"Scheduler", "Starting the app"), not from the code. Every request and its
actual answer is recorded as one row; a row whose answer differs from the
README is collected as a deviation, so one run lists every difference, and the
test fails if there is any. With WALK_OUT set, the rows are written there as
JSON lines (evidence for tests/m3/report.md).

Test-only statements as owner (`as owner`) are used only where the README
describes a time-based rule that a real clock cannot reach in a test: moving
a token into its rotation window, ending a rotation overlap, expiring a token,
and planting hosts for the scheduler checks.
"""

import base64
import gzip
import hashlib
import http.client
import json
import os
import secrets
import socket
import ssl
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest

from bitscan_manager.auth.totp import code_at, step_at

from .certs import make_pki
from .conftest import PgServer
from .contract import loader
from .fake_sink import https_sink, server_context
from .fake_vault import fake_vault
from .test_cli_users_pg import run as run_users
from .test_serve_linux import (
    CANARY_VAULT,
    client_context,
    env_for,
    free_port,
    https_get,
    start,
    wait_ready,
)

pytestmark = pytest.mark.pg

FIX = loader.FIXTURES
V1 = "/api/v1"


@dataclass
class Row:
    label: str
    method: str
    path: str
    auth: str
    expected: str
    status: int
    answer: str
    ok: bool


EARLY_WAIT = 10.0  # seconds a cap check on the header gets to answer


def send_oversize(
    port: int,
    ca: Path,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> tuple[int, dict[str, str], bytes, str]:
    """Sends a request whose body is over a cap, without racing the answer.

    The manager answers 413 from the Content-Length header and closes without
    reading the body, which is valid HTTP. Sending header and body in one go
    (https_get) races that close: the client gets the 413 or an EOF or reset
    in sendall, depending on socket timing (ssl.SSLEOFError under WSL
    mirrored networking, 2026-10-25). So the header goes first, announcing
    the full length, and the answer is read if it comes within EARLY_WAIT.
    If none comes, the body is sent and the answer read after it: a manager
    that only counts the bytes it receives is still held to its 413, and one
    with no cap answers something else and the row fails. A send error is
    tolerated only there, and only when a response can still be read after
    it; it never passes a row by itself.
    """
    lines = [f"{method} {path} HTTP/1.1", f"Host: localhost:{port}"]
    lines += ["Accept-Encoding: identity"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    lines += [f"Content-Length: {len(body)}", "", ""]
    with (
        socket.create_connection(("localhost", port), timeout=10) as raw,
        client_context(ca).wrap_socket(raw, server_hostname="localhost") as tls,
    ):
        tls.sendall("\r\n".join(lines).encode())
        tls.settimeout(EARLY_WAIT)
        resp = http.client.HTTPResponse(tls, method=method)
        try:
            resp.begin()
            how = "answered on the header, body not sent"
        except TimeoutError:
            resp.close()
            tls.settimeout(10)
            how = "answered after the body"
            try:
                tls.sendall(body)
            except (
                BrokenPipeError,
                ConnectionResetError,
                ssl.SSLEOFError,
                ssl.SSLZeroReturnError,
            ):
                how = "answered while the body was being sent"
            resp = http.client.HTTPResponse(tls, method=method)
            resp.begin()
        out = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        resp.close()
        return resp.status, hdrs, out, how


@dataclass
class Walk:
    port: int
    ca: Path
    rows: list[Row] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # value -> placeholder

    def name(self, value: str, placeholder: str) -> str:
        self.names[value] = placeholder
        return value

    def hide(self, text: str) -> str:
        for value, ph in self.names.items():
            text = text.replace(value, ph)
        return text

    def call(
        self,
        label: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: Any = None,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
        want: int,
        want_type: str | None = None,
        oversize: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        h = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        how = ""
        if oversize:
            assert data is not None
            status, hdrs, out, how = send_oversize(
                self.port, self.ca, method, path, h, data
            )
        else:
            status, hdrs, out = https_get(self.port, self.ca, path, h, data, method)
        got_type = None
        answer = ""
        if hdrs.get("content-type", "").startswith("application/problem+json"):
            got_type = json.loads(out).get("type")
            answer = f"type={got_type}"
        elif hdrs.get("content-type", "").startswith("application/json") and out:
            parsed = json.loads(out)
            answer = (
                "keys=" + ",".join(parsed)
                if isinstance(parsed, dict)
                else f"{type(parsed).__name__}"
            )
        if "retry-after" in hdrs:
            answer += f" Retry-After={hdrs['retry-after']}"
        if how:
            answer += f" ({how})"
        ok = status == want and (want_type is None or got_type == want_type)
        auth = "none" if token is None else self.hide(token)[:24]
        expected = f"{want}" + (f" {want_type}" if want_type else "")
        self.rows.append(
            Row(label, method, self.hide(path), auth, expected, status, answer, ok)
        )
        return status, hdrs, out

    def note(self, label: str, expected: str, actual: str, ok: bool) -> None:
        self.rows.append(Row(label, "-", "-", "-", expected, 0, actual, ok))


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


def owner(server: PgServer, sql: str, params: tuple[Any, ...]) -> list[Any]:
    with server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cur = c.execute(sql, params)  # fixed test statements only
        return cur.fetchall() if cur.description else []


def plant(server: PgServer, status: str, heartbeat: datetime | None) -> UUID:
    from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash

    now = datetime.now(UTC)
    rows = owner(
        server,
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status, enrolled_at,"
        " last_heartbeat_at) VALUES (%s, %s, '1.0.0', %s, %s, %s, %s, %s, %s)"
        " RETURNING agent_id",
        (
            secrets.token_hex(16),
            f"walk-plant-{secrets.token_hex(3)}",
            token_hash(new_agent_token(AgentTokenKind.AGENT)),
            now - timedelta(days=1),
            now + timedelta(days=300),
            status,
            now - timedelta(days=1),
            heartbeat,
        ),
    )
    return UUID(str(rows[0][0]))


def gz(obj: Any) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def row_hash(item: dict[str, Any]) -> str:
    """README "Audit log": SHA-256 of the compact UTF-8 JSON array."""
    arr = [
        item["prev_hash"],
        item["audit_id"],
        item["actor"],
        item["action"],
        item["target"],
        item["detail_text"],
        item["at"],
    ]
    text = json.dumps(arr, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def listed(w: Walk, label: str, path: str, token: str, agent: str) -> list[Any]:
    """The items of a paged list whose agent_id is agent. The first request
    is exactly the documented one; later pages follow next_cursor, because
    the shared test database holds other tests' rows (gate fix, 2026-10-23)."""
    sep = "&" if "?" in path else "?"
    q = path
    while True:
        st, _, out = w.call(label, "GET", q, token=token, want=200)
        if st != 200:
            return []
        page = json.loads(out)
        found = [i for i in page["items"] if i["agent_id"] == agent]
        if found or not page.get("next_cursor"):
            return found
        q = f"{path}{sep}cursor={quote(page['next_cursor'], safe='')}"


@pytest.fixture
def walk(migrated_db: PgServer, tmp_path: Path) -> Iterator[tuple[Walk, Any, Any]]:
    pki = make_pki(tmp_path / "pki")
    sink_leaf, vault_leaf, serve_leaf = (pki.leaf(n) for n in ("sink", "vault", "srv"))
    with (
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as v,
    ):
        port = free_port()
        env = env_for(
            migrated_db,
            tmp_path,
            pki,
            serve_leaf,
            f"https://localhost:{sink.port}/audit",
            port,
            BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{v.port}",
        )
        planted_enrolled = plant(migrated_db, "enrolled", None)
        s = start(env, tmp_path, port, pki, serve_leaf)
        try:
            wait_ready(s)
            yield Walk(port, s.ca), s, planted_enrolled
        finally:
            if s.proc.poll() is None:
                s.stop()


def test_every_documented_request_behaves_as_the_readme_says(  # noqa: PLR0915
    walk: tuple[Walk, Any, UUID], migrated_db: PgServer, tmp_path: Path
) -> None:
    w, serve, planted_enrolled = walk
    server = migrated_db
    totp = Totp()

    def now() -> datetime:
        return datetime.now(UTC)

    # ---------------------------------------------------- Starting the app
    _, _, out = w.call("healthz", "GET", "/healthz", want=200)
    w.note(
        "healthz body",
        '{"status": "ok"}',
        out.decode(),
        json.loads(out) == {"status": "ok"},
    )
    _, _, out = w.call("readyz", "GET", "/readyz", want=200)
    w.note(
        "readyz body",
        '{"status": "ok"}',
        out.decode(),
        json.loads(out) == {"status": "ok"},
    )

    # ---------------------------------------------------- Users (CLI) and sign-in
    admin, pw = f"walk-adm-{secrets.token_hex(3)}", "walk pass " + secrets.token_hex(8)
    made = run_users(
        ["create-admin", admin], tmp_path / "creds" / "app_dsn", stdin=pw + "\n"
    )
    w.note(
        "users create-admin", "exit 0", f"exit {made.returncode}", made.returncode == 0
    )
    login = f"{V1}/auth/login"
    _, _, out = w.call(
        "sign-in, admin without TOTP",
        "POST",
        login,
        body={"username": admin, "password": pw},
        want=200,
    )
    s0 = w.name(json.loads(out)["token"], "<restricted session>")
    w.note(
        "restricted session",
        "totp_verified false",
        str(json.loads(out)["totp_verified"]),
        json.loads(out)["totp_verified"] is False,
    )
    w.call(
        "restricted session cannot list users", "GET", f"{V1}/users", token=s0, want=403
    )
    _, _, out = w.call(
        "TOTP enrol start", "POST", f"{V1}/auth/totp/enrol", token=s0, body={}, want=200
    )
    secret = json.loads(out)["secret"]
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    w.call(
        "TOTP enrol confirm",
        "POST",
        f"{V1}/auth/totp/enrol",
        token=s0,
        body={"totp_code": totp.code(seed)},
        want=200,
    )
    # README "Enrolling agents" step 1
    _, _, out = w.call(
        "1. sign in (admin with TOTP)",
        "POST",
        login,
        body={"username": admin, "password": pw, "totp_code": totp.code(seed)},
        want=200,
    )
    body = json.loads(out)
    S = w.name(body["token"], "<admin session>")
    w.note(
        "sign-in answer",
        "token, expires_at, role, totp_enrolled, totp_verified",
        ",".join(sorted(body)),
        sorted(body)
        == sorted(["token", "expires_at", "role", "totp_enrolled", "totp_verified"])
        and body["totp_verified"] is True,
    )
    _, _, out = w.call(
        "admin API token",
        "POST",
        f"{V1}/api-tokens",
        token=S,
        body={"name": "walk"},
        want=201,
    )
    K = w.name(json.loads(out)["token"], "<admin bsk_>")
    oper, vpw = f"walk-op-{secrets.token_hex(3)}", "walk pass " + secrets.token_hex(8)
    viewer = f"walk-vw-{secrets.token_hex(3)}"
    w.call(
        "create operator",
        "POST",
        f"{V1}/users",
        token=S,
        body={"username": oper, "password": vpw, "role": "operator"},
        want=201,
    )
    _, _, out = w.call(
        "create viewer (default role)",
        "POST",
        f"{V1}/users",
        token=S,
        body={"username": viewer, "password": vpw},
        want=201,
    )
    w.note(
        "default role",
        "viewer",
        json.loads(out)["role"],
        json.loads(out)["role"] == "viewer",
    )
    _, _, out = w.call(
        "operator sign-in",
        "POST",
        login,
        body={"username": oper, "password": vpw},
        want=200,
    )
    OP = w.name(json.loads(out)["token"], "<operator session>")
    _, _, out = w.call(
        "viewer sign-in",
        "POST",
        login,
        body={"username": viewer, "password": vpw},
        want=200,
    )
    VS = w.name(json.loads(out)["token"], "<viewer session>")
    _, _, out = w.call(
        "viewer API token (for Prometheus)",
        "POST",
        f"{V1}/api-tokens",
        token=VS,
        body={"name": "prom"},
        want=201,
    )
    VK = w.name(json.loads(out)["token"], "<viewer bsk_>")

    # ---------------------------------------------------- Enrolment tokens
    et = f"{V1}/enrollment-tokens"
    _, _, out = w.call(
        "2. create enrolment token (README body)",
        "POST",
        et,
        token=S,
        body={
            "max_uses": 25,
            "expires_in_hours": 48,
            "allowed_cidrs": ["10.20.0.0/16"],
            "auto_approve": False,
        },
        want=201,
    )
    t1 = json.loads(out)
    E1 = w.name(t1["token"], "<bse_ 10.20/16>")
    want_keys = sorted(
        [
            "token",
            "token_id",
            "max_uses",
            "uses",
            "auto_approve",
            "allowed_cidrs",
            "expires_at",
            "created_at",
        ]
    )
    w.note(
        "create answer keys",
        ",".join(want_keys),
        ",".join(sorted(t1)),
        sorted(t1) == want_keys,
    )
    w.call(
        "create enrolment token with an admin API token",
        "POST",
        et,
        token=K,
        body={},
        want=403,
    )
    _, _, out = w.call(
        "create token, defaults ({})", "POST", et, token=S, body={}, want=201
    )
    d = json.loads(out)
    exp = datetime.fromisoformat(
        d["expires_at"].replace("Z", "+00:00")
    ) - datetime.fromisoformat(d["created_at"].replace("Z", "+00:00"))
    w.note(
        "defaults",
        "max_uses 1, 24 h, allowed_cidrs null, auto_approve false",
        f"{d['max_uses']}, {exp}, {d['allowed_cidrs']}, {d['auto_approve']}",
        d["max_uses"] == 1
        and exp == timedelta(hours=24)
        and d["allowed_cidrs"] is None
        and d["auto_approve"] is False,
    )
    w.call(
        "max_uses 10,001 refused",
        "POST",
        et,
        token=S,
        body={"max_uses": 10001},
        want=400,
    )
    w.call(
        "expires_in_hours 721 refused",
        "POST",
        et,
        token=S,
        body={"expires_in_hours": 721},
        want=400,
    )
    _, _, out = w.call(
        "held-enrolment token (localhost CIDRs)",
        "POST",
        et,
        token=S,
        body={"max_uses": 3, "allowed_cidrs": ["127.0.0.0/8", "::1/128"]},
        want=201,
    )
    E2 = w.name(json.loads(out)["token"], "<bse_ held>")
    _, _, out = w.call(
        "auto-approve token (risky)",
        "POST",
        et,
        token=S,
        body={"max_uses": 10, "auto_approve": True},
        want=201,
    )
    E3 = w.name(json.loads(out)["token"], "<bse_ auto>")
    _, _, out = w.call("list enrolment tokens", "GET", et, token=S, want=200)
    w.note(
        "list holds no token",
        "no bse_ value, no token_hash",
        "checked",
        all(t not in out.decode() for t in (E1, E2, E3)) and b"token_hash" not in out,
    )
    w.call("read enrolment token", "GET", f"{et}/{d['token_id']}", token=S, want=200)
    w.call(
        "revoke enrolment token", "DELETE", f"{et}/{d['token_id']}", token=S, want=204
    )
    rows = owner(
        server,
        "SELECT revoked_at IS NOT NULL FROM enrollment_token WHERE token_id = %s",
        (d["token_id"],),
    )
    w.note("revoked record kept", "row with revoked_at", str(rows), rows == [(True,)])

    # ---------------------------------------------------- Enrol and approve
    enroll = f"{V1}/agent/enroll"
    base: dict[str, Any] = json.loads(
        (FIX / "enrol" / "request_valid_full.json").read_text(encoding="utf-8")
    )

    def enrol_body(host: str, mid: str) -> dict[str, Any]:
        return base | {"hostname": host, "machine_id": mid}

    mA, mB, mC, mD = (secrets.token_hex(16) for _ in range(4))
    w.call(
        "enrol outside allowed_cidrs",
        "POST",
        enroll,
        token=E1,
        body=enrol_body("walk-x", secrets.token_hex(16)),
        want=401,
        want_type="unauthorized",
    )
    _, _, out = w.call(
        "enrol, held", "POST", enroll, token=E2, body=enrol_body("walk-a", mA), want=200
    )
    ea = json.loads(out) if out else {}
    w.note(
        "enrol answer",
        "agent_id, agent_token, issued_at, expires_at, status awaiting_approval",
        ",".join(ea) + f" status={ea.get('status')}",
        ea.get("status") == "awaiting_approval"
        and sorted(ea)
        == sorted(["agent_id", "agent_token", "issued_at", "expires_at", "status"]),
    )
    A, TA = w.name(ea["agent_id"], "<A>"), w.name(ea["agent_token"], "<bsa_ A>")
    hb: dict[str, Any] = json.loads(
        (FIX / "heartbeat" / "request_valid_full.json").read_text(encoding="utf-8")
    )

    def beat(agent: str, tok: str, mid: str, **kw: Any) -> dict[str, Any]:
        clock = kw.pop("clock", now())
        return {
            "agent": agent,
            "tok": tok,
            "mid": mid,
            "body": hb
            | {
                "runner_helpers": [],
                "current_job_id": None,
                "clock": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            | kw,
        }

    def heartbeat(
        label: str,
        b: dict[str, Any],
        want: int,
        want_type: str | None = None,
        mid: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        h = {} if mid == "" else {"X-Bitscan-Machine-Id": mid or b["mid"]}
        return w.call(
            label,
            "POST",
            f"{V1}/agent/{b['agent']}/heartbeat",
            token=b["tok"],
            body=b["body"],
            headers=h,
            want=want,
            want_type=want_type,
        )

    heartbeat("held host heartbeat", beat(A, TA, mA), 403, "pending_approval")
    w.call(
        "held host job pull",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers={"X-Bitscan-Machine-Id": mA},
        want=403,
        want_type="pending_approval",
    )
    items = listed(
        w, "list enrolment requests (session)", f"{V1}/enrollment-requests", S, A
    )
    want_req = sorted(
        [
            "request_id",
            "kind",
            "agent_id",
            "hostname",
            "machine_id",
            "os_pretty_name",
            "agent_version",
            "source_ip",
            "requested_at",
            "token_expires_at",
            "decision",
            "decided_by",
            "decided_at",
            "matches",
        ]
    )
    w.note(
        "request item keys",
        ",".join(want_req),
        ",".join(sorted(items[0])) if items else "missing",
        bool(items) and sorted(items[0]) == want_req,
    )
    rid = items[0]["request_id"]
    w.call(
        "list enrolment requests (admin API token)",
        "GET",
        f"{V1}/enrollment-requests?state=all",
        token=K,
        want=200,
    )
    w.call(
        "list enrolment requests (operator)",
        "GET",
        f"{V1}/enrollment-requests",
        token=OP,
        want=403,
    )
    w.call(
        "approve with admin API token",
        "POST",
        f"{V1}/enrollment-requests/{rid}/approve",
        token=K,
        want=403,
    )
    w.call(
        "approve with operator session",
        "POST",
        f"{V1}/enrollment-requests/{rid}/approve",
        token=OP,
        want=403,
    )
    st, _, _ = w.call(
        "approve (admin TOTP session)",
        "POST",
        f"{V1}/enrollment-requests/{rid}/approve",
        token=S,
        want=200,
    )
    w.call(
        "approve again",
        "POST",
        f"{V1}/enrollment-requests/{rid}/approve",
        token=S,
        want=409,
    )

    # ---------------------------------------------------- Heartbeat
    _, _, out = heartbeat("heartbeat (approved)", beat(A, TA, mA), 200)
    w.note(
        "heartbeat answer",
        "exactly job_pull_seconds, max_parallel_plugins, server_time",
        ",".join(json.loads(out)),
        sorted(json.loads(out))
        == ["job_pull_seconds", "max_parallel_plugins", "server_time"],
    )
    st_a = owner(server, "SELECT status FROM agent WHERE agent_id = %s", (A,))
    w.note(
        "heartbeat makes the host online", "online", str(st_a), st_a == [("online",)]
    )
    heartbeat(
        "heartbeat, runner_helpers changed",
        beat(A, TA, mA, runner_helpers=["capread"]),
        200,
    )
    heartbeat(
        "heartbeat, clock 6 min ahead",
        beat(A, TA, mA, runner_helpers=["capread"], clock=now() + timedelta(minutes=6)),
        200,
    )

    # ---------------------------------------------------- Jobs and inventory
    _, _, out = w.call(
        "job pull (first inventory job)",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers={"X-Bitscan-Machine-Id": mA},
        want=200,
    )
    jobs = json.loads(out)["jobs"]
    w.note(
        "approved host has its inventory job",
        "one job, keys job_id, agent_id, kind inventory, pickup_by",
        json.dumps([sorted(j) for j in jobs]),
        len(jobs) == 1
        and sorted(jobs[0]) == ["agent_id", "job_id", "kind", "pickup_by"]
        and jobs[0]["kind"] == "inventory",
    )
    job = w.name(jobs[0]["job_id"], "<job>") if jobs else str(UUID(int=1))
    _, _, out = w.call(
        "job pull again (handed out once)",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers={"X-Bitscan-Machine-Id": mA},
        want=200,
    )
    w.note("second pull", '{"jobs": []}', out.decode(), json.loads(out) == {"jobs": []})
    inv = json.loads(
        (FIX / "inventory" / "request_valid_multi_arch.json").read_text(
            encoding="utf-8"
        )
    )
    ah = {"X-Bitscan-Machine-Id": mA}
    gzh = ah | {"Content-Type": "application/json", "Content-Encoding": "gzip"}
    w.call(
        "results post (no compliance jobs)",
        "POST",
        f"{V1}/agent/{A}/jobs/{job}/results",
        token=TA,
        body={"results": [], "final": False},
        headers=ah,
        want=409,
        want_type="job_not_acceptable",
    )
    w.call(
        "inventory without Content-Encoding: gzip",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={job}",
        token=TA,
        body=inv,
        headers=ah,
        want=400,
        want_type="invalid_request",
    )
    w.call(
        "inventory ?job_id not hyphenated",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={job.replace('-', '')}",
        token=TA,
        raw=gz(inv),
        headers=gzh,
        want=400,
        want_type="invalid_request",
    )
    w.call(
        "inventory with Content-Encoding GZIP (any case)",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={job}",
        token=TA,
        raw=gz(inv),
        headers=gzh | {"Content-Encoding": "GZIP"},
        want=204,
    )
    js = owner(
        server,
        "SELECT state, finished_at IS NOT NULL FROM scan_job WHERE job_id = %s",
        (job,),
    )
    w.note(
        "dispatched job completed",
        "completed, finished_at set",
        str(js),
        js == [("completed", True)],
    )
    w.call(
        "upload naming the completed job (unscheduled)",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={job}",
        token=TA,
        raw=gz(inv),
        headers=gzh,
        want=204,
    )
    w.call(
        "unscheduled upload within 10 minutes",
        "PUT",
        f"{V1}/agent/{A}/inventory",
        token=TA,
        raw=gz(inv),
        headers=gzh,
        want=429,
        want_type="rate_limited",
    )
    w.call(
        "upload naming an unknown job",
        "PUT",
        f"{V1}/agent/{A}/inventory?job_id={UUID(int=7)}",
        token=TA,
        raw=gz(inv),
        headers=gzh,
        want=409,
        want_type="job_not_acceptable",
    )
    w.call(
        "path id not hyphenated",
        "POST",
        f"{V1}/agent/{A.replace('-', '')}/heartbeat",
        token=TA,
        body=beat(A, TA, mA)["body"],
        headers=ah,
        want=400,
        want_type="invalid_request",
    )
    w.call(
        "another agent's path id",
        "POST",
        f"{V1}/agent/{UUID(int=9)}/heartbeat",
        token=TA,
        body=beat(A, TA, mA)["body"],
        headers=ah,
        want=403,
    )

    # ---------------------------------------------------- Route groups
    w.call(
        "user token on an agent route",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=S,
        headers=ah,
        want=401,
        want_type="unauthorized",
    )
    w.call("agent token on a user route", "GET", f"{V1}/agents", token=TA, want=401)

    # ---------------------------------------------------- Hosts, tags
    item: dict[str, Any] = next(
        iter(listed(w, "list hosts (viewer bsk_)", f"{V1}/agents?limit=500", VK, A)), {}
    )
    want_item = sorted(
        [
            "agent_id",
            "hostname",
            "status",
            "agent_version",
            "os_id",
            "os_version_id",
            "os_pretty_name",
            "last_heartbeat_at",
            "last_inventory_at",
            "tags",
            "runner_helpers",
        ]
    )
    w.note(
        "host item keys",
        ",".join(want_item),
        ",".join(sorted(item)),
        sorted(item) == want_item and item.get("runner_helpers") == ["capread"],
    )
    _, _, out = w.call("host detail", "GET", f"{V1}/agents/{A}", token=VK, want=200)
    det = json.loads(out)
    extra = {"machine_id", "enrolled_at", "last_seen_ip", "os_info", "last_snapshot"}
    snap = det.get("last_snapshot") or {}
    w.note(
        "detail adds",
        "machine_id, enrolled_at, last_seen_ip, token times, os_info, last_snapshot"
        " {snapshot_id, collected_at, package_count, added, removed}",
        ",".join(sorted(set(det) - set(want_item))) + " / " + ",".join(sorted(snap)),
        extra <= set(det)
        and sorted(snap)
        == ["added", "collected_at", "package_count", "removed", "snapshot_id"]
        and snap.get("package_count") == len(inv["packages"]),
    )
    w.note(
        "no token or hash in detail",
        "none",
        "checked",
        TA not in out.decode() and "token_hash" not in out.decode(),
    )
    _, _, out = w.call(
        "host packages", "GET", f"{V1}/agents/{A}/packages?limit=2", token=VK, want=200
    )
    w.note(
        "packages page",
        "2 items, next_cursor set",
        f"{len(json.loads(out)['items'])},"
        f" {json.loads(out)['next_cursor'] is not None}",
        len(json.loads(out)["items"]) == 2
        and json.loads(out)["next_cursor"] is not None,
    )
    tags = f"{V1}/agents/{A}/tags"
    _, _, out = w.call(
        "set tags (operator)",
        "PUT",
        tags,
        token=OP,
        body={"tags": ["prod-web", "db"]},
        want=200,
    )
    w.call("set tags (viewer)", "PUT", tags, token=VS, body={"tags": ["x"]}, want=403)
    w.call(
        "33 tags refused",
        "PUT",
        tags,
        token=OP,
        body={"tags": [f"t{i}" for i in range(33)]},
        want=400,
    )
    w.call(
        "tag with a space refused",
        "PUT",
        tags,
        token=OP,
        body={"tags": ["a b"]},
        want=400,
    )
    w.call("clear tags", "PUT", tags, token=OP, body={"tags": []}, want=200)

    # ---------------------------------------------------- Settings
    w.call("GET settings (admin bsk_)", "GET", f"{V1}/settings", token=K, want=200)
    w.call(
        "PATCH settings with admin bsk_",
        "PATCH",
        f"{V1}/settings",
        token=K,
        body={"job_pull_seconds": 120},
        want=403,
    )
    w.call(
        "PATCH unknown key inventory_enabled",
        "PATCH",
        f"{V1}/settings",
        token=S,
        body={"inventory_enabled": False},
        want=400,
    )
    w.call(
        "PATCH out of range (59)",
        "PATCH",
        f"{V1}/settings",
        token=S,
        body={"job_pull_seconds": 59},
        want=400,
    )
    w.call(
        "PATCH body over 1 MiB",
        "PATCH",
        f"{V1}/settings",
        token=S,
        raw=b" " * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
        want=413,
        oversize=True,
    )
    _, _, out = w.call(
        "PATCH job_pull_seconds 120",
        "PATCH",
        f"{V1}/settings",
        token=S,
        body={"job_pull_seconds": 120},
        want=200,
    )
    _, _, out = heartbeat(
        "heartbeat after the change", beat(A, TA, mA, runner_helpers=["capread"]), 200
    )
    w.note(
        "heartbeat carries the new value",
        "job_pull_seconds 120",
        out.decode(),
        json.loads(out).get("job_pull_seconds") == 120,
    )
    w.call(
        "PATCH job_pull_seconds back to 300",
        "PATCH",
        f"{V1}/settings",
        token=S,
        body={"job_pull_seconds": 300},
        want=200,
    )

    # ---------------------------------------------------- Token rotation (agent A)
    rot = f"{V1}/agent/{A}/token/rotate"
    w.call(
        "rotate a fresh token",
        "POST",
        rot,
        token=TA,
        headers=ah,
        want=403,
        want_type="forbidden",
    )
    owner(
        server,
        "UPDATE agent SET token_issued_at = %s, token_expires_at = %s"
        " WHERE agent_id = %s",
        (now() - timedelta(days=336), now() + timedelta(days=29), A),
    )
    w.note(
        "as owner",
        "token moved into its window (issued 336 d ago, TTL 365)",
        "done",
        True,
    )
    _, _, out = w.call(
        "rotate inside the window", "POST", rot, token=TA, headers=ah, want=200
    )
    r1 = json.loads(out)
    N1 = w.name(r1["agent_token"], "<bsa_ A new 1>")
    life = datetime.fromisoformat(
        r1["expires_at"].replace("Z", "+00:00")
    ) - datetime.fromisoformat(r1["issued_at"].replace("Z", "+00:00"))
    w.note(
        "rotate answer",
        "agent_token, issued_at, expires_at; lifetime 365 d",
        ",".join(r1) + f" {life}",
        list(r1) == ["agent_token", "issued_at", "expires_at"]
        and life == timedelta(days=365),
    )
    _, _, out = w.call(
        "rotate again with the old token (lost answer)",
        "POST",
        rot,
        token=TA,
        headers=ah,
        want=200,
    )
    N2 = w.name(json.loads(out)["agent_token"], "<bsa_ A new 2>")
    w.call(
        "first new token after the retry",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=N1,
        headers=ah,
        want=401,
    )
    w.call(
        "old token while the new one is unused",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers=ah,
        want=200,
    )
    w.call(
        "new token, first use",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=N2,
        headers=ah,
        want=200,
    )
    w.call(
        "old token inside the 10 minutes",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers=ah,
        want=200,
    )
    w.call(
        "second rotation within 24 h of a used one",
        "POST",
        rot,
        token=N2,
        headers=ah,
        want=429,
        want_type="rate_limited",
    )
    owner(
        server,
        "UPDATE agent SET prev_token_expires_at = %s WHERE agent_id = %s",
        (now() - timedelta(seconds=1), A),
    )
    w.note("as owner", "the 10-minute overlap ended", "done", True)
    w.call(
        "old token after the overlap",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=TA,
        headers=ah,
        want=401,
        want_type="token_revoked",
    )
    w.call(
        "new token after reuse",
        "GET",
        f"{V1}/agent/{A}/jobs",
        token=N2,
        headers=ah,
        want=401,
        want_type="token_revoked",
    )

    # ------------------------------------- Revoke and re-enrolment (agent B)
    _, _, out = w.call(
        "enrol with auto-approve token",
        "POST",
        enroll,
        token=E3,
        body=enrol_body("walk-b", mB),
        want=200,
    )
    eb = json.loads(out)
    w.note(
        "auto-approved",
        "status enrolled",
        str(eb.get("status")),
        eb.get("status") == "enrolled",
    )
    B, TB = w.name(eb["agent_id"], "<B>"), w.name(eb["agent_token"], "<bsa_ B>")
    heartbeat("B heartbeat", beat(B, TB, mB), 200)
    w.call(
        "revoke with admin bsk_", "POST", f"{V1}/agents/{B}/revoke", token=K, want=403
    )
    w.call(
        "revoke (admin TOTP session)",
        "POST",
        f"{V1}/agents/{B}/revoke",
        token=S,
        want=204,
    )
    heartbeat("B after revoke", beat(B, TB, mB), 401, "token_revoked")
    _, _, out = w.call(
        "B enrols again with the auto-approve token",
        "POST",
        enroll,
        token=E3,
        body=enrol_body("walk-b", mB),
        want=200,
    )
    eb2 = json.loads(out)
    w.note(
        "re-enrolment is held, same agent",
        "awaiting_approval, agent_id <B>",
        f"{eb2.get('status')}, {w.hide(eb2.get('agent_id', ''))}",
        eb2.get("status") == "awaiting_approval" and eb2.get("agent_id") == B,
    )
    TB2 = w.name(eb2["agent_token"], "<bsa_ B re-enrol>")
    heartbeat("held re-enrolment token", beat(B, TB2, mB), 403, "pending_approval")
    heartbeat(
        "held re-enrolment token, wrong machine-id",
        beat(B, TB2, mB),
        401,
        "machine_id_mismatch",
        mid=secrets.token_hex(16),
    )
    rb = listed(w, "pending requests", f"{V1}/enrollment-requests", S, B)
    w.note(
        "request stays pending after the mismatch",
        "kind reenrol, pending",
        json.dumps([(i["kind"], i["decision"]) for i in rb]),
        len(rb) == 1 and rb[0]["kind"] == "reenrol" and rb[0]["decision"] is None,
    )
    if rb:
        w.call(
            "reject the re-enrolment",
            "POST",
            f"{V1}/enrollment-requests/{rb[0]['request_id']}/reject",
            token=S,
            want=200,
        )
    heartbeat(
        "rejected re-enrolment token", beat(B, TB2, mB), 401, "enrollment_rejected"
    )

    # ------------------- Machine-id (C), re-enrolment approval and expiry (D)
    _, _, out = w.call(
        "enrol C", "POST", enroll, token=E3, body=enrol_body("walk-c", mC), want=200
    )
    C, TC = (
        w.name(json.loads(out)["agent_id"], "<C>"),
        w.name(json.loads(out)["agent_token"], "<bsa_ C>"),
    )
    heartbeat(
        "C without X-Bitscan-Machine-Id",
        beat(C, TC, mC),
        401,
        "machine_id_mismatch",
        mid="",
    )
    heartbeat(
        "C with the right header afterwards", beat(C, TC, mC), 401, "token_revoked"
    )
    _, _, out = w.call(
        "enrol D", "POST", enroll, token=E3, body=enrol_body("walk-d", mD), want=200
    )
    D, TD = (
        w.name(json.loads(out)["agent_id"], "<D>"),
        w.name(json.loads(out)["agent_token"], "<bsa_ D>"),
    )
    heartbeat("D heartbeat", beat(D, TD, mD), 200)
    _, _, out = w.call(
        "D re-enrols (reinstall)",
        "POST",
        enroll,
        token=E2,
        body=enrol_body("walk-d2", mD),
        want=200,
    )
    TD2 = w.name(json.loads(out)["agent_token"], "<bsa_ D re-enrol>")
    heartbeat("D old token while held", beat(D, TD, mD), 200)
    rd = listed(w, "pending requests (D)", f"{V1}/enrollment-requests", S, D)
    w.note(
        "cloned/reinstalled host matches",
        "matches lists other agents sharing hostname or machine-id",
        json.dumps([len(i["matches"]) for i in rd]),
        len(rd) == 1,
    )
    if rd:
        w.call(
            "approve the re-enrolment",
            "POST",
            f"{V1}/enrollment-requests/{rd[0]['request_id']}/approve",
            token=S,
            want=200,
        )
    heartbeat("D old token after approval", beat(D, TD, mD), 401)
    heartbeat("D new token after approval", beat(D, TD2, mD), 200)
    _, _, out = w.call(
        "enrol E sharing A's hostname",
        "POST",
        enroll,
        token=E2,
        body=enrol_body("walk-a", secrets.token_hex(16)),
        want=200,
    )
    E = w.name(json.loads(out)["agent_id"], "<E>")
    re_ = listed(w, "pending requests (E)", f"{V1}/enrollment-requests", S, E)
    got = [m.get("agent_id") for m in re_[0]["matches"]] if re_ else []
    w.note(
        "shared hostname listed in matches",
        "matches holds <A>",
        json.dumps([w.hide(str(g)) for g in got]),
        A in got,
    )
    if re_:
        owner(
            server,
            "UPDATE enrollment_request SET token_expires_at = %s WHERE request_id = %s",
            (now() - timedelta(seconds=1), re_[0]["request_id"]),
        )
        w.note("as owner", "E's request token expired", "done", True)
        w.call(
            "approve a request whose token expired",
            "POST",
            f"{V1}/enrollment-requests/{re_[0]['request_id']}/approve",
            token=S,
            want=409,
        )
    owner(
        server,
        "UPDATE agent SET token_expires_at = %s WHERE agent_id = %s",
        (now() - timedelta(seconds=1), D),
    )
    w.note("as owner", "D's token expired", "done", True)
    heartbeat("D after expires_at", beat(D, TD2, mD), 401, "token_expired")
    w.call(
        "D rotate after expires_at",
        "POST",
        f"{V1}/agent/{D}/token/rotate",
        token=TD2,
        headers={"X-Bitscan-Machine-Id": mD},
        want=401,
        want_type="token_expired",
    )

    # ---------------------------------------------------- Metrics
    st, hdrs, out = w.call(
        "metrics (viewer bsk_)", "GET", f"{V1}/metrics", token=VK, want=200
    )
    text = out.decode()
    names = [
        "bitscan_alerts_total",
        "bitscan_agents",
        "bitscan_heartbeat_latency_seconds",
        "bitscan_jobs_queued",
        "bitscan_jobs_expired_total",
    ]
    w.note(
        "metrics text",
        "text/plain version 0.0.4 with the five metrics",
        hdrs.get("content-type", "") + " " + ",".join(n for n in names if n in text),
        "version=0.0.4" in hdrs.get("content-type", "")
        and all(n in text for n in names),
    )
    w.note(
        "no hostname, token or agent id in labels",
        "none",
        "checked",
        all(x not in text for x in (A, B, C, D, "walk-a", "walk-b", TA)),
    )
    w.call("metrics without a token", "GET", f"{V1}/metrics", want=401)

    # ---------------------------------------------------- Audit log
    w.call("audit log (operator)", "GET", f"{V1}/audit-log", token=OP, want=403)
    items_all: list[dict[str, Any]] = []
    cursor = None
    while True:
        q = f"{V1}/audit-log?limit=500" + (f"&cursor={cursor}" if cursor else "")
        st, _, out = w.call("audit log page (admin bsk_)", "GET", q, token=K, want=200)
        if st != 200:
            break
        page = json.loads(out)
        items_all += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    want_audit = sorted(
        [
            "audit_id",
            "actor",
            "action",
            "target",
            "detail",
            "detail_text",
            "at",
            "prev_hash",
            "row_hash",
        ]
    )
    bad = [i["audit_id"] for i in items_all if row_hash(i) != i["row_hash"]]
    links = all(
        items_all[k]["prev_hash"] == items_all[k + 1]["row_hash"]
        for k in range(len(items_all) - 1)
    )
    w.note(
        "audit item keys",
        ",".join(want_audit),
        ",".join(sorted(items_all[0])) if items_all else "none",
        bool(items_all) and sorted(items_all[0]) == want_audit,
    )
    w.note(
        "README re-verification of every item",
        "every row_hash matches, prev_hash links, newest first",
        f"{len(items_all)} items, {len(bad)} mismatched, links {links}",
        not bad
        and links
        and all(
            items_all[k]["audit_id"] > items_all[k + 1]["audit_id"]
            for k in range(len(items_all) - 1)
        ),
    )
    kinds = {
        i["detail"].get("alert_kind")
        for i in items_all
        if isinstance(i["detail"], dict) and i["detail"].get("alert") is True
    }
    for kind in (
        "enrolment_token_risky",
        "runner_helper_changed",
        "clock_skew",
        "settings_changed",
        "rotation_outside_window",
        "token_reuse",
        "machine_id_mismatch",
        "reenrolment_approved",
    ):
        w.note(
            f"alert {kind}",
            "present",
            "present" if kind in kinds else "missing",
            kind in kinds,
        )
    texts = json.dumps(items_all)
    w.note(
        "no token in the audit log",
        "none of the issued tokens",
        "checked",
        all(
            t not in texts and t[4:] not in texts
            for t in (S, K, VK, E1, E2, E3, TA, N1, N2, TB, TB2, TC, TD, TD2)
        ),
    )

    # ---------------------------------------------------- Scheduler
    js = owner(
        server,
        "SELECT kind, state FROM scan_job WHERE agent_id = %s",
        (planted_enrolled,),
    )
    w.note(
        "inventory queued at start-up",
        "one queued inventory job for an enrolled host",
        str(js),
        js == [("inventory", "queued")],
    )
    stale = plant(server, "online", now() - timedelta(minutes=31))
    deadline = time.monotonic() + 80
    status = None
    while time.monotonic() < deadline:
        status = owner(
            server, "SELECT status FROM agent WHERE agent_id = %s", (stale,)
        )[0][0]
        if status == "offline":
            break
        time.sleep(1)
    w.note(
        "offline_sweep every 60 s",
        "a host with a 31-minute-old heartbeat becomes offline within a minute",
        str(status),
        status == "offline",
    )

    # ---------------------------------------------------- Limits (last)
    _, _, out = w.call(
        "D new token, 30 per minute", "GET", f"{V1}/healthz", want=404
    )  # marker row only
    w.rows.pop()
    # Start in a fresh calendar minute: the limit counts per minute, and D's
    # requests from the steps above must not share it (under parallel load
    # they did: 27 x 200, M3 gate xdist run).
    fresh = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    while datetime.now(UTC) < fresh:
        time.sleep(0.2)
    b2 = beat(D, TD2, mD)
    owner(
        server,
        "UPDATE agent SET token_expires_at = %s WHERE agent_id = %s",
        (now() + timedelta(days=30), D),
    )
    codes = []
    for _ in range(31):
        st, hdrs, _ = https_get(
            w.port,
            w.ca,
            f"{V1}/agent/{D}/heartbeat",
            {
                "Authorization": f"Bearer {TD2}",
                "X-Bitscan-Machine-Id": mD,
                "Content-Type": "application/json",
            },
            json.dumps(b2["body"]).encode(),
            "POST",
        )
        codes.append(st)
    w.note(
        "31 agent requests in a minute",
        "30 x 200 then 429 with Retry-After",
        f"{codes.count(200)} x 200, last {codes[-1]}"
        f" Retry-After={hdrs.get('retry-after')}",
        codes[:30] == [200] * 30 and codes[30] == 429 and "retry-after" in hdrs,
    )
    time.sleep(61 - datetime.now(UTC).second)
    codes = []
    for _ in range(11):
        st, hdrs, _ = https_get(
            w.port,
            w.ca,
            enroll,
            {"Authorization": f"Bearer {E3}", "Content-Type": "application/json"},
            b"{not json",
            "POST",
        )
        codes.append(st)
    w.note(
        "11 malformed enrolments in a minute",
        "10 x 400 then 429 with Retry-After",
        f"{codes.count(400)} x 400, last {codes[-1]}"
        f" Retry-After={hdrs.get('retry-after')}",
        codes[:10] == [400] * 10 and codes[10] == 429 and "retry-after" in hdrs,
    )

    # ---------------------------------------------------- Stopping
    code = serve.stop()
    w.note("SIGTERM", "exit 0", f"exit {code}", code == 0)
    log = serve.output()
    leaked = [
        n
        for n in (S, K, VK, E1, E2, E3, TA, N1, N2, TB, TB2, TC, TD, TD2, pw, vpw)
        if n in log or n[4:] in log
    ]
    w.note(
        "logs: JSON lines, no token or password",
        "every line JSON; none leaked",
        f"{len(leaked)} leaked",
        not leaked
        and all(json.loads(ln) is not None for ln in log.splitlines() if ln.strip()),
    )

    out_path = os.environ.get("WALK_OUT")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for r in w.rows:
                f.write(json.dumps(r.__dict__) + "\n")
    deviations = [r for r in w.rows if not r.ok]
    assert not deviations, "\n".join(
        f"{r.label}: expected {r.expected}, got {r.status} {r.answer}"
        for r in deviations
    )
