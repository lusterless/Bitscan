"""REQ-054 (1), (5), (6): the audit disk queue (TASK-033, revision 1).

Checks CHK-M2-110 to CHK-M2-115 of tests/m2/test-plan.md. TS §5.3 L1051 (queue
on disk while the sink is down), TS §8.7 L1344 (folder 0700), #51 (c) (the
outage start is kept in the queue folder).
"""

import json
import logging
import os
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.services.audit import disk_queue as dq
from bitscan_manager.services.audit.disk_queue import DiskQueue, QueueError, QueueState

POSIX = os.name == "posix"
linux_only = pytest.mark.skipif(not POSIX, reason="not run: Linux only (POSIX modes)")
CANARY = "CANARY-7f3a9c1e5b2d4086"


def rec(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "audit_id": i,
        "actor": "user:1",
        "action": "user.create",
        "target": None if i % 2 else f"user:{i}",
        "detail": {"note": "é\n \"'\\", "n": i, "secret": CANARY},
        "at": "2026-10-21T10:00:00.000000Z",
        "prev_hash": "0" * 64,
        "row_hash": f"{i:064x}",
        **extra,
    }


def ids(records: list[dict[str, Any]]) -> list[int]:
    return [r["audit_id"] for r in records]


def segments(folder: Path) -> list[Path]:
    return sorted(folder.glob("segment-*.jsonl"))


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "audit-queue"


