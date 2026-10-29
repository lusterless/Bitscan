"""Import pipeline: one file from its read buffer to its `bit_import` row
(TS §4.1 L516-L532, §8.4 L1289-L1291; SR §3.6, §4; design note D4; open
questions #23, #98 (j), #99, #100, #101, #110; work/plans/TASK-154.md).

`prepare` is pure and runs before the catalog lock. `import_one` runs under
the lock its caller holds: transaction 1 stores the file with its audit
entries and alerts (`pipeline_record.store_file`); then come the file
removals and the caller's rename; transaction 2 writes the `bit_import` row,
and for a rejection its alert and the failure count. A rejection or skip
rolls transaction 1 back. A database or disk error is not a rejection
(#98 (j)): it propagates and writes no row. Nothing here logs file content,
findings or `Execute` text. The types, `store_in_savepoint` and `record` live
in `pipeline_record` (plan §11 split) and are re-exported here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Final

from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.imports import Mode
from bitscan_manager.runtime import CatalogSession, Clock
from bitscan_manager.services.importer import alerts, bit102
from bitscan_manager.services.importer.delete import remove_after_commit
from bitscan_manager.services.importer.model import (
    LENGTH_LIMITS,
    Code,
    Finding,
    plugin_path,
)
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.pipeline_record import (
    Abort,
    Actor,
    FileInput,
    ImportOutcome,
    Prepared,
    ordered,
    record,
    store_file,
    store_in_savepoint,
    success,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer
from bitscan_manager.services.importer.structure import check
from bitscan_manager.services.importer.validate import validate
from bitscan_manager.services.importer.values import trim_xml

__all__ = [
    "Actor",
    "FileInput",
    "ImportOutcome",
    "Mode",
    "Prepared",
    "import_one",
    "prepare",
    "record",
    "store_in_savepoint",
]

log = logging.getLogger(__name__)
_EXECUTE_MAX: Final = LENGTH_LIMITS["Execute"][1]


def prepare(data: bytes | None) -> Prepared:
    """Parse, structure, content rules and BIT102 (SR §4). No database."""
    if data is None:  # #99 (b): an oversize folder file is a rejected import
        too_big = Finding(None, None, Code.BIT001, "The file is larger than 5 MiB.")
        return Prepared((too_big,), None, None)
    parsed = parse_bit(data)
    if parsed.root is None:
        return Prepared(parsed.findings, None, None)
    shape = check(parsed.root, parsed.pi_lines)
    if shape.parsed is None:  # BIT002: no content rule runs (SR L250)
        return Prepared(shape.findings, None, None)
    valid = validate(shape.parsed)  # BIT016 does not stop these (ruling 10-27)
    risky = [
        finding
        for p in shape.parsed.plugins
        # Only an Execute that passed BIT008 is lexed.
        if 1 <= len(execute := trim_xml(p.execute.text)) <= _EXECUTE_MAX
        for finding in bit102.check_execute(
            execute, line=p.execute.line, element=plugin_path(p.index, "Execute")
        )
    ]
    findings = ordered((*shape.findings, *valid.findings, *risky))
    rejects = any(f.rejects for f in findings)
    return Prepared(findings, valid.rules, None if rejects else valid.candidate)


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
    after_commit: Callable[[ImportOutcome], None] | None = None,
) -> ImportOutcome:
    """Import one file. The caller holds `catalog_lock(session)` and should
    pass `prepared` (computed before the lock). `before_commit(policy_id)` is
    the last step of transaction 1; `after_commit` runs after its commit."""
    prep = prepare(file.data) if prepared is None else prepared
    try:
        with session.transaction() as tx:
            result, findings = store_file(
                tx,
                clock.now(),
                file,
                prep,
                mode=mode,
                actor=actor,
                file_exists=file_exists,
            )
            if before_commit is not None:
                before_commit(result.policy_id)
    except PolicyManagedOnServer as refused:  # #99 (e): no row, no alert
        with session.transaction() as tx:
            alerts.emit(
                PgAuditRepo(tx.conn),
                tx.on_commit,
                alerts.AuditEvent(
                    action="policy.import_refused",
                    target=f"policy:{refused.policy_id}",
                    detail={
                        "policy_id": refused.policy_id,
                        "mode": mode,
                        "file_sha256": file.sha256,
                    },
                ),
                actor=actor.audit,
            )
        raise
    except Abort as stop:  # tx1 rolled back; an error here propagates
        with session.transaction() as tx:
            rejected_id = record(tx, file, mode, actor, stop.pending, now=clock.now())
        return replace(stop.pending, import_id=rejected_id)
    outcome = success(result, findings)
    import_id: int | None = None
    try:
        remove_after_commit(bits_dir, result.remove_after_commit)
        if after_commit is not None:
            after_commit(outcome)
    finally:  # the catalog has committed: its record is always attempted
        try:
            with session.transaction() as tx:
                import_id = record(tx, file, mode, actor, outcome, now=clock.now())
        except Exception as exc:  # the committed catalog change stands
            log.error("bit_import record failed: %s", type(exc).__name__)
    return replace(outcome, import_id=import_id)
