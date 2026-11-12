"""GET /api/v1/auth/session, GET /auth/sessions and DELETE /auth/sessions/{id}
(TS §6.2; owner decision 2026-11-12, work/plans/session-cookie-proposal.md).

All three are session only, for any signed-in user, and only about the
caller's own sessions. A restricted admin session (no TOTP yet) is refused
with 403 totp_enrolment_required, as TS §6.2 allows it only /auth/totp/enrol
and /auth/logout; the web UI reads that answer as "signed in, enrol TOTP".
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
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
from bitscan_manager.auth import session_cookie, sessions
from bitscan_manager.auth.dependencies import require_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.auth.totp_enrol import PendingEnrolments
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/auth", tags=["auth"])
SCOPE = "sessions"


class CurrentSession(BaseModel):
    role: str
    totp_enrolled: bool
    totp_verified: bool
    expires_at: UtcDatetime


class SessionItem(BaseModel):
    session_id: int
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None
    expires_at: UtcDatetime
    totp_verified: bool
    current: bool


@router.get("/session", responses=problem_responses((401, 403, 429, 503)))
def current_session(
    principal: Annotated[Principal, Depends(require_session())],
) -> CurrentSession:
    """The caller's own session, so the web UI can restore itself on reload."""
    return CurrentSession(
        role=principal.role,
        totp_enrolled=principal.totp_enrolled,
        totp_verified=principal.totp_verified,
        expires_at=principal.expires_at,
    )


@router.get("/sessions", responses=problem_responses((401, 403, 429, 503)))
def list_sessions(
    principal: Annotated[Principal, Depends(require_session())],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[SessionItem]:
    after = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with runtime.db.transaction() as tx:
        rows = sessions.list_own(
            tx,
            user_id=principal.user_id,
            now=runtime.clock.now(),
            limit=page.limit + 1,
            after_id=after,
        )
    items = [
        SessionItem(
            session_id=row.token_id,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            totp_verified=row.totp_verified,
            current=row.token_id == principal.token_id,
        )
        for row in rows
    ]
    return page_of(items, page.limit, SCOPE, lambda item: item.session_id)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    responses=problem_responses((401, 403, 404, 429, 503)),
)
def end_session(
    session_id: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_session())],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> Response:
    """Ends one of the caller's own web sessions; 404 for anything else."""
    with runtime.db.transaction() as tx:
        done = sessions.end_own(
            tx,
            user_id=principal.user_id,
            token_id=session_id,
            now=runtime.clock.now(),
        )
        if done:
            tx.on_commit(runtime.sink_gate.wake)
    if not done:
        raise Problem(404, "not_found", "No such session.")
    pending = getattr(request.app.state, "totp_pending", None)
    if isinstance(pending, PendingEnrolments):
        pending.drop(session_id)
    response = Response(status_code=204)
    if session_id == principal.token_id:
        response.headers.append("Set-Cookie", session_cookie.clear_cookie_header())
    return response
