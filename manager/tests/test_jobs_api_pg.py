"""TASK-073: GET /api/v1/agent/{id}/jobs and POST .../jobs/{job_id}/results on
PostgreSQL (TP-M3-27).

Checks CHK-M3-245 to CHK-M3-253 of tests/m3/test-plan.md, the API halves of the
mutation rows CHK-M3-346 to -351 and -359, and the re-run of the agent-route
matrix (CHK-M3-160 to -163) and route walk (CHK-M3-169) on the two real routes.
Expected values come from the spec and the answers, not from the code: TS §6.1
L1064 (pull up to 10 queued jobs, marks them dispatched), L1065, L1071 (a
result post is accepted only for a job addressed to that agent ...; anything
else returns 409 and is audit-logged), L1072 (the manager re-checks every cap),
TS §6.3 L1138 (result batch 1.5 MB after decompression), TS §6.5 L1165-L1184
(Job and Results bodies), TS §3.3 L210-L214 (pull-only; at most 10 per pull),
TS §4.4 (pickup_by in the future; queued -> dispatched), TS §8.4 L1287
(job_id in the logs), L1291 (floods of 409 result posts), #54 (c) (more than
20 409s from one agent in 10 minutes), #65 (f) (once per agent per hour), #71
(agent.result_refused, actor agent:<id>; alert.<kind>; never stdout or stderr;
pulls are not audited), REQ-072 (1)-(6), REQ-073 (1)-(5), REQ-066 (1)-(4),
REQ-087 (1), REQ-088. Lead rulings 2026-10-23: a threshold window is marked
fired only after its alert commits; pickup_by may come back as
...T12:00:00.000000Z (same instant).
"""

import asyncio
import gzip
import io
import json
import logging
import secrets
import threading
import time
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.api.agent import AgentWindows, schemas
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
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import REGISTRY
from tests.contract import loader

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_contract_agent import OPENAPI, validator
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
PULL = "/api/v1/agent/{id}/jobs"
RESULTS = "/api/v1/agent/{id}/jobs/{job_id}/results"
CAP = 1_572_864  # 1.5 MiB (TS §6.3 L1138; #57 (b))
INVENTORY_KEYS = ["job_id", "agent_id", "kind", "pickup_by"]
FORBIDDEN = ("eval_spec", "operator", "expected", "plugins", "redaction_patterns")
STATES = (
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "expired",
    "cancelled",
)


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
    app: FastAPI
    db: AppDatabase
    _ip: int = 0
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def fresh_ip(self) -> str:
        self._ip += 1
        return f"10.73.{self._ip // 256}.{self._ip % 256}"

    def client(self, ip: str | None = None) -> TestClient:
        ip = ip or "10.73.250.1"
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
            "hostname": f"jb-{secrets.token_hex(3)}",
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

    def job(
        self,
        a: Agent,
        *,
        created: datetime,
        pickup_by: datetime | None = None,
        state: str = "queued",
    ) -> UUID:
        """An inventory row as the scheduler writes it (payload of TS §6.5
        L1182, pickup_by = created + 24 h unless given)."""
        jid = uuid4()
        pb = pickup_by if pickup_by is not None else created + timedelta(hours=24)
        payload = {
            "job_id": str(jid),
            "agent_id": str(a.agent_id),
            "kind": "inventory",
            "pickup_by": pb.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        dispatched = None if state == "queued" else created + timedelta(minutes=1)
        finished = (
            created + timedelta(minutes=2)
            if state in ("completed", "partial", "failed", "expired", "cancelled")
            else None
        )
        with self.conn() as c:
            c.execute(
                "INSERT INTO scan_job (job_id, kind, agent_id, state, payload,"
                " created_at, pickup_by, dispatched_at, finished_at)"
                " VALUES (%s, 'inventory', %s, CAST(%s AS scan_state), %s, %s, %s,"
                " %s, %s)",
                (
                    jid,
                    a.agent_id,
                    state,
                    Jsonb(payload),
                    created,
                    pb,
                    dispatched,
                    finished,
                ),
            )
        return jid

    def compliance(self, a: Agent, *, created: datetime, state: str = "queued") -> UUID:
        """A compliance job with an eval_spec, planted as owner (no scan or
        policy can be made by the app in M3)."""
        with self.server.connect("bitscan_migrate") as oc:
            oc.execute("SET ROLE bitscan_owner")
            fam = oc.execute(
                "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
                (f"F{secrets.token_hex(4)}",),
            ).fetchone()
            assert fam is not None
            pol = oc.execute(
                "INSERT INTO policy (policy_name, policy_status, file_status,"
                " family_id, source_file, source_sha256) VALUES (%s, 'enabled',"
                " 'enabled', %s, %s, %s) RETURNING policy_id",
                (secrets.token_hex(4), fam[0], secrets.token_hex(4), "a" * 64),
            ).fetchone()
            assert pol is not None
            scan = oc.execute(
                "INSERT INTO scan (policy_id, policy_version, trigger, target)"
                " VALUES (%s, 1, 'manual', %s) RETURNING scan_id",
                (pol[0], Jsonb({"all": True})),
            ).fetchone()
            assert scan is not None
            jid = uuid4()
            payload = {
                "job_id": str(jid),
                "agent_id": str(a.agent_id),
                "kind": "compliance",
                "pickup_by": iso(created + timedelta(hours=24)),
                "plugins": [
                    {"plugin_uuid": str(uuid4()), "execute": "true", "timeout_s": 5}
                ],
                "redaction_patterns": [],
            }
            oc.execute(
                "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, state, payload,"
                " eval_spec, created_at, pickup_by, dispatched_at)"
                " VALUES (%s, 'compliance', %s, %s, CAST(%s AS scan_state), %s, %s,"
                " %s, %s, %s)",
                (
                    jid,
                    scan[0],
                    a.agent_id,
                    state,
                    Jsonb(payload),
                    Jsonb([{"operator": "equals", "expected": "x"}]),
                    created,
                    created + timedelta(hours=24),
                    None if state == "queued" else created + timedelta(minutes=1),
                ),
            )
            oc.commit()
        return jid

    def headers(self, a: Agent, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {a.token}",
            "X-Bitscan-Machine-Id": a.machine_id,
        } | (extra or {})

    def pull(
        self, a: Agent, *, path_id: str | None = None, ip: str | None = None
    ) -> Any:
        path = PULL.replace("{id}", path_id or str(a.agent_id))
        return self.client(ip).get(path, headers=self.headers(a))

    def post(
        self,
        a: Agent,
        job_id: UUID | str,
        body: Any = None,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        path_id: str | None = None,
        ip: str | None = None,
        auth: bool = True,
    ) -> Any:
        path = RESULTS.replace("{id}", path_id or str(a.agent_id)).replace(
            "{job_id}", str(job_id)
        )
        h = self.headers(a) if auth else {}
        h |= {"Content-Type": "application/json"} | (headers or {})
        if content is None:
            content = json.dumps(body if body is not None else batch()).encode()
        return self.client(ip).post(path, content=content, headers=h)

    def job_row(self, jid: UUID) -> tuple[Any, ...]:
        with self.conn() as c:
            row = c.execute(
                "SELECT state::text, dispatched_at, started_at, deadline_at,"
                " finished_at, payload FROM scan_job WHERE job_id = %s",
                (jid,),
            ).fetchone()
        assert row is not None
        return tuple(row)

    def jobs_of(self, a: Agent) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT job_id, state::text, dispatched_at, finished_at FROM scan_job"
                " WHERE agent_id = %s ORDER BY created_at, job_id",
                (a.agent_id,),
            ).fetchall()

    def all_jobs(self) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute("SELECT * FROM scan_job ORDER BY job_id").fetchall()

    def results_count(self) -> int:
        with self.conn() as c:
            row = c.execute("SELECT count(*) FROM scan_result").fetchone()
        assert row is not None
        return int(row[0])

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

    def windows(self) -> AgentWindows:
        w = self.app.state.agent_windows
        assert isinstance(w, AgentWindows)
        return w


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=12, connect_timeout_s=5
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
    yield e
    for c in e.clients.values():
        c.close()
    db.close()


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


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == type_, body
    assert body["status"] == status
    return body


