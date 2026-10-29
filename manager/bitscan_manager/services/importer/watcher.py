"""The folder watcher (TS §4.1 L528, §4.6 L612; REQ-164; open questions #102
(a)-(c), PD-33 (b)).

Both folders are watched with inotify, `*.bit` entries only, no subfolders.
A completed write or a move in (`IN_CLOSE_WRITE`, `IN_MOVED_TO`) imports the
file in `auto` mode (`folders.import_path`); a deletion or a move out
(`IN_DELETE`, `IN_MOVED_FROM`) deletes the live policy whose `source_file` is
that path, unless the file is back. A queue overflow or a replaced folder
triggers a full `folders.reconcile`. Each file is handled under the catalog
lock. Where inotify is missing (not Linux) the watcher logs one line and
returns.

#102 (c): the manager's own renames and deletions are recorded in
`own_changes.OWN_CHANGES` by their writers, just before each call and under
the catalog lock, and the matching event is dropped. The watcher checks it
only after taking the lock for that path.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Final

from bitscan_manager.repositories import catalog
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Clock, SessionDatabase
from bitscan_manager.services.importer import delete, folders, inotify
from bitscan_manager.services.importer.inotify import (
    IN_CLOSE_WRITE,
    IN_CREATE,
    IN_DELETE,
    IN_DELETE_SELF,
    IN_DONT_FOLLOW,
    IN_EXCL_UNLINK,
    IN_IGNORED,
    IN_ISDIR,
    IN_MOVE_SELF,
    IN_MOVED_FROM,
    IN_MOVED_TO,
    IN_ONLYDIR,
    IN_Q_OVERFLOW,
    Event,
)
from bitscan_manager.services.importer.own_changes import OWN_CHANGES, OwnChanges

log = logging.getLogger(__name__)
RETRY: Final = 10.0  # seconds between reconciles after a failure (#102 (d))
_IN: Final = IN_CLOSE_WRITE | IN_MOVED_TO
_OUT: Final = IN_DELETE | IN_MOVED_FROM
_MASK: Final = (
    _IN | _OUT | IN_CREATE | IN_DELETE_SELF | IN_MOVE_SELF
    | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK
)  # fmt: skip
_RESCAN: Final = IN_Q_OVERFLOW | IN_IGNORED | IN_DELETE_SELF | IN_MOVE_SELF


class Watcher:
    """`open` adds the watches; `run` handles events until `stop` is set.
    The caller (TASK-160) may open before the start-up reconcile, so that
    changes made during it are queued and handled afterwards."""

    def __init__(
        self,
        db: SessionDatabase,
        clock: Clock,
        bits_dir: Path,
        own: OwnChanges = OWN_CHANGES,
    ) -> None:
        self._db, self._clock, self._bits, self._own = db, clock, bits_dir, own
        self._ino: inotify.Inotify | None = None
        self._prefix: dict[int, str] = {}  # watch descriptor -> "" or "uploaded/"

    def open(self) -> bool:
        """False, after one log line, where inotify is unavailable."""
        if not inotify.available():
            log.info("folder watcher not started: inotify is not available here")
            return False
        try:
            self._ino = inotify.Inotify()
            self._watch()
        except OSError as exc:
            log.warning("folder watcher not started: %s", type(exc).__name__)
            return False
        return True

    def _watch(self) -> None:
        if self._ino is None:
            return
        self._prefix = {self._ino.add_watch(self._bits, _MASK): ""}
        try:
            self._prefix[self._ino.add_watch(self._bits / "uploaded", _MASK)] = (
                "uploaded/"
            )
        except FileNotFoundError:  # watched again once it is created
            pass

    def run(self, stop: threading.Event, poll: float = 1.0) -> None:
        """Until `stop` is set. A failed event (the database down, say) is
        followed by a full reconcile, retried every RETRY seconds."""
        if self._ino is None and not self.open():
            return
        ino, rescan, retry_at = self._ino, False, 0.0
        if ino is None:  # unreachable: open() set it
            return
        try:
            while not stop.is_set():
                events = ino.read(poll)
                if rescan and time.monotonic() < retry_at:
                    continue  # the reconcile to come covers these events
                try:
                    rescan = self._handle(events, rescan)
                except Exception as exc:
                    log.error("folder event failed: %s", type(exc).__name__)
                    rescan, retry_at = True, time.monotonic() + RETRY
        finally:
            ino.close()
            self._ino = None

    def _handle(self, events: list[Event], rescan: bool) -> bool:
        """Handle one batch; the last event per path wins. Returns False once
        a pending full reconcile has run."""
        changes: dict[str, bool] = {}  # rel -> True for in, False for out
        for ev in events:
            prefix = self._prefix.get(ev.wd)
            if ev.mask & _RESCAN or prefix is None:
                rescan = True
            elif ev.mask & IN_ISDIR:
                rescan |= prefix == "" and ev.name == "uploaded"
            elif ev.name.endswith(".bit") and not ev.name.startswith("."):
                if not folders.storable(ev.name):
                    log.warning("folder file skipped: its name cannot be stored")
                elif ev.mask & (_IN | _OUT):
                    changes[prefix + ev.name] = bool(ev.mask & _IN)
        if rescan:
            with self._db.session() as session, catalog_lock(session):
                self._watch()
                folders.reconcile(session, self._clock, self._bits)
            return False
        # Incoming paths first (ruling "W6 pre-read rulings" (2)): with
        # `mv a.bit c.bit` in one batch, c.bit moves a.bit's policy
        # (move_server) and the a.bit removal then finds no policy.
        for rel, came_in in sorted(changes.items(), key=lambda kv: not kv[1]):
            with self._db.session() as session, catalog_lock(session):
                self._one(session, rel, came_in)
        return False

    def _one(self, session: CatalogSession, rel: str, came_in: bool) -> None:
        def sha256_now() -> str | None:
            found = folders.read_file(self._bits / rel)  # never follows a symlink
            return None if found is None else found[1]

        if came_in and self._own.drop_write(rel, sha256_now):
            return
        if not came_in and self._own.drop_removal(rel):
            return
        if came_in or folders.is_bit_file(self._bits, rel):  # in, or back again
            folders.import_path(session, self._clock, self._bits, rel)
            return
        with session.transaction() as tx:
            row = catalog.policy_by_source_file_for_update(tx.conn, rel)
            if row is None or row.deleted_at is not None:
                return
            gone = delete.delete_in_tx(
                tx,
                row.policy_id,
                actor=folders.SYSTEM.audit,
                reason="file removed",
                now=self._clock.now(),
            )
        delete.remove_after_commit(self._bits, gone.remove_after_commit)
