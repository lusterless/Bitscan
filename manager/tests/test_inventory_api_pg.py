"""TASK-074: PUT /api/v1/agent/{id}/inventory[?job_id=...] on PostgreSQL (TP-M3-28).

Checks CHK-M3-255 to CHK-M3-263 of tests/m3/test-plan.md, the API halves of the
mutation rows CHK-M3-358, -360 and -361, and the re-run of the agent-route
matrix and route walk on the real route. Expected values come from the spec and
the answers, not from the code: TS §3.4 L239 (at most one upload without job_id
per agent per 10 minutes, otherwise 429), L240 (10 MB gzip / 64 MB / 50,000
rows / raw 256 KB; rejected with 413 or 422 and audit-logged), L244 (an
inventory job whose upload is rejected becomes failed; a late upload carrying
the job_id is stored as unscheduled), TS §6.1 L1066 (?job_id= completes an
inventory job), L1072 (the manager re-checks every cap), TS §6.5 L1186
(Content-Encoding: gzip; 204), TS §6.3 L1138, #72 (a) gzip required, else 400;
(b) 413 for byte limits, 422 for rows, fields, duplicates and the hash; (c) a
malformed body is 400, audit-logged, its job left to the sweep; (d) the job_id
cases; (e) every upload handled as unscheduled counts, the window starts when
it reaches decoding, accepted or not; only the dispatched case is exempt; #71
(agent.inventory_refused, actor agent:<id>; accepted uploads not audited),
REQ-076 (1)-(6), REQ-066 (1)-(3), REQ-087. Lead rulings 2026-10-23: the route
answers InventoryRefused.type, never .reason; the inventory upload documents
its 422; the burst window is built once.
"""

import asyncio
import gzip
import io
import json
import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.api.agent import AgentWindows
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
from tests.contract import loader

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_contract_agent import OPENAPI
from .test_inventory_decode import REASONS, expected_status
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
TEMPLATE = "/api/v1/agent/{id}/inventory"
CAP = 10_485_760  # 10 MiB as sent (TS §6.3 L1138; #57 (b))
INFLATED = 67_108_864  # 64 MiB decompressed (TS §3.4 L240)
TYPES = {400: "invalid_request", 413: "too_large", 422: "about:blank"}
REFUSING = ("queued", "expired", "cancelled", "running")


def iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


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


def pkg(
    name: str, version: str = "1.0", arch: str = "amd64", **over: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "architecture": arch,
        "status": "install ok installed",
        "source": name,
        "installed_size_kb": 10,
    } | over


def inv(packages: list[dict[str, Any]] | None = None, **os_over: Any) -> dict[str, Any]:
    pk = packages if packages is not None else [pkg("bash", "5.2-1"), pkg("coreutils")]
    os_info: dict[str, Any] = {
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "os_pretty_name": "Ubuntu 24.04.1 LTS",
        "kernel_release": "6.8.0-45-generic",
        "architecture": "x86_64",
        "cpu_count": 4,
        "memory_mb": 8192,
        "ip_addresses": ["10.0.0.5"],
        "uptime_s": 3600,
        "raw": {"lsb": "Ubuntu"},
    } | os_over
    return {"os_info": os_info, "packages": pk, "list_sha256": loader.list_sha256(pk)}


def gz(doc: Any, level: int = 9) -> bytes:
    data = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    return gzip.compress(data, compresslevel=level, mtime=0)


def stored_gzip(doc: dict[str, Any], size: int) -> bytes:
    """A valid inventory, padded with JSON whitespace and gzipped without
    compression, so the body as sent is exactly size bytes."""
    raw = json.dumps(doc).encode()
    pad = max(0, size - len(raw) - 1024)
    for _ in range(50):
        body = gz(raw + b" " * pad, level=0)
        if len(body) == size:
            return body
        pad += size - len(body)
        assert pad >= 0
    raise AssertionError("could not hit the size")


