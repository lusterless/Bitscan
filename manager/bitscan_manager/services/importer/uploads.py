"""Policy uploads and the start-up finish of interrupted ones (TS §4.1 L522,
L526, L528; §8.7 L1344, L1377, L1395; REQ-163, REQ-165 (1); open questions
#98 (j), #99).

The client's file name is only metadata (`bit_import.file_name`, #99 (d)).
Under the catalog lock the upload goes through the one pipeline: just before
its transaction commits, the bytes are written to `uploaded/.tmp-<id>-<sha>`
(`O_CREAT | O_EXCL | O_NOFOLLOW`, mode 0600, fsynced). After the commit they
are renamed to `uploaded/policy-<id>.bit`, replacing that policy's previous
upload. A rollback deletes the temp file. A failed rename after the commit
leaves it for the start-up finish (TS L528), which renames a temp file whose
hash is its policy's `source_sha256` and deletes every other one.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bitscan_manager.repositories import catalog
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Clock, SessionDatabase
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.own_changes import OWN_CHANGES
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    import_one,
    prepare,
)
from bitscan_manager.services.importer.store import Target

log = logging.getLogger(__name__)
_UPLOADED: Final = "uploaded"
_TEMP_PREFIX: Final = ".tmp-"
_HEX: Final = frozenset("0123456789abcdef")
_NAME_MAX: Final = 255  # bit_import.file_name, #99 (d)
# Never follow a symlink at the path; both flags are POSIX only.
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_BINARY: Final = getattr(os, "O_BINARY", 0)
_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)  # a FIFO swapped in never blocks


def client_file_name(raw: bytes | str | None) -> str:
    """#99 (d): decoded as UTF-8 with replacement; U+0000 to U+001F, DEL
    and lone surrogates become U+FFFD; at most 255 characters; a missing
    name is the empty string. It is never used as a path or logged."""
    if raw is None:
        return ""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    clean = "".join(
        "�" if ch < "\x20" or ch == "\x7f" or "\ud800" <= ch <= "\udfff" else ch
        for ch in text
    )
    return clean[:_NAME_MAX]


def _temp_name(policy_id: int, sha256: str) -> str:
    return f"{_TEMP_PREFIX}{policy_id}-{sha256}"


def _temp_policy_id(name: str) -> int | None:
    """The id in `.tmp-<policy_id>-<sha256>` (decimal, no leading zero, 64
    lowercase hex digits), or None for any other name."""
    digits, dash, sha = name.removeprefix(_TEMP_PREFIX).partition("-")
    if (
        name.startswith(_TEMP_PREFIX)
        and dash
        and 1 <= len(digits) <= 19
        and digits.isascii()
        and digits.isdigit()
        and digits[0] != "0"
        and len(sha) == 64
        and set(sha) <= _HEX
    ):
        return int(digits)
    return None


def _final_name(policy_id: int) -> str:
    return f"policy-{policy_id}.bit"


def _sync_folder(folder: Path) -> None:
    if os.name == "posix":  # a folder cannot be opened for fsync on Windows
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` (never an existing file or symlink), write and fsync;
    a failed write removes the file it created."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _BINARY
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        path.unlink()
        raise
    os.close(fd)


class UploadStage:
    """One upload's bytes around a pipeline import (TS §4.1 L522; TASK-155
    r1, shared with folders.py): pass `before_commit` and `after_commit` to
    `import_one`. Use it through `staged_upload`, which discards the temp file
    when the import fails before its commit."""

    def __init__(self, bits_dir: Path, sha256: str, data: bytes) -> None:
        self._folder = bits_dir / _UPLOADED
        self._sha256 = sha256
        self._data = data
        self._policy_id: int | None = None
        self._temp: Path | None = None  # set only once this stage created it
        self.committed = False

    def before_commit(self, policy_id: int) -> None:
        """The last step of transaction 1: create, write and fsync the temp
        file `uploaded/.tmp-<policy_id>-<sha256>`."""
        path = self._folder / _temp_name(policy_id, self._sha256)
        _write_new(path, self._data)
        self._policy_id, self._temp = policy_id, path
        _sync_folder(self._folder)

    def after_commit(self, outcome: ImportOutcome) -> None:
        """After the commit: rename it to `uploaded/policy-<policy_id>.bit`,
        replacing that policy's previous upload. A failed rename leaves the
        temp file for the start-up finish (TS §4.1 L528)."""
        self.committed = True
        if self._temp is None or self._policy_id is None:  # unreachable
            raise LookupError("committed upload has no temp file")
        final = _final_name(self._policy_id)
        OWN_CHANGES.wrote(f"{_UPLOADED}/{final}", self._sha256)  # #102 (c)
        os.replace(self._temp, self._folder / final)
        _sync_folder(self._folder)

    def discard(self) -> None:
        """Rolled back: remove the temp file this stage created, if any; never
        after the commit."""
        if self._temp is not None and not self.committed:
            try:
                self._temp.unlink()
            except OSError as exc:
                log.warning("upload temp removal failed: %s", type(exc).__name__)


@contextmanager
def staged_upload(bits_dir: Path, sha256: str, data: bytes) -> Iterator[UploadStage]:
    """Wrap one `import_one` call that stores `data` as an upload; the caller
    holds the catalog lock for the whole block (TS §4.1 L526)."""
    stage = UploadStage(bits_dir, sha256, data)
    try:
        yield stage
    except BaseException:
        stage.discard()
        raise


def upload(
    db: SessionDatabase,
    clock: Clock,
    bits_dir: Path,
    data: bytes,
    client_name: bytes | str | None,
    actor: Actor,
) -> ImportOutcome:
    """Import one uploaded `.bit` (mode `manual`, never skipped). Parsing runs
    before the lock. Raises PolicyManagedOnServer for a server-folder policy
    (409, #99 (e)); a database or disk error propagates (#98 (j))."""
    sha256 = hashlib.sha256(data).hexdigest()
    prepared = prepare(data)
    file = FileInput(
        data, sha256, client_file_name(client_name), Target("upload", None, sha256)
    )
    with (
        db.session() as session,
        catalog_lock(session),
        staged_upload(bits_dir, sha256, data) as stage,
    ):
        return import_one(
            session,
            clock,
            bits_dir,
            file,
            mode="manual",
            actor=actor,
            file_exists=lambda rel: (bits_dir / rel).exists(),
            prepared=prepared,
            before_commit=stage.before_commit,
            after_commit=stage.after_commit,
        )


@dataclass(frozen=True, slots=True)
class FinishResult:
    renamed: int  # temp files moved to uploaded/policy-<id>.bit
    deleted: int  # every other temp file


def _content_sha256(path: Path) -> str | None:
    """The SHA-256 of a regular file of at most 5 MiB, read without following
    a symlink; None for anything else."""
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _BINARY)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BIT_BYTES:
            return None
        with open(fd, "rb", closefd=False) as handle:
            return hashlib.sha256(handle.read(MAX_BIT_BYTES + 1)).hexdigest()
    finally:
        os.close(fd)


