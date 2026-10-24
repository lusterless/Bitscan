"""TASK-070: /api/v1/enrollment-requests list, approve, reject on PostgreSQL (TP-M3-24).

Checks CHK-M3-220 to CHK-M3-226 of tests/m3/test-plan.md and the mutation rows
CHK-M3-326, -327, -328, -370 and -371. Requests are made through the real
enrol route; tokens are checked through the real heartbeat route. Expected
values come from the spec and the answers, not from the code: TS §3.2
L185-L188 (approve new: enrolled; approve re-enrolment: the existing row is
re-linked, the old token stops working, alert; reject: the request is kept, a
new row is decommissioned, never deleted), L192 (same hostname or machine-id
shown, cloned images), TS §6.2 L1084 (approve and reject need a TOTP session;
API tokens refused), L1114-L1115, TS §5.3 L1051 (refused during a 15-minute
sink outage), TS §8.4 L1290 (re-enrolment approved alerts), #26 (rejected
re-enrolment: existing row unchanged, new token 401 enrollment_rejected), #36
(first inventory job on approval), #48 (403 forbidden, totp_session_required,
totp_enrolment_required, 409 conflict, 404 not_found, 503
audit_sink_unavailable), #64 (a)-(f), #68 (list `?state=pending|decided|all`,
items, decision responses), #71 (enrollment_request.approve / .reject, actor
user:<id>; the re-enrolment approval is one reenrolment_approved alert entry),
REQ-063 (5) (no token or hash in a response), REQ-069 (1)-(6), REQ-077 (6).
Lead ruling 2026-10-23 (#64 (d), (f)): rejecting a new request after its
re-enrolment twin was approved records the rejection only and leaves the agent
and its token alone; approving it re-links the agent to its token (409 only for
an already decided or expired request).
"""

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.services.audit import REGISTRY

from . import test_users_api_pg as users_api
from .conftest import PgServer
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env  # the M2 users-API environment (clock, sink, shipper, admins)

ROUTE = "/api/v1/enrollment-requests"
ENROL = "/api/v1/agent/enroll"
ITEM_KEYS = [
    "request_id",
    "kind",
    "agent_id",
    "hostname",
    "machine_id",
    "os_pretty_name",
    "agent_version",
    "source_ip",
    "requested_at",
    "token_expires_at",
    "decision",
    "decided_by",
    "decided_at",
    "matches",
]
MATCH_KEYS = {"agent_id", "hostname", "machine_id", "status"}
JOB_KEYS = {"job_id", "agent_id", "kind", "pickup_by"}
_ips = iter(range(1, 60_000))


