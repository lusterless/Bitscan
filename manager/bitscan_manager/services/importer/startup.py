"""The catalog start-up sequence (TS §4.1 L528, §4.2 L540, L542; REQ-165;
open questions #27, #102 (d), #103).

Under the catalog lock and before any other catalog operation, in this order:
(1) finish interrupted uploads, (2) mark `running` tasks `failed`, (3) the
automatic reconcile of both folders, (4) the integrity check after the
reconcile (#27) with its one alert. `run_until_done` repeats the whole
sequence while the database is unreachable, waiting `retry_s` between tries
on a stop event (no busy loop), so a stop request ends the wait at once.
TASK-160 runs it on a background thread behind the #102 503 gate.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psycopg

from bitscan_manager.db.pool import DatabaseUnavailable
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.repositories.imports import fail_running_tasks
from bitscan_manager.runtime import Clock, SessionDatabase
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.folders import ReconcileResult, reconcile
from bitscan_manager.services.importer.integrity import check_and_alert
from bitscan_manager.services.importer.uploads import (
    FinishedUploads,
    finish_interrupted_uploads,
)

log = logging.getLogger(__name__)
RETRY_S: Final = 10.0  # #102 (d): retry every 10 s while unreachable
# #98 (g): a failed task's result is a fixed text.
INTERRUPTED: Final = {"error": "The manager stopped before the task finished."}


@dataclass(frozen=True, slots=True)
class StartupResult:
    uploads: FinishedUploads
    failed_tasks: int
    reconciled: ReconcileResult
    differences: tuple[Difference, ...]


def _step(name: str) -> None:
    log.info("catalog start-up step: %s", name)  # the recorded step log


def run_once(db: SessionDatabase, clock: Clock, bits_dir: Path) -> StartupResult:
    """One pass of the sequence, all of it inside one catalog lock."""
    with db.session() as session, catalog_lock(session):
        _step("finish_uploads")
        uploads = finish_interrupted_uploads(session, bits_dir)
        _step("fail_running_tasks")
        with session.transaction() as tx:
            failed = fail_running_tasks(tx.conn, INTERRUPTED, clock.now())
        _step("reconcile")
        reconciled = reconcile(session, clock, bits_dir)
        _step("integrity_check")
        found = check_and_alert(session, bits_dir, reconciled)
    _step("done")
    return StartupResult(uploads, len(failed), reconciled, tuple(found))


def run_until_done(
    db: SessionDatabase,
    clock: Clock,
    bits_dir: Path,
    stop: threading.Event,
    *,
    retry_s: float = RETRY_S,
) -> StartupResult | None:
    """`run_once`, repeated from step (1) while the database is unreachable
    (#102 (d)); None if `stop` is set first. Every step is safe to repeat.
    Any other error propagates to the caller."""
    while not stop.is_set():
        try:
            return run_once(db, clock, bits_dir)
        except (DatabaseUnavailable, psycopg.OperationalError) as exc:
            log.warning(
                "catalog start-up: database unreachable, retrying: %s",
                type(exc).__name__,  # never the driver text
            )
        if stop.wait(retry_s):
            break
    return None
