"""Scheduled scans: the 30-second tick (TS §4.4 L557, §2.1 L103; REQ-225,
REQ-227; open questions #3, #128 (d)–(g); plan work/plans/TASK-203.md §5,
design note D4).

Each due schedule (enabled, next_run_at not after now) runs once, in its own
transaction, with its row locked FOR UPDATE SKIP LOCKED, so two ticks never
run one schedule twice. A due time more than 2 minutes old was missed (the
manager was down or stalled) and is not run: runs are not back-filled. A run
is skipped when the previous scan of the schedule is unfinished, the policy is
disabled, or the target resolves to no agent. Skips and misses write no scan
and no audit entry, and are logged with a fixed word and the schedule_id only.
Either way next_run_at moves to the next fire strictly after now. A queued
scan is `queue_scan(trigger='scheduled')` by actor `system`, which never
raises the all-hosts API-token alert.
"""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from bitscan_manager.repositories import schedules
from bitscan_manager.repositories.schedules import ScheduleRow
from bitscan_manager.runtime import Database, Tx
from bitscan_manager.services.jobs import queue
from bitscan_manager.services.jobs.targets import InvalidTarget, parse_target
from bitscan_manager.services.scheduler.cron import (
    InvalidSchedule,
    next_fire,
    parse_schedule,
)

log = logging.getLogger("bitscan_manager.scheduler")

TICK_S: Final = 30
MISSED_AFTER: Final = timedelta(minutes=2)  # #128 (e): older due times were missed
# A stored cron, time zone or target that no longer parses (only an owner
# write can cause it) is retried a day later; the schedule is not disabled.
INVALID_RETRY: Final = timedelta(days=1)
# _run's answer when another session holds the policy row (TASK-203 r1): the
# row is left due and tried at the next tick.
BUSY: Final = "busy"
_REFUSALS: Final[dict[type[Exception], str]] = {
    queue.PolicyDisabled: "policy_disabled",
    queue.PolicyDeleted: "policy_disabled",  # its schedules are disabled (L550)
    queue.PolicyHasNoPlugins: "policy_has_no_plugins",
    queue.NoTargetAgents: "no_target_agents",  # #3
}


@dataclass
class TickResult:
    queued: int = 0
    skipped: Counter[str] = field(default_factory=Counter)  # reason word → count
    failed: int = 0  # rows whose transaction raised; retried next tick
    busy: int = 0  # rows whose policy another session held; retried next tick


def _skip(row: ScheduleRow, reason: str) -> str:
    log.info(
        "scheduled run skipped",
        extra={"data": {"schedule_id": row.schedule_id, "reason": reason}},
    )
    return reason


def _run(tx: Tx, row: ScheduleRow, now: datetime) -> str:
    """One locked due row: queue its scan or skip it, then move next_run_at
    on. Returns "queued", the skip word, or BUSY (nothing written)."""
    conn = tx.conn
    try:
        nxt = next_fire(parse_schedule(row.cron, row.timezone), now)
        target = parse_target(row.target)
    except (InvalidSchedule, InvalidTarget):
        schedules.mark_run(
            conn, row.schedule_id, ran_at=None, next_run_at=now + INVALID_RETRY
        )
        return _skip(row, "invalid")
    reason: str | None = None
    if row.next_run_at is None or row.next_run_at < now - MISSED_AFTER:
        reason = "missed"
    elif schedules.previous_unfinished(conn, row.schedule_id):
        reason = "previous_unfinished"
    elif not schedules.try_share_policy(conn, row.policy_id):
        # Never wait for the policy while holding the schedule row: a policy
        # delete holds the policy, then updates this row (TS §4.3 L550).
        return BUSY
    else:
        state = schedules.policy_state(conn, row.policy_id)
        if state is None or state[0] != "enabled" or state[1]:
            reason = "policy_disabled"
    if reason is None:
        try:
            with conn.transaction():  # a savepoint: a refusal undoes only the try
                queue.queue_scan(
                    tx,
                    policy_id=row.policy_id,
                    target=target,
                    trigger="scheduled",
                    schedule_id=row.schedule_id,
                    requested_by=None,
                    actor="system",
                    via_api_token=False,
                    now=now,
                )
        except tuple(_REFUSALS) as exc:
            reason = _REFUSALS[type(exc)]
    if reason is not None:
        schedules.mark_run(conn, row.schedule_id, ran_at=None, next_run_at=nxt)
        return _skip(row, reason)
    schedules.mark_run(conn, row.schedule_id, ran_at=now, next_run_at=nxt)
    return "queued"


def run_due_schedules(
    db: Database, now: datetime, wake: Callable[[], None]
) -> TickResult:
    """Every schedule due at `now`, one transaction each (#128 (e)). A row
    whose transaction raises is logged by schedule_id and exception type, left
    unchanged and not tried again in this tick; a failure before a row is
    chosen (database down, scheduler stopping) ends the tick."""
    result = TickResult()
    failed: set[int] = set()  # failed or busy: not tried again in this tick
    while True:
        chosen: list[int] = []
        try:
            with db.transaction() as tx:
                tx.on_commit(wake)  # the scan.create entry reaches the sink soon
                due = schedules.due(tx.conn, now, limit=len(failed) + 1)
                rows = [r for r in due if r.schedule_id not in failed]
                if not rows:
                    return result
                chosen.append(rows[0].schedule_id)
                outcome = _run(tx, rows[0], now)
        except Exception as exc:
            if not chosen:
                raise
            failed.add(chosen[0])
            result.failed += 1
            log.error(
                "scheduled run failed",
                extra={
                    "data": {"schedule_id": chosen[0], "exc_type": type(exc).__name__}
                },
            )
            continue
        if outcome == BUSY:
            failed.add(chosen[0])
            result.busy += 1
        elif outcome == "queued":
            result.queued += 1
        else:
            result.skipped[outcome] += 1
