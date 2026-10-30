"""TASK-199 TEST: first result wins under concurrent retries (TP-M9-12;
CHK-M9-170; mutation rows CHK-M9-320, -321; TS §8.3 Security "the first
result wins under concurrent retries").

TS §2.2 L112, §4.4 L578 (for each host and plugin the first result wins,
whether it came from the original job or the retry; the API locks the
original job row while inserting), REQ-216 (3), (4); M8 carry CHK-M8-155:
M8's ``host_counts`` counts a duplicate twice on purpose, so a lost lock is
visible as a double count. Races are driven by a barrier and two sessions,
never by sleeps (decisions 2026-10-26).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.repositories.results import host_counts
from bitscan_manager.services.jobs.intake import Accepted, accept_results

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

REPEATS = 200
NOW = f.T0 + timedelta(hours=1)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("race")) as s:
        yield s


def item(p: f.PluginDef, origin: str) -> dict[str, object]:
    return {
        "plugin_uuid": str(p.plugin_uuid),
        "exit_code": 0,
        "stdout": "ok",  # PASS against the fixture's expected "ok"
        "stderr": origin,
        "started_at": f.iso(NOW - timedelta(seconds=5)),
        "finished_at": f.iso(NOW - timedelta(seconds=4)),
        "timed_out": False,
        "truncated": False,
        "error": None,
    }


def test_two_sessions_posting_one_plugin_to_original_and_retry_store_it_once(
    server: PgServer, tmp_path: Path
) -> None:
    """REQ-216 (3), (4): 200 rounds; in each, two threads (two pooled
    sessions) wait at one barrier, then post the same plugin, one to the
    original and one to its retry. Exactly one row exists for the plugin in
    the unit, the answers are one {1, 0} and one {0, 1}, M8's host_counts
    counts it once (1 PASS, 1 not run), and no round deadlocks or errors."""
    with f.app_database(server, max_size=6) as db:
        cat = f.make_catalog(db, f.Clock(), tmp_path)
        pol = cat.policy(2)
        p1, p2 = pol.plugins
        with f.app(server) as c:
            agents = [f.make_agent(c).agent_id for _ in range(REPEATS)]
        units = []
        with f.owner(server) as o:
            for a in agents:
                sid = f.owner_scan(o, pol, state="running")
                orig = f.owner_job(o, sid, a, pol, state="partial")
                retry = f.owner_job(
                    o,
                    sid,
                    a,
                    pol,
                    [p2],
                    state="running",
                    retry_of=orig.job_id,
                    created_at=f.T0 + timedelta(minutes=45),
                )
                units.append((sid, orig, retry))
        batch_o = schemas.ResultsRequest.model_validate(
            {"results": [item(p2, "via original")], "final": False}
        )
        batch_r = schemas.ResultsRequest.model_validate(
            {"results": [item(p2, "via retry")], "final": False}
        )
        failures: list[str] = []
        for n, (sid, orig, retry) in enumerate(units):
            barrier = threading.Barrier(2, timeout=30)
            outs: dict[str, object] = {}

            def post(
                name: str,
                job: f.JobRow,
                batch: schemas.ResultsRequest,
                barrier: threading.Barrier = barrier,
                outs: dict[str, object] = outs,
            ) -> None:
                barrier.wait()
                outs[name] = accept_results(
                    db, agent_id=job.agent_id, job_id=job.job_id, batch=batch, now=NOW
                )

            order = [("o", orig, batch_o), ("r", retry, batch_r)]
            if n % 2:
                order.reverse()
            threads = [threading.Thread(target=post, args=a) for a in order]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
                assert not t.is_alive(), f"round {n}: a post never finished"
            with f.app(server) as c:
                rows = f.results_of(c, [orig.job_id, retry.job_id])
                counts = host_counts(c, sid)
            got = sorted(
                (getattr(o, "accepted", -1), getattr(o, "duplicates", -1))
                for o in outs.values()
            )
            if not (
                len(rows) == 1
                and got == [(0, 1), (1, 0)]
                and all(isinstance(o, Accepted) for o in outs.values())
                and [(h.passed, h.failed, h.errors, h.not_run) for h in counts]
                == [(1, 0, 0, 1)]
            ):
                failures.append(
                    f"round {n}: rows={len(rows)} answers={got} "
                    f"host_counts={[(h.passed, h.not_run) for h in counts]}"
                )
    assert failures == [], failures[:5]
