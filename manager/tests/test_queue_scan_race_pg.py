"""TASK-198 TEST: queue races on PostgreSQL (TP-M9-11; CHK-M9-150 to -152;
mutation row CHK-M9-353).

REQ-211 (4), #125 (d): the scan takes a per-policy transaction lock, then the
policy row FOR SHARE, then one snapshot statement, so a policy delete or an
import commits wholly before the scan (the scan sees it) or after it (the
delete's cancel sees the scan's queued jobs; the import does not change the
scan's version, commands or eval_spec). TS §4.3 L550 (delete cancels queued
jobs), §4.1 L530, §4.4 L558, L560. Ordering is forced with a gate inside the
scan (after its snapshot, before its writes) and a lock-wait probe, or with
a barrier for unforced rounds; never with sleeps.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import scan_queue
from bitscan_manager.services.jobs import queue
from bitscan_manager.services.jobs.targets import parse_target

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=2)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("queue-race")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server, max_size=8) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


def do_scan(db: AppDatabase, pid: int, target: Any) -> queue.ScanQueued:
    with db.transaction() as tx:
        return queue.queue_scan(
            tx,
            policy_id=pid,
            target=parse_target(target),
            trigger="manual",
            schedule_id=None,
            requested_by=1,
            actor="user:1",
            via_api_token=False,
            now=NOW,
        )


def gated_resolve(monkeypatch: pytest.MonkeyPatch, gate: f.Gate) -> None:
    """The scan parks after its snapshot (FOR SHARE held), before any write."""
    real = scan_queue.resolve_agents

    def parked(*a: Any, **k: Any) -> Any:
        gate.wait()
        return real(*a, **k)

    monkeypatch.setattr(scan_queue, "resolve_agents", parked)


def queued_of_deleted_policies(server: PgServer) -> int:
    with f.app(server) as c:
        return int(
            f.one(
                c,
                (
                    "SELECT count(*) FROM scan_job j"
                    " JOIN scan s ON s.scan_id = j.scan_id"
                    " JOIN policy p ON p.policy_id = s.policy_id"
                    " WHERE p.deleted_at IS NOT NULL AND j.state = 'queued'"
                ),
            )
        )


# ------------------------------------------------------------ CHK-M9-150


def test_a_delete_started_during_the_scan_waits_and_cancels_its_jobs(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan holds the policy row FOR SHARE; M7's delete, started while
    the scan is parked, waits on it (probe); after the scan commits, the
    delete cancels the scan's queued jobs. No queued job of a deleted policy
    remains (CHK-M9-353)."""
    pol = cat.policy(1)
    with f.app(server) as c:
        agents = [str(f.make_agent(c).agent_id) for _ in range(3)]
    gate = f.Gate()
    gated_resolve(monkeypatch, gate)
    out: dict[str, Any] = {}
    t1 = threading.Thread(
        target=lambda: out.setdefault(
            "scan", do_scan(db, pol.policy_id, {"agents": agents})
        )
    )
    t1.start()
    assert gate.reached.wait(30)
    t2 = threading.Thread(target=lambda: out.setdefault("delete", cat.delete(pol)))
    t2.start()
    try:
        f.wait_until_any_waiter(server)
    finally:
        gate.open()
        t1.join(30)
        t2.join(30)
    scan = out["scan"]
    assert scan.jobs == 3 and "delete" in out
    with f.app(server) as c:
        states = [j["state"] for j in f.jobs_of_scan(c, scan.scan_id)]
    assert states == ["cancelled"] * 3
    assert queued_of_deleted_policies(server) == 0


