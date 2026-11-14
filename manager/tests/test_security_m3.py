"""TP-M3-35: the M3 security suite (TS §8.3 Security row, agent part; G28, G31).

Checks CHK-M3-301, -302, -303 and -317 of tests/m3/test-plan.md.

- CHK-M3-301 and -303 run in-process against create_app() on the migrated
  database with a fake clock: tokens on the wrong route group (every route,
  real rows), and no issued token at rest after 20 enrolments, 5 rotations and
  5 enrolment tokens.
- CHK-M3-317 and -302 share one chain against the real `serve` (Linux, as
  G27) with the fake HTTPS audit sink and the fake vault: create a `bse_`
  (TOTP session) -> enrol held -> approve -> heartbeat -> pull the inventory job
  -> a results post (409) -> upload -> GET /agents/{id} shows os_info and the
  snapshot -> rotate -> use the new token -> revoke -> both tokens 401, plus
  failures, then the canary sweep over every log line, response, audit detail
  and sink payload.

Expected values come from the spec and the answers, not from the code: TS §6
L1056 and §2.3 L118 (route groups), §6.1 L1062-L1070, §6.2 L1083 (only hashes
stored), §3.2 L183-L190 (enrolment, approval, rotation), §3.3 L202 (the
heartbeat response is configuration only), §3.4 L230-L240, §6.5, §8.4 L1287
(no token or output in logs), #25 (a) (`last_error` only in one INFO record with
the agent_id), #59 (one 401 `unauthorized` for a wrong or refused token), #62,
#69, #71, REQ-062 (2)-(3), REQ-063 (3), (5), REQ-087 (1)-(2).
"""

import base64
import gzip
import json
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .canary import new_canary, sweep
from .conftest import PgServer
from .contract import loader
from .test_auth_dependencies import api_routes
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
V1 = "/api/v1"
PW = "m3 security suite " + "pass"
HASH = hash_password(PW)
FIX = loader.FIXTURES


