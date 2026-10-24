"""TP-M2-25: the M2 security suite (TS §8.3 Security row, auth part; G25, G28).

Checks CHK-M2-290 to CHK-M2-294 of tests/m2/test-plan.md.

- CHK-M2-290, -291 run in-process against create_app() on the migrated
  database: agent-prefixed tokens on every user route; API tokens of every role
  on every M2 sensitive, session-only and TOTP route.
- CHK-M2-292 to -294 share one end-to-end flow against the real `serve`
  (Linux, as G27) with the fake HTTPS audit sink and the fake vault:
  `users create-admin` (CLI) -> restricted sign-in -> TOTP enrolment -> TOTP
  sign-in -> POST /users -> POST /api-tokens -> DELETE /api-tokens/{id}, then a
  TOTP replacement, a password change, vault errors, failed sign-ins and
  logout, and serve stop.
"""

import base64
import json
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.auth.totp import code_at, step_at
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit.chain import HashInput, compute_row_hash

from .canary import new_canary, sweep
from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_totp_enrol import Cipher, Clock, Gate

pytestmark = pytest.mark.pg

PW = "security suite pass " + "word"
HASH = hash_password(PW)


# ------------------------------------------------------- in-process app (290, 291)


@dataclass
class App:
    server: PgServer
    clock: Clock
    client: TestClient
    sent: int = 0

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str, totp: bool = False) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step) VALUES (%s, %s, %s::user_role, %s, %s)"
                " RETURNING user_id",
                (
                    f"sec-{secrets.token_hex(5)}",
                    HASH,
                    role,
                    "enc:00" if totp else None,
                    5 if totp else None,
                ),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def token(self, uid: int, kind: str = "session", verified: bool = True) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        self.store(uid, tok, kind, verified)
        return tok

    def store(self, uid: int, tok: str, kind: str, verified: bool) -> None:
        """A user_token row for exactly this string (any prefix)."""
        now = self.clock.now()
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at, last_used_at) VALUES (%s, %s, %s, %s, %s,"
                " %s, %s)",
                (
                    uid,
                    kind,
                    token_hash(tok),
                    verified and kind == "session",
                    now + timedelta(days=30),
                    now,
                    now,
                ),
            )

    def call(self, method: str, path: str, token: str, body: Any = None) -> Any:
        # The failed-token limit is 20 a minute per IP (TS §6.3); move the clock
        # on so that every refusal here is the one under test, never a 429.
        self.sent += 1
        if self.sent % 10 == 0:
            self.clock.at += timedelta(seconds=61)
        kw: dict[str, Any] = {} if body is None else {"json": body}
        return self.client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kw
        )

    def snapshot(self) -> tuple[Any, ...]:
        with self.conn() as c:
            users = c.execute("SELECT * FROM app_user ORDER BY user_id").fetchall()
            toks = c.execute(
                "SELECT token_id, revoked_at FROM user_token ORDER BY token_id"
            ).fetchall()
            audit = c.execute(
                "SELECT count(*) FROM audit_log"
                " WHERE action <> 'auth.token_check_failed'"
            ).fetchone()
        return users, toks, audit


@pytest.fixture
def app(migrated_db: PgServer) -> Iterator[App]:
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
    try:
        with TestClient(create_app(rt), client=("10.3.0.1", 1)) as client:
            yield App(migrated_db, clock, client)
    finally:
        db.close()


def user_routes() -> list[tuple[str, str]]:
    """Every M2 user route from the app itself (the route walk of TASK-037),
    as path templates; sign-in takes no token."""
    out = []
    for route in api_routes(create_app().routes):
        for method in sorted(route.methods or ()):
            if not route.path.startswith("/api/v1/"):
                continue  # health routes (#5)
            if route.path.startswith("/api/v1/agent/"):
                # M3 (TASK-067 on): the agent group, with its own bsa_/bse_
                # dependency, is not a user route; its matrix is in
                # test_agent_auth_pg.py and test_enrol_api_pg.py (TS §6 L1056)
                continue
            if (method, route.path) == ("POST", "/api/v1/auth/login"):
                continue
            out.append((method, route.path))
    return sorted(set(out))


def fill(path: str, user_id: int, token_id: int) -> str:
    return path.replace("{user_id}", str(user_id)).replace("{token_id}", str(token_id))


