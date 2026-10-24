"""TASK-063: the agent router and bsa_ dependency on PostgreSQL (G31 part).

Checks CHK-M3-160 to CHK-M3-169 of tests/m3/test-plan.md (TP-M3-17; TS §8.3
Security: tokens on the wrong route group). The real dependency, repositories,
rate limiter and sink gate run on a migrated database; test-only routes at agent
paths stand in for the real routes (TASK-067, 072 to 075 re-run this matrix).
Expected values: #59 (statuses, types, order; 401 counts, 403 does not; a valid
token from a limited IP passes), #63, #25 (b) (record the IP on every accepted
call), #65 (d) (more than 20 401s in a minute for one agent: one alert per
hour), TS §6.3 L1136 (30 per minute per agent; 20 failed checks per minute per
IP), REQ-066 (3) (after-auth: token first, nothing read), REQ-087 (agent_id in
the records; no token in any log).
"""

import asyncio
import hashlib
import io
import json
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import psycopg
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager import app as app_module
from bitscan_manager.api.agent.bodies import read_capped
from bitscan_manager.api.agent.dependencies import AuthenticatedAgent, current_agent
from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.api.request_log import configure_logging
from bitscan_manager.app import RouteCap, create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from .conftest import PgServer
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
CAP = 1024  # the test inventory route's after-auth cap
# A test-only after-auth template of the inventory shape: the real
# PUT /api/v1/agent/{id}/inventory (TASK-074) matches before a test route at
# that template, so the probe lives beside it with the same cap class. The
# real route's own after-auth behaviour is in test_inventory_api_pg.py.
PROBE_INV = "/api/v1/agent/{id}/inventory-probe"
log = logging.getLogger("bitscan_manager.tests.agent_probe")


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Agent:
    agent_id: UUID
    token: str
    machine_id: str


