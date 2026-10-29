"""TP-M7-10 (TASK-148): catalog repository for imports, as bitscan_app.

CHK-M7-150 to -156 (tests/m7/test-plan.md). Expected values: SR §3.1 to §3.4,
§3.6 steps 1 to 5; TS §4.1 L519, §4.3 L548 to L550, §5.2 (DDL and grants);
approved answers #14 (revival adds 1), #21 (counts), #100 (a), #104 (b), (d),
(e); design note D3. A database of this module's own (``own_migrated_server``),
because retire works catalog-wide. Each test runs in a transaction that is
rolled back, unless it needs a second connection.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from bitscan_manager.repositories import catalog as cat
from bitscan_manager.repositories import catalog_plugins as cp
from bitscan_manager.repositories.catalog import PolicyValues
from bitscan_manager.repositories.catalog_plugins import PluginValues

from .catalog_rows import T0, T1, T2, Conn, app, sha, tag
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("catrepo")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[Conn]:
    """bitscan_app inside a transaction that is always rolled back."""
    with app(server) as c, c.transaction(force_rollback=True):
        yield c


def pvalues(conn: Conn, **kw: object) -> PolicyValues:
    t = tag()
    base: dict[str, object] = {
        "policy_name": f"Policy {t}",
        "policy_description": "desc",
        "file_status": "enabled",
        "family_id": cat.upsert_family(conn, f"Family {t}", T0),
        "format_version": "1.0",
        "source_file": f"{t}.bit",
        "source_sha256": sha(t),
    }
    base.update(kw)
    return PolicyValues(**base)  # type: ignore[arg-type]


def new_policy(conn: Conn, **kw: object) -> cat.PolicyRow:
    values = pvalues(conn, **kw)
    return cat.insert_policy(conn, cat.next_policy_id(conn), values, T0)


def plug(**kw: object) -> PluginValues:
    execute = str(kw.pop("execute", f"echo {tag()}"))
    base: dict[str, object] = {
        "plugin_uuid": uuid4(),
        "plugin_name": "1.1 - Check",
        "control_ref": "1.1",
        "plugin_description": "d",
        "execute": execute,
        "execute_sha256": sha(execute),
        "timeout_s": 60,
        "operator": "equals",
        "expected_result": "x",
    }
    base.update(kw)
    return PluginValues(**base)  # type: ignore[arg-type]


def plugin_row(conn: Conn, uuid: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT family_id, owner_policy_id, plugin_name, control_ref,"
        " plugin_description, execute, execute_sha256, timeout_s, operator::text,"
        " expected_result, state::text, updated_at FROM plugin WHERE plugin_uuid = %s",
        (uuid,),
    ).fetchone()
    assert row is not None
    return tuple(row)


# CHK-M7-150: grants and families ---------------------------------------------


def test_app_role_has_exactly_the_spec_catalog_grants(conn: Conn) -> None:
    def priv(table: str, p: str) -> bool:
        row = conn.execute(
            "SELECT has_table_privilege(current_user, %s, %s)", (table, p)
        ).fetchone()
        assert row is not None
        return bool(row[0])

    for table in ("family", "policy", "plugin"):
        assert priv(table, "UPDATE") and not priv(table, "DELETE"), table
    assert priv("policy_plugin", "DELETE") and not priv("policy_plugin", "UPDATE")
    assert not priv("bit_import", "UPDATE") and not priv("bit_import", "DELETE")


def test_upsert_family_same_name_same_id_never_changed(conn: Conn) -> None:
    name = f"Fam {tag()}"
    first = cat.upsert_family(conn, name, T0)
    again = cat.upsert_family(conn, name, T2)
    other = cat.upsert_family(conn, name + " 2", T1)
    assert first == again != other
    rows = conn.execute(
        "SELECT family_id, family_name, created_at FROM family"
        " WHERE family_name LIKE %s ORDER BY family_id",
        (name + "%",),
    ).fetchall()
    assert rows == [(first, name, T0), (other, name + " 2", T1)]


def test_upsert_family_is_exact_not_case_folded(conn: Conn) -> None:
    name = f"Fam {tag()}"
    assert cat.upsert_family(conn, name, T0) != cat.upsert_family(
        conn, name.upper(), T0
    )
    assert cat.upsert_family(conn, name, T0) != cat.upsert_family(conn, name + " ", T0)


def test_concurrent_family_upserts_agree_on_one_row(server: PgServer) -> None:
    # The second INSERT ... ON CONFLICT waits for the first, then SELECTs it.
    name = f"Race {tag()}"
    out: dict[str, int] = {}
    with app(server) as a, app(server) as b:
        a.execute("BEGIN")
        out["a"] = cat.upsert_family(a, name, T0)

        def second() -> None:
            with b.transaction():
                out["b"] = cat.upsert_family(b, name, T1)

        t = threading.Thread(target=second)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "second upsert did not wait for the first"
        a.execute("COMMIT")
        t.join(10)
        assert not t.is_alive()
    assert out["a"] == out["b"]


# CHK-M7-150/151: policies -------------------------------------------------------


def test_insert_policy_version_1_status_from_file(conn: Conn) -> None:
    pid = cat.next_policy_id(conn)
    values = pvalues(conn, file_status="disabled", policy_description="")
    row = cat.insert_policy(conn, pid, values, T0)
    assert row.policy_id == pid
    assert (row.version, row.policy_status, row.file_status) == (
        1,
        "disabled",
        "disabled",
    )
    assert row.status_overridden is False and row.deleted_at is None
    assert (row.imported_at, row.updated_at) == (T0, T0)
    assert (row.policy_name, row.source_file, row.source_sha256) == (
        values.policy_name,
        values.source_file,
        values.source_sha256,
    )
    assert row.policy_description == "" and row.format_version == "1.0"
    assert cat.policy_by_id_for_update(conn, pid) == row


def test_next_policy_id_is_unique_and_usable_for_an_upload_path(conn: Conn) -> None:
    a, b = cat.next_policy_id(conn), cat.next_policy_id(conn)
    assert b > a
    row = cat.insert_policy(
        conn, b, pvalues(conn, source_file=f"uploaded/policy-{b}.bit"), T0
    )
    assert row.source_file == f"uploaded/policy-{b}.bit"


def test_lookups_by_name_source_and_id_include_deleted_rows(conn: Conn) -> None:
    row = new_policy(conn)
    for got in (
        cat.policy_by_name_for_update(conn, row.policy_name),
        cat.policy_by_source_file_for_update(conn, row.source_file),
        cat.policy_by_id_for_update(conn, row.policy_id),
    ):
        assert got == row
    conn.execute(
        "UPDATE policy SET deleted_at = %s, source_file = 'deleted/' || policy_id"
        " WHERE policy_id = %s",
        (T1, row.policy_id),
    )
    dead = cat.policy_by_name_for_update(conn, row.policy_name)
    assert dead is not None and dead.deleted_at == T1
    assert dead.source_file == f"deleted/{row.policy_id}"
    assert cat.policy_by_source_file_for_update(conn, row.source_file) is None
    assert cat.policy_by_name_for_update(conn, row.policy_name.lower()) is None
    assert cat.policy_by_name_for_update(conn, "no such " + tag()) is None
    assert cat.policy_by_id_for_update(conn, 2**62) is None


@pytest.mark.parametrize("how", ["name", "source", "id"])
def test_lookups_lock_the_row_for_update(server: PgServer, how: str) -> None:
    with app(server) as setup, setup.transaction():
        row = new_policy(setup)
    with app(server) as a, app(server) as b:
        with a.transaction():
            if how == "name":
                cat.policy_by_name_for_update(a, row.policy_name)
            elif how == "source":
                cat.policy_by_source_file_for_update(a, row.source_file)
            else:
                cat.policy_by_id_for_update(a, row.policy_id)
            with pytest.raises(psycopg.errors.LockNotAvailable), b.transaction():
                b.execute(
                    "SELECT 1 FROM policy WHERE policy_id = %s FOR UPDATE NOWAIT",
                    (row.policy_id,),
                )
        with b.transaction():
            b.execute(
                "SELECT 1 FROM policy WHERE policy_id = %s FOR UPDATE NOWAIT",
                (row.policy_id,),
            )


def test_update_identical_values_keeps_version_and_updated_at(conn: Conn) -> None:
    row = new_policy(conn)
    values = PolicyValues(
        row.policy_name,
        row.policy_description,
        row.file_status,
        row.family_id,
        row.format_version,
        row.source_file,
        row.source_sha256,
    )
    after = cat.update_policy(conn, row.policy_id, values, T2)
    assert after is not None
    assert after.version == 1 and after.updated_at == T0
    assert after.imported_at == T2  # #104 (d): the time of the last import
    assert replace(after, imported_at=T0) == row


def _same(row: cat.PolicyRow, **kw: object) -> PolicyValues:
    base = PolicyValues(
        row.policy_name,
        row.policy_description,
        row.file_status,
        row.family_id,
        row.format_version,
        row.source_file,
        row.source_sha256,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_update_changed_hash_adds_exactly_one(conn: Conn) -> None:
    row = new_policy(conn)
    a = cat.update_policy(conn, row.policy_id, _same(row, source_sha256=sha("v2")), T1)
    b = cat.update_policy(conn, row.policy_id, _same(row, source_sha256=sha("v3")), T2)
    c = cat.update_policy(conn, row.policy_id, _same(row, source_sha256=sha("v3")), T2)
    assert a is not None and b is not None and c is not None
    assert (a.version, b.version, c.version) == (2, 3, 3)
    assert (a.updated_at, b.updated_at, c.updated_at) == (T1, T2, T2)


@pytest.mark.parametrize(
    ("override", "effective", "file_value", "want_effective"),
    [
        (True, "disabled", "enabled", "disabled"),  # never re-enables (TS §4.3 L548)
        (True, "enabled", "disabled", "enabled"),
        (False, "disabled", "enabled", "enabled"),
        (False, "enabled", "disabled", "disabled"),
    ],
)
def test_update_status_respects_the_override(
    conn: Conn, override: bool, effective: str, file_value: str, want_effective: str
) -> None:
    row = new_policy(conn, file_status=effective)
    conn.execute(
        "UPDATE policy SET status_overridden = %s, policy_status = %s"
        " WHERE policy_id = %s",
        (override, effective, row.policy_id),
    )
    after = cat.update_policy(
        conn,
        row.policy_id,
        _same(row, file_status=file_value, source_sha256=sha("n")),
        T1,
    )
    assert after is not None
    assert after.file_status == file_value
    assert after.policy_status == want_effective
    assert after.status_overridden is override


def test_revival_adds_one_even_for_identical_bytes_and_keeps_override(
    conn: Conn,
) -> None:
    row = new_policy(conn)
    conn.execute(
        "UPDATE policy SET deleted_at = %s, source_file = 'deleted/' || policy_id,"
        " status_overridden = true, policy_status = 'disabled' WHERE policy_id = %s",
        (T1, row.policy_id),
    )
    after = cat.update_policy(conn, row.policy_id, _same(row), T2)
    assert after is not None
    assert after.policy_id == row.policy_id
    assert after.version == 2  # #14
    assert after.deleted_at is None and after.source_file == row.source_file
    assert after.status_overridden is True and after.policy_status == "disabled"
    assert after.updated_at == T2


def test_rename_in_place_keeps_id_and_moves_updated_at(conn: Conn) -> None:
    row = new_policy(conn)
    new_name = f"Renamed {tag()}"
    after = cat.update_policy(conn, row.policy_id, _same(row, policy_name=new_name), T1)
    assert after is not None
    assert (after.policy_id, after.policy_name, after.version) == (
        row.policy_id,
        new_name,
        1,
    )
    assert after.updated_at == T1
    assert cat.policy_by_name_for_update(conn, row.policy_name) is None


@pytest.mark.parametrize(
    "field",
    ["policy_description", "family", "format_version", "source_file"],
)
def test_update_any_stored_column_moves_updated_at(conn: Conn, field: str) -> None:
    row = new_policy(conn)
    changes: dict[str, dict[str, object]] = {
        "policy_description": {"policy_description": "other"},
        "family": {"family_id": cat.upsert_family(conn, f"F2 {tag()}", T0)},
        "format_version": {"format_version": "1.0 "},
        "source_file": {"source_file": f"moved-{tag()}.bit"},
    }
    change = changes[field]
    after = cat.update_policy(conn, row.policy_id, _same(row, **change), T1)
    assert after is not None and after.updated_at == T1 and after.version == 1


def test_update_unknown_id_is_none(conn: Conn) -> None:
    row = new_policy(conn)
    assert cat.update_policy(conn, 2**62, _same(row), T1) is None


def test_unique_name_and_source_file_are_enforced(conn: Conn) -> None:
    row = new_policy(conn)
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        new_policy(conn, policy_name=row.policy_name)
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        new_policy(conn, source_file=row.source_file)


# CHK-M7-152: BIT015 owners ---------------------------------------------------


def test_owners_of_reports_owner_deleted_and_listing(conn: Conn) -> None:
    a = new_policy(conn)
    b = new_policy(conn)
    listed, dropped, dead, fresh = plug(), plug(), plug(), uuid4()
    for p, owner_id in ((listed, a), (dropped, a), (dead, b)):
        cp.upsert_plugins(
            conn,
            [p],
            family_id=owner_id.family_id,
            owner_policy_id=owner_id.policy_id,
            now=T0,
        )
    cp.replace_membership(conn, a.policy_id, [listed.plugin_uuid])
    cp.replace_membership(conn, b.policy_id, [dead.plugin_uuid])
    conn.execute(
        "UPDATE policy SET deleted_at = %s WHERE policy_id = %s", (T1, b.policy_id)
    )
    got = cat.owners_of(
        conn, [fresh, dead.plugin_uuid, listed.plugin_uuid, dropped.plugin_uuid]
    )
    by = {o.plugin_uuid: o for o in got}
    assert set(by) == {listed.plugin_uuid, dropped.plugin_uuid, dead.plugin_uuid}
    assert by[listed.plugin_uuid] == cat.Owner(
        listed.plugin_uuid, a.policy_id, a.policy_name, False, True
    )
    assert by[dropped.plugin_uuid] == cat.Owner(
        dropped.plugin_uuid, a.policy_id, a.policy_name, False, False
    )
    assert by[dead.plugin_uuid] == cat.Owner(
        dead.plugin_uuid, b.policy_id, b.policy_name, True, True
    )
    assert cat.owners_of(conn, []) == []


def test_owner_lists_means_the_owner_itself_lists_it(conn: Conn) -> None:
    # Listed by another policy only: the owner does not list it (BIT015 asks
    # whether the *owner* still lists it).
    a, b = new_policy(conn), new_policy(conn)
    p = plug()
    cp.upsert_plugins(
        conn, [p], family_id=a.family_id, owner_policy_id=a.policy_id, now=T0
    )
    cp.replace_membership(conn, b.policy_id, [p.plugin_uuid])
    (o,) = cat.owners_of(conn, [p.plugin_uuid])
    assert (o.owner_id, o.owner_lists) == (a.policy_id, False)


# CHK-M7-153: plugin upsert and the #21 counts ----------------------------------


def test_first_upsert_reports_every_plugin_added(conn: Conn) -> None:
    pol = new_policy(conn)
    ps = [plug(), plug(control_ref=None), plug(timeout_s=1)]
    got = cp.upsert_plugins(
        conn, ps, family_id=pol.family_id, owner_policy_id=pol.policy_id, now=T0
    )
    assert sorted(got) == sorted((p.plugin_uuid, True) for p in ps)
    row = plugin_row(conn, ps[1].plugin_uuid)
    assert row[:2] == (pol.family_id, pol.policy_id)
    assert row[3] is None and row[10] == "active" and row[11] == T0


def test_identical_upsert_reports_nothing_and_keeps_updated_at(conn: Conn) -> None:
    pol = new_policy(conn)
    ps = [plug(), plug()]
    kw = {"family_id": pol.family_id, "owner_policy_id": pol.policy_id}
    cp.upsert_plugins(conn, ps, now=T0, **kw)
    before = [plugin_row(conn, p.plugin_uuid) for p in ps]
    assert cp.upsert_plugins(conn, ps, now=T2, **kw) == []
    assert [plugin_row(conn, p.plugin_uuid) for p in ps] == before


CHANGES: dict[str, dict[str, object]] = {
    "plugin_name": {"plugin_name": "1.1 - Renamed"},
    "control_ref_to_null": {"control_ref": None},
    "control_ref": {"control_ref": "1.2"},
    "plugin_description": {"plugin_description": "other"},
    "execute": {"execute": "echo changed", "execute_sha256": sha("echo changed")},
    "timeout_s": {"timeout_s": 600},
    "operator": {"operator": "contains"},
    "expected_result": {"expected_result": "y"},
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_each_changed_column_counts_as_updated(conn: Conn, change: str) -> None:
    pol = new_policy(conn)
    p = plug()
    kw = {"family_id": pol.family_id, "owner_policy_id": pol.policy_id}
    cp.upsert_plugins(conn, [p], now=T0, **kw)
    q = replace(p, **CHANGES[change])  # type: ignore[arg-type]
    assert cp.upsert_plugins(conn, [q], now=T1, **kw) == [(p.plugin_uuid, False)]
    row = plugin_row(conn, p.plugin_uuid)
    assert row[2:10] == (
        q.plugin_name,
        q.control_ref,
        q.plugin_description,
        q.execute,
        q.execute_sha256,
        q.timeout_s,
        q.operator,
        q.expected_result,
    )
    assert row[11] == T1


def test_family_owner_and_reactivation_count_as_updated(conn: Conn) -> None:
    a, b = new_policy(conn), new_policy(conn)
    p1, p2, p3 = plug(), plug(), plug()
    cp.upsert_plugins(
        conn, [p1, p2, p3], family_id=a.family_id, owner_policy_id=a.policy_id, now=T0
    )
    # owner changes (a claim, BIT015 allowed)
    assert cp.upsert_plugins(
        conn, [p1], family_id=a.family_id, owner_policy_id=b.policy_id, now=T1
    ) == [(p1.plugin_uuid, False)]
    # family changes (#104 (e): plugins follow the policy's family)
    assert cp.upsert_plugins(
        conn, [p2], family_id=b.family_id, owner_policy_id=a.policy_id, now=T1
    ) == [(p2.plugin_uuid, False)]
    # retired -> active (#21)
    conn.execute(
        "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s", (p3.plugin_uuid,)
    )
    assert cp.upsert_plugins(
        conn, [p3], family_id=a.family_id, owner_policy_id=a.policy_id, now=T1
    ) == [(p3.plugin_uuid, False)]
    assert plugin_row(conn, p1.plugin_uuid)[1] == b.policy_id
    assert plugin_row(conn, p2.plugin_uuid)[0] == b.family_id
    assert plugin_row(conn, p3.plugin_uuid)[10] == "active"


def test_mixed_file_counts(conn: Conn) -> None:
    # 2 new, 1 changed, 1 unchanged, 1 retired then re-listed (#21).
    pol = new_policy(conn)
    kw = {"family_id": pol.family_id, "owner_policy_id": pol.policy_id}
    changed, same, back = plug(), plug(), plug()
    cp.upsert_plugins(conn, [changed, same, back], now=T0, **kw)
    conn.execute(
        "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
        (back.plugin_uuid,),
    )
    new1, new2 = plug(), plug()
    got = cp.upsert_plugins(
        conn,
        [new1, replace(changed, expected_result="z"), same, back, new2],
        now=T1,
        **kw,
    )
    assert sorted(got) == sorted(
        [
            (new1.plugin_uuid, True),
            (new2.plugin_uuid, True),
            (changed.plugin_uuid, False),
            (back.plugin_uuid, False),
        ]
    )
    assert sum(1 for _, ins in got if ins) == 2  # plugins_added
    assert sum(1 for _, ins in got if not ins) == 2  # plugins_updated


def test_batches_over_500_behave_as_one(conn: Conn) -> None:
    pol = new_policy(conn)
    kw = {"family_id": pol.family_id, "owner_policy_id": pol.policy_id}
    ps = [plug(execute=f"echo {i}") for i in range(1001)]  # 500 + 500 + 1
    got = cp.upsert_plugins(conn, ps, now=T0, **kw)
    assert sorted(got) == sorted((p.plugin_uuid, True) for p in ps)
    ps2 = list(ps)
    ps2[1000] = replace(ps[1000], plugin_name="1.1 - last changed")
    ps2[0] = replace(ps[0], timeout_s=5)
    got2 = cp.upsert_plugins(conn, ps2, now=T1, **kw)
    assert sorted(got2) == sorted(
        [(ps[0].plugin_uuid, False), (ps[1000].plugin_uuid, False)]
    )
    assert cp.upsert_plugins(conn, [], now=T1, **kw) == []


def test_current_plugins_returns_stored_hashes(conn: Conn) -> None:
    pol = new_policy(conn)
    p = plug()
    cp.upsert_plugins(
        conn, [p], family_id=pol.family_id, owner_policy_id=pol.policy_id, now=T0
    )
    fresh = uuid4()
    assert cp.current_plugins(conn, [p.plugin_uuid, fresh]) == {
        p.plugin_uuid: p.execute_sha256
    }
    assert cp.current_plugins(conn, []) == {}


# CHK-M7-154: membership ----------------------------------------------------------


def members(conn: Conn, policy_id: int) -> list[tuple[UUID, int]]:
    return [
        (UUID(str(u)), int(n))
        for u, n in conn.execute(
            "SELECT plugin_uuid, sort_order FROM policy_plugin WHERE policy_id = %s"
            " ORDER BY sort_order",
            (policy_id,),
        ).fetchall()
    ]


def test_replace_membership_orders_1_based_and_replaces(conn: Conn) -> None:
    a, b = new_policy(conn), new_policy(conn)
    ps = [plug() for _ in range(4)]
    cp.upsert_plugins(
        conn, ps, family_id=a.family_id, owner_policy_id=a.policy_id, now=T0
    )
    u = [p.plugin_uuid for p in ps]
    cp.replace_membership(conn, a.policy_id, u[:3])
    cp.replace_membership(conn, b.policy_id, [u[3]])
    assert members(conn, a.policy_id) == [(u[0], 1), (u[1], 2), (u[2], 3)]
    cp.replace_membership(conn, a.policy_id, [u[2], u[0]])  # reorder and remove
    assert members(conn, a.policy_id) == [(u[2], 1), (u[0], 2)]
    cp.replace_membership(conn, a.policy_id, [u[1], u[2], u[0], u[3]])  # add
    assert members(conn, a.policy_id) == [(u[1], 1), (u[2], 2), (u[0], 3), (u[3], 4)]
    assert members(conn, b.policy_id) == [(u[3], 1)]  # other policies untouched
    cp.replace_membership(conn, a.policy_id, [])
    assert members(conn, a.policy_id) == []


# CHK-M7-155: retire --------------------------------------------------------------


def test_retire_unreferenced_exact_set(conn: Conn) -> None:
    cp.retire_unreferenced(conn, T0)  # baseline: whatever earlier tests left
    live, dead = new_policy(conn), new_policy(conn)
    kw_live = {"family_id": live.family_id, "owner_policy_id": live.policy_id}
    kw_dead = {"family_id": dead.family_id, "owner_policy_id": dead.policy_id}
    keep, only_dead, nobody, both, already = plug(), plug(), plug(), plug(), plug()
    cp.upsert_plugins(conn, [keep, nobody, already], now=T0, **kw_live)
    cp.upsert_plugins(conn, [only_dead, both], now=T0, **kw_dead)
    cp.replace_membership(conn, live.policy_id, [keep.plugin_uuid, both.plugin_uuid])
    cp.replace_membership(
        conn, dead.policy_id, [only_dead.plugin_uuid, both.plugin_uuid]
    )
    conn.execute(
        "UPDATE policy SET deleted_at = %s WHERE policy_id = %s", (T0, dead.policy_id)
    )
    conn.execute(
        "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
        (already.plugin_uuid,),
    )
    before_already = plugin_row(conn, already.plugin_uuid)
    count = conn.execute("SELECT count(*) FROM plugin").fetchone()
    got = cp.retire_unreferenced(conn, T2)
    assert got == sorted([only_dead.plugin_uuid, nobody.plugin_uuid])
    for p, state in (
        (keep, "active"),
        (both, "active"),
        (only_dead, "retired"),
        (nobody, "retired"),
    ):
        assert plugin_row(conn, p.plugin_uuid)[10] == state
    assert plugin_row(conn, nobody.plugin_uuid)[11] == T2
    assert plugin_row(conn, already.plugin_uuid) == before_already
    assert (
        conn.execute("SELECT count(*) FROM plugin").fetchone() == count
    )  # never deleted
    assert members(conn, dead.policy_id) != []  # #104 (a): rows kept
    assert cp.retire_unreferenced(conn, T2) == []


# CHK-M7-156: hostile and boundary values ----------------------------------------

HOSTILE = [
    "'; DROP TABLE policy; --",
    "%s %(now)s {} \\x00 \\",
    '<script>alert("x")</script>',
    "‮evil​﻿",
    "Überprüfung ✓ 検査 🛡",
    "\x01\x1f\x7f",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_text_round_trips_byte_identical(conn: Conn, text: str) -> None:
    pol = new_policy(
        conn,
        policy_name=text + tag(),
        policy_description=text,
        source_file=text + tag(),
    )
    got = cat.policy_by_id_for_update(conn, pol.policy_id)
    assert got is not None
    assert got.policy_name.startswith(text) and got.policy_description == text
    fam = cat.upsert_family(conn, text, T0)
    assert cat.upsert_family(conn, text, T1) == fam
    p = plug(
        plugin_name=text, plugin_description=text, execute=text, expected_result=text
    )
    cp.upsert_plugins(conn, [p], family_id=fam, owner_policy_id=pol.policy_id, now=T0)
    row = plugin_row(conn, p.plugin_uuid)
    assert row[2] == text and row[4] == text and row[5] == text and row[9] == text
    assert cat.owners_of(conn, [p.plugin_uuid])[0].owner_name == got.policy_name


def test_boundary_lengths_fit_the_columns(conn: Conn) -> None:
    pol = new_policy(conn, policy_name="é" * 128)
    fam = cat.upsert_family(conn, "é" * 128, T0)
    p = plug(
        plugin_name="é" * 255,
        control_ref="1" * 32,
        execute="é" * 16384,
        expected_result="é" * 4000,
        plugin_description="é" * 4000,
        timeout_s=600,
    )
    cp.upsert_plugins(conn, [p], family_id=fam, owner_policy_id=pol.policy_id, now=T0)
    row = plugin_row(conn, p.plugin_uuid)
    assert (len(str(row[2])), len(str(row[3])), len(str(row[5]))) == (255, 32, 16384)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        cp.upsert_plugins(
            conn,
            [plug(timeout_s=601)],
            family_id=fam,
            owner_policy_id=pol.policy_id,
            now=T0,
        )


def test_now_is_stored_exactly_with_microseconds(conn: Conn) -> None:
    pol = new_policy(conn)
    assert pol.imported_at == T0 and T0.microsecond == 123450
    assert pol.updated_at - T0 == timedelta(0)


# TASK-148 r1: retired_among (the #100 (a) widening, user 2026-10-27) ----------


def test_retired_among_returns_only_the_retired_ids(conn: Conn) -> None:
    pol = new_policy(conn)
    kw = {"family_id": pol.family_id, "owner_policy_id": pol.policy_id}
    live, gone1, gone2 = plug(), plug(), plug()
    cp.upsert_plugins(conn, [live, gone1, gone2], now=T0, **kw)
    conn.execute(
        "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = ANY(%s)",
        ([gone1.plugin_uuid, gone2.plugin_uuid],),
    )
    unknown = uuid4()
    got = cp.retired_among(
        conn, [live.plugin_uuid, gone1.plugin_uuid, unknown, gone2.plugin_uuid]
    )
    assert got == frozenset({gone1.plugin_uuid, gone2.plugin_uuid})
    assert cp.retired_among(conn, [live.plugin_uuid, unknown]) == frozenset()


def test_retired_among_empty_input_runs_no_statement(conn: Conn) -> None:
    class NoQuery:
        def execute(self, *a: object, **k: object) -> object:
            raise AssertionError("a statement was sent for an empty input")

    assert cp.retired_among(NoQuery(), []) == frozenset()  # type: ignore[arg-type]
