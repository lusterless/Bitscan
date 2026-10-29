"""GET /api/v1/policies, GET /policies/{id} (viewer), PATCH /policies/{id}
(admin, session or API token) and DELETE /policies/{id} (admin, TOTP session,
sink gate) (TS §6.2 L1100-L1102, L1104, L1084, §4.3 L546-L550; REQ-168,
REQ-169, REQ-171; #1, #9, #98). Lists are {items, next_cursor}. Stored text
is returned as stored, as JSON strings. No route here edits plugins or
commands; every role sees `execute` (catalog content, not host output).
"""

from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from bitscan_manager.api.pagination import (
    Page,
    PageParams,
    decode_cursor,
    page_of,
    page_params,
)
from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role, require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.catalog_admin import ProfileItem
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.importer import profiles as service
from bitscan_manager.services.importer.delete import (
    PolicyAlreadyDeleted as DeleteAlreadyDeleted,
)
from bitscan_manager.services.importer.delete import PolicyNotFound as DeleteNotFound
from bitscan_manager.services.importer.service import (
    RETRY_AFTER_S,
    STARTING_DETAIL,
    CatalogStarting,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer

router = APIRouter(prefix="/policies", tags=["policies"])
VIEWER = Annotated[Principal, Depends(require_role("viewer"))]
ADMIN = Annotated[Principal, Depends(require_role("admin"))]
# A sensitive action (#1): admin, TOTP-verified session, the sink gate.
TOTP_ADMIN = Annotated[Principal, Depends(require_totp_session())]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
PAGE = Annotated[PageParams, Depends(page_params)]
# Digits only, so "+1", "1.0" and "1_0" are 400 (REQ-169 (3)).
POLICY_ID = Annotated[str, Path(pattern="^[0-9]{1,20}$")]
_BASE = (401, 403, 429, 503)
SCOPE: Final = "policies"
_BIGINT_MAX: Final = 2**63 - 1
_NAME_MAX: Final = 128  # policy.policy_name VARCHAR(128)
PolicyStatus = Literal["enabled", "disabled"]
_MANAGED: Final = "This policy is managed in the server folder; change its file there."


class PolicyItem(BaseModel):
    """#98 (a), in this field order."""

    policy_id: int
    policy_name: str
    policy_description: str
    policy_status: PolicyStatus
    file_status: PolicyStatus
    status_overridden: bool
    family_id: int
    family_name: str
    format_version: str
    version: int
    source_file: str
    plugin_count: int
    imported_at: UtcDatetime
    updated_at: UtcDatetime


class PolicyPluginItem(BaseModel):
    """#98 (b), in this field order; display_name from v_plugin."""

    plugin_uuid: UUID
    sort_order: int
    display_name: str
    plugin_name: str
    control_ref: str | None
    plugin_description: str
    execute: str
    execute_sha256: str
    operator: str
    expected_result: str
    timeout_s: int
    state: Literal["active", "retired"]
    updated_at: UtcDatetime


class PolicyDetailItem(PolicyItem):
    deleted_at: UtcDatetime | None
    plugins: list[PolicyPluginItem]


class PatchPolicy(BaseModel):
    """Exactly one of {"policy_status": "enabled" | "disabled"} or
    {"status_overridden": false} (REQ-168)."""

    model_config = ConfigDict(extra="forbid")
    policy_status: PolicyStatus | None = None
    status_overridden: StrictBool | None = None


def _item(r: ProfileItem) -> PolicyItem:
    return PolicyItem.model_validate(r, from_attributes=True)


def _not_found() -> Problem:
    return Problem(404, "not_found", "No such policy.")


def _policy_id(value: str) -> int:
    number = int(value)  # the path pattern allows ASCII digits only
    if not 1 <= number <= _BIGINT_MAX:
        raise _not_found()  # an integer no policy_id can hold
    return number


def _after(cursor: str | None) -> tuple[str, int] | None:
    """The (policy_name, policy_id) of the previous page's last item, checked
    before PostgreSQL casts it (builder checklist 1)."""
    if cursor is None:
        return None
    key = decode_cursor(SCOPE, cursor)
    if (
        isinstance(key, list)
        and len(key) == 2
        and isinstance(key[0], str)
        and 1 <= len(key[0]) <= _NAME_MAX
        and "\x00" not in key[0]
        and type(key[1]) is int
        and 1 <= key[1] <= _BIGINT_MAX
    ):
        return key[0], key[1]
    raise Problem(400, "invalid_request", "Invalid request: query.cursor")


@router.get("", responses=problem_responses(_BASE))
def list_policies(
    principal: VIEWER,
    runtime: RUNTIME,
    page: PAGE,
    status: Annotated[PolicyStatus | None, Query()] = None,
) -> Page[PolicyItem]:
    after = _after(page.cursor)
    with runtime.db.transaction() as tx:
        rows = service.list_profiles(
            tx.conn, limit=page.limit + 1, status=status, after=after
        )
    items = [_item(r) for r in rows]
    return page_of(items, page.limit, SCOPE, lambda p: [p.policy_name, p.policy_id])


@router.get("/{id}", responses=problem_responses((*_BASE, 404)))
def get_policy(id: POLICY_ID, principal: VIEWER, runtime: RUNTIME) -> PolicyDetailItem:
    policy_id = _policy_id(id)
    try:
        with runtime.db.transaction() as tx:
            found = service.get_profile(tx.conn, policy_id)
    except service.PolicyNotFound:
        raise _not_found() from None
    return PolicyDetailItem(
        **_item(found.item).model_dump(),
        deleted_at=found.deleted_at,
        plugins=[
            PolicyPluginItem.model_validate(p, from_attributes=True)
            for p in found.plugins
        ],
    )


@router.patch("/{id}", responses=problem_responses((*_BASE, 404, 409)))
def patch_policy(
    id: POLICY_ID, body: PatchPolicy, principal: ADMIN, runtime: RUNTIME
) -> PolicyItem:
    """Sets the status with an override, or clears the override. Audited;
    a re-enable alerts (#101). 409 for a deleted policy (#98 (c))."""
    policy_id = _policy_id(id)
    change: service.StatusChange
    if body.model_fields_set == {"policy_status"} and body.policy_status is not None:
        change = body.policy_status
    elif (
        body.model_fields_set == {"status_overridden"}
        and body.status_overridden is False
    ):
        change = "clear_override"
    else:
        raise Problem(
            400, "invalid_request", "Invalid request: give exactly one change"
        )
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            row = service.change_status(
                tx,
                policy_id,
                change,
                actor=f"user:{principal.user_id}",
                now=runtime.clock.now(),
            )
    except service.PolicyNotFound:
        failure = _not_found()
    except service.PolicyAlreadyDeleted:
        failure = Problem(409, "conflict", "The policy is deleted.")
    if failure is not None:
        raise failure
    return _item(row)


@router.delete(
    "/{id}", status_code=204, responses=problem_responses((*_BASE, 404, 409))
)
def delete_policy(id: POLICY_ID, principal: TOTP_ADMIN, runtime: RUNTIME) -> Response:
    """Soft-delete a policy (TS §4.3 L550, REQ-167) through the catalog
    service, under the catalog lock; 204. #98 (e): unknown 404, already
    deleted 409 `conflict`, server folder 409 `policy_managed_on_server`.
    Before the catalog start-up ends, 503 with Retry-After (#102 (d))."""
    policy_id = _policy_id(id)
    catalog = runtime.catalog
    if catalog is None:
        raise Problem(503, ABOUT_BLANK, "The service is not ready.")
    failure: Problem | None = None
    try:
        catalog.delete(policy_id, f"user:{principal.user_id}")
    except CatalogStarting:
        retry = {"Retry-After": str(RETRY_AFTER_S)}
        failure = Problem(503, ABOUT_BLANK, STARTING_DETAIL, retry)
    except DeleteNotFound:
        failure = _not_found()
    except DeleteAlreadyDeleted:
        failure = Problem(409, "conflict", "The policy is deleted.")
    except PolicyManagedOnServer:
        failure = Problem(409, "policy_managed_on_server", _MANAGED)
    if failure is not None:
        raise failure
    return Response(status_code=204)
