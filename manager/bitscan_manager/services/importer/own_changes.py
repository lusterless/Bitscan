"""The manager's own folder changes, for the watcher (open question #102
(c); decisions row "#102 (c) wiring", 2026-10-28). A neutral module: it
imports nothing from the importer, so every writer (uploads, delete,
folders) and the watcher can import it.

A writer records each rename into place (`wrote`, with the file's SHA-256)
or removal of a `*.bit` file (`removed`) just BEFORE the call, under the
catalog lock, so even an inotify event read at once finds its record. Paths
are relative to the bits folder (`uploaded/policy-7.bit`). Records last
OWN_TTL seconds and each is used up by one matching event.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Final

OWN_TTL: Final = 60.0  # seconds (#102 (c))


class OwnChanges:
    """The paths the manager itself is renaming into place or removing."""

    def __init__(self, ttl: float = OWN_TTL, now: Callable[[], float] = time.monotonic):
        self._ttl, self._now = ttl, now
        self._lock = threading.Lock()
        self._writes: dict[str, list[tuple[float, str]]] = {}
        self._removals: dict[str, list[float]] = {}

    def wrote(self, rel: str, sha256: str) -> None:
        with self._lock:
            self._writes.setdefault(rel, []).append((self._now() + self._ttl, sha256))

    def removed(self, rel: str) -> None:
        with self._lock:
            self._removals.setdefault(rel, []).append(self._now() + self._ttl)

    def drop_write(self, rel: str, current: Callable[[], str | None]) -> bool:
        """True if the event at `rel` is our own: an unexpired record whose
        SHA-256 equals the file's now (`current` runs only if one exists)."""
        with self._lock:
            now = self._now()
            live = [w for w in self._writes.pop(rel, []) if w[0] > now]
            sha = current() if live else None
            match = next((w for w in live if w[1] == sha), None)
            if match is not None:
                live.remove(match)
            if live:
                self._writes[rel] = live
            return match is not None

    def drop_removal(self, rel: str) -> bool:
        with self._lock:
            now = self._now()
            live = [t for t in self._removals.pop(rel, []) if t > now]
            matched = bool(live)
            if live[1:]:
                self._removals[rel] = live[1:]
            return matched


OWN_CHANGES: Final = OwnChanges()  # the process-wide record (#102 (c))
