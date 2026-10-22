"""TASK-038 through the API on PostgreSQL: sign-in and sign-out.

Checks CHK-M2-170, -172 to -181, -183, -184, -187 of tests/m2/test-plan.md
(TP-M2-16). TS §6.2 L1080 (24 h max, 8 h idle; logout), L1086 (same response
whether or not the user exists), L1087 (Argon2id; each TOTP code once),
L1088 (back-off 1 s doubling to 15 min, admins slowed never locked), L1089
(restricted admin session), TS §6.3 L1136 (10 sign-ins per minute per IP),
#47 (a), #48, #49 (c), #50, #54 (a), #55, #58, decisions 2026-10-22
(DatabaseUnavailable answers 503 about:blank, never 500 or 401).
"""

import base64
import json
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth import totp
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import token_hash
from bitscan_manager.auth.vault import VaultUnavailable
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import new_canary, sweep
from .conftest import PgServer
from .test_db_pool_pg import PausableProxy

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
PW = "correct horse " + "battery"
WRONG = "wrong " + "password!!"
HASH = hash_password(PW)
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"


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
    """Stands in for the vault: 'enc:<hex>' ciphertext; can be switched off."""

    def __init__(self) -> None:
        self.down = False

    def encrypt(self, seed: bytes) -> str:
        return "enc:" + seed.hex()

    def decrypt(self, ciphertext: str) -> bytes:
        if self.down:
            raise VaultUnavailable("vault unreachable: ConnectError")
        return bytes.fromhex(ciphertext.removeprefix("enc:"))


@dataclass
class Env:
    server: PgServer
    clock: Clock
    cipher: Cipher
    limits: RateLimiter
    client: TestClient
    ip_counter: int = 0

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(
        self, role: str = "viewer", *, seed: bytes | None = None, disabled: bool = False
    ) -> str:
        name = f"u-{secrets.token_hex(5)}"
        with self.conn() as c:
            c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " disabled, created_at) VALUES (%s, %s, %s::user_role, %s, %s, %s)",
                (
                    name,
                    HASH,
                    role,
                    None if seed is None else self.cipher.encrypt(seed),
                    disabled,
                    T0,
                ),
            )
        return name

    def row(self, name: str) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM app_user WHERE username = %s", (name,))
            cols = [d.name for d in cur.description or []]
            values = cur.fetchone()
        assert values is not None
        return dict(zip(cols, values, strict=True))

    def fresh_ip(self) -> str:
        self.ip_counter += 1
        return f"10.9.{self.ip_counter // 250}.{self.ip_counter % 250 + 1}"

    def login(
        self,
        username: str,
        password: str,
        code: str | None = None,
        ip: str | None = None,
        **extra: Any,
    ) -> Any:
        body: dict[str, Any] = {"username": username, "password": password, **extra}
        if code is not None:
            body["totp_code"] = code
        client = TestClient(self.client.app, client=(ip or self.fresh_ip(), 40000))
        return client.post(LOGIN, json=body)

    def get_with(self, token: str, path: str = LOGOUT, method: str = "POST") -> Any:
        return self.client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}
        )


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock, cipher = Clock(), Cipher()
    limits = RateLimiter(clock)
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    rt = Runtime(
        clock=clock, db=db, totp_cipher=cipher, sink_gate=Gate(), limits=limits
    )
    with TestClient(create_app(rt), client=("10.8.0.1", 1)) as client:
        yield Env(migrated_db, clock, cipher, limits, client)
    db.close()


def code_for(seed: bytes, at: datetime) -> str:
    return totp.code_at(seed, totp.step_at(at))