def iso(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Host:
    """One enrolment as the host sees it."""

    agent_id: str
    token: str
    machine_id: str
    status: str
    hostname: str
    ip: str


def fresh_ip() -> str:
    n = next(_ips)
    return f"10.70.{n // 256}.{n % 256}"


def client(e: Env, ip: str | None = None) -> TestClient:
    return TestClient(
        e.client.app, client=(ip or fresh_ip(), 1234), raise_server_exceptions=False
    )


def bse(e: Env, *, auto: bool = False) -> str:
    tok = new_agent_token(AgentTokenKind.ENROLMENT)
    with e.conn() as c:
        c.execute(
            "INSERT INTO enrollment_token (token_hash, max_uses, auto_approve,"
            " expires_at, created_by, created_at) VALUES (%s, 1000, %s, %s, 1, %s)",
            (token_hash(tok), auto, e.clock.now() + timedelta(days=2), e.clock.now()),
        )
    return tok


def enrol(
    e: Env,
    *,
    machine: str | None = None,
    hostname: str | None = None,
    version: str = "1.2.3",
    auto: bool = False,
    pretty: str = "Ubuntu 24.04.1 LTS",
) -> Host:
    body = {
        "hostname": hostname or f"rq-{secrets.token_hex(4)}",
        "machine_id": machine or secrets.token_hex(16),
        "agent_version": version,
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "os_pretty_name": pretty,
    }
    ip = fresh_ip()
    with client(e, ip) as c:
        r = c.post(
            ENROL, json=body, headers={"Authorization": f"Bearer {bse(e, auto=auto)}"}
        )
    assert r.status_code == 200, r.text
    out = r.json()
    return Host(
        out["agent_id"],
        out["agent_token"],
        body["machine_id"],
        out["status"],
        body["hostname"],
        ip,
    )


def beat(e: Env, h: Host, token: str | None = None) -> Any:
    """A real bsa_ call: 200 only when the token passes the check."""
    with client(e) as c:
        return c.post(
            f"/api/v1/agent/{h.agent_id}/heartbeat",
            json={
                "agent_version": "1.2.3",
                "uptime_s": 1,
                "last_pull_at": None,
                "current_job_id": None,
                "spool_bytes": 0,
                "last_error": None,
                "runner_helpers": [],
                "clock": iso(e.clock.now()),
            },
            headers={
                "Authorization": f"Bearer {token or h.token}",
                "X-Bitscan-Machine-Id": h.machine_id,
            },
        )


def agent_row(e: Env, agent_id: str) -> dict[str, Any]:
    with e.conn() as c:
        cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (agent_id,))
        cols = [d.name for d in cur.description or []]
        values = cur.fetchone()
    assert values is not None
    return dict(zip(cols, values, strict=True))


def requests_for(e: Env, agent_id: str) -> list[dict[str, Any]]:
    with e.conn() as c:
        cur = c.execute(
            "SELECT * FROM enrollment_request WHERE agent_id = %s ORDER BY request_id",
            (agent_id,),
        )
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def request_id(e: Env, h: Host) -> int:
    return int(requests_for(e, h.agent_id)[-1]["request_id"])


def jobs_for(e: Env, agent_id: str) -> list[tuple[Any, ...]]:
    with e.conn() as c:
        return c.execute(
            "SELECT job_id, kind, state, payload, pickup_by, created_at FROM scan_job"
            " WHERE agent_id = %s ORDER BY created_at",
            (agent_id,),
        ).fetchall()


def last_audit(e: Env) -> int:
    with e.conn() as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


def audit_after(e: Env, audit_id: int) -> list[tuple[Any, ...]]:
    with e.conn() as c:
        return c.execute(
            "SELECT actor, action, target, detail FROM audit_log WHERE audit_id > %s"
            " ORDER BY audit_id",
            (audit_id,),
        ).fetchall()


def state(e: Env, h: Host) -> tuple[Any, ...]:
    with e.conn() as c:
        audit = c.execute("SELECT count(*), max(audit_id) FROM audit_log").fetchone()
    return (
        agent_row(e, h.agent_id),
        requests_for(e, h.agent_id),
        jobs_for(e, h.agent_id),
        audit,
    )


def decide(e: Env, tok: str, rid: int, verb: str) -> Any:
    return e.call("POST", tok, f"{ROUTE}/{rid}/{verb}")


