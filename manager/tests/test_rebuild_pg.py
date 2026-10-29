"""TP-M7-17 (TASK-157): the catalog rebuild on PostgreSQL with temporary
folders (Linux only).

CHK-M7-216, -217 (tests/m7/test-plan.md). Expected values come from the spec
and the approved answers, not from the code: TS §4.2 L540 (re-import every
file of both folders, never skipped, one savepoint per file, a rejected file
keeps its rows, the rebuild commits as a whole, upsert by natural key so ids
stay, gone files deleted, unreferenced plugins retired, tracked in `task`),
L542 (rebuild is the recovery path; it never truncates, never touches
`agent`, inventory, `scan_*` or audit tables), §4.1 L526 (the lock until the
renames are done), §4.3 L550; REQ-166 (1)–(6); #20 (rejected files still end
`succeeded`), #23 and "TASK-157 rulings" (2) (one `policy_rebuilt`, one
`policy_imported` per changed policy, one `policy_import_rejected` per
rejected file), ruling (1) (#98 (j): an internal error rolls everything back,
no rows, the task `failed` with `{error}` and one failed `bits.rebuild`),
ruling (5) (a refused copy is listed as not imported), #98 (g), the
crash-window ruling (a leftover is removed and listed, never revived), the
case (c) ruling (relocated like an upload).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import sql

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.importer import rebuild as rb
from bitscan_manager.services.importer import uploads
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.pipeline import store_in_savepoint as real_store
from bitscan_manager.services.importer.rebuild import FAILED, RebuildResult

from . import catalog_rows as cr
from .catalog_rows import T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, counters, delta, doc, make_env, plug, sha
from .test_uploads_pg import REAL_REPLACE

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(os.name != "posix", reason="Linux file semantics (W only)"),
]

ADMIN = Actor("user:21", 21)
CLI = Actor("cli:root", None)
RESULT_KEYS = {
    "files", "deleted_policy_ids", "plugins_retired", "removed_leftovers",
    "not_imported",
}  # fmt: skip
FILE_KEYS = {"source_file", "import_id", "outcome", "policy_id", "policy_version"}
UNTOUCHED = ["agent", "agent_package", "os_info", "scan", "scan_job", "scan_result",
             "scan_schedule"]  # fmt: skip


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("rebuild")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    # Each test owns its folders; earlier tests' live policies are
    # soft-deleted first, so this rebuild does not delete them (files gone).
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
    yield from make_env(server, tmp_path)


def rebuild(e: Env, actor: Actor = ADMIN) -> RebuildResult:
    tid = rb.start_task(e.db, e.clock, actor.user_id)
    return rb.run(e.db, e.clock, e.bits, tid, actor)


def task(e: Env, tid: UUID) -> imports_repo.TaskRow:
    with app(e.server) as c:
        row = imports_repo.get_task(c, tid)
    assert row is not None
    return row


def table_sum(e: Env, table: str) -> str:
    with owner(e.server) as c:
        q = sql.SQL(
            "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"
            " FROM {} t"
        ).format(sql.Identifier(table))
        row = c.execute(q).fetchone()
    assert row is not None
    return str(row[0])


def audit_upto(e: Env, mark: int) -> str:
    with owner(e.server) as c:
        row = c.execute(
            "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY audit_id), ''))"
            " FROM audit_log t WHERE audit_id <= %s",
            (mark,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def rebuilt_count() -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": "policy_rebuilt"})
    return 0.0 if v is None else v


def kinds(entries: list[dict[str, Any]]) -> list[str]:
    return [e["detail"].get("alert_kind") for e in entries if e["detail"].get("alert")]


def put(e: Env, rel: str, data: bytes) -> Path:
    p = e.bits / rel
    p.write_bytes(data)
    return p


def upload(e: Env, data: bytes) -> int:
    out = uploads.upload(e.db, e.clock, e.bits, data, b"c.bit", ADMIN)
    assert out.outcome == "success"
    return out.policy_id or 0


# CHK-M7-216: REQ-166 (1) a corrupted catalog is restored, ids unchanged ---------


def test_a_corrupted_catalog_is_restored_with_every_id_unchanged(env: Env) -> None:
    t = tag()
    p = {k: [plug(f"cat /etc/{k}1"), plug(f"cat /etc/{k}2")] for k in "abcde"}
    for k, ps in p.items():
        put(env, f"{k}.bit", doc(f"R {k} {t}", ps))
    first = rebuild(env)
    assert first.state == "succeeded"
    ids = {rel: o.policy_id for rel, o in first.files}
    good = env.catalog()
    with owner(env.server) as c:  # REQ-166 (1), four kinds; e.bit untouched
        c.execute("UPDATE plugin SET execute = 'cat /etc/evil' WHERE plugin_uuid = %s",
                  (p["a"][1].uuid,))  # fmt: skip
        c.execute("DELETE FROM policy_plugin WHERE policy_id = %s AND plugin_uuid = %s",
                  (ids["b.bit"], p["b"][1].uuid))  # fmt: skip
        c.execute("UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
                  (p["c"][0].uuid,))  # fmt: skip
        c.execute("UPDATE policy SET policy_status = 'disabled' WHERE policy_id = %s",
                  (ids["d.bit"],))  # fmt: skip
    assert env.catalog() != good
    m0, c0 = env.mark(), counters()
    result = rebuild(env)
    assert result.state == "succeeded"
    assert {rel: o.policy_id for rel, o in result.files} == ids  # ids unchanged
    for k, ps in p.items():
        pid = ids[f"{k}.bit"] or 0
        assert env.members(pid) == [(ps[0].uuid, 1), (ps[1].uuid, 2)]
        assert env.policy(pid)["policy_status"] == "enabled"
        for x in ps:
            row = env.plugin(x.uuid)
            assert (row["execute"], row["state"], row["owner_policy_id"]) == (
                x.execute, "active", pid,
            )  # fmt: skip
    entries = env.entries(m0)
    imported = sorted(e["target"] for e in entries if e["action"] == "policy.import")
    assert imported == sorted(f"policy:{ids[f'{k}.bit']}" for k in "abcd")  # not e
    assert kinds(entries).count("policy_rebuilt") == 1
    d = delta(c0)
    assert d.get("policy_imported") == 4.0 and "policy_import_rejected" not in d


# CHK-M7-217: REQ-166 (2)–(6) ----------------------------------------------------------


def test_one_rejected_of_three_keeps_its_rows_and_the_task_succeeds(env: Env) -> None:
    t, pb = tag(), plug()
    put(env, "x.bit", doc(f"X {t}", [plug()]))
    put(env, "y.bit", doc(f"Y {t}", [pb]))
    put(env, "z.bit", doc(f"Z {t}", [plug()]))
    rebuild(env)
    y = env.policy_by_name(f"Y {t}")
    assert y is not None
    kept = (y, env.members(y["policy_id"]), env.plugin(pb.uuid))
    put(env, "x.bit", doc(f"X {t}", [plug()], desc="v2"))
    put(env, "y.bit", doc(f"Y {t}", [pb, plug("rm x")]))  # BIT102 (stable)
    put(env, "z.bit", doc(f"Z {t}", [plug()], desc="v2"))
    m0, i0, c0, r0 = env.mark(), env.last_import(), counters(), rebuilt_count()
    result = rebuild(env)
    assert result.state == "succeeded"  # #20
    tr = task(env, result.task_id)
    assert (tr.kind, tr.state, tr.requested_by) == ("rebuild", "succeeded", 21)
    assert tr.finished_at is not None and tr.result is not None
    assert set(tr.result) == RESULT_KEYS
    files = {f["source_file"]: f for f in tr.result["files"]}
    assert all(set(f) == FILE_KEYS for f in files.values())
    assert {k: f["outcome"] for k, f in files.items()} == {
        "x.bit": "success", "y.bit": "rejected", "z.bit": "success",
    }  # fmt: skip
    assert files["y.bit"]["policy_version"] is None
    rows = env.imports_after(i0)
    assert sorted((r["file_name"], r["outcome"], r["mode"]) for r in rows) == [
        ("x.bit", "success", "rebuild"), ("y.bit", "rejected", "rebuild"),
        ("z.bit", "success", "rebuild"),
    ]  # fmt: skip
    assert {f["import_id"] for f in files.values()} == {r["import_id"] for r in rows}
    y2 = env.policy(y["policy_id"])
    assert (y2, env.members(y["policy_id"]), env.plugin(pb.uuid)) == kept
    entries = env.entries(m0)
    assert sorted(kinds(entries)) == sorted(
        ["policy_imported", "policy_imported", "policy_import_rejected",
         "policy_rebuilt"]
    )  # fmt: skip
    reb = [e for e in entries if e["action"] == "bits.rebuild"]
    assert len(reb) == 1 and reb[0]["actor"] == "user:21"
    rd = reb[0]["detail"]
    assert (rd["state"], rd["files_imported"], rd["files_rejected"]) == (
        "succeeded",
        2,
        1,
    )
    assert rd["task_id"] == str(result.task_id)
    assert delta(c0) == {
        "policy_imported": 2.0, "policy_import_rejected": 1.0, "fail:rebuild": 1.0,
    }  # fmt: skip
    assert rebuilt_count() - r0 == 1.0


def test_unchanged_files_are_never_skipped_and_alert_nothing(env: Env) -> None:
    for i in range(3):
        put(env, f"u{i}.bit", doc(f"U{i} {tag()}", [plug()]))
    rebuild(env)
    m0, i0, cat0, c0 = env.mark(), env.last_import(), env.catalog(), counters()
    result = rebuild(env)
    assert [o.outcome for _, o in result.files] == ["success"] * 3  # never skipped
    assert [r["outcome"] for r in env.imports_after(i0)] == ["success"] * 3
    entries = env.entries(m0)
    assert [e["action"] for e in entries] == ["bits.rebuild"]  # no policy.import
    assert env.catalog() == cat0 and delta(c0) == {}


def test_untouched_tables_stay_untouched(env: Env) -> None:
    t = tag()
    put(env, "s.bit", doc(f"S {t}", [plug()]))
    pid = rebuild(env).files[0][1].policy_id or 0
    with owner(env.server) as c:
        agent = cr.agent(c)
        cr.scan_with_jobs(c, pid, agent, ["queued", "running"])
        cr.schedule(c, pid)
    put(env, "s.bit", doc(f"S {t}", [plug()], desc="changed"))
    mark = env.mark()
    before = {tb: table_sum(env, tb) for tb in UNTOUCHED}
    audit0 = audit_upto(env, mark)
    assert rebuild(env).state == "succeeded"
    assert {tb: table_sum(env, tb) for tb in UNTOUCHED} == before
    assert audit_upto(env, mark) == audit0  # only new entries were appended


def test_a_removed_file_deletes_its_policy_with_its_alert(env: Env) -> None:
    gone = put(env, "gone.bit", doc(f"Gone {tag()}", [plug()]))
    put(env, "keep.bit", doc(f"Keep {tag()}", [plug()]))
    up = upload(env, doc(f"UpGone {tag()}", [plug()]))
    first = dict(rebuild(env).files)
    gone.unlink()
    (env.bits / "uploaded" / f"policy-{up}.bit").unlink()
    m0, c0 = env.mark(), counters()
    result = rebuild(env)
    gid = first["gone.bit"].policy_id
    assert sorted(result.deleted_policy_ids) == sorted([gid or 0, up])
    res: Any = task(env, result.task_id).result
    assert sorted(res["deleted_policy_ids"]) == sorted([gid or 0, up])
    dels = [e for e in env.entries(m0) if e["action"] == "policy.delete"]
    assert {d["detail"]["reason"] for d in dels} == {"file removed"} and len(dels) == 2
    assert delta(c0)["policy_deleted"] == 2.0
    for pid in (gid, up):
        assert env.policy(pid or 0)["source_file"] == f"deleted/{pid}"


def test_a_database_error_midway_leaves_everything_as_before(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = tag()
    foreign = put(env, "uploaded/foreign.bit", doc(f"F {t}", [plug()]))  # staged 1st
    for k in ("v", "w", "z"):
        put(env, f"{k}.bit", doc(f"{k} {t}", [plug()]))
    i0, m0, cat0, c0 = env.last_import(), env.mark(), env.catalog(), counters()
    r0 = rebuilt_count()
    real = real_store
    calls: list[str] = []

    def failing(*a: Any, **k: Any) -> Any:
        calls.append(a[3].file_name)
        if len(calls) == 3:
            raise psycopg.errors.QueryCanceled("injected")
        return real(*a, **k)

    monkeypatch.setattr(rb, "store_in_savepoint", failing)
    result = rebuild(env)
    monkeypatch.undo()
    assert calls[0] == "uploaded/foreign.bit" and len(calls) == 3
    assert result.state == "failed" and result.files == []
    tr = task(env, result.task_id)
    assert (tr.state, tr.result) == ("failed", {"error": FAILED})
    assert tr.finished_at is not None
    assert env.catalog() == cat0 and env.imports_after(i0) == []  # #98 (j)
    entries = env.entries(m0)
    assert [e["action"] for e in entries] == ["bits.rebuild"]
    assert entries[0]["detail"]["state"] == "failed"
    assert delta(c0) == {} and rebuilt_count() - r0 == 1.0
    assert foreign.exists()
    up = sorted(p.name for p in (env.bits / "uploaded").iterdir())
    assert up == ["foreign.bit"]  # the staged temp was discarded


def test_a_leftover_is_removed_and_listed_never_revived(env: Env) -> None:
    pid = upload(env, doc(f"Left {tag()}", [plug()]))
    left = env.bits / "uploaded" / f"policy-{pid}.bit"
    with app(env.server) as c, c.transaction():
        assert adm.soft_delete_effects(c, pid, T2) is not None
    i0, m0 = env.last_import(), env.mark()
    result = rebuild(env)
    assert not left.exists()
    rel = f"uploaded/policy-{pid}.bit"
    assert result.removed_leftovers == [rel]
    assert task(env, result.task_id).result["removed_leftovers"] == [rel]  # type: ignore[index]
    reb = [e for e in env.entries(m0) if e["action"] == "bits.rebuild"]
    assert reb[0]["detail"]["removed_leftovers"] == [rel]
    assert [r for r in env.imports_after(i0) if r["file_name"] == rel] == []
    assert env.policy(pid)["deleted_at"] is not None  # never revived


def test_a_case_c_file_is_relocated(env: Env) -> None:
    data = doc(f"C {tag()}", [plug()])
    foreign = put(env, "uploaded/foreign.bit", data)
    result = rebuild(env)
    ((rel, out),) = result.files
    assert (rel, out.outcome) == ("uploaded/foreign.bit", "success")
    stored = env.bits / "uploaded" / f"policy-{out.policy_id}.bit"
    assert stored.read_bytes() == data and not foreign.exists()
    assert sorted(p.name for p in (env.bits / "uploaded").iterdir()) == [stored.name]
    assert env.policy(out.policy_id or 0)["source_file"] == f"uploaded/{stored.name}"
    assert env.policy(out.policy_id or 0)["source_sha256"] == sha(data)


def test_a_refused_copy_is_listed_as_not_imported(env: Env) -> None:
    name = f"Managed {tag()}"
    put(env, "managed.bit", doc(name, [plug()]))
    rebuild(env)
    copy = put(env, "uploaded/copy.bit", doc(name, [plug()], desc="copy"))
    i0 = env.last_import()
    result = rebuild(env)
    assert result.not_imported == ["uploaded/copy.bit"]
    assert task(env, result.task_id).result["not_imported"] == ["uploaded/copy.bit"]  # type: ignore[index]
    assert [r["file_name"] for r in env.imports_after(i0)] == ["managed.bit"]
    assert copy.exists()


def test_the_lock_is_held_including_the_renames(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(env, "uploaded/foreign.bit", doc(f"L {tag()}", [plug()]))
    seen: list[bool] = []

    def probe(src: Any, dst: Any) -> None:
        with app(env.server) as c:
            row = c.execute(
                "SELECT pg_try_advisory_lock(hashtext('catalog'))"
            ).fetchone()
            if row == (True,):
                c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        seen.append(row == (True,))
        REAL_REPLACE(src, dst)

    monkeypatch.setattr(os, "replace", probe)
    assert rebuild(env).state == "succeeded"
    monkeypatch.undo()
    assert seen == [False]


def test_a_rebuild_waits_for_the_catalog_lock(env: Env) -> None:
    put(env, "w.bit", doc(f"Wait {tag()}", [plug()]))
    tid = rb.start_task(env.db, env.clock, None)
    with app(env.server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        out: dict[str, RebuildResult] = {}
        th = threading.Thread(
            target=lambda: out.update(r=rb.run(env.db, env.clock, env.bits, tid, CLI))
        )
        th.start()
        th.join(2.0)
        assert th.is_alive() and task(env, tid).state == "running"
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        th.join(30)
    assert out["r"].state == "succeeded"
    tr = task(env, tid)
    assert (tr.state, tr.requested_by) == ("succeeded", None)
    reb = [e for e in env.entries(0) if e["action"] == "bits.rebuild"
           and e["detail"]["task_id"] == str(tid)]  # fmt: skip
    assert [e["actor"] for e in reb] == ["cli:root"]


def test_rows_never_shrink(env: Env) -> None:
    for i in range(2):
        put(env, f"n{i}.bit", doc(f"N{i} {tag()}", [plug()]))
    rebuild(env)
    with owner(env.server) as c:
        before = c.execute("SELECT (SELECT count(*) FROM policy),"
                           " (SELECT count(*) FROM plugin),"
                           " (SELECT count(*) FROM family)").fetchone()  # fmt: skip
    (env.bits / "n0.bit").unlink()
    rebuild(env)
    with owner(env.server) as c:
        after = c.execute("SELECT (SELECT count(*) FROM policy),"
                          " (SELECT count(*) FROM plugin),"
                          " (SELECT count(*) FROM family)").fetchone()  # fmt: skip
    assert before == after  # soft delete and retire only; nothing truncated


def test_no_file_name_or_content_in_the_logs(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    marker = f"mk{tag()}"
    put(env, f"{marker}.bit", doc(f"{marker} p", [plug(f"cat /etc/{marker}")]))
    put(env, f"uploaded/{marker}.bit", doc(f"{marker} c", [plug()]))
    rebuild(env)

    def failing(*a: Any, **k: Any) -> Any:
        raise psycopg.errors.QueryCanceled(marker)

    monkeypatch.setattr(rb, "store_in_savepoint", failing)
    rebuild(env)
    monkeypatch.undo()
    assert marker not in caplog.text
    assert "rebuild failed: QueryCanceled" in caplog.text


# TASK-157 r1 (blocking defect from review): a staged upload target counts as
# present, so the rebuild never deletes the policy it has just imported.


def test_a_relocated_foreign_file_leaves_its_new_policy_live(env: Env) -> None:
    data = doc(f"Foreign live {tag()}", [plug()])
    foreign = put(env, "uploaded/foreign.bit", data)
    m0, c0 = env.mark(), counters()
    result = rebuild(env)
    ((_, out),) = result.files
    pid = out.policy_id or 0
    pol = env.policy(pid)
    assert (pol["deleted_at"], pol["source_file"]) == (
        None,
        f"uploaded/policy-{pid}.bit",
    )
    assert (env.bits / "uploaded" / f"policy-{pid}.bit").read_bytes() == data
    assert not foreign.exists()
    assert result.deleted_policy_ids == []
    res: Any = task(env, result.task_id).result
    assert res["deleted_policy_ids"] == []
    assert "policy_deleted" not in delta(c0)
    assert "policy.delete" not in [e["action"] for e in env.entries(m0)]


def test_a_live_upload_naming_a_new_policy_leaves_both_live(env: Env) -> None:
    holder = upload(env, doc(f"Holder {tag()}", [plug()]))
    own = env.bits / "uploaded" / f"policy-{holder}.bit"
    other = doc(f"Named inside {tag()}", [plug()])
    own.write_bytes(other)  # case (a) file whose content names a new policy
    m0, c0 = env.mark(), counters()
    result = rebuild(env)
    ((_, out),) = result.files
    pid = out.policy_id or 0
    assert pid != holder
    pol = env.policy(pid)
    assert (pol["deleted_at"], pol["source_file"]) == (
        None,
        f"uploaded/policy-{pid}.bit",
    )
    assert (env.bits / "uploaded" / f"policy-{pid}.bit").read_bytes() == other
    assert env.policy(holder)["deleted_at"] is None  # its own file is still there
    assert own.read_bytes() == other
    assert result.deleted_policy_ids == []
    assert "policy_deleted" not in delta(c0)
    assert "policy.delete" not in [e["action"] for e in env.entries(m0)]


@pytest.mark.parametrize("server_name", ["zz.bit", "aa.bit"])
def test_one_new_name_in_an_upload_file_and_a_server_file(
    env: Env, server_name: str
) -> None:
    # The accepted exception (lead, 2026-10-28): in one rebuild,
    # uploaded/foreign.bit and a server-folder file both name the same new
    # policy. The server folder wins (TS L524). #15 decides the order: both
    # are new, so byte order; "uploaded/foreign.bit" sorts before "zz.bit"
    # and after "aa.bit".
    name = f"Both {tag()}"
    foreign = put(env, "uploaded/foreign.bit", doc(name, [plug()], desc="upload"))
    srv = put(env, server_name, doc(name, [plug()], desc="server"))
    m0, c0 = env.mark(), counters()
    result = rebuild(env)
    assert result.state == "succeeded" and result.deleted_policy_ids == []
    pol = env.policy_by_name(name)
    assert pol is not None
    assert (pol["deleted_at"], pol["source_file"]) == (None, server_name)
    assert pol["source_sha256"] == sha(srv.read_bytes())
    up = sorted(p.name for p in (env.bits / "uploaded").iterdir())
    assert not any(n.startswith(".tmp-") for n in up)
    assert f"policy-{pol['policy_id']}.bit" not in up  # no upload copy
    assert "policy.delete" not in [e["action"] for e in env.entries(m0)]
    assert "policy_deleted" not in delta(c0)
    if server_name == "zz.bit":  # the upload first, then the server file moves it
        assert not foreign.exists() and up == []
        assert [rel for rel, _ in result.files] == ["uploaded/foreign.bit", "zz.bit"]
    else:  # the server file first; the upload copy is then refused and stays
        assert foreign.exists() and up == ["foreign.bit"]
        assert result.not_imported == ["uploaded/foreign.bit"]