def audit_actions(env: Env, since_id: int) -> list[tuple[str, str, Any]]:
    with env.conn() as c:
        rows = c.execute(
            "SELECT action, target, detail FROM audit_log WHERE audit_id > %s"
            " ORDER BY audit_id",
            (since_id,),
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def max_audit_id(env: Env) -> int:
    with env.conn() as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


# ------------------------------------------------------------ CHK-M2-170


def test_every_failure_gets_one_identical_401(env: Env) -> None:
    seed_admin, seed_viewer = totp.new_seed(), totp.new_seed()
    plain = env.user()
    disabled = env.user(disabled=True)
    admin = env.user("admin", seed=seed_admin)
    viewer_totp = env.user("viewer", seed=seed_viewer)
    slow = env.user()
    env.login(slow, WRONG)  # puts it in back-off
    used = code_for(seed_admin, env.clock.at)
    assert env.login(admin, PW, used).status_code == 200
    responses = [
        env.login("nobody-" + secrets.token_hex(3), PW),
        env.login(disabled, PW),
        env.login(plain, WRONG),
        env.login(admin, PW),  # admin without a code
        env.login(admin, PW, "000000" if used != "000000" else "111111"),
        env.login(admin, PW, used),  # reused code
        env.login(viewer_totp, PW),  # #49 (c): an enrolled viewer needs a code
        env.login(slow, PW),  # correct password during back-off
    ]
    bodies = {r.text for r in responses}
    assert {r.status_code for r in responses} == {401}
    assert len(bodies) == 1, bodies
    header_sets = {
        tuple(sorted(k for k in r.headers if k != "date")) for r in responses
    }
    assert len(header_sets) == 1
    body = responses[0].json()
    assert body["type"] == "unauthorized" and body["instance"] == LOGIN


# ------------------------------------------------------------ CHK-M2-172


def test_backoff_sequence_and_reset(env: Env) -> None:
    name = env.user()
    for n in range(1, 13):
        failed_at = env.clock.at
        assert env.login(name, WRONG).status_code == 401
        row = env.row(name)
        assert row["failed_logins"] == n
        assert row["next_login_at"] == failed_at + timedelta(
            seconds=min(2 ** (n - 1), 900)
        )
        # the correct password 1 s before next_login_at: refused, not counted
        env.clock.at = row["next_login_at"] - timedelta(seconds=1)
        assert env.login(name, PW).status_code == 401
        assert env.row(name)["failed_logins"] == n
        env.clock.at = row["next_login_at"]
    resp = env.login(name, PW)
    assert resp.status_code == 200
    row = env.row(name)
    assert row["failed_logins"] == 0 and row["next_login_at"] is None


# ------------------------------------------------------------ CHK-M2-173


def test_admin_is_slowed_never_locked(env: Env) -> None:
    seed = totp.new_seed()
    name = env.user("admin", seed=seed)
    for _ in range(100):
        env.clock.at = env.row(name)["next_login_at"] or env.clock.at
        env.login(name, WRONG)
    row = env.row(name)
    assert 0 < row["failed_logins"] <= 32767
    env.clock.at += timedelta(minutes=15)
    resp = env.login(name, PW, code_for(seed, env.clock.at))
    assert resp.status_code == 200


# ------------------------------------------------------- CHK-M2-174, -176


def test_success_body_and_session_row(env: Env) -> None:
    seed = totp.new_seed()
    name = env.user("operator", seed=seed)
    resp = env.login(name, PW, code_for(seed, env.clock.at))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "token",
        "expires_at",
        "role",
        "totp_enrolled",
        "totp_verified",
    }
    assert body["role"] == "operator" and body["totp_enrolled"] is True
    assert body["totp_verified"] is True
    tok = body["token"]
    assert tok.startswith("bsu_") and len(tok) == 47
    assert body["expires_at"] == "2026-10-22T10:00:00.000000Z"
    with env.conn() as c:
        row = c.execute(
            "SELECT kind, totp_verified, created_at, expires_at FROM user_token"
            " WHERE token_hash = %s",
            (token_hash(tok),),
        ).fetchone()
    assert row is not None
    assert row[0] == "session" and row[1] is True
    assert row[3] - row[2] == timedelta(hours=24)
    assert env.get_with(tok, "/api/v1/auth/logout").status_code == 204