def alerts_counted(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


def no_secret(text: str, *tokens: str) -> None:
    assert "new_token_hash" not in text and "token_hash" not in text
    for t in tokens:
        assert t not in text and t[4:] not in text
        assert hashlib.sha256(t.encode()).hexdigest() not in text


def item_of(e: Env, tok: str, rid: int, st: str = "all") -> dict[str, Any]:
    """The request's list item, following every page."""
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"state": st, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = e.call("GET", tok, ROUTE, params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        for it in body["items"]:
            if it["request_id"] == rid:
                return dict(it)
        cursor = body["next_cursor"]
        if cursor is None:
            raise AssertionError(f"request {rid} not listed with state={st}")


def listed_ids(e: Env, tok: str, st: str | None) -> set[int]:
    out: set[int] = set()
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 100}
        if st is not None:
            params["state"] = st
        if cursor:
            params["cursor"] = cursor
        body = e.call("GET", tok, ROUTE, params=params).json()
        ids = [it["request_id"] for it in body["items"]]
        assert not (out & set(ids))  # each item once
        out |= set(ids)
        cursor = body["next_cursor"]
        if cursor is None:
            return out


# ------------------------------------------------------------ CHK-M3-220


def test_list_items_have_the_68_fields_and_no_token(env: Env) -> None:
    """REQ-069 (1), #68, REQ-063 (5)."""
    _, tok = env.admin()
    h = enrol(env, pretty="Debian GNU/Linux 12 (bookworm)", version="1.4.0")
    rid = request_id(env, h)
    r = env.call("GET", tok, ROUTE)  # default: pending
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"items", "next_cursor"}
    no_secret(r.text, h.token)
    it = item_of(env, tok, rid, "pending")
    assert list(it) == ITEM_KEYS
    row = requests_for(env, h.agent_id)[-1]
    assert it["kind"] == "new" and it["agent_id"] == h.agent_id
    assert it["hostname"] == h.hostname and it["machine_id"] == h.machine_id
    assert it["os_pretty_name"] == "Debian GNU/Linux 12 (bookworm)"
    assert it["agent_version"] == "1.4.0"
    assert it["source_ip"] == h.ip == str(row["source_ip"])
    assert it["requested_at"] == iso(env.clock.now())
    assert it["token_expires_at"] == iso(env.clock.now() + timedelta(days=365))
    assert (it["decision"], it["decided_by"], it["decided_at"]) == (None, None, None)
    assert it["matches"] == []
    assert isinstance(it["request_id"], int)


def test_matches_show_shared_hostnames_and_cloned_images(env: Env) -> None:
    """REQ-069 (1), TS §3.2 L192: two hosts sharing a hostname see each other;
    a cloned image (a second host with an enrolled host's machine-id) is a
    re-enrolment request of that agent, beside its other requests."""
    _, tok = env.admin()
    shared = f"web-{secrets.token_hex(3)}"
    a = enrol(env, hostname=shared)
    b = enrol(env, hostname=shared)
    ia, ib = (
        item_of(env, tok, request_id(env, a)),
        item_of(env, tok, request_id(env, b)),
    )
    assert [m["agent_id"] for m in ia["matches"]] == [b.agent_id]
    assert [m["agent_id"] for m in ib["matches"]] == [a.agent_id]
    m = ia["matches"][0]
    assert set(m) == MATCH_KEYS
    assert (m["hostname"], m["machine_id"], m["status"]) == (
        shared,
        b.machine_id,
        "awaiting_approval",
    )
    # cloned image: the original is enrolled; the clone presents its machine-id
    orig = enrol(env, auto=True)
    assert orig.status == "enrolled"
    other = enrol(env, hostname=f"clone-{secrets.token_hex(3)}")
    clone = enrol(env, machine=orig.machine_id, hostname=other.hostname)
    assert clone.agent_id == orig.agent_id and clone.status == "awaiting_approval"
    ic = item_of(env, tok, request_id(env, clone))
    assert ic["kind"] == "reenrol" and ic["agent_id"] == orig.agent_id
    assert ic["machine_id"] == orig.machine_id
    # the clone's hostname is also another agent's: that agent is a match
    assert [mm["agent_id"] for mm in ic["matches"]] == [other.agent_id]
    no_secret(json.dumps([ia, ib, ic]), a.token, b.token, clone.token, orig.token)


