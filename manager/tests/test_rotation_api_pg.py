"""TASK-075: POST /api/v1/agent/{id}/token/rotate on PostgreSQL with a fake
clock (TP-M3-29).

Checks CHK-M3-265 to CHK-M3-273 of tests/m3/test-plan.md, the API halves of the
mutation rows CHK-M3-342 to -344, and the re-run of the agent-route matrix and
route walk on the real route. Expected values come from the spec and the
answers, not from the code: TS §3.2 L190 step 7 (lifetime agent_token_ttl_days,
a change applies to tokens issued or rotated after it; the window issued_at +
max(TTL - 30 days, TTL / 2); at most once per 24 h, counting only rotations
whose new token was then used; the old token valid until the new token is
first used and for 10 minutes after that; a lost response is retried with the
old token and gets a fresh new token, the unused one discarded; once the new
token was used, any later use of the old one revokes both and alerts; a
rotation from a source IP not seen for this agent in the last 7 days alerts),
L191 step 8 (after expiry 401 token_expired), TS §6.5 L1188 (the answer is
exactly agent_token, issued_at, expires_at), TS §8.4 L1290, #60 (no body or {}
only), #62 (outside the window 403 forbidden + rotation_outside_window; a
second rotation within 24 h of a used one 429 with Retry-After to the end of
the 24 h; first use = the first call with the new token that passes the check;
a rotate with the old token before the new one is used is the retry, after it
reuse even inside the 10 minutes), #71 (agent.token_rotate, agent.token_reuse,
alert kinds; no token in an entry), REQ-063 (2), (3) (only hashes stored),
REQ-071 (1)-(8). User ruling 2026-10-23: the old token after an unused
rotation is accepted only until last_rotation_at + 30 days, and the retry keeps
last_rotation_at so the cap cannot be extended.
"""

import json
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.api.agent import schemas
from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from tests.contract import loader

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_contract_agent import OPENAPI, RFC3339, validator
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
DAY = timedelta(days=1)
S = timedelta(seconds=1)
TEMPLATE = "/api/v1/agent/{id}/token/rotate"
KEYS = ["agent_token", "issued_at", "expires_at"]
TOKEN_RE = re2.compile(r"^bsa_[A-Za-z0-9_-]{43}$")
TOKEN_COLS = (
    "token_hash",
    "token_issued_at",
    "token_expires_at",
    "token_revoked_at",
    "prev_token_hash",
    "prev_token_expires_at",
    "last_rotation_at",
)


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


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
    app: FastAPI
    db: AppDatabase
    _ip: int = 0
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def fresh_ip(self) -> str:
        self._ip += 1
        return f"10.75.{self._ip // 256}.{self._ip % 256}"

    def client(self, ip: str) -> TestClient:
        if ip not in self.clients:
            self.clients[ip] = TestClient(
                self.app, client=(ip, 1234), raise_server_exceptions=False
            )
        return self.clients[ip]

    def agent(self, *, issued: datetime, ttl_days: int = 365, **cols: Any) -> Agent:
        tok = new_agent_token(AgentTokenKind.AGENT)
        machine = secrets.token_hex(16)
        values: dict[str, Any] = {
            "machine_id": machine,
            "hostname": f"rt-{secrets.token_hex(3)}",
            "agent_version": "1.0.0",
            "token_hash": token_hash(tok),
            "token_issued_at": issued,
            "token_expires_at": issued + timedelta(days=ttl_days),
            "status": "online",
            "enrolled_at": issued,
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

    def in_window(self, ttl_days: int = 365) -> Agent:
        """A token whose window opened one day before T0."""
        opens = max(timedelta(days=ttl_days - 30), timedelta(days=ttl_days) / 2)
        return self.agent(issued=T0 - opens - DAY, ttl_days=ttl_days)

    def headers(self, a: Agent, token: str | None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token or a.token}",
            "X-Bitscan-Machine-Id": a.machine_id,
        }

    def rotate(
        self,
        a: Agent,
        *,
        token: str | None = None,
        content: bytes | None = b"",
        ip: str = "10.75.250.1",
        path_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        h = self.headers(a, token) | (headers or {})
        if content:
            h["Content-Type"] = "application/json"
        path = TEMPLATE.replace("{id}", path_id or str(a.agent_id))
        return self.client(ip).post(path, content=content or b"", headers=h)

    def use(self, a: Agent, token: str, ip: str = "10.75.250.1") -> Any:
        """A normal agent call (an empty job pull) with the given token."""
        path = f"/api/v1/agent/{a.agent_id}/jobs"
        return self.client(ip).get(path, headers=self.headers(a, token))

    def cols(self, a: Agent) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute(
                "SELECT " + ", ".join(TOKEN_COLS) + " FROM agent WHERE agent_id = %s",  # noqa: S608 - fixed column names
                (a.agent_id,),
            )
            row = cur.fetchone()
        assert row is not None
        return dict(zip(TOKEN_COLS, row, strict=True))

    def whole_row(self, a: Agent) -> str:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (a.agent_id,))
            row = cur.fetchone()
        return json.dumps(row, default=str)

    def seen(self, a: Agent, ip: str, last: datetime) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO agent_ip_seen (agent_id, ip, first_seen_at, last_seen_at)"
                " VALUES (%s, %s, %s, %s)",
                (a.agent_id, ip, last - DAY, last),
            )

    def last_audit(self) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT coalesce(max(audit_id), 0) FROM audit_log"
            ).fetchone()
        assert row is not None
        return int(row[0])

    def audit_after(self, audit_id: int) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT actor, action, target, detail FROM audit_log"
                " WHERE audit_id > %s ORDER BY audit_id",
                (audit_id,),
            ).fetchall()

    def kinds(self, mark: int) -> list[str]:
        return [
            e[3]["alert_kind"]
            for e in self.audit_after(mark)
            if e[3].get("alert") is True
        ]

    def actions(self, mark: int) -> list[str]:
        return [e[1] for e in self.audit_after(mark)]

    def set_ttl(self, days: int) -> None:
        with self.server.connect("bitscan_migrate") as oc:
            oc.execute("SET ROLE bitscan_owner")
            oc.execute(
                "UPDATE setting SET value = %s WHERE key = 'agent_token_ttl_days'",
                (Jsonb(days),),
            )


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=8, connect_timeout_s=5
    )
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    e = Env(migrated_db, clock, create_app(rt), db)
    e.set_ttl(365)
    yield e
    for c in e.clients.values():
        c.close()
    db.close()