@dataclass
class Env:
    server: PgServer
    clock: Clock
    limits: RateLimiter
    app: FastAPI
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def client(self, ip: str = "10.3.0.1") -> TestClient:
        if ip not in self.clients:
            self.clients[ip] = TestClient(self.app, client=(ip, 1234))
        return self.clients[ip]

    def agent(self, status: str = "online", **cols: Any) -> Agent:
        tok = new_agent_token(AgentTokenKind.AGENT)
        machine = secrets.token_hex(16)
        values: dict[str, Any] = {
            "machine_id": machine,
            "hostname": f"h-{secrets.token_hex(3)}",
            "agent_version": "1.0.0",
            "token_hash": token_hash(tok),
            "token_issued_at": T0 - timedelta(days=10),
            "token_expires_at": T0 + timedelta(days=355),
            "status": status,
            "enrolled_at": T0 - timedelta(days=10),
        } | cols
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with self.conn() as c:
            row = c.execute(
                f"INSERT INTO agent ({names}) VALUES ({marks}) RETURNING agent_id",  # noqa: S608 - fixed column names
                list(values.values()),
            ).fetchone()
        assert row is not None
        return Agent(UUID(str(row[0])), tok, machine)

    def enrol_token(self) -> tuple[int, str]:
        tok = new_agent_token(AgentTokenKind.ENROLMENT)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
                " created_by) VALUES (%s, 10, %s, 1) RETURNING token_id",
                (token_hash(tok), T0 + timedelta(days=1)),
            ).fetchone()
        assert row is not None
        return int(row[0]), tok

    def request(self, a: Agent, kind: str, decision: str | None) -> str:
        """An enrollment_request for agent a; returns its new token."""
        tid, _ = self.enrol_token()
        new = new_agent_token(AgentTokenKind.AGENT)
        with self.conn() as c:
            c.execute(
                "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id,"
                " hostname, machine_id, agent_version, new_token_hash,"
                " token_expires_at,"
                " source_ip, requested_at, decision, decided_at) VALUES (%s, %s, %s,"
                " 'h', %s, '1', %s, %s, '10.0.0.1', %s, %s, %s)",
                (
                    kind,
                    a.agent_id,
                    tid,
                    a.machine_id,
                    token_hash(new),
                    T0 + timedelta(days=365),
                    T0 - timedelta(minutes=5),
                    decision,
                    None if decision is None else T0 - timedelta(minutes=1),
                ),
            )
        return new

    def user_token(self, kind: str) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', 'admin', 'enc', 1, %s)"
                " RETURNING user_id",
                (f"a-{secrets.token_hex(4)}", T0),
            ).fetchone()
            assert uid is not None
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uid[0],
                    kind,
                    token_hash(tok),
                    kind == "session",
                    T0 + timedelta(days=1),
                    T0,
                ),
            )
        return tok

    def row(self, agent_id: UUID) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (agent_id,))
            values = cur.fetchone()
            cols = [d.name for d in cur.description or []]
        assert values is not None
        return dict(zip(cols, values, strict=True))

    def ips(self, agent_id: UUID) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT host(ip), first_seen_at, last_seen_at FROM agent_ip_seen"
                " WHERE agent_id = %s ORDER BY 1",
                (agent_id,),
            ).fetchall()

    def alerts(self, kind: str, agent_id: UUID) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT action, actor, target, detail FROM audit_log"
                " WHERE detail->>'alert_kind' = %s AND target = %s ORDER BY audit_id",
                (kind, f"agent:{agent_id}"),
            ).fetchall()

    def probe(
        self,
        a: Agent | None,
        *,
        path_id: str | None = None,
        token: str | None = None,
        machine: str | None = "same",
        ip: str = "10.3.0.1",
        headers: dict[str, str] | None = None,
    ) -> Any:
        h: dict[str, str] = dict(headers or {})
        tok = token if token is not None else (a.token if a else None)
        if tok and "authorization" not in {k.lower() for k in h}:
            h["Authorization"] = f"Bearer {tok}"
        if machine == "same" and a is not None:
            h["X-Bitscan-Machine-Id"] = a.machine_id
        elif machine not in (None, "same"):
            h["X-Bitscan-Machine-Id"] = machine
        pid = (
            path_id
            if path_id is not None
            else (str(a.agent_id) if a else str(UUID(int=1)))
        )
        return self.client(ip).post(f"/api/v1/agent/{pid}/probe", headers=h)


@pytest.fixture
def env(migrated_db: PgServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    db.open()
    limits = RateLimiter(clock)
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=Gate(), limits=limits
    )
    monkeypatch.setattr(
        app_module,
        "ROUTE_BODY_CAPS",
        [RouteCap(PROBE_INV, "inventory", CAP, True)],
    )
    app = create_app(rt)

    @app.post("/api/v1/agent/{id}/probe")
    def probe(
        agent: Annotated[AuthenticatedAgent, Depends(current_agent)],
    ) -> dict[str, Any]:
        log.info("probe ran")
        return {
            "agent_id": str(agent.caller.agent_id),
            "via": agent.caller.via,
            "ip": agent.source_ip,
        }

    @app.put(PROBE_INV)
    async def inventory(
        request: Request, agent: Annotated[AuthenticatedAgent, Depends(current_agent)]
    ) -> dict[str, int]:
        body = await read_capped(request)
        return {"len": len(body)}

    e = Env(migrated_db, clock, limits, app)
    yield e
    for c in e.clients.values():
        c.close()
    db.close()


def problem(r: Any, status: int, type_: str) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == type_, r.json()


# ------------------------------------------------------------ CHK-M3-160


