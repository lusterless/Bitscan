"""Retention rules (TS §5.3 L1049, L1053; #150 (a)–(e), (i), (j); plan
TASK-242 §2).

Pure: no I/O, no clock, no logging. Every instant must be timezone-aware; a
naive one raises ValueError. A row is past a cutoff only when it is strictly
older (time < cutoff), so a row exactly at the cutoff is kept.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

SCAN_AGE: Final = timedelta(days=400)  # scan.created_at (#150 (a))
SNAPSHOT_AGE: Final = timedelta(days=180)  # inventory_snapshot.collected_at
REQUEST_AGE: Final = timedelta(days=90)  # enrollment_request.decided_at (#150 (c))
TOKEN_AGE: Final = timedelta(days=90)  # user_token.expires_at (#150 (b))
INVENTORY_JOB_AGE: Final = timedelta(days=30)  # scan_job.finished_at (#150 (e))
AUDIT_YEARS: Final = 3  # calendar years on audit_log.at (#150 (d))
CLOCK_SKEW: Final = timedelta(minutes=5)  # #150 (j)
FUTURE_SLACK: Final = timedelta(days=1)  # #150 (j)

# One transaction per chunk (#150 (g)).
SCAN_CHUNK: Final = 100
JOB_CHUNK: Final = 1_000
ROW_CHUNK: Final = 10_000
AUDIT_CHUNK: Final = 10_000


@dataclass(frozen=True)
class Cutoffs:
    """Rows strictly older than these instants (UTC) are past retention."""

    scans: datetime
    snapshots: datetime
    requests: datetime
    tokens: datetime
    audit: datetime
    inventory_jobs: datetime


def _aware(moment: datetime, name: str) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return moment.astimezone(UTC)


def minus_years(now: datetime, years: int) -> datetime:
    """now minus whole calendar years, in UTC; Feb 29 becomes Feb 28 when the
    target year has none (2028-02-29 - 3 years = 2025-02-28)."""
    if years < 0:
        raise ValueError("years must not be negative")
    moment = _aware(now, "now")
    year = moment.year - years
    try:
        return moment.replace(year=year)
    except ValueError:  # Feb 29 in a year without one
        return moment.replace(year=year, day=28)


def cutoffs(now: datetime) -> Cutoffs:
    """The six cutoffs for the manager's instant now (#150 (a)–(e))."""
    moment = _aware(now, "now")
    return Cutoffs(
        scans=moment - SCAN_AGE,
        snapshots=moment - SNAPSHOT_AGE,
        requests=moment - REQUEST_AGE,
        tokens=moment - TOKEN_AGE,
        audit=minus_years(moment, AUDIT_YEARS),
        inventory_jobs=moment - INVENTORY_JOB_AGE,
    )


def audit_prefix(
    rows: Sequence[tuple[int, datetime]],
    cutoff: datetime,
    shipped: int | None,
    limit: int,
) -> int | None:
    """The last id of the deletable prefix of the audit chain (#150 (d)).

    rows are the oldest entries as (audit_id, at), in ascending id order. The
    walk takes at most limit of them, stops at the first entry that is not
    older than cutoff (an older entry after a newer one stays, so the chain
    keeps no hole) and at the first id above shipped (an entry not yet queued
    for the sink stays). Returns the last id walked, which is always a stored
    id; None when nothing qualifies or nothing has been shipped yet.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    bound = _aware(cutoff, "cutoff")
    if shipped is None:
        return None
    last: int | None = None
    for audit_id, at in rows[:limit]:
        if last is not None and audit_id <= last:
            raise ValueError("rows must be in ascending audit_id order")
        if audit_id > shipped or _aware(at, "at") >= bound:
            break
        last = audit_id
    return last


def clock_doubt(manager_now: datetime, db_now: datetime) -> bool:
    """True when the two clocks differ by more than CLOCK_SKEW (#150 (j)):
    the run then deletes nothing."""
    gap = _aware(manager_now, "manager_now") - _aware(db_now, "db_now")
    return abs(gap) > CLOCK_SKEW


def future_rows(newest: datetime | None, now: datetime) -> bool:
    """True when a table's newest row is dated more than FUTURE_SLACK after
    now (#150 (j)): that step is skipped. An empty table (None) is not."""
    moment = _aware(now, "now")
    if newest is None:
        return False
    return _aware(newest, "newest") > moment + FUTURE_SLACK
