"""Job pull and the refusal answer of the results route (TS §6.1
L1064–L1065, L1071, §6.5 L1165–L1184, §3.3 L210–L214, §8.4 L1291; REQ-072,
REQ-073, REQ-088, REQ-213, REQ-214; #54 (c), #65 (f), #71, #124 (f), (g)).

Pull: at most 10 of the agent's own queued jobs, inventory and compliance,
whose pickup_by is still ahead, oldest first, each marked dispatched exactly
once. A job body is its stored payload; never an eval_spec, operator or
expected value. Jobs come only from the scheduler and the scan queue.

Refusals: a refused result batch (intake.accept_results, or a body over the
cap) stores nothing, changes no job, and writes one agent.result_refused
entry. More than 20 counted 409s for one agent within 10 minutes write one
result_409_flood alert, at most once per hour, marked on commit; a 409 for
the agent's own cancelled job is not counted (#124 (f)). No stdout or stderr
reaches an entry or a log.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

FLOOD_PER_10_MIN: Final = 20  # #54 (c): more than this alerts
# The 409 refusal reasons (#124 (a), (h)); too_large answers 413.
_FLOOD_REASONS: Final = frozenset({"job_not_acceptable", "eval_spec_invalid"})


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
    count_flood: bool = True,
) -> None:
    """One agent.result_refused entry (#71); counts a 409 toward the flood
    window unless count_flood is False (the agent's own cancelled job). reason
    is a fixed word: job_not_acceptable, eval_spec_invalid, too_large."""
    actor = f"agent:{agent_id}"
    target = f"job:{job_id}"
    audit.audit(actor, "agent.result_refused", target, {"reason": reason, **detail})
    if reason not in _FLOOD_REASONS or not count_flood:
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
