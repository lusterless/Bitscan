"""Results of one scan as pages and as CSV (TS §6.2 L1083, L1123, §4.5 L603,
§4.4 L585, §6.3 L1144; REQ-267 to REQ-269; open questions #144, #146; plan
work/plans/TASK-235.md §4).

Each call is one REPEATABLE READ, READ ONLY transaction: the snapshot, the
scan check (an unknown scan is ScanNotFound, not an empty answer), then one
read. `with_output` comes from `results_view.include_output(role)`, where
`role` is the caller's current role (TS §6.2 L1083), never the token kind;
without it the repository's viewer statement never reads stdout or stderr.
The CSV cap is checked before any text is built (#146 (e)).

SELECT only; nothing is logged.
"""

from dataclasses import dataclass
from uuid import UUID

from bitscan_manager.repositories import result_reads
from bitscan_manager.runtime import Database
from bitscan_manager.services.jobs import results_view
from bitscan_manager.services.jobs.results_view import CSV_MAX_ROWS, ResultQuery
from bitscan_manager.services.jobs.scan_views import ScanNotFound

__all__ = ["ResultPage", "ScanNotFound", "TooManyRows", "results_csv", "results_page"]


class TooManyRows(Exception):
    """The export is over CSV_MAX_ROWS rows (400, "narrow the filters")."""


@dataclass(frozen=True)
class ResultPage:
    """`items` have the ScanResultItem keys, plus stdout and stderr exactly
    when `with_output`; `next_after` is the keyset of the last item when
    another page exists, else None."""

    items: list[dict[str, object]]
    next_after: tuple[UUID, int] | None
    with_output: bool


def results_page(
    db: Database,
    scan_id: UUID,
    query: ResultQuery,
    role: str,
    limit: int,
    after: tuple[UUID, int] | None,
) -> ResultPage:
    """At most `limit` items after the keyset `(agent_id, position)`."""
    with_output = results_view.include_output(role)
    with db.transaction() as tx:
        result_reads.read_only_snapshot(tx.conn)  # the first statement
        if not result_reads.exists(tx.conn, scan_id):
            raise ScanNotFound
        rows = result_reads.results_page(
            tx.conn,
            scan_id,
            status=query.status,
            agent_id=query.agent_id,
            with_output=with_output,
            after=after,
            limit=limit + 1,
        )
    shown = rows[:limit]
    more = len(rows) > limit and bool(shown)
    return ResultPage(
        items=[results_view.item(r, with_output=with_output) for r in shown],
        next_after=(shown[-1].agent_id, shown[-1].position) if more else None,
        with_output=with_output,
    )


def results_csv(db: Database, scan_id: UUID, query: ResultQuery, role: str) -> str:
    """The whole result set as CSV text. Raises TooManyRows before building
    any text when it is over CSV_MAX_ROWS rows."""
    with_output = results_view.include_output(role)
    with db.transaction() as tx:
        result_reads.read_only_snapshot(tx.conn)
        if not result_reads.exists(tx.conn, scan_id):
            raise ScanNotFound
        rows = result_reads.results_export(
            tx.conn,
            scan_id,
            status=query.status,
            agent_id=query.agent_id,
            with_output=with_output,
            max_rows=CSV_MAX_ROWS,
        )
    if len(rows) > CSV_MAX_ROWS:
        raise TooManyRows
    return results_view.csv_text(rows, with_output=with_output)
