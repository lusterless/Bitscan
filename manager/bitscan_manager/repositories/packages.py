"""Fleet package search SQL (TS §7, §7.1, §7.2; work/plans/TASK-110.md).

Read-only: SELECT statements only, run inside the caller's transaction. Every
statement is composed from the fixed psycopg.sql fragments below; which ones
are used depends on which filters are set, every value is a named bound
parameter, and no fragment text comes from input. Every literal % in a
fragment is written %% because every statement takes parameters.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql


class VersionOp(StrEnum):
    LT = "lt"
    LE = "le"
    EQ = "eq"
    GE = "ge"
    GT = "gt"


# #83 (f), user 2026-10-24: held packages, and those selected for removal
# whose files are still there, are installed too (the third word is the
# installed state). The only place status=installed is defined.
INSTALLED_STATUSES: Final[tuple[str, ...]] = (
    "install ok installed",
    "hold ok installed",
    "deinstall ok installed",
)


@dataclass(frozen=True)
class SearchFilter:
    """One search, already validated by parse_search. A field left None is
    no filter; statuses None is status=any."""

    q: str | None = None
    name: str | None = None
    version: str | None = None
    version_op: VersionOp | None = None
    arch: str | None = None
    statuses: tuple[str, ...] | None = INSTALLED_STATUSES
    os_id: str | None = None
    os_version_id: str | None = None
    tag: str | None = None
    host: str | None = None
    agent_id: UUID | None = None


@dataclass(frozen=True)
class PackageRow:
    package_id: int  # cursor anchor only; never in a response
    name: str
    version: str
    architecture: str
    status: str
    agent_id: UUID
    hostname: str


@dataclass(frozen=True)
class PackageGroup:
    package_id: int  # cursor anchor only
    name: str
    version: str
    architecture: str
    host_count: int


@dataclass(frozen=True)
class HostGroup:
    agent_id: UUID
    hostname: str
    package_count: int


RowAnchor = tuple[int, UUID]  # (package_id, agent_id) of the previous last row


class AnchorGone(Exception):
    """The package or agent a cursor points at no longer exists."""


def like_escape(value: str) -> str:
    """value as a literal LIKE pattern under ESCAPE '\\' (backslash first)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_TABLES = sql.SQL(
    "agent_package ap JOIN package p ON p.package_id = ap.package_id"
    " JOIN agent a ON a.agent_id = ap.agent_id"
)
# #83 (e): decommissioned hosts keep their rows but are never searched.
_SCOPE = sql.SQL("a.status <> 'decommissioned'")
# #83 (a): case-insensitive substring, or pg_trgm similarity (the % operator).
_Q = sql.SQL("(p.name ILIKE %(q_like)s ESCAPE '\\' OR p.name %% %(q)s)")
_NAME = sql.SQL("p.name = %(name)s")
_VERSION = sql.SQL("p.version = %(version)s")  # TS §7.1 "Exact version"
# version_op compares in Debian order only (TS §7.2), never as text.
_VERSION_OP: Final[Mapping[VersionOp, sql.Composable]] = {
    VersionOp.LT: sql.SQL("p.version::debversion < CAST(%(version)s AS debversion)"),
    VersionOp.LE: sql.SQL("p.version::debversion <= CAST(%(version)s AS debversion)"),
    VersionOp.EQ: sql.SQL("p.version::debversion = CAST(%(version)s AS debversion)"),
    VersionOp.GE: sql.SQL("p.version::debversion >= CAST(%(version)s AS debversion)"),
    VersionOp.GT: sql.SQL("p.version::debversion > CAST(%(version)s AS debversion)"),
}
_ARCH = sql.SQL("p.architecture = %(arch)s")
_STATUSES = sql.SQL("ap.status = ANY(CAST(%(statuses)s AS text[]))")
_OS = sql.SQL(
    "EXISTS (SELECT 1 FROM os_info o WHERE o.agent_id = a.agent_id"
    " AND o.os_id = %(os_id)s)"
)
_OS_VERSION = sql.SQL(
    "EXISTS (SELECT 1 FROM os_info o WHERE o.agent_id = a.agent_id"
    " AND o.os_id = %(os_id)s AND o.os_version_id = %(os_version_id)s)"
)
_TAG = sql.SQL(
    "EXISTS (SELECT 1 FROM agent_tag t WHERE t.agent_id = a.agent_id"
    " AND t.tag = %(tag)s)"
)
_HOST = sql.SQL("a.hostname ILIKE %(host_like)s ESCAPE '\\'")  # #83 (d)
_AGENT = sql.SQL("ap.agent_id = %(agent_id)s")


