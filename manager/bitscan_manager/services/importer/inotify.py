"""Linux inotify through the standard library (PD-33 (b): `ctypes` for
`inotify_init1` and `inotify_add_watch`, `os.read` for the events; TS §4.1
L528). Linux only: `available()` is False elsewhere, and constructing
`Inotify` there raises OSError. The constants are the Linux ABI values.
"""

from __future__ import annotations

import ctypes
import os
import select
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

IN_CLOSE_WRITE: Final = 0x00000008
IN_MOVED_FROM: Final = 0x00000040
IN_MOVED_TO: Final = 0x00000080
IN_CREATE: Final = 0x00000100
IN_DELETE: Final = 0x00000200
IN_DELETE_SELF: Final = 0x00000400
IN_MOVE_SELF: Final = 0x00000800
IN_Q_OVERFLOW: Final = 0x00004000
IN_IGNORED: Final = 0x00008000
IN_ONLYDIR: Final = 0x01000000
IN_DONT_FOLLOW: Final = 0x02000000
IN_EXCL_UNLINK: Final = 0x04000000
IN_ISDIR: Final = 0x40000000
_IN_NONBLOCK: Final = 0o4000  # O_NONBLOCK
_IN_CLOEXEC: Final = 0o2000000  # O_CLOEXEC
_HEADER: Final = struct.Struct("iIII")  # wd, mask, cookie, len
_BUFFER: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class Event:
    wd: int  # -1 for IN_Q_OVERFLOW
    mask: int
    name: str  # os.fsdecode of the entry name; "" for the folder itself


def available() -> bool:
    return sys.platform.startswith("linux")


class Inotify:
    """One non-blocking, close-on-exec inotify descriptor."""

    def __init__(self) -> None:
        if not available():
            raise OSError("inotify is Linux only")
        self._libc = ctypes.CDLL(None, use_errno=True)
        fd = int(self._libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC))
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self._fd = fd

    def add_watch(self, path: Path, mask: int) -> int:
        """Watch a folder (or update its mask); the watch descriptor."""
        wd = int(self._libc.inotify_add_watch(self._fd, os.fsencode(path), mask))
        if wd < 0:
            raise OSError(ctypes.get_errno(), "inotify_add_watch failed")
        return wd

    def read(self, timeout: float) -> list[Event]:
        """The events queued now, waiting at most `timeout` seconds."""
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return []
        try:
            buf = os.read(self._fd, _BUFFER)
        except BlockingIOError:
            return []
        events, offset = [], 0
        while offset + _HEADER.size <= len(buf):
            wd, mask, _cookie, size = _HEADER.unpack_from(buf, offset)
            start = offset + _HEADER.size
            raw = buf[start : start + size].split(b"\0", 1)[0]
            events.append(Event(wd, mask, os.fsdecode(raw)))
            offset = start + size
        return events

    def close(self) -> None:
        os.close(self._fd)
