"""The start-up integrity check (TS §4.2 L542, §8.4 L1291; REQ-165 (4); open
questions #27, #103 and the user's rulings of 2026-10-27: "Crash window",
"Stray `uploaded/` files", the edited `<PolicyName>` and "Folder guard").

It runs after the reconcile, under the caller's catalog lock, and only reads:
it never repairs (that is the rebuild). Every difference is listed in one
`catalog_integrity_failed` alert; a clean catalog raises none. Subjects are
`policy:<id>`, a path relative to the bits folder or a folder label; no file
content is read into a log, an audit detail or an error.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog_integrity import (
    integrity_rows,
    rejected_files,
)
from bitscan_manager.runtime import CatalogSession
from bitscan_manager.services.importer.alerts import Difference, emit, integrity_failed
from bitscan_manager.services.importer.folders import (
    BITS_ROOT,
    UPLOADED,
    ReconcileResult,
    discover,
    read_input,
    unreadable,
)
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.structure import check as check_structure

log = logging.getLogger(__name__)
# Fixed check texts (#103). The unreadable-folder text does not claim the
# folder is missing: it may be a real folder in which a removal was refused.
FOLDER_CHECK = "folder could not be read safely"
STRAY_CHECK = "uploaded file that is not a live policy's file"
RENAMED_CHECK = "uploaded file whose policy name was edited"
MISSING_CHECK = "file missing at source_file"
HASH_CHECK = "file hash differs from source_sha256"
COUNT_CHECK = "policy_plugin count differs from the Plugin elements in the file"
PARSE_CHECK = "file at source_file could not be parsed"
PLUGIN_CHECK = "listed plugin not active or owned by another policy"
UNTRACKED_CHECK = "file is not a policy's source_file and has no rejected import"


def _folder(rel: str) -> str:
    return UPLOADED if rel.startswith(UPLOADED) else BITS_ROOT


def _plugin_count(data: bytes | None) -> int | None:
    """The number of `<Plugin>` elements (parsed, nothing written), or None
    if the file is oversize or not structurally valid."""
    if data is None:
        return None
    parsed = parse_bit(data)
    if parsed.root is None:
        return None
    shape = check_structure(parsed.root, parsed.pi_lines)
    return None if shape.parsed is None else len(shape.parsed.plugins)


def differences(
    session: CatalogSession, bits_dir: Path, reconciled: ReconcileResult
) -> list[Difference]:
    """Every #103 difference, in a fixed order: unreadable folders, the
    reconcile's leftovers, strays and renamed uploads, then the per-policy
    checks, then folder files that nothing accounts for."""
    blind = set(reconciled.unreadable_folders) | set(unreadable(bits_dir))
    found = [Difference(f, FOLDER_CHECK) for f in (BITS_ROOT, UPLOADED) if f in blind]
    found += reconciled.leftovers
    found += [Difference(p, STRAY_CHECK) for p in reconciled.strays]
    found += [Difference(p, RENAMED_CHECK) for p in reconciled.renamed]
    listed = {d.subject for d in found}
    with session.transaction() as tx:
        rows = integrity_rows(tx.conn)
    for row in rows:
        subject = f"policy:{row.policy_id}"
        if row.bad_plugins:
            found.append(Difference(subject, PLUGIN_CHECK))
        if _folder(row.source_file) in blind:
            continue  # its folder is already listed; never read through it
        file = read_input(bits_dir, row.source_file)
        if file is None:
            found.append(Difference(subject, MISSING_CHECK))
        elif file.sha256 != row.source_sha256:
            # A different file: its Plugin count is not comparable.
            found.append(Difference(subject, HASH_CHECK))
        else:
            count = _plugin_count(file.data)
            if count is None:
                found.append(Difference(subject, PARSE_CHECK))
            elif count != row.plugin_count:
                found.append(Difference(subject, COUNT_CHECK))
    live = {row.source_file for row in rows}
    others = [rel for rel in discover(bits_dir) if rel not in live | listed]
    hashed = [(rel, f.sha256) for rel in others if (f := read_input(bits_dir, rel))]
    with session.transaction() as tx:
        rejected = rejected_files(tx.conn, hashed) if hashed else set()
    found += [
        Difference(rel, UNTRACKED_CHECK)
        for rel, sha in hashed
        if (rel, sha) not in rejected
    ]
    return found


def check_and_alert(
    session: CatalogSession, bits_dir: Path, reconciled: ReconcileResult
) -> list[Difference]:
    """Run the check and, if anything differs, write the one alert (the
    first 100 differences and their total, `alerts.integrity_failed`)."""
    found = differences(session, bits_dir, reconciled)
    if not found:
        log.info("catalog integrity check: clean")
        return found
    with session.transaction() as tx:
        emit(
            PgAuditRepo(tx.conn),
            tx.on_commit,
            integrity_failed(found),
            actor="system",
        )
    log.warning("catalog integrity check failed: %d differences", len(found))
    return found
