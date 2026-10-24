"""In-memory threshold windows for the TS §8.4 L1291 alerts (#61, #65, #66).

One manager instance (TS §2.1 L103), so the counts live in this process and
reset on restart (accepted, #65). Every time comes from the Clock. Each class
only answers "raise the alert now?"; the caller writes it with raise_alert.

- SlidingCount: events per key in a sliding window; fires when the count goes
  above the threshold, then at most once per period per key (#61, #65 (d),
  (e), (f)).
- OncePerPeriod: fires at most once per period per key (#65 (a), #66).
- ReArm: fires when a condition becomes true, and again only after it was
  false in between (#65 (b), (c), (g)).
"""

import threading
from collections import deque
from collections.abc import Hashable, Iterable
from datetime import datetime, timedelta

from bitscan_manager.runtime import Clock


class SlidingCount[K: Hashable]:
    def __init__(
        self, clock: Clock, window: timedelta, period: timedelta, threshold: int
    ) -> None:
        self._clock = clock
        self._window = window
        self._period = period
        self._threshold = threshold
        self._lock = threading.Lock()
        self._events: dict[K, deque[tuple[datetime, int]]] = {}
        self._totals: dict[K, int] = {}
        self._fired: dict[K, datetime] = {}
        self._pruned_at: datetime | None = None

    def add(self, key: K, weight: int = 1, threshold: int | None = None) -> bool:
        """Count weight events for key now; True when the alert is due, which
        is then recorded at once. threshold overrides the constructor's value
        (a runtime setting)."""
        due = self.count_and_check(key, weight, threshold)
        if due:
            self.mark_fired(key)
        return due

    def count_and_check(
        self, key: K, weight: int = 1, threshold: int | None = None
    ) -> bool:
        """As add(), but nothing is marked: the caller calls mark_fired(key)
        once its alert entry has committed, so a rolled-back alert leaves the
        period free (lead ruling 2026-10-23)."""
        limit = self._threshold if threshold is None else threshold
        with self._lock:
            now = self._clock.now()
            self._prune(now)
            events = self._events.setdefault(key, deque())
            events.append((now, weight))
            self._totals[key] = self._totals.get(key, 0) + weight
            self._expire(key, now)
            last = self._fired.get(key)
            return self._totals[key] > limit and (
                last is None or now - last >= self._period
            )

    def mark_fired(self, key: K) -> None:
        with self._lock:
            self._fired[key] = self._clock.now()

    def _expire(self, key: K, now: datetime) -> None:
        events = self._events[key]
        while events and now - events[0][0] >= self._window:
            self._totals[key] -= events.popleft()[1]
        if not events:
            del self._events[key], self._totals[key]

    def _prune(self, now: datetime) -> None:
        """Drops every idle key once per window, so memory stays bounded."""
        if self._pruned_at is not None and now - self._pruned_at < self._window:
            return
        self._pruned_at = now
        for key in list(self._events):
            self._expire(key, now)
        for key in [k for k, t in self._fired.items() if now - t >= self._period]:
            del self._fired[key]

    def count(self, key: K) -> int:
        with self._lock:
            if key in self._events:
                self._expire(key, self._clock.now())
            return self._totals.get(key, 0)

    def size(self) -> int:
        with self._lock:
            return len(self._events) + len(self._fired)


class OncePerPeriod[K: Hashable]:
    def __init__(self, clock: Clock, period: timedelta) -> None:
        self._clock = clock
        self._period = period
        self._lock = threading.Lock()
        self._fired: dict[K, datetime] = {}

    def fire(self, key: K) -> bool:
        """True if key has had no alert within the period; records this one."""
        due = self.due(key)
        if due:
            self.mark(key)
        return due

    def due(self, key: K) -> bool:
        """As fire(), without recording: mark(key) once the alert committed."""
        with self._lock:
            now = self._clock.now()
            for old in [k for k, t in self._fired.items() if now - t >= self._period]:
                del self._fired[old]
            return key not in self._fired

    def mark(self, key: K) -> None:
        with self._lock:
            self._fired[key] = self._clock.now()

    def size(self) -> int:
        with self._lock:
            return len(self._fired)


class ReArm[K: Hashable]:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._above: set[K] = set()

    def update(self, key: K, above: bool) -> bool:
        """True when the condition for key has just become true."""
        with self._lock:
            if not above:
                self._above.discard(key)
                return False
            if key in self._above:
                return False
            self._above.add(key)
            return True

    def sync(self, above: Iterable[K]) -> list[K]:
        """above is every key whose condition holds now; the others re-arm.
        Returns the keys that have just become true, in the order given."""
        with self._lock:
            now_above = list(dict.fromkeys(above))
            fresh = [k for k in now_above if k not in self._above]
            self._above = set(now_above)
            return fresh

    def due(self, above: Iterable[K]) -> list[K]:
        """As sync(), but only re-arms the keys no longer above; the keys that
        have just become true are returned unrecorded: mark(key) each once
        its alert committed, so a rolled-back alert fires again next time."""
        with self._lock:
            now_above = list(dict.fromkeys(above))
            self._above &= set(now_above)
            return [k for k in now_above if k not in self._above]

    def mark(self, key: K) -> None:
        with self._lock:
            self._above.add(key)

    def size(self) -> int:
        with self._lock:
            return len(self._above)
