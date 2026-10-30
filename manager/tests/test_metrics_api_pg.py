"""TASK-079: GET /api/v1/metrics on PostgreSQL (TP-M3-33).

Checks CHK-M3-290 to CHK-M3-292 of tests/m3/test-plan.md. Expected values come
from the spec and the answers, not from the code: TS §8.4 L1288-L1289
(Prometheus metrics: agents by status, heartbeat latency, jobs queued and
expired, bitscan_alerts_total{kind}), TS §2.3 L118 (every call carries a bearer
token), #70 (user ruling 2026-10-23: GET /api/v1/metrics, the normal bearer
check, minimum role viewer; HealthPath unchanged), REQ-086 (1)-(3).
"""

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from psycopg.types.json import Jsonb
from pydantic import SecretStr

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
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.scheduler.sweep import Stores, pg_stores, run_sweep

from .conftest import PgServer
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ROUTE = "/api/v1/metrics"
STATUSES = {
    "awaiting_approval",
    "enrolled",
    "online",
    "stale",
    "offline",
    "decommissioned",
}
NEEDED = {
    "bitscan_alerts_total",
    "bitscan_agents",
    "bitscan_heartbeat_latency_seconds",
    "bitscan_jobs_queued",
    "bitscan_jobs_expired_total",
}


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Env:
    server: PgServer
    db: AppDatabase
    clock: Clock
    client: TestClient

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def user(self, role: str = "viewer", kind: str = "api") -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', %s, 'enc', 1, %s)"
                " RETURNING user_id",
                (f"mt{secrets.token_hex(5)}", role, T0),
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
                    T0 + timedelta(days=30),
                    T0,
                ),
            )
        return tok

    def agent(self, status: str, hostname: str | None = None) -> tuple[str, str, str]:
        tok = new_agent_token(AgentTokenKind.AGENT)
        machine = secrets.token_hex(16)
        name = hostname or f"mt-{secrets.token_hex(4)}"
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
                " token_issued_at, token_expires_at, status, enrolled_at) VALUES"
                " (%s, %s, '1.0.0', %s, %s, %s, %s, %s) RETURNING agent_id",
                (
                    machine,
                    name,
                    token_hash(tok),
                    T0 - timedelta(days=1),
                    T0 + timedelta(days=364),
                    status,
                    T0 - timedelta(days=1),
                ),
            ).fetchone()
        assert row is not None
        return str(row[0]), tok, machine

    def queued_job(self, agent_id: str, pickup_by: datetime) -> None:
        jid = uuid4()
        with self.conn() as c:
            c.execute(
                "INSERT INTO scan_job (job_id, kind, agent_id, state, payload,"
                " created_at, pickup_by) VALUES (%s, 'inventory', %s, 'queued', %s,"
                " %s, %s)",
                (
                    jid,
                    agent_id,
                    Jsonb(
                        {
                            "job_id": str(jid),
                            "agent_id": agent_id,
                            "kind": "inventory",
                            "pickup_by": pickup_by.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
                    ),
                    pickup_by - timedelta(hours=24),
                    pickup_by,
                ),
            )

    def scrape(self, tok: str | None) -> Any:
        h = {} if tok is None else {"Authorization": f"Bearer {tok}"}
        return self.client.get(ROUTE, headers=h)

    def samples(self, tok: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
        r = self.scrape(tok)
        assert r.status_code == 200, r.text
        out = {}
        for fam in text_string_to_metric_families(r.text):
            for s in fam.samples:
                out[(s.name, tuple(sorted(s.labels.items())))] = s.value
        return out


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=4, connect_timeout_s=5
    )
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    with TestClient(create_app(rt), client=("10.79.0.1", 1)) as client:
        yield Env(migrated_db, db, clock, client)
    db.close()


def db_counts(env: Env) -> tuple[dict[str, int], int]:
    with env.conn() as c:
        by = dict(
            c.execute("SELECT status::text, count(*) FROM agent GROUP BY 1").fetchall()
        )
        q = c.execute("SELECT count(*) FROM scan_job WHERE state = 'queued'").fetchone()
    assert q is not None
    return {k: int(v) for k, v in by.items()}, int(q[0])


# ------------------------------------------------------------ CHK-M3-290


def test_viewer_api_token_gets_prometheus_text_with_every_metric(env: Env) -> None:
    """REQ-086 (1), #70: a viewer bsk_ gets 200 Prometheus text (0.0.4) that
    holds every REQ-086 metric, with the security headers."""
    r = env.scrape(env.user("viewer"))
    assert r.status_code == 200, r.text
    ctype = r.headers["content-type"]
    assert ctype.startswith("text/plain") and "version=0.0.4" in ctype
    assert r.headers.get("x-content-type-options") == "nosniff"
    names = {fam.name for fam in text_string_to_metric_families(r.text)}
    # the parser drops _total from counter family names
    assert {
        "bitscan_alerts",
        "bitscan_agents",
        "bitscan_heartbeat_latency_seconds",
        "bitscan_jobs_queued",
        "bitscan_jobs_expired",
    } <= names, names
    for n in NEEDED:
        assert n in r.text


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("none", 401),
        ("bsa", 401),
        ("bse", 401),
        ("viewer-session", 200),
        ("operator-api", 200),
        ("admin-api", 200),
    ],
)
def test_authentication(env: Env, who: str, status: int) -> None:
    """#70: the normal bearer check; any role from viewer up; agent and
    enrolment tokens and no token are 401."""
    if who == "none":
        tok = None
    elif who == "bsa":
        tok = env.agent("online")[1]
    elif who == "bse":
        tok = new_agent_token(AgentTokenKind.ENROLMENT)
    else:
        role, kind = who.split("-")
        tok = env.user(role, kind)
    r = env.scrape(tok)
    assert r.status_code == status, r.text
    if status == 401:
        assert r.json()["type"] == "unauthorized"
        assert "bitscan_" not in r.text


