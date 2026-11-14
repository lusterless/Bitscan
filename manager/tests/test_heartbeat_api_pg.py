"""TASK-072: POST /api/v1/agent/{id}/heartbeat on PostgreSQL (TP-M3-26).

Checks CHK-M3-235 to CHK-M3-242 of tests/m3/test-plan.md, the mutation rows
CHK-M3-345, -367 and -368, and the re-run of the agent-route matrix
(CHK-M3-160 to -163) and route walk (CHK-M3-169) on the real heartbeat route.
Expected values come from the spec and the answers, not from the code: TS §3.3
L202 (the response carries only job_pull_seconds, max_parallel_plugins and the
server time, never jobs or commands), L211-L212 (alert on clock skew over 5
minutes), L218 (status), TS §3.7 L484 (helpers reported in every heartbeat; the
manager shows and audit-logs any change), TS §6.1 L1063, §6.5 L1163 (the body),
§6.3 L1138 (1 MiB for other agent bodies), §8.4 L1287-L1291 (logs carry
agent_id; alert delivery; helper change immediate; clock skew threshold), #25
(a) (uptime_s, spool_bytes, last_pull_at, current_job_id dropped; last_error
logged at INFO with the agent_id, never audited), (b) (every authenticated call
records the IP), #59 (statuses and types), #65 (a) (at most one clock-skew alert
per agent per hour while it lasts), #71 (actor agent:<id>; action
agent.runner_helpers_change with the runner_helper_changed alert, one entry per
event; alert.<kind> for threshold alerts), #73 (a) (enrolled, stale, offline
become online at once), REQ-070 (1)-(6), REQ-086 (2), REQ-088 (4). Lead
ruling 2026-10-23: a threshold window is marked fired only after its alert
commits, so a rolled-back alert leaves the slot free.
"""

import importlib
import io
import json
import logging
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.api.agent import schemas
from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.api.request_log import configure_logging
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import REGISTRY
from tests.contract import loader

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_contract_agent import OPENAPI, RFC3339, validator
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, 250_000, tzinfo=UTC)
TEMPLATE = "/api/v1/agent/{id}/heartbeat"
# Agents below 0.5.0 get exactly the three keys; 0.5.0 and later also get
# max_parallel_jobs (TS §6.5; owner decision 2026-11-14). The test agents
# report 1.0.0.
OLD_KEYS = ["job_pull_seconds", "max_parallel_plugins", "server_time"]
KEYS = [*OLD_KEYS, "max_parallel_jobs"]
MIB = 1_048_576
HEARTBEAT_COLS = ("last_heartbeat_at", "agent_version", "runner_helpers", "status")


def iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
    limits: RateLimiter
    app: FastAPI
    db: AppDatabase
    _ip: int = 0
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def fresh_ip(self) -> str:
        self._ip += 1
        return f"10.72.{self._ip // 256}.{self._ip % 256}"

    def client(self, ip: str | None = None) -> TestClient:
        ip = ip or self.fresh_ip()
        if ip not in self.clients:
            self.clients[ip] = TestClient(
                self.app, client=(ip, 1234), raise_server_exceptions=False
            )
        return self.clients[ip]

    def agent(self, status: str = "online", **cols: Any) -> Agent:
        tok = new_agent_token(AgentTokenKind.AGENT)
        machine = secrets.token_hex(16)
        values: dict[str, Any] = {
            "machine_id": machine,
            "hostname": f"hb-{secrets.token_hex(3)}",
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

    def request(self, a: Agent, kind: str, decision: str | None) -> str:
        """An enrollment_request for agent a; returns its new token."""
        new = new_agent_token(AgentTokenKind.AGENT)
        with self.conn() as c:
            tid = c.execute(
                "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
                " created_by) VALUES (%s, 10, %s, 1) RETURNING token_id",
                (
                    token_hash(new_agent_token(AgentTokenKind.ENROLMENT)),
                    T0 + timedelta(days=1),
                ),
            ).fetchone()
            assert tid is not None
            c.execute(
                "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id,"
                " hostname, machine_id, agent_version, new_token_hash,"
                " token_expires_at, source_ip, requested_at, decision, decided_at)"
                " VALUES (%s, %s, %s, 'h', %s, '1', %s, %s, '10.0.0.1', %s, %s, %s)",
                (
                    kind,
                    a.agent_id,
                    tid[0],
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
        """An admin with TOTP; a TOTP-verified session or an API token."""
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', 'admin', 'enc', 1, %s)"
                " RETURNING user_id",
                (f"hb-{secrets.token_hex(4)}", T0),
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
                    T0 + timedelta(days=400),
                    T0,
                ),
            )
        return tok

    def body(self, **over: Any) -> dict[str, Any]:
        return {
            "agent_version": "1.0.0",
            "uptime_s": 3600,
            "last_pull_at": None,
            "current_job_id": None,
            "spool_bytes": 0,
            "last_error": None,
            "runner_helpers": [],
            "clock": iso(self.clock.now()),
        } | over

    def hb(
        self,
        a: Agent | None,
        body: dict[str, Any] | None = None,
        *,
        ip: str | None = None,
        token: str | None = None,
        machine: str | None = "same",
        path_id: str | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        h: dict[str, str] = dict(headers or {})
        tok = token if token is not None else (a.token if a else None)
        if tok:
            h.setdefault("Authorization", f"Bearer {tok}")
        if machine == "same" and a is not None:
            h["X-Bitscan-Machine-Id"] = a.machine_id
        elif machine not in (None, "same"):
            h["X-Bitscan-Machine-Id"] = machine
        pid = path_id or (str(a.agent_id) if a else str(UUID(int=1)))
        path = TEMPLATE.replace("{id}", pid)
        c = self.client(ip)
        if content is not None:
            h.setdefault("Content-Type", "application/json")
            return c.post(path, content=content, headers=h)
        return c.post(path, json=body if body is not None else self.body(), headers=h)

    def row(self, agent_id: UUID) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (agent_id,))
            values = cur.fetchone()
            cols = [d.name for d in cur.description or []]
        assert values is not None
        return dict(zip(cols, values, strict=True))

    def beat_cols(self, agent_id: UUID) -> tuple[Any, ...]:
        row = self.row(agent_id)
        return tuple(row[c] for c in HEARTBEAT_COLS)

    def ips(self, agent_id: UUID) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT host(ip), first_seen_at, last_seen_at FROM agent_ip_seen"
                " WHERE agent_id = %s ORDER BY 1",
                (agent_id,),
            ).fetchall()

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

    def jobs(self) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute("SELECT * FROM scan_job ORDER BY job_id").fetchall()

    def patch_settings(self, session: str, body: dict[str, Any]) -> Any:
        return self.client("10.72.250.1").patch(
            "/api/v1/settings",
            json=body,
            headers={"Authorization": f"Bearer {session}"},
        )


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=12, connect_timeout_s=5
    )
    db.open()
    limits = RateLimiter(clock)
    rt = Runtime(
        clock=clock, db=db, totp_cipher=Cipher(), sink_gate=Gate(), limits=limits
    )
    e = Env(migrated_db, clock, limits, create_app(rt), db)
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


def problem(r: Any, status: int, type_: str) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == type_, r.json()


