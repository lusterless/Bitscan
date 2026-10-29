"""Import pipeline, the store and record half (SR §3.6; TS §4.1 L520, L530,
§8.4 L1289-L1291; open questions #23, #100, #101; work/plans/TASK-154.md §5,
§7, §8). The plan §11 split: `pipeline` imports from here, never the reverse,
and re-exports the public names.

`store_file` is the body of transaction 1 (or of a rebuild file's savepoint):
the database rules, the store and the audit entries. `record` writes the
`bit_import` row in its own transaction. Nothing here commits, takes the
catalog lock, touches files or logs. In `rebuild` mode a file whose store
changed none of its policy's catalog rows writes no audit entry (#23,
REQ-166 (6); TASK-154 r2, "TASK-157 rulings" 2026-10-28).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

from bitscan_manager.repositories import catalog, catalog_admin, imports
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog import PolicyRow
from bitscan_manager.repositories.imports import ImportRecord, Mode, Outcome
from bitscan_manager.runtime import CatalogSession, Clock, Tx
from bitscan_manager.services.importer import alerts, store, store_decide
from bitscan_manager.services.importer.model import Code, Finding
from bitscan_manager.services.importer.store import (
    Candidate,
    Decision,
    RuleKeys,
    StoreResult,
    Target,
)

_RULE_ORDER: Final = {code: n for n, code in enumerate(Code)}
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
type Fingerprint = tuple[object, ...] | None


@dataclass(frozen=True, slots=True)
class Actor:
    audit: str  # "user:<id>", "cli:root" or "system" (#101)
    user_id: int | None  # bit_import.imported_by; None for system and CLI


@dataclass(frozen=True, slots=True)
class FileInput:
    data: bytes | None  # the one read buffer; None for an oversize folder file
    sha256: str  # of data, or of the streamed oversize file
    file_name: str  # the relative path, or the #99 (d) client name
    target: Target


@dataclass(frozen=True, slots=True)
class Prepared:
    findings: tuple[Finding, ...]  # file-local findings, warnings included
    rules: RuleKeys | None  # None when BIT001 or BIT002 failed
    candidate: Candidate | None  # None when any file-local Reject


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """One import's result. Before its record is written (a rebuild's
    pending file, or `after_commit`) `import_id` is None."""

    import_id: int | None
    outcome: Outcome
    policy_id: int | None = None  # the policy fields are None when rejected
    policy_name: str | None = None  # (#98 (d))
    policy_version: int | None = None
    plugins_added: int = 0
    plugins_updated: int = 0
    plugins_retired: int = 0
    findings: tuple[Finding, ...] = ()  # everything stored in bit_import.errors
    store: StoreResult | None = None  # success only
    matched_policy_id: int | None = None  # rejected: the alert target (#101)


class Abort(Exception):
    """Leaves transaction 1 or the savepoint, so it rolls back."""

    def __init__(self, pending: ImportOutcome) -> None:
        super().__init__(pending.outcome)
        self.pending = pending


def ordered(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """By line, then by rule order (REQ-155 (5)); stable within a rule."""
    return tuple(sorted(findings, key=lambda f: (f.line or 0, _RULE_ORDER[f.code])))


def store_file(
    tx: Tx,
    now: datetime,
    file: FileInput,
    prep: Prepared,
    *,
    mode: Mode,
    actor: Actor,
    file_exists: Callable[[str], bool],
) -> tuple[StoreResult, tuple[Finding, ...]]:
    """The database rules, the store and its audit entries, in `tx`. Raises
    Abort for a skip or a rejection, PolicyManagedOnServer for #99 (e)."""
    if prep.rules is None:
        raise Abort(ImportOutcome(None, "rejected", findings=prep.findings))
    decision = store_decide.decide(tx.conn, prep.rules, file.target, file_exists)
    old = decision.old
    if mode == "auto" and old and store_decide.is_unchanged(decision, file.target):
        # #23: a skip writes only its row, with no policy_version (SR §3.5)
        raise Abort(ImportOutcome(None, "skipped", old.policy_id, old.policy_name))
    owned = store_decide.check_ownership(tx.conn, decision, prep.rules)
    findings = ordered((*prep.findings, *decision.findings, *owned))
    if prep.candidate is None or any(f.rejects for f in findings):
        rejected = ImportOutcome(None, "rejected", findings=findings)
        raise Abort(replace(rejected, matched_policy_id=decision.policy_id))
    displaced = None
    if decision.displaced_id is not None:  # its name and file, before the delete
        displaced = catalog.policy_by_id_for_update(tx.conn, decision.displaced_id)
    rebuild = mode == "rebuild"
    before = _fingerprint(tx, decision.policy_id) if rebuild else None
    result = store.apply(tx.conn, decision, prep.candidate, file.target, now)
    if not rebuild or _changed(decision, result, before, tx):
        _audit(tx, result, decision, displaced, file=file, mode=mode, actor=actor)
    return result, findings


