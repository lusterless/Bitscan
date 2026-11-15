"""TASK-193 TEST: the scan queue repository on PostgreSQL as bitscan_app
(TP-M9-10; CHK-M9-110 to -113; mutation rows CHK-M9-352 to -356, -358,
-381).

Expected values: TS §4.4 L555 (targets resolved at queue time to agents that
are not decommissioned or awaiting approval; offline agents still get jobs;
tags any-of), L558 (a newer queued job for the same agent and policy cancels
the older queued one), L566 (pickup_by = creation + 24 h), §6.5 L1165–L1182
(the Job body), §5.2 (scan_job columns and grants); #122 (c), #125 (a)–(f);
REQ-208 (3), REQ-211, REQ-230. The payload expected here is the test's own
TS §6.5 builder (``scan_pg_fixtures.payload_of``), not the product's.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.repositories import scan_queue as sq
from bitscan_manager.services.jobs import build

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sq")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    with f.app_database(server) as db:
        yield f.make_catalog(db, f.Clock(), tmp_path)


def statements(spy: f.StatementSpy) -> list[str]:
    return [s for s in spy.statements if not s.startswith("SELECT session_user")]


# ------------------------------------------------------------ CHK-M9-110


def test_resolution_follows_status_tags_and_ids(
    server: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-208 (3), TS §4.4 L555, #122 (c), CHK-M9-354 to -356: every earlier
    agent of this module's database is decommissioned first, so ``all`` is
    exactly this fleet's enrolled, online, stale and offline agents, sorted;
    tags match any-of (an agent holding both appears once); listed ids keep
    only eligible known agents."""
    a, b, c = f.new_tag(), f.new_tag(), f.new_tag()
    with f.app(server) as conn:
        conn.execute("UPDATE agent SET status = 'decommissioned'")
        fleet_a = f.fleet(conn, [a])
        both = f.make_agent(conn, "online", tags=[a, b])
        only_b = f.make_agent(conn, "offline", tags=[b])
        only_b_awaiting = f.make_agent(conn, "awaiting_approval", tags=[b])
        only_c = f.make_agent(conn, "stale", tags=[c])
        eligible_a = [fleet_a[s].agent_id for s in f.ELIGIBLE]
        want_all = sorted(
            [*eligible_a, both.agent_id, only_b.agent_id, only_c.agent_id]
        )
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        got_all = sq.resolve_agents(conn, "all", [], [])
        assert len(statements(spy)) == 1
        assert got_all == want_all
        assert sq.resolve_agents(conn, "tags", [], [a, b]) == sorted(
            [*eligible_a, both.agent_id, only_b.agent_id]
        )
        assert sq.resolve_agents(conn, "tags", [], [c]) == [only_c.agent_id]
        assert sq.resolve_agents(conn, "tags", [], ["m9.nobody"]) == []
        x = fleet_a["offline"].agent_id
        listed = [
            x,
            uuid4(),
            fleet_a["decommissioned"].agent_id,
            fleet_a["awaiting_approval"].agent_id,
            only_b_awaiting.agent_id,
        ]
        assert sq.resolve_agents(conn, "agents", listed, []) == [x]
        two = sorted([fleet_a["enrolled"].agent_id, fleet_a["stale"].agent_id])
        assert sq.resolve_agents(conn, "agents", list(reversed(two)), []) == two
        with pytest.raises(ValueError):
            sq.resolve_agents(conn, "hosts", [], [])


# ------------------------------------------------------------ CHK-M9-111