@pytest.fixture(autouse=True)
def restore_settings(migrated_db: PgServer) -> Iterator[None]:
    with migrated_db.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        rows = oc.execute(
            "SELECT key, value, updated_by, updated_at FROM setting"
        ).fetchall()
    yield
    with migrated_db.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        for key, value, by, at in rows:
            oc.execute(
                "UPDATE setting SET value = %s, updated_by = %s, updated_at = %s"
                " WHERE key = %s",
                (Jsonb(value), by, at, key),
            )


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == type_, body
    return body


def response_schema_errors(body: Any) -> list[Any]:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    node = doc["paths"][TEMPLATE]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    return list(validator({**doc, **node}).iter_errors(body))


def rotated(r: Any, env: Env, ttl_days: int = 365) -> str:
    """A 200 answer with exactly the three keys, valid against the document and
    the model; issued_at = now, expires_at = now + the current TTL."""
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert list(body) == KEYS, body
    assert not response_schema_errors(body)
    schemas.RotateResponse.model_validate_json(r.content)
    assert TOKEN_RE.match(body["agent_token"]), body
    for k in ("issued_at", "expires_at"):
        assert RFC3339.match(body[k]) and body[k].endswith("Z")
    assert parse(body["issued_at"]) == env.clock.now()
    assert parse(body["expires_at"]) == env.clock.now() + timedelta(days=ttl_days)
    token: str = body["agent_token"]
    return token


def ok_use(r: Any) -> None:
    assert r.status_code == 200, (r.status_code, r.text)


# ------------------------------------------------------------ CHK-M3-265


def test_ttl_365_window_opens_on_day_335(env: Env) -> None:
    """REQ-071 (1), CHK-M3-343: TTL 365 days: at 334 d 23 h 59 min 59 s the
    rotate is 403 forbidden with one rotation_outside_window alert entry
    and no token change; at day 335 it is 200 and the columns hold the new
    hash, the old hash as previous, last_rotation_at = now; one
    agent.token_rotate entry with no token or hash in it."""
    a = env.agent(issued=T0)
    env.clock.at = T0 + timedelta(days=334, hours=23, minutes=59, seconds=59)
    before = env.cols(a)
    mark = env.last_audit()
    problem(env.rotate(a), 403, "forbidden")
    assert env.cols(a) == before
    entries = env.audit_after(mark)
    assert len(entries) == 1, entries
    actor, action, target, detail = entries[0]
    assert actor == target == f"agent:{a.agent_id}"
    assert action == "alert.rotation_outside_window"
    assert detail["alert"] is True and detail["alert_kind"] == "rotation_outside_window"
    env.clock.at = T0 + timedelta(days=335)
    mark = env.last_audit()
    new = rotated(env.rotate(a), env)
    c = env.cols(a)
    assert c["token_hash"] == token_hash(new)
    assert c["prev_token_hash"] == token_hash(a.token)
    assert c["prev_token_expires_at"] is None  # the new token is unused
    assert c["token_issued_at"] == env.clock.at == c["last_rotation_at"]
    assert c["token_expires_at"] == env.clock.at + timedelta(days=365)
    assert c["token_revoked_at"] is None
    entries = env.audit_after(mark)
    assert "agent.token_rotate" in [e[1] for e in entries]
    assert "rotation_outside_window" not in env.kinds(mark)
    text = json.dumps([list(e) for e in entries], default=str)
    for secret in (new, a.token, new[4:], token_hash(new), token_hash(a.token)):
        assert secret not in text