def test_state_filter_and_paging(env: Env) -> None:
    """#68: ?state=pending (default) | decided | all; {items, next_cursor};
    paging returns each item once."""
    uid, tok = env.admin()
    hosts = [enrol(env) for _ in range(4)]
    rids = [request_id(env, h) for h in hosts]
    assert decide(env, tok, rids[0], "approve").status_code == 200
    assert decide(env, tok, rids[1], "reject").status_code == 200
    pending = listed_ids(env, tok, None)
    assert pending == listed_ids(env, tok, "pending")
    decided = listed_ids(env, tok, "decided")
    every = listed_ids(env, tok, "all")
    assert {rids[2], rids[3]} <= pending and not {rids[0], rids[1]} & pending
    assert {rids[0], rids[1]} <= decided and not {rids[2], rids[3]} & decided
    assert set(rids) <= every and pending | decided == every
    assert not pending & decided
    first = env.call("GET", tok, ROUTE, params={"state": "all", "limit": 1}).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    for bad in ("approved", "", "PENDING"):
        problem(
            env.call("GET", tok, ROUTE, params={"state": bad}), 400, "invalid_request"
        )


def test_list_allows_admin_session_or_api_token_only(env: Env) -> None:
    """REQ-069 (6), TS §6.2 L1114: admin, session or API token."""
    uid, tok = env.admin()
    assert env.call("GET", env.token(uid, "api"), ROUTE).status_code == 200
    assert env.call("GET", tok, ROUTE).status_code == 200
    op, viewer = env.user("operator", totp=True), env.user("viewer", totp=True)
    for cred in (env.token(op), env.token(op, "api"), env.token(viewer)):
        problem(env.call("GET", cred, ROUTE), 403, "forbidden")
    for cred in (new_agent_token(AgentTokenKind.AGENT), bse(env)):
        problem(env.call("GET", cred, ROUTE), 401, "unauthorized")
    problem(env.client.get(ROUTE), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M3-221


def test_approve_new(env: Env) -> None:
    """REQ-069 (2), #36, REQ-077 (6), #71."""
    uid, tok = env.admin()
    h = enrol(env)
    assert h.status == "awaiting_approval"
    problem(beat(env, h), 403, "pending_approval")
    rid = request_id(env, h)
    mark = last_audit(env)
    env.clock.at += timedelta(minutes=3)
    r = decide(env, tok, rid, "approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == ITEM_KEYS
    assert body["decision"] == "approved" and body["decided_by"] == uid
    assert body["decided_at"] == iso(env.clock.now())
    no_secret(r.text, h.token)
    assert agent_row(env, h.agent_id)["status"] == "enrolled"
    jobs = jobs_for(env, h.agent_id)
    assert len(jobs) == 1
    job_id, kind, st, payload, pickup_by, created = jobs[0]
    assert (kind, st) == ("inventory", "queued") and set(payload) == JOB_KEYS
    assert payload["job_id"] == str(job_id) and payload["agent_id"] == h.agent_id
    assert pickup_by == created + timedelta(hours=24)
    entries = audit_after(env, mark)
    assert len(entries) == 1
    actor, action, target, detail = entries[0]
    assert (actor, action, target) == (
        f"user:{uid}",
        "enrollment_request.approve",
        f"enrollment_request:{rid}",
    )
    no_secret(json.dumps(detail), h.token)
    assert beat(env, h).status_code == 200  # the token passes the check now
    assert agent_row(env, h.agent_id)["status"] == "online"


# ------------------------------------------------------------ CHK-M3-222


def give_history(e: Env, agent_id: str) -> None:
    """Tags, os_info and one package, as the app would have written them."""
    now = e.clock.now()
    with e.conn() as c:
        c.execute(
            "INSERT INTO agent_tag (agent_id, tag) VALUES (%s, 'prod'), (%s, 'web')",
            (agent_id, agent_id),
        )
        c.execute(
            "INSERT INTO os_info (agent_id, os_id, os_pretty_name, raw, collected_at)"
            " VALUES (%s, 'ubuntu', 'Ubuntu', '{}', %s)",
            (agent_id, now),
        )
        name = f"pkg-{secrets.token_hex(4)}"
        pid = c.execute(
            "INSERT INTO package (name, version, architecture) VALUES (%s, '1.0',"
            " 'amd64') RETURNING package_id",
            (name,),
        ).fetchone()
        assert pid is not None
        c.execute(
            "INSERT INTO agent_package (agent_id, package_id, status, first_seen_at,"
            " last_seen_at) VALUES (%s, %s, 'install ok installed', %s, %s)",
            (agent_id, pid[0], now, now),
        )


def history(e: Env, agent_id: str) -> tuple[Any, ...]:
    with e.conn() as c:
        return (
            c.execute(
                "SELECT tag FROM agent_tag WHERE agent_id = %s ORDER BY tag",
                (agent_id,),
            ).fetchall(),
            c.execute(
                "SELECT * FROM os_info WHERE agent_id = %s", (agent_id,)
            ).fetchall(),
            c.execute(
                "SELECT * FROM agent_package WHERE agent_id = %s", (agent_id,)
            ).fetchall(),
        )


def test_approve_reenrolment_relinks_the_existing_row(env: Env) -> None:
    """REQ-069 (3), #64 (a)-(c), TS §8.4 L1290, #36."""
    uid, tok = env.admin()
    old = enrol(env, auto=True, version="1.0.0")
    assert beat(env, old).status_code == 200
    give_history(env, old.agent_id)
    with env.conn() as c:  # the first inventory job is done
        c.execute(
            "UPDATE scan_job SET state = 'completed', finished_at = %s"
            " WHERE agent_id = %s",
            (env.clock.now(), old.agent_id),
        )
    hist = history(env, old.agent_id)
    env.clock.at += timedelta(hours=2)
    requested = env.clock.now()
    new = enrol(env, machine=old.machine_id, hostname="renamed-host", version="2.0.0")
    assert new.agent_id == old.agent_id and new.status == "awaiting_approval"
    problem(beat(env, new), 403, "pending_approval")
    assert beat(env, old).status_code == 200  # old token works until approval
    before = agent_row(env, old.agent_id)  # after the old token's last heartbeat
    rid = request_id(env, new)
    mark = last_audit(env)
    counted = alerts_counted("reenrolment_approved")
    env.clock.at += timedelta(hours=1)
    r = decide(env, tok, rid, "approve")
    assert r.status_code == 200, r.text
    no_secret(r.text, old.token, new.token)
    row = agent_row(env, old.agent_id)
    assert row["token_hash"] == token_hash(new.token)
    assert row["token_issued_at"] == requested  # #64 (b): the request's times
    assert row["token_expires_at"] == requested + timedelta(days=365)
    assert row["hostname"] == "renamed-host" and row["agent_version"] == "2.0.0"
    assert row["status"] == "enrolled"
    for col in (
        "token_revoked_at",
        "prev_token_hash",
        "prev_token_expires_at",
        "last_rotation_at",
    ):
        assert row[col] is None, col
    for col in ("machine_id", "enrolled_at", "last_heartbeat_at", "last_inventory_at"):
        assert row[col] == before[col], col  # history kept
    assert history(env, old.agent_id) == hist  # tags, os_info, packages
    entries = audit_after(env, mark)
    assert len(entries) == 1, entries  # one entry: the alert (#71)
    actor, action, target, detail = entries[0]
    assert actor == f"user:{uid}" and target == f"enrollment_request:{rid}"
    assert action == "enrollment_request.approve"
    assert detail["alert"] is True and detail["alert_kind"] == "reenrolment_approved"
    assert alerts_counted("reenrolment_approved") == counted + 1
    problem(beat(env, old), 401, "unauthorized")  # the old token no longer works
    assert beat(env, new).status_code == 200
    jobs = jobs_for(env, old.agent_id)
    assert [j[2] for j in jobs] == ["completed", "queued"]  # #36: one new job


def test_approve_reenrolment_of_a_decommissioned_agent(env: Env) -> None:
    """#64 (c): token_revoked_at and the rotation columns are cleared."""
    _, tok = env.admin()
    old = enrol(env, auto=True)
    now = env.clock.now()
    with env.server.connect(
        "bitscan_migrate"
    ) as oc:  # a rotated, then decommissioned row
        oc.execute("SET ROLE bitscan_owner")
        oc.execute(
            "UPDATE agent SET status = 'decommissioned', token_revoked_at = %s,"
            " prev_token_hash = %s, prev_token_expires_at = %s, last_rotation_at = %s"
            " WHERE agent_id = %s",
            (now, "a" * 64, now, now, old.agent_id),
        )
    problem(beat(env, old), 401, "token_revoked")
    new = enrol(env, machine=old.machine_id)
    assert new.agent_id == old.agent_id
    assert decide(env, tok, request_id(env, new), "approve").status_code == 200
    row = agent_row(env, old.agent_id)
    assert row["status"] == "enrolled"
    for col in (
        "token_revoked_at",
        "prev_token_hash",
        "prev_token_expires_at",
        "last_rotation_at",
    ):
        assert row[col] is None, col
    assert beat(env, new).status_code == 200
    problem(beat(env, old), 401, "unauthorized")


def test_approval_queues_no_second_job_while_one_is_open(env: Env) -> None:
    """#36 with REQ-077 (2): one open inventory job per agent."""
    _, tok = env.admin()
    old = enrol(env, auto=True)  # its first job is still queued
    assert [j[2] for j in jobs_for(env, old.agent_id)] == ["queued"]
    new = enrol(env, machine=old.machine_id)
    assert decide(env, tok, request_id(env, new), "approve").status_code == 200
    assert [j[2] for j in jobs_for(env, old.agent_id)] == ["queued"]


# ------------------------------------------------------------ CHK-M3-223


def test_reject_new_decommissions_and_keeps_the_row(env: Env) -> None:
    """REQ-069 (4), TS §3.2 L188, CHK-M3-370."""
    uid, tok = env.admin()
    h = enrol(env)
    rid = request_id(env, h)
    mark = last_audit(env)
    env.clock.at += timedelta(minutes=1)
    r = decide(env, tok, rid, "reject")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "rejected" and body["decided_by"] == uid
    assert body["decided_at"] == iso(env.clock.now())
    no_secret(r.text, h.token)
    row = agent_row(env, h.agent_id)  # still there
    assert row["status"] == "decommissioned"
    assert row["token_revoked_at"] == env.clock.now()
    assert requests_for(env, h.agent_id)[-1]["decision"] == "rejected"
    problem(beat(env, h), 401, "enrollment_rejected")
    assert jobs_for(env, h.agent_id) == []
    entries = audit_after(env, mark)
    assert [(e[0], e[1], e[2]) for e in entries] == [
        (f"user:{uid}", "enrollment_request.reject", f"enrollment_request:{rid}")
    ]


def test_reject_reenrolment_leaves_the_existing_row_and_token(env: Env) -> None:
    """REQ-069 (4), #26."""
    uid, tok = env.admin()
    old = enrol(env, auto=True)
    assert beat(env, old).status_code == 200
    new = enrol(env, machine=old.machine_id, hostname="evil-twin")
    before = agent_row(env, old.agent_id)
    jobs = jobs_for(env, old.agent_id)
    rid = request_id(env, new)
    mark = last_audit(env)
    r = decide(env, tok, rid, "reject")
    assert r.status_code == 200 and r.json()["decision"] == "rejected"
    assert agent_row(env, old.agent_id) == before
    assert jobs_for(env, old.agent_id) == jobs
    problem(beat(env, new), 401, "enrollment_rejected")
    assert beat(env, old).status_code == 200  # the old token still works
    entries = audit_after(env, mark)
    assert [e[1] for e in entries] == ["enrollment_request.reject"]


# ------------------------------------------------------------ CHK-M3-224


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("approve", "approve"),
        ("approve", "reject"),
        ("reject", "approve"),
        ("reject", "reject"),
    ],
)
def test_a_decided_request_is_409_and_unchanged(
    env: Env, first: str, second: str
) -> None:
    """REQ-069 (5)."""
    _, tok = env.admin()
    h = enrol(env)
    rid = request_id(env, h)
    assert decide(env, tok, rid, first).status_code == 200
    before = state(env, h)
    env.clock.at += timedelta(minutes=1)
    problem(decide(env, tok, rid, second), 409, "conflict")
    assert state(env, h) == before


