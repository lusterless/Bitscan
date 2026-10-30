"""TP-M9-01: a simulated agent and the API environment for the M9 route
suites (tester-m9b; CHK-M9-104).

The real runner is M10. Until then an agent is *simulated*: its requests are
built from the shared contract fixtures in ``tests/contract/fixtures/``
(valid fixtures only), the fixture ``plugin_uuid`` values mapped onto the
pulled job's plugins in order, and sent with a real ``bsa_`` token and
machine id through the real routes of ``create_app``. A gzip variant posts
the same bytes compressed (``Content-Encoding: gzip``).

``ApiEnv`` is the app on PostgreSQL with the real auth dependencies, a
clock double, the M2 shipper over a recording sink, and helpers for users
and tokens of each role and kind.
"""

from __future__ import annotations

import copy
import gzip
import json
import secrets
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from tests.contract import loader

from .catalog_api import RecordingSink
from .conftest import PgServer
from .scan_pg_fixtures import T0, AgentRow, Clock, iso, make_agent
from .test_totp_enrol import Cipher

PULL = "/api/v1/agent/{id}/jobs"
RESULTS = "/api/v1/agent/{id}/jobs/{job_id}/results"
SCANS = "/api/v1/scans"
SCHEDULES = "/api/v1/scan-schedules"
PW_HASH = hash_password("m9 sim pass " + "word")


def fixture_body(name: str) -> dict[str, Any]:
    """A *valid* results request fixture by file stem, e.g.
    ``request_valid_one_final``."""
    for fx in loader.fixtures():
        if fx.route == "results" and fx.id.endswith("/" + name):
            assert fx.valid, f"{name} is not a valid fixture"
            body = fx.body()
            assert isinstance(body, dict)
            return copy.deepcopy(body)
    raise LookupError(name)


def fixture_bytes(name: str) -> bytes:
    for fx in loader.fixtures():
        if fx.route == "results" and fx.id.endswith("/" + name):
            assert fx.valid
            return fx.body_bytes()
    raise LookupError(name)


def map_uuids(body: dict[str, Any], uuids: Sequence[UUID | str]) -> dict[str, Any]:
    """The fixture's items, each given the job's plugin uuid at its position
    (item i → uuids[i]), everything else as the fixture has it."""
    out = copy.deepcopy(body)
    assert len(out["results"]) <= len(uuids), (len(out["results"]), len(uuids))
    for i, it in enumerate(out["results"]):
        it["plugin_uuid"] = str(uuids[i])
    return out


def item(plugin_uuid: UUID | str, **over: Any) -> dict[str, Any]:
    """One result item in the TS §6.5 shape, defaults from the one_final fixture."""
    base: dict[str, Any] = dict(fixture_body("request_valid_one_final")["results"][0])
    base["plugin_uuid"] = str(plugin_uuid)
    base["started_at"] = iso(T0 - timedelta(seconds=3))
    base["finished_at"] = iso(T0 - timedelta(seconds=2))
    return base | over


def batch(*items: dict[str, Any], final: bool = True) -> dict[str, Any]:
    return {"results": list(items), "final": final}


def start_notice() -> dict[str, Any]:
    return fixture_body("request_valid_start_notice")


