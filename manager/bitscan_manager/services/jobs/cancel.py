"""Cancel a scan (TS §4.4 L573, L581, §6.2 L1122; REQ-219, REQ-220, REQ-227;
open questions #122 (g), #127 (d), #129 (a)).

Manager-side only: nothing is sent to any agent. In the caller's transaction
the scan row is locked (two cancels of one scan apply one after the other),
its queued, dispatched and running jobs (originals and retries) become
`cancelled` with `finished_at`, the scan's state is derived at once from its
units (#127 (d), (f)), and one `scan.cancel` entry is written. A scan with
nothing left to cancel answers `cancelled_jobs: 0` (idempotent).

Lock order: the scan row, then open jobs. Intake and the sweep lock root and
job rows and never the scan row, so no cycle can form.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from bitscan_manager.repositories import scan_progress
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import Tx
from bitscan_manager.services.jobs.scan_state import ScanState, derive
from bitscan_manager.services.users import TxAudit


class ScanNotFound(Exception):
    """No scan has this id (404)."""


@dataclass(frozen=True, slots=True)
class ScanCancelled:
    scan_id: UUID
    state: ScanState
    cancelled_jobs: int


def cancel_scan(tx: Tx, *, scan_id: UUID, actor: str, now: datetime) -> ScanCancelled:
    """Cancel the scan's open jobs and derive its state (REQ-220)."""
    conn = tx.conn
    if scan_progress.scan_row(conn, scan_id, lock=True) is None:
        raise ScanNotFound
    cancelled = scan_progress.cancel_open_jobs(conn, scan_id, now)
    units = scan_progress.unit_facts(conn, [scan_id]).get(scan_id, [])
    state, finished = derive(units)  # a scan has at least one job (#3)
    scan_progress.set_scan_state(conn, scan_id, state, now if finished else None)
    TxAudit(PgAuditRepo(conn), tx.on_commit).audit(
        actor, "scan.cancel", f"scan:{scan_id}", {"cancelled_jobs": len(cancelled)}
    )
    return ScanCancelled(scan_id, state, len(cancelled))