def iso(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def gz(doc: Any) -> bytes:
    return gzip.compress(json.dumps(doc).encode(), mtime=0)


def fixture(*parts: str) -> Any:
    return json.loads(FIX.joinpath(*parts).read_text(encoding="utf-8"))


def enrol_body(machine: str | None = None) -> dict[str, Any]:
    base: dict[str, Any] = fixture("enrol", "request_valid_full.json")
    return base | {
        "hostname": f"sec3-{secrets.token_hex(3)}",
        "machine_id": machine or secrets.token_hex(16),
    }


def heartbeat_body(at: datetime, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = fixture("heartbeat", "request_valid_full.json")
    return (
        base | {"clock": iso(at), "current_job_id": None, "runner_helpers": []} | over
    )


def package(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "version": "1.0-1",
        "architecture": "amd64",
        "status": "install ok installed",
        "source": None,
        "installed_size_kb": 12,
    }


def inventory(names: list[str], raw: dict[str, Any] | None = None) -> dict[str, Any]:
    pk = [package(n) for n in names]
    os_info = fixture("inventory", "request_valid_multi_arch.json")["os_info"]
    if raw is not None:
        os_info = os_info | {"raw": raw}
    return {"os_info": os_info, "packages": pk, "list_sha256": loader.list_sha256(pk)}


def results_body(stdout: str, stderr: str) -> dict[str, Any]:
    return {
        "results": [
            {
                "plugin_uuid": str(uuid4()),
                "exit_code": 0,
                "stdout": stdout,
                "stderr": stderr,
                "started_at": iso(T0),
                "finished_at": iso(T0),
                "timed_out": False,
                "truncated": False,
                "error": None,
            }
        ],
        "final": True,
    }


def problem(r: Any, status: int, type_: str | None = None) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    if type_ is not None:
        assert r.json()["type"] == type_, r.json()


# ------------------------------------------------------- in-process app (301, 303)


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Agent:
    agent_id: str
    token: str
    machine_id: str


@dataclass
class Env:
    server: PgServer
    clock: Clock
    app: FastAPI
    _ip: int = 0
    clients: list[TestClient] = field(default_factory=list)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def ip(self) -> str:
        """A new source address per call, so per-IP limits never mix."""
        self._ip += 1
        return f"10.93.{self._ip // 256}.{self._ip % 256}"

    def call(
        self,
        method: str,
        path: str,
        token: str | None,
        *,
        body: Any = None,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
        ip: str | None = None,
    ) -> Any:
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        c = TestClient(
            self.app, client=(ip or self.ip(), 1), raise_server_exceptions=False
        )
        self.clients.append(c)
        kw: dict[str, Any] = {}
        if raw is not None:
            kw["content"] = raw
        elif body is not None:
            kw["json"] = body
        return c.request(method, path, headers=h, **kw)

    def user(self, role: str = "admin") -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, %s, %s::user_role, 'enc:00',"
                " 5, %s) RETURNING user_id",
                (f"sec3-{secrets.token_hex(5)}", HASH, role, T0 - timedelta(days=1)),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def store(self, uid: int, tok: str, kind: str) -> int:
        """A verified user_token row for exactly this string (any prefix)."""
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at, last_used_at) VALUES (%s, %s, %s, %s, %s,"
                " %s, %s) RETURNING token_id",
                (
                    uid,
                    kind,
                    token_hash(tok),
                    kind == "session",
                    self.clock.now() + timedelta(days=30),
                    self.clock.now(),
                    self.clock.now(),
                ),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def session(self, uid: int) -> str:
        tok = new_token(TokenKind.SESSION)
        self.store(uid, tok, "session")
        return tok

    def api(self, uid: int) -> tuple[str, int]:
        tok = new_token(TokenKind.API)
        return tok, self.store(uid, tok, "api")

    def agent(self) -> Agent:
        tok = new_agent_token(AgentTokenKind.AGENT)
        machine = secrets.token_hex(16)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
                " token_issued_at, token_expires_at, status, enrolled_at,"
                " last_heartbeat_at) VALUES (%s, %s, '1.0.0', %s, %s, %s, 'online',"
                " %s, %s) RETURNING agent_id",
                (
                    machine,
                    f"sec3-{secrets.token_hex(3)}",
                    token_hash(tok),
                    T0 - timedelta(days=10),
                    T0 + timedelta(days=355),
                    T0 - timedelta(days=10),
                    T0 - timedelta(minutes=1),
                ),
            ).fetchone()
        assert row is not None
        return Agent(str(row[0]), tok, machine)

    def enrolment_token(self, auto: bool = False) -> tuple[int, str]:
        tok = new_agent_token(AgentTokenKind.ENROLMENT)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO enrollment_token (token_hash, max_uses, auto_approve,"
                " expires_at, created_by) VALUES (%s, 10, %s, %s, 1)"
                " RETURNING token_id",
                (token_hash(tok), auto, T0 + timedelta(days=1)),
            ).fetchone()
        assert row is not None
        return int(row[0]), tok

    def requests_of(self, agent_id: str) -> list[int]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT request_id FROM enrollment_request WHERE agent_id = %s"
                " ORDER BY request_id",
                (agent_id,),
            ).fetchall()
        return [int(r[0]) for r in rows]

    def snapshot(self) -> tuple[Any, ...]:
        """Every row an agent or user route could change (refused = none)."""
        out: list[Any] = []
        with self.conn() as c:
            for table, order in (
                ("agent", "agent_id"),
                ("agent_ip_seen", "agent_id, ip"),
                ("agent_tag", "agent_id, tag"),
                ("os_info", "agent_id"),
                ("enrollment_token", "token_id"),
                ("enrollment_request", "request_id"),
                ("app_user", "user_id"),
                ("setting", "key"),
                ("system_schedule", "job_kind"),
            ):
                out.append(
                    c.execute(
                        sql.SQL("SELECT * FROM {} ORDER BY {}").format(
                            sql.Identifier(table), sql.SQL(order)
                        )
                    ).fetchall()
                )
            out.append(
                c.execute(
                    "SELECT token_id, revoked_at FROM user_token ORDER BY token_id"
                ).fetchall()
            )
            out.append(
                c.execute(
                    "SELECT job_id, agent_id, kind, state FROM scan_job ORDER BY job_id"
                ).fetchall()
            )
            for table in ("agent_package", "package", "inventory_snapshot"):
                out.append(
                    c.execute(
                        sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                    ).fetchone()
                )
            out.append(
                c.execute(
                    "SELECT count(*) FROM audit_log"
                    " WHERE action <> 'auth.token_check_failed'"
                ).fetchone()
            )
        return tuple(out)


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
    e = Env(migrated_db, clock, create_app(rt))
    try:
        yield e
    finally:
        for c in e.clients:
            c.close()
        db.close()


