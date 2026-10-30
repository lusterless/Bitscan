"""Compliance sweep SQL: deadline and never-started candidates, the unit lock,
the job's end and its single retry (TS §4.4 L575, L577, §3.3 L218; #126,
#127 (b); plan TASK-202 §3). Parameterised statements only.

Each function runs in the caller's transaction and never commits. Lock order
is the intake's (#124 (c)): the root job (COALESCE(retry_of, job_id)), then
the job, both SKIP LOCKED so a sweep never waits for a result post; a skipped
job is handled by the next sweep. bitscan_app may UPDATE only the progress
columns of scan_job: a retry is a new row, the original's payload, eval_spec,
agent_id, scan_id and retry_of are never written.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

type Conn = psycopg.Connection[Any]

_ENDINGS: Final = frozenset({"completed", "partial", "failed"})

# The job with its scan's policy and its agent; FOR UPDATE OF j locks only the
# job row, never the policy or the agent.
_JOB: Final = sql.SQL(
    "SELECT j.job_id, COALESCE(j.retry_of, j.job_id), j.retry_of, j.scan_id,"
    " j.agent_id, j.state::text, j.payload, j.eval_spec, j.created_at,"
    " j.dispatched_at, j.started_at, j.deadline_at, p.deleted_at IS NOT NULL,"
    " a.status = 'decommissioned' FROM scan_job j"
    " JOIN scan s ON s.scan_id = j.scan_id JOIN policy p ON p.policy_id = s.policy_id"
    " JOIN agent a ON a.agent_id = j.agent_id"
    " WHERE j.job_id = %s AND j.kind = 'compliance' FOR UPDATE OF j SKIP LOCKED"
)


@dataclass(frozen=True)
class SweepJob:
    job_id: UUID
    root_id: UUID  # COALESCE(retry_of, job_id)
    retry_of: UUID | None
    scan_id: UUID
    agent_id: UUID
    state: str
    payload: dict[str, Any]
    eval_spec: Any
    created_at: datetime
    dispatched_at: datetime | None
    started_at: datetime | None
    deadline_at: datetime | None
    policy_deleted: bool
    agent_decommissioned: bool


def _ids(rows: list[Any]) -> list[UUID]:
    return [UUID(str(r[0])) for r in rows]


def past_deadline(conn: Conn, now: datetime, limit: int = 1000) -> list[UUID]:
    """Compliance jobs dispatched or running whose deadline is strictly past
    (#127 (b)); no lock, the caller locks each with lock_for_sweep."""
    rows = conn.execute(
        "SELECT job_id FROM scan_job WHERE kind = 'compliance'"
        " AND state IN ('dispatched', 'running') AND deadline_at < %s"
        " ORDER BY deadline_at, job_id LIMIT %s",
        (now, limit),
    ).fetchall()
    return _ids(rows)


def never_started(
    conn: Conn, now: datetime, after: timedelta, limit: int = 1000
) -> list[UUID]:
    """Compliance jobs dispatched strictly more than `after` ago that never
    started (TS §4.4 L575: 24 h); no lock."""
    rows = conn.execute(
        "SELECT job_id FROM scan_job WHERE kind = 'compliance'"
        " AND state = 'dispatched' AND started_at IS NULL AND dispatched_at < %s"
        " ORDER BY dispatched_at, job_id LIMIT %s",
        (now - after, limit),
    ).fetchall()
    return _ids(rows)


def lock_for_sweep(conn: Conn, job_id: UUID) -> SweepJob | None:
    """Locks the root job, then the job, skipping either if another session
    holds it. None when the job is unknown, not a compliance job, or held.
    retry_of never changes (no grant), so the unlocked root read is stable."""
    row = conn.execute(
        "SELECT COALESCE(retry_of, job_id) FROM scan_job WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    root = UUID(str(row[0]))
    if root != job_id:
        held = conn.execute(
            "SELECT 1 FROM scan_job WHERE job_id = %s FOR UPDATE SKIP LOCKED", (root,)
        ).fetchone()
        if held is None:
            return None
    r = conn.execute(_JOB, (job_id,)).fetchone()
    if r is None:
        return None
    return SweepJob(
        job_id=UUID(str(r[0])),
        root_id=UUID(str(r[1])),
        retry_of=None if r[2] is None else UUID(str(r[2])),
        scan_id=UUID(str(r[3])),
        agent_id=UUID(str(r[4])),
        state=str(r[5]),
        payload=dict(r[6]),
        eval_spec=r[7],
        created_at=r[8],
        dispatched_at=r[9],
        started_at=r[10],
        deadline_at=r[11],
        policy_deleted=bool(r[12]),
        agent_decommissioned=bool(r[13]),
    )


def unit_result_uuids(conn: Conn, job: SweepJob) -> set[UUID]:
    """Plugins with a result in the job or its sibling (#127 (a)). A sweep
    candidate is dispatched or running, and an original gets its retry only
    when it leaves those states, so the only sibling is a retry's original
    (TASK-195's rule; both rows are read by primary key)."""
    ids = [job.job_id] if job.retry_of is None else [job.job_id, job.retry_of]
    rows = conn.execute(
        "SELECT DISTINCT r.plugin_uuid FROM scan_job j JOIN scan_result r"
        " ON r.job_id = j.job_id AND r.job_created_at = j.created_at"
        " WHERE j.job_id = ANY(%s)",
        (ids,),
    ).fetchall()
    return set(_ids(rows))


def end_job(conn: Conn, job_id: UUID, state: str, now: datetime) -> bool:
    """dispatched or running → completed, partial or failed. True only for the
    call that ended it, so two sweeps make one retry (#126 (c))."""
    if state not in _ENDINGS:
        raise ValueError("unsupported job ending")
    cur = conn.execute(
        "UPDATE scan_job SET state = CAST(%s AS scan_state), finished_at = %s"
        " WHERE job_id = %s AND kind = 'compliance'"
        " AND state IN ('dispatched', 'running')",
        (state, now, job_id),
    )
    return cur.rowcount == 1


def insert_retry(
    conn: Conn,
    *,
    original: SweepJob,
    job_id: UUID,
    payload: Mapping[str, Any],
    eval_spec: Mapping[str, Any],
    created_at: datetime,
    pickup_by: datetime,
) -> None:
    """The original's single retry: a new queued job of the same scan and
    agent with retry_of = the original (TS §4.4 L577). A retry is never
    retried, and the payload's job_id must be the row's."""
    if original.retry_of is not None:
        raise ValueError("a retry is never retried")
    if payload.get("job_id") != str(job_id):
        raise ValueError("retry payload job_id differs from the row")
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, retry_of, state,"
        " payload, eval_spec, created_at, pickup_by)"
        " VALUES (%s, 'compliance', %s, %s, %s, 'queued', %s, %s, %s, %s)",
        (
            job_id,
            original.scan_id,
            original.agent_id,
            original.job_id,
            Jsonb(dict(payload)),
            Jsonb(dict(eval_spec)),
            created_at,
            pickup_by,
        ),
    )
