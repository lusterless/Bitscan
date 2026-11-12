"""The web session cookie, its CSRF check and the own-session routes on
PostgreSQL (TS §8.3 Security).

Expected values: TS §6.2 (sign-in and the TOTP confirm set
`__Host-bitscan_session`; logout, a password change and ending the current
session clear it; user routes read it only without an Authorization header;
agent routes never; GET /auth/session, GET /auth/sessions and
DELETE /auth/sessions/{id} are session only and about the caller's own
sessions; a restricted admin session may call only /auth/totp/enrol and
/auth/logout), TS §6.3 (`X-Bitscan-Request: 1`, a present Origin must be the
manager's own, else 403 csrf_required), TS §8.1 (the token never leaves in
logs), owner decision 2026-11-12 (work/plans/session-cookie-proposal.md §2).

The TestClient talks to http://testserver, so the manager's own origin here
is "http://testserver". The client does not keep a Secure cookie over http,
so tests send the Cookie header themselves.
"""

import logging
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import sweep
from .conftest import PgServer
from .test_totp_enrol import T0, Cipher, Clock, Gate

pytestmark = pytest.mark.pg

COOKIE = "__Host-bitscan_session"
CSRF = {"X-Bitscan-Request": "1"}
OWN_ORIGIN = "http://testserver"
PW = "cookie pass " + "phrase!"
HASH = hash_password(PW)
SESSION = "/api/v1/auth/session"
SESSIONS = "/api/v1/auth/sessions"
ITEM_KEYS = {
    "session_id",
    "created_at",
    "last_used_at",
    "expires_at",
    "totp_verified",
    "current",
}


