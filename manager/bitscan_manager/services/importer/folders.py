"""Folder discovery and the automatic reconcile (TS §4.1 L515, L524, L528,
§4.2, §4.3 L550; SR §3.6; REQ-159, REQ-164, REQ-165 (3); open questions #15,
#102, #103 and the user's "Crash window" ruling of 2026-10-27).

Every function here runs under the catalog lock that its caller holds
(`catalog_lock(session)`). None of them takes or releases it, so the catalog
cannot change between a classification and the import that follows. Only
`*.bit` regular files directly in the bits folder or in `uploaded/` count.
Each is opened once with O_NOFOLLOW and never re-read. Nothing here writes a
file: the only removals are a leftover's and the pipeline's
`remove_after_commit`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import unicodedata
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from bitscan_manager.repositories import catalog
from bitscan_manager.repositories.catalog_integrity import integrity_rows
from bitscan_manager.runtime import CatalogSession, Clock
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.delete import (
    DeleteResult,
    delete_in_tx,
    remove_after_commit,
)
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    Mode,
    Prepared,
    import_one,
    prepare,
)
from bitscan_manager.services.importer.store import Conn, Target

log = logging.getLogger(__name__)
UPLOADED = "uploaded/"
BITS_ROOT = "./"  # the bits folder itself, as listed in `unreadable_folders`
LEFTOVER_CHECK = "leftover of an interrupted delete"
type UploadKind = Literal["live", "leftover", "stray"]
_SYSTEM = Actor("system", None)
_MAX_ID = 2**63 - 1  # policy_id is BIGSERIAL
_OPEN = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)  # a FIFO swapped in never blocks the open
    | getattr(os, "O_CLOEXEC", 0)
)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    outcomes: tuple[ImportOutcome, ...]  # one per file that reached the pipeline
    deleted: tuple[DeleteResult, ...]  # policies whose files disappeared
    leftovers: tuple[Difference, ...]  # #103 differences, for TASK-158's alert
    strays: tuple[str, ...]  # skipped uploaded/ files, for the #103 check
    renamed: tuple[str, ...]  # skipped live uploads with an edited name, for #103
    unreadable_folders: tuple[str, ...]  # BITS_ROOT and/or UPLOADED, for #103


def _wanted(name: str) -> bool:
    """#102 (b): `*.bit`, case-sensitive, not hidden; storable as `file_name`."""
    if not name.endswith(".bit") or name.startswith("."):
        return False
    try:
        raw = name.encode("utf-8")  # a non-UTF-8 name holds surrogate escapes
    except UnicodeEncodeError:
        return False
    return len(raw) <= 255 and not any(unicodedata.category(c) == "Cc" for c in name)


def _real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _names(folder: Path) -> list[str]:
    if not _real_dir(folder):  # missing, or a symlink: never followed
        return []
    found: list[str] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue  # symlinks, FIFOs, devices and subfolders
            name = entry.name
            if _wanted(name):
                found.append(name)
            elif name.endswith(".bit") and not name.startswith("."):
                log.warning("folder file skipped: its name cannot be stored")
    return found


def unreadable(bits_dir: Path) -> tuple[str, ...]:
    """The folders (`BITS_ROOT`, `UPLOADED`) that are missing, not a real
    directory, or a symlink (lstat, never followed). Nothing is imported from
    such a folder and none of its policies is deleted; a real empty folder is
    readable (user, decisions 2026-10-27 "Folder guard")."""
    folders = ((BITS_ROOT, bits_dir), (UPLOADED, bits_dir / UPLOADED.rstrip("/")))
    return tuple(label for label, path in folders if not _real_dir(path))


def _folder(rel: str) -> str:
    return UPLOADED if rel.startswith(UPLOADED) else BITS_ROOT


def discover(bits_dir: Path) -> list[str]:
    """The `*.bit` files of both folders, as paths relative to `bits_dir`."""
    uploads = [UPLOADED + n for n in _names(bits_dir / UPLOADED.rstrip("/"))]
    return _names(bits_dir) + uploads


def present(bits_dir: Path, rel: str) -> bool:
    """Whether `rel` is a file `discover` would find (the `file_exists` of
    `decide`, and the test for a disappeared file)."""
    folder, _, name = rel.rpartition("/")
    if folder not in ("", UPLOADED.rstrip("/")) or not _wanted(name):
        return False
    if folder and not _real_dir(bits_dir / folder):
        return False
    try:
        return stat.S_ISREG(os.lstat(bits_dir / rel).st_mode)
    except OSError:
        return False


