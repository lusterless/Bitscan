"""PUT /api/v1/agent/{id}/inventory[?job_id=…] (TS §6.1 L1066, §3.4
L239–L244, §6.5 L1186, §6.3 L1138; REQ-076, REQ-066; #72).

After-auth body (10 MiB gzip as sent, TASK-049): no FastAPI body parameter,
so nothing is read before a 401. Content-Encoding: gzip is required (#72 (a)).
The service decodes, classifies the job_id, applies the 10-minute window and
ingests; the answer is 204 with no body.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from bitscan_manager.api.agent.bodies import TooLarge, read_capped
from bitscan_manager.api.agent.dependencies import (
    AuthenticatedAgent,
    agent_uuid,
    agent_windows,
    content_coding,
    current_agent,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.request_log import job_id_var
from bitscan_manager.api.user import problem_responses
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.inventory import upload as service

router = APIRouter()
_DETAIL: Final = {
    400: "Invalid request: body",
    401: "A valid agent token is required.",
    409: "This job does not accept an inventory upload.",
    413: "The request body exceeds the size limit.",
    422: "The inventory exceeds a limit or does not match its list_sha256.",
    429: "Too many unscheduled inventory uploads.",
}
_INVENTORY_BODY: Final = {
    "required": True,
    "description": "The TS §6.5 inventory body, sent with Content-Encoding: gzip.",
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/InventoryBody"}}
    },
}


@router.put(
    "/{id}/inventory",
    status_code=204,
    responses=problem_responses((400, 401, 403, 409, 413, 422, 429, 503)),
    openapi_extra={"requestBody": _INVENTORY_BODY},
)
async def put_inventory(
    request: Request,
    agent: Annotated[AuthenticatedAgent, Depends(current_agent)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    job_id: str | None = None,
) -> Response:
    job = None if job_id is None else agent_uuid(job_id, "query.job_id")
    if job is not None:
        job_id_var.set(str(job))
    up = service.Upload(agent.caller.agent_id, job, runtime.clock.now())
    wake = runtime.sink_gate.wake
    if content_coding(request) != "gzip":  # #72 (a), case-insensitive
        await run_in_threadpool(
            service.refuse_unread, runtime.db, wake, up, 400, "not_gzip"
        )
        raise Problem(400, "invalid_request", "Invalid request: content-encoding")
    try:
        body = await read_capped(request)
    except TooLarge:
        await run_in_threadpool(
            service.refuse_unread, runtime.db, wake, up, 413, "too_large"
        )
        raise
    burst = agent_windows(request).new_packages
    try:
        await run_in_threadpool(
            service.store_upload, runtime.db, wake, runtime.limits, burst, up, body
        )
    except service.UploadRefused as exc:
        raise Problem(
            exc.status, exc.type, _DETAIL.get(exc.status), exc.headers or None
        ) from None
    return Response(status_code=204)