def test_admin_without_totp_gets_a_restricted_session(env: Env) -> None:
    name = env.user("admin")
    resp = env.login(name, PW)
    assert resp.status_code == 200
    body = resp.json()
    assert body["totp_verified"] is False and body["totp_enrolled"] is False
    # only logout (and TOTP enrolment, TASK-039) is allowed for it
    assert env.get_with(body["token"]).status_code == 204


def test_non_admin_without_totp_gets_an_ordinary_session(env: Env) -> None:
    resp = env.login(env.user("viewer"), PW)
    assert resp.status_code == 200 and resp.json()["totp_verified"] is False


def test_timestamps_are_utc_z_with_a_non_utc_session_time_zone(
    migrated_db: PgServer,
) -> None:
    """CHK-M2-045 on the login response, session TimeZone Asia/Singapore."""
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params["options"] = "-c TimeZone=Asia/Singapore"
    db = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=3)
    db.open()
    clock = Clock()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    try:
        with psycopg.connect(migrated_db.dsn("bitscan_app"), autocommit=True) as c:
            name = f"tz-{secrets.token_hex(4)}"
            c.execute(
                "INSERT INTO app_user (username, password_hash, created_at)"
                " VALUES (%s, %s, %s)",
                (name, HASH, T0),
            )
        with TestClient(create_app(rt), client=("10.7.0.1", 1)) as client:
            body = client.post(LOGIN, json={"username": name, "password": PW}).json()
        assert body["expires_at"].endswith("Z")
        assert datetime.fromisoformat(body["expires_at"]) == T0 + timedelta(hours=24)
    finally:
        db.close()


# ------------------------------------------------------------ CHK-M2-175


def test_totp_code_is_single_use_and_steps_only_move_forward(env: Env) -> None:
    seed = totp.new_seed()
    name = env.user("admin", seed=seed)
    now_code = code_for(seed, env.clock.at)
    assert env.login(name, PW, now_code).status_code == 200
    assert env.login(name, PW, now_code).status_code == 401
    older = totp.code_at(seed, totp.step_at(env.clock.at) - 1)
    if older != now_code:
        assert env.login(name, PW, older).status_code == 401  # older than the last used
    env.clock.at += timedelta(seconds=30)
    assert env.login(name, PW, code_for(seed, env.clock.at)).status_code == 200