def read_input(bits_dir: Path, rel: str) -> FileInput | None:
    """Read `rel` once into a `FileInput`: a server target for a file in the
    bits folder, an upload target for `uploaded/`. Over 5 MiB, `data` is None
    and the hash covers the whole file (#99 (b)). None if it is gone or is
    not a regular file."""
    digest = hashlib.sha256()
    try:
        with os.fdopen(os.open(bits_dir / rel, _OPEN), "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None
            head = fh.read(MAX_BIT_BYTES + 1)
            digest.update(head)
            data = head if len(head) <= MAX_BIT_BYTES else None
            while data is None and (chunk := fh.read(1 << 20)):
                digest.update(chunk)
    except OSError as exc:
        log.warning("folder file not read: %s", type(exc).__name__)
        return None
    sha = digest.hexdigest()
    if rel.startswith(UPLOADED):  # never a server target (r3)
        return FileInput(data, sha, rel, Target("upload", None, sha))
    return FileInput(data, sha, rel, Target("server", rel, sha))


def upload_policy_id(rel: str) -> int | None:
    """`n` of `uploaded/policy-<n>.bit` (decimal, no leading zeros), else None."""
    digits = rel.removeprefix(UPLOADED + "policy-").removesuffix(".bit")
    if rel != f"{UPLOADED}policy-{digits}.bit" or not digits.isascii():
        return None
    if not digits.isdigit() or digits != str(int(digits)) or int(digits) > _MAX_ID:
        return None
    return int(digits)


def classify_upload(conn: Conn, rel: str) -> UploadKind:
    """The one classification of an `uploaded/` file, shared by the reconcile
    and the rebuild (TASK-157), run in the caller's transaction under the
    catalog lock. "live": a live policy's own `source_file`, imported as an
    upload target (in `auto` mode skipped when unchanged) unless `renamed`.
    "leftover": the file
    of a deleted policy, never imported (`remove_leftover`). "stray": any other
    file (no such policy, or not its source_file), never imported: logged,
    skipped, no row, left for the #103 check (user, decisions 2026-10-27)."""
    policy_id = upload_policy_id(rel)
    row = (
        None if policy_id is None else catalog.policy_by_id_for_update(conn, policy_id)
    )
    if row is None:
        return "stray"
    if row.deleted_at is not None:
        return "leftover"
    return "live" if row.source_file == rel else "stray"


def renamed(conn: Conn, rel: str, prepared: Prepared) -> bool:
    """Whether a "live" upload's parsed `<PolicyName>` differs from its
    policy's current name. Such a file is never imported: skipped and reported
    like a stray, the policy keeps its rows (user, decisions 2026-10-27; TS
    §4.3 renames an uploaded policy only by delete plus upload). A file with
    no valid name is not renamed: the pipeline rejects it."""
    name = prepared.rules.policy_name if prepared.rules is not None else None
    policy_id = upload_policy_id(rel)
    if name is None or policy_id is None:
        return False
    row = catalog.policy_by_id_for_update(conn, policy_id)
    return row is not None and row.policy_name != name


def remove_leftover(bits_dir: Path, rel: str) -> Difference:
    """Remove a leftover of an interrupted delete: no import, no `bit_import`
    row, the policy stays deleted; one log line and one #103 difference."""
    remove_after_commit(bits_dir, (rel,))
    log.warning("removed a leftover of an interrupted delete: %s", rel)
    return Difference(rel, LEFTOVER_CHECK)


def reconcile(session: CatalogSession, clock: Clock, bits_dir: Path) -> ReconcileResult:
    """TS §4.1 L528 in `auto` mode, under the caller's catalog lock: import new
    or changed files, then delete the policies whose files disappeared."""
    blind = unreadable(bits_dir)
    for label in blind:
        log.warning("folder unreadable, not reconciled: %s", label)  # a constant
    files = discover(bits_dir)  # finds nothing in an unreadable folder
    with session.transaction() as tx:
        live = {r.source_file for r in integrity_rows(tx.conn)}
    # #15: a file that is already a live policy's source_file first, then
    # UTF-8 path bytes. Server files before uploads: the server folder wins
    # (TS §4.1 L524), and a moved policy's uploaded copy is gone by its turn.
    server = sorted(
        (f for f in files if not f.startswith(UPLOADED)),
        key=lambda f: (f not in live, f.encode()),
    )
    uploads = sorted((f for f in files if f.startswith(UPLOADED)), key=str.encode)
    outcomes: list[ImportOutcome] = []
    leftovers: list[Difference] = []
    strays: list[str] = []
    edited: list[str] = []
    exists = partial(present, bits_dir)
    for rel in server + uploads:
        if rel.startswith(UPLOADED):
            with session.transaction() as tx:
                kind = classify_upload(tx.conn, rel)
            if kind == "leftover":
                leftovers.append(remove_leftover(bits_dir, rel))
                continue
            if kind == "stray":
                if present(bits_dir, rel):  # not removed by a move above
                    log.warning("uploaded file skipped: not a live policy's file")
                    strays.append(rel)
                continue
        file = read_input(bits_dir, rel)
        if file is None:
            continue
        prepared = prepare(file.data)  # parsed once, passed to import_one
        if rel.startswith(UPLOADED):
            with session.transaction() as tx:
                skip = renamed(tx.conn, rel, prepared)
            if skip:
                log.warning("uploaded file skipped: its policy name was edited")
                edited.append(rel)
                continue
        outcome = import_one(
            session,
            clock,
            bits_dir,
            file,
            mode=Mode.AUTO,
            actor=_SYSTEM,
            file_exists=exists,
            prepared=prepared,
        )
        outcomes.append(outcome)
    deleted = delete_removed(session, clock, bits_dir)
    return ReconcileResult(
        tuple(outcomes),
        deleted,
        tuple(leftovers),
        tuple(strays),
        tuple(edited),
        blind,
    )


def delete_removed(
    session: CatalogSession, clock: Clock, bits_dir: Path
) -> tuple[DeleteResult, ...]:
    """Delete (TS §4.3, soft) each live policy whose `source_file` is no
    longer present, one transaction each. Runs after the imports, so a file
    renamed in the server folder moves its policy instead (REQ-159 (2)).
    A policy whose folder is `unreadable` is never deleted ("Folder guard")."""
    blind = unreadable(bits_dir)
    with session.transaction() as tx:
        rows = integrity_rows(tx.conn)
    results: list[DeleteResult] = []
    for row in rows:
        if _folder(row.source_file) in blind or present(bits_dir, row.source_file):
            continue
        with session.transaction() as tx:
            result = delete_in_tx(
                tx,
                row.policy_id,
                actor=_SYSTEM.audit,
                reason="file removed",
                now=clock.now(),
            )
        remove_after_commit(bits_dir, result.remove_after_commit)
        results.append(result)
    return tuple(results)
