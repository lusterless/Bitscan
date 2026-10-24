"""POST /api/v1/agent/enroll (TS §6.1 L1062, §3.2 L183–L188, §6.3 L1136;
REQ-068, REQ-065; #55 (c), (d), #59; plan work/plans/TASK-067.md).

Only a bse_ token is accepted here. First 10 attempts per minute per source
IP, every attempt counted and before the body is even read (TASK-082: the
route class), 429; then the dependency checks the token shape, before the
body is validated. A wrong shape, a non-IP peer, and every refused
bse_ (unknown, expired, revoked, exhausted, outside allowed_cidrs) get one
401 unauthorized and count as a failed token check (#59).
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from bitscan_manager.api.agent.dependencies import (
    agent_windows,
    bearer_token,
    failed_check,
    source_ip,
)
from bitscan_manager.api.agent.schemas import EnrolRequest, EnrolResponse
from bitscan_manager.api.attempt_limits import limit_first, per_ip_limit
from bitscan_manager.api.peer import peer_key
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.tokens import AgentTokenKind, is_agent_token
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.enrolment import EnrolmentRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.enrolment import enrol as service
from bitscan_manager.services.users import TxAudit

_enrol_limit = per_ip_limit(
    lambda runtime, ip: runtime.limits.allow_enrol(ip), "Too many enrolment attempts."
)
router = APIRouter(route_class=limit_first(_enrol_limit))
RUNTIME = Annotated[Runtime, Depends(get_runtime)]


@dataclass(frozen=True)
class EnrolCaller:
    token: str  # a well-formed bse_; whether it is usable is checked atomically
    source_ip: str
    limiter_key: str


def enrolment_caller(request: Request, runtime: RUNTIME) -> EnrolCaller:
    peer = source_ip(request)
    key = peer_key(request)  # keyed as on user routes (REQ-065 (3))
    raw = bearer_token(request)
    if raw is None or peer is None or not is_agent_token(raw, AgentTokenKind.ENROLMENT):
        raise failed_check(runtime, key)
    return EnrolCaller(raw, peer, key)


enrolment_caller.bitscan_agent_auth = "bse_"  # type: ignore[attr-defined]


@router.post("/enroll", responses=problem_responses((401, 429, 503)))
def enroll(
    body: EnrolRequest,
    caller: Annotated[EnrolCaller, Depends(enrolment_caller)],
    request: Request,
    runtime: RUNTIME,
) -> EnrolResponse:
    window = agent_windows(request).enrolments
    refused = False
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        try:
            done = service.enrol(
                AgentRepo(tx.conn),
                EnrolmentRepo(tx.conn),
                JobRepo(tx.conn),
                SettingsRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                window,
                tx.on_commit,
                enrolment_token=caller.token,
                body=service.Enrolment(
                    body.hostname,
                    body.machine_id,
                    body.agent_version,
                    body.os_pretty_name,
                ),
                source_ip=caller.source_ip,
                now=runtime.clock.now(),
            )
        except service.EnrolRefused:  # use_token changed nothing
            refused = True
    if refused:
        raise failed_check(runtime, caller.limiter_key)
    return EnrolResponse(
        agent_id=done.agent_id,
        agent_token=done.agent_token,
        issued_at=done.issued_at,
        expires_at=done.expires_at,
        status=done.status,
    )
