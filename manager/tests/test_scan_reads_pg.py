"""TASK-234 TEST: the scan reads repository on PostgreSQL, as bitscan_app
(TP-M11-03; CHK-M11-105 to -114).

Expected values: REQ-264 (newest first: created_at desc then scan_id desc;
filters AND; created_after inclusive, created_before exclusive; agent_id = the
stored resolved target holds it), #89 and #145 (d) (cursor = scan_id only; a
deleted anchor is an error the route maps to 400), #145 (a)-(c) (scan item,
detail target without resolved_agents, host history through the stored
target), TS §4.3 L552 (scans of deleted policies stay readable), REQ-272 (5)
(SELECT only). Expected sets come from an oracle over the world description
written here, never from the repository.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import psycopg
import pytest

from bitscan_manager.repositories import scan_reads as sr

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

_WINDOWS = itertools.count()


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("scan-reads")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[m.Conn]:
    with m.app(server) as c:
        yield c


@dataclass(frozen=True)
class S:
    scan_id: UUID
    policy_id: int
    created_at: datetime
    state: str
    agents: tuple[UUID, ...]
    kind: str


@dataclass
class World:
    base: datetime
    end: datetime
    pols: list[m.Pol]
    agents: dict[str, m.AgentRow]
    scans: list[S]


def world(server: PgServer) -> World:
    """Five scans of two policies in three states over two days, with
    overlapping resolved targets, in a time window of this test's own (so
    other tests' scans never fall inside it)."""
    base = datetime(1990, 1, 1, tzinfo=UTC) + timedelta(days=10 * next(_WINDOWS))
    with m.owner(server) as c:
        pols = [m.make_policy(c, 1), m.make_policy(c, 1)]
        ag = {k: m.host(c, at=base) for k in "ABC"}
        a, b, cc = (ag[k].agent_id for k in "ABC")
        plan = [
            (pols[0], base, "completed", (a, b), None),
            (pols[1], base + timedelta(hours=1), "running", (b, cc), None),
            (pols[0], base + timedelta(hours=25), "partial", (a,), None),
            # a tag equal to A's id text: must never match agent A (CHK-M11-108)
            (
                pols[1],
                base + timedelta(hours=26),
                "completed",
                (cc,),
                {"tags": [str(a)]},
            ),
            (pols[0], base + timedelta(hours=26), "running", (a, cc), {"all": True}),
        ]
        scans = []
        for pol, at, state, agents, req in plan:
            sid = m.scan(c, pol, list(agents), request=req, created_at=at, state=state)
            kind = "agents" if req is None else next(iter(req))
            scans.append(S(sid, pol.policy_id, at, state, agents, kind))
    return World(base, base + timedelta(hours=48), pols, ag, scans)


def order(scans: list[S]) -> list[UUID]:
    """REQ-264: created_at descending, then scan_id descending (as UUIDs
    compare in PostgreSQL: by their bytes, which equals Python's int order)."""
    return [
        s.scan_id
        for s in sorted(
            scans, key=lambda s: (s.created_at, s.scan_id.int), reverse=True
        )
    ]


def page(conn: m.Conn, w: World, **kw: Any) -> list[sr.ScanRow]:
    args: dict[str, Any] = {
        "policy_id": None,
        "agent_id": None,
        "state": None,
        "created_after": w.base,
        "created_before": w.end,
        "limit": 500,
        "after": None,
    }
    return sr.scan_page(conn, **(args | kw))


def ids(rows: list[sr.ScanRow]) -> list[UUID]:
    return [r.scan_id for r in rows]


# ------------------------------------------------------------ CHK-M11-105


def test_no_filter_newest_first_with_scan_id_tiebreak(
    server: PgServer, conn: m.Conn
) -> None:
    w = world(server)
    got = page(conn, w)
    assert ids(got) == order(w.scans)
    tied = [s for s in w.scans if s.created_at == w.base + timedelta(hours=26)]
    assert len(tied) == 2  # the tie the scan_id order breaks


