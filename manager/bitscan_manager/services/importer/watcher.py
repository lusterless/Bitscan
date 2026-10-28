"""The folder watcher (TS §4.1 L528, §4.2; REQ-164; #102 (a), (c); the user's
"Folder guard" ruling of 2026-10-27; PD-33 (b)).

One thread watches the bits folder and `uploaded/` (no subfolders) for
completed writes and moves in (IN_CLOSE_WRITE, IN_MOVED_TO) and deletions
and moves out (IN_DELETE, IN_MOVED_FROM) of `*.bit` names that are not
hidden. A burst is coalesced until the folders have been quiet for
`QUIET_S`. The batch is then handled under the catalog lock. A path counts as
changed only if the catalog's live `source_file` and `source_sha256` differ
from the file on disk now. The manager's own upload renames and removals
(and anything else already reflected in the catalog) therefore change
nothing and are dropped (#102 (c), as amended 2026-10-28). The changed paths
go to the approved `folders.reconcile_paths` (`auto` mode); a queue overflow,
a lost watch or a re-arm runs the full `folders.reconcile`. Classification,
the folder guard and the per-row delete check are all reconcile's. A watch
is only a trigger: a folder swapped between a check and `add_watch` costs at
most one extra reconcile, which applies the guard itself. A failed reconcile
(database down, #98 (j)) is logged and left to the next event or start-up.
"""

from __future__ import annotations

import logging
import os
import select
import threading
import time
from pathlib import Path

from bitscan_manager.repositories.catalog_integrity import integrity_rows
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import CatalogSession, Clock, SessionDatabase
from bitscan_manager.services.importer import folders
from bitscan_manager.services.importer import inotify as ino

log = logging.getLogger(__name__)
QUIET_S = 1.0  # a burst ends after this long with no event (REQ-164 (3))
MAX_PENDING = 1024  # more distinct paths in one burst: one full reconcile
REARM_S = 10.0  # retry a lost folder watch this often, never faster
_FILES = ino.IN_CLOSE_WRITE | ino.IN_MOVED_TO | ino.IN_DELETE | ino.IN_MOVED_FROM
_GONE = ino.IN_DELETE_SELF | ino.IN_MOVE_SELF | ino.IN_IGNORED
_MASK = _FILES | ino.IN_DELETE_SELF | ino.IN_MOVE_SELF
_ARM = _MASK | ino.IN_ONLYDIR | ino.IN_DONTFOLLOW  # never through a link
_LABELS = (folders.BITS_ROOT, folders.UPLOADED)


