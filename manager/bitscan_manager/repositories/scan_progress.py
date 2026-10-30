"""Scan progress SQL: unit facts, refresh candidates, the scan's state and a
scan's open jobs cancelled (TS §4.4 L573, L579–L581; #127 (d)–(f); plan
TASK-202 §3). Parameterised statements only.

Each function runs in the caller's transaction and never commits. bitscan_app
may UPDATE only scan.state and scan.finished_at, and only the progress columns
of scan_job. scan_job has no index on scan_id or retry_of (TS §5.2 is the
schema), so unit_facts reads scan_job once per call (#127 (f)); the sweep calls
it once per run with every candidate.

The facts type is the pure derivation's (services.jobs.scan_state.Unit, plain
values only), so the repository and derive() share one shape.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

from bitscan_manager.services.jobs.scan_state import Unit

type Conn = psycopg.Connection[Any]

REFRESH_WINDOW: Final = timedelta(days=8)  # 7-day late window + 24 h pickup
_SCAN_STATES: Final = frozenset(
    {"queued", "running", "completed", "partial", "failed", "cancelled"}
)

# jobs: the scans' compliance jobs, each with its unit's root (#127 (d)).
# got: the distinct plugins with a result in each unit (joined on
# job_created_at, so scan_result partitions are pruned). missing: units whose
# original payload lists a plugin with no result in the unit.
_FACTS: Final = sql.SQL(
    "WITH jobs AS MATERIALIZED (SELECT job_id, scan_id, retry_of, state, created_at,"
    " payload, COALESCE(retry_of, job_id) AS root FROM scan_job"
    " WHERE kind = 'compliance' AND scan_id = ANY(%s)),"
    " got AS (SELECT DISTINCT j.root, r.plugin_uuid FROM jobs j JOIN scan_result r"
    " ON r.job_id = j.job_id AND r.job_created_at = j.created_at),"
    " planned AS (SELECT j.job_id AS root, CAST(p.item ->> 'plugin_uuid' AS uuid)"
    " AS plugin_uuid FROM jobs j CROSS JOIN LATERAL"
    " jsonb_array_elements(j.payload -> 'plugins') AS p(item)"
    " WHERE j.retry_of IS NULL),"
    " missing AS (SELECT DISTINCT pl.root FROM planned pl LEFT JOIN got g"
    " ON g.root = pl.root AND g.plugin_uuid = pl.plugin_uuid"
    " WHERE g.plugin_uuid IS NULL),"
    " hit AS (SELECT DISTINCT root FROM got)"
    " SELECT j.scan_id, j.root,"
    " bool_or(j.state IN ('queued', 'dispatched', 'running')),"
    " m.root IS NULL, h.root IS NOT NULL, bool_or(j.state = 'cancelled'),"
    " bool_and(j.state = 'queued')"
    " FROM jobs j LEFT JOIN missing m ON m.root = j.root"
    " LEFT JOIN hit h ON h.root = j.root"
    " GROUP BY j.scan_id, j.root, m.root, h.root ORDER BY j.scan_id, j.root"
)


def refresh_candidates(
    conn: Conn, now: datetime, window: timedelta = REFRESH_WINDOW
) -> list[UUID]:
    """Scans whose state may still change (#127 (f)): every unfinished scan,
    and every scan not completed that was created within the window (late
    results can still move it)."""
    rows = conn.execute(
        "SELECT scan_id FROM scan WHERE finished_at IS NULL"
        " OR (state <> 'completed' AND created_at > %s) ORDER BY scan_id",
        (now - window,),
    ).fetchall()
    return [UUID(str(r[0])) for r in rows]


def unit_facts(conn: Conn, scan_ids: Sequence[UUID]) -> dict[UUID, list[Unit]]:
    """The units of each scan in one statement, keyed by scan_id. A scan with
    no compliance job is absent (it cannot exist, #3)."""
    if not scan_ids:
        return {}
    facts: dict[UUID, list[Unit]] = {}
    for r in conn.execute(_FACTS, (list(scan_ids),)).fetchall():
        unit = Unit(
            open=bool(r[2]),
            complete=bool(r[3]),
            has_results=bool(r[4]),
            any_cancelled=bool(r[5]),
            all_queued=bool(r[6]),
        )
        facts.setdefault(UUID(str(r[0])), []).append(unit)
    return facts


def scan_row(
    conn: Conn, scan_id: UUID, *, lock: bool = False
) -> tuple[str, datetime | None] | None:
    """(state, finished_at) of the scan, or None if it does not exist."""
    query = (
        "SELECT state::text, finished_at FROM scan WHERE scan_id = %s FOR UPDATE"
        if lock
        else "SELECT state::text, finished_at FROM scan WHERE scan_id = %s"
    )
    row = conn.execute(query, (scan_id,)).fetchone()
    return None if row is None else (str(row[0]), row[1])


def set_scan_state(
    conn: Conn, scan_id: UUID, state: str, finished_at: datetime | None
) -> bool:
    """Writes the derived state; finished_at is set the first time it is given
    and then kept, never moved or cleared (#127 (e)). True only when the row
    changed, so an unchanged scan is not written."""
    if state not in _SCAN_STATES:
        raise ValueError("not a scan state")
    cur = conn.execute(
        "UPDATE scan SET state = CAST(%(state)s AS scan_state),"
        " finished_at = COALESCE(finished_at, CAST(%(fin)s AS timestamptz))"
        " WHERE scan_id = %(id)s AND (state <> CAST(%(state)s AS scan_state)"
        " OR (finished_at IS NULL AND CAST(%(fin)s AS timestamptz) IS NOT NULL))",
        {"state": state, "fin": finished_at, "id": scan_id},
    )
    return cur.rowcount == 1


def cancel_open_jobs(conn: Conn, scan_id: UUID, now: datetime) -> list[UUID]:
    """The scan's queued, dispatched and running jobs (originals and retries)
    → cancelled (TS §4.4 L581). One UPDATE; it locks only open jobs, and a
    unit has at most one (a retry exists only once its original has ended),
    so it cannot deadlock with intake's root-then-job order."""
    rows = conn.execute(
        "UPDATE scan_job SET state = 'cancelled', finished_at = %s"
        " WHERE scan_id = %s AND kind = 'compliance'"
        " AND state IN ('queued', 'dispatched', 'running') RETURNING job_id",
        (now, scan_id),
    ).fetchall()
    return sorted(UUID(str(r[0])) for r in rows)