@pytest.mark.parametrize("verbs", [("approve", "approve"), ("approve", "reject")])
def test_concurrent_decisions_give_one_success(
    env: Env, verbs: tuple[str, str]
) -> None:
    """REQ-069 (5): two decisions at once on one request: exactly one 200."""
    uid, tok = env.admin()
    h = enrol(env)
    rid = request_id(env, h)
    mark = last_audit(env)
    barrier = threading.Barrier(2)
    codes: list[int] = []
    lock = threading.Lock()

    def go(verb: str) -> None:
        with client(env) as c:
            barrier.wait(timeout=30)
            r = c.post(
                f"{ROUTE}/{rid}/{verb}", headers={"Authorization": f"Bearer {tok}"}
            )
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=go, args=(v,)) for v in verbs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(codes) == [200, 409]
    assert len(audit_after(env, mark)) == 1
    decision = requests_for(env, h.agent_id)[-1]["decision"]
    assert decision in ("approved", "rejected")
    assert len(jobs_for(env, h.agent_id)) == (1 if decision == "approved" else 0)


def test_an_expired_request_token_cannot_be_approved(env: Env) -> None:
    """#64 (e): approval refused (409) once now reaches the request's
    token_expires_at; one second before, it is approved."""
    _, tok = env.admin()
    late, ok_ = enrol(env), enrol(env)
    expiry = env.clock.now() + timedelta(minutes=10)
    with env.server.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        for h in (late, ok_):
            oc.execute(
                "UPDATE enrollment_request SET token_expires_at = %s"
                " WHERE agent_id = %s",
                (expiry, h.agent_id),
            )
    env.clock.at = expiry
    before = state(env, late)
    problem(decide(env, tok, request_id(env, late), "approve"), 409, "conflict")
    assert state(env, late) == before
    env.clock.at = expiry - timedelta(seconds=1)
    assert decide(env, tok, request_id(env, ok_), "approve").status_code == 200


