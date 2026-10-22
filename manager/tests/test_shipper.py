"""REQ-053, REQ-054: the audit sink shipper and the outage gate (TASK-034).

Checks CHK-M2-120 to CHK-M2-126, -130 to -133 of tests/m2/test-plan.md (G26).
Expected values: TS §5.3 L1051 (queue on disk while the sink is unreachable,
alert at once, sensitive actions refused after 15 minutes until the queue
drains), TS §8.1 L1256, #51 (committed rows in audit_id order; outage start
kept across restarts; drained = queue empty and cursor caught up; at-least-once
with identical audit_id and row_hash), #50 (audit.sink_unreachable with kind
audit_sink_unreachable; audit.sink_recovered without alert).
A real DiskQueue in tmp_path; fake tail, transport, audit and clock.
"""

import logging
import os
import stat
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bitscan_manager.services.audit.chain import (
    GENESIS_PREV_HASH,
    HashInput,
    compute_row_hash,
)
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.shipper import Shipper
from bitscan_manager.services.audit.sink_transport import DeliveryError, SinkRecord

from .canary import new_canary, sweep

T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
MIN15 = timedelta(minutes=15)
POSIX = os.name == "posix"


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> None:
        self.at += timedelta(**kw)


class Mono:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_records(ids: Sequence[int], detail: str | None = None) -> list[SinkRecord]:
    out = []
    prev = GENESIS_PREV_HASH
    for i in ids:
        at = f"2026-10-21T10:00:00.{i:06d}Z"
        row = compute_row_hash(
            prev, HashInput(i, "user:1", "user.create", None, detail, at)
        )
        out.append(SinkRecord(i, "user:1", "user.create", None, detail, at, prev, row))
        prev = row
    return out


class Tail:
    """Committed rows; `fail` makes entries_after raise (database down)."""

    def __init__(self) -> None:
        self.rows: list[SinkRecord] = []
        self.fail = False
        self.reads = 0

    def commit(self, records: Sequence[SinkRecord]) -> None:
        self.rows.extend(records)

    def entries_after(self, audit_id: int, limit: int) -> list[SinkRecord]:
        self.reads += 1
        if self.fail:
            raise ConnectionError("db down")
        return [r for r in self.rows if r.audit_id > audit_id][:limit]


class Sink:
    """up: accept everything; down: raise; accept_then_fail: take n then raise."""

    def __init__(self) -> None:
        self.up = True
        self.received: list[SinkRecord] = []
        self.accept_before_failing: int | None = None
        self.raise_after_receiving = False
        self.sends = 0
        self.closed = False

    def send(self, records: Sequence[SinkRecord]) -> None:
        self.sends += 1
        if self.raise_after_receiving:  # the sink got them but the ack was lost
            self.received.extend(records)
            raise DeliveryError("ConnectionResetError", 0)
        if not self.up:
            raise DeliveryError("ConnectionRefusedError", 0)
        if self.accept_before_failing is not None:
            n = self.accept_before_failing
            self.received.extend(records[:n])
            if n < len(records):
                raise DeliveryError("HTTP 500", n)
            return
        self.received.extend(records)

    def close(self) -> None:
        self.closed = True


class Audit:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.fail_unreachable = 0

    def unreachable(self) -> None:
        if self.fail_unreachable:
            self.fail_unreachable -= 1
            raise ConnectionError("db down")
        self.events.append("unreachable")

    def recovered(self) -> None:
        self.events.append("recovered")


class World:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.clock, self.mono = Clock(), Mono()
        self.tail, self.sink, self.audit = Tail(), Sink(), Audit()
        self.shipper = self.new_shipper()

    def new_shipper(self) -> Shipper:
        return Shipper(
            self.tail,
            DiskQueue(self.folder),
            self.sink,
            self.clock,
            self.audit,
            monotonic=self.mono,
        )

    def restart(self) -> None:
        self.shipper = self.new_shipper()

    def cycle(self, n: int = 1, step_s: float = 31) -> None:
        """Run n cycles, moving the clock past any back-off between them."""
        for _ in range(n):
            self.shipper.run_once()
            self.clock.advance(seconds=step_s)


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path / "audit-queue")


