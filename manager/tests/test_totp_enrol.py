"""TASK-039: TOTP enrolment and replacement through the API on PostgreSQL.

Checks CHK-M2-190 to CHK-M2-199 of tests/m2/test-plan.md (TP-M2-17). TS §6.2
L1085 (API tokens can never enrol or replace TOTP; replacing needs the current
password and a current code), L1089 (the restricted admin session can enrol;
after enrolling the session is re-issued as TOTP-verified), TS §8.4 L1290
("TOTP enrolled or replaced" alert), REQ-049, REQ-043 (1), #49 (b) (two calls,
pending seed in memory only, bound to the session, 10 min), #53 (b), #58.
"""

import base64
import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth import totp
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.auth.vault import VaultUnavailable
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import sweep
from .conftest import PgServer

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
PW = "enrol pass " + "phrase!"
HASH = hash_password(PW)
ENROL = "/api/v1/auth/totp/enrol"
LOGIN = "/api/v1/auth/login"


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


class Gate:
    def refusing(self) -> bool:
        return False

    def wake(self) -> None:
        return None


class Cipher:
    """'enc:' + XOR-masked hex, so the ciphertext never shows the seed."""

    MASK = bytes(range(101, 141))

    def __init__(self) -> None:
        self.down = False
        self.encrypted: list[bytes] = []

    def encrypt(self, seed: bytes) -> str:
        if self.down:
            raise VaultUnavailable("vault unreachable: ConnectError")
        self.encrypted.append(seed)
        return "enc:" + bytes(b ^ self.MASK[i] for i, b in enumerate(seed)).hex()

    def decrypt(self, ciphertext: str) -> bytes:
        if self.down:
            raise VaultUnavailable("vault unreachable: ConnectError")
        raw = bytes.fromhex(ciphertext.removeprefix("enc:"))
        return bytes(b ^ self.MASK[i] for i, b in enumerate(raw))


