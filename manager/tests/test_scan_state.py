"""TP-M9-03: scan state derivation (TASK-187; REQ-207).

TS §4.4 L579-L580; open questions #22, #127 (d), (e); #3. The scan is
derived per unit (one host's original job and its retry). Expected values
come from #127 (d), not from the code. CHK-M9-015 to -021.
"""

from __future__ import annotations

import itertools
from dataclasses import FrozenInstanceError

import pytest

from bitscan_manager.services.jobs.scan_state import Unit, derive

OPEN = frozenset({"queued", "dispatched", "running"})
SCAN_STATES = frozenset(
    {"queued", "running", "completed", "partial", "failed", "cancelled"}
)


def unit(*job_states: str, plugins: int = 3, results: int = 0) -> Unit:
    """The #127 (d) facts of one unit: `job_states` are the original's state
    and, if given, its retry's; `results` = plugins of the original's payload
    with a result in the unit."""
    assert 1 <= len(job_states) <= 2
    assert 0 <= results <= plugins
    return Unit(
        open=any(s in OPEN for s in job_states),
        complete=results == plugins,
        has_results=results > 0,
        any_cancelled="cancelled" in job_states,
        all_queued=all(s == "queued" for s in job_states),
    )


# --- CHK-M9-015: REQ-207 (1) table ------------------------------------------


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        # every job queued
        ([unit("queued"), unit("queued")], ("queued", False)),
        # one job dispatched (#22)
        ([unit("dispatched"), unit("queued")], ("running", False)),
        # one expired and one queued
        ([unit("expired"), unit("queued")], ("running", False)),
        # every unit complete
        (
            [unit("completed", results=3), unit("completed", results=3)],
            ("completed", True),
        ),
        # an original partial whose retry completed the missing plugins
        (
            [unit("partial", "completed", results=3), unit("completed", results=3)],
            ("completed", True),
        ),
        # one unit complete and one failed without results
        ([unit("completed", results=3), unit("failed")], ("partial", True)),
        # no results and one job cancelled
        ([unit("cancelled"), unit("expired")], ("cancelled", True)),
        # no results, nothing cancelled (expired, failed)
        ([unit("expired"), unit("failed")], ("failed", True)),
        # cancelled after some results -> partial (CHK-M9-360)
        ([unit("cancelled", results=1), unit("cancelled")], ("partial", True)),
        # cancelled when every unit was complete -> completed
        (
            [unit("completed", results=3), unit("cancelled", results=3)],
            ("completed", True),
        ),
    ],
)
def test_req_207_table(units: list[Unit], expected: tuple[str, bool]) -> None:
    assert derive(units) == expected


# --- CHK-M9-016: the unit rule (CHK-M9-361) ---------------------------------


def test_partial_original_with_a_completing_retry_is_one_complete_unit() -> None:
    # Per job, the original "partial" would make the scan partial.
    assert derive([unit("partial", "completed", results=5, plugins=5)]) == (
        "completed",
        True,
    )


def test_failed_original_with_a_queued_retry_is_open() -> None:
    assert derive([unit("failed", "queued")]) == ("running", False)
    assert derive([unit("partial", "running", results=1)]) == ("running", False)


def test_retry_that_still_misses_plugins_gives_partial() -> None:
    assert derive([unit("partial", "partial", results=4, plugins=5)]) == (
        "partial",
        True,
    )
    assert derive([unit("failed", "failed")]) == ("failed", True)


# --- CHK-M9-017: queued vs running (#22) ------------------------------------


def test_queued_only_when_every_job_is_queued() -> None:
    assert derive([unit("queued")]) == ("queued", False)
    assert derive([unit("queued"), unit("queued"), unit("queued")]) == ("queued", False)
    # another unit already closed
    assert derive([unit("queued"), unit("expired")]) == ("running", False)
    assert derive([unit("queued"), unit("completed", results=3)]) == ("running", False)
    # the original ended and its retry is queued: not every job is queued
    assert derive([unit("failed", "queued")]) == ("running", False)
    assert derive([unit("running")]) == ("running", False)


# --- CHK-M9-018: cancelled vs failed (#127 (d)) -----------------------------


def test_cancelled_failed_overlap() -> None:
    assert derive([unit("cancelled"), unit("expired")]) == ("cancelled", True)
    assert derive([unit("cancelled")]) == ("cancelled", True)
    assert derive([unit("failed", "cancelled")]) == ("cancelled", True)
    assert derive([unit("expired"), unit("failed")]) == ("failed", True)
    # results anywhere beat cancelled
    assert derive([unit("cancelled"), unit("failed", results=1)]) == ("partial", True)


# --- CHK-M9-019: empty and container types ----------------------------------


def test_empty_unit_list_raises() -> None:
    with pytest.raises(ValueError):
        derive([])
    with pytest.raises(ValueError):
        derive(())


def test_tuple_and_list_agree() -> None:
    units = [unit("completed", results=3), unit("failed")]
    assert derive(units) == derive(tuple(units))


# --- CHK-M9-020: never dispatched or expired (CHK-M9-362) -------------------

ALL_FACTS = [
    Unit(open=o, complete=c, has_results=h, any_cancelled=a, all_queued=q)
    for o, c, h, a, q in itertools.product((False, True), repeat=5)
]


@pytest.mark.parametrize("u", ALL_FACTS)
def test_one_unit_any_facts(u: Unit) -> None:
    state, finished = derive([u])
    assert state in SCAN_STATES
    assert finished is (not u.open)


def test_two_units_any_facts() -> None:
    for a, b in itertools.product(ALL_FACTS, repeat=2):
        state, finished = derive([a, b])
        assert state in SCAN_STATES, (a, b)
        assert state not in {"dispatched", "expired"}
        assert finished is (not (a.open or b.open)), (a, b)


def test_closed_scan_states_follow_the_order_of_the_rule() -> None:
    """Exhaustive over consistent closed units: completed > partial >
    cancelled > failed, exactly as #127 (d) orders them."""
    closed = [
        u
        for u in ALL_FACTS
        if not u.open and not u.all_queued and (u.has_results or not u.complete)
    ]
    for a, b in itertools.product(closed, repeat=2):
        units = [a, b]
        if all(u.complete for u in units):
            want = "completed"
        elif any(u.has_results for u in units):
            want = "partial"
        elif any(u.any_cancelled for u in units):
            want = "cancelled"
        else:
            want = "failed"
        assert derive(units) == (want, True), units


# --- CHK-M9-021: frozen, no mutation ----------------------------------------


def test_unit_is_frozen_and_input_is_not_mutated() -> None:
    u = unit("queued")
    with pytest.raises(FrozenInstanceError):
        u.open = False  # type: ignore[misc]
    units = (unit("completed", results=3), unit("failed"))
    before = tuple(units)
    derive(units)
    assert units == before
