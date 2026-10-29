"""Results read SQL: effective verdicts and per-host counts of one scan
(TS §4.5 L601–L602, §4.4 L577–L583, §5.2; design note D3). SELECT only,
parameterised statements only.

The effective verdict of a result (job and plugin) is the latest
scan_result_reeval row, the one with the highest reeval_id (#119), or else the
original scan_result verdict. scan_result_reeval has no index on job and
plugin, and TS §5.2 allows none, so every statement reads it in one pass,
filtered by the scan's job ids (never a per-result subquery).

Each function runs in the caller's transaction and never commits. bitscan_app
needs only SELECT on scan_job, scan_result (with its partitions) and
scan_result_reeval.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

type Conn = psycopg.Connection[Any]

# jobs: the scan's compliance jobs, originals and retries (TS §4.4 L577).
# latest: one pass over scan_result_reeval; the job ids are an InitPlan array.
# eff: every result with its original and effective verdicts. Joining on
# job_created_at lets PostgreSQL prune scan_result partitions (the trigger
# keeps it equal to scan_job.created_at).
_EFFECTIVE: Final = sql.SQL(
    "WITH jobs AS MATERIALIZED (SELECT job_id, agent_id, created_at, retry_of,"
    " payload FROM scan_job WHERE scan_id = %(scan_id)s AND kind = 'compliance'),"
    " latest AS (SELECT DISTINCT ON (e.job_id, e.plugin_uuid) e.job_id,"
    " e.plugin_uuid, e.reeval_id, e.eval_code, e.eval_detail, e.policy_version,"
    " e.reevaluated_by, e.reevaluated_at FROM scan_result_reeval e"
    " WHERE e.job_id = ANY(ARRAY(SELECT job_id FROM jobs))"
    " ORDER BY e.job_id, e.plugin_uuid, e.reeval_id DESC),"
    " eff AS (SELECT r.job_id, r.plugin_uuid, j.agent_id,"
    " r.eval_code AS original_code, r.eval_detail AS original_detail,"
    " COALESCE(l.eval_code, r.eval_code) AS code,"
    " CASE WHEN l.reeval_id IS NULL THEN r.eval_detail ELSE l.eval_detail END"
    " AS detail, l.reeval_id, l.policy_version, l.reevaluated_by,"
    " l.reevaluated_at FROM jobs j JOIN scan_result r ON r.job_id = j.job_id"
    " AND r.job_created_at = j.created_at LEFT JOIN latest l"
    " ON l.job_id = r.job_id AND l.plugin_uuid = r.plugin_uuid)"
)

_RESULTS: Final = sql.SQL(
    "{} SELECT job_id, plugin_uuid, agent_id, original_code, original_detail,"
    " code, detail, reeval_id, policy_version, reevaluated_by, reevaluated_at"
    " FROM eff ORDER BY agent_id, job_id, plugin_uuid"
).format(_EFFECTIVE)

# planned: the plugins of each agent's original job (TS §6.5 payload
# "plugins"); an original job with no plugins still gives its agent a row.
# A result in the retry fills the original's planned plugin, so it counts once
# (first result wins, TS §4.4 L578, is the intake's rule). Not run: a planned
# plugin with no result in the job or its retry (TS §4.4 L583).
_COUNTS: Final = sql.SQL(
    "{}, planned AS (SELECT DISTINCT j.agent_id,"
    " CAST(p.item ->> 'plugin_uuid' AS uuid) AS plugin_uuid FROM jobs j"
    " LEFT JOIN LATERAL jsonb_array_elements(j.payload -> 'plugins') AS p(item)"
    " ON true WHERE j.retry_of IS NULL)"
    " SELECT pl.agent_id, count(*) FILTER (WHERE e.code = 0),"
    " count(*) FILTER (WHERE e.code = 1), count(*) FILTER (WHERE e.code = 2),"
    " count(*) FILTER (WHERE pl.plugin_uuid IS NOT NULL AND e.plugin_uuid IS NULL)"
    " FROM planned pl LEFT JOIN eff e ON e.agent_id = pl.agent_id"
    " AND e.plugin_uuid = pl.plugin_uuid GROUP BY pl.agent_id ORDER BY pl.agent_id"
).format(_EFFECTIVE)


@dataclass(frozen=True, slots=True)
class EffectiveRow:
    """One result with its original verdict and its effective one (#119)."""

    job_id: UUID
    plugin_uuid: UUID
    agent_id: UUID
    original_code: int  # scan_result.eval_code
    original_detail: str | None  # scan_result.eval_detail
    code: int  # the latest re-evaluation's, else the original's
    detail: str | None
    reeval_id: int | None  # None when no re-evaluation exists
    reeval_policy_version: int | None
    reevaluated_by: int | None
    reevaluated_at: datetime | None


@dataclass(frozen=True, slots=True)
class HostCounts:
    """Effective counts of one agent in one scan (#120 (c))."""

    agent_id: UUID
    passed: int
    failed: int
    errors: int
    not_run: int


def _opt_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def effective_results(conn: Conn, scan_id: UUID) -> list[EffectiveRow]:
    """Every result of the scan (original jobs and retries), ordered by
    agent_id, job_id and plugin_uuid; [] for an unknown scan."""
    rows = conn.execute(_RESULTS, {"scan_id": scan_id}).fetchall()
    return [
        EffectiveRow(
            job_id=UUID(str(r[0])),
            plugin_uuid=UUID(str(r[1])),
            agent_id=UUID(str(r[2])),
            original_code=int(r[3]),
            original_detail=_opt_str(r[4]),
            code=int(r[5]),
            detail=_opt_str(r[6]),
            reeval_id=_opt_int(r[7]),
            reeval_policy_version=_opt_int(r[8]),
            reevaluated_by=_opt_int(r[9]),
            reevaluated_at=r[10],
        )
        for r in rows
    ]


def host_counts(conn: Conn, scan_id: UUID) -> list[HostCounts]:
    """One row per agent with an original compliance job in the scan, ordered
    by agent_id; [] for an unknown scan."""
    rows = conn.execute(_COUNTS, {"scan_id": scan_id}).fetchall()
    return [
        HostCounts(UUID(str(r[0])), int(r[1]), int(r[2]), int(r[3]), int(r[4]))
        for r in rows
    ]