@dataclass
class Env:
    server: PgServer
    clock: Clock
    cipher: Cipher
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str = "admin", seed: bytes | None = None) -> tuple[str, int]:
        name = f"e-{secrets.token_hex(5)}"
        enc = None if seed is None else self.cipher.encrypt(seed)
        self.cipher.encrypted.clear()
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " created_at) VALUES (%s, %s, %s::user_role, %s, %s) RETURNING user_id",
                (name, HASH, role, enc, T0),
            ).fetchone()
        assert row is not None
        return name, int(row[0])

    def session(
        self, uid: int, verified: bool = False, expires: timedelta = timedelta(hours=24)
    ) -> str:
        tok = new_token(TokenKind.SESSION)
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, 'session', %s, %s, %s, %s)",
                (
                    uid,
                    token_hash(tok),
                    verified,
                    self.clock.at + expires,
                    self.clock.at,
                ),
            )
        return tok

    def api(self, uid: int) -> str:
        tok = new_token(TokenKind.API)
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, expires_at,"
                " created_at) VALUES (%s, 'api', %s, %s, %s)",
                (
                    uid,
                    token_hash(tok),
                    self.clock.at + timedelta(days=90),
                    self.clock.at,
                ),
            )
        return tok

    def enrol(self, token: str, body: dict[str, Any]) -> Any:
        return self.client.post(
            ENROL, json=body, headers={"Authorization": f"Bearer {token}"}
        )

    def stored(self, uid: int) -> tuple[str | None, int | None]:
        with self.conn() as c:
            row = c.execute(
                "SELECT totp_secret_enc, totp_last_step FROM app_user"
                " WHERE user_id = %s",
                (uid,),
            ).fetchone()
        assert row is not None
        return row[0], row[1]

    def alerts(self, uid: int) -> list[tuple[str, dict[str, Any]]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT action, detail FROM audit_log WHERE target = %s"
                " AND action LIKE 'auth.totp%%' ORDER BY audit_id",
                (f"user:{uid}",),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock, cipher = Clock(), Cipher()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=cipher,
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.5.0.1", 1)) as client:
        yield Env(migrated_db, clock, cipher, client)
    db.close()


def seed_of(start_body: dict[str, Any]) -> bytes:
    secret = start_body["secret"]
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code(seed: bytes, at: datetime, delta: int = 0) -> str:
    return totp.code_at(seed, totp.step_at(at) + delta)


def problem(resp: Any, status: int, type_: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == type_


# ------------------------------------------------------------ CHK-M2-190


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_api_tokens_cannot_enrol_or_replace(env: Env, role: str) -> None:
    seed = totp.new_seed()
    _, uid = env.user(role)
    _, uid2 = env.user(role, seed=seed)
    for u, body in (
        (uid, {}),
        (uid, {"totp_code": "123456"}),
        (uid2, {"current_password": PW, "current_code": code(seed, T0)}),
    ):
        resp = env.enrol(env.api(u), body)
        # an admin API token whose admin has no TOTP is refused even earlier,
        # with 403 totp_enrolment_required (#53 (i), lead answer (1))
        expected = (
            "totp_enrolment_required"
            if (role == "admin" and u == uid)
            else "session_required"
        )
        problem(resp, 403, expected)
    assert env.stored(uid) == (None, None)
    assert env.stored(uid2)[1] is None  # the step was not consumed either


# ------------------------------------------------------------ CHK-M2-191


def test_restricted_admin_enrols_and_gets_a_verified_session(env: Env) -> None:
    name, uid = env.user("admin")
    old = env.session(uid, verified=False, expires=timedelta(hours=20))
    start = env.enrol(old, {})
    assert start.status_code == 200
    body = start.json()
    assert set(body) == {"secret", "otpauth_uri"}
    seed = seed_of(body)
    assert len(seed) == 20
    parts = urlsplit(body["otpauth_uri"])
    assert parts.scheme == "otpauth" and name in parts.path
    assert parse_qs(parts.query)["secret"] == [body["secret"]]
    assert env.stored(uid) == (None, None)  # nothing stored before confirmation
    done = env.enrol(old, {"totp_code": code(seed, env.clock.at)})
    assert done.status_code == 200
    out = done.json()
    assert out["totp_verified"] is True and out["totp_enrolled"] is True
    new = out["token"]
    assert new.startswith("bsu_") and new != old
    # the re-issued session keeps the old 24 h maximum (20 h here), not a fresh one
    assert datetime.fromisoformat(out["expires_at"]) == T0 + timedelta(hours=20)
    with env.conn() as c:
        row = c.execute(
            "SELECT totp_verified, expires_at FROM user_token WHERE token_hash = %s",
            (token_hash(new),),
        ).fetchone()
    assert row == (True, T0 + timedelta(hours=20))
    logout = "/api/v1/auth/logout"
    old_resp = env.client.post(logout, headers={"Authorization": f"Bearer {old}"})
    assert old_resp.status_code == 401
    assert (
        env.client.post(logout, headers={"Authorization": f"Bearer {new}"}).status_code
        == 204
    )


def test_new_session_passes_a_totp_session_route(env: Env) -> None:
    """REQ-049 (2): the re-issued session can call TOTP-session routes."""
    from typing import Annotated

    from fastapi import Depends

    from bitscan_manager.auth.dependencies import require_totp_session
    from bitscan_manager.auth.principal import Principal

    app = env.client.app
    dep = require_totp_session()

    @app.get("/api/v1/t/totp-only")  # type: ignore[attr-defined, untyped-decorator]
    def only(p: Annotated[Principal, Depends(dep)]) -> dict[str, int]:
        return {"user_id": p.user_id}

    _, uid = env.user("admin")
    old = env.session(uid)
    hdr = {"Authorization": f"Bearer {old}"}
    problem(
        env.client.get("/api/v1/t/totp-only", headers=hdr),
        403,
        "totp_enrolment_required",
    )
    seed = seed_of(env.enrol(old, {}).json())
    new = env.enrol(old, {"totp_code": code(seed, env.clock.at)}).json()["token"]
    resp = env.client.get(
        "/api/v1/t/totp-only", headers={"Authorization": f"Bearer {new}"}
    )
    assert resp.status_code == 200


# ------------------------------------------------------------ CHK-M2-192


def test_replacement_needs_password_and_a_fresh_code(env: Env) -> None:
    seed = totp.new_seed()
    name, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    before = env.stored(uid)
    good = code(seed, env.clock.at)
    cases = [
        {},
        {"current_password": PW},
        {"current_code": good},
        {"current_password": "not the " + "password", "current_code": good},
        {
            "current_password": PW,
            "current_code": "000000" if good != "000000" else "111111",
        },
    ]
    for body in cases:
        resp = env.enrol(sess, body)
        assert resp.status_code == 403, (body, resp.text)
        assert env.stored(uid) == before
        # failures count now (ruling (c)): wait out any back-off they started
        env.clock.at = max(env.clock.at, failures(env, uid)[1] or env.clock.at)
    good = code(seed, env.clock.at)
    # a used code is refused: first use it at sign-in, then try it here
    sign_in = env.client.post(
        LOGIN, json={"username": name, "password": PW, "totp_code": good}
    )
    assert sign_in.status_code == 200
    problem(
        env.enrol(sess, {"current_password": PW, "current_code": good}),
        403,
        "forbidden",
    )
    assert env.stored(uid)[0] == before[0]
    # the old seed still signs in at the next step, after the back-off
    env.clock.at += timedelta(seconds=30)
    env.clock.at = max(env.clock.at, failures(env, uid)[1] or env.clock.at)
    again = env.client.post(
        LOGIN,
        json={"username": name, "password": PW, "totp_code": code(seed, env.clock.at)},
    )
    assert again.status_code == 200


def test_replacement_code_is_consumed(env: Env) -> None:
    """The code given to start a replacement cannot be replayed at sign-in."""
    seed = totp.new_seed()
    name, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    good = code(seed, env.clock.at)
    assert (
        env.enrol(sess, {"current_password": PW, "current_code": good}).status_code
        == 200
    )
    replay = env.client.post(
        LOGIN, json={"username": name, "password": PW, "totp_code": good}
    )
    assert replay.status_code == 401


# ------------------------------------------------------------ CHK-M2-193


def test_wrong_confirmation_keeps_the_old_seed_and_discards_the_pending(
    env: Env,
) -> None:
    seed = totp.new_seed()
    name, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    start = env.enrol(
        sess, {"current_password": PW, "current_code": code(seed, env.clock.at)}
    )
    new_seed = seed_of(start.json())
    before = env.stored(uid)
    wrong = code(new_seed, env.clock.at, delta=5)
    problem(env.enrol(sess, {"totp_code": wrong}), 403, "forbidden")
    assert env.stored(uid) == before
    # the pending seed is gone: even the right code for it is refused now
    problem(
        env.enrol(sess, {"totp_code": code(new_seed, env.clock.at)}), 409, "conflict"
    )
    env.clock.at += timedelta(seconds=30)
    ok = env.client.post(
        LOGIN,
        json={"username": name, "password": PW, "totp_code": code(seed, env.clock.at)},
    )
    assert ok.status_code == 200


def test_confirm_without_start_is_409(env: Env) -> None:
    _, uid = env.user("viewer")
    problem(env.enrol(env.session(uid), {"totp_code": "123456"}), 409, "conflict")


def test_mixed_body_is_400(env: Env) -> None:
    _, uid = env.user("viewer")
    resp = env.enrol(env.session(uid), {"totp_code": "123456", "current_password": PW})
    problem(resp, 400, "invalid_request")


# ------------------------------------------------------- CHK-M2-194, -195


def test_one_alert_per_enrolment_and_per_replacement(env: Env) -> None:
    _, uid = env.user("operator")
    s1 = env.session(uid)
    seed = seed_of(env.enrol(s1, {}).json())
    env.enrol(s1, {"totp_code": "000000"})  # a failed attempt alerts nothing
    seed = seed_of(env.enrol(s1, {}).json())
    s2 = env.enrol(s1, {"totp_code": code(seed, env.clock.at)}).json()["token"]
    env.clock.at += timedelta(seconds=30)
    start = env.enrol(
        s2, {"current_password": PW, "current_code": code(seed, env.clock.at)}
    )
    seed2 = seed_of(start.json())
    env.enrol(s2, {"totp_code": code(seed2, env.clock.at)})
    entries = env.alerts(uid)
    assert [a for a, _ in entries] == ["auth.totp_enrol", "auth.totp_replace"]
    kinds = [d["alert_kind"] for _, d in entries]
    assert kinds == ["totp_enrolled", "totp_replaced"]
    assert all(d["alert"] is True for _, d in entries)


def test_stored_secret_is_only_vault_ciphertext(env: Env) -> None:
    _, uid = env.user("admin")
    sess = env.session(uid)
    start = env.enrol(sess, {})
    seed = seed_of(start.json())
    assert env.stored(uid) == (None, None)
    env.enrol(sess, {"totp_code": code(seed, env.clock.at)})
    enc, step = env.stored(uid)
    assert enc is not None and enc.startswith("enc:")
    assert env.cipher.encrypted == [seed]  # the vault got exactly this seed
    forms = [
        seed.hex(),
        seed.hex().upper(),
        start.json()["secret"],
        base64.b64encode(seed).decode(),
        base64.b32encode(seed).decode(),
    ]
    for f in forms:
        assert f not in enc
    assert step == totp.step_at(env.clock.at)


# ------------------------------------------------------------ CHK-M2-196


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_viewers_and_operators_can_enrol(env: Env, role: str) -> None:
    _, uid = env.user(role)
    sess = env.session(uid)
    seed = seed_of(env.enrol(sess, {}).json())
    resp = env.enrol(sess, {"totp_code": code(seed, env.clock.at)})
    assert resp.status_code == 200 and resp.json()["role"] == role


def test_replacement_ends_other_sessions_and_keeps_the_reissued_one(env: Env) -> None:
    seed = totp.new_seed()
    _, uid = env.user("operator", seed=seed)
    a, b = env.session(uid, verified=True), env.session(uid, verified=True)
    api = env.api(uid)
    start = env.enrol(
        a, {"current_password": PW, "current_code": code(seed, env.clock.at)}
    )
    new = env.enrol(a, {"totp_code": code(seed_of(start.json()), env.clock.at)}).json()[
        "token"
    ]
    logout = "/api/v1/auth/logout"
    assert (
        env.client.post(logout, headers={"Authorization": f"Bearer {b}"}).status_code
        == 401
    )
    assert (
        env.client.post(logout, headers={"Authorization": f"Bearer {a}"}).status_code
        == 401
    )
    with env.conn() as c:
        live = c.execute(
            "SELECT revoked_at FROM user_token WHERE token_hash = %s",
            (token_hash(api),),
        ).fetchone()
    assert live == (None,)  # API tokens are untouched
    assert (
        env.client.post(logout, headers={"Authorization": f"Bearer {new}"}).status_code
        == 204
    )


# ------------------------------------------------------------ CHK-M2-197


def test_pending_seed_expires_after_10_minutes(env: Env) -> None:
    _, uid = env.user("viewer")
    sess = env.session(uid)
    seed = seed_of(env.enrol(sess, {}).json())
    env.clock.at += timedelta(minutes=9, seconds=59)
    ok = env.enrol(sess, {"totp_code": code(seed, env.clock.at)})
    assert ok.status_code == 200
    _, uid2 = env.user("viewer")
    sess2 = env.session(uid2)
    seed2 = seed_of(env.enrol(sess2, {}).json())
    env.clock.at += timedelta(minutes=10)
    problem(env.enrol(sess2, {"totp_code": code(seed2, env.clock.at)}), 409, "conflict")


def test_pending_seed_is_bound_to_the_session(env: Env) -> None:
    _, uid = env.user("viewer")
    a, b = env.session(uid), env.session(uid)
    seed = seed_of(env.enrol(a, {}).json())
    problem(env.enrol(b, {"totp_code": code(seed, env.clock.at)}), 409, "conflict")
    assert env.enrol(a, {"totp_code": code(seed, env.clock.at)}).status_code == 200


def test_logout_drops_the_pending_seed(env: Env) -> None:
    _, uid = env.user("viewer")
    a = env.session(uid)
    env.enrol(a, {})
    app = env.client.app
    store = app.state.totp_pending  # type: ignore[attr-defined]
    held_before = len(store._by_token)  # noqa: SLF001
    env.client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {a}"})
    assert len(store._by_token) == held_before - 1  # noqa: SLF001


# ------------------------------------------------------------ CHK-M2-198


def test_vault_down_during_confirm_is_503_and_stores_nothing(env: Env) -> None:
    _, uid = env.user("admin")
    sess = env.session(uid)
    seed = seed_of(env.enrol(sess, {}).json())
    env.cipher.down = True
    resp = env.enrol(sess, {"totp_code": code(seed, env.clock.at)})
    problem(resp, 503, "about:blank")
    assert env.stored(uid) == (None, None)
    env.cipher.down = False
    env.clock.at += timedelta(seconds=30)
    done = env.enrol(sess, {"totp_code": code(seed, env.clock.at)})
    assert done.status_code == 200  # the pending seed was kept for a retry


def test_vault_down_during_a_replacement_start_is_503(env: Env) -> None:
    seed = totp.new_seed()
    _, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    env.cipher.down = True
    resp = env.enrol(
        sess, {"current_password": PW, "current_code": code(seed, env.clock.at)}
    )
    problem(resp, 503, "about:blank")


# ------------------------------------------------------------ CHK-M2-199


def test_no_seed_code_or_password_in_logs_audit_or_errors(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    seed0 = totp.new_seed()
    _, uid = env.user("admin", seed=seed0)
    sess = env.session(uid, verified=True)
    c0 = code(seed0, env.clock.at)
    start = env.enrol(sess, {"current_password": PW, "current_code": c0})
    body = start.json()
    seed = seed_of(body)
    bad = env.enrol(sess, {"totp_code": code(seed, env.clock.at, delta=7)})
    with env.conn() as c:
        details = [
            json.dumps(r[0])
            for r in c.execute(
                "SELECT detail FROM audit_log WHERE target = %s", (f"user:{uid}",)
            ).fetchall()
        ]
    secrets_ = [
        PW,
        body["secret"],
        body["otpauth_uri"],
        seed.hex(),
        c0,
        base64.b64encode(seed).decode(),
    ]
    assert sweep(secrets_, caplog.text, bad.text, *details) == []


# ----------------- CHK-M2-192a: failed replacement attempts count (ruling (c))


def failures(env: Env, uid: int) -> tuple[int, datetime | None]:
    with env.conn() as c:
        row = c.execute(
            "SELECT failed_logins, next_login_at FROM app_user WHERE user_id = %s",
            (uid,),
        ).fetchone()
    assert row is not None
    return int(row[0]), row[1]


def test_replacement_failures_count_as_failed_sign_ins(env: Env) -> None:
    seed = totp.new_seed()
    name, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    used = code(seed, env.clock.at)
    ok = env.client.post(
        LOGIN, json={"username": name, "password": PW, "totp_code": used}
    )
    assert ok.status_code == 200
    assert failures(env, uid) == (0, None)
    env.clock.at += timedelta(seconds=30)
    fresh = code(seed, env.clock.at)
    attempts = [
        {"current_password": PW, "current_code": used},  # reused code
        {"current_password": "not the " + "password", "current_code": fresh},
        {"current_password": PW, "current_code": code(seed, env.clock.at, delta=9)},
    ]
    for n, body in enumerate(attempts, start=1):
        failed_at = env.clock.at
        problem(env.enrol(sess, body), 403, "forbidden")
        count, next_at = failures(env, uid)
        assert count == n, body
        assert next_at == failed_at + timedelta(seconds=2 ** (n - 1)), body
        env.clock.at = next_at  # out of the back-off for the next attempt


def test_replacement_during_backoff_runs_one_dummy_and_counts_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bitscan_manager.auth import passwords

    seed = totp.new_seed()
    _, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    until = env.clock.at + timedelta(seconds=60)
    with env.conn() as c:
        c.execute(
            "UPDATE app_user SET failed_logins = 3, next_login_at = %s"
            " WHERE user_id = %s",
            (until, uid),
        )
    before_secret = env.stored(uid)
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
    resp = env.enrol(
        sess, {"current_password": PW, "current_code": code(seed, env.clock.at)}
    )
    monkeypatch.undo()
    problem(resp, 403, "forbidden")
    assert runs["n"] == 1  # one dummy Argon2id run, the password is not checked
    # the dummy check, not the user's password: the stored hash is never verified
    assert against == [passwords._dummy_hash()]  # noqa: SLF001
    assert failures(env, uid) == (3, until)  # not counted, back-off unchanged
    assert env.stored(uid) == before_secret  # the code was not consumed


def test_five_replacement_failures_raise_one_login_failures_alert(env: Env) -> None:
    seed = totp.new_seed()
    _, uid = env.user("admin", seed=seed)
    sess = env.session(uid, verified=True)
    for _ in range(5):
        problem(
            env.enrol(
                sess,
                {
                    "current_password": "wrong " + "password!",
                    "current_code": code(seed, env.clock.at),
                },
            ),
            403,
            "forbidden",
        )
        env.clock.at = failures(env, uid)[1] or env.clock.at
    with env.conn() as c:
        rows = c.execute(
            "SELECT detail FROM audit_log WHERE action = 'auth.login_failures'"
            " AND target = %s",
            (f"user:{uid}",),
        ).fetchall()
    assert [r[0]["failed_logins"] for r in rows] == [5]
    assert rows[0][0]["alert"] is True and rows[0][0]["alert_kind"] == "login_failures"
