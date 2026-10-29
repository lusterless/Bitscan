"""The catalog start-up sequence (TS §4.1 L528, §4.2 L540, L542; §8.4 L1291;
REQ-165; open questions #27, #102 (d), #103; user "Crash window" ruling
2026-10-27).

Under one catalog lock, before any other catalog work:
1. finish interrupted uploads (TASK-155);
2. mark `task` rows still `running` as `failed` (TS §4.2 L540);
3. reconcile both folders in `auto` mode (TASK-156);
4. after the reconcile (#27), run the #103 integrity check. Each leftover the
   reconcile removed is one more difference, and any difference raises one
   `catalog_integrity_failed` alert.

`run` retries the whole sequence every 10 s until it completes (#102 (d)): the
database may be down at start, and one file's internal error aborts the
reconcile before its deletion pass, so a deletion never follows a partial
import pass. TASK-160 runs it on a background thread and keeps the catalog
routes closed until it returns.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.repositories.imports import fail_running_tasks
from bitscan_manager.runtime import Clock, SessionDatabase
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.folders import ReconcileResult, reconcile
from bitscan_manager.services.importer.integrity import alert, check
from bitscan_manager.services.importer.uploads import FinishResult, finish_interrupted

log = logging.getLogger(__name__)
RETRY_S: Final = 10.0  # #102 (d)
# task.result of a task the restart interrupted (#98 (g): fixed text).
TASK_INTERRUPTED: Final = "The manager stopped before the task ended."


@dataclass(frozen=True, slots=True)
class StartupReport:
    finished: FinishResult
    failed_tasks: tuple[UUID, ...]
    reconciled: ReconcileResult
    differences: tuple[Difference, ...]  # leftovers first, then the #103 check


def run_once(db: SessionDatabase, clock: Clock, bits_dir: Path) -> StartupReport:
    """One attempt at the whole sequence; any error propagates."""
    with db.session() as session, catalog_lock(session):
        finished = finish_interrupted(session, bits_dir)
        with session.transaction() as tx:
            failed = fail_running_tasks(
                tx.conn, {"error": TASK_INTERRUPTED}, clock.now()
            )
        reconciled = reconcile(session, clock, bits_dir)
        differences = (*reconciled.leftovers, *check(session, bits_dir))
        if differences:
            with session.transaction() as tx:
                alert(tx, differences)
    log.info(
        "catalog start-up done: %d tasks failed, %d imports, %d deleted,"
        " %d differences",
        len(failed),
        len(reconciled.outcomes),
        len(reconciled.deleted),
        len(differences),
    )
    return StartupReport(finished, tuple(failed), reconciled, differences)


def run(
    db: SessionDatabase,
    clock: Clock,
    bits_dir: Path,
    stop: threading.Event,
    retry_s: float = RETRY_S,
) -> StartupReport | None:
    """Run the sequence until it completes; None if `stop` is set first
    (builder checklist 10). A failed attempt is logged by its type only and
    retried from step 1, which is safe: every step is idempotent."""
    while not stop.is_set():
        try:
            return run_once(db, clock, bits_dir)
        except Exception as exc:
            log.warning("catalog start-up failed, retrying: %s", type(exc).__name__)
        if stop.wait(retry_s):
            break
    return None
