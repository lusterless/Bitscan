"""POST /api/v1/agent/{id}/token/rotate (TS §6.1 L1067, §3.2 L190–L191,
§6.5 L1188; REQ-071; #62). No body, or {} (#60). The answer is exactly
agent_token, issued_at and expires_at; the new token is shown once.
"""

import json
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from bitscan_manager.api.agent.dependencies import AuthenticatedAgent, current_agent
from bitscan_manager.api.agent.schemas import RotateRequest, RotateResponse
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.enrolment import rotation as service
from bitscan_manager.services.users import TxAudit

router = APIRouter()
# Read by the route itself, so an empty body and a JSON null are told apart
# (#60: no body or {} only); documented as an optional RotateRequest.
_ROTATE_BODY: Final = {
    "required": False,
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/RotateRequest"}}
    },
}
_DETAIL = {
    401: "A valid agent token is required.",
    403: "The token is not yet inside its rotation window.",
    429: "The token was rotated less than 24 hours ago.",
}


def _check_body(raw: bytes) -> None:
    if not raw:
        return
    try:
        RotateRequest.model_validate(json.loads(raw))  # an object, and only {}
    except (ValueError, RecursionError, ValidationError):
        raise Problem(400, "invalid_request", "Invalid request: body") from None


@router.post(
    "/{id}/token/rotate",
    responses=problem_responses((400, 401, 403, 429, 503)),
    openapi_extra={"requestBody": _ROTATE_BODY},
)
async def rotate(
    request: Request,
    agent: Annotated[AuthenticatedAgent, Depends(current_agent)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> RotateResponse:
    _check_body(await request.body())  # 1 MiB cap: BodyLimit, before the route
    return await run_in_threadpool(_rotate, agent, runtime)


def _rotate(agent: AuthenticatedAgent, runtime: Runtime) -> RotateResponse:
    refusal: service.RotationRefused | None = None
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        try:
            done = service.rotate_token(
                AgentRepo(tx.conn),
                SettingsRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                caller=agent.caller,
                ip_last_seen=agent.ip_last_seen,
                now=runtime.clock.now(),
            )
        except service.RotationRefused as exc:  # its revoke and alert commit
            refusal = exc
    if refusal is not None:
        raise Problem(
            refusal.status,
            refusal.type,
            _DETAIL.get(refusal.status),
            refusal.headers or None,
        )
    return RotateResponse(
        agent_token=done.agent_token,
        issued_at=done.issued_at,
        expires_at=done.expires_at,
    )
