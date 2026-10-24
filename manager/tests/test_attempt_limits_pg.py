"""TASK-082: every attempt counts on enrol and sign-in (TP-M3-36), on PostgreSQL.

Checks CHK-M3-380 to CHK-M3-384 of tests/m3/test-plan.md. Expected values: TS
§6.3 L1136 (sign-in and enrolment 10 per minute per source IP), #55 (c) (every
request to the route counts, whatever its body), #48/#59 (400
invalid_request for a body that does not parse or validate, 429 rate_limited
with Retry-After), decisions 2026-10-23 "TASK-067 second approval given"
(11 non-JSON attempts from one IP get 429 on each route; no other behaviour
change) and "TASK-082 design" (option (B): the limit runs before FastAPI
reads the body; parsing, problem bodies and the OpenAPI document unchanged;
the body-cap middleware still runs first). The two limits are separate (one
for sign-in, one for enrolment).
"""

import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 5, tzinfo=UTC)  # 55 s to the minute's end
LOGIN = "/api/v1/auth/login"
ENROL = "/api/v1/agent/enroll"
OPENAPI = Path(__file__).resolve().parents[1] / "openapi.json"
PW = "attempt limit pass " + "phrase"
BAD_BODIES: list[tuple[str, bytes, str]] = [
    ("text-plain", b"hello", "text/plain"),
    ("malformed-json", b'{"x":', "application/json"),
    ("truncated-object", b'{"username": "a", "password": ', "application/json"),
    ("invalid-utf8", b'{"username": "\xff\xfe"}', "application/json"),
    ("not-json-bytes", b"\x00\x01\x02", "application/octet-stream"),
]


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Env:
    server: PgServer
    clock: Clock
    limits: RateLimiter
    app: FastAPI
    _n: int = 0
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def ip(self) -> str:
        self._n += 1
        return f"10.82.{self._n // 256}.{self._n % 256}"

    def client(self, ip: str) -> TestClient:
        if ip not in self.clients:
            self.clients[ip] = TestClient(
                self.app, client=(ip, 1234), raise_server_exceptions=False
            )
        return self.clients[ip]

    def bse(self) -> tuple[int, str]:
        tok = new_agent_token(AgentTokenKind.ENROLMENT)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO enrollment_token (token_hash, max_uses, auto_approve,"
                " expires_at, created_by, created_at) VALUES (%s, 100, true, %s, 1, %s)"
                " RETURNING token_id",
                (token_hash(tok), T0 + timedelta(days=1), T0),
            ).fetchone()
        assert row is not None
        return int(row[0]), tok

    def uses(self, token_id: int) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT uses FROM enrollment_token WHERE token_id = %s", (token_id,)
            ).fetchone()
        assert row is not None
        return int(row[0])

    def user(self) -> tuple[int, str]:
        name = f"al-{secrets.token_hex(4)}"
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, created_at)"
                " VALUES (%s, %s, 'viewer', %s) RETURNING user_id",
                (name, hash_password(PW), T0),
            ).fetchone()
        assert row is not None
        return int(row[0]), name

    def sessions(self, uid: int) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT count(*) FROM user_token WHERE user_id = %s", (uid,)
            ).fetchone()
        assert row is not None
        return int(row[0])

    def counts(self) -> tuple[Any, ...]:
        with self.conn() as c:
            return (
                c.execute("SELECT count(*) FROM agent").fetchone(),
                c.execute("SELECT count(*) FROM enrollment_request").fetchone(),
                c.execute("SELECT count(*) FROM user_token").fetchone(),
                c.execute("SELECT count(*) FROM audit_log").fetchone(),
            )


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=5)
    db.open()
    limits = RateLimiter(clock)
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=Gate(), limits=limits
    )
    e = Env(migrated_db, clock, limits, create_app(rt))
    yield e
    for c in e.clients.values():
        c.close()
    db.close()


