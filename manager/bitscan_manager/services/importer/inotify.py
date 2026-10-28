"""A minimal Linux inotify binding through the stdlib `ctypes` (PD-33 (b)):
`inotify_init1`, `inotify_add_watch` and `inotify_rm_watch` from libc, and
`os.read` on the descriptor. No new package. Anywhere else (no libc, no
inotify symbols, or `inotify_init1` failing) `Inotify()` raises
`InotifyUnavailable`, so the caller can log one line and run without it.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# <sys/inotify.h>; the same values on amd64 and arm64.
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_DONTFOLLOW = 0x02000000
IN_ISDIR = 0x40000000

_HEADER = struct.Struct("iIII")  # wd, mask, cookie, len; then len name bytes
_READ_SIZE = 64 * 1024  # many events per read; the kernel queue is bounded


class InotifyUnavailable(Exception):
    """inotify cannot be used on this system (not Linux, or init failed)."""


@dataclass(frozen=True, slots=True)
class Event:
    wd: int
    mask: int
    name: str  # os.fsdecode of the entry name; "" for events on the folder


def _libc() -> ctypes.CDLL:
    if not sys.platform.startswith("linux"):
        raise InotifyUnavailable("not Linux")
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        init, add, rm = (
            libc.inotify_init1,
            libc.inotify_add_watch,
            libc.inotify_rm_watch,
        )
    except (OSError, AttributeError) as exc:
        raise InotifyUnavailable(type(exc).__name__) from exc
    init.argtypes, init.restype = [ctypes.c_int], ctypes.c_int
    add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    add.restype = ctypes.c_int
    rm.argtypes, rm.restype = [ctypes.c_int, ctypes.c_int], ctypes.c_int
    return libc


class Inotify:
    """One non-blocking, close-on-exec inotify descriptor."""

    def __init__(self) -> None:
        self._libc = _libc()
        fd = int(self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
        if fd < 0:
            raise InotifyUnavailable(os.strerror(ctypes.get_errno()))
        self._fd = fd

    def fileno(self) -> int:
        return self._fd

    def add_watch(self, path: Path, mask: int) -> int:
        """The watch descriptor; OSError (with errno) when the kernel refuses,
        for example ENOTDIR under IN_ONLYDIR or ELOOP under IN_DONTFOLLOW."""
        wd = int(self._libc.inotify_add_watch(self._fd, os.fsencode(path), mask))
        if wd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return wd

    def rm_watch(self, wd: int) -> None:
        """Remove a watch; one the kernel already dropped is not an error."""
        self._libc.inotify_rm_watch(self._fd, wd)

    def read(self) -> list[Event]:
        """The queued events; [] if none are ready (the descriptor is
        non-blocking). An entry name is decoded with os.fsdecode."""
        try:
            buf = os.read(self._fd, _READ_SIZE)
        except BlockingIOError:
            return []
        events: list[Event] = []
        pos = 0
        while pos + _HEADER.size <= len(buf):
            wd, mask, _cookie, size = _HEADER.unpack_from(buf, pos)
            pos += _HEADER.size
            raw = buf[pos : pos + size].split(b"\0", 1)[0]
            pos += size
            events.append(Event(wd, mask, os.fsdecode(raw)))
        return events

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
