"""TASK-199 TEST: result intake ``accept_results()`` on PostgreSQL as
bitscan_app (TP-M9-12; CHK-M9-163 to -169, -171 to -175; mutation rows
CHK-M9-320 to -334, -374, -375 service side).

Expected values: TS §6.1 L1071 (accepted only for the agent's own job,
within dispatched_at + 7 days, for plugin ids in the job; anything else 409;
a second result for a plugin is ignored), §4.4 L568–L570, L575, L578, L581,
L582 (states, deadline, first result wins, cancel, final states), §4.5
L587, L596, L599, L603 (verdict against the queued eval_spec in one insert;
caps 64 KB stdout / 16 KB stderr → ERROR oversize; snapshots), §3.3 L222
(the start notice), §8.4 L1288; #12, #116 (d), #121, #124 (a)–(h),
#127 (a)–(c), #129 (c); SR §1.1. Verdicts are written by hand from SR §2.4
and TS §4.5 for each case, not taken from the evaluator.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import job_intake
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.evaluator.eval_spec import parse_eval_spec
from bitscan_manager.services.evaluator.verdict import result_verdict
from bitscan_manager.services.jobs.intake import Accepted, Refused, accept_results

from . import scan_pg_fixtures as f
from .agent_sim import fixture_body, map_uuids
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=1)
SEVEN = timedelta(days=7)
US = timedelta(microseconds=1)
FFFD = "�"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("intake")) as s:
        yield s


@dataclass
class Env:
    server: PgServer
    db: AppDatabase
    cat: f.Catalog

    def agent(self, status: str = "online") -> UUID:
        with f.app(self.server) as c:
            return f.make_agent(c, status).agent_id

    def job(
        self,
        pol: f.Pol,
        *,
        state: str = "dispatched",
        agent: UUID | None = None,
        plugins: list[f.PluginDef] | None = None,
        retry_of: f.JobRow | None = None,
        **kw: Any,
    ) -> f.JobRow:
        a = agent or (retry_of.agent_id if retry_of else self.agent())
        with f.owner(self.server) as o:
            sid = (
                retry_of.scan_id
                if retry_of is not None
                else f.owner_scan(o, pol, state="running")
            )
            assert sid is not None
            return f.owner_job(
                o,
                sid,
                a,
                pol,
                plugins,
                state=state,
                retry_of=None if retry_of is None else retry_of.job_id,
                **kw,
            )

    def post(
        self,
        job: f.JobRow,
        items: list[dict[str, Any]],
        *,
        final: bool = False,
        now: datetime = NOW,
        agent: UUID | None = None,
    ) -> Accepted | Refused:
        batch = schemas.ResultsRequest.model_validate(
            {"results": items, "final": final}
        )
        return accept_results(
            self.db,
            agent_id=agent or job.agent_id,
            job_id=job.job_id,
            batch=batch,
            now=now,
        )

    def state(self, job: f.JobRow) -> dict[str, Any]:
        with f.app(self.server) as c:
            return f.job_state(c, job.job_id)

    def results(self, *jobs: f.JobRow) -> list[dict[str, Any]]:
        with f.app(self.server) as c:
            return f.results_of(c, [j.job_id for j in jobs])


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    with f.app_database(server) as db:
        yield Env(server, db, f.make_catalog(db, f.Clock(), tmp_path))


def it(p: f.PluginDef | UUID, **over: Any) -> dict[str, Any]:
    uid = p if isinstance(p, UUID) else p.plugin_uuid
    return {
        "plugin_uuid": str(uid),
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "started_at": f.iso(NOW - timedelta(seconds=30)),
        "finished_at": f.iso(NOW - timedelta(seconds=20)),
        "timed_out": False,
        "truncated": False,
        "error": None,
    } | over


def counter(label: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_plugin_results_total", {"result": label})
    assert v is not None, f"bitscan_plugin_results_total{{result={label!r}}} missing"
    return v


def counters() -> dict[str, float]:
    return {k: counter(k) for k in ("PASS", "FAIL", "ERROR")}


# ------------------------------------------------------------ CHK-M9-163


def test_refusals_store_nothing_and_change_no_job(env: Env) -> None:
    """REQ-214 (1), #124 (a), (f), (h), CHK-M9-324, -325, -328: each case is
    Refused("job_not_acceptable") (eval_spec: "eval_spec_invalid"), stores
    no row and leaves the job byte-identical; own_cancelled is True only for
    the agent's own cancelled job."""
    pol = env.cat.policy(50)
    a = env.agent()
    other = env.agent()
    with f.owner(env.server) as o:
        inv = f.owner_inventory_job(
            o, a, state="dispatched", created_at=NOW - timedelta(minutes=5)
        )
    cases: list[
        tuple[str, f.JobRow, UUID, datetime, list[dict[str, Any]], str, bool]
    ] = []
    good = [it(p) for p in pol.plugins[:2]]
    d = env.job(pol, agent=a)
    cases.append(("other agent", d, other, NOW, good, "job_not_acceptable", False))
    for st in ("queued", "expired"):
        cases.append(
            (
                st,
                env.job(pol, state=st, agent=a),
                a,
                NOW,
                good,
                "job_not_acceptable",
                False,
            )
        )
    cancelled_d = env.job(pol, state="cancelled", agent=a)
    cancelled_r = env.job(
        pol, state="cancelled", agent=a, started_at=f.T0 + timedelta(minutes=2)
    )
    cases.append(
        (
            "cancelled while dispatched",
            cancelled_d,
            a,
            NOW,
            good,
            "job_not_acceptable",
            True,
        )
    )
    cases.append(
        (
            "cancelled while running",
            cancelled_r,
            a,
            NOW,
            good,
            "job_not_acceptable",
            True,
        )
    )
    cases.append(
        (
            "cancelled, other agent",
            cancelled_d,
            other,
            NOW,
            good,
            "job_not_acceptable",
            False,
        )
    )
    late = env.job(pol, agent=a)
    late_at = f.T0 + timedelta(minutes=1) + SEVEN + timedelta(seconds=1)
    cases.append(("7 days + 1 s", late, a, late_at, good, "job_not_acceptable", False))
    late_us = env.job(pol, agent=a)
    cases.append(
        (
            "7 days + 1 µs",
            late_us,
            a,
            f.T0 + timedelta(minutes=1) + SEVEN + US,
            good,
            "job_not_acceptable",
            False,
        )
    )
    foreign = env.job(pol, agent=a)
    batch50 = [it(p) for p in pol.plugins[:49]] + [it(uuid4())]
    cases.append(
        ("49 + 1 foreign", foreign, a, NOW, batch50, "job_not_acceptable", False)
    )
    sub = env.job(pol, agent=a, plugins=pol.plugins[:3])
    outside = [it(pol.plugins[0]), it(pol.plugins[10])]  # catalog plugin, not in job
    cases.append(
        (
            "plugin of the policy, not of the job",
            sub,
            a,
            NOW,
            outside,
            "job_not_acceptable",
            False,
        )
    )
    bad_spec = env.job(pol, agent=a, eval_spec={"plugins": [{"plugin_uuid": "x"}]})
    cases.append(
        ("eval_spec unreadable", bad_spec, a, NOW, good, "eval_spec_invalid", False)
    )
    for label, job, agent, now, items, reason, own in cases:
        before = env.state(job)
        got = env.post(job, items, final=True, now=now, agent=agent)
        assert got == Refused(reason, own), label  # type: ignore[arg-type]
        assert env.state(job) == before, label
        assert env.results(job) == [], label
    unknown = f.JobRow(uuid4(), None, a, NOW, (), {}, None)
    assert env.post(unknown, good) == Refused("job_not_acceptable", False)
    inv_row = f.JobRow(inv, None, a, NOW, (), {}, None)
    with f.app(env.server) as c:
        inv_before = f.job_state(c, inv)
    assert env.post(inv_row, good, final=True) == Refused("job_not_acceptable", False)
    with f.app(env.server) as c:
        assert f.job_state(c, inv) == inv_before
        assert f.results_of(c, [inv]) == []


