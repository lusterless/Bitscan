"""The catalog service behind the routes and `serve` (TS §4.1 L526, L528, §4.2
L540; REQ-164, REQ-165 (5), REQ-172; open questions #102 (d), (e)).

Upload, delete and rebuild go through here. Until the start-up sequence has
completed once, each raises CatalogStarting, which the routes answer with 503
`about:blank` "The catalog is starting; retry shortly." and `Retry-After: 10`
(#102 (d)); the read routes and `/healthz` never wait for it.

Two daemon threads, started and stopped by `ServeLifecycle`:
- `catalog`: opens the folder watcher, then runs the start-up sequence
  (retried every 10 s while the database is down), opens the gate, then runs
  the watcher. The watches are added before the start-up reconcile, so
  changes made during it are queued and handled afterwards (TASK-159).
- `catalog-rebuild`: the one rebuild worker; rebuilds run one after another.

A thread blocked on the catalog lock has no timeout (TS §4.1 gives none), so
`stop` waits a bounded time and logs what is still running. The threads are
daemons: process exit closes their connections, which releases the
session-level lock; a task left `running` is failed at the next start-up.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final
from uuid import UUID

from bitscan_manager.runtime import Clock, SessionDatabase
from bitscan_manager.services.importer import rebuild, startup, uploads
from bitscan_manager.services.importer.delete import DeleteResult, delete_policy
from bitscan_manager.services.importer.pipeline import Actor, ImportOutcome
from bitscan_manager.services.importer.watcher import Watcher

log = logging.getLogger(__name__)
STARTING_DETAIL: Final = "The catalog is starting; retry shortly."  # #102 (d)
RETRY_AFTER_S: Final = 10
# Per thread: well inside serve's 10 s SIGTERM bound (CHK-M2-257), since a
# daemon thread blocked on the lock or a refused connect needs no longer wait.
STOP_WAIT_S: Final = 2.0


class CatalogStarting(Exception):
    """The start-up sequence has not completed yet (#102 (d))."""


class CatalogService:
    def __init__(
        self,
        db: SessionDatabase,
        clock: Clock,
        bits_dir: Path,
        *,
        wake: Callable[[], None] = lambda: None,  # the audit shipper
        watcher: Watcher | None = None,
    ) -> None:
        self._db, self._clock, self._bits, self._wake = db, clock, bits_dir, wake
        self._watcher = watcher if watcher is not None else Watcher(db, clock, bits_dir)
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._jobs: queue.Queue[tuple[UUID, Actor] | None] = queue.Queue()
        self._threads = (
            threading.Thread(target=self._catalog, name="catalog", daemon=True),
            threading.Thread(target=self._worker, name="catalog-rebuild", daemon=True),
        )

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def _check_ready(self) -> None:
        if not self._ready.is_set():
            raise CatalogStarting()

    def upload(
        self, data: bytes, client_name: bytes | str | None, actor: Actor
    ) -> ImportOutcome:
        """POST /policies/import (TS §4.1 L522); PolicyManagedOnServer and
        internal errors propagate to the route."""
        self._check_ready()
        try:
            return uploads.upload(
                self._db, self._clock, self._bits, data, client_name, actor
            )
        finally:
            self._wake()

    def delete(self, policy_id: int, actor: str) -> DeleteResult:
        """DELETE /policies/{id} (TS §4.3 L550); PolicyNotFound,
        PolicyAlreadyDeleted and PolicyManagedOnServer propagate."""
        self._check_ready()
        try:
            return delete_policy(
                self._db, policy_id, actor=actor, clock=self._clock, bits_dir=self._bits
            )
        finally:
            self._wake()

    def start_rebuild(self, requested_by: int | None, actor: Actor) -> UUID:
        """POST /policies/rebuild: the task row now, the rebuild on the worker
        (the route answers 202 with the id)."""
        self._check_ready()
        task_id = rebuild.start_task(self._db, self._clock, requested_by)
        self._jobs.put((task_id, actor))
        return task_id

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self, wait_s: float = STOP_WAIT_S) -> None:
        """Set stop, then wait at most `wait_s` per thread (see module doc)."""
        self._stop.set()
        self._jobs.put(None)
        for thread in self._threads:
            if thread.ident is None:
                continue  # never started
            thread.join(wait_s)
            if thread.is_alive():
                log.warning("catalog thread still running at stop: %s", thread.name)

    def _catalog(self) -> None:
        watching = self._watcher.open()  # before the reconcile (TASK-159)
        if startup.run(self._db, self._clock, self._bits, self._stop) is None:
            return  # stopped before the start-up completed
        self._wake()
        self._ready.set()
        log.info("catalog ready")
        if watching:
            self._watcher.run(self._stop)

    def _worker(self) -> None:
        while (job := self._jobs.get()) is not None:
            if self._stop.is_set():
                break  # its task stays running; start-up fails it (TS §4.2)
            task_id, actor = job
            try:
                rebuild.run(self._db, self._clock, self._bits, task_id, actor)
            except Exception as exc:  # no session: the task is failed at start-up
                log.error("rebuild did not start: %s", type(exc).__name__)
            finally:
                self._wake()