# ------------------------------------------------------------ CHK-M3-291


def test_gauges_equal_database_counts_at_scrape_time(env: Env) -> None:
    """REQ-086 (2): bitscan_agents{status} equals a count taken from the
    database for every status (0 when none) and bitscan_jobs_queued equals
    the queued jobs; after adding agents and a job the next scrape moves."""
    viewer = env.user("viewer")
    for _ in range(2):
        by, queued = db_counts(env)
        s = env.samples(viewer)
        for st in STATUSES:
            assert s[("bitscan_agents", (("status", st),))] == by.get(st, 0), st
        assert s[("bitscan_jobs_queued", ())] == queued
        a, _, _ = env.agent("stale")
        env.agent("awaiting_approval")
        env.queued_job(a, T0 + timedelta(hours=24))


def test_three_heartbeats_count_three_latency_observations(env: Env) -> None:
    """REQ-086 (2): after 3 heartbeats the latency histogram count rose by 3."""
    viewer = env.user("viewer")
    before = env.samples(viewer)[("bitscan_heartbeat_latency_seconds_count", ())]
    agent_id, tok, machine = env.agent("online")
    for i in range(3):
        env.clock.at = T0 + timedelta(minutes=5 * i)
        r = env.client.post(
            f"/api/v1/agent/{agent_id}/heartbeat",
            json={
                "agent_version": "1.0.0",
                "uptime_s": 1,
                "last_pull_at": None,
                "current_job_id": None,
                "spool_bytes": 0,
                "last_error": None,
                "runner_helpers": [],
                "clock": env.clock.at.isoformat().replace("+00:00", "Z"),
            },
            headers={"Authorization": f"Bearer {tok}", "X-Bitscan-Machine-Id": machine},
        )
        assert r.status_code == 200, r.text
    after = env.samples(viewer)[("bitscan_heartbeat_latency_seconds_count", ())]
    assert after - before == 3