BODIES: dict[tuple[str, str], Any] = {
    ("POST", "/api/v1/users"): {"username": "sec-new", "password": PW},
    ("PATCH", "/api/v1/users/{user_id}"): {"role": "operator"},
    ("POST", "/api/v1/api-tokens"): {"name": "x"},
    ("POST", "/api/v1/auth/password"): {
        "current_password": PW,
        "new_password": PW + " 2",
    },
    ("POST", "/api/v1/auth/totp/enrol"): {},
}
# calls that would end the control session itself
ENDS_SESSION = {("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/password")}


# ------------------------------------------------------------ CHK-M2-290


def test_every_m2_user_route_has_a_token_requirement() -> None:
    routes = user_routes()
    m2 = {  # TS §6.2 route table, the M2 part (sign-in takes no token)
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/password"),
        ("POST", "/api/v1/auth/totp/enrol"),
        ("GET", "/api/v1/api-tokens"),
        ("POST", "/api/v1/api-tokens"),
        ("DELETE", "/api/v1/api-tokens/{token_id}"),
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("GET", "/api/v1/users/{user_id}"),
        ("PATCH", "/api/v1/users/{user_id}"),
        ("DELETE", "/api/v1/users/{user_id}"),
    }
    assert m2 <= set(routes), m2 - set(routes)  # the walk sees the real routes


@pytest.mark.parametrize("prefix", ["bsa_", "bse_"])
def test_agent_tokens_are_refused_on_every_user_route(app: App, prefix: str) -> None:
    """TS §6 L1056, §2.3: user routes accept only bsu_ and bsk_. The agent-
    prefixed token has a verified admin session row stored under its own hash,
    so only the prefix rule can refuse it (not a lookup miss). The control
    shows each route is reachable: a verified admin session never gets 401.
    Path ids are a user and a token this test made (the database is shared)."""
    admin = app.user("admin", totp=True)
    session = app.token(admin)
    body64 = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    foreign = prefix + body64
    app.store(admin, foreign, "session", True)
    target = app.user("viewer")
    with app.conn() as c:
        app.token(admin, "api")
        row = c.execute(
            "SELECT max(token_id) FROM user_token WHERE user_id = %s", (admin,)
        ).fetchone()
    assert row is not None
    own_token = int(row[0])
    for method, template in user_routes():
        path = fill(template, target, own_token)
        before = app.snapshot()
        body = BODIES.get((method, template))
        resp = app.call(method, path, foreign, body)
        assert resp.status_code == 401, (method, path, resp.text)
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert app.snapshot() == before, (method, path)
    for method, template in user_routes():
        if (method, template) in ENDS_SESSION:
            continue
        body = BODIES.get((method, template))
        resp = app.call(method, fill(template, target, own_token), session, body)
        assert resp.status_code != 401, (method, template, resp.text)


# ------------------------------------------------------------ CHK-M2-291


SENSITIVE: list[tuple[str, str, Any]] = [
    ("GET", "/api/v1/users", None),
    ("POST", "/api/v1/users", {"username": "sec-x", "password": PW}),
    ("GET", "/api/v1/users/{target}", None),
    ("PATCH", "/api/v1/users/{target}", {"role": "operator"}),
    ("PATCH", "/api/v1/users/{target}", {"revoke_tokens": True}),
    ("PATCH", "/api/v1/users/{target}", {"totp": None}),
    ("DELETE", "/api/v1/users/{target}", None),
    ("POST", "/api/v1/api-tokens", {"name": "from-api"}),  # token creation
    ("POST", "/api/v1/auth/totp/enrol", {}),  # TOTP enrolment start
    (
        "POST",
        "/api/v1/auth/totp/enrol",
        {"current_password": PW, "current_code": "123456"},
    ),  # replace
    ("POST", "/api/v1/auth/totp/enrol", {"totp_code": "123456"}),  # confirm
    (
        "POST",
        "/api/v1/auth/password",
        {"current_password": PW, "new_password": PW + " 2"},
    ),  # session only
]


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_api_tokens_are_refused_for_sensitive_actions(app: App, role: str) -> None:
    """TS §6.2: sensitive actions need a TOTP-verified session; an API token
    can never create API tokens or enrol or replace TOTP. Each role's own
    bsk_ token, while the same user also holds a verified session."""
    uid = app.user(role, totp=True)
    api = app.token(uid, "api")
    app.token(uid)  # a verified session exists too: the API token still fails
    target = app.user("viewer", totp=True)
    app.token(target)
    app.token(target, "api")
    for method, path, body in SENSITIVE:
        concrete = path.replace("{target}", str(target))
        before = app.snapshot()
        resp = app.call(method, concrete, api, body)
        assert resp.status_code == 403, (role, method, concrete, resp.text)
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert app.snapshot() == before, (role, method, concrete)
    # the API token itself still works where API tokens are allowed
    assert app.call("GET", "/api/v1/api-tokens", api).status_code == 200


