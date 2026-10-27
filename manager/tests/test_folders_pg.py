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
from bitscan_manager.services.importer import folders, pipeline, uploads
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
    assert res.refused == () and res.deleted == () and res.leftovers == ()
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
    assert res.strays == () and res.refused == ()
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
    assert res.refused == res.deleted == res.leftovers == res.strays == ()


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
    assert res.refused == res.deleted == res.leftovers == res.strays == ()


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
                res.refused,
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
    assert res.strays == () and res.refused == () and res.deleted == ()
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
    assert res.strays == () and res.deleted == () and res.refused == ()
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
    real_import = folders.import_one
    real_decide = pipeline.store_decide.decide

    def spy_import(*a: Any, **k: Any) -> ImportOutcome:
        seen.append(a[3])
        return real_import(*a, **k)

    def spy_decide(conn: Any, rules: Any, target: Target, exists: Any) -> Any:
        targets.append(target)
        return real_decide(conn, rules, target, exists)

    monkeypatch.setattr(folders, "import_one", spy_import)
    monkeypatch.setattr(pipeline.store_decide, "decide", spy_decide)
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
        assert res.deleted == () and res.refused == () and res.leftovers == ()
        stray_lines = [
            r for r in caplog.records if r.name == LOGGER and "skipped" in r.msg
        ]
        assert len(stray_lines) == 1
        for r in caplog.records:
            assert rel.removeprefix("uploaded/") not in r.getMessage()
    assert policy_row(server, sid)["source_file"] == "srv.bit"
    assert policy_row(server, lid)["source_file"] == f"uploaded/policy-{lid}.bit"


def test_a_live_upload_edited_to_a_server_policys_name_is_refused(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    sname = f"Server {tag()}"
    put(bits, "srv.bit", bit(sname)[0])
    u1 = upload(db, bits, bit(f"U1 {tag()}")[0])
    u2 = upload(db, bits, bit(f"U2 {tag()}")[0])
    rec(db, bits)
    rels = sorted(
        [f"uploaded/policy-{u1.policy_id}.bit", f"uploaded/policy-{u2.policy_id}.bit"],
        key=str.encode,
    )
    first, later = rels
    later_id = int(later.removeprefix("uploaded/policy-").removesuffix(".bit"))
    later_name = policy_row(server, later_id)["policy_name"]
    put(bits, first, bit(sname)[0])  # hand-edited to the server policy's name
    later_data = bit(later_name, [P(), P()])[0]
    put(bits, later, later_data)  # changed, after the refused one
    srv = policy_by_name(server, sname)
    assert srv is not None
    s = snap(server)
    res = rec(db, bits)
    assert res.refused == (first,)
    rows = imports_since(server, s)
    assert rows_by_file(rows) == [("srv.bit", "skipped"), (later, "success")]
    entries = audits_since(server, s)
    assert actions(entries) == ["policy.import_refused", "policy.import"]
    assert entries[0]["target"] == f"policy:{srv['policy_id']}"
    assert entries[0]["detail"].get("mode") == "auto"
    assert policy_by_name(server, sname) == srv
    assert policy_row(server, later_id)["source_sha256"] == sha(later_data)
    assert (bits / first).exists()
    assert res.deleted == ()


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
    real_import = folders.import_one

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
