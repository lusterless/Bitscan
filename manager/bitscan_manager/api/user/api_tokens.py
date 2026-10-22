"""/api/v1/api-tokens (TS §6.2 L1098-L1099; #8, #47, #48, #52)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

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
from bitscan_manager.auth import api_tokens
from bitscan_manager.auth.dependencies import require_role, require_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])
SCOPE = "api_tokens"


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=api_tokens.NAME_MAX)
    expires_in_days: StrictInt | None = Field(
        default=None, ge=1, le=api_tokens.MAX_DAYS
    )


class Created(BaseModel):
    token_id: int
    token: str
    name: str | None
    expires_at: UtcDatetime


class ApiTokenItem(BaseModel):
    token_id: int
    name: str | None
    created_at: UtcDatetime
    expires_at: UtcDatetime
    last_used_at: UtcDatetime | None
    revoked_at: UtcDatetime | None


@router.post("", status_code=201, responses=problem_responses((401, 403, 429, 503)))
def create(
    body: CreateRequest,
    principal: Annotated[Principal, Depends(require_session(admin_totp=True))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Created:
    """Web session only; an admin needs a TOTP-verified session."""  # TS §6.2 L1081
    with runtime.db.transaction() as tx:
        made = api_tokens.create_api_token(
            tx,
            user_id=principal.user_id,
            name=body.name,
            days=body.expires_in_days,
            now=runtime.clock.now(),
            actor=f"user:{principal.user_id}",
        )
        tx.on_commit(runtime.sink_gate.wake)
    return Created(
        token_id=made.token_id,
        token=made.token,
        name=made.name,
        expires_at=made.expires_at,
    )


@router.get("", responses=problem_responses((401, 403, 429, 503)))
def list_tokens(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[ApiTokenItem]:
    after = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with runtime.db.transaction() as tx:
        rows = api_tokens.list_own(
            tx, user_id=principal.user_id, limit=page.limit + 1, after_id=after
        )
    items = [ApiTokenItem(**vars(row)) for row in rows]
    return page_of(items, page.limit, SCOPE, lambda item: item.token_id)


@router.delete(
    "/{token_id}",
    status_code=204,
    responses=problem_responses((401, 403, 404, 429, 503)),
)
def revoke(
    token_id: int,
    principal: Annotated[Principal, Depends(require_role("viewer"))],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Response:
    """Your own API tokens only; an API token may revoke them too (#8)."""
    with runtime.db.transaction() as tx:
        done = api_tokens.revoke_own(
            tx,
            user_id=principal.user_id,
            token_id=token_id,
            now=runtime.clock.now(),
            actor=f"user:{principal.user_id}",
        )
        if done:
            tx.on_commit(runtime.sink_gate.wake)
    if not done:
        raise Problem(404, "not_found", "No such API token.")
    return Response(status_code=204)
