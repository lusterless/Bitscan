"""TP-M9-08: idempotency store (TASK-192; REQ-222 (1)-(3)).

TS §6.3 L1135, §6.4 L1149, §2.1 L103; open question #123. A fake clock
and a counting call; threads are ordered by barriers and events, never by
sleeps. CHK-M9-075 to -079.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bitscan_manager.api.user import idempotency
from bitscan_manager.api.user.idempotency import (
    IdempotencyStore,
    InvalidKey,
    KeyReused,
    body_digest,
    check_key,
)

T0 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
WAIT = 10.0  # bound for every barrier/event wait (s)
BODY = {"policy_id": 7, "target": {"tags": ["web"]}}


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.t = now

    def now(self) -> datetime:
        return self.t


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict[str, Any]


@dataclass
class Counter:
    calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def make(self, scan: str = "s1") -> Callable[[], Answer]:
        def call() -> Answer:
            with self.lock:
                self.calls += 1
                n = self.calls
            return Answer(202, {"scan_id": f"{scan}-{n}", "state": "queued"})

        return call


class Refused(Exception):
    """Stands in for a 409 refusal raised by the route's call."""


def store(clock: FakeClock | None = None, **kw: Any) -> IdempotencyStore[Answer]:
    return IdempotencyStore(clock or FakeClock(), **kw)


# --- CHK-M9-075: repeats, users, bodies -------------------------------------


def test_same_user_key_body_returns_the_first_answer() -> None:
    s, c = store(), Counter()
    first = s.run(1, "key-1", BODY, c.make())
    again = s.run(1, "key-1", BODY, c.make())
    assert again == first
    assert c.calls == 1


def test_another_user_with_the_same_key_gets_a_new_answer() -> None:
    s, c = store(), Counter()
    a = s.run(1, "key-1", BODY, c.make())
    b = s.run(2, "key-1", BODY, c.make())
    assert a != b and c.calls == 2
    assert s.run(2, "key-1", BODY, c.make()) == b and c.calls == 2


def test_same_key_other_body_is_a_conflict() -> None:
    s, c = store(), Counter()
    s.run(1, "key-1", BODY, c.make())
    with pytest.raises(KeyReused) as info:
        s.run(1, "key-1", {"policy_id": 8, "target": {"tags": ["web"]}}, c.make())
    assert str(info.value) == "Idempotency-Key was used with a different request."
    assert c.calls == 1
    # the first answer is still remembered
    assert s.run(1, "key-1", BODY, c.make()).body["scan_id"] == "s1-1"


def test_bodies_are_compared_after_parsing() -> None:
    s, c = store(), Counter()
    s.run(1, "k", {"a": 1, "b": {"x": [1, 2], "y": None}}, c.make())
    s.run(1, "k", {"b": {"y": None, "x": [1, 2]}, "a": 1}, c.make())
    assert c.calls == 1
    for other in (
        {"a": 1, "b": {"x": [2, 1], "y": None}},
        {"a": True, "b": {"x": [1, 2], "y": None}},
        {"a": 1.0, "b": {"x": [1, 2], "y": None}},
    ):
        with pytest.raises(KeyReused):
            s.run(1, "k", other, c.make())


def test_body_digest_properties() -> None:
    assert body_digest({"a": 1, "b": 2}) == body_digest({"b": 2, "a": 1})
    assert body_digest({"a": 1}) != body_digest({"a": True})
    assert body_digest({"a": 1}) != body_digest({"a": 1.0})
    assert len(body_digest(BODY)) == 32


def test_body_digest_nan_is_recorded(record_property: Any) -> None:
    # Python's json.loads accepts NaN; recorded for TASK-205's order of checks.
    try:
        body_digest({"a": float("nan")})
        record_property("nan_body", "digested")
    except ValueError as exc:
        record_property("nan_body", type(exc).__name__)


# --- CHK-M9-076: 24 hours ---------------------------------------------------


def test_kept_for_24_hours_then_forgotten(record_property: Any) -> None:
    clock = FakeClock()
    s, c = store(clock), Counter()
    s.run(1, "k", BODY, c.make())
    clock.t = T0 + timedelta(hours=24) - timedelta(seconds=1)
    s.run(1, "k", BODY, c.make())
    assert c.calls == 1
    clock.t = T0 + timedelta(hours=24) + timedelta(seconds=1)
    fresh = s.run(1, "k", BODY, c.make())
    assert c.calls == 2 and fresh.body["scan_id"] == "s1-2"
    # exactly 24 h: recorded, not asserted
    clock2 = FakeClock()
    s2, c2 = store(clock2), Counter()
    s2.run(1, "k", BODY, c2.make())
    clock2.t = T0 + timedelta(hours=24)
    s2.run(1, "k", BODY, c2.make())
    record_property("kept_at_exactly_24h", c2.calls == 1)


def test_expired_key_can_take_another_body() -> None:
    clock = FakeClock()
    s, c = store(clock), Counter()
    s.run(1, "k", BODY, c.make())
    clock.t = T0 + timedelta(hours=25)
    s.run(1, "k", {"policy_id": 9, "target": {"all": True}}, c.make())
    assert c.calls == 2


def test_defaults() -> None:
    assert timedelta(hours=24) == idempotency.TTL
    assert idempotency.MAX_ENTRIES == 100_000
    assert idempotency.KEY_MAX == 255


# --- CHK-M9-077: only an answer is remembered -------------------------------


def test_a_refused_first_request_is_not_remembered() -> None:
    s, c = store(), Counter()

    def refuse() -> Answer:
        raise Refused

    with pytest.raises(Refused):
        s.run(1, "k", BODY, refuse)
    assert s.run(1, "k", BODY, c.make()).body["scan_id"] == "s1-1"
    assert c.calls == 1