def _fingerprint(tx: Tx, policy_id: int | None) -> Fingerprint:
    """The policy's catalog state: its row (policy_status included, not
    imported_at, which every import sets), its policy_plugin rows and its
    plugins, from one snapshot read under the catalog lock."""
    found = None if policy_id is None else catalog_admin.detail(tx.conn, policy_id)
    if found is None:
        return None
    head = replace(found.item, imported_at=_EPOCH)
    return (head, found.deleted_at, *found.plugins)


def _changed(
    decision: Decision, result: StoreResult, before: Fingerprint, tx: Tx
) -> bool:
    """A rebuild file changed its policy's rows ("TASK-157 rulings" (2)):
    new, revived, renamed or moved (any case but `update`), a policy
    displaced, plugins added, updated or retired, a changed Execute, or any
    other difference in the catalog state (a version bump included)."""
    return bool(
        decision.case != "update"
        or result.deleted_policy_ids
        or result.plugins_added
        or result.plugins_updated
        or result.plugins_retired
        or result.changed_executes
        or before != _fingerprint(tx, result.policy_id)
    )


def _audit(
    tx: Tx,
    result: StoreResult,
    decision: Decision,
    displaced: PolicyRow | None,
    *,
    file: FileInput,
    mode: Mode,
    actor: Actor,
) -> None:
    """Plan §7, in transaction 1 (or the rebuild's savepoint)."""

    def put(event: alerts.AuditEvent) -> None:
        alerts.emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)

    put(
        alerts.imported(
            policy_id=result.policy_id,
            policy_name=result.policy_name,
            version=result.version,
            mode=mode,
            file_sha256=file.sha256,
            source_file=result.source_file,
            plugins_added=result.plugins_added,
            plugins_updated=result.plugins_updated,
            plugins_retired=result.plugins_retired,
            renamed_from=result.renamed_from,
            revived=result.revived,
            changed_executes=result.changed_executes,  # reactivated included
        )
    )
    if result.moved_from is not None:
        put(
            alerts.moved(
                policy_id=result.policy_id,
                from_file=result.moved_from,
                to_file=result.source_file,
            )
        )
    if displaced is not None and displaced.policy_id in result.deleted_policy_ids:
        put(
            alerts.deleted(
                policy_id=displaced.policy_id,
                policy_name=displaced.policy_name,
                source_file=displaced.source_file,
                reason="file now holds another policy",
            )
        )
    if result.reenabled and decision.old is not None:
        put(
            alerts.status_change(
                policy_id=result.policy_id,
                policy_name=result.policy_name,
                before="disabled",
                after="enabled",
                status_overridden=decision.old.status_overridden,
                by="file",
            )
        )


def success(result: StoreResult, findings: tuple[Finding, ...]) -> ImportOutcome:
    return ImportOutcome(
        None,
        "success",
        result.policy_id,
        result.policy_name,
        result.version,
        result.plugins_added,
        result.plugins_updated,
        result.plugins_retired,
        findings,  # warnings included (#110)
        result,
    )


def store_in_savepoint(
    session: CatalogSession,
    tx: Tx,
    clock: Clock,
    file: FileInput,
    prepared: Prepared,
    *,
    actor: Actor,
    file_exists: Callable[[str], bool],
) -> ImportOutcome:
    """A rebuild file (plan §8): the transaction 1 body in its own savepoint
    of the rebuild's transaction `tx`; never skipped. A rejection rolls back
    to the savepoint, dropping its entries and hooks. PolicyManagedOnServer
    propagates after the savepoint rolls back. The caller writes `record`
    for the returned pending outcome after its transaction ends."""
    try:
        with session.savepoint():
            result, findings = store_file(
                tx,
                clock.now(),
                file,
                prepared,
                mode="rebuild",
                actor=actor,
                file_exists=file_exists,
            )
    except Abort as stop:
        return stop.pending
    return success(result, findings)


def record(
    tx: Tx,
    file: FileInput,
    mode: Mode,
    actor: Actor,
    pending: ImportOutcome,
    *,
    now: datetime,
) -> int:
    """The `bit_import` row in its own transaction (SR §3.6), and for a
    rejection its alert and, on commit, the failure count (#101)."""
    import_id = imports.insert_import(
        tx.conn,
        ImportRecord(
            file_name=file.file_name,
            file_sha256=file.sha256,
            mode=mode,
            outcome=pending.outcome,
            # SR §3.5: "after the import, if it succeeded"; NULL otherwise.
            policy_version=(
                pending.policy_version if pending.outcome == "success" else None
            ),
            plugins_added=pending.plugins_added,
            plugins_updated=pending.plugins_updated,
            plugins_retired=pending.plugins_retired,
            errors=[f.to_json() for f in pending.findings],
            imported_by=actor.user_id,
        ),
        now,
    )
    if pending.outcome == "rejected":
        event = alerts.rejected(
            import_id=import_id,
            mode=mode,
            file_name=file.file_name,
            file_sha256=file.sha256,
            policy_id=pending.matched_policy_id,
            findings=pending.findings,
        )
        alerts.emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor.audit)
        alerts.count_failure(tx.on_commit, mode)
    return import_id
