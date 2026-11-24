"""GET /api/v1/scans/{id}/files and GET /api/v1/scans/{id}/jobs/{job_id}/
files/{name} (TS §3.8, §6.2; owner decision 2026-11-23): the redacted
ClusterMAX files of a scan's cluster_audit jobs, for operator and admin only.
A download is the stored gzip, as an attachment.
"""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel

from bitscan_manager.api.problems import Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories import cluster_audit as repo
from bitscan_manager.runtime import Runtime, get_runtime

router = APIRouter(prefix="/scans", tags=["scans"])
OPERATOR = Annotated[Principal, Depends(require_role("operator"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_UUID: Final = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SCAN_ID = Annotated[str, Path(pattern=_UUID)]
JOB_ID = Annotated[str, Path(pattern=_UUID)]
_BASE: Final = (401, 403, 404, 429, 503)


class ScanFileItem(BaseModel):
    job_id: UUID
    agent_id: UUID
    name: str
    size_bytes: int
    sha256: str
    truncated: bool
    received_at: UtcDatetime


class ScanFiles(BaseModel):
    items: list[ScanFileItem]


@router.get("/{id}/files", responses=problem_responses(_BASE))
def list_files(id: SCAN_ID, principal: OPERATOR, runtime: RUNTIME) -> ScanFiles:
    with runtime.db.transaction() as tx:
        rows = repo.files_of_scan(tx.conn, UUID(id))
    if rows is None:
        raise Problem(404, "not_found", "No such scan.")
    return ScanFiles(
        items=[
            ScanFileItem(
                job_id=r.job_id,
                agent_id=r.agent_id,
                name=r.name,
                size_bytes=r.size_bytes,
                sha256=r.sha256,
                truncated=r.truncated,
                received_at=r.received_at,
            )
            for r in rows
        ]
    )


@router.get(
    "/{id}/jobs/{job_id}/files/{name}",
    responses={
        200: {"content": {"application/gzip": {}}, "description": "The file, gzip"},
        **problem_responses(_BASE),
    },
    response_class=Response,
)
def download_file(
    id: SCAN_ID, job_id: JOB_ID, name: str, principal: OPERATOR, runtime: RUNTIME
) -> Response:
    if name not in repo.FILE_NAMES:
        raise Problem(404, "not_found", "No such file.")
    with runtime.db.transaction() as tx:
        content = repo.file_content(tx.conn, UUID(id), UUID(job_id), name)
    if content is None:
        raise Problem(404, "not_found", "No such file.")
    return Response(
        content=content,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}-{name}.gz"',
            "Cache-Control": "no-store",
        },
    )
