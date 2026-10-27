"""TP-M7-15 (TASK-155): uploads on a real temporary folder plus PostgreSQL.

CHK-M7-200 to -204 and the REQ-165 (1) half of CHK-M7-230
(tests/m7/test-plan.md); mutation rows CHK-M7-357 to -359. Expected values
come from the spec and the approved answers, not from the code: TS §4.1 L522
(the client name is ignored; temp ``uploaded/.tmp-<policy_id>-<sha256>``
opened ``O_NOFOLLOW | O_EXCL`` before the commit, renamed to
``uploaded/policy-<policy_id>.bit`` after it; a rejected upload leaves the
file and catalog untouched; 409 ``policy_managed_on_server``), L526 (the
caller's lock spans the rename), L528 (finish interrupted uploads), §8.7
L1377 (``UMask=0077``), REQ-163 (1)-(6), REQ-165 (1), #99 (d), (e), #101, and
the lead rulings of 2026-10-27: "Crash window ruling", "TASK-155 built"
(1) live policy and ``source_file`` must match too, (2) a ``DatabaseUnavailable``
at COMMIT keeps the temp file, and "TASK-154 REVIEW APPROVED" carry (a).

Owner: tester-m7-155. The code under test runs as ``bitscan_app``; results are
read as owner. Each test uses its own temporary bits folder and fresh names.
"""

from __future__ import annotations

import errno
import hashlib
import inspect
import logging
import os
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase, DatabaseUnavailable
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Tx
from bitscan_manager.services.importer import store, uploads
from bitscan_manager.services.importer.delete import delete_policy
from bitscan_manager.services.importer.pipeline import (
    Actor,
    ImportOutcome,
    Mode,
    import_one,
    prepare,
)
from bitscan_manager.services.importer.uploads import (
    FinishedUploads,
    client_file_name,
    finish_interrupted_uploads,
    import_upload,
)

from .catalog_rows import app, owner, tag
from .conftest import PgServer, own_migrated_server
from .pipeline_rows import (
    NONE,
    FixedClock,
    audits_since,
    bit,
    catalog_now,
    counter_delta,
    imports_since,
    policy_by_name,
    policy_row,
    server_file,
    sha,
    snap,
)

pytestmark = pytest.mark.pg

USER = Actor("user:7", 7)
R = "�"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("uploads")) as s:
        yield s


@pytest.fixture(scope="module")
def db(server: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=6, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    b = tmp_path / "bits"
    (b / "uploaded").mkdir(parents=True)
    os.chmod(b / "uploaded", 0o700)
    return b


def up(
    db: AppDatabase,
    bits: Path,
    data: bytes,
    name: bytes | str | None = b"client.bit",
    **kw: Any,
) -> ImportOutcome:
    """The caller's contract: a pinned session holding the catalog lock."""
    with db.session() as s, catalog_lock(s):
        return import_upload(s, FixedClock(), bits, data, name, actor=USER, **kw)


def finish(db: AppDatabase, bits: Path) -> FinishedUploads:
    with db.session() as s, catalog_lock(s):
        return finish_interrupted_uploads(s, bits)


def tmp_name(policy_id: int, data: bytes) -> str:
    return f".tmp-{policy_id}-{sha(data)}"


def listing(folder: Path) -> list[str]:
    return sorted(os.listdir(folder))


def tree(root: Path) -> dict[str, tuple[str, int, str]]:
    """Every entry under root: kind, mode, and content hash or link target."""
    out: dict[str, tuple[str, int, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in [*dirnames, *filenames]:
            p = Path(dirpath) / n
            st = p.lstat()
            rel = str(p.relative_to(root))
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", 0, os.readlink(p))
            elif stat.S_ISREG(st.st_mode):
                out[rel] = ("file", stat.S_IMODE(st.st_mode), sha(p.read_bytes()))
            else:
                out[rel] = ("other", stat.S_IMODE(st.st_mode), "")
    return out


def seed(db: AppDatabase, bits: Path) -> tuple[str, int, bytes]:
    """A live uploaded policy: its name, id and file."""
    name = f"Upload {tag()}"
    data, _ = bit(name)
    out = up(db, bits, data)
    assert out.outcome == "success" and out.policy_id is not None
    return name, out.policy_id, data


def stored(bits: Path, policy_id: int) -> Path:
    return bits / "uploaded" / f"policy-{policy_id}.bit"


def server_import(db: AppDatabase, bits: Path, data: bytes, path: str) -> int:
    with db.session() as s, catalog_lock(s):
        out = import_one(
            s, FixedClock(), bits, server_file(data, path), mode=Mode.AUTO,
            actor=Actor("system", None), file_exists=NONE,
        )  # fmt: skip
    assert out.outcome == "success" and out.policy_id is not None
    return out.policy_id


class Session:
    """Wraps a real session. In its first transaction it runs ``in_body``
    after the caller's body (before COMMIT); with ``lie`` it then reports
    ``DatabaseUnavailable`` although the COMMIT succeeded."""

    def __init__(
        self,
        real: CatalogSession,
        in_body: Callable[[], None],
        *,
        lie: bool = False,
        after: Callable[[], None] = lambda: None,
    ) -> None:
        self.real, self.in_body, self.lie, self.n = real, in_body, lie, 0
        self.after = after

    @property
    def conn(self) -> psycopg.Connection[Any]:
        return self.real.conn

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        self.n += 1
        first = self.n == 1
        with self.real.transaction() as tx:
            yield tx
            if first:
                self.in_body()
        if first:
            self.after()  # the first transaction has committed
        if first and self.lie:
            raise DatabaseUnavailable("database unavailable: OperationalError")

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        with self.real.savepoint():
            yield


def wait_gone(server: PgServer, pid: int) -> None:
    with app(server) as probe:
        probe.execute("SELECT pg_terminate_backend(%s)", (pid,))
        for _ in range(200):
            row = probe.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE pid = %s", (pid,)
            ).fetchone()
            if row == (0,):
                return
            time.sleep(0.025)
    raise AssertionError("backend did not end")


def lock_free(probe: psycopg.Connection[Any]) -> bool:
    row = probe.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
    assert row is not None
    if row[0]:
        probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    return bool(row[0])


def waiting(probe: psycopg.Connection[Any], pid: int) -> bool:
    row = probe.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        " AND pid = %s AND NOT granted",
        (pid,),
    ).fetchone()
    return row == (1,)


def until(cond: Callable[[], bool], what: str, bound: float = 20.0) -> None:
    end = time.monotonic() + bound
    while not cond():
        if time.monotonic() > end:
            raise AssertionError(f"timed out: {what}")
        time.sleep(0.05)


# CHK-M7-200 / REQ-163 (1): hostile client names --------------------------------


HOSTILE: list[bytes | str | None] = [
    b"../../etc/passwd",
    b"/abs.bit",
    b"a/b.bit",
    b"..",
    b".",
    b"",
    None,
    b"a" * 5000,
    b"x\x00y.bit",
    b"x\ry.bit",
    b"x\ny.bit",
    b"<script>alert(1)</script>.bit",
    "evil‮gnp.bit".encode(),
    b"\xff\xfe\xc0\xaf.bit",
    b"uploaded/../../x.bit",
    b"policy-1.bit",
    b".tmp-1-" + b"0" * 64,
    "../../etc/passwd",
    "a\x00b/../c.bit",
    "a\udcffb.bit",
    "é" * 5000,
]
EXPECTED_NAME: dict[int, str] = {
    0: "../../etc/passwd",
    1: "/abs.bit",
    3: "..",
    5: "",
    6: "",
    7: "a" * 255,
    8: f"x{R}y.bit",
    9: f"x{R}y.bit",
    10: f"x{R}y.bit",
    11: "<script>alert(1)</script>.bit",
    12: "evil‮gnp.bit",
    13: f"{R}{R}{R}{R}.bit",
    18: f"a{R}b/../c.bit",
    20: "é" * 255,
}


def root_state() -> dict[str, tuple[int, int, str] | None]:
    """What an absolute client name would hit: compared before and after, so
    a leftover from an earlier run cannot mask or fake a write."""
    out: dict[str, tuple[int, int, str] | None] = {}
    for n in ("/abs.bit", "/x.bit", "/a/b.bit"):
        p = Path(n)
        if not p.exists() and not p.is_symlink():
            out[n] = None
            continue
        st = p.lstat()
        body = sha(p.read_bytes()) if stat.S_ISREG(st.st_mode) else ""
        out[n] = (st.st_ino, st.st_mtime_ns, body)
    return out


@pytest.mark.parametrize("i", range(len(HOSTILE)))
def test_a_hostile_client_name_lands_only_as_policy_id_bit(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    i: int,
) -> None:
    raw = HOSTILE[i]
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    victim = tmp_path / "victim.bit"
    victim.write_bytes(b"victim")
    passwd = sha(Path("/etc/passwd").read_bytes())
    before = tree(tmp_path)
    roots0 = root_state()
    name = f"Hostile {tag()}"
    data, _ = bit(name)
    s0 = snap(server)
    out = up(db, bits, data, raw)
    assert out.outcome == "success" and out.policy_id is not None
    after = tree(tmp_path)
    added = {k: v for k, v in after.items() if before.get(k) != v}
    rel = f"bits/uploaded/policy-{out.policy_id}.bit"
    assert added == {rel: ("file", 0o600, sha(data))}
    assert set(before) <= set(after)
    assert root_state() == roots0  # nothing created or rewritten at "/"
    assert sha(Path("/etc/passwd").read_bytes()) == passwd
    row = imports_since(server, s0)
    assert len(row) == 1
    assert row[0]["file_name"] == client_file_name(raw)
    if i in EXPECTED_NAME:  # literal #99 (d) values, independent of the code
        assert row[0]["file_name"] == EXPECTED_NAME[i]
    assert len(row[0]["file_name"]) <= 255
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in row[0]["file_name"])
    p = policy_row(server, out.policy_id)
    assert p["source_file"] == f"uploaded/policy-{out.policy_id}.bit"
    assert p["source_sha256"] == sha(data)