def test_scan_row_fields(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    rows = {r.scan_id: r for r in page(conn, w)}
    for s in w.scans:
        r = rows[s.scan_id]
        pol = next(p for p in w.pols if p.policy_id == s.policy_id)
        assert (r.policy_id, r.policy_name, r.policy_version) == (
            pol.policy_id,
            pol.name,
            1,
        )
        assert (str(r.state), r.target_kind, r.resolved_count) == (
            s.state,
            s.kind,
            len(s.agents),
        )
        assert r.created_at == s.created_at and r.finished_at is None
        assert (r.trigger, r.schedule_id, r.requested_by) == ("manual", None, None)


# ------------------------------------------------------------ CHK-M11-106


def test_each_filter_alone_and_all_together(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    a = w.agents["A"].agent_id
    p0 = w.pols[0].policy_id
    day2 = w.base + timedelta(hours=25)
    cases: list[tuple[dict[str, Any], list[S]]] = [
        ({"policy_id": p0}, [s for s in w.scans if s.policy_id == p0]),
        ({"agent_id": a}, [s for s in w.scans if a in s.agents]),
        ({"state": "running"}, [s for s in w.scans if s.state == "running"]),
        ({"state": "queued"}, []),
        ({"created_after": day2}, [s for s in w.scans if s.created_at >= day2]),
        ({"created_before": day2}, [s for s in w.scans if s.created_at < day2]),
        (
            {"policy_id": p0, "agent_id": a, "state": "running", "created_after": day2},
            [
                s
                for s in w.scans
                if s.policy_id == p0
                and a in s.agents
                and s.state == "running"
                and s.created_at >= day2
            ],
        ),
    ]
    for kw, want in cases:
        assert ids(page(conn, w, **kw)) == order(want), kw
    assert len(cases[-1][1]) == 1


def test_date_bounds_inclusive_and_exclusive(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    s = w.scans[2]
    at = page(
        conn, w, created_after=s.created_at, created_before=s.created_at + m.MICRO
    )
    assert ids(at) == [s.scan_id]
    assert page(conn, w, created_after=s.created_at, created_before=s.created_at) == []
    before = page(conn, w, created_before=s.created_at)
    assert s.scan_id not in ids(before)


def test_times_with_any_offset(server: PgServer, conn: m.Conn) -> None:
    """Aware times in any zone select by instant; +18:00 is accepted
    (PostgreSQL alone refuses offsets past ±15:59)."""
    w = world(server)
    plus18 = timezone(timedelta(hours=18))
    got = page(conn, w, created_after=w.base.astimezone(plus18))
    assert ids(got) == order(w.scans)
    with pytest.raises(ValueError):
        page(conn, w, created_after=datetime(1990, 1, 1))


# ------------------------------------------------------------ CHK-M11-107


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize(
    "kw", [{}, {"policy_id": "p0"}, {"agent_id": "A"}, {"state": "completed"}]
)
def test_keyset_limit_2_visits_every_scan_once(
    server: PgServer, conn: m.Conn, kw: dict[str, Any], limit: int
) -> None:
    """limit 1 makes the created_at tie straddle a page boundary."""
    w = world(server)
    real = {
        k: (
            w.pols[0].policy_id
            if v == "p0"
            else w.agents["A"].agent_id
            if v == "A"
            else v
        )
        for k, v in kw.items()
    }
    want = ids(page(conn, w, **real))
    seen: list[UUID] = []
    after: UUID | None = None
    for _ in range(10):
        got = page(conn, w, limit=limit, after=after, **real)
        assert len(got) <= limit
        if not got:
            break
        seen += ids(got)
        after = got[-1].scan_id
    assert seen == want and len(set(seen)) == len(seen)


# ------------------------------------------------------------ CHK-M11-108


def test_agent_filter_matches_the_resolved_list_only(
    server: PgServer, conn: m.Conn
) -> None:
    w = world(server)
    a = w.agents["A"].agent_id
    tag_scan = w.scans[3]
    got = ids(page(conn, w, agent_id=a))
    assert tag_scan.scan_id not in got
    assert set(got) == {s.scan_id for s in w.scans if a in s.agents}


# ------------------------------------------------------------ CHK-M11-109


def test_a_deleted_anchor_raises_anchor_gone(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    first = page(conn, w, limit=2)
    with m.owner(server) as c:
        c.execute("DELETE FROM scan WHERE scan_id = %s", (first[-1].scan_id,))
    with pytest.raises(sr.AnchorGone):
        page(conn, w, limit=2, after=first[-1].scan_id)
    with pytest.raises(sr.AnchorGone):
        sr.agent_scan_page(
            conn, w.agents["A"].agent_id, limit=2, after=first[-1].scan_id
        )


# ------------------------------------------------------------ CHK-M11-110


def test_scan_detail(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    s = w.scans[3]
    got = sr.scan_detail(conn, s.scan_id)
    assert got is not None
    assert got.scan.scan_id == s.scan_id and got.scan.policy_name == w.pols[1].name
    assert got.target == {"tags": [str(w.agents["A"].agent_id)]}
    assert "resolved_agents" not in got.target
    with m.owner(server) as c:
        m.soft_delete(c, w.pols[1])
    again = sr.scan_detail(conn, s.scan_id)
    assert again is not None and again.scan.policy_name == w.pols[1].name
    assert sr.scan_detail(conn, UUID(int=s.scan_id.int ^ 1)) is None


# ------------------------------------------------------------ CHK-M11-111


def test_scan_jobs_with_hostnames_in_detail_order(
    server: PgServer, conn: m.Conn
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 2)
        hosts = [m.host(c, "zeta"), m.host(c, "alpha"), m.host(c, "alpha")]
        sid = m.scan(c, pol, [h.agent_id for h in hosts])
        made: list[tuple[str, UUID, bool, UUID, str]] = []
        states = iter(m.JOB_STATES)
        for h, name in zip(hosts, ("zeta", "alpha", "alpha"), strict=True):
            st = next(states)
            orig = m.job(c, sid, h.agent_id, pol, state=st)
            made.append((name, h.agent_id, False, orig.job_id, st))
            retry = m.job(
                c,
                sid,
                h.agent_id,
                pol,
                pol.plugins[1:],
                state="completed",
                created_at=m.T0 + timedelta(minutes=5),
                retry_of=orig.job_id,
            )
            made.append((name, h.agent_id, True, retry.job_id, "completed"))
        f9.owner_inventory_job(c, hosts[0].agent_id)
    got = sr.scan_jobs(conn, sid)
    want = sorted(made, key=lambda t: (t[0], t[1].int, t[2]))
    assert [
        (j.hostname, j.agent_id, j.retry_of is not None, j.job_id, str(j.state))
        for j in got
    ] == want
    retries = {j.job_id: j.retry_of for j in got if j.retry_of is not None}
    assert set(retries.values()) == {t[3] for t in made if not t[2]}


# ------------------------------------------------------------ CHK-M11-112


def test_agent_history(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    a = w.agents["A"].agent_id
    want = order([s for s in w.scans if a in s.agents])
    assert len(want) == 3
    assert ids(sr.agent_scan_page(conn, a, limit=500, after=None)) == want
    seen: list[UUID] = []
    after: UUID | None = None
    for _ in range(6):
        got = sr.agent_scan_page(conn, a, limit=1, after=after)
        if not got:
            break
        assert len(got) == 1
        seen.append(got[0].scan_id)
        after = got[0].scan_id
    assert seen == want
    assert sr.agent_exists(conn, a) is True
    assert sr.agent_exists(conn, UUID(int=a.int ^ 1)) is False


def test_decommissioned_agent_history(server: PgServer, conn: m.Conn) -> None:
    w = world(server)
    b = w.agents["B"].agent_id
    with m.owner(server) as c:
        c.execute(
            "UPDATE agent SET status = 'decommissioned' WHERE agent_id = %s", (b,)
        )
    assert sr.agent_exists(conn, b) is True
    assert ids(sr.agent_scan_page(conn, b, limit=50, after=None)) == order(
        [s for s in w.scans if b in s.agents]
    )


# ------------------------------------------------------------ CHK-M11-113, -114


def test_select_only_as_bitscan_app(
    server: PgServer, conn: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(server)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    first = page(conn, w, limit=2, agent_id=w.agents["A"].agent_id)
    page(conn, w, limit=2, after=first[-1].scan_id)
    sr.scan_detail(conn, w.scans[0].scan_id)
    sr.scan_jobs(conn, w.scans[0].scan_id)
    sr.agent_scan_page(conn, w.agents["A"].agent_id, limit=1, after=first[0].scan_id)
    sr.agent_exists(conn, w.agents["A"].agent_id)
    monkeypatch.undo()
    assert spy.statements, "the spy saw nothing"
    assert set(spy.roles) == {"bitscan_app"}
    for text in spy.statements:
        words = text.upper().replace("(", " ").replace(")", " ").split()
        assert words[0] in {"SELECT", "WITH"}, text
        assert not set(words) & (m.WRITE_VERBS | m.DDL_VERBS | {"FOR"}), text
        assert str(w.agents["A"].agent_id) not in text, "ids are parameters"


def test_wrong_grants_would_be_seen(server: PgServer) -> None:
    """The reads hold no write: under a read-only transaction they all work."""
    with psycopg.connect(server.dsn("bitscan_app")) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        sr.scan_page(
            c,
            policy_id=None,
            agent_id=None,
            state=None,
            created_after=None,
            created_before=None,
            limit=1,
            after=None,
        )
        c.rollback()