def test_a_failing_call_releases_the_key_lock() -> None:
    s, c = store(), Counter()

    def boom() -> Answer:
        raise RuntimeError("db down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            s.run(1, "k", BODY, boom)
    done = threading.Event()

    def other() -> None:
        s.run(1, "k", BODY, c.make())
        done.set()

    t = threading.Thread(target=other)
    t.start()
    assert done.wait(WAIT), "the key lock was left held"
    t.join(WAIT)
    assert c.calls == 1


def test_a_refused_body_does_not_block_another_body() -> None:
    s, c = store(), Counter()

    def refuse() -> Answer:
        raise Refused

    with pytest.raises(Refused):
        s.run(1, "k", BODY, refuse)
    s.run(1, "k", {"policy_id": 1, "target": {"all": True}}, c.make())
    assert c.calls == 1


# --- CHK-M9-078: concurrency ------------------------------------------------


def test_two_concurrent_identical_requests_run_once() -> None:
    s = store()
    calls = 0
    entered = threading.Event()
    release = threading.Event()
    barrier = threading.Barrier(2)
    answers: list[Answer] = []
    errors: list[BaseException] = []

    def call() -> Answer:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(WAIT)
        return Answer(202, {"scan_id": "only"})

    def worker() -> None:
        try:
            barrier.wait(WAIT)
            answers.append(s.run(1, "k", BODY, call))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    assert entered.wait(WAIT)
    release.set()
    for t in threads:
        t.join(WAIT)
    assert errors == []
    assert calls == 1
    assert len(answers) == 2 and answers[0] is answers[1]


def test_lock_is_per_key_not_global() -> None:
    s, c = store(), Counter()
    entered = threading.Event()
    release = threading.Event()

    def slow() -> Answer:
        entered.set()
        assert release.wait(WAIT)
        return Answer(202, {"scan_id": "slow"})

    holder = threading.Thread(target=lambda: s.run(1, "A", BODY, slow))
    holder.start()
    assert entered.wait(WAIT)
    finished: list[str] = []

    def quick(user: int, key: str) -> None:
        s.run(user, key, BODY, c.make())
        finished.append(f"{user}:{key}")

    others = [threading.Thread(target=quick, args=a) for a in ((1, "B"), (2, "A"))]
    for t in others:
        t.start()
    for t in others:
        t.join(WAIT)
    try:
        assert sorted(finished) == ["1:B", "2:A"]  # not blocked by user 1's key A
    finally:
        release.set()
        holder.join(WAIT)
    assert c.calls == 2


def test_a_waiting_repeat_with_another_body_gets_the_conflict() -> None:
    s = store()
    entered = threading.Event()
    release = threading.Event()
    result: list[object] = []

    def slow() -> Answer:
        entered.set()
        assert release.wait(WAIT)
        return Answer(202, {"scan_id": "first"})

    first = threading.Thread(target=lambda: s.run(1, "k", BODY, slow))
    first.start()
    assert entered.wait(WAIT)

    def second() -> None:
        try:
            s.run(1, "k", {"other": 1}, lambda: Answer(202, {}))
            result.append("ran")
        except KeyReused:
            result.append("conflict")

    t2 = threading.Thread(target=second)
    t2.start()
    release.set()
    first.join(WAIT)
    t2.join(WAIT)
    assert result == ["conflict"]


# --- CHK-M9-079: key validation and capacity --------------------------------


@pytest.mark.parametrize("key", ["a", "x" * 255, "abc-123_~!", "~", "!"])
def test_valid_keys(key: str) -> None:
    assert check_key(key) == key
    store().run(1, key, BODY, Counter().make())


@pytest.mark.parametrize(
    "key",
    [
        "",
        "x" * 256,
        "a\x00",
        "a\x1f",
        "a\x7f",
        "a\n",
        "a\t",
        "\u00e9",
        "\U0001f600",
        "a\r",
    ],
)
def test_invalid_keys(key: str) -> None:
    with pytest.raises(InvalidKey):
        check_key(key)
    c = Counter()
    with pytest.raises(InvalidKey):
        store().run(1, key, BODY, c.make())
    assert c.calls == 0


def test_space_in_a_key_is_recorded(record_property: Any) -> None:
    for label, key in (("inner_space", "a b"), ("only_space", " ")):
        try:
            check_key(key)
            record_property(label, "accepted")
        except InvalidKey:
            record_property(label, "refused")


def test_invalid_key_message_is_fixed() -> None:
    with pytest.raises(InvalidKey) as info:
        check_key("secret\x00")
    assert "secret" not in str(info.value)
    assert isinstance(info.value, ValueError)


def test_capacity_drops_the_oldest_first() -> None:
    s, c = store(), Counter()
    for i in range(100_000):
        s.run(1, f"k{i}", BODY, c.make())
    assert c.calls == 100_000
    s.run(1, "new", BODY, c.make())  # the 100,001st entry drops the oldest stored, k0
    assert c.calls == 100_001
    s.run(1, "k1", BODY, c.make())  # still remembered (a hit stores nothing)
    s.run(1, "k99999", BODY, c.make())
    assert c.calls == 100_001
    s.run(1, "k0", BODY, c.make())  # forgotten: called again
    assert c.calls == 100_002


def test_capacity_with_a_small_bound() -> None:
    s, c = store(max_entries=3), Counter()
    for k in ("a", "b", "c"):
        s.run(1, k, BODY, c.make())
    s.run(1, "d", BODY, c.make())  # drops "a"
    assert c.calls == 4
    s.run(1, "b", BODY, c.make())
    s.run(1, "c", BODY, c.make())
    s.run(1, "d", BODY, c.make())
    assert c.calls == 4
    s.run(1, "a", BODY, c.make())  # forgotten
    assert c.calls == 5
