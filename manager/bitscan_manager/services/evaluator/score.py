"""Host compliance score and the effective-verdict rule (TS §4.5 L601–L602,
§4.4 L583; #119, #120).

- Score (#120): passed ÷ (passed + failed), unrounded, in [0, 1]; None when
  passed + failed is 0 (shown as "n/a" by M11). ERROR and Not run never enter
  the ratio; the error count is carried beside it.
- Effective verdict (#119): the scan_result_reeval row with the highest
  reeval_id for the result's job and plugin, else the original verdict.
  `repositories/results.py` is the SQL form of this rule; the two must agree.

Pure: no I/O, no logging, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class HostScore:
    passed: int
    failed: int
    errors: int
    not_run: int
    score: float | None


def host_score(passed: int, failed: int, errors: int, not_run: int) -> HostScore:
    """Raises ValueError for a count that is negative or not an int."""
    for count in (passed, failed, errors, not_run):
        # `type(...) is int` also refuses True and False.
        if type(count) is not int or count < 0:
            raise ValueError("counts must be non-negative integers")
    rated = passed + failed
    score = None if rated == 0 else passed / rated
    return HostScore(passed, failed, errors, not_run, score)


@dataclass(frozen=True, slots=True)
class ReevalRow:
    """One scan_result_reeval row."""

    reeval_id: int
    job_id: UUID
    plugin_uuid: UUID
    policy_version: int
    eval_code: int
    eval_detail: str | None
    reevaluated_by: int
    reevaluated_at: datetime


@dataclass(frozen=True, slots=True)
class Effective:
    """A result's original verdict and the one shown (`result` beside
    `original_result`, M11), with the latest row's provenance or None."""

    job_id: UUID
    plugin_uuid: UUID
    original_code: int
    original_detail: str | None
    code: int
    detail: str | None
    reeval_id: int | None
    policy_version: int | None
    reevaluated_by: int | None
    reevaluated_at: datetime | None


def effective(
    job_id: UUID,
    plugin_uuid: UUID,
    original_code: int,
    original_detail: str | None,
    reevals: Iterable[ReevalRow],
) -> Effective:
    """The verdict shown for one result. Rows for another job or plugin are
    ignored; among the rest the highest reeval_id wins, whatever the order of
    `reevals` or their reevaluated_at."""
    latest: ReevalRow | None = None
    for row in reevals:
        if row.job_id != job_id or row.plugin_uuid != plugin_uuid:
            continue
        if latest is None or row.reeval_id > latest.reeval_id:
            latest = row
    if latest is None:
        return Effective(
            job_id,
            plugin_uuid,
            original_code,
            original_detail,
            original_code,
            original_detail,
            None,
            None,
            None,
            None,
        )
    return Effective(
        job_id,
        plugin_uuid,
        original_code,
        original_detail,
        latest.eval_code,
        latest.eval_detail,
        latest.reeval_id,
        latest.policy_version,
        latest.reevaluated_by,
        latest.reevaluated_at,
    )
