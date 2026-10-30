"""TASK-197 TEST: the schedules repository on PostgreSQL as bitscan_app
(TP-M9-10; CHK-M9-122; mutation row CHK-M9-373).

Expected values: TS §5.2 L846–L857 (scan_schedule columns), L864 (scan.
schedule_id ON DELETE SET NULL), L1013 (bitscan_app holds DELETE on
scan_schedule), §4.4 L557 (skip if the previous scan from the schedule has
finished_at NULL); #122 (h) (policy_id never changes; list ordered by
schedule_id), #128 (d) (last_run_at = when a scan was last queued), (e)
(due = enabled and next_run_at ≤ now; two ticks never run one row twice).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from bitscan_manager.repositories import schedules as sr

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=5)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sr")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    with f.app_database(server) as db:
        yield f.make_catalog(db, f.Clock(), tmp_path)


def test_crud_round_trip(server: PgServer, cat: f.Catalog) -> None:
    pol = cat.policy(1)
    target = {"tags": ["prod-web", "db"]}
    nxt = NOW + timedelta(hours=1)
    with f.app(server) as conn:
        row = sr.insert(
            conn,
            name="  nightly é ",
            policy_id=pol.policy_id,
            target=target,
            cron="0 3 * * 0",
            timezone="Asia/Kolkata",
            enabled=True,
            next_run_at=nxt,
            created_by=7,
        )
        assert row.name == "  nightly é "  # stored as given (#122 (h))
        assert (row.policy_id, row.target, row.cron, row.timezone) == (
            pol.policy_id,
            target,
            "0 3 * * 0",
            "Asia/Kolkata",
        )
        assert (row.enabled, row.last_run_at, row.next_run_at, row.created_by) == (
            True,
            None,
            nxt,
            7,
        )
        assert sr.get(conn, row.schedule_id) == row
        changed = sr.update(
            conn,
            row.schedule_id,
            {
                "name": "n2",
                "target": {"all": True},
                "cron": "*/5 * * * *",
                "timezone": "UTC",
                "enabled": False,
                "next_run_at": None,
            },
        )
        assert changed is not None
        assert (changed.name, changed.target, changed.cron, changed.timezone) == (
            "n2",
            {"all": True},
            "*/5 * * * *",
            "UTC",
        )
        assert (
            changed.enabled,
            changed.next_run_at,
            changed.policy_id,
            changed.created_by,
        ) == (
            False,
            None,
            pol.policy_id,
            7,
        )
        for bad in (
            {"policy_id": 1},
            {"created_by": 1},
            {},
            {"last_run_at": NOW},
            {"name": "x", "policy_id": 2},
        ):
            with pytest.raises(ValueError):
                sr.update(conn, row.schedule_id, bad)
        assert sr.get(conn, row.schedule_id) == changed
        assert sr.update(conn, 2**62, {"name": "x"}) is None
        assert sr.get(conn, 2**62) is None
        assert sr.delete(conn, row.schedule_id) is True
        assert sr.delete(conn, row.schedule_id) is False
        assert sr.get(conn, row.schedule_id) is None
        assert sr.policy_state(conn, pol.policy_id) == ("enabled", False)
        assert sr.policy_state(conn, 2**62) is None


def test_page_by_schedule_id(server: PgServer, cat: f.Catalog) -> None:
    pol = cat.policy(1)
    with f.app(server) as conn:
        ids = [f.owner_schedule(conn, pol) for _ in range(5)]
        start = ids[0] - 1
        first = sr.page(conn, 2, start)
        second = sr.page(conn, 2, first[-1].schedule_id)
        third = sr.page(conn, 2, second[-1].schedule_id)
        everything = sr.page(conn, 500, None)
    assert [r.schedule_id for r in first + second] == ids[:4]
    assert [r.schedule_id for r in third][:1] == [ids[4]]
    listed = [r.schedule_id for r in everything]
    assert listed == sorted(listed) and set(ids) <= set(listed)


def test_delete_leaves_the_schedules_scans_with_schedule_id_null(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §5.2 L864, REQ-224 (4)."""
    pol = cat.policy(1)
    with f.app(server) as conn:
        sid = f.owner_schedule(conn, pol)
    with f.owner(server) as o:
        scans = [
            f.owner_scan(o, pol, schedule_id=sid, trigger="scheduled") for _ in range(2)
        ]
    with f.app(server) as conn:
        assert sr.delete(conn, sid)
        for s in scans:
            row = f.scan_row(conn, s)
            assert row["schedule_id"] is None and row["trigger"] == "scheduled"


def test_due_rows_are_enabled_not_after_now_and_skip_locked(
    server: PgServer, cat: f.Catalog
) -> None:
    """#128 (e), CHK-M9-373: due = enabled AND next_run_at ≤ now (exactly
    now is due; 1 µs later is not; NULL never); oldest due first; a row
    another session holds is skipped, so two ticks never take one row."""
    pol = cat.policy(1)
    with f.app(server) as conn:
        conn.execute("UPDATE scan_schedule SET enabled = false")  # this module only
        at_now = f.owner_schedule(conn, pol, next_run_at=NOW)
        older = f.owner_schedule(conn, pol, next_run_at=NOW - timedelta(minutes=1))
        later = f.owner_schedule(conn, pol, next_run_at=NOW + timedelta(microseconds=1))
        off = f.owner_schedule(
            conn, pol, next_run_at=NOW - timedelta(hours=1), enabled=False
        )
        never = f.owner_schedule(conn, pol, next_run_at=None)
    with f.app(server, autocommit=False) as a, f.app(server, autocommit=False) as b:
        got_a = [r.schedule_id for r in sr.due(a, NOW)]
        b.execute("SET lock_timeout = '2s'")
        got_b = [r.schedule_id for r in sr.due(b, NOW)]
        a.rollback()
        got_b_after = [r.schedule_id for r in sr.due(b, NOW)]
        b.rollback()
    assert got_a == [older, at_now]
    assert got_b == []
    assert got_b_after == [older, at_now]
    assert not {later, off, never} & set(got_a)
    with f.app(server, autocommit=False) as a:
        assert [r.schedule_id for r in sr.due(a, NOW, limit=1)] == [older]
        a.rollback()