def post(e: Env, ip: str, path: str, content: bytes, ctype: str, **h: str) -> Any:
    headers = {"Content-Type": ctype, **h}
    return e.client(ip).post(path, content=content, headers=headers)


def bse_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.ENROLMENT)}"}


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == type_, body
    return body


def headers_for(path: str) -> dict[str, str]:
    return bse_header() if path == ENROL else {}


# ------------------------------------------------------------ CHK-M3-380


@pytest.mark.parametrize("path", [LOGIN, ENROL])
@pytest.mark.parametrize(
    ("name", "content", "ctype"), BAD_BODIES, ids=[b[0] for b in BAD_BODIES]
)
def test_eleven_unparseable_attempts_give_ten_400_then_429(
    env: Env, path: str, name: str, content: bytes, ctype: str
) -> None:
    """TP-M3-36: 10 x 400 invalid_request, then 429 rate_limited with
    Retry-After to the minute's end; the 400 bodies are all the same; nothing
    is written; another IP is not limited; the next minute is open again."""
    ip = env.ip()
    before = env.counts()
    bodies = set()
    for _ in range(10):
        r = post(env, ip, path, content, ctype, **headers_for(path))
        problem(r, 400, "invalid_request")
        bodies.add(r.content)
    assert len(bodies) == 1
    r = post(env, ip, path, content, ctype, **headers_for(path))
    body = problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"
    assert body["status"] == 429 and body["instance"] == path
    assert "content-security-policy" in {k.lower() for k in r.headers}
    assert env.counts() == before
    other = post(env, env.ip(), path, content, ctype, **headers_for(path))
    problem(other, 400, "invalid_request")
    env.clock.at = T0 + timedelta(minutes=1)
    problem(
        post(env, ip, path, content, ctype, **headers_for(path)), 400, "invalid_request"
    )
    env.clock.at = T0


# ------------------------------------------------------------ CHK-M3-381


def test_login_after_ten_malformed_attempts_refuses_the_right_password(
    env: Env,
) -> None:
    """#55 (c): malformed attempts count toward the same limit as real ones;
    the 11th is refused before the password is checked (no session)."""
    uid, name = env.user()
    ip = env.ip()
    for i in range(10):
        if i % 2:
            r = post(env, ip, LOGIN, b"{", "application/json")
            problem(r, 400, "invalid_request")
        else:
            # an unknown user, so the real account gets no back-off
            nobody = {"username": f"nobody-{i}-{name}", "password": "x" * 12}
            r = env.client(ip).post(LOGIN, json=nobody)
            assert r.status_code == 401
    r = env.client(ip).post(LOGIN, json={"username": name, "password": PW})
    problem(r, 429, "rate_limited")
    assert env.sessions(uid) == 0
    r = env.client(env.ip()).post(LOGIN, json={"username": name, "password": PW})
    assert r.status_code == 200, r.text  # from another IP the password works
    assert env.sessions(uid) == 1