@dataclass
class Env:
    server: PgServer
    clock: Clock
    app: FastAPI
    db: AppDatabase
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def client(self, ip: str | None = None) -> TestClient:
        ip = ip or "10.74.250.1"
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
            "hostname": f"iv-{secrets.token_hex(3)}",
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

    def job(self, a: Agent, state: str = "dispatched", *, minutes_ago: int = 5) -> UUID:
        jid = uuid4()
        created = T0 - timedelta(minutes=minutes_ago + 1)
        pb = created + timedelta(hours=24)
        payload = {
            "job_id": str(jid),
            "agent_id": str(a.agent_id),
            "kind": "inventory",
            "pickup_by": pb.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        dispatched = None if state == "queued" else T0 - timedelta(minutes=minutes_ago)
        finished = (
            T0 - timedelta(minutes=1)
            if state in ("completed", "failed", "expired", "cancelled")
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

    def compliance(self, a: Agent) -> UUID:
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
            created = T0 - timedelta(minutes=6)
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
                " eval_spec, created_at, pickup_by, dispatched_at) VALUES (%s,"
                " 'compliance', %s, %s, 'dispatched', %s, %s, %s, %s, %s)",
                (
                    jid,
                    scan[0],
                    a.agent_id,
                    Jsonb(payload),
                    Jsonb([{"operator": "equals", "expected": "x"}]),
                    created,
                    created + timedelta(hours=24),
                    T0 - timedelta(minutes=5),
                ),
            )
            oc.commit()
        return jid

    def put(
        self,
        a: Agent,
        doc: Any = None,
        *,
        content: bytes | None = None,
        job_id: UUID | str | None = None,
        headers: dict[str, str] | None = None,
        encoding: str | None = "gzip",
        token: str | None = None,
        machine: str | None = None,
        path_id: str | None = None,
        ip: str | None = None,
    ) -> Any:
        h: dict[str, str] = {
            "Authorization": f"Bearer {token if token is not None else a.token}",
            "X-Bitscan-Machine-Id": machine or a.machine_id,
            "Content-Type": "application/json",
        }
        if encoding is not None:
            h["Content-Encoding"] = encoding
        h |= headers or {}
        if content is None:
            content = gz(doc if doc is not None else inv())
        params = {} if job_id is None else {"job_id": str(job_id)}
        path = TEMPLATE.replace("{id}", path_id or str(a.agent_id))
        return self.client(ip).put(path, content=content, headers=h, params=params)

    def job_row(self, jid: UUID) -> tuple[Any, ...]:
        with self.conn() as c:
            row = c.execute(
                "SELECT state::text, dispatched_at, finished_at FROM scan_job"
                " WHERE job_id = %s",
                (jid,),
            ).fetchone()
        assert row is not None
        return tuple(row)

    def stored(self, a: Agent) -> dict[str, Any]:
        """What an accepted upload writes for agent a."""
        with self.conn() as c:
            os_row = c.execute(
                "SELECT os_pretty_name, raw, collected_at FROM os_info"
                " WHERE agent_id = %s",
                (a.agent_id,),
            ).fetchone()
            pk = c.execute(
                "SELECT p.name, p.version, p.architecture, ap.status FROM agent_package"
                " ap JOIN package p USING (package_id) WHERE ap.agent_id = %s"
                " ORDER BY 1, 2, 3",
                (a.agent_id,),
            ).fetchall()
            snaps = c.execute(
                "SELECT list_sha256, package_count, collected_at FROM"
                " inventory_snapshot WHERE agent_id = %s ORDER BY snapshot_id",
                (a.agent_id,),
            ).fetchall()
            last = c.execute(
                "SELECT last_inventory_at FROM agent WHERE agent_id = %s", (a.agent_id,)
            ).fetchone()
        assert last is not None
        return {"os": os_row, "packages": pk, "snapshots": snaps, "last": last[0]}

    def nothing_stored(self, a: Agent) -> None:
        s = self.stored(a)
        assert s == {"os": None, "packages": [], "snapshots": [], "last": None}, s

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

    def all_jobs(self) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute("SELECT * FROM scan_job ORDER BY job_id").fetchall()


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
    assert set(body) <= {"type", "title", "status", "detail", "instance"}
    # the answer carries the type, never the decoder's internal reason word
    assert not [w for w in REASONS if w in r.text], r.text
    return body


def accepted(r: Any) -> None:
    assert r.status_code == 204, (r.status_code, r.text)
    assert r.content == b""


def refusals(env: Env, mark: int) -> list[tuple[Any, ...]]:
    return [e for e in env.audit_after(mark) if e[1] == "agent.inventory_refused"]


def one_refusal(
    env: Env, mark: int, a: Agent, status: int, job_id: UUID | None
) -> dict[str, Any]:
    """Exactly one entry since mark: agent.inventory_refused, actor and target
    agent:<id>, detail naming the status and the job."""
    entries = env.audit_after(mark)
    assert len(entries) == 1, entries
    actor, action, target, detail = entries[0]
    assert (actor, action, target) == (
        f"agent:{a.agent_id}",
        "agent.inventory_refused",
        f"agent:{a.agent_id}",
    )
    assert detail["status"] == status
    assert detail["job_id"] == (None if job_id is None else str(job_id))
    assert detail.get("alert") is not True
    assert "packages" not in detail and "raw" not in detail and "os_info" not in detail
    return dict(detail)


# ------------------------------------------------------------ CHK-M3-255


def test_dispatched_job_upload_completes_it_and_stores_the_inventory(env: Env) -> None:
    """REQ-076 (1), TS §6.1 L1066, #72 (d): 204 with no body; the job is
    completed with finished_at = now; os_info, agent_package and one snapshot
    are written and last_inventory_at is now; an accepted upload writes no
    audit entry (#71)."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    accepted(env.put(a, inv(), job_id=jid))
    assert env.job_row(jid) == ("completed", T0 - timedelta(minutes=5), T0)
    s = env.stored(a)
    assert s["os"][0] == "Ubuntu 24.04.1 LTS" and s["os"][1] == {"lsb": "Ubuntu"}
    assert s["os"][2] == T0
    assert s["packages"] == [
        ("bash", "5.2-1", "amd64", "install ok installed"),
        ("coreutils", "1.0", "amd64", "install ok installed"),
    ]
    assert s["snapshots"] == [(inv()["list_sha256"], 2, T0)]
    assert s["last"] == T0
    assert env.audit_after(mark) == []


def test_completion_is_in_the_ingest_transaction(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carry-over (#72 (d)): the job completes in the same transaction as the
    ingest, so a failure while completing stores nothing and leaves the job
    dispatched; the next upload completes it."""
    from bitscan_manager.repositories.jobs import JobRepo

    a = env.agent()
    jid = env.job(a)
    real = JobRepo.complete
    calls = {"n": 0}

    def failing(self: JobRepo, job_id: UUID, now: datetime) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected while completing")
        return real(self, job_id, now)

    monkeypatch.setattr(JobRepo, "complete", failing)
    r = env.put(a, inv(), job_id=jid)
    assert r.status_code == 500, r.text
    assert env.job_row(jid)[0] == "dispatched"
    env.nothing_stored(a)
    accepted(env.put(a, inv(), job_id=jid))
    assert env.job_row(jid)[0] == "completed"
    assert env.stored(a)["last"] == T0


def test_a_failed_ingest_does_not_complete_the_job(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reverse: an ingest that fails after its writes leaves no data and
    the job dispatched (one transaction)."""
    from bitscan_manager.repositories.agents import AgentRepo

    a = env.agent()
    jid = env.job(a)

    def boom(self: AgentRepo, agent_id: UUID, now: datetime) -> None:
        raise RuntimeError("injected after the package writes")

    monkeypatch.setattr(AgentRepo, "set_last_inventory", boom)
    assert env.put(a, inv(), job_id=jid).status_code == 500
    assert env.job_row(jid)[0] == "dispatched"
    env.nothing_stored(a)


def test_the_agent_row_gone_is_401_token_revoked(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carry-over: AgentGone (the row vanished after the token check) is 401
    token_revoked; nothing is stored and the job is not completed."""
    from bitscan_manager.repositories.agents import AgentRepo

    a = env.agent()
    jid = env.job(a)
    real = AgentRepo.get

    def gone_in_ingest(self: AgentRepo, agent_id: UUID, *, lock: bool = False) -> Any:
        return None if lock else real(self, agent_id, lock=lock)

    monkeypatch.setattr(AgentRepo, "get", gone_in_ingest)
    problem(env.put(a, inv(), job_id=jid), 401, "token_revoked")
    assert env.job_row(jid)[0] == "dispatched"
    env.nothing_stored(a)


def test_a_dispatched_job_upload_is_exempt_from_the_window(env: Env) -> None:
    """#72 (e): only the dispatched case is exempt: an unscheduled upload, then
    a dispatched-job upload a minute later (204), then another unscheduled
    one two minutes later (still 429: the dispatched one neither counted nor
    restarted the window)."""
    a = env.agent()
    jid = env.job(a)
    accepted(env.put(a, inv()))
    env.clock.at = T0 + timedelta(minutes=1)
    accepted(env.put(a, inv(), job_id=jid))
    assert env.job_row(jid)[0] == "completed"
    env.clock.at = T0 + timedelta(minutes=2)
    r = env.put(a, inv())
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "480"
    env.clock.at = T0 + timedelta(minutes=10)
    accepted(env.put(a, inv()))


def test_two_dispatched_jobs_in_a_row_both_complete(env: Env) -> None:
    a = env.agent()
    j1, j2 = env.job(a, minutes_ago=6), env.job(a, minutes_ago=5)
    accepted(env.put(a, inv(), job_id=j1))
    env.clock.at = T0 + timedelta(seconds=30)
    accepted(env.put(a, inv([pkg("bash", "5.2-2")]), job_id=j2))
    assert env.job_row(j1)[0] == env.job_row(j2)[0] == "completed"
    assert len(env.stored(a)["snapshots"]) == 2


# ------------------------------------------------------------ CHK-M3-256


@pytest.mark.parametrize("state", ["failed", "completed"])
def test_failed_or_completed_job_upload_is_stored_as_unscheduled(
    env: Env, state: str
) -> None:
    """REQ-076 (2), TS §3.4 L244, #72 (d), (e): 204, stored, the job unchanged;
    it counts as unscheduled: a second such upload within 10 minutes is 429."""
    a = env.agent()
    jid = env.job(a, state)
    before = env.job_row(jid)
    mark = env.last_audit()
    accepted(env.put(a, inv(), job_id=jid))
    assert env.job_row(jid) == before
    s = env.stored(a)
    assert s["last"] == T0 and len(s["snapshots"]) == 1 and len(s["packages"]) == 2
    assert env.audit_after(mark) == []
    env.clock.at = T0 + timedelta(minutes=9, seconds=59)
    problem(env.put(a, inv(), job_id=jid), 429, "rate_limited")
    problem(env.put(a, inv()), 429, "rate_limited")
    assert env.job_row(jid) == before


# ------------------------------------------------------------ CHK-M3-257


def test_unscheduled_uploads_once_per_ten_minutes(env: Env) -> None:
    """REQ-076 (3), TS §3.4 L239: a second unscheduled upload 9 min 59 s after
    the first is 429 rate_limited with Retry-After (whole seconds to the
    window end) and stores nothing; 10 min after the first it is accepted; a
    refused 429 does not restart the window; another agent is not affected."""
    a, b = env.agent(), env.agent()
    accepted(env.put(a, inv()))
    first = env.stored(a)
    env.clock.at = T0 + timedelta(minutes=5)
    r = env.put(a, inv([pkg("zsh")]))
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "300"
    env.clock.at = T0 + timedelta(minutes=9, seconds=59)
    r = env.put(a, inv([pkg("zsh")]))
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "1"
    assert env.stored(a) == first
    accepted(env.put(b, inv()))  # per agent
    env.clock.at = T0 + timedelta(minutes=10)
    accepted(env.put(a, inv([pkg("zsh")])))
    assert env.stored(a)["packages"] == [
        ("zsh", "1.0", "amd64", "install ok installed")
    ]


def test_the_window_is_asked_before_decoding(env: Env) -> None:
    """#72 (e): while limited, even an undecodable or over-limit body is 429
    (nothing is decompressed), and no refusal entry is written."""
    a = env.agent()
    accepted(env.put(a, inv()))
    env.clock.at = T0 + timedelta(minutes=1)
    mark = env.last_audit()
    for content in (
        b"\x1f\x8b\x08\x00garbage",
        gz(b" " * (INFLATED + 1)),
        gz(inv() | {"list_sha256": "0" * 64}),
    ):
        problem(env.put(a, content=content), 429, "rate_limited")
    assert env.audit_after(mark) == []


@pytest.mark.parametrize(
    ("content", "status"),
    [
        (b"\x1f\x8b\x08\x00garbage", 400),
        (gz(b"not json"), 400),
        (gz(inv() | {"list_sha256": "0" * 64}), 422),
        (gz(inv([pkg("a"), pkg("a")])), 422),
        (gz(b" " * (INFLATED + 1)), 413),
    ],
    ids=["bad-gzip-400", "bad-json-400", "hash-422", "duplicate-422", "inflated-413"],
)
def test_an_upload_refused_at_decoding_starts_the_window(
    env: Env, content: bytes, status: int
) -> None:
    """#72 (e): the window starts when an unscheduled upload reaches decoding,
    accepted or not: a valid upload a minute after a refused one is 429."""
    a = env.agent()
    mark = env.last_audit()
    problem(env.put(a, content=content), status, TYPES[status])
    one_refusal(env, mark, a, status, None)
    env.nothing_stored(a)
    env.clock.at = T0 + timedelta(minutes=1)
    problem(env.put(a, inv()), 429, "rate_limited")


def test_an_upload_refused_before_decoding_does_not_start_the_window(env: Env) -> None:
    """#72 (e): the window starts at decoding; an upload refused before it
    (no gzip, or over 10 MiB as sent) decompresses nothing, so a valid upload
    right after is accepted."""
    a = env.agent()
    problem(
        env.put(a, inv(), encoding=None, content=json.dumps(inv()).encode()),
        400,
        "invalid_request",
    )
    accepted(env.put(a, inv()))
    b = env.agent()
    problem(env.put(b, content=b"\x00" * (CAP + 1)), 413, "too_large")
    accepted(env.put(b, inv()))


def test_a_409_does_not_use_the_window(env: Env) -> None:
    """#72 (d), (e): a refused job_id (409) is not an unscheduled upload."""
    a = env.agent()
    problem(env.put(a, inv(), job_id=uuid4()), 409, "job_not_acceptable")
    accepted(env.put(a, inv()))


# ------------------------------------------------------------ CHK-M3-258


def test_over_cap_upload_naming_a_dispatched_job_fails_it(env: Env) -> None:
    """REQ-076 (4), REQ-066 (1), (3), TS §3.4 L240, L244, CHK-M3-361: a body of
    10,485,761 bytes as sent naming a dispatched job is 413 too_large with
    Connection: close; the job is failed (finished_at now); one
    agent.inventory_refused entry; nothing stored."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    r = env.put(a, content=b"\x1f" * (CAP + 1), job_id=jid)
    problem(r, 413, "too_large")
    assert r.headers.get("connection") == "close"
    assert env.job_row(jid) == ("failed", T0 - timedelta(minutes=5), T0)
    one_refusal(env, mark, a, 413, jid)
    env.nothing_stored(a)


@pytest.mark.parametrize(
    ("make", "status"),
    [
        (lambda: gz(inv() | {"list_sha256": "0" * 64}), 422),
        (lambda: gz(inv([pkg("a"), pkg("a")])), 422),
        (lambda: gz(inv([pkg("x" * 256)])), 422),
        (lambda: gz(b" " * (INFLATED + 1)), 413),
        (lambda: gz(inv(raw={"pad": "a" * 262_144})), 413),
    ],
    ids=["hash-422", "duplicate-422", "long-name-422", "inflated-413", "raw-413"],
)
def test_413_or_422_from_decoding_fails_the_dispatched_job(
    env: Env, make: Any, status: int
) -> None:
    """REQ-076 (4), TS §3.4 L240, L244, #72 (b): a decoder refusal with 413 or
    422 naming a dispatched job fails it, with one entry; nothing stored."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    problem(env.put(a, content=make(), job_id=jid), status, TYPES[status])
    assert env.job_row(jid) == ("failed", T0 - timedelta(minutes=5), T0)
    detail = one_refusal(env, mark, a, status, jid)
    assert detail["reason"] in REASONS | {"too_large"}
    env.nothing_stored(a)


def test_51k_packages_naming_a_dispatched_job_is_422_and_fails_it(env: Env) -> None:
    """TS §3.4 L240: more than 50,000 rows is 422 (#72 (b)); 50,000 pass."""
    a = env.agent()
    jid = env.job(a)
    many = [pkg(f"p{i}") for i in range(50_001)]
    problem(env.put(a, inv(many), job_id=jid), 422, "about:blank")
    assert env.job_row(jid)[0] == "failed"
    b = env.agent()
    jb = env.job(b)
    accepted(env.put(b, inv(many[:50_000]), job_id=jb))
    assert env.job_row(jb)[0] == "completed"
    assert env.stored(b)["snapshots"][0][1] == 50_000


@pytest.mark.parametrize("state", ["queued", "failed", "completed"])
def test_over_cap_naming_a_job_that_is_not_dispatched_leaves_it(
    env: Env, state: str
) -> None:
    """TS §3.4 L244 fails only a dispatched job: any other state is unchanged;
    the refusal is still audit-logged."""
    a = env.agent()
    jid = env.job(a, state)
    before = env.job_row(jid)
    mark = env.last_audit()
    problem(env.put(a, content=b"\x1f" * (CAP + 1), job_id=jid), 413, "too_large")
    assert env.job_row(jid) == before
    one_refusal(env, mark, a, 413, jid)


def test_another_agents_dispatched_job_is_never_failed(env: Env) -> None:
    """A refused upload naming B's dispatched job fails nothing of B's."""
    a, b = env.agent(), env.agent()
    theirs = env.job(b)
    for content in (b"\x1f" * (CAP + 1), gz(inv() | {"list_sha256": "0" * 64})):
        env.clock.at += timedelta(seconds=1)
        r = env.put(a, content=content, job_id=theirs)
        assert r.status_code in (409, 413), r.text
    assert env.job_row(theirs)[0] == "dispatched"


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
    env: Env, path: str, query: bytes, headers: list[tuple[bytes, bytes]], feed: Feed
) -> tuple[int, dict[str, str]]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-encoding", b"gzip"),
            *headers,
        ],
        "client": ("10.74.252.1", 1),
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
    """REQ-066 (3) carry-over: no token, an unknown bsa_, a user token or
    another scheme: 401 with 0 body bytes pulled (Content-Length over the cap
    or chunked); no entry, the named dispatched job left dispatched."""
    a = env.agent()
    jid = env.job(a)
    path = TEMPLATE.replace("{id}", str(a.agent_id))
    query = f"job_id={jid}".encode()
    mark = env.last_audit()
    for auth in (
        [],
        [
            (
                b"authorization",
                b"Bearer " + new_agent_token(AgentTokenKind.AGENT).encode(),
            )
        ],
        [(b"authorization", f"Bearer {new_token(TokenKind.API)}".encode())],
        [(b"authorization", f"Basic {a.token}".encode())],
    ):
        for length in ([(b"content-length", str(CAP + 1).encode())], []):
            feed = Feed([b"\x1f" * 1_048_576] * 12)
            status, _ = drive(
                env,
                path,
                query,
                [*auth, *length, (b"x-bitscan-machine-id", a.machine_id.encode())],
                feed,
            )
            assert status == 401
            assert feed.pulled == 0, (auth, length)
    assert env.audit_after(mark) == []
    assert env.job_row(jid)[0] == "dispatched"