# ------------------------------------------------------------ CHK-M9-164


@pytest.mark.parametrize(
    "state", ["dispatched", "running", "failed", "partial", "completed"]
)
def test_accepting_states_answer_counts(env: Env, state: str) -> None:
    """REQ-214 (2), #124 (a), (b): accepted + duplicates = items."""
    pol = env.cat.policy(3)
    job = env.job(pol, state=state)
    got = env.post(job, [it(pol.plugins[0]), it(pol.plugins[0])])
    assert got == Accepted(1, 1)


def test_the_seven_day_window_is_inclusive_and_runs_from_dispatch(env: Env) -> None:
    """REQ-214 (3), TS §6.1 L1071, CHK-M9-326, -327: dispatched_at + 7 days
    exactly is accepted; a job created 10 days ago but dispatched 6 days ago
    is accepted (the window is from dispatched_at, not created_at)."""
    pol = env.cat.policy(2)
    edge = env.job(pol, state="failed")
    at = f.T0 + timedelta(minutes=1) + SEVEN
    assert env.post(edge, [it(pol.plugins[0])], now=at) == Accepted(1, 0)
    old = env.job(
        pol,
        state="failed",
        created_at=NOW - timedelta(days=10),
        dispatched_at=NOW - timedelta(days=6),
    )
    assert env.post(old, [it(pol.plugins[0])]) == Accepted(1, 0)


