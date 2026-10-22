"""On-disk audit queue for sink outages (TS §5.3 L1051, §8.7 L1344).

Records are JSON objects carrying an integer audit_id, appended in audit_id
order to segment files of JSON lines, each line {"crc": n, "record": {...}}
with n the CRC-32 of the canonical record JSON. Every write is fsynced.
A crash can only leave an incomplete last line in the newest segment: that
line is skipped and cut away when the queue is opened. Any other bad line means the
queue is damaged and raises QueueError, so no queued entry is silently lost.
Used by one thread only. Nothing here logs record content.
"""

import json
import logging
import os
import sys
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

SEGMENT_RECORDS: Final = 10_000
_STATE: Final = "state.json"
_ACKED: Final = "acked.json"
_POSIX: Final = os.name == "posix"
_BINARY: Final = getattr(os, "O_BINARY", 0)  # no newline translation on Windows


class QueueError(Exception):
    """The queue folder or a queue file cannot be used safely."""


@dataclass(frozen=True)
class QueueState:
    cursor: int  # highest audit_id read from the database into the queue
    outage_since: datetime | None  # first failed delivery of the current outage
    alerted: bool  # the outage alert has been written


@dataclass
class _Segment:
    path: Path
    ids: list[int]
    end: int  # byte offset after the last valid line


