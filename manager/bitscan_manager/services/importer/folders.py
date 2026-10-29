"""Folder discovery and the `auto` reconcile (TS §4.1 L515, L524, L528, §4.2,
§4.3 L550, §4.6 L612, L615; SR §3.6 step 2, §4.1 BIT007; REQ-159, REQ-164,
REQ-165 (3); open questions #15, #102 (b), #103; user "Crash window" ruling
2026-10-27).

The server folder is `bits_dir`; uploads live in `bits_dir/uploaded/`. Only
`*.bit` regular files directly in either folder count: not hidden, not
symlinks, FIFOs or devices (opened with O_NOFOLLOW), not in subfolders. A name
the database cannot store is skipped with one log line and no row (#102 (b)).
Every function runs under the catalog lock its caller holds (start-up,
watcher, rebuild). Nothing here logs file names or content.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from bitscan_manager.repositories import catalog, catalog_integrity
from bitscan_manager.runtime import CatalogSession, Clock, Tx
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.delete import (
    PolicyAlreadyDeleted,
    PolicyNotFound,
    delete_in_tx,
    remove_after_commit,
)
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.own_changes import OWN_CHANGES
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    import_one,
    prepare,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer, Target
from bitscan_manager.services.importer.uploads import UploadStage, staged_upload

log = logging.getLogger(__name__)
UPLOADED: Final = "uploaded"
LEFTOVER: Final = "leftover of an interrupted delete"
SYSTEM: Final = Actor("system", None)  # #101: folder imports have no user
_NAME_MAX: Final = 255  # bytes (#102 (b))
_ID_MAX: Final = 2**63 - 1  # policy_id BIGINT
_OPEN: Final = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)  # a FIFO swapped in never blocks
    | getattr(os, "O_BINARY", 0)
)


@dataclass(frozen=True, slots=True)
class UploadClass:
    """How an `uploaded/` file reaches decide() (TASK-156 row (a)-(c))."""

    kind: Literal["live", "leftover", "other"]
    policy_id: int | None  # the policy-<n> id for live and leftover


@dataclass(slots=True)
class ReconcileResult:
    outcomes: list[tuple[str, ImportOutcome]] = field(default_factory=list)
    not_imported: list[str] = field(default_factory=list)  # no row (see import_path)
    deleted: list[int] = field(default_factory=list)  # policies whose file went
    leftovers: list[Difference] = field(default_factory=list)  # #103 differences


def classify_upload(tx: Tx, name: str) -> UploadClass:
    """Classify the file `uploaded/<name>`, reading its policy row under the
    catalog lock. Shared by the reconcile and the rebuild (TASK-157). (a)
    `policy-<n>.bit` (decimal, no leading zero) of a live policy whose
    source_file is that path: "live". (b) Of a deleted policy: "leftover";
    a deleted policy never comes back by itself. (c) Anything else: "other"."""
    digits = name.removeprefix("policy-").removesuffix(".bit")
    if not (
        name == f"policy-{digits}.bit"
        and digits.isascii()
        and digits.isdigit()
        and digits[0] != "0"
        and int(digits) <= _ID_MAX
    ):
        return UploadClass("other", None)
    row = catalog.policy_by_id_for_update(tx.conn, int(digits))
    if row is None:
        return UploadClass("other", None)
    if row.deleted_at is not None:
        return UploadClass("leftover", row.policy_id)
    if row.source_file == f"{UPLOADED}/{name}":
        return UploadClass("live", row.policy_id)
    return UploadClass("other", None)


def discover(bits_dir: Path) -> list[str]:
    """The relative paths of the candidate files of both folders (#102 (b))."""
    found: list[str] = []
    for folder, prefix in ((bits_dir, ""), (bits_dir / UPLOADED, f"{UPLOADED}/")):
        try:
            with os.scandir(folder) as entries:
                names = [e.name for e in entries if e.is_file(follow_symlinks=False)]
        except FileNotFoundError:
            continue
        for name in names:
            if not name.endswith(".bit") or name.startswith("."):
                continue
            if not storable(name):
                log.warning("folder file skipped: its name cannot be stored")
                continue
            found.append(prefix + name)
    return found


def storable(name: str) -> bool:
    """Valid UTF-8 (a POSIX name that is not decodes to lone surrogates), no
    control character, at most 255 bytes (#102 (b))."""
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError:
        return False
    controls = any(ch < "\x20" or "\x7f" <= ch <= "\x9f" for ch in name)
    return size <= _NAME_MAX and not controls


def is_bit_file(bits_dir: Path, rel: str) -> bool:
    """`rel` is a regular file now, not a symlink (BIT007, deletions)."""
    try:
        return stat.S_ISREG(os.lstat(bits_dir / rel).st_mode)
    except OSError:
        return False


def read_file(path: Path) -> tuple[bytes | None, str] | None:
    """The one read (TS §4.1 step 2): (data, sha256); data None over 5 MiB
    (#99 (b), the hash still covers the whole file). None if it is not a
    regular file when opened."""
    try:
        fd = os.open(path, _OPEN)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        digest, buf = hashlib.sha256(), bytearray()
        with open(fd, "rb", closefd=False) as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
                if len(buf) <= MAX_BIT_BYTES:
                    buf += chunk
        return (bytes(buf) if len(buf) <= MAX_BIT_BYTES else None), digest.hexdigest()
    finally:
        os.close(fd)


def import_path(
    session: CatalogSession, clock: Clock, bits_dir: Path, rel: str
) -> ImportOutcome | Difference | None:
    """One discovered file in `auto` mode: an outcome, a removed leftover as
    its #103 difference, or None when it was skipped without a row (gone,
    not a regular file, or a server-folder policy's uploaded copy, refused
    and audit-logged by the pipeline). A server file is a
    `Target("server", name)`; an `uploaded/` file never is."""
    folder, _, name = rel.rpartition("/")
    kind = UploadClass("other", None)
    if folder:
        with session.transaction() as tx:
            kind = classify_upload(tx, name)
        if kind.kind == "leftover":
            return _remove_leftover(bits_dir, rel, kind.policy_id)
    read = read_file(bits_dir / rel)
    if read is None:
        log.warning("folder file skipped: not a regular file when read")
        return None
    data, sha256 = read
    target = Target("upload", None, sha256) if folder else Target("server", rel, sha256)
    staging: AbstractContextManager[UploadStage | None] = (
        staged_upload(bits_dir, sha256, data)
        if folder and data is not None
        else nullcontext(None)
    )
    try:
        with staging as stage:
            moved = None if stage is None else Relocate(stage, bits_dir / rel, kind)
            return import_one(
                session,
                clock,
                bits_dir,
                FileInput(data, sha256, rel, target),
                mode="auto",
                actor=SYSTEM,
                file_exists=lambda path: is_bit_file(bits_dir, path),
                prepared=prepare(data),
                before_commit=None if moved is None else moved.before_commit,
                after_commit=None if moved is None else moved.after_commit,
            )
    except PolicyManagedOnServer:  # case (c): the old copy stays for #103
        log.info("uploaded copy refused: its policy lives in the server folder")
        return None


@dataclass(slots=True)
class Relocate:
    """An `uploaded/` file imported as a policy whose upload name is another
    (case (c), ruling "TASK-156 case (c) success"): the bytes are staged as
    `uploaded/policy-<id>.bit` like an upload (TS §4.1 L522), and after the
    rename a case (c) file is unlinked, so disk matches the catalog (L526).
    A file already at its policy's name is left as it is."""

    stage: UploadStage
    path: Path
    kind: UploadClass
    staged: bool = False

    def before_commit(self, policy_id: int) -> None:
        if self.path.name != f"policy-{policy_id}.bit":
            self.stage.before_commit(policy_id)
            self.staged = True

    def after_commit(self, outcome: ImportOutcome) -> None:
        if not self.staged:
            return
        self.stage.after_commit(outcome)
        if self.kind.kind == "other":
            OWN_CHANGES.removed(f"{UPLOADED}/{self.path.name}")  # before (#102 (c))
            try:
                self.path.unlink()  # never follows a symlink
            except OSError as exc:
                log.warning("relocated upload removal failed: %s", type(exc).__name__)


def _remove_leftover(bits_dir: Path, rel: str, policy_id: int | None) -> Difference:
    """Case (b): no import, no bit_import row, the policy stays deleted."""
    OWN_CHANGES.removed(rel)  # before the unlink (#102 (c))
    try:
        (bits_dir / rel).unlink()
    except OSError as exc:
        log.warning("leftover removal failed: %s", type(exc).__name__)
    log.warning("removed the leftover upload of deleted policy %s", policy_id)
    return Difference(rel, LEFTOVER)


def reconcile(session: CatalogSession, clock: Clock, bits_dir: Path) -> ReconcileResult:
    """Start-up step 3 (TS §4.1 L528, REQ-165 (3)): import new or changed
    files, then delete live policies whose file is gone (TS §4.3 L550). The
    imports come first, so a file that replaces a removed one moves its
    policy (REQ-159 (2)). #15 order: files that are a live policy's
    source_file first, then by the bytes of the UTF-8 relative path."""
    with session.transaction() as tx:
        recorded = {r.source_file for r in catalog_integrity.integrity_rows(tx.conn)}
    paths = discover(bits_dir)
    paths.sort(key=lambda p: (p not in recorded, p.encode("utf-8")))
    result = ReconcileResult()
    for rel in paths:
        found = import_path(session, clock, bits_dir, rel)
        if isinstance(found, Difference):
            result.leftovers.append(found)
        elif found is None:
            result.not_imported.append(rel)
        else:
            result.outcomes.append((rel, found))
    with session.transaction() as tx:
        live = catalog_integrity.integrity_rows(tx.conn)
    for row in live:
        if is_bit_file(bits_dir, row.source_file):
            continue
        try:
            with session.transaction() as tx:
                gone = delete_in_tx(
                    tx,
                    row.policy_id,
                    actor=SYSTEM.audit,
                    reason="file removed",
                    now=clock.now(),
                )
        except (PolicyNotFound, PolicyAlreadyDeleted):
            continue
        remove_after_commit(bits_dir, gone.remove_after_commit)
        result.deleted.append(row.policy_id)
    return result
