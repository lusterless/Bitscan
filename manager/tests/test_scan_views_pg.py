"""TP-M11-08: the scan views service on PostgreSQL, as bitscan_app through
AppDatabase (TASK-240 TEST, tester-m11c; REQ-264 to REQ-266; CHK-M11-155 to
-162).

Expected values come from the spec and the approved answers, not the code:
TS §4.5 L603-L604 and #120 (score = passed ÷ (passed + failed), unrounded,
None when that is 0; ERROR and Not run never in the ratio; errors beside it),
#119 (the effective verdict is the highest reeval_id, else the original),
TS §4.4 L577-L585 (a retry holds only the original's unanswered plugins; the
unit counts once), the M9 interface note (the scan state is ``scan.state``
as stored, never re-derived), #145 (a)-(c) (hosts ordered by hostname then
agent_id, original job first then its retry; the target as requested,
without ``resolved_agents``; host history through the stored resolved
target), TS §4.3 L552 (scans of deleted policies stay readable), REQ-265
(one read-only snapshot, computed when read) and REQ-266 (an unknown agent
is AgentNotFound; a decommissioned agent's history is returned). M8's
``scores.scan_host_scores()`` is the reference REQ-265 (2) agrees with.

Races use a hook inside the service's transaction, never a sleep.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import scan_reads
from bitscan_manager.services.evaluator import scores
from bitscan_manager.services.jobs import scan_views as sv

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

_WINDOWS = itertools.count()
NO_FILTER = sv.ScanFilters(None, None, None, None, None)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-scan-views")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with m.app_database(server, max_size=4) as d:
        yield d


def by_agent(detail: sv.ScanDetail) -> dict[UUID, sv.HostView]:
    return {h.agent_id: h for h in detail.hosts}


def counts(h: sv.HostView) -> tuple[int, int, int, int, float | None]:
    s = h.host
    return (s.passed, s.failed, s.errors, s.not_run, s.score)


# ----- CHK-M11-155: counts and score ---------------------------------------------


def score_world(server: PgServer) -> dict[str, Any]:
    """Six plugins p0..p5.

    - host A: original (partial) p0 PASS, p1 FAIL re-evaluated to PASS, p2
      FAIL, p3 ERROR runner_unavailable; p4 and p5 unanswered, so the retry
      plans [p4, p5]: p4 PASS, p5 not run. Expected 3 passed, 1 failed,
      1 error, 1 not run, score 0.75.
    - host B: every plugin ERROR (oversize): score None, 6 errors.
    - host C: job still queued, no result: score None, 6 not run.
    - host D: p0 PASS re-evaluated twice, the higher id FAIL (the later
      time PASS); the rest FAIL. Expected 0 passed, 6 failed, score 0.0.
    """
    with m.owner(server) as c:
        pol = m.make_policy(c, 6)
        p = pol.plugins
        hs = {k: m.host(c, f"score-{k}-{uuid4().hex[:6]}") for k in "ABCD"}
        sid = m.scan(c, pol, [h.agent_id for h in hs.values()], state="running")
        ja = m.job(c, sid, hs["A"].agent_id, pol, state="partial")
        m.result(c, ja, pol, p[0], code=0)
        m.result(c, ja, pol, p[1], code=1)
        m.result(c, ja, pol, p[2], code=1)
        m.runner_unavailable(c, ja, pol, p[3])
        jar = m.job(
            c,
            sid,
            hs["A"].agent_id,
            pol,
            [p[4], p[5]],
            state="completed",
            created_at=f9.next_month(f9.T0),
            retry_of=ja.job_id,
        )
        m.result(c, jar, pol, p[4], code=0)
        jb = m.job(c, sid, hs["B"].agent_id, pol, state="completed")
        for pd in p:
            m.oversize(c, jb, pol, pd)
        jc = m.job(c, sid, hs["C"].agent_id, pol, state="queued")
        jd = m.job(c, sid, hs["D"].agent_id, pol, state="completed")
        for i, pd in enumerate(p):
            m.result(c, jd, pol, pd, code=0 if i == 0 else 1)
        base = m.reserve_reeval_ids(c, 10)
        m.add_reeval(c, ja.job_id, p[1].plugin_uuid, code=0, by=1, reeval_id=base + 1)
        m.add_reeval(
            c,
            jd.job_id,
            p[0].plugin_uuid,
            code=0,
            by=1,
            reeval_id=base + 2,
            at=f9.T0 + timedelta(hours=5),
        )
        m.add_reeval(
            c,
            jd.job_id,
            p[0].plugin_uuid,
            code=1,
            by=1,
            reeval_id=base + 3,
            at=f9.T0 + timedelta(hours=1),
        )
    return {"pol": pol, "scan": sid, "hosts": hs, "jobs": [ja, jar, jb, jc, jd]}


def test_counts_and_score_per_host(server: PgServer, db: AppDatabase) -> None:
    w = score_world(server)
    d = sv.scan_detail(db, w["scan"])
    got = {k: counts(by_agent(d)[h.agent_id]) for k, h in w["hosts"].items()}
    assert got == {
        "A": (3, 1, 1, 1, 0.75),
        "B": (0, 0, 6, 0, None),
        "C": (0, 0, 0, 6, None),
        "D": (0, 6, 0, 0, 0.0),
    }
    assert len(d.hosts) == 4  # the retry joins A; it is no host of its own
    ja, jar = w["jobs"][0], w["jobs"][1]
    assert [j.job_id for j in by_agent(d)[w["hosts"]["A"].agent_id].jobs] == [
        ja.job_id,
        jar.job_id,
    ]


# ----- CHK-M11-156: agreement with M8 over 50 random scans -----------------------


def test_fifty_random_scans_agree_with_m8(server: PgServer, db: AppDatabase) -> None:
    rng = random.Random(24311)  # noqa: S311 (test data, not crypto)
    with m.owner(server) as c:
        pol = m.make_policy(c, 4)
        agents = [m.host(c).agent_id for _ in range(5)]
        made = [m.random_scan(c, rng, pol, agents) for _ in range(50)]
    hosts_seen = 0
    for rs in made:
        d = sv.scan_detail(db, rs.scan_id)
        ref = {a.agent_id: a.host for a in scores.scan_host_scores(db, rs.scan_id)}
        assert {h.agent_id: h.host for h in d.hosts} == ref, rs.scan_id
        hosts_seen += len(ref)
    assert hosts_seen >= 50


# ----- CHK-M11-157: host and job order -------------------------------------------


def test_hosts_by_hostname_then_agent_id_and_jobs_original_first(
    server: PgServer, db: AppDatabase
) -> None:
    tag = uuid4().hex[:6]
    with m.owner(server) as c:
        pol = m.make_policy(c, 2)
        z = m.host(c, f"zz-{tag}")
        dup = [m.host(c, f"mm-{tag}") for _ in range(3)]
        a = m.host(c, f"aa-{tag}")
        everyone = [z, *dup, a]
        sid = m.scan(c, pol, [h.agent_id for h in everyone])
        jobs: dict[UUID, list[m.JobRow]] = {}
        for h in everyone:
            orig = m.job(c, sid, h.agent_id, pol, state="partial")
            jobs[h.agent_id] = [orig]
        # retries created before their originals' created_at, so an order by
        # time alone would put them first
        for h in (z, dup[1]):
            retry = m.job(
                c,
                sid,
                h.agent_id,
                pol,
                pol.plugins[1:],
                state="running",
                created_at=f9.T0 - timedelta(days=1),
                retry_of=jobs[h.agent_id][0].job_id,
            )
            jobs[h.agent_id].append(retry)
    d = sv.scan_detail(db, sid)
    want = [
        a.agent_id,
        *sorted((h.agent_id for h in dup), key=lambda u: u.int),
        z.agent_id,
    ]
    assert [h.agent_id for h in d.hosts] == want
    assert [h.hostname for h in d.hosts] == [
        f"aa-{tag}",
        f"mm-{tag}",
        f"mm-{tag}",
        f"mm-{tag}",
        f"zz-{tag}",
    ]
    for hv in d.hosts:
        assert [j.job_id for j in hv.jobs] == [j.job_id for j in jobs[hv.agent_id]]
        assert hv.jobs[0].retry_of is None
        assert [j.retry_of for j in hv.jobs[1:]] == [hv.jobs[0].job_id] * (
            len(hv.jobs) - 1
        )
    with m.owner(server) as c:
        stored = {
            r[0]: (r[1], r[2], r[3], r[4])
            for r in c.execute(
                "SELECT job_id, state::text, dispatched_at, started_at, finished_at"
                " FROM scan_job WHERE scan_id = %s",
                (sid,),
            ).fetchall()
        }
    for hv in d.hosts:
        for j in hv.jobs:
            assert (j.state, j.dispatched_at, j.started_at, j.finished_at) == stored[
                j.job_id
            ]


# ----- CHK-M11-158: the stored state ---------------------------------------------


@pytest.mark.parametrize(
    ("stored", "job_states"),
    [
        ("running", ["completed", "completed"]),
        ("completed", ["running", "queued"]),
        ("queued", ["failed", "expired"]),
        ("partial", ["completed", "completed"]),
    ],
)
def test_state_is_scan_state_as_stored(
    server: PgServer, db: AppDatabase, stored: str, job_states: list[str]
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        hs = [m.host(c) for _ in job_states]
        sid = m.scan(c, pol, [h.agent_id for h in hs], state=stored)
        for h, st in zip(hs, job_states, strict=True):
            m.job(c, sid, h.agent_id, pol, state=st)
    assert sv.scan_detail(db, sid).scan.state == stored
    listed = sv.list_scans(
        db, sv.ScanFilters(pol.policy_id, None, None, None, None), 10, None
    )
    assert [(r.scan_id, r.state) for r in listed] == [(sid, stored)]


# ----- CHK-M11-159: deleted policy; late result then re-evaluation ---------------


def test_scan_of_a_deleted_policy_is_returned(
    server: PgServer, db: AppDatabase
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        h = m.host(c)
        sid = m.scan(c, pol, [h.agent_id], state="completed")
        jr = m.job(c, sid, h.agent_id, pol, state="completed")
        m.result(c, jr, pol, pol.plugins[0], code=0)
        m.soft_delete(c, pol)
    d = sv.scan_detail(db, sid)
    assert (d.scan.scan_id, d.scan.policy_name) == (sid, pol.name)
    assert counts(d.hosts[0]) == (1, 0, 0, 0, 1.0)
    listed = sv.list_scans(
        db, sv.ScanFilters(pol.policy_id, None, None, None, None), 10, None
    )
    assert [r.scan_id for r in listed] == [sid]


def test_late_result_then_reevaluation_change_the_next_answer(
    server: PgServer, db: AppDatabase
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 2)
        h = m.host(c)
        sid = m.scan(c, pol, [h.agent_id])
        jr = m.job(c, sid, h.agent_id, pol, state="running")
        m.result(c, jr, pol, pol.plugins[0], code=1)
    assert counts(sv.scan_detail(db, sid).hosts[0]) == (0, 1, 0, 1, 0.0)
    with m.owner(server) as c:
        m.result(c, jr, pol, pol.plugins[1], code=0)
    assert counts(sv.scan_detail(db, sid).hosts[0]) == (1, 1, 0, 0, 0.5)
    with m.owner(server) as c:
        m.add_reeval(c, jr.job_id, pol.plugins[0].plugin_uuid, code=0, by=1)
    assert counts(sv.scan_detail(db, sid).hosts[0]) == (2, 0, 0, 0, 1.0)


# ----- CHK-M11-160: one read-only snapshot ----------------------------------------


def test_detail_reads_one_read_only_snapshot(
    server: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result and a re-evaluation committed by another session after the
    jobs read, inside the service's transaction, are not seen by its counts
    read; the next call sees them. The first statement is the snapshot."""
    with m.owner(server) as c:
        pol = m.make_policy(c, 2)
        h = m.host(c)
        sid = m.scan(c, pol, [h.agent_id])
        jr = m.job(c, sid, h.agent_id, pol, state="running")
        m.result(c, jr, pol, pol.plugins[0], code=1)
    real = scan_reads.scan_jobs
    fired: list[int] = []

    def jobs_then_commit(conn: Any, scan_id: UUID) -> Any:
        rows = real(conn, scan_id)
        if not fired:
            fired.append(1)
            with m.owner(server) as other:
                m.result(other, jr, pol, pol.plugins[1], code=0)
                m.add_reeval(other, jr.job_id, pol.plugins[0].plugin_uuid, code=0, by=1)
        return rows

    # the service calls scan_reads.scan_jobs through the module, so this hook
    # runs inside its transaction, between the jobs read and the counts read
    monkeypatch.setattr(scan_reads, "scan_jobs", jobs_then_commit)
    spy = m.RoleSpy()
    with pytest.MonkeyPatch.context() as mp:
        spy.install(mp)
        d = sv.scan_detail(db, sid)
    assert fired == [1]
    assert counts(d.hosts[0]) == (0, 1, 0, 1, 0.0)  # as before the commit
    app = spy.by_role("bitscan_app")
    assert app[0].upper().startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert "READ ONLY" in app[0].upper()
    assert counts(sv.scan_detail(db, sid).hosts[0]) == (2, 0, 0, 0, 1.0)