def test_unknown_request_is_404(env: Env) -> None:
    _, tok = env.admin()
    for verb in ("approve", "reject"):
        problem(decide(env, tok, 9_000_000_001, verb), 404, "not_found")
    problem(env.call("POST", tok, f"{ROUTE}/abc/approve"), 400, "invalid_request")


# ------------------------------------------------------------ CHK-M3-225


def test_decisions_refuse_api_tokens_unverified_and_lower_roles(env: Env) -> None:
    """REQ-069 (6), TS §6.2 L1084, #48; CHK-M3-326, -327, -371."""
    admin, _ = env.admin()
    h = enrol(env)
    rid = request_id(env, h)
    op, viewer = env.user("operator", totp=True), env.user("viewer", totp=True)
    cases = [
        (env.token(admin, "api"), 403, "totp_session_required"),
        (env.token(admin, "session", verified=False), 403, "totp_enrolment_required"),
        (env.token(op), 403, "forbidden"),
        (env.token(op, "api"), 403, "totp_session_required"),
        (env.token(viewer), 403, "forbidden"),
        (new_agent_token(AgentTokenKind.AGENT), 401, "unauthorized"),
        (bse(env), 401, "unauthorized"),
        (h.token, 401, "unauthorized"),
    ]
    for verb in ("approve", "reject"):
        for cred, status, type_ in cases:
            before = state(env, h)
            problem(decide(env, cred, rid, verb), status, type_)
            assert state(env, h) == before, (verb, type_)
        problem(env.client.post(f"{ROUTE}/{rid}/{verb}"), 401, "unauthorized")
    assert requests_for(env, h.agent_id)[-1]["decision"] is None


