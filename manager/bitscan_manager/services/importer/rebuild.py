"""Catalog rebuild (TS §4.2 L540, §4.3 L550, §8.4 L1290; REQ-166; open
questions #20, #23, #98 (g), (j), #101; user "Crash window" ruling 2026-10-27;
lead's "TASK-157 rulings" 2026-10-28).

`start_task` writes the `task` row (`rebuild`, `running`), so a route can
answer 202 with its id at once. `run` then, under the catalog lock and in one
transaction, re-imports every file of both folders in `rebuild` mode (never
skipped), each in its own savepoint, so a rejected file keeps its rows. It
deletes the policies whose files are gone; the store retires unreferenced
plugins. `uploaded/` files are classified first, as by the reconcile: a
leftover of an interrupted delete is removed after the commit and listed,
never revived. After the commit, a final transaction writes the `bit_import`
rows, finishes the task and writes the one `bits.rebuild` entry (the
`policy_rebuilt` alert). An internal error rolls everything back: no rows, the
task ends `failed` (#98 (j)). Nothing here logs file names or content.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from bitscan_manager.repositories import catalog_integrity, imports
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Clock, SessionDatabase, Tx
from bitscan_manager.services.importer.alerts import emit, rebuilt
from bitscan_manager.services.importer.delete import (
    PolicyAlreadyDeleted,
    PolicyNotFound,
    delete_in_tx,
    remove_after_commit,
)
from bitscan_manager.services.importer.folders import (
    Relocate,
    UploadClass,
    classify_upload,
    discover,
    is_bit_file,
    read_file,
)
from bitscan_manager.services.importer.own_changes import OWN_CHANGES
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    ImportOutcome,
    prepare,
    record,
    store_in_savepoint,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer, Target
from bitscan_manager.services.importer.uploads import staged_upload

log = logging.getLogger(__name__)
FAILED: Final = "The rebuild failed; the catalog was left unchanged."  # #98 (g)
NOT_RUNNING: Final = "interrupted by manager start-up; run it again"  # r2, for the CLI


@dataclass(slots=True)
class RebuildResult:
    task_id: UUID
    state: Literal["succeeded", "failed"] = "failed"
    files: list[tuple[str, ImportOutcome]] = field(default_factory=list)
    not_imported: list[str] = field(default_factory=list)  # no row (see run)
    deleted_policy_ids: list[int] = field(default_factory=list)
    plugins_retired: int = 0
    removed_leftovers: list[str] = field(default_factory=list)
    reason: str | None = None  # NOT_RUNNING when the task was no longer running


@dataclass(slots=True)
class _Work:
    """What the rebuild transaction did, for after its commit."""

    files: list[tuple[str, FileInput, ImportOutcome]] = field(default_factory=list)
    moves: list[tuple[Relocate, ImportOutcome]] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    # uploaded/policy-<id>.bit files staged here, on disk only after the commit
    staged: set[str] = field(default_factory=set)


def start_task(db: SessionDatabase, clock: Clock, requested_by: int | None) -> UUID:
    """The `task` row, `running` from now; requested_by None for the CLI."""
    with db.session() as session, session.transaction() as tx:
        return imports.insert_task(tx.conn, requested_by, clock.now())


def run(
    db: SessionDatabase, clock: Clock, bits_dir: Path, task_id: UUID, actor: Actor
) -> RebuildResult:
    """The rebuild for `task_id`; `actor` is `user:<id>` or `cli:root`.
    Returns the result with state `succeeded` (rejected files included, #20)
    or `failed`; it raises only if the session or lock cannot be had."""
    out = RebuildResult(task_id)
    work = _Work()
    with db.session() as session, catalog_lock(session):
        # r2: start-up may have failed this task while it waited for the lock;
        # then nothing runs, so the task row and the audit log agree.
        with session.transaction() as tx:
            task = imports.get_task(tx.conn, task_id)
        if task is None or task.state != "running":
            return RebuildResult(task_id, reason=NOT_RUNNING)
        try:
            with ExitStack() as stages, session.transaction() as tx:
                _rebuild(session, tx, clock, bits_dir, actor, out, work, stages)
        except Exception as exc:  # rolled back, staged files discarded
            log.error("rebuild failed: %s", type(exc).__name__)
            out = RebuildResult(task_id)
            _finish(session, clock, out, actor)
            return out
        out.state = "succeeded"
        for rel in out.removed_leftovers:
            _unlink(bits_dir, rel)
        for move, stored_outcome in work.moves:
            try:
                move.after_commit(stored_outcome)
            except Exception as exc:  # the temp file waits for the start-up finish
                log.warning("rebuild upload rename failed: %s", type(exc).__name__)
        remove_after_commit(bits_dir, work.removals)
        try:
            with session.transaction() as tx:
                for rel, file, pending in work.files:
                    import_id = record(
                        tx, file, "rebuild", actor, pending, now=clock.now()
                    )
                    out.files.append((rel, replace(pending, import_id=import_id)))
                _end(tx, clock, out, actor)
        except Exception as exc:  # the catalog stands; the task is failed at start-up
            log.error("rebuild record failed: %s", type(exc).__name__)
    return out


def _rebuild(
    session: CatalogSession,
    tx: Tx,
    clock: Clock,
    bits_dir: Path,
    actor: Actor,
    out: RebuildResult,
    work: _Work,
    stages: ExitStack,
) -> None:
    """The rebuild transaction's body. The #15 order, as the reconcile."""
    recorded = {r.source_file for r in catalog_integrity.integrity_rows(tx.conn)}
    paths = sorted(discover(bits_dir), key=lambda p: (p not in recorded, p.encode()))
    for rel in paths:
        folder, _, name = rel.rpartition("/")
        kind = classify_upload(tx, name) if folder else UploadClass("other", None)
        if kind.kind == "leftover":  # crash window: never revived
            out.removed_leftovers.append(rel)
            continue
        read = read_file(bits_dir / rel)
        if read is None:  # gone, or not a regular file when opened
            out.not_imported.append(rel)
            continue
        data, sha256 = read
        target = (
            Target("upload", None, sha256) if folder else Target("server", rel, sha256)
        )
        file = FileInput(data, sha256, rel, target)
        try:
            pending = store_in_savepoint(
                session,
                tx,
                clock,
                file,
                prepare(data),
                actor=actor,
                file_exists=lambda path: is_bit_file(bits_dir, path),
            )
        except PolicyManagedOnServer:  # a case (c) copy; stays for #103
            out.not_imported.append(rel)
            continue
        work.files.append((rel, file, pending))
        stored = pending.store
        if stored is None:
            continue
        out.plugins_retired += stored.plugins_retired
        work.removals.extend(stored.remove_after_commit)
        if folder and data is not None:  # stored like an upload (case (c) ruling)
            stage = stages.enter_context(staged_upload(bits_dir, sha256, data))
            move = Relocate(stage, bits_dir / rel, kind)
            move.before_commit(stored.policy_id)
            work.moves.append((move, pending))
            if move.staged:
                work.staged.add(f"uploaded/policy-{stored.policy_id}.bit")
    for row in catalog_integrity.integrity_rows(tx.conn):
        # A staged upload is that policy's file; it lands after the commit (r1).
        if row.source_file in work.staged or is_bit_file(bits_dir, row.source_file):
            continue
        try:
            gone = delete_in_tx(
                tx,
                row.policy_id,
                actor=actor.audit,
                reason="file removed",
                now=clock.now(),
            )
        except (PolicyNotFound, PolicyAlreadyDeleted):
            continue
        out.deleted_policy_ids.append(row.policy_id)
        out.plugins_retired += len(gone.effects.retired_plugin_uuids)
        work.removals.extend(gone.remove_after_commit)


def _unlink(bits_dir: Path, rel: str) -> None:
    try:
        OWN_CHANGES.removed(rel)  # #102 (c): just before the call
        (bits_dir / rel).unlink()  # never follows a symlink
    except OSError as exc:
        log.warning("rebuild leftover removal failed: %s", type(exc).__name__)


def _end(tx: Tx, clock: Clock, out: RebuildResult, actor: Actor) -> None:
    """finish_task with the #98 (g) result and the one `bits.rebuild` entry."""
    result: dict[str, object] = (
        {"error": FAILED}
        if out.state == "failed"
        else {
            "files": [
                {
                    "source_file": rel,
                    "import_id": o.import_id,
                    "outcome": o.outcome,
                    "policy_id": o.policy_id,
                    "policy_version": o.policy_version,
                }
                for rel, o in out.files
            ],
            "deleted_policy_ids": out.deleted_policy_ids,
            "plugins_retired": out.plugins_retired,
            "removed_leftovers": out.removed_leftovers,
            "not_imported": out.not_imported,
        }
    )
    imports.finish_task(tx.conn, out.task_id, out.state, result, clock.now())
    event = rebuilt(
        task_id=out.task_id,
        state=out.state,
        files_imported=sum(1 for _, o in out.files if o.outcome == "success"),
        files_rejected=sum(1 for _, o in out.files if o.outcome == "rejected"),
        deleted_policy_ids=out.deleted_policy_ids,
        plugins_retired=out.plugins_retired,
        removed_leftovers=out.removed_leftovers,
    )
    emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)


def _finish(
    session: CatalogSession, clock: Clock, out: RebuildResult, actor: Actor
) -> None:
    """A failed rebuild's task end and alert; if even that fails, the task is
    marked failed at the next start-up (TS §4.2 L540)."""
    try:
        with session.transaction() as tx:
            _end(tx, clock, out, actor)
    except Exception as exc:
        log.error("rebuild failure record failed: %s", type(exc).__name__)
