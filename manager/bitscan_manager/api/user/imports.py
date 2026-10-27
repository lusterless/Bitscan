"""GET /api/v1/imports (TS §6.2 L1107; REQ-173; #98 (h), (i)). Admin, session
or API token. Read-only: every bit_import column, newest first by import_id,
no filters, {items, next_cursor}. errors is returned as stored, warnings
included (#110); file_name is returned byte for byte as a JSON string.
"""

from typing import Annotated, Any, Final, Literal

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
from bitscan_manager.repositories.imports import imports_newest_first
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/imports", tags=["imports"])
SCOPE: Final = "imports"
_BIGINT_MAX: Final = 2**63 - 1


class ImportItem(BaseModel):
    """#98 (h): the bit_import columns in DDL order (TS §5.2)."""

    import_id: int
    file_name: str
    file_sha256: str
    policy_version: int | None
    mode: Literal["auto", "manual", "rebuild"]
    outcome: Literal["success", "skipped", "rejected"]
    plugins_added: int
    plugins_updated: int
    plugins_retired: int
    errors: list[dict[str, Any]]
    imported_by: int | None
    imported_at: UtcDatetime


def _before(cursor: str | None) -> int | None:
    """The import_id of the previous page's last item, checked before
    PostgreSQL casts it (builder checklist 1)."""
    if cursor is None:
        return None
    key = decode_cursor(SCOPE, cursor)
    if type(key) is int and 1 <= key <= _BIGINT_MAX:
        return key
    raise Problem(400, "invalid_request", "Invalid request: query.cursor")


@router.get("", responses=problem_responses((401, 403, 429, 503)))
def list_imports(
    principal: Annotated[Principal, Depends(require_role("admin"))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[ImportItem]:
    before = _before(page.cursor)
    with runtime.db.transaction() as tx:  # reads only
        rows = imports_newest_first(tx.conn, page.limit + 1, before)
    items = [ImportItem.model_validate(r, from_attributes=True) for r in rows]
    return page_of(items, page.limit, SCOPE, lambda i: i.import_id)