# ------------------------------------------------- end-to-end flow (292 to 294)


@dataclass
class Step:
    label: str
    status: int
    body: bytes
    own: list[str] = field(default_factory=list)  # the one-time secret it carries


@dataclass
class Flow:
    server: PgServer
    start_id: int
    end_id: int
    steps: list[Step]
    cli: list[str]
    output: str
    posts: list[dict[str, Any]]
    canaries: list[str]
    tokens: list[str]
    api_token_id: int
    api_token: str


class Totp:
    """Codes for one user: each step is used once (totp_last_step is per
    user), so a new code is always a newer step, waiting when none is left."""

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


def seed_of(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def max_audit_id(server: PgServer) -> int:
    with server.connect("bitscan_app") as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture(scope="module")
def flow(
    migrated_db: PgServer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Flow]:
    from .certs import make_pki
    from .fake_sink import https_sink, server_context
    from .fake_vault import fake_vault
    from .test_cli_users_pg import run as run_users
    from .test_serve_linux import (
        CANARY_VAULT,
        env_for,
        free_port,
        https_get,
        start,
        wait_ready,
    )

    tmp = tmp_path_factory.mktemp("e2e")
    pki = make_pki(tmp / "pki")
    admin_pw, viewer_pw, viewer_pw2 = (new_canary(k) for k in ("adm", "vw", "vw2"))
    bad_pw, bad_pw2, vault_err = (new_canary(k) for k in ("bad", "bad2", "verr"))
    admin, viewer = f"e2e-adm-{secrets.token_hex(3)}", f"e2e-vw-{secrets.token_hex(3)}"
    dsn_pw = [
        str(conninfo_to_dict(migrated_db.dsn(r))["password"])
        for r in ("bitscan_app", "bitscan_retention")
    ]
    steps: list[Step] = []
    cli: list[str] = []
    tokens: list[str] = []
    secrets_seen: list[str] = []
    sink_leaf, vault_leaf, serve_leaf = (pki.leaf(n) for n in ("sink", "vault", "srv"))
    with (
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(
            server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT
        ) as vault,
    ):
        port = free_port()
        env = env_for(
            migrated_db,
            tmp,
            pki,
            serve_leaf,
            f"https://localhost:{sink.port}/audit",
            port,
            BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{vault.port}",
        )
        start_id = max_audit_id(migrated_db)
        made = run_users(
            ["create-admin", admin], tmp / "creds" / "app_dsn", stdin=admin_pw + "\n"
        )
        assert made.returncode == 0, made.stderr
        cli += [made.stdout, made.stderr]
        s = start(env, tmp, port, pki, serve_leaf)
        try:
            wait_ready(s)

            def call(
                label: str,
                method: str,
                path: str,
                token: str | None = None,
                body: Any = None,
            ) -> Step:
                headers = {"Content-Type": "application/json"}
                if token is not None:
                    headers["Authorization"] = f"Bearer {token}"
                data = None if body is None else json.dumps(body).encode()
                status, _, out = https_get(port, s.ca, path, headers, data, method)
                step = Step(label, status, out)
                steps.append(step)
                return step

            def issued(step: Step, key: str) -> str:
                value = str(json.loads(step.body)[key])
                step.own.append(value)
                return value

            totp = Totp()
            login = "/api/v1/auth/login"
            enrol = "/api/v1/auth/totp/enrol"
            # restricted first sign-in of the CLI admin
            st = call(
                "login-restricted",
                "POST",
                login,
                body={"username": admin, "password": admin_pw},
            )
            assert st.status == 200 and json.loads(st.body)["totp_verified"] is False
            s1 = issued(st, "token")
            st = call("enrol-start", "POST", enrol, s1, {})
            assert st.status == 200, st.body
            secret_a = issued(st, "secret")
            seed_a = seed_of(secret_a)
            st = call(
                "enrol-confirm", "POST", enrol, s1, {"totp_code": totp.code(seed_a)}
            )
            assert st.status == 200 and json.loads(st.body)["totp_verified"] is True
            s2 = issued(st, "token")
            st = call(
                "login-totp",
                "POST",
                login,
                body={
                    "username": admin,
                    "password": admin_pw,
                    "totp_code": totp.code(seed_a),
                },
            )
            assert st.status == 200 and json.loads(st.body)["totp_verified"] is True
            s3 = issued(st, "token")
            st = call(
                "user-create",
                "POST",
                "/api/v1/users",
                s3,
                {"username": viewer, "password": viewer_pw, "role": "operator"},
            )
            assert st.status == 201, st.body
            st = call(
                "api-token-create", "POST", "/api/v1/api-tokens", s3, {"name": "e2e"}
            )
            assert st.status == 201, st.body
            k1 = issued(st, "token")
            k1_id = int(json.loads(st.body)["token_id"])
            st = call("api-token-list", "GET", "/api/v1/api-tokens", k1)
            assert st.status == 200, st.body
            st = call("api-token-delete", "DELETE", f"/api/v1/api-tokens/{k1_id}", s3)
            assert st.status == 204, st.body
            # TOTP replacement: current password and a current code
            st = call(
                "replace-start",
                "POST",
                enrol,
                s3,
                {"current_password": admin_pw, "current_code": totp.code(seed_a)},
            )
            assert st.status == 200, st.body
            secret_b = issued(st, "secret")
            st = call(
                "replace-confirm",
                "POST",
                enrol,
                s3,
                {"totp_code": totp.code(seed_of(secret_b))},
            )
            assert st.status == 200, st.body
            s4 = issued(st, "token")
            # a password change by the new user
            st = call(
                "viewer-login",
                "POST",
                login,
                body={"username": viewer, "password": viewer_pw},
            )
            assert st.status == 200, st.body
            v1 = issued(st, "token")
            st = call(
                "password-change",
                "POST",
                "/api/v1/auth/password",
                v1,
                {"current_password": viewer_pw, "new_password": viewer_pw2},
            )
            assert st.status == 204, st.body
            st = call(
                "viewer-login-2",
                "POST",
                login,
                body={"username": viewer, "password": viewer_pw2},
            )
            assert st.status == 200, st.body
            v2 = issued(st, "token")
            # vault errors: the vault answers 500 with a canary in its body
            vault.mode, vault.status = "status", 500
            vault.raw = json.dumps({"errors": [vault_err]}).encode()
            st = call(
                "login-vault-down",
                "POST",
                login,
                body={
                    "username": admin,
                    "password": admin_pw,
                    "totp_code": totp.code(seed_of(secret_b)),
                },
            )
            assert st.status != 200, st.body
            vault.mode = "good"
            # failed sign-ins (last, so back-off cannot touch the steps above)
            st = call(
                "login-unknown",
                "POST",
                login,
                body={"username": f"ghost-{secrets.token_hex(3)}", "password": bad_pw},
            )
            assert st.status == 401, st.body
            st = call(
                "login-wrong",
                "POST",
                login,
                body={"username": viewer, "password": bad_pw2},
            )
            assert st.status == 401, st.body
            for tok in (s4, v2):
                st = call("logout", "POST", "/api/v1/auth/logout", tok)
                assert st.status == 204, st.body
            end_id = max_audit_id(migrated_db)
            # ids can have gaps (a rolled-back insert uses a sequence value), so
            # wait for the committed ids themselves, from the first one on
            want = {r[0] for r in db_rows(migrated_db, 1, end_id)}
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                ids = {json.loads(p.body)["audit_id"] for p in list(sink.posts)}
                if want <= ids:
                    break
                time.sleep(0.5)
        finally:
            if s.proc.poll() is None:
                s.stop()
        posts = [json.loads(p.body) for p in sink.posts]
        tokens = [s1, s2, s3, s4, v1, v2, k1]
        secrets_seen = [secret_a, secret_b]
        yield Flow(
            server=migrated_db,
            start_id=start_id,
            end_id=end_id,
            steps=steps,
            cli=cli,
            output=s.output(),
            posts=posts,
            canaries=[
                admin_pw,
                viewer_pw,
                viewer_pw2,
                bad_pw,
                bad_pw2,
                vault_err,
                CANARY_VAULT,
                *dsn_pw,
                *secrets_seen,
                *tokens,
                *(t[4:] for t in tokens),
            ],
            tokens=tokens,
            api_token_id=k1_id,
            api_token=k1,
        )


def db_rows(server: PgServer, first: int, last: int) -> list[tuple[Any, ...]]:
    with server.connect("bitscan_app") as c:
        return c.execute(
            "SELECT audit_id, actor, action, target, detail::text,"
            " to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
            " prev_hash, row_hash FROM audit_log"
            " WHERE audit_id BETWEEN %s AND %s ORDER BY audit_id",
            (first, last),
        ).fetchall()


# ------------------------------------------------------------ CHK-M2-292


def test_end_to_end_every_entry_reaches_the_sink_as_one_chain(flow: Flow) -> None:
    ids = [p["audit_id"] for p in flow.posts]
    assert ids == sorted(ids) and len(ids) == len(set(ids)), "order or duplicates"
    by_id = {p["audit_id"]: p for p in flow.posts}
    # every committed entry, from the start of the database, arrives once
    committed = db_rows(flow.server, 1, flow.end_id)
    assert [r[0] for r in committed if r[0] not in by_id] == []
    for audit_id, actor, action, target, detail, at, prev, row in committed:
        p = by_id[audit_id]
        assert (p["actor"], p["action"], p["target"]) == (actor, action, target)
        assert (p["detail_text"], p["at_text"]) == (detail, at)
        assert (p["prev_hash"], p["row_hash"]) == (prev, row)
    # the flow's window re-hashes and links (the entry before it included)
    window = [by_id[r[0]] for r in committed if r[0] >= flow.start_id]
    assert len(window) >= 12
    for before, entry in zip(window, window[1:], strict=False):
        assert entry["prev_hash"] == before["row_hash"], entry["audit_id"]
    for entry in window:
        again = compute_row_hash(
            entry["prev_hash"],
            HashInput(
                entry["audit_id"],
                entry["actor"],
                entry["action"],
                entry["target"],
                entry["detail_text"],
                entry["at_text"],
            ),
        )
        assert again == entry["row_hash"], entry["audit_id"]
    flow_entries = [by_id[r[0]] for r in committed if r[0] > flow.start_id]
    kinds = {
        json.loads(e["detail_text"]).get("alert_kind")
        for e in flow_entries
        if e["detail_text"] and json.loads(e["detail_text"]).get("alert") is True
    }
    assert {
        "admin_created",
        "totp_enrolled",
        "user_created",
        "api_token_created",
        "totp_replaced",
    } <= kinds
    actions = [(e["actor"], e["action"]) for e in flow_entries]
    assert actions[0] == ("cli:root", "user.create")
    for action in ("api_token.revoke", "auth.password_change"):
        assert any(a == action for _, a in actions), action


# ------------------------------------------------------- CHK-M2-293 (G28)


def test_canary_sweep_over_the_whole_flow(flow: Flow) -> None:
    out = flow.output
    assert '"bitscan_manager.access"' in out  # the log really was captured
    for line in out.splitlines():
        if line.strip():
            json.loads(line)
    assert sweep(flow.canaries, out) == []
    assert sweep(flow.canaries, *flow.cli) == []
    for step in flow.steps:
        for own in step.own:  # one-time responses carry exactly their own secret
            assert own in step.body.decode(), step.label
        others = [c for c in flow.canaries if all(c not in o for o in step.own)]
        assert sweep(others, step.body) == [], step.label
    assert sweep(flow.canaries, *(json.dumps(p) for p in flow.posts)) == []
    with flow.server.connect("bitscan_app") as c:
        details = c.execute(
            "SELECT detail::text FROM audit_log WHERE audit_id > %s",
            (flow.start_id,),
        ).fetchall()
    assert sweep(flow.canaries, *(d[0] or "" for d in details)) == []


# ------------------------------------------------------------ CHK-M2-294


def test_no_raw_token_at_rest_in_any_text_column(flow: Flow) -> None:
    """Every text, varchar, char, json and jsonb column of every public table,
    read as bitscan_owner (bitscan_migrate, SET ROLE)."""
    needles = [*flow.tokens, *(t[4:] for t in flow.tokens)]
    hits: list[tuple[str, str]] = []
    found_hash = False
    with flow.server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cols = c.execute(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c"
            " JOIN information_schema.tables t USING (table_schema, table_name)"
            " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
            " AND c.data_type IN ('text', 'character varying', 'character',"
            " 'json', 'jsonb') ORDER BY 1, 2"
        ).fetchall()
        assert ("user_token", "token_hash") in cols
        for table, column in cols:
            query = sql.SQL(
                "SELECT count(*) FROM {} WHERE strpos({}::text, %s) > 0"
            ).format(sql.Identifier(table), sql.Identifier(column))
            for needle in needles:
                row = c.execute(query, (needle,)).fetchone()
                if row is not None and row[0]:
                    hits.append((f"{table}.{column}", needle[:8]))
            if (table, column) == ("user_token", "token_hash"):
                row = c.execute(query, (token_hash(flow.api_token),)).fetchone()
                found_hash = row is not None and row[0] == 1
    assert hits == []
    assert found_hash  # the scan reads the columns: the stored hash is found
