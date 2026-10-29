"""Re-evaluate a scan against its policy's current version (TS §4.5 L601,
§2.2 L114, §5.3 L1049; #12, #118; design note D4).

One transaction: the per-scan lock, the scan, the current definitions (one
statement), then the stored results in chunks, each result's new verdict
added to scan_result_reeval, and one `scan.reevaluate` audit entry. Original
results are never changed; a fault anywhere leaves neither rows nor entry.

- A plugin the current version no longer lists gets no row (#118 (b)).
- A result whose ERROR was decided at intake keeps it (#12, #118 (e)).
- An ERROR whose stored detail is not a Detail value (NULL included) is ERROR
  `cannot evaluate`, never compared (decisions 2026-10-29).
- A NULL stdout is ERROR `cannot evaluate`, never compared (fails closed;
  decisions 2026-10-29).

Authorisation (admin, TOTP session, sink gate) is the route's (M11). Nothing
here logs, and no exception or audit detail carries result text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from bitscan_manager.repositories import reeval
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.reeval import Definitions, ReevalInsert, StoredResult
from bitscan_manager.runtime import Database
from bitscan_manager.services.audit.chain import append_entry
from bitscan_manager.services.evaluator.evaluate import classify
from bitscan_manager.services.evaluator.model import (
    ERROR,
    INTAKE_DETAILS,
    Detail,
)


class ScanNotFound(Exception):
    """No scan has this id (M11: 404 `not_found`)."""


class PolicyDeleted(Exception):
    """The scan's policy is deleted (M11: 409 `conflict`, #118 (c))."""


@dataclass(frozen=True, slots=True)
class ReevalResult:
    scan_id: UUID
    policy_id: int
    scan_policy_version: int  # the version the scan was built from
    policy_version: int  # the version whose definitions were used
    rows_added: int
    not_in_version: int


_KNOWN_DETAILS: Final = frozenset(d.value for d in Detail)


def _new_verdict(row: StoredResult, operator: str, expected: str) -> ReevalInsert:
    if row.eval_detail in INTAKE_DETAILS:
        return ReevalInsert(row.job_id, row.plugin_uuid, ERROR, row.eval_detail)
    detail: str | None = str(Detail.CANNOT_EVALUATE)
    # An ERROR whose stored detail is not a Detail value (NULL included) may be
    # a misspelt intake ERROR stored with stdout '': fail closed (decisions
    # 2026-10-29), so it can never PASS under `empty`.
    if row.eval_code == ERROR and row.eval_detail not in _KNOWN_DETAILS:
        return ReevalInsert(row.job_id, row.plugin_uuid, ERROR, detail)
    if row.stdout is None:
        return ReevalInsert(row.job_id, row.plugin_uuid, ERROR, detail)
    v = classify(
        operator, expected, row.stdout, row.exit_code, row.timed_out, row.truncated
    )
    # A plain str, so the database gets the value, never an enum name.
    detail = None if v.detail is None else str(v.detail)
    return ReevalInsert(row.job_id, row.plugin_uuid, int(v.code), detail)


def _batch(
    chunk: list[StoredResult], defs: Definitions
) -> tuple[list[ReevalInsert], int]:
    """The rows to add for one chunk, and how many results were skipped
    because the current version does not list their plugin."""
    rows: list[ReevalInsert] = []
    skipped = 0
    for row in chunk:
        spec = defs.plugins.get(row.plugin_uuid)
        if spec is None:
            skipped += 1
        else:
            rows.append(_new_verdict(row, *spec))
    return rows, skipped


def reevaluate_scan(
    db: Database,
    scan_id: UUID,
    *,
    user_id: int,
    wake: Callable[[], None] | None = None,
) -> ReevalResult:
    """Raises ScanNotFound or PolicyDeleted with nothing written. `wake`
    (the audit shipper's) runs after the commit only."""
    with db.transaction() as tx:
        conn = tx.conn
        # The lock comes first, so a second run of this scan waits before it
        # reads anything; its rows then get the higher reeval_ids (#119).
        ref = reeval.lock_scan(conn, scan_id)
        if ref is None:
            raise ScanNotFound()
        defs = reeval.current_definitions(conn, ref.policy_id)
        if defs is None or defs.deleted:
            raise PolicyDeleted()
        rows_added = 0
        not_in_version = 0
        for chunk in reeval.stored_results(conn, scan_id):
            batch, skipped = _batch(chunk, defs)
            not_in_version += skipped
            rows_added += reeval.insert_reevals(
                conn,
                batch,
                policy_version=defs.policy_version,
                reevaluated_by=user_id,
            )
        # Last, so it records the true counts; same transaction (#118 (g)).
        append_entry(
            PgAuditRepo(conn),
            actor=f"user:{user_id}",
            action="scan.reevaluate",
            target=f"scan:{scan_id}",
            detail={
                "policy_id": ref.policy_id,
                "scan_policy_version": ref.policy_version,
                "policy_version": defs.policy_version,
                "rows_added": rows_added,
                "not_in_version": not_in_version,
            },
        )
        if wake is not None:
            tx.on_commit(wake)
    return ReevalResult(
        scan_id=scan_id,
        policy_id=ref.policy_id,
        scan_policy_version=ref.policy_version,
        policy_version=defs.policy_version,
        rows_added=rows_added,
        not_in_version=not_in_version,
    )
