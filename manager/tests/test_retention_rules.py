"""TASK-236 TEST: retention rules, pure (TP-M11-05; CHK-M11-040 to -048, -080).

Expected values: TS §5.3 L1049 (400 d scans, 180 d snapshots, 90 d decided
requests and expired tokens, 3 years audit, 30 d inventory jobs), L1053
(checkpoint, so only a prefix of the chain can go); #150 (a)-(e), (g), (j)
as approved 2026-11-08; REQ-274 (1)-(4), REQ-278 (the 5-minute and 1-day
guards: "more than", so the boundary itself is not doubt).
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.retention import rules

US = timedelta(microseconds=1)
NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)
PLUS8 = timezone(timedelta(hours=8))
MINUS5 = timezone(timedelta(hours=-5))


# ------------------------------------------------------------ CHK-M11-040


def test_constants_are_the_spec_values() -> None:
    assert rules.SCAN_AGE == timedelta(days=400)
    assert rules.SNAPSHOT_AGE == timedelta(days=180)
    assert rules.REQUEST_AGE == timedelta(days=90)
    assert rules.TOKEN_AGE == timedelta(days=90)
    assert rules.INVENTORY_JOB_AGE == timedelta(days=30)
    assert rules.AUDIT_YEARS == 3
    assert rules.CLOCK_SKEW == timedelta(minutes=5)
    assert rules.FUTURE_SLACK == timedelta(days=1)
    # Scans 2, not #150 (g)'s 100: user decision 2026-11-11, TASK-261 r1 (the
    # lead, from CHK-M11-387's fleet measurements); PD-51.
    assert (rules.SCAN_CHUNK, rules.JOB_CHUNK, rules.ROW_CHUNK, rules.AUDIT_CHUNK) == (
        2,
        1_000,
        10_000,
        10_000,
    )


# ------------------------------------------------------------ CHK-M11-041

AGES = {
    "scans": timedelta(days=400),
    "snapshots": timedelta(days=180),
    "requests": timedelta(days=90),
    "tokens": timedelta(days=90),
    "inventory_jobs": timedelta(days=30),
}


@pytest.mark.parametrize(
    "now",
    [
        NOW,
        datetime(2027, 3, 28, 1, 30, tzinfo=UTC),  # a London DST change day
        datetime(2026, 11, 8, 20, 0, tzinfo=PLUS8),  # aware, not UTC
        datetime(2028, 2, 29, 23, 59, 59, 999_999, tzinfo=MINUS5),
    ],
)
def test_each_cutoff_is_now_minus_its_age(now: datetime) -> None:
    """REQ-274 (1) at rule level: the cutoff of each rule is exactly now − age,
    so a row stamped at the cutoff is not older than it (kept by the strict
    `<` of TASK-237) and one 1 µs older is."""
    got = rules.cutoffs(now)
    assert set(vars(got)) >= set(AGES) | {"audit"}
    for name, age in AGES.items():
        cut = getattr(got, name)
        assert cut.tzinfo is not None and cut.utcoffset() == timedelta(0), name
        assert cut == now - age, name
        at_cutoff, older = now - age, now - age - US
        assert not at_cutoff < cut and older < cut, name


# ------------------------------------------------------------ CHK-M11-042


@pytest.mark.parametrize(
    ("now", "want"),
    [
        (datetime(2029, 3, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
        (datetime(2028, 2, 29, tzinfo=UTC), datetime(2025, 2, 28, tzinfo=UTC)),
        (datetime(2028, 2, 29, 12, tzinfo=UTC), datetime(2025, 2, 28, 12, tzinfo=UTC)),
        (datetime(2028, 2, 28, tzinfo=UTC), datetime(2025, 2, 28, tzinfo=UTC)),
        (datetime(2028, 3, 1, tzinfo=UTC), datetime(2025, 3, 1, tzinfo=UTC)),
        (
            datetime(2027, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC),
            datetime(2024, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC),
        ),
        (datetime(2026, 11, 8, 12, tzinfo=UTC), datetime(2023, 11, 8, 12, tzinfo=UTC)),
    ],
)
def test_audit_cutoff_is_three_calendar_years(now: datetime, want: datetime) -> None:
    """REQ-274 (3), #150 (d): calendar years, Feb 29 → Feb 28."""
    assert rules.cutoffs(now).audit == want
    assert rules.minus_years(now, 3) == want


