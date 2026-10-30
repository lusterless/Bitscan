"""`Idempotency-Key` for `POST /scans` (TS §6.3 L1135, §6.4 L1149; REQ-222;
open question #123).

Per calling user and key, in memory (one manager instance, TS §2.1 L103):
kept 24 h, at most 100,000 entries with the oldest dropped first, lost on
restart (accepted, #123 (c)). A repeat with the same parsed body returns the
first answer; another body raises `KeyReused` (409). A repeat while the
first is still running waits for it (one lock per key), so two concurrent
identical requests run once. Only an answer `call()` returned is kept: a
refusal raises out of `call()` and leaves the key free (#123 (g)).

Only a SHA-256 digest of each body is kept, never the body. Pure apart from
its own locks: no I/O, no logging; the time comes from the given clock.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

KEY_MAX: Final = 255
TTL: Final = timedelta(hours=24)
MAX_ENTRIES: Final = 100_000


class Clock(Protocol):
    def now(self) -> datetime: ...


class InvalidKey(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid request: Idempotency-Key")


class KeyReused(Exception):
    def __init__(self) -> None:
        super().__init__("Idempotency-Key was used with a different request.")


def check_key(value: str) -> str:
    """1–255 printable ASCII characters (#123 (a)), else InvalidKey."""
    if not 1 <= len(value) <= KEY_MAX or not all(" " <= c <= "~" for c in value):
        raise InvalidKey
    return value


def body_digest(body: object) -> bytes:
    """The digest of a parsed JSON body, independent of key order and spacing;
    `1`, `1.0` and `true` stay distinct."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest()


@dataclass(frozen=True, slots=True)
class _Entry[T]:
    digest: bytes
    answer: T
    stored_at: datetime


@dataclass(slots=True)
class _KeyLock:
    lock: threading.Lock
    users: int


class IdempotencyStore[T]:
    """Built once per process. `run()` is safe to call from many threads."""

    def __init__(
        self, clock: Clock, *, ttl: timedelta = TTL, max_entries: int = MAX_ENTRIES
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._max = max_entries
        self._guard = threading.Lock()
        self._entries: OrderedDict[Hashable, _Entry[T]] = OrderedDict()
        self._locks: dict[Hashable, _KeyLock] = {}

    def run(self, user_id: int, key: str, body: object, call: Callable[[], T]) -> T:
        """The remembered answer for (user, key) and the same body, or
        `call()`'s answer, remembered once it returns. `call()` must only
        return after its transaction committed."""
        ident = (user_id, check_key(key))
        digest = body_digest(body)
        key_lock = self._enter(ident)
        try:
            with key_lock.lock:
                entry = self._lookup(ident)
                if entry is not None:
                    if entry.digest != digest:
                        raise KeyReused
                    return entry.answer
                answer = call()
                self._remember(ident, _Entry(digest, answer, self._clock.now()))
                return answer
        finally:
            self._leave(ident)

    def _enter(self, ident: Hashable) -> _KeyLock:
        with self._guard:
            held = self._locks.get(ident)
            if held is None:
                held = self._locks[ident] = _KeyLock(threading.Lock(), 0)
            held.users += 1
            return held

    def _leave(self, ident: Hashable) -> None:
        with self._guard:
            held = self._locks[ident]
            held.users -= 1
            if held.users == 0:
                del self._locks[ident]

    def _expired(self, entry: _Entry[T], now: datetime) -> bool:
        return now - entry.stored_at > self._ttl

    def _lookup(self, ident: Hashable) -> _Entry[T] | None:
        now = self._clock.now()
        with self._guard:
            entry = self._entries.get(ident)
            if entry is not None and self._expired(entry, now):
                del self._entries[ident]
                return None
            return entry

    def _remember(self, ident: Hashable, entry: _Entry[T]) -> None:
        with self._guard:
            self._entries.pop(ident, None)
            self._entries[ident] = entry  # newest last
            while self._entries:  # drop expired entries from the oldest end
                oldest = next(iter(self._entries.values()))
                if not self._expired(oldest, entry.stored_at):
                    break
                self._entries.popitem(last=False)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
