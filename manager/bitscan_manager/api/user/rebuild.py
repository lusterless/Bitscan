"""POST /api/v1/policies/rebuild (admin, TOTP session, sink gate) and
GET /api/v1/tasks/{id} (admin, session or API token) (TS §6.2 L1084,
L1105-L1106, §4.2 L540; REQ-172; open questions #1, #20, #98 (f), (g), (i),
#102 (d)).

The rebuild is a sensitive action: it is refused for API tokens and during a
long audit-sink outage, and runs on the catalog service's worker; the route
answers 202 with the task id at once. The POST declares no body, so none is
read (#98 (f): no body or `{}`). The task route reads the `task` row in a
read-only transaction; there is no business logic to put in a service, as for
`GET /audit-log`.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from bitscan_manager.api.agent.schemas import UUID_PATTERN
from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role, require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories import imports
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.service import (
    RETRY_AFTER_S,
    STARTING_DETAIL,
    CatalogStarting,
)

router = APIRouter(tags=["policies"])
TOTP_ADMIN = Annotated[Principal, Depends(require_totp_session())]
ADMIN = Annotated[Principal, Depends(require_role("admin"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
# The hyphenated 8-4-4-4-12 form only (builder checklist 5); anything else 400.
TASK_ID = Annotated[str, Path(pattern=UUID_PATTERN)]
_BASE = (401, 403, 429, 503)


class RebuildStarted(BaseModel):
    task_id: UUID


class TaskFile(BaseModel):
    """One re-imported file; its findings are in `GET /imports`."""

    source_file: str
    import_id: int | None  # None if its record could not be written
    outcome: Literal["success", "rejected"]
    policy_id: int | None  # None when rejected
    policy_version: int | None


class TaskResult(BaseModel):
    """#98 (g) for a `succeeded` rebuild (rejected files included, #20)."""

    files: list[TaskFile]
    deleted_policy_ids: list[int]  # policies whose files were gone
    plugins_retired: int
    removed_leftovers: list[str]  # uploads of deleted policies, removed (crash window)
    not_imported: list[str]  # files with no import row, e.g. a refused copy


class TaskFailure(BaseModel):
    """A `failed` task: the rebuild errored, or start-up found it running."""

    error: str


class TaskItem(BaseModel):
    """#98 (g), in this field order."""

    task_id: UUID
    kind: Literal["rebuild"]
    state: Literal["running", "succeeded", "failed"]
    requested_by: int | None  # None for the CLI (#107)
    result: TaskResult | TaskFailure | None  # None while running
    started_at: UtcDatetime
    finished_at: UtcDatetime | None


@router.post(
    "/policies/rebuild",
    status_code=202,
    responses=problem_responses(_BASE),
)
def start_rebuild(principal: TOTP_ADMIN, runtime: RUNTIME) -> RebuildStarted:
    """Start a rebuild of both policy folders (TS §4.2); poll `GET /tasks/{id}`.
    Before the catalog start-up ends, 503 with Retry-After (#102 (d))."""
    catalog = runtime.catalog
    if catalog is None:
        raise Problem(503, ABOUT_BLANK, "The service is not ready.")
    actor = Actor(f"user:{principal.user_id}", principal.user_id)
    try:
        task_id = catalog.start_rebuild(principal.user_id, actor)
    except CatalogStarting:
        retry = {"Retry-After": str(RETRY_AFTER_S)}
        raise Problem(503, ABOUT_BLANK, STARTING_DETAIL, retry) from None
    return RebuildStarted(task_id=task_id)


@router.get("/tasks/{id}", responses=problem_responses((*_BASE, 404)))
def get_task(id: TASK_ID, principal: ADMIN, runtime: RUNTIME) -> TaskItem:
    """The `task` row (#98 (g)); 404 for an unknown id."""
    with runtime.db.transaction() as tx:  # reads only
        row = imports.get_task(tx.conn, UUID(id))
    if row is None:
        raise Problem(404, "not_found", "No such task.")
    return TaskItem.model_validate(row, from_attributes=True)