def ids(records: Sequence[SinkRecord]) -> list[int]:
    return [r.audit_id for r in records]


# ------------------------------------------------------------ CHK-M2-120


def test_sends_committed_entries_in_order_once(w: World) -> None:
    w.tail.commit(make_records([1, 2, 5, 9]))  # gaps from rolled-back appends
    w.cycle()
    w.tail.commit(make_records([10, 11]))
    w.cycle()
    w.cycle()
    assert ids(w.sink.received) == [1, 2, 5, 9, 10, 11]
    assert w.shipper.refusing() is False
    assert w.audit.events == []
    assert DiskQueue(w.folder).depth() == 0


def test_large_backlog_goes_out_in_batches_in_order(w: World) -> None:
    w.tail.commit(make_records(range(1, 1203)))
    for _ in range(5):
        w.cycle()
    assert ids(w.sink.received) == list(range(1, 1203))


def test_records_reach_the_sink_unchanged(w: World) -> None:
    records = make_records([1, 2, 3], detail='{"note": "é"}')
    w.tail.commit(records)
    w.cycle()
    assert w.sink.received == records


# ------------------------------------------------------------ CHK-M2-121


def test_sink_down_queues_on_disk_and_a_restart_delivers(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1, 2, 3]))
    w.cycle(3)
    assert w.sink.received == []
    assert [r["audit_id"] for r in DiskQueue(w.folder).peek(10)] == [1, 2, 3]
    w.tail.rows.clear()  # after a restart only the disk queue holds them
    w.restart()
    w.sink.up = True
    w.cycle(2)
    assert ids(w.sink.received) == [1, 2, 3]
    assert DiskQueue(w.folder).depth() == 0


# ------------------------------------------------------------ CHK-M2-122