def test_wrong_and_missing_tokens_are_one_401(env: Env) -> None:
    """REQ-062 (2): one byte-identical body for every case; nothing changes."""
    a = env.agent()
    _, bse = env.enrol_token()
    cases: list[dict[str, str]] = [
        {},
        {"Authorization": f"Basic {a.token}"},
        {"Authorization": f"Token {a.token}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {env.user_token('session')}"},
        {"Authorization": f"Bearer {env.user_token('api')}"},
        {"Authorization": f"Bearer {bse}"},
        {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
        {"Authorization": f"Bearer {a.token} extra"},
    ]
    before = env.row(a.agent_id)
    bodies = set()
    for i, h in enumerate(cases):
        r = env.probe(a, token="", headers=h, ip=f"10.3.1.{i}")
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1
    # token only in the query string or a cookie: not read
    for i, (params, cookies) in enumerate(
        [
            ({"token": a.token}, {}),
            ({}, {"token": a.token}),
            ({"access_token": a.token}, {}),
        ]
    ):
        c = env.client(f"10.3.2.{i}")
        c.cookies.clear()
        for k, v in cookies.items():
            c.cookies.set(k, v)
        r = c.post(
            f"/api/v1/agent/{a.agent_id}/probe",
            params=params,
            headers={"X-Bitscan-Machine-Id": a.machine_id},
        )
        problem(r, 401, "unauthorized")
    assert env.row(a.agent_id) == before
    assert env.ips(a.agent_id) == []


def test_two_authorization_headers_are_refused(env: Env) -> None:
    a = env.agent()
    r = env.client("10.3.3.1").post(
        f"/api/v1/agent/{a.agent_id}/probe",
        headers=[
            ("Authorization", f"Bearer {a.token}"),
            ("Authorization", f"Bearer {a.token}"),
            ("X-Bitscan-Machine-Id", a.machine_id),
        ],
    )
    problem(r, 401, "unauthorized")


# ------------------------------------------------------------ CHK-M3-161


def test_token_states_through_the_dependency(env: Env) -> None:
    """REQ-064 (1): each state gives its #59 status and type."""
    revoked = env.agent(token_revoked_at=T0 - timedelta(minutes=1))
    problem(env.probe(revoked, ip="10.3.4.1"), 401, "token_revoked")
    expired = env.agent(token_expires_at=T0)
    problem(env.probe(expired, ip="10.3.4.2"), 401, "token_expired")
    pending = env.agent(status="awaiting_approval")
    problem(env.probe(pending, ip="10.3.4.3"), 403, "pending_approval")
    held = env.agent()
    held_new = env.request(held, "reenrol", None)
    problem(env.probe(held, token=held_new, ip="10.3.4.4"), 403, "pending_approval")
    assert env.probe(held, ip="10.3.4.4").status_code == 200  # old token works
    rejected = env.agent(status="decommissioned", token_revoked_at=T0)
    env.request(rejected, "new", "rejected")
    problem(env.probe(rejected, ip="10.3.4.5"), 401, "enrollment_rejected")
    re_rejected = env.agent()
    rr_new = env.request(re_rejected, "reenrol", "rejected")
    problem(
        env.probe(re_rejected, token=rr_new, ip="10.3.4.6"), 401, "enrollment_rejected"
    )
    assert env.probe(re_rejected, ip="10.3.4.6").status_code == 200  # #26


@pytest.mark.parametrize(
    "machine", ["f" * 32, None, "NOT-HEX"], ids=["other", "missing", "malformed"]
)
def test_mismatch_revokes_and_alerts_and_commits(env: Env, machine: str | None) -> None:
    """REQ-064 (2), #63: the revoke and the alert written by the check commit."""
    a = env.agent()
    problem(env.probe(a, machine=machine, ip="10.3.5.1"), 401, "machine_id_mismatch")
    row = env.row(a.agent_id)
    assert row["token_revoked_at"] == T0
    alerts = env.alerts("machine_id_mismatch", a.agent_id)
    assert len(alerts) == 1 and alerts[0][0] == "agent.machine_id_mismatch"
    assert a.token not in json.dumps(alerts[0][3]) and a.machine_id not in json.dumps(
        alerts[0][3]
    )
    problem(env.probe(a, ip="10.3.5.1"), 401, "token_revoked")  # right header now
    assert len(env.alerts("machine_id_mismatch", a.agent_id)) == 1


# ------------------------------------------------------------ CHK-M3-162


def test_foreign_id_is_403_not_counted(env: Env) -> None:
    a, b = env.agent(), env.agent()
    before_b = env.row(b.agent_id)
    for _ in range(25):  # never counted toward the failed-check limit
        problem(env.probe(a, path_id=str(b.agent_id), ip="10.3.6.1"), 403, "forbidden")
    # TASK-083 ruling 2026-10-23: a malformed {id} is 400, still not counted
    for bad in ("not-a-uuid", str(a.agent_id).replace("-", ""), f"{{{a.agent_id}}}"):
        problem(env.probe(a, path_id=bad, ip="10.3.6.1"), 400, "invalid_request")
    assert env.row(b.agent_id) == before_b and env.ips(b.agent_id) == []
    # the {id} check comes before the 30-per-minute limit: 403s use no budget
    r = env.probe(a, path_id=str(a.agent_id).upper(), ip="10.3.6.1")
    assert r.status_code == 200  # upper-case UUID is the same id
    assert not [d for d in env.limits.drain(final=True) if d.ip == "10.3.6.1"]


# ------------------------------------------------------------ CHK-M3-163


def test_thirty_per_minute_per_agent(env: Env) -> None:
    """REQ-065 (1)."""
    a, b = env.agent(), env.agent()
    env.clock.at = T0 + timedelta(seconds=5)
    for _ in range(30):
        assert env.probe(a, ip="10.3.7.1").status_code == 200
    r = env.probe(a, ip="10.3.7.1")
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"
    assert env.probe(b, ip="10.3.7.1").status_code == 200
    env.clock.at = T0 + timedelta(minutes=1)
    assert env.probe(a, ip="10.3.7.1").status_code == 200


# ------------------------------------------------------------ CHK-M3-164


def test_failed_checks_feed_the_ip_limit_and_valid_tokens_pass(env: Env) -> None:
    """REQ-065 (3), REQ-062 (4); CHK-M3-362, -363."""
    ip = "10.3.8.1"
    good = env.agent()
    for _ in range(25):  # valid requests first: never counted
        env.probe(good, ip=ip)
    env.clock.at += timedelta(minutes=1)
    bad = new_agent_token(AgentTokenKind.AGENT)
    for _ in range(20):
        problem(env.probe(None, token=bad, ip=ip), 401, "unauthorized")
    r = env.probe(None, token=bad, ip=ip)
    problem(r, 429, "rate_limited")
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert env.probe(good, ip=ip).status_code == 200  # a valid token still passes
    # user-route failures from the same IP join the same count
    uc = env.client(ip)
    for _ in range(2):
        uc.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"})
    other = env.probe(None, token=bad, ip="10.3.8.2")
    problem(other, 401, "unauthorized")  # another IP is not limited
    env.clock.at += timedelta(minutes=1)
    entries = {d.ip: d.count for d in env.limits.drain()}
    assert entries[ip] == 21 + 2
    assert entries["10.3.8.2"] == 1


def test_pending_403_is_not_counted(env: Env) -> None:
    pending = env.agent(status="awaiting_approval")
    for _ in range(25):
        problem(env.probe(pending, ip="10.3.9.1"), 403, "pending_approval")
    env.clock.at += timedelta(minutes=1)
    assert "10.3.9.1" not in {d.ip for d in env.limits.drain()}


# ------------------------------------------------------------ CHK-M3-165


def test_more_than_20_401s_for_one_agent_alert_once_an_hour(env: Env) -> None:
    """REQ-065 (4), #65 (d), from several IPs so the IP limit is not the cause."""
    a = env.agent(token_expires_at=T0 - timedelta(seconds=1))
    for i in range(20):
        problem(env.probe(a, ip=f"10.4.0.{i}"), 401, "token_expired")
    assert env.alerts("agent_auth_failures", a.agent_id) == []
    problem(env.probe(a, ip="10.4.1.1"), 401, "token_expired")  # the 21st
    alerts = env.alerts("agent_auth_failures", a.agent_id)
    assert len(alerts) == 1
    action, actor, target, detail = alerts[0]
    assert (
        action == "alert.agent_auth_failures"
        and actor == target == f"agent:{a.agent_id}"
    )
    assert detail["alert"] is True
    for i in range(25):  # within the hour: no second alert
        env.probe(a, ip=f"10.4.2.{i}")
    assert len(env.alerts("agent_auth_failures", a.agent_id)) == 1
    env.clock.at += timedelta(hours=1)
    for i in range(21):
        env.probe(a, ip=f"10.4.3.{i}")
    assert len(env.alerts("agent_auth_failures", a.agent_id)) == 2


def test_rolled_back_auth_failure_alert_leaves_the_hour_free(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead ruling 2026-10-23 (commit-only "fired", re-checked in TASK-067):
    when the transaction holding the agent_auth_failures alert rolls back,
    the alert is gone and the hour's slot stays free, so the next 401 for
    that agent alerts; after the committed alert none within the hour. The
    window is the one create_app() built (windows ruling)."""
    from bitscan_manager.api.agent import dependencies
    from bitscan_manager.services.users import TxAudit

    windows = env.app.state.agent_windows
    a = env.agent(token_expires_at=T0 - timedelta(seconds=1))
    for i in range(20):
        problem(env.probe(a, ip=f"10.4.4.{i}"), 401, "token_expired")
    fail = {"on": True, "armed": False}

    class ArmingAudit(TxAudit):
        def alert(self, *args: Any, **kwargs: Any) -> None:
            super().alert(*args, **kwargs)
            if fail["on"]:
                fail["armed"] = True

    db = env.app.state.runtime.db
    original_tx = db.transaction

    @contextmanager
    def failing_tx() -> Iterator[Any]:
        """The whole body runs (so a mark made inside it would happen), then
        the transaction is made to fail: the alert entry rolls back."""
        with original_tx() as tx:
            yield tx
            if fail["armed"]:
                fail["armed"] = False
                raise RuntimeError("forced failure after the body, before commit")

    monkeypatch.setattr(dependencies, "TxAudit", ArmingAudit)
    monkeypatch.setattr(db, "transaction", failing_tx)
    with TestClient(
        env.app, client=("10.4.5.1", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(
            f"/api/v1/agent/{a.agent_id}/probe",
            headers={
                "Authorization": f"Bearer {a.token}",
                "X-Bitscan-Machine-Id": a.machine_id,
            },
        )
    assert r.status_code == 500
    assert env.alerts("agent_auth_failures", a.agent_id) == []
    fail["on"] = False
    problem(env.probe(a, ip="10.4.5.2"), 401, "token_expired")
    assert len(env.alerts("agent_auth_failures", a.agent_id)) == 1
    for i in range(5):
        problem(env.probe(a, ip=f"10.4.5.{10 + i}"), 401, "token_expired")
    assert len(env.alerts("agent_auth_failures", a.agent_id)) == 1
    assert env.app.state.agent_windows is windows


# ------------------------------------------------------------ CHK-M3-166


def test_accepted_calls_record_the_ip(env: Env) -> None:
    """#25 (b): last_seen_ip and agent_ip_seen; IPv4-mapped peers as IPv4."""
    a = env.agent()
    r = env.probe(a, ip="::ffff:10.5.0.7")
    assert r.status_code == 200 and r.json()["ip"] == "10.5.0.7"
    assert env.row(a.agent_id)["last_seen_ip"] is not None
    assert env.ips(a.agent_id) == [("10.5.0.7", T0, T0)]
    env.clock.at += timedelta(minutes=5)
    env.probe(a, ip="2001:db8::9")
    env.probe(a, ip="::ffff:10.5.0.7")
    assert env.ips(a.agent_id) == [
        ("10.5.0.7", T0, T0 + timedelta(minutes=5)),
        ("2001:db8::9", T0 + timedelta(minutes=5), T0 + timedelta(minutes=5)),
    ]
    pending = env.agent(status="awaiting_approval")
    env.probe(pending, ip="10.5.0.8")
    env.probe(a, path_id=str(pending.agent_id), ip="10.5.0.9")
    assert env.ips(pending.agent_id) == []


# ------------------------------------------------------------ CHK-M3-167


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    stream = io.StringIO()
    configure_logging(stream, logging.DEBUG)
    yield stream
    for h in list(root.handlers):
        if h not in before[0]:
            root.removeHandler(h)
    root.setLevel(before[1])


def test_records_carry_the_agent_id_and_no_token(env: Env, logs: io.StringIO) -> None:
    """REQ-087 (1), (2)."""
    a = env.agent()
    b = env.agent()
    assert env.probe(a, ip="10.6.0.1").status_code == 200
    env.probe(b, machine="f" * 32, ip="10.6.0.2")  # a mismatch: revoke and alert
    env.probe(None, token=new_agent_token(AgentTokenKind.AGENT), ip="10.6.0.3")
    text = logs.getvalue()
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    mine = [ln for ln in lines if ln.get("message") == "probe ran"]
    assert mine and all(ln["agent_id"] == str(a.agent_id) for ln in mine)
    access = [ln for ln in lines if ln.get("agent_id") == str(a.agent_id)]
    assert len(access) >= 2  # the route record and its access record
    for secret in (
        a.token,
        b.token,
        a.token[4:],
        hashlib.sha256(a.token.encode()).hexdigest(),
    ):
        assert secret not in text


# ------------------------------------------------------------ CHK-M3-168


@dataclass
class Feed:
    chunks: list[bytes]
    pulled: int = 0

    async def receive(self) -> dict[str, Any]:
        if not self.chunks:
            return {"type": "http.disconnect"}
        chunk = self.chunks.pop(0)
        self.pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(self.chunks)}


def drive(
    env: Env, path: str, headers: list[tuple[bytes, bytes]], feed: Feed
) -> tuple[int, dict[str, str]]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("10.7.0.1", 1),
        "server": ("t", 443),
    }
    status: list[int] = []
    resp_headers: dict[str, str] = {}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
            resp_headers.update(
                {k.decode(): v.decode() for k, v in message.get("headers", [])}
            )

    asyncio.run(env.app(scope, feed.receive, send))  # type: ignore[arg-type]
    return status[0], resp_headers