def alerts_counted(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


def latency_count() -> float:
    return REGISTRY.get_sample_value("bitscan_heartbeat_latency_seconds_count") or 0.0


def current_settings(env: Env) -> tuple[int, int]:
    with env.conn() as c:
        rows = dict(
            c.execute(
                "SELECT key, value FROM setting WHERE key IN"
                " ('job_pull_seconds', 'max_parallel_plugins')"
            ).fetchall()
        )
    return int(rows["job_pull_seconds"]), int(rows["max_parallel_plugins"])


def response_schema_errors(body: Any) -> list[Any]:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    node = doc["paths"][TEMPLATE]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    return list(validator({**doc, **node}).iter_errors(body))


def ok(r: Any) -> dict[str, Any]:
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/json")
    body: dict[str, Any] = r.json()
    want = KEYS if "max_parallel_jobs" in body else OLD_KEYS
    assert list(body) == want, body  # exactly these keys (REQ-070 (1))
    assert not response_schema_errors(body)
    schemas.HeartbeatResponse.model_validate_json(r.content)
    return body


# ------------------------------------------------------------ CHK-M3-235


def test_response_is_exactly_the_three_configuration_keys(env: Env) -> None:
    """REQ-070 (1), REQ-088 (4), CHK-M3-345: configuration only, from the
    current settings; server_time = the fake clock, RFC 3339 UTC."""
    a = env.agent()
    body = ok(env.hb(a))
    assert (body["job_pull_seconds"], body["max_parallel_plugins"]) == current_settings(
        env
    )
    assert RFC3339.match(body["server_time"]) and body["server_time"].endswith("Z")
    assert parse(body["server_time"]) == T0
    for word in ("jobs", "job_id", "command", "execute", "plugins"):
        assert word not in body


@pytest.mark.parametrize(
    ("version", "sent"),
    [
        ("0.2.0-1", False),
        ("0.4.1-1", False),
        ("0.5.0~rc1-1", False),
        ("dev", False),
        ("0.5.0", True),
        ("0.5.0-1", True),
        ("0.10.0-1", True),
        ("1.0.0", True),
    ],
)
def test_max_parallel_jobs_only_for_agents_0_5_0_or_later(
    env: Env, version: str, sent: bool
) -> None:
    """TS §3.3, §6.5, §8.3 Integration (owner decision 2026-11-14): agents
    0.3.0 to 0.4.1 refuse an unknown key, so they get exactly the three
    keys; 0.5.0 or later also get the max_parallel_jobs setting."""
    a = env.agent()
    body = ok(env.hb(a, env.body(agent_version=version)))
    if not sent:
        assert list(body) == OLD_KEYS
        return
    with env.conn() as c:
        row = c.execute(
            "SELECT value FROM setting WHERE key = 'max_parallel_jobs'"
        ).fetchone()
    assert row is not None and body["max_parallel_jobs"] == int(row[0]) == 2


def test_seeded_defaults_are_answered(env: Env) -> None:
    """TS §8.6: job_pull_seconds 300, max_parallel_plugins 2 by default."""
    with env.server.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        oc.execute("UPDATE setting SET value = '300' WHERE key = 'job_pull_seconds'")
        oc.execute("UPDATE setting SET value = '2' WHERE key = 'max_parallel_plugins'")
    body = ok(env.hb(env.agent()))
    assert (body["job_pull_seconds"], body["max_parallel_plugins"]) == (300, 2)


def test_patch_settings_changes_the_next_answer(env: Env) -> None:
    """REQ-070 (1): after PATCH /settings the next heartbeat returns the new
    values (never a cached copy), at both ends of the ranges."""
    a = env.agent()
    session = env.user_token("session")
    for pull, par in ((600, 5), (60, 1), (3600, 8)):
        r = env.patch_settings(
            session, {"job_pull_seconds": pull, "max_parallel_plugins": par}
        )
        assert r.status_code == 200, r.text
        env.clock.at += timedelta(minutes=5)
        body = ok(env.hb(a))
        assert (body["job_pull_seconds"], body["max_parallel_plugins"]) == (pull, par)
        assert parse(body["server_time"]) == env.clock.now()


def test_server_time_is_utc_whatever_the_clock_offset(env: Env) -> None:
    """#60: output timestamps are UTC with Z; the instant is the clock's."""
    a = env.agent()
    env.clock.at = (T0 + timedelta(microseconds=123_456)).astimezone(
        timezone(timedelta(hours=8))
    )
    body = ok(env.hb(a, env.body(clock=iso(env.clock.at))))
    assert body["server_time"].endswith("Z")
    assert parse(body["server_time"]) == env.clock.at


# ------------------------------------------------------------ CHK-M3-236


def test_heartbeat_records_time_ip_version_and_helpers(env: Env) -> None:
    """REQ-070 (2), #25 (b): last_heartbeat_at, last_seen_ip, agent_version and
    runner_helpers are stored; nothing else in the row changes."""
    a = env.agent(last_heartbeat_at=T0 - timedelta(minutes=5))
    before = env.row(a.agent_id)
    ok(
        env.hb(
            a,
            env.body(agent_version="2.0.0-rc.1", runner_helpers=["capread"]),
            ip="10.72.200.9",
        )
    )
    after = env.row(a.agent_id)
    assert after["last_heartbeat_at"] == T0
    assert str(after["last_seen_ip"]) == "10.72.200.9"
    assert after["agent_version"] == "2.0.0-rc.1"
    assert after["runner_helpers"] == ["capread"]
    assert after["status"] == "online"
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {
        "last_heartbeat_at",
        "last_seen_ip",
        "agent_version",
        "runner_helpers",
    }
    assert env.ips(a.agent_id) == [("10.72.200.9", T0, T0)]
    env.clock.at = T0 + timedelta(minutes=5)
    ok(env.hb(a, env.body(runner_helpers=["capread"]), ip="10.72.200.10"))
    later = env.row(a.agent_id)
    assert later["last_heartbeat_at"] == env.clock.at
    assert str(later["last_seen_ip"]) == "10.72.200.10"
    assert later["agent_version"] == "1.0.0"
    assert env.ips(a.agent_id) == [
        ("10.72.200.10", env.clock.at, env.clock.at),
        ("10.72.200.9", T0, T0),
    ]


@pytest.mark.parametrize(
    ("status", "last"),
    [
        ("enrolled", None),
        ("stale", T0 - timedelta(minutes=20)),
        ("offline", T0 - timedelta(hours=5)),
        ("online", T0 - timedelta(minutes=4)),
    ],
)
def test_status_becomes_online_at_once(
    env: Env, status: str, last: datetime | None
) -> None:
    """#73 (a): enrolled, stale and offline become online on the heartbeat."""
    a = env.agent(status=status, last_heartbeat_at=last)
    ok(env.hb(a))
    row = env.row(a.agent_id)
    assert row["status"] == "online"
    assert row["last_heartbeat_at"] == T0


# ------------------------------------------------------------ CHK-M3-237


def helper_entries(env: Env, after: int, a: Agent) -> list[tuple[Any, ...]]:
    return [
        e
        for e in env.audit_after(after)
        if e[3].get("alert_kind") == "runner_helper_changed"
        or e[1] == "agent.runner_helpers_change"
    ]


def test_helper_change_writes_one_entry_and_the_same_list_none(env: Env) -> None:
    """REQ-070 (3), TS §3.7 L484, #71, CHK-M3-368."""
    a = env.agent()  # runner_helpers DEFAULT '[]' (TS §5.2)
    assert env.row(a.agent_id)["runner_helpers"] == []
    mark = env.last_audit()
    counted = alerts_counted("runner_helper_changed")
    ok(env.hb(a, env.body(runner_helpers=[])))
    assert env.audit_after(mark) == []  # [] → []: nothing

    ok(env.hb(a, env.body(runner_helpers=["capread"])))
    entries = env.audit_after(mark)
    assert len(entries) == 1, entries  # one entry: the audit entry and the alert
    actor, action, target, detail = entries[0]
    assert actor == target == f"agent:{a.agent_id}"
    assert action == "agent.runner_helpers_change"
    assert detail["alert"] is True and detail["alert_kind"] == "runner_helper_changed"
    values = list(detail.values())
    assert [] in values and ["capread"] in values  # the old and the new list
    assert alerts_counted("runner_helper_changed") == counted + 1

    mark = env.last_audit()
    for _ in range(3):  # the same list again: nothing
        env.clock.at += timedelta(minutes=5)
        ok(env.hb(a, env.body(runner_helpers=["capread"])))
    assert env.audit_after(mark) == []
    assert alerts_counted("runner_helper_changed") == counted + 1

    ok(env.hb(a, env.body(runner_helpers=[])))  # disabled again: one entry
    entries = env.audit_after(mark)
    assert len(entries) == 1 and entries[0][1] == "agent.runner_helpers_change"
    assert ["capread"] in entries[0][3].values() and [] in entries[0][3].values()
    assert env.row(a.agent_id)["runner_helpers"] == []
    assert alerts_counted("runner_helper_changed") == counted + 2


def test_concurrent_heartbeats_judge_a_change_once(env: Env) -> None:
    """Six simultaneous heartbeats reporting the same new helper: one entry."""
    a = env.agent()
    mark = env.last_audit()
    barrier = threading.Barrier(6)
    codes: list[int] = []
    lock = threading.Lock()

    def beat(i: int) -> None:
        with TestClient(
            env.app, client=(f"10.72.201.{i}", 1), raise_server_exceptions=False
        ) as c:
            barrier.wait(timeout=30)
            r = c.post(
                TEMPLATE.replace("{id}", str(a.agent_id)),
                json=env.body(runner_helpers=["capread"]),
                headers={
                    "Authorization": f"Bearer {a.token}",
                    "X-Bitscan-Machine-Id": a.machine_id,
                },
            )
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=beat, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert codes == [200] * 6
    assert len(helper_entries(env, mark, a)) == 1


# ------------------------------------------------------------ CHK-M3-238


def skew_entries(env: Env, after: int) -> list[tuple[Any, ...]]:
    return [e for e in env.audit_after(after) if e[3].get("alert_kind") == "clock_skew"]


def times_in(detail: dict[str, Any]) -> set[datetime]:
    out = set()
    for v in detail.values():
        if isinstance(v, str):
            try:
                out.add(parse(v))
            except ValueError:
                pass
    return out


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(minutes=5, seconds=1),
        -timedelta(minutes=5, seconds=1),
        timedelta(minutes=5, milliseconds=1),
        timedelta(days=3),
    ],
    ids=["ahead-5m1s", "behind-5m1s", "ahead-5m-plus-1ms", "ahead-3d"],
)
def test_skew_over_five_minutes_alerts_once_with_both_times(
    env: Env, offset: timedelta
) -> None:
    """REQ-070 (4), TS §3.3 L212, §6.5 L1163, CHK-M3-367: one clock_skew alert
    entry holding the agent's clock and the server time."""
    a = env.agent()
    mark = env.last_audit()
    counted = alerts_counted("clock_skew")
    agent_clock = T0 + offset
    body = ok(env.hb(a, env.body(clock=iso(agent_clock))))
    assert parse(body["server_time"]) == T0  # the answer is unchanged
    entries = skew_entries(env, mark)
    assert len(entries) == 1, env.audit_after(mark)
    actor, action, target, detail = entries[0]
    assert actor == target == f"agent:{a.agent_id}"
    assert action == "alert.clock_skew"  # #71: alert.<kind> for threshold alerts
    assert detail["alert"] is True
    assert {agent_clock, T0} <= times_in(detail), detail  # both times
    assert alerts_counted("clock_skew") == counted + 1
    assert env.row(a.agent_id)["last_heartbeat_at"] == T0  # still recorded


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(minutes=5),
        -timedelta(minutes=5),
        timedelta(minutes=4, seconds=59),
        timedelta(0),
    ],
    ids=["ahead-exactly-5m", "behind-exactly-5m", "ahead-4m59s", "none"],
)
def test_skew_of_five_minutes_or_less_does_not_alert(
    env: Env, offset: timedelta
) -> None:
    a = env.agent()
    mark = env.last_audit()
    counted = alerts_counted("clock_skew")
    ok(env.hb(a, env.body(clock=iso(T0 + offset))))
    assert env.audit_after(mark) == []
    assert alerts_counted("clock_skew") == counted


