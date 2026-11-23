"""kubeconfig SQL (TS §5.2; owner decision 2026-11-23). Parameterised
statements only; runs inside the caller's transaction.

content_enc is written here and read only by the agent fetch (part 2); no
read in this module returns it. bitscan_app may UPDATE kubeconfig (replace and
soft delete); a delete overwrites content_enc with '' and keeps the row, so
old scans keep the name.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg


@dataclass(frozen=True)
class KubeconfigRow:
    kubeconfig_id: int
    name: str
    description: str
    cluster_name: str
    server: str
    created_by: int
    created_at: datetime
    replaced_at: datetime | None
    deleted_at: datetime | None


class KubeconfigRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        name: str,
        description: str,
        cluster_name: str,
        server: str,
        content_enc: str,
        created_by: int,
        now: datetime,
    ) -> int | None:
        """The new id, or None when the name is taken (also by a deleted one)."""
        row = self._conn.execute(
            "INSERT INTO kubeconfig (name, description, cluster_name, server,"
            " content_enc, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (name) DO NOTHING RETURNING kubeconfig_id",
            (name, description, cluster_name, server, content_enc, created_by, now),
        ).fetchone()
        return None if row is None else int(row[0])

    def replace(
        self,
        kubeconfig_id: int,
        *,
        description: str | None,
        cluster_name: str,
        server: str,
        content_enc: str,
        now: datetime,
    ) -> str | None:
        """The name of the replaced kubeconfig, or None when it does not exist
        or is deleted."""
        row = self._conn.execute(
            "UPDATE kubeconfig SET description = COALESCE(%s, description),"
            " cluster_name = %s, server = %s, content_enc = %s, replaced_at = %s"
            " WHERE kubeconfig_id = %s AND deleted_at IS NULL RETURNING name",
            (description, cluster_name, server, content_enc, now, kubeconfig_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def soft_delete(self, kubeconfig_id: int, now: datetime) -> str | None:
        row = self._conn.execute(
            "UPDATE kubeconfig SET content_enc = '', deleted_at = %s"
            " WHERE kubeconfig_id = %s AND deleted_at IS NULL RETURNING name",
            (now, kubeconfig_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def get(self, kubeconfig_id: int) -> KubeconfigRow | None:
        row = self._conn.execute(
            "SELECT kubeconfig_id, name, description, cluster_name, server, created_by,"
            " created_at, replaced_at, deleted_at FROM kubeconfig"
            " WHERE kubeconfig_id = %s",
            (kubeconfig_id,),
        ).fetchone()
        return None if row is None else KubeconfigRow(*row)

    def page(
        self, limit: int, after_id: int | None, *, include_deleted: bool
    ) -> list[KubeconfigRow]:
        rows = self._conn.execute(
            "SELECT kubeconfig_id, name, description, cluster_name, server, created_by,"
            " created_at, replaced_at, deleted_at FROM kubeconfig"
            " WHERE kubeconfig_id > %s"
            " AND (%s OR deleted_at IS NULL) ORDER BY kubeconfig_id LIMIT %s",
            (after_id or 0, include_deleted, limit),
        ).fetchall()
        return [KubeconfigRow(*r) for r in rows]