@dataclass
class SimAgent:
    env: ApiEnv
    row: AgentRow
    ip: str

    @property
    def agent_id(self) -> UUID:
        return self.row.agent_id

    def client(self) -> TestClient:
        return self.env.client_for(self.ip)

    def pull(self, *, path_id: str | None = None) -> Any:
        return self.client().get(
            PULL.replace("{id}", path_id or str(self.agent_id)),
            headers=self.row.headers(),
        )

    def pulled(self) -> list[dict[str, Any]]:
        r = self.pull()
        assert r.status_code == 200, (r.status_code, r.text)
        jobs: list[dict[str, Any]] = r.json()["jobs"]
        return jobs

    def post(
        self,
        job_id: UUID | str,
        body: Any = None,
        *,
        content: bytes | None = None,
        gzip_body: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        path = RESULTS.replace("{id}", str(self.agent_id)).replace(
            "{job_id}", str(job_id)
        )
        h = self.row.headers() | {"Content-Type": "application/json"}
        raw = content if content is not None else json.dumps(body).encode()
        if gzip_body:
            raw = gzip.compress(raw)
            h["Content-Encoding"] = "gzip"
        return self.client().post(path, content=raw, headers=h | dict(headers or {}))

    def start(self, job_id: UUID | str) -> Any:
        return self.post(job_id, start_notice())


@dataclass
class ApiEnv:
    server: PgServer
    clock: Clock
    db: AppDatabase
    sink: RecordingSink
    shipper: Shipper
    app: Any
    _clients: dict[str, TestClient] = field(default_factory=dict)
    _ip: int = 0

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def client_for(self, ip: str) -> TestClient:
        if ip not in self._clients:
            self._clients[ip] = TestClient(
                self.app, client=(ip, 1234), raise_server_exceptions=False
            )
        return self._clients[ip]

    @property
    def client(self) -> TestClient:
        return self.client_for("10.9.0.1")

    def fresh_ip(self) -> str:
        self._ip += 1
        return f"10.9.{1 + self._ip // 250}.{1 + self._ip % 250}"

    # --- agents ------------------------------------------------------------

    def agent(self, status: str = "online", **kw: Any) -> SimAgent:
        with self.conn() as c:
            row = make_agent(c, status, at=self.clock.now(), **kw)
        return SimAgent(self, row, self.fresh_ip())

    # --- users and tokens --------------------------------------------------

    def user(self, role: str = "operator", *, totp: bool = True) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, %s, %s::user_role, %s, %s,"
                " %s) RETURNING user_id",
                (
                    f"m9-{secrets.token_hex(5)}",
                    PW_HASH,
                    role,
                    "enc:00" if totp else None,
                    5 if totp else None,
                    self.clock.now() - timedelta(days=1),
                ),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def token(self, uid: int, kind: str = "session", *, revoked: bool = False) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        now = self.clock.now()
        with self.conn() as c:
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at, revoked_at) VALUES (%s, %s, %s, %s, %s,"
                " %s, %s)",
                (
                    uid,
                    kind,
                    token_hash(tok),
                    kind == "session",
                    now + timedelta(days=30),
                    now - timedelta(minutes=1),
                    now - timedelta(seconds=1) if revoked else None,
                ),
            )
        return tok

    def caller(self, role: str = "operator", kind: str = "session") -> tuple[int, str]:
        uid = self.user(role)
        return uid, self.token(uid, kind)

    def call(
        self,
        method: str,
        path: str,
        token: str | None,
        *,
        body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        h = {"Authorization": f"Bearer {token}"} if token else {}
        if content is None and body is not None:
            content = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        elif content is not None:
            h["Content-Type"] = "application/json"
        return self.client.request(
            method, path, content=content, headers=h | dict(headers or {})
        )


@contextmanager
def api_env(
    server: PgServer, tmp: Path, clock: Clock | None = None
) -> Iterator[ApiEnv]:
    clock = clock or Clock()
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=10, connect_timeout_s=5
    )
    db.open()
    sink = RecordingSink()
    shipper = Shipper(
        PgAuditTail(db), DiskQueue(tmp / "q"), sink, clock, DbOutageAudit(db)
    )
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=shipper,
        limits=RateLimiter(clock),
    )
    env = ApiEnv(server, clock, db, sink, shipper, create_app(rt))
    try:
        yield env
    finally:
        for c in env._clients.values():
            c.close()
        db.close()


def alerts_total(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


def results_total(result: str) -> float | None:
    return REGISTRY.get_sample_value("bitscan_plugin_results_total", {"result": result})