@dataclass
class Env:
    server: PgServer
    clock: Clock
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str = "viewer", totp: bool = False) -> tuple[int, str]:
        name = f"c-{secrets.token_hex(5)}"
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " created_at) VALUES (%s, %s, %s::user_role, %s, %s)"
                " RETURNING user_id",
                (name, HASH, role, "enc:00" if totp else None, T0),
            ).fetchone()
        assert row is not None
        return int(row[0]), name

    def token(
        self,
        uid: int,
        kind: TokenKind = TokenKind.SESSION,
        *,
        verified: bool = False,
        created: Any = None,
        expires: Any = None,
        revoked: Any = None,
    ) -> tuple[int, str]:
        tok = new_token(kind)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, revoked_at, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING token_id",
                (
                    uid,
                    kind.value,
                    token_hash(tok),
                    verified and kind is TokenKind.SESSION,
                    expires or T0 + timedelta(hours=24),
                    revoked,
                    created or T0,
                ),
            ).fetchone()
        assert row is not None
        return int(row[0]), tok

    def revoked_at(self, token_id: int) -> Any:
        with self.conn() as c:
            row = c.execute(
                "SELECT revoked_at FROM user_token WHERE token_id = %s", (token_id,)
            ).fetchone()
        assert row is not None
        return row[0]

    def last_audit(self) -> tuple[str, str, Any]:
        with self.conn() as c:
            row = c.execute(
                "SELECT action, target, detail FROM audit_log"
                " ORDER BY audit_id DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        return row[0], row[1], row[2]

    def by_cookie(
        self,
        method: str,
        path: str,
        token: str,
        extra: dict[str, str] | None = None,
        **kw: Any,
    ) -> Any:
        headers = {"Cookie": f"{COOKIE}={token}", **CSRF, **(extra or {})}
        return self.client.request(method, path, headers=headers, **kw)

    def by_bearer(self, method: str, path: str, token: str, **kw: Any) -> Any:
        headers = {"Authorization": f"Bearer {token}"}
        return self.client.request(method, path, headers=headers, **kw)


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.4.0.1", 1)) as client:
        yield Env(migrated_db, clock, client)
    db.close()


def problem(resp: Any, status: int, type_: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.json()["type"] == type_


def set_cookies(resp: Any) -> list[str]:
    return list(resp.headers.get_list("set-cookie"))


def cleared(resp: Any) -> bool:
    return any(
        v.startswith(f"{COOKIE}=;") and "Max-Age=0" in v for v in set_cookies(resp)
    )


# ------------------------------------------------------------ sign-in, logout


def test_sign_in_sets_the_session_cookie_and_keeps_the_body(env: Env) -> None:
    _, name = env.user()
    resp = env.client.post(
        "/api/v1/auth/login", json={"username": name, "password": PW}
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    assert set_cookies(resp) == [
        f"{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict"
    ]
    assert env.by_cookie("GET", SESSION, token).status_code == 200


def test_a_failed_sign_in_sets_no_cookie(env: Env) -> None:
    _, name = env.user()
    resp = env.client.post(
        "/api/v1/auth/login", json={"username": name, "password": PW + "x"}
    )
    assert resp.status_code == 401
    assert set_cookies(resp) == []


def test_logout_by_cookie_ends_the_session_and_clears_the_cookie(env: Env) -> None:
    uid, _ = env.user()
    tid, tok = env.token(uid)
    resp = env.by_cookie("POST", "/api/v1/auth/logout", tok)
    assert resp.status_code == 204
    assert cleared(resp)
    assert env.revoked_at(tid) is not None
    later = env.by_cookie("GET", SESSION, tok)
    problem(later, 401, "unauthorized")
    assert cleared(later)


def test_a_password_change_clears_the_cookie(env: Env) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    body = {"current_password": PW, "new_password": "a brand new " + "phrase!"}
    resp = env.by_cookie("POST", "/api/v1/auth/password", tok, json=body)
    assert resp.status_code == 204
    assert cleared(resp)
    problem(env.by_cookie("GET", SESSION, tok), 401, "unauthorized")


# ------------------------------------------------------------ which token


def test_the_cookie_authenticates_a_user_route(env: Env) -> None:
    uid, _ = env.user("operator", totp=True)
    _, tok = env.token(uid, verified=True)
    resp = env.by_cookie("GET", SESSION, tok)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "role": "operator",
        "totp_enrolled": True,
        "totp_verified": True,
        "expires_at": body["expires_at"],
    }
    assert body["expires_at"].endswith("Z")
    assert set_cookies(resp) == []


def test_a_bearer_header_wins_over_the_cookie(env: Env) -> None:
    uid, _ = env.user()
    _, good = env.token(uid)
    resp = env.client.get(
        SESSION,
        headers={
            "Authorization": "Bearer bsu_" + "x" * 43,
            "Cookie": f"{COOKIE}={good}",
            **CSRF,
        },
    )
    problem(resp, 401, "unauthorized")
    assert set_cookies(resp) == []  # the cookie was not used, so not cleared


def test_a_bearer_needs_no_csrf_header(env: Env) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    assert env.by_bearer("GET", SESSION, tok).status_code == 200


def test_a_bad_cookie_is_401_and_cleared(env: Env) -> None:
    resp = env.by_cookie("GET", SESSION, "bsu_" + "y" * 43)
    problem(resp, 401, "unauthorized")
    assert cleared(resp)


def test_no_token_at_all_is_401_without_a_cookie_header(env: Env) -> None:
    resp = env.client.get(SESSION, headers=CSRF)
    problem(resp, 401, "unauthorized")
    assert set_cookies(resp) == []


def test_an_api_token_in_the_cookie_is_not_a_session(env: Env) -> None:
    uid, _ = env.user()
    _, api = env.token(uid, TokenKind.API, expires=T0 + timedelta(days=90))
    problem(env.by_cookie("GET", SESSION, api), 403, "session_required")


def test_agent_routes_never_read_the_cookie(env: Env) -> None:
    uid, _ = env.user("admin", totp=True)
    _, tok = env.token(uid, verified=True)
    resp = env.by_cookie("GET", f"/api/v1/agent/{uuid.uuid4()}/jobs", tok)
    assert resp.status_code == 401


# ------------------------------------------------------------ CSRF


def test_a_cookie_without_the_csrf_header_is_403(env: Env) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    resp = env.client.get(SESSION, headers={"Cookie": f"{COOKIE}={tok}"})
    problem(resp, 403, "csrf_required")


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "https://testserver", "null"]
)
def test_a_foreign_origin_is_403(env: Env, origin: str) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    resp = env.by_cookie("GET", SESSION, tok, {"Origin": origin})
    problem(resp, 403, "csrf_required")


def test_the_own_origin_is_accepted(env: Env) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    resp = env.by_cookie("GET", SESSION, tok, {"Origin": OWN_ORIGIN})
    assert resp.status_code == 200


def test_a_csrf_refusal_does_not_end_the_session(env: Env) -> None:
    uid, _ = env.user()
    tid, tok = env.token(uid)
    resp = env.client.post("/api/v1/auth/logout", headers={"Cookie": f"{COOKIE}={tok}"})
    problem(resp, 403, "csrf_required")
    assert env.revoked_at(tid) is None


# ------------------------------------------------------------ GET /auth/session


def test_a_restricted_admin_session_is_told_to_enrol(env: Env) -> None:
    uid, _ = env.user("admin")
    _, tok = env.token(uid)
    problem(env.by_cookie("GET", SESSION, tok), 403, "totp_enrolment_required")
    problem(env.by_cookie("GET", SESSIONS, tok), 403, "totp_enrolment_required")


