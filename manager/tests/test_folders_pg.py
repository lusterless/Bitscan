"""TP-M7-16 (TASK-156): folder discovery, the `auto` reconcile and the
`uploaded/` classification, on PostgreSQL with temporary folders (Linux only:
symlinks, FIFOs, undecodable names).

CHK-M7-208 to -210 (tests/m7/test-plan.md) and the TASK-156 row's extra tests
(i) to (iv). Expected values come from the spec and the approved answers, not
from the code: TS §4.1 L515 (both folders), L522 (uploads kept only as
`uploaded/policy-<id>.bit`), L524 (the server folder wins, the move is
audit-logged), L526 (disk matches the catalog), L528 (start-up imports new or
changed files and deletes policies whose files disappeared), §4.3 L550; SR
§4.1 BIT007; REQ-159 (2), (3), (6), REQ-164 (2), REQ-165 (3); #15 (recorded
files first, then byte-wise path order), #102 (b) (`*.bit`, case-sensitive,
not hidden, regular files opened with O_NOFOLLOW; an unstorable name is
skipped with one log line and no row), #103; the crash-window ruling
(2026-10-27) and decisions 2026-10-28 "TASK-156 case (c) success" and
"TASK-156 staging extension and size".
"""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import folders, uploads
from bitscan_manager.services.importer.folders import (
    LEFTOVER,
    ReconcileResult,
    discover,
    reconcile,
    storable,
)
from bitscan_manager.services.importer.pipeline import Actor, ImportOutcome
from bitscan_manager.services.importer.pipeline import import_one as real_import_one
from bitscan_manager.services.importer.store import PolicyManagedOnServer, Target

from .catalog_rows import T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, counters, delta, doc, make_env, plug, sha
from .test_uploads_pg import MKFIFO, REAL_OPEN, in_thread, tree

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(os.name != "posix", reason="Linux file semantics (W only)"),
]

ADMIN = Actor("user:12", 12)
FIVE_MIB = 5 * 1024 * 1024
SKIP_LINE = "folder file skipped: its name cannot be stored"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("folders")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    # Each test owns its bits folder; earlier tests' live policies (whose files
    # are elsewhere) are soft-deleted first, so a reconcile here neither
    # deletes them nor sees their paths as recorded (#15).
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
    yield from make_env(server, tmp_path)


def rec(e: Env) -> ReconcileResult:
    with e.db.session() as s, catalog_lock(s):
        result: ReconcileResult = in_thread(lambda: reconcile(s, e.clock, e.bits))
        return result


def up_dir(e: Env) -> Path:
    return e.bits / "uploaded"


def put(e: Env, rel: str, data: bytes) -> Path:
    p = e.bits / rel
    p.write_bytes(data)
    return p


