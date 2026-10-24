"""POST /api/v1/agent/{id}/heartbeat (TS §6.1 L1063, §6.5 L1163, §3.3
L202; REQ-070, REQ-086, REQ-088). The answer is exactly job_pull_seconds,
max_parallel_plugins and server_time; it never carries jobs or commands.
The bsa_ check runs before the body is parsed (TASK-083: the route class),
so a bad token is 401 and counted whatever the body; a valid token with a
bad body is still 400.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from bitscan_manager.api.agent.dependencies import (
    AuthenticatedAgent,
    agent_windows,
    current_agent,
    token_first,
)
from bitscan_manager.api.agent.schemas import HeartbeatRequest, HeartbeatResponse
from bitscan_manager.api.attempt_limits import limit_first
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services import agents as service
from bitscan_manager.services.audit.metrics import HEARTBEAT_LATENCY
from bitscan_manager.services.users import TxAudit

router = APIRouter(route_class=limit_first(token_first))


@router.post("/{id}/heartbeat", responses=problem_responses((401, 403, 429, 503)))
def heartbeat(
    body: HeartbeatRequest,
    agent: Annotated[AuthenticatedAgent, Depends(current_agent)],
    request: Request,
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> HeartbeatResponse:
    started = time.perf_counter()
    skew = agent_windows(request).clock_skew
    gone = False
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        try:
            answer = service.heartbeat(
                AgentRepo(tx.conn),
                SettingsRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                skew,
                tx.on_commit,
                agent_id=agent.caller.agent_id,
                beat=service.Beat(
                    body.agent_version, body.runner_helpers, body.clock, body.last_error
                ),
                now=runtime.clock.now(),
            )
        except service.AgentGone:
            gone = True
    if gone:
        raise Problem(401, "token_revoked", "A valid agent token is required.")
    HEARTBEAT_LATENCY.observe(time.perf_counter() - started)
    return HeartbeatResponse(
        job_pull_seconds=answer.job_pull_seconds,
        max_parallel_plugins=answer.max_parallel_plugins,
        server_time=answer.server_time,
    )