def test_two_concurrent_sign_ins_with_one_code_give_one_session(env: Env) -> None:
    for _ in range(5):
        seed = totp.new_seed()
        name = env.user("admin", seed=seed)
        code = code_for(seed, env.clock.at)
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def attempt(
            barrier: threading.Barrier, name: str, code: str, codes: list[int]
        ) -> None:
            barrier.wait(10)
            codes.append(env.login(name, PW, code).status_code)

        threads = [
            threading.Thread(target=attempt, args=(barrier, name, code, codes))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert sorted(codes) == [200, 401]
        with env.conn() as c:
            n = c.execute(
                "SELECT count(*) FROM user_token t JOIN app_user u USING (user_id)"
                " WHERE u.username = %s",
                (name,),
            ).fetchone()
        assert n == (1,)


# ------------------------------------------------------------ CHK-M2-177


def test_sign_in_limit_10_per_minute_per_ip(env: Env) -> None:
    # each attempt goes to a fresh user, so back-off never interferes; every
    # attempt counts toward the per-IP limit, success or failure (#55 (c))
    ip = "10.1.1.1"
    codes = [
        env.login(env.user(), WRONG if i % 2 else PW, ip=ip).status_code
        for i in range(10)
    ]
    assert codes == [200, 401] * 5
    name = env.user()
    resp = env.login(name, PW, ip=ip)
    assert resp.status_code == 429
    assert resp.json()["type"] == "rate_limited"
    assert 1 <= int(resp.headers["retry-after"]) <= 60
    assert resp.headers["content-security-policy"].startswith("default-src 'self'")
    assert env.login(name, PW, ip="10.1.1.2").status_code == 200
    env.clock.at += timedelta(minutes=1)
    assert env.login(name, PW, ip=ip).status_code == 200


# ------------------------------------------------------------ CHK-M2-183


def test_forwarded_headers_do_not_change_the_ip(env: Env) -> None:
    name = env.user()
    client = TestClient(env.client.app, client=("10.2.2.2", 1))
    codes = []
    for i in range(11):
        headers = {
            "X-Forwarded-For": f"203.0.113.{i}",
            "Forwarded": f"for=198.51.100.{i}",
            "X-Real-IP": f"192.0.2.{i}",
        }
        codes.append(
            client.post(
                LOGIN, json={"username": name, "password": PW}, headers=headers
            ).status_code
        )
    assert codes[-1] == 429 and 429 not in codes[:10]


# ------------------------------------------------------------ CHK-M2-178


def test_login_failures_alert_and_audit_entries(env: Env) -> None:
    name = env.user()
    uid = env.row(name)["user_id"]
    start = max_audit_id(env)
    for _ in range(10):
        env.clock.at = env.row(name)["next_login_at"] or env.clock.at
        env.login(name, WRONG)
    entries = audit_actions(env, start)
    alerts = [e for e in entries if e[0] == "auth.login_failures"]
    assert [a[2]["failed_logins"] for a in alerts] == [5, 10]
    for _action, target, detail in alerts:
        assert target == f"user:{uid}"
        assert detail["alert"] is True and detail["alert_kind"] == "login_failures"
        assert name not in json.dumps(detail) and WRONG not in json.dumps(detail)
    assert not [e for e in entries if e[0] == "auth.login"]
    env.clock.at = env.row(name)["next_login_at"]
    resp = env.login(name, PW)
    assert resp.status_code == 200
    env.get_with(resp.json()["token"])
    later = audit_actions(env, start)
    assert [e[0] for e in later][-2:] == ["auth.login", "auth.logout"]


def test_unknown_usernames_never_alert_or_audit(env: Env) -> None:
    start = max_audit_id(env)
    for i in range(12):
        env.login(f"ghost-{i}", WRONG)
    assert audit_actions(env, start) == []


# ------------------------------------------------------------ CHK-M2-179


def test_logout_revokes_only_the_presenting_session(env: Env) -> None:
    name = env.user()
    a = env.login(name, PW).json()["token"]
    b = env.login(name, PW).json()["token"]
    assert env.get_with(a).status_code == 204
    assert env.get_with(a).status_code == 401
    assert env.get_with(b).status_code == 204  # the other session still worked


def test_logout_with_an_api_token_is_refused_and_keeps_it(env: Env) -> None:
    name = env.user()
    uid = env.row(name)["user_id"]
    api = "bsk_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(
        "="
    )
    with env.conn() as c:
        c.execute(
            "INSERT INTO user_token (user_id, kind, token_hash, expires_at,"
            " created_at) VALUES (%s, 'api', %s, %s, %s)",
            (uid, token_hash(api), T0 + timedelta(days=90), T0),
        )
    resp = env.get_with(api)
    assert resp.status_code == 403 and resp.json()["type"] == "session_required"
    with env.conn() as c:
        row = c.execute(
            "SELECT revoked_at FROM user_token WHERE token_hash = %s",
            (token_hash(api),),
        ).fetchone()
    assert row == (None,)


# ------------------------------------------------------------ CHK-M2-180