def rows_by_name(e: Env, i0: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in e.imports_after(i0):
        out.setdefault(r["file_name"], []).append(r["outcome"])
    return out


def upload(e: Env, data: bytes) -> ImportOutcome:
    out = uploads.upload(e.db, e.clock, e.bits, data, b"client.bit", ADMIN)
    assert out.outcome == "success", out.findings
    return out


def next_policy_id(e: Env) -> int:
    with owner(e.server) as c:
        row = c.execute(
            "SELECT last_value, is_called FROM policy_policy_id_seq"
        ).fetchone()
    assert row is not None
    return int(row[0]) + (1 if row[1] else 0)


# CHK-M7-208: REQ-164 (2), #102 (b) -------------------------------------------------


def test_only_storable_bit_regular_files_directly_in_a_folder_count(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    good = {
        "n.bit": doc(f"N {tag()}", [plug()]),
        "x" * 251 + ".bit": doc(f"Long {tag()}", [plug()]),  # 255 bytes
        "uploaded/u.bit": doc(f"U {tag()}", [plug()]),
    }
    for rel, data in good.items():
        put(env, rel, data)
    junk = doc(f"Junk {tag()}", [plug()])
    for folder in (env.bits, up_dir(env)):
        for name in ["n.txt", ".n.bit", "A.BIT", "n.bit.bak", ".tmp-1-x"]:
            if not (folder / name).exists():
                (folder / name).write_bytes(junk)
        (folder / "sub").mkdir()
        (folder / "sub" / "s.bit").write_bytes(junk)
        MKFIFO(folder / "f.bit")
        outside = env.bits.parent / f"outside-{folder.name}.bit"
        outside.write_bytes(junk)
        (folder / "l.bit").symlink_to(outside)
        raw = os.fsencode(folder)
        # A name over 255 bytes cannot exist on Linux (NAME_MAX): see the
        # storable rows below.
        for bad in [b"\xff.bit", b"a\x01.bit", b"a\nb.bit"]:
            fd = REAL_OPEN(raw + b"/" + bad, os.O_WRONLY | os.O_CREAT, 0o600)
            os.write(fd, junk)
            os.close(fd)
    assert sorted(discover(env.bits)) == sorted(good)
    caplog.clear()
    i0, before = env.last_import(), tree(env.bits.parent)
    result = rec(env)
    rows = rows_by_name(env, i0)
    assert rows == {rel: ["success"] for rel in good}  # no row for any other
    assert sorted(rel for rel, _ in result.outcomes) == sorted(good)
    # one fixed line per unstorable name (3 in each folder), naming nothing
    assert caplog.text.count(SKIP_LINE) == 6
    assert "\\xff" not in caplog.text and "x" * 40 not in caplog.text
    moved = dict(result.outcomes)["uploaded/u.bit"].policy_id  # case (c)
    expected = {k: v for k, v in before.items() if k != "bits/uploaded/u.bit"}
    expected[f"bits/uploaded/policy-{moved}.bit"] = (
        "file",
        sha(good["uploaded/u.bit"]),
    )
    assert tree(env.bits.parent) == expected  # every skipped entry untouched


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("a.bit", True),
        ("é" * 125 + ".bit", True),  # 254 bytes
        ("é" * 126 + ".bit", False),  # 256 bytes
        ("x" * 252 + ".bit", False),  # 256 bytes
        ("a\x7f.bit", False),
        ("a\x9f.bit", False),
        ("a\ud800.bit", False),  # an undecodable POSIX name
        ("a .bit", True),
    ],
)
def test_storable_name_rules(name: str, ok: bool) -> None:
    assert storable(name) is ok


# CHK-M7-209: #15 order, REQ-159 (2), (3), (6) -----------------------------------------


def test_two_new_files_with_one_name_the_first_in_byte_order_wins(env: Env) -> None:
    name = f"Twin {tag()}"
    put(env, "a.bit", doc(name, [plug()]))
    put(env, "B.bit", doc(name, [plug()]))  # b"B" < b"a"
    i0 = env.last_import()
    rec(env)
    assert rows_by_name(env, i0) == {"B.bit": ["success"], "a.bit": ["rejected"]}
    row = [r for r in env.imports_after(i0) if r["file_name"] == "a.bit"][0]
    assert [e["code"] for e in row["errors"]] == ["BIT007"]


def test_byte_order_not_locale_order(env: Env) -> None:
    name = f"Bytes {tag()}"
    put(env, "é.bit", doc(name, [plug()]))  # b"\xc3\xa9" > b"z"
    put(env, "z.bit", doc(name, [plug()]))
    i0 = env.last_import()
    rec(env)
    assert rows_by_name(env, i0) == {"z.bit": ["success"], "é.bit": ["rejected"]}


def test_a_recorded_file_goes_before_a_new_one(env: Env) -> None:
    name, p = f"Recorded {tag()}", plug()
    put(env, "z.bit", doc(name, [p]))
    rec(env)
    put(env, "z.bit", doc(name, [p], desc="v2"))  # changed, recorded
    put(env, "a.bit", doc(name, [plug()]))  # new, same name, earlier in bytes
    i0 = env.last_import()
    rec(env)
    assert rows_by_name(env, i0) == {"z.bit": ["success"], "a.bit": ["rejected"]}


