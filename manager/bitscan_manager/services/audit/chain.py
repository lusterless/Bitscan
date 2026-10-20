"""Audit chain append (TS §5.2 audit_log, §5.3; hash input #38).

Pure: the database is reached only through an AuditRepo. Nothing here logs.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

GENESIS_PREV_HASH = "0" * 64


@dataclass(frozen=True)
class HashInput:
    audit_id: int
    actor: str
    action: str
    target: str | None
    detail_text: str | None
    at_text: str


@dataclass(frozen=True)
class AppendedEntry:
    audit_id: int
    prev_hash: str
    row_hash: str
    at_text: str


class AuditRepo(Protocol):
    def lock_chain(self) -> None: ...

    def head_row_hash(self) -> str | None: ...

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]: ...

    def insert(
        self,
        audit_id: int,
        actor: str,
        action: str,
        target: str | None,
        detail_text: str | None,
        at_text: str,
        prev_hash: str,
        row_hash: str,
    ) -> None: ...


def compute_row_hash(prev_hash: str, entry: HashInput) -> str:
    """SHA-256, lowercase hex, of the compact JSON array of the entry (#38).

    detail_text is PostgreSQL's own detail::text and is hashed as a string,
    never re-parsed; at_text is YYYY-MM-DDTHH:MM:SS.ffffffZ in UTC.
    """
    payload = json.dumps(
        [
            prev_hash,
            entry.audit_id,
            entry.actor,
            entry.action,
            entry.target,
            entry.detail_text,
            entry.at_text,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_entry(
    repo: AuditRepo,
    *,
    actor: str,
    action: str,
    target: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> AppendedEntry:
    """Append one entry inside the caller's transaction; the caller commits.

    The id, the timestamp and detail's text come from the database under the
    chain lock, so the stored row can be re-hashed byte for byte.
    """
    detail_json = (
        None
        if detail is None
        else json.dumps(dict(detail), ensure_ascii=False, allow_nan=False)
    )
    repo.lock_chain()
    prev_hash = repo.head_row_hash() or GENESIS_PREV_HASH
    audit_id, at_text, detail_text = repo.allocate(detail_json)
    row_hash = compute_row_hash(
        prev_hash, HashInput(audit_id, actor, action, target, detail_text, at_text)
    )
    repo.insert(
        audit_id, actor, action, target, detail_text, at_text, prev_hash, row_hash
    )
    return AppendedEntry(audit_id, prev_hash, row_hash, at_text)