def test_no_secret_in_responses_or_logs(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    canary_pw = new_canary("pw")
    seed = totp.new_seed()
    name = env.user("admin", seed=seed)
    first = env.login(name, canary_pw)
    env.clock.at = env.row(name)["next_login_at"]  # past the back-off
    responses = [first, env.login(name, PW, code_for(seed, env.clock.at))]
    assert [r.status_code for r in responses] == [401, 200]
    row = env.row(name)
    secrets_ = [canary_pw, PW, row["password_hash"], row["totp_secret_enc"]]
    token = responses[1].json()["token"]
    secrets_ += [token_hash(token)]
    assert sweep(secrets_, caplog.text, *[r.text for r in responses]) == []
    for r in responses:
        assert "password_hash" not in r.text and "totp_secret_enc" not in r.text


# ------------------------------------------------------------ CHK-M2-181


def test_vault_down_is_503_for_totp_users_only(env: Env) -> None:
    seed = totp.new_seed()
    with_totp = env.user("admin", seed=seed)
    without = env.user("operator")
    env.cipher.down = True
    resp = env.login(with_totp, PW, code_for(seed, env.clock.at))
    assert resp.status_code == 503
    assert resp.json()["type"] == "about:blank"
    assert env.row(with_totp)["failed_logins"] == 0
    assert env.login(without, PW).status_code == 200


# ------------------------------------------------------------ CHK-M2-184


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "x"},
        {"password": "x"},
        {"username": 5, "password": "x"},
        {"username": "x", "password": "y", "extra": 1},
        [],
        "x",
    ],
)
def test_malformed_body_is_400_and_counts_nothing(env: Env, body: Any) -> None:
    name = env.user()
    resp = TestClient(env.client.app, client=(env.fresh_ip(), 1)).post(LOGIN, json=body)
    assert resp.status_code == 400 and resp.json()["type"] == "invalid_request"
    assert env.row(name)["failed_logins"] == 0


def test_oversized_body_is_413(env: Env) -> None:
    resp = TestClient(env.client.app, client=(env.fresh_ip(), 1)).post(
        LOGIN,
        content=b'{"username": "' + b"a" * 2_000_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413 and resp.json()["type"] == "too_large"


# ------------------------------------------------------------ CHK-M2-187


def test_database_unavailable_is_503_never_500_or_401(migrated_db: PgServer) -> None:
    proxy = PausableProxy(migrated_db.host, migrated_db.port)
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params.update(host="127.0.0.1", port=1)
    clock = Clock()
    limits = RateLimiter(clock)
    db = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=1)
    db.open()
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=Gate(), limits=limits
    )
    try:
        with TestClient(create_app(rt), client=("10.6.0.1", 1)) as c:
            token = "bsu_" + "A" * 43
            for _ in range(25):
                resp = c.post(LOGOUT, headers={"Authorization": f"Bearer {token}"})
                assert resp.status_code == 503, resp.text
                assert resp.json()["type"] == "about:blank"
            assert limits.failed_check_blocked("10.6.0.1") is False
            resp = c.post(LOGIN, json={"username": "x", "password": "y" * 12})
            assert resp.status_code == 503 and resp.json()["type"] == "about:blank"
            assert (
                sweep([str(params["password"]), "127.0.0.1", "port=1"], resp.text) == []
            )
    finally:
        db.close()
        proxy.close()


def session_verified(env: Env, token: str) -> bool:
    with env.conn() as c:
        row = c.execute(
            "SELECT totp_verified FROM user_token WHERE token_hash = %s",
            (token_hash(token),),
        ).fetchone()
    assert row is not None
    return bool(row[0])


@pytest.mark.parametrize("role", ["admin", "operator", "viewer"])
def test_sessions_without_a_code_are_never_totp_verified(env: Env, role: str) -> None:
    """REQ-048 (5): totp_verified is true only after a verified code, in the
    stored row too; an admin without TOTP stays restricted when it acts."""
    token = env.login(env.user(role), PW).json()["token"]
    assert session_verified(env, token) is False
    if role == "admin":
        # the restricted session may log out but nothing else (REQ-046 (d))
        resp = env.client.get(
            "/api/v1/api-tokens", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code in (403, 404, 405)
    seed = totp.new_seed()
    with_code = env.login(env.user(role, seed=seed), PW, code_for(seed, env.clock.at))
    assert session_verified(env, with_code.json()["token"]) is True