def test_a_new_file_replacing_a_removed_one_moves_its_policy(env: Env) -> None:
    name, p = f"Move {tag()}", plug()
    put(env, "a.bit", doc(name, [p]))
    first = rec(env).outcomes[0][1]
    (env.bits / "a.bit").unlink()
    put(env, "c.bit", doc(name, [p]))
    m0, c0 = env.mark(), counters()
    result = rec(env)
    pid = first.policy_id or 0
    assert result.deleted == [] and result.outcomes[0][1].policy_id == pid
    pol = env.policy(pid)
    assert (pol["source_file"], pol["deleted_at"]) == ("c.bit", None)
    moves = [e for e in env.entries(m0) if e["action"] == "policy.move"]
    assert [m["detail"] for m in moves] == [{"from": "a.bit", "to": "c.bit"}]
    assert "policy_deleted" not in delta(c0)


def test_the_server_folder_wins_over_an_upload_then_uploads_get_409(env: Env) -> None:
    name, p = f"Wins {tag()}", plug()
    up = upload(env, doc(name, [p]))
    copy = up_dir(env) / f"policy-{up.policy_id}.bit"
    assert copy.is_file()
    put(env, "srv.bit", doc(name, [p], desc="server"))
    m0 = env.mark()
    rec(env)
    pol = env.policy(up.policy_id or 0)
    assert pol["source_file"] == "srv.bit" and pol["deleted_at"] is None
    assert not copy.exists()  # the uploaded copy is deleted
    moves = [e for e in env.entries(m0) if e["action"] == "policy.move"]
    assert [m["detail"]["to"] for m in moves] == ["srv.bit"]
    with pytest.raises(PolicyManagedOnServer):
        uploads.upload(
            env.db, env.clock, env.bits, doc(name, [p], desc="u"), b"x", ADMIN
        )


def test_a_symlink_at_the_old_path_does_not_keep_bit007_alive(env: Env) -> None:
    name, p = f"Link {tag()}", plug()
    put(env, "a.bit", doc(name, [p]))
    first = rec(env).outcomes[0][1]
    # The symlink points at a valid *.bit regular file holding the same
    # policy, so only the lstat rule (a symlink never counts) lets it go.
    elsewhere = env.bits.parent / "elsewhere.bit"
    elsewhere.write_bytes((env.bits / "a.bit").read_bytes())
    (env.bits / "a.bit").unlink()
    (env.bits / "a.bit").symlink_to(elsewhere)
    put(env, "b.bit", doc(name, [p]))
    i0 = env.last_import()
    rec(env)
    assert rows_by_name(env, i0) == {"b.bit": ["success"]}  # no BIT007
    assert env.policy(first.policy_id or 0)["source_file"] == "b.bit"
    assert elsewhere.is_file() and (env.bits / "a.bit").is_symlink()


# CHK-M7-210, REQ-165 (3): unchanged, added, removed ----------------------------------


def test_an_unchanged_folder_writes_only_skipped_rows(env: Env) -> None:
    put(env, "s1.bit", doc(f"S1 {tag()}", [plug()]))
    put(env, "s2.bit", doc(f"S2 {tag()}", [plug()]))
    upload(env, doc(f"S3 {tag()}", [plug()]))
    rec(env)
    i0, m0, cat0, c0 = env.last_import(), env.mark(), env.catalog(), counters()
    result = rec(env)
    rows = env.imports_after(i0)
    assert sorted(r["file_name"] for r in rows) == sorted(
        ["s1.bit", "s2.bit", *[n for n in discover(env.bits) if n.startswith("upl")]]
    )
    assert {r["outcome"] for r in rows} == {"skipped"}
    assert {r["policy_version"] for r in rows} == {None}  # TASK-154 r1
    assert env.entries(m0) == [] and env.catalog() == cat0 and delta(c0) == {}
    assert result.deleted == [] and result.leftovers == []


