"""TASK-067: POST /api/v1/agent/enroll through the real app on PostgreSQL (TP-M3-21).

Checks CHK-M3-200 to CHK-M3-208 of tests/m3/test-plan.md and the mutation rows
CHK-M3-322, -324, -337 and -365. Expected values come from the spec and the
answers, not from the code: TS §3.2 L183-L187 (not expired or revoked, source
inside allowed_cidrs, atomic uses < max_uses; agent_id, a bsa_ shown once,
issued_at, expires_at; held unless auto_approve and a new machine-id; a
re-enrolment is always held; held new = awaiting_approval row holding the
hash; held re-enrolment = existing agent_id, hash only in the request), TS §6.1
L1062 (bse_ only), §6.3 L1136 (10 per minute per IP; failed checks 20 per
minute per IP, valid tokens never throttled), §6.5 L1161 (Enrol body), §8.4
L1291 (enrolments per hour), #36 (first inventory job on auto-approval), #55 (c),
(d) (every attempt counts; the TCP peer), #59 (one 401 unauthorized for every
refused or wrong token, counted; 429 not counted), #61 (every successful
enrolment counts, sliding 60 min per token, alert above the setting, once per
token per hour), #64 (f), #71 (agent.enrol detail; alert actor agent:<id>,
lead ruling 2026-10-23), REQ-063 (2), (3), REQ-068 (1)-(7), REQ-065 (2).
Lead rulings 2026-10-23: a held re-enrolment records no source IP on the
existing agent; windows are built once in create_app(); a window is marked
fired only after its alert commits.
"""

import hashlib
import io
import json
import logging
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from bitscan_manager.api.agent import AgentWindows, schemas
from bitscan_manager.api.agent.dependencies import AuthenticatedAgent, current_agent
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
from bitscan_manager.repositories.enrolment import EnrolmentRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import REGISTRY
from bitscan_manager.services.enrolment import enrol as enrol_service
from tests.contract import loader

from .conftest import PgServer
from .test_auth_dependencies import api_routes
from .test_contract_agent import OPENAPI, validator
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ROUTE = "/api/v1/agent/enroll"
BSA = re2.compile(r"^bsa_[A-Za-z0-9_-]{43}$")
RESPONSE_KEYS = ["agent_id", "agent_token", "issued_at", "expires_at", "status"]
JOB_KEYS = {"job_id", "agent_id", "kind", "pickup_by"}
DETAIL_KEYS = {"token_id", "kind", "status", "request_id"}


def iso(at: datetime) -> str:
    """RFC 3339 UTC ending in Z, as the M2 timestamp type writes it."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Env:
    server: PgServer
    clock: Clock
    limits: RateLimiter
    app: FastAPI
    db: AppDatabase
    _ip: int = 0
    restore: list[tuple[str, Any]] = field(default_factory=list)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def fresh_ip(self) -> str:
        """A new source address per call, so the per-IP limits never mix."""
        self._ip += 1
        return f"10.{67 + self._ip // 65536}.{(self._ip // 256) % 256}.{self._ip % 256}"

    def client(self, ip: str | None = None) -> TestClient:
        return TestClient(
            self.app,
            client=(ip or self.fresh_ip(), 1234),
            raise_server_exceptions=False,
        )

    def token(
        self,
        *,
        max_uses: int = 10,
        auto: bool = False,
        cidrs: list[str] | None = None,
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
        uses: int = 0,
        raw: str | None = None,
    ) -> tuple[int, str]:
        tok = raw or new_agent_token(AgentTokenKind.ENROLMENT)
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO enrollment_token (token_hash, max_uses, uses,"
                " auto_approve, allowed_cidrs, expires_at, revoked_at, created_by,"
                " created_at) VALUES (%s, %s, %s, %s, CAST(%s AS cidr[]), %s, %s,"
                " 1, %s)"
                " RETURNING token_id",
                (
                    token_hash(tok),
                    max_uses,
                    uses,
                    auto,
                    cidrs,
                    expires_at or T0 + timedelta(hours=24),
                    revoked_at,
                    T0 - timedelta(hours=1),
                ),
            ).fetchone()
        assert row is not None
        return int(row[0]), tok

    def uses(self, token_id: int) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT uses FROM enrollment_token WHERE token_id = %s", (token_id,)
            ).fetchone()
        assert row is not None
        return int(row[0])

    def setting(self, key: str, value: Any) -> None:
        with self.conn() as c:
            row = c.execute(
                "SELECT value FROM setting WHERE key = %s", (key,)
            ).fetchone()
            assert row is not None
            self.restore.append((key, row[0]))
            c.execute(
                "UPDATE setting SET value = %s WHERE key = %s",
                (psycopg.types.json.Jsonb(value), key),
            )

    def enrol(
        self,
        tok: str | None,
        body: dict[str, Any] | None = None,
        *,
        ip: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        h = dict(headers or {})
        if tok is not None:
            h.setdefault("Authorization", f"Bearer {tok}")
        with self.client(ip) as c:
            return c.post(
                ROUTE, json=body if body is not None else self.body(), headers=h
            )

    @staticmethod
    def body(machine: str | None = None, **over: Any) -> dict[str, Any]:
        return {
            "hostname": f"host-{secrets.token_hex(3)}",
            "machine_id": machine or secrets.token_hex(16),
            "agent_version": "1.2.3",
            "os_id": "ubuntu",
            "os_version_id": "24.04",
            "os_pretty_name": "Ubuntu 24.04.1 LTS",
        } | over

    def agent_row(self, agent_id: UUID | str) -> dict[str, Any]:
        with self.conn() as c:
            cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (str(agent_id),))
            values = cur.fetchone()
            cols = [d.name for d in cur.description or []]
        assert values is not None
        return dict(zip(cols, values, strict=True))

    def requests_for(self, agent_id: UUID | str) -> list[dict[str, Any]]:
        with self.conn() as c:
            cur = c.execute(
                "SELECT * FROM enrollment_request WHERE agent_id = %s"
                " ORDER BY request_id",
                (str(agent_id),),
            )
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def jobs_for(self, agent_id: UUID | str) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT job_id, kind, state, payload, pickup_by, created_at"
                " FROM scan_job WHERE agent_id = %s",
                (str(agent_id),),
            ).fetchall()

    def ips(self, agent_id: UUID | str) -> list[tuple[Any, ...]]:
        with self.conn() as c:
            return c.execute(
                "SELECT host(ip), first_seen_at, last_seen_at FROM agent_ip_seen"
                " WHERE agent_id = %s ORDER BY 1",
                (str(agent_id),),
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

    def snapshot(self) -> tuple[Any, ...]:
        """The "Refused" row snapshot of the test plan's conventions."""
        out: list[Any] = []
        with self.conn() as c:
            for table, order in (
                ("agent", "agent_id"),
                ("agent_ip_seen", "agent_id, ip"),
                ("agent_tag", "agent_id, tag"),
                ("enrollment_token", "token_id"),
                ("enrollment_request", "request_id"),
                ("os_info", "agent_id"),
            ):
                out.append(
                    c.execute(
                        sql.SQL("SELECT * FROM {} ORDER BY {}").format(
                            sql.Identifier(table), sql.SQL(order)
                        )
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
                    "SELECT job_id, agent_id, kind, state FROM scan_job ORDER BY job_id"
                ).fetchall()
            )
            out.append(
                c.execute("SELECT count(*), max(audit_id) FROM audit_log").fetchone()
            )
        return tuple(out)

    def user_token(self, kind: str) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', 'admin', 'enc', 1, %s)"
                " RETURNING user_id",
                (f"e-{secrets.token_hex(4)}", T0),
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

    def probe(self, agent_id: str, token: str, machine: str) -> Any:
        """A bsa_ call through the real agent dependency (no bsa_ route exists
        yet in this wave); answers 200 only for a usable agent token."""
        with self.client() as c:
            return c.post(
                f"/api/v1/agent/{agent_id}/probe",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Bitscan-Machine-Id": machine,
                },
            )


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=25, connect_timeout_s=5
    )
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
        return {"agent_id": str(agent.caller.agent_id)}

    e = Env(migrated_db, clock, limits, app, db)
    yield e
    with e.conn() as c:
        for key, value in reversed(e.restore):
            c.execute(
                "UPDATE setting SET value = %s WHERE key = %s",
                (psycopg.types.json.Jsonb(value), key),
            )
    db.close()