@pytest.fixture
def small_segments(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(dq, "SEGMENT_RECORDS", 3)
    yield


# ------------------------------------------------- CHK-M2-110 order, restart


def test_records_come_back_unchanged_in_append_order(folder: Path) -> None:
    q = DiskQueue(folder)
    batch = [rec(i) for i in (1, 2, 5, 9, 10)]
    q.append(batch[:2])
    q.append(batch[2:])
    assert q.peek(100) == batch
    assert q.depth() == 5
    assert q.last_queued_id() == 10


def test_order_survives_recreation(folder: Path) -> None:
    DiskQueue(folder).append([rec(i) for i in range(1, 8)])
    again = DiskQueue(folder)
    assert ids(again.peek(100)) == list(range(1, 8))
    assert again.peek(100) == [rec(i) for i in range(1, 8)]


def test_order_across_segment_rollover_and_recreation(
    folder: Path, small_segments: None
) -> None:
    q = DiskQueue(folder)
    for i in range(1, 26):
        q.append([rec(i)])
    assert len(segments(folder)) == 9  # 3 per segment
    assert ids(DiskQueue(folder).peek(1000)) == list(range(1, 26))


def test_peek_limits_and_returns_the_oldest(folder: Path) -> None:
    q = DiskQueue(folder)
    q.append([rec(i) for i in range(1, 6)])
    assert ids(q.peek(2)) == [1, 2]
    assert ids(q.peek(5)) == [1, 2, 3, 4, 5]
    assert ids(q.peek(50)) == [1, 2, 3, 4, 5]


def test_peek_zero_returns_nothing(folder: Path) -> None:
    """Docstring contract: "at most max_records"."""
    q = DiskQueue(folder)
    q.append([rec(1), rec(2)])
    assert q.peek(0) == []


def test_ids_at_or_below_the_last_queued_are_skipped(folder: Path) -> None:
    """A re-read after a crash (append done, cursor not saved) adds no duplicate."""
    q = DiskQueue(folder)
    q.append([rec(1), rec(2), rec(3)])
    q.append([rec(2), rec(3), rec(4)])
    assert ids(DiskQueue(folder).peek(100)) == [1, 2, 3, 4]


@pytest.mark.parametrize("bad", [None, "7", 7.0, True, False])
def test_record_without_integer_audit_id_is_refused(folder: Path, bad: object) -> None:
    q = DiskQueue(folder)
    with pytest.raises(ValueError):
        q.append([{"audit_id": bad}])
    with pytest.raises(ValueError):
        q.append([{"actor": "x"}])
    assert q.depth() == 0


def test_empty_queue(folder: Path) -> None:
    q = DiskQueue(folder)
    assert q.peek(10) == []
    assert q.depth() == 0
    assert q.last_queued_id() is None
    assert folder.is_dir()


def test_path_that_is_a_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "audit-queue"
    path.write_text("x")
    with pytest.raises(QueueError):
        DiskQueue(path)


# ------------------------------------------------------ CHK-M2-111 ack


def test_acknowledged_records_are_not_returned_again(folder: Path) -> None:
    q = DiskQueue(folder)
    q.append([rec(i) for i in range(1, 6)])
    q.ack(2)
    assert ids(q.peek(10)) == [3, 4, 5]
    assert q.depth() == 3
    assert ids(DiskQueue(folder).peek(10)) == [3, 4, 5]


def test_ack_lower_than_before_changes_nothing(folder: Path) -> None:
    q = DiskQueue(folder)
    q.append([rec(i) for i in range(1, 6)])
    q.ack(3)
    q.ack(1)
    assert ids(DiskQueue(folder).peek(10)) == [4, 5]


def test_ack_beyond_the_tail_empties_the_queue(
    folder: Path, small_segments: None
) -> None:
    q = DiskQueue(folder)
    for i in range(1, 8):
        q.append([rec(i)])
    q.ack(10**9)
    assert q.depth() == 0
    assert q.peek(10) == []
    assert segments(folder) == []
    again = DiskQueue(folder)
    assert again.depth() == 0
    again.append([rec(5), rec(10**9), rec(10**9 + 1)])
    assert ids(again.peek(10)) == [10**9 + 1]


def test_fully_acked_segments_are_deleted(folder: Path, small_segments: None) -> None:
    q = DiskQueue(folder)
    for i in range(1, 10):
        q.append([rec(i)])
    assert len(segments(folder)) == 3
    q.ack(4)  # first segment (1-3) fully acked, second (4-6) partly
    assert [p.name for p in segments(folder)] == [
        f"segment-{4:020d}.jsonl",
        f"segment-{7:020d}.jsonl",
    ]
    assert ids(q.peek(10)) == [5, 6, 7, 8, 9]


def test_crash_between_ack_write_and_segment_delete_is_cleaned_up(
    folder: Path, small_segments: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = DiskQueue(folder)
    for i in range(1, 7):
        q.append([rec(i)])

    def boom(self: Path, missing_ok: bool = False) -> None:
        raise RuntimeError("crash")

    monkeypatch.setattr(Path, "unlink", boom)
    with pytest.raises(RuntimeError):
        q.ack(3)
    monkeypatch.undo()
    assert len(segments(folder)) == 2
    again = DiskQueue(folder)
    assert len(segments(folder)) == 1
    assert ids(again.peek(10)) == [4, 5, 6]


# ---------------------------------------------- CHK-M2-112 cut-off record


def _last_line_span(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    start = data.rstrip(b"\n").rfind(b"\n") + 1
    return start, len(data)


def test_cut_off_at_every_offset_of_the_last_record(folder: Path) -> None:
    """REQ-054 (6): earlier records come back, the cut one never does."""
    q = DiskQueue(folder)
    q.append([rec(i) for i in range(1, 4)])
    (path,) = segments(folder)
    whole = path.read_bytes()
    start, end = _last_line_span(path)
    assert end - start > 100
    for cut in range(start + 1, end):  # every offset inside the last line
        path.write_bytes(whole[:cut])
        again = DiskQueue(folder)
        assert ids(again.peek(10)) == [1, 2], cut
        assert path.read_bytes() == whole[:start], cut  # tail cut at open
        assert again.last_queued_id() == 2
    path.write_bytes(whole)


def test_after_a_cut_the_next_append_is_readable(folder: Path) -> None:
    q = DiskQueue(folder)
    q.append([rec(1), rec(2)])
    (path,) = segments(folder)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) - 20])
    again = DiskQueue(folder)
    again.append([rec(2), rec(3)])  # 2 was lost in the crash and is re-queued
    assert ids(DiskQueue(folder).peek(10)) == [1, 2, 3]