@pytest.mark.parametrize(
    ("ttl", "opens_after"),
    [(60, 30), (61, 31), (100, 70), (365, 335), (730, 700)],
    ids=["ttl60", "ttl61", "ttl100", "ttl365", "ttl730"],
)
def test_window_edges_for_each_ttl(env: Env, ttl: int, opens_after: int) -> None:
    """REQ-071 (1), (2), CHK-M3-266: the window opens at issued_at +
    max(TTL - 30 d, TTL / 2), the TTL being the presented token's own
    expires_at - issued_at (whatever the setting is now): refused one second
    before, accepted at the instant."""
    env.set_ttl(90)  # the setting must not move the window of the old token
    a = env.agent(issued=T0, ttl_days=ttl)
    env.clock.at = T0 + timedelta(days=opens_after) - S
    problem(env.rotate(a), 403, "forbidden")
    env.clock.at = T0 + timedelta(days=opens_after)
    rotated(env.rotate(a), env, ttl_days=90)


# ------------------------------------------------------------ CHK-M3-267


def test_lost_response_retry_gives_a_fresh_token_and_kills_the_unused_one(
    env: Env,
) -> None:
    """REQ-071 (3), #62: a second rotate with the old token while the new one
    is unused returns another new token; the first new token then gets 401;
    the old token still works; last_rotation_at and the previous hash are
    kept; one agent.token_rotate entry per rotate."""
    a = env.in_window()
    n1 = rotated(env.rotate(a), env)
    first = env.cols(a)
    env.clock.at = T0 + timedelta(minutes=1)
    mark = env.last_audit()
    n2 = rotated(env.rotate(a), env)
    assert n2 not in (n1, a.token)
    c = env.cols(a)
    assert c["token_hash"] == token_hash(n2)
    assert c["prev_token_hash"] == token_hash(a.token)
    assert c["last_rotation_at"] == first["last_rotation_at"] == T0
    assert c["prev_token_expires_at"] is None
    assert env.actions(mark).count("agent.token_rotate") == 1
    env.clock.at = T0 + timedelta(minutes=2)
    problem(env.use(a, n1), 401, "unauthorized")
    ok_use(env.use(a, a.token))
    ok_use(env.use(a, n2))  # the first use of the fresh token


def test_the_retry_token_lives_for_the_current_ttl(env: Env) -> None:
    """TS §3.2 L190 (a change applies to tokens issued or rotated after it):
    the fresh token of a lost-response retry also gets the current
    agent_token_ttl_days, in the answer and in the row."""
    a = env.in_window()
    env.set_ttl(90)
    rotated(env.rotate(a), env, ttl_days=90)
    env.set_ttl(120)
    env.clock.at = T0 + timedelta(minutes=1)
    n2 = rotated(env.rotate(a), env, ttl_days=120)  # the retry, with the old token
    c = env.cols(a)
    assert c["token_hash"] == token_hash(n2)
    assert c["token_expires_at"] == env.clock.at + timedelta(days=120)


def test_the_retry_cannot_extend_the_thirty_day_cap(env: Env) -> None:
    """User ruling 2026-10-23: the old token after an unused rotation lives
    until last_rotation_at + 30 days; a retry at day 29 keeps
    last_rotation_at, so at day 30 the old token is 401 token_expired."""
    a = env.in_window()
    rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(days=29)
    n2 = rotated(env.rotate(a), env)  # the retry, with the old token
    assert env.cols(a)["last_rotation_at"] == T0
    env.clock.at = T0 + timedelta(days=30) - S
    ok_use(env.use(a, a.token))
    env.clock.at = T0 + timedelta(days=30)
    problem(env.use(a, a.token), 401, "token_expired")
    problem(env.rotate(a), 401, "token_expired")
    ok_use(env.use(a, n2))


# ------------------------------------------------------------ CHK-M3-268


def test_old_token_works_ten_minutes_after_the_new_ones_first_use(env: Env) -> None:
    """REQ-071 (4), #62, CHK-M3-344: the new token's first use at T+1 min;
    the old token at +9 min 59 s after that works; at +10 min it revokes both
    tokens (401 token_revoked) with one token_reuse alert."""
    a = env.in_window()
    n1 = rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(minutes=1)
    ok_use(env.use(a, n1))
    assert env.cols(a)["prev_token_expires_at"] == T0 + timedelta(minutes=11)
    env.clock.at = T0 + timedelta(minutes=10, seconds=59)
    ok_use(env.use(a, a.token))
    env.clock.at = T0 + timedelta(minutes=11)
    mark = env.last_audit()
    problem(env.use(a, a.token), 401, "token_revoked")
    assert env.kinds(mark) == ["token_reuse"]
    assert env.cols(a)["token_revoked_at"] == env.clock.at
    problem(env.use(a, n1), 401, "token_revoked")