def test_service_runs_select_only(server: PgServer, db: AppDatabase) -> None:
    """REQ-264 (5): the three reads issue SELECT (and transaction control)
    only, all as bitscan_app."""
    w = score_world(server)
    a = next(iter(w["hosts"].values())).agent_id
    spy = m.RoleSpy()
    with pytest.MonkeyPatch.context() as mp:
        spy.install(mp)
        sv.scan_detail(db, w["scan"])
        sv.list_scans(db, NO_FILTER, 5, None)
        sv.agent_scans(db, a, 5, None)
    assert spy.statements
    assert set(spy.roles) == {"bitscan_app"}
    verbs = {m.verb(s) for s in spy.statements}
    assert verbs <= {"SELECT", "WITH", "SET"}, verbs
    assert not [s for s in spy.statements if m.verb(s) in m.WRITE_VERBS]


# ----- CHK-M11-161: not found; host history; decommissioned ----------------------


def test_unknown_scan_and_unknown_agent(server: PgServer, db: AppDatabase) -> None:
    with pytest.raises(sv.ScanNotFound):
        sv.scan_detail(db, uuid4())
    with pytest.raises(sv.AgentNotFound):
        sv.agent_scans(db, uuid4(), 10, None)


@pytest.mark.parametrize("status", ["online", "decommissioned"])
def test_agent_history_three_of_five_newest_first(
    server: PgServer, db: AppDatabase, status: str
) -> None:
    """REQ-266 (1), (3): an agent in 3 of 5 scans gets exactly those,
    newest first; limit=1 visits each once; decommissioned too."""
    base = datetime(1991, 1, 1, tzinfo=UTC) + timedelta(days=10 * next(_WINDOWS))
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        me = m.host(c, status=status)
        other = m.host(c)
        mine: list[tuple[datetime, UUID]] = []
        for i in range(5):
            at = base + timedelta(hours=i)
            agents = (
                [me.agent_id, other.agent_id] if i in (0, 2, 3) else [other.agent_id]
            )
            sid = m.scan(c, pol, agents, created_at=at)
            if i in (0, 2, 3):
                mine.append((at, sid))
        # a scan whose request names the agent but whose resolved target does
        # not hold it: not in its history (the stored resolved target decides)
        m.scan(
            c,
            pol,
            [other.agent_id],
            request={"agents": [str(me.agent_id)]},
            created_at=base + timedelta(hours=9),
        )
    want = [sid for _, sid in sorted(mine, reverse=True)]
    assert [r.scan_id for r in sv.agent_scans(db, me.agent_id, 10, None)] == want
    seen: list[UUID] = []
    after: UUID | None = None
    for _ in range(10):
        page = sv.agent_scans(db, me.agent_id, 1, after)
        if not page:
            break
        assert len(page) == 1
        seen.append(page[0].scan_id)
        after = page[0].scan_id
    assert seen == want


