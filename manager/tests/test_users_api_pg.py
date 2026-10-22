"""TASK-043: /api/v1/users through the API on PostgreSQL.

Checks CHK-M2-230 to CHK-M2-236 of tests/m2/test-plan.md (TP-M2-20, API
part). TS §6.2 L1125 (CRUD /users, delete means disable; admin, TOTP
session), L1084 (sensitive: API tokens refused), TS §5.3 L1051 (refused after
15 minutes of sink outage until the queue drains), REQ-052, REQ-046, REQ-054,
#47 (c), #48, #52, #53, lead rulings on TASK-042.
"""

import secrets
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password, verify_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import DeliveryError, SinkRecord

from .canary import sweep
from .conftest import PgServer
from .test_totp_enrol import Cipher, Clock

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
PW = "users api pass " + "word"
HASH = hash_password(PW)
ROUTE = "/api/v1/users"
ITEM_KEYS = {"user_id", "username", "role", "disabled", "totp_enrolled", "created_at"}


class SwitchSink:
    def __init__(self) -> None:
        self.up = True

    def send(self, records: Sequence[SinkRecord]) -> None:
        if not self.up:
            raise DeliveryError("ConnectionRefusedError", 0)

    def close(self) -> None:
        return None


@dataclass
class Env:
    server: PgServer
    clock: Clock
    sink: SwitchSink
    shipper: Shipper
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(
        self, role: str = "viewer", totp: bool = False, disabled: bool = False
    ) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, disabled, created_at) VALUES (%s, %s,"
                " %s::user_role, %s, %s, %s, %s) RETURNING user_id",
                (
                    f"x-{secrets.token_hex(5)}",
                    HASH,
                    role,
                    "enc:00" if totp else None,
                    5 if totp else None,
                    disabled,
                    T0,
                ),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def token(self, uid: int, kind: str = "session", verified: bool = True) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uid,
                    kind,
                    token_hash(tok),
                    verified and kind == "session",
                    T0 + timedelta(days=30),
                    T0,
                ),
            )
        return tok

    def admin(self) -> tuple[int, str]:
        uid = self.user("admin", totp=True)
        return uid, self.token(uid)

    def call(self, method: str, token: str, path: str = ROUTE, **kw: Any) -> Any:
        return self.client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kw
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

    def snapshot(self) -> tuple[Any, ...]:
        with self.conn() as c:
            users = c.execute("SELECT * FROM app_user ORDER BY user_id").fetchall()
            toks = c.execute(
                "SELECT token_id, revoked_at FROM user_token ORDER BY token_id"
            ).fetchall()
            audit = c.execute("SELECT count(*) FROM audit_log").fetchone()
        return users, toks, audit

    def entries(self, uid: int) -> list[tuple[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT action, detail FROM audit_log WHERE target = %s"
                " ORDER BY audit_id",
                (f"user:{uid}",),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]


@pytest.fixture
def env(migrated_db: PgServer, tmp_path: Path) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    sink = SwitchSink()
    shipper = Shipper(
        PgAuditTail(db), DiskQueue(tmp_path / "q"), sink, clock, DbOutageAudit(db)
    )
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=shipper,
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.2.0.1", 1)) as client:
        with migrated_db.connect("bitscan_app") as c:  # one other admin always exists
            c.execute("UPDATE app_user SET role = 'operator' WHERE role = 'admin'")
        yield Env(migrated_db, clock, sink, shipper, client)
    db.close()


def problem(resp: Any, status: int, type_: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == type_


# ------------------------------------------------------------ CHK-M2-230


def test_create_get_and_list(env: Env) -> None:
    _, tok = env.admin()
    name = f"new-{secrets.token_hex(4)}"
    resp = env.call("POST", tok, json={"username": name, "password": PW})
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == ITEM_KEYS
    assert (
        body["username"],
        body["role"],
        body["disabled"],
        body["totp_enrolled"],
    ) == (name, "viewer", False, False)
    assert isinstance(body["user_id"], int) and body["created_at"].endswith("Z")
    uid = body["user_id"]
    assert verify_password(env.row(uid)["password_hash"], PW)
    assert env.call("GET", tok, f"{ROUTE}/{uid}").json() == body
    op = env.call(
        "POST", tok, json={"username": name + "o", "password": PW, "role": "operator"}
    )
    assert op.status_code == 201 and op.json()["role"] == "operator"
    assert [a for a, _ in env.entries(uid)] == ["user.create"]
    assert env.entries(uid)[0][1]["alert_kind"] == "user_created"


@pytest.mark.parametrize(
    ("body", "status", "type_"),
    [
        ({"username": "dup", "password": PW}, 409, "conflict"),
        ({"username": "adm", "password": PW, "role": "admin"}, 400, "invalid_request"),
        ({"username": "short", "password": "a" * 11}, 400, "invalid_request"),
        ({"username": "a b", "password": PW}, 400, "invalid_request"),
        ({"username": "é", "password": PW}, 400, "invalid_request"),
        ({"username": "x", "password": PW, "extra": 1}, 400, "invalid_request"),
    ],
)
def test_create_refusals_change_nothing(
    env: Env, body: dict[str, Any], status: int, type_: str
) -> None:
    _, tok = env.admin()
    if body["username"] == "dup":
        body = {**body, "username": f"dup-{secrets.token_hex(3)}"}
        assert env.call("POST", tok, json=body).status_code == 201
    before = env.snapshot()
    problem(env.call("POST", tok, json=body), status, type_)
    assert env.snapshot() == before
    assert PW not in env.call("POST", tok, json=body).text


def test_promotion_needs_totp_and_alerts_role_granted(env: Env) -> None:
    _, tok = env.admin()
    plain, with_totp = env.user("operator"), env.user("operator", totp=True)
    s1, s2 = env.token(plain), env.token(with_totp)
    api = env.token(with_totp, "api")
    before = env.snapshot()
    problem(
        env.call("PATCH", tok, f"{ROUTE}/{plain}", json={"role": "admin"}),
        409,
        "conflict",
    )
    assert env.snapshot() == before
    resp = env.call("PATCH", tok, f"{ROUTE}/{with_totp}", json={"role": "admin"})
    assert resp.status_code == 200 and resp.json()["role"] == "admin"
    assert not env.live(s2) and env.live(api)  # a raise ends sessions only
    assert env.live(s1)
    kinds = [
        d.get("alert_kind")
        for a, d in env.entries(with_totp)
        if a == "user.role_change"
    ]
    assert kinds == ["role_granted"]


def test_demotion_revokes_sessions_and_api_tokens(env: Env) -> None:
    _, tok = env.admin()
    other_admin = env.user("admin", totp=True)
    sess, api = env.token(other_admin), env.token(other_admin, "api")
    resp = env.call("PATCH", tok, f"{ROUTE}/{other_admin}", json={"role": "operator"})
    assert resp.status_code == 200 and resp.json()["role"] == "operator"
    assert not env.live(sess) and not env.live(api)
    entry = [d for a, d in env.entries(other_admin) if a == "user.role_change"][-1]
    assert entry is None or "alert" not in entry


def test_disable_keeps_the_row_and_revokes_everything(env: Env) -> None:
    _, tok = env.admin()
    uid = env.user("operator")
    sess, api = env.token(uid), env.token(uid, "api")
    assert env.call("DELETE", tok, f"{ROUTE}/{uid}").status_code == 204
    row = env.row(uid)
    assert row["disabled"] is True
    assert not env.live(sess) and not env.live(api)
    assert env.call("GET", tok, f"{ROUTE}/{uid}").json()["disabled"] is True
    resp = env.call("PATCH", tok, f"{ROUTE}/{uid}", json={"disabled": False})
    assert resp.status_code == 200 and resp.json()["disabled"] is False
    assert not env.live(sess)  # re-enable does not un-revoke (#53 (g))
    actions = [a for a, _ in env.entries(uid)]
    assert actions[-2:] == ["user.disable", "user.enable"]


def test_last_active_admin_cannot_be_disabled_or_demoted(env: Env) -> None:
    me, tok = env.admin()
    for method, body in (
        ("DELETE", None),
        ("PATCH", {"role": "operator"}),
        ("PATCH", {"role": "viewer"}),
    ):
        before = env.snapshot()
        kw = {} if body is None else {"json": body}
        problem(env.call(method, tok, f"{ROUTE}/{me}", **kw), 409, "conflict")
        assert env.snapshot() == before


def test_totp_reset_by_another_admin_and_not_of_oneself(env: Env) -> None:
    me, tok = env.admin()
    other = env.user("admin", totp=True)
    their_session = env.token(other)
    resp = env.call("PATCH", tok, f"{ROUTE}/{other}", json={"totp": None})
    assert resp.status_code == 200 and resp.json()["totp_enrolled"] is False
    row = env.row(other)
    assert (row["totp_secret_enc"], row["totp_last_step"]) == (None, None)
    assert not env.live(their_session)
    assert env.entries(other)[-1][1]["alert_kind"] == "totp_reset"
    problem(
        env.call("PATCH", tok, f"{ROUTE}/{me}", json={"totp": None}), 409, "conflict"
    )


def test_revoke_tokens_ends_sessions_and_api_tokens(env: Env) -> None:
    _, tok = env.admin()
    uid = env.user("operator")
    sess, api = env.token(uid), env.token(uid, "api")
    resp = env.call("PATCH", tok, f"{ROUTE}/{uid}", json={"revoke_tokens": True})
    assert resp.status_code == 200
    assert not env.live(sess) and not env.live(api)
    assert env.entries(uid)[-1][0] == "user.tokens_revoke"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"role": "admin", "disabled": False},
        {"disabled": True},
        {"revoke_tokens": False},
        {"totp": "x"},
        {"role": "root"},
    ],
)
def test_patch_needs_exactly_one_known_action(env: Env, body: dict[str, Any]) -> None:
    _, tok = env.admin()
    uid = env.user()
    before = env.snapshot()
    problem(env.call("PATCH", tok, f"{ROUTE}/{uid}", json=body), 400, "invalid_request")
    assert env.snapshot() == before


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("field", ["revoke_tokens", "disabled", "role"])
def test_patch_null_is_refused_unless_it_is_the_documented_value(
    env: Env, field: str, disabled: bool
) -> None:
    """Reviewer finding 1 (TASK-043 revision 1): the four PATCH actions are
    {role}, {disabled: false}, {totp: null}, {revoke_tokens: true} (lead ruling
    2026-10-22); null is a value only for totp. The target has TOTP, a session
    and an API token, so a null read as any action would show in the snapshot
    (rows, token revocations, audit count)."""
    _, tok = env.admin()
    uid = env.user("operator", totp=True, disabled=disabled)
    sess, api = env.token(uid), env.token(uid, "api")
    before = env.snapshot()
    resp = env.call("PATCH", tok, f"{ROUTE}/{uid}", json={field: None})
    problem(resp, 400, "invalid_request")
    assert env.snapshot() == before
    assert env.live(sess) and env.live(api)
    assert env.row(uid)["role"] == "operator"
    assert env.row(uid)["disabled"] is disabled
    assert env.row(uid)["totp_secret_enc"] is not None


