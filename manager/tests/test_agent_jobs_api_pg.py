"""TASK-204 TEST: the agent job routes for compliance jobs, end to end with
the simulated agent on PostgreSQL (TP-M9-16; CHK-M9-220 to -230; mutation
rows CHK-M9-325, -328, -378 to -380).

Jobs are queued by M9's ``queue_scan`` (as POST /scans does) from a catalog
imported through M7; the agent is simulated from the shared contract
fixtures with a real bsa_ token through ``create_app``'s real routes.
Expected values: TS §6.1 L1064 (pull: up to 10 queued jobs, marked
dispatched), L1065, L1071 (results accepted only for the agent's own job,
within dispatched_at + 7 days, for plugin ids in the job; anything else 409
and audit-logged; second result ignored), L1072 (caps re-checked), §3.3
L203, L214, L222, L224, §6.5 L1165–L1190 (Job, Results and their answer),
§4.4 L567, L578, L581, §4.5 L587, L599, §8.4 L1291 (409 floods); REQ-066,
REQ-213 to REQ-216, REQ-229 (3); #54 (c), #121, #124 (a)–(h).
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.api.request_log import configure_logging
from bitscan_manager.repositories.results import host_counts
from bitscan_manager.services.jobs import queue
from bitscan_manager.services.jobs.targets import parse_target

from . import scan_pg_fixtures as f
from .agent_sim import (
    ApiEnv,
    SimAgent,
    alerts_total,
    api_env,
    batch,
    fixture_body,
    fixture_bytes,
    item,
    map_uuids,
    start_notice,
)
from .conftest import PgServer, own_migrated_server
from .test_contract_agent import OPENAPI, validator

pytestmark = pytest.mark.pg

CAP = 1_572_864  # TS §6.3 L1138: 1.5 MiB after decompression
PULL = "/api/v1/agent/{id}/jobs"
WORDS = ('"eval_spec"', '"operator"', '"expected"', '"expected_result"')


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("agent-jobs")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def cat(env: ApiEnv, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(env.db, env.clock, tmp_path)


def queue_for(
    env: ApiEnv, pol: f.Pol, *agents: SimAgent, at: datetime | None = None
) -> UUID:
    with env.db.transaction() as tx:
        out = queue.queue_scan(
            tx,
            policy_id=pol.policy_id,
            target=parse_target({"agents": [str(a.agent_id) for a in agents]}),
            trigger="manual",
            schedule_id=None,
            requested_by=1,
            actor="user:1",
            via_api_token=False,
            now=at or env.clock.now(),
        )
    return out.scan_id


def job_of(env: ApiEnv, scan_id: UUID, a: SimAgent) -> dict[str, Any]:
    with env.conn() as c:
        (j,) = [x for x in f.jobs_of_scan(c, scan_id) if x["agent_id"] == a.agent_id]
    return j


def tick(env: ApiEnv, seconds: float = 3) -> None:
    """Moves the clock so the 30-per-minute agent limit is never what answers."""
    env.clock.advance(seconds=seconds)


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == type_, body
    return body


def ok(r: Any, accepted: int, duplicates: int) -> None:
    assert r.status_code == 200, (r.status_code, r.text)
    schemas.ResultsResponse.model_validate_json(r.content)
    assert r.json() == {"accepted": accepted, "duplicates": duplicates}


def pull_schema_errors(body: Any) -> list[Any]:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    node = doc["paths"][PULL]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    return list(validator({**doc, **node}).iter_errors(body))


def refused(env: ApiEnv, mark: int) -> list[dict[str, Any]]:
    with env.conn() as c:
        return [
            e for e in f.audit_after(c, mark) if e["action"] == "agent.result_refused"
        ]


def mark_of(env: ApiEnv) -> int:
    with env.conn() as c:
        return f.last_audit(c)


def stored(env: ApiEnv, *job_ids: UUID) -> list[dict[str, Any]]:
    with env.conn() as c:
        return f.results_of(c, list(job_ids))


def state_of(env: ApiEnv, job_id: UUID) -> dict[str, Any]:
    with env.conn() as c:
        return f.job_state(c, job_id)


# ------------------------------------------------------------ CHK-M9-220, -221


def test_pull_returns_compliance_and_inventory_jobs_oldest_first(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-213 (1), (2), TS §6.1 L1064, §3.3 L214, CHK-M9-378, -379: 6
    inventory and 6 compliance jobs queued at interleaved times; the first
    pull returns the 10 oldest in creation order, the second the other 2,
    each dispatched once with dispatched_at = the clock. Each compliance job
    equals its stored payload, validates as ComplianceJob and against the
    pull schema of manager/openapi.json; no answer holds eval_spec, operator
    or expected."""
    a = env.agent()
    base = env.clock.now() - timedelta(hours=2)
    order: list[UUID] = []
    for i in range(12):
        at = base + timedelta(minutes=i)
        if i % 2:
            with f.owner(env.server) as o:
                order.append(f.owner_inventory_job(o, a.agent_id, created_at=at))
        else:
            pol = cat.policy(2)
            order.append(job_of(env, queue_for(env, pol, a, at=at), a)["job_id"])
    r1 = a.pull()
    assert r1.status_code == 200 and not pull_schema_errors(r1.json())
    schemas.JobsResponse.model_validate_json(r1.content)
    first = r1.json()["jobs"]
    assert [UUID(j["job_id"]) for j in first] == order[:10]
    t1 = env.clock.now()
    tick(env, 60)
    r2 = a.pull()
    second = r2.json()["jobs"]
    assert [UUID(j["job_id"]) for j in second] == order[10:]
    for text in (r1.text, r2.text):
        for w in WORDS:
            assert w not in text, w
    for j in first + second:
        row = state_of(env, UUID(j["job_id"]))
        if j["kind"] == "compliance":
            # the stored payload; pickup_by may come back as …00.000000Z, the
            # same instant (ruling 2026-10-23)
            want = dict(row["payload"])
            assert f.parse_ts(j["pickup_by"]) == f.parse_ts(want.pop("pickup_by"))
            assert {k: v for k, v in j.items() if k != "pickup_by"} == want
            schemas.ComplianceJob.model_validate(j)
            assert list(sorted(j)) == sorted(
                [
                    "job_id",
                    "agent_id",
                    "kind",
                    "pickup_by",
                    "plugins",
                    "redaction_patterns",
                ]
            )
        assert row["state"] == "dispatched"
    for jid in order[:10]:
        assert state_of(env, jid)["dispatched_at"] == t1
    tick(env, 60)
    assert a.pull().json() == {"jobs": []}