# ----- CHK-M11-162: list filters, keyset, AnchorGone, target ---------------------


def test_list_scans_filters_keyset_and_anchor_gone(
    server: PgServer, db: AppDatabase
) -> None:
    base = datetime(1992, 1, 1, tzinfo=UTC) + timedelta(days=10 * next(_WINDOWS))
    with m.owner(server) as c:
        pols = [m.make_policy(c, 1), m.make_policy(c, 1)]
        a, b = m.host(c), m.host(c)
        plan = [
            (pols[0], base, "completed", [a, b]),
            (pols[1], base + timedelta(hours=1), "running", [b]),
            (pols[0], base + timedelta(hours=25), "partial", [a]),
            (pols[0], base + timedelta(hours=26), "running", [a, b]),
            (pols[1], base + timedelta(hours=26), "completed", [a]),
        ]
        made = []
        for pol, at, st, hs in plan:
            sid = m.scan(c, pol, [h.agent_id for h in hs], created_at=at, state=st)
            made.append((sid, pol.policy_id, at, st, {h.agent_id for h in hs}))
    end = base + timedelta(hours=48)

    def expect(**f: Any) -> list[UUID]:
        rows = [
            x
            for x in made
            if (f.get("policy_id") is None or x[1] == f["policy_id"])
            and (f.get("agent_id") is None or f["agent_id"] in x[4])
            and (f.get("state") is None or x[3] == f["state"])
            and x[2] >= f.get("created_after", base)
            and x[2] < f.get("created_before", end)
        ]
        return [
            x[0] for x in sorted(rows, key=lambda x: (x[2], x[0].int), reverse=True)
        ]

    def got(**f: Any) -> list[UUID]:
        filters = sv.ScanFilters(
            f.get("policy_id"),
            f.get("agent_id"),
            f.get("state"),
            f.get("created_after", base),
            f.get("created_before", end),
        )
        return [r.scan_id for r in sv.list_scans(db, filters, 500, None)]

    cases: list[dict[str, Any]] = [
        {},
        {"policy_id": pols[0].policy_id},
        {"agent_id": b.agent_id},
        {"state": "running"},
        {"created_after": base + timedelta(hours=25)},
        {"created_before": base + timedelta(hours=26)},
        {
            "policy_id": pols[0].policy_id,
            "agent_id": a.agent_id,
            "state": "running",
            "created_after": base + timedelta(hours=1),
            "created_before": base + timedelta(hours=27),
        },
    ]
    for f in cases:
        assert got(**f) == expect(**f), f
    assert (
        len(expect()) == 5
        and len(expect(created_after=base + timedelta(hours=25))) == 3
    )
    window = sv.ScanFilters(None, None, None, base, end)
    seen: list[UUID] = []
    after: UUID | None = None
    for _ in range(10):
        page = sv.list_scans(db, window, 2, after)
        if not page:
            break
        seen += [r.scan_id for r in page]
        after = page[-1].scan_id
    assert seen == expect()
    with m.owner(server) as c:
        c.execute("DELETE FROM scan WHERE scan_id = %s", (seen[1],))
    with pytest.raises(sv.AnchorGone):
        sv.list_scans(db, window, 2, seen[1])


@pytest.mark.parametrize(
    "request_",
    [None, {"tags": ["web", "db"]}, {"all": True}],
    ids=["agents", "tags", "all"],
)
def test_detail_target_is_the_request_without_resolved_agents(
    server: PgServer, db: AppDatabase, request_: dict[str, Any] | None
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        hs = [m.host(c), m.host(c)]
        sid = m.scan(c, pol, [h.agent_id for h in hs], request=request_)
    d = sv.scan_detail(db, sid)
    want = (
        request_ if request_ is not None else {"agents": [str(h.agent_id) for h in hs]}
    )
    assert d.target == want
    assert "resolved_agents" not in d.target
    assert d.scan.resolved_count == 2
    assert d.scan.target_kind == next(iter(want))
    assert d.hosts == []  # no job yet: no host
