"""GET /api/v1/audit-log (TS §6.2 L1127, §5.3 L1051; REQ-085; #68). Admin,
session or API token. Read-only: newest first, the eight columns per item
plus detail_text, {items, next_cursor}. detail_text is PostgreSQL's own
detail::text, the exact string the chain hashed (null when detail is null),
and at is the hashed UTC text form, so a reader re-verifies row_hash with
compute_row_hash from detail_text, never by re-serialising detail (jsonb
writes 1e-07 as 0.0000001; lead ruling 2026-10-23, TASK-078 revision 1).
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from bitscan_manager.api.pagination import (
    Page,
    PageParams,
    decode_cursor,
    page_of,
    page_params,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.audit_log import page_newest_first
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/audit-log", tags=["audit-log"])
SCOPE = "audit_log"


class AuditItem(BaseModel):
    audit_id: int
    actor: str
    action: str
    target: str | None
    detail: Any
    detail_text: str | None
    at: UtcDatetime
    prev_hash: str
    row_hash: str


@router.get("", responses=problem_responses((401, 403, 429, 503)))
def list_audit_log(
    principal: Annotated[Principal, Depends(require_role("admin"))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[AuditItem]:
    before = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if before is not None and not isinstance(before, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with runtime.db.transaction() as tx:  # reads only
        rows = page_newest_first(tx.conn, page.limit + 1, before)
    items = [
        AuditItem(
            audit_id=r[0],
            actor=r[1],
            action=r[2],
            target=r[3],
            detail=None if r[4] is None else json.loads(r[4]),
            detail_text=r[4],
            at=r[5],
            prev_hash=r[6],
            row_hash=r[7],
        )
        for r in rows
    ]
    return page_of(items, page.limit, SCOPE, lambda i: i.audit_id)
