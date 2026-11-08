"""Retention SQL (TS §5.3 L1049, L1051; §5.2 L1002–L1006; #150 (a)–(c), (e)–(g),
(j), (k); plan TASK-242 §3). Parameterised statements only.

Run as bitscan_retention, which may read every table and delete only from the
retention tables; bitscan_app is refused every delete here by the grants. Each
function runs in the caller's transaction and never commits; each delete
removes at most one chunk and returns its row count. No DDL: partitions are
dropped by `db maintain`.

bitscan_retention has no UPDATE privilege, so it cannot take row locks
(SELECT ... FOR UPDATE needs UPDATE); a scan under re-evaluation is skipped
through the M8 advisory lock instead (decisions 2026-11-08).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Literal
from uuid import UUID

import psycopg
from psycopg import sql

type Conn = psycopg.Connection[Any]

# The step tables whose newest row date is probed for a wrong clock (#150 (j)).
ProbeTable = Literal[
    "scan", "scan_job", "inventory_snapshot", "enrollment_request", "user_token"
]


_NO_FILTER: Final = sql.SQL("")


def _newest(
    table: str, column: str, where: sql.Composable = _NO_FILTER
) -> sql.Composed:
    return sql.SQL("SELECT max({}) FROM {}{}").format(
        sql.Identifier(column), sql.Identifier(table), where
    )


# Fixed mapping: only these statements can run. Every column is written by the
# manager. user_token is probed on created_at, not expires_at, which is ahead
# for every live token (decisions 2026-11-08).
_NEWEST: Final[Mapping[str, sql.Composed]] = MappingProxyType(
    {
        "scan": _newest("scan", "created_at"),
        "scan_job": _newest(
            "scan_job", "finished_at", sql.SQL(" WHERE kind = 'inventory'")
        ),
        "inventory_snapshot": _newest("inventory_snapshot", "collected_at"),
        "enrollment_request": _newest("enrollment_request", "decided_at"),
        "user_token": _newest("user_token", "created_at"),
    }
)


def _limit(n: int) -> int:
    if n < 1:
        raise ValueError("chunk size must be at least 1")
    return n


def _cutoff(cutoff: datetime) -> datetime:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    return cutoff


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("expected a timestamp")
    return value


def db_now(conn: Conn) -> datetime:
    """The database's clock, compared with the manager's before any delete."""
    row = conn.execute("SELECT now()").fetchone()
    moment = None if row is None else _timestamp(row[0])
    if moment is None:
        raise RuntimeError("the database returned no time")
    return moment


def newest(conn: Conn, table: ProbeTable) -> datetime | None:
    """The newest row date of a step's table; None when it holds no dated row."""
    statement = _NEWEST.get(table)
    if statement is None:
        raise ValueError("unknown retention table")
    row = conn.execute(statement).fetchone()
    return None if row is None else _timestamp(row[0])


def scan_chunk(conn: Conn, cutoff: datetime, n: int) -> list[UUID]:
    """Up to n scans created before cutoff, oldest first; no row lock."""
    rows = conn.execute(
        "SELECT scan_id FROM scan WHERE created_at < %s"
        " ORDER BY created_at, scan_id LIMIT %s",
        (_cutoff(cutoff), _limit(n)),
    ).fetchall()
    return [UUID(str(r[0])) for r in rows]


def try_reeval_lock(conn: Conn, scan_id: UUID) -> bool:
    """Try M8's per-scan re-evaluation lock (the same key as
    repositories.reeval.lock_scan, #150 (k)); False when a re-evaluation holds
    it. Held until the caller's transaction ends."""
    if conn.autocommit:  # the lock would end with this statement
        raise RuntimeError("try_reeval_lock needs a transaction, not autocommit")
    row = conn.execute(
        "SELECT pg_try_advisory_xact_lock(hashtext('scan_reeval'),"
        " hashtext(CAST(CAST(%s AS uuid) AS text)))",
        (scan_id,),
    ).fetchone()
    return row is not None and row[0] is True


def delete_scans(conn: Conn, ids: Sequence[UUID]) -> int:
    """Delete whole scans in one statement: the cascades remove their jobs
    (originals and retries), results in every partition and re-evaluation rows
    together (TS §5.3 L1049). Returns the number of scans deleted."""
    if not ids:
        return 0
    return conn.execute(
        "DELETE FROM scan WHERE scan_id = ANY(CAST(%s AS uuid[]))", (list(ids),)
    ).rowcount


def delete_inventory_jobs(conn: Conn, cutoff: datetime, n: int) -> int:
    """Up to n inventory jobs finished before cutoff (#150 (e))."""
    return conn.execute(
        "DELETE FROM scan_job WHERE job_id IN (SELECT job_id FROM scan_job"
        " WHERE kind = 'inventory' AND finished_at < %s LIMIT %s)",
        (_cutoff(cutoff), _limit(n)),
    ).rowcount


def delete_snapshots(conn: Conn, cutoff: datetime, n: int) -> int:
    """Up to n inventory snapshots collected before cutoff."""
    return conn.execute(
        "DELETE FROM inventory_snapshot WHERE snapshot_id IN (SELECT snapshot_id"
        " FROM inventory_snapshot WHERE collected_at < %s LIMIT %s)",
        (_cutoff(cutoff), _limit(n)),
    ).rowcount


def delete_requests(conn: Conn, cutoff: datetime, n: int) -> int:
    """Up to n decided enrolment requests decided before cutoff; pending
    requests are never deleted (#150 (c))."""
    return conn.execute(
        "DELETE FROM enrollment_request WHERE request_id IN (SELECT request_id"
        " FROM enrollment_request WHERE decision IS NOT NULL AND decided_at < %s"
        " LIMIT %s)",
        (_cutoff(cutoff), _limit(n)),
    ).rowcount


def delete_tokens(conn: Conn, cutoff: datetime, n: int) -> int:
    """Up to n user tokens whose expiry is before cutoff, revoked or not
    (#150 (b))."""
    return conn.execute(
        "DELETE FROM user_token WHERE token_id IN (SELECT token_id FROM user_token"
        " WHERE expires_at < %s LIMIT %s)",
        (_cutoff(cutoff), _limit(n)),
    ).rowcount


def delete_packages(conn: Conn, n: int) -> int:
    """Up to n package rows no agent_package row references (#150 (f); the
    NOT EXISTS uses ix_agent_package_pkg)."""
    return conn.execute(
        "DELETE FROM package WHERE package_id IN (SELECT p.package_id FROM package p"
        " WHERE NOT EXISTS (SELECT 1 FROM agent_package ap"
        " WHERE ap.package_id = p.package_id) LIMIT %s)",
        (_limit(n),),
    ).rowcount