def test_added_files_import_and_removed_files_delete_their_policy(env: Env) -> None:
    keep = put(env, "keep.bit", doc(f"Keep {tag()}", [plug()]))
    gone = put(env, "gone.bit", doc(f"Gone {tag()}", [plug()]))
    up = upload(env, doc(f"UpGone {tag()}", [plug()]))
    first = dict(rec(env).outcomes)
    gone.unlink()
    (up_dir(env) / f"policy-{up.policy_id}.bit").unlink()
    put(env, "new.bit", doc(f"New {tag()}", [plug()]))
    m0, c0 = env.mark(), counters()
    result = rec(env)
    gone_id = first["gone.bit"].policy_id
    assert sorted(result.deleted) == sorted([gone_id or 0, up.policy_id or 0])
    for pid in (gone_id, up.policy_id):
        pol = env.policy(pid or 0)
        assert pol["deleted_at"] is not None
        assert pol["source_file"] == f"deleted/{pid}"
    dels = [e for e in env.entries(m0) if e["action"] == "policy.delete"]
    assert sorted(d["target"] for d in dels) == sorted(
        [f"policy:{gone_id}", f"policy:{up.policy_id}"]
    )
    assert {d["actor"] for d in dels} == {"system"}
    assert {d["detail"]["reason"] for d in dels} == {"file removed"}
    assert {d["detail"]["alert_kind"] for d in dels} == {"policy_deleted"}
    assert delta(c0)["policy_deleted"] == 2.0
    assert [rel for rel, o in result.outcomes if o.outcome == "success"] == ["new.bit"]
    assert keep.exists()


def test_a_file_replaced_by_a_symlink_counts_as_removed(env: Env) -> None:
    path = put(env, "sym.bit", doc(f"Sym {tag()}", [plug()]))
    pid = rec(env).outcomes[0][1].policy_id
    target = env.bits.parent / "real.bit"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    result = rec(env)
    assert result.deleted == [pid]
    assert target.read_bytes()  # never followed or removed


def test_an_oversize_folder_file_is_rejected_with_its_full_hash(env: Env) -> None:
    data = doc(f"Big {tag()}", [plug()])
    data += b" " * (FIVE_MIB + 1 - len(data))
    put(env, "big.bit", data)
    i0 = env.last_import()
    rec(env)
    (row,) = env.imports_after(i0)
    assert (row["outcome"], row["file_sha256"]) == ("rejected", sha(data))
    assert [e["code"] for e in row["errors"]] == ["BIT001"]


# The row's classification: extra tests (i) to (iv) ------------------------------------


def test_i_live_upload_unchanged_skips_changed_imports_keeping_its_name(
    env: Env,
) -> None:
    name, p = f"Live {tag()}", plug()
    up = upload(env, doc(name, [p]))
    own = up_dir(env) / f"policy-{up.policy_id}.bit"
    i0, m0 = env.last_import(), env.mark()
    rec(env)
    assert rows_by_name(env, i0) == {f"uploaded/{own.name}": ["skipped"]}
    assert env.entries(m0) == []  # no alert
    v2 = doc(name, [p], desc="edited in place")
    own.write_bytes(v2)
    i1 = env.last_import()
    result = rec(env)  # the own-name path: nothing staged, nothing removed
    assert rows_by_name(env, i1) == {f"uploaded/{own.name}": ["success"]}
    assert own.read_bytes() == v2  # still present, no error
    assert [n.name for n in up_dir(env).iterdir() if n.name.startswith(".tmp-")] == []
    assert env.policy(up.policy_id or 0)["source_sha256"] == sha(v2)
    assert result.leftovers == [] and result.deleted == []


def test_ii_the_leftover_of_an_interrupted_delete_is_removed(env: Env) -> None:
    up = upload(env, doc(f"Left {tag()}", [plug()]))
    own = up_dir(env) / f"policy-{up.policy_id}.bit"
    with app(env.server) as c, c.transaction():
        assert adm.soft_delete_effects(c, up.policy_id or 0, T2) is not None
    assert own.exists()  # the crash came before the file removal
    i0, cat0 = env.last_import(), env.catalog()
    result = rec(env)
    assert not own.exists()
    assert env.imports_after(i0) == []  # no bit_import row
    assert env.catalog() == cat0
    assert env.policy(up.policy_id or 0)["deleted_at"] is not None
    assert [(d.subject, d.check) for d in result.leftovers] == [
        (f"uploaded/{own.name}", LEFTOVER)
    ]


