"""The retention run (TS §5.3 L1049, L1051, L1053; #150, #151; plan TASK-242 §4,
as corrected in decisions 2026-11-08).

`db` is the bitscan_retention pool only: that role can delete from the
retention tables and nothing else, and insert the audit checkpoints. A run:

1. compares the manager's clock with the database's and deletes nothing when
   they differ by more than 5 minutes;
2. runs the steps in order: scans, inventory jobs, snapshots, decided
   requests, expired tokens, the audit prefix, unreferenced packages. Each
   chunk is its own transaction, so a fault rolls back one chunk; a step that
   raises is logged by name and exception type, and the next step runs. A
   dated step is skipped when its table holds a row dated more than a day
   after now.

Logs carry step names, counts and exception types only, never row content.
The only audit entries written are the `audit.checkpoint` entries.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg

from bitscan_manager.repositories import retention, retention_audit
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.retention import ProbeTable
from bitscan_manager.runtime import Database
from bitscan_manager.services.audit.chain import append_entry
from bitscan_manager.services.retention import rules

type Conn = psycopg.Connection[Any]

log = logging.getLogger(__name__)

CLOCK_DOUBT: Final = "clock_doubt"  # the run deleted nothing
FUTURE_ROWS: Final = "future_rows"  # the step's table holds future-dated rows
FAILED: Final = "failed"  # the step raised; chunks committed before it stay

STEPS: Final = (
    "scans",
    "inventory_jobs",
    "snapshots",
    "requests",
    "tokens",
    "audit",
    "packages",
)


@dataclass(frozen=True)
class StepResult:
    step: str
    deleted: int  # rows committed as deleted (scans for "scans")
    chunks: int  # committed transactions that deleted rows
    skipped: str | None  # None, CLOCK_DOUBT, FUTURE_ROWS or FAILED


@dataclass
class _Count:
    deleted: int = 0
    chunks: int = 0

    def add(self, n: int) -> None:
        if n > 0:
            self.deleted += n
            self.chunks += 1


def _chunks(db: Database, delete: Callable[[Conn], int], size: int, c: _Count) -> None:
    """Delete in chunks of one transaction each until a chunk comes back
    short. Each transaction goes through db, so a stopping scheduler ends the
    loop at its next chunk."""
    while True:
        with db.transaction() as tx:
            n = delete(tx.conn)
        c.add(n)
        if n < size:
            return


def _dated(
    db: Database,
    delete: Callable[[Conn, datetime, int], int],
    cutoff: datetime,
    size: int,
    c: _Count,
) -> None:
    _chunks(db, lambda conn: delete(conn, cutoff, size), size, c)


def _scans(db: Database, cutoff: datetime, c: _Count) -> None:
    """Chunks of whole scans. A scan whose re-evaluation lock another session
    holds is left for the next run (#150 (k)). scan_chunk takes no row lock
    and returns the oldest scans, so a skipped scan would head every later
    chunk: the skipped ids are carried through the run, each chunk asks for
    that many more rows and leaves them out, so scans behind them are still
    reached. The loop ends when a chunk brings no scan not yet tried, or the
    table has no more past the cutoff."""
    skipped: set[UUID] = set()
    while True:
        limit = rules.SCAN_CHUNK + len(skipped)
        with db.transaction() as tx:
            conn = tx.conn
            ids = retention.scan_chunk(conn, cutoff, limit)
            fresh = [i for i in ids if i not in skipped]
            free = [i for i in fresh if retention.try_reeval_lock(conn, i)]
            n = retention.delete_scans(conn, free)
        c.add(n)
        skipped.update(set(fresh) - set(free))
        if not fresh or len(ids) < limit:
            return


def _audit(
    db: Database,
    cutoff: datetime,
    shipped_through: Callable[[], int | None],
    wake: Callable[[], None] | None,
    c: _Count,
) -> None:
    """The expired prefix of the chain, at most AUDIT_CHUNK entries per
    transaction. In each: the chain lock, the oldest entries, the prefix
    capped at the shipper's cursor, then the checkpoint through the chain and
    only then the delete (TS §5.3 L1053). Both commit together or neither."""
    while True:
        with db.transaction() as tx:
            conn = tx.conn
            repo = PgAuditRepo(conn)
            # Decide under the chain lock, so no writer moves the head meanwhile
            # (append_entry takes the same lock again; it is re-entrant).
            repo.lock_chain()
            rows = retention_audit.oldest(conn, rules.AUDIT_CHUNK)
            last = rules.audit_prefix(
                rows, cutoff, shipped_through(), rules.AUDIT_CHUNK
            )
            if last is None:
                return
            count = sum(1 for audit_id, _ in rows if audit_id <= last)
            append_entry(
                repo,
                actor="system",
                action="audit.checkpoint",
                target=None,
                detail={
                    "last_deleted_id": last,
                    "last_deleted_row_hash": retention_audit.row_hash(conn, last),
                    "deleted": count,
                },
            )
            n = retention_audit.delete_through(conn, last)
            if n != count:  # rolls back the checkpoint and the delete
                raise RuntimeError("audit prefix changed during the delete")
            if wake is not None:
                tx.on_commit(wake)
        c.add(n)


def _future(db: Database, table: ProbeTable, now: datetime) -> bool:
    with db.transaction() as tx:
        newest = retention.newest(tx.conn, table)
    return rules.future_rows(newest, now)


def run_retention(
    db: Database,
    now: datetime,
    *,
    shipped_through: Callable[[], int | None],
    wake: Callable[[], None] | None = None,
) -> list[StepResult]:
    """One retention run at the manager's instant now (timezone-aware).
    shipped_through returns the id of the last audit entry queued for the
    sink (None before the first); wake (the shipper's) runs after each
    committed checkpoint. A failure of the clock check itself propagates:
    without it nothing is deleted."""
    cut = rules.cutoffs(now)
    with db.transaction() as tx:
        db_now = retention.db_now(tx.conn)
    if rules.clock_doubt(now, db_now):
        log.warning("retention refused: clock_doubt", extra={"data": {}})
        return [StepResult(s, 0, 0, CLOCK_DOUBT) for s in STEPS]

    # (step, the table probed for future-dated rows or None, the step's run)
    plan: tuple[tuple[str, ProbeTable | None, Callable[[_Count], None]], ...] = (
        ("scans", "scan", lambda c: _scans(db, cut.scans, c)),
        (
            "inventory_jobs",
            "scan_job",
            lambda c: _dated(
                db,
                retention.delete_inventory_jobs,
                cut.inventory_jobs,
                rules.JOB_CHUNK,
                c,
            ),
        ),
        (
            "snapshots",
            "inventory_snapshot",
            lambda c: _dated(
                db, retention.delete_snapshots, cut.snapshots, rules.ROW_CHUNK, c
            ),
        ),
        (
            "requests",
            "enrollment_request",
            lambda c: _dated(
                db, retention.delete_requests, cut.requests, rules.ROW_CHUNK, c
            ),
        ),
        (
            "tokens",
            "user_token",
            lambda c: _dated(
                db, retention.delete_tokens, cut.tokens, rules.ROW_CHUNK, c
            ),
        ),
        ("audit", None, lambda c: _audit(db, cut.audit, shipped_through, wake, c)),
        (
            "packages",
            None,
            lambda c: _chunks(
                db,
                lambda conn: retention.delete_packages(conn, rules.ROW_CHUNK),
                rules.ROW_CHUNK,
                c,
            ),
        ),
    )
    results: list[StepResult] = []
    for name, table, run in plan:
        c = _Count()
        skipped: str | None = None
        try:
            if table is not None and _future(db, table, now):
                skipped = FUTURE_ROWS
            else:
                run(c)
        except Exception as exc:  # the later steps still run (REQ-277)
            log.error(
                "retention step failed",
                extra={"data": {"step": name, "exc_type": type(exc).__name__}},
            )
            skipped = FAILED
        result = StepResult(name, c.deleted, c.chunks, skipped)
        data = {"step": name, "deleted": c.deleted, "chunks": c.chunks}
        log.info("retention step done", extra={"data": {**data, "skipped": skipped}})
        results.append(result)
    return results