def test_over_cap_with_a_valid_token_reads_at_most_cap_plus_a_chunk(env: Env) -> None:
    """REQ-066 (2): a Content-Length over the cap is refused unread; a chunked
    body is refused after the chunk that crosses the cap; each 413 fails its
    dispatched job and writes one entry."""
    a = env.agent()
    path = TEMPLATE.replace("{id}", str(a.agent_id))
    auth = [
        (b"authorization", f"Bearer {a.token}".encode()),
        (b"x-bitscan-machine-id", a.machine_id.encode()),
    ]
    j1, j2 = env.job(a, minutes_ago=6), env.job(a, minutes_ago=5)
    mark = env.last_audit()
    feed = Feed([b"\x1f" * 65536] * 200)
    status, headers = drive(
        env,
        path,
        f"job_id={j1}".encode(),
        [*auth, (b"content-length", str(CAP + 1).encode())],
        feed,
    )
    assert status == 413 and feed.pulled == 0
    assert headers.get("connection") == "close"
    feed = Feed([b"\x1f" * 65536] * 200)
    status, _ = drive(env, path, f"job_id={j2}".encode(), auth, feed)
    assert status == 413
    assert CAP < feed.pulled <= CAP + 65536
    assert env.job_row(j1)[0] == env.job_row(j2)[0] == "failed"
    assert [e[3]["job_id"] for e in refusals(env, mark)] == [str(j1), str(j2)]