def test_previous_unfinished_uses_the_latest_scan(
    server: PgServer, cat: f.Catalog
) -> None:
    """TS §4.4 L557: skip when the previous scan from the same schedule has
    finished_at NULL. The latest by created_at decides; no scan → False."""
    pol = cat.policy(1)
    with f.app(server) as conn:
        sid = f.owner_schedule(conn, pol)
        assert sr.previous_unfinished(conn, sid) is False
    with f.owner(server) as o:
        f.owner_scan(
            o,
            pol,
            schedule_id=sid,
            trigger="scheduled",
            created_at=NOW - timedelta(days=2),
        )  # unfinished, older
        f.owner_scan(
            o,
            pol,
            schedule_id=sid,
            trigger="scheduled",
            state="completed",
            created_at=NOW - timedelta(days=1),
            finished_at=NOW,
        )
    with f.app(server) as conn:
        assert sr.previous_unfinished(conn, sid) is False
    with f.owner(server) as o:
        f.owner_scan(o, pol, schedule_id=sid, trigger="scheduled", created_at=NOW)
    with f.app(server) as conn:
        assert sr.previous_unfinished(conn, sid) is True


def test_mark_run_keeps_last_run_on_a_skip(server: PgServer, cat: f.Catalog) -> None:
    """#128 (d): last_run_at is when a scan was last queued; a skipped or
    missed run moves only next_run_at."""
    pol = cat.policy(1)
    with f.app(server) as conn:
        sid = f.owner_schedule(conn, pol, next_run_at=NOW)
        sr.mark_run(conn, sid, ran_at=NOW, next_run_at=NOW + timedelta(days=1))
        row = sr.get(conn, sid)
        assert row is not None
        assert (row.last_run_at, row.next_run_at) == (NOW, NOW + timedelta(days=1))
        sr.mark_run(conn, sid, ran_at=None, next_run_at=NOW + timedelta(days=2))
        row = sr.get(conn, sid)
        assert row is not None
        assert (row.last_run_at, row.next_run_at) == (NOW, NOW + timedelta(days=2))


def test_get_for_update_holds_the_row(server: PgServer, cat: f.Catalog) -> None:
    pol = cat.policy(1)
    with f.app(server) as conn:
        sid = f.owner_schedule(conn, pol)
    with f.app(server, autocommit=False) as a, f.app(server, autocommit=False) as b:
        assert sr.get(a, sid, lock=True) is not None
        b.execute("SET lock_timeout = '300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            sr.get(b, sid, lock=True)
        b.rollback()
        a.rollback()


# ------------------------------------------------------------ TASK-197 r1


def test_policy_state_for_share_makes_a_policy_delete_wait(
    server: PgServer, cat: f.Catalog
) -> None:
    """Decisions "M9 builder rulings" (FOR SHARE on schedule create and
    enable), TS §4.3 L550: policy_state(lock=True) holds the policy row so a
    delete's UPDATE policy waits until the schedule write commits (and then
    its "disable the schedules" UPDATE sees the new schedule)."""
    import threading

    pol = cat.policy(1)
    with f.app(server, autocommit=False) as a, f.app(server) as b:
        assert sr.policy_state(a, pol.policy_id, lock=True) == ("enabled", False)
        pid = f.backend_pid(b)
        done = threading.Event()

        def delete_like() -> None:
            b.execute(
                "UPDATE policy SET updated_at = now() WHERE policy_id = %s",
                (pol.policy_id,),
            )
            done.set()

        t = threading.Thread(target=delete_like)
        t.start()
        try:
            f.wait_until_lock_waiting(server, pid)
            assert not done.is_set()
        finally:
            a.commit()
            t.join(10)
        assert done.is_set()


def test_try_share_policy_skips_a_held_policy_without_waiting(
    server: PgServer, cat: f.Catalog
) -> None:
    """TASK-203 r1 deadlock fix: the tick never waits for a policy row an
    import or delete holds; it gets False at once, and True once released.
    A plain share lock held by another scan does not block it."""
    pol = cat.policy(1)
    with f.app(server, autocommit=False) as a, f.app(server, autocommit=False) as b:
        b.execute("SET lock_timeout = '2s'")
        a.execute(
            "UPDATE policy SET updated_at = now() WHERE policy_id = %s",
            (pol.policy_id,),
        )
        assert sr.try_share_policy(b, pol.policy_id) is False
        b.rollback()
        a.rollback()
        a.execute(
            "SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE", (pol.policy_id,)
        )
        assert sr.try_share_policy(b, pol.policy_id) is True
        b.rollback()
        a.rollback()
        assert sr.try_share_policy(b, 2**62) is False
        b.rollback()