# ------------------------------------------------------------ CHK-M2-231


def every_method(uid: int) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("GET", ROUTE, {}),
        (
            "POST",
            ROUTE,
            {"json": {"username": f"z-{secrets.token_hex(3)}", "password": PW}},
        ),
        ("GET", f"{ROUTE}/{uid}", {}),
        ("PATCH", f"{ROUTE}/{uid}", {"json": {"role": "operator"}}),
        ("DELETE", f"{ROUTE}/{uid}", {}),
    ]


def test_every_method_refuses_the_wrong_callers(env: Env) -> None:
    admin_id, admin_session = env.admin()
    admin_api = env.token(admin_id, "api")
    unverified = env.token(admin_id, verified=False)
    op_session = env.token(env.user("operator", totp=True))
    viewer_session = env.token(env.user("viewer"))
    target = env.user("viewer")
    callers = [
        (admin_api, "totp_session_required"),
        # restricted rule first (TASK-037)
        (unverified, "totp_enrolment_required"),
        (op_session, "forbidden"),
        (viewer_session, "forbidden"),
    ]
    for method, path, kw in every_method(target):
        for tok, type_ in callers:
            before = env.snapshot()
            problem(env.call(method, tok, path, **kw), 403, type_)
            assert env.snapshot() == before, (method, path)
    assert env.live(admin_session)  # the admin's verified session existed throughout


