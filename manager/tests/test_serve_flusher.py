"""CHK-M2-263b: serve's failed-check flusher (TASK-045; reviewer request on
TASK-036; decisions 2026-10-21 user decision (2)). Runs anywhere.

When an audit write fails the flusher keeps that minute's aggregated entries
(and any token_check_failures alert) and writes them at the next flush, in
order; it holds at most 10,000, oldest dropped first, logging the dropped
count as a number only; the limiter is drained and pruned every time.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.cli import serve as serve_module
from bitscan_manager.cli.serve import HELD_MAX, FailedCheckFlusher

from .canary import new_canary

T0 = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


class Tx:
    def __init__(self) -> None:
        self.hooks: list[Callable[[], None]] = []
        self.conn = None

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


class Db:
    def __init__(self) -> None:
        self.fail = False

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        if self.fail:
            raise ConnectionError("database down")
        tx = Tx()
        yield tx
        for hook in tx.hooks:
            hook()


class Wake:
    def __init__(self) -> None:
        self.n = 0

    def wake(self) -> None:
        self.n += 1


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(serve_module, "PgAuditRepo", lambda conn: None)

    def append_entry(repo: object, **kw: Any) -> None:
        out.append(("entry", kw))

    def raise_alert(repo: object, on_commit: object, **kw: Any) -> None:
        out.append(("alert", kw))

    monkeypatch.setattr(serve_module, "append_entry", append_entry)
    monkeypatch.setattr(serve_module, "raise_alert", raise_alert)
    return out


def setup() -> tuple[Clock, RateLimiter, Db, Wake, FailedCheckFlusher]:
    clock = Clock()
    limits = RateLimiter(clock)
    db, wake = Db(), Wake()
    flusher = FailedCheckFlusher(limits, db, wake)  # type: ignore[arg-type]
    return clock, limits, db, wake, flusher


def fail_checks(limits: RateLimiter, ip: str, n: int) -> None:
    for _ in range(n):
        limits.failed_check_blocked(ip)
        limits.record_failed_check(ip)


def test_failed_write_keeps_entries_and_the_next_flush_writes_both_in_order(
    written: list[tuple[str, dict[str, Any]]], caplog: pytest.LogCaptureFixture
) -> None:
    clock, limits, db, wake, flusher = setup()
    fail_checks(limits, "192.0.2.1", 25)  # minute m: over the limit, alert
    clock.at += timedelta(minutes=1)
    db.fail = True
    caplog.set_level(logging.DEBUG)
    flusher.flush()
    assert written == []
    assert limits.size() <= 1  # drained and pruned even though the write failed
    assert "ConnectionError" in caplog.text and "192.0.2.1" not in caplog.text
    fail_checks(limits, "192.0.2.2", 3)  # minute m + 1
    clock.at += timedelta(minutes=1)
    db.fail = False
    flusher.flush()
    kinds = [(k, kw["detail"]["ip"], kw["detail"]["count"]) for k, kw in written]
    assert kinds == [("alert", "192.0.2.1", 25), ("entry", "192.0.2.2", 3)]
    assert written[0][1]["kind"] == "token_check_failures"
    for _, kw in written:
        assert kw["action"] == "auth.token_check_failed" and kw["actor"] == "system"
    assert wake.n == 2
    flusher.flush()
    assert len(written) == 2  # each entry once


def test_failure_in_the_middle_keeps_the_rest_in_order(
    written: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock, limits, db, _, flusher = setup()
    for i in range(5):
        fail_checks(limits, f"198.51.100.{i}", 1)
    clock.at += timedelta(minutes=1)
    calls = {"n": 0}

    def flaky(repo: object, **kw: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("write failed")
        written.append(("entry", kw))

    monkeypatch.setattr(serve_module, "append_entry", flaky)
    flusher.flush()
    assert [kw["detail"]["ip"] for _, kw in written] == ["198.51.100.0", "198.51.100.1"]
    flusher.flush()
    ips = [kw["detail"]["ip"] for _, kw in written]
    assert ips == [f"198.51.100.{i}" for i in range(5)]


def test_at_most_10000_held_oldest_dropped_count_logged_only(
    written: list[tuple[str, dict[str, Any]]], caplog: pytest.LogCaptureFixture
) -> None:
    assert HELD_MAX == 10_000
    clock, limits, db, _, flusher = setup()
    db.fail = True
    canary_ips = []
    total = 0
    for minute in range(11):  # 11 minutes x 1,000 IPs = 11,000 entries
        for i in range(1000):
            ip = f"10.{minute}.{i // 250}.{i % 250}"
            if minute == 0 and i < 3:
                ip = new_canary("ip")
                canary_ips.append(ip)
            fail_checks(limits, ip, 1)
            total += 1
        clock.at += timedelta(minutes=1)
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        flusher.flush()
    assert total == 11_000
    dropped_lines = [
        r.getMessage() for r in caplog.records if "dropped" in r.getMessage()
    ]
    assert dropped_lines == ["failed-check entries dropped: 1000"]
    for ip in canary_ips:
        assert ip not in caplog.text
    db.fail = False
    flusher.flush()
    assert len(written) == 10_000
    first = written[0][1]["detail"]["ip"]
    assert first.startswith("10.1.")  # the oldest minute (minute 0) was dropped
    assert not any(kw["detail"]["ip"] in canary_ips for _, kw in written)
    order = [kw["detail"]["window_start"] for _, kw in written]
    assert order == sorted(order)


def test_final_flush_includes_the_current_minute(
    written: list[tuple[str, dict[str, Any]]],
) -> None:
    clock, limits, _, _, flusher = setup()
    clock.at += timedelta(seconds=30)
    fail_checks(limits, "203.0.113.9", 3)
    flusher.flush()
    assert written == []
    flusher.flush(final=True)
    assert [(kw["detail"]["ip"], kw["detail"]["count"]) for _, kw in written] == [
        ("203.0.113.9", 3)
    ]


def test_the_flusher_thread_survives_a_failed_write(
    written: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(serve_module, "FLUSH_EVERY_S", 0.05)
    clock, limits, db, _, flusher = setup()
    flusher = FailedCheckFlusher(limits, db, Wake())  # type: ignore[arg-type]
    db.fail = True
    flusher.start()
    try:
        fail_checks(limits, "192.0.2.50", 2)
        clock.at += timedelta(minutes=1)
        import time

        time.sleep(0.3)
        db.fail = False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not written:
            time.sleep(0.05)
    finally:
        flusher.stop()
    assert [kw["detail"]["ip"] for _, kw in written] == ["192.0.2.50"]
