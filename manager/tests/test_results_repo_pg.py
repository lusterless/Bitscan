"""TP-M8-09: results read repository on PostgreSQL (TASK-182; REQ-197, REQ-198).

As ``bitscan_app``, with scans, jobs, results and re-evaluation rows written
as owner by the TP-M8-01 builder. Expected values: TS §4.5 L601-L602 (latest
re-evaluation row per job and plugin, else the original; score inputs), §4.4
L577-L583 (retries hold the missing plugins; Not run = planned with no result),
§5.2 (no index on ``scan_result_reeval``: read once), #119 (highest reeval_id).
CHK-M8-140 to -142, -150 to -160.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from bitscan_manager.repositories import results
from bitscan_manager.repositories.results import EffectiveRow, HostCounts

from . import evaluator_pg_fixtures as fx
from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]


@dataclass
class World:
    policy: fx.Policy
    scan: UUID
    other_scan: UUID
    agents: dict[str, UUID]
    jobs: dict[str, fx.Job]
    base: int  # reserved reeval_id block
    result_count: int


def build_world(conn: Conn) -> World:
    """Hosts A-E (the REQ-198 (1) shapes) in one scan, plus a second scan."""
    pol = fx.make_policy(conn, [("equals", "x")] * 5)
    p = pol.plugins
    scan = fx.make_scan(conn, pol)
    agents = {k: fx.make_agent(conn) for k in "ABCDE"}
    jobs: dict[str, fx.Job] = {}
    # A: all four kinds: PASS, PASS, FAIL, ERROR, not run
    jobs["A"] = a = fx.make_job(conn, scan, agents["A"], pol, p)
    fx.add_result(conn, a, pol, p[0], code=0, stdout="x")
    fx.add_result(conn, a, pol, p[1], code=0, stdout="x")
    fx.add_result(conn, a, pol, p[2], code=1, stdout="y")
    fx.add_result(conn, a, pol, p[3], code=2, detail="timed out", timed_out=True)
    # B: the original holds p0; its retry (created next month: another
    # partition) holds p1 and p2
    jobs["B"] = b = fx.make_job(conn, scan, agents["B"], pol, p[:3], state="failed")
    fx.add_result(conn, b, pol, p[0], code=0, stdout="x")
    jobs["B2"] = b2 = fx.make_job(
        conn,
        scan,
        agents["B"],
        pol,
        p[1:3],
        retry_of=b.job_id,
        created_at=fx.next_month_start(),
    )
    fx.add_result(conn, b2, pol, p[1], code=1, stdout="y")
    fx.add_result(conn, b2, pol, p[2], code=0, stdout="x")
    # C: still queued, no results
    jobs["C"] = fx.make_job(conn, scan, agents["C"], pol, p[:3], state="queued")
    # D: a FAIL re-evaluated to PASS by the highest id (out of insertion and
    # time order), and a PASS
    jobs["D"] = d = fx.make_job(conn, scan, agents["D"], pol, p[:2])
    fx.add_result(conn, d, pol, p[0], code=1, stdout="y")
    fx.add_result(conn, d, pol, p[1], code=0, stdout="x")
    base = fx.reserve_reeval_ids(conn)
    now = d.created_at
    pu = p[0].plugin_uuid
    for rid, code, detail, version, by, hours in (
        (5, 2, "cannot evaluate", 5, 50, 1),
        (9, 0, None, 9, 90, -5),
        (7, 1, None, 7, 70, 9),
    ):
        fx.add_reeval(
            conn,
            d.job_id,
            pu,
            code=code,
            detail=detail,
            policy_version=version,
            by=by,
            reeval_id=base + rid,
            at=now + timedelta(hours=hours),
        )
    # E: all ERROR
    jobs["E"] = e = fx.make_job(conn, scan, agents["E"], pol, p[:2])
    fx.add_result(conn, e, pol, p[0], code=2, detail="oversize")
    fx.add_result(conn, e, pol, p[1], code=2, detail="stdout not numeric", stdout="a")
    # An inventory job of A (ignored)
    fx.make_inventory_job(conn, agents["A"])
    # A second scan with the same agents and plugins, and a re-evaluation of
    # its A job's p2 (a FAIL in scan 1) to PASS with a higher id
    other = fx.make_scan(conn, pol)
    jobs["A_other"] = ao = fx.make_job(conn, other, agents["A"], pol, p)
    for plugin in p:
        fx.add_result(conn, ao, pol, plugin, code=1, stdout="z")
    fx.add_reeval(conn, ao.job_id, p[2].plugin_uuid, code=0, reeval_id=base + 500)
    fx.add_reeval(conn, ao.job_id, p[3].plugin_uuid, code=0, reeval_id=base + 501)
    return World(pol, scan, other, agents, jobs, base, result_count=11)


@pytest.fixture
def world(migrated_db: PgServer) -> World:
    with fx.owner(migrated_db) as conn:
        return build_world(conn)


@pytest.fixture
def app_conn_m8(migrated_db: PgServer) -> Iterator[Conn]:
    with fx.app(migrated_db) as conn:
        yield conn


# CHK-M8-140, -142: the builder's rows read back as bitscan_app
def test_builder_rows_are_readable_as_app(world: World, app_conn_m8: Conn) -> None:
    rows = app_conn_m8.execute(
        "SELECT j.job_id, j.created_at = r.job_created_at, j.payload, j.eval_spec"
        " FROM scan_job j JOIN scan_result r ON r.job_id = j.job_id"
        " WHERE j.scan_id = %s",
        (world.scan,),
    ).fetchall()
    assert len(rows) == world.result_count
    assert all(r[1] for r in rows)
    for _, _, payload, spec in rows:
        assert set(payload["plugins"][0]) == {"plugin_uuid", "execute", "timeout_s"}
        assert set(spec) == {"plugins"}
        assert set(spec["plugins"][0]) == {
            "plugin_uuid",
            "name",
            "operator",
            "expected",
        }
        assert "execute" not in json.dumps(spec)
    parts = app_conn_m8.execute(
        "SELECT DISTINCT tableoid::regclass::text FROM scan_result"
        " WHERE job_id = ANY(%s)",
        ([world.jobs["B"].job_id, world.jobs["B2"].job_id],),
    ).fetchall()
    assert len(parts) == 2  # two monthly partitions, neither the default
    assert all(p[0] != "scan_result_default" for p in parts)


def test_trigger_refuses_a_wrong_job_created_at(
    world: World, migrated_db: PgServer
) -> None:
    job = world.jobs["C"]
    bad = fx.Job(
        job.job_id, job.created_at + timedelta(seconds=1), job.agent_id, job.plugins
    )
    with fx.owner(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        fx.add_result(conn, bad, world.policy, world.policy.plugins[0], code=0)


# CHK-M8-141
def test_row_checksum_is_sensitive(world: World, migrated_db: PgServer) -> None:
    with fx.owner(migrated_db) as conn:
        before = fx.result_checksums(conn)
        assert before == fx.result_checksums(conn)
        changed: dict[str, str] = {}
        with conn.transaction():
            conn.execute(
                "UPDATE scan_result SET stderr = stderr || 'x' WHERE job_id = %s",
                (world.jobs["A"].job_id,),
            )
            changed = fx.result_checksums(conn)
            raise psycopg.Rollback()
        assert changed["scan_result"] != before["scan_result"]
        assert changed != before
        assert fx.result_checksums(conn) == before


# CHK-M8-150, -151: REQ-198 (1a)
def _by_key(rows: list[EffectiveRow]) -> dict[tuple[UUID, UUID], EffectiveRow]:
    return {(r.job_id, r.plugin_uuid): r for r in rows}


def test_effective_results_returns_exactly_the_scans_results(
    world: World, app_conn_m8: Conn
) -> None:
    rows = results.effective_results(app_conn_m8, world.scan)
    assert len(rows) == world.result_count
    assert all(isinstance(r, EffectiveRow) for r in rows)
    scan_jobs = {j.job_id for k, j in world.jobs.items() if k != "A_other"}
    assert {r.job_id for r in rows} <= scan_jobs
    # Ordered by agent, job, plugin
    keys = [(str(r.agent_id), str(r.job_id), str(r.plugin_uuid)) for r in rows]
    assert keys == sorted(keys)
    p = world.policy.plugins
    got = _by_key(rows)
    a = world.jobs["A"].job_id
    assert (
        got[(a, p[0].plugin_uuid)].original_code,
        got[(a, p[0].plugin_uuid)].code,
    ) == (0, 0)
    row = got[(a, p[3].plugin_uuid)]
    assert (row.original_code, row.original_detail, row.code, row.detail) == (
        2, "timed out", 2, "timed out"
    )  # fmt: skip
    assert row.reeval_id is None
    assert row.reeval_policy_version is None
    assert row.reevaluated_by is None
    assert row.reevaluated_at is None
    assert row.agent_id == world.agents["A"]
    # retry results are the scan's too, with the agent of the original
    b2 = world.jobs["B2"].job_id
    assert got[(b2, p[1].plugin_uuid)].agent_id == world.agents["B"]
    assert got[(b2, p[1].plugin_uuid)].code == 1


def test_effective_is_the_highest_reeval_id(world: World, app_conn_m8: Conn) -> None:
    rows = _by_key(results.effective_results(app_conn_m8, world.scan))
    p = world.policy.plugins
    d = rows[(world.jobs["D"].job_id, p[0].plugin_uuid)]
    assert (d.original_code, d.original_detail) == (1, None)
    assert (d.code, d.detail) == (0, None)
    assert d.reeval_id == world.base + 9
    assert d.reeval_policy_version == 9
    assert d.reevaluated_by == 90
    assert d.reevaluated_at is not None
    untouched = rows[(world.jobs["D"].job_id, p[1].plugin_uuid)]
    assert untouched.reeval_id is None and untouched.code == 0


# CHK-M8-152: REQ-198 (1b)
def test_host_counts(world: World, app_conn_m8: Conn) -> None:
    counts = results.host_counts(app_conn_m8, world.scan)
    assert all(isinstance(c, HostCounts) for c in counts)
    got = {c.agent_id: (c.passed, c.failed, c.errors, c.not_run) for c in counts}
    a = world.agents
    assert got == {
        a["A"]: (2, 1, 1, 1),
        a["B"]: (2, 1, 0, 0),
        a["C"]: (0, 0, 0, 3),
        a["D"]: (2, 0, 0, 0),
        a["E"]: (0, 0, 2, 0),
    }
    assert [str(c.agent_id) for c in counts] == sorted(str(c.agent_id) for c in counts)


# CHK-M8-153, -154: REQ-198 (2), (3)
def test_other_scans_rows_never_appear(world: World, app_conn_m8: Conn) -> None:
    rows = results.effective_results(app_conn_m8, world.scan)
    assert world.jobs["A_other"].job_id not in {r.job_id for r in rows}
    # The other scan's re-evaluation of p2 (a higher id) does not touch scan 1
    p = world.policy.plugins
    a_p2 = _by_key(rows)[(world.jobs["A"].job_id, p[2].plugin_uuid)]
    assert (a_p2.code, a_p2.reeval_id) == (1, None)
    other = results.effective_results(app_conn_m8, world.other_scan)
    assert len(other) == 5
    assert {r.agent_id for r in other} == {world.agents["A"]}
    o = _by_key(other)
    assert o[(world.jobs["A_other"].job_id, p[2].plugin_uuid)].code == 0
    assert (
        o[(world.jobs["A_other"].job_id, p[2].plugin_uuid)].reeval_id
        == world.base + 500
    )
    counts = results.host_counts(app_conn_m8, world.other_scan)
    assert [(c.agent_id, c.passed, c.failed, c.errors, c.not_run) for c in counts] == [
        (world.agents["A"], 2, 3, 0, 0)
    ]


# CHK-M8-155: a planted duplicate (original and retry both hold a plugin) is
# counted twice, not hidden (TASK-182 plan §3), so M9's own test can see it
def test_duplicate_result_is_not_hidden(
    migrated_db: PgServer, app_conn_m8: Conn
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")] * 2)
        p = pol.plugins
        scan = fx.make_scan(conn, pol)
        agent = fx.make_agent(conn)
        orig = fx.make_job(conn, scan, agent, pol, p)
        retry = fx.make_job(conn, scan, agent, pol, p[1:], retry_of=orig.job_id)
        fx.add_result(conn, orig, pol, p[1], code=0)
        fx.add_result(conn, retry, pol, p[1], code=1)
    counts = results.host_counts(app_conn_m8, scan)
    assert [(c.passed, c.failed, c.errors, c.not_run) for c in counts] == [(1, 1, 0, 1)]
    assert len(results.effective_results(app_conn_m8, scan)) == 2


def test_retry_plugins_are_not_double_counted_as_not_run(
    migrated_db: PgServer, app_conn_m8: Conn
) -> None:
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")] * 3)
        p = pol.plugins
        scan = fx.make_scan(conn, pol)
        agent = fx.make_agent(conn)
        orig = fx.make_job(conn, scan, agent, pol, p)
        fx.make_job(conn, scan, agent, pol, p[1:], retry_of=orig.job_id, state="queued")
        fx.add_result(conn, orig, pol, p[0], code=0)
    # p1 and p2 are planned once (the original's payload), whatever the retry holds
    counts = results.host_counts(app_conn_m8, scan)
    assert [(c.passed, c.failed, c.errors, c.not_run) for c in counts] == [(1, 0, 0, 2)]


# CHK-M8-157
def test_unknown_scan_and_scan_without_results(
    migrated_db: PgServer, app_conn_m8: Conn
) -> None:
    unknown = uuid4()
    assert results.effective_results(app_conn_m8, unknown) == []
    assert results.host_counts(app_conn_m8, unknown) == []
    with fx.owner(migrated_db) as conn:
        pol = fx.make_policy(conn, [("equals", "x")] * 2)
        empty_scan = fx.make_scan(conn, pol)
        no_jobs = results.effective_results(app_conn_m8, empty_scan)
        agent = fx.make_agent(conn)
        fx.make_job(conn, empty_scan, agent, pol, pol.plugins, state="queued")
        fx.make_job(conn, empty_scan, fx.make_agent(conn), pol, [], state="queued")
    assert no_jobs == []
    assert results.effective_results(app_conn_m8, empty_scan) == []
    got = sorted(
        (c.passed, c.failed, c.errors, c.not_run)
        for c in results.host_counts(app_conn_m8, empty_scan)
    )
    assert got == [(0, 0, 0, 0), (0, 0, 0, 2)]


# CHK-M8-160: inventory jobs are not compliance results
def test_inventory_jobs_are_ignored(world: World, app_conn_m8: Conn) -> None:
    counts = results.host_counts(app_conn_m8, world.scan)
    assert len(counts) == 5


# CHK-M8-158, -159: one statement, SELECT only, reeval read once
class Capture:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> Capture:
    cap = Capture()
    real = psycopg.Cursor.execute

    def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
        cap.calls.append((query, params))
        return real(cur, query, params, **kw)

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    return cap


def _text(conn: Conn, query: Any) -> str:
    return query if isinstance(query, str) else query.as_string(conn)


@pytest.mark.parametrize("fn", [results.effective_results, results.host_counts])
def test_one_select_statement_with_bound_parameters(
    world: World, app_conn_m8: Conn, capture: Capture, fn: Any
) -> None:
    fn(app_conn_m8, world.scan)
    assert len(capture.calls) == 1
    query, params = capture.calls[0]
    text = _text(app_conn_m8, query)
    assert text.lstrip().upper().startswith(("WITH", "SELECT"))
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "FOR UPDATE", "FOR SHARE"):
        assert verb not in text.upper(), verb
    assert str(world.scan) not in text  # bound, never built into the SQL
    assert params is not None and world.scan in dict(params).values()


def _nodes(
    node: dict[str, Any], path: tuple[dict[str, Any], ...] = ()
) -> Iterator[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    yield node, path
    for child in node.get("Plans", []):
        yield from _nodes(child, (*path, node))


@pytest.mark.parametrize("fn", [results.effective_results, results.host_counts])
def test_explain_reads_scan_result_reeval_once(
    world: World, app_conn_m8: Conn, capture: Capture, fn: Any
) -> None:
    """REQ-198 (5): one scan node over scan_result_reeval, executed once (no
    per-result probe: no SubPlan above it and Actual Loops = 1)."""
    fn(app_conn_m8, world.scan)
    query, params = capture.calls[0]
    capture.calls.clear()
    stmt = sql.SQL("EXPLAIN (ANALYZE, FORMAT JSON) ") + (
        sql.SQL(query) if isinstance(query, str) else query
    )
    plan = app_conn_m8.execute(stmt, params).fetchone()
    assert plan is not None
    root = plan[0][0]["Plan"]
    found = [
        (n, path)
        for n, path in _nodes(root)
        if n.get("Relation Name") == "scan_result_reeval"
    ]
    assert len(found) == 1, [n.get("Node Type") for n, _ in found]
    node, path = found[0]
    assert node["Actual Loops"] == 1, node
    for step in (*path, node):
        assert step.get("Parent Relationship") != "SubPlan", step.get("Node Type")