# ------------------------------------------------------------ CHK-M3-259


def test_job_ids_that_cannot_take_an_upload_are_409(env: Env) -> None:
    """REQ-076 (5), #72 (d): unknown, another agent's (dispatched), the agent's
    own compliance job (owner-planted, dispatched), queued, expired, cancelled
    and running inventory jobs: 409 job_not_acceptable, one entry naming the
    job, nothing stored, no job changed."""
    a, b = env.agent(), env.agent()
    cases: dict[str, UUID] = {
        "unknown": uuid4(),
        "another-agents": env.job(b),
        "compliance": env.compliance(a),
    }
    for state in REFUSING:
        cases[state] = env.job(a, state)
    jobs_before = env.all_jobs()
    for name, jid in cases.items():
        env.clock.at += timedelta(seconds=1)
        mark = env.last_audit()
        r = env.put(a, inv(), job_id=jid)
        problem(r, 409, "job_not_acceptable")
        detail = one_refusal(env, mark, a, 409, jid)
        assert detail["reason"] == "job_not_acceptable", name
        env.nothing_stored(a)
    assert env.all_jobs() == jobs_before


def test_a_409_is_decided_before_the_body_is_decoded(env: Env) -> None:
    """#72 (d): nothing is stored or decoded for a refused job_id: even an
    undecodable body is answered 409."""
    a = env.agent()
    jid = env.job(a, "expired")
    problem(
        env.put(a, content=b"\x1f\x8b\x08\x00garbage", job_id=jid),
        409,
        "job_not_acceptable",
    )


