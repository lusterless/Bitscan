"""TP-M7-16 (TASK-156): folder discovery and the automatic reconcile on
PostgreSQL with temporary bits folders.

CHK-M7-208, -209, -210 (tests/m7/test-plan.md) and mutation row CHK-M7-363,
plus the TASK-156 row's extra tests (i) to (iv). Expected values come from the
spec and the approved rulings, not from the code:

- TS §4.1 L515 (two folders), L524 (the server folder wins, the uploaded copy
  is deleted, the move is audit-logged), L526 (the catalog lock), L528 (the
  watcher sees ``*.bit`` files only, no subfolders; at start-up new or changed
  files are imported and policies whose files disappeared are deleted), L532
  (automatic imports skip a file whose hash equals the last successful
  import); TS §4.2 (automatic mode); TS §4.3 L550 (soft delete); TS §4.6.
- REQ-159 (1), (2), (3), (6); REQ-164 (2); REQ-165 (3).
- #15 (BIT007 order: a live policy's ``source_file`` first, then UTF-8 path
  bytes); #102 (b) (``.bit`` case-sensitive, not hidden, regular files opened
  with O_NOFOLLOW; not UTF-8, a control character or over 255 bytes: one log
  line, skipped, no row); #103.
- decisions 2026-10-27 "Crash window" (a deleted policy's
  ``uploaded/policy-<id>.bit`` is a leftover: removed, nothing imported, no
  row, the policy stays deleted, one #103 difference) and "Stray ``uploaded/``
  files are skipped and reported" (never imported, no row, no alert, no
  catalog change, reported for #103; a server-folder policy's old uploaded
  copy is a stray), plus the accepted order (server files before
  ``uploaded/``, all imports before the removed-file deletes).

Owner: tester-m7-156. The reconcile works on the whole catalog, so every test
starts from a catalog with no live policy: the autouse ``clean`` fixture
soft-deletes, as owner, whatever earlier tests left live. The code under test
runs as ``bitscan_app``; results are read as owner.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import delete as dl
from bitscan_manager.services.importer import folders, pipeline, store_decide, uploads
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.pipeline import Actor, FileInput, ImportOutcome
from bitscan_manager.services.importer.store import PolicyManagedOnServer, Target

from .catalog_rows import T1, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .pipeline_rows import (
    FixedClock,
    P,
    audits_since,
    bit,
    catalog_now,
    codes,
    counter_delta,
    imports_since,
    members,
    policy_by_name,
    policy_row,
    sha,
    snap,
)

pytestmark = pytest.mark.pg

ADMIN = Actor("user:7", 7)
LOGGER = "bitscan_manager.services.importer.folders"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("folders")) as s:
        yield s


@pytest.fixture(scope="module")
def db(server: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture(autouse=True)
def clean(request: pytest.FixtureRequest) -> None:
    """No live policy at the start of a PostgreSQL test (owner UPDATE)."""
    if "server" not in request.fixturenames:
        return
    srv: PgServer = request.getfixturevalue("server")
    with owner(srv) as c:
        c.execute(
            "UPDATE policy SET deleted_at = now(),"
            " source_file = 'deleted/' || policy_id WHERE deleted_at IS NULL"
        )


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    folder = tmp_path / "bits"
    (folder / "uploaded").mkdir(parents=True)
    return folder


def rec(db: AppDatabase, bits: Path) -> folders.ReconcileResult:
    """The caller's side of the contract: a pinned session holding the lock."""
    with db.session() as s, catalog_lock(s):
        return folders.reconcile(s, FixedClock(), bits)


def put(bits: Path, rel: str, data: bytes) -> Path:
    path = bits / rel
    path.write_bytes(data)
    return path


def upload(db: AppDatabase, bits: Path, data: bytes) -> ImportOutcome:
    with db.session() as s, catalog_lock(s):
        out = uploads.import_upload(
            s, FixedClock(), bits, data, "client.bit", actor=ADMIN
        )
    assert out.outcome == "success", out
    assert out.policy_id is not None
    assert (bits / f"uploaded/policy-{out.policy_id}.bit").read_bytes() == data
    return out


def tree(bits: Path) -> dict[str, bytes | str]:
    """Every entry under the bits folder: bytes for regular files, a marker
    otherwise (symlinks are never followed)."""
    out: dict[str, bytes | str] = {}
    for root, dirs, files in os.walk(bits, followlinks=False):
        for name in dirs + files:
            p = Path(root) / name
            rel = str(p.relative_to(bits))
            mode = os.lstat(p).st_mode
            if stat.S_ISREG(mode):
                out[rel] = p.read_bytes()
            elif stat.S_ISLNK(mode):
                out[rel] = "link:" + os.readlink(p)
            else:
                out[rel] = "dir" if stat.S_ISDIR(mode) else "special"
    return out


def rows_by_file(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(r["file_name"], r["outcome"]) for r in rows]


def actions(entries: list[dict[str, Any]]) -> list[str]:
    return [e["action"] for e in entries]


def live_count(server: PgServer) -> int:
    with owner(server) as c:
        row = c.execute("SELECT count(*) FROM policy WHERE deleted_at IS NULL")
        got = row.fetchone()
    assert got is not None
    return int(got[0])


# ----------------------------------------------------------------------------
# CHK-M7-208: REQ-164 (2) and #102 (b), discovery (no database)
# ----------------------------------------------------------------------------


def _hostile_folder(bits: Path, outside: Path) -> None:
    good, _ = bit()
    put(bits, "a.bit", good)
    put(bits, "n.txt", good)
    put(bits, ".n.bit", good)
    put(bits, "A.BIT", good)
    put(bits, "a.Bit", good)
    put(bits, "a.bit.txt", good)
    put(bits, "a.bit~", good)
    (bits / "sub").mkdir()
    put(bits, "sub/n.bit", good)
    (bits / "d.bit").mkdir()
    put(bits, "d.bit/inner.bit", good)
    os.mkfifo(bits / "f.bit")
    os.mknod(bits / "c.bit", stat.S_IFCHR | 0o600, os.makedev(1, 3))
    os.symlink(bits / "a.bit", bits / "l.bit")
    os.symlink("/etc/passwd", bits / "passwd.bit")
    os.symlink("/etc", bits / "etc.bit")
    os.symlink("/nonexistent/x.bit", bits / "dangling.bit")
    put(outside, "o.bit", good)
    os.symlink(outside / "o.bit", bits / "o.bit")
    put(bits, "uploaded/policy-1.bit", good)
    put(bits, "uploaded/.tmp-1-" + "0" * 64, good)
    put(bits, "uploaded/.policy-2.bit", good)
    (bits / "uploaded" / "sub").mkdir()
    put(bits, "uploaded/sub/policy-3.bit", good)
    os.mkfifo(bits / "uploaded" / "policy-4.bit")
    os.symlink(bits / "a.bit", bits / "uploaded" / "policy-5.bit")


