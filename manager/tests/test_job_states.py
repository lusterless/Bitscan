"""TP-M9-02: job state rules (TASK-186; REQ-206, REQ-217 at rule level).

TS §4.4 L562-L582, §3.3 L222, §6.1 L1071; open questions #124 (a), #127
(a)-(c). Every expected value below is written from the spec and the approved
answers (tests/m9/test-plan.md "Expected values"), not from the code.
CHK-M9-001 to -014.
"""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args

import pytest

import bitscan_manager
from bitscan_manager.services.jobs import states

BM = Path(bitscan_manager.__file__).resolve().parent
MANAGER = BM.parent

STATES = (
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "expired",
)

# REQ-206 statement: the only allowed transitions.
ALLOWED = frozenset(
    {
        ("queued", "dispatched"),
        ("queued", "expired"),
        ("queued", "cancelled"),
        ("dispatched", "running"),
        ("dispatched", "failed"),
        ("dispatched", "cancelled"),
        ("running", "completed"),
        ("running", "partial"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("failed", "completed"),
        ("failed", "partial"),
        ("partial", "completed"),
        ("partial", "partial"),
    }
)

D = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
US = timedelta(microseconds=1)


def allowed(a: str, b: str) -> bool:
    """The module's own transition check (bound to its public interface)."""
    return states.allowed(a, b)


# --- CHK-M9-001 / -012: constants ------------------------------------------


def test_final_and_accepting_sets() -> None:
    assert frozenset({"completed", "expired", "cancelled"}) == states.FINAL
    assert isinstance(states.FINAL, frozenset)
    assert (
        frozenset({"dispatched", "running", "failed", "partial", "completed"})
        == states.ACCEPTING
    )
    assert isinstance(states.ACCEPTING, frozenset)


def test_job_state_literal_is_the_eight_states() -> None:
    assert set(get_args(states.JobState)) == set(STATES)
    assert len(get_args(states.JobState)) == 8


def test_window_and_slack_constants() -> None:
    assert timedelta(days=7) == states.LATE_WINDOW
    assert timedelta(minutes=10) == states.DEADLINE_SLACK
    # TS §4.4 L575 "fails 24 h after dispatch"; the settings range of
    # max_parallel_plugins (REQ-206 (2): outside 1-8 raises).
    assert timedelta(hours=24) == states.NEVER_STARTED_AFTER
    assert (states.MAX_PARALLEL_MIN, states.MAX_PARALLEL_MAX) == (1, 8)


def test_transitions_mapping_is_the_table_and_read_only() -> None:
    pairs = {(a, b) for a, targets in states.TRANSITIONS.items() for b in targets}
    assert pairs == ALLOWED
    assert set(states.TRANSITIONS) == set(STATES)
    with pytest.raises(TypeError):
        states.TRANSITIONS["completed"] = frozenset({"running"})  # type: ignore[index]


# --- CHK-M9-002: transition table ------------------------------------------


@pytest.mark.parametrize(("a", "b"), [(a, b) for a in STATES for b in STATES])
def test_transition_table_is_exactly_req_206(a: str, b: str) -> None:
    assert allowed(a, b) is ((a, b) in ALLOWED)


def test_no_transition_leaves_a_final_state() -> None:
    for a in ("completed", "expired", "cancelled"):
        assert not any(allowed(a, b) for b in STATES)


def test_unknown_state_names_are_refused() -> None:
    for a, b in [("queued", "QUEUED"), ("bogus", "running"), ("running", ""), ("", "")]:
        assert allowed(a, b) is False


# --- CHK-M9-003: (state x event) table --------------------------------------

REFUSED = "refused"
NA = "n/a"

# Batch events: (stored, all_have_results, final).
BATCHES: dict[str, tuple[int, bool, bool]] = {
    "batch_empty": (0, False, False),
    "batch_empty_final": (0, False, True),
    "batch_some": (1, False, False),
    "batch_some_final": (1, False, True),
    "batch_all": (1, True, False),
    "batch_all_final": (1, True, True),
}
# Deadline events: (any_result, all_have_results).
DEADLINES: dict[str, tuple[bool, bool]] = {
    "deadline_none": (False, False),
    "deadline_some": (True, False),
    "deadline_all": (True, True),
}
EVENTS = ("pull", *BATCHES, *DEADLINES, "never_started_24h", "cancel", "pickup_passed")

# Hand-written answers (#127 (a), (b); #124 (a), (d); TS §4.4 L566-L582).
# A batch answer is (state, start); "refused" = not accepted; "n/a" = the rule
# is applied by the repository's candidate filter, not by a pure function
# (deadline and never-started candidates are dispatched/running only: CHK-M9-120).
TABLE: dict[str, dict[str, Any]] = {
    "queued": {
        "pull": "dispatched",
        **dict.fromkeys(BATCHES, REFUSED),
        **dict.fromkeys(DEADLINES, REFUSED),
        "never_started_24h": REFUSED,
        "cancel": "cancelled",
        "pickup_passed": "expired",
    },
    "dispatched": {
        "pull": REFUSED,
        "batch_empty": ("running", True),
        "batch_empty_final": ("partial", True),
        "batch_some": ("running", True),
        "batch_some_final": ("partial", True),
        "batch_all": ("completed", True),
        "batch_all_final": ("completed", True),
        # A dispatched job has no results and no deadline; only "none" can occur.
        "deadline_none": "failed",
        "deadline_some": REFUSED,
        "deadline_all": REFUSED,
        "never_started_24h": "failed",
        "cancel": "cancelled",
        "pickup_passed": REFUSED,
    },
    "running": {
        "pull": REFUSED,
        "batch_empty": ("running", False),
        "batch_empty_final": ("partial", False),
        "batch_some": ("running", False),
        "batch_some_final": ("partial", False),
        "batch_all": ("completed", False),
        "batch_all_final": ("completed", False),
        "deadline_none": "failed",
        "deadline_some": "partial",
        "deadline_all": "completed",
        "never_started_24h": NA,  # started: the 24 h rule does not apply
        "cancel": "cancelled",
        "pickup_passed": REFUSED,
    },
    "completed": {
        "pull": REFUSED,
        **dict.fromkeys(BATCHES, ("completed", False)),
        **dict.fromkeys(DEADLINES, REFUSED),
        "never_started_24h": REFUSED,
        "cancel": REFUSED,
        "pickup_passed": REFUSED,
    },
    "partial": {
        "pull": REFUSED,
        "batch_empty": ("partial", False),
        "batch_empty_final": ("partial", False),
        "batch_some": ("partial", False),
        "batch_some_final": ("partial", False),
        "batch_all": ("completed", False),
        "batch_all_final": ("completed", False),
        **dict.fromkeys(DEADLINES, NA),
        "never_started_24h": REFUSED,
        "cancel": REFUSED,
        "pickup_passed": REFUSED,
    },
    "failed": {
        "pull": REFUSED,
        "batch_empty": ("failed", False),
        "batch_empty_final": ("failed", False),
        "batch_some": ("partial", False),
        "batch_some_final": ("partial", False),
        "batch_all": ("completed", False),
        "batch_all_final": ("completed", False),
        **dict.fromkeys(DEADLINES, NA),
        "never_started_24h": REFUSED,
        "cancel": REFUSED,
        "pickup_passed": REFUSED,
    },
    "cancelled": {
        "pull": REFUSED,
        **dict.fromkeys(BATCHES, REFUSED),
        **dict.fromkeys(DEADLINES, REFUSED),
        "never_started_24h": REFUSED,
        "cancel": REFUSED,
        "pickup_passed": REFUSED,
    },
    "expired": {
        "pull": REFUSED,
        **dict.fromkeys(BATCHES, REFUSED),
        **dict.fromkeys(DEADLINES, REFUSED),
        "never_started_24h": REFUSED,
        "cancel": REFUSED,
        "pickup_passed": REFUSED,
    },
}


def _apply(state: str, event: str) -> Any:
    if event == "pull":
        return "dispatched" if allowed(state, "dispatched") else REFUSED
    if event == "cancel":
        return "cancelled" if allowed(state, "cancelled") else REFUSED
    if event == "pickup_passed":
        return "expired" if allowed(state, "expired") else REFUSED
    if event == "never_started_24h":
        return "failed" if allowed(state, "failed") else REFUSED
    if event in DEADLINES:
        any_result, all_have = DEADLINES[event]
        outcome = states.after_deadline(
            any_result=any_result, all_have_results=all_have
        )
        return outcome if allowed(state, outcome) else REFUSED
    stored, all_have, final = BATCHES[event]
    if not states.accepts_results("compliance", state, D, D):
        with pytest.raises(ValueError):
            states.after_batch(
                state, stored=stored, all_have_results=all_have, final=final
            )
        return REFUSED
    out = states.after_batch(
        state, stored=stored, all_have_results=all_have, final=final
    )
    # Every move a batch makes is an allowed transition (or no move at all).
    path = [state, "running", out.state] if out.start else [state, out.state]
    for a, b in zip(path, path[1:], strict=False):
        assert a == b or allowed(a, b), (state, event, out)
    return (out.state, out.start)


def test_table_covers_every_pair() -> None:
    assert set(TABLE) == set(STATES)
    for row in TABLE.values():
        assert set(row) == set(EVENTS)


PAIRS = [(s, e) for s in STATES for e in EVENTS if TABLE[s][e] != NA]


def test_na_rows_are_only_the_sweep_filtered_ones() -> None:
    # The n/a rows are applied by the sweep candidate filter (CHK-M9-120), not
    # here; left out of the parametrisation (CI runs with nothing skipped).
    na = {(s, e) for s in STATES for e in EVENTS if TABLE[s][e] == NA}
    assert na == {("running", "never_started_24h")} | {
        (s, e) for s in ("partial", "failed") for e in DEADLINES
    }


@pytest.mark.parametrize(("state", "event"), PAIRS)
def test_state_event_table(state: str, event: str) -> None:
    assert _apply(state, event) == TABLE[state][event]


# --- CHK-M9-004 to -008: batch and deadline outcomes ------------------------


def _batch(state: str, *, stored: int, all_have: bool, final: bool) -> tuple[str, bool]:
    out = states.after_batch(
        state, stored=stored, all_have_results=all_have, final=final
    )
    return out.state, out.start


def test_dispatched_batch_starts_the_job() -> None:
    assert _batch("dispatched", stored=0, all_have=False, final=False) == (
        "running",
        True,
    )
    assert _batch("dispatched", stored=3, all_have=False, final=False) == (
        "running",
        True,
    )
    assert _batch("dispatched", stored=3, all_have=False, final=True) == (
        "partial",
        True,
    )
    assert _batch("dispatched", stored=3, all_have=True, final=False) == (
        "completed",
        True,
    )
    assert _batch("dispatched", stored=3, all_have=True, final=True) == (
        "completed",
        True,
    )


def test_running_never_restarts() -> None:
    # A second start notice changes neither started_at nor deadline_at (CHK-M9-334).
    for stored in (0, 1, 50):
        for all_have in (False, True):
            for final in (False, True):
                _, start = _batch(
                    "running", stored=stored, all_have=all_have, final=final
                )
                assert start is False


def test_running_outcomes() -> None:
    # CHK-M9-337: a non-final batch with plugins missing stays running.
    assert _batch("running", stored=2, all_have=False, final=False) == (
        "running",
        False,
    )
    assert _batch("running", stored=0, all_have=False, final=False) == (
        "running",
        False,
    )
    assert _batch("running", stored=2, all_have=False, final=True) == ("partial", False)
    assert _batch("running", stored=2, all_have=True, final=False) == (
        "completed",
        False,
    )
    assert _batch("running", stored=0, all_have=True, final=True) == (
        "completed",
        False,
    )


@pytest.mark.parametrize("state", ["failed", "partial"])
def test_late_batches(state: str) -> None:
    for all_have in (False, True):
        for final in (False, True):
            assert _batch(state, stored=0, all_have=all_have, final=final) == (
                state,
                False,
            )
    assert _batch(state, stored=1, all_have=False, final=False) == ("partial", False)
    assert _batch(state, stored=1, all_have=False, final=True) == ("partial", False)
    assert _batch(state, stored=1, all_have=True, final=False) == ("completed", False)


def test_req_217_4_failed_job_late_results() -> None:
    # A failed job given a non-final batch with 1 of 3 plugins -> partial;
    # the other 2 -> completed; an empty batch on a failed job changes nothing.
    assert _batch("failed", stored=1, all_have=False, final=False) == ("partial", False)
    assert _batch("partial", stored=2, all_have=True, final=False) == (
        "completed",
        False,
    )
    assert _batch("failed", stored=0, all_have=False, final=False) == ("failed", False)


def test_completed_job_never_changes() -> None:
    # CHK-M9-338
    for stored in (0, 1):
        for all_have in (False, True):
            for final in (False, True):
                assert _batch(
                    "completed", stored=stored, all_have=all_have, final=final
                ) == (
                    "completed",
                    False,
                )


@pytest.mark.parametrize("state", ["queued", "expired", "cancelled", "bogus"])
def test_batch_on_a_non_accepting_state_raises(state: str) -> None:
    with pytest.raises(ValueError):
        states.after_batch(state, stored=0, all_have_results=False, final=False)


def test_batch_outcome_is_frozen() -> None:
    out = states.after_batch(
        "dispatched", stored=0, all_have_results=False, final=False
    )
    with pytest.raises(AttributeError):
        out.state = "completed"  # type: ignore[misc]


def test_after_deadline() -> None:
    assert states.after_deadline(any_result=False, all_have_results=False) == "failed"
    assert states.after_deadline(any_result=True, all_have_results=False) == "partial"
    assert states.after_deadline(any_result=True, all_have_results=True) == "completed"


# --- CHK-M9-009 / -010: deadline -------------------------------------------


@pytest.mark.parametrize(
    ("timeouts", "mpp", "seconds"),
    [
        ([45, 50], 2, 648),  # REQ-206 (2): sum 95, 2 parallel
        ([30], 8, 604),  # sum 30, 8 parallel
        ([600] * 5_000, 1, 3_000_600),  # sum 3,000,000, exact
        ([2, 2], 2, 602),  # sum 4 / 2 = 2
        ([5], 2, 603),  # 2.5 -> 3
        ([1], 8, 601),  # 0.125 -> 1
        ([1] * 8, 8, 601),  # 1
        ([1] * 9, 8, 602),  # 1.125 -> 2
        ([600] * 5_000, 8, 375_600),  # 3,000,000 / 8 = 375,000
        ([599, 1], 7, 686),  # 600 / 7 = 85.71 -> 86
    ],
)
def test_deadline_rows(timeouts: list[int], mpp: int, seconds: int) -> None:
    assert states.deadline_at(D, timeouts, mpp) == D + timedelta(seconds=seconds)


def test_deadline_is_exact_for_large_sums() -> None:
    got = states.deadline_at(D, [600] * 5_000, 1)
    assert got - D == timedelta(seconds=3_000_600)
    assert got.microsecond == 0


def test_deadline_keeps_the_start_microseconds_and_instant() -> None:
    start = datetime(2026, 10, 30, 12, 0, 0, 123_456, tzinfo=UTC)
    assert states.deadline_at(start, [95], 2) == start + timedelta(seconds=648)
    plus8 = start.astimezone(timezone(timedelta(hours=8)))
    assert states.deadline_at(plus8, [95], 2) == start + timedelta(seconds=648)


def test_deadline_accepts_a_tuple() -> None:
    assert states.deadline_at(D, (45, 50), 2) == D + timedelta(seconds=648)


@pytest.mark.parametrize("mpp", [0, -1, 9, 100])
def test_deadline_refuses_parallelism_out_of_range(mpp: int) -> None:
    with pytest.raises(ValueError):
        states.deadline_at(D, [30], mpp)


@pytest.mark.parametrize("mpp", [1, 8])
def test_deadline_accepts_parallelism_bounds(mpp: int) -> None:
    states.deadline_at(D, [30], mpp)


@pytest.mark.parametrize("empty", [[], ()])
def test_deadline_refuses_no_plugins(empty: list[int]) -> None:
    with pytest.raises(ValueError):
        states.deadline_at(D, empty, 2)


def test_deadline_unspecified_inputs_are_recorded(record_property: Any) -> None:
    # Not asserted (the spec is silent): a bool parallelism, a 0 or negative timeout.
    for label, args in {
        "mpp_true": ([30], True),
        "timeout_0": ([0], 2),
        "timeout_negative": ([-5], 2),
    }.items():
        try:
            got: object = states.deadline_at(D, args[0], args[1])
        except Exception as exc:  # noqa: BLE001 - recording only
            got = type(exc).__name__
        record_property(label, str(got))


# --- CHK-M9-011: acceptance window -----------------------------------------


@pytest.mark.parametrize(
    "state", ["dispatched", "running", "failed", "partial", "completed"]
)
def test_acceptance_window_boundary(state: str) -> None:
    week = timedelta(days=7)
    for now in (D, D + week - US, D + week):
        assert states.accepts_results("compliance", state, D, now) is True
    for now in (D + week + US, D + week + timedelta(seconds=1)):
        assert states.accepts_results("compliance", state, D, now) is False


@pytest.mark.parametrize("state", ["queued", "expired", "cancelled"])
def test_non_accepting_states_are_refused_at_any_time(state: str) -> None:
    for now in (D, D + timedelta(seconds=1), D + timedelta(days=1)):
        assert states.accepts_results("compliance", state, D, now) is False


@pytest.mark.parametrize("state", STATES)
def test_inventory_jobs_are_never_accepted(state: str) -> None:
    assert states.accepts_results("inventory", state, D, D) is False


def test_unknown_kind_and_missing_dispatch_are_refused() -> None:
    assert states.accepts_results("bogus", "running", D, D) is False
    assert states.accepts_results("compliance", "running", None, D) is False


def test_now_before_dispatch_is_recorded(record_property: Any) -> None:
    record_property(
        "now_before_dispatched_at",
        states.accepts_results("compliance", "running", D, D - timedelta(seconds=1)),
    )


# --- CHK-M9-013 / -014: pure-module import graph and no I/O -----------------

PURE_MODULES = {
    "bitscan_manager.services.jobs.states": BM / "services" / "jobs" / "states.py",
    "bitscan_manager.services.jobs.scan_state": BM
    / "services"
    / "jobs"
    / "scan_state.py",
    "bitscan_manager.services.jobs.targets": BM / "services" / "jobs" / "targets.py",
    "bitscan_manager.services.jobs.build": BM / "services" / "jobs" / "build.py",
    "bitscan_manager.services.jobs.intake_plan": BM
    / "services"
    / "jobs"
    / "intake_plan.py",
    "bitscan_manager.services.scheduler.cron": BM
    / "services"
    / "scheduler"
    / "cron.py",
    "bitscan_manager.api.user.idempotency": BM / "api" / "user" / "idempotency.py",
}
FORBIDDEN_PREFIXES = (
    "bitscan_manager.db",
    "bitscan_manager.repositories",
    "bitscan_manager.api",
    "bitscan_manager.app",
    "bitscan_manager.cli",
    "bitscan_manager.runtime",
    "psycopg",
    "psycopg_pool",
    "fastapi",
    "starlette",
)
FORBIDDEN_EXACT = {"re", "logging", "socket", "subprocess", "requests", "httpx"}
CLOCK_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "time_ns"}
# Package inits Python runs implicitly; services/jobs/__init__.py is M3's
# (re-exports pull.py, owned by TASK-204) and is recorded separately.
EXEMPT_INITS = {
    "bitscan_manager.services.jobs",
    "bitscan_manager.api.user",
    "bitscan_manager.api",
}


