"""Scan read SQL for the scan list, the scan detail and a host's scan history
(TS §6.2 L1113, L1120, L1122, §6.3 L1136; REQ-264 to REQ-266, REQ-272; open
questions #89, #145; plan work/plans/TASK-232.md). SELECT only,
parameterised statements only.

Lists are newest first (`created_at` then `scan_id`, both descending) and
keyset-paged; the cursor holds the anchor's `scan_id` only, and its
`created_at` is read here (#89, #145 (d)); a deleted anchor is AnchorGone.
"Scans of a host" is the stored resolved target holding the agent, a JSONB
containment test with a parameter (#145 (a), (c)); `scan_job` has no index
on `agent_id` or `scan_id` and none may be added. The resolved list itself
never leaves the database: items carry its length and the detail the target
without it.

Each function runs in the caller's transaction and never commits.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

from bitscan_manager.repositories.packages import AnchorGone

__all__ = ["AnchorGone", "JobRow", "ScanDetailRow", "ScanRow"]

type Conn = psycopg.Connection[Any]

_SCAN_COLS: Final = sql.SQL(
    "s.scan_id, s.policy_id, p.policy_name, s.policy_version, s.trigger,"
    " s.schedule_id, s.requested_by, s.state::text,"
    " CASE WHEN s.target ? 'agents' THEN 'agents' WHEN s.target ? 'tags'"
    " THEN 'tags' WHEN s.target ? 'all' THEN 'all' END,"
    " COALESCE(jsonb_array_length(s.target -> 'resolved_agents'), 0),"
    " s.created_at, s.finished_at"
)

_PAGE: Final = sql.SQL(
    "SELECT {} FROM scan s JOIN policy p ON p.policy_id = s.policy_id"
    " WHERE (%(policy_id)s::bigint IS NULL OR s.policy_id = %(policy_id)s::bigint)"
    " AND (%(agent)s::text IS NULL"
    " OR s.target -> 'resolved_agents' @> jsonb_build_array(%(agent)s::text))"
    " AND (%(state)s::text IS NULL OR s.state::text = %(state)s::text)"
    " AND (%(lower)s::timestamptz IS NULL OR s.created_at >= %(lower)s::timestamptz)"
    " AND (%(upper)s::timestamptz IS NULL OR s.created_at < %(upper)s::timestamptz)"
    " AND (%(anchor_at)s::timestamptz IS NULL OR (s.created_at, s.scan_id)"
    " < (%(anchor_at)s::timestamptz, %(anchor_id)s::uuid))"
    " ORDER BY s.created_at DESC, s.scan_id DESC LIMIT %(limit)s"
).format(_SCAN_COLS)

_ONE: Final = sql.SQL(
    "SELECT {}, s.target - 'resolved_agents' FROM scan s"
    " JOIN policy p ON p.policy_id = s.policy_id WHERE s.scan_id = %(scan_id)s"
).format(_SCAN_COLS)

# The original before its retry (TS §4.4 L577), hosts by hostname.
_JOBS: Final = (
    "SELECT j.job_id, j.agent_id, a.hostname, j.state::text, j.retry_of,"
    " j.dispatched_at, j.started_at, j.finished_at FROM scan_job j"
    " JOIN agent a ON a.agent_id = j.agent_id"
    " WHERE j.scan_id = %(scan_id)s AND j.kind = 'compliance'"
    " ORDER BY a.hostname, j.agent_id, j.retry_of IS NOT NULL, j.created_at, j.job_id"
)


@dataclass(frozen=True, slots=True)
class ScanRow:
    """One scan as the #145 (a) item; `state` is `scan.state` as stored."""

    scan_id: UUID
    policy_id: int
    policy_name: str
    policy_version: int
    trigger: str
    schedule_id: int | None
    requested_by: int | None
    state: str
    target_kind: str  # agents, tags or all
    resolved_count: int
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScanDetailRow:
    scan: ScanRow
    target: dict[str, Any]  # the stored target without resolved_agents


