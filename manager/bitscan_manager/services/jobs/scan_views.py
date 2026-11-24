"""Scan list, scan detail and a host's scan history (TS §6.2 L1113, L1120,
L1122, §4.5 L602–L604, §4.4 L577–L585; REQ-264 to REQ-266; open questions
#120, #145; plan work/plans/TASK-232.md §5).

- The state is `scan.state` as stored, never re-derived (M9 interface note).
- The per-host counts are M8's effective counts (`results.host_counts`) and
  the score M8's `score.host_score`: passed ÷ (passed + failed), None when
  that is 0, errors beside it. Computed when read, never stored.
- The detail is read in one REPEATABLE READ, READ ONLY snapshot, so the
  scan, its jobs and the counts agree.

SELECT only; nothing is logged. The routes map ScanNotFound and
AgentNotFound to 404 and AnchorGone (re-exported here, so a route imports
no repository) to 400.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from bitscan_manager.repositories import result_reads, results, scan_reads
from bitscan_manager.repositories.scan_reads import AnchorGone, JobRow, ScanRow
from bitscan_manager.runtime import Database
from bitscan_manager.services.evaluator.score import HostScore, host_score

__all__ = [
    "AgentNotFound",
    "AnchorGone",
    "HostView",
    "ScanDetail",
    "ScanFilters",
    "ScanNotFound",
    "agent_scans",
    "list_scans",
    "scan_detail",
]


class ScanNotFound(Exception):
    """No scan has this id (404 `not_found`)."""


class AgentNotFound(Exception):
    """No agent has this id (404 `not_found`)."""


@dataclass(frozen=True)
class ScanFilters:
    """REQ-264 filters, combined with AND; None = not filtered."""

    policy_id: int | None
    agent_id: UUID | None
    state: str | None
    created_after: datetime | None  # inclusive
    created_before: datetime | None  # exclusive


@dataclass(frozen=True, slots=True)
class ClusterVerdict:
    """TS §3.8: `error` when the exit code is not 0, `pass` when every graded
    check passes, otherwise `fail`, with the ClusterMAX verdict counts."""

    verdict: str
    exit_code: int
    passed: int
    failed: int
    warning: int
    not_applicable: int


@dataclass(frozen=True, slots=True)
class HostView:
    """One agent with an original job in the scan (#145 (b))."""

    agent_id: UUID
    hostname: str
    jobs: list[JobRow]  # the original first, then its retry
    host: HostScore  # effective counts and score
    clustermax: ClusterVerdict | None = None  # a ClusterMAX scan's run


def cluster_verdict(run: scan_reads.ClusterRunRow) -> ClusterVerdict:
    if run.exit_code != 0:
        verdict = "error"
    elif run.all_graded_pass:
        verdict = "pass"
    else:
        verdict = "fail"
    return ClusterVerdict(
        verdict,
        run.exit_code,
        run.passed,
        run.failed,
        run.warning,
        run.not_applicable,
    )


@dataclass(frozen=True, slots=True)
class ScanDetail:
    scan: ScanRow
    target: dict[str, Any]  # as requested, without resolved_agents
    hosts: list[HostView]  # by hostname, then agent_id


def list_scans(
    db: Database, filters: ScanFilters, limit: int, after: UUID | None
) -> list[ScanRow]:
    """At most `limit` scans, newest first, after the anchor scan `after`."""
    with db.transaction() as tx:
        return scan_reads.scan_page(
            tx.conn,
            policy_id=filters.policy_id,
            agent_id=filters.agent_id,
            state=filters.state,
            created_after=filters.created_after,
            created_before=filters.created_before,
            limit=limit,
            after=after,
        )


def agent_scans(
    db: Database, agent_id: UUID, limit: int, after: UUID | None
) -> list[ScanRow]:
    """The scans whose resolved target holds the agent, newest first; a
    decommissioned agent's history too."""
    with db.transaction() as tx:
        if not scan_reads.agent_exists(tx.conn, agent_id):
            raise AgentNotFound
        return scan_reads.agent_scan_page(tx.conn, agent_id, limit=limit, after=after)


def _hosts(
    jobs: list[JobRow],
    counts: dict[UUID, results.HostCounts],
    runs: dict[UUID, scan_reads.ClusterRunRow],
) -> list[HostView]:
    """Jobs come ordered by hostname, agent_id, original first; a host is an
    agent with an original job, and its retry joins it."""
    by_agent: dict[UUID, list[JobRow]] = {}
    for job in jobs:
        by_agent.setdefault(job.agent_id, []).append(job)
    hosts: list[HostView] = []
    for agent_id, unit in by_agent.items():
        if all(j.retry_of is not None for j in unit):
            continue
        c = counts[agent_id]
        run = next((runs[j.job_id] for j in unit if j.job_id in runs), None)
        hosts.append(
            HostView(
                agent_id=agent_id,
                hostname=unit[0].hostname,
                jobs=unit,
                host=host_score(c.passed, c.failed, c.errors, c.not_run),
                clustermax=None if run is None else cluster_verdict(run),
            )
        )
    return hosts


def scan_detail(db: Database, scan_id: UUID) -> ScanDetail:
    """The scan, its target and every host's jobs, counts and score, from
    one read-only snapshot. Raises ScanNotFound."""
    with db.transaction() as tx:
        result_reads.read_only_snapshot(tx.conn)  # the first statement
        found = scan_reads.scan_detail(tx.conn, scan_id)
        if found is None:
            raise ScanNotFound
        jobs = scan_reads.scan_jobs(tx.conn, scan_id)
        counts = {c.agent_id: c for c in results.host_counts(tx.conn, scan_id)}
        runs = scan_reads.cluster_runs(tx.conn, scan_id)
    return ScanDetail(
        scan=found.scan, target=found.target, hosts=_hosts(jobs, counts, runs)
    )