def test_calendar_years_are_taken_on_the_utc_instant() -> None:
    """An aware non-UTC `now` gives the same instant as its UTC form, so the
    cutoff does not depend on the caller's zone."""
    local = datetime(2028, 2, 29, 5, 0, tzinfo=PLUS8)  # = 2028-02-28T21:00Z
    utc = local.astimezone(UTC)
    assert rules.cutoffs(local).audit == rules.cutoffs(utc).audit
    assert rules.cutoffs(local).audit == datetime(2025, 2, 28, 21, 0, tzinfo=UTC)
    assert rules.minus_years(local, 3) == datetime(2025, 2, 28, 21, 0, tzinfo=UTC)


def test_audit_cutoff_is_not_a_fixed_number_of_days() -> None:
    """Planted 365-day (or 1,095-day) arithmetic is red: across a leap year
    three calendar years are 1,096 days."""
    now = datetime(2029, 3, 1, tzinfo=UTC)
    assert now - rules.cutoffs(now).audit == timedelta(days=1096)
    now = datetime(2027, 3, 1, tzinfo=UTC)  # 2024-03-01 .. 2027-03-01: no Feb 29
    assert now - rules.cutoffs(now).audit == timedelta(days=1095)


# ------------------------------------------------------------ CHK-M11-043

NAIVE = datetime(2026, 11, 8, 12, 0, 0)


def test_a_naive_datetime_raises_value_error() -> None:
    """REQ-274 (4); the message names no value."""
    calls: list[Callable[[], object]] = [
        lambda: rules.cutoffs(NAIVE),
        lambda: rules.minus_years(NAIVE, 3),
        lambda: rules.clock_doubt(NAIVE, NOW),
        lambda: rules.clock_doubt(NOW, NAIVE),
        lambda: rules.future_rows(NAIVE, NOW),
        lambda: rules.future_rows(NOW, NAIVE),
        lambda: rules.audit_prefix([(1, NAIVE)], NOW, 5, 10),
        lambda: rules.audit_prefix([(1, NOW)], NAIVE, 5, 10),
    ]
    for i, call in enumerate(calls):
        with pytest.raises(ValueError) as exc:
            call()
        assert "2026" not in str(exc.value), i


# ------------------------------------------------------------ CHK-M11-044, -045

CUT = datetime(2023, 11, 8, tzinfo=UTC)
OLD = CUT - timedelta(days=10)
NEW = CUT + timedelta(days=10)


@pytest.mark.parametrize(
    ("rows", "shipped", "limit", "want"),
    [
        ([(1, OLD), (2, OLD), (3, NEW), (4, OLD)], 10, 100, 2),  # REQ-274 (2)
        ([(1, NEW), (2, NEW), (3, NEW), (4, NEW)], 10, 100, None),
        ([(1, OLD), (2, OLD), (3, OLD), (4, OLD)], 4, 100, 4),
        ([(1, OLD), (2, OLD), (3, OLD), (4, OLD)], 99, 100, 4),
        ([(1, OLD), (5, OLD), (9, OLD)], 10, 100, 9),  # gaps allowed
        ([(1, OLD), (2, OLD), (3, NEW), (4, OLD)], 1, 100, 1),  # cursor caps
        ([(1, OLD), (2, OLD)], None, 100, None),  # no cursor yet
        ([(5, OLD), (8, OLD)], 7, 100, 5),  # cap is a stored id, never 7
        ([(5, OLD), (8, OLD)], 4, 100, None),  # cursor below the first id
        ([], 10, 100, None),
        ([(1, OLD), (2, OLD), (3, OLD), (4, OLD)], 10, 2, 2),  # at most limit
        ([(1, OLD), (2, OLD), (3, OLD), (4, OLD)], 10, 1, 1),
        ([(1, NEW), (2, OLD)], 10, 100, None),  # first entry new: nothing
    ],
)
def test_audit_prefix(
    rows: list[tuple[int, datetime]], shipped: int | None, limit: int, want: int | None
) -> None:
    assert rules.audit_prefix(rows, CUT, shipped, limit) == want


def test_audit_prefix_boundary_is_strict() -> None:
    """An entry exactly at the cutoff is not expired and stops the prefix;
    1 µs older continues it (REQ-274 (1) for the audit rule)."""
    assert rules.audit_prefix([(1, OLD), (2, CUT), (3, OLD)], CUT, 10, 100) == 1
    assert rules.audit_prefix([(1, OLD), (2, CUT - US), (3, OLD)], CUT, 10, 100) == 3
    assert rules.audit_prefix([(1, CUT)], CUT, 10, 100) is None


def test_audit_prefix_accepts_aware_non_utc_times() -> None:
    rows = [(1, (CUT - US).astimezone(PLUS8)), (2, CUT.astimezone(MINUS5))]
    assert rules.audit_prefix(rows, CUT, 10, 100) == 1


