"""Fleet package search (TS §7, §7.1; work/plans/TASK-113.md).

The route parses the query (parse_search) and the cursor, then calls search
inside one transaction. Cursor keys hold ids only (#89), never stored text.
"""

from collections.abc import Iterator, Mapping
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.packages import (
    HostGroup,
    PackageGroup,
    PackageRow,
    RowAnchor,
    SearchFilter,
)
from bitscan_manager.services.packages.csv_export import write_csv
from bitscan_manager.services.packages.query import GroupBy, SearchQuery


class SearchStore(Protocol):  # PackageSearchRepo satisfies it
    def rows(
        self, f: SearchFilter, limit: int, after: RowAnchor | None
    ) -> list[PackageRow]: ...

    def package_groups(
        self, f: SearchFilter, limit: int, after: int | None
    ) -> list[PackageGroup]: ...

    def host_groups(
        self, f: SearchFilter, limit: int, after: UUID | None
    ) -> list[HostGroup]: ...


Anchor = RowAnchor | int | UUID
Found = list[PackageRow] | list[PackageGroup] | list[HostGroup]


def search(
    store: SearchStore, query: SearchQuery, limit: int, after: Anchor | None
) -> Found:
    """limit is what the store is asked for (the route passes page limit + 1).
    after must match the query's shape (the route decodes it from the
    cursor). AnchorGone passes through."""
    if query.group_by is GroupBy.PACKAGE:
        if not (after is None or isinstance(after, int)):
            raise TypeError("a package-group anchor is a package_id")
        return store.package_groups(query.filter, limit, after)
    if query.group_by is GroupBy.HOST:
        if not (after is None or isinstance(after, UUID)):
            raise TypeError("a host-group anchor is an agent_id")
        return store.host_groups(query.filter, limit, after)
    if not (after is None or isinstance(after, tuple)):
        raise TypeError("a row anchor is (package_id, agent_id)")
    return store.rows(query.filter, limit, after)


# ------------------------------------------------- CSV export (TASK-114, #84)

CSV_MAX_ROWS: Final = 100_000  # #84 (a); data rows, the header not counted
# #84 (b): the JSON field names of each shape, in the TS §7.1 order.
CSV_HEADERS: Final[Mapping[str, tuple[str, ...]]] = {
    "rows": ("name", "version", "architecture", "status", "agent_id", "hostname"),
    "package": ("name", "version", "architecture", "host_count"),
    "host": ("agent_id", "hostname", "package_count"),
}


class ExportStore(Protocol):  # PackageSearchRepo satisfies it
    def count_capped(self, f: SearchFilter, shape: str, cap: int) -> int: ...

    def stream(
        self, f: SearchFilter, shape: str
    ) -> Iterator[PackageRow | PackageGroup | HostGroup]: ...


class TooManyRows(Exception):
    """The result is over the export cap; nothing was written."""


def _cells(item: PackageRow | PackageGroup | HostGroup) -> list[str]:
    """The JSON values as text, in the CSV_HEADERS order (UUIDs lower-case)."""
    if isinstance(item, PackageRow):
        return [
            item.name,
            item.version,
            item.architecture,
            item.status,
            str(item.agent_id),
            item.hostname,
        ]
    if isinstance(item, PackageGroup):
        return [item.name, item.version, item.architecture, str(item.host_count)]
    return [str(item.agent_id), item.hostname, str(item.package_count)]


def export_csv(store: ExportStore, query: SearchQuery, cap: int = CSV_MAX_ROWS) -> str:
    """The whole result set as one CSV document through the shared writer
    (every cell escaped, TS §6.3 L1142). Raises TooManyRows before reading
    any row when there are more than cap."""
    shape = query.shape()
    if store.count_capped(query.filter, shape, cap) > cap:
        raise TooManyRows
    rows = (_cells(item) for item in store.stream(query.filter, shape))
    return write_csv(CSV_HEADERS[shape], rows)
