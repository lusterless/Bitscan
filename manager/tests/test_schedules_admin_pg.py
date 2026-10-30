"""TASK-201 TEST (and r1): schedule management on PostgreSQL as bitscan_app
(TP-M9-14; CHK-M9-188, -189; decisions "M9 builder rulings": FOR SHARE on
schedule create and enable).

Expected values: TS §6.2 L1124 (CRUD /scan-schedules), §4.4 L557 (cron in
the schedule's timezone, default UTC; users may enable or disable), §4.3
L550 (a policy delete disables its schedules), §5.2 L846–L857, L864;
#122 (h) (policy_id never changes; 409 for a deleted policy, a disabled one
allowed; name 1–128 characters stored as given), #128 (d) (next_run_at =
next fire strictly after now, on create, cron/timezone change and enable),
#129 (a) (one scan_schedule.* entry per change). Next fire times are worked
out here by hand from the calendar.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.services.jobs.queue import PolicyNotFound
from bitscan_manager.services.jobs.targets import InvalidTarget
from bitscan_manager.services.scheduler import schedules_admin as sa
from bitscan_manager.services.scheduler.cron import InvalidSchedule

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0  # day 15, 12:00:00 UTC
NEXT_3AM = (NOW + timedelta(days=1)).replace(hour=3)  # 16th 03:00 UTC


def next_sunday_3am(at: datetime) -> datetime:
    """Sunday 03:00 UTC strictly after ``at`` (Python: Monday = 0)."""
    d = at.replace(hour=3, minute=0, second=0, microsecond=0)
    while d.weekday() != 6 or d <= at:
        d += timedelta(days=1)
    return d


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sched-admin")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


def create(db: AppDatabase, pol: f.Pol, **kw: Any) -> Any:
    args: dict[str, Any] = {
        "name": "nightly",
        "policy_id": pol.policy_id,
        "target": {"all": True},
        "cron": "0 3 * * *",
        "user_id": 7,
        "now": NOW,
    } | kw
    with db.transaction() as tx:
        return sa.create(tx, **args)


def update(db: AppDatabase, sid: int, changes: dict[str, Any], **kw: Any) -> Any:
    with db.transaction() as tx:
        return sa.update(
            tx,
            sid,
            changes=changes,
            user_id=kw.get("user_id", 8),
            now=kw.get("now", NOW),
        )


def entries(server: PgServer, mark: int) -> list[dict[str, Any]]:
    with f.app(server) as c:
        return f.audit_after(c, mark)


def mark(server: PgServer) -> int:
    with f.app(server) as c:
        return f.last_audit(c)


# ------------------------------------------------------------ CHK-M9-188


def test_create_computes_next_run_and_writes_one_entry(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-224 (1), (6), #128 (d), #129 (a): defaults timezone UTC and
    enabled true; next_run_at = the next 03:00 UTC after now; the target is
    stored as requested (agent ids lowercase) and resolved only at each run;
    one scan_schedule.create entry by the creator, target scan_schedule:<id>."""
    pol = cat.policy(1)
    m = mark(server)
    upper = "8F14E45F-CEEA-467A-9575-D8B4E0B5F8A1"
    row = create(db, pol, target={"agents": [upper]})
    assert (row.timezone, row.enabled, row.next_run_at) == ("UTC", True, NEXT_3AM)
    assert row.target == {"agents": [upper.lower()]}
    assert (row.created_by, row.policy_id, row.last_run_at) == (7, pol.policy_id, None)
    (e,) = entries(server, m)
    assert (e["actor"], e["action"], e["target"]) == (
        "user:7",
        "scan_schedule.create",
        f"scan_schedule:{row.schedule_id}",
    )
    assert (
        e["detail"]["cron"] == "0 3 * * *" and e["detail"]["policy_id"] == pol.policy_id
    )
    kol = create(db, pol, cron="0 9 * * *", timezone="Asia/Kolkata")
    assert kol.next_run_at == NEXT_3AM.replace(minute=30)  # 09:00 IST = 03:30 UTC
    sun = create(db, pol, cron="0 3 * * 0")
    assert sun.next_run_at == next_sunday_3am(NOW)
    assert create(db, pol, cron="0 3 * * 7").next_run_at == next_sunday_3am(NOW)
    with db.transaction() as tx:
        assert sa.get(tx, row.schedule_id) == row
        listed = [r.schedule_id for r in sa.list_page(tx, limit=500, after_id=None)]
    assert {row.schedule_id, kol.schedule_id, sun.schedule_id} <= set(listed)
    assert listed == sorted(listed)


