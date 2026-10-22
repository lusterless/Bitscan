"""TASK-041: API tokens through the API on PostgreSQL.

Checks CHK-M2-210 to CHK-M2-219 of tests/m2/test-plan.md (TP-M2-19). TS §6.2
L1081 (created only from a web session, TOTP-verified for admins; default 90
days, at most 365; shown once), L1085 (an API token can never create API
tokens), L1098-L1099 (create; list and revoke your own; viewer), TS §8.4
L1290 ("API token created" alerts), REQ-051, REQ-040 (3), (5), #8 (an API
token may revoke its own), #47, #48, #52, lead ruling 2026-10-22 (201 Created,
body {token_id, token, name, expires_at}; shown once).
"""

import secrets
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
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import sweep
from .conftest import PgServer
from .test_totp_enrol import Cipher, Clock, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
ROUTE = "/api/v1/api-tokens"
ITEM_KEYS = {
    "token_id",
    "name",
    "created_at",
    "expires_at",
    "last_used_at",
    "revoked_at",
}


class RefusingGate(Gate):
    def __init__(self) -> None:
        self.refuse = False

    def refusing(self) -> bool:
        return self.refuse


@dataclass
class Env:
    server: PgServer
    clock: Clock
    gate: RefusingGate
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str = "viewer", totp: bool = False) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " created_at) VALUES (%s, '$argon2id$x', %s::user_role, %s, %s)"
                " RETURNING user_id",
                (f"k-{secrets.token_hex(5)}", role, "enc:00" if totp else None, T0),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def session(self, uid: int, verified: bool = False) -> str:
        tok = new_token(TokenKind.SESSION)
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, 'session', %s, %s, %s, %s)",
                (uid, token_hash(tok), verified, T0 + timedelta(hours=24), T0),
            )
        return tok

    def call(self, method: str, token: str, path: str = ROUTE, **kw: Any) -> Any:
        return self.client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kw
        )

    def create(self, token: str, **body: Any) -> Any:
        return self.call("POST", token, json=body)


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock, gate = Clock(), RefusingGate()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=gate,
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.3.0.1", 1)) as client:
        yield Env(migrated_db, clock, gate, client)
    db.close()


def problem(resp: Any, status: int, type_: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.json()["type"] == type_


# ------------------------------------------------------------ CHK-M2-210


def test_default_lifetime_is_90_days(env: Env) -> None:
    sess = env.session(env.user())
    resp = env.create(sess)
    assert resp.status_code == 201
    body = resp.json()
    assert datetime.fromisoformat(body["expires_at"]) == T0 + timedelta(days=90)
    assert body["expires_at"].endswith("Z")


@pytest.mark.parametrize("days", [1, 365])
def test_lifetime_bounds_accepted(env: Env, days: int) -> None:
    resp = env.create(env.session(env.user()), expires_in_days=days)
    assert resp.status_code == 201
    assert datetime.fromisoformat(resp.json()["expires_at"]) == T0 + timedelta(
        days=days
    )


@pytest.mark.parametrize("days", [366, 0, -1, 1.5, "30", True, None])
def test_bad_lifetimes_are_400(env: Env, days: Any) -> None:
    uid = env.user()
    sess = env.session(uid)
    body: dict[str, Any] = {"expires_in_days": days}
    resp = env.create(sess, **body)
    if days is None:  # explicit null means the default
        assert resp.status_code == 201
        return
    problem(resp, 400, "invalid_request")
    with env.conn() as c:
        n = c.execute(
            "SELECT count(*) FROM user_token WHERE user_id = %s AND kind = 'api'",
            (uid,),
        ).fetchone()
    assert n == (0,)


@pytest.mark.parametrize(
    ("name", "ok"),
    [("x" * 64, True), ("x" * 65, False), ("é" * 64, True), (None, True)],
)
def test_name_length(env: Env, name: str | None, ok: bool) -> None:
    resp = env.create(env.session(env.user()), name=name)
    if ok:
        assert resp.status_code == 201 and resp.json()["name"] == name
    else:
        problem(resp, 400, "invalid_request")


def test_unknown_field_is_400(env: Env) -> None:
    problem(env.create(env.session(env.user()), role="admin"), 400, "invalid_request")


# ------------------------------------------------------- CHK-M2-211, -217


def test_token_shown_once_and_works_on_its_next_request(env: Env) -> None:
    uid = env.user("operator")
    sess = env.session(uid)
    resp = env.create(sess, name="ci")
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"token_id", "token", "name", "expires_at"}
    tok = body["token"]
    assert tok.startswith("bsk_") and len(tok) == 47
    assert isinstance(body["token_id"], int)  # #52
    listed = env.call("GET", tok)  # the new token itself works
    assert listed.status_code == 200
    page = listed.json()
    assert set(page) == {"items", "next_cursor"}
    (item,) = page["items"]
    assert set(item) == ITEM_KEYS
    assert item["token_id"] == body["token_id"] and item["name"] == "ci"
    assert item["last_used_at"] is not None  # used by this very request
    for text in (listed.text, env.call("GET", sess).text):
        assert tok not in text and tok[4:] not in text and token_hash(tok) not in text
    with env.conn() as c:
        row = c.execute(
            "SELECT token_hash, totp_verified FROM user_token WHERE token_id = %s",
            (body["token_id"],),
        ).fetchone()
    assert row == (
        token_hash(tok),
        False,
    )  # only the hash; never verified (REQ-051 (7))


