"""Audit chain verifier (TS §5.3; hash #38, checkpoint rule #39). Pure.

Rows are checked in audit_id order. Each row_hash is recomputed from the stored
row, and each prev_hash must equal the previous row's row_hash. Only the oldest
remaining row may instead link to a checkpoint: genesis, or the
last_deleted_row_hash of an audit.checkpoint row of this same chain, verified
before the first failure, written after the rows it records and recording a
last_deleted_id lower than the oldest row's id. A forged checkpoint therefore
cannot make a mid-chain row count as "oldest".

verify_rows() is pure; verify_chain() reads the rows through the repository.
"""

import json
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from typing import Any

import psycopg

from bitscan_manager.repositories.audit_log import iter_entries
from bitscan_manager.services.audit.chain import (
    GENESIS_PREV_HASH,
    HashInput,
    compute_row_hash,
)

CHECKPOINT_ACTION = "audit.checkpoint"
HASH_MISMATCH = "row_hash mismatch"
BROKEN_LINK = "broken link"


@dataclass(frozen=True)
class StoredEntry:
    audit_id: int
    actor: str
    action: str
    target: str | None
    detail_text: str | None
    at_text: str
    prev_hash: str
    row_hash: str


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_id: int | None
    reason: str | None


def _checkpoint(entry: StoredEntry) -> tuple[int, str] | None:
    """(last_deleted_id, last_deleted_row_hash) of a well-formed checkpoint."""
    if entry.action != CHECKPOINT_ACTION or entry.detail_text is None:
        return None
    try:
        detail = json.loads(entry.detail_text)
    except ValueError:
        return None
    if not isinstance(detail, dict):
        return None
    last_id = detail.get("last_deleted_id")
    last_hash = detail.get("last_deleted_row_hash")
    if type(last_id) is not int or not isinstance(last_hash, str):
        return None
    if last_id >= entry.audit_id:
        return None
    return last_id, last_hash


def verify_rows(rows: Iterable[StoredEntry]) -> VerifyResult:
    """Verify rows given in ascending audit_id order. Gaps in audit_id are fine."""
    checked = 0
    first: StoredEntry | None = None
    first_linked = False
    previous_hash: str | None = None
    bad: tuple[int, str] | None = None
    for entry in rows:
        checked += 1
        expected = compute_row_hash(
            entry.prev_hash,
            HashInput(
                entry.audit_id,
                entry.actor,
                entry.action,
                entry.target,
                entry.detail_text,
                entry.at_text,
            ),
        )
        if expected != entry.row_hash:
            bad = (entry.audit_id, HASH_MISMATCH)
            break
        if first is None:
            first = entry
            first_linked = entry.prev_hash == GENESIS_PREV_HASH
        elif entry.prev_hash != previous_hash:
            bad = (entry.audit_id, BROKEN_LINK)
            break
        mark = _checkpoint(entry)
        if (
            not first_linked
            and mark is not None
            and mark[0] < first.audit_id
            and mark[1] == first.prev_hash
        ):
            first_linked = True
        previous_hash = entry.row_hash
    # A definite failure wins: the walk stopped there, before any later
    # checkpoint that might have linked the oldest row could be seen.
    if bad is not None:
        return VerifyResult(False, checked, bad[0], bad[1])
    if first is not None and not first_linked:
        return VerifyResult(False, checked, first.audit_id, BROKEN_LINK)
    return VerifyResult(True, checked, None, None)


def verify_chain(conn: psycopg.Connection[Any]) -> VerifyResult:
    """Verify the whole audit_log from one read-only snapshot.

    The connection must have no open transaction (AuditError otherwise).
    """
    with closing(iter_entries(conn)) as rows:
        return verify_rows(StoredEntry(*row) for row in rows)
