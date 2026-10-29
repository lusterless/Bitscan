"""TP-M8-11: host scores service and the SQL-versus-`effective()` property
(TASK-184; REQ-197 (3), REQ-199).

TS §4.5 L602 and #120: per host per scan, passed / (passed + failed) over the
effective verdicts, None with no PASS or FAIL; computed when read (§2.1 L105),
so late results and re-evaluations change the next read. #119: the REQ-198
SQL and the pure `effective()` must agree. CHK-M8-180 to -184.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import results
from bitscan_manager.services.evaluator.score import HostScore, ReevalRow, effective
from bitscan_manager.services.evaluator.scores import AgentScore, scan_host_scores

from . import evaluator_pg_fixtures as fx
from .conftest import PgServer
from .test_results_repo_pg import World, build_world

pytestmark = pytest.mark.pg


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=2, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture
def world(migrated_db: PgServer) -> World:
    with fx.owner(migrated_db) as conn:
        return build_world(conn)


def _scores(db: AppDatabase, scan: UUID) -> dict[UUID, HostScore]:
    got = scan_host_scores(db, scan)
    assert all(isinstance(s, AgentScore) for s in got)
    assert [str(s.agent_id) for s in got] == sorted(str(s.agent_id) for s in got)
    return {s.agent_id: s.host for s in got}


# CHK-M8-180: REQ-199 (1)
def test_scores_per_host(world: World, db: AppDatabase) -> None:
    got = _scores(db, world.scan)
    a = world.agents
    assert got == {
        a["A"]: HostScore(2, 1, 1, 1, 2 / 3),
        a["B"]: HostScore(2, 1, 0, 0, 2 / 3),
        a["C"]: HostScore(0, 0, 0, 3, None),  # queued
        a["D"]: HostScore(2, 0, 0, 0, 1.0),  # FAIL re-evaluated to PASS
        a["E"]: HostScore(0, 0, 2, 0, None),  # all ERROR
    }


# CHK-M8-181: REQ-199 (2) computed when read
def test_late_result_then_reeval_change_the_next_read(
    world: World, db: AppDatabase, migrated_db: PgServer
) -> None:
    c = world.agents["C"]
    assert _scores(db, world.scan)[c].score is None
    p = world.policy.plugins
    with fx.owner(migrated_db) as conn:
        fx.add_result(conn, world.jobs["C"], world.policy, p[0], code=0, stdout="x")
    assert _scores(db, world.scan)[c] == HostScore(1, 0, 0, 2, 1.0)
    with fx.owner(migrated_db) as conn:
        fx.add_reeval(conn, world.jobs["C"].job_id, p[0].plugin_uuid, code=1)
    assert _scores(db, world.scan)[c] == HostScore(0, 1, 0, 2, 0.0)
    with fx.owner(migrated_db) as conn:
        fx.add_reeval(conn, world.jobs["C"].job_id, p[0].plugin_uuid, code=2,
                      detail="cannot evaluate")  # fmt: skip
    assert _scores(db, world.scan)[c] == HostScore(0, 0, 1, 2, None)


# CHK-M8-182: REQ-199 (3)
def test_unknown_scan_is_empty(db: AppDatabase) -> None:
    assert scan_host_scores(db, uuid4()) == []


# CHK-M8-183: REQ-199 (4)
def test_only_select(
    world: World, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = fx.StatementSpy()
    spy.install(monkeypatch)
    scan_host_scores(db, world.scan)
    verbs = [v for v in spy.verbs() if v not in ("BEGIN", "COMMIT", "ROLLBACK")]
    assert verbs and set(verbs) <= {"SELECT", "WITH"}, spy.statements
    text = " ".join(spy.statements).upper().split()
    for bad in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert bad not in text


# CHK-M8-184: REQ-197 (3), 200 random sets
def _random_set(conn: Any, rng: random.Random) -> tuple[UUID, list[UUID]]:
    n_plugins = rng.randint(1, 4)
    pol = fx.make_policy(conn, [("equals", "x")] * n_plugins)
    scan = fx.make_scan(conn, pol)
    jobs: list[UUID] = []
    for _ in range(rng.randint(1, 3)):
        agent = fx.make_agent(conn)
        plugins = rng.sample(pol.plugins, rng.randint(1, n_plugins))
        job = fx.make_job(conn, scan, agent, pol, plugins)
        jobs.append(job.job_id)
        with_result = [p for p in plugins if rng.random() < 0.8]
        for p in with_result:
            code = rng.choice([0, 1, 2])
            fx.add_result(conn, job, pol, p, code=code,
                          detail="timed out" if code == 2 else None)  # fmt: skip
        if rng.random() < 0.5:
            missing = [p for p in plugins if p not in with_result]
            if missing:
                retry = fx.make_job(
                    conn, scan, agent, pol, missing, retry_of=job.job_id
                )
                jobs.append(retry.job_id)
                for p in missing:
                    if rng.random() < 0.7:
                        fx.add_result(conn, retry, pol, p, code=rng.choice([0, 1]))
    # re-evaluation rows with random ids (some out of order) and times, some for
    # pairs without a result, some for jobs of another scan
    base = fx.reserve_reeval_ids(conn, 100)
    pairs = conn.execute(
        "SELECT r.job_id, r.plugin_uuid FROM scan_result r JOIN scan_job j"
        " ON j.job_id = r.job_id WHERE j.scan_id = %s",
        (scan,),
    ).fetchall()
    ids = rng.sample(range(base + 1, base + 100), k=min(len(pairs) * 3, 60))
    for rid in ids:
        if not pairs:
            break
        job_id, plugin = rng.choice(pairs)
        code = rng.choice([0, 1, 2])
        fx.add_reeval(
            conn,
            job_id,
            plugin,
            code=code,
            detail="cannot evaluate" if code == 2 else None,
            policy_version=rng.randint(1, 9),
            reeval_id=rid,
            at=fx.next_month_start() - timedelta(minutes=rng.randint(0, 10_000)),
        )
    return scan, jobs


def test_sql_and_effective_agree_on_200_random_sets(migrated_db: PgServer) -> None:
    rng = random.Random(20261029)  # noqa: S311  # test data, seeded
    with fx.owner(migrated_db) as conn, fx.app(migrated_db) as app_conn:
        for _ in range(200):
            scan, jobs = _random_set(conn, rng)
            sql_rows = results.effective_results(app_conn, scan)
            originals = conn.execute(
                "SELECT r.job_id, r.plugin_uuid, r.eval_code, r.eval_detail"
                " FROM scan_result r JOIN scan_job j ON j.job_id = r.job_id"
                " WHERE j.scan_id = %s",
                (scan,),
            ).fetchall()
            # every re-evaluation row of every job (other scans' rows included)
            reevals = [
                ReevalRow(
                    int(r[0]), r[1], r[2], int(r[3]), int(r[4]), r[5], int(r[6]), r[7]
                )
                for r in conn.execute(
                    "SELECT reeval_id, job_id, plugin_uuid, policy_version,"
                    " eval_code, eval_detail, reevaluated_by, reevaluated_at"
                    " FROM scan_result_reeval"
                    " WHERE job_id = ANY(%s) OR reeval_id %% 7 = 0",
                    (jobs,),
                ).fetchall()
            ]
            assert len(sql_rows) == len(originals)
            by_key = {(r.job_id, r.plugin_uuid): r for r in sql_rows}
            for job_id, plugin, code, detail in originals:
                want = effective(job_id, plugin, int(code), detail, reevals)
                got = by_key[(job_id, plugin)]
                assert (got.code, got.detail, got.reeval_id) == (
                    want.code,
                    want.detail,
                    want.reeval_id,
                )
                assert (got.original_code, got.original_detail) == (
                    want.original_code,
                    want.original_detail,
                )
                assert got.reeval_policy_version == want.policy_version
                assert got.reevaluated_by == want.reevaluated_by