def test_no_raw_token_in_any_text_column(env: Env) -> None:
    """REQ-040 (5): after 50 creations no token appears in user_token,
    app_user or audit_log."""
    uid = env.user()
    sess = env.session(uid)
    tokens = [env.create(sess).json()["token"] for _ in range(50)]
    with env.conn() as c:
        dump = []
        for table in ("user_token", "app_user", "audit_log"):
            dump += [repr(r) for r in c.execute(f"SELECT * FROM {table}").fetchall()]  # noqa: S608  fixed names
    blob = "\n".join(dump)
    assert sweep([*tokens, *(t[4:] for t in tokens)], blob) == []


# ------------------------------------------------------------ CHK-M2-212


def test_users_see_and_revoke_only_their_own(env: Env) -> None:
    a, b = env.user(), env.user()
    sa, sb = env.session(a), env.session(b)
    tok_a = env.create(sa, name="mine").json()
    env.create(sb, name="theirs")
    listed_b = env.call("GET", sb).json()["items"]
    assert [i["name"] for i in listed_b] == ["theirs"]
    with env.conn() as c:
        top = c.execute("SELECT max(token_id) FROM user_token").fetchone()
    assert top is not None
    for guess in range(1, int(top[0]) + 6):
        resp = env.call("DELETE", sb, f"{ROUTE}/{guess}")
        if resp.status_code == 204:
            continue  # one of b's own tokens
        problem(resp, 404, "not_found")
    assert env.call("GET", tok_a["token"]).status_code == 200  # a's token survived


def test_sessions_cannot_be_revoked_through_this_route(env: Env) -> None:
    uid = env.user()
    sess = env.session(uid)
    with env.conn() as c:
        row = c.execute(
            "SELECT token_id FROM user_token WHERE token_hash = %s", (token_hash(sess),)
        ).fetchone()
    assert row is not None
    problem(env.call("DELETE", sess, f"{ROUTE}/{row[0]}"), 404, "not_found")


@pytest.mark.parametrize("bad", ["abc", "1.5", "-1", "0x10"])
def test_non_integer_id_is_400(env: Env, bad: str) -> None:
    resp = env.call("DELETE", env.session(env.user()), f"{ROUTE}/{bad}")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 422


# ------------------------------------------------------- CHK-M2-213, -215


def test_revoked_token_is_refused_on_its_next_request(env: Env) -> None:
    sess = env.session(env.user())
    made = env.create(sess).json()
    assert env.call("DELETE", sess, f"{ROUTE}/{made['token_id']}").status_code == 204
    problem(env.call("GET", made["token"]), 401, "unauthorized")
    problem(env.call("DELETE", sess, f"{ROUTE}/{made['token_id']}"), 404, "not_found")


