"""TASK-056: in-memory threshold windows and the M3 metric definitions.

Checks CHK-M3-100 to CHK-M3-105 of tests/m3/test-plan.md (TP-M3-10; the kind
list itself, CHK-M3-103, is in tests/test_alerts.py). Expected values: #65
("more than" a threshold; once per period; re-arm only after the condition was
false), #61 (sliding 60 minutes, threshold from the setting), #66 (once per
hour), TS §2.1 L103 (one instance: in memory), TS §8.4 L1288-L1289 and REQ-086
(3) (agents by status, heartbeat latency, jobs queued, jobs expired; bounded
labels only). The agent_status values are read from the spec DDL.
"""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import re2  # type: ignore[import-untyped]
from prometheus_client import generate_latest

from bitscan_manager.services.audit import (
    AGENT_STATUSES,
    AGENTS_BY_STATUS,
    ALERT_KINDS,
    HEARTBEAT_LATENCY,
    JOBS_EXPIRED,
    JOBS_QUEUED,
    REGISTRY,
    OncePerPeriod,
    ReArm,
    SlidingCount,
)

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
TS = (
    Path(__file__).resolve().parents[2] / "docs" / "spec" / "Technical_Specification.md"
)


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at

    def advance(self, d: timedelta) -> None:
        self.at += d


@pytest.fixture
def clock() -> Clock:
    return Clock()


# ------------------------------------------------------------ CHK-M3-100


@pytest.mark.parametrize(
    ("window", "period", "threshold"),
    [
        (MIN, HOUR, 20),  # #65 (d): 401s per agent
        (10 * MIN, HOUR, 20),  # #54 (c), #65 (f): 409 flood
        (60 * MIN, HOUR, 50),  # #61: enrolments per token (default setting)
        (timedelta(hours=24), timedelta(hours=24), 1000),  # #65 (e): new packages
    ],
    ids=["1m", "10m", "60m", "24h"],
)
def test_sliding_count_fires_once_above_the_threshold(
    clock: Clock, window: timedelta, period: timedelta, threshold: int
) -> None:
    w: SlidingCount[str] = SlidingCount(clock, window, period, threshold)
    step = window / (threshold * 4)
    fired = []
    for _ in range(threshold):
        fired.append(w.add("a"))
        clock.advance(step)
    assert fired == [False] * threshold  # exactly the threshold: nothing
    assert w.add("a") is True  # threshold + 1
    assert [w.add("a") for _ in range(threshold)] == [False] * threshold  # same period
    assert w.add("b") is False  # keys are independent
    assert w.count("a") == 2 * threshold + 1


def test_sliding_count_again_only_after_the_period(clock: Clock) -> None:
    w: SlidingCount[str] = SlidingCount(clock, 10 * MIN, HOUR, 20)
    for _ in range(21):
        last = w.add("a")
    assert last is True
    clock.advance(59 * MIN)
    assert [w.add("a") for _ in range(21)] == [False] * 21  # inside the hour
    clock.advance(MIN)  # exactly one hour after the alert
    assert w.add("a") is True  # 22 events in the last 10 minutes


def test_events_leave_the_window_at_its_length(clock: Clock) -> None:
    w: SlidingCount[str] = SlidingCount(clock, MIN, HOUR, 20)
    for _ in range(20):
        w.add("a")
    clock.advance(MIN - SEC)
    assert w.count("a") == 20
    assert w.add("a") is True  # 21 within the minute
    w2: SlidingCount[str] = SlidingCount(clock, MIN, HOUR, 20)
    for _ in range(20):
        w2.add("x")
    clock.advance(MIN)  # the first 20 are now a minute old
    assert w2.count("x") == 0
    assert w2.add("x") is False


def test_weights_count_as_events(clock: Clock) -> None:
    """#65 (e): 1,000 new packages do not alert, 1,001 do."""
    w: SlidingCount[str] = SlidingCount(
        clock, timedelta(hours=24), timedelta(hours=24), 1000
    )
    assert w.add("agent", 600) is False
    assert w.add("agent", 400) is False
    assert w.count("agent") == 1000
    assert w.add("agent", 1) is True
    w2: SlidingCount[str] = SlidingCount(
        clock, timedelta(hours=24), timedelta(hours=24), 1000
    )
    assert w2.add("agent", 1001) is True