def alerts_counted(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


def item(**over: Any) -> dict[str, Any]:
    return {
        "plugin_uuid": str(uuid4()),
        "exit_code": 0,
        "stdout": "install ok installed",
        "stderr": "",
        "started_at": iso(T0 - timedelta(seconds=3)),
        "finished_at": iso(T0 - timedelta(seconds=2)),
        "timed_out": False,
        "truncated": False,
        "error": None,
    } | over


def batch(*items: dict[str, Any], final: bool = True) -> dict[str, Any]:
    return {"results": list(items) if items else [item()], "final": final}


def pull_schema_errors(body: Any) -> list[Any]:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    node = doc["paths"][PULL]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    return list(validator({**doc, **node}).iter_errors(body))


def pulled(r: Any) -> list[dict[str, Any]]:
    """A 200 pull answer that matches the contract both ways (REQ-072 (6))."""
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert list(body) == ["jobs"], body
    assert not pull_schema_errors(body)
    schemas.JobsResponse.model_validate_json(r.content)
    for word in FORBIDDEN:
        assert f'"{word}"' not in r.text, word
    jobs: list[dict[str, Any]] = body["jobs"]
    return jobs


def refused_entries(env: Env, mark: int) -> list[tuple[Any, ...]]:
    return [e for e in env.audit_after(mark) if e[1] == "agent.result_refused"]


def flood_entries(env: Env, mark: int) -> list[tuple[Any, ...]]:
    return [
        e for e in env.audit_after(mark) if e[3].get("alert_kind") == "result_409_flood"
    ]


# ------------------------------------------------------------ CHK-M3-245


def test_twelve_queued_come_back_ten_oldest_first_then_two_then_none(env: Env) -> None:
    """REQ-072 (1), (5), TS §6.1 L1064, §3.3 L214, CHK-M3-348: at most 10 per
    pull, oldest first, each dispatched exactly once with dispatched_at = now;
    the rest wait; then an empty list. Rows are inserted out of order so the
    order cannot come from insertion."""
    a = env.agent()
    created = [T0 - timedelta(minutes=60 - i) for i in range(12)]
    order = [5, 0, 11, 3, 8, 1, 10, 6, 2, 9, 4, 7]
    ids = {i: env.job(a, created=created[i]) for i in order}
    oldest_first = [ids[i] for i in range(12)]
    jobs = pulled(env.pull(a))
    assert [UUID(j["job_id"]) for j in jobs] == oldest_first[:10]
    for j, i in zip(jobs, range(10), strict=True):
        assert list(j) == INVENTORY_KEYS
        assert j["agent_id"] == str(a.agent_id) and j["kind"] == "inventory"
        assert parse(j["pickup_by"]) == created[i] + timedelta(hours=24)
        assert j["pickup_by"].endswith("Z")
    rows = {r[0]: r for r in env.jobs_of(a)}
    for jid in oldest_first[:10]:
        assert rows[jid][1:3] == ("dispatched", T0)
    for jid in oldest_first[10:]:
        assert rows[jid][1:3] == ("queued", None)
    env.clock.at = T0 + timedelta(minutes=5)
    second = pulled(env.pull(a))
    assert [UUID(j["job_id"]) for j in second] == oldest_first[10:]
    rows = {r[0]: r for r in env.jobs_of(a)}
    assert rows[oldest_first[10]][1:3] == ("dispatched", T0 + timedelta(minutes=5))
    assert rows[oldest_first[0]][1:3] == ("dispatched", T0)  # not touched again
    env.clock.at = T0 + timedelta(minutes=10)
    before = env.all_jobs()
    r = env.pull(a)
    assert pulled(r) == [] and r.json() == {"jobs": []}
    assert env.all_jobs() == before


def test_payload_is_the_stored_payload(env: Env) -> None:
    """TS §6.5 L1182: the job body is the stored payload (exactly the four
    inventory keys); job_id is the row's id."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=1))
    stored = env.job_row(jid)[5]
    (job,) = pulled(env.pull(a))
    assert job["job_id"] == str(jid) == stored["job_id"]
    assert job["agent_id"] == stored["agent_id"] and job["kind"] == stored["kind"]
    # ruling 2026-10-23: re-serialised as ...000000Z, the same instant
    assert parse(job["pickup_by"]) == parse(stored["pickup_by"])


def test_empty_queue_answers_jobs_empty_and_changes_nothing(env: Env) -> None:
    """REQ-072 (5): an agent with no queued job gets {"jobs": []}; no job,
    agent column or audit entry changes (pulls are not audited, #71)."""
    a = env.agent()
    for i, state in enumerate(STATES):
        env.job(a, created=T0 - timedelta(hours=2, minutes=i), state=state)
    before = env.all_jobs()
    mark = env.last_audit()
    r = env.pull(a)
    assert r.content == b'{"jobs":[]}'
    assert env.all_jobs() == before
    assert env.audit_after(mark) == []


def test_a_pull_that_dispatches_writes_no_audit_entry(env: Env) -> None:
    """#71: pulls are not audited."""
    a = env.agent()
    env.job(a, created=T0 - timedelta(minutes=3))
    mark = env.last_audit()
    assert len(pulled(env.pull(a))) == 1
    assert env.audit_after(mark) == []


# ------------------------------------------------------------ CHK-M3-246


def _one_concurrent_round(env: Env) -> None:
    a = env.agent()
    ids = {env.job(a, created=T0 - timedelta(minutes=30 - i)) for i in range(12)}
    barrier = threading.Barrier(4)
    got: list[list[str]] = []
    errors: list[Any] = []
    lock = threading.Lock()

    def puller(n: int) -> None:
        client = TestClient(env.app, client=(f"10.73.251.{n}", 1234))
        try:
            barrier.wait(timeout=30)
            r = client.get(
                PULL.replace("{id}", str(a.agent_id)), headers=env.headers(a)
            )
            with lock:
                if r.status_code != 200:
                    errors.append((r.status_code, r.text))
                else:
                    got.append([j["job_id"] for j in r.json()["jobs"]])
        finally:
            client.close()

    threads = [threading.Thread(target=puller, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    flat = [UUID(j) for js in got for j in js]
    assert len(flat) == len(set(flat)), got  # never one job twice
    assert set(flat) == ids
    assert all(len(js) <= 10 for js in got)
    assert {r[1] for r in env.jobs_of(a)} == {"dispatched"}


def test_concurrent_pulls_never_share_a_job(env: Env) -> None:
    """REQ-072 (2), CHK-M3-350 via the API: four simultaneous pulls by one
    agent return every queued job at most once, and all of them between the
    four (4 x 10 >= 12); repeated over five agents."""
    for _ in range(5):
        _one_concurrent_round(env)


# ------------------------------------------------------------ CHK-M3-247


def test_other_agents_jobs_are_never_returned(env: Env) -> None:
    """REQ-072 (3), CHK-M3-347: B's queued jobs never reach A and stay queued."""
    a, b = env.agent(), env.agent()
    theirs = [env.job(b, created=T0 - timedelta(minutes=9 - i)) for i in range(3)]
    mine = env.job(a, created=T0 - timedelta(minutes=1))
    assert [j["job_id"] for j in pulled(env.pull(a))] == [str(mine)]
    assert [r[1] for r in env.jobs_of(b)] == ["queued"] * 3
    assert {UUID(j["job_id"]) for j in pulled(env.pull(b))} == set(theirs)


def test_jobs_in_any_state_but_queued_are_never_returned(env: Env) -> None:
    """REQ-072 (3), CHK-M3-349: dispatched, running, completed, partial,
    failed, expired and cancelled jobs (pickup_by still ahead) are not
    returned and do not change."""
    a = env.agent()
    for i, state in enumerate(STATES):
        env.job(a, created=T0 - timedelta(minutes=30 - i), state=state)
    before = env.jobs_of(a)
    assert pulled(env.pull(a)) == []
    assert env.jobs_of(a) == before


def test_pickup_by_must_still_be_ahead(env: Env) -> None:
    """REQ-072 (3), TS §4.4, CHK-M3-349: a queued job whose pickup_by is now
    or past is not returned (and stays queued for the sweep to expire); one
    microsecond ahead is returned."""
    a = env.agent()
    at_now = env.job(a, created=T0 - timedelta(hours=24), pickup_by=T0)
    past = env.job(
        a, created=T0 - timedelta(hours=25), pickup_by=T0 - timedelta(hours=1)
    )
    ahead = env.job(
        a,
        created=T0 - timedelta(hours=23),
        pickup_by=T0 + timedelta(microseconds=1),
    )
    assert [j["job_id"] for j in pulled(env.pull(a))] == [str(ahead)]
    states = {r[0]: r[1] for r in env.jobs_of(a)}
    assert states[at_now] == states[past] == "queued"
    assert states[ahead] == "dispatched"


def test_a_compliance_job_is_returned_with_the_inventory_job(env: Env) -> None:
    """PD-40 (a): REQ-072 (4) ("not returned in M3") is superseded by REQ-213
    (1), (2) (CHK-M3-247's compliance half → CHK-M9-221). A queued compliance
    row planted as owner (with an eval_spec) is now returned with the
    inventory job, oldest first, as its stored payload, and dispatched; no
    answer holds eval_spec, operator or expected (CHK-M3-346 kept)."""
    a = env.agent()
    comp = env.compliance(a, created=T0 - timedelta(minutes=20))
    inv = env.job(a, created=T0 - timedelta(minutes=10))
    r = env.pull(a)
    assert r.status_code == 200 and not pull_schema_errors(r.json())
    schemas.JobsResponse.model_validate_json(r.content)
    jobs = r.json()["jobs"]
    assert [j["job_id"] for j in jobs] == [str(comp), str(inv)]
    want = dict(env.job_row(comp)[5])  # pickup_by: the same instant (ruling 10-23)
    assert parse(jobs[0]["pickup_by"]) == parse(want.pop("pickup_by"))
    assert {k: v for k, v in jobs[0].items() if k != "pickup_by"} == want
    assert jobs[0]["kind"] == "compliance"
    for word in ("eval_spec", "operator", "expected"):
        assert f'"{word}"' not in r.text, word
    assert env.job_row(comp)[:2] == ("dispatched", T0)
    assert pulled(env.pull(a)) == []


# ------------------------------------------------------------ CHK-M3-248


def test_ten_jobs_answer_validates_against_document_and_fixture_shape(env: Env) -> None:
    """REQ-072 (6): the full answer validates against the job-pull response
    schema of manager/openapi.json and the model; it has the shape of the
    jobs/response_valid_ten_jobs.json fixture (ten inventory jobs)."""
    fx = next(f for f in loader.select("jobs", "response") if f.id.endswith("ten_jobs"))
    a = env.agent()
    for i in range(10):
        env.job(a, created=T0 - timedelta(minutes=20 - i))
    jobs = pulled(env.pull(a))
    want = fx.body()["jobs"]
    assert len(jobs) == len(want) == 10
    assert [list(j) for j in jobs] == [list(w) for w in want]


def test_openapi_documents_the_pull_operation() -> None:
    """REQ-060 (1), (5): GET only, no request body, 200 -> JobsResponse (both
    Job variants, maxItems 10), refusals problem+json, no 422."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert set(doc["paths"][PULL]) == {"get"}
    op = doc["paths"][PULL]["get"]
    assert "requestBody" not in op
    resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert resp == {"$ref": "#/components/schemas/JobsResponse"}
    jr = doc["components"]["schemas"]["JobsResponse"]
    assert jr["properties"]["jobs"]["maxItems"] == 10
    refs = {x["$ref"] for x in jr["properties"]["jobs"]["items"]["oneOf"]}
    assert refs == {
        "#/components/schemas/InventoryJob",
        "#/components/schemas/ComplianceJob",
    }
    assert "422" not in op["responses"]
    for status in ("401", "403", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
    params = [(p["name"], p["in"]) for p in op.get("parameters", [])]
    assert params == [("id", "path")]  # no query parameter at all


# ------------------------------------------------------------ CHK-M3-249


def test_well_formed_batches_for_jobs_that_cannot_take_them_are_409(
    env: Env, tmp_path: Path
) -> None:
    """REQ-073 (2), TS §6.1 L1071: a valid batch for the agent's own
    dispatched and queued inventory jobs, an unknown job and another agent's
    job, and an empty start notice: each 409 job_not_acceptable, one
    agent.result_refused entry (actor agent:<id>, target job:<job_id>, no
    stdout or stderr), no scan_result row and no job change.

    PD-40 (a): REQ-073 (1) ("every well-formed post answers 409", CHK-M3-249's
    own-compliance case and plant CHK-M3-359) is superseded by REQ-214 (2):
    a well-formed batch for the agent's own dispatched compliance job is now
    200 and stored (→ CHK-M9-225); the other cases are unchanged."""
    a, b = env.agent(), env.agent()
    canary_out = f"CANARY-{secrets.token_hex(8)}"
    canary_err = f"CANARY-{secrets.token_hex(8)}"
    own_dispatched = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    own_queued = env.job(a, created=T0 - timedelta(minutes=4))
    theirs = env.job(b, created=T0 - timedelta(minutes=2), state="dispatched")
    unknown = uuid4()
    loud = batch(item(stdout=canary_out, stderr=canary_err), item(), final=True)
    cases: list[tuple[UUID, dict[str, Any]]] = [
        (own_dispatched, loud),
        (own_queued, loud),
        (unknown, loud),
        (theirs, loud),
        (own_dispatched, {"results": [], "final": False}),  # the start notice
    ]
    jobs_before = env.all_jobs()
    results_before = env.results_count()
    for jid, body in cases:
        env.clock.at += timedelta(seconds=10)
        mark = env.last_audit()
        r = env.post(a, jid, body)
        p = problem(r, 409, "job_not_acceptable")
        assert canary_out not in r.text and canary_err not in r.text
        assert set(p) <= {"type", "title", "status", "detail", "instance"}
        entries = env.audit_after(mark)
        assert len(entries) == 1, entries
        actor, action, target, detail = entries[0]
        assert (actor, action, target) == (
            f"agent:{a.agent_id}",
            "agent.result_refused",
            f"job:{jid}",
        )
        assert detail["reason"] == "job_not_acceptable"
        assert detail.get("alert") is not True
        text = json.dumps(detail)
        assert canary_out not in text and canary_err not in text
        assert "stdout" not in text and "stderr" not in text
        assert env.results_count() == results_before
        assert env.all_jobs() == jobs_before
    with env.conn() as c:
        row = c.execute(
            "SELECT count(*) FROM audit_log WHERE detail::text LIKE %s"
            " OR detail::text LIKE %s",
            (f"%{canary_out}%", f"%{canary_err}%"),
        ).fetchone()
    assert row == (0,)
    # REQ-214 (2): the agent's own dispatched compliance job takes the batch.
    from . import scan_pg_fixtures as sf

    cat = sf.make_catalog(env.db, sf.Clock(env.clock.now()), tmp_path)
    pol = cat.policy(1)
    with sf.owner(env.server) as o:
        sid = sf.owner_scan(o, pol, state="running")
        own = sf.owner_job(
            o,
            sid,
            a.agent_id,
            pol,
            state="dispatched",
            created_at=T0 - timedelta(minutes=3),
        )
    # PR #18 CI fix (work/reports/PR18-ci-fix-test.md): the stored row is
    # committed to the shared session database. Its job is dated T0
    # (2026-10), so once `db migrate` runs in a later month there is no
    # partition for it and the row sits in scan_result_default, which
    # test_schema_scanning and test_fleet_alerts_pg require to be empty. It
    # is removed afterwards, as planted_default_row does.
    try:
        env.clock.at += timedelta(seconds=10)
        mark = env.last_audit()
        r = env.post(a, own.job_id, batch(item(plugin_uuid=str(pol.uuids[0]))))
        assert r.status_code == 200 and r.json() == {"accepted": 1, "duplicates": 0}, (
            r.text
        )
        assert refused_entries(env, mark) == []
        assert env.results_count() == results_before + 1
    finally:
        with sf.owner(env.server) as o:
            o.execute("DELETE FROM scan_result WHERE job_id = %s", (own.job_id,))


def test_refusal_entry_counts_the_batch_without_its_content(env: Env) -> None:
    """#71: the entry may describe the batch (count, final) but never holds a
    plugin's output; a 50-item batch (TS §3.5 L253 maximum) is refused once."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    marks = [f"CANARY-{secrets.token_hex(8)}" for _ in range(50)]
    mark = env.last_audit()
    r = env.post(a, jid, batch(*(item(stdout=m, stderr=m) for m in marks), final=False))
    problem(r, 409, "job_not_acceptable")
    (entry,) = refused_entries(env, mark)
    text = json.dumps(entry[3])
    assert not [m for m in marks if m in text]
    assert entry[3].get("results") in (None, 50)
    assert entry[3].get("final") in (None, False)


# ------------------------------------------------------------ CHK-M3-250


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"",
        b"[1, 2]",
        b"null",
        b"{}",
        b'{"results": [], "final": false',
        b"\xff\xfe{}",
        b'{"results": [], "final": false, "x": 1}',
        b'{"results": {}, "final": true}',
        b"[" * 200_000 + b"]" * 200_000,
        json.dumps(batch(*(item() for _ in range(51)))).encode(),
        json.dumps(batch(item(stdout=None))).encode(),
        json.dumps(batch(item(exit_code=1.0))).encode(),
        json.dumps(batch(item(started_at="2026-10-23T12:00:00"))).encode(),
        b'{"results": [], "final": NaN}',
    ],
    ids=[
        "not-json",
        "empty",
        "array",
        "null",
        "empty-object",
        "truncated",
        "bad-utf8",
        "extra-key",
        "results-object",
        "deep-nesting",
        "batch-51",
        "stdout-null",
        "exit-code-float",
        "naive-timestamp",
        "nan",
    ],
)
def test_malformed_bodies_are_400_and_write_nothing(env: Env, content: bytes) -> None:
    """REQ-073 (3): a malformed body with a valid token is 400
    invalid_request, never 422 or 500; no entry, no job change, no flood
    count."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    before = env.job_row(jid)
    mark = env.last_audit()
    r = env.post(a, jid, content=content)
    problem(r, 400, "invalid_request")
    assert env.audit_after(mark) == []
    assert env.job_row(jid) == before
    assert env.windows().result_409.count(a.agent_id) == 0


@pytest.mark.parametrize(
    "job_id",
    ["x", "123", "not-a-uuid", str(uuid4())[:-1], str(uuid4()) + "0"],
    ids=["x", "digits", "word", "short", "long"],
)
def test_a_job_id_that_is_not_a_uuid_is_400(env: Env, job_id: str) -> None:
    """#59 (malformed parameter): 400 invalid_request, no entry."""
    a = env.agent()
    mark = env.last_audit()
    problem(env.post(a, job_id, batch()), 400, "invalid_request")
    assert env.audit_after(mark) == []


def padded(size: int) -> bytes:
    """A well-formed batch padded with JSON whitespace to exactly size bytes."""
    raw = json.dumps(batch()).encode()
    assert len(raw) < size
    return raw + b" " * (size - len(raw))


def test_exactly_the_cap_as_sent_passes_and_one_byte_more_is_413(env: Env) -> None:
    """REQ-066 (1), (3), TS §6.3 L1138: 1,572,864 bytes as sent reach the
    route (409 in M3); 1,572,865 get 413 too_large with Connection: close and
    one agent.result_refused entry; nothing stored; a 413 is not a 409 and
    does not count toward the flood window."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    mark = env.last_audit()
    problem(env.post(a, jid, content=padded(CAP)), 409, "job_not_acceptable")
    assert [e[3]["reason"] for e in refused_entries(env, mark)] == [
        "job_not_acceptable"
    ]
    mark = env.last_audit()
    jobs_before = env.all_jobs()
    r = env.post(a, jid, content=padded(CAP + 1))
    problem(r, 413, "too_large")
    assert r.headers.get("connection") == "close"
    entries = env.audit_after(mark)
    assert [(e[1], e[2], e[3]["reason"]) for e in entries] == [
        ("agent.result_refused", f"job:{jid}", "too_large")
    ]
    assert env.all_jobs() == jobs_before
    assert env.windows().result_409.count(a.agent_id) == 1


def test_gzip_body_is_inflated_and_capped_at_one_and_a_half_mib(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-066 (4), TS §6.3 L1138 "after decompression": a gzip batch that
    inflates to exactly 1,572,864 bytes is read (409); to 1,572,865 it is 413
    with one too_large entry; the inflater is asked for the 1.5 MiB cap, so it
    stops after at most cap + 1 bytes (bound proven in TASK-060)."""
    from bitscan_manager.api.agent import jobs as jobs_module
    from bitscan_manager.services.inventory.decode import gunzip_capped as real

    caps: list[int] = []

    def spy(chunks: Any, cap: int) -> bytes:
        caps.append(cap)
        return real(chunks, cap)

    monkeypatch.setattr(jobs_module, "gunzip_capped", spy)
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    gz = {"Content-Encoding": "gzip"}
    mark = env.last_audit()
    problem(
        env.post(a, jid, content=gzip.compress(padded(CAP)), headers=gz),
        409,
        "job_not_acceptable",
    )
    small = gzip.compress(padded(CAP + 1))
    assert len(small) < 64 * 1024  # small as sent: only the inflated size is over
    r = env.post(a, jid, content=small, headers=gz)
    problem(r, 413, "too_large")
    assert [e[3]["reason"] for e in refused_entries(env, mark)] == [
        "job_not_acceptable",
        "too_large",
    ]
    assert caps == [CAP, CAP]


def test_gzip_bomb_is_refused_quickly(env: Env) -> None:
    """TS §8.1 L1250: a small body inflating to 256 MiB is 413 well within
    the time bound, with one too_large entry."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    co = zlib.compressobj(9, zlib.DEFLATED, 31)  # gzip wrapper
    zeros = bytes(1 << 20)
    bomb = b"".join(co.compress(zeros) for _ in range(256)) + co.flush()
    assert len(bomb) < CAP
    mark = env.last_audit()
    started = time.monotonic()
    problem(
        env.post(a, jid, content=bomb, headers={"Content-Encoding": "gzip"}),
        413,
        "too_large",
    )
    assert time.monotonic() - started < 10
    assert [e[3]["reason"] for e in refused_entries(env, mark)] == ["too_large"]


@pytest.mark.parametrize(
    ("content", "encoding"),
    [
        (b"\x1f\x8b\x08\x00garbage", "gzip"),
        (gzip.compress(json.dumps(batch()).encode())[:-6], "gzip"),
        (gzip.compress(json.dumps(batch()).encode()) + b"trailing", "gzip"),
        (json.dumps(batch()).encode(), "gzip"),
        (gzip.compress(b"not json"), "gzip"),
        (gzip.compress(b"\xff\xfe"), "gzip"),
        (json.dumps(batch()).encode(), "br"),
        (json.dumps(batch()).encode(), "deflate"),
    ],
    ids=[
        "bad-gzip",
        "truncated-gzip",
        "trailing-data",
        "plain-labelled-gzip",
        "gzip-not-json",
        "gzip-bad-utf8",
        "br",
        "deflate",
    ],
)
def test_bad_encodings_are_400_and_write_nothing(
    env: Env, content: bytes, encoding: str
) -> None:
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    mark = env.last_audit()
    r = env.post(a, jid, content=content, headers={"Content-Encoding": encoding})
    problem(r, 400, "invalid_request")
    assert env.audit_after(mark) == []


def test_identity_encoding_is_read_as_plain(env: Env) -> None:
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    r = env.post(a, jid, batch(), headers={"Content-Encoding": "identity"})
    problem(r, 409, "job_not_acceptable")


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
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), *headers],
        "client": ("10.73.252.1", 1),
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


def test_no_body_byte_is_read_before_a_401_on_the_real_route(env: Env) -> None:
    """REQ-066 (3) carry-over: with no token, an unknown bsa_, a user token or
    another scheme, the real results route answers 401 having pulled 0 body
    bytes, with a Content-Length over the cap or a chunked body, and writes
    no entry."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    path = RESULTS.replace("{id}", str(a.agent_id)).replace("{job_id}", str(jid))
    user = new_token(TokenKind.API)
    mark = env.last_audit()
    for auth in (
        [],
        [
            (
                b"authorization",
                b"Bearer " + new_agent_token(AgentTokenKind.AGENT).encode(),
            )
        ],
        [(b"authorization", f"Bearer {user}".encode())],
        [(b"authorization", f"Basic {a.token}".encode())],
    ):
        for length in ([(b"content-length", str(CAP + 1).encode())], []):
            feed = Feed([b" " * 65536] * 30)
            status, _ = drive(
                env,
                path,
                [*auth, *length, (b"x-bitscan-machine-id", a.machine_id.encode())],
                feed,
            )
            assert status == 401
            assert feed.pulled == 0, (auth, length)
    assert env.audit_after(mark) == []


def test_over_cap_with_a_valid_token_reads_at_most_cap_plus_a_chunk(env: Env) -> None:
    """REQ-066 (2), (3): with a valid token, a Content-Length over the cap is
    refused unread; a chunked body is refused after the chunk that crosses the
    cap; each gives 413 and one too_large entry."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    path = RESULTS.replace("{id}", str(a.agent_id)).replace("{job_id}", str(jid))
    auth = [
        (b"authorization", f"Bearer {a.token}".encode()),
        (b"x-bitscan-machine-id", a.machine_id.encode()),
    ]
    mark = env.last_audit()
    feed = Feed([b" " * 65536] * 30)
    status, headers = drive(
        env, path, [*auth, (b"content-length", str(CAP + 1).encode())], feed
    )
    assert status == 413 and feed.pulled == 0
    assert headers.get("connection") == "close"
    env.clock.at += timedelta(seconds=10)
    feed = Feed([b" " * 65536] * 30)
    status, _ = drive(env, path, auth, feed)
    assert status == 413
    assert CAP < feed.pulled <= CAP + 65536
    assert [e[3]["reason"] for e in refused_entries(env, mark)] == [
        "too_large",
        "too_large",
    ]


# ------------------------------------------------------------ CHK-M3-251


def post_refused(env: Env, a: Agent, jid: UUID, step: timedelta) -> None:
    env.clock.at += step
    problem(env.post(a, jid, batch()), 409, "job_not_acceptable")


def test_twenty_refusals_in_ten_minutes_do_not_alert_and_the_21st_does(
    env: Env,
) -> None:
    """REQ-073 (4), #54 (c), #65 (f), #71: 20 refused posts from one agent
    within 10 minutes write no alert; the 21st (at 9 min 59 s after the
    first) writes one result_409_flood entry (action alert.result_409_flood,
    actor and target agent:<id>, detail.alert true) and the metric rises by
    one; further 409s within the hour write none."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    mark = env.last_audit()
    counted = alerts_counted("result_409_flood")
    first = env.clock.at = T0 + timedelta(seconds=1)
    problem(env.post(a, jid, batch()), 409, "job_not_acceptable")
    for _ in range(19):
        post_refused(env, a, jid, timedelta(seconds=25))
    assert flood_entries(env, mark) == []
    assert alerts_counted("result_409_flood") == counted
    env.clock.at = first + timedelta(minutes=9, seconds=59)
    problem(env.post(a, jid, batch()), 409, "job_not_acceptable")
    entries = flood_entries(env, mark)
    assert len(entries) == 1, entries
    actor, action, target, detail = entries[0]
    assert actor == target == f"agent:{a.agent_id}"
    assert action == "alert.result_409_flood"
    assert detail["alert"] is True
    assert alerts_counted("result_409_flood") == counted + 1
    assert len(refused_entries(env, mark)) == 21  # every 409 has its own entry
    fired = env.clock.at
    for _ in range(178):  # 20 s apart: about 30 inside every 10 minutes
        post_refused(env, a, jid, timedelta(seconds=20))
        assert env.windows().result_409.count(a.agent_id) > 20
    assert env.clock.at - fired == timedelta(minutes=59, seconds=20)
    assert len(flood_entries(env, mark)) == 1
    env.clock.at = fired + timedelta(hours=1)
    problem(env.post(a, jid, batch()), 409, "job_not_acceptable")
    assert len(flood_entries(env, mark)) == 2  # the next hour, still flooding
    assert alerts_counted("result_409_flood") == counted + 2


def test_twenty_one_refusals_spread_over_more_than_ten_minutes_do_not_alert(
    env: Env,
) -> None:
    """#54 (c): the window slides: 21 posts 31 s apart (10 min 20 s from the
    first to the last) never have more than 20 inside 10 minutes."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    mark = env.last_audit()
    for _ in range(21):
        post_refused(env, a, jid, timedelta(seconds=31))
    assert flood_entries(env, mark) == []


def test_the_flood_window_is_per_agent_and_counts_409s_only(env: Env) -> None:
    """#54 (c): two agents with 15 refusals each do not alert; 413s and 400s
    from an agent with 20 409s do not make 21."""
    a, b = env.agent(), env.agent()
    ja = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    jb = env.job(b, created=T0 - timedelta(minutes=5), state="dispatched")
    mark = env.last_audit()
    for _ in range(15):
        env.clock.at += timedelta(seconds=20)
        problem(env.post(a, ja, batch()), 409, "job_not_acceptable")
        problem(env.post(b, jb, batch()), 409, "job_not_acceptable")
    for _ in range(5):
        env.clock.at += timedelta(seconds=10)
        problem(env.post(a, ja, batch()), 409, "job_not_acceptable")
    assert env.windows().result_409.count(a.agent_id) == 20
    for _ in range(3):
        env.clock.at += timedelta(seconds=5)
        problem(env.post(a, ja, content=padded(CAP + 1)), 413, "too_large")
        problem(env.post(a, ja, content=b"[]"), 400, "invalid_request")
    assert flood_entries(env, mark) == []
    env.clock.at += timedelta(seconds=5)
    problem(env.post(a, ja, batch()), 409, "job_not_acceptable")
    assert [e[2] for e in flood_entries(env, mark)] == [f"agent:{a.agent_id}"]


def test_a_rolled_back_flood_alert_leaves_the_hour_free(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead ruling 2026-10-23 (commit-only marking): if the transaction that
    wrote the 21st refusal and its alert fails, neither entry exists, the
    metric does not move, and the next refusal alerts."""
    from bitscan_manager.services import jobs as service

    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    for _ in range(20):
        post_refused(env, a, jid, timedelta(seconds=20))
    real = service.refuse_results
    calls = {"n": 0}

    def failing(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected after the alert")

    monkeypatch.setattr(service, "refuse_results", failing)
    mark = env.last_audit()
    counted = alerts_counted("result_409_flood")
    env.clock.at += timedelta(seconds=5)
    r = env.post(a, jid, batch())
    assert r.status_code == 500, r.text
    assert calls["n"] == 1
    assert env.audit_after(mark) == []
    assert alerts_counted("result_409_flood") == counted
    post_refused(env, a, jid, timedelta(seconds=5))
    assert len(flood_entries(env, mark)) == 1
    assert alerts_counted("result_409_flood") == counted + 1


def test_the_flood_window_is_built_once_per_app(env: Env) -> None:
    """Ruling 2026-10-23 (TASK-063 nit): create_app() builds the windows once;
    every request uses that object (no lazy build), and another app has its
    own."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    windows = env.app.state.agent_windows
    flood = windows.result_409
    for _ in range(3):
        post_refused(env, a, jid, timedelta(seconds=10))
    assert env.app.state.agent_windows is windows
    assert env.app.state.agent_windows.result_409 is flood
    assert flood.count(a.agent_id) == 3
    other = create_app(
        Runtime(
            clock=env.clock,
            db=env.db,
            totp_cipher=Cipher(),
            sink_gate=Gate(),
            limits=RateLimiter(env.clock),
        )
    )
    assert other.state.agent_windows.result_409 is not flood
    assert other.state.agent_windows.result_409.count(a.agent_id) == 0


# ------------------------------------------------------------ CHK-M3-252


def test_stdout_never_reaches_a_log_and_records_carry_agent_and_job(
    env: Env, logs: io.StringIO
) -> None:
    """REQ-073 (5), REQ-087 (1), TS §8.4 L1287, CHK-M3-366: canary stdout and
    stderr (plain and gzip) are in no log record; every record of a results
    request after the token check carries its agent_id and job_id; no token
    or token hash is logged."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    outs = [f"CANARY-{secrets.token_hex(8)}" for _ in range(4)]
    body = batch(item(stdout=outs[0], stderr=outs[1]))
    problem(env.post(a, jid, body), 409, "job_not_acceptable")
    env.clock.at += timedelta(seconds=5)
    gz = gzip.compress(json.dumps(batch(item(stdout=outs[2], stderr=outs[3]))).encode())
    problem(
        env.post(a, jid, content=gz, headers={"Content-Encoding": "gzip"}),
        409,
        "job_not_acceptable",
    )
    env.clock.at += timedelta(seconds=5)
    problem(env.post(a, jid, content=padded(CAP + 1)), 413, "too_large")
    text = logs.getvalue()
    for c in outs:
        assert c not in text
    for secret in (a.token, a.token[4:], token_hash(a.token)):
        assert secret not in text
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    access = [
        ln
        for ln in lines
        if ln.get("message") == "request" and str(jid) in str(ln.get("path"))
    ]
    assert len(access) == 3, access
    for ln in access:
        assert ln["agent_id"] == str(a.agent_id)
        assert ln["job_id"] == str(jid)
    for rid in {ln["request_id"] for ln in access}:
        mine = [ln for ln in lines if ln.get("request_id") == rid]
        assert all(ln["job_id"] == str(jid) for ln in mine), mine
        assert all(ln["agent_id"] == str(a.agent_id) for ln in mine), mine


def test_pull_records_carry_the_agent_id(env: Env, logs: io.StringIO) -> None:
    """REQ-087 (1): a pull's records carry its agent_id; no token logged."""
    a = env.agent()
    env.job(a, created=T0 - timedelta(minutes=5))
    pulled(env.pull(a))
    lines = [json.loads(ln) for ln in logs.getvalue().splitlines() if ln.strip()]
    access = [ln for ln in lines if ln.get("message") == "request"]
    assert access and all(ln["agent_id"] == str(a.agent_id) for ln in access)
    assert a.token not in logs.getvalue()


# ------------------------------------------------------------ CHK-M3-253


REQUEST_FIXTURES = list(loader.select("results", "request"))


def test_every_results_request_fixture_is_present() -> None:
    assert len([f for f in REQUEST_FIXTURES if f.valid]) >= 6
    assert len([f for f in REQUEST_FIXTURES if not f.valid]) >= 20


@pytest.mark.parametrize("fx", REQUEST_FIXTURES, ids=lambda f: f.id)
def test_results_request_fixtures_through_the_route(
    env: Env, fx: loader.Fixture
) -> None:
    """REQ-060, REQ-061: a valid fixture is well formed, so in M3 it gets 409
    with one entry (the NUL-in-stdout fixture included: its rule is M9); an
    invalid one is 400 with no entry. Both plain and gzip."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    for encoding in (None, "gzip"):
        env.clock.at += timedelta(seconds=5)
        content = fx.body_bytes()
        headers = {}
        if encoding:
            content = gzip.compress(content)
            headers["Content-Encoding"] = encoding
        mark = env.last_audit()
        r = env.post(a, jid, content=content, headers=headers)
        if fx.valid:
            problem(r, 409, "job_not_acceptable")
            assert len(refused_entries(env, mark)) == 1
        else:
            problem(r, 400, "invalid_request")
            assert env.audit_after(mark) == []


def test_openapi_documents_the_results_operation() -> None:
    """REQ-060 (1), (3), (5), decisions 2026-10-23 (self-read bodies still
    documented): POST only; requestBody required -> ResultsRequest (items
    ResultItem, at most 50, exact TS §6.5 keys); 200 -> ResultsResponse with
    exactly accepted and duplicates; 409 and 413 documented as problem+json;
    no 422; no dangling $ref."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert set(doc["paths"][RESULTS]) == {"post"}
    op = doc["paths"][RESULTS]["post"]
    assert op["requestBody"]["required"] is True
    assert op["requestBody"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ResultsRequest"}}
    }
    comps = doc["components"]["schemas"]
    req = comps["ResultsRequest"]
    assert req["additionalProperties"] is False
    assert sorted(req["properties"]) == ["final", "results"]
    assert sorted(req["required"]) == ["final", "results"]
    assert req["properties"]["results"]["maxItems"] == 50
    assert req["properties"]["results"]["items"] == {
        "$ref": "#/components/schemas/ResultItem"
    }
    it = comps["ResultItem"]
    assert it["additionalProperties"] is False
    assert sorted(it["properties"]) == sorted(
        [
            "plugin_uuid",
            "exit_code",
            "stdout",
            "stderr",
            "started_at",
            "finished_at",
            "timed_out",
            "truncated",
            "error",
        ]
    )
    resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert resp == {"$ref": "#/components/schemas/ResultsResponse"}
    assert sorted(comps["ResultsResponse"]["properties"]) == ["accepted", "duplicates"]
    assert "422" not in op["responses"]
    for status in ("400", "401", "403", "409", "413", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
    params = sorted((p["name"], p["in"]) for p in op.get("parameters", []))
    assert params == [("id", "path"), ("job_id", "path")]
    refs = set(
        re2.findall(
            r'"\$ref": ?"#/components/schemas/([A-Za-z0-9_]+)"', json.dumps(doc)
        )
    )
    assert refs <= set(comps), refs - set(comps)
    assert "HTTPValidationError" not in json.dumps(doc)


# ------------------------------------------------- matrix (CHK-M3-160 to -163)


def call(env: Env, route: str, a: Agent, h: dict[str, str], **kw: Any) -> Any:
    pid = kw.get("path_id") or str(a.agent_id)
    if route == "pull":
        return env.client(kw.get("ip")).get(PULL.replace("{id}", pid), headers=h)
    jid = kw["job_id"]
    path = RESULTS.replace("{id}", pid).replace("{job_id}", str(jid))
    return env.client(kw.get("ip")).post(
        path,
        content=json.dumps(batch()).encode(),
        headers={"Content-Type": "application/json"} | h,
    )


@pytest.mark.parametrize("route", ["pull", "results"])
def test_wrong_tokens_are_one_401(env: Env, route: str) -> None:
    """REQ-062 (2) on the real routes: no header, Basic, empty bearer, admin
    bsu_ and bsk_, a live bse_, an unknown bsa_ and an unknown prefix each get
    one byte-identical 401; no job is dispatched and nothing is written."""
    a = env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5))
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    users = []
    with env.conn() as c:
        c.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
            " created_by) VALUES (%s, 10, %s, 1)",
            (token_hash(bse), T0 + timedelta(days=1)),
        )
        uid = c.execute(
            "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
            " totp_last_step, created_at) VALUES (%s, 'x', 'admin', 'enc', 1, %s)"
            " RETURNING user_id",
            (f"jb-{secrets.token_hex(4)}", T0),
        ).fetchone()
        assert uid is not None
        for kind, tk in (("session", TokenKind.SESSION), ("api", TokenKind.API)):
            tok = new_token(tk)
            users.append(tok)
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
    cases = [
        {},
        {"Authorization": f"Basic {a.token}"},
        {"Authorization": "Bearer "},
        *({"Authorization": f"Bearer {u}"} for u in users),
        {"Authorization": f"Bearer {bse}"},
        {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
    ]
    before = env.all_jobs()
    mark = env.last_audit()
    bodies = set()
    for h in cases:
        r = call(env, route, a, h | {"X-Bitscan-Machine-Id": a.machine_id}, job_id=jid)
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1
    assert env.all_jobs() == before
    assert env.audit_after(mark) == []


@pytest.mark.parametrize("route", ["pull", "results"])
def test_token_outcomes_dispatch_and_write_nothing(env: Env, route: str) -> None:
    """REQ-064 (1), (6), CHK-M3-339 on the real routes: revoked, expired,
    pending, rejected, decommissioned and foreign-{id} callers get their #59
    answer; their queued job stays queued (pull) and no refusal entry is
    written (results); a mismatch writes only its own alert."""
    revoked = env.agent(token_revoked_at=T0 - timedelta(minutes=1))
    expired = env.agent(token_expires_at=T0)
    pending = env.agent(status="awaiting_approval")
    decom = env.agent(status="decommissioned", token_revoked_at=T0 - timedelta(days=1))
    other = env.agent()
    mismatch = env.agent()
    cases = [
        (revoked, {}, 401, "token_revoked"),
        (expired, {}, 401, "token_expired"),
        (pending, {}, 403, "pending_approval"),
        (decom, {}, 401, "token_revoked"),
        (other, {"path_id": str(revoked.agent_id)}, 403, "forbidden"),
        (mismatch, {"machine": "f" * 32}, 401, "machine_id_mismatch"),
    ]
    for a, kw, status, type_ in cases:
        jid = env.job(a, created=T0 - timedelta(minutes=5))
        target = (
            env.job(revoked, created=T0 - timedelta(minutes=4))
            if kw.get("path_id")
            else jid
        )
        before = env.all_jobs()
        mark = env.last_audit()
        h = {
            "Authorization": f"Bearer {a.token}",
            "X-Bitscan-Machine-Id": kw.get("machine", a.machine_id),
        }
        problem(
            call(env, route, a, h, job_id=target, path_id=kw.get("path_id")),
            status,
            type_,
        )
        assert env.all_jobs() == before, type_
        kinds = [e[3].get("alert_kind") for e in env.audit_after(mark)]
        assert not refused_entries(env, mark), type_
        assert kinds == (
            ["machine_id_mismatch"] if type_ == "machine_id_mismatch" else []
        ), (
            type_,
            kinds,
        )


@pytest.mark.parametrize("route", ["pull", "results"])
def test_thirty_requests_a_minute_then_429(env: Env, route: str) -> None:
    """REQ-065 (1), CHK-M3-163 on the real routes: the 31st request of one
    agent in a minute is 429 with Retry-After and changes nothing; another
    agent passes; the next minute is open."""
    a, b = env.agent(), env.agent()
    jid = env.job(a, created=T0 - timedelta(minutes=5), state="dispatched")
    jb = env.job(b, created=T0 - timedelta(minutes=5))
    env.clock.at = T0 + timedelta(seconds=5)
    h = env.headers(a)
    for _ in range(30):
        r = call(env, route, a, h, job_id=jid)
        assert r.status_code in (200, 409), r.text
    env.job(a, created=T0 - timedelta(minutes=1))  # a queued job for the 31st pull
    before = env.all_jobs()
    mark = env.last_audit()
    r = call(env, route, a, h, job_id=jid)
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"
    assert env.all_jobs() == before and env.audit_after(mark) == []
    assert call(env, route, b, env.headers(b), job_id=jb).status_code in (200, 409)
    env.clock.at = T0 + timedelta(minutes=1)
    assert call(env, route, a, h, job_id=jid).status_code in (200, 409)


# ------------------------------------------------------------ CHK-M3-169


@pytest.mark.parametrize(
    ("path", "method"), [(PULL, "GET"), (RESULTS, "POST")], ids=["pull", "results"]
)
def test_route_is_in_the_agent_group_with_the_bsa_dependency(
    path: str, method: str
) -> None:
    """REQ-062 (1): each route exists once with exactly its method, carries the
    bsa_ dependency and no user dependency."""
    app = create_app()
    routes = [r for r in api_routes(app.routes) if r.path == path]
    assert len(routes) == 1 and routes[0].methods == {method}
    marks: set[Any] = set()
    stack = list(routes[0].dependant.dependencies)
    while stack:
        dep = stack.pop()
        marks.add(getattr(dep.call, "bitscan_agent_auth", None))
        assert getattr(dep.call, "bitscan_auth", None) is None
        stack.extend(dep.dependencies)
    assert "bsa_" in marks and "bse_" not in marks


def test_results_route_declares_no_body_parameter() -> None:
    """Carry-over (REQ-066 (3)): the results route reads its own body after the
    token check, so FastAPI must not read it first: no body field."""
    app = create_app()
    (route,) = [r for r in api_routes(app.routes) if r.path == RESULTS]
    assert route.body_field is None
    assert route.dependant.body_params == []