def test_patch_recomputes_next_run_and_enable_disable(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-224 (2), #128 (d): a cron change and a timezone change recompute
    next_run_at from now; enabled false stops runs (next_run_at left); enabled
    true recomputes from the enabling moment; policy_id cannot be patched;
    each change is one scan_schedule.update entry naming the changed fields."""
    pol = cat.policy(1)
    row = create(db, pol)
    m = mark(server)
    later = NOW + timedelta(days=2, hours=5)  # day 17, 17:00 UTC
    r = update(db, row.schedule_id, {"cron": "30 4 * * *"}, now=NOW)
    assert r.next_run_at == NEXT_3AM.replace(hour=4, minute=30)
    r = update(db, row.schedule_id, {"timezone": "Asia/Kolkata"}, now=NOW)
    assert r.next_run_at == NEXT_3AM.replace(hour=23, minute=0) - timedelta(
        days=1
    )  # 04:30 IST = 23:00 UTC
    r = update(db, row.schedule_id, {"enabled": False}, now=later)
    assert r.enabled is False and r.next_run_at == NEXT_3AM.replace(
        hour=23
    ) - timedelta(days=1)
    r = update(db, row.schedule_id, {"enabled": True}, now=later)
    assert r.enabled is True
    assert r.next_run_at == datetime(later.year, later.month, 17, 23, 0, tzinfo=UTC)
    with pytest.raises(sa.InvalidField):
        update(db, row.schedule_id, {"policy_id": pol.policy_id})
    with pytest.raises(sa.InvalidField):
        update(db, row.schedule_id, {})
    got = entries(server, m)
    assert [e["action"] for e in got] == ["scan_schedule.update"] * 4
    assert all(e["actor"] == "user:8" for e in got)
    assert "cron" in got[0]["detail"] and "timezone" in got[1]["detail"]
    assert got[2]["detail"].get("enabled") is False


def test_deleted_policy_refuses_create_and_enable_but_disabled_is_allowed(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-224 (3), #122 (h), TS §4.3 L550: creating, or enabling, a schedule
    of a deleted policy is a conflict (nothing written); a disabled policy is
    accepted (its runs are skipped); an unknown policy is PolicyNotFound."""
    off = cat.policy(1, status="disabled")
    assert create(db, off).enabled is True
    gone = cat.policy(1)
    kept = create(db, gone)
    cat.delete(gone)  # M7 disables its schedules
    with f.app(server) as c:
        before = f.counts(c)
        assert (
            f.one(
                c,
                "SELECT enabled FROM scan_schedule WHERE schedule_id = %s",
                (kept.schedule_id,),
            )
            is False
        )
    m = mark(server)
    with pytest.raises(sa.ScheduleConflict):
        create(db, gone)
    with pytest.raises(sa.ScheduleConflict):
        update(db, kept.schedule_id, {"enabled": True})
    with pytest.raises(PolicyNotFound):
        create(db, f.Pol(2**62, "x", "x", [], 1))
    assert entries(server, m) == []
    with f.app(server) as c:
        assert f.counts(c) == before
    renamed = update(db, kept.schedule_id, {"name": "still editable"})
    assert renamed.enabled is False


# ------------------------------------------------------------ CHK-M9-189


def test_delete_removes_the_row_and_keeps_its_scans(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-224 (4), (6), TS §5.2 L864: one scan_schedule.delete entry; the
    schedule's scans keep their rows with schedule_id NULL; a second delete,
    get and update are ScheduleNotFound."""
    pol = cat.policy(1)
    row = create(db, pol)
    with f.owner(server) as o:
        scan = f.owner_scan(o, pol, schedule_id=row.schedule_id, trigger="scheduled")
    m = mark(server)
    with db.transaction() as tx:
        sa.delete(tx, row.schedule_id, user_id=9)
    (e,) = entries(server, m)
    assert (e["actor"], e["action"], e["target"]) == (
        "user:9",
        "scan_schedule.delete",
        f"scan_schedule:{row.schedule_id}",
    )
    with f.app(server) as c:
        assert f.scan_row(c, scan)["schedule_id"] is None
    for call in (
        lambda tx: sa.delete(tx, row.schedule_id, user_id=9),
        lambda tx: sa.get(tx, row.schedule_id),
        lambda tx: sa.update(
            tx, row.schedule_id, changes={"name": "x"}, user_id=9, now=NOW
        ),
    ):
        with pytest.raises(sa.ScheduleNotFound), db.transaction() as tx:
            call(tx)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("name", "", sa.InvalidField),
        ("name", "n" * 129, sa.InvalidField),
        ("name", "a\x00b", sa.InvalidField),
        ("name", "a\ud800b", sa.InvalidField),
        ("name", 5, sa.InvalidField),
        ("cron", "61 * * * *", InvalidSchedule),
        ("cron", "@daily", InvalidSchedule),
        ("cron", "0 0 1 * 1", InvalidSchedule),
        ("cron", "0 0 30 2 *", InvalidSchedule),
        ("cron", "* * * * * *", InvalidSchedule),
        ("cron", 3, InvalidSchedule),
        ("timezone", "Mars/Base", InvalidSchedule),
        ("timezone", "localtime", InvalidSchedule),
        ("timezone", "../etc/passwd", InvalidSchedule),
        ("target", {"all": False}, InvalidTarget),
        ("target", {"tags": []}, InvalidTarget),
        ("target", {"agents": ["x"]}, InvalidTarget),
        ("enabled", "yes", sa.InvalidField),
    ],
)
def test_bad_fields_are_refused_and_write_nothing(
    server: PgServer,
    db: AppDatabase,
    cat: f.Catalog,
    field: str,
    value: Any,
    error: type[Exception],
) -> None:
    """REQ-224 (7), #122 (h), #128 (a)–(c): each bad field is refused with the
    field's error on create and on PATCH; no row and no entry is written; the
    message never holds the input."""
    pol = cat.policy(1)
    existing = create(db, pol)
    with f.app(server) as c:
        before = (f.counts(c), f.checksum(c, "scan_schedule"))
    with pytest.raises(error) as exc:
        create(db, pol, **{field: value})
    if isinstance(value, str) and len(value) > 2:
        assert value not in str(exc.value)
    with pytest.raises(error):
        update(db, existing.schedule_id, {field: value})
    with f.app(server) as c:
        assert (f.counts(c), f.checksum(c, "scan_schedule")) == before


def test_a_128_character_name_is_kept_as_given(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    pol = cat.policy(1)
    name = " " + "é" * 126 + " "
    assert create(db, pol, name=name).name == name


def test_any_operator_may_change_another_operators_schedule(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """#128 (i): created by user 7, changed by user 8; created_by is kept."""
    pol = cat.policy(1)
    row = create(db, pol, user_id=7)
    r = update(db, row.schedule_id, {"name": "theirs"}, user_id=8)
    assert (r.name, r.created_by) == ("theirs", 7)


# ------------------------------------------------------------ r1: racing delete


@pytest.mark.parametrize("op", ["create", "enable"])
def test_a_policy_delete_racing_a_schedule_write_never_leaves_it_enabled(
    server: PgServer, db: AppDatabase, cat: f.Catalog, op: str
) -> None:
    """Ruling "FOR SHARE on schedule create and enable", TS §4.3 L550: the
    schedule transaction is held open after its write; M7's policy delete,
    started then, waits on the policy row (lock probe) until the schedule
    commits, then disables it. The schedule ends disabled, the policy
    deleted."""
    pol = cat.policy(1)
    pre = create(db, pol, enabled=False) if op == "enable" else None
    gate = f.Gate()
    out: dict[str, Any] = {}

    def write() -> None:
        with db.transaction() as tx:
            if op == "create":
                out["row"] = sa.create(
                    tx,
                    name="race",
                    policy_id=pol.policy_id,
                    target={"all": True},
                    cron="0 3 * * *",
                    user_id=7,
                    now=NOW,
                )
            else:
                assert pre is not None
                out["row"] = sa.update(
                    tx, pre.schedule_id, changes={"enabled": True}, user_id=7, now=NOW
                )
            gate.wait()

    def delete() -> None:
        cat.delete(pol)

    t1 = threading.Thread(target=write)
    t1.start()
    assert gate.reached.wait(30)
    t2 = threading.Thread(target=delete)
    t2.start()
    try:
        f.wait_until_any_waiter(server)
    finally:
        gate.open()
        t1.join(30)
        t2.join(30)
    sid = out["row"].schedule_id
    with f.app(server) as c:
        enabled = f.one(
            c, "SELECT enabled FROM scan_schedule WHERE schedule_id = %s", (sid,)
        )
        deleted = f.one(
            c,
            "SELECT deleted_at IS NOT NULL FROM policy WHERE policy_id = %s",
            (pol.policy_id,),
        )
    assert (enabled, deleted) == (False, True)