def walk() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(agent operations, user operations) from the app's own route walk; sign-in
    takes no token and the health routes are outside the groups (#5)."""
    agent: set[tuple[str, str]] = set()
    user: set[tuple[str, str]] = set()
    for route in api_routes(create_app().routes):
        for method in route.methods or ():
            if not route.path.startswith(V1 + "/"):
                continue
            if route.path.startswith(V1 + "/agent/"):
                agent.add((method, route.path))
            elif (method, route.path) != ("POST", V1 + "/auth/login"):
                user.add((method, route.path))
    return sorted(agent), sorted(user)


# ------------------------------------------------------------ CHK-M3-301


def agent_request(
    a: Agent, method: str, template: str, job: str, at: datetime
) -> dict[str, Any]:
    """The path, headers and a valid body for one agent operation."""
    path = template.replace("{id}", a.agent_id).replace("{job_id}", job)
    headers = {"X-Bitscan-Machine-Id": a.machine_id}
    kw: dict[str, Any] = {"headers": headers}
    if template.endswith("/enroll"):
        kw["body"] = enrol_body()
    elif template.endswith("/heartbeat"):
        kw["body"] = heartbeat_body(at)
    elif template.endswith("/results"):
        kw["body"] = results_body("ok", "")
    elif template.endswith("/inventory"):
        kw["raw"] = gz(inventory(["sec3-pkg"]))
        headers |= {"Content-Type": "application/json", "Content-Encoding": "gzip"}
    return {"method": method, "path": path, **kw}


def test_user_and_wrong_agent_tokens_are_refused_on_every_agent_route(
    env: Env,
) -> None:
    """REQ-062 (2): on every agent route a valid admin bsu_ and bsk_, a bse_ on
    a bsa_ route and a bsa_ on enrol each get one 401 `unauthorized` (#59) and
    change nothing. Every token is a real row: the session and API token are a
    verified admin's, the bsa_ is an online agent's, the bse_ a usable
    enrolment token. The control shows each route answers the right token."""
    agent_ops, _ = walk()
    assert len(agent_ops) == 6
    a = env.agent()
    _, bse = env.enrolment_token()
    admin = env.user()
    bsu = env.session(admin)
    bsk, _ = env.api(admin)
    job = str(uuid4())
    for method, template in agent_ops:
        enrol = template.endswith("/enroll")
        wrong = [bsu, bsk, a.token if enrol else bse]
        for tok in wrong:
            before = env.snapshot()
            req = agent_request(a, method, template, job, T0)
            r = env.call(req.pop("method"), req.pop("path"), tok, **req)
            problem(r, 401, "unauthorized")
            assert env.snapshot() == before, (method, template, tok[:4])
    # control: the right token reaches each route (no 401)
    want = {
        "/enroll": 200,
        "/heartbeat": 200,
        "/jobs": 200,
        "/results": 409,
        "/inventory": 204,
        "/rotate": 403,  # outside the rotation window
    }
    for method, template in agent_ops:
        tok = bse if template.endswith("/enroll") else a.token
        req = agent_request(a, method, template, job, T0)
        r = env.call(req.pop("method"), req.pop("path"), tok, **req)
        status = next(v for k, v in want.items() if template.endswith(k))
        assert r.status_code == status, (method, template, r.text)


USER_BODIES: dict[tuple[str, str], Any] = {
    ("POST", V1 + "/users"): {"username": "sec3-new", "password": PW},
    ("PATCH", V1 + "/users/{user_id}"): {"role": "operator"},
    ("POST", V1 + "/api-tokens"): {"name": "x"},
    ("POST", V1 + "/auth/password"): {"current_password": PW, "new_password": PW + "2"},
    ("POST", V1 + "/auth/totp/enrol"): {},
    ("PUT", V1 + "/agents/{id}/tags"): {"tags": ["sec3"]},
    ("POST", V1 + "/enrollment-tokens"): {},
}
ENDS_SESSION = {("POST", V1 + "/auth/logout"), ("POST", V1 + "/auth/password")}


@pytest.mark.parametrize("prefix", ["bsa_", "bse_"])
def test_real_agent_tokens_are_refused_on_every_user_route(
    env: Env, prefix: str
) -> None:
    """REQ-062 (3) (M2 REQ-044 (1) re-run with real rows): the bsa_ of a real
    online agent and the bse_ of a real usable enrolment token get 401 on
    every user route, and nothing changes. A verified admin session row is
    also stored under that exact token's hash, so only the prefix rule can
    refuse it. Path ids are real rows this test made; the control shows each
    route is reachable with a verified admin session."""
    _, user_ops = walk()
    assert len(user_ops) >= 27
    a = env.agent()
    et_id, bse = env.enrolment_token()
    admin = env.user()
    session = env.session(admin)
    _, api_id = env.api(admin)
    target = env.user("viewer")
    held_id, held = env.enrolment_token()
    r = env.call("POST", V1 + "/agent/enroll", held, body=enrol_body())
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    request_id = env.requests_of(r.json()["agent_id"])[0]
    foreign = a.token if prefix == "bsa_" else bse
    env.store(admin, foreign, "session")
    with env.conn() as c:
        row = c.execute("SELECT value FROM setting WHERE key = 'job_pull_seconds'")
        current = row.fetchone()
    assert current is not None
    bodies = USER_BODIES | {
        ("PATCH", V1 + "/settings"): {"job_pull_seconds": current[0]}
    }

    def fill(template: str) -> str:
        tid = et_id if "/enrollment-tokens/" in template else api_id
        return (
            template.replace("{id}", a.agent_id)
            .replace("{user_id}", str(target))
            .replace("{token_id}", str(tid))
            .replace("{request_id}", str(request_id))
        )

    for method, template in user_ops:
        before = env.snapshot()
        r = env.call(
            method, fill(template), foreign, body=bodies.get((method, template))
        )
        problem(r, 401)
        assert env.snapshot() == before, (method, template)
    for method, template in user_ops:
        if (method, template) in ENDS_SESSION:
            continue
        r = env.call(
            method, fill(template), session, body=bodies.get((method, template))
        )
        assert r.status_code != 401, (method, template, r.text)
    assert held_id != et_id


# ------------------------------------------------------------ CHK-M3-303


def test_no_issued_token_at_rest_after_enrolments_and_rotations(env: Env) -> None:
    """REQ-063 (3): after 5 enrolment tokens (created through the API), 20
    enrolments (auto-approved, approved, rejected and held) and 5 rotations
    (one with a lost-response retry, three new tokens used), no text, char or
    JSON column of any table, audit_log.detail included, holds any issued
    token, with or without its prefix. Control: the hashes are found."""
    admin = env.user()
    s = env.session(admin)
    made: list[str] = []
    for body in (
        {"max_uses": 10, "auto_approve": True},
        {"max_uses": 10, "auto_approve": True},
        {"max_uses": 10},
        {"max_uses": 5, "allowed_cidrs": ["10.93.0.0/16"]},
        {},
    ):
        r = env.call("POST", V1 + "/enrollment-tokens", s, body=body)
        assert r.status_code == 201, r.text
        made.append(r.json()["token"])
    assert len(set(made)) == 5
    agents: list[Agent] = []
    held: list[Agent] = []
    plan = [made[0]] * 6 + [made[1]] * 6 + [made[2]] * 4 + [made[3]] * 3 + [made[4]]
    for tok in plan:
        mid = secrets.token_hex(16)
        r = env.call("POST", V1 + "/agent/enroll", tok, body=enrol_body(mid))
        assert r.status_code == 200, r.text
        got = Agent(r.json()["agent_id"], r.json()["agent_token"], mid)
        (agents if r.json()["status"] == "enrolled" else held).append(got)
    assert (len(agents), len(held)) == (12, 8)
    decide = [("approve", held[0]), ("approve", held[1]), ("reject", held[2])]
    for verb, target in decide:
        rid = env.requests_of(target.agent_id)[0]
        r = env.call("POST", f"{V1}/enrollment-requests/{rid}/{verb}", s)
        assert r.status_code == 200, r.text
    issued = [*made, *(x.token for x in agents + held)]
    # rotations: inside the window of a 365-day token (issued + 335 days)
    env.clock.at = T0 + timedelta(days=336)
    rotated: list[str] = []
    for i, x in enumerate(agents[:5]):
        path = f"{V1}/agent/{x.agent_id}/token/rotate"
        h = {"X-Bitscan-Machine-Id": x.machine_id}
        r = env.call("POST", path, x.token, headers=h)
        assert r.status_code == 200, r.text
        rotated.append(r.json()["agent_token"])
        if i == 0:  # lost response: retry with the old token
            r = env.call("POST", path, x.token, headers=h)
            assert r.status_code == 200, r.text
            rotated.append(r.json()["agent_token"])
        if i < 3:  # first use of the newest token starts the overlap
            r = env.call("GET", f"{V1}/agent/{x.agent_id}/jobs", rotated[-1], headers=h)
            assert r.status_code == 200, r.text
    issued += rotated
    assert len(set(issued)) == len(issued) == 5 + 20 + 6
    needles = [*issued, *(t[4:] for t in issued), s, s[4:]]
    hits: list[tuple[str, str]] = []
    found: set[tuple[str, str]] = set()
    controls = {
        token_hash(made[0]): ("enrollment_token", "token_hash"),
        token_hash(rotated[-1]): ("agent", "token_hash"),
        token_hash(agents[2].token): ("agent", "prev_token_hash"),
        token_hash(held[5].token): ("enrollment_request", "new_token_hash"),
    }
    with env.server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cols = c.execute(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c"
            " JOIN information_schema.tables t USING (table_schema, table_name)"
            " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
            " AND c.data_type IN ('text', 'character varying', 'character',"
            " 'json', 'jsonb') ORDER BY 1, 2"
        ).fetchall()
        assert ("audit_log", "detail") in cols
        assert ("enrollment_request", "new_token_hash") in cols
        for table, column in cols:
            query = sql.SQL(
                "SELECT count(*) FROM {} WHERE strpos({}::text, %s) > 0"
            ).format(sql.Identifier(table), sql.Identifier(column))
            for needle in needles:
                row = c.execute(query, (needle,)).fetchone()
                if row is not None and row[0]:
                    hits.append((f"{table}.{column}", needle[:8]))
            for digest, where in controls.items():
                if where == (table, column):
                    row = c.execute(query, (digest,)).fetchone()
                    if row is not None and row[0] == 1:
                        found.add(where)
    assert hits == []
    assert found == set(controls.values())  # the scan reads the right columns


# ------------------------------------------------- serve chain (317, 302; G28)


@dataclass
class Step:
    label: str
    status: int
    body: bytes
    own: list[str] = field(default_factory=list)  # the one-time secret it carries
    data: list[str] = field(default_factory=list)  # canaries it may echo as data


@dataclass
class Chain:
    server: PgServer
    start_id: int
    steps: list[Step]
    output: str
    posts: list[dict[str, Any]]
    tokens: list[str]
    secrets: list[str]
    agent_id: str
    job_id: str
    last_error: str
    rows: dict[str, Any]


class Totp:
    def __init__(self) -> None:
        self.used = -1

    def code(self, seed: bytes) -> str:
        from bitscan_manager.auth.totp import code_at, step_at

        while True:
            now = step_at(datetime.now(UTC))
            for step in (now, now + 1):
                if step > self.used:
                    self.used = step
                    return code_at(seed, step)
            time.sleep(0.5)


def owner(server: PgServer, statement: str, params: tuple[Any, ...]) -> list[Any]:
    with server.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cur = c.execute(statement, params)  # fixed test statements only
        return cur.fetchall() if cur.description else []


def max_audit_id(server: PgServer) -> int:
    with server.connect("bitscan_app") as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture(scope="module")
def chain(  # noqa: PLR0915
    migrated_db: PgServer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Chain]:
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

    tmp = tmp_path_factory.mktemp("m3chain")
    pki = make_pki(tmp / "pki")
    admin_pw = new_canary("adm")
    stdout, stderr = new_canary("stdout"), new_canary("stderr")
    pkg_name = new_canary("pkg").lower()  # a valid Debian package name
    raw_value = new_canary("raw")
    last_error = new_canary("lasterr")
    admin = f"m3c-adm-{secrets.token_hex(3)}"
    steps: list[Step] = []
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
        s = start(env, tmp, port, pki, serve_leaf)
        try:
            wait_ready(s)

            def call(
                label: str,
                method: str,
                path: str,
                token: str | None = None,
                body: Any = None,
                raw: bytes | None = None,
                headers: dict[str, str] | None = None,
            ) -> Step:
                h = {"Content-Type": "application/json"} | (headers or {})
                if token is not None:
                    h["Authorization"] = f"Bearer {token}"
                data = (
                    raw
                    if raw is not None
                    else (None if body is None else json.dumps(body).encode())
                )
                status, _, out = https_get(port, s.ca, path, h, data, method)
                step = Step(label, status, out)
                steps.append(step)
                return step

            def issued(step: Step, key: str) -> str:
                value = str(json.loads(step.body)[key])
                step.own.append(value)
                return value

            def now() -> datetime:
                return datetime.now(UTC)

            totp = Totp()
            login = V1 + "/auth/login"
            enrol_totp = V1 + "/auth/totp/enrol"
            st = call(
                "login-restricted",
                "POST",
                login,
                body={"username": admin, "password": admin_pw},
            )
            assert st.status == 200, st.body
            s1 = issued(st, "token")
            st = call("totp-start", "POST", enrol_totp, s1, {})
            assert st.status == 200, st.body
            secret = issued(st, "secret")
            seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
            st = call(
                "totp-confirm", "POST", enrol_totp, s1, {"totp_code": totp.code(seed)}
            )
            assert st.status == 200, st.body
            s2 = issued(st, "token")
            st = call(
                "login-totp",
                "POST",
                login,
                body={
                    "username": admin,
                    "password": admin_pw,
                    "totp_code": totp.code(seed),
                },
            )
            assert st.status == 200, st.body
            S = issued(st, "token")
            st = call("api-token", "POST", V1 + "/api-tokens", S, {"name": "m3c"})
            assert st.status == 201, st.body
            K = issued(st, "token")
            # 1. create a bse_ with a TOTP session
            st = call(
                "enrolment-token-create",
                "POST",
                V1 + "/enrollment-tokens",
                S,
                {"max_uses": 2, "allowed_cidrs": ["127.0.0.0/8", "::1/128"]},
            )
            assert st.status == 201, st.body
            E = issued(st, "token")
            st = call("enrolment-token-list", "GET", V1 + "/enrollment-tokens", S)
            assert st.status == 200, st.body
            # failures before enrolment
            st = call("enrol-with-bsk", "POST", V1 + "/agent/enroll", K, enrol_body())
            assert st.status == 401, st.body
            st = call(
                "enrol-unknown-bse",
                "POST",
                V1 + "/agent/enroll",
                new_agent_token(AgentTokenKind.ENROLMENT),
                enrol_body(),
            )
            assert st.status == 401, st.body
            # 2. enrol, held
            mid = secrets.token_hex(16)
            st = call("enrol", "POST", V1 + "/agent/enroll", E, enrol_body(mid))
            assert st.status == 200, st.body
            assert json.loads(st.body)["status"] == "awaiting_approval"
            A = json.loads(st.body)["agent_id"]
            TA = issued(st, "agent_token")
            ah = {"X-Bitscan-Machine-Id": mid}
            hb = f"{V1}/agent/{A}/heartbeat"
            st = call(
                "heartbeat-held", "POST", hb, TA, heartbeat_body(now()), headers=ah
            )
            assert st.status == 403, st.body
            # 3. approve with the TOTP session
            # page through: the shared test database holds other requests
            listing = V1 + "/enrollment-requests?limit=500"
            rid = None
            while rid is None:
                st = call("requests-list", "GET", listing, S)
                assert st.status == 200, st.body
                page = json.loads(st.body)
                rid = next(
                    (i["request_id"] for i in page["items"] if i["agent_id"] == A),
                    None,
                )
                if rid is None:
                    assert page["next_cursor"], "the held request is not listed"
                    listing = (
                        V1
                        + "/enrollment-requests?limit=500&cursor="
                        + quote(page["next_cursor"], safe="")
                    )
            st = call("approve", "POST", f"{V1}/enrollment-requests/{rid}/approve", S)
            assert st.status == 200, st.body
            # 4. heartbeat with a last_error
            st = call(
                "heartbeat",
                "POST",
                hb,
                TA,
                heartbeat_body(now(), last_error=last_error),
                headers=ah,
            )
            assert st.status == 200, st.body
            # max_parallel_jobs: the test agent is 0.5.0 or later (TS §6.5)
            assert sorted(json.loads(st.body)) == [
                "job_pull_seconds",
                "max_parallel_jobs",
                "max_parallel_plugins",
                "server_time",
            ]
            # 5. pull the first inventory job
            st = call("pull", "GET", f"{V1}/agent/{A}/jobs", TA, headers=ah)
            assert st.status == 200, st.body
            jobs = json.loads(st.body)["jobs"]
            assert [j["kind"] for j in jobs] == ["inventory"], jobs
            J = jobs[0]["job_id"]
            # 6. a results post: 409 in M3, never stored
            st = call(
                "results",
                "POST",
                f"{V1}/agent/{A}/jobs/{J}/results",
                TA,
                results_body(stdout, stderr),
                headers=ah,
            )
            assert st.status == 409, st.body
            # 7. upload the inventory, completing the job
            body = inventory(["bash", pkg_name], raw={"m3c": raw_value})
            st = call(
                "inventory",
                "PUT",
                f"{V1}/agent/{A}/inventory?job_id={J}",
                TA,
                raw=gz(body),
                headers=ah | {"Content-Encoding": "gzip"},
            )
            assert st.status == 204, st.body
            # 8. the host detail shows os_info and the snapshot
            st = call("agent-detail", "GET", f"{V1}/agents/{A}", S)
            assert st.status == 200, st.body
            st.data += [pkg_name, raw_value]
            detail = json.loads(st.body)
            st = call("agent-packages", "GET", f"{V1}/agents/{A}/packages", S)
            assert st.status == 200, st.body
            st.data.append(pkg_name)
            # failures with agent tokens
            st = call(
                "unknown-bsa",
                "GET",
                f"{V1}/agent/{A}/jobs",
                new_agent_token(AgentTokenKind.AGENT),
                headers=ah,
            )
            assert st.status == 401, st.body
            st = call(
                "bse-on-heartbeat", "POST", hb, E, heartbeat_body(now()), headers=ah
            )
            assert st.status == 401, st.body
            st = call("session-on-pull", "GET", f"{V1}/agent/{A}/jobs", S, headers=ah)
            assert st.status == 401, st.body
            st = call("bsa-on-user-route", "GET", f"{V1}/agents/{A}", TA)
            assert st.status == 401, st.body
            # 9. rotate (the token moved into its window as owner)
            owner(
                migrated_db,
                "UPDATE agent SET token_issued_at = %s, token_expires_at = %s"
                " WHERE agent_id = %s",
                (now() - timedelta(days=336), now() + timedelta(days=29), A),
            )
            rot = f"{V1}/agent/{A}/token/rotate"
            st = call("rotate", "POST", rot, TA, headers=ah)
            assert st.status == 200, st.body
            N = issued(st, "agent_token")
            st = call("pull-new-token", "GET", f"{V1}/agent/{A}/jobs", N, headers=ah)
            assert st.status == 200, st.body
            st = call(
                "heartbeat-new-token", "POST", hb, N, heartbeat_body(now()), headers=ah
            )
            assert st.status == 200, st.body
            # 10. revoke with the TOTP session: both tokens refused
            st = call("revoke", "POST", f"{V1}/agents/{A}/revoke", S)
            assert st.status == 204, st.body
            st = call(
                "pull-after-revoke-new", "GET", f"{V1}/agent/{A}/jobs", N, headers=ah
            )
            assert st.status == 401, st.body
            revoked_new = json.loads(st.body)["type"]
            st = call(
                "pull-after-revoke-old", "GET", f"{V1}/agent/{A}/jobs", TA, headers=ah
            )
            assert st.status == 401, st.body
            revoked_old = json.loads(st.body)["type"]
            st = call("logout", "POST", V1 + "/auth/logout", S)
            assert st.status == 204, st.body
            end_id = max_audit_id(migrated_db)
            with migrated_db.connect("bitscan_app") as c:
                want = {
                    r[0]
                    for r in c.execute(
                        "SELECT audit_id FROM audit_log WHERE audit_id <= %s", (end_id,)
                    ).fetchall()
                }
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                ids = {json.loads(p.body)["audit_id"] for p in list(sink.posts)}
                if want <= ids:
                    break
                time.sleep(0.5)
            rows = {
                "agent": owner(
                    migrated_db,
                    "SELECT status, token_revoked_at IS NOT NULL, token_hash"
                    " FROM agent WHERE agent_id = %s",
                    (A,),
                ),
                "job": owner(
                    migrated_db,
                    "SELECT state FROM scan_job WHERE job_id = %s",
                    (J,),
                ),
                "os_info": owner(
                    migrated_db,
                    "SELECT kernel_release FROM os_info WHERE agent_id = %s",
                    (A,),
                ),
                "snapshots": owner(
                    migrated_db,
                    "SELECT package_count FROM inventory_snapshot WHERE agent_id = %s",
                    (A,),
                ),
                "detail": detail,
                "revoked_types": (revoked_new, revoked_old),
                "N": N,
            }
        finally:
            if s.proc.poll() is None:
                s.stop()
        posts = [json.loads(p.body) for p in sink.posts]
        tokens = [s1, s2, S, K, E, TA, N]
        yield Chain(
            server=migrated_db,
            start_id=start_id,
            steps=steps,
            output=s.output(),
            posts=posts,
            tokens=tokens,
            secrets=[admin_pw, secret, stdout, stderr, pkg_name, raw_value],
            agent_id=A,
            job_id=J,
            last_error=last_error,
            rows=rows,
        )


def test_api_chain_end_to_end(chain: Chain) -> None:
    """CHK-M3-317: the chain's steps all answered as the spec says (asserted
    while it ran), and the database ends in the stated state."""
    r = chain.rows
    status, revoked, stored_hash = r["agent"][0]
    assert revoked is True and stored_hash == token_hash(r["N"])
    assert status in ("online", "enrolled")
    assert r["job"] == [("completed",)]
    assert len(r["os_info"]) == 1
    assert r["snapshots"] == [(2,)]
    detail = r["detail"]
    assert detail["os_info"] is not None and detail["last_snapshot"] is not None
    assert detail["last_snapshot"]["package_count"] == 2
    assert r["revoked_types"] == ("token_revoked", "token_revoked")
    labels = [s.label for s in chain.steps]
    for label in ("enrol", "approve", "heartbeat", "pull", "inventory", "rotate"):
        assert label in labels


def records(output: str) -> list[dict[str, Any]]:
    out = []
    for line in output.splitlines():
        if line.strip():
            out.append(json.loads(line))  # every line is one JSON record
    return out


def test_canary_sweep_over_the_agent_chain(chain: Chain) -> None:
    """CHK-M3-302 (G28), REQ-087 (2), REQ-063 (5): no bsa_ or bse_ token (with
    or without its prefix), user token, stdout, stderr, package name or raw
    value in serve's output, any audit detail or any sink payload; last_error
    only in its one #25 (a) INFO record carrying the agent_id; each response
    holds its own one-time secret and no other."""
    out = chain.output
    recs = records(out)
    assert any(r.get("logger") == "bitscan_manager.access" for r in recs)
    canaries = [*chain.secrets, *chain.tokens, *(t[4:] for t in chain.tokens)]
    assert sweep(canaries, out) == []
    lines = [line for line in out.splitlines() if chain.last_error in line]
    assert len(lines) == 1, lines
    rec = json.loads(lines[0])
    assert rec["level"] == "INFO" and rec["agent_id"] == chain.agent_id
    for step in chain.steps:
        for own in step.own:
            assert own in step.body.decode(), step.label
        others = [
            c
            for c in [*canaries, chain.last_error]
            if all(c not in o for o in step.own) and c not in step.data
        ]
        assert sweep(others, step.body) == [], step.label
    assert (
        sweep([*canaries, chain.last_error], *(json.dumps(p) for p in chain.posts))
        == []
    )
    with chain.server.connect("bitscan_app") as c:
        details = c.execute(
            "SELECT detail::text FROM audit_log WHERE audit_id > %s",
            (chain.start_id,),
        ).fetchall()
    assert details  # the chain wrote entries
    assert sweep([*canaries, chain.last_error], *(d[0] or "" for d in details)) == []


def test_agent_route_records_carry_the_agent_and_job_id(chain: Chain) -> None:
    """REQ-087 (1): a heartbeat's records carry its agent_id; a results post's
    records carry the agent_id and the job_id."""
    recs = records(chain.output)
    access = [r for r in recs if r.get("logger") == "bitscan_manager.access"]
    beats = [r for r in access if str(r.get("path", "")).endswith("/heartbeat")]
    assert beats and all(
        r["agent_id"] == chain.agent_id for r in beats if r.get("status") == 200
    )
    posts = [r for r in access if str(r.get("path", "")).endswith("/results")]
    assert posts, access[:3]
    assert all(
        (r["agent_id"], r["job_id"]) == (chain.agent_id, chain.job_id) for r in posts
    )
    assert UUID(chain.job_id)