def test_one_alert_per_outage_at_the_first_failed_delivery(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    assert w.audit.events == ["unreachable"]  # at once, at the first failure
    w.cycle(100)
    assert w.audit.events == ["unreachable"]
    w.sink.up = True
    w.cycle(2)
    assert w.audit.events == ["unreachable", "recovered"]
    w.sink.up = False
    w.tail.commit(make_records([2]))
    w.cycle(3)
    assert w.audit.events == ["unreachable", "recovered", "unreachable"]


def test_alert_retried_when_its_write_fails_then_written_once(w: World) -> None:
    w.sink.up = False
    w.audit.fail_unreachable = 2
    w.tail.commit(make_records([1]))
    w.cycle(5)
    assert w.audit.events == ["unreachable"]


def test_alert_not_repeated_after_a_restart_during_the_outage(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.cycle(2)
    w.restart()
    w.cycle(5)
    assert w.audit.events == ["unreachable"]


# ------------------------------------------------------------ CHK-M2-123


def test_refusing_at_exactly_15_minutes(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()  # first failed delivery at T0
    first = w.clock.now()
    assert w.shipper.refusing() is False
    w.clock.at = first + MIN15 - timedelta(microseconds=1)
    assert w.shipper.refusing() is False
    w.clock.at = first + MIN15 - timedelta(seconds=1)
    assert w.shipper.refusing() is False
    w.clock.at = first + MIN15
    assert w.shipper.refusing() is True
    w.clock.at = first + timedelta(hours=5)
    assert w.shipper.refusing() is True


def test_outage_measured_from_the_first_failure_not_the_latest(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    first = w.clock.now()
    for _ in range(30):  # many failures over 15 minutes
        w.cycle(1, step_s=30)
    w.clock.at = first + MIN15
    assert w.shipper.refusing() is True


# ------------------------------------------------------------ CHK-M2-124


def test_refusing_stays_until_queue_empty_and_cursor_caught_up(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records(range(1, 1201)))  # more than one batch of 500
    w.shipper.run_once()
    w.clock.advance(minutes=16)
    assert w.shipper.refusing() is True
    w.sink.up = True
    w.sink.accept_before_failing = 300  # one partial batch then failure
    w.shipper.run_once()
    assert ids(w.sink.received) == list(range(1, 301))
    assert w.shipper.refusing() is True  # a partial success does not end it
    w.sink.accept_before_failing = None
    w.clock.advance(seconds=31)
    w.shipper.run_once()  # 500 read in, 700 still unread in audit_log
    w.clock.advance(seconds=31)
    # all 1,200 have been read and sent by now, so the outage may end
    assert set(ids(w.sink.received)) == set(range(1, 1201))
    for _ in range(5):
        w.cycle()
    assert ids(w.sink.received) == list(range(1, 1201))
    assert w.shipper.refusing() is False
    assert w.audit.events == ["unreachable", "recovered"]


def test_full_batch_read_means_not_caught_up_even_with_an_empty_queue(
    w: World,
) -> None:
    """Exactly 500 rows read (a full batch) and all sent: the queue is empty,
    but more may be unread, so the outage must not end on that cycle."""
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    w.clock.advance(minutes=16)
    w.sink.up = True
    w.cycle()  # sends 1; queue empty, caught up: outage ends
    assert w.shipper.refusing() is False
    w.sink.up = False
    w.tail.commit(make_records(range(2, 502)))  # exactly 500 new rows
    w.shipper.run_once()
    w.clock.advance(minutes=16)
    w.sink.up = True
    w.shipper.run_once()  # reads 0 new (all 500 queued before), sends 500
    assert DiskQueue(w.folder).depth() == 0
    assert w.shipper.refusing() is False  # the read returned < 500: caught up


def test_queue_empty_but_read_not_caught_up_keeps_refusing(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    w.clock.advance(minutes=16)
    w.sink.up = True
    w.tail.fail = True  # database down: the cursor cannot be confirmed caught up
    w.cycle(3)
    assert ids(w.sink.received) == [1]
    assert w.shipper.refusing() is True
    assert "recovered" not in w.audit.events
    w.tail.fail = False
    w.cycle(2)
    assert w.shipper.refusing() is False


# ------------------------------------------------------------ CHK-M2-125


def test_restart_does_not_reset_the_15_minute_clock(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    first = w.clock.now()
    w.clock.at = first + timedelta(minutes=10)
    w.restart()
    w.shipper.run_once()
    w.clock.at = first + MIN15 - timedelta(seconds=1)
    assert w.shipper.refusing() is False
    w.clock.at = first + MIN15
    assert w.shipper.refusing() is True  # 15 min after the ORIGINAL failure
    w.restart()
    assert w.shipper.refusing() is True  # straight after a restart too


# ------------------------------------------------------------ CHK-M2-126


def test_record_leaves_the_queue_only_after_the_sink_accepted(w: World) -> None:
    w.tail.commit(make_records([1, 2]))
    w.sink.raise_after_receiving = True
    w.cycle()
    assert [r["audit_id"] for r in DiskQueue(w.folder).peek(10)] == [1, 2]
    w.sink.raise_after_receiving = False
    w.cycle()
    assert DiskQueue(w.folder).depth() == 0
    assert ids(w.sink.received) == [1, 2, 1, 2]  # at-least-once: resent
    first, again = w.sink.received[:2], w.sink.received[2:]
    assert [(r.audit_id, r.row_hash) for r in first] == [
        (r.audit_id, r.row_hash) for r in again
    ]


def test_partial_delivery_acknowledges_only_the_accepted_prefix(w: World) -> None:
    w.tail.commit(make_records([1, 2, 3, 4]))
    w.sink.accept_before_failing = 2
    w.cycle()
    assert [r["audit_id"] for r in DiskQueue(w.folder).peek(10)] == [3, 4]
    w.sink.accept_before_failing = None
    w.cycle()
    assert ids(w.sink.received) == [1, 2, 3, 4]  # no duplicate of the acked prefix


# ------------------------------------------------------------ CHK-M2-130


def test_crash_between_queue_and_send_loses_nothing(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1, 2, 3]))
    w.shipper.run_once()  # queued and cursor saved, send failed: "crash" now
    w.restart()
    w.sink.up = True
    w.cycle(2)
    assert ids(w.sink.received) == [1, 2, 3]


def test_crash_after_queueing_before_cursor_save_reads_again_without_duplicates(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1, 2]))

    def crash(self: DiskQueue, state: object) -> None:
        raise RuntimeError("crash before the cursor is saved")

    monkeypatch.setattr(DiskQueue, "save_state", crash)
    with pytest.raises(RuntimeError):
        w.shipper.run_once()
    monkeypatch.undo()
    w.restart()  # cursor still 0: the same rows are read again
    w.sink.up = True
    w.cycle(2)
    assert ids(w.sink.received) == [1, 2]


# ------------------------------------------------------------ CHK-M2-131


def test_database_down_while_sink_up_is_not_an_outage(w: World) -> None:
    w.tail.fail = True
    w.cycle(40, step_s=30)  # 20 minutes
    assert w.shipper.refusing() is False
    assert w.audit.events == []


def test_queued_records_still_go_out_while_the_database_is_down(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1, 2]))
    w.shipper.run_once()
    w.tail.fail = True
    w.sink.up = True
    w.cycle(2)
    assert ids(w.sink.received) == [1, 2]