# ------------------------------------------------------------ CHK-M3-260


def test_a_well_formed_body_of_the_wrong_shape_is_422(env: Env) -> None:
    """TASK-060 mapping (#72 (b)): JSON the model refuses (a top-level array)
    is 422 about:blank and, naming a dispatched job, fails it."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    problem(env.put(a, content=gz(b"[]"), job_id=jid), 422, "about:blank")
    assert env.job_row(jid)[0] == "failed"
    one_refusal(env, mark, a, 422, jid)


@pytest.mark.parametrize(
    "job_id",
    ["x", "123", "not-a-uuid", str(uuid4())[:-1], "", str(uuid4()) + "0"],
    ids=["x", "digits", "word", "short", "empty", "long"],
)
def test_a_job_id_that_is_not_a_uuid_is_400(env: Env, job_id: str) -> None:
    """REQ-076 (6): 400 invalid_request; nothing stored."""
    a = env.agent()
    problem(env.put(a, inv(), job_id=job_id), 400, "invalid_request")
    env.nothing_stored(a)


@pytest.mark.parametrize("encoding", [None, "identity", "br", "deflate", "x-gzip"])
def test_without_content_encoding_gzip_it_is_400_audited_and_job_left(
    env: Env, encoding: str | None
) -> None:
    """#72 (a), (c): a body not sent with Content-Encoding: gzip (TS §6.5
    L1186) is 400, audit-logged, and its dispatched job is left to the sweep;
    nothing stored."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    r = env.put(a, content=json.dumps(inv()).encode(), job_id=jid, encoding=encoding)
    problem(r, 400, "invalid_request")
    assert env.job_row(jid)[0] == "dispatched"
    one_refusal(env, mark, a, 400, jid)
    env.nothing_stored(a)


