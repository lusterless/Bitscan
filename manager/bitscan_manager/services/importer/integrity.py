"""The start-up catalog integrity check (TS §4.2 L542, §8.4 L1291; REQ-165
(4); open questions #27, #103).

For each non-deleted policy: its file exists at `source_file` with SHA-256
`source_sha256`, its `policy_plugin` count equals the `Plugin` elements in that
file (parsed, nothing written), and every plugin it lists is active and owned
by it. Each `*.bit` file in both folders is a non-deleted policy's
`source_file` or has a `rejected` `bit_import` row for its current hash. It
never repairs anything (that is the rebuild). Nothing here logs.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from bitscan_manager.repositories import catalog_integrity
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import CatalogSession, Tx
from bitscan_manager.services.importer.alerts import Difference, emit, integrity_failed
from bitscan_manager.services.importer.folders import SYSTEM, discover, read_file
from bitscan_manager.services.importer.parse import parse_bit

# The #103 checks, fixed text (a Difference's `check`).
MISSING: Final = "its file is missing"
HASH: Final = "its file's hash differs from source_sha256"
COUNT: Final = "its plugin count differs from its file"
PLUGINS: Final = "a listed plugin is not active or not owned by it"
UNKNOWN: Final = "the file is neither a policy's file nor a rejected import"


def _plugin_count(data: bytes) -> int | None:
    """The `Plugin` elements under `PluginsGroups`, or None if it no longer
    parses (only reached when the hash matches, so not expected)."""
    root = parse_bit(data).root
    if root is None:
        return None
    groups = [c for c in root.children if c.name == "PluginsGroups"]
    return sum(1 for g in groups for c in g.children if c.name == "Plugin")


def check(session: CatalogSession, bits_dir: Path) -> list[Difference]:
    """Every #103 difference, policies first (by id), then folder files (in
    discovery order). The caller holds the catalog lock."""
    with session.transaction() as tx:
        rows = catalog_integrity.integrity_rows(tx.conn)
    found: list[Difference] = []
    for row in rows:
        subject = f"policy:{row.policy_id}"
        read = read_file(bits_dir / row.source_file)
        if read is None:
            found.append(Difference(subject, MISSING))
        elif read[1] != row.source_sha256:
            found.append(Difference(subject, HASH))
        elif read[0] is not None and _plugin_count(read[0]) != row.plugin_count:
            found.append(Difference(subject, COUNT))
        if row.bad_plugins:
            found.append(Difference(subject, PLUGINS))
    sources = {row.source_file for row in rows}
    others: list[tuple[str, str]] = []
    for rel in discover(bits_dir):
        if rel not in sources and (read := read_file(bits_dir / rel)) is not None:
            others.append((rel, read[1]))
    with session.transaction() as tx:
        rejected = catalog_integrity.rejected_files(tx.conn, others)
    found.extend(
        Difference(rel, UNKNOWN) for rel, sha in others if (rel, sha) not in rejected
    )
    return found


def alert(tx: Tx, differences: Sequence[Difference]) -> None:
    """One `catalog.integrity_check` entry, the `catalog_integrity_failed`
    alert, listing the first 100 differences (#103); the caller writes it
    only when there is a difference."""
    emit(
        PgAuditRepo(tx.conn),
        tx.on_commit,
        integrity_failed(differences),
        actor=SYSTEM.audit,
    )