def test_rotate_with_the_old_token_after_first_use_is_reuse(env: Env) -> None:
    """#62: a rotate with the old token after the new one was used is reuse
    even inside the 10 minutes: both revoked, 401 token_revoked, one
    token_reuse alert (action agent.token_reuse), no new token issued."""
    a = env.in_window()
    n1 = rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(minutes=1)
    ok_use(env.use(a, n1))
    env.clock.at = T0 + timedelta(minutes=2)
    before_hash = env.cols(a)["token_hash"]
    mark = env.last_audit()
    r = env.rotate(a)
    problem(r, 401, "token_revoked")
    assert "bsa_" not in r.text
    entries = env.audit_after(mark)
    reuse = [e for e in entries if e[3].get("alert_kind") == "token_reuse"]
    assert len(reuse) == 1, entries
    assert reuse[0][1] == "agent.token_reuse"
    assert reuse[0][0] == reuse[0][2] == f"agent:{a.agent_id}"
    c = env.cols(a)
    assert c["token_revoked_at"] == env.clock.at and c["token_hash"] == before_hash
    problem(env.use(a, n1), 401, "token_revoked")
    problem(env.use(a, a.token), 401, "token_revoked")
    problem(env.rotate(a, token=n1), 401, "token_revoked")


# ------------------------------------------------------------ CHK-M3-269


def test_second_rotation_within_24h_of_a_used_one_is_429(env: Env) -> None:
    """REQ-071 (5), #62, CHK-M3-269: rotate at T, the new token used at
    T+1 min, then a rotate with that (current) token at T+1 h: 429
    rate_limited with Retry-After to the end of the 24 h (82,800 s), no token
    change and no outside-window alert. (Question 1 to main, 2026-10-23: the
    service checks the window first, which answers 403 here.)"""
    a = env.in_window()
    n1 = rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(minutes=1)
    ok_use(env.use(a, n1))
    env.clock.at = T0 + timedelta(hours=1)
    before = env.cols(a)
    mark = env.last_audit()
    r = env.rotate(a, token=n1)
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == str(23 * 3600)
    assert env.cols(a) == before
    assert "rotation_outside_window" not in env.kinds(mark)


def test_after_an_unused_rotation_another_rotation_is_allowed(env: Env) -> None:
    """REQ-071 (5): the 24 h rule counts only rotations whose new token was
    used: after an unused one, rotating again within the hour succeeds (it is
    the retry with the old token) and is not 429."""
    a = env.in_window()
    rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(hours=1)
    rotated(env.rotate(a), env)


# ------------------------------------------------------------ CHK-M3-270


def test_rotation_from_a_never_seen_ip_alerts_once(env: Env) -> None:
    """REQ-071 (6): a rotation from an IP this agent was never seen from
    writes exactly one rotation_new_ip alert entry."""
    a = env.in_window()
    mark = env.last_audit()
    rotated(env.rotate(a, ip="10.75.200.1"), env)
    assert env.kinds(mark) == ["rotation_new_ip"]
    entry = [e for e in env.audit_after(mark) if e[1] == "alert.rotation_new_ip"]
    assert len(entry) == 1 and entry[0][0] == entry[0][2] == f"agent:{a.agent_id}"


@pytest.mark.parametrize(
    ("ago", "alerts"),
    [
        (timedelta(days=6), False),
        (timedelta(days=6, hours=23, minutes=59), False),
        (timedelta(days=7, seconds=1), True),
        (timedelta(days=8), True),
    ],
    ids=["6d", "6d23h59m", "7d1s", "8d"],
)
def test_rotation_new_ip_seven_day_rule(env: Env, ago: timedelta, alerts: bool) -> None:
    """REQ-071 (6): an IP last seen 6 days ago does not alert; 8 days ago it
    does (the IP's last_seen_at before this call is what counts)."""
    a = env.in_window()
    env.seen(a, "10.75.201.1", T0 - ago)
    mark = env.last_audit()
    rotated(env.rotate(a, ip="10.75.201.1"), env)
    assert env.kinds(mark) == (["rotation_new_ip"] if alerts else [])


def test_another_ip_seen_recently_does_not_cover_a_new_one(env: Env) -> None:
    """TS §3.2 L190: "a source IP not seen for this agent": the agent being
    seen recently from another IP does not cover the new one."""
    a = env.in_window()
    env.seen(a, "10.75.202.1", T0 - timedelta(hours=1))
    mark = env.last_audit()
    rotated(env.rotate(a, ip="10.75.202.2"), env)
    assert env.kinds(mark) == ["rotation_new_ip"]


def test_a_retry_from_a_never_seen_ip_alerts(env: Env) -> None:
    """TS §3.2 L190 (question 2 to main, 2026-10-23): the lost-response retry
    issues a working token, so it is a rotation; from an IP not seen for this
    agent in 7 days it alerts rotation_new_ip, as a stolen old token would."""
    a = env.in_window()
    env.seen(a, "10.75.203.1", T0 - timedelta(hours=1))
    rotated(env.rotate(a, ip="10.75.203.1"), env)
    env.clock.at = T0 + timedelta(minutes=5)
    mark = env.last_audit()
    rotated(env.rotate(a, ip="10.75.203.99"), env)  # the retry, from a new IP
    assert env.kinds(mark) == ["rotation_new_ip"]