# #83 (b) orders. The version text after the Debian version keeps the order
# total when 1.0 and 1.0-0 are equal in Debian order; the keyset tuple is the
# order tuple, compared in WHERE (the group keys are the order columns).
@dataclass(frozen=True)
class _Shape:
    select: sql.SQL
    group: sql.SQL
    order: sql.SQL
    after: sql.SQL  # the order tuple > the anchor's values
    row: type[PackageRow] | type[PackageGroup] | type[HostGroup]


_SHAPES: Final[Mapping[str, _Shape]] = {
    "rows": _Shape(
        sql.SQL(
            "p.package_id, p.name, p.version, p.architecture, ap.status,"
            " a.agent_id, a.hostname"
        ),
        sql.SQL(""),
        sql.SQL(
            "p.name, p.version::debversion, p.version, p.architecture,"
            " a.hostname, a.agent_id"
        ),
        sql.SQL(
            "(p.name, p.version::debversion, p.version, p.architecture,"
            " a.hostname, a.agent_id) > (CAST(%(k_name)s AS text),"
            " CAST(%(k_deb)s AS debversion), CAST(%(k_version)s AS text),"
            " CAST(%(k_arch)s AS text), CAST(%(k_host)s AS text),"
            " CAST(%(k_agent)s AS uuid))"
        ),
        PackageRow,
    ),
    "package": _Shape(
        sql.SQL("p.package_id, p.name, p.version, p.architecture, count(*)"),
        sql.SQL(" GROUP BY p.package_id"),
        sql.SQL("p.name, p.version::debversion, p.version, p.architecture"),
        sql.SQL(
            "(p.name, p.version::debversion, p.version, p.architecture) >"
            " (CAST(%(k_name)s AS text), CAST(%(k_deb)s AS debversion),"
            " CAST(%(k_version)s AS text), CAST(%(k_arch)s AS text))"
        ),
        PackageGroup,
    ),
    "host": _Shape(
        sql.SQL("a.agent_id, a.hostname, count(*)"),
        sql.SQL(" GROUP BY a.agent_id"),
        sql.SQL("a.hostname, a.agent_id"),
        sql.SQL(
            "(a.hostname, a.agent_id) >"
            " (CAST(%(k_host)s AS text), CAST(%(k_agent)s AS uuid))"
        ),
        HostGroup,
    ),
}
_SELECT = sql.SQL("SELECT {select} FROM {tables} WHERE {where}{group} ORDER BY {order}")
_LIMIT = sql.SQL(" LIMIT %(limit)s")
# The export's count stops at cap + 1 rows or groups (TASK-114, #84 (a)).
_COUNT = sql.SQL(
    "SELECT count(*) FROM (SELECT 1 FROM {tables} WHERE {where}{group} LIMIT %(cap)s) s"
)


def _where(f: SearchFilter) -> tuple[list[sql.Composable], dict[str, Any]]:
    """The fragments of the set filters, combined with AND (TS §7.1 L1212),
    and their bound values."""
    parts: list[sql.Composable] = [_SCOPE]
    params: dict[str, Any] = {}

    def add(part: sql.Composable, **values: Any) -> None:
        parts.append(part)
        params.update(values)

    if f.q is not None:
        add(_Q, q=f.q, q_like="%" + like_escape(f.q) + "%")
    if f.name is not None:
        add(_NAME, name=f.name)
    if f.version_op is not None:
        add(_VERSION_OP[f.version_op], version=f.version)
    elif f.version is not None:
        add(_VERSION, version=f.version)
    if f.arch is not None:
        add(_ARCH, arch=f.arch)
    if f.statuses is not None:
        add(_STATUSES, statuses=list(f.statuses))
    if f.os_version_id is not None:
        add(_OS_VERSION, os_id=f.os_id, os_version_id=f.os_version_id)
    elif f.os_id is not None:
        add(_OS, os_id=f.os_id)
    if f.tag is not None:
        add(_TAG, tag=f.tag)
    if f.host is not None:
        add(_HOST, host_like="%" + like_escape(f.host) + "%")
    if f.agent_id is not None:
        add(_AGENT, agent_id=f.agent_id)
    return parts, params


class PackageSearchRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def rows(
        self, f: SearchFilter, limit: int, after: RowAnchor | None
    ) -> list[PackageRow]:
        """Rows without group_by; the route asks for limit + 1."""
        keys: dict[str, Any] | None = None
        if after is not None:
            name, version, arch, host = self._anchor(
                "SELECT p.name, p.version, p.architecture, a.hostname"
                " FROM package p, agent a WHERE p.package_id = %s AND a.agent_id = %s",
                after,
            )
            keys = {
                "k_name": name,
                "k_deb": version,
                "k_version": version,
                "k_arch": arch,
                "k_host": host,
                "k_agent": after[1],
            }
        return [PackageRow(*r) for r in self._page("rows", f, keys, limit)]

    def package_groups(
        self, f: SearchFilter, limit: int, after: int | None
    ) -> list[PackageGroup]:
        """group_by=package: host_count is count(*), one row per host, since
        (agent_id, package_id) is the agent_package primary key."""
        keys: dict[str, Any] | None = None
        if after is not None:
            name, version, arch = self._anchor(
                "SELECT name, version, architecture FROM package WHERE package_id = %s",
                (after,),
            )
            keys = {
                "k_name": name,
                "k_deb": version,
                "k_version": version,
                "k_arch": arch,
            }
        return [PackageGroup(*r) for r in self._page("package", f, keys, limit)]

    def host_groups(
        self, f: SearchFilter, limit: int, after: UUID | None
    ) -> list[HostGroup]:
        """group_by=host: package_count is the host's matching rows."""
        keys: dict[str, Any] | None = None
        if after is not None:
            (host,) = self._anchor(
                "SELECT hostname FROM agent WHERE agent_id = %s", (after,)
            )
            keys = {"k_host": host, "k_agent": after}
        return [HostGroup(*r) for r in self._page("host", f, keys, limit)]

    # TASK-114: the CSV export reads the whole result set in one snapshot.

    def read_only_snapshot(self) -> None:
        """Must be the transaction's first statement (PostgreSQL refuses it
        later): the count and the read then see one snapshot, and nothing can
        be written (REQ-115 (5))."""
        self._conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    def count_capped(self, f: SearchFilter, shape: str, cap: int) -> int:
        """min(the rows or groups of the result, cap + 1); never counts past."""
        s = _SHAPES[shape]
        parts, params = _where(f)
        params["cap"] = cap + 1
        query = _COUNT.format(
            tables=_TABLES, where=sql.SQL(" AND ").join(parts), group=s.group
        )
        row = self._conn.execute(query, params).fetchone()
        return int(row[0]) if row is not None else 0

    def stream(
        self, f: SearchFilter, shape: str
    ) -> Iterator[PackageRow | PackageGroup | HostGroup]:
        """The whole result in the paging order, through a server-side cursor;
        consume it inside the transaction."""
        query, params = self._statement(shape, f, None)
        row = _SHAPES[shape].row
        with self._conn.cursor(name="package_export") as cur:
            cur.itersize = 1000
            cur.execute(query, params)
            for r in cur:
                yield row(*r)

    def _anchor(self, query: LiteralString, params: tuple[Any, ...]) -> tuple[Any, ...]:
        """The sort values of a cursor's ids (cursors hold ids only, #89)."""
        row = self._conn.execute(query, params).fetchone()
        if row is None:
            raise AnchorGone
        return tuple(row)

    def _statement(
        self, shape: str, f: SearchFilter, keys: dict[str, Any] | None
    ) -> tuple[sql.Composed, dict[str, Any]]:
        """The shape's ordered query; keys (the anchor values) add the keyset
        condition."""
        s = _SHAPES[shape]
        parts, params = _where(f)
        if keys is not None:
            parts.append(s.after)
            params.update(keys)
        query = _SELECT.format(
            select=s.select,
            tables=_TABLES,
            where=sql.SQL(" AND ").join(parts),
            group=s.group,
            order=s.order,
        )
        return query, params

    def _page(
        self, shape: str, f: SearchFilter, keys: dict[str, Any] | None, limit: int
    ) -> list[tuple[Any, ...]]:
        query, params = self._statement(shape, f, keys)
        params["limit"] = limit
        return self._conn.execute(query + _LIMIT, params).fetchall()
