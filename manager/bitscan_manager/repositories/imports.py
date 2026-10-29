"""bit_import and task SQL (SR §3.5; TS §4.1 L520, §4.2 L540, §5.2). Parameterised
statements only.

Each function runs in the caller's transaction and never commits. A bit_import
row is written in its own transaction, after the catalog transaction commits
or rolls back (SR §3.6), so the caller opens a separate one for insert_import.
bitscan_app may only INSERT and SELECT bit_import (TS §5.2 L1005): the log is
never updated or deleted. It has INSERT and UPDATE on task.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

type Conn = psycopg.Connection[Any]
Mode = Literal["auto", "manual", "rebuild"]
Outcome = Literal["success", "skipped", "rejected"]

_PAGE = sql.SQL(
    "SELECT import_id, file_name, file_sha256, policy_version, mode, outcome,"
    " plugins_added, plugins_updated, plugins_retired, errors, imported_by,"
    " imported_at FROM bit_import WHERE CAST(%s AS bigint) IS NULL"
    " OR import_id < %s ORDER BY import_id DESC LIMIT %s"
)
_TASK = sql.SQL(
    "SELECT task_id, kind, state, requested_by, result, started_at, finished_at"
    " FROM task WHERE task_id = %s"
)


@dataclass(frozen=True)
class ImportRecord:
    """One import outcome. file_name is the folder path relative to the server
    folder, or the upload's client name in the #99 (d) form; errors are the
    {line, element, code, message} findings, warnings included (#110), with no
    U+0000 or lone surrogate (jsonb refuses them). imported_by None = system."""

    file_name: str
    file_sha256: str
    mode: Mode
    outcome: Outcome
    policy_version: int | None = None
    plugins_added: int = 0
    plugins_updated: int = 0
    plugins_retired: int = 0
    errors: Sequence[Mapping[str, object]] = ()
    imported_by: int | None = None


@dataclass(frozen=True)
class ImportRow:
    import_id: int
    file_name: str
    file_sha256: str
    policy_version: int | None
    mode: str
    outcome: str
    plugins_added: int
    plugins_updated: int
    plugins_retired: int
    errors: list[dict[str, Any]]
    imported_by: int | None
    imported_at: datetime


@dataclass(frozen=True)
class TaskRow:
    task_id: UUID
    kind: str
    state: str
    requested_by: int | None
    result: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None


def insert_import(conn: Conn, record: ImportRecord, now: datetime) -> int:
    """The new import_id."""
    params = {f.name: getattr(record, f.name) for f in fields(record)}
    row = conn.execute(
        "INSERT INTO bit_import (file_name, file_sha256, policy_version, mode,"
        " outcome, plugins_added, plugins_updated, plugins_retired, errors,"
        " imported_by, imported_at) VALUES (%(file_name)s, %(file_sha256)s,"
        " %(policy_version)s, %(mode)s, %(outcome)s, %(plugins_added)s,"
        " %(plugins_updated)s, %(plugins_retired)s, %(errors)s, %(imported_by)s,"
        " %(now)s) RETURNING import_id",
        {**params, "errors": Jsonb([dict(e) for e in record.errors]), "now": now},
    ).fetchone()
    if row is None:
        raise LookupError("INSERT … RETURNING gave no row")
    return int(row[0])


def imports_newest_first(
    conn: Conn, limit: int, before_id: int | None
) -> list[ImportRow]:
    """GET /imports (#98 (h)): every column, newest first, keyset by
    import_id (rows with import_id < before_id). The caller asks for limit + 1
    to learn whether another page exists."""
    rows = conn.execute(_PAGE, (before_id, before_id, limit)).fetchall()
    return [ImportRow(*r) for r in rows]


def insert_task(conn: Conn, requested_by: int | None, now: datetime) -> UUID:
    """A rebuild task, running from now; requested_by None for the CLI (#107)."""
    row = conn.execute(
        "INSERT INTO task (kind, state, requested_by, started_at)"
        " VALUES ('rebuild', 'running', %s, %s) RETURNING task_id",
        (requested_by, now),
    ).fetchone()
    if row is None:
        raise LookupError("INSERT … RETURNING gave no row")
    return UUID(str(row[0]))


def finish_task(
    conn: Conn,
    task_id: UUID,
    state: Literal["succeeded", "failed"],
    result: Mapping[str, object],
    now: datetime,
) -> bool:
    """running → state with its result (#98 (g)); False when the task is not
    running (already finished, or marked failed at start-up)."""
    return (
        conn.execute(
            "UPDATE task SET state = %s, result = %s, finished_at = %s"
            " WHERE task_id = %s AND state = 'running'",
            (state, Jsonb(dict(result)), now, task_id),
        ).rowcount
        == 1
    )


def get_task(conn: Conn, task_id: UUID) -> TaskRow | None:
    row = conn.execute(_TASK, (task_id,)).fetchone()
    return None if row is None else TaskRow(*row)


def fail_running_tasks(
    conn: Conn, result: Mapping[str, object], now: datetime
) -> list[UUID]:
    """Start-up (TS §4.2 L540): every task still running becomes failed with
    result and finished_at; other rows are untouched. Returns their ids."""
    rows = conn.execute(
        "UPDATE task SET state = 'failed', result = %s, finished_at = %s"
        " WHERE state = 'running' RETURNING task_id",
        (Jsonb(dict(result)), now),
    ).fetchall()
    return sorted(UUID(str(r[0])) for r in rows)
