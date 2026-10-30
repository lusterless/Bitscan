"""Compliance job state rules (TS §4.4 L562–L582, §3.3 L222; REQ-206, REQ-217;
open questions #124 (a), #127 (a)–(c)).

Pure: plain values in, plain values out. No I/O, no logging, no clock (the
caller passes `now`), no database, repository or API import.

"Has a result" counts the job's sibling too (original ↔ retry, #127 (a)): the
callers compute `all_have_results` and `any_result` over the unit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final, Literal

JobState = Literal[
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "expired",
]

# States that never change (TS §4.4 L582).
FINAL: Final = frozenset({"completed", "expired", "cancelled"})
# States whose job takes a result post, within LATE_WINDOW (#124 (a)); a
# completed job yields only duplicates.
ACCEPTING: Final = frozenset(
    {"dispatched", "running", "failed", "partial", "completed"}
)
LATE_WINDOW: Final = timedelta(days=7)  # TS §4.4 L578: dispatched_at + 7 days
DEADLINE_SLACK: Final = timedelta(minutes=10)  # TS §4.4 L575
NEVER_STARTED_AFTER: Final = timedelta(hours=24)  # TS §4.4 L575
MAX_PARALLEL_MIN: Final = 1
MAX_PARALLEL_MAX: Final = 8

# The allowed compliance transitions (REQ-206). Staying in a state is not a
# transition; `partial → partial` is listed because a late batch re-enters it.
TRANSITIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "queued": frozenset({"dispatched", "expired", "cancelled"}),
        "dispatched": frozenset({"running", "failed", "cancelled"}),
        "running": frozenset({"completed", "partial", "failed", "cancelled"}),
        "failed": frozenset({"completed", "partial"}),
        "partial": frozenset({"completed", "partial"}),
        "completed": frozenset(),
        "expired": frozenset(),
        "cancelled": frozenset(),
    }
)


def allowed(old: str, new: str) -> bool:
    """True when `old → new` is one of the TRANSITIONS; False for any other
    pair, including unknown state names."""
    return new in TRANSITIONS.get(old, frozenset())


def deadline_at(
    started_at: datetime, timeouts: Sequence[int], max_parallel: int
) -> datetime:
    """start + ceil(Σ timeout_s ÷ max_parallel_plugins) s + 10 min, in integer
    arithmetic so 5,000 × 600 s stays exact (TS §4.4 L575)."""
    if not MAX_PARALLEL_MIN <= max_parallel <= MAX_PARALLEL_MAX:
        raise ValueError("max_parallel_plugins must be 1 to 8")
    if not timeouts:
        raise ValueError("a job has at least one plugin")
    seconds = -(-sum(timeouts) // max_parallel)  # ceiling division
    return started_at + timedelta(seconds=seconds) + DEADLINE_SLACK


def accepts_results(
    kind: str, state: str, dispatched_at: datetime | None, now: datetime
) -> bool:
    """Whether a result post for this job is taken at `now` (#124 (a)): a
    compliance job in an ACCEPTING state, while now ≤ dispatched_at + 7 days."""
    if kind != "compliance" or state not in ACCEPTING or dispatched_at is None:
        return False
    return now <= dispatched_at + LATE_WINDOW


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """The job's state after an accepted batch; `start` means set `started_at`
    and `deadline_at` now (only on the first batch of a dispatched job)."""

    state: JobState
    start: bool


def after_batch(
    state: str, *, stored: int, all_have_results: bool, final: bool
) -> BatchOutcome:
    """The outcome of an accepted batch (#127 (a), #124 (d)). Callers check
    `accepts_results` first; any other state raises ValueError."""
    if state == "dispatched" or state == "running":
        start = state == "dispatched"
        if all_have_results:
            return BatchOutcome("completed", start)
        return BatchOutcome("partial" if final else "running", start)
    if state == "failed" or state == "partial":
        if stored == 0:  # a start notice or only duplicates: nothing changes
            return BatchOutcome("failed" if state == "failed" else "partial", False)
        return BatchOutcome("completed" if all_have_results else "partial", False)
    if state == "completed":
        return BatchOutcome("completed", False)
    raise ValueError("job state does not accept results")


def after_deadline(*, any_result: bool, all_have_results: bool) -> JobState:
    """The state of a job whose deadline passed (#127 (b)); also the never-
    started rule, where no result can exist (gives `failed`)."""
    if all_have_results:
        return "completed"
    return "partial" if any_result else "failed"