# ------------------------------------------------------------ CHK-M2-232


def test_sink_outage_refuses_every_method_after_15_minutes(env: Env) -> None:
    _, tok = env.admin()
    target = env.user("viewer")
    env.sink.up = False
    env.shipper.run_once()  # first failed delivery: the outage starts now
    start = env.clock.now()
    env.clock.at = start + timedelta(minutes=14, seconds=59)
    assert env.call("GET", tok, f"{ROUTE}/{target}").status_code == 200
    env.clock.at = start + timedelta(minutes=15)
    for method, path, kw in every_method(target):
        before = env.snapshot()
        problem(env.call(method, tok, path, **kw), 503, "audit_sink_unavailable")
        assert env.snapshot() == before, (method, path)
    # sign-in and /api-tokens keep working during the outage (REQ-054 (4))
    assert env.call("GET", tok, "/api/v1/api-tokens").status_code == 200
    env.sink.up = True
    for _ in range(5):
        env.clock.at += timedelta(seconds=31)
        env.shipper.run_once()
    assert env.shipper.refusing() is False
    assert env.call("GET", tok, f"{ROUTE}/{target}").status_code == 200


# ------------------------------------------------------- CHK-M2-233, -234


def test_no_hash_or_seed_in_any_response(env: Env) -> None:
    _, tok = env.admin()
    other = env.user("operator", totp=True)
    responses = [
        env.call("GET", tok),
        env.call("GET", tok, f"{ROUTE}/{other}"),
        env.call("PATCH", tok, f"{ROUTE}/{other}", json={"role": "viewer"}),
        env.call(
            "POST", tok, json={"username": f"h-{secrets.token_hex(3)}", "password": PW}
        ),
    ]
    row = env.row(other)
    assert (
        sweep([HASH, row["password_hash"], "enc:00", PW], *[r.text for r in responses])
        == []
    )
    for r in responses:
        data = r.json()
        items = data["items"] if "items" in data else [data]
        for item in items:
            assert set(item) == ITEM_KEYS