def _canonical(record: Mapping[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode()


def _parse(line: bytes) -> dict[str, Any] | None:
    try:
        item = json.loads(line)
    except ValueError:
        return None
    if not isinstance(item, dict) or not isinstance(item.get("record"), dict):
        return None
    record: dict[str, Any] = item["record"]
    if item.get("crc") != zlib.crc32(_canonical(record)) or not _audit_id_ok(record):
        return None
    return record


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _audit_id_ok(record: Mapping[str, Any]) -> bool:
    return _is_int(record.get("audit_id"))


def _owner_only(fd: int) -> None:
    # os.open's mode applies only when it creates the file; a leftover file
    # (a stale .tmp or segment) keeps its old mode unless it is reset here.
    if sys.platform != "win32":  # Windows has no fchmod and no POSIX modes
        os.fchmod(fd, 0o600)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("audit queue: short write")
        view = view[written:]


class DiskQueue:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        if not folder.exists():
            folder.mkdir(mode=0o700, parents=True)
        if not folder.is_dir():
            raise QueueError(f"audit queue path {folder} is not a folder")
        if _POSIX and folder.stat().st_mode & 0o077:
            raise QueueError(f"audit queue folder {folder} must be mode 0700")
        acked = self._read_json(_ACKED, 0)
        if not _is_int(acked):
            raise QueueError(f"audit queue file {_ACKED} is damaged")
        self._acked = acked
        paths = sorted(folder.glob("segment-*.jsonl"))
        self._segments = [self._scan(p, p == paths[-1]) for p in paths]
        self._drop_acked()

    def _scan(self, path: Path, newest: bool) -> _Segment:
        data = path.read_bytes()
        ids: list[int] = []
        end = 0
        while (newline := data.find(b"\n", end)) != -1:
            record = _parse(data[end:newline])
            if record is None:
                raise QueueError(f"audit queue file {path.name} is damaged")
            ids.append(record["audit_id"])
            end = newline + 1
        if end != len(data):
            if not newest:
                raise QueueError(f"audit queue file {path.name} is damaged")
            log.warning("audit queue: incomplete record at the end of %s", path.name)
            # Cut it now, so a later segment roll-over cannot leave it behind.
            os.truncate(path, end)
        return _Segment(path, ids, end)

    def _records(self) -> list[int]:
        return [i for s in self._segments for i in s.ids if i > self._acked]

    def _sync_folder(self) -> None:
        if _POSIX:
            fd = os.open(self.folder, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def append(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Queue records in audit_id order; ids already queued are skipped."""
        high = max(self._acked, self.last_queued_id() or 0)
        for record in records:
            if not _audit_id_ok(record):
                raise ValueError("a queued record needs an integer audit_id")
            audit_id = int(record["audit_id"])
            if audit_id <= high:
                continue
            body = _canonical(record)
            line = _canonical({"crc": zlib.crc32(body), "record": dict(record)})
            if not self._segments or len(self._segments[-1].ids) >= SEGMENT_RECORDS:
                path = self.folder / f"segment-{audit_id:020d}.jsonl"
                segment = _Segment(path, [], 0)
            else:
                segment = self._segments[-1]
            fd = os.open(segment.path, os.O_WRONLY | os.O_CREAT | _BINARY, 0o600)
            if not self._segments or segment is not self._segments[-1]:
                self._segments.append(segment)
            try:
                _owner_only(fd)
                # Cut any partial line a crash or failed write left behind.
                os.ftruncate(fd, segment.end)
                os.lseek(fd, segment.end, os.SEEK_SET)
                _write_all(fd, line + b"\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            if segment.end == 0:
                self._sync_folder()
            segment.ids.append(audit_id)
            segment.end += len(line) + 1
            high = audit_id

    def peek(self, max_records: int) -> list[dict[str, Any]]:
        """The oldest unacknowledged records, at most max_records."""
        out: list[dict[str, Any]] = []
        if max_records <= 0:
            return out
        for segment in self._segments:
            data = segment.path.read_bytes()[: segment.end]
            for line in data.splitlines():
                record = _parse(line)
                if record is not None and record["audit_id"] > self._acked:
                    out.append(record)
                    if len(out) >= max_records:
                        return out
        return out

    def ack(self, upto_audit_id: int) -> None:
        """Drop every record with audit_id <= upto_audit_id."""
        if upto_audit_id > self._acked:
            self._write_json(_ACKED, upto_audit_id)
            self._acked = upto_audit_id
        self._drop_acked()

    def _drop_acked(self) -> None:
        while self._segments and all(i <= self._acked for i in self._segments[0].ids):
            self._segments.pop(0).path.unlink(missing_ok=True)

    def depth(self) -> int:
        return len(self._records())

    def last_queued_id(self) -> int | None:
        for segment in reversed(self._segments):
            if segment.ids:
                return segment.ids[-1]
        return None

    def load_state(self) -> QueueState:
        raw = self._read_json(_STATE, None)
        if raw is None:
            return QueueState(cursor=0, outage_since=None, alerted=False)
        damaged = QueueError(f"audit queue state file {_STATE} is damaged")
        if not isinstance(raw, dict) or set(raw) != {
            "cursor",
            "outage_since",
            "alerted",
        }:
            raise damaged
        cursor, since, alerted = raw["cursor"], raw["outage_since"], raw["alerted"]
        if not _is_int(cursor) or not isinstance(alerted, bool):
            raise damaged
        outage_since: datetime | None = None
        if since is not None:
            try:
                outage_since = datetime.fromisoformat(since)
            except (TypeError, ValueError) as exc:
                raise damaged from exc
            if outage_since.tzinfo is None:
                raise damaged
        return QueueState(cursor=cursor, outage_since=outage_since, alerted=alerted)

    def save_state(self, state: QueueState) -> None:
        since = state.outage_since
        if since is not None and since.tzinfo is None:
            raise ValueError("outage_since must be timezone-aware")
        self._write_json(
            _STATE,
            {
                "cursor": state.cursor,
                "outage_since": None if since is None else since.isoformat(),
                "alerted": state.alerted,
            },
        )

    def _read_json(self, name: str, default: Any) -> Any:
        path = self.folder / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_bytes())
        except ValueError as exc:
            raise QueueError(f"audit queue file {name} is damaged") from exc

    def _write_json(self, name: str, value: Any) -> None:
        tmp = self.folder / f".{name}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, 0o600)
        try:
            _owner_only(fd)
            _write_all(fd, json.dumps(value).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, self.folder / name)
        self._sync_folder()