def test_snapshot_is_one_statement_of_active_plugins_in_sort_order(
    server: PgServer, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#125 (a), (d), CHK-M9-352: after the FOR SHARE, ONE statement gives the
    version, status, deleted flag and the active plugins in sort_order with
    the v_plugin display name (SR §1.1), plus execute, timeout_s, operator
    and expected. A re-import that reverses the document order reverses the
    snapshot (SR §2.3); a listed plugin made retired by owner is left out."""
    defs = [f.sr_plugin(), f.plugin(timeout_s=7), f.plugin(operator="not_empty")]
    pol = cat.policy(defs, family=f.SR_FAMILY)
    cat.reimport(pol, list(reversed(defs)))
    with f.owner(server) as o:
        o.execute(
            "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
            (defs[1].plugin_uuid,),
        )
    with f.app(server, autocommit=False) as conn:
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        snap = sq.policy_snapshot(conn, pol.policy_id)
        sts = statements(spy)
        conn.rollback()
    assert snap is not None
    assert len(sts) == 2, sts
    assert "FOR SHARE" in sts[0].upper()
    assert "FOR SHARE" not in sts[1].upper()
    assert (snap.policy_id, snap.version, snap.status, snap.deleted) == (
        pol.policy_id,
        pol.version,
        "enabled",
        False,
    )
    want = [defs[2], defs[0]]
    assert [p.plugin_uuid for p in snap.plugins] == [p.plugin_uuid for p in want]
    for got, d in zip(snap.plugins, want, strict=True):
        assert (got.display_name, got.execute, got.timeout_s) == (
            pol.display(d),
            d.execute,
            d.timeout_s,
        )
        assert (got.operator, got.expected) == (d.operator, d.expected)
    assert (
        snap.plugins[1].display_name
        == "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed"
    )


def test_snapshot_flags_disabled_deleted_unknown_and_no_plugins(
    server: PgServer, cat: f.Catalog
) -> None:
    """The snapshot reports what the service refuses (REQ-211 (2)):
    status disabled, deleted (TS §4.3 L550 soft delete), an unknown id
    (None), and a listed set with no active plugin (#125 (h))."""
    off = cat.policy(2, status="disabled")
    gone = cat.policy(1)
    cat.delete(gone)
    empty = cat.policy(1)
    with f.owner(server) as o:
        o.execute(
            "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
            (empty.uuids[0],),
        )
    with f.app(server, autocommit=False) as conn:
        s_off = sq.policy_snapshot(conn, off.policy_id)
        s_gone = sq.policy_snapshot(conn, gone.policy_id)
        s_empty = sq.policy_snapshot(conn, empty.policy_id)
        assert sq.policy_snapshot(conn, 2**62) is None
        conn.rollback()
    assert s_off is not None and s_off.status == "disabled" and not s_off.deleted
    assert len(s_off.plugins) == 2
    assert s_gone is not None and s_gone.deleted
    assert s_empty is not None and s_empty.plugins == []


def test_policy_row_is_share_locked_until_the_scan_commits(
    server: PgServer, cat: f.Catalog
) -> None:
    """#125 (d), CHK-M9-353: a policy UPDATE (what a delete or an import does
    first) in a second session waits on the snapshot's FOR SHARE until the
    scan transaction ends, then proceeds."""
    pol = cat.policy(1)
    with f.app(server, autocommit=False) as a, f.app(server) as b:
        assert sq.policy_snapshot(a, pol.policy_id) is not None
        pid = f.backend_pid(b)
        done = threading.Event()

        def writer() -> None:
            b.execute(
                "UPDATE policy SET updated_at = now() WHERE policy_id = %s",
                (pol.policy_id,),
            )
            done.set()

        t = threading.Thread(target=writer)
        t.start()
        try:
            f.wait_until_lock_waiting(server, pid)
            assert not done.is_set()
        finally:
            a.commit()
            t.join(10)
        assert done.is_set()


def test_queue_lock_serialises_one_policy_and_not_another(
    server: PgServer, cat: f.Catalog
) -> None:
    """#125 (d): the per-policy transaction lock makes a second scan of the
    same policy wait until the first ends; another policy does not wait."""
    p1, p2 = cat.policy(1), cat.policy(1)
    with (
        f.app(server, autocommit=False) as a,
        f.app(server, autocommit=False) as b,
    ):
        sq.lock_policy_queue(a, p1.policy_id)
        sq.lock_policy_queue(b, p2.policy_id)  # returns at once
        b.rollback()
        pid = f.backend_pid(b)
        done = threading.Event()

        def second() -> None:
            sq.lock_policy_queue(b, p1.policy_id)
            done.set()

        t = threading.Thread(target=second)
        t.start()
        try:
            f.wait_until_lock_waiting(server, pid)
            assert not done.is_set()
        finally:
            a.rollback()  # a transaction lock: released at the end
            t.join(10)
        assert done.is_set()
        b.rollback()


# ------------------------------------------------------------ CHK-M9-112


def _spec_and_plugins(pol: f.Pol) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plugins = f.payload_of(uuid4(), uuid4(), f.T0, pol.plugins)["plugins"]
    return plugins, f.eval_spec_of(pol, pol.plugins)


def test_scan_and_jobs_insert_in_one_statement_with_the_spec_payload(
    server: PgServer, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-209 (1), #125 (c), (f), CHK-M9-112: one INSERT for N jobs; each
    payload is exactly the TS §6.5 Job (six keys, job_id = row id,
    lowercase ids, pickup_by text), validates ComplianceJob, equals the
    pure builder's ``payload()`` for the same ids; created_at = the scan's;
    eval_spec stored as given; state queued."""
    pol = cat.policy(3)
    patterns = [r"(?i)password=\S+", r"bsa_[A-Za-z0-9_-]+"]
    plugins, spec = _spec_and_plugins(pol)
    created = f.T0 + timedelta(microseconds=654_321)
    with f.app(server) as conn:
        agents = [f.make_agent(conn).agent_id for _ in range(3)]
    jobs = [uuid4() for _ in agents]
    target = {"all": True, "resolved_agents": sorted(str(a) for a in agents)}
    with f.app(server, autocommit=False) as conn:
        sid = sq.insert_scan(
            conn,
            policy_id=pol.policy_id,
            policy_version=pol.version,
            trigger="scheduled",
            schedule_id=None,
            target_json=target,
            requested_by=42,
            created_at=created,
        )
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        n = sq.insert_jobs(
            conn,
            scan_id=sid,
            policy_id=pol.policy_id,
            agent_ids=agents,
            job_ids=jobs,
            created_at=created,
            pickup_by=created + timedelta(hours=24),
            pickup_text=f.zsec(created + timedelta(hours=24)),
            plugins_json=plugins,
            patterns=patterns,
            eval_spec_json=spec,
        )
        sts = statements(spy)
        monkeypatch.undo()
        conn.commit()
    assert n == sq.JobsInserted(queued=3, already_running=0)
    assert [s.split(None, 1)[0].upper() for s in sts] == ["INSERT"]
    with f.app(server) as conn:
        scan = f.scan_row(conn, sid)
        rows = {r["job_id"]: r for r in f.jobs_of_scan(conn, sid)}
    assert scan["target"] == target and scan["state"] == "queued"
    assert (scan["policy_version"], scan["trigger"], scan["requested_by"]) == (
        pol.version,
        "scheduled",
        42,
    )
    assert scan["created_at"] == created
    for jid, aid in zip(jobs, agents, strict=True):
        r = rows[jid]
        want = f.payload_of(jid, aid, created, pol.plugins, patterns)
        assert r["payload"] == want
        assert list(r["payload"]) != [] and set(r["payload"]) == set(want)
        assert r["payload"]["job_id"] == str(jid) == str(jid).lower()
        assert r["payload"]["agent_id"] == str(aid).lower()
        schemas.ComplianceJob.model_validate(r["payload"])
        assert r["eval_spec"] == spec
        assert (r["state"], r["agent_id"], r["created_at"]) == ("queued", aid, created)
        assert r["pickup_by"] == created + timedelta(hours=24)
        assert r["retry_of"] is None and r["dispatched_at"] is None
        built = build.plugins_and_spec(
            [
                build.CatalogPlugin(
                    p.plugin_uuid,
                    pol.display(p),
                    p.execute,
                    p.timeout_s,
                    p.operator,
                    p.expected,
                )
                for p in pol.plugins
            ],
            patterns,
        )
        assert r["payload"] == build.payload(jid, aid, created, built)


def test_ten_thousand_jobs_are_still_one_insert(
    server: PgServer, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#122 (b) AGENTS_MAX boundary, D1: a 10,000-agent scan's jobs are one
    INSERT statement, each with its own job_id in its payload."""
    pol = cat.policy(1)
    plugins, spec = _spec_and_plugins(pol)
    with f.owner(server) as o:
        rows = o.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status)"
            " SELECT md5('m9b-' || g || %s), 'bulk-' || g, '1.0.0',"
            " encode(sha256(convert_to('m9b' || g || %s, 'UTF8')), 'hex'),"
            " now(), now() + interval '30 days', 'offline'"
            " FROM generate_series(1, 10000) g RETURNING agent_id",
            (str(uuid4()), str(uuid4())),
        ).fetchall()
    agents = [UUID(str(r[0])) for r in rows]
    jobs = [uuid4() for _ in agents]
    with f.app(server, autocommit=False) as conn:
        sid = sq.insert_scan(
            conn,
            policy_id=pol.policy_id,
            policy_version=pol.version,
            trigger="manual",
            schedule_id=None,
            target_json={"all": True, "resolved_agents": []},
            requested_by=1,
            created_at=f.T0,
        )
        spy = f.StatementSpy()
        spy.install(monkeypatch)
        n = sq.insert_jobs(
            conn,
            scan_id=sid,
            policy_id=pol.policy_id,
            agent_ids=agents,
            job_ids=jobs,
            created_at=f.T0,
            pickup_by=f.T0 + timedelta(hours=24),
            pickup_text=f.zsec(f.T0 + timedelta(hours=24)),
            plugins_json=plugins,
            patterns=[],
            eval_spec_json=spec,
        )
        assert len(statements(spy)) == 1
        monkeypatch.undo()
        bad = conn.execute(
            "SELECT count(*) FROM scan_job WHERE scan_id = %s"
            " AND (payload->>'job_id')::uuid <> job_id",
            (sid,),
        ).fetchone()
        conn.rollback()
    assert n == sq.JobsInserted(queued=10_000, already_running=0) and bad == (0,)


def test_insert_jobs_refuses_mismatched_or_empty_ids_writing_nothing(
    server: PgServer, cat: f.Catalog
) -> None:
    pol = cat.policy(1)
    plugins, spec = _spec_and_plugins(pol)
    with f.app(server) as conn:
        a = f.make_agent(conn).agent_id
        before = f.counts(conn)
    with f.app(server, autocommit=False) as conn:
        sid = sq.insert_scan(
            conn,
            policy_id=pol.policy_id,
            policy_version=pol.version,
            trigger="manual",
            schedule_id=None,
            target_json={"agents": [str(a)], "resolved_agents": [str(a)]},
            requested_by=1,
            created_at=f.T0,
        )
        kw: dict[str, Any] = {
            "scan_id": sid,
            "policy_id": pol.policy_id,
            "created_at": f.T0,
            "pickup_by": f.T0 + timedelta(hours=24),
            "pickup_text": f.zsec(f.T0 + timedelta(hours=24)),
            "plugins_json": plugins,
            "patterns": [],
            "eval_spec_json": spec,
        }
        for agents, jobs in (([a], []), ([], []), ([a, a], [uuid4()])):
            with pytest.raises(ValueError):
                sq.insert_jobs(conn, agent_ids=agents, job_ids=jobs, **kw)
        conn.rollback()
    with f.app(server) as conn:
        assert f.counts(conn) == before


# ------------------------------------------------------------ CHK-M9-113


def test_cancel_older_queued_touches_only_that_policys_queued_jobs(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L558, #125 (e), REQ-211 (3), CHK-M9-358, -381: only queued
    compliance jobs (originals and retries) of earlier scans of THIS policy
    for the listed agents become cancelled with finished_at = now; the new
    scan's own jobs, dispatched jobs, unlisted agents, another policy's
    queued job and every inventory job are byte-identical afterwards."""
    pol, other = cat.policy(2), cat.policy(1)
    now = f.T0 + timedelta(hours=1)
    with f.app(server) as conn:
        a1, a2, a3 = (f.make_agent(conn).agent_id for _ in range(3))
    with f.owner(server) as o:
        s0 = f.owner_scan(o, pol, state="partial", created_at=f.T0 - timedelta(hours=3))
        orig = f.owner_job(
            o, s0, a1, pol, state="failed", created_at=f.T0 - timedelta(hours=3)
        )
        retry = f.owner_job(
            o,
            s0,
            a1,
            pol,
            pol.plugins[1:],
            state="queued",
            retry_of=orig.job_id,
            created_at=f.T0 - timedelta(hours=2),
        )
        s1 = f.owner_scan(o, pol, created_at=f.T0 - timedelta(hours=1))
        q1 = f.owner_job(o, s1, a1, pol, created_at=f.T0 - timedelta(hours=1))
        q2 = f.owner_job(o, s1, a2, pol, created_at=f.T0 - timedelta(hours=1))
        d3 = f.owner_job(
            o, s1, a3, pol, state="dispatched", created_at=f.T0 - timedelta(hours=1)
        )
        so = f.owner_scan(o, other)
        qo = f.owner_job(o, so, a1, other)
        inv = [f.owner_inventory_job(o, a) for a in (a1, a3)]
        s2 = f.owner_scan(o, pol, created_at=now)
        new1 = f.owner_job(o, s2, a1, pol, created_at=now)
        new3 = f.owner_job(o, s2, a3, pol, created_at=now)
        untouched = [
            orig.job_id,
            q2.job_id,
            d3.job_id,
            qo.job_id,
            *inv,
            new1.job_id,
            new3.job_id,
        ]
        before = {j: f.job_state(o, j) for j in untouched}
        scans_before = f.checksum(o, "scan")
    with f.app(server, autocommit=False) as conn:
        got = sq.cancel_older_queued(
            conn, policy_id=pol.policy_id, agent_ids=[a1, a3], new_scan_id=s2, now=now
        )
        conn.commit()
    assert got == sorted([q1.job_id, retry.job_id])
    with f.owner(server) as o:
        for jid in got:
            st = f.job_state(o, jid)
            assert (st["state"], st["finished_at"]) == ("cancelled", now)
        for jid, row in before.items():
            assert f.job_state(o, jid) == row, jid
        assert f.checksum(o, "scan") == scans_before
    with f.app(server, autocommit=False) as conn:  # nothing left to cancel
        assert (
            sq.cancel_older_queued(
                conn,
                policy_id=pol.policy_id,
                agent_ids=[a1, a3],
                new_scan_id=s2,
                now=now,
            )
            == []
        )
        conn.rollback()


def test_repository_runs_with_app_grants_only(server: PgServer, cat: f.Catalog) -> None:
    """REQ-230 (3): the role the repository runs as cannot move a job or
    rewrite its payload (the TS §8.3 'cannot move a job to another host or
    scan' probe), so nothing here could; the grant refusal is an error."""
    pol = cat.policy(1)
    with f.app(server) as conn:
        a = f.make_agent(conn).agent_id
    with f.owner(server) as o:
        sid = f.owner_scan(o, pol)
        job = f.owner_job(o, sid, a, pol)
    for col, value in (
        ("agent_id", str(uuid4())),
        ("scan_id", str(uuid4())),
        ("payload", "{}"),
        ("eval_spec", "{}"),
        ("retry_of", str(job.job_id)),
    ):
        with f.app(server) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                f"UPDATE scan_job SET {col} = %s WHERE job_id = %s",  # noqa: S608 - fixed column list
                (value, job.job_id),
            )
    scan_cols: list[tuple[str, object]] = [
        ("policy_id", 1),
        ("policy_version", 9),
        ("target", "{}"),
    ]
    for scol, svalue in scan_cols:
        with f.app(server) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                f"UPDATE scan SET {scol} = %s WHERE scan_id = %s",  # noqa: S608 - fixed column list
                (svalue, sid),
            )
