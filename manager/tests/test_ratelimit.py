"""REQ-047 (1)-(4), (6), (7): in-memory rate limits and the failed-check
aggregator (TASK-036). Checks CHK-M2-140 to CHK-M2-146 of tests/m2/test-plan.md.

TS §6.3 L1136 (sign-in 10/min per IP; 600/min per user; 20 failed token
checks/min per IP, counting failures only; one aggregated audit entry per IP
per minute), #55 (c) (every sign-in attempt counts), #55 (e) (Retry-After),
#50 (a), (e) (action, detail), decisions 2026-10-21 "M2 test-plan answers" (3)
(429-answered requests count) and "Lead ruling on #54 (b)" (alert at 21, once
per IP per hour).
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.runtime import RateLimits

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)  # a minute boundary


class Clock:
    def __init__(self, at: datetime = T0) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def rl(clock: Clock) -> RateLimiter:
    return RateLimiter(clock)


def fail(rl: RateLimiter, ip: str, n: int) -> list[bool]:
    """Like the auth dependency: check blocked, record the failure, n times.
    Returns whether each request was answered 429."""
    answered_429 = []
    for _ in range(n):
        answered_429.append(rl.failed_check_blocked(ip))
        rl.record_failed_check(ip)
    return answered_429


def test_implements_the_runtime_protocol(rl: RateLimiter) -> None:
    limits: RateLimits = rl
    assert limits.allow_login("192.0.2.1") is True


# ------------------------------------------------------------ CHK-M2-140


def test_sign_in_limit_is_10_per_ip_per_minute(rl: RateLimiter, clock: Clock) -> None:
    assert [rl.allow_login("192.0.2.1") for _ in range(11)] == [True] * 10 + [False]
    assert rl.allow_login("192.0.2.1") is False  # still refused, keeps counting
    assert rl.allow_login("192.0.2.2") is True
    clock.advance(59.999)
    assert rl.allow_login("192.0.2.1") is False  # same minute
    clock.advance(0.001)
    assert [rl.allow_login("192.0.2.1") for _ in range(11)] == [True] * 10 + [False]


def test_windows_are_fixed_minutes_not_sliding(rl: RateLimiter, clock: Clock) -> None:
    clock.advance(50)
    assert all(rl.allow_login("a") for _ in range(10))
    clock.advance(10)  # next minute starts: a fresh 10
    assert all(rl.allow_login("a") for _ in range(10))
    assert rl.allow_login("a") is False


# ------------------------------------------------------------ CHK-M2-141


def test_user_limit_is_600_per_minute(rl: RateLimiter, clock: Clock) -> None:
    results = [rl.allow_user(1) for _ in range(601)]
    assert results.count(True) == 600 and results[-1] is False
    assert rl.allow_user(2) is True
    clock.advance(60)
    assert rl.allow_user(1) is True


def test_user_limit_is_per_user_not_per_token_or_ip(rl: RateLimiter) -> None:
    """The limiter keys on user_id only, so two tokens of one user share it."""
    for _ in range(300):
        rl.allow_user(7)  # token A
    for _ in range(300):
        rl.allow_user(7)  # token B
    assert rl.allow_user(7) is False


def test_counting_is_thread_safe(rl: RateLimiter) -> None:
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        mine = [rl.allow_user(9) for _ in range(100)]
        with lock:
            results.extend(mine)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 600 and results.count(False) == 400


# ------------------------------------------------------------ CHK-M2-142


def test_failed_checks_block_from_the_21st(rl: RateLimiter) -> None:
    answered = fail(rl, "198.51.100.1", 25)
    assert answered == [False] * 20 + [True] * 5
    assert rl.failed_check_blocked("198.51.100.2") is False


def test_valid_requests_are_never_counted_or_blocked(rl: RateLimiter) -> None:
    ip = "198.51.100.3"
    fail(rl, ip, 19)
    for _ in range(1000):
        assert rl.allow_user(5) or True  # valid-token traffic from the same IP
    assert rl.failed_check_blocked(ip) is False
    fail(rl, ip, 1)
    assert rl.failed_check_blocked(ip) is True
    assert rl.allow_user(6) is True  # a valid user from the blocked IP still passes


def test_block_ends_with_the_minute(rl: RateLimiter, clock: Clock) -> None:
    fail(rl, "a", 20)
    assert rl.failed_check_blocked("a") is True
    clock.advance(60)
    assert rl.failed_check_blocked("a") is False


# ------------------------------------------------------------ CHK-M2-143


def test_one_entry_per_ip_per_minute_with_failures(
    rl: RateLimiter, clock: Clock
) -> None:
    fail(rl, "A", 3)
    fail(rl, "B", 1)
    assert rl.drain() == []  # the minute is not over yet
    clock.advance(120)  # minute m + 2
    fail(rl, "A", 2)
    clock.advance(60)  # minute m + 3
    entries = rl.drain()
    got = [(e.ip, e.window_start, e.count, e.action) for e in entries]
    assert sorted(got) == sorted(
        [
            ("A", T0, 3, "auth.token_check_failed"),
            ("B", T0, 1, "auth.token_check_failed"),
            ("A", T0 + timedelta(minutes=2), 2, "auth.token_check_failed"),
        ]
    )
    for e in entries:
        assert set(e.detail) == {"ip", "window_start", "count"}
        assert e.detail["ip"] == e.ip and e.detail["count"] == e.count
        text = e.detail["window_start"]
        assert isinstance(text, str) and text.endswith("Z")
        assert datetime.fromisoformat(text) == e.window_start
    assert rl.drain() == []  # idempotent


def test_429_answered_requests_count_in_the_aggregate(
    rl: RateLimiter, clock: Clock
) -> None:
    """User decision (3): 20 x 401 plus 5 x 429 gives count 25."""
    answered = fail(rl, "C", 25)
    assert answered.count(True) == 5
    clock.advance(60)
    (entry,) = rl.drain()
    assert entry.count == 25 and entry.detail["count"] == 25


def test_final_drain_includes_the_current_minute(rl: RateLimiter, clock: Clock) -> None:
    """Shutdown flush (REQ-057 (6)): the pending minute is written too."""
    clock.advance(30)
    fail(rl, "D", 3)
    assert rl.drain() == []
    (entry,) = rl.drain(final=True)
    assert (entry.ip, entry.count, entry.window_start) == ("D", 3, T0)
    assert rl.drain(final=True) == []


# ------------------------------------------------------------ CHK-M2-144


def drain_after_minute(rl: RateLimiter, clock: Clock) -> dict[str, bool]:
    clock.advance(60)
    return {e.ip: e.alert for e in rl.drain()}


def test_exactly_20_gives_no_alert_21_gives_one(rl: RateLimiter, clock: Clock) -> None:
    fail(rl, "E20", 20)
    fail(rl, "E21", 21)
    alerts = drain_after_minute(rl, clock)
    assert alerts == {"E20": False, "E21": True}


def test_the_21st_may_be_a_429_answered_request(rl: RateLimiter, clock: Clock) -> None:
    answered = fail(rl, "F", 21)
    assert answered[-1] is True  # the 21st was answered 429
    assert drain_after_minute(rl, clock) == {"F": True}


def test_at_most_one_alert_per_ip_per_hour(rl: RateLimiter, clock: Clock) -> None:
    fail(rl, "G", 30)
    assert drain_after_minute(rl, clock) == {"G": True}
    for _ in range(58):  # minutes 1..58 after the alert minute: over the limit
        fail(rl, "G", 25)
        assert drain_after_minute(rl, clock) == {"G": False}
    # the next minute's start is 59 min after the alert minute: still no alert
    fail(rl, "G", 25)
    assert drain_after_minute(rl, clock) == {"G": False}
    # 60 min after the alert minute: alerts again
    fail(rl, "G", 25)
    assert drain_after_minute(rl, clock) == {"G": True}


def test_second_ip_has_its_own_alert(rl: RateLimiter, clock: Clock) -> None:
    fail(rl, "H1", 21)
    assert drain_after_minute(rl, clock) == {"H1": True}
    fail(rl, "H1", 21)
    fail(rl, "H2", 21)
    assert drain_after_minute(rl, clock) == {"H1": False, "H2": True}


def test_more_failures_in_the_same_minute_give_one_entry_one_alert(
    rl: RateLimiter, clock: Clock
) -> None:
    fail(rl, "I", 100)
    clock.advance(60)
    entries = rl.drain()
    assert len(entries) == 1 and entries[0].alert is True and entries[0].count == 100


# ------------------------------------------------------------ CHK-M2-145


def test_keys_are_dropped_once_their_window_has_passed(
    rl: RateLimiter, clock: Clock
) -> None:
    for i in range(10_000):
        rl.allow_login(f"10.0.{i // 256}.{i % 256}")
        rl.allow_user(i)
        rl.record_failed_check(f"10.1.{i // 256}.{i % 256}")
    assert rl.size() == 30_000
    clock.advance(60)
    rl.drain()
    assert rl.size() == 0


def test_alert_memory_is_dropped_after_an_hour(rl: RateLimiter, clock: Clock) -> None:
    fail(rl, "J", 21)
    clock.advance(60)
    rl.drain()
    assert rl.size() == 1  # the alert timestamp
    clock.advance(3600)
    rl.drain()
    assert rl.size() == 0


# ------------------------------------------------------------ CHK-M2-146


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (0.0, 60),
        (0.001, 60),
        (0.999, 60),
        (1.0, 59),
        (5.0, 55),
        (59.0, 1),
        (59.5, 1),
        (59.999, 1),
    ],
)
def test_retry_after_is_whole_seconds_to_the_window_end(
    clock: Clock, offset: float, expected: int
) -> None:
    clock.advance(offset)
    assert RateLimiter(clock).retry_after() == expected
