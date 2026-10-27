"""Catalog integrity reads for the start-up check (TS §4.2 L542; #103).
Parameterised statements only; read-only (SELECT on policy, policy_plugin,
plugin and bit_import). The check compares these rows with the files in both
folders and never repairs anything (that is the rebuild).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

type Conn = psycopg.Connection[Any]


@dataclass(frozen=True)
class IntegrityRow:
    """One non-deleted policy for the #103 check. bad_plugins counts listed
    plugins that are not active or are owned by another policy."""

    policy_id: int
    source_file: str
    source_sha256: str
    plugin_count: int
    bad_plugins: int


def integrity_rows(conn: Conn) -> list[IntegrityRow]:
    """#103, the catalog side: every non-deleted policy with its file, hash,
    policy_plugin count and the listed plugins that are wrong."""
    rows = conn.execute(
        "SELECT p.policy_id, p.source_file, p.source_sha256, count(pp.plugin_uuid),"
        " count(pp.plugin_uuid) FILTER (WHERE pl.state <> 'active'"
        " OR pl.owner_policy_id <> p.policy_id) FROM policy p"
        " LEFT JOIN policy_plugin pp ON pp.policy_id = p.policy_id"
        " LEFT JOIN plugin pl ON pl.plugin_uuid = pp.plugin_uuid"
        " WHERE p.deleted_at IS NULL GROUP BY p.policy_id ORDER BY p.policy_id"
    ).fetchall()
    return [
        IntegrityRow(int(i), str(f), str(h), int(n), int(b)) for i, f, h, n, b in rows
    ]


def rejected_files(
    conn: Conn, files: Sequence[tuple[str, str]]
) -> set[tuple[str, str]]:
    """#103, the folder side: which (file_name, file_sha256) pairs have a
    rejected bit_import row."""
    rows = conn.execute(
        "SELECT DISTINCT b.file_name, b.file_sha256 FROM bit_import b"
        " JOIN unnest(CAST(%s AS text[]), CAST(%s AS char(64)[])) AS f (name, sha)"
        " ON b.file_name = f.name AND b.file_sha256 = f.sha"
        " WHERE b.outcome = 'rejected'",
        ([n for n, _ in files], [s for _, s in files]),
    ).fetchall()
    return {(str(n), str(s)) for n, s in rows}