def test_after_auth_route_checks_the_token_before_any_byte(env: Env) -> None:
    """REQ-066 (3) carry-over: 0 bytes pulled before a 401."""
    a = env.agent()
    path = f"/api/v1/agent/{a.agent_id}/inventory-probe"
    for hdrs in (
        [(b"content-length", str(CAP + 1).encode())],
        [],
        [
            (
                b"authorization",
                b"Bearer " + new_agent_token(AgentTokenKind.AGENT).encode(),
            )
        ],
    ):
        feed = Feed([b"a" * 512] * 4)
        status, _ = drive(
            env, path, [*hdrs, (b"x-bitscan-machine-id", a.machine_id.encode())], feed
        )
        assert status == 401
        assert feed.pulled == 0


def test_after_auth_cap_with_a_valid_token(env: Env) -> None:
    a = env.agent()
    path = f"/api/v1/agent/{a.agent_id}/inventory-probe"
    auth = [
        (b"authorization", f"Bearer {a.token}".encode()),
        (b"x-bitscan-machine-id", a.machine_id.encode()),
    ]
    feed = Feed([b"a" * CAP])
    assert drive(env, path, auth, feed)[0] == 200
    feed = Feed([b"a" * 512] * 4)  # chunked over the cap
    status, headers = drive(env, path, auth, feed)
    assert status == 413 and headers.get("connection") == "close"
    assert feed.pulled <= CAP + 512
    feed = Feed([b"a" * 512] * 4)
    status, _ = drive(
        env, path, [*auth, (b"content-length", str(CAP + 1).encode())], feed
    )
    assert status == 413 and feed.pulled == 0


