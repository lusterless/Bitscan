"""/api/v1/enrollment-tokens and /api/v1/enrollment-requests (TS §6.2
L1114–L1116; TS §3.2 L181, L185–L192; #48, #68).

Managing enrolment tokens and deciding requests are sensitive actions (TS
§6.2 L1084): they need an admin TOTP-verified session, refuse API tokens and
are refused during a long audit-sink outage. Listing requests is admin with
a session or API token. Enrolment tokens have no PATCH. The bse_ token
appears only in the create response; no response ever holds a token or a
token hash.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

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
from bitscan_manager.api.user.agents import AgentStatus
from bitscan_manager.auth.dependencies import require_role, require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.enrolment import EnrolmentRepo, EnrolmentTokenRow
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.enrolment import enrolment_tokens as service
from bitscan_manager.services.enrolment import requests as decisions
from bitscan_manager.services.users import TxAudit

tokens = APIRouter(prefix="/enrollment-tokens", tags=["enrollment-tokens"])
requests = APIRouter(prefix="/enrollment-requests", tags=["enrollment-requests"])
SCOPE = "enrollment_tokens"
ADMIN = Annotated[Principal, Depends(require_totp_session())]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_BASE = (401, 403, 429, 503)


class CreateToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_uses: StrictInt = Field(default=1, ge=1, le=10_000)
    expires_in_hours: StrictInt = Field(default=24, ge=1, le=720)
    allowed_cidrs: list[StrictStr] | None = Field(
        default=None, min_length=1, max_length=service.MAX_CIDRS
    )
    auto_approve: StrictBool = False


class TokenItem(BaseModel):
    token_id: int
    max_uses: int
    uses: int
    auto_approve: bool
    allowed_cidrs: list[str] | None
    expires_at: UtcDatetime
    created_at: UtcDatetime
    revoked_at: UtcDatetime | None
    created_by: int


class CreatedToken(BaseModel):
    token_id: int
    token: str
    max_uses: int
    uses: int
    auto_approve: bool
    allowed_cidrs: list[str] | None
    expires_at: UtcDatetime
    created_at: UtcDatetime


def _item(row: EnrolmentTokenRow) -> TokenItem:
    return TokenItem(
        token_id=row.token_id,
        max_uses=row.max_uses,
        uses=row.uses,
        auto_approve=row.auto_approve,
        allowed_cidrs=row.allowed_cidrs,
        expires_at=row.expires_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        created_by=row.created_by,
    )


@contextmanager
def _stores(runtime: Runtime) -> Iterator[tuple[EnrolmentRepo, TxAudit]]:
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        yield EnrolmentRepo(tx.conn), TxAudit(PgAuditRepo(tx.conn), tx.on_commit)


@tokens.post("", status_code=201, responses=problem_responses(_BASE))
def create_token(body: CreateToken, principal: ADMIN, runtime: RUNTIME) -> CreatedToken:
    failure: Problem | None = None
    try:
        with _stores(runtime) as (repo, audit):
            made = service.create_token(
                repo,
                audit,
                admin_id=principal.user_id,
                max_uses=body.max_uses,
                expires_in_hours=body.expires_in_hours,
                allowed_cidrs=body.allowed_cidrs,
                auto_approve=body.auto_approve,
                now=runtime.clock.now(),
            )
    except service.InvalidCidrs:
        failure = Problem(400, "invalid_request", "Invalid request: body.allowed_cidrs")
    if failure is not None:
        raise failure
    row = made.row
    return CreatedToken(
        token_id=row.token_id,
        token=made.token,
        max_uses=row.max_uses,
        uses=row.uses,
        auto_approve=row.auto_approve,
        allowed_cidrs=row.allowed_cidrs,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@tokens.get("", responses=problem_responses(_BASE))
def list_tokens(
    principal: ADMIN,
    runtime: RUNTIME,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[TokenItem]:
    after = None if page.cursor is None else decode_cursor(SCOPE, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with _stores(runtime) as (repo, _):
        rows = repo.token_page(page.limit + 1, after)
    return page_of([_item(r) for r in rows], page.limit, SCOPE, lambda t: t.token_id)


@tokens.get("/{token_id}", responses=problem_responses((*_BASE, 404)))
def get_token(token_id: int, principal: ADMIN, runtime: RUNTIME) -> TokenItem:
    with _stores(runtime) as (repo, _):
        row = repo.get_token(token_id)
    if row is None:
        raise Problem(404, "not_found", "No such enrolment token.")
    return _item(row)


@tokens.delete(
    "/{token_id}", status_code=204, responses=problem_responses((*_BASE, 404))
)
def revoke_token(token_id: int, principal: ADMIN, runtime: RUNTIME) -> Response:
    with _stores(runtime) as (repo, audit):
        found = service.revoke_token(
            repo,
            audit,
            admin_id=principal.user_id,
            token_id=token_id,
            now=runtime.clock.now(),
        )
    if not found:
        raise Problem(404, "not_found", "No such enrolment token.")
    return Response(status_code=204)


# ------------------------------------------------- /enrollment-requests (#68)


class MatchItem(BaseModel):
    agent_id: UUID
    hostname: str
    machine_id: str
    status: AgentStatus


class RequestItem(BaseModel):
    """Never the new token or its hash (REQ-063 (5))."""

    request_id: int
    # kind and decision: the enrollment_request CHECK values (TS §5.2 L763,
    # L774; PD-29).
    kind: Literal["new", "reenrol"]
    agent_id: UUID
    hostname: str
    machine_id: str
    os_pretty_name: str | None
    agent_version: str
    source_ip: str
    requested_at: UtcDatetime
    token_expires_at: UtcDatetime
    decision: Literal["approved", "rejected"] | None
    decided_by: int | None
    decided_at: UtcDatetime | None
    matches: list[MatchItem]


def _request_item(view: decisions.RequestView) -> RequestItem:
    r = view.request
    return RequestItem(
        request_id=r.request_id,
        kind=r.kind,
        agent_id=r.agent_id,
        hostname=r.hostname,
        machine_id=r.machine_id,
        os_pretty_name=r.os_pretty_name,
        agent_version=r.agent_version,
        source_ip=r.source_ip,
        requested_at=r.requested_at,
        token_expires_at=r.token_expires_at,
        decision=r.decision,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
        matches=[
            MatchItem(
                agent_id=m.agent_id,
                hostname=m.hostname,
                machine_id=m.machine_id,
                status=m.status,
            )
            for m in view.matches
        ],
    )


@requests.get("", responses=problem_responses(_BASE))
def list_requests(
    principal: Annotated[Principal, Depends(require_role("admin"))],
    runtime: RUNTIME,
    page: Annotated[PageParams, Depends(page_params)],
    state: Literal["pending", "decided", "all"] = "pending",
) -> Page[RequestItem]:
    scope = f"enrollment_requests:{state}"  # a cursor is valid for its state only
    after = None if page.cursor is None else decode_cursor(scope, page.cursor)
    if after is not None and not isinstance(after, int):
        raise Problem(400, "invalid_request", "Invalid request: query.cursor")
    with runtime.db.transaction() as tx:
        views = decisions.list_requests(
            EnrolmentRepo(tx.conn), state, page.limit + 1, after
        )
    items = [_request_item(v) for v in views]
    return page_of(items, page.limit, scope, lambda i: i.request_id)


def _decide(
    runtime: Runtime, admin_id: int, request_id: int, approve: bool
) -> RequestItem:
    failure: Problem | None = None
    now: datetime = runtime.clock.now()
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            view = decisions.decide_request(
                EnrolmentRepo(tx.conn),
                AgentRepo(tx.conn),
                JobRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                request_id=request_id,
                approve=approve,
                admin_id=admin_id,
                now=now,
            )
    except decisions.RequestNotFound:
        failure = Problem(404, "not_found", "No such enrolment request.")
    except decisions.RequestConflict as exc:  # rolled back: nothing changed
        failure = Problem(409, "conflict", exc.reason)
    if failure is not None:
        raise failure
    return _request_item(view)


@requests.post("/{request_id}/approve", responses=problem_responses((*_BASE, 404, 409)))
def approve_request(request_id: int, principal: ADMIN, runtime: RUNTIME) -> RequestItem:
    return _decide(runtime, principal.user_id, request_id, approve=True)


@requests.post("/{request_id}/reject", responses=problem_responses((*_BASE, 404, 409)))
def reject_request(request_id: int, principal: ADMIN, runtime: RUNTIME) -> RequestItem:
    return _decide(runtime, principal.user_id, request_id, approve=False)


router = APIRouter()  # mounted by api/user/__init__.py
router.include_router(tokens)
router.include_router(requests)