def _module_file(name: str) -> Path | None:
    rel = name.split(".")[1:]
    base = BM.joinpath(*rel) if rel else BM
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    return None


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in {path}"
            assert node.module is not None
            found.add(node.module)
            for a in node.names:
                if _module_file(
                    f"{node.module}.{a.name}"
                ) is not None and node.module.startswith("bitscan_manager"):
                    found.add(f"{node.module}.{a.name}")
    return found


def _closure(start: str) -> set[str]:
    """Every bm module reached through explicit imports (and the parent package
    inits Python runs for them, except the exempt ones), plus every
    third-party top-level name."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if not name.startswith("bitscan_manager"):
            continue
        path = _module_file(name)
        if path is None:
            continue
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            if parent not in EXEMPT_INITS and parent != "bitscan_manager":
                todo.append(parent)
        todo.extend(_imports(path))
    return seen


@pytest.mark.parametrize("name", sorted(PURE_MODULES))
def test_pure_module_import_graph(name: str) -> None:
    assert PURE_MODULES[name].exists(), name
    reached = _closure(name)
    own = _imports(PURE_MODULES[name])
    bad = sorted(
        m
        for m in reached
        if m != name
        and (m.split(".")[0] in FORBIDDEN_EXACT or m.startswith(FORBIDDEN_PREFIXES))
    )
    assert bad == [], f"{name} reaches {bad}"
    assert not (own & FORBIDDEN_EXACT), own


CLOCK_OWNERS = {"datetime", "date", "time"}


def _owner(node: ast.expr) -> str | None:
    """`datetime` for `datetime.now`, `datetime.datetime.now`, `time.time`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


