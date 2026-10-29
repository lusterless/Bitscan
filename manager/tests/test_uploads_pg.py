"""TP-M7-15 (TASK-155): uploads and the start-up finish of interrupted ones,
on PostgreSQL with a temporary bits folder (Linux only: symlinks, FIFOs,
modes, O_NOFOLLOW).

CHK-M7-200 to -204 and the REQ-165 (1) part of CHK-M7-230 (tests/m7/
test-plan.md). Expected values come from the spec and the approved answers,
not from the code: TS §4.1 L522 (the client name is ignored; the file is kept
only if the import succeeds, as `uploaded/policy-<policy_id>.bit`; it is
written to `uploaded/.tmp-<policy_id>-<sha256>` opened with `O_NOFOLLOW |
O_EXCL` before the transaction commits and renamed after; a rejected upload
leaves the file and catalog untouched; 409 for a server-folder policy), L526
(the lock is held until the rename), L528 (start-up: a temp whose hash equals
the policy's `source_sha256` is renamed, every other temp deleted), §8.7
L1377 (`UMask=0077`); REQ-163 (1) to (6), REQ-165 (1); #98 (j) (a disk error
is not a rejection: no row), #99 (d), (e); the crash-window ruling
(2026-10-27: a deleted policy never comes back by itself).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import uploads
from bitscan_manager.services.importer.pipeline import Actor, ImportOutcome
from bitscan_manager.services.importer.pipeline import import_one as real_import_one
from bitscan_manager.services.importer.store import PolicyManagedOnServer
from bitscan_manager.services.importer.uploads import (
    FinishResult,
    UploadStage,
    client_file_name,
    finish_interrupted,
    staged_upload,
)

from .catalog_rows import T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, counters, delta, doc, make_env, plug

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(os.name != "posix", reason="Linux file semantics (W only)"),
]

ADMIN = Actor("user:11", 11)
FIVE_MIB = 5 * 1024 * 1024
REAL_OPEN = os.open
REAL_REPLACE = os.replace
# POSIX only (the module is skipped elsewhere); getattr keeps mypy on Windows.
O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK: int = getattr(os, "O_NONBLOCK", 0)


def MKFIFO(path: Path) -> None:  # noqa: N802 - os.mkfifo
    getattr(os, "mkfifo")(path)  # noqa: B009


def GETUID() -> int:  # noqa: N802
    return int(getattr(os, "getuid")())  # noqa: B009


def GETGID() -> int:  # noqa: N802
    return int(getattr(os, "getgid")())  # noqa: B009


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("uploads")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    for e in make_env(server, tmp_path):
        os.chmod(e.bits / "uploaded", 0o750)  # noqa: S103 - TS L1344
        yield e


def up(e: Env, data: bytes, name: bytes | str | None = b"p.bit") -> ImportOutcome:
    return uploads.upload(e.db, e.clock, e.bits, data, name, ADMIN)


def uploaded(e: Env) -> Path:
    return e.bits / "uploaded"


def final(e: Env, pid: int | None) -> Path:
    assert pid is not None
    return uploaded(e) / f"policy-{pid}.bit"


def temp(e: Env, pid: int | None, data: bytes) -> Path:
    return uploaded(e) / f".tmp-{pid}-{sha(data)}"


def tree(root: Path) -> dict[str, tuple[str, str]]:
    """Every entry under root (symlinks not followed): kind and content."""
    out: dict[str, tuple[str, str]] = {}
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        for n in dirs + files:
            p = Path(dirpath) / n
            st = p.lstat()
            rel = p.relative_to(root).as_posix()
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(p))
            elif stat.S_ISREG(st.st_mode):
                out[rel] = ("file", sha(p.read_bytes()))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir", "")
            else:
                out[rel] = ("other", stat.filemode(st.st_mode))
    return out


def snapshot(e: Env) -> tuple[Any, ...]:
    return e.catalog(), e.last_import(), e.mark(), counters()


def unchanged(e: Env, snap: tuple[Any, ...]) -> None:
    cat0, i0, m0, c0 = snap
    assert e.catalog() == cat0
    assert e.imports_after(i0) == [] and e.entries(m0) == []
    assert delta(c0) == {}


def finish(e: Env) -> FinishResult:
    with e.db.session() as s, catalog_lock(s):
        return finish_interrupted(s, e.bits)


def in_thread(
    fn: Callable[[], Any],
    seconds: float = 20.0,
    unblock: Callable[[], None] | None = None,
) -> Any:
    """Run fn; fail (not hang) if it blocks, e.g. on a FIFO. `unblock` lets a
    blocked writer finish, so it releases the catalog lock it holds."""
    out: dict[str, Any] = {}

    def run() -> None:
        try:
            out["v"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            out["e"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive() and unblock is not None:
        unblock()
        t.join(seconds)
        pytest.fail("blocked until unblocked")
    assert not t.is_alive(), "blocked"
    if "e" in out:
        raise out["e"]
    return out.get("v")


def new_policy(e: Env, **kw: Any) -> tuple[bytes, ImportOutcome]:
    data = doc(f"Up {tag()}", [plug()], **kw)
    out = up(e, data)
    assert out.outcome == "success", out.findings
    return data, out


def leave_temp(
    e: Env, monkeypatch: pytest.MonkeyPatch, data: bytes, name: bytes = b"r.bit"
) -> ImportOutcome:
    """An upload whose rename fails after the commit (the temp is left)."""
    seen: dict[str, ImportOutcome] = {}
    real_after = real_import_one

    def spy(*a: Any, **k: Any) -> ImportOutcome:
        inner = k["after_commit"]

        def after(o: ImportOutcome) -> None:
            seen["o"] = o
            inner(o)

        k["after_commit"] = after
        return real_after(*a, **k)

    def broken(src: Any, dst: Any) -> None:
        raise OSError("rename failed")

    with monkeypatch.context() as mp:
        mp.setattr(uploads, "import_one", spy)
        mp.setattr(os, "replace", broken)
        with pytest.raises(OSError, match="rename failed"):
            up(e, data, name)
    return seen["o"]


# CHK-M7-200: REQ-163 (1) hostile client names ------------------------------------

REPL = "�"
HOSTILE: list[tuple[bytes | str | None, str]] = [
    (b"../../etc/passwd", "../../etc/passwd"),
    (b"/abs.bit", "/abs.bit"),
    (b"a/b.bit", "a/b.bit"),
    (b"..", ".."),
    (b"n" * 5000, "n" * 255),
    (b"a\x00b.bit", f"a{REPL}b.bit"),
    (b"a\rb\nc.bit", f"a{REPL}b{REPL}c.bit"),
    (b"t\tx\x1f\x7f.bit", f"t{REPL}x{REPL}{REPL}.bit"),
    (b"<script>alert(1)</script>.bit", "<script>alert(1)</script>.bit"),
    ("‮gnp.bit".encode(), "‮gnp.bit"),
    (b"\xff\xfe.bit", f"{REPL}{REPL}.bit"),  # invalid UTF-8
    ("é" * 300, "é" * 255),  # characters, not bytes
    (None, ""),  # a missing name
    (b"", ""),
]


@pytest.mark.parametrize(("raw", "stored"), HOSTILE, ids=range(len(HOSTILE)))
def test_hostile_client_names_never_reach_the_file_system(
    env: Env, raw: bytes | str | None, stored: str
) -> None:
    before = tree(env.bits.parent)
    data = doc(f"Name {tag()}", [plug()])
    i0, m0 = env.last_import(), env.mark()
    out = up(env, data, raw)
    assert out.outcome == "success"
    after = tree(env.bits.parent)
    rel = f"bits/uploaded/policy-{out.policy_id}.bit"
    assert after == {**before, rel: ("file", sha(data))}  # nothing else
    (row,) = env.imports_after(i0)
    assert row["file_name"] == stored  # the #99 (d) form
    assert env.policy(out.policy_id or 0)["source_file"] == (
        f"uploaded/policy-{out.policy_id}.bit"
    )
    if stored:
        text = json.dumps([e["detail"] for e in env.entries(m0)])
        assert json.dumps(stored)[1:-1] not in text or stored in ("..", "n" * 255)


def test_client_file_name_rules() -> None:
    assert client_file_name(None) == ""
    assert client_file_name("a\ud800b") == f"a{REPL}b"  # storable in PostgreSQL
    assert client_file_name(b"x" * 255) == "x" * 255
    assert client_file_name(b"x" * 256) == "x" * 255
    assert client_file_name(" keep spaces ") == " keep spaces "
    assert client_file_name(" é") == " é"  # only C0 and DEL replaced
    for raw, stored in HOSTILE:
        assert client_file_name(raw) == stored
        assert client_file_name(stored) == stored  # idempotent


# CHK-M7-201: REQ-163 (2) a symlink, a file or a FIFO at the temp path -------------


@pytest.mark.parametrize("kind", ["symlink", "dangling", "file", "fifo"])
def test_anything_at_the_temp_path_fails_the_write_and_rolls_back(
    env: Env, kind: str
) -> None:
    data, first = new_policy(env)
    v2 = doc(env.policy(first.policy_id or 0)["policy_name"], [plug()], desc="v2")
    planted = temp(env, first.policy_id, v2)
    outside = env.bits.parent / f"outside-{tag()}"
    if kind == "symlink":
        outside.write_bytes(b"keep")
        planted.symlink_to(outside)
    elif kind == "dangling":
        planted.symlink_to(outside)  # following it would create `outside`
    elif kind == "file":
        planted.write_bytes(b"left by a failed rename")
    else:
        MKFIFO(planted)
    before = tree(env.bits.parent)
    snap = snapshot(env)
    readers: list[int] = []

    def drain() -> None:  # a FIFO writer that blocked gets a reader
        readers.append(REAL_OPEN(planted, os.O_RDONLY | O_NONBLOCK))

    with pytest.raises(OSError):
        in_thread(lambda: up(env, v2), unblock=drain if kind == "fifo" else None)
    unchanged(env, snap)  # no row, no entry, no alert (#98 (j))
    assert tree(env.bits.parent) == before  # target untouched, nothing removed
    assert final(env, first.policy_id).read_bytes() == data
    if kind == "dangling":
        assert not outside.exists()


def test_the_temp_file_is_opened_with_the_spec_flags(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int, int | None]] = []

    def spy(path: Any, flags: int, mode: int = 0o777, *a: Any, **k: Any) -> int:
        if ".tmp-" in str(path):
            calls.append((str(path), flags, mode))
        return REAL_OPEN(path, flags, mode, *a, **k)

    monkeypatch.setattr(os, "open", spy)
    _, out = new_policy(env)
    monkeypatch.undo()
    (path, flags, mode) = calls[0]
    assert Path(path).name.startswith(f".tmp-{out.policy_id}-")
    need = os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW  # TS L522
    assert flags & need == need and not flags & os.O_TRUNC
    assert mode == 0o600


# CHK-M7-202: REQ-163 (3), (4) ------------------------------------------------------


def test_a_rejected_re_upload_leaves_the_file_byte_identical(env: Env) -> None:
    data, first = new_policy(env)
    name = env.policy(first.policy_id or 0)["policy_name"]
    path = final(env, first.policy_id)
    st0 = path.stat()
    before = tree(env.bits.parent)
    cat0, i0 = env.catalog(), env.last_import()
    out = up(env, doc(name, [plug("rm x")]))  # BIT102 (stable under 146 r2)
    assert out.outcome == "rejected"
    assert [r["outcome"] for r in env.imports_after(i0)] == ["rejected"]
    assert env.catalog() == cat0
    assert tree(env.bits.parent) == before
    st1 = path.stat()
    assert (st1.st_ino, st1.st_mtime_ns, path.read_bytes()) == (
        st0.st_ino,
        st0.st_mtime_ns,
        data,
    )


@pytest.mark.parametrize("error", [OSError("fsync failed"), RuntimeError("late")])
def test_a_fault_after_the_temp_write_before_commit_leaves_no_temp(
    env: Env, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    data, first = new_policy(env)
    v2 = doc(env.policy(first.policy_id or 0)["policy_name"], [plug()], desc="v2")
    before = tree(env.bits.parent)
    snap = snapshot(env)
    seen: list[bool] = []

    def failing_sync(folder: Path) -> None:  # runs right after the temp write
        seen.append(temp(env, first.policy_id, v2).is_file())
        raise error

    monkeypatch.setattr(uploads, "_sync_folder", failing_sync)
    with pytest.raises(type(error)):
        up(env, v2)
    monkeypatch.undo()
    assert seen == [True]  # the fault came after the temp was written
    unchanged(env, snap)
    assert tree(env.bits.parent) == before  # no temp; the old file kept
    assert final(env, first.policy_id).read_bytes() == data


def test_a_fault_between_commit_and_rename_is_finished_at_start_up(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, first = new_policy(env)
    v2 = doc(env.policy(first.policy_id or 0)["policy_name"], [plug()], desc="v2")
    i0, c0 = env.last_import(), counters()
    o = leave_temp(env, monkeypatch, v2)
    assert (o.outcome, o.policy_id) == ("success", first.policy_id)
    (row,) = env.imports_after(i0)  # the record is still written
    assert (row["outcome"], row["file_sha256"]) == ("success", sha(v2))
    assert env.policy(first.policy_id or 0)["source_sha256"] == sha(v2)  # committed
    assert delta(c0) == {"policy_imported": 1.0}
    left = temp(env, first.policy_id, v2)
    assert left.read_bytes() == v2
    assert final(env, first.policy_id).read_bytes() == data  # not yet renamed
    # A same-bytes re-upload before the restart clashes on O_EXCL: an internal
    # error (503, #98 (j)) that changes nothing and keeps the left temp.
    snap = snapshot(env)
    with pytest.raises(FileExistsError):
        up(env, v2)
    unchanged(env, snap)
    assert left.read_bytes() == v2
    assert finish(env) == FinishResult(renamed=1, deleted=0)
    assert final(env, first.policy_id).read_bytes() == v2
    assert not left.exists()
    assert stat.S_IMODE(final(env, first.policy_id).stat().st_mode) == 0o600
    assert sorted(p.name for p in uploaded(env).iterdir()) == [
        f"policy-{first.policy_id}.bit"
    ]


# Order and lock (TS L522, L526) -----------------------------------------------------


def test_written_before_commit_renamed_after_inside_the_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, first = new_policy(env)
    pid = first.policy_id or 0
    v2 = doc(env.policy(pid)["policy_name"], [plug()], desc="v2")
    log: list[tuple[str, Any]] = []
    real_write = uploads._write_new

    def committed() -> str:
        with app(env.server) as c:
            row = c.execute(
                "SELECT source_sha256 FROM policy WHERE policy_id = %s", (pid,)
            ).fetchone()
        assert row is not None
        return str(row[0])

    def lock_free() -> bool:
        with app(env.server) as c:
            row = c.execute(
                "SELECT pg_try_advisory_lock(hashtext('catalog'))"
            ).fetchone()
            if row == (True,):
                c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        return row == (True,)

    def write(path: Path, b: bytes) -> None:
        log.append(("write", committed() == sha(v2)))
        real_write(path, b)

    def replace(src: Any, dst: Any) -> None:
        p = Path(src)
        mode = stat.S_IMODE(p.stat().st_mode)
        log.append(
            (
                "replace",
                (committed() == sha(v2), lock_free(), mode, p.read_bytes() == v2),
            )
        )
        REAL_REPLACE(src, dst)

    monkeypatch.setattr(uploads, "_write_new", write)
    monkeypatch.setattr(os, "replace", replace)
    out = up(env, v2)
    monkeypatch.undo()
    assert out.outcome == "success"
    # written while the new version was not yet committed; renamed after the
    # commit, the temp complete and 0600, the catalog lock still held
    assert log == [("write", False), ("replace", (True, False, 0o600, True))]
    assert final(env, pid).read_bytes() == v2


def test_a_re_upload_replaces_the_previous_file_and_is_never_skipped(env: Env) -> None:
    data, first = new_policy(env)
    pid = first.policy_id or 0
    name = env.policy(pid)["policy_name"]
    same = up(env, data)  # identical bytes: manual, never skipped
    assert same.outcome == "success" and same.policy_id == pid
    v2 = doc(name, [plug()], desc="v2")
    assert up(env, v2).policy_version == (first.policy_version or 0) + 1
    assert sorted(p.name for p in uploaded(env).iterdir()) == [f"policy-{pid}.bit"]
    assert final(env, pid).read_bytes() == v2


# CHK-M7-203: REQ-163 (5) a server-folder policy --------------------------------------


def test_a_server_folder_name_is_refused_with_no_row_and_no_file(env: Env) -> None:
    name = f"Server {tag()}"
    srv = env.imp(doc(name, [plug()]), "server.bit")
    assert srv.outcome == "success"
    before = tree(env.bits.parent)
    cat0, i0, m0, c0 = snapshot(env)
    with pytest.raises(PolicyManagedOnServer):
        up(env, doc(name, [plug()], desc="from an upload"), b"evil.bit")
    assert env.catalog() == cat0 and env.imports_after(i0) == []
    assert [e["action"] for e in env.entries(m0)] == ["policy.import_refused"]
    assert delta(c0) == {}
    assert tree(env.bits.parent) == before  # no file, no temp


# CHK-M7-204: REQ-163 (6) mode and owner ----------------------------------------------


def test_the_stored_file_is_0600_and_owned_by_the_service_user(env: Env) -> None:
    old = os.umask(0)  # even without the unit's UMask=0077
    try:
        _, out = new_policy(env)
    finally:
        os.umask(old)
    st = final(env, out.policy_id).stat()
    assert stat.S_IMODE(st.st_mode) == 0o600
    assert (st.st_uid, st.st_gid) == (GETUID(), GETGID())
    assert stat.S_ISREG(st.st_mode)


def test_imported_by_and_mode(env: Env) -> None:
    i0 = env.last_import()
    _, out = new_policy(env)
    (row,) = env.imports_after(i0)
    assert (row["imported_by"], row["mode"]) == (11, "manual")


def test_no_client_name_or_content_in_the_logs(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = f"client-{tag()}.bit"
    data, first = new_policy(env)
    name = env.policy(first.policy_id or 0)["policy_name"]
    up(env, doc(name, [plug("cat /etc/marker-x")]), marker.encode())
    up(env, doc(name, [plug("rm x")]), marker.encode())
    leave_temp(env, monkeypatch, doc(name, [plug()], desc="v3"), marker.encode())
    finish(env)
    for text in (marker, name, "cat /etc/marker-x", "rm x", ".tmp-"):
        assert text not in caplog.text
    assert "1 renamed, 0 deleted" in caplog.text


# CHK-M7-230 part: REQ-165 (1) the start-up finish -------------------------------------


def test_finish_renames_only_a_committed_temp_and_deletes_every_other(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    up_dir = uploaded(env)
    # committed: the rename failed after the commit
    a_data, a = new_policy(env)
    a_v2 = doc(env.policy(a.policy_id or 0)["policy_name"], [plug()], desc="v2")
    leave_temp(env, monkeypatch, a_v2)
    # uncommitted: bytes that never became source_sha256
    b_data, b = new_policy(env)
    stray = b"uncommitted bytes"
    (up_dir / f".tmp-{b.policy_id}-{sha(stray)}").write_bytes(stray)
    # a deleted policy's committed bytes (crash-window ruling)
    c_data, c = new_policy(env)
    with app(env.server) as conn, conn.transaction():
        assert adm.soft_delete_effects(conn, c.policy_id or 0, T2) is not None
    (up_dir / f".tmp-{c.policy_id}-{sha(c_data)}").write_bytes(c_data)
    # a live server-folder policy's bytes (source_file not uploaded/…)
    s_data = doc(f"Srv {tag()}", [plug()])
    s = env.imp(s_data, "srv.bit")
    (up_dir / f".tmp-{s.policy_id}-{sha(s_data)}").write_bytes(s_data)
    # a symlink with a valid name to a file holding b's committed bytes
    outside = env.bits.parent / "outside.bit"
    outside.write_bytes(b_data)
    (up_dir / f".tmp-{b.policy_id}-{sha(b_data)}").symlink_to(outside)
    # a FIFO with a valid name
    MKFIFO(up_dir / f".tmp-{a.policy_id}-{'0' * 64}")
    # names that are not the form
    for odd in [
        ".tmp-x",
        f".tmp-0{b.policy_id}-{sha(b_data)}",
        f".tmp-{b.policy_id}-{sha(b_data).upper()}",
        f".tmp-{b.policy_id}-{sha(b_data)[:63]}",
        f".tmp-{b.policy_id}-{sha(b_data)}-x",
        f".tmp-999999999-{sha(b_data)}",
        ".tmp-",
    ]:
        (up_dir / odd).write_bytes(b_data)
    big = b_data + b" " * (FIVE_MIB + 1 - len(b_data))
    (up_dir / f".tmp-{b.policy_id}-{sha(big)}").write_bytes(big)
    (up_dir / ".tmp-dir").mkdir()  # cannot be unlinked: logged, the loop goes on
    for keep in ["notes.txt", ".hidden", "policy-999999.bit", "tmp-1-x"]:
        (up_dir / keep).write_bytes(b"keep")
    server_before = {
        k: v for k, v in tree(env.bits).items() if not k.startswith("uploaded")
    }
    result = in_thread(lambda: finish(env))
    assert result == FinishResult(renamed=1, deleted=13)
    assert sorted(p.name for p in up_dir.iterdir()) == sorted(
        [
            ".hidden", ".tmp-dir", "notes.txt", "policy-999999.bit", "tmp-1-x",
            f"policy-{a.policy_id}.bit", f"policy-{b.policy_id}.bit",
            f"policy-{c.policy_id}.bit",
        ]
    )  # fmt: skip
    assert final(env, a.policy_id).read_bytes() == a_v2  # renamed into place
    assert final(env, b.policy_id).read_bytes() == b_data  # untouched
    assert outside.read_bytes() == b_data and not outside.is_symlink()
    assert env.policy(c.policy_id or 0)["deleted_at"] is not None  # stays deleted
    assert {
        k: v for k, v in tree(env.bits).items() if not k.startswith("uploaded")
    } == (server_before)
    assert finish(env) == FinishResult(renamed=0, deleted=0)  # idempotent


def test_finish_reads_the_temp_without_following_a_swapped_in_symlink(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The temp is a regular file when listed, then replaced by a symlink to a
    # file holding the committed bytes before it is opened for its hash. With
    # O_NOFOLLOW the open fails and the temp is deleted; the stored upload
    # never becomes a symlink.
    data, first = new_policy(env)
    v2 = doc(env.policy(first.policy_id or 0)["policy_name"], [plug()], desc="v2")
    leave_temp(env, monkeypatch, v2)
    left = temp(env, first.policy_id, v2)
    outside = env.bits.parent / "outside-v2.bit"
    outside.write_bytes(v2)
    flags_seen: list[int] = []

    def racing_open(path: Any, flags: int, *a: Any, **k: Any) -> int:
        if str(path) == str(left) and not flags & os.O_WRONLY:
            flags_seen.append(flags)
            if not left.is_symlink():
                left.unlink()
                left.symlink_to(outside)
        return REAL_OPEN(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", racing_open)
    result = finish(env)
    monkeypatch.undo()
    assert flags_seen and all(f & O_NOFOLLOW and f & O_NONBLOCK for f in flags_seen)
    assert result == FinishResult(renamed=0, deleted=1)
    path = final(env, first.policy_id)
    assert not path.is_symlink() and path.read_bytes() == data
    assert outside.read_bytes() == v2 and not left.exists() and not left.is_symlink()


# TASK-155 r1: the public staging (shared with folders.py) -------------------------


def stage_for(e: Env, data: bytes) -> UploadStage:
    return UploadStage(e.bits, sha(data), data)


def test_staged_upload_discards_its_temp_when_the_import_fails(env: Env) -> None:
    data = b"staged bytes"
    with pytest.raises(RuntimeError), staged_upload(env.bits, sha(data), data) as st:
        st.before_commit(424242)
        assert temp(env, 424242, data).read_bytes() == data
        raise RuntimeError("import failed before its commit")
    assert not temp(env, 424242, data).exists()
    assert list(uploaded(env).iterdir()) == []


def test_after_the_commit_discard_removes_nothing(env: Env) -> None:
    data = b"committed bytes"
    st = stage_for(env, data)
    st.before_commit(434343)
    st.after_commit(ImportOutcome(None, "success", policy_id=434343))
    assert st.committed
    st.discard()
    assert final(env, 434343).read_bytes() == data


def test_a_failed_rename_is_never_discarded(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"rename fails"

    def broken(src: Any, dst: Any) -> None:
        raise OSError("rename failed")

    with pytest.raises(OSError), staged_upload(env.bits, sha(data), data) as st:
        st.before_commit(444444)
        monkeypatch.setattr(os, "replace", broken)
        st.after_commit(ImportOutcome(None, "success", policy_id=444444))
    monkeypatch.undo()
    assert temp(env, 444444, data).read_bytes() == data  # left for the finish


def test_a_stage_that_created_nothing_discards_nothing(env: Env) -> None:
    data = b"someone else's temp"
    planted = temp(env, 454545, data)
    planted.write_bytes(data)
    stage_for(env, data).discard()  # never ran before_commit
    assert planted.read_bytes() == data
    st = stage_for(env, data)
    with pytest.raises(FileExistsError):
        st.before_commit(454545)  # O_EXCL: it did not create the file
    st.discard()
    assert planted.read_bytes() == data


def test_the_rename_target_is_the_id_recorded_before_commit(env: Env) -> None:
    data = b"recorded id"
    st = stage_for(env, data)
    st.before_commit(464646)
    st.after_commit(ImportOutcome(None, "success", policy_id=474747))
    assert final(env, 464646).read_bytes() == data
    assert not final(env, 474747).exists()


def test_a_deleted_policy_still_naming_its_upload_is_never_renamed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The finish's own live check (impl reading 1): a row the app could not
    # write (deleted, source_file kept), made as owner.
    data, first = new_policy(env)
    pid = first.policy_id or 0
    v2 = doc(env.policy(pid)["policy_name"], [plug()], desc="v2")
    leave_temp(env, monkeypatch, v2)
    with owner(env.server) as c:
        c.execute("UPDATE policy SET deleted_at = now() WHERE policy_id = %s", (pid,))
    assert env.policy(pid)["source_file"] == f"uploaded/policy-{pid}.bit"
    assert finish(env) == FinishResult(renamed=0, deleted=1)
    assert final(env, pid).read_bytes() == data  # never replaced
    assert not temp(env, pid, v2).exists()