def test_enrol_after_ten_malformed_attempts_refuses_a_valid_token(env: Env) -> None:
    """The 11th enrolment with a valid bse_ and body is refused; the token is
    not used and no agent is created."""
    tid, tok = env.bse()
    ip = env.ip()
    for _ in range(10):
        problem(
            post(
                env,
                ip,
                ENROL,
                b"not json",
                "application/json",
                Authorization=f"Bearer {tok}",
            ),
            400,
            "invalid_request",
        )
    assert env.uses(tid) == 0
    before = env.counts()
    body = {
        "hostname": "al-host",
        "machine_id": secrets.token_hex(16),
        "agent_version": "1.0.0",
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "os_pretty_name": "Ubuntu 24.04 LTS",
    }
    r = env.client(ip).post(
        ENROL, json=body, headers={"Authorization": f"Bearer {tok}"}
    )
    problem(r, 429, "rate_limited")
    assert env.uses(tid) == 0 and env.counts() == before
    r = env.client(env.ip()).post(
        ENROL, json=body, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200, r.text
    assert env.uses(tid) == 1


def test_the_two_limits_are_separate(env: Env) -> None:
    """TS §6.3 L1136 names two limits: ten enrol attempts from an IP do not
    limit its sign-in, and the other way round."""
    ip = env.ip()
    for _ in range(11):
        post(env, ip, ENROL, b"x", "text/plain", **bse_header())
    problem(post(env, ip, LOGIN, b"x", "text/plain"), 400, "invalid_request")
    ip2 = env.ip()
    for _ in range(11):
        post(env, ip2, LOGIN, b"x", "text/plain")
    problem(
        post(env, ip2, ENROL, b"x", "text/plain", **bse_header()),
        400,
        "invalid_request",
    )


def test_malformed_enrol_attempts_are_not_failed_token_checks(env: Env) -> None:
    """A body that does not parse never reaches the bse_ check, so it is not a
    failed token check (the 20-per-minute limit is for token checks)."""
    ip = env.ip()
    env.limits.drain(final=True)
    for _ in range(11):
        post(env, ip, ENROL, b"x", "text/plain", **bse_header())
    env.clock.at = T0 + timedelta(minutes=1)
    assert ip not in {d.ip for d in env.limits.drain()}
    env.clock.at = T0


# ------------------------------------------------------------ CHK-M3-382


def test_the_limit_is_decided_before_the_body_is_parsed(env: Env) -> None:
    """Decisions 2026-10-23 (option (B)): the per-IP limit runs before FastAPI
    parses the body, so the 11th attempt is 429 whatever its body, and a body
    that would be valid is not looked at (no user lookup, no session). The M2
    body-cap middleware (REQ-037) still buffers and caps every normal-mode
    body before any route, so bytes are read from the client in both cases;
    that is unchanged and not what this checks."""
    ip = env.ip()
    for _ in range(10):
        post(env, ip, LOGIN, b"{", "application/json")
    for content, ctype in (
        (b"{", "application/json"),
        (b'{"username": "u", "password": "p"}', "application/json"),
        (b"", "text/plain"),
    ):
        problem(post(env, ip, LOGIN, content, ctype), 429, "rate_limited")


def test_an_over_cap_body_is_still_413_first(env: Env) -> None:
    """The body-cap middleware still runs before the route (TS §6.3 L1138)."""
    for path in (LOGIN, ENROL):
        r = post(
            env,
            env.ip(),
            path,
            b" " * (1_048_576 + 1),
            "application/json",
            **headers_for(path),
        )
        problem(r, 413, "too_large")


# ------------------------------------------------------------ CHK-M3-383


def test_only_the_two_routes_use_the_limit_first_route_class() -> None:
    """The extension point is used on exactly these operations: enrol and
    sign-in (TASK-082), and the heartbeat, the one bsa_ route with a FastAPI
    JSON body, so its token is checked before the body (TASK-083); the enrol
    dependency marker is intact."""
    app = create_app()
    special = sorted(
        (sorted(r.methods)[0], r.path)
        for r in api_routes(app.routes)
        if type(getattr(r, "original_route", r)) is not APIRoute
    )
    assert special == sorted(
        [("POST", ENROL), ("POST", LOGIN), ("POST", "/api/v1/agent/{id}/heartbeat")]
    )
    enrol = next(r for r in api_routes(app.routes) if r.path == ENROL)
    marks = {
        getattr(d.call, "bitscan_agent_auth", None)
        for d in enrol.dependant.dependencies
    }
    assert "bse_" in marks


def test_openapi_documents_both_request_bodies_without_422() -> None:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    for path, schema in ((LOGIN, "LoginRequest"), (ENROL, "EnrolRequest")):
        op = doc["paths"][path]["post"]
        body = op["requestBody"]["content"]["application/json"]["schema"]
        assert body == {"$ref": f"#/components/schemas/{schema}"}
        assert op["requestBody"].get("required") is True
        assert "422" not in op["responses"]
        assert {"400", "429"} <= set(op["responses"])
