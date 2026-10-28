"""The import pipeline (TS §4.1 L516-L532, §8.4 L1290-L1291; SR §3.6; design
note D4; open questions #23, #98 (j), #99, #100, #101, #110), per
work/plans/TASK-154.md.

`prepare` is pure and runs before the catalog lock. `import_one` runs under
the lock its caller holds: transaction 1 decides, stores and writes the
success audit entries; transaction 2 writes the `bit_import` row and, for a
rejection, its alert and the failure count. A database or disk error is not
a rejection: it propagates and writes no row (#98 (j)). Nothing here logs
file content, findings or `Execute` text. The types, audit writers and
`record` are in pipeline_record (plan §11).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import cast

from bitscan_manager.repositories import catalog
from bitscan_manager.runtime import CatalogSession, Clock, Tx
from bitscan_manager.services.importer import bit102, store, store_decide
from bitscan_manager.services.importer.delete import remove_after_commit
from bitscan_manager.services.importer.model import (
    LENGTH_LIMITS,
    Code,
    Finding,
    plugin_path,
)
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.pipeline_record import (
    Actor,
    FileInput,
    Mode,
    Pending,
    audit_refused,
    audit_success,
    record,
)
from bitscan_manager.services.importer.store import Candidate, RuleKeys
from bitscan_manager.services.importer.structure import check as check_structure
from bitscan_manager.services.importer.validate import validate
from bitscan_manager.services.importer.values import trim_xml

__all__ = [
    "Actor",
    "FileInput",
    "ImportOutcome",
    "Mode",
    "Pending",
    "Prepared",
    "import_one",
    "prepare",
    "record",
    "store_in_savepoint",
]

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Prepared:
    findings: tuple[Finding, ...]  # file-local, warnings included
    rules: RuleKeys | None  # None when BIT001 or BIT002 failed
    candidate: Candidate | None  # None when any file-local Reject


@dataclass(frozen=True)
class ImportOutcome(Pending):
    import_id: int | None = None  # None only if the record transaction failed


class _Abort(Exception):
    """Leaves transaction 1 (or a savepoint) so that it rolls back."""

    def __init__(self, pending: Pending) -> None:
        super().__init__(pending.outcome)
        self.pending = pending


def _ordered(found: Iterable[Finding]) -> tuple[Finding, ...]:
    # Stable: by line, then in rule order within a line (REQ-155 (5)).
    return tuple(sorted(found, key=lambda f: f.line or 0))


def prepare(data: bytes | None) -> Prepared:
    """Parse, structure, content rules and BIT102 on the one buffer; pure."""
    if data is None:  # #99 (b): an oversize folder file is a rejected import
        too_big = Finding(None, None, Code.BIT001, "The file is larger than 5 MiB.")
        return Prepared((too_big,), None, None)
    parsed = parse_bit(data)
    if parsed.root is None:
        return Prepared(parsed.findings, None, None)
    shape = check_structure(parsed.root, parsed.pi_lines)
    if shape.parsed is None:  # BIT002 stops the content rules (SR L250)
        return Prepared(shape.findings, None, None)
    checked = validate(shape.parsed)
    found = [*shape.findings, *checked.findings]  # BIT016 does not stop them
    for plugin in shape.parsed.plugins:
        execute = trim_xml(plugin.execute.text)
        if 1 <= len(execute) <= LENGTH_LIMITS["Execute"][1]:  # passed BIT008
            path = plugin_path(plugin.index, "Execute")
            found += bit102.check_execute(
                execute, line=plugin.execute.line, element=path
            )
    findings = _ordered(found)
    rejected = any(f.rejects for f in findings)
    return Prepared(findings, checked.rules, None if rejected else checked.candidate)


def _rejected(findings: tuple[Finding, ...], policy_id: int | None) -> Pending:
    return Pending("rejected", policy_id, None, None, 0, 0, 0, findings, None)


def _store(
    tx: Tx,
    clock: Clock,
    file: FileInput,
    prep: Prepared,
    *,
    mode: Mode,
    actor: Actor,
    file_exists: Callable[[str], bool],
) -> Pending:
    """The transaction-1 body: database rules, the `auto` skip, the store
    and the success audit entries. Raises PolicyManagedOnServer (#99 (e))."""
    if prep.rules is None:
        return _rejected(prep.findings, None)
    decision = store_decide.decide(tx.conn, prep.rules, file.target, file_exists)
    old = decision.old
    if mode is Mode.AUTO and old and store_decide.is_unchanged(decision, file.target):
        return Pending(
            "skipped", old.policy_id, old.policy_name, old.version, 0, 0, 0, (), None
        )
    ownership = store_decide.check_ownership(tx.conn, decision, prep.rules)
    findings = _ordered([*prep.findings, *decision.findings, *ownership])
    if prep.candidate is None or any(f.rejects for f in findings):
        return _rejected(findings, decision.policy_id)
    displaced = None
    if decision.displaced_id is not None:  # already locked by decide
        displaced = catalog.policy_by_id_for_update(tx.conn, decision.displaced_id)
    result = store.apply(tx.conn, decision, prep.candidate, file.target, clock.now())
    # #23 with #100 (a) (lead, 2026-10-28): a rebuild alerts only when a
    # command goes live (new, changed or reactivated), even on a same-hash file.
    quiet = mode is Mode.REBUILD and not result.changed_executes
    audit_success(
        tx, result, decision, displaced, file, mode, actor, announce=not quiet
    )
    return Pending(
        "success",
        result.policy_id,
        result.policy_name,
        result.version,
        result.plugins_added,
        result.plugins_updated,
        result.plugins_retired,
        findings,
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
) -> Pending:
    """A rebuild file (plan §8): the transaction-1 body in its own savepoint
    of the rebuild's transaction `tx`; never skips. A rejection rolls back to
    the savepoint, dropping its entries. The caller removes
    `store.remove_after_commit` after its commit, then calls `record`."""
    try:
        with session.savepoint():
            pending = _store(
                tx,
                clock,
                file,
                prepared,
                mode=Mode.REBUILD,
                actor=actor,
                file_exists=file_exists,
            )
            if pending.outcome != "success":
                raise _Abort(pending)
    except _Abort as stop:
        return stop.pending
    return pending


def import_one(
    session: CatalogSession,
    clock: Clock,
    bits_dir: Path,
    file: FileInput,
    *,
    mode: Mode,
    actor: Actor,
    file_exists: Callable[[str], bool],
    prepared: Prepared | None = None,
    before_commit: Callable[[int], None] | None = None,
    after_commit: Callable[[Pending], None] | None = None,
) -> ImportOutcome:
    """One file under the caller's catalog lock (design note D4). Pass
    `prepared` (from `prepare`, before the lock) so parsing never holds it.
    `before_commit(policy_id)` runs last in transaction 1 (the upload's temp
    file); `after_commit` runs after its commit on success (the rename)."""
    mode = Mode(mode)
    prep = prepared if prepared is not None else prepare(file.data)
    try:
        with session.transaction() as tx:
            pending = _store(
                tx, clock, file, prep, mode=mode, actor=actor, file_exists=file_exists
            )
            if pending.outcome != "success":
                raise _Abort(pending)
            if before_commit is not None:
                before_commit(cast(int, pending.policy_id))
    except _Abort as stop:
        pending = stop.pending
    except store.PolicyManagedOnServer as refused:  # #99 (e): no row, no alert
        with session.transaction() as tx:
            audit_refused(tx, refused.policy_id, file, mode, actor)
        raise
    import_id: int | None = None
    try:
        if pending.store is not None:
            remove_after_commit(bits_dir, pending.store.remove_after_commit)
            if after_commit is not None:
                after_commit(pending)
    finally:  # the record is written even if the rename failed
        try:
            with session.transaction() as tx:
                import_id = record(tx, clock, file, mode, actor, pending)
        except Exception as exc:
            if pending.outcome != "success":
                raise  # nothing committed: an internal error (#98 (j))
            # The catalog change stands; the row is lost (REQ-160 (4)).
            log.error("bit_import record failed: %s", type(exc).__name__)
    log.info(
        "bit import %s: import_id=%s added=%d updated=%d retired=%d",
        pending.outcome,
        import_id,
        pending.plugins_added,
        pending.plugins_updated,
        pending.plugins_retired,
    )
    values = {f.name: getattr(pending, f.name) for f in fields(Pending)}
    return ImportOutcome(**values, import_id=import_id)