@pytest.mark.parametrize(
    "content",
    [
        b"\x1f\x8b\x08\x00garbage",
        gz(inv())[:-6],
        gz(inv()) + b"trailing",
        gz(b"not json"),
        gz(b"\xff\xfe{}"),
        gz(b"[" * 100 + b"]" * 100),
        b"",
    ],
    ids=[
        "bad-gzip",
        "truncated",
        "trailing",
        "not-json",
        "bad-utf8",
        "deep",
        "empty",
    ],
)
def test_malformed_gzip_or_json_is_400_audited_and_job_left(
    env: Env, content: bytes
) -> None:
    """#72 (c): 400 invalid_request, one entry, the dispatched job is not
    failed (TS §3.4 names only 413 and 422); nothing stored."""
    a = env.agent()
    jid = env.job(a)
    mark = env.last_audit()
    problem(env.put(a, content=content, job_id=jid), 400, "invalid_request")
    assert env.job_row(jid)[0] == "dispatched"
    one_refusal(env, mark, a, 400, jid)
    env.nothing_stored(a)


# ------------------------------------------------------------ CHK-M3-261


def test_a_valid_two_mib_upload_is_accepted(env: Env) -> None:
    """REQ-066 (1), CHK-M3-360: a valid 2 MiB body (as sent) is not held to
    the 1 MiB JSON cap."""
    a = env.agent()
    body = stored_gzip(inv(), 2 * 1_048_576)
    assert len(body) == 2 * 1_048_576
    accepted(env.put(a, content=body))
    assert env.stored(a)["last"] == T0


def test_exactly_ten_mib_as_sent_passes_and_one_byte_more_is_413(env: Env) -> None:
    """REQ-066 (1): exactly 10,485,760 bytes as sent pass the cap (a valid body
    is stored); 10,485,761 get 413."""
    a = env.agent()
    jid = env.job(a)
    body = stored_gzip(inv(), CAP)
    assert len(body) == CAP
    accepted(env.put(a, content=body, job_id=jid))
    assert env.job_row(jid)[0] == "completed"
    b = env.agent()
    over = stored_gzip(inv(), CAP + 1)
    assert len(over) == CAP + 1
    problem(env.put(b, content=over), 413, "too_large")
    env.nothing_stored(b)