class FolderWatcher:
    """Start with `start()` (False, with one log line, where inotify is
    missing); stop with `stop()`. Used by `serve` (TASK-160)."""

    def __init__(self, db: SessionDatabase, clock: Clock, bits_dir: Path) -> None:
        self._db, self._clock, self._bits = db, clock, bits_dir
        self._ino: ino.Inotify | None = None
        self._wds: dict[int, str] = {}  # watch descriptor -> folder label
        self._lost: set[str] = set()  # labels already logged as lost
        self._wake_r, self._wake_w = -1, -1
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._ino = ino.Inotify()
        except ino.InotifyUnavailable:
            log.warning("folder watcher not started: inotify is not available")
            return False
        self._wake_r, self._wake_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self._arm(self._ino)
        self._thread = threading.Thread(
            target=self._loop, args=(self._ino,), name="folder-watcher", daemon=True
        )
        self._thread.start()
        return True

    def stop(self, timeout_s: float = 5.0) -> None:
        """Wake the thread and wait for it; a reconcile in progress ends first
        (bounded by the caller's timeout; the thread is a daemon)."""
        self._stop.set()
        if self._wake_w >= 0:
            os.write(self._wake_w, b"x")
        if self._thread is not None:
            self._thread.join(timeout_s)
            if self._thread.is_alive():
                return  # still in a reconcile: a daemon; keep its descriptors
        self._close()

    def _close(self) -> None:
        if self._ino is not None:
            self._ino.close()
            self._ino = None
        for fd in (self._wake_r, self._wake_w):
            if fd >= 0:
                os.close(fd)
        self._wake_r = self._wake_w = -1

    def _path(self, label: str) -> Path:
        return self._bits if label == folders.BITS_ROOT else self._bits / "uploaded"

    def _arm(self, notify: ino.Inotify) -> bool:
        """Watch each folder not watched yet, if it is a real directory and,
        for `uploaded/`, the bits folder is too. True if one was (re-)armed."""
        armed = False
        for label in _LABELS:
            if label in self._wds.values():
                continue
            if (
                label == folders.UPLOADED
                and folders.BITS_ROOT not in self._wds.values()
            ):
                continue  # reached through the bits folder: arm that first
            try:
                self._wds[notify.add_watch(self._path(label), _ARM)] = label
            except OSError as exc:
                if label not in self._lost:
                    log.warning(
                        "folder not watched: %s (%s)", label, type(exc).__name__
                    )
                    self._lost.add(label)
                continue
            if label in self._lost:
                log.warning("folder watched again: %s", label)
                self._lost.discard(label)
            armed = True
        return armed

    def _drop(self, notify: ino.Inotify, label: str) -> None:
        """Invalidate a folder's watch (and `uploaded/`'s with the bits folder's,
        since it is reached through it), logging each once."""
        for wd, name in list(self._wds.items()):
            if name == label or label == folders.BITS_ROOT:
                notify.rm_watch(wd)  # already gone after IN_IGNORED: harmless
                del self._wds[wd]
                if name not in self._lost:
                    log.warning("folder watch lost, reconciling: %s", name)
                    self._lost.add(name)

    def _collect(self, notify: ino.Inotify, pending: set[str]) -> tuple[bool, bool]:
        """Read the queued events into `pending`. Returns (relevant, full):
        whether any event counted, and whether a full reconcile is due
        (queue overflow, a lost folder, or too many paths)."""
        relevant = full = False
        for ev in notify.read():
            label = self._wds.get(ev.wd)
            if ev.mask & ino.IN_Q_OVERFLOW:
                full = True
            elif label is None:
                continue  # a watch already dropped
            elif ev.mask & _GONE:
                self._drop(notify, label)
                full = True
            elif ev.mask & _FILES and not ev.mask & ino.IN_ISDIR:
                name = ev.name
                if name.endswith(".bit") and not name.startswith("."):
                    prefix = "" if label == folders.BITS_ROOT else folders.UPLOADED
                    pending.add(prefix + name)
                    relevant = True
        return relevant or full, full or len(pending) > MAX_PENDING

    def _loop(self, notify: ino.Inotify) -> None:
        poller = select.poll()
        poller.register(notify.fileno(), select.POLLIN)
        poller.register(self._wake_r, select.POLLIN)
        pending: set[str] = set()
        full = False
        last = next_arm = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if len(self._wds) < len(_LABELS) and now >= next_arm:
                if self._arm(notify):  # catch up on changes made while unwatched
                    full, last = True, now
                next_arm = now + REARM_S
            due = [next_arm] if len(self._wds) < len(_LABELS) else []
            if pending or full:
                due.append(last + QUIET_S)
            wait = None if not due else max(0, int((min(due) - now) * 1000) + 1)
            if poller.poll(wait) and not self._stop.is_set():  # blocks until due
                relevant, overflow = self._collect(notify, pending)
                full |= overflow
                if relevant:
                    last = time.monotonic()  # the burst goes on
            if self._stop.is_set():
                break
            if (pending or full) and time.monotonic() >= last + QUIET_S:
                self._handle(set() if full else pending)
                pending, full = set(), False

    def _handle(self, paths: set[str]) -> None:
        """Under the catalog lock: a full `folders.reconcile` if `paths` is
        empty (overflow, a lost watch or a re-arm), else `reconcile_paths`
        for the paths that differ from the catalog, if any (decisions
        2026-10-28: "One-file reconcile" and the self-event check)."""
        try:
            with self._db.session() as session, catalog_lock(session):
                if not paths:
                    result = folders.reconcile(session, self._clock, self._bits)
                else:
                    changed = self._changed(session, paths)
                    if not changed:
                        return  # self-caused or already in the catalog (#102 (c))
                    result = folders.reconcile_paths(
                        session, self._clock, self._bits, changed
                    )
        except Exception as exc:  # retried by the next event or start-up
            log.warning("folder reconcile failed: %s", type(exc).__name__)
            return
        log.info(
            "folder reconcile: files=%d deleted=%d unreadable=%d",
            len(result.outcomes),
            len(result.deleted),
            len(result.unreadable_folders),
        )

    def _changed(self, session: CatalogSession, paths: set[str]) -> list[str]:
        """The paths whose file on disk (its SHA-256, or None if gone) differs
        from the live catalog's `source_sha256` for that `source_file`."""
        with session.transaction() as tx:
            live = {r.source_file: r.source_sha256 for r in integrity_rows(tx.conn)}
        changed: list[str] = []
        for rel in sorted(paths):
            file = None
            if folders.present(self._bits, rel):  # no read, no log, if gone
                file = folders.read_input(self._bits, rel)
            if (file.sha256 if file is not None else None) != live.get(rel):
                changed.append(rel)
        return changed