def test_an_api_token_may_revoke_its_own_tokens_and_itself(env: Env) -> None:
    sess = env.session(env.user())
    one = env.create(sess).json()
    two = env.create(sess).json()
    assert (
        env.call("DELETE", one["token"], f"{ROUTE}/{two['token_id']}").status_code
        == 204
    )
    assert (
        env.call("DELETE", one["token"], f"{ROUTE}/{one['token_id']}").status_code
        == 204
    )
    problem(env.call("GET", one["token"]), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M2-214


def test_each_creation_alerts_and_each_revoke_is_audited(env: Env) -> None:
    uid = env.user()
    sess = env.session(uid)
    made = [env.create(sess).json() for _ in range(3)]
    env.call("DELETE", sess, f"{ROUTE}/{made[0]['token_id']}")
    with env.conn() as c:
        rows = c.execute(
            "SELECT action, detail FROM audit_log WHERE target = %s ORDER BY audit_id",
            (f"user:{uid}",),
        ).fetchall()
    actions = [r[0] for r in rows]
    assert actions == ["api_token.create"] * 3 + ["api_token.revoke"]
    for _, detail in rows[:3]:
        assert detail["alert"] is True and detail["alert_kind"] == "api_token_created"
    assert "alert" not in rows[3][1]
    blob = repr(rows)
    assert (
        sweep([m["token"] for m in made] + [token_hash(m["token"]) for m in made], blob)
        == []
    )


# ------------------------------------------------------- CHK-M2-216


def test_who_may_create(env: Env) -> None:
    viewer, operator = env.user("viewer"), env.user("operator")
    admin = env.user("admin", totp=True)
    no_totp_admin = env.user("admin")
    assert env.create(env.session(viewer)).status_code == 201
    assert env.create(env.session(operator)).status_code == 201
    assert env.create(env.session(admin, verified=True)).status_code == 201
    problem(
        env.create(env.session(admin, verified=False)), 403, "totp_session_required"
    )
    problem(env.create(env.session(no_totp_admin)), 403, "totp_session_required")
    api = env.create(env.session(viewer)).json()["token"]
    problem(env.create(api), 403, "session_required")  # REQ-046 (2), REQ-051 (8)
    admin_api = env.create(env.session(admin, verified=True)).json()["token"]
    problem(env.create(admin_api), 403, "session_required")


# ------------------------------------------------------------ CHK-M2-218


def test_sink_gate_does_not_apply(env: Env) -> None:
    env.gate.refuse = True
    viewer = env.session(env.user())
    admin = env.session(env.user("admin", totp=True), verified=True)
    assert env.create(viewer).status_code == 201
    assert env.create(admin).status_code == 201
    assert env.call("GET", viewer).status_code == 200


# ------------------------------------------------------------ CHK-M2-219


def test_list_pagination(env: Env) -> None:
    sess = env.session(env.user())
    ids = [env.create(sess).json()["token_id"] for _ in range(51)]
    first = env.call("GET", sess).json()
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = env.call("GET", sess, params={"cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    got = [i["token_id"] for i in first["items"] + second["items"]]
    assert got == ids
    problem(
        env.call("GET", sess, params={"cursor": first["next_cursor"][:-2] + "AA"}),
        400,
        "invalid_request",
    )


def test_timestamps_are_utc_z_with_a_non_utc_session_time_zone(
    migrated_db: PgServer,
) -> None:
    """CHK-M2-045 on the create and list responses (TimeZone Asia/Singapore)."""
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
        with TestClient(create_app(rt), client=("10.3.9.1", 1)) as client:
            env = Env(migrated_db, clock, RefusingGate(), client)
            sess = env.session(env.user())
            created = env.create(sess).json()
            item = env.call("GET", sess).json()["items"][0]
        assert created["expires_at"].endswith("Z")
        for key in ("created_at", "expires_at", "last_used_at"):
            if item[key] is not None:
                assert item[key].endswith("Z"), key
        assert datetime.fromisoformat(item["created_at"]) == T0
    finally:
        db.close()
