"""REQ-044, REQ-045, REQ-046, REQ-047 (3): the user-route auth dependencies
(TASK-037; TP-M2-15; G25, TS §8.3 Security).

Checks CHK-M2-150 to CHK-M2-167 of tests/m2/test-plan.md. Expected values:
TS §2.3 L118, §6 L1056 (user routes accept only bsu_ and bsk_), TS §6.2
L1080-L1091 (8 h idle, 24 h max, role read each request, sensitive actions
need a TOTP session and refuse API tokens, restricted admin session), TS §6.3
L1136 (failed-check limit; valid tokens never throttled), #48 (statuses and
types), #53 (i) and decisions 2026-10-21 (admin API token without TOTP: 403
totp_enrolment_required, not counted), "Correction to M2 test-plan answers
(3)" (every token is checked first).

The matrix runs on PostgreSQL as bitscan_app (marker pg); the route-walk tests
at the end run anywhere.
"""

import hashlib
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import psycopg
import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.dependencies import (
    AuthMarker,
    require_role,
    require_session,
    require_totp_session,
)
from bitscan_manager.auth.principal import Principal
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import sweep
from .conftest import PgServer
from .test_runtime import FakeCipher

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
UNAUTH_KEYS = {"type", "title", "status", "detail", "instance"}

ROUTES = {
    "/t/viewer": require_role("viewer"),
    "/t/operator": require_role("operator"),
    "/t/admin": require_role("admin"),
    "/t/session": require_session(),
    "/t/session-restricted": require_session(allow_restricted=True),
    "/t/totp": require_totp_session(),
    "/t/totp-viewer": require_totp_session(minimum="viewer"),
}


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


class Gate:
    def __init__(self) -> None:
        self.refuse = False

    def refusing(self) -> bool:
        return self.refuse

    def wake(self) -> None:
        return None


def make_app(runtime: Runtime | None) -> FastAPI:
    app = create_app(runtime)
    for path, dep in ROUTES.items():

        def handler(p: Annotated[Principal, Depends(dep)]) -> dict[str, Any]:
            return {"user_id": p.user_id, "role": p.role, "kind": p.kind.value}

        app.add_api_route(path, handler, methods=["GET"])
    return app


@dataclass
class Env:
    server: PgServer
    clock: Clock
    gate: Gate
    limits: RateLimiter
    db: AppDatabase
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(
        self, role: str = "viewer", totp: bool = False, disabled: bool = False
    ) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " disabled, created_at) VALUES (%s, %s, %s::user_role, %s, %s, %s)"
                " RETURNING user_id",
                (
                    f"u-{secrets.token_hex(5)}",
                    "$argon2id$x",
                    role,
                    "vault:v1:x" if totp else None,
                    disabled,
                    self.clock.at,
                ),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def token(
        self,
        user_id: int,
        kind: str = "session",
        *,
        verified: bool = False,
        expires: timedelta = timedelta(hours=24),
        raw: str | None = None,
        store_kind: str | None = None,
    ) -> str:
        tok = raw or new_token(
            TokenKind.SESSION if kind == "session" else TokenKind.API
        )
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    store_kind or kind,
                    token_hash(tok),
                    verified,
                    self.clock.at + expires,
                    self.clock.at,
                ),
            )
        return tok

    def get(
        self,
        path: str,
        token: str | None = None,
        ip: str = "192.0.2.10",
        **headers: str,
    ) -> Any:
        h = dict(headers)
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        return self.client.get(path, headers=h)

    def snapshot(self) -> tuple[Any, ...]:
        with self.conn() as c:
            users = c.execute("SELECT * FROM app_user ORDER BY user_id").fetchall()
            toks = c.execute(
                "SELECT token_id, revoked_at, expires_at FROM user_token"
                " ORDER BY token_id"
            ).fetchall()
            audit = c.execute("SELECT count(*) FROM audit_log").fetchone()
        return (users, toks, audit)


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock, gate = Clock(), Gate()
    limits = RateLimiter(clock)
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    rt = Runtime(
        clock=clock, db=db, totp_cipher=FakeCipher(), sink_gate=gate, limits=limits
    )
    with TestClient(make_app(rt), client=("192.0.2.10", 50000)) as client:
        yield Env(migrated_db, clock, gate, limits, db, client)
    db.close()


def body_of(resp: Any) -> dict[str, Any]:
    data: dict[str, Any] = resp.json()
    return data