# ------------------------------------------------------------ CHK-M9-165


@pytest.mark.parametrize("where", ["set_state", "start"])
def test_a_fault_after_the_insert_leaves_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """REQ-214 (6), REQ-226 (2): a fault after the result INSERT rolls the
    whole batch back: no row, the job unchanged, no counter increment."""
    pol = env.cat.policy(2)
    job = env.job(pol, state="dispatched" if where == "start" else "running")
    before = env.state(job)
    counts = counters()

    def boom(*a: Any, **k: Any) -> bool:
        raise RuntimeError("injected fault")

    monkeypatch.setattr(job_intake, where, boom)
    with pytest.raises(RuntimeError, match="injected fault"):
        env.post(job, [it(p) for p in pol.plugins], final=True)
    monkeypatch.undo()
    assert env.state(job) == before
    assert env.results(job) == []
    assert counters() == counts


# ------------------------------------------------------------ CHK-M9-166


def test_rows_carry_the_queued_spec_payload_command_and_manager_clock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-215 (1), TS §4.5 L587, L603, CHK-M9-329, -332, -333: one INSERT per
    batch; each row's verdict is result_verdict(entry, item) and the hand
    verdict; name, operator, expected snapshots come from the job's
    eval_spec and execute from its payload (both deliberately different
    from the catalog row); job_created_at = scan_job.created_at;
    received_at = the manager's now, not the item's finished_at; exit_code,
    timed_out, truncated, started_at, finished_at as sent."""
    pol = env.cat.policy(
        [f.plugin(), f.plugin(), f.plugin(operator="regex", expected="^a")]
    )
    queued = [
        f.PluginDef(p.plugin_uuid, f"queued {i}", f"echo queued-{i}", op, exp, 11)
        for i, (p, op, exp) in enumerate(
            zip(
                pol.plugins,
                ["equals", "contains", "ge"],
                ["yes", "es", "10"],
                strict=True,
            )
        )
    ]
    spec = {
        "plugins": [
            {
                "plugin_uuid": str(q.plugin_uuid),
                "name": f"Fam Q - {q.name}",
                "operator": q.operator,
                "expected": q.expected,
            }
            for q in queued
        ]
    }
    job = env.job(pol, plugins=queued, eval_spec=spec, state="running")
    items = [
        it(queued[0], stdout="yes\r\n", exit_code=3),  # PASS (CRLF, trim; exit ignored)
        it(queued[1], stdout="no", exit_code=0),  # FAIL
        it(queued[2], stdout="abc", exit_code=0, truncated=True),  # ERROR truncated
    ]
    spy = f.StatementSpy()
    spy.install(monkeypatch)
    got = env.post(job, items, now=NOW)
    inserts = [s for s in spy.statements if s.lstrip().upper().startswith("INSERT")]
    monkeypatch.undo()
    assert got == Accepted(3, 0)
    assert len(inserts) == 1 and "scan_result" in inserts[0]
    rows = {r["plugin_uuid"]: r for r in env.results(job)}
    parsed = parse_eval_spec(spec)
    batch = schemas.ResultsRequest.model_validate({"results": items, "final": False})
    for q, item, code in zip(queued, batch.results, (0, 1, 2), strict=True):
        r = rows[q.plugin_uuid]
        want = result_verdict(parsed.get(q.plugin_uuid), item)  # type: ignore[arg-type]
        assert (r["eval_code"], r["eval_detail"]) == (
            want.code,
            None if want.detail is None else want.detail.value,
        )
        assert r["eval_code"] == code
        assert (r["plugin_name_snap"], r["operator_snap"], r["expected_snap"]) == (
            f"Fam Q - {q.name}",
            q.operator,
            q.expected,
        )
        assert r["execute_snap"] == q.execute
        assert r["job_created_at"] == job.created_at
        assert r["received_at"] == NOW != item.finished_at
        assert (r["exit_code"], r["timed_out"], r["truncated"]) == (
            item.exit_code,
            item.timed_out,
            item.truncated,
        )
        assert (r["started_at"], r["finished_at"]) == (
            item.started_at,
            item.finished_at,
        )
        assert r["stdout"] == item.stdout and r["stderr"] == item.stderr


# ------------------------------------------------------------ CHK-M9-167


def test_caps_are_measured_in_utf8_bytes_and_oversize_streams_are_empty(
    env: Env,
) -> None:
    """REQ-215 (2), TS §4.5 L599, #116 (d), CHK-M9-330: stdout of 65,536
    UTF-8 bytes (32,768 × é) is stored as sent; 65,537 is ERROR oversize with
    stdout and stderr ''; stderr 16,384 bytes kept, 16,385 oversize."""
    pol = env.cat.policy([f.plugin(operator="not_empty") for _ in range(4)])
    job = env.job(pol, state="running")
    p = pol.plugins
    out_ok = "é" * 32_768
    out_big = out_ok + "a"
    err_ok = "e" * 16_384
    items = [
        it(p[0], stdout=out_ok, stderr="kept"),
        it(p[1], stdout=out_big, stderr="dropped " + f.CANARY),
        it(p[2], stdout="x", stderr=err_ok),
        it(p[3], stdout="x", stderr=err_ok + "e"),
    ]
    assert env.post(job, items) == Accepted(4, 0)
    rows = {r["plugin_uuid"]: r for r in env.results(job)}
    assert (rows[p[0].plugin_uuid]["result"], rows[p[0].plugin_uuid]["stdout"]) == (
        "PASS",
        out_ok,
    )
    assert rows[p[0].plugin_uuid]["stderr"] == "kept"
    for i in (1, 3):
        r = rows[p[i].plugin_uuid]
        assert (r["result"], r["eval_detail"], r["stdout"], r["stderr"]) == (
            "ERROR",
            "oversize",
            "",
            "",
        )
    assert rows[p[2].plugin_uuid]["stderr"] == err_ok
    assert rows[p[2].plugin_uuid]["result"] == "PASS"


def test_runner_errors_from_the_shared_fixture_are_error_with_their_detail(
    env: Env,
) -> None:
    """REQ-215 (3), #12, #74, TS §4.5 L587: the error_cases fixture (timed out,
    spool_overflow, runner_unavailable — the 0.1.0 agent's answer) mapped
    onto three distinct plugins: ERROR with 'timed out', 'spool_overflow' and
    'runner_unavailable' details."""
    pol = env.cat.policy([f.plugin(operator="empty") for _ in range(3)])
    job = env.job(pol, state="running")
    body = map_uuids(fixture_body("request_valid_error_cases"), pol.uuids)
    assert env.post(job, body["results"], final=body["final"]) == Accepted(3, 0)
    rows = {r["plugin_uuid"]: r for r in env.results(job)}
    details = [rows[u]["eval_detail"] for u in pol.uuids]
    assert [rows[u]["result"] for u in pol.uuids] == ["ERROR"] * 3
    assert details[1:] == ["spool_overflow", "runner_unavailable"]
    assert details[0] is not None and "time" in details[0]


def test_nul_and_lone_surrogates_are_stored_as_fffd_and_evaluated_as_stored(
    env: Env,
) -> None:
    """REQ-215 (4), #121, CHK-M9-331: the shared NUL fixture is accepted; the
    stored stdout is 'a\\ufffdb' and stderr '\\ufffd'; the verdict compares
    the stored text (expected 'a\\ufffdb' → PASS, which a NUL compare would
    FAIL). A lone surrogate parsed by json.loads is stored the same way."""
    pol = env.cat.policy([f.plugin(expected="a�b"), f.plugin(expected="x�y")])
    job = env.job(pol, state="running")
    body = map_uuids(
        fixture_body("request_valid_nul_in_stdout_and_stderr"), pol.uuids[:1]
    )
    assert body["results"][0]["stdout"] == "a\x00b"
    lone = json.loads('{"s": "x\\ud800y"}')["s"]
    items = [body["results"][0], it(pol.plugins[1], stdout=lone, stderr="\udfff")]
    assert env.post(job, items) == Accepted(2, 0)
    rows = {r["plugin_uuid"]: r for r in env.results(job)}
    a, b = rows[pol.uuids[0]], rows[pol.uuids[1]]
    assert (a["stdout"], a["stderr"], a["result"]) == ("a" + FFFD + "b", FFFD, "PASS")
    assert (b["stdout"], b["stderr"], b["result"]) == ("x" + FFFD + "y", FFFD, "PASS")


def test_the_sr_canonical_plugin_passes_and_fails_as_sr_says(env: Env) -> None:
    """REQ-215 (6), SR §1.1: 'install ok installed', exit 0 → PASS;
    '' with exit 1 → FAIL; names and snapshots from the queued spec."""
    pol = env.cat.policy([f.sr_plugin()], family=f.SR_FAMILY)
    one, two = env.job(pol, state="running"), env.job(pol, state="running")
    sr = pol.plugins[0]
    assert env.post(
        one, [it(sr, stdout="install ok installed", exit_code=0)]
    ) == Accepted(1, 0)
    assert env.post(two, [it(sr, stdout="", exit_code=1)]) == Accepted(1, 0)
    (r1,), (r2,) = env.results(one), env.results(two)
    assert (r1["result"], r2["result"]) == ("PASS", "FAIL")
    assert (
        r1["plugin_name_snap"]
        == "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed"
    )
    assert (r1["operator_snap"], r1["expected_snap"]) == (
        "equals",
        "install ok installed",
    )


# ------------------------------------------------------------ CHK-M9-168


def test_a_catalog_change_after_queue_does_not_change_the_verdict(env: Env) -> None:
    """REQ-215 (5), TS §8.3 Integration, TS §4.5 L587, §4.1 L530, CHK-M9-329:
    the job is queued from the catalog (payload + eval_spec of version v);
    an import then changes the plugin's ExpectedResult and Execute; the
    result is evaluated against the queued eval_spec (PASS on the old
    expected, which the new one would FAIL) and the snapshots hold the
    queued values."""
    old = f.plugin(expected="before")
    pol = env.cat.policy([old])
    queued = list(pol.plugins)
    job = env.job(pol, plugins=queued, state="running")
    new = f.PluginDef(
        old.plugin_uuid, old.name, "echo changed-command", "equals", "after", 30
    )
    env.cat.reimport(pol, [new])
    with f.app(env.server) as c:
        cur = c.execute(
            "SELECT execute, expected_result FROM plugin WHERE plugin_uuid = %s",
            (old.plugin_uuid,),
        ).fetchone()
    assert cur == ("echo changed-command", "after")
    assert env.post(job, [it(old, stdout="before")]) == Accepted(1, 0)
    (r,) = env.results(job)
    assert r["result"] == "PASS"
    assert (r["expected_snap"], r["execute_snap"]) == ("before", old.execute)


# ------------------------------------------------------------ CHK-M9-169


def test_a_second_result_for_a_plugin_is_a_duplicate_and_changes_nothing(
    env: Env,
) -> None:
    """REQ-216 (1), (5), TS §6.1 L1071: the same plugin twice to one job is
    {0, 1} the second time, the first row unchanged; two items for one
    plugin in one batch: the first (in batch order) is stored."""
    pol = env.cat.policy(2)
    job = env.job(pol, state="running")
    p, q = pol.plugins
    assert env.post(job, [it(p, stdout="first")]) == Accepted(1, 0)
    (row,) = env.results(job)
    assert env.post(
        job, [it(p, stdout="second")], now=NOW + timedelta(minutes=1)
    ) == Accepted(0, 1)
    assert env.results(job) == [row]
    assert env.post(job, [it(q, stdout="one"), it(q, stdout="two")]) == Accepted(1, 1)
    assert {r["plugin_uuid"]: r["stdout"] for r in env.results(job)}[
        q.plugin_uuid
    ] == "one"


@pytest.mark.parametrize("first", ["original", "retry"])
def test_first_result_wins_across_original_and_retry(env: Env, first: str) -> None:
    """REQ-216 (2), TS §4.4 L578, CHK-M9-322: a plugin posted to the original
    and then to its retry (and the reverse) is stored once, from the first
    post; the second post counts it as a duplicate."""
    pol = env.cat.policy(3)
    orig = env.job(pol, state="partial")
    retry = env.job(
        pol,
        state="running",
        plugins=pol.plugins[1:],
        retry_of=orig,
        created_at=f.T0 + timedelta(minutes=50),
    )
    p = pol.plugins[1]
    a, b = (orig, retry) if first == "original" else (retry, orig)
    assert env.post(a, [it(p, stdout=first)]) == Accepted(1, 0)
    assert env.post(
        b, [it(p, stdout="late")], now=NOW + timedelta(minutes=1)
    ) == Accepted(0, 1)
    rows = env.results(orig, retry)
    assert [(r["job_id"], r["stdout"]) for r in rows] == [(a.job_id, first)]


def test_a_completed_original_still_sees_its_retrys_results(env: Env) -> None:
    """REQ-216 (2), TS §4.4 L577, L578, #127 (a): the original failed at its
    deadline and got a retry; the retry stored plugin 2; a late batch to the
    original stored plugin 1, so the original became completed (every plugin
    has a result in the unit). A second late copy of plugin 2 posted to that
    completed original is a duplicate: plugin 2 is stored once in the unit."""
    pol = env.cat.policy(2)
    p1, p2 = pol.plugins
    orig = env.job(pol, state="failed")
    retry = env.job(
        pol, state="running", retry_of=orig, created_at=f.T0 + timedelta(minutes=50)
    )
    assert env.post(retry, [it(p2, stdout="from retry")]) == Accepted(1, 0)
    assert env.post(orig, [it(p1)], now=NOW + timedelta(minutes=1)) == Accepted(1, 0)
    assert env.state(orig)["state"] == "completed"
    got = env.post(orig, [it(p2, stdout="late copy")], now=NOW + timedelta(minutes=2))
    rows = env.results(orig, retry)
    by_plugin = [r["plugin_uuid"] for r in rows]
    assert by_plugin.count(p2.plugin_uuid) == 1, rows
    assert got == Accepted(0, 1)


# ------------------------------------------------------------ CHK-M9-171


def test_the_root_is_locked_before_the_insert(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-216 (4), TS §4.4 L578: posting to a retry, the first FOR UPDATE
    (the root) and the posted job's FOR UPDATE both come before the INSERT."""
    pol = env.cat.policy(2)
    orig = env.job(pol, state="failed")
    retry = env.job(
        pol, state="running", retry_of=orig, created_at=f.T0 + timedelta(minutes=50)
    )
    spy = f.StatementSpy()
    spy.install(monkeypatch)
    env.post(retry, [it(pol.plugins[0])])
    sts = [s.upper() for s in spy.statements]
    monkeypatch.undo()
    ins = next(
        i for i, s in enumerate(sts) if s.lstrip().startswith("INSERT INTO SCAN_RESULT")
    )
    locks = [i for i, s in enumerate(sts) if "FOR UPDATE" in s]
    assert len(locks) >= 2 and max(locks[:2]) < ins, sts


