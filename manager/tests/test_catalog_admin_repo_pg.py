"""TP-M7-10 (TASK-150): catalog admin and integrity repositories, as bitscan_app.

CHK-M7-165 to -170 (tests/m7/test-plan.md). Expected values: TS §4.3 L546 to
L551, §5.2 (DDL, v_plugin, grants L1005 to L1013); REQ-167 (1), (6), REQ-168
(1), REQ-169 (1), (2), (4); #9, #98 (a), (b), #103, #104 (a), (b), (d); D3.
Catalog rows are written here with plain SQL as bitscan_app (independent of
TASK-148); scans, jobs and schedules as owner.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import catalog_integrity as integ

from . import catalog_rows as cr
from .catalog_rows import T0, T1, T2, Conn, app, owner, sha, tag
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("catadm")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[Conn]:
    with app(server) as c, c.transaction(force_rollback=True):
        yield c


@dataclass
class Pol:
    policy_id: int
    name: str
    family_id: int
    family_name: str


def family(conn: Conn, name: str | None = None) -> tuple[int, str]:
    name = name or f"Fam {tag()}"
    row = conn.execute(
        "INSERT INTO family (family_name, created_at) VALUES (%s, %s)"
        " RETURNING family_id",
        (name, T0),
    ).fetchone()
    assert row is not None
    return int(row[0]), name


def policy(
    conn: Conn,
    name: str | None = None,
    *,
    status: str = "enabled",
    file_status: str | None = None,
    overridden: bool = False,
    deleted: bool = False,
    desc: str = "d",
    fam: tuple[int, str] | None = None,
    source_file: str | None = None,
) -> Pol:
    fid, fname = fam or family(conn)
    name = name or f"Pol {tag()}"
    row = conn.execute(
        "INSERT INTO policy (policy_name, policy_description, policy_status,"
        " file_status,"
        " status_overridden, family_id, version, source_file, source_sha256,"
        " deleted_at, imported_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, 3,"
        " %s, %s, %s, %s, %s) RETURNING policy_id",
        (
            name,
            desc,
            status,
            file_status or status,
            overridden,
            fid,
            source_file or f"{tag()}.bit",
            sha(name),
            T0 if deleted else None,
            T0,
            T0,
        ),
    ).fetchone()
    assert row is not None
    pid = int(row[0])
    if deleted:
        conn.execute(
            "UPDATE policy SET source_file = 'deleted/' || policy_id"
            " WHERE policy_id = %s",
            (pid,),
        )
    return Pol(pid, name, fid, fname)


def plugin(
    conn: Conn,
    owner_pol: Pol,
    *,
    name: str = "1.1 - Check",
    state: str = "active",
    **kw: Any,
) -> UUID:
    u = uuid4()
    execute = kw.get("execute", f"echo {tag()}")
    conn.execute(
        "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
        " control_ref, plugin_description, execute, execute_sha256, operator,"
        " expected_result, timeout_s, state, updated_at) VALUES (%s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            u,
            owner_pol.family_id,
            owner_pol.policy_id,
            name,
            kw.get("control_ref", "1.1"),
            kw.get("desc", "pd"),
            execute,
            sha(execute),
            kw.get("operator", "equals"),
            kw.get("expected", "x"),
            kw.get("timeout_s", 60),
            state,
            T0,
        ),
    )
    return u


def member(conn: Conn, pol: Pol, uuids: list[UUID]) -> None:
    for i, u in enumerate(uuids, 1):
        conn.execute(
            "INSERT INTO policy_plugin (policy_id, plugin_uuid, sort_order)"
            " VALUES (%s, %s, %s)",
            (pol.policy_id, u, i),
        )


def walk(conn: Conn, limit: int, status: Any = None) -> list[adm.ProfileItem]:
    out: list[adm.ProfileItem] = []
    after: tuple[str, int] | None = None
    while True:
        page = adm.list_page(conn, limit + 1, status, after)
        out += page[:limit]
        if len(page) <= limit:
            return out
        last = page[limit - 1]
        after = (last.policy_name, last.policy_id)


# CHK-M7-165: list ------------------------------------------------------------------


def test_list_excludes_deleted_and_filters_by_effective_status(conn: Conn) -> None:
    t = tag()
    for i in range(3):
        policy(conn, f"m7list-{t}-e{i}", status="enabled")
    policy(conn, f"m7list-{t}-d0", status="disabled")
    # effective disabled by override while the file says enabled
    policy(
        conn,
        f"m7list-{t}-d1",
        status="disabled",
        file_status="enabled",
        overridden=True,
    )
    policy(conn, f"m7list-{t}-x0", status="enabled", deleted=True)

    def mine(items: list[adm.ProfileItem]) -> list[str]:
        return [
            i.policy_name for i in items if i.policy_name.startswith(f"m7list-{t}-")
        ]

    assert len(mine(walk(conn, 500))) == 5
    assert sorted(mine(walk(conn, 500, "enabled"))) == [
        f"m7list-{t}-e{i}" for i in range(3)
    ]
    assert sorted(mine(walk(conn, 500, "disabled"))) == [
        f"m7list-{t}-d0",
        f"m7list-{t}-d1",
    ]


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_list_pages_each_policy_once_in_name_then_id_order(conn: Conn, n: int) -> None:
    t = tag()
    names = [f"m7page-{t}-{i:02d}" for i in range(n + 1)]
    for name in reversed(names):  # inserted against the order
        policy(conn, name)
    items = walk(conn, n)
    ids = [i.policy_id for i in items]
    assert len(ids) == len(set(ids))
    assert [
        i.policy_name for i in items if i.policy_name.startswith(f"m7page-{t}-")
    ] == names
    oracle = conn.execute(
        "SELECT policy_id FROM policy WHERE deleted_at IS NULL"
        " ORDER BY policy_name, policy_id"
    ).fetchall()
    assert ids == [int(r[0]) for r in oracle]


def test_item_fields_are_the_98a_shape(conn: Conn) -> None:
    assert [f.name for f in dataclasses.fields(adm.ProfileItem)] == [
        "policy_id",
        "policy_name",
        "policy_description",
        "policy_status",
        "file_status",
        "status_overridden",
        "family_id",
        "family_name",
        "format_version",
        "version",
        "source_file",
        "plugin_count",
        "imported_at",
        "updated_at",
    ]
    p = policy(conn, status="disabled", file_status="enabled", overridden=True)
    member(conn, p, [plugin(conn, p), plugin(conn, p)])
    other = policy(conn)
    member(conn, other, [plugin(conn, other)])
    got = adm.item(conn, p.policy_id)
    assert got is not None
    assert dataclasses.astuple(got) == (
        p.policy_id,
        p.name,
        "d",
        "disabled",
        "enabled",
        True,
        p.family_id,
        p.family_name,
        "1.0",
        3,
        got.source_file,
        2,
        T0,
        T0,
    )
    assert next(i for i in walk(conn, 500) if i.policy_id == p.policy_id) == got


def test_item_returns_deleted_policies_and_none_for_unknown(conn: Conn) -> None:
    p = policy(conn, deleted=True)
    got = adm.item(conn, p.policy_id)
    assert got is not None and got.source_file == f"deleted/{p.policy_id}"
    assert adm.item(conn, 2**62) is None


# CHK-M7-166: detail ----------------------------------------------------------------

HOSTILE = '<img src=x onerror=alert(1)> "q" \\ \x01\x1f\x7f   ‮ 🛡 é'


def test_detail_plugins_in_sort_order_with_display_name(conn: Conn) -> None:
    fam = family(conn, f"CIS {tag()}")
    p = policy(conn, fam=fam, desc=HOSTILE)
    a = plugin(conn, p, name="1.3.1.1 - Ensure AppArmor is installed", timeout_s=30)
    b = plugin(conn, p, name=HOSTILE, control_ref=None, desc=HOSTILE, expected=HOSTILE,
               operator="regex", execute=HOSTILE)  # fmt: skip
    c = plugin(conn, p, name="2 - Last", state="retired")
    member(conn, p, [c, a, b])  # file order c, a, b
    got = adm.detail(conn, p.policy_id)
    assert got is not None
    assert got.deleted_at is None
    assert got.item.plugin_count == 3 and got.item.policy_description == HOSTILE
    assert [x.plugin_uuid for x in got.plugins] == [c, a, b]
    assert [x.sort_order for x in got.plugins] == [1, 2, 3]
    assert (
        got.plugins[1].display_name
        == f"{fam[1]} - 1.3.1.1 - Ensure AppArmor is installed"
    )
    hb = got.plugins[2]
    assert dataclasses.astuple(hb) == (
        b,
        3,
        f"{fam[1]} - {HOSTILE}",
        HOSTILE,
        None,
        HOSTILE,
        HOSTILE,
        sha(HOSTILE),
        "regex",
        HOSTILE,
        60,
        "active",
        T0,
    )
    assert got.plugins[0].state == "retired"
    assert [f.name for f in dataclasses.fields(adm.ProfilePlugin)] == [
        "plugin_uuid", "sort_order", "display_name", "plugin_name", "control_ref",
        "plugin_description", "execute", "execute_sha256", "operator",
        "expected_result", "timeout_s", "state", "updated_at",
    ]  # fmt: skip


def test_detail_timestamps_survive_any_session_time_zone(conn: Conn) -> None:
    p = policy(conn)
    member(conn, p, [plugin(conn, p)])
    conn.execute("SET LOCAL TIME ZONE 'Asia/Kathmandu'")  # +05:45
    got = adm.detail(conn, p.policy_id)
    assert got is not None
    stamp = got.plugins[0].updated_at
    assert isinstance(stamp, datetime) and stamp.utcoffset() is not None
    assert stamp == T0 and stamp.microsecond == T0.microsecond


def test_detail_of_deleted_policy_shows_deleted_at_and_keeps_plugins(
    conn: Conn,
) -> None:
    p = policy(conn)
    u = plugin(conn, p)
    member(conn, p, [u])
    conn.execute(
        "UPDATE policy SET deleted_at = %s WHERE policy_id = %s", (T1, p.policy_id)
    )
    got = adm.detail(conn, p.policy_id)
    assert got is not None and got.deleted_at == T1
    assert [x.plugin_uuid for x in got.plugins] == [u]  # #104 (a)


def test_detail_unknown_and_empty(conn: Conn) -> None:
    assert adm.detail(conn, 2**62) is None
    p = policy(conn)
    got = adm.detail(conn, p.policy_id)
    assert got is not None and got.plugins == [] and got.item.plugin_count == 0


# CHK-M7-167: status ----------------------------------------------------------------


def state(conn: Conn, pid: int) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT policy_status::text, file_status::text, status_overridden, updated_at,"
        " version, deleted_at, source_file FROM policy WHERE policy_id = %s",
        (pid,),
    ).fetchone()
    assert row is not None
    return tuple(row)


@pytest.mark.parametrize("target", ["enabled", "disabled"])
def test_set_status_sets_override(conn: Conn, target: str) -> None:
    p = policy(conn, status="disabled" if target == "enabled" else "enabled")
    assert adm.set_status(conn, p.policy_id, target, T1) is True  # type: ignore[arg-type]
    s = state(conn, p.policy_id)
    assert s[:4] == (target, "disabled" if target == "enabled" else "enabled", True, T1)


def test_set_status_noop_keeps_updated_at_but_a_change_of_override_moves_it(
    conn: Conn,
) -> None:
    p = policy(conn, status="disabled", overridden=True)
    assert adm.set_status(conn, p.policy_id, "disabled", T2) is True
    assert state(conn, p.policy_id)[3] == T0
    q = policy(conn, status="enabled")  # same status, override not yet set
    assert adm.set_status(conn, q.policy_id, "enabled", T2) is True
    assert state(conn, q.policy_id)[2:4] == (True, T2)


@pytest.mark.parametrize("file_status", ["enabled", "disabled"])
def test_clear_override_restores_file_status(conn: Conn, file_status: str) -> None:
    other = "disabled" if file_status == "enabled" else "enabled"
    p = policy(conn, status=other, file_status=file_status, overridden=True)
    assert adm.clear_override(conn, p.policy_id, T1) is True
    assert state(conn, p.policy_id)[:4] == (file_status, file_status, False, T1)
    assert adm.clear_override(conn, p.policy_id, T2) is True  # no-op
    assert state(conn, p.policy_id)[3] == T1


def test_status_changes_refuse_deleted_and_unknown(conn: Conn) -> None:
    p = policy(conn, deleted=True, status="disabled")
    before = state(conn, p.policy_id)
    assert adm.set_status(conn, p.policy_id, "enabled", T1) is False
    assert adm.clear_override(conn, p.policy_id, T1) is False
    assert state(conn, p.policy_id) == before
    assert adm.set_status(conn, 2**62, "enabled", T1) is False
    assert adm.clear_override(conn, 2**62, T1) is False


def test_lock_returns_state_and_holds_the_row(server: PgServer) -> None:
    with app(server) as s, s.transaction():
        p = policy(s, status="disabled", file_status="enabled", overridden=True)
    with app(server) as a, app(server) as b:
        with a.transaction():
            got = adm.lock(a, p.policy_id)
            assert got is not None
            assert dataclasses.astuple(got)[:5] == (
                p.policy_id, "disabled", "enabled", True, got.source_file,
            )  # fmt: skip
            assert got.deleted_at is None
            with pytest.raises(psycopg.errors.LockNotAvailable), b.transaction():
                b.execute(
                    "SELECT 1 FROM policy WHERE policy_id = %s FOR UPDATE NOWAIT",
                    (p.policy_id,),
                )
        assert adm.lock(b, 2**62) is None


def test_file_update_racing_a_patch_never_loses_the_override(server: PgServer) -> None:
    # D3: the importer's UPDATE decides policy_status from the row it updates,
    # so a PATCH disable committed while it waited is kept (TS §4.3 L548).
    from bitscan_manager.repositories import catalog as cat

    with app(server) as s, s.transaction():
        p = policy(s, status="enabled")
        row = cat.policy_by_id_for_update(s, p.policy_id)
    assert row is not None
    values = cat.PolicyValues(
        row.policy_name, row.policy_description, "enabled", row.family_id,
        row.format_version, row.source_file, sha("new bytes"),
    )  # fmt: skip
    with app(server) as patch, app(server) as imp:
        patch.execute("BEGIN")
        assert adm.set_status(patch, p.policy_id, "disabled", T1)
        done: dict[str, Any] = {}

        def file_update() -> None:
            with imp.transaction():
                done["row"] = cat.update_policy(imp, p.policy_id, values, T2)

        t = threading.Thread(target=file_update)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "the file UPDATE did not wait for the PATCH row lock"
        patch.execute("COMMIT")
        t.join(10)
        assert not t.is_alive()
    assert done["row"].policy_status == "disabled"
    assert done["row"].status_overridden is True
    with app(server) as check:
        assert state(check, p.policy_id)[:3] == ("disabled", "enabled", True)


# CHK-M7-168: soft delete -------------------------------------------------------------


def job_rows(conn: Conn, ids: list[UUID]) -> dict[UUID, tuple[str, Any]]:
    rows = conn.execute(
        "SELECT job_id, state::text, finished_at FROM scan_job WHERE job_id = ANY(%s)",
        (ids,),
    ).fetchall()
    return {UUID(str(j)): (s, f) for j, s, f in rows}


def test_soft_delete_changes_exactly_the_req_167_rows(server: PgServer) -> None:
    with app(server) as s, s.transaction():
        p = policy(s, status="disabled", file_status="enabled", overridden=True)
        q = policy(s)
        owned_listed = plugin(s, p)
        shared = plugin(s, p)  # owned by p, also listed by live q: stays active
        q_owned = plugin(s, q)  # owned by q, listed only by p: nobody live lists it
        owned_unlisted = plugin(s, p)
        q_live = plugin(s, q)
        member(s, p, [owned_listed, shared, q_owned])
        member(s, q, [shared, q_live])
    with owner(server) as o:
        ag = cr.agent(o)
        scan_p, jobs_p = cr.scan_with_jobs(
            o, p.policy_id, ag, ["queued", "dispatched", "running", "completed"]
        )
        retry = uuid4()
        o.execute(
            "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, retry_of, state,"
            " payload, eval_spec, pickup_by) VALUES (%s, 'compliance', %s, %s, %s,"
            " 'queued', '{}', '[]', now() + interval '1 day')",
            (retry, scan_p, ag, jobs_p["running"]),
        )
        _, jobs_q = cr.scan_with_jobs(o, q.policy_id, ag, ["queued"])
        inv = uuid4()
        o.execute(
            "INSERT INTO scan_job (job_id, kind, agent_id, payload, pickup_by)"
            " VALUES (%s, 'inventory', %s, '{}', now() + interval '1 day')",
            (inv, ag),
        )
        s1, s2 = cr.schedule(o, p.policy_id), cr.schedule(o, p.policy_id)
        s3 = cr.schedule(o, p.policy_id, enabled=False)
        sq = cr.schedule(o, q.policy_id)
        other_jobs = [
            jobs_p["dispatched"],
            jobs_p["running"],
            jobs_p["completed"],
            jobs_q["queued"],
            inv,
        ]
        before_other = job_rows(o, other_jobs)
    with app(server) as c, c.transaction():
        before = state(c, p.policy_id)
        eff = adm.soft_delete_effects(c, p.policy_id, T2)
    assert eff is not None
    assert eff.cancelled_job_ids == sorted([jobs_p["queued"], retry])
    assert eff.disabled_schedule_ids == sorted([s1, s2])
    assert eff.retired_plugin_uuids == sorted([owned_listed, q_owned, owned_unlisted])
    with owner(server) as o:
        jobs = job_rows(o, [jobs_p["queued"], retry])
        assert all(v == ("cancelled", T2) for v in jobs.values())
        assert job_rows(o, other_jobs) == before_other
        en = dict(o.execute(
            "SELECT schedule_id, enabled FROM scan_schedule"
            " WHERE schedule_id = ANY(%s)",
            ([s1, s2, s3, sq],),
        ).fetchall())  # fmt: skip
        assert en == {s1: False, s2: False, s3: False, sq: True}
        after = state(o, p.policy_id)
        assert (
            after[:3] == before[:3] and after[4] == before[4]
        )  # statuses, version kept
        assert (after[3], after[5], after[6]) == (T2, T2, f"deleted/{p.policy_id}")
        states = dict(o.execute(
            "SELECT plugin_uuid, state::text FROM plugin WHERE plugin_uuid = ANY(%s)",
            ([owned_listed, shared, q_owned, owned_unlisted, q_live],),
        ).fetchall())  # fmt: skip
        assert states == {
            owned_listed: "retired", shared: "active", q_owned: "retired",
            owned_unlisted: "retired", q_live: "active",
        }  # fmt: skip
        kept = o.execute(
            "SELECT count(*) FROM policy_plugin WHERE policy_id = %s", (p.policy_id,)
        ).fetchone()
        assert kept == (3,)  # #104 (a)
        assert o.execute(
            "SELECT count(*) FROM policy WHERE policy_id = %s", (p.policy_id,)
        ).fetchone() == (1,)
        sums = {t: cr.checksum(o, t, k) for t, k in [("scan_job", "job_id"),
                ("scan_schedule", "schedule_id"), ("policy", "policy_id"),
                ("plugin", "plugin_uuid")]}  # fmt: skip
    # a second delete is refused and changes nothing
    with app(server) as c, c.transaction():
        assert adm.soft_delete_effects(c, p.policy_id, T2 + (T2 - T1)) is None
        assert adm.soft_delete_effects(c, 2**62, T2) is None
    with owner(server) as o:
        assert sums == {t: cr.checksum(o, t, k) for t, k in [("scan_job", "job_id"),
                ("scan_schedule", "schedule_id"), ("policy", "policy_id"),
                ("plugin", "plugin_uuid")]}  # fmt: skip


def test_soft_delete_rolls_back_with_the_caller(server: PgServer) -> None:
    with app(server) as s, s.transaction():
        p = policy(s)
        member(s, p, [plugin(s, p)])
    with owner(server) as o:
        _, jobs = cr.scan_with_jobs(o, p.policy_id, cr.agent(o), ["queued"])
        cr.schedule(o, p.policy_id)
        before = {t: cr.checksum(o, t, k) for t, k in [("scan_job", "job_id"),
                  ("scan_schedule", "schedule_id"), ("policy", "policy_id"),
                  ("plugin", "plugin_uuid")]}  # fmt: skip
    with app(server) as c:
        with pytest.raises(RuntimeError), c.transaction():
            assert adm.soft_delete_effects(c, p.policy_id, T1) is not None
            raise RuntimeError("fault before commit")
    with owner(server) as o:
        assert before == {t: cr.checksum(o, t, k) for t, k in [("scan_job", "job_id"),
                ("scan_schedule", "schedule_id"), ("policy", "policy_id"),
                ("plugin", "plugin_uuid")]}  # fmt: skip


def test_app_can_never_delete_a_policy_row(conn: Conn) -> None:
    p = policy(conn)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("DELETE FROM policy WHERE policy_id = %s", (p.policy_id,))


# CHK-M7-169: integrity reads ---------------------------------------------------------


def test_integrity_rows_count_listed_and_bad_plugins(conn: Conn) -> None:
    good, bad, empty = policy(conn), policy(conn), policy(conn)
    dead = policy(conn, deleted=True)
    member(conn, good, [plugin(conn, good), plugin(conn, good)])
    foreign = plugin(conn, good)
    member(conn, bad, [plugin(conn, bad), plugin(conn, bad, state="retired"), foreign])
    member(conn, dead, [plugin(conn, dead)])
    rows = {r.policy_id: r for r in integ.integrity_rows(conn)}
    assert dead.policy_id not in rows
    for pol, count, bad_n in ((good, 2, 0), (bad, 3, 2), (empty, 0, 0)):
        r = rows[pol.policy_id]
        assert (r.plugin_count, r.bad_plugins) == (count, bad_n), pol
        assert r.source_sha256 == sha(pol.name)
    assert list(rows) == sorted(rows)


def test_rejected_files_only_pairs_with_a_rejected_row(conn: Conn) -> None:
    from bitscan_manager.repositories import imports as rep

    a, b = f"{tag()}.bit", f"{tag()}.bit"
    ha, hb = sha("a"), sha("b")
    rep.insert_import(conn, rep.ImportRecord(a, ha, "auto", "rejected"), T0)
    rep.insert_import(conn, rep.ImportRecord(a, ha, "manual", "success", 1), T1)
    rep.insert_import(conn, rep.ImportRecord(b, hb, "auto", "success", 1), T0)
    rep.insert_import(conn, rep.ImportRecord(b, ha, "auto", "rejected"), T0)
    got = integ.rejected_files(conn, [(a, ha), (b, hb), (a, hb), ("missing.bit", ha)])
    assert got == {(a, ha)}
    assert integ.rejected_files(conn, []) == set()
