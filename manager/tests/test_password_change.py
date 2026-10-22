"""TASK-040: change your own password, through the API on PostgreSQL.

Checks CHK-M2-200 to CHK-M2-205 of tests/m2/test-plan.md (TP-M2-18). TS §6.2
L1086 (a password change ends the user's sessions), L1087 (Argon2id, at least
12 characters), L1097 (session only, current password required), REQ-050,
REQ-041, #53 (a) (all sessions end, the presenting one too), #56 (b) (at most
1,024 characters), decisions 2026-10-22 "Rulings on TASK-039" (c) (a wrong
current password counts as a failed sign-in; nothing is checked or counted
during back-off).
"""

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth import passwords
from bitscan_manager.auth.passwords import hash_password, verify_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import new_canary, sweep
from .conftest import PgServer
from .test_totp_enrol import Cipher, Clock, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
OLD = "old pass " + "phrase 1"
NEW = "new pass " + "phrase 2"
OLD_HASH = hash_password(OLD)
ROUTE = "/api/v1/auth/password"
LOGIN = "/api/v1/auth/login"


@dataclass
class Env:
    server: PgServer
    clock: Clock
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(
        self, role: str = "operator", totp_enc: str | None = None
    ) -> tuple[str, int]:
        name = f"p-{secrets.token_hex(5)}"
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " created_at) VALUES (%s, %s, %s::user_role, %s, %s) RETURNING user_id",
                (name, OLD_HASH, role, totp_enc, T0),
            ).fetchone()
        assert row is not None
        return name, int(row[0])

    def token(self, uid: int, kind: str = "session", verified: bool = False) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (uid, kind, token_hash(tok), verified, T0 + timedelta(days=30), T0),
            )
        return tok

    def change(self, token: str, current: Any, new: Any) -> Any:
        return self.client.post(
            ROUTE,
            json={"current_password": current, "new_password": new},
            headers={"Authorization": f"Bearer {token}"},
        )

    def row(self, uid: int) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM app_user WHERE user_id = %s", (uid,))
            cols = [d.name for d in cur.description or []]
            values = cur.fetchone()
        assert values is not None
        return dict(zip(cols, values, strict=True))

    def live(self, tok: str) -> bool:
        with self.conn() as c:
            row = c.execute(
                "SELECT revoked_at FROM user_token WHERE token_hash = %s",
                (token_hash(tok),),
            ).fetchone()
        assert row is not None
        return row[0] is None

    def entries(self, uid: int) -> list[tuple[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT action, detail FROM audit_log WHERE target = %s"
                " ORDER BY audit_id",
                (f"user:{uid}",),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]


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


# ------------------------------------------------------------ CHK-M2-200


def test_api_token_is_refused_and_nothing_changes(env: Env) -> None:
    _, uid = env.user()
    problem(env.change(env.token(uid, "api"), OLD, NEW), 403, "session_required")
    assert env.row(uid)["password_hash"] == OLD_HASH


# ------------------------------------------------------------ CHK-M2-201


def test_wrong_current_password_counts_and_changes_nothing(env: Env) -> None:
    _, uid = env.user()
    sess, other = env.token(uid), env.token(uid)
    problem(env.change(sess, "not the old " + "password", NEW), 403, "forbidden")
    row = env.row(uid)
    assert row["password_hash"] == OLD_HASH
    assert row["failed_logins"] == 1  # ruling (c): counted as a failed sign-in
    assert row["next_login_at"] == T0 + timedelta(seconds=1)
    assert env.live(sess) and env.live(other)
    assert [a for a, _ in env.entries(uid)] == []


def test_during_backoff_one_dummy_check_and_nothing_counted(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, uid = env.user()
    sess = env.token(uid)
    until = T0 + timedelta(seconds=40)
    with env.conn() as c:
        c.execute(
            "UPDATE app_user SET failed_logins = 2, next_login_at = %s"
            " WHERE user_id = %s",
            (until, uid),
        )
    passwords._dummy_hash.cache_clear()  # noqa: SLF001
    passwords._dummy_hash()  # noqa: SLF001
    runs = {"n": 0}
    against: list[str] = []
    hasher = passwords._HASHER  # noqa: SLF001

    class Counting:
        def hash(self, pw: bytes) -> str:
            return str(hasher.hash(pw))

        def verify(self, stored: str, pw: bytes) -> bool:
            runs["n"] += 1
            against.append(stored)
            return bool(hasher.verify(stored, pw))

    monkeypatch.setattr(passwords, "_HASHER", Counting())
    resp = env.change(sess, OLD, NEW)  # the correct current password
    monkeypatch.undo()
    problem(resp, 403, "forbidden")
    assert runs["n"] == 1
    # the dummy check, not the user's password: the stored hash is never verified
    assert against == [passwords._dummy_hash()]  # noqa: SLF001
    row = env.row(uid)
    assert (row["failed_logins"], row["next_login_at"]) == (2, until)
    assert row["password_hash"] == OLD_HASH


def test_five_wrong_current_passwords_raise_one_alert(env: Env) -> None:
    _, uid = env.user()
    sess = env.token(uid)
    for _ in range(5):
        problem(env.change(sess, "wrong " + "password!", NEW), 403, "forbidden")
        env.clock.at = env.row(uid)["next_login_at"]
    alerts = [d for a, d in env.entries(uid) if a == "auth.login_failures"]
    assert [d["failed_logins"] for d in alerts] == [5]


# ------------------------------------------------------------ CHK-M2-202


@pytest.mark.parametrize(
    ("new", "ok"),
    [
        ("a" * 11, False),
        ("a" * 12, True),
        ("😀" * 11, False),
        ("😀" * 12, True),
        ("x" * 1024, True),
        ("x" * 1025, False),
    ],
)
def test_new_password_length_rules(env: Env, new: str, ok: bool) -> None:
    _, uid = env.user()
    sess = env.token(uid)
    resp = env.change(sess, OLD, new)
    if ok:
        assert resp.status_code == 204, resp.text
        assert verify_password(env.row(uid)["password_hash"], new)
    else:
        problem(resp, 400, "invalid_request")
        assert env.row(uid)["password_hash"] == OLD_HASH
        assert new not in resp.text
        assert env.row(uid)["failed_logins"] == 0  # the rule is checked first


def test_bad_new_password_is_checked_before_the_current_one(env: Env) -> None:
    _, uid = env.user()
    resp = env.change(env.token(uid), "wrong " + "password!", "short")
    problem(resp, 400, "invalid_request")
    assert env.row(uid)["failed_logins"] == 0


# ------------------------------------------------------------ CHK-M2-203


def test_success_ends_every_session_and_keeps_api_tokens(env: Env) -> None:
    name, uid = env.user()
    sess, other = env.token(uid), env.token(uid)
    api = env.token(uid, "api")
    other_user = env.token(env.user()[1])
    resp = env.change(sess, OLD, NEW)
    assert resp.status_code == 204 and resp.content == b""
    row = env.row(uid)
    assert row["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(row["password_hash"], NEW)
    assert not verify_password(row["password_hash"], OLD)
    assert not env.live(sess) and not env.live(other)  # #53 (a)
    assert env.live(api) and env.live(other_user)
    logout = "/api/v1/auth/logout"
    assert (
        env.client.post(logout, headers={"Authorization": f"Bearer {sess}"}).status_code
        == 401
    )
    old_login = env.client.post(LOGIN, json={"username": name, "password": OLD})
    assert old_login.status_code == 401
    env.clock.at = env.row(uid)["next_login_at"] or env.clock.at
    new_login = env.client.post(LOGIN, json={"username": name, "password": NEW})
    assert new_login.status_code == 200


# ------------------------------------------------------------ CHK-M2-204


def test_one_audit_entry_without_any_password(env: Env) -> None:
    canary = new_canary("newpw") + "-long-enough"
    _, uid = env.user()
    assert env.change(env.token(uid), OLD, canary).status_code == 204
    entries = env.entries(uid)
    assert [a for a, _ in entries] == ["auth.password_change"]
    new_hash = env.row(uid)["password_hash"]
    assert sweep([canary, OLD, new_hash, OLD_HASH], repr(entries)) == []


# ------------------------------------------------------------ CHK-M2-205


def test_restricted_admin_session_is_refused(env: Env) -> None:
    _, uid = env.user("admin")
    sess = env.token(uid, verified=False)
    problem(env.change(sess, OLD, NEW), 403, "totp_enrolment_required")
    assert env.row(uid)["password_hash"] == OLD_HASH


def test_no_password_or_hash_in_logs_or_bodies(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    canary = new_canary("pw") + "-long-enough"
    _, uid = env.user()
    sess = env.token(uid)
    bodies = [env.change(sess, canary, NEW).text]
    env.clock.at = env.row(uid)["next_login_at"]
    bodies.append(env.change(sess, OLD, canary).text)
    assert (
        sweep(
            [canary, OLD, OLD_HASH, env.row(uid)["password_hash"]], caplog.text, *bodies
        )
        == []
    )


def test_hashing_the_new_password_takes_the_verify_gate(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead rulings on TASK-040: Argon2id hashing of the new password runs
    under the 4-slot gate (it costs the same memory as a verification)."""
    from bitscan_manager.auth import login

    inside_gate: list[bool] = []
    real_hash = passwords.hash_password
    depth = {"n": 0}

    class Gate:
        def __enter__(self) -> None:
            depth["n"] += 1

        def __exit__(self, *exc: object) -> None:
            depth["n"] -= 1

    def spy(pw: str) -> str:
        inside_gate.append(depth["n"] > 0)
        return real_hash(pw)

    monkeypatch.setattr(login, "VERIFY_GATE", Gate())
    monkeypatch.setattr(passwords, "hash_password", spy)
    _, uid = env.user()
    assert env.change(env.token(uid), OLD, NEW).status_code == 204
    assert inside_gate == [True]