def test_threshold_override_from_a_setting(clock: Clock) -> None:
    """#61: enrolment_alert_per_hour is read at call time."""
    w: SlidingCount[int] = SlidingCount(clock, HOUR, HOUR, 50)
    assert [w.add(7, threshold=3) for _ in range(4)] == [False, False, False, True]
    assert [w.add(8) for _ in range(4)] == [False] * 4  # default 50 for others


def test_sliding_count_is_exact_under_threads(clock: Clock) -> None:
    w: SlidingCount[str] = SlidingCount(clock, HOUR, HOUR, 999)
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def hit() -> None:
        barrier.wait(10)
        for _ in range(50):
            ok = w.add("k")
            with lock:
                results.append(ok)

    ts = [threading.Thread(target=hit) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert len(results) == 1000 and results.count(True) == 1
    assert w.count("k") == 1000


# ------------------------------------------------------------ CHK-M3-101


def test_once_per_period(clock: Clock) -> None:
    o: OncePerPeriod[str] = OncePerPeriod(clock, HOUR)
    assert o.fire("agent-a") is True
    assert o.fire("agent-a") is False
    assert o.fire("agent-b") is True  # per key
    clock.advance(HOUR - SEC)
    assert o.fire("agent-a") is False
    clock.advance(SEC)
    assert o.fire("agent-a") is True


# ------------------------------------------------------------ CHK-M3-102


def test_rearm_update(clock: Clock) -> None:
    r: ReArm[str] = ReArm()
    assert r.update("fleet", False) is False
    assert r.update("fleet", True) is True  # just became true
    assert r.update("fleet", True) is False  # still true: no repeat
    assert r.update("fleet", False) is False  # back at or below: re-arm
    assert r.update("fleet", True) is True
    assert r.update("other", True) is True


def test_rearm_sync(clock: Clock) -> None:
    """#65 (c): stale inventory per agent until its next upload."""
    r: ReArm[str] = ReArm()
    assert r.sync(["a", "b", "a"]) == ["a", "b"]
    assert r.sync(["b", "a"]) == []
    assert r.sync(["b"]) == []  # a re-arms
    assert r.sync(["a", "b"]) == ["a"]
    assert r.sync([]) == []
    assert r.size() == 0


def test_offline_share_rearm_example(clock: Clock) -> None:
    """#65 (b) through ReArm as the caller uses it: share > 5 % of 100 agents."""
    r: ReArm[str] = ReArm()
    seq = [5, 6, 7, 6, 5, 6, 4, 4, 6]
    fired = [r.update("offline_share", n / 100 > 0.05) for n in seq]
    assert fired == [False, True, False, False, False, True, False, False, True]


# ------------------------------------------------------------ CHK-M3-105


def test_sliding_count_memory_is_bounded(clock: Clock) -> None:
    w: SlidingCount[int] = SlidingCount(clock, MIN, HOUR, 0)
    for k in range(10_000):
        w.add(k)  # threshold 0: every key fires once, so _fired holds them too
    assert w.size() == 20_000
    clock.advance(MIN)
    w.add(-1)
    assert w.size() == 10_000 + 2  # events gone; alert times kept for the period
    clock.advance(HOUR)
    w.add(-2)
    assert w.size() <= 2


def test_once_per_period_memory_is_bounded(clock: Clock) -> None:
    o: OncePerPeriod[int] = OncePerPeriod(clock, HOUR)
    for k in range(10_000):
        o.fire(k)
    clock.advance(HOUR)
    o.fire(-1)
    assert o.size() == 1


# ------------------------------------------------------------ CHK-M3-104


def spec_agent_statuses() -> list[str]:
    text = TS.read_text(encoding="utf-8")
    m = re2.search(r"CREATE TYPE agent_status AS ENUM \(([^)]*)\)", text)
    assert m is not None
    return [v.strip().strip("'") for v in m.group(1).split(",")]


def test_metric_families_and_labels() -> None:
    assert list(AGENT_STATUSES) == spec_agent_statuses()
    families = {m.name: m for m in REGISTRY.collect()}
    assert set(families) == {
        "bitscan_alerts",
        "bitscan_agents",
        "bitscan_heartbeat_latency_seconds",
        "bitscan_jobs_queued",
        "bitscan_jobs_expired",
    }
    assert families["bitscan_agents"].type == "gauge"
    assert families["bitscan_jobs_queued"].type == "gauge"
    assert families["bitscan_heartbeat_latency_seconds"].type == "histogram"
    assert families["bitscan_jobs_expired"].type == "counter"
    assert families["bitscan_alerts"].type == "counter"
    allowed = {
        "bitscan_alerts": {"kind"},
        "bitscan_agents": {"status"},
        "bitscan_heartbeat_latency_seconds": {"le"},
        "bitscan_jobs_queued": set(),
        "bitscan_jobs_expired": set(),
    }
    for name, fam in families.items():
        for sample in fam.samples:
            assert set(sample.labels) <= allowed[name], (name, sample.labels)
            if "status" in sample.labels:
                assert sample.labels["status"] in AGENT_STATUSES
            if "kind" in sample.labels:
                assert sample.labels["kind"] in ALERT_KINDS


def test_every_status_exported_from_zero_and_names_on_the_wire() -> None:
    text = generate_latest(REGISTRY).decode()
    for status in spec_agent_statuses():
        assert f'bitscan_agents{{status="{status}"}}' in text
    assert "bitscan_jobs_expired_total" in text
    assert "bitscan_heartbeat_latency_seconds_bucket" in text
    assert (
        "bitscan_jobs_queued " in text
        or "bitscan_jobs_queued\n" in text
        or ("# TYPE bitscan_jobs_queued gauge" in text)
    )


def test_no_unbounded_label_names_anywhere() -> None:
    """REQ-086 (3): the only label names on the wire are kind, status and le."""
    text = generate_latest(REGISTRY).decode()
    names = {m.group(1) for m in re2.finditer(r'[{,]([a-zA-Z_]+)="', text)}
    assert names <= {"kind", "status", "le"}, names
    assert names >= {"kind", "status", "le"}


def test_metrics_move() -> None:
    """The objects behave as their type (the callers move them in later tasks)."""
    before = REGISTRY.get_sample_value("bitscan_jobs_expired_total") or 0.0
    JOBS_EXPIRED.inc(2)
    assert REGISTRY.get_sample_value("bitscan_jobs_expired_total") == before + 2
    count = REGISTRY.get_sample_value("bitscan_heartbeat_latency_seconds_count") or 0.0
    for _ in range(3):
        HEARTBEAT_LATENCY.observe(0.004)
    assert (
        REGISTRY.get_sample_value("bitscan_heartbeat_latency_seconds_count")
        == count + 3
    )
    JOBS_QUEUED.set(7)
    assert REGISTRY.get_sample_value("bitscan_jobs_queued") == 7
    AGENTS_BY_STATUS.labels(status="online").set(5)
    assert REGISTRY.get_sample_value("bitscan_agents", {"status": "online"}) == 5


# ------------------------------------------------ TASK-064 r1, TASK-068: two-phase


def test_sliding_count_check_without_mark_fires_again(clock: Clock) -> None:
    """Ruling 2026-10-23: a window is marked only after its alert committed."""
    s: SlidingCount[str] = SlidingCount(clock, HOUR, HOUR, 2)
    assert [s.count_and_check("k") for _ in range(3)] == [False, False, True]
    assert s.count_and_check("k") is True  # not marked: still due
    s.mark_fired("k")
    assert s.count_and_check("k") is False
    clock.advance(HOUR)
    assert s.count_and_check("k") is False  # the window emptied: 1 event
    assert s.count_and_check("k") is False
    assert s.count_and_check("k") is True  # 3 in the window, period over


def test_once_per_period_due_and_mark(clock: Clock) -> None:
    o: OncePerPeriod[str] = OncePerPeriod(clock, HOUR)
    assert o.due("q") is True and o.due("q") is True  # due never records
    o.mark("q")
    assert o.due("q") is False and o.due("other") is True
    clock.advance(HOUR - SEC)
    assert o.due("q") is False
    clock.advance(SEC)
    assert o.due("q") is True
    assert o.fire("q") is True and o.fire("q") is False  # fire = due + mark


def test_rearm_due_and_mark(clock: Clock) -> None:
    r: ReArm[str] = ReArm()
    assert r.due(["a", "b"]) == ["a", "b"]
    assert r.due(["a", "b"]) == ["a", "b"]  # nothing recorded yet
    r.mark("a")
    assert r.due(["a", "b"]) == ["b"]
    assert r.due(["b"]) == ["b"]  # a left the set: re-armed
    assert r.due(["a", "b"]) == ["a", "b"]
    r.mark("a")
    r.mark("b")
    assert r.due(["a", "b", "a"]) == []
    assert r.size() == 2