# ------------------------------------------------------------ CHK-M3-271


def test_after_expires_at_rotate_is_401_token_expired(env: Env) -> None:
    """REQ-071 (7), REQ-064 (5), CHK-M3-342: one second before expires_at the
    rotate is accepted; at expires_at it is 401 token_expired and nothing
    changes."""
    a = env.agent(issued=T0 - timedelta(days=365), ttl_days=365)
    b = env.agent(issued=T0 - timedelta(days=365), ttl_days=365)
    env.clock.at = T0 - S
    rotated(env.rotate(b), env)
    env.clock.at = T0
    before = env.cols(a)
    mark = env.last_audit()
    problem(env.rotate(a), 401, "token_expired")
    assert env.cols(a) == before
    assert "agent.token_rotate" not in env.actions(mark)


# ------------------------------------------------------------ CHK-M3-272


def test_ttl_change_applies_only_to_tokens_issued_or_rotated_after(env: Env) -> None:
    """REQ-071 (8), REQ-083 (6), TS §3.2 L190: with agent_token_ttl_days set
    to 90, a rotation issues a 90-day token, while another agent's existing
    token keeps its expiry."""
    a, other = env.in_window(), env.in_window()
    other_before = env.cols(other)
    env.set_ttl(90)
    new = rotated(env.rotate(a), env, ttl_days=90)
    assert env.cols(a)["token_expires_at"] == T0 + timedelta(days=90)
    assert env.cols(other) == other_before
    env.set_ttl(730)
    env.clock.at = T0 + timedelta(minutes=1)
    ok_use(env.use(a, new))
    assert env.cols(a)["token_expires_at"] == T0 + timedelta(days=90)


# ------------------------------------------------------------ CHK-M3-273


@pytest.mark.parametrize(
    ("content", "status"),
    [
        (b"", 200),
        (b"{}", 200),
        (b"null", 400),
        (b'{"x": 1}', 400),
        (b"[]", 400),
        (b'"x"', 400),
        (b"1", 400),
        (b"not json", 400),
        (b"{", 400),
        (b"\xff\xfe", 400),
    ],
    ids=[
        "empty",
        "object",
        "null",
        "extra-key",
        "array",
        "string",
        "number",
        "text",
        "truncated",
        "bad-utf8",
    ],
)
def test_body_is_empty_or_an_empty_object(
    env: Env, content: bytes, status: int
) -> None:
    """#60 (decisions 2026-10-23): no body or {} only; null and anything else
    is 400 invalid_request with no token change and no entry."""
    a = env.in_window()
    before = env.cols(a)
    mark = env.last_audit()
    r = env.rotate(a, content=content)
    if status == 200:
        rotated(r, env)
    else:
        problem(r, 400, "invalid_request")
        assert env.cols(a) == before
        assert env.audit_after(mark) == []


def test_bad_body_without_a_token_is_401(env: Env) -> None:
    a = env.in_window()
    r = env.client("10.75.250.2").post(
        TEMPLATE.replace("{id}", str(a.agent_id)),
        content=b"null",
        headers={"Content-Type": "application/json"},
    )
    problem(r, 401, "unauthorized")


def test_body_over_one_mib_is_413(env: Env) -> None:
    a = env.in_window()
    before = env.cols(a)
    problem(env.rotate(a, content=b"{" + b" " * 1_048_576 + b"}"), 413, "too_large")
    assert env.cols(a) == before


ROTATE_FIXTURES = list(loader.select("rotate", "request"))


@pytest.mark.parametrize("fx", ROTATE_FIXTURES, ids=lambda f: f.id)
def test_rotate_request_fixtures_through_the_route(
    env: Env, fx: loader.Fixture
) -> None:
    """REQ-060, REQ-061: valid fixtures rotate; invalid ones are 400."""
    a = env.in_window()
    r = env.rotate(a, content=fx.body_bytes())
    if fx.valid:
        rotated(r, env)
    else:
        problem(r, 400, "invalid_request")


def test_only_hashes_are_stored(env: Env) -> None:
    """REQ-063 (2), (3): after a rotation, a retry and a first use, no agent
    column and no audit entry holds any issued token; the stored hashes are
    the SHA-256 hex of the whole tokens."""
    a = env.in_window()
    n1 = rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(minutes=1)
    n2 = rotated(env.rotate(a), env)
    env.clock.at = T0 + timedelta(minutes=2)
    ok_use(env.use(a, n2))
    row = env.whole_row(a)
    for t in (a.token, n1, n2):
        assert t not in row and t[4:] not in row
    c = env.cols(a)
    assert (c["token_hash"], c["prev_token_hash"]) == (
        token_hash(n2),
        token_hash(a.token),
    )
    with env.conn() as conn:
        for t in (a.token, n1, n2):
            hit = conn.execute(
                "SELECT count(*) FROM audit_log WHERE detail::text LIKE %s"
                " OR detail::text LIKE %s",
                (f"%{t[4:]}%", f"%{token_hash(t)}%"),
            ).fetchone()
            assert hit == (0,)