def test_cut_off_tail_without_newline_but_complete_json_is_not_returned(
    folder: Path,
) -> None:
    q = DiskQueue(folder)
    q.append([rec(1), rec(2)])
    (path,) = segments(folder)
    path.write_bytes(path.read_bytes()[:-1])  # drop only the final "\n"
    assert ids(DiskQueue(folder).peek(10)) == [1]


def test_cut_off_warning_names_the_file_only(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    q = DiskQueue(folder)
    q.append([rec(1), rec(2)])
    (path,) = segments(folder)
    path.write_bytes(path.read_bytes()[:-30])
    with caplog.at_level(logging.DEBUG):
        DiskQueue(folder)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert path.name in text
    assert CANARY not in text
    assert "user.create" not in text


@pytest.mark.parametrize(
    "damage",
    ["crc", "json", "shape", "audit_id_type", "record_edited"],
)
def test_newline_terminated_damage_raises_and_touches_nothing(
    folder: Path, damage: str
) -> None:
    q = DiskQueue(folder)
    q.append([rec(i) for i in range(1, 6)])
    (path,) = segments(folder)
    lines = path.read_bytes().split(b"\n")
    item = json.loads(lines[1])
    if damage == "crc":
        item["crc"] += 1
        lines[1] = json.dumps(item).encode()
    elif damage == "json":
        lines[1] = lines[1][:-5] + b"#####"
    elif damage == "shape":
        lines[1] = json.dumps([item]).encode()
    elif damage == "audit_id_type":
        item["record"]["audit_id"] = "2"
        lines[1] = json.dumps(item).encode()
    else:
        item["record"]["actor"] = "user:666"
        lines[1] = json.dumps(item).encode()
    damaged = b"\n".join(lines)
    path.write_bytes(damaged)
    with pytest.raises(QueueError):
        DiskQueue(folder)
    assert path.read_bytes() == damaged


def test_incomplete_tail_in_an_older_segment_raises(
    folder: Path, small_segments: None
) -> None:
    q = DiskQueue(folder)
    for i in range(1, 6):
        q.append([rec(i)])
    first = segments(folder)[0]
    data = first.read_bytes()
    first.write_bytes(data[:-10])
    with pytest.raises(QueueError):
        DiskQueue(folder)


@pytest.mark.parametrize("content", [b"true", b'"5"', b"{", b"5.0"])
def test_damaged_ack_file_raises(folder: Path, content: bytes) -> None:
    DiskQueue(folder).append([rec(1)])
    (folder / "acked.json").write_bytes(content)
    with pytest.raises(QueueError):
        DiskQueue(folder)


# --------------------------------------------------------- CHK-M2-114 state


def test_state_defaults_when_missing(folder: Path) -> None:
    assert DiskQueue(folder).load_state() == QueueState(0, None, False)


@pytest.mark.parametrize(
    "since",
    [
        None,
        datetime(2026, 10, 21, 10, 0, 0, 123456, tzinfo=UTC),
        datetime(2026, 10, 21, 18, 0, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_state_round_trips_across_recreation(
    folder: Path, since: datetime | None
) -> None:
    DiskQueue(folder).save_state(
        QueueState(cursor=42, outage_since=since, alerted=True)
    )
    loaded = DiskQueue(folder).load_state()
    assert loaded == QueueState(cursor=42, outage_since=since, alerted=True)
    if since is not None:
        assert loaded.outage_since is not None
        assert loaded.outage_since.utcoffset() is not None


def test_naive_outage_since_is_refused(folder: Path) -> None:
    q = DiskQueue(folder)
    with pytest.raises(ValueError):
        q.save_state(QueueState(1, datetime(2026, 10, 21), False))  # noqa: DTZ001
    assert q.load_state() == QueueState(0, None, False)


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b'{"cursor": 1, "outage_since": null}',
        b'{"cursor": 1, "outage_since": null, "alerted": false, "x": 1}',
        b'{"cursor": true, "outage_since": null, "alerted": false}',
        b'{"cursor": "1", "outage_since": null, "alerted": false}',
        b'{"cursor": 1, "outage_since": null, "alerted": 0}',
        b'{"cursor": 1, "outage_since": "yesterday", "alerted": false}',
        b'{"cursor": 1, "outage_since": "2026-10-21T10:00:00", "alerted": false}',
        b'{"cursor": 1, "outage_since": 5, "alerted": false}',
    ],
)
def test_damaged_state_raises_never_resets(folder: Path, raw: bytes) -> None:
    """#51 (c): a damaged state must not silently restart the outage clock."""
    q = DiskQueue(folder)
    (folder / "state.json").write_bytes(raw)
    with pytest.raises(QueueError):
        q.load_state()


def test_state_write_is_atomic(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    q = DiskQueue(folder)
    old = QueueState(7, datetime(2026, 10, 21, tzinfo=UTC), True)
    q.save_state(old)

    def crash(src: object, dst: object) -> None:
        raise RuntimeError("crash before rename")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(RuntimeError):
        q.save_state(QueueState(8, None, False))
    monkeypatch.undo()
    assert DiskQueue(folder).load_state() == old


# ------------------------------------------------- CHK-M2-115 durability


def test_every_append_is_fsynced(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    q = DiskQueue(folder)
    calls: list[int] = []
    real = os.fsync

    def spy(fd: int) -> None:
        calls.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    q.append([rec(1), rec(2), rec(3)])
    assert len(calls) >= 3
    before = len(calls)
    q.ack(1)
    assert len(calls) > before


def test_short_writes_are_retried(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.write

    def one_byte(fd: int, data: bytes | memoryview) -> int:
        return real(fd, bytes(data[:1]))

    monkeypatch.setattr(os, "write", one_byte)
    DiskQueue(folder).append([rec(1), rec(2)])
    DiskQueue(folder).save_state(QueueState(2, None, False))
    monkeypatch.undo()
    again = DiskQueue(folder)
    assert again.peek(10) == [rec(1), rec(2)]
    assert again.load_state() == QueueState(2, None, False)


def test_zero_byte_write_raises_and_queues_nothing(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = DiskQueue(folder)
    q.append([rec(1)])
    real = os.write
    state = {"n": 0}

    def flaky(fd: int, data: bytes | memoryview) -> int:
        state["n"] += 1
        if state["n"] == 1:
            return real(fd, bytes(data[:10]))  # partial bytes, then the disk is full
        return 0

    monkeypatch.setattr(os, "write", flaky)
    with pytest.raises(OSError):
        q.append([rec(2)])
    monkeypatch.undo()
    assert q.depth() == 1
    q.append([rec(2), rec(3)])  # the partial bytes are cut before the write
    assert ids(DiskQueue(folder).peek(10)) == [1, 2, 3]


# ------------------------------------------- CHK-M2-113 permissions (Linux)


@linux_only
@pytest.mark.parametrize("umask", [0o000, 0o022, 0o077])
def test_folder_0700_and_files_0600_under_any_umask(tmp_path: Path, umask: int) -> None:
    folder = tmp_path / "q"
    old = os.umask(umask)
    try:
        q = DiskQueue(folder)
        q.append([rec(1), rec(2)])
        q.ack(1)
        q.save_state(QueueState(2, datetime(2026, 10, 21, tzinfo=UTC), True))
    finally:
        os.umask(old)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    files = sorted(folder.iterdir())
    names = {p.name for p in files}
    assert {"acked.json", "state.json"} <= names
    assert any(n.startswith("segment-") for n in names)
    for p in files:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p.name


@linux_only
@pytest.mark.parametrize("mode", [0o750, 0o770, 0o701, 0o707, 0o755, 0o777])
def test_existing_folder_with_group_or_other_bits_is_refused(
    tmp_path: Path, mode: int
) -> None:
    folder = tmp_path / "q"
    folder.mkdir()
    os.chmod(folder, mode)
    with pytest.raises(QueueError):
        DiskQueue(folder)


@linux_only
def test_existing_0700_folder_is_accepted(tmp_path: Path) -> None:
    folder = tmp_path / "q"
    folder.mkdir()
    os.chmod(folder, 0o700)
    DiskQueue(folder).append([rec(1)])
    assert ids(DiskQueue(folder).peek(5)) == [1]
