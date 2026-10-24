"""Job pull and the M3 results answer (TS §6.1 L1064–L1065, L1071, §6.5
L1165–L1184, §3.3 L210–L214, §8.4 L1291; REQ-072, REQ-073, REQ-088; #54 (c),
#65 (f), #71).

Pull: at most 10 of the agent's own queued inventory jobs whose pickup_by is
still ahead, oldest first, each marked dispatched exactly once (TASK-054).
A job body is its stored payload: job_id, agent_id, kind, pickup_by; never
an eval_spec, operator or expected value. Jobs come only from the scheduler.

Results: no compliance job exists before M9, so every well-formed batch is
refused 409 job_not_acceptable, stores nothing, changes no job, and writes
one agent.result_refused entry. More than 20 refusals for one agent within 10
minutes write one result_409_flood alert, at most once per hour, marked on
commit. No stdout or stderr reaches an entry or a log.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

FLOOD_PER_10_MIN: Final = 20  # #54 (c): more than this alerts


class JobPuller(Protocol):  # repositories.jobs.JobRepo
    def pull(self, agent_id: UUID, now: datetime) -> list[dict[str, Any]]: ...


class Auditor(Protocol):  # services.users.TxAudit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...

    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


class FloodWindow(Protocol):  # services.audit.thresholds.SlidingCount
    def count_and_check(
        self, key: Any, weight: int = 1, threshold: int | None = None
    ) -> bool: ...

    def mark_fired(self, key: Any) -> None: ...


def pull_jobs(jobs: JobPuller, agent_id: UUID, now: datetime) -> list[dict[str, Any]]:
    """The payloads of the jobs this pull dispatched, oldest first."""
    return jobs.pull(agent_id, now)


def refuse_results(
    audit: Auditor,
    flood: FloodWindow,
    on_commit: Callable[[Callable[[], None]], None],
    *,
    agent_id: UUID,
    job_id: UUID,
    reason: str,
    detail: Mapping[str, object],
) -> None:
    """One agent.result_refused entry (#71); counts a 409 toward the flood
    window. reason is a fixed word: job_not_acceptable, too_large."""
    actor = f"agent:{agent_id}"
    target = f"job:{job_id}"
    audit.audit(actor, "agent.result_refused", target, {"reason": reason, **detail})
    if reason != "job_not_acceptable":
        return
    if flood.count_and_check(agent_id):
        audit.alert(
            "result_409_flood",
            actor,
            "alert.result_409_flood",
            actor,
            {"over_per_10_min": FLOOD_PER_10_MIN},
        )
        on_commit(lambda: flood.mark_fired(agent_id))  # the hour taken on commit