# ------------------------------------------------------------ CHK-M3-262


def test_package_names_raw_and_tokens_never_reach_a_log(
    env: Env, logs: io.StringIO
) -> None:
    """REQ-087: canary package names and raw values (accepted, refused and
    over-cap uploads) are in no log record; no token is logged; the records of
    a job upload carry its agent_id and job_id."""
    a = env.agent()
    jid = env.job(a)
    names = [f"canary-{secrets.token_hex(8)}" for _ in range(3)]
    raws = [f"CANARY-{secrets.token_hex(8)}" for _ in range(3)]
    accepted(env.put(a, inv([pkg(names[0])], raw={"k": raws[0]}), job_id=jid))
    env.clock.at = T0 + timedelta(seconds=10)
    bad = inv([pkg(names[1])], raw={"k": raws[1]}) | {"list_sha256": "0" * 64}
    problem(env.put(a, bad), 422, "about:blank")
    b = env.agent()
    big = inv([pkg(names[2])], raw={"k": raws[2]})
    problem(env.put(b, content=stored_gzip(big, CAP + 1)), 413, "too_large")
    text = logs.getvalue()
    for c in names + raws:
        assert c not in text
    for secret in (a.token, a.token[4:], token_hash(a.token), b.token):
        assert secret not in text
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    access = [
        ln
        for ln in lines
        if ln.get("message") == "request" and ln.get("job_id") == str(jid)
    ]
    assert len(access) == 1, access
    assert access[0]["agent_id"] == str(a.agent_id)
    mine = [ln for ln in lines if ln.get("request_id") == access[0]["request_id"]]
    assert all(ln["agent_id"] == str(a.agent_id) for ln in mine)
    # nor in an audit entry
    with env.conn() as conn:
        for x in names + raws:
            row = conn.execute(
                "SELECT count(*) FROM audit_log WHERE detail::text LIKE %s", (f"%{x}%",)
            ).fetchone()
            assert row == (0,), x


# ------------------------------------------------------------ CHK-M3-263


INVENTORY = list(loader.select("inventory", "request"))


@pytest.mark.parametrize("fx", INVENTORY, ids=lambda f: f.id)
def test_inventory_fixtures_through_the_route(env: Env, fx: loader.Fixture) -> None:
    """REQ-060, REQ-061, #72 (b): each fixture (gzipped) on a fresh agent: a
    valid one with no decoder mark is 204 and stored; every other gets its
    TASK-060 status (413 byte limits, 422 rows/fields/duplicates/hash, 400 not
    storable or not JSON) with its type, one refusal entry and nothing
    stored."""
    a = env.agent()
    mark = env.last_audit()
    r = env.put(a, content=gz(fx.body_bytes()))
    if fx.valid and fx.decoder is None:
        accepted(r)
        assert env.stored(a)["last"] == T0
        assert refusals(env, mark) == []
        # an accepted upload is not audited; only the new-package burst alert
        # (more than 1,000 packages new to the fleet, #65 (e)) may be written
        kinds = {e[3].get("alert_kind") for e in env.audit_after(mark)}
        assert kinds <= {"new_packages_burst"}, kinds
    else:
        status = expected_status(fx)
        problem(r, status, TYPES[status])
        one_refusal(env, mark, a, status, None)
        env.nothing_stored(a)