def test_the_current_session_refuses_api_tokens(env: Env) -> None:
    uid, _ = env.user()
    _, api = env.token(uid, TokenKind.API, expires=T0 + timedelta(days=90))
    problem(env.by_bearer("GET", SESSION, api), 403, "session_required")
    problem(env.by_bearer("GET", SESSIONS, api), 403, "session_required")


# ------------------------------------------------------------ GET /auth/sessions


def test_only_the_callers_active_sessions_are_listed(env: Env) -> None:
    env.clock.at = T0 + timedelta(hours=1)
    uid, _ = env.user()
    other, _ = env.user()
    current, tok = env.token(uid, verified=False)
    second, _ = env.token(uid, created=T0 + timedelta(minutes=30))
    env.token(uid, revoked=T0)  # revoked
    env.token(uid, expires=T0 + timedelta(minutes=59))  # expired
    env.token(uid, created=T0 - timedelta(hours=8))  # idle 9 h
    env.token(uid, TokenKind.API, expires=T0 + timedelta(days=90))  # not a session
    env.token(other)  # another user's
    resp = env.by_cookie("GET", SESSIONS, tok)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["session_id"] for i in items] == [current, second]
    assert all(set(i) == ITEM_KEYS for i in items)
    assert [i["current"] for i in items] == [True, False]


def test_the_session_list_pages(env: Env) -> None:
    uid, _ = env.user()
    first, tok = env.token(uid)
    ids = [first] + [env.token(uid)[0] for _ in range(2)]
    seen: list[int] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        body = env.by_cookie("GET", SESSIONS, tok, params=params).json()
        seen += [i["session_id"] for i in body["items"]]
        cursor = body.get("next_cursor")
        if not cursor:
            break
    assert seen == ids


# ------------------------------------------------------------ DELETE


def test_ending_another_own_session(env: Env) -> None:
    uid, _ = env.user()
    _, tok = env.token(uid)
    other_id, other_tok = env.token(uid)
    resp = env.by_cookie("DELETE", f"{SESSIONS}/{other_id}", tok)
    assert resp.status_code == 204
    assert set_cookies(resp) == []
    assert env.revoked_at(other_id) is not None
    action, target, detail = env.last_audit()
    assert (action, target) == ("auth.session_revoke", f"user:{uid}")
    assert detail["token_id"] == other_id
    problem(env.by_bearer("GET", SESSION, other_tok), 401, "unauthorized")
    assert env.by_cookie("GET", SESSION, tok).status_code == 200


def test_ending_the_current_session_clears_the_cookie(env: Env) -> None:
    uid, _ = env.user()
    tid, tok = env.token(uid)
    resp = env.by_cookie("DELETE", f"{SESSIONS}/{tid}", tok)
    assert resp.status_code == 204
    assert cleared(resp)
    problem(env.by_cookie("GET", SESSION, tok), 401, "unauthorized")


def test_others_tokens_and_api_tokens_are_404(env: Env) -> None:
    uid, _ = env.user()
    other, _ = env.user()
    _, tok = env.token(uid)
    theirs, _ = env.token(other)
    api, _ = env.token(uid, TokenKind.API, expires=T0 + timedelta(days=90))
    gone, _ = env.token(uid, revoked=T0)
    for target in (theirs, api, gone, 999_999_999):
        resp = env.by_cookie("DELETE", f"{SESSIONS}/{target}", tok)
        problem(resp, 404, "not_found")
    assert env.revoked_at(theirs) is None
    assert env.revoked_at(api) is None


def test_ending_a_session_refuses_api_tokens(env: Env) -> None:
    uid, _ = env.user()
    sid, _ = env.token(uid)
    _, api = env.token(uid, TokenKind.API, expires=T0 + timedelta(days=90))
    problem(env.by_bearer("DELETE", f"{SESSIONS}/{sid}", api), 403, "session_required")
    assert env.revoked_at(sid) is None


# ------------------------------------------------------------ no leaks


def test_the_cookie_token_never_reaches_the_logs(
    env: Env, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    uid, _ = env.user()
    tid, tok = env.token(uid)
    bad = "bsu_" + "z" * 43
    env.by_cookie("GET", SESSION, tok)
    env.by_cookie("GET", SESSIONS, tok)
    env.client.get(SESSION, headers={"Cookie": f"{COOKIE}={tok}"})  # csrf refusal
    env.by_cookie("GET", SESSION, bad)
    env.by_cookie("DELETE", f"{SESSIONS}/{tid}", tok)
    out, err = capfd.readouterr()
    canaries = [tok, tok[4:], bad, token_hash(tok)]
    assert sweep(canaries, caplog.text, out, err) == []
    action, _, detail = env.last_audit()
    assert action == "auth.session_revoke"
    assert sweep(canaries, str(detail)) == []