def test_read_capped_fails_closed_without_a_cap(env: Env) -> None:
    """CHK-M3-168 carry-over: the newline path the router matches but the cap
    pattern does not gets no BodyCap: 413, nothing read."""
    a = env.agent()
    path = f"/api/v1/agent/{a.agent_id}/inventory-probe\n"
    auth = [
        (b"authorization", f"Bearer {a.token}".encode()),
        (b"x-bitscan-machine-id", a.machine_id.encode()),
    ]
    feed = Feed([b"a" * 10])
    status, _ = drive(env, path, auth, feed)
    assert status == 413
    assert feed.pulled in (
        0,
        10,
    )  # the json default cap may buffer the small body; nothing reaches the route


# ------------------------------------------------------------ CHK-M3-169


def test_route_walk_of_the_agent_group() -> None:
    """REQ-062 (1): every /api/v1/agent/ operation other than enrol carries the
    bsa_ dependency; none carries a user dependency (re-run per route task)."""
    from .test_auth_dependencies import api_routes

    # TS §6.1 L1062-L1067: the only operations the agent group may have
    allowed = {
        ("POST", "/api/v1/agent/enroll"),
        ("POST", "/api/v1/agent/{id}/heartbeat"),
        ("GET", "/api/v1/agent/{id}/jobs"),
        ("POST", "/api/v1/agent/{id}/jobs/{job_id}/results"),
        ("PUT", "/api/v1/agent/{id}/inventory"),
        ("POST", "/api/v1/agent/{id}/token/rotate"),
    }
    app = create_app()
    # The walk must descend into included routers (TASK-067 TEST: a walk over
    # app.routes alone saw none of them and passed vacuously).
    agent_routes = [
        r for r in api_routes(app.routes) if r.path.startswith("/api/v1/agent/")
    ]
    ops = {(m, r.path) for r in agent_routes for m in r.methods or ()}
    assert ("POST", "/api/v1/agent/enroll") in ops  # the walk sees the real routes
    assert ops <= allowed, ops - allowed
    for route in agent_routes:
        deps = {
            getattr(d.call, "bitscan_agent_auth", None)
            for d in route.dependant.dependencies
        }
        stack = list(route.dependant.dependencies)
        while stack:  # no user dependency anywhere in the tree
            dep = stack.pop()
            assert getattr(dep.call, "bitscan_auth", None) is None, route.path
            stack.extend(dep.dependencies)
        if route.path == "/api/v1/agent/enroll":
            assert "bse_" in deps and "bsa_" not in deps
            continue
        assert "bsa_" in deps and "bse_" not in deps, route.path
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert not any("principal" in n or "require_" in n for n in names), route.path
    assert len(ops) <= 6


