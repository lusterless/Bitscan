"""scan_job SQL for inventory jobs and the job pull (TS §5.2, §3.4, §4.4,
§6.1). Parameterised statements only.

Runs inside the caller's transaction; never commits. bitscan_app may INSERT
scan_job rows and UPDATE only state, dispatched_at, started_at, deadline_at and
finished_at; it can never DELETE a job or change its agent_id or payload.
Inventory jobs are built here, from the scheduler, and compliance jobs in
scan_queue and job_sweep: no caller supplies a payload, so no path can queue
a command (TS §3.3). eval_spec is never selected.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

PULL_LIMIT: Final = 10  # TS §6.1 L1064: up to 10 jobs per pull

# Agents that get an inventory job (TS §3.4 L230): not decommissioned or
# awaiting approval, with no inventory job queued, dispatched or running.
_QUEUE = sql.SQL(
    "WITH due AS MATERIALIZED (SELECT a.agent_id, gen_random_uuid() AS job_id"
    " FROM agent a"
    " WHERE a.status NOT IN ('decommissioned', 'awaiting_approval')"
    " AND (CAST(%(agent)s AS uuid) IS NULL OR a.agent_id = %(agent)s)"
    " AND NOT EXISTS (SELECT 1 FROM scan_job j WHERE j.agent_id = a.agent_id"
    " AND j.kind = 'inventory' AND j.state IN ('queued', 'dispatched', 'running')))"
    " INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
    " pickup_by) SELECT job_id, 'inventory', agent_id, 'queued',"
    " jsonb_build_object('job_id', job_id, 'agent_id', agent_id, 'kind',"
    " 'inventory', 'pickup_by', {pickup_text}), %(now)s, %(pickup_by)s FROM due"
    " RETURNING job_id"
).format(
    pickup_text=sql.SQL(
        """to_char(%(pickup_by)s AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')"""
    )
)


@dataclass(frozen=True)
class JobRow:
    job_id: UUID
    kind: str
    agent_id: UUID
    state: str
    created_at: datetime
    pickup_by: datetime
    dispatched_at: datetime | None
    finished_at: datetime | None


class JobRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def queue_inventory(
        self, now: datetime, pickup_by: datetime, agent_id: UUID | None = None
    ) -> list[UUID]:
        """One inventory job per eligible agent (or only agent_id), each with
        its TS §6.5 payload whose job_id is the row's id, in one statement.
        Runs are serialised by a transaction lock, so two at once (the timer
        and a first job, #36) still give one open job per agent."""
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtext('inventory_queue'))")
        params = {"now": now, "pickup_by": pickup_by, "agent": agent_id}
        rows = self._conn.execute(_QUEUE, params).fetchall()
        return [UUID(str(r[0])) for r in rows]

    def has_open_inventory(self, agent_id: UUID) -> bool:
        row = self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM scan_job WHERE agent_id = %s"
            " AND kind = 'inventory' AND state IN ('queued', 'dispatched', 'running'))",
            (agent_id,),
        ).fetchone()
        return bool(row is not None and row[0])

    def pull(self, agent_id: UUID, now: datetime) -> list[dict[str, Any]]:
        """Marks at most PULL_LIMIT of the agent's queued jobs, inventory and
        compliance together, whose pickup_by is still ahead dispatched and
        returns their payloads, oldest first (TS §6.1 L1064, REQ-213). Locked
        rows are skipped and the state re-checked, so two concurrent pulls
        never return one job. Only the stored payload is returned."""
        rows = self._conn.execute(
            "UPDATE scan_job j SET state = 'dispatched', dispatched_at = %(now)s"
            " FROM (SELECT job_id FROM scan_job WHERE agent_id = %(agent)s"
            " AND state = 'queued' AND pickup_by > %(now)s"
            " ORDER BY created_at, job_id LIMIT %(limit)s FOR UPDATE SKIP LOCKED) d"
            " WHERE j.job_id = d.job_id AND j.state = 'queued'"
            " RETURNING j.created_at, j.job_id, j.payload",
            {"now": now, "agent": agent_id, "limit": PULL_LIMIT},
        ).fetchall()
        return [dict(payload) for _, _, payload in sorted(rows, key=lambda r: r[:2])]

    def get_for_agent(
        self, job_id: UUID, agent_id: UUID, *, lock: bool = False
    ) -> JobRow | None:
        """The job only if it is addressed to agent_id."""
        query = sql.SQL(
            "SELECT job_id, kind, agent_id, state::text, created_at, pickup_by,"
            " dispatched_at, finished_at FROM scan_job WHERE job_id = %s"
            " AND agent_id = %s{}"
        ).format(sql.SQL(" FOR UPDATE" if lock else ""))
        row = self._conn.execute(query, (job_id, agent_id)).fetchone()
        return None if row is None else JobRow(*row)

    def _finish(self, state: str, job_id: UUID, now: datetime) -> bool:
        return (
            self._conn.execute(
                "UPDATE scan_job SET state = CAST(%s AS scan_state), finished_at = %s"
                " WHERE job_id = %s AND state = 'dispatched'",
                (state, now, job_id),
            ).rowcount
            == 1
        )

    def complete(self, job_id: UUID, now: datetime) -> bool:
        """dispatched → completed (an accepted inventory upload)."""
        return self._finish("completed", job_id, now)

    def fail(self, job_id: UUID, now: datetime) -> bool:
        """dispatched → failed (a refused upload, TS §3.4 L244)."""
        return self._finish("failed", job_id, now)

    def expire_past_pickup(self, now: datetime) -> int:
        """queued jobs whose pickup_by is not after now → expired."""
        return self._conn.execute(
            "UPDATE scan_job SET state = 'expired', finished_at = %s"
            " WHERE state = 'queued' AND pickup_by <= %s",
            (now, now),
        ).rowcount

    def fail_dispatched_inventory(
        self, dispatched_before: datetime, now: datetime
    ) -> int:
        """Inventory jobs dispatched before the cut-off and never uploaded →
        failed. No retry row is ever made (inventory jobs are never retried)."""
        return self._conn.execute(
            "UPDATE scan_job SET state = 'failed', finished_at = %s"
            " WHERE kind = 'inventory' AND state = 'dispatched' AND dispatched_at < %s",
            (now, dispatched_before),
        ).rowcount

    def oldest_queued_for_online(self) -> datetime | None:
        """created_at of the oldest queued job whose agent is online (#66)."""
        row = self._conn.execute(
            "SELECT min(j.created_at) FROM scan_job j JOIN agent a"
            " ON a.agent_id = j.agent_id"
            " WHERE j.state = 'queued' AND a.status = 'online'"
        ).fetchone()
        oldest: datetime | None = None if row is None else row[0]
        return oldest

    def count_queued(self) -> int:
        row = self._conn.execute(
            "SELECT count(*) FROM scan_job WHERE state = 'queued'"
        ).fetchone()
        return 0 if row is None else int(row[0])

    def default_partition_has_rows(self) -> bool:
        """Rows in scan_result_default (TS §5.3 L1047): they must alert (#44)."""
        row = self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM scan_result_default)"
        ).fetchone()
        return bool(row is not None and row[0])
