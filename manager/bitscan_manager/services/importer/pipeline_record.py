"""The import pipeline's shared types and its audit and record writers (TS
§4.1 L520, L530, §8.4 L1290-L1291; SR §3.6; open questions #99 (e), #100,
#101), per work/plans/TASK-154.md §3, §6, §7 and §8 (split off pipeline.py
by plan §11). Every writer runs in the caller's transaction or savepoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from bitscan_manager.repositories import imports
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog import PolicyRow
from bitscan_manager.repositories.imports import ImportRecord
from bitscan_manager.runtime import Clock, Tx
from bitscan_manager.services.importer import alerts
from bitscan_manager.services.importer.model import Finding
from bitscan_manager.services.importer.store import Decision, StoreResult, Target


class Mode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    REBUILD = "rebuild"


@dataclass(frozen=True, slots=True)
class Actor:
    audit: str  # "user:<id>", "cli:root" or "system" (#101)
    user_id: int | None  # bit_import.imported_by


@dataclass(frozen=True, slots=True)
class FileInput:
    data: bytes | None  # the one read buffer; None for an oversize folder file
    sha256: str  # of data, or of the streamed oversize file
    file_name: str  # the relative path, or the #99 (d) client name
    target: Target


@dataclass(frozen=True)
class Pending:
    """An outcome before its `bit_import` row exists."""

    outcome: Literal["success", "skipped", "rejected"]
    policy_id: int | None
    policy_name: str | None
    policy_version: int | None
    plugins_added: int
    plugins_updated: int
    plugins_retired: int
    findings: tuple[Finding, ...]  # everything stored in bit_import.errors
    store: StoreResult | None  # success only


def mode_value(mode: Mode) -> imports.Mode:
    return Mode(mode).value


def audit_success(
    tx: Tx,
    r: StoreResult,
    decision: Decision,
    displaced: PolicyRow | None,
    file: FileInput,
    mode: Mode,
    actor: Actor,
) -> None:
    """Plan §7: the import alert, then the move, the displaced policy's delete
    and the re-enable, in the store's transaction or savepoint."""
    events = [
        alerts.imported(
            policy_id=r.policy_id,
            policy_name=r.policy_name,
            version=r.version,
            mode=mode_value(mode),
            file_sha256=file.sha256,
            source_file=r.source_file,
            plugins_added=r.plugins_added,
            plugins_updated=r.plugins_updated,
            plugins_retired=r.plugins_retired,
            renamed_from=r.renamed_from,
            revived=r.revived,
            changed_executes=r.changed_executes,
        )
    ]
    if r.moved_from is not None:
        events.append(
            alerts.moved(
                policy_id=r.policy_id, from_file=r.moved_from, to_file=r.source_file
            )
        )
    if displaced is not None:
        events.append(
            alerts.deleted(
                policy_id=displaced.policy_id,
                policy_name=displaced.policy_name,
                source_file=displaced.source_file,
                reason="file now holds another policy",
            )
        )
    if r.reenabled and decision.old is not None:
        events.append(
            alerts.status_change(
                policy_id=r.policy_id,
                policy_name=r.policy_name,
                before="disabled",
                after="enabled",
                status_overridden=decision.old.status_overridden,
                by="file",
            )
        )
    repo = PgAuditRepo(tx.conn)
    for event in events:
        alerts.emit(repo, tx.on_commit, event, actor=actor.audit)


def audit_refused(
    tx: Tx, policy_id: int, file: FileInput, mode: Mode, actor: Actor
) -> None:
    """#99 (e): one `policy.import_refused` entry, no alert and no row. #101
    names the action only; the detail holds no client text."""
    event = alerts.AuditEvent(
        action="policy.import_refused",
        target=f"policy:{policy_id}",
        detail={
            "policy_id": policy_id,
            "mode": mode_value(mode),
            "file_sha256": file.sha256,
        },
    )
    alerts.emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)


def record(
    tx: Tx, clock: Clock, file: FileInput, mode: Mode, actor: Actor, pending: Pending
) -> int:
    """The `bit_import` row; for a rejection also its alert and the failure
    count on commit (#101). Its own transaction, after the store's."""
    lit = mode_value(mode)
    row = ImportRecord(
        file_name=file.file_name,
        file_sha256=file.sha256,
        mode=lit,
        outcome=pending.outcome,
        policy_version=pending.policy_version,
        plugins_added=pending.plugins_added,
        plugins_updated=pending.plugins_updated,
        plugins_retired=pending.plugins_retired,
        errors=[f.to_json() for f in pending.findings],
        imported_by=actor.user_id,
    )
    import_id = imports.insert_import(tx.conn, row, clock.now())
    if pending.outcome == "rejected":
        event = alerts.rejected(
            import_id=import_id,
            mode=lit,
            file_name=file.file_name,
            file_sha256=file.sha256,
            policy_id=pending.policy_id,
            findings=pending.findings,
        )
        alerts.emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)
        alerts.count_failure(tx.on_commit, lit)
    return import_id