def test_database_down_is_503_not_counted(
    migrated_db: PgServer, tmp_path: Path
) -> None:
    clock = Clock()
    dsn = migrated_db.dsn("bitscan_app").replace(f"port={migrated_db.port}", "port=1")
    db = AppDatabase(SecretStr(dsn), connect_timeout_s=1)
    db.open()
    limits = RateLimiter(clock)
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=Gate(), limits=limits
    )
    app = create_app(rt)

    @app.post("/api/v1/agent/{id}/probe")
    def probe(
        agent: Annotated[AuthenticatedAgent, Depends(current_agent)],
    ) -> dict[str, str]:
        return {}

    tok = new_agent_token(AgentTokenKind.AGENT)
    with TestClient(app, client=("10.8.0.1", 1)) as c:
        for _ in range(3):
            r = c.post(
                f"/api/v1/agent/{UUID(int=5)}/probe",
                headers={"Authorization": f"Bearer {tok}"},
            )
            problem(r, 503, "about:blank")
    assert not limits.failed_check_blocked("10.8.0.1")
    db.close()


@pytest.mark.parametrize("prefix", ["bse_", "bsu_", "bsk_"])
def test_wrong_prefix_refused_when_its_hash_is_an_agent_row(
    env: Env, prefix: str
) -> None:
    """Only the prefix check can refuse these (M2 CHK-M2-151 (b); CHK-M3-320, -321)."""
    raw = prefix + secrets.token_urlsafe(32)[:43].ljust(43, "A")
    a = env.agent(token_hash=token_hash(raw))
    r = env.probe(Agent(a.agent_id, raw, a.machine_id), ip="10.9.0.1")
    problem(r, 401, "unauthorized")
    assert env.ips(a.agent_id) == []