def test_skew_alerts_once_per_agent_per_hour_while_it_lasts(env: Env) -> None:
    """#65 (a): at most one alert per agent per hour; another agent alerts on
    its own; after the hour a lasting skew alerts again."""
    a, b = env.agent(), env.agent()
    mark = env.last_audit()

    def skewed(agent: Agent) -> None:
        ok(env.hb(agent, env.body(clock=iso(env.clock.now() + timedelta(minutes=10)))))

    skewed(a)
    assert len(skew_entries(env, mark)) == 1
    for minutes in (5, 30, 59):
        env.clock.at = T0 + timedelta(minutes=minutes)
        skewed(a)
    env.clock.at = T0 + timedelta(minutes=59, seconds=59)
    skewed(a)
    env.clock.at = T0 + timedelta(minutes=10)
    skewed(b)  # b's first skewed heartbeat: its own alert
    entries = skew_entries(env, mark)
    assert [e[2] for e in entries] == [f"agent:{a.agent_id}", f"agent:{b.agent_id}"]
    env.clock.at = T0 + timedelta(hours=1, seconds=1)
    skewed(a)  # the skew lasts past the hour: a second alert for a
    entries = skew_entries(env, mark)
    assert [e[2] for e in entries] == [
        f"agent:{a.agent_id}",
        f"agent:{b.agent_id}",
        f"agent:{a.agent_id}",
    ]


