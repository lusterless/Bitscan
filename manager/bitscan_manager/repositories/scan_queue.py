"""Scan queue SQL: the per-policy queue lock, the policy snapshot, target
resolution, the scan row, its jobs in one statement, and the older queued jobs
cancelled (TS §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L550, §6.5; #125
(d)–(f); plan TASK-198 §3). Parameterised statements only.

Each function runs in the caller's transaction and never commits. Consistency
with a concurrent import or delete (#125 (d)): the queue lock serialises scans
of one policy; the policy row FOR SHARE makes an import's or delete's UPDATE
policy wait for this transaction (or this one see its commit); the version,
status, deleted_at and the active plugins then come from one statement, so
from one snapshot. A compliance payload is composed here (and in job_sweep for
a retry) from the snapshot's plugins only; no caller supplies command text.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from bitscan_manager.services.jobs.build import CatalogPlugin

type Conn = psycopg.Connection[Any]

_SNAPSHOT: Final = sql.SQL(
    "SELECT p.version, p.policy_status::text, p.deleted_at IS NOT NULL,"
    " COALESCE((SELECT json_agg(json_build_array(v.plugin_uuid, v.display_name,"
    " v.execute, v.timeout_s, v.operator::text, v.expected_result)"
    " ORDER BY pp.sort_order, pp.plugin_uuid) FROM policy_plugin pp"
    " JOIN v_plugin v ON v.plugin_uuid = pp.plugin_uuid"
    " WHERE pp.policy_id = p.policy_id AND v.state = 'active'), '[]')"
    " FROM policy p WHERE p.policy_id = %s"
)

# Eligible agents (TS §4.4 L555): not decommissioned or awaiting approval;
# offline agents included. Unknown ids drop out by the match. Tags: any of.
_RESOLVE_ANY: Final = sql.SQL(
    "SELECT a.agent_id FROM agent a"
    " WHERE a.status NOT IN ('decommissioned', 'awaiting_approval'){}"
    " ORDER BY a.agent_id"
)
_RESOLVE: Final[Mapping[str, sql.Composed]] = {
    "all": _RESOLVE_ANY.format(sql.SQL("")),
    "agents": _RESOLVE_ANY.format(
        sql.SQL(" AND a.agent_id = ANY(CAST(%(agents)s AS uuid[]))")
    ),
    "tags": _RESOLVE_ANY.format(
        sql.SQL(
            " AND EXISTS (SELECT 1 FROM agent_tag t WHERE t.agent_id = a.agent_id"
            " AND t.tag = ANY(CAST(%(tags)s AS text[])))"
        )
    ),
}

# One INSERT for every job of the scan; job_id and agent_id go into the
# payload as lowercase hyphenated text, the rest is the scan's shared parts.
# No duplicate run (TS §4.4, §5.2; owner decision 2026-11-14): an agent that
# already has a dispatched or running compliance job of the same policy gets
# this scan's job inserted cancelled, with cancel_reason 'already_running'
# and finished_at = created_at, so it is never sent. It is decided at INSERT
# because bitscan_app may not UPDATE cancel_reason. The policy queue lock
# serialises scans of one policy; a job a concurrent pull dispatches just
# after this check is caught by the agent's own rule (TS §3.3).
_JOBS: Final = sql.SQL(
    "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, state, payload,"
    " eval_spec, created_at, pickup_by, finished_at, cancel_reason)"
    " SELECT t.job_id, 'compliance', %(scan)s, t.agent_id,"
    " CASE WHEN b.busy THEN 'cancelled' ELSE 'queued' END::scan_state,"
    " jsonb_build_object('job_id', t.job_id::text, 'agent_id', t.agent_id::text,"
    " 'kind', 'compliance', 'pickup_by', CAST(%(text)s AS text),"
    " 'plugins', CAST(%(plugins)s AS jsonb),"
    " 'redaction_patterns', CAST(%(patterns)s AS jsonb)),"
    " CAST(%(spec)s AS jsonb), %(created)s, %(pickup)s,"
    " CASE WHEN b.busy THEN CAST(%(created)s AS timestamptz) END,"
    " CASE WHEN b.busy THEN 'already_running' END"
    " FROM unnest(CAST(%(jobs)s AS uuid[]), CAST(%(agents)s AS uuid[]))"
    " AS t(job_id, agent_id)"
    " CROSS JOIN LATERAL (SELECT EXISTS (SELECT 1 FROM scan_job j"
    " JOIN scan s ON s.scan_id = j.scan_id"
    " WHERE j.agent_id = t.agent_id AND j.kind = 'compliance'"
    " AND j.state IN ('dispatched', 'running') AND s.policy_id = %(policy)s)"
    " AS busy) AS b"
    " RETURNING (cancel_reason IS NOT NULL)"
)


@dataclass(frozen=True)
class PolicySnapshot:
    policy_id: int
    version: int
    status: str  # 'enabled' | 'disabled'
    deleted: bool
    plugins: list[CatalogPlugin]  # active only, in sort_order


def lock_policy_queue(conn: Conn, policy_id: int) -> None:
    """Serialises the scans of one policy until this transaction ends."""
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('scan_queue:' || CAST(%s AS text)))",
        (policy_id,),
    )


def policy_snapshot(conn: Conn, policy_id: int) -> PolicySnapshot | None:
    """The policy row FOR SHARE, then its version, status, deleted flag and
    active plugins in one statement. None if the policy does not exist."""
    held = conn.execute(
        "SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE", (policy_id,)
    ).fetchone()
    if held is None:
        return None
    row = conn.execute(_SNAPSHOT, (policy_id,)).fetchone()
    if row is None:  # the row is share-locked, so it cannot have gone
        return None
    plugins = [  # json_build_array order = CatalogPlugin order
        CatalogPlugin(
            plugin_uuid=UUID(p[0]),
            display_name=str(p[1]),
            execute=str(p[2]),
            timeout_s=int(p[3]),
            operator=str(p[4]),
            expected=str(p[5]),
        )
        for p in row[3]
    ]
    return PolicySnapshot(policy_id, int(row[0]), str(row[1]), bool(row[2]), plugins)


def resolve_agents(
    conn: Conn, kind: str, agents: Sequence[UUID], tags: Sequence[str]
) -> list[UUID]:
    """The target's eligible agents, distinct and sorted, in one statement."""
    query = _RESOLVE.get(kind)
    if query is None:
        raise ValueError("unsupported target kind")
    params = {"agents": list(agents), "tags": list(tags)}
    rows = conn.execute(query, params).fetchall()
    return [UUID(str(r[0])) for r in rows]