def test_discover_keeps_only_regular_bit_files_directly_in_each_folder(
    tmp_path: Path, bits: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _hostile_folder(bits, outside)
    assert folders.discover(bits) == ["a.bit", "uploaded/policy-1.bit"]


def test_present_matches_discover(tmp_path: Path, bits: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _hostile_folder(bits, outside)
    yes = ["a.bit", "uploaded/policy-1.bit"]
    no = [
        "n.txt",
        ".n.bit",
        "A.BIT",
        "sub/n.bit",
        "d.bit",
        "d.bit/inner.bit",
        "f.bit",
        "c.bit",
        "l.bit",
        "passwd.bit",
        "etc.bit",
        "dangling.bit",
        "o.bit",
        "missing.bit",
        "uploaded/.policy-2.bit",
        "uploaded/sub/policy-3.bit",
        "uploaded/policy-4.bit",
        "uploaded/policy-5.bit",
        "../bits/a.bit",
        "uploaded/../a.bit",
        "deleted/1",
    ]
    assert [r for r in yes if folders.present(bits, r)] == yes
    assert [r for r in no if folders.present(bits, r)] == []


def test_a_symlinked_uploaded_folder_is_never_followed(
    tmp_path: Path, bits: Path
) -> None:
    good, _ = bit()
    target = tmp_path / "elsewhere"
    target.mkdir()
    put(target, "policy-1.bit", good)
    (bits / "uploaded").rmdir()
    os.symlink(target, bits / "uploaded")
    put(bits, "s.bit", good)
    assert folders.discover(bits) == ["s.bit"]
    assert not folders.present(bits, "uploaded/policy-1.bit")


def test_a_missing_uploaded_folder_gives_server_files_only(bits: Path) -> None:
    (bits / "uploaded").rmdir()
    put(bits, "s.bit", bit()[0])
    assert folders.discover(bits) == ["s.bit"]


def test_read_input_never_follows_a_symlink_or_blocks_on_a_fifo(
    tmp_path: Path, bits: Path
) -> None:
    good, _ = bit()
    put(tmp_path, "real.bit", good)
    os.symlink(tmp_path / "real.bit", bits / "l.bit")
    os.symlink("/etc/passwd", bits / "passwd.bit")
    os.mkfifo(bits / "f.bit")
    os.mknod(bits / "c.bit", stat.S_IFCHR | 0o600, os.makedev(1, 3))
    (bits / "d.bit").mkdir()
    for rel in ["l.bit", "passwd.bit", "f.bit", "c.bit", "d.bit", "gone.bit"]:
        assert folders.read_input(bits, rel) is None, rel


def test_read_input_targets(bits: Path) -> None:
    data, _ = bit()
    put(bits, "s.bit", data)
    put(bits, "uploaded/policy-12.bit", data)
    d = sha(data)
    assert folders.read_input(bits, "s.bit") == FileInput(
        data, d, "s.bit", Target("server", "s.bit", d)
    )
    assert folders.read_input(bits, "uploaded/policy-12.bit") == FileInput(
        data, d, "uploaded/policy-12.bit", Target("upload", None, d)
    )


def test_read_input_oversize_hashes_the_whole_file(bits: Path) -> None:
    exact = b"<" + b"x" * (MAX_BIT_BYTES - 1)
    big = exact + b"y" * (3 << 20)  # crosses several read chunks
    put(bits, "exact.bit", exact)
    put(bits, "big.bit", big)
    got = folders.read_input(bits, "exact.bit")
    assert got is not None and got.data == exact and got.sha256 == sha(exact)
    over = folders.read_input(bits, "big.bit")
    assert over is not None and over.data is None
    assert over.sha256 == sha(big) == over.target.file_sha256
    put(bits, "one.bit", exact + b"z")
    one = folders.read_input(bits, "one.bit")
    assert one is not None and one.data is None and one.sha256 == sha(exact + b"z")


@pytest.mark.parametrize(
    ("name", "wanted"),
    [
        ("a.bit", True),
        ("a" * 251 + ".bit", True),  # 255 bytes
        ("a" * 252 + ".bit", False),  # 256 bytes
        ("é" * 125 + "a.bit", True),  # 255 bytes, 131 characters
        ("é" * 126 + ".bit", False),  # 256 bytes, 130 characters
        ("a\x01.bit", False),
        ("a\t.bit", False),
        ("a\n.bit", False),
        ("a\x7f.bit", False),
        ("a\x85.bit", False),  # C1 control
        ("bad\udcff.bit", False),  # a non-UTF-8 byte as a surrogate escape
        ("a‮.bit", True),  # Cf, not a control character (#102 (b))
        ("日本.bit", True),
        (".a.bit", False),
        ("a.BIT", False),
        ("a.bitx", False),
        (".bit", False),
    ],
)
def test_wanted_name_rules(name: str, wanted: bool) -> None:
    assert folders._wanted(name) is wanted


@pytest.mark.parametrize(
    ("rel", "policy_id"),
    [
        ("uploaded/policy-1.bit", 1),
        ("uploaded/policy-42.bit", 42),
        (f"uploaded/policy-{2**63 - 1}.bit", 2**63 - 1),
        (f"uploaded/policy-{2**63}.bit", None),
        ("uploaded/policy-99999999999999999999.bit", None),
        ("uploaded/policy-0.bit", 0),
        ("uploaded/policy-01.bit", None),
        ("uploaded/policy-00.bit", None),
        ("uploaded/policy-+1.bit", None),
        ("uploaded/policy--1.bit", None),
        ("uploaded/policy- 1.bit", None),
        ("uploaded/policy-1 .bit", None),
        ("uploaded/policy-１２.bit", None),  # fullwidth digits
        ("uploaded/policy-١.bit", None),  # Arabic-Indic digit
        ("uploaded/policy-.bit", None),
        ("uploaded/policy-1.bit.bit", None),
        ("uploaded/Policy-1.bit", None),
        ("uploaded/x.bit", None),
        ("policy-1.bit", None),
        ("uploaded/sub/policy-1.bit", None),
    ],
)
def test_upload_policy_id(rel: str, policy_id: int | None) -> None:
    assert folders.upload_policy_id(rel) == policy_id


# ----------------------------------------------------------------------------
# CHK-M7-208 on PostgreSQL: nothing hostile is imported; unstorable names
# ----------------------------------------------------------------------------


def test_hostile_entries_are_never_imported(
    server: PgServer, db: AppDatabase, tmp_path: Path, bits: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _hostile_folder(bits, outside)
    # Every hostile entry holds a distinct new policy: none may appear.
    names = {}
    for rel in ["n.txt", ".n.bit", "A.BIT", "sub/n.bit", "d.bit/inner.bit"]:
        names[rel] = f"Hostile {tag()}"
        put(bits, rel, bit(names[rel])[0])
    names["outside"] = f"Hostile {tag()}"
    outside_data = bit(names["outside"])[0]
    put(outside, "o.bit", outside_data)
    names["passwd-target"] = "root:x:0:0"
    names["uploaded/.policy-2.bit"] = f"Hostile {tag()}"
    put(bits, "uploaded/.policy-2.bit", bit(names["uploaded/.policy-2.bit"])[0])
    names["uploaded/sub"] = f"Hostile {tag()}"
    put(bits, "uploaded/sub/policy-3.bit", bit(names["uploaded/sub"])[0])
    a_name = f"Good {tag()}"
    put(bits, "a.bit", bit(a_name)[0])  # l.bit links to it
    put(bits, "uploaded/policy-1.bit", bit(f"Stray {tag()}")[0])
    before_tree = tree(bits)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("a.bit", "success")]
    assert [o.outcome for o in res.outcomes] == ["success"]
    assert res.strays == ("uploaded/policy-1.bit",)  # no policy 1 is live
    assert res.deleted == () and res.leftovers == () and res.renamed == ()
    a = policy_by_name(server, a_name)
    assert a is not None and a["source_file"] == "a.bit"
    for name in names.values():
        assert policy_by_name(server, name) is None, name
    assert live_count(server) == 1
    assert tree(bits) == before_tree  # nothing written, removed or followed
    assert (outside / "o.bit").read_bytes() == outside_data


def test_unstorable_names_are_logged_once_and_skipped(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad = [
        os.fsencode(bits) + b"/bad\xff.bit",
        os.fsencode(bits) + b"/a\x01.bit",
        os.fsencode(bits) + b"/del\x7f.bit",
        os.fsencode(bits) + b"/uploaded/policy-1\xfe.bit",
    ]
    hidden: list[str] = []
    for path in bad:
        hidden.append(f"Unstorable {tag()}")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(bit(hidden[-1])[0])
    long_ok = "a" * 251 + ".bit"  # 255 bytes: storable
    long_name = f"Long {tag()}"
    put(bits, long_ok, bit(long_name)[0])
    s = snap(server)
    caplog.set_level(logging.DEBUG)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [(long_ok, "success")]
    assert [o.outcome for o in res.outcomes] == ["success"]
    assert res.strays == () and res.renamed == ()
    for name in hidden:
        assert policy_by_name(server, name) is None
    skipped = [
        r
        for r in caplog.records
        if r.name == LOGGER and "name cannot be stored" in r.getMessage()
    ]
    assert len(skipped) == len(bad)  # one line per file, once per reconcile
    for r in caplog.records:
        text = r.getMessage() + repr(r.args)
        for frag in ("bad", "del", "a\x01", "\udcff", "\udcfe", "policy-1"):
            assert frag not in text, (frag, text)
    # Still skipped (and still logged once) on the next reconcile.
    caplog.clear()
    s2 = snap(server)
    rec(db, bits)
    assert rows_by_file(imports_since(server, s2)) == [(long_ok, "skipped")]
    again = [r for r in caplog.records if "name cannot be stored" in r.getMessage()]
    assert len(again) == len(bad)


def test_oversize_server_file_is_one_rejected_bit001_row(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    big = b"<" + b"x" * MAX_BIT_BYTES  # one byte over
    put(bits, "big.bit", big)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert len(rows) == 1
    row = rows[0]
    assert (row["file_name"], row["outcome"], row["mode"]) == (
        "big.bit",
        "rejected",
        "auto",
    )
    assert row["file_sha256"] == sha(big)
    assert codes(row["errors"]) == ["BIT001"]
    assert row["imported_by"] is None
    assert [o.outcome for o in res.outcomes] == ["rejected"]
    assert catalog_now(server) == s.catalog


# ----------------------------------------------------------------------------
# CHK-M7-210: an unchanged folder writes only `skipped` rows; idempotence
# ----------------------------------------------------------------------------


def test_new_server_files_are_imported_in_auto_mode_by_the_system(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    na, nb = f"New {tag()}", f"New {tag()}"
    da, _ = bit(na)
    db_, _ = bit(nb, [P(), P(execute="cat /etc/os-release")])
    put(bits, "a.bit", da)
    put(bits, "b.bit", db_)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert [(r["file_name"], r["outcome"], r["mode"]) for r in rows] == [
        ("a.bit", "success", "auto"),
        ("b.bit", "success", "auto"),
    ]
    assert [r["imported_by"] for r in rows] == [None, None]
    assert [r["file_sha256"] for r in rows] == [sha(da), sha(db_)]
    assert [(r["plugins_added"], r["policy_version"]) for r in rows] == [(1, 1), (2, 1)]
    for name, rel, data in [(na, "a.bit", da), (nb, "b.bit", db_)]:
        p = policy_by_name(server, name)
        assert p is not None
        assert (p["source_file"], p["source_sha256"], p["version"]) == (
            rel,
            sha(data),
            1,
        )
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.import", "policy.import"]
    assert {e["actor"] for e in entries} == {"system"}
    assert counter_delta(s) == {"alert:policy_imported": 2.0}
    assert (res.deleted, res.leftovers, res.strays, res.renamed) == ((),) * 4


def _mixed_folder(server: PgServer, db: AppDatabase, bits: Path) -> dict[str, Any]:
    """Three server files and one live upload, all imported."""
    names = [f"Mixed {tag()}" for _ in range(3)]
    for i, n in enumerate(names):
        put(bits, f"s{i}.bit", bit(n, [P(), P()])[0])
    up = upload(db, bits, bit(f"Mixed up {tag()}")[0])
    first = rec(db, bits)
    assert sorted(o.outcome for o in first.outcomes) == [
        "skipped",
        "success",
        "success",
        "success",
    ]
    return {"names": names, "upload": up}


def test_an_unchanged_folder_writes_only_skipped_rows(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    mixed = _mixed_folder(server, db, bits)
    before_tree = tree(bits)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    up_rel = f"uploaded/policy-{mixed['upload'].policy_id}.bit"
    assert rows_by_file(rows) == [(f"s{i}.bit", "skipped") for i in range(3)] + [
        (up_rel, "skipped")
    ]
    assert {r["outcome"] for r in rows} == {"skipped"}
    assert len(rows) == 4
    assert {r["mode"] for r in rows} == {"auto"}
    assert all(
        (r["plugins_added"], r["plugins_updated"], r["plugins_retired"]) == (0, 0, 0)
        for r in rows
    )
    assert [o.outcome for o in res.outcomes] == ["skipped"] * 4
    assert audits_since(server, s) == []
    assert counter_delta(s) == {}
    assert catalog_now(server) == s.catalog
    assert tree(bits) == before_tree
    assert (res.deleted, res.leftovers, res.strays, res.renamed) == ((),) * 4


def test_three_reconciles_and_a_restart_cause_no_churn(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """A mixed folder: server files, a live upload, a BIT007 loser, strays and
    a leftover. After the first reconcile every further run is the same."""
    mixed = _mixed_folder(server, db, bits)
    loser = mixed["names"][0]
    put(bits, "z-dup.bit", bit(loser)[0])  # BIT007 against s0.bit
    put(bits, "uploaded/stray.bit", bit(f"Stray {tag()}")[0])
    gone = upload(db, bits, bit(f"Gone {tag()}")[0])
    gone_rel = f"uploaded/policy-{gone.policy_id}.bit"
    gone_bytes = (bits / gone_rel).read_bytes()
    dl.delete_policy(
        db, int(gone.policy_id or 0), actor="user:7", clock=FixedClock(), bits_dir=bits
    )
    put(bits, gone_rel, gone_bytes)  # the crash window: file left behind
    first = rec(db, bits)
    assert first.leftovers == (Difference(gone_rel, folders.LEFTOVER_CHECK),)
    assert first.strays == ("uploaded/stray.bit",)
    states: list[Any] = []
    for run in range(4):
        if run == 3:  # a simulated restart: a new pool and new sessions
            d2 = AppDatabase(
                SecretStr(server.dsn("bitscan_app")), max_size=2, connect_timeout_s=3
            )
            d2.open()
            try:
                s = snap(server)
                res = rec(d2, bits)
            finally:
                d2.close()
        else:
            s = snap(server)
            res = rec(db, bits)
        rows = imports_since(server, s)
        outcome = sorted(rows_by_file(rows))
        states.append(
            (
                outcome,
                res.strays,
                res.leftovers,
                res.deleted,
                res.renamed,
                actions(audits_since(server, s)),
                catalog_now(server),
                tree(bits),
            )
        )
        assert catalog_now(server) == s.catalog
        assert ("z-dup.bit", "rejected") in outcome  # retried (TS §4.1 L532)
        assert {o for _, o in outcome} == {"skipped", "rejected"}
        assert actions(audits_since(server, s)) == ["policy.import_rejected"]
    assert all(st == states[0] for st in states), states
    assert states[0][1] == ("uploaded/stray.bit",)
    assert states[0][2] == ()
    assert policy_row(server, int(gone.policy_id or 0))["deleted_at"] is not None


# ----------------------------------------------------------------------------
# REQ-165 (3): new and changed files imported, removed files deleted
# ----------------------------------------------------------------------------


def test_a_removed_server_file_soft_deletes_its_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Removed {tag()}"
    put(bits, "a.bit", bit(name, [P(), P()])[0])
    keep = f"Kept {tag()}"
    put(bits, "b.bit", bit(keep)[0])
    rec(db, bits)
    before = policy_by_name(server, name)
    assert before is not None
    pid = int(before["policy_id"])
    plugs = members(server, pid)
    assert [st for _, _, st in plugs] == ["active", "active"]
    (bits / "a.bit").unlink()
    added = f"Added {tag()}"
    put(bits, "c.bit", bit(added)[0])
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("b.bit", "skipped"), ("c.bit", "success")]
    after = policy_row(server, pid)
    assert after["deleted_at"] == T1
    assert after["source_file"] == f"deleted/{pid}"
    assert after["policy_name"] == name
    assert [(u, st) for u, _, st in members(server, pid)] == [
        (u, "retired") for u, _, _ in plugs
    ]
    assert [d.policy_id for d in res.deleted] == [pid]
    assert res.deleted[0].source_file == "a.bit"
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.import", "policy.delete"]
    delete = entries[1]
    assert (delete["actor"], delete["target"]) == ("system", f"policy:{pid}")
    assert delete["detail"]["reason"] == "file removed"
    assert delete["detail"]["source_file"] == "a.bit"
    assert counter_delta(s) == {
        "alert:policy_imported": 1.0,
        "alert:policy_deleted": 1.0,
    }
    k = policy_by_name(server, keep)
    assert k is not None and k["deleted_at"] is None
    # A second reconcile deletes nothing more and writes only skips.
    s2 = snap(server)
    res2 = rec(db, bits)
    assert res2.deleted == ()
    assert {r["outcome"] for r in imports_since(server, s2)} == {"skipped"}


def test_a_server_file_replaced_by_a_symlink_counts_as_removed(
    server: PgServer, db: AppDatabase, tmp_path: Path, bits: Path
) -> None:
    name = f"Linked {tag()}"
    data = bit(name)[0]
    put(bits, "a.bit", data)
    rec(db, bits)
    p = policy_by_name(server, name)
    assert p is not None
    put(tmp_path, "copy.bit", data)
    (bits / "a.bit").unlink()
    os.symlink(tmp_path / "copy.bit", bits / "a.bit")
    s = snap(server)
    res = rec(db, bits)
    assert imports_since(server, s) == []
    assert [d.policy_id for d in res.deleted] == [p["policy_id"]]
    assert (tmp_path / "copy.bit").read_bytes() == data


def test_a_removed_upload_soft_deletes_its_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    up = upload(db, bits, bit(f"Up {tag()}")[0])
    pid = int(up.policy_id or 0)
    (bits / f"uploaded/policy-{pid}.bit").unlink()
    s = snap(server)
    res = rec(db, bits)
    assert imports_since(server, s) == []
    assert [d.policy_id for d in res.deleted] == [pid]
    row = policy_row(server, pid)
    assert row["deleted_at"] == T1 and row["source_file"] == f"deleted/{pid}"
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.delete"]
    assert entries[0]["actor"] == "system"
    assert entries[0]["detail"]["reason"] == "file removed"


def test_a_changed_server_file_is_reimported(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Changed {tag()}"
    first, ids = bit(name)
    put(bits, "a.bit", first)
    rec(db, bits)
    second, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])
    put(bits, "a.bit", second)
    s = snap(server)
    rec(db, bits)
    rows = imports_since(server, s)
    assert [(r["file_name"], r["outcome"], r["policy_version"]) for r in rows] == [
        ("a.bit", "success", 2)
    ]
    assert rows[0]["plugins_updated"] == 1


# ----------------------------------------------------------------------------
# CHK-M7-209: REQ-159 (1), (2), (3), (6) through the folders; #15
# ----------------------------------------------------------------------------


def test_req159_1_bit007_when_both_files_still_exist(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    na, nb = f"A {tag()}", f"B {tag()}"
    put(bits, "a.bit", bit(na)[0])
    put(bits, "b.bit", bit(nb)[0])
    rec(db, bits)
    a0, b0 = policy_by_name(server, na), policy_by_name(server, nb)
    put(bits, "b.bit", bit(na)[0])
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("a.bit", "skipped"), ("b.bit", "rejected")]
    assert codes(rows[1]["errors"]) == ["BIT007"]
    assert "a.bit" in rows[1]["errors"][0]["message"]
    assert catalog_now(server) == s.catalog
    assert policy_by_name(server, na) == a0 and policy_by_name(server, nb) == b0
    assert res.deleted == ()


def test_req159_2_a_renamed_file_moves_the_policy_not_delete_then_revive(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Moving {tag()}"
    data, _ = bit(name, [P(), P()])
    put(bits, "a.bit", data)
    rec(db, bits)
    before = policy_by_name(server, name)
    assert before is not None
    pid = int(before["policy_id"])
    plugs = members(server, pid)
    os.rename(bits / "a.bit", bits / "c.bit")
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert [(r["file_name"], r["outcome"]) for r in rows] == [("c.bit", "success")]
    after = policy_row(server, pid)
    assert after["deleted_at"] is None
    assert after["source_file"] == "c.bit"
    assert after["version"] == before["version"]  # same bytes, not a revival
    assert members(server, pid) == plugs
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.import", "policy.move"]
    assert entries[1]["target"] == f"policy:{pid}"
    assert entries[1]["detail"] == {"from": "a.bit", "to": "c.bit"}
    assert res.deleted == ()
    assert counter_delta(s) == {"alert:policy_imported": 1.0}


def test_req159_3_server_file_takes_an_uploaded_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Uploaded {tag()}"
    data = bit(name)[0]
    up = upload(db, bits, data)
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    put(bits, "x.bit", data)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("x.bit", "success")]  # the copy never reached
    row = policy_row(server, pid)
    assert (row["source_file"], row["deleted_at"]) == ("x.bit", None)
    assert not (bits / rel).exists()
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.import", "policy.move"]
    assert entries[1]["detail"] == {"from": rel, "to": "x.bit"}
    assert res.strays == () and res.renamed == () and res.deleted == ()
    assert res.leftovers == ()
    # A later upload with that name is refused (409 policy_managed_on_server).
    with db.session() as se, catalog_lock(se), pytest.raises(PolicyManagedOnServer):
        uploads.import_upload(se, FixedClock(), bits, data, "c.bit", actor=ADMIN)
    s2 = snap(server)
    res2 = rec(db, bits)
    assert rows_by_file(imports_since(server, s2)) == [("x.bit", "skipped")]
    assert res2.strays == ()


@pytest.mark.parametrize(
    ("first", "second"),
    [("a.bit", "b.bit"), ("B.bit", "a.bit"), ("a.bit", "a0.bit"), ("z.bit", "é.bit")],
)
def test_req159_6_first_import_of_two_files_with_one_name_follows_15(
    server: PgServer, db: AppDatabase, bits: Path, first: str, second: str
) -> None:
    name = f"Twin {tag()}"
    win, _ = bit(name)
    lose, _ = bit(name, [P(execute="cat /etc/issue")])
    put(bits, second, lose)  # created first, so creation order cannot decide
    put(bits, first, win)
    s = snap(server)
    rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [(first, "success"), (second, "rejected")]
    assert codes(rows[1]["errors"]) == ["BIT007"]
    assert first in rows[1]["errors"][0]["message"]
    p = policy_by_name(server, name)
    assert p is not None
    assert (p["source_file"], p["source_sha256"]) == (first, sha(win))


def test_15_a_live_policys_file_goes_before_a_new_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """z.bit holds X; in one reconcile it renames X to Y in place and a new
    a.bit (earlier in byte order) takes the name X. z.bit goes first (#15), so
    the rename happens and a.bit then imports X as a new policy."""
    x, y = f"X {tag()}", f"Y {tag()}"
    put(bits, "z.bit", bit(x)[0])
    rec(db, bits)
    old = policy_by_name(server, x)
    assert old is not None
    put(bits, "z.bit", bit(y)[0])
    put(bits, "a.bit", bit(x)[0])
    s = snap(server)
    rec(db, bits)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("z.bit", "success"), ("a.bit", "success")]
    renamed = policy_row(server, int(old["policy_id"]))
    assert (renamed["policy_name"], renamed["source_file"]) == (y, "z.bit")
    new = policy_by_name(server, x)
    assert new is not None and new["policy_id"] != old["policy_id"]
    assert new["source_file"] == "a.bit"


def test_server_files_are_reconciled_before_uploaded_files(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """With aa.bit sorting after uploaded/... by bytes would be wrong anyway;
    here every server file comes before any upload, whatever the bytes."""
    up = upload(db, bits, bit(f"U {tag()}")[0])
    put(bits, "zz.bit", bit(f"Z {tag()}")[0])
    put(bits, "aa.bit", bit(f"A {tag()}")[0])
    s = snap(server)
    rec(db, bits)
    assert rows_by_file(imports_since(server, s)) == [
        ("aa.bit", "success"),
        ("zz.bit", "success"),
        (f"uploaded/policy-{up.policy_id}.bit", "skipped"),
    ]


# ----------------------------------------------------------------------------
# Extra tests (i) to (iv) and the classification (a), (b), (c)
# ----------------------------------------------------------------------------


def test_i_a_live_upload_unchanged_is_skipped_and_changed_is_success(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Live {tag()}"
    data, ids = bit(name)
    up = upload(db, bits, data)
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert [(r["file_name"], r["outcome"], r["mode"]) for r in rows] == [
        (rel, "skipped", "auto")
    ]
    assert audits_since(server, s) == [] and counter_delta(s) == {}
    assert catalog_now(server) == s.catalog
    assert res.outcomes[0].policy_id == pid
    changed, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])
    put(bits, rel, changed)
    s2 = snap(server)
    res2 = rec(db, bits)
    rows2 = imports_since(server, s2)
    assert [(r["file_name"], r["outcome"], r["policy_version"]) for r in rows2] == [
        (rel, "success", 2)
    ]
    row = policy_row(server, pid)
    assert (row["source_file"], row["source_sha256"]) == (rel, sha(changed))
    assert (bits / rel).read_bytes() == changed
    assert actions(audits_since(server, s2)) == ["policy.import"]
    assert counter_delta(s2) == {"alert:policy_imported": 1.0}
    assert res2.leftovers == () and res2.strays == ()


def _leftover(db: AppDatabase, bits: Path, content: bytes | None = None) -> int:
    up = upload(db, bits, bit(f"Deleted {tag()}")[0])
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    kept = (bits / rel).read_bytes()
    dl.delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    assert not (bits / rel).exists()
    put(bits, rel, kept if content is None else content)  # the crash window
    return pid


@pytest.mark.parametrize("content", ["same", "other", "names-live", "garbage"])
def test_ii_a_leftover_is_removed_never_imported_and_reported(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    live_name = f"Live {tag()}"
    put(bits, "live.bit", bit(live_name)[0])
    rec(db, bits)
    data = {
        "same": None,
        "other": bit(f"Other {tag()}")[0],
        "names-live": bit(live_name)[0],
        "garbage": b"\x00not xml",
    }[content]
    pid = _leftover(db, bits, data)
    rel = f"uploaded/policy-{pid}.bit"
    before = policy_row(server, pid)
    reads: list[str] = []
    real_read = folders.read_input

    def spy(bits_dir: Path, r: str) -> FileInput | None:
        reads.append(r)
        return real_read(bits_dir, r)

    monkeypatch.setattr(folders, "read_input", spy)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert res.leftovers == (Difference(rel, "leftover of an interrupted delete"),)
    assert not (bits / rel).exists()
    assert rel not in reads  # never read
    assert rows_by_file(imports_since(server, s)) == [("live.bit", "skipped")]
    assert audits_since(server, s) == [] and counter_delta(s) == {}
    assert catalog_now(server) == s.catalog
    assert policy_row(server, pid) == before  # still deleted, untouched
    assert res.strays == () and res.deleted == () and res.renamed == ()
    lines = [r for r in caplog.records if r.name == LOGGER and "leftover" in r.msg]
    assert len(lines) == 1
    # Next time there is nothing left to report.
    res2 = rec(db, bits)
    assert res2.leftovers == ()


def test_iii_the_leftover_rule_never_fires_for_a_live_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Live {tag()}"
    data, ids = bit(name)
    up = upload(db, bits, data)
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    other, _ = bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])
    put(bits, rel, other)  # another hash
    s = snap(server)
    res = rec(db, bits)
    assert res.leftovers == ()
    assert rows_by_file(imports_since(server, s)) == [(rel, "success")]
    assert (bits / rel).read_bytes() == other
    assert policy_row(server, pid)["deleted_at"] is None
    with db.session() as se, se.transaction() as tx:
        assert folders.classify_upload(tx.conn, rel) == "live"


def test_classify_upload_cases(server: PgServer, db: AppDatabase, bits: Path) -> None:
    live = upload(db, bits, bit(f"L {tag()}")[0])
    lid = int(live.policy_id or 0)
    put(bits, "srv.bit", bit(f"S {tag()}")[0])
    rec(db, bits)
    with owner(server) as c:
        got = c.execute(
            "SELECT policy_id FROM policy WHERE source_file = 'srv.bit'"
        ).fetchone()
    assert got is not None
    sid = int(got[0])
    gone = _leftover(db, bits)
    cases = {
        f"uploaded/policy-{lid}.bit": "live",
        f"uploaded/policy-{gone}.bit": "leftover",
        f"uploaded/policy-{sid}.bit": "stray",  # a server policy's old copy
        f"uploaded/policy-0{lid}.bit": "stray",
        "uploaded/policy-999999999.bit": "stray",
        f"uploaded/policy-{2**63 - 1}.bit": "stray",
        f"uploaded/policy-{2**63}.bit": "stray",
        "uploaded/x.bit": "stray",
    }
    with db.session() as se, se.transaction() as tx:
        got_kinds = {rel: folders.classify_upload(tx.conn, rel) for rel in cases}
    assert got_kinds == cases


def test_iv_no_uploaded_file_ever_reaches_the_pipeline_as_a_server_target(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = upload(db, bits, bit(f"L {tag()}")[0])
    lid = int(live.policy_id or 0)
    live_rel = f"uploaded/policy-{lid}.bit"
    changed = upload(db, bits, bit(f"C {tag()}")[0])
    cid = int(changed.policy_id or 0)
    cname = policy_row(server, cid)["policy_name"]
    put(bits, f"uploaded/policy-{cid}.bit", bit(cname, [P(), P()])[0])
    put(bits, "srv.bit", bit(f"S {tag()}")[0])
    rec(db, bits)
    with owner(server) as c:
        got = c.execute(
            "SELECT policy_id FROM policy WHERE source_file = 'srv.bit'"
        ).fetchone()
    assert got is not None
    sid = int(got[0])
    put(bits, f"uploaded/policy-{sid}.bit", bit(f"S copy {tag()}")[0])
    put(bits, "uploaded/x.bit", bit(f"X {tag()}")[0])
    put(bits, "uploaded/policy-999999.bit", bit(f"N {tag()}")[0])
    put(bits, f"uploaded/policy-0{lid}.bit", bit(f"Z {tag()}")[0])
    gone = _leftover(db, bits)
    put(bits, "new.bit", bit(f"New {tag()}")[0])
    seen: list[FileInput] = []
    targets: list[Target] = []
    real_import = pipeline.import_one
    real_decide = store_decide.decide

    def spy_import(*a: Any, **k: Any) -> ImportOutcome:
        seen.append(a[3])
        return real_import(*a, **k)

    def spy_decide(conn: Any, rules: Any, target: Target, exists: Any) -> Any:
        targets.append(target)
        return real_decide(conn, rules, target, exists)

    monkeypatch.setattr(folders, "import_one", spy_import)
    monkeypatch.setattr(store_decide, "decide", spy_decide)
    res = rec(db, bits)
    for t in targets:
        assert not (t.kind == "server" and (t.source_file or "").startswith("uploaded"))
    by_name = {f.file_name: f for f in seen}
    assert sorted(by_name) == sorted(
        ["new.bit", "srv.bit", live_rel, f"uploaded/policy-{cid}.bit"]
    )
    for rel, f in by_name.items():
        if rel.startswith("uploaded/"):
            assert f.target == Target("upload", None, f.sha256), rel
        else:
            assert f.target == Target("server", rel, f.sha256), rel
    assert len(targets) == len(seen)
    assert sorted(res.strays) == sorted(
        [
            f"uploaded/policy-{sid}.bit",
            "uploaded/x.bit",
            "uploaded/policy-999999.bit",
            f"uploaded/policy-0{lid}.bit",
        ]
    )
    assert res.leftovers == (
        Difference(f"uploaded/policy-{gone}.bit", folders.LEFTOVER_CHECK),
    )


@pytest.mark.parametrize(
    "kind",
    [
        "new-name",
        "no-policy",
        "leading-zero",
        "over-bigserial",
        "server-copy",
        "live-name",
    ],
)
def test_c_strays_are_never_imported_and_are_reported(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    live = upload(db, bits, bit(f"Live {tag()}")[0])
    lid = int(live.policy_id or 0)
    sname = f"Server {tag()}"
    sdata = bit(sname)[0]
    put(bits, "srv.bit", sdata)
    rec(db, bits)
    srv = policy_by_name(server, sname)
    assert srv is not None
    sid = int(srv["policy_id"])
    lname = policy_row(server, lid)["policy_name"]
    rel, data = {
        "new-name": ("uploaded/x.bit", bit(f"Stray {tag()}")[0]),
        "no-policy": ("uploaded/policy-999999.bit", bit(f"Stray {tag()}")[0]),
        "leading-zero": (f"uploaded/policy-0{lid}.bit", bit(lname, [P(), P()])[0]),
        "over-bigserial": (
            "uploaded/policy-99999999999999999999.bit",
            bit(f"Stray {tag()}")[0],
        ),
        "server-copy": (f"uploaded/policy-{sid}.bit", bit(sname, [P(), P()])[0]),
        "live-name": ("uploaded/y.bit", bit(lname, [P(), P(), P()])[0]),
    }[kind]
    put(bits, rel, data)
    reads: list[str] = []
    real_read = folders.read_input

    def spy(bits_dir: Path, r: str) -> FileInput | None:
        reads.append(r)
        return real_read(bits_dir, r)

    monkeypatch.setattr(folders, "read_input", spy)
    caplog.set_level(logging.DEBUG)
    before_tree = tree(bits)
    for run in range(2):  # the same answer every time: no churn
        reads.clear()
        caplog.clear()
        s = snap(server)
        res = rec(db, bits)
        assert res.strays == (rel,), run
        assert rel not in reads
        rows = imports_since(server, s)
        assert rel not in {r["file_name"] for r in rows}
        assert {r["outcome"] for r in rows} == {"skipped"}
        assert audits_since(server, s) == [] and counter_delta(s) == {}
        assert catalog_now(server) == s.catalog
        assert tree(bits) == before_tree  # left in place, byte-identical
        assert res.deleted == () and res.renamed == () and res.leftovers == ()
        stray_lines = [
            r for r in caplog.records if r.name == LOGGER and "skipped" in r.msg
        ]
        assert len(stray_lines) == 1
        for r in caplog.records:
            assert rel.removeprefix("uploaded/") not in r.getMessage()
    assert policy_row(server, sid)["source_file"] == "srv.bit"
    assert policy_row(server, lid)["source_file"] == f"uploaded/policy-{lid}.bit"


@pytest.mark.parametrize(
    "edit", ["new-name", "other-upload", "server-name", "new-name-with-bit102"]
)
def test_a_live_upload_with_an_edited_name_is_skipped_and_reported(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    edit: str,
) -> None:
    """decisions 2026-10-27, "A live upload file with a hand-edited
    <PolicyName> is skipped and reported like a stray": nothing imported, no
    row, no alert, one log line, listed for #103, the policy keeps its last
    good rows; this replaces the refusal for a server policy's name. The next
    file is still reconciled."""
    sname = f"Server {tag()}"
    put(bits, "srv.bit", bit(sname)[0])
    u1 = upload(db, bits, bit(f"U1 {tag()}")[0])
    u2 = upload(db, bits, bit(f"U2 {tag()}")[0])
    rec(db, bits)
    first, later = sorted(
        [f"uploaded/policy-{u1.policy_id}.bit", f"uploaded/policy-{u2.policy_id}.bit"],
        key=str.encode,
    )
    first_id = int(first.removeprefix("uploaded/policy-").removesuffix(".bit"))
    later_id = int(later.removeprefix("uploaded/policy-").removesuffix(".bit"))
    later_name = policy_row(server, later_id)["policy_name"]
    new_name = f"Edited {tag()}"
    edited = {
        "new-name": bit(new_name)[0],
        "other-upload": bit(later_name, [P(), P(), P()])[0],
        "server-name": bit(sname, [P(), P()])[0],
        "new-name-with-bit102": bit(new_name, [P(execute="rm -rf /tmp/x")])[0],
    }[edit]
    put(bits, first, edited)
    later_data = bit(later_name, [P(), P()])[0]
    put(bits, later, later_data)  # changed, after the skipped one
    first_before = policy_row(server, first_id)
    srv = policy_by_name(server, sname)
    assert srv is not None
    parses: list[int] = []
    real_prepare = pipeline.prepare

    def spy(data: bytes | None) -> Any:
        parses.append(1)
        return real_prepare(data)

    monkeypatch.setattr(folders, "prepare", spy)
    monkeypatch.setattr(pipeline, "prepare", spy)  # a re-parse inside import_one
    caplog.set_level(logging.DEBUG)
    for run in range(3):
        parses.clear()
        caplog.clear()
        s = snap(server)
        res = rec(db, bits)
        assert res.renamed == (first,), run
        rows = imports_since(server, s)
        want = [("srv.bit", "skipped"), (later, "success" if run == 0 else "skipped")]
        assert rows_by_file(rows) == want
        entries = audits_since(server, s)
        assert actions(entries) == (["policy.import"] if run == 0 else [])
        assert counter_delta(s) == ({"alert:policy_imported": 1.0} if run == 0 else {})
        assert res.strays == () and res.deleted == () and res.leftovers == ()
        assert len(parses) == 3  # srv.bit, first, later: each parsed once
        assert (bits / first).read_bytes() == edited
        lines = [
            r
            for r in caplog.records
            if r.name == LOGGER and "policy name was edited" in r.getMessage()
        ]
        assert len(lines) == 1
        for r in caplog.records:
            text = r.getMessage() + repr(r.args)
            assert new_name not in text and first not in text
            assert first.removeprefix("uploaded/") not in text
    row = policy_row(server, first_id)
    assert row == first_before  # keeps its last good rows, not deleted
    assert policy_by_name(server, sname) == srv
    assert policy_by_name(server, new_name) is None
    assert policy_row(server, later_id)["source_sha256"] == sha(later_data)


@pytest.mark.parametrize("bad", ["unparsable", "oversize", "bad-name"])
def test_a_live_upload_with_no_valid_name_is_rejected_every_time(
    server: PgServer, db: AppDatabase, bits: Path, bad: str
) -> None:
    """A file with no valid PolicyName is not `renamed`: the pipeline rejects
    it, and it is retried at each reconcile (TS §4.1 L532)."""
    up = upload(db, bits, bit(f"U {tag()}")[0])
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    data = {
        "unparsable": b"<not xml",
        "oversize": b"<" + b"x" * MAX_BIT_BYTES,
        "bad-name": bit("x" * 129)[0],  # PolicyName over 128 characters
    }[bad]
    put(bits, rel, data)
    before = policy_row(server, pid)
    for _ in range(3):
        s = snap(server)
        res = rec(db, bits)
        rows = imports_since(server, s)
        assert rows_by_file(rows) == [(rel, "rejected")]
        assert rows[0]["file_sha256"] == sha(data)
        assert actions(audits_since(server, s)) == ["policy.import_rejected"]
        assert res.renamed == () and res.strays == () and res.deleted == ()
        assert catalog_now(server) == s.catalog
    assert policy_row(server, pid) == before
    assert (bits / rel).read_bytes() == data


# ----------------------------------------------------------------------------
# Catalog lock (TASK-154 review carry (a)) and logging
# ----------------------------------------------------------------------------


def _catalog_free(server: PgServer) -> bool:
    with app(server) as c:
        row = c.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
        assert row is not None
        if row[0]:
            c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        return bool(row[0])


def test_the_lock_spans_every_import_and_a_concurrent_delete_waits(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    victim = upload(db, bits, bit(f"Victim {tag()}")[0])
    vid = int(victim.policy_id or 0)
    put(bits, "a.bit", bit(f"A {tag()}")[0])
    put(bits, "b.bit", bit(f"B {tag()}")[0])
    inside = threading.Event()
    release = threading.Event()
    held: list[bool] = []
    real_import = pipeline.import_one

    def slow(*a: Any, **k: Any) -> ImportOutcome:
        held.append(not _catalog_free(server))
        if a[3].file_name == "b.bit":
            inside.set()
            assert release.wait(20)
        return real_import(*a, **k)

    monkeypatch.setattr(folders, "import_one", slow)
    errors: list[BaseException] = []
    after: list[bool] = []

    def reconcile_thread() -> None:
        try:
            with db.session() as s, catalog_lock(s):
                folders.reconcile(s, FixedClock(), bits)
                after.append(not _catalog_free(server))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    deleted: list[dl.DeleteResult] = []

    def delete_thread() -> None:
        try:
            deleted.append(
                dl.delete_policy(
                    db, vid, actor="user:7", clock=FixedClock(), bits_dir=bits
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=reconcile_thread)
    t.start()
    assert inside.wait(20)
    d = threading.Thread(target=delete_thread)
    d.start()
    d.join(1.0)
    assert d.is_alive() and deleted == []  # waits for the reconcile's lock
    release.set()
    t.join(20)
    d.join(20)
    assert not t.is_alive() and not d.is_alive()
    assert errors == []
    assert held == [True, True, True]  # a.bit, b.bit, the live upload
    assert after == [True]  # still held when reconcile returns
    assert [r.policy_id for r in deleted] == [vid]
    assert _catalog_free(server)


def test_reconcile_never_logs_file_content_or_names(
    server: PgServer, db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    canary = f"canary{tag()}"
    put(bits, f"{canary}-a.bit", bit(f"{canary} A", [P(execute=f"echo {canary}")])[0])
    put(bits, f"{canary}-dup.bit", bit(f"{canary} A")[0])
    put(bits, f"uploaded/{canary}.bit", bit(f"{canary} S")[0])
    put(bits, f"{canary}-bad.bit", b"<Policy>" + canary.encode())
    os.symlink("/etc/passwd", bits / f"{canary}-l.bit")
    caplog.set_level(logging.DEBUG)
    rec(db, bits)
    rec(db, bits)
    for r in caplog.records:
        text = r.getMessage() + repr(r.args) + repr(r.__dict__)
        assert canary not in text, text


def test_reconcile_leaves_temp_files_and_writes_no_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    up = upload(db, bits, bit(f"T {tag()}")[0])
    tmp = f"uploaded/.tmp-{up.policy_id}-{'a' * 64}"
    put(bits, tmp, b"half written")
    put(bits, "s.bit", bit(f"S {tag()}")[0])
    rec(db, bits)
    before = tree(bits)
    rec(db, bits)
    assert tree(bits) == before
    assert (bits / tmp).read_bytes() == b"half written"


def test_spy_contract() -> None:
    """Guards the spies above: `file` is import_one's fourth positional
    parameter, as the reconcile passes it."""
    import inspect

    params = list(inspect.signature(pipeline.import_one).parameters)
    assert params[:4] == ["session", "clock", "bits_dir", "file"]


# ----------------------------------------------------------------------------
# TASK-156 revision 2: the folder guard (decisions 2026-10-27, user "Folder
# guard" and lead "Folder guard details" (1)). A missing, symlinked or
# non-directory `uploaded/` or bits folder is unreadable: nothing is imported
# from it, no policy whose source_file is in it is deleted, one fixed-words
# log line per folder (no path), and the result lists it. An unreadable bits
# folder makes both folders unreadable. A real empty folder is still empty.
# ----------------------------------------------------------------------------

BOTH = ("./", "uploaded/")
BREAKS = ["missing", "symlink", "file"]


def _break(path: Path, how: str, away: Path) -> None:
    """Make the folder at `path` unreadable; its real content goes to `away`
    (for "symlink", `path` then links to that real directory)."""
    path.rename(away)
    if how == "symlink":
        os.symlink(away, path)
    elif how == "file":
        path.write_bytes(b"a regular file where a folder belongs\n")
    else:
        assert how == "missing"


def _restore(path: Path, away: Path) -> None:
    if os.path.lexists(path):
        path.unlink()
    away.rename(path)


def _guard_setup(server: PgServer, db: AppDatabase, bits: Path) -> dict[str, Any]:
    """Server policies S (s.bit) and R (r.bit), a live upload U and a deleted
    upload D, all reconciled once with both folders readable."""
    s_name, r_name, u_name = f"GS {tag()}", f"GR {tag()}", f"GU {tag()}"
    put(bits, "s.bit", bit(s_name, [P(), P()])[0])
    put(bits, "r.bit", bit(r_name)[0])
    u_data, u_ids = bit(u_name, [P(), P()])
    upload(db, bits, u_data)
    d = upload(db, bits, bit(f"GD {tag()}")[0])
    d_id = int(d.policy_id or 0)
    d_rel = f"uploaded/policy-{d_id}.bit"
    d_bytes = (bits / d_rel).read_bytes()
    dl.delete_policy(db, d_id, actor="user:7", clock=FixedClock(), bits_dir=bits)
    first = rec(db, bits)
    assert first.unreadable_folders == ()
    assert first.deleted == () and first.leftovers == () and first.strays == ()
    ids = {}
    for key, name in [("S", s_name), ("R", r_name), ("U", u_name)]:
        p = policy_by_name(server, name)
        assert p is not None and p["deleted_at"] is None
        ids[key] = int(p["policy_id"])
    assert policy_row(server, ids["U"])["source_file"] == (
        f"uploaded/policy-{ids['U']}.bit"
    )
    return {
        **ids,
        "D": d_id,
        "d_rel": d_rel,
        "d_bytes": d_bytes,
        "u_name": u_name,
        "u_ids": u_ids,
        "s_name": s_name,
    }


def _frozen(server: PgServer, ids: list[int]) -> dict[int, Any]:
    """Each policy's row and its members' states."""
    return {i: (policy_row(server, i), members(server, i)) for i in ids}


def _guard_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.getMessage().startswith("folder unreadable")
    ]


def _assert_guard_log(
    caplog: pytest.LogCaptureFixture, labels: tuple[str, ...], tmp_path: Path
) -> list[str]:
    """Exactly one line per unreadable folder, naming its label and no path."""
    lines = _guard_lines(caplog)
    assert len(lines) == len(labels), lines
    for label in labels:
        assert sum(line.endswith(" " + label) for line in lines) == 1, lines
    for r in caplog.records:
        text = r.getMessage() + repr(r.args)
        assert str(tmp_path) not in text, text
        assert "/bits" not in text and "policy-" not in text, text
    return lines


@pytest.mark.parametrize(
    ("make", "labels"),
    [
        ("real", ()),
        ("both-empty", ()),
        ("uploaded-missing", ("uploaded/",)),
        ("uploaded-symlink", ("uploaded/",)),
        ("uploaded-dangling", ("uploaded/",)),
        ("uploaded-file", ("uploaded/",)),
        ("bits-missing", BOTH),
        ("bits-symlink", BOTH),
        ("bits-file", BOTH),
        ("bits-symlink-uploaded-missing", BOTH),
    ],
)
def test_unreadable_labels(
    tmp_path: Path, bits: Path, make: str, labels: tuple[str, ...]
) -> None:
    good = bit()[0]
    if make != "both-empty":
        put(bits, "s.bit", good)
        put(bits, "uploaded/policy-1.bit", good)
    away = tmp_path / "away"
    if make.startswith("uploaded-"):
        how = make.removeprefix("uploaded-")
        if how == "dangling":
            (bits / "uploaded/policy-1.bit").unlink()
            (bits / "uploaded").rmdir()
            os.symlink(tmp_path / "nowhere", bits / "uploaded")
        else:
            _break(bits / "uploaded", how, away)
    elif make == "bits-symlink-uploaded-missing":
        (bits / "uploaded/policy-1.bit").unlink()
        (bits / "uploaded").rmdir()
        _break(bits, "symlink", away)
    elif make.startswith("bits-"):
        _break(bits, make.removeprefix("bits-"), away)
    before = tree(tmp_path)
    assert folders.unreadable(bits) == labels
    expect = {
        (): ["s.bit", "uploaded/policy-1.bit"] if make == "real" else [],
        ("uploaded/",): ["s.bit"],
        BOTH: [],
    }[labels]
    assert folders.discover(bits) == expect  # nothing read through a link
    assert tree(tmp_path) == before


@pytest.mark.parametrize("how", BREAKS)
def test_an_unreadable_uploaded_folder_is_left_alone_and_the_server_folder_reconciled(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _guard_setup(server, db, bits)
    u_rel = f"uploaded/policy-{g['U']}.bit"
    away = tmp_path / "uploaded-real"
    _break(bits / "uploaded", how, away)
    # Content that a followed link would act on: a changed live upload, a
    # leftover (would be removed) and a stray (would be reported).
    changed = bit(g["u_name"], [P(uuid=g["u_ids"][0], execute="cat /etc/issue")])[0]
    put(away, f"policy-{g['U']}.bit", changed)
    put(away, f"policy-{g['D']}.bit", g["d_bytes"])
    put(away, "policy-999999999.bit", bit(f"GX {tag()}")[0])
    away_tree = tree(away)
    # The server folder changes: r.bit removed, n.bit added.
    (bits / "r.bit").unlink()
    n_name = f"GN {tag()}"
    put(bits, "n.bit", bit(n_name)[0])
    frozen = _frozen(server, [g["U"], g["D"]])
    reads: list[str] = []
    real_read = folders.read_input

    def spy(bits_dir: Path, r: str) -> FileInput | None:
        reads.append(r)
        return real_read(bits_dir, r)

    monkeypatch.setattr(folders, "read_input", spy)
    lines_per_run: list[list[str]] = []
    for run in range(3):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        s = snap(server)
        res = rec(db, bits)
        rows = imports_since(server, s)
        assert res.unreadable_folders == ("uploaded/",)
        lines_per_run.append(_assert_guard_log(caplog, ("uploaded/",), tmp_path))
        assert [r for r in rows if r["file_name"].startswith("uploaded/")] == []
        assert res.leftovers == () and res.strays == () and res.renamed == ()
        assert _frozen(server, [g["U"], g["D"]]) == frozen  # U live, D deleted
        assert tree(away) == away_tree
        entries = audits_since(server, s)
        if run == 0:
            assert sorted(rows_by_file(rows)) == [
                ("n.bit", "success"),
                ("s.bit", "skipped"),
            ]
            assert [d.policy_id for d in res.deleted] == [g["R"]]
            assert sorted(actions(entries)) == ["policy.delete", "policy.import"]
            assert counter_delta(s) == {
                "alert:policy_imported": 1.0,
                "alert:policy_deleted": 1.0,
            }
            assert policy_row(server, g["R"])["deleted_at"] == T1
        else:  # no churn
            assert sorted(rows_by_file(rows)) == [
                ("n.bit", "skipped"),
                ("s.bit", "skipped"),
            ]
            assert res.deleted == ()
            assert entries == [] and counter_delta(s) == {}
            assert catalog_now(server) == s.catalog
    assert [r for r in reads if r.startswith("uploaded/")] == []
    assert lines_per_run[0] == lines_per_run[1] == lines_per_run[2]
    assert policy_row(server, g["S"])["deleted_at"] is None
    n = policy_by_name(server, n_name)
    assert n is not None and n["deleted_at"] is None
    # Recovery: the real folder is back and is read again.
    _restore(bits / "uploaded", away)
    s = snap(server)
    res = rec(db, bits)
    assert res.unreadable_folders == ()
    assert sorted(rows_by_file(imports_since(server, s))) == [
        ("n.bit", "skipped"),
        ("s.bit", "skipped"),
        (u_rel, "success"),
    ]
    assert policy_row(server, g["U"])["source_sha256"] == sha(changed)
    assert res.leftovers == (Difference(g["d_rel"], folders.LEFTOVER_CHECK),)
    assert res.strays == ("uploaded/policy-999999999.bit",)
    assert res.deleted == ()


@pytest.mark.parametrize("how", BREAKS)
def test_an_unreadable_bits_folder_makes_both_folders_unreadable(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _guard_setup(server, db, bits)
    away = tmp_path / "bits-real"
    _break(bits, how, away)
    # Everything a followed link would act on, in both folders.
    s_changed = bit(g["s_name"], [P(), P(execute="cat /etc/issue")])[0]
    put(away, "s.bit", s_changed)
    (away / "r.bit").unlink()
    put(away, "n.bit", bit(f"GN {tag()}")[0])
    changed = bit(g["u_name"], [P(uuid=g["u_ids"][0], execute="cat /etc/issue")])[0]
    put(away, f"uploaded/policy-{g['U']}.bit", changed)
    put(away, g["d_rel"], g["d_bytes"])
    put(away, "uploaded/policy-999999999.bit", bit(f"GX {tag()}")[0])
    away_tree = tree(away)
    ids = [g["S"], g["R"], g["U"], g["D"]]
    frozen = _frozen(server, ids)
    reads: list[str] = []
    real_read = folders.read_input

    def spy(bits_dir: Path, r: str) -> FileInput | None:
        reads.append(r)
        return real_read(bits_dir, r)

    monkeypatch.setattr(folders, "read_input", spy)
    lines_per_run: list[list[str]] = []
    for _ in range(3):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        s = snap(server)
        res = rec(db, bits)
        assert res.unreadable_folders == BOTH
        lines_per_run.append(_assert_guard_log(caplog, BOTH, tmp_path))
        assert imports_since(server, s) == []
        assert audits_since(server, s) == [] and counter_delta(s) == {}
        assert catalog_now(server) == s.catalog
        assert (res.outcomes, res.deleted, res.leftovers) == ((), (), ())
        assert (res.strays, res.renamed) == ((), ())
        assert _frozen(server, ids) == frozen
        assert tree(away) == away_tree
        assert folders.discover(bits) == []
    assert reads == []
    assert lines_per_run[0] == lines_per_run[1] == lines_per_run[2]
    # Recovery: the real folder is back and both folders are reconciled.
    _restore(bits, away)
    s = snap(server)
    res = rec(db, bits)
    assert res.unreadable_folders == ()
    assert [d.policy_id for d in res.deleted] == [g["R"]]
    assert sorted(
        (r["file_name"], r["outcome"])
        for r in imports_since(server, s)
        if not r["file_name"].startswith("uploaded/")
    ) == [("n.bit", "success"), ("s.bit", "success")]
    assert policy_row(server, g["U"])["source_sha256"] == sha(changed)
    assert res.leftovers == (Difference(g["d_rel"], folders.LEFTOVER_CHECK),)


@pytest.mark.parametrize("inner", ["missing", "symlink", "file"])
def test_both_folders_unreadable_together(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    inner: str,
) -> None:
    """A symlinked bits folder whose own uploaded/ is broken too."""
    g = _guard_setup(server, db, bits)
    _break(bits / "uploaded", inner, tmp_path / "uploaded-real")
    _break(bits, "symlink", tmp_path / "bits-real")
    (tmp_path / "bits-real" / "s.bit").unlink()
    ids = [g["S"], g["R"], g["U"], g["D"]]
    frozen = _frozen(server, ids)
    before = tree(tmp_path)
    for _ in range(2):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        s = snap(server)
        res = rec(db, bits)
        assert res.unreadable_folders == BOTH
        _assert_guard_log(caplog, BOTH, tmp_path)
        assert imports_since(server, s) == [] and audits_since(server, s) == []
        assert res.deleted == () and catalog_now(server) == s.catalog
        assert _frozen(server, ids) == frozen
        assert tree(tmp_path) == before


@pytest.mark.parametrize("empty", ["uploaded", "server", "both"])
def test_a_real_empty_folder_still_deletes_its_policies(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    empty: str,
) -> None:
    g = _guard_setup(server, db, bits)
    gone: list[int] = []
    if empty in ("uploaded", "both"):
        (bits / f"uploaded/policy-{g['U']}.bit").unlink()
        assert os.listdir(bits / "uploaded") == []
        gone.append(g["U"])
    if empty in ("server", "both"):
        (bits / "s.bit").unlink()
        (bits / "r.bit").unlink()
        assert os.listdir(bits) == ["uploaded"]
        gone += [g["S"], g["R"]]
    kept = [i for i in (g["S"], g["R"], g["U"]) if i not in gone]
    for run in range(3):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        s = snap(server)
        res = rec(db, bits)
        assert res.unreadable_folders == ()
        assert _guard_lines(caplog) == []
        entries = audits_since(server, s)
        if run == 0:
            assert sorted(d.policy_id for d in res.deleted) == sorted(gone)
            assert actions(entries) == ["policy.delete"] * len(gone)
            assert {e["detail"]["reason"] for e in entries} == {"file removed"}
            assert counter_delta(s) == {"alert:policy_deleted": float(len(gone))}
            for i in gone:
                row = policy_row(server, i)
                assert row["deleted_at"] == T1
                assert row["source_file"] == f"deleted/{i}"
                assert {st for _, _, st in members(server, i)} == {"retired"}
        else:
            assert res.deleted == () and entries == [] and counter_delta(s) == {}
            assert catalog_now(server) == s.catalog
        for i in kept:
            assert policy_row(server, i)["deleted_at"] is None


def test_delete_removed_skips_an_unreadable_folder_but_not_an_empty_one(
    server: PgServer, db: AppDatabase, tmp_path: Path, bits: Path
) -> None:
    g = _guard_setup(server, db, bits)
    u_rel = f"uploaded/policy-{g['U']}.bit"
    _break(bits / "uploaded", "missing", tmp_path / "uploaded-real")
    (bits / "r.bit").unlink()
    with db.session() as s, catalog_lock(s):
        got = folders.delete_removed(s, FixedClock(), bits)
    assert [d.policy_id for d in got] == [g["R"]]  # the server folder still works
    assert policy_row(server, g["U"])["deleted_at"] is None
    _restore(bits / "uploaded", tmp_path / "uploaded-real")
    (bits / u_rel).unlink()  # now a real, empty uploaded/
    with db.session() as s, catalog_lock(s):
        got = folders.delete_removed(s, FixedClock(), bits)
    assert [d.policy_id for d in got] == [g["U"]]
    assert policy_row(server, g["U"])["deleted_at"] == T1
    _break(bits, "symlink", tmp_path / "bits-real")
    (tmp_path / "bits-real" / "s.bit").unlink()
    with db.session() as s, catalog_lock(s):
        got = folders.delete_removed(s, FixedClock(), bits)
    assert got == ()
    assert policy_row(server, g["S"])["deleted_at"] is None


# ----------------------------------------------------------------------------
# TASK-156 revision 3 (review TASK-156 finding 1, nit 2): the folder state is
# checked again right before each delete, and files are read relative to a
# no-follow handle of their folder. Folders are swapped at deterministic
# points by wrapping the module's own calls (no sleeps).
# ----------------------------------------------------------------------------


def _many(server: PgServer, db: AppDatabase, bits: Path, n: int) -> dict[str, Any]:
    """`n` server files (k*.bit) and `n` live uploads, reconciled once."""
    server_ids, upload_ids = [], []
    for i in range(n):
        name = f"MS {tag()}"
        put(bits, f"k{i}.bit", bit(name)[0])
        up = upload(db, bits, bit(f"MU {tag()}")[0])
        upload_ids.append(int(up.policy_id or 0))
    first = rec(db, bits)
    assert first.unreadable_folders == () and first.deleted == ()
    with owner(server) as c:
        got = c.execute(
            "SELECT policy_id FROM policy WHERE deleted_at IS NULL"
            " AND source_file LIKE 'k%%.bit' ORDER BY policy_id"
        ).fetchall()
    server_ids = [int(r[0]) for r in got]
    assert len(server_ids) == n
    return {"server": server_ids, "uploads": upload_ids}


def _deletes_of(entries: list[dict[str, Any]]) -> list[str]:
    return sorted(e["target"] for e in entries if e["action"] == "policy.delete")


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_uploaded_folder_broken_after_the_first_delete_deletes_no_more(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _many(server, db, bits, 3)
    ups = g["uploads"]
    for pid in ups:  # every upload's file removed: each would be deleted
        (bits / f"uploaded/policy-{pid}.bit").unlink()
    (bits / "k0.bit").unlink()  # a server deletion, before or after the swap
    target = tmp_path / "empty-target"
    target.mkdir()
    real = dl.delete_in_tx
    calls: list[int] = []

    def hook(tx: Any, policy_id: int, **kw: Any) -> Any:
        out = real(tx, policy_id, **kw)
        calls.append(policy_id)
        if policy_id in ups and not (tmp_path / "uploaded-real").exists():
            _break(bits / "uploaded", how, tmp_path / "uploaded-real")
            if how == "symlink":  # a link to a folder without those files
                (bits / "uploaded").unlink()
                os.symlink(target, bits / "uploaded")
        return out

    monkeypatch.setattr(folders, "delete_in_tx", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    gone_ups = [d.policy_id for d in res.deleted if d.policy_id in ups]
    assert len(gone_ups) == 1, res.deleted
    assert sorted(d.policy_id for d in res.deleted) == sorted(
        [g["server"][0], gone_ups[0]]
    )
    assert sorted(calls) == sorted(d.policy_id for d in res.deleted)
    for pid in ups:
        row = policy_row(server, pid)
        assert (row["deleted_at"] is None) == (pid != gone_ups[0]), pid
    for pid in g["server"][1:]:
        assert policy_row(server, pid)["deleted_at"] is None
    assert _deletes_of(audits_since(server, s)) == sorted(
        f"policy:{p}" for p in (g["server"][0], gone_ups[0])
    )
    assert res.unreadable_folders == ("uploaded/",)
    _assert_guard_log(caplog, ("uploaded/",), tmp_path)
    assert os.listdir(target) == []
    # The next reconcile still deletes nothing in the broken folder.
    s2 = snap(server)
    res2 = rec(db, bits)
    assert res2.deleted == () and res2.unreadable_folders == ("uploaded/",)
    assert _deletes_of(audits_since(server, s2)) == []


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_bits_folder_broken_after_the_first_delete_deletes_no_more(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _many(server, db, bits, 2)
    every = g["server"] + g["uploads"]
    for i in range(2):
        (bits / f"k{i}.bit").unlink()
    for pid in g["uploads"]:
        (bits / f"uploaded/policy-{pid}.bit").unlink()
    target = tmp_path / "bits-target"
    (target / "uploaded").mkdir(parents=True)  # real folders, no such files
    real = dl.delete_in_tx
    calls: list[int] = []

    def hook(tx: Any, policy_id: int, **kw: Any) -> Any:
        out = real(tx, policy_id, **kw)
        calls.append(policy_id)
        if len(calls) == 1:
            _break(bits, how, tmp_path / "bits-real")
            if how == "symlink":
                bits.unlink()
                os.symlink(target, bits)
        return out

    monkeypatch.setattr(folders, "delete_in_tx", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert [d.policy_id for d in res.deleted] == calls
    assert len(calls) == 1
    for pid in every:
        assert (policy_row(server, pid)["deleted_at"] is None) == (pid != calls[0])
    assert _deletes_of(audits_since(server, s)) == [f"policy:{calls[0]}"]
    assert res.unreadable_folders == BOTH
    _assert_guard_log(caplog, BOTH, tmp_path)
    assert tree(target) == {"uploaded": "dir"}


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_uploaded_folder_swapped_after_discover_is_not_read_or_deleted(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _guard_setup(server, db, bits)
    u_rel = f"uploaded/policy-{g['U']}.bit"
    u_before = policy_row(server, g["U"])
    n_name = f"GN {tag()}"
    put(bits, "n.bit", bit(n_name)[0])
    # The link target holds a changed copy of U's file: reading it would
    # import a new version.
    evil = tmp_path / "evil"
    evil.mkdir()
    changed = bit(g["u_name"], [P(uuid=g["u_ids"][0], execute="cat /etc/issue")])[0]
    put(evil, f"policy-{g['U']}.bit", changed)
    evil_tree = tree(evil)
    real = folders.discover

    def hook(bits_dir: Path) -> list[str]:
        found = real(bits_dir)
        assert u_rel in found
        _break(bits / "uploaded", "missing", tmp_path / "uploaded-real")
        if how == "symlink":
            os.symlink(evil, bits / "uploaded")
        return found

    monkeypatch.setattr(folders, "discover", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    rows = imports_since(server, s)
    assert sorted(rows_by_file(rows)) == [
        ("n.bit", "success"),
        ("r.bit", "skipped"),
        ("s.bit", "skipped"),
    ]
    assert res.unreadable_folders == ("uploaded/",)
    _assert_guard_log(caplog, ("uploaded/",), tmp_path)
    assert policy_row(server, g["U"]) == u_before
    assert res.deleted == ()
    assert res.strays == () and res.renamed == ()
    assert tree(evil) == evil_tree
    n = policy_by_name(server, n_name)
    assert n is not None and n["deleted_at"] is None


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_bits_folder_swapped_after_discover_is_not_read_or_deleted(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _guard_setup(server, db, bits)
    ids = [g["S"], g["R"], g["U"], g["D"]]
    s_changed = bit(g["s_name"], [P(), P(execute="cat /etc/issue")])[0]
    put(bits, "s.bit", s_changed)  # changed before discover: would be v2
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    put(evil, "s.bit", s_changed)
    put(evil, f"uploaded/policy-{g['U']}.bit", bit(f"GZ {tag()}")[0])
    evil_tree = tree(evil)
    frozen = _frozen(server, ids)
    real = folders.discover

    def hook(bits_dir: Path) -> list[str]:
        found = real(bits_dir)
        assert "s.bit" in found
        _break(bits, "missing", tmp_path / "bits-real")
        if how == "symlink":
            os.symlink(evil, bits)
        return found

    monkeypatch.setattr(folders, "discover", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert imports_since(server, s) == []
    assert audits_since(server, s) == [] and counter_delta(s) == {}
    assert catalog_now(server) == s.catalog
    assert res.unreadable_folders == BOTH
    _assert_guard_log(caplog, BOTH, tmp_path)
    assert (res.outcomes, res.deleted, res.strays, res.renamed) == ((),) * 4
    assert _frozen(server, ids) == frozen
    assert tree(evil) == evil_tree


def test_a_file_is_read_through_its_folder_handle_not_its_path(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bits folder is swapped for a link right after read_input opens its
    folder handle: the file comes from the real folder, never the link."""
    g = _guard_setup(server, db, bits)
    (bits / "r.bit").unlink()
    s_before = policy_row(server, g["S"])
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    put(evil, "s.bit", bit(g["s_name"], [P(), P(execute="cat /etc/issue")])[0])
    evil_tree = tree(evil)
    real_open = folders._open_folder
    real_read = folders.read_input
    armed: list[bool] = []

    def open_hook(bits_dir: Path, label: str) -> int:
        fd = real_open(bits_dir, label)
        if armed == [True]:
            armed.append(False)
            bits.rename(tmp_path / "bits-real")
            os.symlink(evil, bits)
        return fd

    def read_hook(bits_dir: Path, rel: str) -> FileInput | None:
        if rel == "s.bit" and not armed:
            armed.append(True)
        return real_read(bits_dir, rel)

    monkeypatch.setattr(folders, "_open_folder", open_hook)
    monkeypatch.setattr(folders, "read_input", read_hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert armed == [True, False]
    rows = imports_since(server, s)
    assert [r for r in rows if r["outcome"] == "success"] == []
    assert ("s.bit", "skipped") in rows_by_file(rows)
    after = policy_row(server, g["S"])
    assert (after["version"], after["source_sha256"], after["deleted_at"]) == (
        s_before["version"],
        s_before["source_sha256"],
        None,
    )
    assert res.unreadable_folders == BOTH
    assert res.deleted == ()
    assert policy_row(server, g["R"])["deleted_at"] is None
    assert tree(evil) == evil_tree


def test_present_and_read_input_never_resolve_a_symlinked_bits_folder(
    tmp_path: Path, bits: Path
) -> None:
    data = bit()[0]
    put(bits, "a.bit", data)
    put(bits, "uploaded/policy-1.bit", data)
    real = tmp_path / "real"
    bits.rename(real)
    os.symlink(real, bits)
    for rel in ["a.bit", "uploaded/policy-1.bit"]:
        assert folders.present(bits, rel) is False, rel
        assert folders.read_input(bits, rel) is None, rel
    # The same files through the real folder are found.
    for rel in ["a.bit", "uploaded/policy-1.bit"]:
        assert folders.present(real, rel) is True, rel
        got = folders.read_input(real, rel)
        assert got is not None and got.data == data
    # A symlinked uploaded/ inside a real bits folder: the same.
    os.unlink(bits)
    os.mkdir(bits)
    os.symlink(real / "uploaded", bits / "uploaded")
    assert folders.present(bits, "uploaded/policy-1.bit") is False
    assert folders.read_input(bits, "uploaded/policy-1.bit") is None


def test_a_stat_error_other_than_not_found_is_unreadable_not_absent(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a missing name is "absent"; any other stat failure (EACCES, EIO)
    leaves the policy alone and reports its folder."""
    g = _guard_setup(server, db, bits)
    name = f"policy-{g['U']}.bit"
    (bits / "uploaded" / name).unlink()  # would be deleted if "absent"
    real_stat = os.stat

    def stat_hook(path: Any, *a: Any, **kw: Any) -> os.stat_result:
        if path == name and kw.get("dir_fd") is not None:
            raise PermissionError(13, "Permission denied")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", stat_hook)
    assert folders.present(bits, f"uploaded/{name}") is False
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert res.deleted == ()
    assert policy_row(server, g["U"])["deleted_at"] is None
    assert _deletes_of(audits_since(server, s)) == []
    assert res.unreadable_folders == ("uploaded/",)
    assert len(_guard_lines(caplog)) == 1


@pytest.mark.parametrize("how", BREAKS)
@pytest.mark.parametrize("folder", ["uploaded", "bits"])
def test_an_unreadable_folder_with_no_policy_in_it_is_still_reported(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    folder: str,
    how: str,
) -> None:
    """The #103 report does not depend on the folder holding a live policy:
    with an empty catalog, the start-of-reconcile check alone reports it."""
    assert live_count(server) == 0
    put(bits, "n.bit", bit(f"GN {tag()}")[0])
    path = bits / "uploaded" if folder == "uploaded" else bits
    _break(path, how, tmp_path / "real")
    labels = ("uploaded/",) if folder == "uploaded" else BOTH
    for _ in range(2):
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        res = rec(db, bits)
        assert res.unreadable_folders == labels
        _assert_guard_log(caplog, labels, tmp_path)
    expect = 1 if folder == "uploaded" else 0  # n.bit imported only then
    assert live_count(server) == expect


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_a_folder_swapped_after_discover_is_reported_by_the_read(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """No live policy anywhere, so only the failed read can report the
    folder: a new server file is discovered, then the bits folder goes."""
    assert live_count(server) == 0
    put(bits, "n.bit", bit(f"GN {tag()}")[0])
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    put(evil, "n.bit", bit(f"GE {tag()}")[0])
    evil_tree = tree(evil)
    real = folders.discover

    def hook(bits_dir: Path) -> list[str]:
        found = real(bits_dir)
        assert found == ["n.bit"]
        _break(bits, "missing", tmp_path / "bits-real")
        if how == "symlink":
            os.symlink(evil, bits)
        return found

    monkeypatch.setattr(folders, "discover", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert imports_since(server, s) == [] and live_count(server) == 0
    assert res.unreadable_folders == BOTH
    _assert_guard_log(caplog, BOTH, tmp_path)
    assert tree(evil) == evil_tree


# ----------------------------------------------------------------------------
# TASK-156 revision 4 (r3 TEST findings 1 and 2; decisions "TASK-156 r3 TEST
# PASS ... revision 4"): an unreadable folder logs only the guard line, never
# a line per file; a leftover is reported removed only once it is confirmed
# gone through the no-follow folder handle, otherwise uploaded/ is marked
# unreadable and the next reconcile retries it.
# ----------------------------------------------------------------------------


def _module_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("how", ["missing", "symlink"])
@pytest.mark.parametrize("folder", ["uploaded", "bits"])
def test_a_folder_swapped_after_discover_logs_only_the_guard_line(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    folder: str,
    how: str,
) -> None:
    """Three changed live uploads and three changed server files: each would
    reach read_input, and none may log a line of its own."""
    ups, names = [], []
    for i in range(3):
        name = f"LS {tag()}"
        data, ids = bit(name)
        put(bits, f"k{i}.bit", data)
        names.append((f"k{i}.bit", name, ids))
        uname = f"LU {tag()}"
        udata, uids = bit(uname)
        up = upload(db, bits, udata)
        ups.append((int(up.policy_id or 0), uname, uids))
    rec(db, bits)
    for rel, name, ids in names:
        put(bits, rel, bit(name, [P(uuid=ids[0], execute="cat /etc/issue")])[0])
    for pid, uname, uids in ups:
        changed = bit(uname, [P(uuid=uids[0], execute="cat /etc/issue")])[0]
        put(bits, f"uploaded/policy-{pid}.bit", changed)
    every = [p for p, _, _ in ups]
    with owner(server) as c:
        every += [
            int(r[0])
            for r in c.execute(
                "SELECT policy_id FROM policy WHERE deleted_at IS NULL"
                " AND source_file LIKE 'k%%.bit'"
            ).fetchall()
        ]
    assert len(every) == 6
    frozen = _frozen(server, every)
    path = bits / "uploaded" if folder == "uploaded" else bits
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    real = folders.discover

    def hook(bits_dir: Path) -> list[str]:
        found = real(bits_dir)
        assert len(found) == 6
        _break(path, "missing", tmp_path / "real")
        if how == "symlink":
            os.symlink(evil / "uploaded" if folder == "uploaded" else evil, path)
        return found

    monkeypatch.setattr(folders, "discover", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    labels = ("uploaded/",) if folder == "uploaded" else BOTH
    assert res.unreadable_folders == labels
    assert sorted(_module_warnings(caplog)) == sorted(_guard_lines(caplog))
    _assert_guard_log(caplog, labels, tmp_path)
    assert not [m for m in _module_warnings(caplog) if "not read" in m]
    assert res.deleted == ()
    rows = imports_since(server, s)
    if folder == "uploaded":  # the server folder is still reconciled
        assert sorted(rows_by_file(rows)) == [
            (f"k{i}.bit", "success") for i in range(3)
        ]
        assert _frozen(server, every[:3]) == {p: frozen[p] for p in every[:3]}
    else:
        assert rows == []
        assert _frozen(server, every) == frozen


def test_a_read_error_inside_a_readable_folder_still_logs_its_type(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = _guard_setup(server, db, bits)
    s_before = policy_row(server, g["S"])
    real_open = os.open

    def open_hook(path: Any, flags: int, *a: Any, **kw: Any) -> int:
        if path == "s.bit" and kw.get("dir_fd") is not None:
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(os, "open", open_hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    assert _module_warnings(caplog) == ["folder file not read: PermissionError"]
    assert res.unreadable_folders == () and res.deleted == ()
    assert "s.bit" not in [r["file_name"] for r in imports_since(server, s)]
    assert policy_row(server, g["S"]) == s_before


def _leftover_case(
    server: PgServer, db: AppDatabase, bits: Path
) -> tuple[dict[str, Any], dict[int, Any]]:
    g = _guard_setup(server, db, bits)
    put(bits, g["d_rel"], g["d_bytes"])  # the crash window
    return g, _frozen(server, [g["S"], g["R"], g["U"], g["D"]])


@pytest.mark.parametrize(
    "how", ["missing", "symlink-with-copy", "symlink-empty", "bits-symlink-with-copy"]
)
def test_a_leftover_whose_folder_is_swapped_after_discover_is_not_reported_removed(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g, frozen = _leftover_case(server, db, bits)
    d_name = g["d_rel"].removeprefix("uploaded/")
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    if how.endswith("with-copy"):  # a link target that holds the same file
        put(evil, g["d_rel"], g["d_bytes"])
        put(evil, f"uploaded/policy-{g['U']}.bit", b"copy of U")
        put(evil, "s.bit", b"copy of S")
        put(evil, "r.bit", b"copy of R")
    evil_tree = tree(evil)
    real = folders.discover

    def hook(bits_dir: Path) -> list[str]:
        found = real(bits_dir)
        assert g["d_rel"] in found
        if how == "bits-symlink-with-copy":
            _break(bits, "missing", tmp_path / "bits-real")
            os.symlink(evil, bits)
        else:
            _break(bits / "uploaded", "missing", tmp_path / "uploaded-real")
            if how != "missing":
                os.symlink(evil / "uploaded", bits / "uploaded")
        return found

    monkeypatch.setattr(folders, "discover", hook)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec(db, bits)
    labels = BOTH if how.startswith("bits") else ("uploaded/",)
    assert res.leftovers == ()
    assert res.unreadable_folders == labels
    _assert_guard_log(caplog, labels, tmp_path)
    assert not [m for m in _module_warnings(caplog) if "removed a leftover" in m]
    assert _frozen(server, [g["S"], g["R"], g["U"], g["D"]]) == frozen
    assert audits_since(server, s) == [] and res.deleted == ()
    assert tree(evil) == evil_tree  # nothing removed through the link
    real_dir = tmp_path / (
        "bits-real/uploaded" if how.startswith("bits") else "uploaded-real"
    )
    assert (real_dir / d_name).read_bytes() == g["d_bytes"]


@pytest.mark.parametrize("fail", ["no-op", "unlink-raises"])
def test_a_leftover_that_cannot_be_removed_is_retried_and_reported_once_gone(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    fail: str,
) -> None:
    g, frozen = _leftover_case(server, db, bits)
    d_name = g["d_rel"].removeprefix("uploaded/")
    (bits / f"uploaded/policy-{g['U']}.bit").unlink()  # U's file removed by hand
    with monkeypatch.context() as m:
        if fail == "no-op":
            m.setattr(folders, "remove_after_commit", lambda bits_dir, paths: None)
        else:
            real_unlink = os.unlink

            def unlink_hook(path: Any, *a: Any, **kw: Any) -> None:
                if path == d_name and kw.get("dir_fd") is not None:
                    raise PermissionError(13, "Permission denied")
                real_unlink(path, *a, **kw)

            m.setattr(os, "unlink", unlink_hook)
        for _ in range(2):  # retried, still refused: no churn
            caplog.clear()
            caplog.set_level(logging.DEBUG)
            s = snap(server)
            res = rec(db, bits)
            assert res.leftovers == ()
            assert res.unreadable_folders == ("uploaded/",)
            _assert_guard_log(caplog, ("uploaded/",), tmp_path)
            assert not [
                w for w in _module_warnings(caplog) if "removed a leftover" in w
            ]
            assert (bits / g["d_rel"]).read_bytes() == g["d_bytes"]
            assert policy_row(server, g["D"]) == frozen[g["D"]][0]
            assert [
                r for r in imports_since(server, s) if r["file_name"] == g["d_rel"]
            ] == []
        # The folder is real: the mark only reports, U's removed file still
        # deleted its policy (once, in the first run).
        assert policy_row(server, g["U"])["deleted_at"] == T1
    caplog.clear()
    res = rec(db, bits)
    assert res.leftovers == (Difference(g["d_rel"], folders.LEFTOVER_CHECK),)
    assert res.unreadable_folders == ()
    assert not (bits / g["d_rel"]).exists()
    assert len([w for w in _module_warnings(caplog) if "removed a leftover" in w]) == 1
    assert policy_row(server, g["D"])["deleted_at"] is not None
    assert rec(db, bits).leftovers == ()


def test_remove_leftover_returns_a_difference_only_when_the_file_is_gone(
    tmp_path: Path, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel = "uploaded/policy-7.bit"
    put(bits, rel, b"x")
    assert folders.remove_leftover(bits, rel) == Difference(rel, folders.LEFTOVER_CHECK)
    assert not (bits / rel).exists()
    put(bits, rel, b"x")
    with monkeypatch.context() as m:
        m.setattr(folders, "remove_after_commit", lambda bits_dir, paths: None)
        assert folders.remove_leftover(bits, rel) is None
    assert (bits / rel).read_bytes() == b"x"
    (bits / "uploaded").rename(tmp_path / "real")
    os.symlink(tmp_path / "real", bits / "uploaded")
    assert folders.remove_leftover(bits, rel) is None
    assert (tmp_path / "real" / "policy-7.bit").read_bytes() == b"x"
    os.unlink(bits / "uploaded")
    assert folders.remove_leftover(bits, rel) is None  # folder missing


def test_a_bits_folder_swapped_before_an_upload_copy_is_removed_is_not_followed(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U's file is removed by hand, so U is deleted. Right after its
    delete_in_tx, the bits folder becomes a link to a folder holding a file of
    the same name: the copy removal must not reach it through the link."""
    g = _guard_setup(server, db, bits)
    u_rel = f"uploaded/policy-{g['U']}.bit"
    (bits / u_rel).unlink()
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    put(evil, u_rel, b"not the manager's file")
    evil_tree = tree(evil)
    real = dl.delete_in_tx

    def hook(tx: Any, policy_id: int, **kw: Any) -> Any:
        out = real(tx, policy_id, **kw)
        if policy_id == g["U"]:
            _break(bits, "missing", tmp_path / "bits-real")
            os.symlink(evil, bits)
        return out

    monkeypatch.setattr(folders, "delete_in_tx", hook)
    res = rec(db, bits)
    assert [d.policy_id for d in res.deleted] == [g["U"]]
    assert res.unreadable_folders == BOTH
    assert tree(evil) == evil_tree


def test_req159_3_move_does_not_remove_the_copy_through_a_swapped_bits_folder(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-159 (3): a server file takes an uploaded policy's name, so the
    policy moves and its uploaded copy is removed after commit. The bits
    folder becomes a link just before that removal: the file of the same name
    in the link target must stay, and the real copy is left in place."""
    name = f"Uploaded {tag()}"
    data = bit(name)[0]
    up = upload(db, bits, data)
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    put(bits, "x.bit", data)
    evil = tmp_path / "evil"
    (evil / "uploaded").mkdir(parents=True)
    put(evil, rel, b"not the manager's file")
    evil_tree = tree(evil)
    real = dl.remove_after_commit
    calls: list[tuple[str, ...]] = []

    def hook(bits_dir: Path, paths: Any) -> None:
        calls.append(tuple(paths))
        if rel in paths and not os.path.islink(bits):
            _break(bits, "missing", tmp_path / "bits-real")
            os.symlink(evil, bits)
        real(bits_dir, paths)

    monkeypatch.setattr(pipeline, "remove_after_commit", hook)
    s = snap(server)
    res = rec(db, bits)
    assert (rel,) in calls  # the move's removal was reached
    row = policy_row(server, pid)
    assert (row["source_file"], row["deleted_at"]) == ("x.bit", None)
    assert actions(audits_since(server, s)) == ["policy.import", "policy.move"]
    assert tree(evil) == evil_tree  # nothing removed through the link
    assert (tmp_path / "bits-real" / rel).read_bytes() == data  # left in place
    assert res.unreadable_folders == BOTH
    assert res.deleted == ()


# ----------------------------------------------------------------------------
# TASK-156 revision 5 (user, decisions 2026-10-28 "One-file reconcile"; lead
# "W6 rulings" Q2): reconcile_paths runs the reconcile's classification,
# folder guard, #15 order and per-row check for only the given paths; deletes
# only for given files that disappeared; nothing else is touched. state() is
# public.
# ----------------------------------------------------------------------------


def rec_paths(db: AppDatabase, bits: Path, paths: Any) -> folders.ReconcileResult:
    with db.session() as s, catalog_lock(s):
        return folders.reconcile_paths(s, FixedClock(), bits, paths)


EMPTY = folders.ReconcileResult((), (), (), (), (), ())


def test_reconcile_paths_touches_only_the_given_server_files(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    names = {k: f"RP{k} {tag()}" for k in "abcoq"}
    datas = {k: bit(names[k]) for k in names}
    for k, (data, _) in datas.items():
        put(bits, f"{k}.bit", data)
    rec(db, bits)
    pid = {}
    for k in names:
        p = policy_by_name(server, names[k])
        assert p is not None
        pid[k] = int(p["policy_id"])
    for k in "bo":  # changed
        ids = datas[k][1]
        put(
            bits,
            f"{k}.bit",
            bit(names[k], [P(uuid=ids[0], execute="cat /etc/issue")])[0],
        )
    for k in "cq":  # removed
        (bits / f"{k}.bit").unlink()
    n_name = f"RPn {tag()}"
    put(bits, "n.bit", bit(n_name)[0])
    put(bits, "m.bit", bit(f"RPm {tag()}")[0])  # new, not in the batch
    o_before = policy_row(server, pid["o"])
    s = snap(server)
    res = rec_paths(db, bits, ["a.bit", "b.bit", "c.bit", "n.bit"])
    rows = imports_since(server, s)
    assert sorted(rows_by_file(rows)) == [
        ("a.bit", "skipped"),
        ("b.bit", "success"),
        ("n.bit", "success"),
    ]
    assert [d.policy_id for d in res.deleted] == [pid["c"]]
    assert policy_row(server, pid["c"])["deleted_at"] == T1
    assert policy_row(server, pid["q"])["deleted_at"] is None  # not in the batch
    assert policy_row(server, pid["o"]) == o_before  # changed, not in the batch
    assert policy_row(server, pid["b"])["version"] == 2
    assert sorted(actions(audits_since(server, s))) == [
        "policy.delete",
        "policy.import",
        "policy.import",
    ]
    assert res.unreadable_folders == () and res.strays == () and res.leftovers == ()
    # The full reconcile then picks up what the batch left.
    s2 = snap(server)
    res2 = rec(db, bits)
    assert [d.policy_id for d in res2.deleted] == [pid["q"]]
    assert ("o.bit", "success") in rows_by_file(imports_since(server, s2))
    assert ("m.bit", "success") in rows_by_file(imports_since(server, s2))


@pytest.mark.parametrize(
    ("first", "second"), [("a.bit", "b.bit"), ("B.bit", "a.bit"), ("z.bit", "é.bit")]
)
def test_reconcile_paths_follows_15_within_a_batch(
    server: PgServer, db: AppDatabase, bits: Path, first: str, second: str
) -> None:
    name = f"Twin {tag()}"
    put(bits, second, bit(name, [P(execute="cat /etc/issue")])[0])
    put(bits, first, bit(name)[0])
    s = snap(server)
    rec_paths(db, bits, [second, first])
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [(first, "success"), (second, "rejected")]
    assert codes(rows[1]["errors"]) == ["BIT007"]


def test_reconcile_paths_puts_a_live_policys_file_first(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    x, y = f"X {tag()}", f"Y {tag()}"
    put(bits, "z.bit", bit(x)[0])
    rec(db, bits)
    old = policy_by_name(server, x)
    assert old is not None
    put(bits, "z.bit", bit(y)[0])
    put(bits, "a.bit", bit(x)[0])
    s = snap(server)
    rec_paths(db, bits, ["a.bit", "z.bit"])
    assert rows_by_file(imports_since(server, s)) == [
        ("z.bit", "success"),
        ("a.bit", "success"),
    ]
    assert policy_row(server, int(old["policy_id"]))["policy_name"] == y


@pytest.mark.parametrize("order", ["upload-first", "server-first"])
def test_reconcile_paths_server_file_wins_over_an_upload_in_a_batch(
    server: PgServer, db: AppDatabase, bits: Path, order: str
) -> None:
    name = f"Uploaded {tag()}"
    data = bit(name)[0]
    up = upload(db, bits, data)
    pid = int(up.policy_id or 0)
    rel = f"uploaded/policy-{pid}.bit"
    put(bits, "x.bit", data)
    batch = [rel, "x.bit"] if order == "upload-first" else ["x.bit", rel]
    s = snap(server)
    res = rec_paths(db, bits, batch)
    assert rows_by_file(imports_since(server, s)) == [("x.bit", "success")]
    row = policy_row(server, pid)
    assert (row["source_file"], row["deleted_at"]) == ("x.bit", None)
    assert not (bits / rel).exists()
    assert actions(audits_since(server, s)) == ["policy.import", "policy.move"]
    assert res.strays == () and res.deleted == () and res.leftovers == ()


@pytest.mark.parametrize("given", ["both", "new-only", "old-only"])
def test_reconcile_paths_rename_of_a_server_file(
    server: PgServer, db: AppDatabase, bits: Path, given: str
) -> None:
    name = f"Ren {tag()}"
    put(bits, "a.bit", bit(name)[0])
    rec(db, bits)
    p = policy_by_name(server, name)
    assert p is not None
    pid = int(p["policy_id"])
    (bits / "a.bit").rename(bits / "c.bit")
    batch = {"both": ["a.bit", "c.bit"], "new-only": ["c.bit"], "old-only": ["a.bit"]}
    s = snap(server)
    res = rec_paths(db, bits, batch[given])
    row = policy_row(server, pid)
    if given == "old-only":  # a.bit disappeared; c.bit was not given
        assert [d.policy_id for d in res.deleted] == [pid]
        assert row["deleted_at"] == T1
        assert imports_since(server, s) == []
    else:
        assert res.deleted == ()
        assert (row["source_file"], row["deleted_at"]) == ("c.bit", None)
        assert rows_by_file(imports_since(server, s)) == [("c.bit", "success")]
        assert actions(audits_since(server, s)) == ["policy.import", "policy.move"]


def test_reconcile_paths_uploaded_files_are_classified_as_in_reconcile(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    ch_name = f"Ch {tag()}"
    ch_data, ch_ids = bit(ch_name)
    ch = upload(db, bits, ch_data)
    same = upload(db, bits, bit(f"Same {tag()}")[0])
    ed = upload(db, bits, bit(f"Ed {tag()}")[0])
    ch_rel = f"uploaded/policy-{ch.policy_id}.bit"
    same_rel = f"uploaded/policy-{same.policy_id}.bit"
    ed_rel = f"uploaded/policy-{ed.policy_id}.bit"
    rec(db, bits)
    put(bits, ch_rel, bit(ch_name, [P(uuid=ch_ids[0], execute="cat /etc/issue")])[0])
    put(bits, ed_rel, bit(f"Edited {tag()}")[0])
    put(bits, "uploaded/stray.bit", bit(f"Stray {tag()}")[0])
    d_id = _leftover(db, bits)
    d_rel = f"uploaded/policy-{d_id}.bit"
    ed_before = policy_row(server, int(ed.policy_id or 0))
    s = snap(server)
    res = rec_paths(db, bits, [ch_rel, same_rel, ed_rel, "uploaded/stray.bit", d_rel])
    assert sorted(rows_by_file(imports_since(server, s))) == sorted(
        [(ch_rel, "success"), (same_rel, "skipped")]
    )
    assert res.renamed == (ed_rel,)
    assert res.strays == ("uploaded/stray.bit",)
    assert res.leftovers == (Difference(d_rel, folders.LEFTOVER_CHECK),)
    assert not (bits / d_rel).exists()
    assert policy_row(server, int(ed.policy_id or 0)) == ed_before
    assert res.deleted == () and res.unreadable_folders == ()


def test_reconcile_paths_a_leftover_that_cannot_be_removed_marks_uploaded(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d_id = _leftover(db, bits)
    d_rel = f"uploaded/policy-{d_id}.bit"
    monkeypatch.setattr(folders, "remove_after_commit", lambda bits_dir, paths: None)
    res = rec_paths(db, bits, [d_rel])
    assert res.leftovers == () and res.unreadable_folders == ("uploaded/",)
    assert (bits / d_rel).exists()


@pytest.mark.parametrize("how", BREAKS)
@pytest.mark.parametrize("folder", ["uploaded", "bits"])
def test_reconcile_paths_folder_guard(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    folder: str,
    how: str,
) -> None:
    g = _guard_setup(server, db, bits)
    u_rel = f"uploaded/policy-{g['U']}.bit"
    (bits / "r.bit").unlink()
    n_name = f"GN {tag()}"
    put(bits, "n.bit", bit(n_name)[0])
    path = bits / "uploaded" if folder == "uploaded" else bits
    away = tmp_path / "real"
    _break(path, how, away)
    if folder == "uploaded":  # U's file gone in the real folder too
        (away / f"policy-{g['U']}.bit").unlink()
    away_tree = tree(away)
    frozen = _frozen(server, [g["U"], g["D"]] + ([g["S"]] if folder == "bits" else []))
    reads: list[str] = []
    real_read = folders.read_input

    def spy(bits_dir: Path, r: str) -> FileInput | None:
        reads.append(r)
        return real_read(bits_dir, r)

    monkeypatch.setattr(folders, "read_input", spy)
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec_paths(db, bits, [u_rel, g["d_rel"], "r.bit", "n.bit", "s.bit"])
    labels = ("uploaded/",) if folder == "uploaded" else BOTH
    assert res.unreadable_folders == labels
    _assert_guard_log(caplog, labels, tmp_path)
    assert [r for r in reads if r.startswith("uploaded/")] == []
    assert res.leftovers == () and res.strays == ()
    assert tree(away) == away_tree
    rows = imports_since(server, s)
    if folder == "uploaded":  # the server folder is reconciled for its paths
        assert sorted(rows_by_file(rows)) == [
            ("n.bit", "success"),
            ("s.bit", "skipped"),
        ]
        assert [d.policy_id for d in res.deleted] == [g["R"]]
        assert _frozen(server, [g["U"], g["D"]]) == frozen
    else:
        assert rows == [] and res.deleted == () and reads == []
        assert _frozen(server, [g["U"], g["D"], g["S"]]) == frozen
        assert policy_row(server, g["R"])["deleted_at"] is None


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_reconcile_paths_folder_broken_after_the_first_delete(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    g = _many(server, db, bits, 3)
    ups = g["uploads"]
    rels = [f"uploaded/policy-{p}.bit" for p in ups]
    for rel in rels:
        (bits / rel).unlink()
    target = tmp_path / "empty-target"
    target.mkdir()
    real = dl.delete_in_tx
    calls: list[int] = []

    def hook(tx: Any, policy_id: int, **kw: Any) -> Any:
        out = real(tx, policy_id, **kw)
        calls.append(policy_id)
        if len(calls) == 1:
            _break(bits / "uploaded", "missing", tmp_path / "uploaded-real")
            if how == "symlink":
                os.symlink(target, bits / "uploaded")
        return out

    monkeypatch.setattr(folders, "delete_in_tx", hook)
    res = rec_paths(db, bits, rels)
    assert len(calls) == 1 and [d.policy_id for d in res.deleted] == calls
    for pid in ups:
        assert (policy_row(server, pid)["deleted_at"] is None) == (pid != calls[0])
    assert res.unreadable_folders == ("uploaded/",)


def test_reconcile_paths_ignores_paths_that_are_not_folder_files(
    server: PgServer,
    db: AppDatabase,
    tmp_path: Path,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each hostile path names an existing regular .bit file somewhere (so a
    lookup by basename or by full path would find one)."""
    good = bit(f"H {tag()}")[0]
    put(bits, "x.bit", good)
    (bits / "sub").mkdir()
    put(bits, "sub/x.bit", bit(f"Hs {tag()}")[0])
    (bits / "uploaded" / "sub").mkdir()
    put(bits, "uploaded/sub/policy-1.bit", bit(f"Hu {tag()}")[0])
    put(bits, ".hidden.bit", bit(f"Hh {tag()}")[0])
    put(bits, "x.txt", bit(f"Ht {tag()}")[0])
    put(tmp_path, "x.bit", bit(f"Ho {tag()}")[0])
    os.symlink(bits / "x.bit", bits / "l.bit")
    os.mkfifo(bits / "f.bit")
    before = tree(tmp_path)
    hostile = [
        "sub/x.bit",
        "../x.bit",
        str(bits / "x.bit"),
        str(tmp_path / "x.bit"),
        "/x.bit",
        "./x.bit",
        "x.bit/",
        "x.txt",
        ".hidden.bit",
        "nope.bit",
        "uploaded/sub/policy-1.bit",
        "uploaded/../x.bit",
        "uploaded/policy-1.bit",
        "l.bit",
        "f.bit",
        "",
        "uploaded/",
        "deleted/1",
    ]
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    res = rec_paths(db, bits, hostile)
    assert res == EMPTY
    assert imports_since(server, s) == [] and audits_since(server, s) == []
    assert catalog_now(server) == s.catalog
    assert tree(tmp_path) == before
    assert _module_warnings(caplog) == []


def test_reconcile_paths_deduplicates_and_accepts_any_iterable(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Dup {tag()}"
    put(bits, "n.bit", bit(name)[0])
    put(bits, "gone.bit", bit(f"Gone {tag()}")[0])
    rec(db, bits)
    p = policy_by_name(server, name)
    assert p is not None
    put(bits, "n.bit", bit(name, [P(), P()])[0])
    (bits / "gone.bit").unlink()
    s = snap(server)
    res = rec_paths(db, bits, (r for r in ["n.bit", "n.bit", "gone.bit", "gone.bit"]))
    assert rows_by_file(imports_since(server, s)) == [("n.bit", "success")]
    assert len(res.deleted) == 1 and res.deleted[0].source_file == "gone.bit"
    assert actions(audits_since(server, s)) == ["policy.import", "policy.delete"]


def test_reconcile_paths_empty_batch(
    server: PgServer, db: AppDatabase, tmp_path: Path, bits: Path
) -> None:
    g = _guard_setup(server, db, bits)
    (bits / "r.bit").unlink()
    put(bits, "n.bit", bit(f"N {tag()}")[0])
    s = snap(server)
    assert rec_paths(db, bits, []) == EMPTY
    assert imports_since(server, s) == [] and audits_since(server, s) == []
    assert policy_row(server, g["R"])["deleted_at"] is None
    _break(bits / "uploaded", "missing", tmp_path / "away")
    res = rec_paths(db, bits, [])
    assert res == folders.ReconcileResult((), (), (), (), (), ("uploaded/",))


def test_state_is_public_and_three_way(tmp_path: Path, bits: Path) -> None:
    assert folders._state is folders.state
    put(bits, "a.bit", bit()[0])
    put(bits, "uploaded/policy-1.bit", bit()[0])
    os.mkfifo(bits / "f.bit")
    os.symlink(bits / "a.bit", bits / "l.bit")
    assert folders.state(bits, "a.bit") == "present"
    assert folders.state(bits, "uploaded/policy-1.bit") == "present"
    for rel in ["gone.bit", "f.bit", "l.bit", "sub/a.bit", "../a.bit", "a.txt"]:
        assert folders.state(bits, rel) == "absent", rel
    (bits / "uploaded").rename(tmp_path / "up")
    os.symlink(tmp_path / "up", bits / "uploaded")
    assert folders.state(bits, "uploaded/policy-1.bit") == "unreadable"
    assert folders.state(bits, "a.bit") == "present"
    bits.rename(tmp_path / "b")
    os.symlink(tmp_path / "b", bits)
    assert folders.state(bits, "a.bit") == "unreadable"