def test_scoped_ipv6_peer_passes_and_is_stored_without_its_zone(env: Env) -> None:
    """Lead ruling 2026-10-23 (TASK-067 r1): a link-local peer's zone id
    (fe80::1%eth0) is dropped; the call passes and fe80::1 is recorded; #59
    has no 500 for agent routes."""
    a = env.agent()
    with TestClient(
        env.app, client=("fe80::1%eth0", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(
            f"/api/v1/agent/{a.agent_id}/probe",
            headers={
                "Authorization": f"Bearer {a.token}",
                "X-Bitscan-Machine-Id": a.machine_id,
            },
        )
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["ip"] == "fe80::1"
    assert env.ips(a.agent_id) == [("fe80::1", T0, T0)]


def test_user_and_agent_routes_key_one_peer_alike(env: Env) -> None:
    """TASK-067 r1 (api.peer, REQ-065 (3)): an IPv4-mapped peer and a zoned
    IPv6 peer key the failed-check limiter and its aggregated entry by the
    same normalised address on user and agent routes, so one IP gets one
    entry; the sign-in limit shares the key too."""
    bad = new_agent_token(AgentTokenKind.AGENT)
    with TestClient(env.app, client=("::ffff:10.12.0.1", 1)) as mapped:
        for _ in range(3):
            r = mapped.get(
                "/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"}
            )
            assert r.status_code == 401
    for _ in range(2):
        problem(env.probe(None, token=bad, ip="10.12.0.1"), 401, "unauthorized")
    with TestClient(env.app, client=("fe80::7%eth0", 1)) as zoned:
        r = zoned.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401
    env.clock.at += timedelta(minutes=1)
    entries = {d.ip: d.count for d in env.limits.drain()}
    assert entries.get("10.12.0.1") == 5, entries
    assert entries.get("fe80::7") == 1, entries
    assert not [ip for ip in entries if "%" in ip or ip.startswith("::ffff:")]
    # the 10-per-minute sign-in limit: mapped and plain attempts share one key
    body = {"username": f"nobody-{secrets.token_hex(3)}", "password": "x" * 12}
    with TestClient(env.app, client=("::ffff:10.12.0.2", 1)) as mapped:
        for _ in range(5):
            assert mapped.post("/api/v1/auth/login", json=body).status_code == 401
    with TestClient(env.app, client=("10.12.0.2", 1)) as plain:
        for _ in range(5):
            assert plain.post("/api/v1/auth/login", json=body).status_code == 401
        r = plain.post("/api/v1/auth/login", json=body)
    problem(r, 429, "rate_limited")


def test_a_non_ip_peer_is_keyed_alike_on_both_route_groups(env: Env) -> None:
    """TASK-067 r1 final (lead ruling on the reviewer's nit): a peer that is
    not an IP (TestClient's "testclient") keys the failed-check limiter by the
    same peer_key on agent routes, enrol and user routes."""
    bad = new_agent_token(AgentTokenKind.AGENT)
    env.limits.drain(final=True)  # start from no pending counts
    with TestClient(env.app) as c:  # peer "testclient"
        for _ in range(2):
            r = c.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"})
            assert r.status_code == 401
        uid = UUID(int=9)
        for _ in range(2):
            r = c.post(
                f"/api/v1/agent/{uid}/probe", headers={"Authorization": f"Bearer {bad}"}
            )
            problem(r, 401, "unauthorized")
        r = c.post(
            "/api/v1/agent/enroll",
            json={},
            headers={"Authorization": "Bearer bse_" + "A" * 43},
        )
        assert r.status_code in (400, 401)  # bad body (400) or non-IP peer (401)
        expected = 4 + (1 if r.status_code == 401 else 0)
    env.clock.at += timedelta(minutes=1)
    entries = {d.ip: d.count for d in env.limits.drain()}
    assert entries.get("testclient") == expected, entries
    assert "unknown" not in entries