def test_decisions_refused_during_the_sink_outage(env: Env) -> None:
    """TS §5.3 L1051, CHK-M3-328: 15 minutes into a sink outage both decisions
    are refused with nothing changed; after the queue drains they work."""
    _, tok = env.admin()
    h = enrol(env)
    rid = request_id(env, h)
    env.sink.up = False
    env.shipper.run_once()
    start = env.clock.now()
    env.clock.at = start + timedelta(minutes=15)
    for verb in ("approve", "reject"):
        before = state(env, h)
        problem(decide(env, tok, rid, verb), 503, "audit_sink_unavailable")
        assert state(env, h) == before
    assert env.call("GET", tok, ROUTE).status_code == 200  # the list is not gated
    env.sink.up = True
    for _ in range(5):
        env.clock.at += timedelta(seconds=31)
        env.shipper.run_once()
    assert env.shipper.refusing() is False
    assert decide(env, tok, rid, "approve").status_code == 200


# ------------------------------------------------- #64 (d), (f) (TASK-070 r1)


def test_reject_new_after_its_reenrolment_twin_was_approved(env: Env) -> None:
    """Lead ruling 2026-10-23: R1 (new) and R2 (reenrol of the same held
    agent); R2 approved; rejecting R1 records the rejection on R1 only, the
    agent and R2's token are untouched."""
    uid, tok = env.admin()
    first = enrol(env)
    second = enrol(env, machine=first.machine_id)
    assert second.agent_id == first.agent_id
    r1, r2 = [int(q["request_id"]) for q in requests_for(env, first.agent_id)]
    kinds = [q["kind"] for q in requests_for(env, first.agent_id)]
    assert kinds == ["new", "reenrol"]
    assert decide(env, tok, r2, "approve").status_code == 200
    assert beat(env, second).status_code == 200
    before = agent_row(env, first.agent_id)
    r = decide(env, tok, r1, "reject")
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "rejected"
    assert agent_row(env, first.agent_id) == before
    assert beat(env, second).status_code == 200  # R2's token still works


