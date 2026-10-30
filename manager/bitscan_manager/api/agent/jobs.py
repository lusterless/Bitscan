"""GET /api/v1/agent/{id}/jobs and POST /api/v1/agent/{id}/jobs/{job_id}/
results (TS §6.1 L1064–L1065, L1071–L1072, §6.3 L1138, §6.5 L1165–L1184;
REQ-072, REQ-073, REQ-066, REQ-087, REQ-088, REQ-213, REQ-214; #124).

The results route reads its own body after the token check (after-auth cap,
1.5 MiB as sent), so it declares no FastAPI body parameter: nothing is read
before a 401. A gzip body is inflated as a stream to at most 1.5 MiB. A
well-formed batch goes to the intake service; a refused one answers 409
job_not_acceptable, stores nothing and writes one refusal entry in its own
transaction. The log line of an accepted batch carries counts only.
"""

import json
import logging
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from bitscan_manager.api.agent.bodies import TooLarge, read_capped
from bitscan_manager.api.agent.dependencies import (
    AuthenticatedAgent,
    agent_uuid,
    agent_windows,
    content_coding,
    current_agent,
)
from bitscan_manager.api.agent.schemas import (
    JobsResponse,
    ResultsRequest,
    ResultsResponse,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.request_log import job_id_var
from bitscan_manager.api.user import problem_responses
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services import jobs as service
from bitscan_manager.services.inventory.decode import InventoryRefused, gunzip_capped
from bitscan_manager.services.jobs import intake
from bitscan_manager.services.users import TxAudit

log = logging.getLogger("bitscan_manager.jobs")
router = APIRouter()
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
AGENT = Annotated[AuthenticatedAgent, Depends(current_agent)]
RESULT_BATCH_CAP: Final = 1_572_864  # 1.5 MiB (TS §6.3 L1138, #57 (b))
_RESULTS_BODY: Final = {
    "required": True,
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/ResultsRequest"}}
    },
}


@router.get("/{id}/jobs", responses=problem_responses((401, 403, 429, 503)))
def pull_jobs(agent: AGENT, runtime: RUNTIME) -> JobsResponse:
    with runtime.db.transaction() as tx:
        payloads = service.pull_jobs(
            JobRepo(tx.conn), agent.caller.agent_id, runtime.clock.now()
        )
    return JobsResponse.model_validate({"jobs": payloads})


def _refuse(
    request: Request,
    runtime: Runtime,
    agent_id: UUID,
    job_id: UUID,
    reason: str,
    detail: dict[str, object],
    count_flood: bool = True,
) -> None:
    flood = agent_windows(request).result_409
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        service.refuse_results(
            TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
            flood,
            tx.on_commit,
            agent_id=agent_id,
            job_id=job_id,
            reason=reason,
            detail=detail,
            count_flood=count_flood,
        )


def _accept(
    runtime: Runtime, agent_id: UUID, job_id: UUID, batch: ResultsRequest
) -> intake.Accepted | intake.Refused:
    return intake.accept_results(
        runtime.db,
        agent_id=agent_id,
        job_id=job_id,
        batch=batch,
        now=runtime.clock.now(),
    )


def _batch(body: bytes, encoding: str | None) -> ResultsRequest:  # lowercased
    if encoding == "gzip":
        body = gunzip_capped((body,), RESULT_BATCH_CAP)  # 413 past 1.5 MiB
    elif encoding not in (None, "identity"):
        raise Problem(400, "invalid_request", "Invalid request: content-encoding")
    try:
        return ResultsRequest.model_validate(json.loads(body))
    except (ValueError, RecursionError, ValidationError):
        raise Problem(400, "invalid_request", "Invalid request: body") from None


@router.post(
    "/{id}/jobs/{job_id}/results",
    responses=problem_responses((400, 401, 403, 409, 413, 429, 503)),
    openapi_extra={"requestBody": _RESULTS_BODY},
)
async def post_results(
    id: str, job_id: str, request: Request, agent: AGENT, runtime: RUNTIME
) -> ResultsResponse:
    job = agent_uuid(job_id, "path.job_id")
    job_id_var.set(str(job))
    agent_id = agent.caller.agent_id
    encoding = content_coding(request)
    try:
        batch = _batch(await read_capped(request), encoding)
    except (TooLarge, InventoryRefused) as exc:
        if isinstance(exc, InventoryRefused) and exc.status != 413:
            raise Problem(exc.status, exc.type, "Invalid request: body") from None
        await run_in_threadpool(
            _refuse, request, runtime, agent_id, job, "too_large", {}
        )
        raise TooLarge from None
    outcome = await run_in_threadpool(_accept, runtime, agent_id, job, batch)
    if isinstance(outcome, intake.Refused):
        detail: dict[str, object] = {
            "results": len(batch.results),
            "final": batch.final,
        }
        await run_in_threadpool(
            _refuse,
            request,
            runtime,
            agent_id,
            job,
            outcome.reason,
            detail,
            not outcome.own_cancelled,  # #124 (f): not a flood
        )
        raise Problem(409, "job_not_acceptable", "This job does not accept results.")
    counts = {"accepted": outcome.accepted, "duplicates": outcome.duplicates}
    log.info("result batch accepted", extra={"data": counts})
    return ResultsResponse.model_validate(counts)