def test_manager_150_days_ahead_of_three_agents_alerts_for_each(env: Env) -> None:
    """REQ-070 (4): with the manager's fake clock 150 days ahead, each of three
    agents' first heartbeats alerts, and every entry shows the same skew, so a
    manager-wide skew can be told apart from one host's."""
    agents = [env.agent() for _ in range(3)]
    mark = env.last_audit()
    env.clock.at = T0 + timedelta(days=150)
    for a in agents:
        ok(env.hb(a, env.body(clock=iso(T0))))
    entries = skew_entries(env, mark)
    assert sorted(e[2] for e in entries) == sorted(
        f"agent:{a.agent_id}" for a in agents
    )
    for e in entries:
        assert {T0, T0 + timedelta(days=150)} <= times_in(e[3])


def test_a_rolled_back_alert_leaves_the_hour_free(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead ruling 2026-10-23 (commit-only marking): a heartbeat whose
    transaction fails after the alerts were written leaves no entry and no
    count, records nothing, and the next skewed heartbeat alerts; the helper
    change is judged again too."""
    # the package re-exports the heartbeat() function under the module's name
    hb_module = importlib.import_module("bitscan_manager.services.agents.heartbeat")

    a = env.agent()
    mark = env.last_audit()
    counted = alerts_counted("clock_skew")
    real = hb_module.read_settings
    calls = {"n": 0}

    def failing(reader: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected after the alerts")
        return real(reader)

    monkeypatch.setattr(hb_module, "read_settings", failing)
    skewed = env.body(clock=iso(T0 + timedelta(minutes=6)), runner_helpers=["capread"])
    r = env.hb(a, skewed)
    assert r.status_code == 500, r.text
    assert calls["n"] == 1
    assert env.audit_after(mark) == []
    assert alerts_counted("clock_skew") == counted
    assert env.row(a.agent_id)["last_heartbeat_at"] is None
    assert env.row(a.agent_id)["runner_helpers"] == []
    env.clock.at = T0 + timedelta(minutes=1)
    ok(
        env.hb(
            a,
            env.body(
                clock=iso(env.clock.at + timedelta(minutes=6)),
                runner_helpers=["capread"],
            ),
        )
    )
    kinds = sorted(e[3].get("alert_kind") for e in env.audit_after(mark))
    assert kinds == ["clock_skew", "runner_helper_changed"]
    assert alerts_counted("clock_skew") == counted + 1


# ------------------------------------------------------------ CHK-M3-239


def test_heartbeat_creates_and_changes_no_job(env: Env) -> None:
    """REQ-070 (5), REQ-088: no scan_job row is created or changed, also for a
    first heartbeat of an enrolled agent with no job (the #36 job is queued on
    approval, not on a heartbeat)."""
    busy = env.agent()
    queued = env.agent()
    fresh = env.agent(status="enrolled")
    with env.conn() as c:
        jobs = JobRepo(c)
        jobs.queue_inventory(
            T0 - timedelta(minutes=10), T0 + timedelta(hours=24), busy.agent_id
        )
        assert len(jobs.pull(busy.agent_id, T0 - timedelta(minutes=9))) == 1
        jobs.queue_inventory(
            T0 - timedelta(minutes=10), T0 + timedelta(hours=24), queued.agent_id
        )
    before = env.jobs()
    for a in (busy, queued, fresh, busy, queued, fresh):
        env.clock.at += timedelta(minutes=5)
        ok(env.hb(a, env.body(current_job_id=str(uuid4()), last_pull_at=iso(T0))))
    assert env.jobs() == before
    assert [j for j in before if j[1] == fresh.agent_id] == []


# ------------------------------------------------------------ CHK-M3-240


def test_last_error_is_logged_with_the_agent_id_and_never_audited(
    env: Env, logs: io.StringIO
) -> None:
    """REQ-070 (6), #25 (a), REQ-087 (1): last_error goes to one INFO record
    carrying the agent_id, never to the audit log or the response; every
    record of the request carries the agent_id; no token is logged; the
    dropped fields are not stored."""
    canary = f"CANARY-{secrets.token_hex(8)}"
    job = str(uuid4())
    a = env.agent()
    mark = env.last_audit()
    r = env.hb(
        a,
        env.body(
            last_error=f"runner unavailable {canary}",
            current_job_id=job,
            runner_helpers=["capread"],  # an audited event in the same request
            clock=iso(T0 + timedelta(minutes=9)),  # and an alert
        ),
    )
    ok(r)
    assert canary not in r.text
    lines = [json.loads(ln) for ln in logs.getvalue().splitlines() if ln.strip()]
    with_canary = [ln for ln in lines if canary in json.dumps(ln)]
    assert len(with_canary) == 1, with_canary
    rec = with_canary[0]
    assert rec["level"] == "INFO"
    assert rec["agent_id"] == str(a.agent_id)
    mine = [ln for ln in lines if ln.get("request_id") == rec["request_id"]]
    assert len(mine) >= 2 and all(ln["agent_id"] == str(a.agent_id) for ln in mine)
    text = logs.getvalue()
    assert (
        a.token not in text
        and a.token[4:] not in text
        and token_hash(a.token) not in text
    )
    entries = env.audit_after(mark)
    assert len(entries) == 2  # the helper change and the skew alert
    with env.conn() as c:
        rows = c.execute(
            "SELECT count(*) FROM audit_log WHERE detail::text LIKE %s"
            " OR actor LIKE %s OR action LIKE %s OR target LIKE %s",
            (f"%{canary}%",) * 4,
        ).fetchone()
    assert rows == (0,)
    row_text = json.dumps(env.row(a.agent_id), default=str)
    assert canary not in row_text and job not in row_text
    assert job not in json.dumps([e[3] for e in entries])


def test_no_last_error_writes_no_last_error_record(env: Env, logs: io.StringIO) -> None:
    a = env.agent()
    ok(env.hb(a))
    lines = [json.loads(ln) for ln in logs.getvalue().splitlines() if ln.strip()]
    assert not [ln for ln in lines if "last_error" in ln]


# ------------------------------------------------------------ CHK-M3-241


def test_three_heartbeats_observe_the_latency_histogram_three_times(env: Env) -> None:
    """REQ-086 (2): the count rises by 3; the histogram has no unbounded label."""
    a = env.agent()
    before = latency_count()
    for _ in range(3):
        env.clock.at += timedelta(minutes=5)
        ok(env.hb(a))
    assert latency_count() == before + 3
    for metric in REGISTRY.collect():
        if metric.name == "bitscan_heartbeat_latency_seconds":
            for sample in metric.samples:
                assert set(sample.labels) <= {"le"}, sample
            break
    else:
        pytest.fail("bitscan_heartbeat_latency_seconds is not registered")


# ------------------------------------------------------------ CHK-M3-242


REQUEST_FIXTURES = list(loader.select("heartbeat", "request"))


def test_every_heartbeat_request_fixture_is_present() -> None:
    assert len([f for f in REQUEST_FIXTURES if f.valid]) >= 4
    assert len([f for f in REQUEST_FIXTURES if not f.valid]) >= 40


@pytest.mark.parametrize("fx", REQUEST_FIXTURES, ids=lambda f: f.id)
def test_request_fixtures_through_the_route(env: Env, fx: loader.Fixture) -> None:
    """REQ-060, REQ-061: each valid fixture is 200 and stored as sent; each
    invalid one is 400 invalid_request and records no heartbeat or entry."""
    a = env.agent(last_heartbeat_at=T0 - timedelta(minutes=5))
    before = env.beat_cols(a.agent_id)
    mark = env.last_audit()
    r = env.hb(a, content=fx.body_bytes())
    if fx.valid:
        ok(r)
        sent = fx.body()
        row = env.row(a.agent_id)
        assert row["agent_version"] == sent["agent_version"]
        assert row["runner_helpers"] == sent["runner_helpers"]
        assert row["last_heartbeat_at"] == T0
    else:
        problem(r, 400, "invalid_request")
        assert env.beat_cols(a.agent_id) == before
        assert env.audit_after(mark) == []


@pytest.mark.parametrize(
    ("content", "ctype"),
    [
        (b"[1, 2]", "application/json"),
        (b"null", "application/json"),
        (b"{}", "application/json"),
        (b'{"agent_version": ', "application/json"),
        (b"not json", "application/json"),
        (b"", "application/json"),
        (b"\xff\xfe{}", "application/json"),
    ],
    ids=["array", "null", "empty-object", "truncated", "not-json", "empty", "bad-utf8"],
)
def test_bad_bodies_with_a_valid_token_are_400(
    env: Env, content: bytes, ctype: str
) -> None:
    """The heartbeat's own documented 400 (the M2 documented-400 walk sees only
    the 401 without a token): never 422, nothing recorded."""
    a = env.agent(last_heartbeat_at=T0 - timedelta(minutes=5))
    before = env.beat_cols(a.agent_id)
    mark = env.last_audit()
    r = env.hb(a, content=content, headers={"Content-Type": ctype})
    problem(r, 400, "invalid_request")
    assert env.beat_cols(a.agent_id) == before
    assert env.audit_after(mark) == []


def test_bad_body_without_a_token_is_401(env: Env) -> None:
    """A well-formed JSON body that fails validation, sent without a token,
    gets 401: the token check runs before the body is validated."""
    r = env.hb(None, content=b"[1, 2]", path_id=str(uuid4()))
    problem(r, 401, "unauthorized")


def test_body_cap_on_the_real_route(env: Env) -> None:
    """REQ-066 (1), TS §6.3 L1138: the heartbeat keeps the 1 MiB cap; a valid
    body of exactly 1,048,576 bytes is accepted, one more byte is 413."""
    a = env.agent()
    raw = json.dumps(env.body()).encode()
    exact = raw + b" " * (MIB - len(raw))
    assert len(exact) == MIB
    ok(env.hb(a, content=exact))
    env.clock.at += timedelta(minutes=5)
    before = env.beat_cols(a.agent_id)
    problem(env.hb(a, content=exact + b" "), 413, "too_large")
    assert env.beat_cols(a.agent_id) == before


# ------------------------------------------------- matrix (CHK-M3-160 to -163)


def leaky_body(env: Env) -> dict[str, Any]:
    """A body that would write a helper entry and a skew alert if accepted."""
    return env.body(
        agent_version="9.9.9",
        runner_helpers=["capread"],
        clock=iso(T0 + timedelta(hours=2)),
    )


def test_wrong_tokens_are_one_401_on_heartbeat(env: Env) -> None:
    """REQ-062 (2) on the real route: one body for every case; no change."""
    a = env.agent()
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    with env.conn() as c:
        c.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
            " created_by) VALUES (%s, 10, %s, 1)",
            (token_hash(bse), T0 + timedelta(days=1)),
        )
    cases = [
        {},
        {"Authorization": f"Basic {a.token}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {env.user_token('session')}"},
        {"Authorization": f"Bearer {env.user_token('api')}"},
        {"Authorization": f"Bearer {bse}"},
        {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
    ]
    before = env.row(a.agent_id)
    mark = env.last_audit()
    bodies = set()
    for h in cases:
        r = env.hb(a, leaky_body(env), token="", headers=h)
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1
    assert env.row(a.agent_id) == before and env.ips(a.agent_id) == []
    assert env.audit_after(mark) == []


def outcome_cases(env: Env) -> list[tuple[str, Agent, dict[str, Any], int, str]]:
    revoked = env.agent(token_revoked_at=T0 - timedelta(minutes=1))
    expired = env.agent(token_expires_at=T0)
    pending = env.agent(status="awaiting_approval")
    held = env.agent()
    held_new = env.request(held, "reenrol", None)
    rejected = env.agent(status="decommissioned", token_revoked_at=T0)
    env.request(rejected, "new", "rejected")
    re_rejected = env.agent()
    rr_new = env.request(re_rejected, "reenrol", "rejected")
    decom = env.agent(status="decommissioned", token_revoked_at=T0 - timedelta(days=1))
    other = env.agent()
    return [
        ("revoked", revoked, {}, 401, "token_revoked"),
        ("expired", expired, {}, 401, "token_expired"),
        ("pending-new", pending, {}, 403, "pending_approval"),
        ("pending-reenrol", held, {"token": held_new}, 403, "pending_approval"),
        ("rejected-new", rejected, {}, 401, "enrollment_rejected"),
        (
            "rejected-reenrol",
            re_rejected,
            {"token": rr_new},
            401,
            "enrollment_rejected",
        ),
        ("decommissioned", decom, {}, 401, "token_revoked"),
        ("foreign-id", other, {"path_id": str(revoked.agent_id)}, 403, "forbidden"),
        ("mismatch", env.agent(), {"machine": "f" * 32}, 401, "machine_id_mismatch"),
        (
            "missing-machine-id",
            env.agent(),
            {"machine": None},
            401,
            "machine_id_mismatch",
        ),
    ]


def test_token_outcomes_on_heartbeat_record_nothing(env: Env) -> None:
    """REQ-064 (1), (2), (6), CHK-M3-161, -162 on the real route: each state
    gives its #59 answer and the heartbeat records nothing (no heartbeat
    columns, no helper entry, no skew alert); only a mismatch revokes and
    writes its own machine_id_mismatch alert."""
    for name, a, kw, status, type_ in outcome_cases(env):
        before = env.beat_cols(a.agent_id)
        mark = env.last_audit()
        problem(env.hb(a, leaky_body(env), **kw), status, type_)
        assert env.beat_cols(a.agent_id) == before, name
        kinds = [e[3].get("alert_kind") for e in env.audit_after(mark)]
        assert "runner_helper_changed" not in kinds and "clock_skew" not in kinds, name
        if type_ == "machine_id_mismatch":
            assert kinds == ["machine_id_mismatch"], name
            assert env.row(a.agent_id)["token_revoked_at"] == T0
        else:
            assert kinds == [], (name, kinds)
    # the held re-enrolment's and the rejected re-enrolment's old tokens work
    for name, a, _kw, _, _ in outcome_cases(env):
        if name in ("pending-reenrol", "rejected-reenrol"):
            ok(env.hb(a))


def test_thirty_heartbeats_a_minute_then_429(env: Env) -> None:
    """REQ-065 (1), CHK-M3-163 on the real route: the 31st request of one
    agent in a minute is 429 and records nothing; another agent passes."""
    a, b = env.agent(), env.agent()
    whole = T0.replace(microsecond=0)
    env.clock.at = whole + timedelta(seconds=5)
    for _ in range(30):
        ok(env.hb(a))
    before = env.beat_cols(a.agent_id)
    mark = env.last_audit()
    r = env.hb(a, leaky_body(env))
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"  # whole seconds to the window end
    assert env.beat_cols(a.agent_id) == before and env.audit_after(mark) == []
    ok(env.hb(b))
    env.clock.at = whole + timedelta(minutes=1)
    ok(env.hb(a))


def test_agent_row_gone_after_the_check_is_401_token_revoked(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row cannot be deleted by bitscan_app; simulate it vanishing between
    the token check and the service: 401 token_revoked, nothing written."""
    from bitscan_manager.repositories.agents import AgentRepo

    a = env.agent()
    mark = env.last_audit()
    before = latency_count()
    monkeypatch.setattr(AgentRepo, "get", lambda self, agent_id, *, lock=False: None)
    problem(env.hb(a, leaky_body(env)), 401, "token_revoked")
    assert env.audit_after(mark) == []
    assert latency_count() == before