@dataclass(frozen=True, slots=True)
class JobRow:
    """One compliance job of the scan, with its host's current hostname."""

    job_id: UUID
    agent_id: UUID
    hostname: str
    state: str
    retry_of: UUID | None
    dispatched_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


def _opt_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _scan(r: Any) -> ScanRow:
    if r[8] is None:
        raise ValueError("scan target has no known kind")
    return ScanRow(
        scan_id=UUID(str(r[0])),
        policy_id=int(r[1]),
        policy_name=str(r[2]),
        policy_version=int(r[3]),
        trigger=str(r[4]),
        schedule_id=_opt_int(r[5]),
        requested_by=_opt_int(r[6]),
        state=str(r[7]),
        target_kind=str(r[8]),
        resolved_count=int(r[9]),
        created_at=r[10],
        finished_at=r[11],
    )


def _utc(value: datetime | None) -> datetime | None:
    """Bound in UTC: PostgreSQL refuses offsets past ±15:59 that Python
    accepts. A moment outside Python's UTC range clamps to its end, which
    gives the same rows (builder checklist 1)."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a time filter must carry an offset")
    try:
        return value.astimezone(UTC)
    except OverflowError:
        edge = datetime.min if value.year == datetime.min.year else datetime.max
        return edge.replace(tzinfo=UTC)


def _anchor(conn: Conn, after: UUID | None) -> datetime | None:
    if after is None:
        return None
    found = conn.execute(
        "SELECT created_at FROM scan WHERE scan_id = %(scan_id)s", {"scan_id": after}
    ).fetchone()
    if found is None:
        raise AnchorGone
    created_at: datetime = found[0]
    return created_at


def scan_page(
    conn: Conn,
    *,
    policy_id: int | None,
    agent_id: UUID | None,
    state: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
    limit: int,
    after: UUID | None,
) -> list[ScanRow]:
    """At most `limit` scans after the anchor scan `after`, filters combined
    with AND: `created_after` inclusive, `created_before` exclusive."""
    params = {
        "policy_id": policy_id,
        "agent": None if agent_id is None else str(agent_id),
        "state": state,
        "lower": _utc(created_after),
        "upper": _utc(created_before),
        "anchor_at": _anchor(conn, after),
        "anchor_id": after,
        "limit": limit,
    }
    return [_scan(r) for r in conn.execute(_PAGE, params).fetchall()]


def agent_scan_page(
    conn: Conn, agent_id: UUID, *, limit: int, after: UUID | None
) -> list[ScanRow]:
    """The scans whose resolved target holds the agent, as scan_page."""
    return scan_page(
        conn,
        policy_id=None,
        agent_id=agent_id,
        state=None,
        created_after=None,
        created_before=None,
        limit=limit,
        after=after,
    )


def agent_exists(conn: Conn, agent_id: UUID) -> bool:
    found = conn.execute(
        "SELECT 1 FROM agent WHERE agent_id = %(agent_id)s", {"agent_id": agent_id}
    ).fetchone()
    return found is not None


def scan_detail(conn: Conn, scan_id: UUID) -> ScanDetailRow | None:
    """The scan with its policy name and requested target, or None."""
    r = conn.execute(_ONE, {"scan_id": scan_id}).fetchone()
    if r is None:
        return None
    return ScanDetailRow(scan=_scan(r), target=dict(r[12]))


def scan_jobs(conn: Conn, scan_id: UUID) -> list[JobRow]:
    """The scan's compliance jobs by hostname, agent_id, original first."""
    rows = conn.execute(_JOBS, {"scan_id": scan_id}).fetchall()
    return [
        JobRow(
            job_id=UUID(str(r[0])),
            agent_id=UUID(str(r[1])),
            hostname=str(r[2]),
            state=str(r[3]),
            retry_of=_opt_uuid(r[4]),
            dispatched_at=r[5],
            started_at=r[6],
            finished_at=r[7],
        )
        for r in rows
    ]