# ------------------------------------------------------------ CHK-M9-222


def test_cancelled_expired_foreign_and_past_pickup_jobs_are_never_pulled(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-213 (3), TS §4.4 L567, L581: only the agent's own queued jobs with
    pickup_by ahead come back."""
    a, b = env.agent(), env.agent()
    pol = cat.policy(1)
    now = env.clock.now()
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol)
        for st in ("cancelled", "expired"):
            f.owner_job(
                o, s, a.agent_id, pol, state=st, created_at=now - timedelta(hours=1)
            )
        f.owner_job(
            o, s, a.agent_id, pol, created_at=now - timedelta(hours=25), pickup_by=now
        )  # pickup_by not ahead
        theirs = f.owner_job(o, s, b.agent_id, pol, created_at=now - timedelta(hours=1))
        mine = f.owner_job(
            o,
            s,
            a.agent_id,
            pol,
            created_at=now - timedelta(minutes=5),
            pickup_by=now + timedelta(microseconds=1),
        )
    assert [j["job_id"] for j in a.pulled()] == [str(mine.job_id)]
    assert state_of(env, theirs.job_id)["state"] == "queued"


def test_two_concurrent_pulls_never_return_one_compliance_job(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-213 (4): four simultaneous pulls by one agent over 12 compliance
    jobs return each at most once and all of them between them."""
    a = env.agent()
    base = env.clock.now() - timedelta(hours=1)
    ids = {
        job_of(
            env, queue_for(env, cat.policy(1), a, at=base + timedelta(minutes=i)), a
        )["job_id"]
        for i in range(12)
    }
    barrier = threading.Barrier(4, timeout=30)
    got: list[list[str]] = []
    lock = threading.Lock()

    def puller() -> None:
        from fastapi.testclient import TestClient

        client = TestClient(env.app, client=(env.fresh_ip(), 1))
        try:
            barrier.wait()
            r = client.get(
                PULL.replace("{id}", str(a.agent_id)), headers=a.row.headers()
            )
            with lock:
                got.append([j["job_id"] for j in r.json()["jobs"]])
        finally:
            client.close()

    outs = f.run_threads([puller] * 4)
    assert [o.error for o in outs] == [None] * 4
    flat = [UUID(j) for js in got for j in js]
    assert len(flat) == len(set(flat)) and set(flat) == ids


# ------------------------------------------------------------ CHK-M9-224


def test_refusals_through_the_route_are_409_with_one_entry_and_store_nothing(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-214 (1), (2), TS §6.1 L1071, #124 (a), (g), (h), CHK-M9-325, -328:
    unknown, another agent's, an inventory, a queued, an expired, a cancelled
    (while dispatched and while running) job, past dispatched_at + 7 days, a
    50-item batch with one plugin outside the job, and an unreadable
    eval_spec: each 409 job_not_acceptable with no stored row, no job change
    and exactly one agent.result_refused entry (reason, results, final; no
    stdout or stderr)."""
    pol = cat.policy(50)
    a, b = env.agent(), env.agent()
    now = env.clock.now()
    loud = f.CANARY
    good = [item(p.plugin_uuid, stdout=loud, stderr=loud) for p in pol.plugins[:2]]
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")

        def job(state: str, agent: SimAgent = a, **kw: Any) -> f.JobRow:
            return f.owner_job(o, s, agent.agent_id, pol, state=state, **kw)

        cases: list[tuple[str, UUID, list[dict[str, Any]], str]] = [
            ("unknown", uuid4(), good, "job_not_acceptable"),
            ("foreign", job("dispatched", b).job_id, good, "job_not_acceptable"),
            (
                "inventory",
                f.owner_inventory_job(
                    o,
                    a.agent_id,
                    state="dispatched",
                    created_at=now - timedelta(minutes=5),
                ),
                good,
                "job_not_acceptable",
            ),
            ("queued", job("queued").job_id, good, "job_not_acceptable"),
            ("expired", job("expired").job_id, good, "job_not_acceptable"),
            (
                "cancelled-dispatched",
                job("cancelled").job_id,
                good,
                "job_not_acceptable",
            ),
            (
                "cancelled-running",
                job("cancelled", started_at=f.T0).job_id,
                good,
                "job_not_acceptable",
            ),
            (
                "late",
                job("failed", dispatched_at=now - timedelta(days=7, seconds=1)).job_id,
                good,
                "job_not_acceptable",
            ),
            (
                "foreign plugin",
                job("dispatched").job_id,
                [item(p.plugin_uuid) for p in pol.plugins[:49]] + [item(uuid4())],
                "job_not_acceptable",
            ),
            (
                "bad eval_spec",
                job("dispatched", eval_spec={"plugins": []}).job_id,
                good,
                "eval_spec_invalid",
            ),
        ]
    with env.conn() as c:
        jobs_before = f.checksum(c, "scan_job")
    for label, jid, items, reason in cases:
        tick(env)
        m = mark_of(env)
        r = a.post(jid, batch(*items, final=True))
        body = problem(r, 409, "job_not_acceptable")
        assert loud not in r.text and set(body) <= {
            "type",
            "title",
            "status",
            "detail",
            "instance",
        }, label
        (e,) = refused(env, m)
        assert (e["actor"], e["target"]) == (f"agent:{a.agent_id}", f"job:{jid}"), label
        assert e["detail"]["reason"] == reason, label
        assert (e["detail"]["results"], e["detail"]["final"]) == (len(items), True), (
            label
        )
        assert loud not in json.dumps(e["detail"]), label
        assert stored(env, jid) == [], label
    with env.conn() as c:
        assert f.checksum(c, "scan_job") == jobs_before


# ------------------------------------------------------------ CHK-M9-225


@pytest.mark.parametrize(
    "st", ["dispatched", "running", "failed", "partial", "completed"]
)
def test_accepting_states_answer_200_with_the_counts(
    env: ApiEnv, cat: f.Catalog, st: str
) -> None:
    """REQ-214 (2), TS §6.5 L1190: 200 {accepted, duplicates} validating
    ResultsResponse; an item the unit already holds is a duplicate."""
    pol = cat.policy(2)
    a = env.agent()
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a.agent_id, pol, state=st)
        f.owner_result(o, j, pol, pol.plugins[1])
    ok(
        a.post(j.job_id, batch(item(pol.uuids[0]), item(pol.uuids[1]), final=False)),
        1,
        1,
    )


def test_dispatched_plus_seven_days_exactly_is_accepted(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-214 (3), TS §6.1 L1071."""
    pol = cat.policy(1)
    a = env.agent()
    d = env.clock.now() - timedelta(days=7)
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a.agent_id, pol, state="failed", dispatched_at=d)
    ok(a.post(j.job_id, batch(item(pol.uuids[0]))), 1, 0)


# ------------------------------------------------------------ CHK-M9-226


def test_malformed_over_cap_and_gzip_bodies_behave_as_req_066(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-214 (4), REQ-066: a malformed body is 400 (no entry), a body over
    1.5 MiB as sent is 413 too_large (one too_large entry), a gzip body is
    inflated and stored, a gzip body inflating past 1.5 MiB is 413; none
    changes the job or stores a row except the good gzip batch."""
    pol = cat.policy(2)
    a = env.agent()
    jid = job_of(env, queue_for(env, pol, a), a)["job_id"]
    a.pulled()
    tick(env)
    m = mark_of(env)
    problem(
        a.post(jid, content=b'{"results": [], "final": "yes"}'), 400, "invalid_request"
    )
    with env.conn() as c:
        assert f.audit_after(c, m) == []
    raw = json.dumps(batch(item(pol.uuids[0]))).encode()
    tick(env)
    problem(a.post(jid, content=raw + b" " * (CAP + 1 - len(raw))), 413, "too_large")
    assert [e["detail"]["reason"] for e in refused(env, m)] == ["too_large"]
    assert stored(env, jid) == []
    tick(env)
    ok(a.post(jid, batch(item(pol.uuids[0])), gzip_body=True), 1, 0)
    tick(env)
    big = gzip.compress(raw + b" " * (CAP + 1 - len(raw)))
    problem(
        a.post(jid, content=big, headers={"Content-Encoding": "gzip"}), 413, "too_large"
    )
    assert len(stored(env, jid)) == 1


# ------------------------------------------------------------ CHK-M9-227


def test_floods_count_409s_but_not_the_agents_own_cancelled_job(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-214 (5), #54 (c), #124 (f), CHK-M9-380: 21 counted 409s from one
    agent within 10 minutes write one result_409_flood alert (and count it);
    21 409s for the agent's own cancelled job write none, each still with
    its refusal entry."""
    pol = cat.policy(1)
    a, b = env.agent(), env.agent()
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")
        expired = f.owner_job(o, s, a.agent_id, pol, state="expired")
        cancelled = f.owner_job(
            o, s, b.agent_id, pol, state="cancelled", started_at=f.T0
        )
    body = batch(item(pol.uuids[0]))
    m = mark_of(env)
    base = alerts_total("result_409_flood")
    for _ in range(21):
        tick(env, 20)
        problem(b.post(cancelled.job_id, body), 409, "job_not_acceptable")
    for _ in range(21):
        tick(env, 20)
        problem(a.post(expired.job_id, body), 409, "job_not_acceptable")
    with env.conn() as c:
        es = f.audit_after(c, m)
    floods = [e for e in es if e["detail"].get("alert_kind") == "result_409_flood"]
    assert [e["target"] for e in floods] == [f"agent:{a.agent_id}"]
    assert alerts_total("result_409_flood") == base + 1
    assert (
        len(
            [
                e
                for e in es
                if e["action"] == "agent.result_refused"
                and e["actor"] == f"agent:{b.agent_id}"
            ]
        )
        == 21
    )


# ------------------------------------------------------------ CHK-M9-228


def test_simulated_agent_runs_a_scan_end_to_end(env: ApiEnv, cat: f.Catalog) -> None:
    """REQ-213 to -217 end to end: pull → the start notice fixture (job
    running, deadline set) → the one_final fixture for the SR §1.1 plugin
    (PASS, stored with its snapshots) → the job completed; the same post
    again is a duplicate; host_counts counts one PASS."""
    pol = cat.policy([f.sr_plugin()], family=f.SR_FAMILY)
    a = env.agent()
    sid = queue_for(env, pol, a)
    (job,) = a.pulled()
    jid = UUID(job["job_id"])
    tick(env)
    with f.setting(env.server, "max_parallel_plugins", 2):
        ok(a.post(jid, start_notice()), 0, 0)
    st = state_of(env, jid)
    assert (st["state"], st["started_at"]) == ("running", env.clock.now())
    assert st["deadline_at"] == env.clock.now() + timedelta(seconds=15 + 600)  # 30 / 2
    tick(env)
    body = map_uuids(fixture_body("request_valid_one_final"), [pol.uuids[0]])
    ok(a.post(jid, body), 1, 0)
    (r,) = stored(env, jid)
    assert (r["result"], r["stdout"], r["received_at"]) == (
        "PASS",
        "install ok installed",
        env.clock.now(),
    )
    assert (
        r["plugin_name_snap"]
        == "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed"
    )
    assert (r["execute_snap"], r["expected_snap"]) == (
        f.SR_EXECUTE,
        "install ok installed",
    )
    assert state_of(env, jid)["state"] == "completed"
    tick(env)
    ok(a.post(jid, body), 0, 1)
    with env.conn() as c:
        (h,) = host_counts(c, sid)
    assert (h.passed, h.failed, h.errors, h.not_run) == (1, 0, 0, 0)


def test_a_0_1_0_agent_answers_runner_unavailable_and_it_is_error(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-215 (3), #28, #74: the error_cases fixture from an N−1 agent (agent
    version 0.1.0), mapped onto three plugins: three ERROR rows with details
    timed out / spool_overflow / runner_unavailable."""
    pol = cat.policy([f.plugin(operator="empty") for _ in range(3)])
    a = env.agent(version="0.1.0")
    sid = queue_for(env, pol, a)
    (job,) = a.pulled()
    tick(env)
    body = map_uuids(fixture_body("request_valid_error_cases"), pol.uuids)
    ok(a.post(job["job_id"], body), 3, 0)
    rows = {r["plugin_uuid"]: r for r in stored(env, UUID(job["job_id"]))}
    assert [rows[u]["result"] for u in pol.uuids] == ["ERROR"] * 3
    assert [rows[u]["eval_detail"] for u in pol.uuids[1:]] == [
        "spool_overflow",
        "runner_unavailable",
    ]
    assert sid is not None


def test_the_nul_fixture_is_accepted_and_stored_as_fffd(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-215 (4), #121: the shared NUL fixture (bytes as the agent sends
    them) is accepted; stdout 'a\\ufffdb', stderr '\\ufffd'; plain and gzip."""
    pol = cat.policy([f.plugin(expected="a�b")])
    for gz in (False, True):
        a = env.agent()
        queue_for(env, pol, a)
        (job,) = a.pulled()
        tick(env)
        raw = fixture_bytes("request_valid_nul_in_stdout_and_stderr").replace(
            b"3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48", str(pol.uuids[0]).encode()
        )
        ok(a.post(job["job_id"], content=raw, gzip_body=gz), 1, 0)
        (r,) = stored(env, UUID(job["job_id"]))
        assert (r["stdout"], r["stderr"], r["result"]) == ("a�b", "�", "PASS")


def test_a_catalog_change_after_queue_is_not_seen_by_the_verdict(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-215 (5), TS §8.3 Integration "verdict uses the queued eval_spec
    after a catalog change", end to end: queue (expected 'before'), import
    (Execute and ExpectedResult changed), pull, post 'before' → PASS with the
    queued snapshots; the pulled job carries the queued command."""
    old = f.plugin(expected="before")
    pol = cat.policy([old])
    a = env.agent()
    queue_for(env, pol, a)
    cat.reimport(pol, [replace(old, execute="echo after-import", expected="after")])
    (job,) = a.pulled()
    assert job["plugins"][0]["execute"] == old.execute
    tick(env)
    ok(a.post(job["job_id"], batch(item(old.plugin_uuid, stdout="before"))), 1, 0)
    (r,) = stored(env, UUID(job["job_id"]))
    assert (r["result"], r["expected_snap"], r["execute_snap"]) == (
        "PASS",
        "before",
        old.execute,
    )


def test_first_result_wins_through_the_route(env: ApiEnv, cat: f.Catalog) -> None:
    """REQ-216 (1)–(2) through the route: an original that ended partial and
    its retry; a plugin posted to the original then the retry is stored
    once; the reverse order for another plugin likewise."""
    pol = cat.policy(3)
    a = env.agent()
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")
        orig = f.owner_job(o, s, a.agent_id, pol, state="partial")
        retry = f.owner_job(
            o,
            s,
            a.agent_id,
            pol,
            pol.plugins[1:],
            state="running",
            retry_of=orig.job_id,
        )
    p2, p3 = pol.uuids[1], pol.uuids[2]
    for first, second, p in ((orig, retry, p2), (retry, orig, p3)):
        tick(env)
        ok(a.post(first.job_id, batch(item(p))), 1, 0)
        tick(env)
        ok(a.post(second.job_id, batch(item(p))), 0, 1)
    rows = stored(env, orig.job_id, retry.job_id)
    assert sorted((r["job_id"], r["plugin_uuid"]) for r in rows) == sorted(
        [(orig.job_id, p2), (retry.job_id, p3)]
    )


# ------------------------------------------------------------ CHK-M9-229


def test_inventory_and_compliance_job_ids_stay_on_their_routes(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-229 (3), #72 (d): the results route refuses an inventory job id
    (409, the inventory job unchanged); the inventory route refuses a
    compliance job id (409, the compliance job unchanged)."""
    pol = cat.policy(1)
    a = env.agent()
    with f.owner(env.server) as o:
        inv = f.owner_inventory_job(
            o,
            a.agent_id,
            state="dispatched",
            created_at=env.clock.now() - timedelta(minutes=5),
        )
    jid = job_of(env, queue_for(env, pol, a), a)["job_id"]
    a.pulled()
    before_inv, before_c = state_of(env, inv), state_of(env, jid)
    tick(env)
    problem(a.post(inv, batch(item(pol.uuids[0]))), 409, "job_not_acceptable")
    tick(env)
    r = a.client().put(
        f"/api/v1/agent/{a.agent_id}/inventory",
        params={"job_id": str(jid)},
        content=gzip.compress(b"{}"),
        headers=a.row.headers()
        | {"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    problem(r, 409, "job_not_acceptable")
    assert (state_of(env, inv), state_of(env, jid)) == (before_inv, before_c)


# ------------------------------------------------------------ CHK-M9-230


def test_user_tokens_and_other_agents_tokens_are_refused_on_both_routes(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """TS §6 route groups: bsu_ and bsk_ tokens on the agent job routes are
    401; another agent's bsa_ token on this agent's path is 403; nothing is
    dispatched or stored."""
    pol = cat.policy(1)
    a, b = env.agent(), env.agent()
    jid = job_of(env, queue_for(env, pol, a), a)["job_id"]
    _, ses = env.caller("admin", "session")
    _, api = env.caller("admin", "api")
    path_pull = PULL.replace("{id}", str(a.agent_id))
    path_post = f"/api/v1/agent/{a.agent_id}/jobs/{jid}/results"
    for tok in (ses, api):
        h = {"Authorization": f"Bearer {tok}", "X-Bitscan-Machine-Id": a.row.machine_id}
        assert env.client.get(path_pull, headers=h).status_code == 401
        r = env.client.post(
            path_post,
            content=json.dumps(batch(item(pol.uuids[0]))),
            headers=h | {"Content-Type": "application/json"},
        )
        assert r.status_code == 401
    assert b.pull(path_id=str(a.agent_id)).status_code == 403
    assert state_of(env, jid)["state"] == "queued" and stored(env, jid) == []


# ------------------------------------------------------------ canary / logs


def test_no_output_reaches_the_logs_and_the_accept_line_carries_counts(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-230 (5), REQ-087, TS §8.4 L1287, CHK-M9-375: a canary in stdout and
    stderr (accepted, duplicate, refused, gzip) is in no log line; the accept
    line carries agent_id, job_id and the counts only."""
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    stream = io.StringIO()
    configure_logging(stream, logging.DEBUG)
    try:
        pol = cat.policy([f.plugin(execute=f"echo {f.CANARY}", expected=f.CANARY)])
        a = env.agent()
        jid = job_of(env, queue_for(env, pol, a), a)["job_id"]
        a.pulled()
        loud = item(pol.uuids[0], stdout=f.CANARY, stderr=f.CANARY)
        for gz in (False, True):
            tick(env)
            a.post(jid, batch(loud), gzip_body=gz)
        tick(env)
        a.post(jid, batch(loud, item(uuid4(), stdout=f.CANARY)))
    finally:
        for h in list(root.handlers):
            if h not in before[0]:
                root.removeHandler(h)
        root.setLevel(before[1])
    text = stream.getvalue()
    assert f.CANARY not in text
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    acc = [ln for ln in lines if ln.get("message") == "result batch accepted"]
    assert acc and all(
        ln["agent_id"] == str(a.agent_id) and ln["job_id"] == str(jid) for ln in acc
    )
    counts = {(ln.get("accepted"), ln.get("duplicates")) for ln in acc}
    assert counts <= {(1, 0), (0, 1)} and counts, acc
    allowed = {
        "time",
        "level",
        "logger",
        "message",
        "request_id",
        "agent_id",
        "job_id",
        "accepted",
        "duplicates",
    }
    assert all(set(ln) <= allowed for ln in acc), acc