def insert_scan(
    conn: Conn,
    *,
    policy_id: int,
    policy_version: int,
    trigger: str,
    schedule_id: int | None,
    target_json: Mapping[str, Any],
    requested_by: int | None,
    created_at: datetime,
) -> UUID:
    row = conn.execute(
        "INSERT INTO scan (policy_id, policy_version, trigger, schedule_id, target,"
        " requested_by, state, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s) RETURNING scan_id",
        (
            policy_id,
            policy_version,
            trigger,
            schedule_id,
            Jsonb(dict(target_json)),
            requested_by,
            created_at,
        ),
    ).fetchone()
    if row is None:  # INSERT … RETURNING gives exactly one row
        raise RuntimeError("INSERT … RETURNING returned no row")
    return UUID(str(row[0]))


@dataclass(frozen=True)
class JobsInserted:
    queued: int  # jobs that will be sent
    already_running: int  # jobs inserted cancelled: the policy runs on that host


def insert_jobs(
    conn: Conn,
    *,
    scan_id: UUID,
    policy_id: int,
    agent_ids: Sequence[UUID],
    job_ids: Sequence[UUID],
    created_at: datetime,
    pickup_by: datetime,
    pickup_text: str,
    plugins_json: Sequence[Mapping[str, Any]],
    patterns: Sequence[str],
    eval_spec_json: Mapping[str, Any],
) -> JobsInserted:
    """One compliance job per (job_id, agent_id) pair, in one INSERT; every
    job has the scan's created_at (#125 (f)). A job for an agent that already
    runs policy_id is inserted cancelled with 'already_running' (_JOBS)."""
    if not agent_ids or len(agent_ids) != len(job_ids):
        raise ValueError("one job id per agent is required")
    params = {
        "scan": scan_id,
        "policy": policy_id,
        "text": pickup_text,
        "plugins": Jsonb([dict(p) for p in plugins_json]),
        "patterns": Jsonb(list(patterns)),
        "spec": Jsonb(dict(eval_spec_json)),
        "created": created_at,
        "pickup": pickup_by,
        "jobs": list(job_ids),
        "agents": list(agent_ids),
    }
    rows = conn.execute(_JOBS, params).fetchall()
    skipped = sum(1 for r in rows if r[0])
    return JobsInserted(queued=len(rows) - skipped, already_running=skipped)


def cancel_older_queued(
    conn: Conn,
    *,
    policy_id: int,
    agent_ids: Sequence[UUID],
    new_scan_id: UUID,
    now: datetime,
) -> list[UUID]:
    """The newer scan cancels every queued compliance job (original or retry)
    of an earlier scan of the same policy for the listed agents (TS §4.4
    L558, #125 (e)). Dispatched and running jobs, other policies and
    inventory jobs are untouched; only the scan_job rows are locked."""
    rows = conn.execute(
        "UPDATE scan_job j SET state = 'cancelled', finished_at = %(now)s FROM scan s"
        " WHERE j.scan_id = s.scan_id AND s.policy_id = %(policy)s"
        " AND j.kind = 'compliance' AND j.state = 'queued'"
        " AND j.agent_id = ANY(CAST(%(agents)s AS uuid[])) AND j.scan_id <> %(new)s"
        " RETURNING j.job_id",
        {
            "now": now,
            "policy": policy_id,
            "agents": list(agent_ids),
            "new": new_scan_id,
        },
    ).fetchall()
    return sorted(UUID(str(r[0])) for r in rows)