# ------------------------------------------------------------ CHK-M3-169


def test_heartbeat_is_in_the_agent_group_with_the_bsa_dependency() -> None:
    """REQ-062 (1): POST /api/v1/agent/{id}/heartbeat exists once, carries the
    bsa_ dependency and no user dependency."""
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


def test_openapi_documents_the_heartbeat_operation() -> None:
    """REQ-060 (1), (2), (5): request and response schemas; the response has
    exactly the three properties, all required, no extra keys; refusals are
    problem+json with the #59 statuses; no 422."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    op = doc["paths"][TEMPLATE]["post"]
    assert set(doc["paths"][TEMPLATE]) == {"post"}
    req = op["requestBody"]["content"]["application/json"]["schema"]
    assert req == {"$ref": "#/components/schemas/HeartbeatRequest"}
    resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert resp == {"$ref": "#/components/schemas/HeartbeatResponse"}
    schema = doc["components"]["schemas"]["HeartbeatResponse"]
    assert sorted(schema["properties"]) == sorted(KEYS)
    assert sorted(schema["required"]) == sorted(OLD_KEYS)  # max_parallel_jobs optional
    assert schema["properties"]["max_parallel_jobs"] == {
        "maximum": 4.0,
        "minimum": 1.0,
        "title": "Max Parallel Jobs",
        "type": "integer",
    }  # never null
    assert schema["additionalProperties"] is False
    assert "422" not in op["responses"]
    for status in ("400", "401", "403", "429", "503"):
        content = op["responses"][status]["content"]
        assert list(content) == ["application/problem+json"], status
    hb_req = doc["components"]["schemas"]["HeartbeatRequest"]
    assert hb_req["additionalProperties"] is False
    assert sorted(hb_req["properties"]) == sorted(
        [
            "agent_version",
            "uptime_s",
            "last_pull_at",
            "current_job_id",
            "spool_bytes",
            "last_error",
            "runner_helpers",
            "clock",
        ]
    )
    bsa = re2.compile(r"(?i)command|script|execute|plugins")
    assert not [k for k in hb_req["properties"] if bsa.search(k)]
