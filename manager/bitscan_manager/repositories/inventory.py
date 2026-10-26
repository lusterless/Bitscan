"""os_info, package, agent_package and inventory_snapshot SQL (TS §5.2, §3.4).
Parameterised statements only; arrays travel as parameters, never as text.

Runs inside the caller's transaction; never commits. bitscan_app has only
SELECT and INSERT on package and inventory_snapshot (no UPDATE), so package
rows are written with INSERT … ON CONFLICT DO NOTHING and then selected.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from bitscan_manager.repositories.packages import AnchorGone

BATCH = 1000

PackageKey = tuple[str, str, str]  # (name, version, architecture)

_OS_COLS = (
    "os_id",
    "os_version_id",
    "os_pretty_name",
    "kernel_release",
    "architecture",
    "cpu_count",
    "memory_mb",
    "ip_addresses",
    "uptime_s",
    "raw",
    "collected_at",
)
_OS_UPSERT = sql.SQL(
    "INSERT INTO os_info (agent_id, {cols}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,"
    " CAST(%s AS inet[]), %s, %s, %s) ON CONFLICT (agent_id) DO UPDATE SET {sets}"
).format(
    cols=sql.SQL(", ").join(map(sql.Identifier, _OS_COLS)),
    sets=sql.SQL(", ").join(
        sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in _OS_COLS
    ),
)


@dataclass(frozen=True)
class OsInfoRow:
    os_id: str | None
    os_version_id: str | None
    os_pretty_name: str | None
    kernel_release: str | None
    architecture: str | None
    cpu_count: int | None
    memory_mb: int | None
    ip_addresses: list[str]
    uptime_s: int | None
    raw: dict[str, Any]
    collected_at: datetime


@dataclass(frozen=True)
class PackageRow:
    name: str
    version: str
    architecture: str
    source_name: str | None


@dataclass(frozen=True)
class AgentPackageRow:
    """One agent's package line: the four list_sha256 fields and the rest."""

    package_id: int
    name: str
    version: str
    architecture: str
    status: str
    source_name: str | None
    installed_size_kb: int | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class SnapshotRow:
    snapshot_id: int
    list_sha256: str
    package_count: int
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    collected_at: datetime


@dataclass(frozen=True)
class PackageIds:
    ids: dict[PackageKey, int]
    new: frozenset[PackageKey]  # rows this call inserted


def _batches(rows: Sequence[Any]) -> list[Sequence[Any]]:
    return [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]


class InventoryRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def upsert_os_info(self, agent_id: UUID, row: OsInfoRow) -> None:
        values = (
            row.os_id,
            row.os_version_id,
            row.os_pretty_name,
            row.kernel_release,
            row.architecture,
            row.cpu_count,
            row.memory_mb,
            row.ip_addresses,
            row.uptime_s,
            Jsonb(row.raw),
            row.collected_at,
        )
        self._conn.execute(_OS_UPSERT, (agent_id, *values))

    def get_os_info(self, agent_id: UUID) -> OsInfoRow | None:
        row = self._conn.execute(
            "SELECT os_id, os_version_id, os_pretty_name, kernel_release,"
            " architecture, cpu_count, memory_mb, ARRAY(SELECT abbrev(x) FROM"
            " unnest(ip_addresses) WITH ORDINALITY AS u(x, n) ORDER BY n), uptime_s,"
            " raw, collected_at FROM os_info WHERE agent_id = %s",
            (agent_id,),
        ).fetchone()
        return None if row is None else OsInfoRow(*row)

    def insert_packages(self, rows: Sequence[PackageRow]) -> PackageIds:
        """Inserts the unknown rows and returns every row's id. Keys are written
        in sorted order, so concurrent uploads wait on each other's rows in one
        order and cannot deadlock; a concurrent insert of the same key gives one
        row (the later one waits, then selects it)."""
        ordered = sorted(rows, key=lambda r: (r.name, r.version, r.architecture))
        ids: dict[PackageKey, int] = {}
        new: set[PackageKey] = set()
        for batch in _batches(ordered):
            columns = [
                [r.name for r in batch],
                [r.version for r in batch],
                [r.architecture for r in batch],
            ]
            inserted = self._conn.execute(
                "INSERT INTO package (name, version, architecture, source_name)"
                " SELECT * FROM unnest(CAST(%s AS varchar[]), CAST(%s AS varchar[]),"
                " CAST(%s AS varchar[]), CAST(%s AS varchar[]))"
                " ON CONFLICT (name, version, architecture) DO NOTHING"
                " RETURNING name, version, architecture",
                (*columns, [r.source_name for r in batch]),
            ).fetchall()
            new.update((str(n), str(v), str(a)) for n, v, a in inserted)
            found = self._conn.execute(
                "SELECT p.package_id, p.name, p.version, p.architecture FROM package p"
                " JOIN unnest(CAST(%s AS varchar[]), CAST(%s AS varchar[]),"
                " CAST(%s AS varchar[])) AS k(name, version, architecture)"
                " USING (name, version, architecture)",
                columns,
            ).fetchall()
            ids.update(((str(n), str(v), str(a)), int(i)) for i, n, v, a in found)
        return PackageIds(ids, frozenset(new))

    def agent_packages(self, agent_id: UUID) -> list[AgentPackageRow]:
        return self.package_page(agent_id, None, None)

    def upsert_agent_packages(
        self,
        agent_id: UUID,
        rows: Sequence[tuple[int, str, int | None]],
        now: datetime,
    ) -> None:
        """rows: (package_id, status, installed_size_kb). first_seen_at is kept."""
        for batch in _batches(rows):
            self._conn.execute(
                "INSERT INTO agent_package (agent_id, package_id, status,"
                " installed_size_kb, first_seen_at, last_seen_at)"
                " SELECT %s, k.id, k.status, k.size, %s, %s FROM unnest("
                "CAST(%s AS bigint[]), CAST(%s AS varchar[]), CAST(%s AS integer[]))"
                " AS k(id, status, size) ON CONFLICT (agent_id, package_id) DO UPDATE"
                " SET status = EXCLUDED.status, installed_size_kb ="
                " EXCLUDED.installed_size_kb, last_seen_at = EXCLUDED.last_seen_at",
                (agent_id, now, now, *(list(c) for c in zip(*batch, strict=True))),
            )

    def delete_not_listed(self, agent_id: UUID, keep_ids: Sequence[int]) -> int:
        """Removes the agent's rows for packages not in keep_ids; package rows
        stay (retention prunes unreferenced ones, M11)."""
        return self._conn.execute(
            "DELETE FROM agent_package WHERE agent_id = %s AND package_id NOT IN"
            " (SELECT unnest(CAST(%s AS bigint[])))",
            (agent_id, list(keep_ids)),
        ).rowcount

    def insert_snapshot(
        self,
        agent_id: UUID,
        list_sha256: str,
        package_count: int,
        added: list[dict[str, Any]],
        removed: list[dict[str, Any]],
        collected_at: datetime,
    ) -> int:
        row = self._conn.execute(
            "INSERT INTO inventory_snapshot (agent_id, list_sha256, package_count,"
            " added, removed, collected_at) VALUES (%s, %s, %s, %s, %s, %s)"
            " RETURNING snapshot_id",
            (
                agent_id,
                list_sha256,
                package_count,
                Jsonb(added),
                Jsonb(removed),
                collected_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("INSERT … RETURNING returned no row")
        return int(row[0])

    def latest_snapshot(self, agent_id: UUID) -> SnapshotRow | None:
        """The newest snapshot by insertion order (snapshot_id)."""
        row = self._conn.execute(
            "SELECT snapshot_id, list_sha256, package_count, added, removed,"
            " collected_at FROM inventory_snapshot WHERE agent_id = %s"
            " ORDER BY snapshot_id DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return None if row is None else SnapshotRow(*row)

    def package_page(
        self, agent_id: UUID, limit: int | None, after_package_id: int | None
    ) -> list[AgentPackageRow]:
        """One agent's packages ordered by name, architecture, version (#68),
        the version in Debian order (version::debversion, TS §7.2), then as
        text so the key stays total; limit None reads them all.

        after_package_id is the previous page's last row. The cursor holds
        only that id (#89); its sort values are read here from package, in the
        caller's transaction, so paging continues even if the agent no longer
        has that package. AnchorGone if the package row is gone."""
        name: str | None = None
        arch: str | None = None
        version: str | None = None
        if after_package_id is not None:
            anchor = self._conn.execute(
                "SELECT name, architecture, version FROM package WHERE package_id = %s",
                (after_package_id,),
            ).fetchone()
            if anchor is None:
                raise AnchorGone
            name, arch, version = anchor
        rows = self._conn.execute(
            "SELECT p.package_id, p.name, p.version, p.architecture, ap.status,"
            " p.source_name, ap.installed_size_kb, ap.first_seen_at, ap.last_seen_at"
            " FROM agent_package ap JOIN package p USING (package_id)"
            " WHERE ap.agent_id = %s AND (CAST(%s AS text) IS NULL OR"
            " (p.name, p.architecture, p.version::debversion, p.version) >"
            " (CAST(%s AS text), CAST(%s AS text), CAST(%s AS debversion),"
            " CAST(%s AS text)))"
            " ORDER BY p.name, p.architecture, p.version::debversion, p.version"
            " LIMIT %s",
            (agent_id, name, name, arch, version, version, limit),
        ).fetchall()
        return [AgentPackageRow(*r) for r in rows]