def assert_problem(resp: Any, status: int, type_: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = body_of(resp)
    assert set(body) == UNAUTH_KEYS and body["type"] == type_


pg = pytest.mark.pg


# ------------------------------------------------------------ CHK-M2-150


@pg
def test_missing_or_malformed_credentials_get_one_401(env: Env) -> None:
    uid = env.user()
    good = env.token(uid)
    unknown_session = new_token(TokenKind.SESSION)
    unknown_api = new_token(TokenKind.API)
    cases: list[dict[str, str]] = [
        {},
        {"Authorization": f"Basic {good}"},
        {"Authorization": f"Token {good}"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer  {good}"},
        {"Authorization": f"Bearer {good} extra"},
        {"Authorization": f"Bearer {unknown_session}"},
        {"Authorization": f"Bearer {unknown_api}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
        {"Authorization": "Bearer " + "A" * 47},
        {"Cookie": f"token={good}"},
    ]
    bodies = set()
    for headers in cases:
        resp = env.client.get("/t/viewer", headers=headers)
        assert_problem(resp, 401, "unauthorized")
        bodies.add(resp.text)
    resp = env.client.get(f"/t/viewer?token={good}&access_token={good}")
    assert_problem(resp, 401, "unauthorized")
    bodies.add(resp.text)
    assert len(bodies) == 1  # byte-identical for every cause
    assert (
        env.client.get(
            "/t/viewer", headers={"Authorization": f"bearer {good}"}
        ).status_code
        == 200
    )
    assert (
        env.client.get(
            "/t/viewer", headers={"Authorization": f"BEARER {good}"}
        ).status_code
        == 200
    )


@pg
def test_two_authorization_headers_are_refused(env: Env) -> None:
    good = env.token(env.user())
    resp = env.client.get(
        "/t/viewer",
        headers=[
            ("Authorization", f"Bearer {good}"),
            ("Authorization", f"Bearer {good}"),
        ],
    )
    assert_problem(resp, 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-151


@pg
@pytest.mark.parametrize("prefix", ["bsa_", "bse_"])
def test_agent_and_enrolment_tokens_refused_even_with_planted_hashes(
    env: Env, prefix: str
) -> None:
    """The prefix check alone must refuse them: their SHA-256 is planted on a
    live session row and a live API row of a real admin."""
    uid = env.user("admin", totp=True)
    raw = prefix + secrets.token_urlsafe(32)
    assert len(raw) == 47
    env.token(uid, "session", verified=True, raw=raw)
    raw2 = prefix + secrets.token_urlsafe(32)
    env.token(uid, "api", raw=raw2)
    for tok in (raw, raw2):
        for path in ROUTES:
            assert_problem(env.get(path, tok), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-152


@pg
def test_prefix_must_match_the_row_kind(env: Env) -> None:
    uid = env.user("admin", totp=True)
    bsu_on_api = new_token(TokenKind.SESSION)
    env.token(uid, "api", raw=bsu_on_api)
    bsk_on_session = new_token(TokenKind.API)
    env.token(uid, "session", verified=True, raw=bsk_on_session)
    for tok in (bsu_on_api, bsk_on_session):
        assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-153


@pg
def test_session_idle_limit_is_8_hours_from_last_use(env: Env) -> None:
    uid = env.user()
    tok = env.token(uid)
    env.clock.at = T0 + timedelta(hours=7, minutes=59)
    assert env.get("/t/viewer", tok).status_code == 200  # touches last_used_at
    env.clock.at += timedelta(hours=7, minutes=59)
    assert env.get("/t/viewer", tok).status_code == 200
    env.clock.at += timedelta(hours=8)
    assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")


@pg
def test_never_used_session_counts_idle_from_creation(env: Env) -> None:
    tok = env.token(env.user())
    env.clock.at = T0 + timedelta(hours=8)
    assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")


@pg
def test_session_maximum_is_24_hours_even_when_used_every_hour(env: Env) -> None:
    tok = env.token(env.user())
    for hour in range(1, 24):
        env.clock.at = T0 + timedelta(hours=hour) - timedelta(minutes=1)
        assert env.get("/t/viewer", tok).status_code == 200, hour
    env.clock.at = T0 + timedelta(hours=23, minutes=59)
    assert env.get("/t/viewer", tok).status_code == 200
    env.clock.at = T0 + timedelta(hours=24)
    assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-154


@pg
def test_api_token_expiry_and_revocation(env: Env) -> None:
    uid = env.user("operator")
    tok = env.token(uid, "api", expires=timedelta(days=90))
    env.clock.at = T0 + timedelta(days=90) - timedelta(seconds=1)
    assert env.get("/t/viewer", tok).status_code == 200
    env.clock.at = T0 + timedelta(days=90)
    assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")
    tok2 = env.token(uid, "api", expires=timedelta(days=200))
    with env.conn() as c:
        c.execute(
            "UPDATE user_token SET revoked_at = %s WHERE token_hash = %s",
            (env.clock.at, token_hash(tok2)),
        )
    assert_problem(env.get("/t/viewer", tok2), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-155


@pg
def test_disabled_user_loses_every_token(env: Env) -> None:
    uid = env.user("operator")
    sess, api = env.token(uid), env.token(uid, "api")
    assert env.get("/t/viewer", sess).status_code == 200
    with env.conn() as c:
        c.execute("UPDATE app_user SET disabled = true WHERE user_id = %s", (uid,))
    for tok in (sess, api):
        assert_problem(env.get("/t/viewer", tok), 401, "unauthorized")


# ------------------------------------------------------- CHK-M2-156, -158


@pg
def test_role_is_read_on_every_request(env: Env) -> None:
    uid = env.user("viewer")
    api = env.token(uid, "api")
    assert_problem(env.get("/t/operator", api), 403, "forbidden")
    with env.conn() as c:
        c.execute("UPDATE app_user SET role = 'operator' WHERE user_id = %s", (uid,))
    assert env.get("/t/operator", api).status_code == 200
    with env.conn() as c:
        c.execute("UPDATE app_user SET role = 'viewer' WHERE user_id = %s", (uid,))
    assert_problem(env.get("/t/operator", api), 403, "forbidden")


@pg
@pytest.mark.parametrize(
    ("path", "ok_roles"),
    [
        ("/t/viewer", {"viewer", "operator", "admin"}),
        ("/t/operator", {"operator", "admin"}),
        ("/t/admin", {"admin"}),
    ],
)
def test_role_order(env: Env, path: str, ok_roles: set[str]) -> None:
    for role in ("viewer", "operator", "admin"):
        uid = env.user(role, totp=True)
        tok = env.token(uid, "session", verified=True)
        resp = env.get(path, tok)
        if role in ok_roles:
            assert resp.status_code == 200, (role, path)
            assert body_of(resp)["role"] == role
        else:
            assert_problem(resp, 403, "forbidden")


# ------------------------------------------------------------ CHK-M2-157


@pg
def test_accepted_requests_move_last_used_at(env: Env) -> None:
    tok = env.token(env.user())

    def last_used() -> datetime | None:
        with env.conn() as c:
            row = c.execute(
                "SELECT last_used_at FROM user_token WHERE token_hash = %s",
                (token_hash(tok),),
            ).fetchone()
        assert row is not None
        return row[0]  # type: ignore[no-any-return]

    assert last_used() is None
    env.clock.at = T0 + timedelta(minutes=5)
    env.get("/t/viewer", tok)
    assert last_used() == env.clock.at
    env.clock.at += timedelta(seconds=30)
    env.get("/t/viewer", tok)
    assert last_used() == T0 + timedelta(minutes=5)  # 60 s write skip (TASK-031)
    env.clock.at += timedelta(seconds=31)
    env.get("/t/viewer", tok)
    assert last_used() == env.clock.at
    before = last_used()
    env.clock.at += timedelta(minutes=5)
    env.get("/t/viewer", "bsu_" + "A" * 43)  # a failed check touches nothing
    assert last_used() == before


# ------------------------------------------------------------ CHK-M2-160


@pg
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_api_tokens_refused_on_session_only_routes(env: Env, role: str) -> None:
    uid = env.user(role, totp=True)
    api = env.token(uid, "api")
    before = env.snapshot()
    for path in ("/t/session", "/t/session-restricted"):
        assert_problem(env.get(path, api), 403, "session_required")
    assert env.snapshot()[0] == before[0] and env.snapshot()[2] == before[2]
    sess = env.token(uid, "session", verified=True)
    assert env.get("/t/session", sess).status_code == 200


# ------------------------------------------------------------ CHK-M2-161


@pg
def test_totp_session_routes(env: Env) -> None:
    admin = env.user("admin", totp=True)
    verified = env.token(admin, "session", verified=True)
    api = env.token(admin, "api")
    assert env.get("/t/totp", verified).status_code == 200
    # the admin's own API token is refused even while the verified session exists
    assert_problem(env.get("/t/totp", api), 403, "totp_session_required")
    assert_problem(env.get("/t/totp-viewer", api), 403, "totp_session_required")
    for role in ("operator", "viewer"):
        uid = env.user(role, totp=True)
        tok = env.token(uid, "session", verified=True)
        assert_problem(env.get("/t/totp", tok), 403, "forbidden")


@pg
def test_unverified_session_of_a_non_admin_on_totp_route(env: Env) -> None:
    uid = env.user("operator", totp=True)
    tok = env.token(uid, "session", verified=False)
    assert_problem(env.get("/t/totp-viewer", tok), 403, "totp_session_required")


# ------------------------------------------------------------ CHK-M2-162


@pg
def test_sink_gate_refusal_is_503_after_the_other_checks(env: Env) -> None:
    admin = env.user("admin", totp=True)
    verified = env.token(admin, "session", verified=True)
    api = env.token(admin, "api")
    env.gate.refuse = True
    assert_problem(env.get("/t/totp", verified), 503, "audit_sink_unavailable")
    assert_problem(
        env.get("/t/totp", api), 403, "totp_session_required"
    )  # basic reason first
    op = env.token(env.user("operator", totp=True), "session", verified=True)
    assert_problem(env.get("/t/totp", op), 403, "forbidden")
    for path in ("/t/viewer", "/t/admin", "/t/session"):  # not TOTP-session routes
        assert env.get(path, verified).status_code == 200
    env.gate.refuse = False
    assert env.get("/t/totp", verified).status_code == 200


# ------------------------------------------------------------ CHK-M2-163


@pg
def test_restricted_admin_session(env: Env) -> None:
    admin = env.user("admin", totp=False)
    restricted = env.token(admin, "session", verified=False)
    allowed = {"/t/session-restricted"}
    for path in ROUTES:
        resp = env.get(path, restricted)
        if path in allowed:
            assert resp.status_code == 200
        else:
            assert_problem(resp, 403, "totp_enrolment_required")


# ------------------------------------------------------------ CHK-M2-164


@pg
def test_admin_api_token_without_totp_is_refused_and_not_counted(env: Env) -> None:
    admin = env.user("admin", totp=False)
    api = env.token(admin, "api")
    for _ in range(25):
        assert_problem(env.get("/t/viewer", api), 403, "totp_enrolment_required")
    assert env.limits.failed_check_blocked("192.0.2.10") is False
    env.clock.at += timedelta(minutes=1)
    assert env.limits.drain() == []
    with env.conn() as c:
        c.execute(
            "UPDATE app_user SET totp_secret_enc = 'vault:v1:y' WHERE user_id = %s",
            (admin,),
        )
    assert env.get("/t/admin", api).status_code == 200


# ------------------------------------------------------- CHK-M2-165, -166


@pg
def test_failed_check_limit_and_valid_tokens_from_a_limited_ip(env: Env) -> None:
    good_s = env.token(env.user("viewer"))
    good_k = env.token(env.user("viewer"), "api")
    bad = "bsu_" + "B" * 43
    for _ in range(20):
        assert env.get("/t/viewer", good_s).status_code == 200  # never counted
        assert_problem(env.get("/t/viewer", bad), 401, "unauthorized")
    resp = env.get("/t/viewer", bad)
    assert_problem(resp, 429, "rate_limited")
    assert 1 <= int(resp.headers["retry-after"]) <= 60
    for _ in range(4):
        assert_problem(env.get("/t/viewer", bad), 429, "rate_limited")
    # every token is checked first: valid tokens from the limited IP pass
    assert env.get("/t/viewer", good_s).status_code == 200
    assert env.get("/t/viewer", good_k).status_code == 200
    env.clock.at += timedelta(minutes=1)
    (entry,) = env.limits.drain()
    assert entry.count == 25 and entry.ip == "192.0.2.10"


@pg
def test_failed_checks_are_per_ip(env: Env, migrated_db: PgServer) -> None:
    bad = "bsu_" + "C" * 43
    for _ in range(21):
        env.get("/t/viewer", bad)
    other = TestClient(env.client.app, client=("198.51.100.7", 1))
    assert_problem(
        other.get("/t/viewer", headers={"Authorization": f"Bearer {bad}"}),
        401,
        "unauthorized",
    )


@pg
def test_per_user_limit_over_all_tokens(env: Env) -> None:
    uid = env.user("viewer")
    a, b = env.token(uid), env.token(uid, "api")
    for i in range(600):
        assert env.get("/t/viewer", a if i % 2 else b).status_code == 200
    resp = env.get("/t/viewer", a)
    assert_problem(resp, 429, "rate_limited")
    assert "retry-after" in resp.headers
    other = env.token(env.user("viewer"))
    assert env.get("/t/viewer", other).status_code == 200


# ------------------------------------------------------------ CHK-M2-167


@pg
def test_no_token_or_hash_in_logs(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    tok = env.token(env.user("admin", totp=True), "session", verified=True)
    bad = "bsu_" + secrets.token_urlsafe(32)
    for path in ROUTES:
        env.get(path, tok)
        env.get(path, bad)
    secrets_ = [tok, tok[4:], token_hash(tok), bad, bad[4:], token_hash(bad)]
    assert sweep(secrets_, caplog.text) == []


# --------------------------------------- CHK-M2-159 route walk (no database)


def api_routes(routes: Any) -> Iterator[Any]:
    """Every endpoint route, including those inside included routers (this
    FastAPI wraps them in _IncludedRouter; the walk must descend into them)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            yield from (c for c in contexts() if hasattr(c, "dependant"))
        inner = getattr(route, "original_router", None)
        if inner is not None and not callable(contexts):
            yield from api_routes(inner.routes)


def markers(app: FastAPI) -> dict[tuple[str, str], AuthMarker | None]:
    out: dict[tuple[str, str], AuthMarker | None] = {}
    for route in api_routes(app.routes):
        found: AuthMarker | None = None
        stack = list(route.dependant.dependencies)
        while stack:
            dep = stack.pop()
            marker = getattr(dep.call, "bitscan_auth", None)
            if isinstance(marker, AuthMarker):
                found = marker
            stack.extend(dep.dependencies)
        for method in route.methods or set():
            out[(method, route.path)] = found
    return out


def test_route_walk_every_user_route_declares_a_requirement() -> None:
    walked = markers(create_app())
    user_routes = [k for k in walked if k[1].startswith("/api/v1/")]
    assert len(user_routes) >= 10  # the walk must see the real routes, not none
    for (method, path), marker in walked.items():
        if not path.startswith("/api/v1/"):
            continue  # health routes are outside the walk (#5)
        if (method, path) == ("POST", "/api/v1/auth/login"):
            assert marker is None
            continue
        assert marker is not None, f"{method} {path} has no auth dependency"
        if path == "/api/v1/users" or path.startswith("/api/v1/users/"):
            assert marker.check == "totp_session" and marker.minimum == "admin"
            assert marker.sink_gate is True


def test_route_walk_can_fail() -> None:
    app = create_app()

    @app.get("/api/v1/t/unprotected")
    def open_route() -> dict[str, str]:
        return {}

    @app.get("/api/v1/users/t-planted")
    def weak(p: Annotated[Principal, Depends(require_role("admin"))]) -> dict[str, str]:
        return {}

    walked = markers(app)
    assert walked[("GET", "/api/v1/t/unprotected")] is None
    marker = walked[("GET", "/api/v1/users/t-planted")]
    assert marker is not None and marker.check != "totp_session"


def marker_of(dep: object) -> AuthMarker:
    found = getattr(dep, "bitscan_auth", None)
    assert isinstance(found, AuthMarker)
    return found


def test_factories_mark_their_requirement() -> None:
    assert marker_of(require_totp_session()) == AuthMarker(
        "totp_session", "admin", False, True
    )
    assert marker_of(require_session()).check == "session"
    assert marker_of(require_role("operator")).minimum == "operator"
    with pytest.raises(ValueError):
        require_role("root")


def test_planted_hash_helper_is_sha256() -> None:
    assert token_hash("bsa_x") == hashlib.sha256(b"bsa_x").hexdigest()


def test_route_walk_sees_the_admin_totp_check_on_api_token_creation() -> None:
    """TASK-041 carry-over (lead rulings on TASK-043): the admin TOTP-session
    check for POST /api-tokens is a dependency marker, not route-body code."""
    walked = markers(create_app())
    create = walked[("POST", "/api/v1/api-tokens")]
    assert create is not None and create.check == "session"
    assert getattr(create, "admin_totp", False) is True
    for key in (
        ("GET", "/api/v1/api-tokens"),
        ("DELETE", "/api/v1/api-tokens/{token_id}"),
    ):
        marker = walked[key]
        assert marker is not None and getattr(marker, "admin_totp", False) is False
    users_routes = [k for k in walked if k[1].startswith("/api/v1/users")]
    assert len(users_routes) == 5  # GET/POST /users, GET/PATCH/DELETE /users/{id}
