"""TP-M9-09: property suite (hypothesis) for the M9 pure modules.

REQ-206 (3), REQ-207 (2), REQ-216 (accounting), REQ-223 (4); #121, #127.
CHK-M9-080 to -086. Invariants are the spec's, stated before the code was
read; the model below applies only the events the spec says can happen to a
job in each state (the sweep's candidate filter for deadlines, the 7-day
acceptance for batches).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bitscan_manager.api.agent.schemas import ResultItem
from bitscan_manager.services.evaluator.eval_spec import EvalSpec
from bitscan_manager.services.evaluator.model import PluginSpec
from bitscan_manager.services.jobs import states
from bitscan_manager.services.jobs.intake_plan import PluginNotInJob, plan, storable
from bitscan_manager.services.jobs.scan_state import Unit, derive
from bitscan_manager.services.jobs.targets import (
    InvalidTarget,
    parse_target,
    stored_target,
)
from bitscan_manager.services.scheduler.cron import next_fire, parse_schedule

D = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
FINAL = {"completed", "expired", "cancelled"}

# --- CHK-M9-080: random walks over the job state machine --------------------

EVENT = st.one_of(
    st.just(("pull",)),
    st.just(("cancel",)),
    st.just(("pickup",)),
    st.just(("never_started",)),
    st.just(("deadline",)),
    st.tuples(st.just("batch"), st.integers(0, 4), st.booleans()),
)


@settings(max_examples=5_000, deadline=None)
@given(st.integers(1, 6), st.lists(EVENT, max_size=20))
def test_state_machine_walks(plugins: int, events: list[tuple[Any, ...]]) -> None:
    state, started, results = "queued", False, 0
    left_running = False
    for ev in events:
        before = state
        kind = ev[0]
        if kind == "pull" and states.allowed(state, "dispatched"):
            state = "dispatched"
        elif kind == "cancel" and states.allowed(state, "cancelled"):
            state = "cancelled"
        elif kind == "pickup" and states.allowed(state, "expired"):
            state = "expired"
        elif kind == "never_started" and state == "dispatched" and not started:
            state = states.after_deadline(any_result=False, all_have_results=False)
            assert state == "failed"
        elif kind == "deadline" and state in ("dispatched", "running") and started:
            state = states.after_deadline(
                any_result=results > 0, all_have_results=results == plugins
            )
        elif kind == "batch" and states.accepts_results("compliance", state, D, D):
            new = min(ev[1], plugins - results)
            results += new
            out = states.after_batch(
                state, stored=new, all_have_results=results == plugins, final=ev[2]
            )
            if out.start:
                assert not started, "started twice"
                assert before == "dispatched"
                started = True
                assert states.allowed("dispatched", "running")
                if out.state != "running":
                    assert states.allowed("running", out.state)
            elif out.state != before:
                assert states.allowed(before, out.state), (before, out.state)
            state = out.state
        else:
            continue
        # REQ-206 (3)
        if before in FINAL:
            assert state == before, (before, ev, state)
        if before in ("failed", "partial"):
            assert state in ("failed", "partial", "completed"), (before, ev, state)
            if state != before:
                assert state in ("completed", "partial")
        if before == "running" and state != "running":
            left_running = True
        if left_running:
            assert state != "running"
        if kind != "batch" and state != before:
            assert states.allowed(before, state), (before, ev, state)


# --- CHK-M9-081: deadline arithmetic ---------------------------------------


@settings(max_examples=3_000, deadline=None)
@given(st.lists(st.integers(1, 600), min_size=1, max_size=5_000), st.integers(1, 8))
def test_deadline_is_the_integer_ceiling(timeouts: list[int], mpp: int) -> None:
    total = sum(timeouts)
    extra = states.deadline_at(D, timeouts, mpp) - D - timedelta(minutes=10)
    assert extra == timedelta(seconds=(total + mpp - 1) // mpp)
    assert extra.microseconds == 0
    assert total <= extra.total_seconds() * mpp < total + mpp


# --- CHK-M9-082: scan derivation over consistent unit sets ------------------


@st.composite
def units(draw: st.DrawFn) -> Unit:
    is_open = draw(st.booleans())
    all_queued = is_open and draw(st.booleans())
    has_results = not all_queued and draw(st.booleans())
    complete = has_results and draw(st.booleans())
    any_cancelled = not all_queued and draw(st.booleans())
    return Unit(
        open=is_open,
        complete=complete,
        has_results=has_results,
        any_cancelled=any_cancelled,
        all_queued=all_queued,
    )


@settings(max_examples=5_000, deadline=None)
@given(st.lists(units(), min_size=1, max_size=20), st.data())
def test_derivation_properties(us: list[Unit], data: st.DataObject) -> None:
    state, finished = derive(us)
    assert finished is (not any(u.open for u in us))
    assert state not in ("dispatched", "expired")
    assert derive(list(reversed(us))) == (state, finished)
    # adding a result to one unit never turns partial/completed into failed/cancelled
    i = data.draw(st.integers(0, len(us) - 1))
    u = us[i]
    if not u.all_queued:
        more = Unit(
            open=u.open,
            complete=u.complete or data.draw(st.booleans()),
            has_results=True,
            any_cancelled=u.any_cancelled,
            all_queued=False,
        )
        after, _ = derive([*us[:i], more, *us[i + 1 :]])
        if state in ("partial", "completed"):
            assert after not in ("failed", "cancelled"), (state, after)
        if not finished:
            assert after in ("queued", "running")


# --- CHK-M9-083: intake plan accounting -------------------------------------


def _pid(n: int) -> UUID:
    return UUID(int=(0xACC << 112) + n)


def _item(n: int, stdout: str) -> ResultItem:
    return ResultItem.model_validate(
        {
            "plugin_uuid": str(_pid(n)),
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
            "started_at": "2026-10-30T12:00:00Z",
            "finished_at": "2026-10-30T12:00:01Z",
            "timed_out": False,
            "truncated": False,
            "error": None,
        }
    )


@settings(
    max_examples=2_000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
@given(
    st.integers(1, 60),
    st.data(),
)
def test_plan_accounting(job_size: int, data: st.DataObject) -> None:
    spec = EvalSpec(
        tuple(
            PluginSpec(
                plugin_uuid=_pid(n), name=f"N {n}", operator="equals", expected="ok"
            )
            for n in range(job_size)
        )
    )
    cmds = {_pid(n): f"cmd {n}" for n in range(job_size)}
    existing = set(data.draw(st.sets(st.integers(0, job_size - 1))))
    picks = data.draw(st.lists(st.integers(0, job_size + 2), max_size=50))
    items = [_item(n, f"v{i}") for i, n in enumerate(picks)]
    if any(n >= job_size for n in picks):
        try:
            plan(spec, cmds, {_pid(n) for n in existing}, items)
        except PluginNotInJob:
            return
        raise AssertionError("a foreign plugin was planned")
    p = plan(spec, cmds, {_pid(n) for n in existing}, items)
    assert len(p.rows) + p.duplicates == len(items)
    uuids = [r.plugin_uuid for r in p.rows]
    assert len(set(uuids)) == len(uuids)
    assert not set(uuids) & {_pid(n) for n in existing}
    for r in p.rows:
        first = next(i for i, n in enumerate(picks) if _pid(n) == r.plugin_uuid)
        assert r.stdout == f"v{first}"
    assert set(uuids) == {_pid(n) for n in picks} - {_pid(n) for n in existing}


# --- CHK-M9-084: storable ---------------------------------------------------

TEXT = st.text(
    alphabet=st.one_of(
        st.characters(codec=None),
        st.sampled_from(
            ["\x00", "\ud800", "\udbff", "\udc00", "\udfff", "\ufffd", "\U0001f600"]
        ),
    ),
    max_size=200,
)


@settings(max_examples=5_000, deadline=None)
@given(TEXT)
def test_storable_properties(text: str) -> None:
    out = storable(text)
    out.encode("utf-8")
    assert "\x00" not in out
    assert len(out) == len(text)
    clean = "\x00" not in text and not any(0xD800 <= ord(c) <= 0xDFFF for c in text)
    if clean:
        assert out == text
    for a, b in zip(text, out, strict=True):
        assert b == a or (b == "\ufffd" and (a == "\x00" or 0xD800 <= ord(a) <= 0xDFFF))


@settings(max_examples=1_000, deadline=None)
@given(TEXT, TEXT)
def test_plan_rows_always_encode(stdout: str, stderr: str) -> None:
    spec = EvalSpec(
        (PluginSpec(plugin_uuid=_pid(0), name="N", operator="contains", expected="x"),)
    )
    it = ResultItem.model_validate(
        json.loads(
            json.dumps(
                {
                    "plugin_uuid": str(_pid(0)),
                    "exit_code": 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "started_at": "2026-10-30T12:00:00Z",
                    "finished_at": "2026-10-30T12:00:01Z",
                    "timed_out": False,
                    "truncated": False,
                    "error": None,
                }
            )
        )
    )
    (row,) = plan(spec, {_pid(0): "c"}, set(), [it]).rows
    row.stdout.encode("utf-8")
    row.stderr.encode("utf-8")
    assert row.eval_code in (0, 1, 2)


# --- CHK-M9-085: next_fire strictly increasing ------------------------------


def _field(low: int, high: int) -> st.SearchStrategy[str]:
    value = st.integers(low, high)
    return st.one_of(
        st.just("*"),
        st.builds(lambda s: f"*/{s}", st.integers(1, max(1, high - low))),
        value.map(str),
        st.tuples(value, value).map(lambda t: f"{min(t)}-{max(t)}"),
        st.lists(value, min_size=2, max_size=4, unique=True).map(
            lambda v: ",".join(map(str, v))
        ),
    )


@st.composite
def crons(draw: st.DrawFn) -> str:
    minute = draw(_field(0, 59))
    hour = draw(_field(0, 23))
    month = draw(_field(1, 12))
    if draw(st.booleans()):
        dom, dow = draw(_field(1, 28)), "*"
    else:
        dom, dow = "*", draw(_field(0, 7))
    return f"{minute} {hour} {dom} {month} {dow}"


ZONES = [
    "UTC",
    "Europe/London",
    "Asia/Kolkata",
    "America/New_York",
    "Australia/Lord_Howe",
    "Asia/Kathmandu",
]


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    crons(),
    st.sampled_from(ZONES),
    st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2030, 12, 31)),
)
def test_next_fire_strictly_increasing(cron: str, zone: str, start: datetime) -> None:
    s = parse_schedule(cron, zone)
    t = start.replace(tzinfo=UTC)
    for _ in range(10):
        n = next_fire(s, t)
        assert n > t
        assert n.utcoffset() == timedelta(0)
        t = n


# --- CHK-M9-086: targets on random JSON -------------------------------------

JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False)
    | st.text(max_size=40),
    lambda inner: (
        st.lists(inner, max_size=5)
        | st.dictionaries(
            st.sampled_from(["agents", "tags", "all", "x"]) | st.text(max_size=5),
            inner,
            max_size=3,
        )
    ),
    max_leaves=20,
)


@settings(max_examples=5_000, deadline=None)
@given(JSON)
def test_parse_target_never_raises_anything_else(value: Any) -> None:
    try:
        t = parse_target(value)
    except InvalidTarget:
        return
    got = stored_target(t, [])
    assert len(set(got) - {"resolved_agents"}) == 1
    assert json.loads(json.dumps(got)) == got
