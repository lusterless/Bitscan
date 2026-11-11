"""Results read SQL for the results views and CSV (TS §4.5 L603, §4.4 L585,
§6.2 L1123; REQ-267, REQ-269, REQ-272; #119, #144; PD-46; plan
work/plans/TASK-235.md §3). SELECT only, parameterised statements only.

PD-46: every statement begins with M8's `results._EFFECTIVE`, imported, never
copied, so the latest-re-evaluation rule keeps one SQL form (REQ-197). Then:
the planned plugins of each host's original job, in payload order (`WITH
ORDINALITY`); each original job's eval_spec entries, for the name, Operator
and ExpectedResult of a plugin that was not run (never the current catalog);
the effective rows; and the back-join to `scan_result` on the full key, so
partitions prune on `job_created_at`. `scan_result_reeval` is read once per
statement, in `_EFFECTIVE` (no per-row subquery).

`stdout` and `stderr` are selected only when the caller may see them; the
viewer variant selects NULL, so a viewer's output never leaves the database.
Each function runs in the caller's transaction and never commits.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

from bitscan_manager.repositories import results as _m8

type Conn = psycopg.Connection[Any]

# Effective and original codes, as TS §5.2 scan_result.eval_code.
_CODES: Final = {"PASS": 0, "FAIL": 1, "ERROR": 2}
_NOT_RUN: Final = "NOT_RUN"
_WITH_OUTPUT: Final = sql.SQL("r.stdout, r.stderr")
_WITHOUT_OUTPUT: Final = sql.SQL("NULL::text, NULL::text")

_ROWS: Final = sql.SQL(
    "{effective},"
    " planned AS (SELECT j.agent_id, j.job_id AS orig_job_id, p.ord,"
    " CAST(p.item ->> 'plugin_uuid' AS uuid) AS plugin_uuid,"
    " p.item ->> 'execute' AS planned_execute FROM jobs j"
    " CROSS JOIN LATERAL jsonb_array_elements(j.payload -> 'plugins')"
    " WITH ORDINALITY AS p(item, ord) WHERE j.retry_of IS NULL),"
    " specs AS (SELECT j.job_id, CAST(s.item ->> 'plugin_uuid' AS uuid)"
    " AS plugin_uuid, s.item ->> 'name' AS name, s.item ->> 'operator' AS operator,"
    " s.item ->> 'expected' AS expected FROM jobs j"
    " JOIN scan_job sj ON sj.job_id = j.job_id"
    " CROSS JOIN LATERAL jsonb_array_elements(sj.eval_spec -> 'plugins') AS s(item)"
    " WHERE j.retry_of IS NULL)"
    " SELECT pl.agent_id, a.hostname, pl.ord, pl.plugin_uuid, pl.orig_job_id,"
    " e.job_id, e.original_code, e.original_detail, e.code, e.detail,"
    " e.policy_version, e.reevaluated_by, e.reevaluated_at,"
    " CASE WHEN e.job_id IS NULL THEN s.name ELSE r.plugin_name_snap END,"
    " CASE WHEN e.job_id IS NULL THEN s.operator ELSE r.operator_snap::text END,"
    " CASE WHEN e.job_id IS NULL THEN s.expected ELSE r.expected_snap END,"
    " CASE WHEN e.job_id IS NULL THEN pl.planned_execute ELSE r.execute_snap END,"
    " r.exit_code, r.timed_out, r.truncated, r.started_at, r.finished_at,"
    " r.received_at, {output}"
    " FROM planned pl JOIN agent a ON a.agent_id = pl.agent_id"
    " LEFT JOIN eff e ON e.agent_id = pl.agent_id AND e.plugin_uuid = pl.plugin_uuid"
    " LEFT JOIN jobs rj ON rj.job_id = e.job_id"
    " LEFT JOIN scan_result r ON r.job_id = e.job_id"
    " AND r.plugin_uuid = e.plugin_uuid AND r.job_created_at = rj.created_at"
    " LEFT JOIN specs s ON s.job_id = pl.orig_job_id"
    " AND s.plugin_uuid = pl.plugin_uuid"
    " WHERE (%(agent_id)s::uuid IS NULL OR pl.agent_id = %(agent_id)s::uuid)"
    " AND (%(any_status)s OR (%(not_run)s AND e.job_id IS NULL)"
    " OR e.code = %(code)s::smallint)"
    " AND (%(after_agent)s::uuid IS NULL"
    " OR (pl.agent_id, pl.ord) > (%(after_agent)s::uuid, %(after_ord)s::bigint))"
    " ORDER BY pl.agent_id, pl.ord LIMIT %(limit)s"
)
# Operator and admin; and the viewer variant, which never reads the output.
_PAGE: Final = _ROWS.format(effective=_m8._EFFECTIVE, output=_WITH_OUTPUT)
_PAGE_VIEWER: Final = _ROWS.format(effective=_m8._EFFECTIVE, output=_WITHOUT_OUTPUT)


class UnreadableRow(Exception):
    """A planned plugin with no result has no eval_spec entry (M9 always
    writes one per payload plugin, #117). Fixed text only."""


@dataclass(frozen=True, slots=True)
class ResultRow:
    """One planned plugin of one host: its result in the unit (original or
    retry), or Not run (`job_id` None and every result field None)."""

    agent_id: UUID
    hostname: str  # the agent's current hostname
    position: int  # 1-based position in the original job's payload
    plugin_uuid: UUID
    orig_job_id: UUID
    job_id: UUID | None  # the job holding the result; None = Not run
    original_code: int | None  # scan_result.eval_code
    original_detail: str | None
    code: int | None  # the latest re-evaluation's, else the original's (#119)
    detail: str | None
    reeval_policy_version: int | None
    reevaluated_by: int | None
    reevaluated_at: datetime | None
    plugin_name: str  # the snapshot, or the eval_spec name when not run
    operator: str
    expected: str
    execute: str  # the snapshot, or the payload's execute when not run
    exit_code: int | None
    timed_out: bool | None
    truncated: bool | None
    started_at: datetime | None
    finished_at: datetime | None
    received_at: datetime | None
    stdout: str | None  # always None in the viewer variant
    stderr: str | None

    @property
    def retry(self) -> bool:
        """The result came to the retry, not the original job."""
        return self.job_id is not None and self.job_id != self.orig_job_id


def _opt_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _text(value: object) -> str:
    if value is None:
        raise UnreadableRow("a planned plugin has no eval_spec entry")
    return str(value)


def _opt_bool(value: object) -> bool | None:
    return None if value is None else bool(value)


def _row(r: Any) -> ResultRow:
    return ResultRow(
        agent_id=UUID(str(r[0])),
        hostname=str(r[1]),
        position=int(r[2]),
        plugin_uuid=UUID(str(r[3])),
        orig_job_id=UUID(str(r[4])),
        job_id=None if r[5] is None else UUID(str(r[5])),
        original_code=_opt_int(r[6]),
        original_detail=_opt_str(r[7]),
        code=_opt_int(r[8]),
        detail=_opt_str(r[9]),
        reeval_policy_version=_opt_int(r[10]),
        reevaluated_by=_opt_int(r[11]),
        reevaluated_at=r[12],
        plugin_name=_text(r[13]),
        operator=_text(r[14]),
        expected=_text(r[15]),
        execute=_text(r[16]),
        exit_code=_opt_int(r[17]),
        timed_out=_opt_bool(r[18]),
        truncated=_opt_bool(r[19]),
        started_at=r[20],
        finished_at=r[21],
        received_at=r[22],
        stdout=_opt_str(r[23]),
        stderr=_opt_str(r[24]),
    )


def _read(
    conn: Conn,
    scan_id: UUID,
    *,
    status: str | None,
    agent_id: UUID | None,
    with_output: bool,
    after: tuple[UUID, int] | None,
    limit: int,
) -> list[ResultRow]:
    if status is not None and status != _NOT_RUN and status not in _CODES:
        raise ValueError("unknown status")
    statement = _PAGE if with_output else _PAGE_VIEWER
    params = {
        "scan_id": scan_id,
        "agent_id": agent_id,
        "any_status": status is None,
        "not_run": status == _NOT_RUN,
        "code": None if status is None else _CODES.get(status),
        "after_agent": None if after is None else after[0],
        "after_ord": None if after is None else after[1],
        "limit": limit,
    }
    return [_row(r) for r in conn.execute(statement, params).fetchall()]


def read_only_snapshot(conn: Conn) -> None:
    """Must be the transaction's first statement (PostgreSQL refuses it
    later): every read then sees one snapshot and nothing can be written."""
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def exists(conn: Conn, scan_id: UUID) -> bool:
    """So an unknown scan is a 404, not an empty page."""
    found = conn.execute(
        "SELECT 1 FROM scan WHERE scan_id = %(scan_id)s", {"scan_id": scan_id}
    ).fetchone()
    return found is not None


def results_page(
    conn: Conn,
    scan_id: UUID,
    *,
    status: str | None,
    agent_id: UUID | None,
    with_output: bool,
    after: tuple[UUID, int] | None,
    limit: int,
) -> list[ResultRow]:
    """At most `limit` rows after the keyset `(agent_id, position)`, ordered
    by agent_id then payload position. `status` is PASS, FAIL or ERROR (on
    the effective code), NOT_RUN, or None for all; [] for an unknown scan."""
    return _read(
        conn,
        scan_id,
        status=status,
        agent_id=agent_id,
        with_output=with_output,
        after=after,
        limit=limit,
    )


def results_export(
    conn: Conn,
    scan_id: UUID,
    *,
    status: str | None,
    agent_id: UUID | None,
    with_output: bool,
    max_rows: int,
) -> list[ResultRow]:
    """The whole set in page order, read with LIMIT max_rows + 1, so the
    caller can refuse an over-cap export before building any text."""
    return _read(
        conn,
        scan_id,
        status=status,
        agent_id=agent_id,
        with_output=with_output,
        after=None,
        limit=max_rows + 1,
    )