def test_a_sweep_expiring_two_jobs_raises_the_counter_by_two(env: Env) -> None:
    """REQ-086 (2): after a sweep expires 2 jobs, bitscan_jobs_expired_total
    has risen by 2. The sweep runs at a time only these two jobs are past
    (pickup in the year 2000); its other steps are stubbed so nothing else in
    the shared database moves."""
    viewer = env.user("viewer")
    before = env.samples(viewer)[("bitscan_jobs_expired_total", ())]
    a, _, _ = env.agent("online")
    at = datetime(2000, 1, 2, tzinfo=UTC)
    env.queued_job(a, at - timedelta(hours=1))
    env.queued_job(a, at - timedelta(minutes=1))
    env.queued_job(a, at + timedelta(hours=1))  # not yet past

    class NoAgents:
        def apply_heartbeat_ages(self, *a: Any) -> int:
            return 0

        def decommission_offline(self, *a: Any) -> list[Any]:
            return []

    class OnlyExpire:
        def __init__(self, jobs: JobRepo) -> None:
            self.jobs = jobs

        def expire_past_pickup(self, now: datetime) -> int:
            return self.jobs.expire_past_pickup(now)

        def fail_dispatched_inventory(self, *a: Any) -> int:
            return 0

    def stores(tx: Any) -> Stores:
        real = pg_stores(tx)
        return Stores(
            real.tx, NoAgents(), OnlyExpire(JobRepo(tx.conn)), real.settings, real.audit
        )

    out = run_sweep(env.db, at, stores)
    assert out.expired == 2 and not out.failed_steps
    after = env.samples(viewer)[("bitscan_jobs_expired_total", ())]
    assert after - before == 2


# ------------------------------------------------------------ CHK-M3-292


def test_no_label_holds_an_unbounded_value(env: Env) -> None:
    """REQ-086 (3): the bitscan_ samples use only the kind, status and le
    labels, with values from fixed sets; no hostname, agent id or token of a
    planted agent appears anywhere in the scrape."""
    host = f"secret-host-{secrets.token_hex(4)}"
    agent_id, tok, machine = env.agent("online", hostname=host)
    r = env.scrape(env.user("viewer"))
    for planted in (host, agent_id, tok, tok[4:], token_hash(tok), machine):
        assert planted not in r.text
    kinds: set[str] = set()
    for fam in text_string_to_metric_families(r.text):
        if not fam.name.startswith("bitscan_"):
            continue
        for s in fam.samples:
            # M9 (REQ-226 (3), #129 (c)): "result" on the plugin results
            # counter, PASS/FAIL/ERROR only. Old → new: CHK-M3's label set →
            # CHK-M9-234 (plus "result"); every other assertion is unchanged.
            assert set(s.labels) <= {"kind", "status", "le", "mode", "result"}, (
                s.name,
                s.labels,
            )
            if "result" in s.labels:
                assert s.name.startswith("bitscan_plugin_results_")  # _total, _created
                assert s.labels["result"] in {"PASS", "FAIL", "ERROR"}
            if "mode" in s.labels:  # M7 (#101): bit_import.mode only
                assert s.labels["mode"] in {"auto", "manual", "rebuild"}
            if "status" in s.labels:
                assert s.labels["status"] in STATUSES
            if "kind" in s.labels:
                kinds.add(s.labels["kind"])
                assert s.labels["kind"].replace("_", "").isalnum()
    assert {"result_409_flood", "clock_skew", "token_reuse"} <= kinds


def test_openapi_documents_the_metrics_route() -> None:
    import json

    from .test_contract_agent import OPENAPI

    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    op = doc["paths"][ROUTE]["get"]
    assert set(doc["paths"][ROUTE]) == {"get"}
    content = op["responses"]["200"]["content"]
    assert [k for k in content if k.startswith("text/plain")], content
    for status in ("401", "403", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
    assert all(
        p.startswith("/api/v1/") or p in ("/healthz", "/readyz") for p in doc["paths"]
    )