def finish_interrupted(session: CatalogSession, bits_dir: Path) -> FinishResult:
    """Start-up step 1 (TS §4.1 L528, REQ-165 (1)); the caller holds
    `catalog_lock(session)` and runs it before any other catalog work. A
    `.tmp-<policy_id>-<sha256>` whose content hash equals that live policy's
    `source_sha256`, with `source_file` `uploaded/policy-<id>.bit`, is
    renamed into place; any other temp file (a foreign name, a symlink, a
    mismatch) is deleted, never followed."""
    folder = bits_dir / _UPLOADED
    renamed = deleted = 0
    with os.scandir(folder) as found:
        entries = sorted(found, key=lambda e: e.name)
    for entry in entries:
        if not entry.name.startswith(_TEMP_PREFIX):
            continue
        path = folder / entry.name
        policy_id = _temp_policy_id(entry.name)
        target: Path | None = None
        if policy_id is not None and entry.is_file(follow_symlinks=False):
            with session.transaction() as tx:
                row = catalog.policy_by_id_for_update(tx.conn, policy_id)
            if (
                row is not None
                and row.deleted_at is None
                and row.source_file == f"{_UPLOADED}/{_final_name(policy_id)}"
                and row.source_sha256 == _content_sha256(path)
            ):
                target = folder / _final_name(policy_id)
                sha256 = row.source_sha256
        try:
            if target is not None:
                OWN_CHANGES.wrote(f"{_UPLOADED}/{target.name}", sha256)  # #102 (c)
                os.replace(path, target)
                renamed += 1
            else:
                path.unlink()
                deleted += 1
        except OSError as exc:  # a folder named .tmp-x, or a vanished file
            log.warning("upload temp finish failed: %s", type(exc).__name__)
    if renamed or deleted:
        _sync_folder(folder)
    log.info("interrupted uploads: %d renamed, %d deleted", renamed, deleted)
    return FinishResult(renamed, deleted)
