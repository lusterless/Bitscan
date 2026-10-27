"""Uploaded `.bit` files on disk (TS §4.1 L522, L526, L528; §8.7 L1344;
REQ-163, REQ-165 (1); open question #99 (d), (e)).

Every function here runs under the catalog lock, which its caller holds
(`catalog_lock(session)`). An upload is written to
`uploaded/.tmp-<policy_id>-<sha256>` (`O_EXCL | O_NOFOLLOW`, mode 0600) and
flushed as the last step of the import transaction, renamed to
`uploaded/policy-<policy_id>.bit` after it commits, and deleted if it does
not commit. The client's file name is only `bit_import.file_name`; it is
never part of a path. Nothing here logs file names or content.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from bitscan_manager.db.pool import DatabaseUnavailable
from bitscan_manager.repositories import catalog
from bitscan_manager.runtime import CatalogSession, Clock
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    Mode,
    Pending,
    Prepared,
    import_one,
)
from bitscan_manager.services.importer.store import Target

log = logging.getLogger(__name__)
_TMP = ".tmp-"
_HEX = frozenset("0123456789abcdef")
_NAME_CAP = 255
_BIGINT_MAX = 2**63 - 1  # policy_id is BIGINT; never send a larger id
_CONTROLS = {c: "�" for c in [*range(0x20), 0x7F]}  # C0 (with NUL), DEL


def client_file_name(raw: bytes | str | None) -> str:
    """#99 (d): the part's `filename` as UTF-8 with replacement, U+0000, C0
    controls and DEL as U+FFFD, cut to 255 characters; missing is ""."""
    if raw is None:
        return ""
    if isinstance(raw, str):  # lone surrogates become U+FFFD too
        raw = raw.encode("utf-8", "surrogatepass")
    return raw.decode("utf-8", "replace").translate(_CONTROLS)[:_NAME_CAP]


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_uploads(bits_dir: Path) -> int:
    """`uploaded/` as a directory fd. A missing, symlinked or non-directory
    `uploaded/` raises OSError (user ruling "Folder guard"); every later
    path is relative to this fd, so no link in the folder path is followed."""
    return os.open(bits_dir / "uploaded", _DIR_FLAGS)


@dataclass
class _Upload:
    """The before_commit / after_commit hooks of one upload."""

    bits_dir: Path
    data: bytes
    sha256: str
    dir_fd: int | None = None  # `uploaded/`, opened in write()
    temp: str | None = None  # set once this upload created the temp file
    committed: bool = False
    kept: bool = False  # the commit outcome is unknown

    def write(self, policy_id: int) -> None:
        self.dir_fd = _open_uploads(self.bits_dir)
        name = f"{_TMP}{policy_id}-{self.sha256}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        # A planted file or symlink at the temp name: OSError.
        fd = os.open(name, flags, 0o600, dir_fd=self.dir_fd)
        self.temp = name
        try:
            view = memoryview(self.data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.dir_fd)

    def rename(self, pending: Pending) -> None:
        self.committed = True
        if self.temp is None or self.dir_fd is None or pending.store is None:
            raise RuntimeError("an upload committed without its temp file")
        final = f"policy-{pending.policy_id}.bit"
        if pending.store.source_file != f"uploaded/{final}" or (
            self.temp != f"{_TMP}{pending.policy_id}-{self.sha256}"
        ):
            raise RuntimeError("the stored source_file is not this upload's")
        fd = self.dir_fd  # rename(2) replaces a symlink at `final` itself
        os.replace(self.temp, final, src_dir_fd=fd, dst_dir_fd=fd)
        self.temp = None
        os.fsync(fd)

    def discard(self) -> None:
        """After the import: delete the temp file unless the commit happened
        (start-up then renames it) or its outcome is unknown; close the fd."""
        try:
            if self.temp is not None and not (self.committed or self.kept):
                os.unlink(self.temp, dir_fd=self.dir_fd)
        except OSError as exc:
            log.error("upload temp removal failed: %s", type(exc).__name__)
        finally:
            if self.dir_fd is not None:
                os.close(self.dir_fd)


def import_upload(
    session: CatalogSession,
    clock: Clock,
    bits_dir: Path,
    data: bytes,
    client_name: bytes | str | None,
    *,
    actor: Actor,
    prepared: Prepared | None = None,
) -> ImportOutcome:
    """A manual import of an uploaded file. The caller holds the catalog lock
    and passes `prepared` from `prepare(data)`, run before taking it. Raises
    PolicyManagedOnServer (409, #99 (e)) with nothing written to disk."""
    sha = hashlib.sha256(data).hexdigest()
    file = FileInput(
        data, sha, client_file_name(client_name), Target("upload", None, sha)
    )
    up = _Upload(bits_dir, data, sha)
    try:
        return import_one(
            session,
            clock,
            bits_dir,
            file,
            mode=Mode.MANUAL,
            actor=actor,
            file_exists=lambda rel: (bits_dir / rel).is_file(),
            prepared=prepared,
            before_commit=up.write,
            after_commit=up.rename,
        )
    except DatabaseUnavailable:
        up.kept = up.temp is not None  # COMMIT may have happened
        raise
    finally:
        up.discard()


def _temp_hash(name: str, dir_fd: int) -> str | None:
    """The SHA-256 of a regular temp file, read without following a link."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = fh.read(MAX_BIT_BYTES + 1)
    return None if len(data) > MAX_BIT_BYTES else hashlib.sha256(data).hexdigest()


def _parse_temp(name: str) -> tuple[int, str] | None:
    digits, _, sha = name.removeprefix(_TMP).partition("-")
    if not (digits.isascii() and digits.isdigit() and len(digits) <= 19):
        return None
    if str(int(digits)) != digits or int(digits) > _BIGINT_MAX:
        return None
    return (int(digits), sha) if len(sha) == 64 and set(sha) <= _HEX else None


@dataclass(frozen=True, slots=True)
class FinishedUploads:
    renamed: int
    deleted: int


def finish_interrupted_uploads(
    session: CatalogSession, bits_dir: Path
) -> FinishedUploads:
    """TS §4.1 L528, REQ-165 (1): rename each `uploaded/.tmp-<id>-<sha256>`
    whose content hashes to `<sha256>` and to the live policy `<id>`'s
    `source_sha256`, with `source_file` `uploaded/policy-<id>.bit`; delete
    every other `.tmp-*` entry (a symlink is removed, never followed). The
    caller holds the catalog lock and has no transaction open on `session`:
    start-up (TASK-158) and the rebuild before it reads the folders (TASK-157,
    user ruling "Rebuild finishes interrupted uploads first"). A missing,
    symlinked or non-directory `uploaded/` is unreadable: one log line and
    nothing is touched or created (rulings "A missing `bits/uploaded/`
    folder" and "Folder guard")."""
    try:
        dir_fd = _open_uploads(bits_dir)
    except OSError as exc:
        log.warning(
            "interrupted uploads: uploaded folder unreadable: %s", type(exc).__name__
        )
        return FinishedUploads(0, 0)
    try:
        return _finish(session, dir_fd)
    finally:
        os.close(dir_fd)


def _finish(session: CatalogSession, dir_fd: int) -> FinishedUploads:
    temps = sorted(n for n in os.listdir(dir_fd) if n.startswith(_TMP))
    keep: dict[str, int] = {}
    with session.transaction() as tx:
        for name in temps:
            parsed = _parse_temp(name)
            if parsed is None or _temp_hash(name, dir_fd) != parsed[1]:
                continue
            row = catalog.policy_by_id_for_update(tx.conn, parsed[0])
            if (
                row is not None
                and row.deleted_at is None
                and row.source_file == f"uploaded/policy-{parsed[0]}.bit"
                and row.source_sha256 == parsed[1]
            ):
                keep[name] = parsed[0]
    for name in temps:
        if name in keep:
            final = f"policy-{keep[name]}.bit"
            os.replace(name, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            continue
        try:  # a directory or an unremovable entry is left; it is not *.bit
            os.unlink(name, dir_fd=dir_fd)
        except OSError as exc:
            log.error("upload temp removal failed: %s", type(exc).__name__)
    if temps:
        os.fsync(dir_fd)
    log.info(
        "interrupted uploads: renamed=%d deleted=%d", len(keep), len(temps) - len(keep)
    )
    return FinishedUploads(len(keep), len(temps) - len(keep))
