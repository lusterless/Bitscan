"""scan_schedule SQL (TS §5.2 L846–L857, §4.4 L557, §6.2 L1124; #122 (h),
#128 (d)). Parameterised statements only.

Each function runs in the caller's transaction and never commits. bitscan_app
holds SELECT, INSERT, UPDATE and DELETE on scan_schedule; it only reads scan
and policy here. Deleting a schedule leaves its scans, whose schedule_id the
foreign key sets to NULL (L864). Column names in an update come from a fixed
map, never from the caller.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

type Conn = psycopg.Connection[Any]

_COLS: Final = sql.SQL(
    "schedule_id, name, policy_id, target, cron, timezone, enabled, last_run_at,"
    " next_run_at, created_by"
)
# The columns an update may change (#122 (h): policy_id and created_by never).
_UPDATABLE: Final = frozenset(
    {"name", "target", "cron", "timezone", "enabled", "next_run_at"}
)


@dataclass(frozen=True)
class ScheduleRow:
    schedule_id: int
    name: str
    policy_id: int
    target: dict[str, Any]
    cron: str
    timezone: str
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_by: int


def _row(r: Any) -> ScheduleRow:
    return ScheduleRow(
        schedule_id=int(r[0]),
        name=str(r[1]),
        policy_id=int(r[2]),
        target=dict(r[3]),
        cron=str(r[4]),
        timezone=str(r[5]),
        enabled=bool(r[6]),
        last_run_at=r[7],
        next_run_at=r[8],
        created_by=int(r[9]),
    )


def _value(column: str, value: object) -> object:
    return Jsonb(value) if column == "target" else value


def insert(
    conn: Conn,
    *,
    name: str,
    policy_id: int,
    target: Mapping[str, Any],
    cron: str,
    timezone: str,
    enabled: bool,
    next_run_at: datetime | None,
    created_by: int,
) -> ScheduleRow:
    query = sql.SQL(
        "INSERT INTO scan_schedule (name, policy_id, target, cron, timezone, enabled,"
        " next_run_at, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING {}"
    ).format(_COLS)
    params = (name, policy_id, Jsonb(dict(target)), cron, timezone, enabled)
    row = conn.execute(query, (*params, next_run_at, created_by)).fetchone()
    if row is None:  # INSERT … RETURNING gives exactly one row
        raise RuntimeError("INSERT … RETURNING returned no row")
    return _row(row)


def get(conn: Conn, schedule_id: int, *, lock: bool = False) -> ScheduleRow | None:
    query = sql.SQL("SELECT {} FROM scan_schedule WHERE schedule_id = %s{}").format(
        _COLS, sql.SQL(" FOR UPDATE" if lock else "")
    )
    row = conn.execute(query, (schedule_id,)).fetchone()
    return None if row is None else _row(row)


def page(conn: Conn, limit: int, after_id: int | None) -> list[ScheduleRow]:
    """Ordered by schedule_id, after the previous page's last id."""
    query = sql.SQL(
        "SELECT {} FROM scan_schedule WHERE %s::bigint IS NULL OR schedule_id > %s"
        " ORDER BY schedule_id LIMIT %s"
    ).format(_COLS)
    rows = conn.execute(query, (after_id, after_id, limit)).fetchall()
    return [_row(r) for r in rows]


def update(
    conn: Conn, schedule_id: int, changes: Mapping[str, object]
) -> ScheduleRow | None:
    """Sets the given columns; None if the schedule does not exist. A column
    outside the fixed map, or no change at all, is a programming error."""
    if not changes or not _UPDATABLE.issuperset(changes):
        raise ValueError("unsupported schedule change")
    columns = sorted(changes)
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns
    )
    query = sql.SQL(
        "UPDATE scan_schedule SET {} WHERE schedule_id = %s RETURNING {}"
    ).format(assignments, _COLS)
    params = [_value(c, changes[c]) for c in columns]
    row = conn.execute(query, (*params, schedule_id)).fetchone()
    return None if row is None else _row(row)


def delete(conn: Conn, schedule_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM scan_schedule WHERE schedule_id = %s", (schedule_id,)
    )
    return cur.rowcount == 1


def due(conn: Conn, now: datetime, limit: int = 100) -> list[ScheduleRow]:
    """Enabled schedules whose next_run_at is not after now, oldest due first,
    each locked; rows another session holds are skipped (#128 (e))."""
    query = sql.SQL(
        "SELECT {} FROM scan_schedule WHERE enabled AND next_run_at <= %s"
        " ORDER BY next_run_at, schedule_id LIMIT %s FOR UPDATE SKIP LOCKED"
    ).format(_COLS)
    rows = conn.execute(query, (now, limit)).fetchall()
    return [_row(r) for r in rows]


def previous_unfinished(conn: Conn, schedule_id: int) -> bool:
    """The schedule's latest scan has finished_at NULL (TS §4.4 L557). scan has
    no index on schedule_id; the table is small (one row per scan)."""
    row = conn.execute(
        "SELECT finished_at IS NULL FROM scan WHERE schedule_id = %s"
        " ORDER BY created_at DESC, scan_id DESC LIMIT 1",
        (schedule_id,),
    ).fetchone()
    return bool(row is not None and row[0])


def policy_state(
    conn: Conn, policy_id: int, *, lock: bool = False
) -> tuple[str, bool] | None:
    """(policy_status, deleted) of the policy, or None if it does not exist.
    lock=True reads the row FOR SHARE (TASK-197 r1): a policy delete's UPDATE
    policy then waits for this transaction, and its "disable the schedules"
    UPDATE sees a schedule this transaction wrote (TS §4.3 L550); a delete
    that committed first is seen as deleted."""
    query = (
        "SELECT policy_status::text, deleted_at IS NOT NULL FROM policy"
        " WHERE policy_id = %s FOR SHARE"
        if lock
        else "SELECT policy_status::text, deleted_at IS NOT NULL FROM policy"
        " WHERE policy_id = %s"
    )
    row = conn.execute(query, (policy_id,)).fetchone()
    return None if row is None else (str(row[0]), bool(row[1]))


def try_share_policy(conn: Conn, policy_id: int) -> bool:
    """The policy row FOR SHARE SKIP LOCKED: False when another session holds
    it (an import, status change or delete is running). The scheduler tick
    holds its schedule row and must not wait for the policy, since a policy
    delete holds the policy and then updates that schedule row."""
    row = conn.execute(
        "SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE SKIP LOCKED",
        (policy_id,),
    ).fetchone()
    return row is not None


def mark_run(
    conn: Conn, schedule_id: int, *, ran_at: datetime | None, next_run_at: datetime
) -> None:
    """Moves next_run_at on; last_run_at changes only when a scan was queued
    (ran_at given), so a skipped or missed run keeps the previous one."""
    conn.execute(
        "UPDATE scan_schedule SET"
        " last_run_at = COALESCE(CAST(%s AS timestamptz), last_run_at),"
        " next_run_at = %s WHERE schedule_id = %s",
        (ran_at, next_run_at, schedule_id),
    )
