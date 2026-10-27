"""TP-M7-11 (TASK-151): the import store (SR §3.6) on PostgreSQL, as bitscan_app.

CHK-M7-173 to -184 (tests/m7/test-plan.md); plan work/plans/TASK-151.md §6
rows 1 to 12. Expected values: SR §3.1 to §3.6, §4.1 BIT007 and BIT015; TS §4.1
L519, L522, L524; §4.3 L548 to L550; REQ-158 (1) to (6), REQ-159 (1) to (5);
#14 (revival adds 1, override kept), #21 (counts), #100 (a), #104, #106. The
``Candidate`` and ``RuleKeys`` are built here, as TASK-144 will build them.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import catalog_plugins
from bitscan_manager.services.importer import store
from bitscan_manager.services.importer import store_decide as sd
from bitscan_manager.services.importer.model import Code
from bitscan_manager.services.importer.store import (
    Candidate,
    CandidatePlugin,
    RuleId,
    RuleKeys,
    Target,
)

from . import catalog_rows as cr
from .catalog_rows import T0, T1, T2, Conn, app, owner, sha, tag
from .conftest import PgServer, own_migrated_server
from .test_bit_fixtures import sr_example

pytestmark = pytest.mark.pg

NONE: Callable[[str], bool] = lambda path: False  # noqa: E731
ALL: Callable[[str], bool] = lambda path: True  # noqa: E731


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("store")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[Conn]:
    with app(server) as c, c.transaction(force_rollback=True):
        yield c


def cp(**kw: Any) -> CandidatePlugin:
    execute = str(kw.pop("execute", f"echo {tag()}"))
    base: dict[str, Any] = {
        "plugin_uuid": uuid4(),
        "line": 10,
        "plugin_name": "1.1 - Check",
        "control_ref": "1.1",
        "plugin_description": "d",
        "execute": execute,
        "execute_sha256": hashlib.sha256(execute.encode()).hexdigest(),
        "operator": "equals",
        "expected_result": "x",
        "timeout_s": 60,
    }
    base.update(kw)
    return CandidatePlugin(**base)


def cand(plugins: list[CandidatePlugin] | None = None, **kw: Any) -> Candidate:
    base: dict[str, Any] = {
        "policy_name": f"Policy {tag()}",
        "policy_name_line": 3,
        "policy_description": "desc",
        "file_status": "enabled",
        "family_name": f"Family {tag()}",
        "format_version": "1.0",
        "plugins": tuple(plugins if plugins is not None else [cp()]),
    }
    base.update(kw)
    return Candidate(**base)


def rules(c: Candidate) -> RuleKeys:
    return RuleKeys(
        c.policy_name,
        c.policy_name_line,
        tuple(
            RuleId(p.plugin_uuid, 10 + 7 * i, i + 1) for i, p in enumerate(c.plugins)
        ),
    )


def server_t(path: str, digest: str | None = None) -> Target:
    return Target("server", path, digest or sha(path + tag()))


def upload_t(digest: str | None = None) -> Target:
    return Target("upload", None, digest or sha(tag()))


def run(
    conn: Conn, c: Candidate, t: Target, exists: Callable[[str], bool] = NONE
) -> tuple[store.Decision, tuple[Any, ...], store.StoreResult | None]:
    d = sd.decide(conn, rules(c), t, exists)
    f = d.findings + sd.check_ownership(conn, d, rules(c))
    if f or d.case == "rejected":
        return d, f, None
    return d, f, store.apply(conn, d, c, t, T1)


def ok(
    conn: Conn, c: Candidate, t: Target, exists: Callable[[str], bool] = NONE
) -> store.StoreResult:
    d, f, r = run(conn, c, t, exists)
    assert f == () and r is not None, (d.case, f)
    return r


def policy(conn: Conn, pid: int) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT policy_id, policy_name, policy_description, policy_status::text,"
        " file_status::text, status_overridden, family_id, format_version, version,"
        " source_file, source_sha256, deleted_at, imported_at, updated_at"
        " FROM policy WHERE policy_id = %s",
        (pid,),
    )
    row = cur.fetchone()
    assert row is not None
    return dict(zip([d.name for d in cur.description or []], row, strict=True))


def plugin(conn: Conn, u: UUID) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT family_id, owner_policy_id, plugin_name, control_ref,"
        " plugin_description, execute, execute_sha256, timeout_s, operator::text,"
        " expected_result,"
        " state::text FROM plugin WHERE plugin_uuid = %s",
        (u,),
    )
    row = cur.fetchone()
    assert row is not None
    return dict(zip([d.name for d in cur.description or []], row, strict=True))


def members(conn: Conn, pid: int) -> list[tuple[UUID, int]]:
    return [
        (UUID(str(u)), int(n))
        for u, n in conn.execute(
            "SELECT plugin_uuid, sort_order FROM policy_plugin WHERE policy_id = %s"
            " ORDER BY sort_order",
            (pid,),
        ).fetchall()
    ]


# Row 1 / CHK-M7-173 ---------------------------------------------------------------

SR_UUID = UUID("3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48")
SR_DESC = "CIS Benchmark Level 1 controls for Ubuntu 24.04 servers."
SR_EXEC = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"


def sr_candidate() -> Candidate:
    return Candidate(
        policy_name="CIS Ubuntu 24.04 Level 1 - Server",
        policy_name_line=3,
        policy_description=SR_DESC,
        file_status="enabled",
        family_name="CIS Ubuntu 24.04",
        format_version="1.0",
        plugins=(
            CandidatePlugin(
                plugin_uuid=SR_UUID,
                line=13,
                plugin_name="1.3.1.1 - Ensure AppArmor is installed",
                control_ref="1.3.1.1",
                plugin_description="Checks that the AppArmor package is installed.",
                execute=SR_EXEC,
                execute_sha256=hashlib.sha256(SR_EXEC.encode()).hexdigest(),
                operator="equals",
                expected_result="install ok installed",
                timeout_s=30,
            ),
        ),
    )


def test_sr_example_stores_exactly_the_req_158_1_rows(conn: Conn) -> None:
    file_sha = hashlib.sha256(sr_example()).hexdigest()
    r = ok(conn, sr_candidate(), Target("server", "x.bit", file_sha))
    assert (r.version, r.plugins_added, r.plugins_updated, r.plugins_retired) == (
        1,
        1,
        0,
        0,
    )
    assert (r.renamed_from, r.moved_from, r.revived, r.reenabled) == (
        None,
        None,
        False,
        False,
    )
    assert (r.deleted_policy_ids, r.remove_after_commit, r.source_file) == (
        (),
        (),
        "x.bit",
    )
    assert [(c.plugin_uuid, c.reason) for c in r.changed_executes] == [(SR_UUID, "new")]
    p = policy(conn, r.policy_id)
    assert {k: p[k] for k in ("policy_name", "policy_description", "policy_status",
            "file_status", "status_overridden", "format_version", "version",
            "source_file", "source_sha256", "deleted_at")} == {
        "policy_name": "CIS Ubuntu 24.04 Level 1 - Server",
        "policy_description": SR_DESC,
        "policy_status": "enabled", "file_status": "enabled",
        "status_overridden": False,
        "format_version": "1.0", "version": 1, "source_file": "x.bit",
        "source_sha256": file_sha, "deleted_at": None,
    }  # fmt: skip
    fam = conn.execute(
        "SELECT family_name FROM family WHERE family_id = %s", (p["family_id"],)
    ).fetchone()
    assert fam == ("CIS Ubuntu 24.04",)
    assert plugin(conn, SR_UUID) == {
        "family_id": p["family_id"], "owner_policy_id": r.policy_id,
        "plugin_name": "1.3.1.1 - Ensure AppArmor is installed",
        "control_ref": "1.3.1.1",
        "plugin_description": "Checks that the AppArmor package is installed.",
        "execute": SR_EXEC,
        "execute_sha256": hashlib.sha256(SR_EXEC.encode()).hexdigest(),
        "timeout_s": 30, "operator": "equals",
        "expected_result": "install ok installed",
        "state": "active",
    }  # fmt: skip
    assert members(conn, r.policy_id) == [(SR_UUID, 1)]
    dn = conn.execute(
        "SELECT display_name FROM v_plugin WHERE plugin_uuid = %s", (SR_UUID,)
    ).fetchone()
    assert dn == ("CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed",)


# Row 2 / CHK-M7-174 ---------------------------------------------------------------


def test_identical_reimport_keeps_version_and_ids_changed_adds_one(conn: Conn) -> None:
    c = cand([cp(), cp()])
    t = server_t(f"{tag()}.bit")
    first = ok(conn, c, t)
    d = sd.decide(conn, rules(c), t, NONE)
    assert d.case == "update" and sd.is_unchanged(d, t)
    again = store.apply(conn, d, c, t, T2)
    assert (again.policy_id, again.version) == (first.policy_id, 1)
    assert (again.plugins_added, again.plugins_updated, again.plugins_retired) == (
        0,
        0,
        0,
    )
    assert again.changed_executes == ()
    t2 = replace(t, file_sha256=sha("other bytes"))
    d2 = sd.decide(conn, rules(c), t2, NONE)
    assert not sd.is_unchanged(d2, t2)
    assert store.apply(conn, d2, c, t2, T2).version == 2
    t3 = replace(t, file_sha256=sha("third"))
    assert ok(conn, c, t3).version == 3


def test_is_unchanged_only_for_a_live_update_of_the_same_file_and_hash(
    conn: Conn,
) -> None:
    c = cand()
    t = server_t(f"{tag()}.bit")
    ok(conn, c, t)
    assert sd.is_unchanged(sd.decide(conn, rules(c), t, NONE), t)
    other = cand(policy_name=f"New {tag()}")
    assert not sd.is_unchanged(sd.decide(conn, rules(other), t, NONE), t)  # rename


# Row 3 / CHK-M7-175, row 11 --------------------------------------------------------


@pytest.mark.parametrize("override", [True, False])
def test_override_kept_by_a_file_update(conn: Conn, override: bool) -> None:
    c = cand(file_status="disabled")
    t = server_t(f"{tag()}.bit")
    r = ok(conn, c, t)
    if override:
        assert adm.set_status(conn, r.policy_id, "disabled", T1)
    later = ok(
        conn, replace(c, file_status="enabled"), replace(t, file_sha256=sha("v2"))
    )
    p = policy(conn, r.policy_id)
    assert p["file_status"] == "enabled"
    assert p["policy_status"] == ("disabled" if override else "enabled")
    assert p["status_overridden"] is override
    assert later.reenabled is (not override)  # row 11 (#101)


def test_disable_by_file_is_not_a_reenable(conn: Conn) -> None:
    c = cand()
    t = server_t(f"{tag()}.bit")
    ok(conn, c, t)
    r = ok(conn, replace(c, file_status="disabled"), replace(t, file_sha256=sha("x")))
    assert r.reenabled is False


def test_concurrent_patch_wins_over_a_waiting_import(server: PgServer) -> None:
    c = cand()
    t = server_t(f"{tag()}.bit")
    with app(server) as s, s.transaction():
        pid = ok(s, c, t).policy_id
    done: dict[str, Any] = {}
    with app(server) as patch, app(server) as imp:
        patch.execute("BEGIN")
        assert adm.set_status(patch, pid, "disabled", T1)

        def importer() -> None:
            with imp.transaction():
                done["r"] = ok(imp, c, replace(t, file_sha256=sha("v2")))

        th = threading.Thread(target=importer, daemon=True)
        th.start()
        th.join(1.0)
        assert th.is_alive(), "decide did not wait for the PATCH row lock"
        patch.execute("COMMIT")
        th.join(15)
        assert not th.is_alive()
    with app(server) as check:
        p = policy(check, pid)
    assert (p["policy_status"], p["status_overridden"], p["version"]) == (
        "disabled",
        True,
        2,
    )
    assert done["r"].reenabled is False


# Row 4 / CHK-M7-176, row 10 --------------------------------------------------------


def test_reorder_drop_and_change_counts(conn: Conn) -> None:
    a, b, c3 = cp(), cp(), cp()
    c = cand([a, b, c3])
    t = server_t(f"{tag()}.bit")
    pid = ok(conn, c, t).policy_id
    r = ok(conn, replace(c, plugins=(c3, a, b)), replace(t, file_sha256=sha("1")))
    assert (r.plugins_added, r.plugins_updated, r.plugins_retired) == (0, 0, 0)
    assert members(conn, pid) == [
        (c3.plugin_uuid, 1),
        (a.plugin_uuid, 2),
        (b.plugin_uuid, 3),
    ]
    r = ok(conn, replace(c, plugins=(c3, a)), replace(t, file_sha256=sha("2")))
    assert (r.plugins_added, r.plugins_updated, r.plugins_retired) == (0, 0, 1)
    assert plugin(conn, b.plugin_uuid)["state"] == "retired"  # row kept
    a2 = replace(a, execute="echo new", execute_sha256=sha("echo new"))
    r = ok(conn, replace(c, plugins=(c3, a2)), replace(t, file_sha256=sha("3")))
    assert (r.plugins_added, r.plugins_updated, r.plugins_retired) == (0, 1, 0)
    assert [
        (x.plugin_uuid, x.execute, x.execute_sha256, x.reason)
        for x in r.changed_executes
    ] == [(a.plugin_uuid, "echo new", sha("echo new"), "changed")]
    assert plugin(conn, a.plugin_uuid)["execute_sha256"] == sha("echo new")


def test_mixed_file_counts_2_1_1(conn: Conn) -> None:
    keep, change, drop = cp(), cp(), cp()
    c = cand([keep, change, drop])
    t = server_t(f"{tag()}.bit")
    ok(conn, c, t)
    n1, n2 = cp(), cp()
    changed = replace(change, plugin_name="1.1 - Renamed")
    r = ok(
        conn,
        replace(c, plugins=(n1, keep, changed, n2)),
        replace(t, file_sha256=sha("m")),
    )
    assert (r.plugins_added, r.plugins_updated, r.plugins_retired) == (2, 1, 1)
    assert [(x.plugin_uuid, x.reason) for x in r.changed_executes] == [
        (n1.plugin_uuid, "new"),
        (n2.plugin_uuid, "new"),
    ]  # keep (active, unchanged) and a rename-only change are not in it


def test_family_change_points_to_another_family_and_plugins_follow(conn: Conn) -> None:
    p1 = cp()
    c = cand([p1])
    t = server_t(f"{tag()}.bit")
    r = ok(conn, c, t)
    old_fam = policy(conn, r.policy_id)["family_id"]
    r2 = ok(
        conn, replace(c, family_name=f"Other {tag()}"), replace(t, file_sha256=sha("f"))
    )
    new_fam = policy(conn, r.policy_id)["family_id"]
    assert new_fam != old_fam and plugin(conn, p1.plugin_uuid)["family_id"] == new_fam
    assert r2.plugins_updated == 1
    assert conn.execute(
        "SELECT count(*) FROM family WHERE family_id = %s", (old_fam,)
    ).fetchone() == (1,)


# Row 5 / CHK-M7-177 ---------------------------------------------------------------


@pytest.mark.parametrize("existing", [False, True])
def test_fault_after_the_third_plugin_leaves_the_catalog_unchanged(
    server: PgServer, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    # The fault fires once 3 plugin rows were written, counted across calls,
    # and the catalog is read from another connection afterwards, so a commit
    # per plugin (CHK-M7-338) or per batch would show.
    c = cand([cp() for _ in range(5)])
    t = server_t(f"{tag()}.bit")
    with app(server) as s:
        if existing:
            with s.transaction():
                ok(s, c, t)
            v2 = tuple(replace(p, plugin_name="1.1 - v2") for p in c.plugins)
            c = replace(c, plugins=(*v2, cp()))
        with owner(server) as o:
            before = cr.catalog_checksums(o)
        real = catalog_plugins.upsert_plugins
        written = [0]

        def faulty(cn: Conn, plugins: Any, **kw: Any) -> Any:
            rows = list(plugins)
            room = 3 - written[0]
            if len(rows) > room:
                if room > 0:
                    real(cn, rows[:room], **kw)
                raise RuntimeError("fault after the third plugin")
            written[0] += len(rows)
            return real(cn, rows, **kw)

        monkeypatch.setattr(catalog_plugins, "upsert_plugins", faulty)
        with pytest.raises(RuntimeError), s.transaction():
            run(s, c, replace(t, file_sha256=sha("fault")))
    with owner(server) as o:
        assert cr.catalog_checksums(o) == before


# Row 6 / CHK-M7-178 ---------------------------------------------------------------


def test_revival_same_id_version_plus_one_override_kept_schedules_off(
    server: PgServer,
) -> None:
    p1, p2 = cp(), cp()
    c = cand([p1, p2])
    digest = sha("bytes" + tag())
    t = server_t(f"{tag()}.bit", digest)
    with app(server) as s, s.transaction():
        r = ok(s, c, t)
        assert adm.set_status(s, r.policy_id, "disabled", T1)
    with owner(server) as o:
        sch = cr.schedule(o, r.policy_id)
    with app(server) as s, s.transaction():
        assert adm.soft_delete_effects(s, r.policy_id, T1) is not None
    with app(server) as s, s.transaction():
        d = sd.decide(s, rules(c), t, NONE)  # identical bytes, the file is back
        assert d.case == "revive" and d.policy_id == r.policy_id
        assert not sd.is_unchanged(d, t)
        back = store.apply(s, d, c, t, T2)
        p = policy(s, r.policy_id)
        assert back.revived and back.policy_id == r.policy_id
        assert (p["version"], p["deleted_at"], p["source_file"]) == (
            2,
            None,
            t.source_file,
        )
        assert (p["status_overridden"], p["policy_status"]) == (True, "disabled")
        assert {plugin(s, x.plugin_uuid)["state"] for x in (p1, p2)} == {"active"}
        assert back.plugins_updated == 2  # retired -> active (#21)
        # #100 (a) widened: every plugin of a revival goes live again
        assert [(x.plugin_uuid, x.reason) for x in back.changed_executes] == [
            (p1.plugin_uuid, "reactivated"),
            (p2.plugin_uuid, "reactivated"),
        ]
    with owner(server) as o:
        en = o.execute(
            "SELECT enabled FROM scan_schedule WHERE schedule_id = %s", (sch,)
        ).fetchone()
        assert en == (False,)  # #14: schedules stay disabled


def test_upload_revival_of_a_server_policy_goes_to_uploaded(conn: Conn) -> None:
    c = cand()
    r = ok(conn, c, server_t(f"{tag()}.bit"))
    assert adm.soft_delete_effects(conn, r.policy_id, T1) is not None
    back = ok(conn, c, upload_t())
    assert back.policy_id == r.policy_id and back.revived
    assert back.source_file == f"uploaded/policy-{r.policy_id}.bit"


# Row 7 / CHK-M7-179, -180 ----------------------------------------------------------


def test_upload_decisions(conn: Conn) -> None:
    c = cand()
    d = sd.decide(conn, rules(c), upload_t(), NONE)
    assert (d.case, d.policy_id, d.displaced_id) == ("insert", None, None)
    r = ok(conn, c, upload_t())
    assert r.source_file == f"uploaded/policy-{r.policy_id}.bit"
    assert policy(conn, r.policy_id)["source_file"] == r.source_file
    d = sd.decide(conn, rules(c), upload_t(), NONE)
    assert (d.case, d.policy_id) == ("update", r.policy_id)
    srv = cand()
    rs = ok(conn, srv, server_t(f"{tag()}.bit"))
    before = cr.catalog_checksums(conn)
    with pytest.raises(store.PolicyManagedOnServer) as info:
        sd.decide(conn, rules(srv), upload_t(), NONE)
    assert info.value.policy_id == rs.policy_id
    assert str(info.value) == "policy_managed_on_server"
    assert cr.catalog_checksums(conn) == before


def test_bit007_when_the_other_server_file_still_exists(conn: Conn) -> None:
    c = cand()
    a = f"{tag()}-a.bit"
    ra = ok(conn, c, server_t(a))
    before = cr.catalog_checksums(conn)
    seen: list[str] = []

    def exists(path: str) -> bool:
        seen.append(path)
        return True

    b = f"{tag()}-b.bit"
    d = sd.decide(conn, rules(c), server_t(b), exists)
    assert d.case == "rejected" and seen == [a]
    (f,) = d.findings
    assert (f.code, f.line, f.element) == (Code.BIT007, 3, "Policy/PolicyName")
    assert a in f.message and c.policy_name in f.message
    assert cr.catalog_checksums(conn) == before
    with pytest.raises(ValueError):
        store.apply(conn, d, c, server_t(b), T1)
    assert policy(conn, ra.policy_id)["source_file"] == a


def test_move_when_the_other_server_file_is_gone(conn: Conn) -> None:
    c = cand()
    a = f"{tag()}-a.bit"
    digest = sha("same")
    ra = ok(conn, c, server_t(a, digest))
    cfile = f"{tag()}-c.bit"
    d = sd.decide(conn, rules(c), server_t(cfile, digest), NONE)
    assert (d.case, d.policy_id) == ("move_server", ra.policy_id)
    r = store.apply(conn, d, c, server_t(cfile, digest), T2)
    assert (r.policy_id, r.source_file, r.moved_from, r.version) == (
        ra.policy_id,
        cfile,
        a,
        1,
    )


def test_server_file_wins_over_an_upload(conn: Conn) -> None:
    c = cand()
    up = ok(conn, c, upload_t())
    s = f"{tag()}.bit"
    d = sd.decide(conn, rules(c), server_t(s), ALL)
    assert (d.case, d.policy_id) == ("move_upload", up.policy_id)
    r = store.apply(conn, d, c, server_t(s), T2)
    assert r.policy_id == up.policy_id and r.source_file == s
    assert r.moved_from == f"uploaded/policy-{up.policy_id}.bit"
    assert r.remove_after_commit == (f"uploaded/policy-{up.policy_id}.bit",)
    with pytest.raises(store.PolicyManagedOnServer):  # REQ-159 (3): later upload 409
        sd.decide(conn, rules(c), upload_t(), NONE)


def test_target_kind_and_path_must_agree() -> None:
    with pytest.raises(ValueError):
        Target("upload", "x.bit", "a" * 64)
    with pytest.raises(ValueError):
        Target("server", None, "a" * 64)


def test_invalid_policy_name_is_rejected_without_extra_findings(conn: Conn) -> None:
    c = cand()
    rk = RuleKeys(None, 3, rules(c).plugin_ids)
    d = sd.decide(conn, rk, server_t(f"{tag()}.bit"), NONE)
    assert d.case == "rejected" and d.findings == ()
    assert sd.check_ownership(conn, d, rk) == ()


# Row 8 / CHK-M7-181 (#106) ---------------------------------------------------------


def x_at_a(conn: Conn) -> tuple[str, store.StoreResult, Candidate]:
    a = f"{tag()}-a.bit"
    cx = cand()
    return a, ok(conn, cx, server_t(a)), cx


def test_106_y_in_another_existing_server_file_is_bit007(conn: Conn) -> None:
    a, rx, cx = x_at_a(conn)
    cy = cand()
    ry = ok(conn, cy, server_t(f"{tag()}-b.bit"))
    before = cr.catalog_checksums(conn)
    d, f, r = run(conn, replace(cx, policy_name=cy.policy_name), server_t(a), ALL)
    assert r is None and d.case == "rejected"
    # Every failing rule is reported (SR §4): besides BIT007, the file still
    # lists X's plugin, and X (live, not displaced since nothing moves) lists
    # it, so BIT015 names X. Reading reported to main 2026-10-27.
    assert [x.code for x in f] == [Code.BIT007, Code.BIT015]
    assert cx.policy_name in f[1].message
    assert cr.catalog_checksums(conn) == before
    assert policy(conn, rx.policy_id)["policy_name"] == cx.policy_name
    assert policy(conn, ry.policy_id)["deleted_at"] is None


def test_106_y_uploaded_moves_to_the_file_and_x_is_deleted(conn: Conn) -> None:
    a, rx, cx = x_at_a(conn)
    cy = cand()
    ry = ok(conn, cy, upload_t())
    d, f, r = run(conn, replace(cx, policy_name=cy.policy_name), server_t(a), ALL)
    assert f == () and r is not None and d.case == "move_upload"
    assert (d.policy_id, d.displaced_id) == (ry.policy_id, rx.policy_id)
    assert r.policy_id == ry.policy_id and r.source_file == a
    assert r.deleted_policy_ids == (rx.policy_id,)
    assert r.remove_after_commit == (f"uploaded/policy-{ry.policy_id}.bit",)
    px = policy(conn, rx.policy_id)
    assert px["deleted_at"] == T1 and px["source_file"] == f"deleted/{rx.policy_id}"


def test_106_y_deleted_is_revived_at_the_file_and_x_is_deleted(conn: Conn) -> None:
    a, rx, cx = x_at_a(conn)
    cy = cand()
    ry = ok(conn, cy, server_t(f"{tag()}-b.bit"))
    assert adm.soft_delete_effects(conn, ry.policy_id, T0) is not None
    d, f, r = run(conn, replace(cx, policy_name=cy.policy_name), server_t(a), NONE)
    assert f == () and r is not None and d.case == "revive"
    assert (r.policy_id, r.revived, r.deleted_policy_ids) == (
        ry.policy_id,
        True,
        (rx.policy_id,),
    )
    assert policy(conn, ry.policy_id)["source_file"] == a
    assert policy(conn, rx.policy_id)["deleted_at"] is not None


def test_106_y_absent_renames_x_in_place_keeping_its_scans(server: PgServer) -> None:
    with app(server) as s, s.transaction():
        a, rx, cx = x_at_a(s)
    with owner(server) as o:
        scan, _ = cr.scan_with_jobs(o, rx.policy_id, cr.agent(o), ["completed"])
    new = f"Renamed {tag()}"
    with app(server) as s, s.transaction():
        d, f, r = run(s, replace(cx, policy_name=new), server_t(a), NONE)
        assert f == () and r is not None and d.case == "rename"
        assert (r.policy_id, r.renamed_from, r.policy_name) == (
            rx.policy_id,
            cx.policy_name,
            new,
        )
        assert r.deleted_policy_ids == ()
        assert members(s, rx.policy_id) == [(cx.plugins[0].plugin_uuid, 1)]
    with owner(server) as o:
        row = o.execute(
            "SELECT policy_id FROM scan WHERE scan_id = %s", (scan,)
        ).fetchone()
        assert row == (rx.policy_id,)


# Row 9 / CHK-M7-182 (BIT015) -------------------------------------------------------


def test_bit015_when_the_owner_is_live_and_still_lists_it(conn: Conn) -> None:
    shared = cp()
    owner_c = cand([cp(), shared])
    ro = ok(conn, owner_c, server_t(f"{tag()}.bit"))
    claimer = cand([cp(), cp(), replace(shared, line=24)])
    before = cr.catalog_checksums(conn)
    d, f, r = run(conn, claimer, server_t(f"{tag()}.bit"))
    assert r is None
    (b,) = f
    assert (b.code, b.line, b.element) == (
        Code.BIT015,
        10 + 7 * 2,
        "Policy/PluginsGroups/Plugin[3]/PluginId",
    )
    assert owner_c.policy_name in b.message and str(shared.plugin_uuid) in b.message
    assert cr.catalog_checksums(conn) == before
    assert plugin(conn, shared.plugin_uuid)["owner_policy_id"] == ro.policy_id


@pytest.mark.parametrize("how", ["owner deleted", "owner dropped it"])
def test_claim_when_the_owner_is_deleted_or_no_longer_lists_it(
    conn: Conn, how: str
) -> None:
    shared, other = cp(), cp()
    owner_c = cand([other, shared])
    t = server_t(f"{tag()}.bit")
    ro = ok(conn, owner_c, t)
    if how == "owner deleted":
        assert adm.soft_delete_effects(conn, ro.policy_id, T1) is not None
    else:
        ok(conn, replace(owner_c, plugins=(other,)), replace(t, file_sha256=sha("d")))
    claimer = cand([shared])
    r = ok(conn, claimer, upload_t())
    assert plugin(conn, shared.plugin_uuid)["owner_policy_id"] == r.policy_id
    assert plugin(conn, shared.plugin_uuid)["state"] == "active"
    if how == "owner deleted":  # #104 (c): the deleted policy's row stays
        assert (shared.plugin_uuid, 2) in members(conn, ro.policy_id)


def test_no_bit015_for_self_or_the_displaced_policy(conn: Conn) -> None:
    a, rx, cx = x_at_a(conn)
    # self: re-import keeps its own plugin
    assert run(conn, cx, server_t(a, sha("again")))[1] == ()
    # displaced X: Y (uploaded) takes a.bit and lists X's plugin
    cy = cand([cp(), cx.plugins[0]])
    ok(conn, replace(cy, plugins=cy.plugins[:1]), upload_t())
    d, f, r = run(conn, replace(cy, policy_name=cy.policy_name), server_t(a), ALL)
    assert f == () and r is not None and d.displaced_id == rx.policy_id
    assert plugin(conn, cx.plugins[0].plugin_uuid)["owner_policy_id"] == r.policy_id


def test_bit015_findings_in_document_order(conn: Conn) -> None:
    s1, s2 = cp(), cp()
    ok(conn, cand([s1, s2]), server_t(f"{tag()}.bit"))
    claimer = cand([s2, cp(), s1])
    _, f, _ = run(conn, claimer, upload_t())
    assert [(x.code, x.element) for x in f] == [
        (Code.BIT015, "Policy/PluginsGroups/Plugin[1]/PluginId"),
        (Code.BIT015, "Policy/PluginsGroups/Plugin[3]/PluginId"),
    ]


# Row 12 / CHK-M7-184 ---------------------------------------------------------------


def test_no_policy_row_is_ever_deleted(conn: Conn) -> None:
    before = conn.execute("SELECT count(*) FROM policy").fetchone()
    a, rx, cx = x_at_a(conn)
    cy = cand()
    ok(conn, cy, upload_t())
    run(conn, replace(cx, policy_name=cy.policy_name), server_t(a), ALL)
    after = conn.execute("SELECT count(*) FROM policy").fetchone()
    assert before is not None and after == (before[0] + 2,)


def test_timestamps_follow_104_d(conn: Conn) -> None:
    c = cand()
    t = server_t(f"{tag()}.bit")
    r = ok(conn, c, t)
    p = policy(conn, r.policy_id)
    assert p["imported_at"] == T1 and p["updated_at"] == T1
    d = sd.decide(conn, rules(c), t, NONE)
    store.apply(conn, d, c, t, T2)
    p = policy(conn, r.policy_id)
    assert p["imported_at"] == T2 and p["updated_at"] == T1  # nothing stored changed


def test_revival_changed_executes_reactivated(conn: Conn) -> None:
    # #100 (a) widened (user, 2026-10-27): a revival with identical Executes
    # carries every plugin as reactivated (pinned as () before TASK-151 r2).
    p = cp(execute="cat /etc/shadow")
    c = cand([p])
    r = ok(conn, c, server_t(f"{tag()}.bit"))
    assert adm.soft_delete_effects(conn, r.policy_id, T1) is not None
    back = ok(conn, c, upload_t())
    assert back.revived
    assert [(x.plugin_uuid, x.execute, x.reason) for x in back.changed_executes] == [
        (p.plugin_uuid, "cat /etc/shadow", "reactivated")
    ]


def test_a_retired_plugin_listed_again_is_reactivated(conn: Conn) -> None:
    keep, back = cp(), cp()
    c = cand([keep, back])
    t = server_t(f"{tag()}.bit")
    ok(conn, c, t)
    ok(conn, replace(c, plugins=(keep,)), replace(t, file_sha256=sha("1")))
    r = ok(conn, c, replace(t, file_sha256=sha("2")))
    assert [(x.plugin_uuid, x.reason) for x in r.changed_executes] == [
        (back.plugin_uuid, "reactivated")
    ]  # keep is active and unchanged, so it is not in the alert


def test_106_takeover_from_the_displaced_policy_is_not_reactivated(conn: Conn) -> None:
    # (b) Y (uploaded) takes a.bit listing X's plugins: X is displaced, and its
    # plugins are read before step 1 retires them, so none is reactivated.
    a, rx, cx = x_at_a(conn)
    cy = cand()
    ok(conn, cy, upload_t())
    d, f, r = run(conn, replace(cx, policy_name=cy.policy_name), server_t(a), ALL)
    assert f == () and r is not None and d.case == "move_upload"
    assert r.changed_executes == ()
    # (c) Y deleted and revived at a.bit: a revive, so every plugin is reactivated
    a2, rx2, cx2 = x_at_a(conn)
    cz = cand()
    rz = ok(conn, cz, server_t(f"{tag()}-b.bit"))
    assert adm.soft_delete_effects(conn, rz.policy_id, T0) is not None
    d2, f2, r2 = run(conn, replace(cx2, policy_name=cz.policy_name), server_t(a2), NONE)
    assert f2 == () and r2 is not None and d2.case == "revive"
    assert [(x.plugin_uuid, x.reason) for x in r2.changed_executes] == [
        (cx2.plugins[0].plugin_uuid, "reactivated")
    ]


# TASK-151 r3: the crash-window ruling (user, 2026-10-27; plan §3.3 r3).


@pytest.mark.parametrize(
    "path", ["uploaded/policy-1.bit", "deleted/1", "a/b.bit", "/abs.bit", "sub/x.bit"]
)
def test_a_server_target_refuses_a_path_with_a_slash(path: str) -> None:
    with pytest.raises(ValueError):
        Target("server", path, "a" * 64)


def test_a_plain_server_file_name_is_accepted() -> None:
    assert Target("server", "a.bit", "a" * 64).source_file == "a.bit"


def test_is_unchanged_for_an_upload_target(conn: Conn) -> None:
    c = cand()
    digest = sha("upload bytes" + tag())
    r = ok(conn, c, upload_t(digest))
    same = upload_t(digest)
    d = sd.decide(conn, rules(c), same, NONE)
    assert d.case == "update" and sd.is_unchanged(d, same)
    other = upload_t(sha("other"))
    assert not sd.is_unchanged(sd.decide(conn, rules(c), other, NONE), other)
    # a deleted policy is never "unchanged" (its upload is a leftover or a revival)
    assert adm.soft_delete_effects(conn, r.policy_id, T1) is not None
    d2 = sd.decide(conn, rules(c), same, NONE)
    assert d2.case == "revive" and not sd.is_unchanged(d2, same)


def test_is_unchanged_still_compares_the_server_file(conn: Conn) -> None:
    c = cand()
    digest = sha("server bytes" + tag())
    ok(conn, c, server_t(f"{tag()}-a.bit", digest))
    moved = server_t(f"{tag()}-b.bit", digest)
    d = sd.decide(conn, rules(c), moved, NONE)
    assert d.case == "move_server" and not sd.is_unchanged(d, moved)
