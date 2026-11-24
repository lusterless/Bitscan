"""POST /api/v1/agent/{id}/jobs/{job_id}/kubeconfig and PUT /api/v1/agent/
{id}/jobs/{job_id}/files/{name} (TS §3.8, §6.1, §6.5; owner decision
2026-11-23).

The kubeconfig of a cluster_audit job is returned once, to that job's agent,
while the job is dispatched or running; a second request is 409
job_not_acceptable and alerts. The answer is `Cache-Control: no-store` and its
content is never logged or audit-logged: the fetch entry names the job, the
agent, the kubeconfig and the source IP.

A file upload is one gzip body, read after the token check (at most 32 MiB as
sent, 64 MiB inflated), for one of the four names, once per job. The manager
inflates it itself to check the size and compute the SHA-256.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from bitscan_manager.api.agent.bodies import TooLarge, read_capped
from bitscan_manager.api.agent.dependencies import (
    AuthenticatedAgent,
    agent_uuid,
    current_agent,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.request_log import job_id_var
from bitscan_manager.api.user import problem_responses
from bitscan_manager.repositories import cluster_audit as repo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.inventory.decode import InventoryRefused, gunzip_capped
from bitscan_manager.services.users import TxAudit

router = APIRouter()
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
AGENT = Annotated[AuthenticatedAgent, Depends(current_agent)]
FILE_CAP: Final = 32 * 1024 * 1024  # as sent (gzip)
INFLATED_CAP: Final = 64 * 1024 * 1024
LATE_WINDOW: Final = timedelta(days=7)
REFETCH_ALERT: Final = "kubeconfig_refetch"
_NOT_ACCEPTABLE: Final = "This job does not accept this request."


class KubeconfigAnswer(BaseModel):
    kubeconfig: str


class FileAccepted(BaseModel):
    name: str
    size_bytes: int
    sha256: str


def _not_acceptable() -> Problem:
    return Problem(409, "job_not_acceptable", _NOT_ACCEPTABLE)


def _fetch(runtime: Runtime, agent: AuthenticatedAgent, job_id: UUID) -> str:
    agent_id = agent.caller.agent_id
    now = runtime.clock.now()
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        conn = tx.conn
        audit = TxAudit(PgAuditRepo(conn), tx.on_commit)
        job = repo.job_for_agent(conn, job_id, agent_id)
        if (
            job is None
            or job.kind != "cluster_audit"
            or job.state not in ("dispatched", "running")
            or job.kubeconfig_id is None
            or agent.source_ip is None  # kubeconfig_fetch.source_ip is NOT NULL
        ):
            raise _not_acceptable()
        source_ip: str = agent.source_ip
        secret = repo.kubeconfig_secret(conn, job.kubeconfig_id)
        if secret is None:
            raise _not_acceptable()
        name, ciphertext = secret
        detail = {
            "job_id": str(job_id),
            "kubeconfig_id": job.kubeconfig_id,
            "name": name,
            "source_ip": agent.source_ip,
        }
        if not repo.insert_fetch(conn, job_id, job.kubeconfig_id, source_ip, now):
            audit.alert(
                REFETCH_ALERT,
                f"agent:{agent_id}",
                "kubeconfig.refetch",
                f"job:{job_id}",
                detail,
            )
            refused = True
        else:
            audit.audit(
                f"agent:{agent_id}", "kubeconfig.fetch", f"job:{job_id}", detail
            )
            refused = False
    if refused:  # the alert is committed before the refusal is answered
        raise _not_acceptable()
    return runtime.totp_cipher.decrypt(ciphertext).decode("utf-8")


@router.post(
    "/{id}/jobs/{job_id}/kubeconfig",
    responses=problem_responses((401, 403, 409, 429, 503)),
)
async def fetch_kubeconfig(
    id: str, job_id: str, agent: AGENT, runtime: RUNTIME, response: Response
) -> KubeconfigAnswer:
    job = agent_uuid(job_id, "path.job_id")
    job_id_var.set(str(job))
    content = await run_in_threadpool(_fetch, runtime, agent, job)
    response.headers["Cache-Control"] = "no-store"
    return KubeconfigAnswer(kubeconfig=content)


def _store(
    runtime: Runtime,
    agent: AuthenticatedAgent,
    job_id: UUID,
    name: str,
    truncated: bool,
    body: bytes,
    inflated: bytes,
) -> FileAccepted:
    agent_id = agent.caller.agent_id
    now: datetime = runtime.clock.now()
    sha = hashlib.sha256(inflated).hexdigest()
    with runtime.db.transaction() as tx:
        tx.on_commit(runtime.sink_gate.wake)
        conn = tx.conn
        job = repo.job_for_agent(conn, job_id, agent_id)
        if (
            job is None
            or job.kind != "cluster_audit"
            or job.dispatched_at is None
            or now > job.dispatched_at + LATE_WINDOW
            or job.state == "cancelled"
        ):
            raise _not_acceptable()
        if not repo.insert_file(
            conn,
            job_id=job_id,
            name=name,
            size_bytes=len(inflated),
            sha256=sha,
            truncated=truncated,
            content_gz=body,
            now=now,
        ):
            raise _not_acceptable()
        TxAudit(PgAuditRepo(conn), tx.on_commit).audit(
            f"agent:{agent_id}",
            "scan_file.upload",
            f"job:{job_id}",
            {
                "name": name,
                "size_bytes": len(inflated),
                "sha256": sha,
                "truncated": truncated,
            },
        )
    return FileAccepted(name=name, size_bytes=len(inflated), sha256=sha)


@router.put(
    "/{id}/jobs/{job_id}/files/{name}",
    status_code=201,
    responses=problem_responses((400, 401, 403, 404, 409, 413, 429, 503)),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/gzip": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_file(
    id: str,
    job_id: str,
    name: str,
    request: Request,
    agent: AGENT,
    runtime: RUNTIME,
    truncated: Annotated[
        Literal["true", "false"], Header(alias="X-Bitscan-Truncated")
    ] = "false",
) -> FileAccepted:
    job = agent_uuid(job_id, "path.job_id")
    job_id_var.set(str(job))
    if name not in repo.FILE_NAMES:
        raise Problem(404, "not_found", "No such file name.")
    body = await read_capped(request)  # TooLarge → 413 past 32 MiB
    try:
        inflated = gunzip_capped((body,), INFLATED_CAP)
    except InventoryRefused as exc:
        if exc.status == 413:
            raise TooLarge from None
        raise Problem(400, "invalid_request", "Invalid request: body") from None
    return await run_in_threadpool(
        _store, runtime, agent, job, name, truncated == "true", body, inflated
    )