def test_after_a_reset_the_admin_signs_in_restricted(env: Env) -> None:
    _, tok = env.admin()
    other = env.user("admin", totp=True)
    env.call("PATCH", tok, f"{ROUTE}/{other}", json={"totp": None})
    name = env.row(other)["username"]
    login = env.client.post(
        "/api/v1/auth/login", json={"username": name, "password": PW}
    )
    assert login.status_code == 200 and login.json()["totp_verified"] is False
    problem(env.call("GET", login.json()["token"]), 403, "totp_enrolment_required")


# ------------------------------------------------------------ CHK-M2-235


def test_list_pagination_and_bad_ids(env: Env) -> None:
    _, tok = env.admin()
    made = [env.user() for _ in range(7)]
    seen: list[int] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = env.call("GET", tok, params=params).json()
        seen += [i["user_id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert (
        seen == sorted(seen) and set(made) <= set(seen) and len(seen) == len(set(seen))
    )
    problem(env.call("GET", tok, f"{ROUTE}/999999999"), 404, "not_found")
    for bad in ("abc", "1.5"):
        resp = env.call("GET", tok, f"{ROUTE}/{bad}")
        assert resp.status_code in (400, 404) and resp.status_code != 422


def test_timestamps_are_utc_z_with_a_non_utc_session_time_zone(
    migrated_db: PgServer, tmp_path: Path
) -> None:
    """CHK-M2-045 on /users responses (session TimeZone Asia/Singapore)."""
    params: dict[str, Any] = dict(conninfo_to_dict(migrated_db.dsn("bitscan_app")))
    params["options"] = "-c TimeZone=Asia/Singapore"
    db = AppDatabase(SecretStr(make_conninfo("", **params)), connect_timeout_s=3)
    db.open()
    clock = Clock()
    shipper = Shipper(
        PgAuditTail(db),
        DiskQueue(tmp_path / "tzq"),
        SwitchSink(),
        clock,
        DbOutageAudit(db),
    )
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=shipper,
        limits=RateLimiter(clock),
    )
    try:
        with TestClient(create_app(rt), client=("10.2.9.1", 1)) as client:
            env = Env(migrated_db, clock, SwitchSink(), shipper, client)
            _, tok = env.admin()
            uid = env.user()
            item = env.call("GET", tok, f"{ROUTE}/{uid}").json()
        assert item["created_at"].endswith("Z")
        assert datetime.fromisoformat(item["created_at"]) == T0
    finally:
        db.close()