def test_a_delete_committed_before_the_scan_refuses_it(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    pol = cat.policy(1)
    with f.app(server) as c:
        a = str(f.make_agent(c).agent_id)
        before = f.counts(c)
    cat.delete(pol)
    with f.app(server) as c:
        before = f.counts(c)
    with pytest.raises(queue.PolicyDeleted):
        do_scan(db, pol.policy_id, {"agents": [a]})
    with f.app(server) as c:
        assert f.counts(c) == before


def test_unforced_delete_and_scan_rounds_never_leave_a_queued_job(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """20 rounds released by one barrier: whichever commits first, the policy
    ends deleted with no queued job; the scan either refused (PolicyDeleted)
    or its jobs were cancelled by the delete."""
    with f.app(server) as c:
        agents = [str(f.make_agent(c).agent_id) for _ in range(2)]
    for n in range(20):
        pol = cat.policy(1)
        barrier = threading.Barrier(2, timeout=30)

        def s(pol: f.Pol = pol, barrier: threading.Barrier = barrier) -> Any:
            barrier.wait()
            return do_scan(db, pol.policy_id, {"agents": agents})

        def d(pol: f.Pol = pol, barrier: threading.Barrier = barrier) -> Any:
            barrier.wait()
            return cat.delete(pol)

        outs = f.run_threads([s, d])
        assert outs[1].error is None, (n, outs[1].error)
        assert outs[0].error is None or isinstance(
            outs[0].error, queue.PolicyDeleted
        ), n
        assert queued_of_deleted_policies(server) == 0, n


# ------------------------------------------------------------ CHK-M9-151


def test_an_import_during_the_scan_never_mixes_versions(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-211 (4): an import that changes an Execute and bumps the version,
    started while the scan is parked after its snapshot, waits; the scan's
    recorded version, its jobs' commands and their eval_spec all belong to
    the version before the import. A scan after the import has the new ones."""
    old = f.plugin(expected="v1")
    pol = cat.policy([old])
    v1 = pol.version
    with f.app(server) as c:
        a = str(f.make_agent(c).agent_id)
    gate = f.Gate()
    gated_resolve(monkeypatch, gate)
    new = replace(old, execute="echo version-two", expected="v2")
    out: dict[str, Any] = {}
    t1 = threading.Thread(
        target=lambda: out.setdefault(
            "scan", do_scan(db, pol.policy_id, {"agents": [a]})
        )
    )
    t1.start()
    assert gate.reached.wait(30)
    t2 = threading.Thread(
        target=lambda: out.setdefault("imp", cat.reimport(pol, [new]))
    )
    t2.start()
    try:
        f.wait_until_any_waiter(server)
    finally:
        gate.open()
        t1.join(30)
        t2.join(30)
    monkeypatch.undo()
    scan = out["scan"]
    with f.app(server) as c:
        (j,) = f.jobs_of_scan(c, scan.scan_id)
        row = f.scan_row(c, scan.scan_id)
    assert (scan.policy_version, row["policy_version"]) == (v1, v1)
    assert j["payload"]["plugins"][0]["execute"] == old.execute
    assert j["eval_spec"]["plugins"][0]["expected"] == "v1"
    assert pol.version == v1 + 1
    after = do_scan(db, pol.policy_id, {"agents": [a]})
    with f.app(server) as c:
        (j2,) = f.jobs_of_scan(c, after.scan_id)
    assert after.policy_version == v1 + 1
    assert j2["payload"]["plugins"][0]["execute"] == "echo version-two"
    assert j2["eval_spec"]["plugins"][0]["expected"] == "v2"


# ------------------------------------------------------------ CHK-M9-152


def test_two_concurrent_scans_of_one_policy_and_agent_leave_one_queued_job(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """TS §4.4 L558, #125 (d), (e): 20 rounds of two scans of one policy for
    one agent released by one barrier: both succeed and exactly one of the
    two jobs is still queued (the later scan cancelled the earlier's)."""
    pol = cat.policy(1)
    for n in range(20):
        with f.app(server) as c:
            a = str(f.make_agent(c).agent_id)
        barrier = threading.Barrier(2, timeout=30)

        def s(a: str = a, barrier: threading.Barrier = barrier) -> Any:
            barrier.wait()
            return do_scan(db, pol.policy_id, {"agents": [a]})

        outs = f.run_threads([s, s])
        assert [o.error for o in outs] == [None, None], n
        with f.app(server) as c:
            states = sorted(
                r[0]
                for r in c.execute(
                    "SELECT state::text FROM scan_job WHERE agent_id = %s", (a,)
                ).fetchall()
            )
        assert states == ["cancelled", "queued"], (n, states)
