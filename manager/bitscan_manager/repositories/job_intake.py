"""Result intake SQL: the unit lock, the job read, the unit's result plugins,
the one-statement result insert and the job's progress (TS §4.4 L568–L570,
L578, §4.5 L587, §5.2 L892–L913; #124 (c), #127 (f); plan TASK-199 §3).
Parameterised statements only.

Each function runs in the caller's transaction and never commits. First
result wins (TS §4.4 L578): the root job (COALESCE(retry_of, job_id)) is
locked FOR UPDATE before the posted job, the same order as the sweep, so two
posts to an original and its retry serialise and the second sees the first's
rows. bitscan_app INSERTs scan_result rows and never updates or deletes them;
on scan_job it updates only state, started_at, deadline_at and finished_at.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

from bitscan_manager.services.jobs.intake_plan import ResultRow

type Conn = psycopg.Connection[Any]

_JOB: Final = sql.SQL(
    "SELECT job_id, kind, agent_id, scan_id, retry_of, state::text, created_at,"
    " dispatched_at, started_at, payload, eval_spec FROM scan_job"
    " WHERE job_id = %s FOR UPDATE"
)

# One INSERT per batch; job_created_at is the job's created_at, which the
# TS §5.2 trigger checks. result is a generated column and is never written.
_INSERT: Final = sql.SQL(
    "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
    " eval_detail, exit_code, stdout, stderr, timed_out, truncated,"
    " plugin_name_snap, execute_snap, operator_snap, expected_snap, started_at,"
    " finished_at, received_at)"
    " SELECT %(job)s, %(created)s, t.plugin_uuid, t.eval_code, t.eval_detail,"
    " t.exit_code, t.stdout, t.stderr, t.timed_out, t.truncated, t.name,"
    " t.execute, CAST(t.operator AS plugin_operator), t.expected, t.started_at,"
    " t.finished_at, %(received)s FROM unnest(CAST(%(uuids)s AS uuid[]),"
    " CAST(%(codes)s AS smallint[]), CAST(%(details)s AS text[]),"
    " CAST(%(exits)s AS integer[]), CAST(%(stdouts)s AS text[]),"
    " CAST(%(stderrs)s AS text[]), CAST(%(timeouts)s AS boolean[]),"
    " CAST(%(truncs)s AS boolean[]), CAST(%(names)s AS text[]),"
    " CAST(%(executes)s AS text[]), CAST(%(operators)s AS text[]),"
    " CAST(%(expecteds)s AS text[]), CAST(%(starts)s AS timestamptz[]),"
    " CAST(%(ends)s AS timestamptz[])) AS t(plugin_uuid, eval_code, eval_detail,"
    " exit_code, stdout, stderr, timed_out, truncated, name, execute, operator,"
    " expected, started_at, finished_at)"
)
_INTAKE_STATES: Final = frozenset({"running", "completed", "partial"})
# Ended originals that take results; only these can have a retry (sibling()).
_MAY_HAVE_RETRY: Final = frozenset({"failed", "partial", "completed"})


@dataclass(frozen=True)
class IntakeJob:
    job_id: UUID
    kind: str
    agent_id: UUID
    scan_id: UUID | None
    retry_of: UUID | None
    state: str
    created_at: datetime
    dispatched_at: datetime | None
    started_at: datetime | None
    payload: dict[str, Any]
    eval_spec: Any  # parsed by the service with parse_eval_spec (fails closed)


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def lock_unit(conn: Conn, job_id: UUID) -> IntakeJob | None:
    """Locks the root job, then the posted job (when it is a retry), and
    returns the posted job; None if it is unknown. retry_of never changes
    (no grant), so the unlocked root read is stable."""
    row = conn.execute(
        "SELECT COALESCE(retry_of, job_id) FROM scan_job WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    root = UUID(str(row[0]))
    if root != job_id:
        conn.execute("SELECT 1 FROM scan_job WHERE job_id = %s FOR UPDATE", (root,))
    r = conn.execute(_JOB, (job_id,)).fetchone()
    if r is None:
        return None
    return IntakeJob(
        job_id=UUID(str(r[0])),
        kind=str(r[1]),
        agent_id=UUID(str(r[2])),
        scan_id=_opt_uuid(r[3]),
        retry_of=_opt_uuid(r[4]),
        state=str(r[5]),
        created_at=r[6],
        dispatched_at=r[7],
        started_at=r[8],
        payload=dict(r[9]),
        eval_spec=r[10],
    )


def sibling(conn: Conn, job: IntakeJob) -> tuple[UUID, datetime] | None:
    """The other job of the unit with its created_at: a retry's original, or
    an original's retry. An original gets its retry when it ends failed or
    partial at its deadline, and late results can then move it to partial or
    completed (TS §4.4 L577, L582), so scan_job is searched by retry_of for
    every original that has ended in an accepting state: failed, partial or
    completed (a full read: no index, #127 (f)). A dispatched or running
    original cannot have a retry yet."""
    if job.retry_of is not None:
        row = conn.execute(
            "SELECT job_id, created_at FROM scan_job WHERE job_id = %s",
            (job.retry_of,),
        ).fetchone()
    elif job.state in _MAY_HAVE_RETRY:
        row = conn.execute(
            "SELECT job_id, created_at FROM scan_job WHERE retry_of = %s",
            (job.job_id,),
        ).fetchone()
    else:
        return None
    return None if row is None else (UUID(str(row[0])), row[1])


def result_uuids(conn: Conn, jobs: Sequence[tuple[UUID, datetime]]) -> set[UUID]:
    """Plugins with a result in any of the (job_id, job_created_at) jobs; the
    partition key is given, so partitions are pruned."""
    if not jobs:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT r.plugin_uuid FROM unnest(CAST(%s AS uuid[]),"
        " CAST(%s AS timestamptz[])) AS u(job_id, created_at) JOIN scan_result r"
        " ON r.job_id = u.job_id AND r.job_created_at = u.created_at",
        ([j for j, _ in jobs], [c for _, c in jobs]),
    ).fetchall()
    return {UUID(str(r[0])) for r in rows}


def insert_results(
    conn: Conn, job: IntakeJob, rows: Sequence[ResultRow], received_at: datetime
) -> int:
    """Every row of the batch in one INSERT; returns the row count."""
    if not rows:
        return 0
    params = {
        "job": job.job_id,
        "created": job.created_at,
        "received": received_at,
        "uuids": [r.plugin_uuid for r in rows],
        "codes": [r.eval_code for r in rows],
        "details": [r.eval_detail for r in rows],
        "exits": [r.exit_code for r in rows],
        "stdouts": [r.stdout for r in rows],
        "stderrs": [r.stderr for r in rows],
        "timeouts": [r.timed_out for r in rows],
        "truncs": [r.truncated for r in rows],
        "names": [r.plugin_name_snap for r in rows],
        "executes": [r.execute_snap for r in rows],
        "operators": [r.operator_snap for r in rows],
        "expecteds": [r.expected_snap for r in rows],
        "starts": [r.started_at for r in rows],
        "ends": [r.finished_at for r in rows],
    }
    return conn.execute(_INSERT, params).rowcount


def start(
    conn: Conn, job_id: UUID, started_at: datetime, deadline_at: datetime
) -> bool:
    """dispatched → running with started_at and deadline_at, written only
    while started_at is NULL, so a second start notice changes nothing
    (TS §4.4 L575, §3.3 L222). True when this call started the job."""
    cur = conn.execute(
        "UPDATE scan_job SET state = 'running', started_at = %s, deadline_at = %s"
        " WHERE job_id = %s AND state = 'dispatched' AND started_at IS NULL",
        (started_at, deadline_at, job_id),
    )
    return cur.rowcount == 1


def set_state(
    conn: Conn, job_id: UUID, state: str, finished_at: datetime | None
) -> bool:
    """The state after an accepted batch (running, completed or partial) with
    its finished_at (#127 (c)). A final state is never left."""
    if state not in _INTAKE_STATES:
        raise ValueError("unsupported intake state")
    cur = conn.execute(
        "UPDATE scan_job SET state = CAST(%s AS scan_state), finished_at = %s"
        " WHERE job_id = %s"
        " AND state IN ('dispatched', 'running', 'failed', 'partial')",
        (state, finished_at, job_id),
    )
    return cur.rowcount == 1