def test_iii_the_leftover_rule_never_fires_for_a_live_policy(env: Env) -> None:
    up = upload(env, doc(f"Live2 {tag()}", [plug()]))
    own = up_dir(env) / f"policy-{up.policy_id}.bit"
    own.write_bytes(doc(f"Live2 other content {tag()}", [plug()]))  # other hash
    srv = env.imp(doc(f"SrvN {tag()}", [plug()]), "srvn.bit")
    copy = up_dir(env) / f"policy-{srv.policy_id}.bit"  # a live server policy's id
    copy.write_bytes(doc(env.policy(srv.policy_id or 0)["policy_name"], [plug()]))
    result = rec(env)
    assert result.leftovers == []
    assert env.policy(up.policy_id or 0)["deleted_at"] is None
    assert own.exists()  # its own source_file: never unlinked
    assert copy.exists()  # refused (server-folder name), kept for #103
    assert env.policy(srv.policy_id or 0)["source_file"] == "srvn.bit"


def test_iv_no_uploaded_file_is_ever_a_server_target(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets: list[tuple[str, Target]] = []

    def spy(*a: Any, **k: Any) -> ImportOutcome:
        f = a[3]
        targets.append((f.file_name, f.target))
        return real_import_one(*a, **k)

    monkeypatch.setattr(folders, "import_one", spy)
    upload(env, doc(f"T1 {tag()}", [plug()]))
    put(env, "uploaded/foreign.bit", doc(f"T2 {tag()}", [plug()]))
    put(env, "srv.bit", doc(f"T3 {tag()}", [plug()]))
    rec(env)
    monkeypatch.undo()
    assert {rel.split("/")[0] for rel, _ in targets} >= {"uploaded", "srv.bit"}
    for rel, t in targets:
        if rel.startswith("uploaded/"):
            assert (t.kind, t.source_file) == ("upload", None), rel
        else:
            assert (t.kind, t.source_file) == ("server", rel)
    with pytest.raises(ValueError):
        Target("server", "uploaded/policy-1.bit", "a" * 64)


# Case (c) and the staging extension (decisions 2026-10-28) ----------------------------


def test_c_success_is_stored_as_policy_id_and_the_foreign_file_removed(
    env: Env,
) -> None:
    data = doc(f"Foreign {tag()}", [plug()])
    foreign = put(env, "uploaded/foreign.bit", data)
    i0 = env.last_import()
    result = rec(env)
    ((rel, out),) = [(r, o) for r, o in result.outcomes if r == "uploaded/foreign.bit"]
    assert out.outcome == "success"
    stored = up_dir(env) / f"policy-{out.policy_id}.bit"
    assert stored.read_bytes() == data
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert not foreign.exists()
    assert [p.name for p in up_dir(env).iterdir()] == [stored.name]
    pol = env.policy(out.policy_id or 0)
    assert pol["source_file"] == f"uploaded/{stored.name}"
    assert rows_by_name(env, i0) == {"uploaded/foreign.bit": ["success"]}
    i1 = env.last_import()
    rec(env)  # next start-up: the stored copy is unchanged
    assert rows_by_name(env, i1) == {f"uploaded/{stored.name}": ["skipped"]}


def test_c_foreign_symlink_target_is_never_removed(env: Env) -> None:
    data = doc(f"ForeignLink {tag()}", [plug()])
    real = env.bits.parent / "real-foreign.bit"
    real.write_bytes(data)
    (up_dir(env) / "fl.bit").symlink_to(real)
    i0 = env.last_import()
    rec(env)
    assert env.imports_after(i0) == []  # a symlink is never imported
    assert real.read_bytes() == data and (up_dir(env) / "fl.bit").is_symlink()


def test_c_rejected_or_refused_files_stay(env: Env) -> None:
    bad = put(env, "uploaded/bad.bit", doc(f"Bad {tag()}", [plug("rm x")]))
    srv = env.imp(doc(f"Managed {tag()}", [plug()]), "managed.bit")
    name = env.policy(srv.policy_id or 0)["policy_name"]
    refused = put(env, "uploaded/copy.bit", doc(name, [plug()]))
    i0, m0 = env.last_import(), env.mark()
    rec(env)
    assert rows_by_name(env, i0) == {
        "uploaded/bad.bit": ["rejected"],
        "managed.bit": ["skipped"],  # the server file itself, unchanged
    }  # no row for the refused copy (#99 (e))
    assert bad.exists() and refused.exists()
    assert "policy.import_refused" in [e["action"] for e in env.entries(m0)]
    assert [p.name for p in up_dir(env).iterdir() if p.name.startswith(".tmp-")] == []


def test_c_own_name_inserted_as_that_id_keeps_its_file(env: Env) -> None:
    n = next_policy_id(env)
    data = doc(f"OwnName {tag()}", [plug()])
    own = put(env, f"uploaded/policy-{n}.bit", data)
    result = rec(env)
    ((_, out),) = [
        (r, o) for r, o in result.outcomes if r == own.relative_to(env.bits).as_posix()
    ]
    assert (out.outcome, out.policy_id) == ("success", n)
    assert own.read_bytes() == data  # not staged, not removed
    assert [p.name for p in up_dir(env).iterdir()] == [own.name]


def test_a_live_file_naming_another_policy_is_staged_for_that_one(env: Env) -> None:
    up = upload(env, doc(f"Holder {tag()}", [plug()]))
    own = up_dir(env) / f"policy-{up.policy_id}.bit"
    other = doc(f"Other {tag()}", [plug()])
    own.write_bytes(other)
    result = rec(env)
    ((_, out),) = [(r, o) for r, o in result.outcomes if r == f"uploaded/{own.name}"]
    assert out.outcome == "success" and out.policy_id != up.policy_id
    staged = up_dir(env) / f"policy-{out.policy_id}.bit"
    assert staged.read_bytes() == other
    assert own.read_bytes() == other  # its own source_file: never unlinked
    assert env.policy(up.policy_id or 0)["deleted_at"] is None


# O_NOFOLLOW on the read, and logs -----------------------------------------------------


def test_a_file_swapped_for_a_symlink_before_the_read_is_skipped(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = put(env, "race.bit", doc(f"Race {tag()}", [plug()]))
    outside = env.bits.parent / "race-outside.bit"
    outside.write_bytes(doc(f"Outside {tag()}", [plug()]))
    seen: list[int] = []

    def racing_open(p: Any, flags: int, *a: Any, **k: Any) -> int:
        if str(p) == str(path) and not flags & os.O_WRONLY:
            seen.append(flags)
            if not path.is_symlink():
                path.unlink()
                path.symlink_to(outside)
        return REAL_OPEN(p, flags, *a, **k)

    monkeypatch.setattr(os, "open", racing_open)
    i0 = env.last_import()
    result = rec(env)
    monkeypatch.undo()
    assert seen and all(f & getattr(os, "O_NOFOLLOW") for f in seen)  # noqa: B009
    assert env.imports_after(i0) == []  # not imported through the symlink
    assert result.not_imported == ["race.bit"]


def test_no_file_name_or_content_in_the_logs(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = f"marker{tag()}"
    put(env, f"{marker}.bit", doc(f"{marker} policy", [plug(f"cat /etc/{marker}")]))
    put(env, f"uploaded/{marker}-c.bit", doc(f"{marker} c", [plug()]))
    put(env, f"{marker}-bad.bit", doc(f"{marker} bad", [plug("rm x")]))
    up = upload(env, doc(f"{marker} left", [plug()]))
    with app(env.server) as c, c.transaction():
        adm.soft_delete_effects(c, up.policy_id or 0, T2)
    rec(env)
    assert marker not in caplog.text
