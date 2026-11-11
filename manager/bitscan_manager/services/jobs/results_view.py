"""Results view rules: the status filter, who sees raw output, the item
mapping and the results CSV (TS §6.2 L1083, L1123, §6.3 L1144, §4.5 L603,
§4.4 L585; REQ-267 to REQ-269; open questions #144, #146; plan
work/plans/TASK-235.md §2).

`include_output` is the only place the role rule lives: stdout and stderr go
to operator and admin only, whatever the token kind, and an unknown role
gets none (fails closed). Without output, an item has no `stdout` or
`stderr` key and the CSV no such columns; they are left out, not emptied.
Every CSV cell, header included, goes through M5's `csv_export.write_csv`.

Pure: no I/O, no logging, no clock. Errors carry a parameter name only.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from bitscan_manager.repositories.result_reads import ResultRow
from bitscan_manager.services.packages.csv_export import write_csv

Status = Literal["PASS", "FAIL", "ERROR", "NOT_RUN"]
STATUSES: Final[tuple[Status, ...]] = ("PASS", "FAIL", "ERROR", "NOT_RUN")
CSV_MAX_ROWS: Final = 100_000  # #146 (e)
CSV_HEADER: Final = (
    "hostname",
    "agent_id",
    "plugin_uuid",
    "plugin_name",
    "result",
    "eval_detail",
    "original_result",
    "original_eval_detail",
    "reevaluated_at",
    "reeval_policy_version",
    "exit_code",
    "timed_out",
    "truncated",
    "started_at",
    "finished_at",
    "job_id",
    "retry",
)
OUTPUT_COLUMNS: Final = ("stdout", "stderr")
_OUTPUT_ROLES: Final = frozenset({"operator", "admin"})


class InvalidResultQuery(Exception):
    """A results filter is not allowed. The message is the parameter name."""


@dataclass(frozen=True)
class ResultQuery:
    status: Status | None
    agent_id: UUID | None


def parse_query(status: str | None, agent_id: UUID | None) -> ResultQuery:
    """#144 (d): `status` is one of PASS, FAIL, ERROR, NOT_RUN, or absent."""
    if status is None:
        return ResultQuery(None, agent_id)
    for known in STATUSES:
        if status == known:
            return ResultQuery(known, agent_id)
    raise InvalidResultQuery("status")


def include_output(role: str) -> bool:
    """True for operator and admin only (TS §6.2 L1123)."""
    return role in _OUTPUT_ROLES


def _verdict(code: int | None) -> str | None:
    """As the generated `scan_result.result` column (TS §5.2)."""
    if code is None:
        return None
    return {0: "PASS", 1: "FAIL"}.get(code, "ERROR")


def item(row: ResultRow, *, with_output: bool) -> dict[str, object]:
    """The keys of ScanResultItem, plus stdout and stderr only with output."""
    out: dict[str, object] = {
        "agent_id": row.agent_id,
        "hostname": row.hostname,
        "job_id": row.job_id,
        "retry": row.retry,
        "plugin_uuid": row.plugin_uuid,
        "plugin_name": row.plugin_name,
        "result": _verdict(row.code),
        "eval_detail": row.detail,
        "original_result": _verdict(row.original_code),
        "original_eval_detail": row.original_detail,
        "reeval_policy_version": row.reeval_policy_version,
        "reevaluated_by": row.reevaluated_by,
        "reevaluated_at": row.reevaluated_at,
        "operator": row.operator,
        "expected": row.expected,
        "execute": row.execute,
        "exit_code": row.exit_code,
        "timed_out": row.timed_out,
        "truncated": row.truncated,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "received_at": row.received_at,
    }
    if with_output:
        out["stdout"] = row.stdout
        out["stderr"] = row.stderr
    return out


def _cell(value: object) -> str:
    """#146 (b): null empty, booleans true/false, times RFC 3339 UTC."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _record(row: ResultRow, with_output: bool) -> Sequence[str]:
    values: list[object] = [
        row.hostname,
        row.agent_id,
        row.plugin_uuid,
        row.plugin_name,
        _verdict(row.code),
        row.detail,
        _verdict(row.original_code),
        row.original_detail,
        row.reevaluated_at,
        row.reeval_policy_version,
        row.exit_code,
        row.timed_out,
        row.truncated,
        row.started_at,
        row.finished_at,
        row.job_id,
        row.retry,
    ]
    if with_output:
        values += [row.stdout, row.stderr]
    return [_cell(v) for v in values]


def csv_header(*, with_output: bool) -> tuple[str, ...]:
    return CSV_HEADER + OUTPUT_COLUMNS if with_output else CSV_HEADER


def csv_text(rows: Iterable[ResultRow], *, with_output: bool) -> str:
    """The #146 header, then one record per row, in the given order."""
    return write_csv(
        csv_header(with_output=with_output),
        (_record(r, with_output) for r in rows),
    )
