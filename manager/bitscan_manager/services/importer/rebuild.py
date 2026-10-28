"""The rebuild (TS §4.2 L540, §4.1 L524-L532, §4.3 L550, §8.4 L1290; SR §3.6;
REQ-166; open questions #20, #23, #98 (g) (j); user rulings of 2026-10-27:
"Crash window", "Rebuild finishes interrupted uploads first", stray files,
edited names and "Folder guard").

Under the catalog lock, held for the whole run: finish interrupted uploads,
then one transaction re-imports every file of both folders in `rebuild`
mode, one savepoint each (a rejected file keeps its rows), and deletes the
policies whose files are gone. Only after its commit are upload copies and
leftovers of interrupted deletes removed. A last transaction writes the
`bit_import` rows, ends the task and raises the `policy_rebuilt` alert. Any
error rolls the catalog back and ends the task `failed` with no rows (#98
(j)). `uploaded/` files go through `folders.classify_upload`: leftovers are
removed and listed, strays and renamed files are skipped and reported.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import UUID

from bitscan_manager.repositories import imports
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog_integrity import integrity_rows
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Clock, SessionDatabase, Tx
from bitscan_manager.services.importer import alerts, folders
from bitscan_manager.services.importer.delete import (
    DeleteResult,
    delete_in_tx,
    remove_after_commit,
)
from bitscan_manager.services.importer.folders import BITS_ROOT, UPLOADED
from bitscan_manager.services.importer.pipeline import (
    Actor,
    FileInput,
    Mode,
    Pending,
    prepare,
    record,
    store_in_savepoint,
)
from bitscan_manager.services.importer.uploads import finish_interrupted_uploads

log = logging.getLogger(__name__)
FAILED_TEXT = "rebuild failed"  # #98 (g): fixed text, never the error itself
type State = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class RebuildResult:
    task_id: UUID
    state: State
    result: Mapping[str, object]  # as stored in task.result


@dataclass
class _Run:
    blind: list[str]  # folders found unreadable: nothing imported or deleted
    stored: list[tuple[FileInput, Pending]]
    deleted: list[DeleteResult]
    removals: list[str]  # upload copies to remove after the commit
    leftovers: list[str]  # uploaded/ files of deleted policies
    skipped: list[dict[str, str]]


def create_task(db: SessionDatabase, clock: Clock, actor: Actor) -> UUID:
    """The `task` row (`rebuild`, `running`); `requested_by` NULL for the CLI."""
    with db.session() as session, session.transaction() as tx:
        return imports.insert_task(tx.conn, actor.user_id, clock.now())


def run_rebuild(
    db: SessionDatabase, clock: Clock, bits_dir: Path, task_id: UUID, actor: Actor
) -> RebuildResult:
    """REQ-166 for the task `task_id` (from `create_task`). On a rebuild error
    the catalog rolls back, the task ends `failed` with fixed text and the
    alert is raised best-effort (#20, #98 (g) (j)); then the error re-raises."""
    try:
        with db.session() as session, catalog_lock(session):
            return _rebuild(session, clock, bits_dir, task_id, actor)
    except Exception as exc:
        log.error("rebuild failed: %s", type(exc).__name__)
        try:
            with db.session() as session, session.transaction() as tx:
                failed = {"error": FAILED_TEXT}
                _finish(tx, clock, task_id, actor, "failed", failed, _empty())
        except Exception as inner:  # start-up marks it failed (REQ-165 (2))
            log.error("rebuild task not finished: %s", type(inner).__name__)
        raise


def _empty() -> _Run:
    return _Run([], [], [], [], [], [])


def _mark(run: _Run, bits_dir: Path, label: str) -> None:
    for name in (label, *folders.unreadable(bits_dir)):
        if name not in run.blind:
            log.warning("folder unreadable, not rebuilt: %s", name)
            run.blind.append(name)


def _folder(rel: str) -> str:
    return UPLOADED if rel.startswith(UPLOADED) else BITS_ROOT


def _rebuild(
    session: CatalogSession, clock: Clock, bits_dir: Path, task_id: UUID, actor: Actor
) -> RebuildResult:
    finish_interrupted_uploads(session, bits_dir)  # ruling: before any read
    run = _empty()
    for label in folders.unreadable(bits_dir):
        _mark(run, bits_dir, label)
    files = folders.discover(bits_dir)
    with session.transaction() as tx:
        live = {r.source_file for r in integrity_rows(tx.conn)}
        server = sorted(  # #15 order, server files first (as the reconcile)
            (f for f in files if not f.startswith(UPLOADED)),
            key=lambda f: (f not in live, f.encode()),
        )
        uploads = sorted((f for f in files if f.startswith(UPLOADED)), key=str.encode)
        for rel in server + uploads:
            _one(session, tx, clock, bits_dir, rel, actor, run)
        _delete_gone(tx, clock, bits_dir, actor, run)
    remove_after_commit(bits_dir, run.removals)
    removed: list[str] = []
    for rel in run.leftovers:
        if folders.remove_leftover(bits_dir, rel) is None:
            _mark(run, bits_dir, UPLOADED)  # not confirmed gone: not listed
        else:
            removed.append(rel)
    run.leftovers = removed
    with session.transaction() as tx:
        files_out = [
            {
                "source_file": file.file_name,
                "import_id": record(tx, clock, file, Mode.REBUILD, actor, pending),
                "outcome": pending.outcome,
                "policy_id": pending.policy_id,
                "policy_version": pending.policy_version,
            }
            for file, pending in run.stored
        ]
        result = {
            "files": files_out,
            "deleted_policy_ids": _deleted_ids(run),
            "plugins_retired": _retired(run),
            "removed_leftovers": run.leftovers,
            "skipped": run.skipped,
            "unreadable_folders": [f for f in (BITS_ROOT, UPLOADED) if f in run.blind],
        }
        _finish(tx, clock, task_id, actor, "succeeded", result, run)
    return RebuildResult(task_id, "succeeded", result)


def _one(
    session: CatalogSession,
    tx: Tx,
    clock: Clock,
    bits_dir: Path,
    rel: str,
    actor: Actor,
    run: _Run,
) -> None:
    """One discovered file, in the rebuild transaction (the reconcile's steps)."""
    if _folder(rel) in run.blind or rel in run.removals:  # gone after commit
        return
    if rel.startswith(UPLOADED):
        kind = folders.classify_upload(tx.conn, rel)
        if kind == "leftover":  # removed only after the commit
            run.leftovers.append(rel)
            return
        if kind == "stray":
            log.warning("uploaded file skipped: not a live policy's file")
            run.skipped.append({"source_file": rel, "reason": "stray"})
            return
    file = folders.read_input(bits_dir, rel)
    if file is None:
        if _folder(rel) in folders.unreadable(bits_dir):  # swapped after discover
            _mark(run, bits_dir, _folder(rel))
        return
    prepared = prepare(file.data)
    if rel.startswith(UPLOADED) and folders.renamed(tx.conn, rel, prepared):
        log.warning("uploaded file skipped: its policy name was edited")
        run.skipped.append({"source_file": rel, "reason": "renamed"})
        return
    pending = store_in_savepoint(
        session,
        tx,
        clock,
        file,
        prepared,
        actor=actor,
        file_exists=partial(folders.present, bits_dir),
    )
    run.stored.append((file, pending))
    if pending.store is not None:
        run.removals.extend(pending.store.remove_after_commit)


def _delete_gone(tx: Tx, clock: Clock, bits_dir: Path, actor: Actor, run: _Run) -> None:
    """REQ-167 for each live policy whose file is gone, in the rebuild
    transaction. The three-way test runs right before each delete, so a
    folder that goes away mid-loop deletes none of its policies."""
    for row in integrity_rows(tx.conn):
        if _folder(row.source_file) in run.blind:
            continue
        state = folders.state(bits_dir, row.source_file)
        if state == "unreadable":
            _mark(run, bits_dir, _folder(row.source_file))
        if state != "absent":
            continue
        result = delete_in_tx(
            tx, row.policy_id, actor=actor.audit, reason="file removed", now=clock.now()
        )
        run.deleted.append(result)
        run.removals.extend(result.remove_after_commit)


def _deleted_ids(run: _Run) -> list[int]:
    displaced = [
        i for _, p in run.stored if p.store for i in p.store.deleted_policy_ids
    ]
    return [*displaced, *(d.policy_id for d in run.deleted)]


def _retired(run: _Run) -> int:
    by_files = sum(p.plugins_retired for _, p in run.stored)
    return by_files + sum(len(d.effects.retired_plugin_uuids) for d in run.deleted)


def _finish(
    tx: Tx,
    clock: Clock,
    task_id: UUID,
    actor: Actor,
    state: State,
    result: Mapping[str, object],
    run: _Run,
) -> None:
    """End the task and raise the one `policy_rebuilt` alert (#20, #23)."""
    if not imports.finish_task(tx.conn, task_id, state, result, clock.now()):
        log.warning("rebuild task was no longer running")
    event = alerts.rebuilt(
        task_id=task_id,
        state=state,
        files_imported=sum(p.outcome == "success" for _, p in run.stored),
        files_rejected=sum(p.outcome == "rejected" for _, p in run.stored),
        deleted_policy_ids=_deleted_ids(run),
        plugins_retired=_retired(run),
        removed_leftovers=run.leftovers,
    )
    alerts.emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)