# ------------------------------------------------------------ CHK-M9-172


def test_no_output_or_command_reaches_logs_exceptions_or_audit(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-230 (5), REQ-227 (4), #124 (h), CHK-M9-375: a canary in stdout,
    stderr, execute and expected, through accepted, duplicate, refused,
    oversize and unreadable-eval_spec batches, appears in no log record and
    no audit entry."""
    caplog.set_level(logging.DEBUG)
    p = f.plugin(execute=f"echo {f.CANARY}", expected=f.CANARY)
    pol = env.cat.policy([p])
    with f.app(env.server) as c:
        mark = f.last_audit(c)
    job = env.job(pol, state="running")
    loud = it(p, stdout=f.CANARY, stderr=f.CANARY)
    env.post(job, [loud])
    env.post(job, [loud])
    env.post(job, [it(p, stdout=f.CANARY + "x" * 70_000)])
    env.post(job, [loud, it(uuid4(), stdout=f.CANARY)])
    bad = env.job(pol, state="running", eval_spec={"plugins": f.CANARY})
    env.post(bad, [loud])
    assert f.canary_hits(f.log_texts(caplog.records)) == []
    with f.app(env.server) as c:
        entries = f.audit_after(c, mark)
    assert f.canary_hits([json.dumps(e["detail"]) for e in entries]) == []
    assert any("eval_spec" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------ CHK-M9-173


def test_start_notice_starts_once_with_the_setting_deadline(env: Env) -> None:
    """REQ-217 (1), (2), TS §4.4 L575, §3.3 L222, CHK-M9-334, -335: the
    empty batch on a dispatched job → running, started_at = the manager's
    now, deadline_at = now + ceil(95 / 2) s + 10 min = now + 648 s with
    max_parallel_plugins 2 (the setting at that moment); a second start
    notice changes neither; a first non-empty batch also starts a job."""
    pol = env.cat.policy(
        [f.plugin(timeout_s=30), f.plugin(timeout_s=30), f.plugin(timeout_s=35)]
    )
    job = env.job(pol)
    with f.setting(env.server, "max_parallel_plugins", 2):
        assert env.post(job, [], now=NOW) == Accepted(0, 0)
    st = env.state(job)
    assert (st["state"], st["started_at"], st["deadline_at"]) == (
        "running",
        NOW,
        NOW + timedelta(seconds=648),
    )
    assert st["finished_at"] is None
    with f.setting(env.server, "max_parallel_plugins", 8):
        assert env.post(job, [], now=NOW + timedelta(minutes=3)) == Accepted(0, 0)
    assert env.state(job) == st
    other = env.job(pol)
    with f.setting(env.server, "max_parallel_plugins", 8):
        assert env.post(other, [it(pol.plugins[0])], now=NOW) == Accepted(1, 0)
    st2 = env.state(other)
    assert (st2["state"], st2["started_at"]) == ("running", NOW)
    assert st2["deadline_at"] == NOW + timedelta(seconds=12 + 600)  # ceil(95 / 8)


def test_batch_outcomes_on_a_running_job(env: Env) -> None:
    """REQ-217 (3), #127 (a), CHK-M9-337: a non-final batch with plugins
    missing keeps running; a final batch with plugins missing → partial with
    finished_at; results for every plugin → completed."""
    pol = env.cat.policy(3)
    p = pol.plugins
    keep = env.job(pol, state="running")
    assert env.post(keep, [it(p[0])], final=False) == Accepted(1, 0)
    assert (env.state(keep)["state"], env.state(keep)["finished_at"]) == (
        "running",
        None,
    )
    part = env.job(pol, state="running")
    assert env.post(part, [it(p[0])], final=True) == Accepted(1, 0)
    assert (env.state(part)["state"], env.state(part)["finished_at"]) == (
        "partial",
        NOW,
    )
    full = env.job(pol, state="dispatched")
    assert env.post(full, [it(x) for x in p], final=False) == Accepted(3, 0)
    st = env.state(full)
    assert (st["state"], st["finished_at"], st["started_at"]) == ("completed", NOW, NOW)


# ------------------------------------------------------------ CHK-M9-174


def test_late_results_move_failed_and_partial_and_never_final_states(env: Env) -> None:
    """REQ-217 (4)–(6), TS §4.4 L578, L582, #127 (c), CHK-M9-338: a failed job
    given a non-final batch with 1 of 3 → partial (finished_at = then); the
    other 2 → completed (finished_at moves to then); an empty batch on a
    failed job changes nothing; completed stays completed (duplicates only);
    expired and cancelled are refused and unchanged."""
    pol = env.cat.policy(3)
    p = pol.plugins
    job = env.job(pol, state="failed")
    idle = env.job(pol, state="failed")
    before_idle = env.state(idle)
    t1, t2 = NOW, NOW + timedelta(hours=1)
    assert env.post(idle, [], now=t1) == Accepted(0, 0)
    assert env.state(idle) == before_idle
    assert env.post(job, [it(p[0])], final=False, now=t1) == Accepted(1, 0)
    assert (env.state(job)["state"], env.state(job)["finished_at"]) == ("partial", t1)
    assert env.post(job, [it(p[1]), it(p[2])], final=False, now=t2) == Accepted(2, 0)
    done = env.state(job)
    assert (done["state"], done["finished_at"]) == ("completed", t2)
    assert env.post(job, [it(p[0])], now=t2 + timedelta(minutes=1)) == Accepted(0, 1)
    assert env.post(job, [], now=t2 + timedelta(minutes=2)) == Accepted(0, 0)
    assert env.state(job) == done
    for st in ("expired", "cancelled"):
        j = env.job(pol, state=st)
        b = env.state(j)
        assert isinstance(env.post(j, [it(p[0])]), Refused)
        assert env.state(j) == b


# ------------------------------------------------------------ CHK-M9-175


def test_result_counter_counts_stored_rows_by_verdict_after_commit(env: Env) -> None:
    """REQ-226 (1)–(3), #129 (c), CHK-M9-374: the counter exports exactly the
    labels PASS, FAIL, ERROR; a batch storing 2 PASS, 1 FAIL and 3 ERROR adds
    exactly those; a duplicate batch and a refused batch add nothing."""
    names = {
        tuple(sorted(s.labels.items()))
        for m in REGISTRY.collect()
        if m.name == "bitscan_plugin_results"
        for s in m.samples
        if s.name == "bitscan_plugin_results_total"
    }
    assert names == {(("result", r),) for r in ("PASS", "FAIL", "ERROR")}
    pol = env.cat.policy(6)
    p = pol.plugins
    job = env.job(pol, state="running")
    items = [
        it(p[0]),
        it(p[1]),
        it(p[2], stdout="no"),
        it(p[3], timed_out=True),
        it(p[4], exit_code=127),
        it(p[5], error="spool_overflow"),
    ]
    before = counters()
    assert env.post(job, items, final=True) == Accepted(6, 0)
    after = counters()
    assert {k: after[k] - before[k] for k in after} == {
        "PASS": 2,
        "FAIL": 1,
        "ERROR": 3,
    }
    assert env.post(job, items) == Accepted(0, 6)
    assert isinstance(env.post(job, [it(uuid4())]), Refused)
    assert counters() == after


def test_inventory_jobs_are_never_touched_by_intake(env: Env) -> None:
    """REQ-229 (3), G2: the results path refuses an inventory job id and the
    inventory job keeps its state."""
    a = env.agent()
    with f.owner(env.server) as o:
        inv = f.owner_inventory_job(
            o, a, state="dispatched", created_at=NOW - timedelta(minutes=5)
        )
    row = f.JobRow(inv, None, a, NOW, (), {}, None)
    with f.app(env.server) as c:
        before = f.job_state(c, inv)
    assert env.post(row, [], final=False) == Refused("job_not_acceptable", False)
    with f.app(env.server) as c:
        assert f.job_state(c, inv) == before


def test_sibling_lookup_reads_by_key_for_a_retry(env: Env) -> None:
    """The repository's sibling for a retry is its original (by key)."""
    pol = env.cat.policy(1)
    orig = env.job(pol, state="failed")
    retry = env.job(
        pol, state="running", retry_of=orig, created_at=f.T0 + timedelta(minutes=50)
    )
    with env.db.transaction() as tx:
        j = job_intake.lock_unit(tx.conn, retry.job_id)
        assert j is not None
        assert job_intake.sibling(tx.conn, j) == (orig.job_id, orig.created_at)


def test_a_commit_that_fails_counts_nothing_and_stores_nothing(env: Env) -> None:
    """REQ-226 (2), #129 (c), CHK-M9-374: the counter moves only once the
    batch's transaction commits. Here the transaction fails after the body
    (as a failed COMMIT would): no row, the job unchanged, no increment."""
    from contextlib import contextmanager

    pol = env.cat.policy(2)
    job = env.job(pol, state="running")
    before, counts = env.state(job), counters()

    class FailingCommit:
        def __init__(self, db: AppDatabase) -> None:
            self.db = db

        @contextmanager
        def transaction(self) -> Iterator[Any]:
            with self.db.transaction() as tx:
                yield tx
                raise RuntimeError("commit failed")

        def ping(self) -> bool:
            return True

    batch = schemas.ResultsRequest.model_validate(
        {"results": [it(p) for p in pol.plugins], "final": True}
    )
    with pytest.raises(RuntimeError, match="commit failed"):
        accept_results(
            FailingCommit(env.db),
            agent_id=job.agent_id,
            job_id=job.job_id,
            batch=batch,
            now=NOW,
        )
    assert env.results(job) == [] and env.state(job) == before
    assert counters() == counts
