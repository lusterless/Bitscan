"""TASK-235 TEST: property agreement of the results page with M8 on
PostgreSQL (TP-M11-04; CHK-M11-082; REQ-267 (4)).

For 200 random scans (seeded; originals, retries holding only the plugins
the original did not answer, random results, random re-evaluations whose ids
and times are in independent random orders, #119), every item's effective
verdict equals M8's pure ``score.effective()`` over the stored rows, every
``original_result`` equals the stored code, each host has one item per
planned plugin of its original job, and the per-host counts of the items
(PASS, FAIL, ERROR, Not run) equal M8's ``results.host_counts``.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator
from uuid import UUID

import pytest

from bitscan_manager.repositories import result_reads as rr
from bitscan_manager.repositories import results as m8
from bitscan_manager.services.evaluator import score

from . import m11_pg_fixtures as m
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

SEED = 235_082
SCANS = 200


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("results-property")) as s:
        yield s


def stored_rows(
    conn: m.Conn, job_ids: list[UUID]
) -> tuple[dict[tuple[UUID, UUID], tuple[int, str | None]], list[score.ReevalRow]]:
    results = {
        (UUID(str(j)), UUID(str(p))): (int(c), None if d is None else str(d))
        for j, p, c, d in conn.execute(
            "SELECT job_id, plugin_uuid, eval_code, eval_detail FROM scan_result"
            " WHERE job_id = ANY(%s)",
            (job_ids,),
        ).fetchall()
    }
    reevals = [
        score.ReevalRow(
            int(r), UUID(str(j)), UUID(str(p)), int(v), int(c), d, int(b), t
        )
        for r, j, p, v, c, d, b, t in conn.execute(
            "SELECT reeval_id, job_id, plugin_uuid, policy_version, eval_code,"
            " eval_detail, reevaluated_by, reevaluated_at FROM scan_result_reeval"
            " WHERE job_id = ANY(%s)",
            (job_ids,),
        ).fetchall()
    ]
    return results, reevals


def test_200_random_scans_agree_with_m8(server: PgServer) -> None:
    rng = random.Random(SEED)  # noqa: S311 - seeded test data
    with m.owner(server) as c:
        pol = m.make_policy(c, 4)
        agents = [m.host(c).agent_id for _ in range(5)]
        scans = [m.random_scan(c, rng, pol, agents) for _ in range(SCANS)]
    checked = Counter[str]()
    with m.app(server) as app, m.owner(server) as own:
        for i, rs in enumerate(scans):
            where = f"seed {SEED} scan {i}"
            items = rr.results_page(
                app,
                rs.scan_id,
                status=None,
                agent_id=None,
                with_output=True,
                after=None,
                limit=100_000,
            )
            results, reevals = stored_rows(own, [j.job_id for j in rs.jobs])
            originals = {j.agent_id: j for j in rs.jobs if j.retry_of is None}
            # one item per planned plugin of each host's original job, in order
            assert [(r.agent_id, r.plugin_uuid) for r in items] == [
                (a, p)
                for a in sorted(originals, key=lambda u: u.int)
                for p in originals[a].uuids
            ], where
            seen: set[tuple[UUID, UUID]] = set()
            for r in items:
                assert r.orig_job_id == originals[r.agent_id].job_id, where
                if r.job_id is None:
                    unit = {j.job_id for j in rs.jobs if j.agent_id == r.agent_id}
                    assert not any((j, r.plugin_uuid) in results for j in unit), where
                    assert r.code is None and r.original_code is None, where
                    checked["not_run"] += 1
                    continue
                key = (r.job_id, r.plugin_uuid)
                code, detail = results[key]
                want = score.effective(r.job_id, r.plugin_uuid, code, detail, reevals)
                assert (r.original_code, r.original_detail) == (code, detail), where
                assert (r.code, r.detail) == (want.code, want.detail), where
                assert (
                    r.reeval_policy_version,
                    r.reevaluated_by,
                    r.reevaluated_at,
                ) == (want.policy_version, want.reevaluated_by, want.reevaluated_at), (
                    where
                )
                assert r.retry == (r.job_id != r.orig_job_id), where
                seen.add(key)
                checked["reevaluated" if want.reeval_id else "original"] += 1
                checked["retry" if r.retry else "in_original"] += 1
            assert seen == set(results), where  # every stored result, once
            counts = {
                a: m8.HostCounts(
                    a,
                    sum(1 for r in items if r.agent_id == a and r.code == 0),
                    sum(1 for r in items if r.agent_id == a and r.code == 1),
                    sum(1 for r in items if r.agent_id == a and r.code == 2),
                    sum(1 for r in items if r.agent_id == a and r.job_id is None),
                )
                for a in sorted(originals, key=lambda u: u.int)
            }
            assert list(counts.values()) == m8.host_counts(app, rs.scan_id), where
            # a random filter is the matching subset of the full page
            status = rng.choice((None, "PASS", "FAIL", "ERROR", "NOT_RUN"))
            agent = rng.choice([None, *originals])
            sub = rr.results_page(
                app,
                rs.scan_id,
                status=status,
                agent_id=agent,
                with_output=False,
                after=None,
                limit=100_000,
            )
            codes = {"PASS": 0, "FAIL": 1, "ERROR": 2}
            assert [(r.agent_id, r.plugin_uuid) for r in sub] == [
                (r.agent_id, r.plugin_uuid)
                for r in items
                if (agent is None or r.agent_id == agent)
                and (
                    status is None
                    or (status == "NOT_RUN" and r.job_id is None)
                    or (r.job_id is not None and r.code == codes.get(status or ""))
                )
            ], (where, status, agent)
    # the random worlds exercised every branch
    assert min(checked.values()) > 0 and len(checked) == 5, checked