def _post_rotate(env: Env, a: Agent, ip: str, out: list[Any], lock: Any) -> None:
    client = TestClient(env.app, client=(ip, 1234), raise_server_exceptions=False)
    try:
        r = client.post(
            TEMPLATE.replace("{id}", str(a.agent_id)), headers=env.headers(a, None)
        )
        with lock:
            out.append((ip, r))
    finally:
        client.close()


def _waiting_on_locks(env: Env) -> int:
    with env.conn() as c:
        row = c.execute("SELECT count(*) FROM pg_locks WHERE NOT granted").fetchone()
    assert row is not None
    return int(row[0])


def _both_checked_then_serialised(
    env: Env, a: Agent, ips: tuple[str, str]
) -> list[tuple[str, Any]]:
    """Two rotates with the same current token whose token checks both pass
    before either rotates: the agent row is held FOR UPDATE by another
    connection until both requests wait on a lock (each has read the token
    as current), then released, so the row lock serialises them."""
    out: list[tuple[str, Any]] = []
    lock = threading.Lock()
    holder = psycopg.connect(env.server.dsn("bitscan_app"))
    try:
        holder.execute(
            "SELECT 1 FROM agent WHERE agent_id = %s FOR UPDATE", (a.agent_id,)
        )
        threads = [
            threading.Thread(target=_post_rotate, args=(env, a, ip, out, lock))
            for ip in ips
        ]
        for t in threads:
            t.start()
        deadline = datetime.now(UTC) + timedelta(seconds=30)
        while _waiting_on_locks(env) < 2:
            assert datetime.now(UTC) < deadline, "the rotates never waited on the row"
            threading.Event().wait(0.05)
        assert not out  # neither answered while the row was held
    finally:
        holder.rollback()
        holder.close()
    for t in threads:
        t.join(timeout=60)
    assert len(out) == 2, out
    return out


def test_simultaneous_rotates_with_one_token_give_a_rotation_and_a_retry(
    env: Env,
) -> None:
    """User ruling 2026-10-23 (TASK-075 revision 2), #62: two rotates with the
    same current token, both checked before either rotated. The first rotates;
    the second, whose token has just become the previous one with the new
    token unused, is the lost-response retry: 200 with another fresh token, no
    403 and no rotation_outside_window alert. Afterwards the state is exactly
    that of a rotation plus a retry: the retry's token is current, the
    previous hash is the presented token's, last_rotation_at = T0 and the
    overlap unset; the first new token is dead, the presented one still works;
    one agent.token_rotate entry with retry false and one with retry true,
    no token in any entry."""
    a = env.in_window()
    for ip in ("10.75.241.1", "10.75.241.2"):
        env.seen(a, ip, T0 - timedelta(hours=1))
    mark = env.last_audit()
    out = _both_checked_then_serialised(env, a, ("10.75.241.1", "10.75.241.2"))
    assert [r.status_code for _, r in out] == [200, 200], [
        (r.status_code, r.text) for _, r in out
    ]
    tokens = [rotated(r, env) for _, r in out]
    assert len(set(tokens)) == 2 and a.token not in tokens
    c = env.cols(a)
    current = [t for t in tokens if token_hash(t) == c["token_hash"]]
    assert len(current) == 1, "the stored hash must be one of the two answers"
    dead = next(t for t in tokens if t != current[0])
    assert c["prev_token_hash"] == token_hash(a.token)
    assert c["prev_token_expires_at"] is None
    assert c["last_rotation_at"] == T0 and c["token_revoked_at"] is None
    entries = env.audit_after(mark)
    assert env.kinds(mark) == [], entries  # no outside-window, no new-IP alert
    rot = [e[3] for e in entries if e[1] == "agent.token_rotate"]
    assert sorted(d["retry"] for d in rot) == [False, True], entries
    assert [e[1] for e in entries] == ["agent.token_rotate"] * 2, entries
    text = json.dumps([e[3] for e in entries])
    for t in (a.token, *tokens):
        assert t[4:] not in text and token_hash(t) not in text
    env.clock.at = T0 + timedelta(minutes=1)
    problem(env.use(a, dead), 401, "unauthorized")
    ok_use(env.use(a, a.token))
    ok_use(env.use(a, current[0]))  # its first use starts the overlap
    assert env.cols(a)["prev_token_expires_at"] == T0 + timedelta(minutes=11)


def test_simultaneous_rotates_keep_the_new_ip_rule(env: Env) -> None:
    """Revision 2: the retry path still applies the 7-day new-IP rule, on the
    IP's last_seen_at before each call. One call from an IP seen an hour ago
    and one from an IP last seen 8 days ago: exactly one rotation_new_ip
    entry, whichever of the two became the retry, and no other alert."""
    a = env.in_window()
    env.seen(a, "10.75.242.1", T0 - timedelta(hours=1))
    env.seen(a, "10.75.242.2", T0 - timedelta(days=8))
    mark = env.last_audit()
    out = _both_checked_then_serialised(env, a, ("10.75.242.1", "10.75.242.2"))
    assert [r.status_code for _, r in out] == [200, 200]
    assert env.kinds(mark) == ["rotation_new_ip"], env.audit_after(mark)