def test_openapi_documents_the_inventory_operation() -> None:
    """REQ-060 (1), (5), lead ruling 2026-10-23 (option (a)): PUT only;
    requestBody required -> InventoryBody; 204; the declared 422 and the other
    refusals as problem+json; the job_id query parameter; no
    HTTPValidationError anywhere; InventoryBody, OsInfo, PackageItem and
    RawValue present."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert set(doc["paths"][TEMPLATE]) == {"put"}
    op = doc["paths"][TEMPLATE]["put"]
    assert op["requestBody"]["required"] is True
    assert op["requestBody"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/InventoryBody"}}
    }
    assert "204" in op["responses"] and "content" not in op["responses"]["204"]
    for status in ("400", "401", "403", "409", "413", "422", "429", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
        assert op["responses"][status]["content"]["application/problem+json"][
            "schema"
        ] == {"$ref": "#/components/schemas/Problem"}
    params = sorted(
        (p["name"], p["in"], p.get("required", False)) for p in op["parameters"]
    )
    assert params == [("id", "path", True), ("job_id", "query", False)]
    comps = doc["components"]["schemas"]
    for name in ("InventoryBody", "OsInfo", "PackageItem", "RawValue"):
        assert name in comps, name
    body = comps["InventoryBody"]
    assert sorted(body["properties"]) == ["list_sha256", "os_info", "packages"]
    assert body["additionalProperties"] is False
    assert "HTTPValidationError" not in json.dumps(doc)


# ------------------------------------------------- matrix (CHK-M3-160 to -163)


def test_wrong_tokens_are_one_401_and_store_nothing(env: Env) -> None:
    """REQ-062 (2) on the real route: no header, Basic, empty bearer, a user
    token, a live bse_, an unknown bsa_ and an unknown prefix: one
    byte-identical 401; nothing stored, the job left dispatched, no entry."""
    a = env.agent()
    jid = env.job(a)
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    with env.conn() as c:
        c.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
            " created_by) VALUES (%s, 10, %s, 1)",
            (token_hash(bse), T0 + timedelta(days=1)),
        )
    path = TEMPLATE.replace("{id}", str(a.agent_id))
    mark = env.last_audit()
    bodies = set()
    for h in (
        {},
        {"Authorization": f"Basic {a.token}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {new_token(TokenKind.API)}"},
        {"Authorization": f"Bearer {bse}"},
        {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
    ):
        r = env.client().put(
            path,
            content=gz(inv()),
            params={"job_id": str(jid)},
            headers=h
            | {
                "X-Bitscan-Machine-Id": a.machine_id,
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
            },
        )
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1
    env.nothing_stored(a)
    assert env.job_row(jid)[0] == "dispatched"
    assert env.audit_after(mark) == []


def test_token_outcomes_store_nothing(env: Env) -> None:
    """REQ-064 on the real route: revoked, expired, pending, decommissioned,
    foreign {id} and mismatch callers get their #59 answer; nothing is stored
    for anyone, no job changes, no refusal entry (a mismatch writes only its
    own alert)."""
    revoked = env.agent(token_revoked_at=T0 - timedelta(minutes=1))
    cases: list[tuple[Agent, dict[str, Any], int, str]] = [
        (revoked, {}, 401, "token_revoked"),
        (env.agent(token_expires_at=T0), {}, 401, "token_expired"),
        (env.agent(status="awaiting_approval"), {}, 403, "pending_approval"),
        (
            env.agent(status="decommissioned", token_revoked_at=T0 - timedelta(days=1)),
            {},
            401,
            "token_revoked",
        ),
        (env.agent(), {"path_id": str(revoked.agent_id)}, 403, "forbidden"),
        (env.agent(), {"machine": "f" * 32}, 401, "machine_id_mismatch"),
    ]
    for a, kw, status, type_ in cases:
        kw = dict(kw)
        jid = env.job(a)
        jobs_before = env.all_jobs()
        mark = env.last_audit()
        problem(env.put(a, inv(), job_id=jid, **kw), status, type_)
        env.nothing_stored(a)
        env.nothing_stored(revoked)
        assert env.all_jobs() == jobs_before, type_
        assert refusals(env, mark) == [], type_
        kinds = [e[3].get("alert_kind") for e in env.audit_after(mark)]
        assert kinds == (
            ["machine_id_mismatch"] if type_ == "machine_id_mismatch" else []
        )


def test_thirty_requests_a_minute_then_429(env: Env) -> None:
    """REQ-065 (1) on the real route: the agent's 31st request in a minute
    (over any of its routes) is 429 and stores nothing."""
    a = env.agent()
    env.clock.at = T0 + timedelta(seconds=5)
    path = f"/api/v1/agent/{a.agent_id}/jobs"
    h = {"Authorization": f"Bearer {a.token}", "X-Bitscan-Machine-Id": a.machine_id}
    for _ in range(30):
        assert env.client().get(path, headers=h).status_code == 200
    jid = env.job(a)
    r = env.put(a, inv(), job_id=jid)
    problem(r, 429, "rate_limited")
    assert r.headers["Retry-After"] == "55"
    env.nothing_stored(a)
    assert env.job_row(jid)[0] == "dispatched"


# ------------------------------------------------------------ CHK-M3-169


def test_inventory_is_in_the_agent_group_with_the_bsa_dependency() -> None:
    """REQ-062 (1): PUT /api/v1/agent/{id}/inventory exists once, carries the
    bsa_ dependency and no user dependency, and has no FastAPI body field
    (so nothing is read before the token check)."""
    app = create_app()
    routes = [r for r in api_routes(app.routes) if r.path == TEMPLATE]
    assert len(routes) == 1 and routes[0].methods == {"PUT"}
    route = routes[0]
    assert route.body_field is None and route.dependant.body_params == []
    marks: set[Any] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        marks.add(getattr(dep.call, "bitscan_agent_auth", None))
        assert getattr(dep.call, "bitscan_auth", None) is None
        stack.extend(dep.dependencies)
    assert "bsa_" in marks and "bse_" not in marks


def test_the_burst_window_is_built_once_per_app(env: Env) -> None:
    """Carry-over: the new-packages burst window is the one create_app()
    built; requests reuse it and count into it."""
    windows = env.app.state.agent_windows
    assert isinstance(windows, AgentWindows)
    burst = windows.new_packages
    a = env.agent()
    names = [f"burst-{secrets.token_hex(6)}" for _ in range(3)]
    accepted(env.put(a, inv([pkg(n) for n in names])))
    assert env.app.state.agent_windows is windows
    assert env.app.state.agent_windows.new_packages is burst
    assert burst.count(a.agent_id) == 3