def test_approve_new_after_its_reenrolment_twin_was_approved_relinks(env: Env) -> None:
    """Lead ruling 2026-10-23: approving R1 after R2 re-links the agent to
    R1's token (as a re-enrolment approval does)."""
    uid, tok = env.admin()
    first = enrol(env)
    second = enrol(env, machine=first.machine_id)
    r1, r2 = [int(q["request_id"]) for q in requests_for(env, first.agent_id)]
    assert decide(env, tok, r2, "approve").status_code == 200
    r = decide(env, tok, r1, "approve")
    assert r.status_code == 200, r.text
    row = agent_row(env, first.agent_id)
    assert row["token_hash"] == token_hash(first.token)
    assert row["status"] == "enrolled" and row["token_revoked_at"] is None
    assert beat(env, first).status_code == 200
    problem(beat(env, second), 401, "unauthorized")


def test_tokens_issued_for_requests_are_never_in_a_response(
    env: Env, migrated_db: PgServer
) -> None:
    """REQ-063 (5): no response of the three routes holds a token or a hash
    (a sweep of every stored hash against the list response)."""
    _, tok = env.admin()
    hosts = [enrol(env) for _ in range(3)]
    text = env.call("GET", tok, ROUTE, params={"state": "all", "limit": 100}).text
    with psycopg.connect(migrated_db.dsn("bitscan_app"), autocommit=True) as c:
        hashes = [
            r[0]
            for r in c.execute(
                "SELECT new_token_hash FROM enrollment_request UNION"
                " SELECT token_hash FROM agent"
            ).fetchall()
        ]
    assert hashes and not [x for x in hashes if x in text]
    for h in hosts:
        no_secret(text, h.token)
        no_secret(decide(env, tok, request_id(env, h), "reject").text, h.token)
    assert all(UUID(h.agent_id) for h in hosts)
