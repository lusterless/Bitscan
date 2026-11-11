"""TASK-242 TEST: retention races on PostgreSQL, driven by held locks and
lock-wait probes, never sleeps (TP-M11-10; CHK-M11-193 to -195; decisions
2026-10-26).

Expected values: REQ-278 (2) and #150 (k) (a scan whose M8 re-evaluation lock
is held is skipped and deleted on the next run; a re-evaluation started after
the delete finds no scan); REQ-276 (3) and TS §5.3 L1053 (app writers
appending during the audit step never fork the chain); #150 (f) (an inventory
upload racing the package prune: one side fails, nothing is lost, the next
run or the retried upload completes).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest

from bitscan_manager.repositories import retention_audit as ra
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.audit.chain import append_entry
from bitscan_manager.services.audit.verify import verify_chain
from bitscan_manager.services.evaluator.reevaluate import ScanNotFound, reevaluate_scan
from bitscan_manager.services.retention import rules, task

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("retention-race")) as s:
        yield s


@pytest.fixture
def fresh(server: PgServer) -> PgServer:
    with m.owner(server) as c:
        c.execute(
            "TRUNCATE scan, scan_job, scan_result, scan_result_reeval,"
            " inventory_snapshot, enrollment_request, enrollment_token, user_token,"
            " package, agent_package, os_info, audit_log CASCADE"
        )
    return server


@pytest.fixture
def rdb(fresh: PgServer) -> Iterator[Any]:
    with m.retention_database(fresh) as db:
        yield db


def run(db: Any, now: datetime, shipped: int | None = None) -> dict[str, Any]:
    out = task.run_retention(db, now, shipped_through=m.shipped(shipped))
    return {r.step: r for r in out}


def in_thread(fn: Any) -> tuple[threading.Thread, dict[str, Any]]:
    out: dict[str, Any] = {}

    def wrap() -> None:
        try:
            out["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            out["error"] = exc

    t = threading.Thread(target=wrap)
    t.start()
    return t, out


def waiters(server: PgServer, n: int, bound_s: float = 10.0) -> None:
    """Polls (20 ms, bounded) until exactly n backends wait on a lock."""
    deadline = time.monotonic() + bound_s
    with m.owner(server) as probe:
        while time.monotonic() < deadline:
            row = probe.execute(
                "SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted"
            ).fetchone()
            if row == (n,):
                return
            time.sleep(0.02)
    raise AssertionError(f"{n} lock waiters not seen within {bound_s} s")


# ------------------------------------------------------------------ CHK-M11-193


def test_a_scan_under_reevaluation_is_skipped_then_deleted(
    fresh: PgServer, rdb: Any
) -> None:
    with m.owner(fresh) as c:
        w = m.aged_world(c, m.now_utc())
    held, other = w.key("scan", "old"), w.key("scan", "past")
    with m.holding_reeval_lock(fresh, held):
        res = run(rdb, w.now)
        assert res["scans"].deleted == 1
        with m.owner(fresh) as c:
            assert m.scan_remains(c, held, w.scan_jobs["old"])["scan"] == 1
            assert m.scan_remains(c, other, w.scan_jobs["past"])["scan"] == 0
    assert run(rdb, w.now)["scans"].deleted == 1  # next run, lock released
    with m.owner(fresh) as c:
        assert m.scan_remains(c, held, w.scan_jobs["old"]) == dict.fromkeys(
            ("scan", "scan_job", "scan_result", "scan_result_reeval"), 0
        )
    with f9.app_database(fresh) as adb, pytest.raises(ScanNotFound):
        reevaluate_scan(adb, held, user_id=1)


# ------------------------------------------------------------------ CHK-M11-194


def test_app_writers_during_the_audit_step_never_fork_the_chain(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit step holds the chain lock from before it reads the prefix to
    its commit. Two app writers started inside that window (at the delete)
    park on the chain lock; after the commit they append after the
    checkpoint, and M1's verifier accepts the chain."""
    now = m.now_utc()
    ids = m.audit_chain(fresh, [rules.minus_years(now, 3) - timedelta(days=5)] * 20)
    real = ra.delete_through
    writers: list[tuple[threading.Thread, dict[str, Any]]] = []

    def write(n: int) -> int:
        with m.tx_conn(fresh, "bitscan_app") as c:
            e = append_entry(PgAuditRepo(c), actor="m11-writer", action=f"m11.w{n}")
            c.commit()
            return int(e.audit_id)

    def delete_then_park(conn: Any, audit_id: int) -> int:
        n = int(real(conn, audit_id))
        for i in range(2):
            writers.append(in_thread(lambda i=i: write(i)))
            waiters(fresh, i + 1)  # parked on the chain lock
        return n

    monkeypatch.setattr(ra, "delete_through", delete_then_park)
    res = run(rdb, now, shipped=ids[-1])
    monkeypatch.undo()
    for t, _ in writers:
        t.join(30)
        assert not t.is_alive()
    got = [out.get("value") for _, out in writers]
    assert all(isinstance(g, int) for g in got), [out for _, out in writers]
    assert res["audit"].deleted == 20
    with m.owner(fresh) as c:
        cps = m.checkpoints(c)
        assert len(cps) == 1
        assert all(g > cps[0]["audit_id"] for g in got)  # after the checkpoint
        assert m.audit_ids(c) == sorted([cps[0]["audit_id"], *got])  # none lost
        assert verify_chain(c).ok


# ------------------------------------------------------------------ CHK-M11-195


def test_upload_racing_the_package_prune_loses_nothing(
    fresh: PgServer, rdb: Any
) -> None:
    """An upload's uncommitted agent_package row references an unreferenced
    package while the prune runs: the prune's delete waits on it; the upload
    commits; the prune's chunk fails on the reference and rolls back (the
    step is logged failed). The package and its reference stay; the next run
    prunes only what is still unreferenced."""
    now = m.now_utc()
    with m.owner(fresh) as c:
        a = m.host(c, at=now)
        racing = m.package(c)
        spare = m.package(c)
    with m.tx_conn(fresh, "bitscan_app") as up:
        up.execute(
            "INSERT INTO agent_package (agent_id, package_id, status, first_seen_at,"
            " last_seen_at) VALUES (%s, %s, 'install ok installed', %s, %s)",
            (a.agent_id, racing, now, now),
        )
        t, out = in_thread(lambda: run(rdb, now))
        f9.wait_until_any_waiter(fresh)  # the prune waits on the upload
        up.commit()
        t.join(60)
        assert not t.is_alive() and "error" not in out
    res = out["value"]
    with m.owner(fresh) as c:
        pkgs = {int(r[0]) for r in c.execute("SELECT package_id FROM package")}
        refs = c.execute(
            "SELECT count(*) FROM agent_package WHERE package_id = %s", (racing,)
        ).fetchone()
    assert racing in pkgs and refs == (1,)  # nothing lost
    if res["packages"].skipped == "failed":  # the prune lost its chunk
        assert spare in pkgs
        assert run(rdb, now)["packages"].deleted == 1
    with m.owner(fresh) as c:
        pkgs = {int(r[0]) for r in c.execute("SELECT package_id FROM package")}
    assert pkgs == {racing}