def test_a_client_name_naming_another_policy_never_touches_its_file(
    db: AppDatabase, bits: Path
) -> None:
    _, a, a_data = seed(db, bits)
    a_name = f"policy-{a}.bit".encode()
    b_data, _ = bit(f"Other {tag()}")
    out = up(db, bits, b_data, a_name)
    assert out.policy_id != a
    assert stored(bits, a).read_bytes() == a_data
    assert stored(bits, out.policy_id or 0).read_bytes() == b_data
    assert listing(bits / "uploaded") == sorted(
        [f"policy-{a}.bit", f"policy-{out.policy_id}.bit"]
    )


# CHK-M7-204 / REQ-163 (6): mode 0600 and the service user ----------------------


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_the_stored_file_is_0600_and_the_service_users(
    db: AppDatabase, bits: Path, mask: int
) -> None:
    old = os.umask(mask)
    try:
        _, pid, data = seed(db, bits)
        st = stored(bits, pid).lstat()
        assert stat.S_ISREG(st.st_mode)
        assert stat.S_IMODE(st.st_mode) == 0o600
        assert (st.st_uid, st.st_gid) == (os.geteuid(), os.getegid())
        # A re-upload over a file someone made 0644 leaves a 0600 file again.
        os.chmod(stored(bits, pid), 0o644)
        name = policy_row_name(db, pid)
        v2, _ = bit(name, status="disabled")
        assert up(db, bits, v2).outcome == "success"
        assert stat.S_IMODE(stored(bits, pid).lstat().st_mode) == 0o600
        assert stored(bits, pid).read_bytes() == v2
    finally:
        os.umask(old)


