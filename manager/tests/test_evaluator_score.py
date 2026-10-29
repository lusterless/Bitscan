"""TP-M8-07: host score and the effective-verdict rule (TASK-181; REQ-196,
REQ-197 (1), (2)).

TS §4.5 L602 and #120: score = passed / (passed + failed), unrounded, None
when passed + failed is 0; ERROR and Not run never enter it. TS §4.5 L601 and
#119: the effective verdict is the `scan_result_reeval` row with the highest
`reeval_id` for that job and plugin, else the original; the original stays
beside it. CHK-M8-120 to -124, -134.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.evaluator.score import (
    Effective,
    HostScore,
    ReevalRow,
    effective,
    host_score,
)

JOB = uuid.UUID(int=1)
OTHER_JOB = uuid.UUID(int=2)
PLUGIN = uuid.UUID(int=10)
OTHER_PLUGIN = uuid.UUID(int=11)
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


# CHK-M8-120: REQ-196 (1)
def test_req196_rows() -> None:
    s = host_score(3, 1, 5, 7)
    assert s == HostScore(passed=3, failed=1, errors=5, not_run=7, score=0.75)
    assert host_score(0, 0, 4, 2).score is None
    zero = host_score(0, 3, 0, 0).score
    assert zero is not None and zero == 0.0
    assert host_score(1, 0, 0, 0).score == 1.0
    assert host_score(1, 2, 0, 0).score == 1 / 3
    assert host_score(0, 0, 0, 0).score is None


def test_counts_are_carried() -> None:
    s = host_score(2, 1, 9, 4)
    assert (s.passed, s.failed, s.errors, s.not_run) == (2, 1, 9, 4)
    assert s.score == 2 / 3


def test_score_is_unrounded_float() -> None:
    s = host_score(2, 1, 0, 0).score
    assert isinstance(s, float)
    assert s == 2 / 3  # not 0.67, not 66.7


# CHK-M8-121: REQ-196 (2)
@pytest.mark.parametrize(
    "counts", [(-1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, -1)]
)
def test_negative_count_raises(counts: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        host_score(*counts)


def test_bool_counts_are_refused() -> None:
    with pytest.raises((ValueError, TypeError)):
        host_score(True, 0, 0, 0)


# CHK-M8-134: REQ-196 (3) property
N = st.integers(min_value=0, max_value=10**9)


@settings(max_examples=3_000, deadline=None)
@given(N, N, N, N, N, N)
def test_score_bounds_and_independence(
    p: int, f: int, e: int, n: int, e2: int, n2: int
) -> None:
    s = host_score(p, f, e, n)
    if p + f == 0:
        assert s.score is None
    else:
        assert s.score is not None
        assert 0.0 <= s.score <= 1.0
        assert s.score == p / (p + f)
    assert host_score(p, f, e2, n2).score == s.score


# CHK-M8-122: REQ-197 (1)
def _row(
    rid: int,
    code: int,
    detail: str | None,
    *,
    job: uuid.UUID = JOB,
    plugin: uuid.UUID = PLUGIN,
    at: datetime = T0,
    version: int = 3,
) -> ReevalRow:
    return ReevalRow(
        reeval_id=rid,
        job_id=job,
        plugin_uuid=plugin,
        policy_version=version,
        eval_code=code,
        eval_detail=detail,
        reevaluated_by=7,
        reevaluated_at=at,
    )


def test_no_reeval_gives_the_original() -> None:
    e = effective(JOB, PLUGIN, 1, None, [])
    assert e == Effective(
        job_id=JOB,
        plugin_uuid=PLUGIN,
        original_code=1,
        original_detail=None,
        code=1,
        detail=None,
        reeval_id=None,
        policy_version=None,
        reevaluated_by=None,
        reevaluated_at=None,
    )
    e2 = effective(JOB, PLUGIN, 2, "timed out", iter(()))
    assert (e2.code, e2.detail) == (2, "timed out")


ROWS_579 = [
    _row(5, 1, None, at=T0 + timedelta(hours=3), version=5),
    _row(9, 2, "cannot evaluate", at=T0, version=9),
    _row(7, 0, None, at=T0 + timedelta(hours=9), version=7),
]


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_highest_reeval_id_wins_whatever_order_or_time(order: tuple[int, ...]) -> None:
    rows = [ROWS_579[i] for i in order]
    e = effective(JOB, PLUGIN, 0, None, rows)
    assert e.reeval_id == 9
    assert (e.code, e.detail) == (2, "cannot evaluate")
    assert e.policy_version == 9
    assert e.reevaluated_by == 7
    assert e.reevaluated_at == T0
    assert (e.original_code, e.original_detail) == (0, None)


def test_equal_timestamps_still_pick_the_highest_id() -> None:
    rows = [_row(3, 0, None), _row(4, 1, None), _row(2, 2, "timed out")]
    e = effective(JOB, PLUGIN, 2, "oversize", rows)
    assert (e.reeval_id, e.code, e.detail) == (4, 1, None)
    assert (e.original_code, e.original_detail) == (2, "oversize")


def test_accepts_a_one_shot_iterator() -> None:
    e = effective(JOB, PLUGIN, 0, None, iter(ROWS_579))
    assert e.reeval_id == 9


# CHK-M8-123: REQ-197 (2)
def test_rows_for_another_plugin_or_job_are_ignored() -> None:
    rows = [
        _row(100, 0, None, plugin=OTHER_PLUGIN),
        _row(101, 0, None, job=OTHER_JOB),
        _row(102, 0, None, job=OTHER_JOB, plugin=OTHER_PLUGIN),
    ]
    e = effective(JOB, PLUGIN, 1, None, rows)
    assert (e.code, e.detail, e.reeval_id) == (1, None, None)
    e = effective(JOB, PLUGIN, 1, None, [*rows, _row(4, 2, "timed out")])
    assert (e.code, e.detail, e.reeval_id) == (2, "timed out", 4)


# CHK-M8-124
def test_error_reevaluated_to_pass_and_pass_to_error() -> None:
    e = effective(JOB, PLUGIN, 2, "stdout not numeric", [_row(1, 0, None)])
    assert (e.code, e.detail) == (0, None)
    assert (e.original_code, e.original_detail) == (2, "stdout not numeric")
    e = effective(JOB, PLUGIN, 0, None, [_row(1, 2, "cannot evaluate")])
    assert (e.code, e.detail) == (2, "cannot evaluate")
    assert (e.original_code, e.original_detail) == (0, None)


@settings(max_examples=2_000, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10_000),
            st.sampled_from([JOB, OTHER_JOB]),
            st.sampled_from([PLUGIN, OTHER_PLUGIN]),
            st.sampled_from([0, 1, 2]),
            st.integers(min_value=-10_000, max_value=10_000),
        ),
        max_size=12,
        unique_by=lambda t: t[0],
    ),
    st.sampled_from([0, 1, 2]),
)
def test_effective_matches_a_max_id_oracle(
    rows: list[tuple[int, uuid.UUID, uuid.UUID, int, int]], original: int
) -> None:
    built = [
        _row(
            rid,
            code,
            None if code < 2 else "cannot evaluate",
            job=job,
            plugin=plugin,
            at=T0 + timedelta(seconds=offset),
        )
        for rid, job, plugin, code, offset in rows
    ]
    mine = [r for r in built if r.job_id == JOB and r.plugin_uuid == PLUGIN]
    e = effective(JOB, PLUGIN, original, None, built)
    if not mine:
        assert (e.code, e.reeval_id) == (original, None)
    else:
        best = max(mine, key=lambda r: r.reeval_id)
        assert (e.code, e.detail, e.reeval_id) == (
            best.eval_code,
            best.eval_detail,
            best.reeval_id,
        )
    assert e.original_code == original