def test_guards_fail_closed() -> None:
    """Implementer additions (TASK-236 IMPL report), not spec values: a call
    the service never makes raises instead of returning a prefix."""
    with pytest.raises(ValueError):
        rules.audit_prefix([(1, OLD)], CUT, 10, 0)
    with pytest.raises(ValueError):
        rules.audit_prefix([(2, OLD), (1, OLD)], CUT, 10, 10)
    with pytest.raises(ValueError):
        rules.minus_years(NOW, -1)


# ------------------------------------------------------------ CHK-M11-046


@pytest.mark.parametrize(
    ("gap", "doubt"),
    [
        (timedelta(0), False),
        (timedelta(minutes=4, seconds=59), False),
        (timedelta(minutes=5), False),
        (timedelta(minutes=5) + US, True),
        (timedelta(minutes=5, seconds=1), True),
        (timedelta(hours=1), True),
        (timedelta(days=365 * 10), True),
    ],
)
def test_clock_doubt_is_more_than_five_minutes_either_way(
    gap: timedelta, doubt: bool
) -> None:
    """#150 (j), TASK-236 acceptance: true at 5 min 1 s, false at 5 min;
    the manager ahead of the database and behind it alike."""
    assert rules.clock_doubt(NOW + gap, NOW) is doubt
    assert rules.clock_doubt(NOW - gap, NOW) is doubt
    assert (
        rules.clock_doubt((NOW + gap).astimezone(PLUS8), NOW.astimezone(MINUS5))
        is doubt
    )


# ------------------------------------------------------------ CHK-M11-047


@pytest.mark.parametrize(
    ("newest", "future"),
    [
        (None, False),
        (NOW - timedelta(days=500), False),
        (NOW, False),
        (NOW + timedelta(hours=23), False),
        (NOW + timedelta(days=1), False),
        (NOW + timedelta(days=1) + US, True),
        (NOW + timedelta(days=2), True),
        (NOW + timedelta(days=3650), True),
    ],
)
def test_future_rows_is_more_than_one_day_ahead(
    newest: datetime | None, future: bool
) -> None:
    """#150 (j), REQ-278 (1): a step is skipped when its table holds a row
    dated more than 1 day after now."""
    assert rules.future_rows(newest, NOW) is future


# ------------------------------------------------------------ CHK-M11-048

ALLOWED_IMPORTS = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "datetime",
    "typing",
}


def test_rules_are_pure() -> None:
    """No I/O, no clock read, no logging, no `re` (RE2 rule), no database."""
    tree = ast.parse(inspect.getsource(rules))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names = {node.module or ""}
        else:
            names = set()
        assert names <= ALLOWED_IMPORTS, names
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "time", "monotonic"}, (
                node.attr
            )
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "print", "logging", "logger"}, node.id


def test_package_exports_nothing_with_side_effects() -> None:
    import bitscan_manager.services.retention as pkg

    tree = ast.parse(inspect.getsource(pkg))
    assert all(isinstance(n, ast.Expr) for n in tree.body), "only a docstring"


# ------------------------------------------------------------ CHK-M11-080


@settings(max_examples=600, deadline=None)
@given(
    lead=st.integers(min_value=0, max_value=40),
    tail=st.lists(st.booleans(), max_size=20),
    gaps=st.lists(st.integers(min_value=1, max_value=5), min_size=60, max_size=60),
    cursor=st.one_of(st.none(), st.integers(min_value=0, max_value=300)),
    limit=st.integers(min_value=1, max_value=60),
)
def test_audit_prefix_property(
    lead: int, tail: list[bool], gaps: list[int], cursor: int | None, limit: int
) -> None:
    """For any id-ordered entries (with gaps; a leading run of old entries
    of any length, then any mix), cutoff, cursor and limit: the answer is the
    largest stored id N among the first `limit` entries such that every entry
    up to N is older than the cutoff and N <= the cursor; None when there is
    no such id or no cursor."""
    olds = [True] * lead + tail
    ids, last = [], 0
    for g in gaps[: len(olds)]:
        last += g
        ids.append(last)
    rows = [(i, OLD if o else NEW) for i, o in zip(ids, olds, strict=True)]
    want: int | None = None
    if cursor is not None:
        for audit_id, at in rows[:limit]:
            if not at < CUT or audit_id > cursor:
                break
            want = audit_id
    got = rules.audit_prefix(rows, CUT, cursor, limit)
    assert got == want
    if got is not None:
        assert got in ids and cursor is not None and got <= cursor