def policy_row_name(db: AppDatabase, policy_id: int) -> str:
    with db.transaction() as tx:
        row = tx.conn.execute(
            "SELECT policy_name FROM policy WHERE policy_id = %s", (policy_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


# REQ-163 flags and order: O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, flushed, commit, rename


def test_temp_open_flags_flush_then_commit_then_rename(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, pid, _ = seed(db, bits)
    data, _ = bit(name, status="disabled")
    temp = bits / "uploaded" / tmp_name(pid, data)
    events: list[tuple[str, Any]] = []
    real_open, real_fsync, real_replace = os.open, os.fsync, os.replace
    fds: dict[int, str] = {}
    dir_flags: list[int] = []

    def spy_open(path: Any, flags: int, mode: int = 0o777, **kw: Any) -> int:
        fd = real_open(path, flags, mode, **kw)
        via = fds.get(kw.get("dir_fd", -1))  # "dir" when relative to uploaded/
        if Path(path) == temp or (via == "dir" and Path(path).name == temp.name):
            events.append(("open", (flags, mode, via)))
            fds[fd] = "temp"
        elif Path(path) == bits:
            dir_flags.append(flags)
            fds[fd] = "bits"
        elif str(path) == "uploaded" and fds.get(kw.get("dir_fd", -1)) == "bits":
            dir_flags.append(flags)
            fds[fd] = "dir"
        return fd

    def spy_fsync(fd: int) -> None:
        events.append(("fsync", fds.get(fd, "?")))
        real_fsync(fd)

    def spy_replace(a: Any, b: Any, **kw: Any) -> None:
        via = (fds.get(kw.get("src_dir_fd", -1)), fds.get(kw.get("dst_dir_fd", -1)))
        events.append(("replace", (Path(a).name, Path(b).name, via)))
        real_replace(a, b, **kw)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    def committed() -> None:
        events.append(("commit", None))

    with db.session() as s, catalog_lock(s):
        wrapped = Session(s, lambda: events.append(("body end", None)), after=committed)
        out = import_upload(wrapped, FixedClock(), bits, data, b"c.bit", actor=USER)
    assert out.outcome == "success"
    opens = [e for e in events if e[0] == "open"]
    assert len(opens) == 1
    flags, mode, via = opens[0][1]
    for flag in ("O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW"):
        assert flags & getattr(os, flag), flag
    assert not flags & os.O_TRUNC and not flags & os.O_APPEND
    assert mode == 0o600
    # Folder guard (r2, r3 rulings): the bits folder, then uploaded/ relative
    # to it, each O_DIRECTORY | O_NOFOLLOW; the temp open, the directory fsync
    # and the rename are relative to the uploaded/ fd.
    assert via == "dir"
    assert "dir" in fds.values() and "bits" in fds.values()
    assert dir_flags and all(
        f & os.O_DIRECTORY and f & os.O_NOFOLLOW for f in dir_flags
    )
    kinds = [e[0] if e[0] != "fsync" else f"fsync:{e[1]}" for e in events]
    assert kinds.index("fsync:temp") < kinds.index("commit")
    assert kinds.index("fsync:dir") < kinds.index("commit")
    assert kinds.index("commit") < kinds.index("replace")
    assert ("replace", (temp.name, f"policy-{pid}.bit", ("dir", "dir"))) in events
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == data


# CHK-M7-201 / REQ-163 (2): something planted at the temp path ------------------


def _planted_case(
    server: PgServer, db: AppDatabase, bits: Path, plant: Callable[[Path], object]
) -> tuple[Path, int, bytes, Any]:
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    temp = bits / "uploaded" / tmp_name(pid, v2)
    plant(temp)
    before_disk = tree(bits.parent)
    s0 = snap(server)
    with pytest.raises(OSError) as err:
        up(db, bits, v2)
    assert imports_since(server, s0) == []  # an internal error: no row (#98 (j))
    assert audits_since(server, s0) == []
    assert catalog_now(server) == s0.catalog
    assert counter_delta(s0) == {}
    assert tree(bits.parent) == before_disk  # link, target, old file untouched
    assert stored(bits, pid).read_bytes() == v1
    assert policy_row(server, pid)["source_sha256"] == sha(v1)
    return temp, pid, v1, err.value


def test_a_symlink_at_the_temp_path_fails_closed_and_its_target_is_untouched(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    victim = bits.parent / "outside" / "victim"
    victim.parent.mkdir()
    victim.write_bytes(b"secret victim bytes\n")
    os.chmod(victim, 0o644)
    temp, *_, exc = _planted_case(server, db, bits, lambda t: t.symlink_to(victim))
    assert exc.errno in (errno.EEXIST, errno.ELOOP)
    assert temp.is_symlink() and os.readlink(temp) == str(victim)
    assert victim.read_bytes() == b"secret victim bytes\n"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644


def test_a_dangling_symlink_at_the_temp_path_creates_nothing_at_its_target(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    target = bits.parent / "outside" / "created-by-follow.bit"
    target.parent.mkdir()
    temp, *_ = _planted_case(server, db, bits, lambda t: t.symlink_to(target))
    assert temp.is_symlink()
    assert not target.exists() and not target.is_symlink()


def test_a_regular_file_at_the_temp_path_is_neither_overwritten_nor_deleted(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    temp, *_ = _planted_case(
        server, db, bits, lambda t: t.write_bytes(b"planted, not ours")
    )
    assert temp.read_bytes() == b"planted, not ours"


def test_a_directory_at_the_temp_path_fails_closed(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    temp, *_ = _planted_case(server, db, bits, lambda t: t.mkdir())
    assert temp.is_dir()


def test_a_symlink_at_the_final_path_is_replaced_never_followed(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, _ = seed(db, bits)
    victim = bits.parent / "victim"
    victim.write_bytes(b"victim")
    stored(bits, pid).unlink()
    stored(bits, pid).symlink_to(victim)
    v2, _ = bit(name, status="disabled")
    assert up(db, bits, v2).outcome == "success"
    assert not stored(bits, pid).is_symlink()
    assert stored(bits, pid).read_bytes() == v2
    assert victim.read_bytes() == b"victim"


# CHK-M7-202 / REQ-163 (3): a rejected upload leaves file and catalog ------------


def test_a_rejected_reupload_leaves_the_stored_file_byte_identical(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, v1 = seed(db, bits)
    st0 = stored(bits, pid).stat()
    bad, _ = bit(name, status="maybe")  # BIT003
    s0 = snap(server)
    out = up(db, bits, bad, b"bad.bit")
    assert out.outcome == "rejected"
    assert [e["code"] for e in out_errors(out)] == ["BIT003"]
    assert stored(bits, pid).read_bytes() == v1
    st1 = stored(bits, pid).stat()
    assert (st1.st_ino, st1.st_mtime_ns, st1.st_mode) == (
        st0.st_ino, st0.st_mtime_ns, st0.st_mode,
    )  # fmt: skip
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert catalog_now(server) == s0.catalog
    rows = imports_since(server, s0)
    assert [(r["outcome"], r["file_name"]) for r in rows] == [("rejected", "bad.bit")]


def out_errors(out: ImportOutcome) -> list[dict[str, Any]]:
    return [{"code": f.code} for f in out.findings]


def test_a_rejected_new_upload_writes_nothing(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    bad, _ = bit(f"New {tag()}", status="maybe")
    s0 = snap(server)
    assert up(db, bits, bad).outcome == "rejected"
    assert listing(bits / "uploaded") == []
    assert catalog_now(server) == s0.catalog
    assert up(db, bits, b"<not xml").outcome == "rejected"
    assert listing(bits / "uploaded") == []


def test_a_reupload_replaces_only_that_policys_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, v1 = seed(db, bits)
    _, other, other_data = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    assert up(db, bits, v2).outcome == "success"
    assert stored(bits, pid).read_bytes() == v2
    assert stored(bits, other).read_bytes() == other_data
    assert policy_row(server, pid)["source_sha256"] == sha(v2)
    # The same bytes again (manual never skips): still exactly one file each.
    assert up(db, bits, v2).outcome == "success"
    assert listing(bits / "uploaded") == sorted(
        [f"policy-{pid}.bit", f"policy-{other}.bit"]
    )
    assert v1 != v2


def test_a_deleted_uploaded_policy_comes_back_with_its_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, v1 = seed(db, bits)
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    assert listing(bits / "uploaded") == []
    out = up(db, bits, v1)
    assert (out.outcome, out.policy_id) == ("success", pid)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == v1
    assert policy_row(server, pid)["deleted_at"] is None


# CHK-M7-203 / REQ-163 (5), #99 (e): 409 policy_managed_on_server ---------------


def test_an_upload_of_a_server_folder_policy_is_409_with_nothing_written(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name = f"Server {tag()}"
    d1, _ = bit(name)
    (bits / "srv.bit").write_bytes(d1)
    srv = server_import(db, bits, d1, "srv.bit")
    d2, _ = bit(name, status="disabled")
    disk0 = tree(bits.parent)
    s0 = snap(server)
    with pytest.raises(store.PolicyManagedOnServer) as err:
        up(db, bits, d2, b"../srv.bit")
    assert err.value.policy_id == srv
    assert tree(bits.parent) == disk0
    assert listing(bits / "uploaded") == []
    assert imports_since(server, s0) == []
    entries = audits_since(server, s0)
    assert len(entries) == 1
    e = entries[0]
    assert (e["action"], e["target"], e["actor"]) == (
        "policy.import_refused", f"policy:{srv}", "user:7",
    )  # fmt: skip
    assert not (e["detail"] or {}).get("alert")
    assert counter_delta(s0) == {}
    assert catalog_now(server) == s0.catalog


# CHK-M7-202 / REQ-163 (4): faults before the commit -----------------------------


def _fault(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    if target == "write":
        real = os.write

        def half(fd: int, data: Any) -> int:
            if len(data) > 8:
                real(fd, bytes(data[: len(data) // 2]))
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(fd, data)

        monkeypatch.setattr(os, "write", half)
    elif target == "fsync":

        def full(fd: int) -> None:
            raise OSError(errno.EIO, "I/O error")

        monkeypatch.setattr(os, "fsync", full)
    else:

        def dirsync(folder: Any) -> None:
            raise OSError(errno.EIO, "I/O error")

        monkeypatch.setattr(uploads, "_fsync_dir", dirsync)


@pytest.mark.parametrize("where", ["write", "fsync", "dirsync"])
@pytest.mark.parametrize("new", [True, False], ids=["new", "update"])
def test_a_fault_after_the_temp_open_and_before_commit_leaves_no_temp(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    new: bool,
) -> None:
    if new:
        name, pid, v1 = f"Fault {tag()}", 0, b""
    else:
        name, pid, v1 = seed(db, bits)
    data, _ = bit(name, status="disabled")
    disk0 = tree(bits.parent)
    s0 = snap(server)
    _fault(monkeypatch, where)
    with pytest.raises(OSError):
        up(db, bits, data)
    monkeypatch.undo()
    assert tree(bits.parent) == disk0  # no temp; the old file as it was
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == []
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    if not new:
        assert stored(bits, pid).read_bytes() == v1
    assert policy_by_name(server, name) is None or not new


def test_a_failed_commit_keeps_the_temp_and_finish_deletes_it_when_not_committed(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """Lead ruling (2): DatabaseUnavailable at COMMIT keeps the file; the next
    finish step resolves it by the row (here the commit did not happen)."""
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    s0 = snap(server)
    with db.session() as s, catalog_lock(s):
        backend = s.conn.info.backend_pid

        def kill() -> None:
            wait_gone(server, backend)

        with pytest.raises(DatabaseUnavailable):
            import_upload(Session(s, kill), FixedClock(), bits, v2, b"c", actor=USER)
    assert listing(bits / "uploaded") == sorted(
        [f"policy-{pid}.bit", tmp_name(pid, v2)]
    )
    assert stored(bits, pid).read_bytes() == v1  # never renamed before commit
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == []
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=1)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == v1


def test_a_commit_that_happened_but_reported_unavailable_is_renamed_by_finish(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    s0 = snap(server)

    with db.session() as s, catalog_lock(s):
        lying = Session(s, lambda: None, lie=True)
        with pytest.raises(DatabaseUnavailable):
            import_upload(lying, FixedClock(), bits, v2, b"c", actor=USER)
    assert policy_row(server, pid)["source_sha256"] == sha(v2)  # committed
    assert imports_since(server, s0) == []
    temp = bits / "uploaded" / tmp_name(pid, v2)
    assert temp.read_bytes() == v2
    assert stored(bits, pid).read_bytes() == v1
    # Until then the same bytes again fail closed and do not touch that temp.
    with pytest.raises(OSError):
        up(db, bits, v2)
    assert temp.read_bytes() == v2
    assert finish(db, bits) == FinishedUploads(renamed=1, deleted=0)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == v2
    assert stat.S_IMODE(stored(bits, pid).stat().st_mode) == 0o600


# CHK-M7-202 / REQ-163 (4): a fault between the commit and the rename ------------


def test_a_fault_between_commit_and_rename_is_finished_at_the_next_start(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    s0 = snap(server)

    def broken(a: Any, b: Any, **kw: Any) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        up(db, bits, v2, b"v2.bit")
    monkeypatch.undo()
    rows = imports_since(server, s0)  # TASK-154 deviation (5): the row stands
    assert [(r["outcome"], r["file_name"]) for r in rows] == [("success", "v2.bit")]
    assert policy_row(server, pid)["source_sha256"] == sha(v2)
    assert listing(bits / "uploaded") == sorted(
        [f"policy-{pid}.bit", tmp_name(pid, v2)]
    )
    assert stored(bits, pid).read_bytes() == v1
    assert finish(db, bits) == FinishedUploads(renamed=1, deleted=0)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == v2


def test_a_new_policy_whose_rename_failed_gets_its_file_from_finish(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"New {tag()}"
    data, _ = bit(name)

    def broken(a: Any, b: Any, **kw: Any) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        up(db, bits, data)
    monkeypatch.undo()
    p = policy_by_name(server, name)
    assert p is not None
    pid = int(p["policy_id"])
    assert listing(bits / "uploaded") == [tmp_name(pid, data)]
    assert finish(db, bits) == FinishedUploads(renamed=1, deleted=0)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == data


# CHK-M7-230 (REQ-165 (1)): finish_interrupted_uploads ----------------------------


def test_finish_renames_only_full_matches_and_deletes_every_other_temp(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    folder = bits / "uploaded"
    # (a) committed: live, uploaded, source_sha256 = the name = the content.
    name_a, a, a1 = seed(db, bits)
    a2, _ = bit(name_a, status="disabled")
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s", (sha(a2), a)
        )
    (folder / tmp_name(a, a2)).write_bytes(a2)
    # (b) uncommitted: the content hashes to its name but not to the row.
    _, b, b1 = seed(db, bits)
    b2, _ = bit(f"Other {tag()}")
    (folder / tmp_name(b, b2)).write_bytes(b2)
    # (c) the name's hash is the row's, the content is not.
    _, c_id, c1 = seed(db, bits)
    (folder / tmp_name(c_id, c1)).write_bytes(c1 + b"\n")
    # (d) a symlink temp to a file whose bytes match the live row.
    _, d, d1 = seed(db, bits)
    outside = bits.parent / "outside.bit"
    outside.write_bytes(d1)
    (folder / tmp_name(d, d1)).symlink_to(outside)
    # (e) foreign and malformed names, (f) unknown id, (g) huge ids.
    junk = [
        ".tmp-x",
        ".tmp-",
        f".tmp-{a}",
        f".tmp-{a}-{sha(a2).upper()}",
        f".tmp-0{a}-{sha(a2)}",
        f".tmp-{a}-{sha(a2)}-extra",
        f".tmp--{a}-{sha(a2)}",
        f".tmp-{9_000_000_000}-{sha(b'z')}",
        f".tmp-{2**63}-{sha(b'z')}",
        f".tmp-{'9' * 30}-{sha(b'z')}",
        f".tmp-{a}-{sha(a2)[:63]}",
    ]
    for j in junk:
        (folder / j).write_bytes(a2)
    (folder / f".tmp-{'9' * 30}-{sha(b'z')}").write_bytes(b"z")
    keep = ["notes.txt", ".tmpfoo", "tmp-1-x", "x.bit"]
    for k in keep:
        (folder / k).write_bytes(b"leave me")
    before_outside = outside.read_bytes()
    s0 = snap(server)
    got = finish(db, bits)
    assert got == FinishedUploads(renamed=1, deleted=3 + len(junk))
    assert listing(folder) == sorted(
        [f"policy-{x}.bit" for x in (a, b, c_id, d)] + keep
    )
    assert stored(bits, a).read_bytes() == a2
    assert stored(bits, b).read_bytes() == b1
    assert stored(bits, c_id).read_bytes() == c1
    assert stored(bits, d).read_bytes() == d1 and not stored(bits, d).is_symlink()
    assert outside.read_bytes() == before_outside and outside.is_file()
    for k in keep:
        assert (folder / k).read_bytes() == b"leave me"
    assert catalog_now(server) == s0.catalog  # finishing writes no row
    assert imports_since(server, s0) == []
    assert audits_since(server, s0) == []
    assert a1 != a2


def test_finish_never_renames_a_symlink_into_place_even_if_its_target_matches(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s", (sha(v2), pid)
        )
    target = bits.parent / "target.bit"
    target.write_bytes(v2)
    link = bits / "uploaded" / tmp_name(pid, v2)
    link.symlink_to(target)
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=1)
    assert not link.exists() and not link.is_symlink()
    assert stored(bits, pid).read_bytes() == v1 and not stored(bits, pid).is_symlink()
    assert target.read_bytes() == v2


def test_finish_deletes_the_temp_of_a_deleted_policy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """Crash window ruling: a deleted policy never gets its file back."""
    _, pid, v1 = seed(db, bits)
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    temp = bits / "uploaded" / tmp_name(pid, v1)
    temp.write_bytes(v1)
    assert policy_row(server, pid)["source_sha256"] == sha(v1)
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=1)
    assert listing(bits / "uploaded") == []


def test_finish_deletes_the_temp_of_a_deleted_row_even_if_source_file_matches(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """A state the app never writes (built as owner): deleted_at set while
    source_file still names the upload. Liveness alone must refuse it."""
    _, pid, v1 = seed(db, bits)
    stored(bits, pid).unlink()
    with owner(server) as c:
        c.execute("UPDATE policy SET deleted_at = now() WHERE policy_id = %s", (pid,))
    (bits / "uploaded" / tmp_name(pid, v1)).write_bytes(v1)
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=1)
    assert listing(bits / "uploaded") == []


def test_finish_deletes_the_temp_of_a_policy_that_moved_to_the_server_folder(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, _ = seed(db, bits)
    srv, _ = bit(name, status="disabled")
    (bits / "moved.bit").write_bytes(srv)
    assert server_import(db, bits, srv, "moved.bit") == pid
    row = policy_row(server, pid)
    assert (row["source_file"], row["source_sha256"]) == ("moved.bit", sha(srv))
    assert listing(bits / "uploaded") == []  # the server folder wins
    (bits / "uploaded" / tmp_name(pid, srv)).write_bytes(srv)
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=1)
    assert listing(bits / "uploaded") == []
    assert (bits / "moved.bit").read_bytes() == srv


def test_finish_does_not_hang_on_a_fifo_and_deletes_it(
    db: AppDatabase, bits: Path
) -> None:
    _, pid, v1 = seed(db, bits)
    fifo = bits / "uploaded" / tmp_name(pid, v1)
    os.mkfifo(fifo)
    result: list[Any] = []
    t = threading.Thread(target=lambda: result.append(finish(db, bits)), daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive(), "finish hung on a FIFO"
    assert result == [FinishedUploads(renamed=0, deleted=1)]
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]


def test_finish_on_an_empty_folder_does_nothing(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    s0 = snap(server)
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=0)
    assert listing(bits / "uploaded") == []
    assert catalog_now(server) == s0.catalog


def test_finish_on_a_missing_folder_is_empty_logs_one_line_and_creates_nothing(
    server: PgServer, db: AppDatabase, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Lead ruling "A missing bits/uploaded/ folder": counted as empty, one
    log line, never created, so start-up goes on to reconcile."""
    bits = tmp_path / "bits"
    bits.mkdir()
    s0 = snap(server)
    caplog.set_level("DEBUG", logger="bitscan_manager.services.importer.uploads")
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=0)
    assert listing(bits) == []
    assert not (bits / "uploaded").exists()
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    recs = [
        r for r in caplog.records
        if r.name == "bitscan_manager.services.importer.uploads"
    ]  # fmt: skip
    assert len(recs) == 1 and recs[0].levelno >= 30  # one warning
    assert str(tmp_path) not in recs[0].getMessage()


def test_an_upload_with_no_uploaded_folder_fails_closed_with_no_row(
    server: PgServer, db: AppDatabase, tmp_path: Path
) -> None:
    """Same ruling, #98 (j): an internal disk error, no bit_import row, no
    catalog change, and the folder is not created."""
    bits = tmp_path / "bits"
    bits.mkdir()
    data, _ = bit(f"NoFolder {tag()}")
    s0 = snap(server)
    with pytest.raises(FileNotFoundError):
        up(db, bits, data, b"../evil.bit")
    assert listing(bits) == [] and listing(tmp_path) == ["bits"]
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    # A rejected upload never reaches the disk: its normal row is written.
    bad, _ = bit(f"NoFolder {tag()}", status="maybe")
    assert up(db, bits, bad).outcome == "rejected"
    assert [r["outcome"] for r in imports_since(server, s0)] == ["rejected"]
    assert listing(bits) == []


# Folder guard on the upload path (lead ruling, decisions 2026-10-27, TASK-155 r2)

GUARD_KINDS = ["file", "dir-link", "file-link", "dangling-link"]


def _break_folder(server: PgServer, db: AppDatabase, bits: Path, kind: str) -> Path:
    """A live upload whose interrupted rename would be finished, then
    ``uploaded/`` replaced by ``kind``. Returns the directory that holds the
    real files (the symlink's target for "dir-link")."""
    name, pid, v1 = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s", (sha(v2), pid)
        )
    folder = bits / "uploaded"
    (folder / tmp_name(pid, v2)).write_bytes(v2)  # would be renamed if followed
    (folder / ".tmp-x").write_bytes(b"junk")  # would be deleted if followed
    real = bits.parent / "real-uploaded"
    folder.rename(real)
    if kind == "file":
        folder.write_bytes(b"not a directory")
    elif kind == "dir-link":
        folder.symlink_to(real, target_is_directory=True)
    elif kind == "file-link":
        (bits.parent / "plain").write_bytes(b"plain")
        folder.symlink_to(bits.parent / "plain")
    else:
        folder.symlink_to(bits.parent / "nowhere")
    return real


def _guard_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == "bitscan_manager.services.importer.uploads"
    ]  # fmt: skip


@pytest.mark.parametrize("kind", GUARD_KINDS)
def test_finish_touches_nothing_when_uploaded_is_not_a_real_directory(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    _break_folder(server, db, bits, kind)
    disk0 = tree(bits.parent)
    s0 = snap(server)
    caplog.set_level("DEBUG", logger="bitscan_manager.services.importer.uploads")
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=0)
    assert tree(bits.parent) == disk0  # nothing renamed or deleted in the target
    assert not (bits.parent / "nowhere").exists()
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    recs = _guard_logs(caplog)
    assert len(recs) == 1 and recs[0].levelno >= logging.WARNING
    msg = recs[0].getMessage()  # fixed words: no path, no entry name
    assert str(bits.parent) not in msg and "uploaded/" not in msg
    assert ".tmp-" not in msg and "real-uploaded" not in msg


@pytest.mark.parametrize("new", [True, False], ids=["new", "update"])
@pytest.mark.parametrize("kind", GUARD_KINDS)
def test_an_upload_writes_nothing_when_uploaded_is_not_a_real_directory(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    new: bool,
) -> None:
    real = _break_folder(server, db, bits, kind)
    if new:
        data, _ = bit(f"Guard {tag()}")
    else:
        pid = int(next(iter(_live_upload_ids(real))))
        data, _ = bit(policy_row_name(db, pid))
    disk0 = tree(bits.parent)
    s0 = snap(server)
    canary = f"client-canary-{tag()}"
    caplog.set_level("DEBUG")
    with pytest.raises(OSError):
        up(db, bits, data, canary.encode())
    assert tree(bits.parent) == disk0  # nothing written through the link
    assert not (bits.parent / "nowhere").exists()
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == []  # #98 (j): an internal error, no row
    assert audits_since(server, s0) == []
    assert counter_delta(s0) == {}
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert canary not in text


def _live_upload_ids(real: Path) -> list[str]:
    return [
        n.removeprefix("policy-").removesuffix(".bit")
        for n in sorted(os.listdir(real))
        if n.startswith("policy-")
    ]


@pytest.mark.parametrize("kind", GUARD_KINDS)
def test_a_rejected_upload_still_gets_its_row_with_a_broken_folder(
    server: PgServer, db: AppDatabase, bits: Path, kind: str
) -> None:
    """A rejection never reaches the disk, so the guard does not change it."""
    _break_folder(server, db, bits, kind)
    disk0 = tree(bits.parent)
    s0 = snap(server)
    bad, _ = bit(f"Guard {tag()}", status="maybe")
    assert up(db, bits, bad).outcome == "rejected"
    assert [r["outcome"] for r in imports_since(server, s0)] == ["rejected"]
    assert tree(bits.parent) == disk0


def test_the_folder_is_checked_at_each_call_not_cached(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """Swapped to a symlink after a good upload, the next upload still refuses;
    restored, uploads work again."""
    _, pid, _ = seed(db, bits)
    real = bits.parent / "real-uploaded"
    (bits / "uploaded").rename(real)
    (bits / "uploaded").symlink_to(real, target_is_directory=True)
    data, _ = bit(f"Swap {tag()}")
    before = tree(real)
    with pytest.raises(OSError):
        up(db, bits, data)
    assert tree(real) == before
    (bits / "uploaded").unlink()
    real.rename(bits / "uploaded")
    out = up(db, bits, data)
    assert out.outcome == "success"
    assert listing(bits / "uploaded") == sorted(
        [f"policy-{pid}.bit", f"policy-{out.policy_id}.bit"]
    )


def _link_uploaded(bits: Path) -> Path:
    """Replace a real uploaded/ by a symlink to it; return the real folder."""
    real = bits.parent / "real-uploaded"
    (bits / "uploaded").rename(real)
    (bits / "uploaded").symlink_to(real, target_is_directory=True)
    return real


def test_a_server_file_taking_an_uploaded_name_through_a_linked_folder_leaves_the_copy(
    server: PgServer, db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """r2: the post-commit removal of the uploaded copy (``move_upload``) goes
    through the guarded handle: the catalog move commits, nothing raises, the
    copy behind the link is left (for the #103 check) and one line is logged."""
    name, pid, v1 = seed(db, bits)
    real = _link_uploaded(bits)
    srv, _ = bit(name, status="disabled")
    (bits / "srv.bit").write_bytes(srv)
    caplog.set_level("DEBUG")
    assert server_import(db, bits, srv, "srv.bit") == pid
    row = policy_row(server, pid)
    assert (row["source_file"], row["source_sha256"]) == ("srv.bit", sha(srv))
    assert listing(real) == [f"policy-{pid}.bit"]
    assert (real / f"policy-{pid}.bit").read_bytes() == v1
    msgs = [r.getMessage() for r in caplog.records]
    assert any("upload removal skipped" in m for m in msgs), msgs
    assert not any(str(bits.parent) in m for m in msgs)


def test_a_delete_through_a_linked_folder_commits_and_leaves_the_copy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    _, pid, v1 = seed(db, bits)
    real = _link_uploaded(bits)
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    assert policy_row(server, pid)["deleted_at"] is not None
    assert listing(real) == [f"policy-{pid}.bit"]
    assert (real / f"policy-{pid}.bit").read_bytes() == v1


def test_a_delete_with_a_real_folder_still_removes_the_copy(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    _, pid, _ = seed(db, bits)
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    assert listing(bits / "uploaded") == []


def test_a_failed_copy_removal_is_logged_by_type_and_never_raises(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """r2 ``remove_after_commit``: the catalog has committed, so an unlink
    error other than "missing" is logged by type only and the copy is left."""
    _, pid, v1 = seed(db, bits)
    real_unlink = os.unlink

    def refuse(path: Any, *a: Any, **kw: Any) -> None:
        if str(path) == f"policy-{pid}.bit":
            raise PermissionError(errno.EACCES, "denied")
        real_unlink(path, *a, **kw)

    monkeypatch.setattr(os, "unlink", refuse)
    caplog.set_level("DEBUG")
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    monkeypatch.undo()
    assert policy_row(server, pid)["deleted_at"] is not None
    assert stored(bits, pid).read_bytes() == v1
    msgs = [r.getMessage() for r in caplog.records]
    assert "upload removal failed: PermissionError" in msgs
    assert not any(f"policy-{pid}" in m or str(bits) in m for m in msgs)


def test_a_folder_swapped_for_a_link_after_the_write_renames_in_the_original(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handle opened at the write is the one renamed in: a swap between
    commit and rename never moves the file into the link's target."""
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    decoy = bits.parent / "decoy"
    decoy.mkdir()
    (decoy / "keep").write_bytes(b"decoy")
    real_rename = uploads._Upload.rename
    moved = bits.parent / "moved-uploaded"

    def rename(self: Any, pending: Any) -> None:
        (bits / "uploaded").rename(moved)
        (bits / "uploaded").symlink_to(decoy, target_is_directory=True)
        real_rename(self, pending)

    monkeypatch.setattr(uploads._Upload, "rename", rename)
    assert up(db, bits, v2).outcome == "success"
    assert listing(decoy) == ["keep"]
    assert listing(moved) == [f"policy-{pid}.bit"]
    assert (moved / f"policy-{pid}.bit").read_bytes() == v2


# Folder guard on the bits folder itself (TASK-155 r3, decisions 2026-10-27) ----

BITS_KINDS = ["dir-link", "file", "dangling-link"]


def _break_bits(
    server: PgServer, db: AppDatabase, bits: Path, kind: str
) -> tuple[Path, str, int]:
    """A live upload with an interrupted rename and a junk temp, then the
    bits folder replaced by ``kind``. Returns the real folder, the policy's
    name and id."""
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s", (sha(v2), pid)
        )
    (bits / "uploaded" / tmp_name(pid, v2)).write_bytes(v2)
    (bits / "uploaded" / ".tmp-x").write_bytes(b"junk")
    real = bits.parent / "real-bits"
    bits.rename(real)
    if kind == "dir-link":
        bits.symlink_to(real, target_is_directory=True)
    elif kind == "file":
        bits.write_bytes(b"not a directory")
    else:
        bits.symlink_to(bits.parent / "nowhere")
    return real, name, pid


@pytest.mark.parametrize("kind", BITS_KINDS)
def test_finish_touches_nothing_when_the_bits_folder_is_not_a_real_directory(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    _break_bits(server, db, bits, kind)
    disk0 = tree(bits.parent)
    s0 = snap(server)
    caplog.set_level("DEBUG", logger="bitscan_manager.services.importer.uploads")
    assert finish(db, bits) == FinishedUploads(renamed=0, deleted=0)
    assert tree(bits.parent) == disk0
    assert not (bits.parent / "nowhere").exists()
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    recs = _guard_logs(caplog)
    assert len(recs) == 1 and recs[0].levelno >= logging.WARNING
    assert str(bits.parent) not in recs[0].getMessage()


@pytest.mark.parametrize("new", [True, False], ids=["new", "update"])
@pytest.mark.parametrize("kind", BITS_KINDS)
def test_an_upload_writes_nothing_when_the_bits_folder_is_not_a_real_directory(
    server: PgServer, db: AppDatabase, bits: Path, kind: str, new: bool
) -> None:
    _, name, _ = _break_bits(server, db, bits, kind)
    data, _ = bit(f"Guard {tag()}" if new else name)
    disk0 = tree(bits.parent)
    s0 = snap(server)
    with pytest.raises(OSError):
        up(db, bits, data)
    assert tree(bits.parent) == disk0
    assert not (bits.parent / "nowhere").exists()
    assert catalog_now(server) == s0.catalog
    assert imports_since(server, s0) == [] and audits_since(server, s0) == []
    assert counter_delta(s0) == {}


def test_a_delete_through_a_linked_bits_folder_commits_and_leaves_the_copy(
    server: PgServer, db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    real, _, pid = _break_bits(server, db, bits, "dir-link")
    before = tree(real)
    caplog.set_level("DEBUG")
    delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    assert policy_row(server, pid)["deleted_at"] is not None
    assert tree(real) == before  # policy-<id>.bit still there, behind the link
    assert (real / "uploaded" / f"policy-{pid}.bit").is_file()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("upload removal skipped" in m for m in msgs), msgs


def test_a_server_file_taking_an_uploaded_name_through_a_linked_bits_folder(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """``move_upload``'s removal: the catalog move commits; the copy behind a
    symlinked bits folder is left."""
    real, name, pid = _break_bits(server, db, bits, "dir-link")
    srv, _ = bit(name)
    (real / "srv.bit").write_bytes(srv)
    before = tree(real / "uploaded")
    assert server_import(db, bits, srv, "srv.bit") == pid
    assert policy_row(server, pid)["source_file"] == "srv.bit"
    assert tree(real / "uploaded") == before


def test_a_bits_folder_swapped_for_a_link_after_the_write_renames_in_the_original(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    decoy = bits.parent / "decoy"
    (decoy / "uploaded").mkdir(parents=True)
    moved = bits.parent / "moved-bits"
    real_rename = uploads._Upload.rename

    def rename(self: Any, pending: Any) -> None:
        bits.rename(moved)
        bits.symlink_to(decoy, target_is_directory=True)
        real_rename(self, pending)

    monkeypatch.setattr(uploads._Upload, "rename", rename)
    assert up(db, bits, v2).outcome == "success"
    assert listing(decoy / "uploaded") == []
    assert listing(moved / "uploaded") == [f"policy-{pid}.bit"]
    assert (moved / "uploaded" / f"policy-{pid}.bit").read_bytes() == v2


def test_finish_leaves_a_directory_named_like_a_temp_and_still_finishes(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s", (sha(v2), pid)
        )
    (bits / "uploaded" / ".tmp-dir").mkdir()
    (bits / "uploaded" / tmp_name(pid, v2)).write_bytes(v2)
    got = finish(db, bits)
    assert got.renamed == 1
    assert stored(bits, pid).read_bytes() == v2
    assert (bits / "uploaded" / ".tmp-dir").is_dir()  # not a file; not *.bit


def test_finish_writes_no_log_line_with_names_or_content(
    db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _, pid, v1 = seed(db, bits)
    canary = f".tmp-canary{tag()}"
    (bits / "uploaded" / canary).write_bytes(b"content-canary")
    caplog.set_level("DEBUG")
    finish(db, bits)
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert canary not in text and "content-canary" not in text
    assert str(pid) not in [str(a) for r in caplog.records for a in (r.args or ())]


# Carry (a): the caller's catalog lock and serialisation (TS §4.1 L526, §8.3) ----


def test_import_upload_and_finish_never_take_the_catalog_lock_themselves(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(f"NoLock {tag()}")
    result: list[Any] = []

    def worker() -> None:
        try:
            with db.session() as s:
                result.append(
                    import_upload(s, FixedClock(), bits, data, b"c", actor=USER)
                )
                result.append(finish_interrupted_uploads(s, bits))
        except BaseException as exc:  # reported below
            result.append(exc)

    with app(server) as probe:
        probe.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(30)
            assert not t.is_alive(), "waited on the catalog lock"
        finally:
            probe.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    assert len(result) == 2 and isinstance(result[0], ImportOutcome), result
    for fn in (import_upload, finish_interrupted_uploads):
        doc = inspect.getdoc(fn) or ""
        assert "caller" in doc and "lock" in doc  # the contract is documented


def test_the_callers_lock_is_held_at_the_temp_write_and_the_rename(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    seen: list[tuple[str, bool]] = []
    real_write, real_rename = uploads._Upload.write, uploads._Upload.rename
    with app(server) as probe:

        def write(self: Any, policy_id: int) -> None:
            seen.append(("write", lock_free(probe)))
            real_write(self, policy_id)

        def rename(self: Any, pending: Any) -> None:
            seen.append(("rename", lock_free(probe)))
            real_rename(self, pending)

        monkeypatch.setattr(uploads._Upload, "write", write)
        monkeypatch.setattr(uploads._Upload, "rename", rename)
        with db.session() as s, catalog_lock(s):
            out = import_upload(s, FixedClock(), bits, v2, b"c", actor=USER)
            assert not lock_free(probe)
        assert lock_free(probe)
    assert out.outcome == "success"
    assert seen == [("write", False), ("rename", False)]


def test_a_concurrent_upload_and_delete_serialise_and_disk_matches_the_catalog(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The upload pauses after its commit, before the rename; a delete of the
    same policy must wait for the lock. Unserialised, the delete would find
    no file and the rename would then leave a file for a deleted policy."""
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    paused, go = threading.Event(), threading.Event()
    order: list[str] = []
    errors: list[BaseException] = []
    real_rename = uploads._Upload.rename

    def rename(self: Any, pending: Any) -> None:
        paused.set()
        assert go.wait(30)
        real_rename(self, pending)
        order.append("renamed")

    monkeypatch.setattr(uploads._Upload, "rename", rename)
    pid_b: list[int] = []

    def uploader() -> None:
        try:
            up(db, bits, v2)
            order.append("upload released")
        except BaseException as exc:
            errors.append(exc)

    class Spy:
        """delete_policy's db, recording the session's backend pid."""

        @contextmanager
        def session(self) -> Iterator[CatalogSession]:
            with db.session() as s:
                pid_b.append(s.conn.info.backend_pid)
                yield s
                order.append("delete done")

    def deleter() -> None:
        try:
            delete_policy(Spy(), pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
        except BaseException as exc:
            errors.append(exc)

    ta = threading.Thread(target=uploader, daemon=True)
    ta.start()
    assert paused.wait(30)
    tb = threading.Thread(target=deleter, daemon=True)
    tb.start()
    with app(probe_server := server) as probe:
        until(lambda: bool(pid_b) and waiting(probe, pid_b[0]), "delete waits")
        assert policy_row(probe_server, pid)["deleted_at"] is None
        go.set()
        ta.join(30)
        tb.join(30)
    assert not ta.is_alive() and not tb.is_alive() and errors == []
    assert order.index("renamed") < order.index("delete done")
    assert policy_row(server, pid)["deleted_at"] is not None
    assert listing(bits / "uploaded") == []  # the file went with the policy


def test_a_concurrent_upload_and_server_import_serialise(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another catalog writer (the watcher's import of a server-folder file
    with the same name) waits while the upload holds the lock after writing
    its temp file; then the server folder wins and the copy is removed."""
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    srv, _ = bit(name)
    (bits / "srv.bit").write_bytes(srv)
    paused, go = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    pid_b: list[int] = []
    order: list[str] = []
    real_write = uploads._Upload.write

    def write(self: Any, policy_id: int) -> None:
        real_write(self, policy_id)
        paused.set()
        assert go.wait(30)

    real_rename = uploads._Upload.rename

    def rename(self: Any, pending: Any) -> None:
        real_rename(self, pending)
        order.append("upload renamed")  # still inside the caller's lock

    monkeypatch.setattr(uploads._Upload, "write", write)
    monkeypatch.setattr(uploads._Upload, "rename", rename)

    def uploader() -> None:
        try:
            up(db, bits, v2)
        except BaseException as exc:
            errors.append(exc)

    def watcher() -> None:
        try:
            with db.session() as s:
                pid_b.append(s.conn.info.backend_pid)
                with catalog_lock(s):
                    order.append("server import locked")
                    import_one(
                        s, FixedClock(), bits, server_file(srv, "srv.bit"),
                        mode=Mode.AUTO, actor=Actor("system", None), file_exists=NONE,
                    )  # fmt: skip
        except BaseException as exc:
            errors.append(exc)

    ta = threading.Thread(target=uploader, daemon=True)
    ta.start()
    assert paused.wait(30)
    tb = threading.Thread(target=watcher, daemon=True)
    tb.start()
    with app(server) as probe:
        until(lambda: bool(pid_b) and waiting(probe, pid_b[0]), "import waits")
        assert order == []
        go.set()
        ta.join(30)
        tb.join(30)
    assert not ta.is_alive() and not tb.is_alive() and errors == []
    assert order == ["upload renamed", "server import locked"]
    row = policy_row(server, pid)
    assert (row["source_file"], row["source_sha256"]) == ("srv.bit", sha(srv))
    assert listing(bits / "uploaded") == []


def test_two_concurrent_uploads_of_one_policy_serialise(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first upload pauses after its temp write (lock held, not yet
    committed); the second waits on the lock, then runs after the first has
    renamed. The last writer's bytes are both the row and the file."""
    name, pid, _ = seed(db, bits)
    v2, _ = bit(name, status="disabled")
    v3, _ = bit(name)
    paused, go = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    order: list[str] = []
    pid_b: list[int] = []
    real_write, real_rename = uploads._Upload.write, uploads._Upload.rename

    def write(self: Any, policy_id: int) -> None:
        real_write(self, policy_id)
        order.append(f"write {self.sha256 == sha(v2) and 'v2' or 'v3'}")
        if self.sha256 == sha(v2):
            paused.set()
            assert go.wait(30)

    def rename(self: Any, pending: Any) -> None:
        tag_ = self.sha256 == sha(v2) and "v2" or "v3"
        real_rename(self, pending)
        order.append(f"rename {tag_}")

    monkeypatch.setattr(uploads._Upload, "write", write)
    monkeypatch.setattr(uploads._Upload, "rename", rename)

    def first() -> None:
        try:
            up(db, bits, v2)
        except BaseException as exc:
            errors.append(exc)

    def second() -> None:
        try:
            with db.session() as s:
                pid_b.append(s.conn.info.backend_pid)
                with catalog_lock(s):
                    import_upload(s, FixedClock(), bits, v3, b"c", actor=USER)
        except BaseException as exc:
            errors.append(exc)

    ta = threading.Thread(target=first, daemon=True)
    ta.start()
    assert paused.wait(30)
    tb = threading.Thread(target=second, daemon=True)
    tb.start()
    with app(server) as probe:
        until(lambda: bool(pid_b) and waiting(probe, pid_b[0]), "second waits")
        assert order == ["write v2"]
        go.set()
        ta.join(30)
        tb.join(30)
    assert not ta.is_alive() and not tb.is_alive() and errors == []
    assert order == ["write v2", "rename v2", "write v3", "rename v3"]
    assert policy_row(server, pid)["source_sha256"] == sha(v3)
    assert listing(bits / "uploaded") == [f"policy-{pid}.bit"]
    assert stored(bits, pid).read_bytes() == v3


def test_prepared_is_used_and_parsing_needs_no_lock(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, _ = bit(f"Prep {tag()}")
    prep = prepare(data)
    calls: list[Any] = []
    from bitscan_manager.services.importer import pipeline

    monkeypatch.setattr(pipeline, "prepare", lambda d: calls.append(d))
    out = up(db, bits, data, prepared=prep)
    assert out.outcome == "success" and calls == []
    assert stored(bits, out.policy_id or 0).read_bytes() == data


def test_the_stored_bytes_hash_is_the_recorded_hash(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    data, _ = bit(f"Hash {tag()}")
    s0 = snap(server)
    out = up(db, bits, data)
    row = imports_since(server, s0)[0]
    on_disk = stored(bits, out.policy_id or 0).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == row["file_sha256"] == sha(data)
    assert row["mode"] == "manual" and row["imported_by"] == 7