def test_simultaneous_rotates_from_two_new_ips_alert_twice(env: Env) -> None:
    """Revision 2: two simultaneous rotates from two IPs never seen for this
    agent are a rotation and a retry, each from a new IP: two rotation_new_ip
    entries and no rotation_outside_window."""
    a = env.in_window()
    mark = env.last_audit()
    out = _both_checked_then_serialised(env, a, ("10.75.243.1", "10.75.243.2"))
    assert [r.status_code for _, r in out] == [200, 200]
    assert env.kinds(mark) == ["rotation_new_ip", "rotation_new_ip"]


def test_concurrent_rotations_are_one_rotation_and_retries(env: Env) -> None:
    """Row lock plus revision 2: four simultaneous rotates with the same
    in-window token (barrier, real interleaving): every one is 200 (one
    rotation, three lost-response retries, whichever order), the four tokens
    differ, the stored hash is one of them and only that one works besides
    the presented token; one entry with retry false; no window alert, no
    5xx."""
    a = env.in_window()
    for n in range(4):
        env.seen(a, f"10.75.240.{n}", T0 - timedelta(hours=1))
    barrier = threading.Barrier(4)
    out: list[Any] = []
    lock = threading.Lock()
    mark = env.last_audit()

    def one(n: int) -> None:
        client = TestClient(
            env.app, client=(f"10.75.240.{n}", 1234), raise_server_exceptions=False
        )
        try:
            barrier.wait(timeout=30)
            r = client.post(
                TEMPLATE.replace("{id}", str(a.agent_id)), headers=env.headers(a, None)
            )
            with lock:
                out.append(r)
        finally:
            client.close()

    threads = [threading.Thread(target=one, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert [r.status_code for r in out] == [200] * 4, [
        (r.status_code, r.text) for r in out
    ]
    tokens = [rotated(r, env) for r in out]
    assert len(set(tokens)) == 4
    c = env.cols(a)
    assert sum(token_hash(t) == c["token_hash"] for t in tokens) == 1
    assert c["prev_token_hash"] == token_hash(a.token)
    assert env.kinds(mark) == []
    rot = [e[3]["retry"] for e in env.audit_after(mark) if e[1] == "agent.token_rotate"]
    assert sorted(rot) == [False, True, True, True]
    env.clock.at = T0 + timedelta(minutes=1)
    for tok in tokens:
        if token_hash(tok) != c["token_hash"]:
            problem(env.use(a, tok), 401, "unauthorized")
    ok_use(env.use(a, a.token))


def test_a_waiting_rotate_after_the_new_token_was_used_issues_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision 2 boundary (impl report r2): call B is checked with the
    current token, then waits; meanwhile A rotates and A's new token is used
    (the overlap starts). B then gets the row: the ruling's retry needs the
    new token unused, so B is not a retry: it issues no token, writes no
    rotation_outside_window alert and stays on the current-token path, where
    the 24 h rule answers 429 (r1). The state is A's rotation plus the first
    use, unchanged by B. B is held between its token check and the service
    by a test-only gate around rotation.rotate_token."""
    from bitscan_manager.services.enrolment import rotation

    real = rotation.rotate_token
    gate, entered = threading.Event(), threading.Event()
    held = {"first": True}

    def gated(*args: Any, **kwargs: Any) -> Any:
        if held.pop("first", False):
            entered.set()
            assert gate.wait(timeout=30)
        return real(*args, **kwargs)

    monkeypatch.setattr(rotation, "rotate_token", gated)
    a = env.in_window()
    env.seen(a, "10.75.244.1", T0 - timedelta(hours=1))
    out: list[Any] = []
    b = threading.Thread(
        target=_post_rotate, args=(env, a, "10.75.244.1", out, threading.Lock())
    )
    b.start()
    try:
        assert entered.wait(timeout=30)
        n1 = rotated(env.rotate(a, ip="10.75.244.1"), env)  # A
        env.clock.at = T0 + timedelta(minutes=1)
        ok_use(env.use(a, n1, ip="10.75.244.1"))
        after_use = env.cols(a)
        mark = env.last_audit()
    finally:
        gate.set()
        b.join(timeout=60)
    assert len(out) == 1
    r = out[0][1]
    problem(r, 429, "rate_limited")
    assert "bsa_" not in r.text
    assert env.cols(a) == after_use
    assert env.kinds(mark) == [] and env.actions(mark) == []
    ok_use(env.use(a, n1, ip="10.75.244.1"))


def test_openapi_documents_the_rotate_operation() -> None:
    """REQ-060 (1), (5), TS §6.5 L1188, #60: POST only; an optional
    requestBody -> RotateRequest (no properties, additionalProperties false);
    200 -> RotateResponse with exactly the three keys, all required;
    refusals problem+json; no 422."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert set(doc["paths"][TEMPLATE]) == {"post"}
    op = doc["paths"][TEMPLATE]["post"]
    assert op["requestBody"].get("required", False) is False
    assert op["requestBody"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RotateRequest"}}
    }
    comps = doc["components"]["schemas"]
    req = comps["RotateRequest"]
    assert req["additionalProperties"] is False and not req.get("properties")
    resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert resp == {"$ref": "#/components/schemas/RotateResponse"}
    rr = comps["RotateResponse"]
    assert sorted(rr["properties"]) == sorted(KEYS) == sorted(rr["required"])
    assert rr["additionalProperties"] is False
    assert "422" not in op["responses"]
    for status in ("400", "401", "403", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]


# ------------------------------------------------- matrix (CHK-M3-160 to -163)


def test_wrong_tokens_are_one_401_and_rotate_nothing(env: Env) -> None:
    """REQ-062 (2) on the real route: no header, Basic, empty bearer, a user
    token, a live bse_, an unknown bsa_ and an unknown prefix: one
    byte-identical 401 and no token change."""
    a = env.in_window()
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    with env.conn() as c:
        c.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
            " created_by) VALUES (%s, 10, %s, 1)",
            (token_hash(bse), T0 + DAY),
        )
    before = env.cols(a)
    mark = env.last_audit()
    bodies = set()
    path = TEMPLATE.replace("{id}", str(a.agent_id))
    for h in (
        {},
        {"Authorization": f"Basic {a.token}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {new_token(TokenKind.API)}"},
        {"Authorization": f"Bearer {new_token(TokenKind.SESSION)}"},
        {"Authorization": f"Bearer {bse}"},
        {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
    ):
        r = env.client("10.75.250.3").post(
            path, headers=h | {"X-Bitscan-Machine-Id": a.machine_id}
        )
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1
    assert env.cols(a) == before
    assert env.audit_after(mark) == []


def test_token_outcomes_rotate_nothing(env: Env) -> None:
    """REQ-064 on the real route (all tokens in their window): revoked,
    pending, decommissioned, foreign {id} and mismatch get their #59 answer;
    no token changes; only a mismatch writes its own alert."""
    revoked = env.in_window()
    with env.conn() as c:
        c.execute(
            "UPDATE agent SET token_revoked_at = %s WHERE agent_id = %s",
            (T0 - S, revoked.agent_id),
        )
    pending = env.in_window()
    decom = env.in_window()
    with env.conn() as c:
        c.execute(
            "UPDATE agent SET status = 'awaiting_approval' WHERE agent_id = %s",
            (pending.agent_id,),
        )
        c.execute(
            "UPDATE agent SET status = 'decommissioned', token_revoked_at = %s"
            " WHERE agent_id = %s",
            (T0 - DAY, decom.agent_id),
        )
    other, mismatch = env.in_window(), env.in_window()
    cases: list[tuple[Agent, dict[str, Any], int, str]] = [
        (revoked, {}, 401, "token_revoked"),
        (pending, {}, 403, "pending_approval"),
        (decom, {}, 401, "token_revoked"),
        (other, {"path_id": str(revoked.agent_id)}, 403, "forbidden"),
        (
            mismatch,
            {"headers": {"X-Bitscan-Machine-Id": "f" * 32}},
            401,
            "machine_id_mismatch",
        ),
    ]
    for a, kw, status, type_ in cases:
        before = (env.cols(a), env.cols(revoked))
        mark = env.last_audit()
        problem(env.rotate(a, **kw), status, type_)
        after = env.cols(a)
        if type_ == "machine_id_mismatch":
            assert after["token_revoked_at"] == T0
            after = after | {"token_revoked_at": None}
        assert (after, env.cols(revoked)) == before, type_
        assert "agent.token_rotate" not in env.actions(mark)
        assert env.kinds(mark) == (
            ["machine_id_mismatch"] if type_ == "machine_id_mismatch" else []
        )


def test_thirty_requests_a_minute_then_429(env: Env) -> None:
    """REQ-065 (1) on the real route: the 31st request in a minute is 429
    with Retry-After and rotates nothing."""
    a = env.in_window()
    env.clock.at = T0 + timedelta(seconds=5)
    for _ in range(30):
        ok_use(env.use(a, a.token))
    before = env.cols(a)
    r = env.rotate(a)
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"
    assert env.cols(a) == before


# ------------------------------------------------------------ CHK-M3-169


def test_rotate_is_in_the_agent_group_with_the_bsa_dependency() -> None:
    """REQ-062 (1): the route exists once, POST only, carries the bsa_
    dependency and no user dependency."""
    app = create_app()
    routes = [r for r in api_routes(app.routes) if r.path == TEMPLATE]
    assert len(routes) == 1 and routes[0].methods == {"POST"}
    marks: set[Any] = set()
    stack = list(routes[0].dependant.dependencies)
    while stack:
        dep = stack.pop()
        marks.add(getattr(dep.call, "bitscan_agent_auth", None))
        assert getattr(dep.call, "bitscan_auth", None) is None
        stack.extend(dep.dependencies)
    assert "bsa_" in marks and "bse_" not in marks