@pytest.mark.parametrize("name", sorted(PURE_MODULES))
def test_pure_module_reads_no_clock_and_opens_nothing(name: str) -> None:
    """A pure module never reads the system clock; the idempotency store reads
    only the clock it is given (`self._clock.now()`)."""
    tree = ast.parse(PURE_MODULES[name].read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in CLOCK_CALLS:
                assert _owner(func.value) not in CLOCK_OWNERS, (
                    f"{name}: system clock .{func.attr}()"
                )
            if isinstance(func, ast.Name):
                assert func.id not in {"open", "print", "input", "exec", "eval"}, name
        if isinstance(node, ast.ImportFrom) and node.module in {"time", "datetime"}:
            imported = {a.name for a in node.names}
            assert not imported & {"time", "monotonic", "perf_counter", "time_ns"}, name


def test_package_init_effect_is_recorded(record_property: Any) -> None:
    """Recorded, not asserted: importing a services.jobs module also runs the
    M3 package init (pull.py). Listed for the reviewer."""
    import subprocess

    code = (
        "import sys, bitscan_manager.services.jobs.states;"
        "p = ('psycopg', 'bitscan_manager.repositories', 'bitscan_manager.db');"
        "print(sorted(m for m in sys.modules if m.startswith(p)))"
    )
    out = subprocess.run(  # noqa: S603 - our own interpreter, fixed code
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    record_property("loaded_by_package_init", out.stdout.strip())


def test_state_functions_do_no_io() -> None:
    events: list[str] = []

    def hook(event: str, _args: tuple[object, ...]) -> None:
        if event in {
            "open",
            "socket.connect",
            "socket.__new__",
            "subprocess.Popen",
            "os.system",
        }:
            events.append(event)

    sys.addaudithook(hook)
    armed = True
    try:
        for _ in range(20):
            for s in STATES:
                for t in STATES:
                    allowed(s, t)
                states.accepts_results("compliance", s, D, D)
                if s in states.ACCEPTING:
                    for stored in (0, 1):
                        for all_have in (False, True):
                            for final in (False, True):
                                states.after_batch(
                                    s,
                                    stored=stored,
                                    all_have_results=all_have,
                                    final=final,
                                )
            for a, b in ((False, False), (True, False), (True, True)):
                states.after_deadline(any_result=a, all_have_results=b)
            states.deadline_at(D, [95], 2)
        snapshot = list(events)
    finally:
        armed = False  # audit hooks cannot be removed; the list is just ignored
    assert armed is False
    assert snapshot == []