def test_disk_queue_write_failure_is_an_outage(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(self: DiskQueue, records: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(DiskQueue, "append", full)
    w.tail.commit(make_records([1]))
    w.shipper.run_once()
    assert w.audit.events == ["unreachable"]
    w.clock.advance(minutes=15)
    assert w.shipper.refusing() is True
    assert w.sink.received == []  # nothing is sent that was not queued first


def test_backoff_doubles_to_30_seconds(w: World) -> None:
    w.sink.up = False
    w.tail.commit(make_records([1]))
    gaps: list[float] = []
    last = None
    for _ in range(400):
        before = w.sink.sends
        w.shipper.run_once()
        if w.sink.sends > before:
            if last is not None:
                gaps.append((w.clock.now() - last).total_seconds())
            last = w.clock.now()
        w.clock.advance(seconds=0.5)
    assert gaps[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
    assert set(gaps[6:]) == {30.0}


def test_one_attempt_is_bounded_by_the_monotonic_deadline(w: World) -> None:
    """Ten batches queued while the sink was down; each send then takes 10 s of
    monotonic time, so one attempt sends at most 3 batches (30 s budget)."""

    class SlowSink(Sink):
        def __init__(self, mono: Mono) -> None:
            super().__init__()
            self.mono = mono

        def send(self, records: Sequence[SinkRecord]) -> None:
            self.mono.t += 10
            super().send(records)

    w.sink.up = False
    w.tail.commit(make_records(range(1, 5001)))
    for _ in range(12):  # read all 5,000 into the disk queue while down
        w.cycle()
    assert DiskQueue(w.folder).depth() == 5000
    w.sink = SlowSink(w.mono)
    w.restart()
    w.clock.advance(seconds=60)
    w.shipper.run_once()
    assert 1 <= w.sink.sends <= 4
    assert len(w.sink.received) <= 4 * 500
    assert DiskQueue(w.folder).depth() >= 5000 - 4 * 500


# ------------------------------------------------------------ CHK-M2-132


def test_logs_hold_counts_and_ids_only(
    w: World, caplog: pytest.LogCaptureFixture
) -> None:
    secret = new_canary("detail")
    caplog.set_level(logging.DEBUG)
    w.tail.commit(make_records([1, 2], detail=f'{{"x": "{secret}"}}'))
    w.cycle()
    w.sink.up = False
    w.tail.commit(make_records([3], detail=f'{{"x": "{secret}"}}'))
    w.cycle(2)
    assert sweep([secret, "user.create", "user:1"], caplog.text) == []


# ------------------------------------------------------------ CHK-M2-133


@pytest.mark.skipif(not POSIX, reason="not run: Linux only (POSIX modes)")
@pytest.mark.parametrize("umask", [0o000, 0o022])
def test_stale_temp_and_segment_files_end_owner_only(
    tmp_path: Path, umask: int
) -> None:
    folder = tmp_path / "q"
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    old = os.umask(umask)
    try:
        for name in (".state.json.tmp", ".acked.json.tmp"):
            (folder / name).write_text("stale")
            os.chmod(folder / name, 0o666 if umask == 0 else 0o644)
        seg = folder / f"segment-{1:020d}.jsonl"
        seg.write_text("")
        os.chmod(seg, 0o644)
        q = DiskQueue(folder)
        q.append([{"audit_id": 1}, {"audit_id": 2}])
        q.ack(1)
        q.save_state(q.load_state())
    finally:
        os.umask(old)
    for p in folder.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p.name
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


# ------------------------------------------------- thread lifecycle (SinkGate)


def test_start_wake_stop(w: World) -> None:
    import time

    w.shipper.start()
    try:
        w.tail.commit(make_records([1]))
        w.shipper.wake()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not w.sink.received:
            time.sleep(0.02)
        assert ids(w.sink.received) == [1]
    finally:
        w.shipper.stop(timeout_s=5)
    assert w.sink.closed is True


def test_a_failing_cycle_does_not_kill_the_thread(w: World) -> None:
    import time

    w.restart()
    calls = {"n": 0}
    real = w.shipper.run_once

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("cycle failed")
        real()

    w.shipper.run_once = flaky  # type: ignore[method-assign]
    w.shipper.start()
    try:
        w.tail.commit(make_records([1]))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not w.sink.received:
            w.shipper.wake()
            time.sleep(0.05)
        assert ids(w.sink.received) == [1]
    finally:
        w.shipper.stop(timeout_s=5)


# ------------------------------- revision 1 (review finding 1): fail closed


def _drive_15_minutes(w: World) -> None:
    first = w.clock.now()
    for _ in range(40):
        w.shipper.run_once()
        w.clock.advance(seconds=30)
    w.clock.at = first + MIN15


def test_unwrapped_transport_error_is_an_outage(w: World) -> None:
    class Broken(Sink):
        def send(self, records: Sequence[SinkRecord]) -> None:
            self.sends += 1
            raise RuntimeError("unwrapped transport error")

    w.sink = Broken()
    w.restart()
    w.tail.commit(make_records([1, 2]))
    _drive_15_minutes(w)
    assert w.audit.events == ["unreachable"]
    assert w.shipper.refusing() is True
    assert [r["audit_id"] for r in DiskQueue(w.folder).peek(10)] == [1, 2]


@pytest.mark.parametrize("where", ["ack", "peek"])
def test_queue_error_during_send_is_an_outage(
    w: World, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    def disk_full(self: DiskQueue, *args: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(DiskQueue, where, disk_full)
    w.tail.commit(make_records([1, 2]))
    _drive_15_minutes(w)
    assert w.audit.events == ["unreachable"]
    assert w.shipper.refusing() is True


def test_state_file_that_cannot_be_written_does_not_open_the_gate(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(self: DiskQueue, state: object) -> None:
        raise OSError(28, "No space left on device")

    w.sink.up = False
    monkeypatch.setattr(DiskQueue, "save_state", disk_full)
    w.tail.commit(make_records([1]))
    _drive_15_minutes(w)
    assert w.audit.events == ["unreachable"]
    assert w.shipper.refusing() is True