def problem(r: Any, status: int, type_: str) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == type_, r.json()


def failed_counts(env: Env) -> dict[str, int]:
    env.clock.at += timedelta(minutes=1)
    return {d.ip: d.count for d in env.limits.drain()}


def alerts_counted(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


# ------------------------------------------------------------ CHK-M3-200


REFUSED = [
    "expired_now",
    "expired_past",
    "revoked",
    "outside_cidr",
    "exhausted",
    "unknown",
]


@pytest.mark.parametrize("case", REFUSED)
def test_refused_bse_is_one_401_changes_nothing_and_counts(env: Env, case: str) -> None:
    """REQ-068 (1), #59: every refused bse_ gets the same 401 unauthorized,
    changes no row (uses not incremented) and counts as a failed check."""
    cases: dict[str, dict[str, Any]] = {
        "expired_now": {"expires_at": T0},
        "expired_past": {"expires_at": T0 - timedelta(seconds=1)},
        "revoked": {"revoked_at": T0 - timedelta(seconds=1)},
        "outside_cidr": {"cidrs": ["192.0.2.0/24"]},
        "exhausted": {"max_uses": 3, "uses": 3},
        "unknown": {},
    }
    kw = cases[case]
    tid, tok = env.token(auto=True, **kw)
    if case == "unknown":
        tok = new_agent_token(AgentTokenKind.ENROLMENT)  # never stored
    before_uses = env.uses(tid)
    machine = secrets.token_hex(16)
    before = env.snapshot()
    ip = env.fresh_ip()
    r = env.enrol(tok, env.body(machine), ip=ip)
    problem(r, 401, "unauthorized")
    assert tok not in r.text
    assert env.snapshot() == before
    assert env.uses(tid) == before_uses
    assert failed_counts(env).get(ip) == 1


def test_valid_token_one_second_before_expiry_enrols(env: Env) -> None:
    """The boundary of the expired cases above: still valid until expires_at."""
    tid, tok = env.token(expires_at=T0 + timedelta(seconds=1))
    assert env.enrol(tok).status_code == 200
    assert env.uses(tid) == 1


def test_wrong_kinds_and_shapes_are_the_same_401(env: Env) -> None:
    """REQ-062 (2), #59, CHK-M3-322: a bsa_ (of a real agent), bsu_, bsk_, a
    malformed bse_, no header, another scheme, a token only in the query: one
    byte-identical 401 body with every refused bse_; nothing changes; each
    attempt is a failed check. The bsa_ is refused although its hash is also
    planted as a live enrolment token (only the prefix check can refuse it)."""
    live_tid, live = env.token(auto=True)
    bsa = new_agent_token(AgentTokenKind.AGENT)
    planted_tid, _ = env.token(auto=True, raw=bsa)  # its hash is a usable bse_ row
    agent = env.enrol(live, env.body()).json()
    _, revoked = env.token(revoked_at=T0 - timedelta(hours=1))
    headers: list[dict[str, str]] = [
        {},
        {"Authorization": f"Bearer {bsa}"},
        {"Authorization": f"Bearer {agent['agent_token']}"},
        {"Authorization": f"Bearer {env.user_token('session')}"},
        {"Authorization": f"Bearer {env.user_token('api')}"},
        {"Authorization": f"Bearer {live[:-1]}"},
        {"Authorization": f"Bearer {live}x"},
        {"Authorization": f"Basic {live}"},
        {"Authorization": f"Token {live}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {live} {live}"},
        {"Authorization": "Bearer bsx_" + "A" * 43},
        {"Authorization": f"Bearer {revoked}"},
    ]
    before = env.snapshot()
    used = env.uses(live_tid)
    bodies: set[bytes] = set()
    ips: list[str] = []
    for h in headers:
        ip = env.fresh_ip()
        ips.append(ip)
        with env.client(ip) as c:
            r = c.post(ROUTE, json=env.body(), headers=h)
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    ip = env.fresh_ip()
    ips.append(ip)
    with env.client(ip) as c:
        r = c.post(ROUTE, params={"token": live}, json=env.body())
    problem(r, 401, "unauthorized")
    bodies.add(r.content)
    assert len(bodies) == 1
    assert env.snapshot() == before
    assert env.uses(live_tid) == used and env.uses(planted_tid) == 0
    counts = failed_counts(env)
    assert all(counts.get(i) == 1 for i in ips), counts


def test_two_authorization_headers_are_refused(env: Env) -> None:
    tid, tok = env.token(auto=True)
    with env.client() as c:
        r = c.post(
            ROUTE,
            json=env.body(),
            headers=[("Authorization", f"Bearer {tok}")] * 2,
        )
    problem(r, 401, "unauthorized")
    assert env.uses(tid) == 0


def test_non_ip_peer_is_refused_without_use(env: Env) -> None:
    """#55 (d): the source is the TCP peer; a peer that is not an IP address
    cannot be checked against allowed_cidrs, so nothing is used."""
    tid, tok = env.token(auto=True)
    before = env.snapshot()
    with TestClient(
        env.app, client=("testclient", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(ROUTE, json=env.body(), headers={"Authorization": f"Bearer {tok}"})
    problem(r, 401, "unauthorized")
    assert env.snapshot() == before and env.uses(tid) == 0


def test_ip_over_the_failed_limit_valid_bse_still_enrols(env: Env) -> None:
    """TS §6.3 L1136, REQ-065 (3): 20 failed checks from one IP (user-route and
    enrol failures share the count) then a bad bse_ gets 429; a valid bse_
    from that IP is never throttled by it."""
    ip = env.fresh_ip()
    tid, tok = env.token(max_uses=5)
    bad = new_agent_token(AgentTokenKind.ENROLMENT)
    with env.client(ip) as c:
        for _ in range(16):
            r = c.get("/api/v1/api-tokens", headers={"Authorization": f"Bearer {bad}"})
            assert r.status_code == 401
    for _ in range(4):
        problem(env.enrol(bad, ip=ip), 401, "unauthorized")
    r = env.enrol(bad, ip=ip)  # the 21st failed check
    problem(r, 429, "rate_limited")
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    ok = env.enrol(tok, ip=ip)
    assert ok.status_code == 200, ok.text
    assert env.uses(tid) == 1


# ------------------------------------------------------------ CHK-M3-201


def test_twenty_concurrent_enrolments_on_a_five_use_token(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-068 (2), CHK-M3-332 through the API: all 20 transactions are open
    and reach the atomic use together; exactly 5 succeed and uses ends at 5."""
    tid, tok = env.token(max_uses=5)
    barrier = threading.Barrier(20, timeout=60)
    original = EnrolmentRepo.use_token

    def gated(self: EnrolmentRepo, *a: Any, **kw: Any) -> Any:
        barrier.wait()
        return original(self, *a, **kw)

    monkeypatch.setattr(EnrolmentRepo, "use_token", gated)
    machines = [secrets.token_hex(16) for _ in range(20)]
    ips = [env.fresh_ip() for _ in range(20)]
    results: list[Any] = [None] * 20

    def one(i: int) -> None:
        results[i] = env.enrol(tok, env.body(machines[i]), ip=ips[i])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    codes = sorted(r.status_code for r in results)
    assert codes == [200] * 5 + [401] * 15, codes
    assert env.uses(tid) == 5
    won = [r.json() for r in results if r.status_code == 200]
    assert len({w["agent_id"] for w in won}) == 5
    for w in won:
        assert w["status"] == "awaiting_approval"
        assert len(env.requests_for(w["agent_id"])) == 1
    for r in results:
        if r.status_code == 401:
            assert r.json()["type"] == "unauthorized"
    with env.conn() as c:
        row = c.execute(
            "SELECT count(*) FROM agent WHERE machine_id = ANY(%s)", (machines,)
        ).fetchone()
    assert row == (5,)


def test_concurrent_first_enrolments_of_one_machine_id(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan TASK-067 step 5, #64 (f): two first enrolments of one new
    machine-id at once give one agent row; the second is a held re-enrolment
    of it; both uses are counted; never a 500. Two auto-approve tokens: on
    one token the atomic use's row lock already serialises the enrolments."""
    tid, tok = env.token(auto=True)
    tid2, tok2 = env.token(auto=True)
    barrier = threading.Barrier(2, timeout=60)
    from bitscan_manager.repositories.agents import AgentRepo

    original = AgentRepo.find_by_machine_id
    calls = {"n": 0}
    lock_ = threading.Lock()

    def gated(self: AgentRepo, machine_id: str, *, lock: bool = False) -> Any:
        row = original(self, machine_id, lock=lock)
        with lock_:
            calls["n"] += 1
            n = calls["n"]
        if n <= 2:  # each thread's first read: both see "no row" before inserting
            barrier.wait()
        return row

    monkeypatch.setattr(AgentRepo, "find_by_machine_id", gated)
    machine = secrets.token_hex(16)
    ips = [env.fresh_ip(), env.fresh_ip()]
    results: list[Any] = [None, None]

    def one(i: int) -> None:
        results[i] = env.enrol((tok, tok2)[i], env.body(machine), ip=ips[i])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    assert sorted(r.status_code for r in results) == [200, 200], [
        r.text for r in results
    ]
    bodies = [r.json() for r in results]
    assert bodies[0]["agent_id"] == bodies[1]["agent_id"]
    assert sorted(b["status"] for b in bodies) == ["awaiting_approval", "enrolled"]
    assert env.uses(tid) == env.uses(tid2) == 1
    agent_id = bodies[0]["agent_id"]
    row = env.agent_row(agent_id)
    first = next(b for b in bodies if b["status"] == "enrolled")
    second = next(b for b in bodies if b["status"] == "awaiting_approval")
    assert row["status"] == "enrolled"
    assert row["token_hash"] == token_hash(first["agent_token"])
    reqs = env.requests_for(agent_id)
    assert [(q["kind"], q["new_token_hash"]) for q in reqs] == [
        ("reenrol", token_hash(second["agent_token"]))
    ]
    assert len(env.jobs_for(agent_id)) == 1


# ------------------------------------------------------------ CHK-M3-202


def check_response(r: Any, ttl_days: int = 365) -> dict[str, Any]:
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert list(body) == RESPONSE_KEYS
    assert BSA.match(body["agent_token"]), body["agent_token"]
    assert UUID(body["agent_id"]).hex and body["agent_id"] == body["agent_id"].lower()
    assert body["issued_at"] == iso(T0)
    assert body["expires_at"] == iso(T0 + timedelta(days=ttl_days))
    schemas.EnrolResponse.model_validate_json(r.content)
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    node = doc["paths"][ROUTE]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert not list(validator({**doc, **node}).iter_errors(body))
    return body


def test_new_machine_auto_approve(env: Env) -> None:
    """REQ-068 (3), #36, #25 (b): an enrolled agent, no request, one first
    inventory job, the IP recorded; the token is usable at once."""
    tid, tok = env.token(auto=True)
    ip = env.fresh_ip()
    mark = env.last_audit()
    sent = env.body(hostname="web-01.example", os_pretty_name="Debian GNU/Linux 12")
    r = env.enrol(tok, sent, ip=ip)
    body = check_response(r)
    assert body["status"] == "enrolled"
    row = env.agent_row(body["agent_id"])
    assert row["machine_id"] == sent["machine_id"]
    assert row["hostname"] == "web-01.example" and row["agent_version"] == "1.2.3"
    assert row["token_hash"] == token_hash(body["agent_token"])
    assert row["token_hash"] == hashlib.sha256(body["agent_token"].encode()).hexdigest()
    assert (row["token_issued_at"], row["token_expires_at"]) == (
        T0,
        T0 + timedelta(days=365),
    )
    assert row["status"] == "enrolled" and row["enrolled_at"] == T0
    for col in (
        "token_revoked_at",
        "prev_token_hash",
        "prev_token_expires_at",
        "last_rotation_at",
        "last_heartbeat_at",
        "last_inventory_at",
    ):
        assert row[col] is None, col
    assert row["runner_helpers"] == []
    assert str(row["last_seen_ip"]).split("/")[0] == ip
    assert env.ips(body["agent_id"]) == [(ip, T0, T0)]
    assert env.requests_for(body["agent_id"]) == []
    jobs = env.jobs_for(body["agent_id"])
    assert len(jobs) == 1
    job_id, kind, state, payload, pickup_by, created_at = jobs[0]
    assert (kind, state) == ("inventory", "queued")
    assert set(payload) == JOB_KEYS and payload["job_id"] == str(job_id)
    assert payload["agent_id"] == body["agent_id"] and payload["kind"] == "inventory"
    assert pickup_by == created_at + timedelta(hours=24) and created_at == T0
    with env.conn() as c:
        assert c.execute(
            "SELECT count(*) FROM os_info WHERE agent_id = %s", (body["agent_id"],)
        ).fetchone() == (0,)
    assert env.uses(tid) == 1
    entries = env.audit_after(mark)
    assert entries == [
        (
            f"agent:{body['agent_id']}",
            "agent.enrol",
            f"agent:{body['agent_id']}",
            {"token_id": tid, "kind": "new", "status": "enrolled", "request_id": None},
        )
    ]
    ok = env.probe(body["agent_id"], body["agent_token"], sent["machine_id"])
    assert ok.status_code == 200, ok.text


def test_new_machine_held(env: Env) -> None:
    """REQ-068 (3): an awaiting_approval row holding the token hash, one 'new'
    request with the same hash, no job; the token gets 403 pending_approval."""
    tid, tok = env.token()
    ip = env.fresh_ip()
    mark = env.last_audit()
    sent = env.body(os_pretty_name=None, os_id=None, os_version_id=None)
    body = check_response(env.enrol(tok, sent, ip=ip))
    assert body["status"] == "awaiting_approval"
    row = env.agent_row(body["agent_id"])
    digest = token_hash(body["agent_token"])
    assert row["status"] == "awaiting_approval" and row["token_hash"] == digest
    assert (
        row["machine_id"] == sent["machine_id"] and row["hostname"] == sent["hostname"]
    )
    assert row["token_expires_at"] == T0 + timedelta(days=365)
    assert row["token_revoked_at"] is None
    reqs = env.requests_for(body["agent_id"])
    assert len(reqs) == 1
    q = reqs[0]
    assert q["kind"] == "new" and q["enrollment_token_id"] == tid
    assert q["new_token_hash"] == digest
    assert (q["hostname"], q["machine_id"], q["agent_version"]) == (
        sent["hostname"],
        sent["machine_id"],
        "1.2.3",
    )
    assert q["os_pretty_name"] is None
    assert q["token_expires_at"] == T0 + timedelta(days=365)
    assert str(q["source_ip"]).split("/")[0] == ip and q["requested_at"] == T0
    assert (q["decision"], q["decided_by"], q["decided_at"]) == (None, None, None)
    assert env.jobs_for(body["agent_id"]) == []
    assert env.uses(tid) == 1
    assert env.audit_after(mark) == [
        (
            f"agent:{body['agent_id']}",
            "agent.enrol",
            f"agent:{body['agent_id']}",
            {
                "token_id": tid,
                "kind": "new",
                "status": "awaiting_approval",
                "request_id": q["request_id"],
            },
        )
    ]
    problem(
        env.probe(body["agent_id"], body["agent_token"], sent["machine_id"]),
        403,
        "pending_approval",
    )


def plant_known_agent(env: Env, status: str = "online") -> tuple[UUID, str, str]:
    """An existing agent with tags, os_info, an IP, a heartbeat and an
    inventory, so an unchanged row is a real check."""
    tok = new_agent_token(AgentTokenKind.AGENT)
    machine = secrets.token_hex(16)
    with env.conn() as c:
        row = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, last_heartbeat_at,"
            " last_inventory_at, last_seen_ip, runner_helpers, enrolled_at)"
            " VALUES (%s, 'old-host', '0.9.0', %s, %s, %s, %s, %s, %s, '10.66.0.9',"
            " '[\"capread\"]', %s) RETURNING agent_id",
            (
                machine,
                token_hash(tok),
                T0 - timedelta(days=100),
                T0 + timedelta(days=265),
                status,
                T0 - timedelta(minutes=2),
                T0 - timedelta(hours=1),
                T0 - timedelta(days=100),
            ),
        ).fetchone()
        assert row is not None
        agent_id = UUID(str(row[0]))
        c.execute(
            "INSERT INTO agent_tag (agent_id, tag) VALUES (%s, 'prod-web'), (%s, 'db')",
            (agent_id, agent_id),
        )
        c.execute(
            "INSERT INTO os_info (agent_id, os_id, os_pretty_name, raw, collected_at)"
            " VALUES (%s, 'ubuntu', 'Ubuntu 22.04', '{\"k\": \"v\"}', %s)",
            (agent_id, T0 - timedelta(hours=1)),
        )
        c.execute(
            "INSERT INTO agent_ip_seen (agent_id, ip, first_seen_at, last_seen_at)"
            " VALUES (%s, '10.66.0.9', %s, %s)",
            (agent_id, T0 - timedelta(days=100), T0 - timedelta(minutes=2)),
        )
    return agent_id, tok, machine


def known_state(env: Env, agent_id: UUID) -> tuple[Any, ...]:
    with env.conn() as c:
        tags = c.execute(
            "SELECT tag FROM agent_tag WHERE agent_id = %s ORDER BY tag", (agent_id,)
        ).fetchall()
        os_info = c.execute(
            "SELECT * FROM os_info WHERE agent_id = %s", (agent_id,)
        ).fetchall()
    return (
        env.agent_row(agent_id),
        tags,
        os_info,
        env.ips(agent_id),
        env.jobs_for(agent_id),
    )


@pytest.mark.parametrize(
    "auto", [False, True], ids=["held_token", "auto_approve_token"]
)
def test_reenrolment_is_held_and_leaves_the_agent_unchanged(
    env: Env, auto: bool
) -> None:
    """REQ-068 (3), (4), CHK-M3-203, -337, #64; lead ruling 2026-10-23 (2):
    the existing agent_id, a 'reenrol' request holding the new hash, the
    agent row (token, status, tags, os_info, IPs) unchanged and no source IP
    recorded on it; no job; the old token still works, the new one is
    pending."""
    agent_id, old_tok, machine = plant_known_agent(env)
    tid, tok = env.token(auto=auto)
    before = known_state(env, agent_id)
    ip = env.fresh_ip()
    mark = env.last_audit()
    sent = env.body(machine, hostname="new-host", agent_version="2.0.0")
    body = check_response(env.enrol(tok, sent, ip=ip))
    assert body["agent_id"] == str(agent_id)
    assert body["status"] == "awaiting_approval"
    assert known_state(env, agent_id) == before
    reqs = env.requests_for(agent_id)
    assert len(reqs) == 1
    q = reqs[0]
    assert q["kind"] == "reenrol" and q["enrollment_token_id"] == tid
    assert q["new_token_hash"] == token_hash(body["agent_token"])
    assert q["new_token_hash"] != before[0]["token_hash"]
    assert (q["hostname"], q["agent_version"]) == ("new-host", "2.0.0")
    assert q["token_expires_at"] == T0 + timedelta(days=365)
    assert str(q["source_ip"]).split("/")[0] == ip and q["decision"] is None
    assert env.uses(tid) == 1
    entries = env.audit_after(mark)
    assert entries == [
        (
            f"agent:{agent_id}",
            "agent.enrol",
            f"agent:{agent_id}",
            {
                "token_id": tid,
                "kind": "reenrol",
                "status": "awaiting_approval",
                "request_id": q["request_id"],
            },
        )
    ]
    assert env.probe(str(agent_id), old_tok, machine).status_code == 200
    problem(
        env.probe(str(agent_id), body["agent_token"], machine), 403, "pending_approval"
    )


@pytest.mark.parametrize("status", ["awaiting_approval", "decommissioned", "offline"])
def test_reenrolment_of_an_agent_in_any_status(env: Env, status: str) -> None:
    """Plan step 4 ("any status, any token"), #64 (f)."""
    agent_id, _, machine = plant_known_agent(env, status)
    _, tok = env.token(auto=True)
    before = known_state(env, agent_id)
    body = check_response(env.enrol(tok, env.body(machine)))
    assert (body["agent_id"], body["status"]) == (str(agent_id), "awaiting_approval")
    assert known_state(env, agent_id) == before
    assert [q["kind"] for q in env.requests_for(agent_id)] == ["reenrol"]


def test_second_enrolment_while_the_first_is_held(env: Env) -> None:
    """#64 (f): a second enrolment of a machine-id whose first one still
    awaits approval is a 'reenrol' request of that agent row, which keeps the
    first token hash."""
    _, tok = env.token(max_uses=2)
    machine = secrets.token_hex(16)
    first = check_response(env.enrol(tok, env.body(machine)))
    second = check_response(env.enrol(tok, env.body(machine)))
    assert second["agent_id"] == first["agent_id"]
    assert second["status"] == "awaiting_approval"
    row = env.agent_row(first["agent_id"])
    assert row["status"] == "awaiting_approval"
    assert row["token_hash"] == token_hash(first["agent_token"])
    assert [
        (q["kind"], q["new_token_hash"]) for q in env.requests_for(first["agent_id"])
    ] == [
        ("new", token_hash(first["agent_token"])),
        ("reenrol", token_hash(second["agent_token"])),
    ]


@pytest.mark.parametrize("ttl", [60, 730])
def test_token_lifetime_follows_the_setting(env: Env, ttl: int) -> None:
    """REQ-068 (3): token_expires_at = issued_at + agent_token_ttl_days."""
    env.setting("agent_token_ttl_days", ttl)
    _, auto_tok = env.token(auto=True)
    body = check_response(env.enrol(auto_tok), ttl)
    assert env.agent_row(body["agent_id"])["token_expires_at"] == T0 + timedelta(
        days=ttl
    )
    _, held_tok = env.token()
    held = check_response(env.enrol(held_tok), ttl)
    (q,) = env.requests_for(held["agent_id"])
    assert q["token_expires_at"] == T0 + timedelta(days=ttl)


# ------------------------------------------------------------ CHK-M3-204


@pytest.mark.parametrize(
    ("cidrs", "peer", "ok", "stored"),
    [
        (["10.0.0.0/8", "2001:db8::/32"], "10.255.255.255", True, "10.255.255.255"),
        (["10.0.0.0/8", "2001:db8::/32"], "11.0.0.0", False, None),
        (["10.0.0.0/8", "2001:db8::/32"], "2001:db8::5", True, "2001:db8::5"),
        (["10.0.0.0/8", "2001:db8::/32"], "2001:db9::1", False, None),
        (["10.0.0.0/8", "2001:db8::/32"], "::ffff:10.0.0.1", True, "10.0.0.1"),
        (["10.0.0.0/8", "2001:db8::/32"], "::ffff:192.168.0.1", False, None),
        (["2001:db8:1::/48"], "10.0.0.1", False, None),
        (["2001:db8:1::/48"], "2001:db8:1:ffff::1", True, "2001:db8:1:ffff::1"),
        (["192.0.2.7/32"], "192.0.2.7", True, "192.0.2.7"),
        (["192.0.2.7/32"], "192.0.2.8", False, None),
        (None, "2001:db8:ff::1", True, "2001:db8:ff::1"),
        (None, "::ffff:203.0.113.4", True, "203.0.113.4"),
    ],
)
def test_source_cidrs(
    env: Env, cidrs: list[str] | None, peer: str, ok: bool, stored: str | None
) -> None:
    """REQ-068 (5), CHK-M3-062 through the route: IPv4 and IPv6 peers against a
    mixed list; an IPv4-mapped peer is converted to IPv4 before the check
    (plan TASK-067 edge cases); NULL accepts any source."""
    tid, tok = env.token(cidrs=cidrs)
    before = env.snapshot()
    r = env.enrol(tok, ip=peer)
    if not ok:
        problem(r, 401, "unauthorized")
        assert env.snapshot() == before and env.uses(tid) == 0
        return
    body = check_response(r)
    (q,) = env.requests_for(body["agent_id"])
    assert str(q["source_ip"]).split("/")[0] == stored
    assert env.ips(body["agent_id"]) == [(stored, T0, T0)]
    assert env.uses(tid) == 1


def test_scoped_ipv6_peer_enrols_without_its_zone(env: Env) -> None:
    """A link-local IPv6 peer carries a zone id (fe80::1%eth0), which
    PostgreSQL's inet does not accept. Lead ruling 2026-10-23 (TASK-067 r1):
    the zone is dropped, so the peer enrols and fe80::1 is stored (request
    source_ip, agent_ip_seen, last_seen_ip); never a 500. With a CIDR list
    the zone-less address is what is checked."""
    tid, tok = env.token(auto=True)
    with TestClient(
        env.app, client=("fe80::1%eth0", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(ROUTE, json=env.body(), headers={"Authorization": f"Bearer {tok}"})
    body = check_response(r)
    assert str(env.agent_row(body["agent_id"])["last_seen_ip"]).split("/")[0] == (
        "fe80::1"
    )
    assert env.ips(body["agent_id"]) == [("fe80::1", T0, T0)]
    assert env.uses(tid) == 1
    _, held = env.token(cidrs=["fe80::/10"])
    with TestClient(
        env.app, client=("fe80::2%eth0", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(ROUTE, json=env.body(), headers={"Authorization": f"Bearer {held}"})
    (q,) = env.requests_for(check_response(r)["agent_id"])
    assert str(q["source_ip"]).split("/")[0] == "fe80::2"
    tid3, outside = env.token(cidrs=["2001:db8::/32"])
    with TestClient(
        env.app, client=("fe80::3%eth0", 1), raise_server_exceptions=False
    ) as c:
        r = c.post(
            ROUTE, json=env.body(), headers={"Authorization": f"Bearer {outside}"}
        )
    problem(r, 401, "unauthorized")
    assert env.uses(tid3) == 0


# ------------------------------------------------------------ CHK-M3-205


def alert_rows(env: Env, token_id: int, mark: int = 0) -> list[tuple[Any, ...]]:
    return [
        e
        for e in env.audit_after(mark)
        if e[1] == "alert.enrolments_per_hour"
        and e[2] == f"enrollment_token:{token_id}"
    ]


def test_enrolments_per_hour_alert(env: Env) -> None:
    """REQ-068 (6), #61, #71 (lead ruling 2026-10-23: actor agent:<id> of the
    enrolment that crossed the threshold): with the setting at 3 the 4th
    successful enrolment on one token within 60 minutes writes one alert
    entry, the 5th none; held, auto-approved and re-enrolments all count,
    refused attempts do not; another token has its own count; the metric
    moves once, after commit."""
    env.setting("enrolment_alert_per_hour", 3)
    tid, tok = env.token(max_uses=50, cidrs=["10.0.0.0/8"])
    other_tid, other = env.token(max_uses=50)
    machine = secrets.token_hex(16)
    counted = alerts_counted("enrolments_per_hour")
    mark = env.last_audit()
    check_response(env.enrol(tok, env.body(machine)))  # new, held
    check_response(env.enrol(tok, env.body()))
    env.clock.at = T0 + timedelta(minutes=10)
    for _ in range(4):  # refused (outside the CIDRs): never counted
        problem(env.enrol(tok, ip="192.0.2.50"), 401, "unauthorized")
    for _ in range(3):  # another token's enrolments: its own count
        check_response_ok(env.enrol(other))
    env.clock.at = T0 + timedelta(minutes=20)
    third = env.enrol(tok, env.body(machine))  # a re-enrolment counts too
    assert third.status_code == 200
    assert alert_rows(env, tid, mark) == []
    env.clock.at = T0 + timedelta(minutes=59, seconds=59)
    fourth = env.enrol(tok)
    assert fourth.status_code == 200
    rows = alert_rows(env, tid, mark)
    assert len(rows) == 1
    actor, action, target, detail = rows[0]
    assert actor == f"agent:{fourth.json()['agent_id']}"
    assert (action, target) == ("alert.enrolments_per_hour", f"enrollment_token:{tid}")
    assert detail["alert"] is True and detail["alert_kind"] == "enrolments_per_hour"
    assert tok not in json.dumps(detail) and token_hash(tok) not in json.dumps(detail)
    assert alerts_counted("enrolments_per_hour") == counted + 1
    # the 4th enrolment is still its own agent.enrol entry (one entry per event)
    enrol_entries = [e for e in env.audit_after(mark) if e[1] == "agent.enrol"]
    assert len(enrol_entries) == 4 + 3
    assert env.enrol(tok).status_code == 200  # the 5th, same moment: none
    assert len(alert_rows(env, tid, mark)) == 1
    assert alert_rows(env, other_tid, mark) == []
    assert alerts_counted("enrolments_per_hour") == counted + 1


def check_response_ok(r: Any) -> None:
    assert r.status_code == 200, r.text


def test_enrolments_per_hour_window_slides_and_repeats_after_an_hour(env: Env) -> None:
    """#61: a sliding 60 minutes (events older than an hour no longer count),
    at most once per token per hour, again after the hour."""
    env.setting("enrolment_alert_per_hour", 3)
    tid, tok = env.token(max_uses=50)
    mark = env.last_audit()
    for _ in range(3):
        check_response_ok(env.enrol(tok))
    env.clock.at = T0 + timedelta(minutes=60, seconds=1)  # the first 3 aged out
    check_response_ok(env.enrol(tok))
    assert alert_rows(env, tid, mark) == []
    for _ in range(3):  # 4 inside the hour now: alert on the last one
        check_response_ok(env.enrol(tok))
    assert len(alert_rows(env, tid, mark)) == 1
    fired = env.clock.at
    env.clock.at = fired + timedelta(minutes=59)
    for _ in range(5):  # count well above 3, but inside the hour: none
        check_response_ok(env.enrol(tok))
    assert len(alert_rows(env, tid, mark)) == 1
    env.clock.at = fired + timedelta(minutes=60, seconds=1)
    check_response_ok(env.enrol(tok))  # still > 3 in the last 60 min: again
    assert len(alert_rows(env, tid, mark)) == 2


def test_enrolments_per_hour_reads_the_setting_per_call(env: Env) -> None:
    env.setting("enrolment_alert_per_hour", 10)
    tid, tok = env.token(max_uses=50)
    mark = env.last_audit()
    for _ in range(10):
        check_response_ok(env.enrol(tok))
    assert alert_rows(env, tid, mark) == []
    check_response_ok(env.enrol(tok))  # the 11th
    assert len(alert_rows(env, tid, mark)) == 1


def test_rolled_back_alert_leaves_the_hour_free(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lead ruling 2026-10-23 (commit-only "fired"): if the transaction holding
    the alert rolls back, nothing of that enrolment stays (no row, no use, no
    entry, no count) and the next qualifying enrolment alerts; after a
    committed alert none for the hour."""
    env.setting("enrolment_alert_per_hour", 3)
    tid, tok = env.token(max_uses=50)
    for _ in range(3):
        check_response_ok(env.enrol(tok))
    original = enrol_service.enrol
    fail = {"on": True}

    def failing(*a: Any, **kw: Any) -> Any:
        done = original(*a, **kw)
        if fail["on"]:
            raise RuntimeError("forced failure after the alert was written")
        return done

    monkeypatch.setattr(enrol_service, "enrol", failing)
    counted = alerts_counted("enrolments_per_hour")
    mark = env.last_audit()
    before = env.snapshot()
    machine = secrets.token_hex(16)
    r = env.enrol(tok, env.body(machine))
    assert r.status_code == 500
    assert env.snapshot() == before and env.uses(tid) == 3
    assert alert_rows(env, tid, mark) == []
    assert alerts_counted("enrolments_per_hour") == counted
    fail["on"] = False
    check_response_ok(env.enrol(tok, env.body(machine)))
    assert len(alert_rows(env, tid, mark)) == 1
    assert alerts_counted("enrolments_per_hour") == counted + 1
    check_response_ok(env.enrol(tok))
    assert len(alert_rows(env, tid, mark)) == 1


# ------------------------------------------------------------ CHK-M3-206


def test_no_issued_token_at_rest_or_in_the_audit_log(
    env: Env, migrated_db: PgServer
) -> None:
    """REQ-063 (2), (3), REQ-068 (7), CHK-M3-324: the stored hash is the
    SHA-256 of the returned token; no text, char or JSON column of any table
    (read as owner) holds an issued bsa_ or bse_ token or its body."""
    _, auto_tok = env.token(auto=True, max_uses=5)
    _, held_tok = env.token(max_uses=5)
    issued: list[str] = []
    machine = secrets.token_hex(16)
    for tok, body in (
        (auto_tok, env.body(machine)),
        (held_tok, env.body()),
        (held_tok, env.body(machine)),  # re-enrolment
    ):
        r = env.enrol(tok, body)
        assert r.status_code == 200
        assert auto_tok not in r.text and held_tok not in r.text
        issued.append(r.json()["agent_token"])
    secrets_ = [*issued, auto_tok, held_tok]
    needles = [*secrets_, *(t[4:] for t in secrets_)]
    hits: list[str] = []
    with migrated_db.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cols = c.execute(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c"
            " JOIN information_schema.tables t USING (table_schema, table_name)"
            " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
            " AND c.data_type IN ('text', 'character varying', 'character',"
            " 'json', 'jsonb') ORDER BY 1, 2"
        ).fetchall()
        assert ("agent", "token_hash") in cols
        for table, column in cols:
            query = sql.SQL(
                "SELECT count(*) FROM {} WHERE strpos({}::text, %s) > 0"
            ).format(sql.Identifier(table), sql.Identifier(column))
            for needle in needles:
                row = c.execute(query, (needle,)).fetchone()
                if row is not None and row[0]:
                    hits.append(f"{table}.{column}")
        found = c.execute(
            "SELECT (SELECT count(*) FROM agent WHERE token_hash = ANY(%s))"
            " + (SELECT count(*) FROM enrollment_request"
            " WHERE new_token_hash = ANY(%s))",
            ([token_hash(t) for t in issued], [token_hash(t) for t in issued]),
        ).fetchone()
    assert hits == []
    # auto: agent; held: agent and request; re-enrolment: request only
    assert found == (4,)


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


def test_no_token_in_any_log_record(env: Env, logs: io.StringIO) -> None:
    """REQ-087, security invariants: neither the bse_ nor the issued bsa_
    (nor their bodies or hashes) reaches a log record, for an accepted, a
    refused and a malformed enrolment."""
    _, tok = env.token(auto=True)
    issued = env.enrol(tok).json()["agent_token"]
    _, revoked = env.token(revoked_at=T0 - timedelta(hours=1))
    env.enrol(revoked)
    env.enrol(tok, {"hostname": "x"})
    text = logs.getvalue()
    assert text  # the access records were captured
    for secret in (tok, issued, revoked):
        for needle in (secret, secret[4:], token_hash(secret)):
            assert needle not in text


# ------------------------------------------------------------ CHK-M3-207


def test_eleventh_attempt_from_one_ip_is_429(env: Env) -> None:
    """REQ-065 (2), #55 (c), CHK-M3-365: 10 per minute per source IP, every
    attempt counting (successes, refusals and bad bodies); the 11th gets 429
    with Retry-After to the window end before the token or body is looked
    at, and changes nothing; the 429 is not a failed check (#59); another IP
    passes; the next minute passes."""
    env.clock.at = T0 + timedelta(seconds=5)
    ip, other_ip = env.fresh_ip(), env.fresh_ip()
    tid, tok = env.token(max_uses=50)
    bad = new_agent_token(AgentTokenKind.ENROLMENT)
    for _ in range(4):
        check_response_ok(env.enrol(tok, ip=ip))
    for _ in range(3):
        problem(env.enrol(bad, ip=ip), 401, "unauthorized")
    for _ in range(3):
        problem(env.enrol(tok, {"hostname": "x"}, ip=ip), 400, "invalid_request")
    before = env.snapshot()
    used = env.uses(tid)
    for attempt in (tok, bad, None):
        r = env.enrol(attempt, ip=ip)
        problem(r, 429, "rate_limited")
        assert r.headers["Retry-After"] == "55"
    r = env.enrol(tok, {"hostname": "x"}, ip=ip)
    problem(r, 429, "rate_limited")  # before the body is validated
    assert env.snapshot() == before and env.uses(tid) == used
    check_response_ok(env.enrol(tok, ip=other_ip))
    env.clock.at = T0 + timedelta(minutes=1)
    drained = {d.ip: d.count for d in env.limits.drain()}
    assert drained.get(ip) == 3  # the 401s only; 400s and 429s are not counted
    check_response_ok(env.enrol(tok, ip=ip))


# ------------------------------------------------------------ CHK-M3-208


REQUEST_FIXTURES = [fx for fx in loader.select("enrol", "request")]


@pytest.mark.parametrize("fx", REQUEST_FIXTURES, ids=lambda f: f.id)
def test_request_fixtures_through_the_route(env: Env, fx: loader.Fixture) -> None:
    """REQ-060, REQ-061: every valid request fixture enrols (200, a valid
    response), every invalid one is 400 invalid_request with no row change
    and no use of the token (the body is refused before the token is used)."""
    tid, tok = env.token(max_uses=10_000)
    before = env.snapshot()
    with env.client() as c:
        r = c.post(
            ROUTE,
            content=fx.body_bytes(),
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
            },
        )
    if fx.valid:
        body = check_response(r)
        assert body["status"] == "awaiting_approval"
        assert env.uses(tid) == 1
        sent = fx.body()
        q = env.requests_for(body["agent_id"])[-1]
        assert q["hostname"] == sent["hostname"]
        assert q["machine_id"] == sent["machine_id"]
        if sent["os_pretty_name"]:
            assert q["os_pretty_name"] == sent["os_pretty_name"]
    else:
        problem(r, 400, "invalid_request")
        assert env.snapshot() == before and env.uses(tid) == 0


def test_oversized_body_is_413_and_uses_nothing(env: Env) -> None:
    """TS §6.3 L1138: other JSON bodies 1 MB; larger gets 413."""
    tid, tok = env.token()
    with env.client() as c:
        r = c.post(
            ROUTE,
            content=b'{"hostname": "' + b"a" * 1_048_576 + b'"}',
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
            },
        )
    problem(r, 413, "too_large")
    assert env.uses(tid) == 0


# ------------------------------------------------------------ CHK-M3-169 (enrol)


def test_route_walk_enrol_is_the_only_bse_route() -> None:
    """REQ-062 (1): exactly one POST /api/v1/agent/enroll; it carries the bse_
    dependency, not the bsa_ one and no user dependency; every other agent
    operation carries bsa_ (test_agent_auth_pg walk)."""
    app = create_app()
    routes = [r for r in api_routes(app.routes) if r.path.startswith("/api/v1/agent/")]
    enrol = [r for r in routes if r.path == ROUTE]
    assert len(enrol) == 1 and enrol[0].methods == {"POST"}
    marks: set[Any] = set()
    stack = list(enrol[0].dependant.dependencies)
    while stack:
        dep = stack.pop()
        marks.add(getattr(dep.call, "bitscan_agent_auth", None))
        assert getattr(dep.call, "bitscan_auth", None) is None
        stack.extend(dep.dependencies)
    assert "bse_" in marks and "bsa_" not in marks
    for r in routes:
        if r.path != ROUTE:
            top = {
                getattr(d.call, "bitscan_agent_auth", None)
                for d in r.dependant.dependencies
            }
            assert "bse_" not in top, r.path


# ------------------------------------------------------------ windows ruling


def test_windows_are_built_once_per_app(env: Env) -> None:
    """Lead ruling 2026-10-23 (TASK-063 nit): create_app() builds the agent
    windows once; requests reuse them; another app has its own; without
    them enrol answers 503 and uses nothing (never built lazily)."""
    windows = env.app.state.agent_windows
    assert isinstance(windows, AgentWindows)
    _, tok = env.token(max_uses=5)
    check_response_ok(env.enrol(tok))
    problem(env.enrol(new_agent_token(AgentTokenKind.ENROLMENT)), 401, "unauthorized")
    assert env.app.state.agent_windows is windows
    other = create_app(
        Runtime(
            clock=env.clock,
            db=env.db,
            totp_cipher=Cipher(),
            sink_gate=Gate(),
            limits=env.limits,
        )
    )
    assert other.state.agent_windows is not windows
    assert other.state.agent_windows.enrolments is not windows.enrolments
    tid, tok2 = env.token()
    del env.app.state.agent_windows
    problem(env.enrol(tok2), 503, "about:blank")
    assert env.uses(tid) == 0
    assert not hasattr(env.app.state, "agent_windows")
