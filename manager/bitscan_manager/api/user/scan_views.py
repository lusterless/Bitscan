"""GET /api/v1/scans, /scans/{id}, /scans/{id}/results, /scans/{id}/results.csv
and /agents/{id}/scans (viewer, `bsu_` or `bsk_`; TS §6.2 L1113, L1120,
L1122, L1123, §6.3 L1135–L1136, L1141, §4.5 L603–L604; REQ-264 to REQ-269,
REQ-273; open questions #144 to #146; plan work/plans/TASK-232.md).

The handlers only validate, authorise and call services; this module imports
no repository (REQ-272 (2)). `stdout` and `stderr` exist only in
ScanResultItemWithOutput, the operator and admin model (TS §6.2 L1123), so a
viewer's items have no such keys. Every problem detail is fixed text.

Contract first (PD-48): every operation is declared here with its final
parameters and models; the bodies answer 501 after the auth dependency ran,
until TASK-244 fills them.
"""

from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import AwareDatetime, BaseModel

from bitscan_manager.api.agent.schemas import UUID_PATTERN
from bitscan_manager.api.pagination import Page, PageParams, page_params
from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.jobs.scan_state import ScanState
from bitscan_manager.services.jobs.states import JobState

router = APIRouter(tags=["scans"])
VIEWER = Annotated[Principal, Depends(require_role("viewer"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
PAGE = Annotated[PageParams, Depends(page_params)]
# The hyphenated 8-4-4-4-12 form only (builder checklist 5); no dot, so
# `{id}` never swallows `results.csv`. Anything else is 400.
SCAN_ID = Annotated[str, Path(pattern=UUID_PATTERN)]
# Query agent_id: the same form only, as package search (TASK-232 r1); the
# handler converts it with UUID().
AGENT_ID = Annotated[str | None, Query(pattern=UUID_PATTERN)]
_BASE: Final = (401, 403, 429, 503)
_JSON_SAFE_MAX: Final = 2**53 - 1

TargetKind = Literal["agents", "tags", "all"]
ResultCode = Literal["PASS", "FAIL", "ERROR"]
StatusFilter = Literal["PASS", "FAIL", "ERROR", "NOT_RUN"]


def _not_yet() -> Problem:
    """PD-48: the M11 branch only; never merged as a 501."""
    return Problem(501, ABOUT_BLANK, "Not implemented yet.")


class ScanItem(BaseModel):
    """#145 (a). `state` is read from `scan.state`, never re-derived."""

    scan_id: UUID
    policy_id: int
    policy_name: str
    policy_version: int
    trigger: Literal["manual", "scheduled"]
    schedule_id: int | None
    requested_by: int | None
    state: ScanState
    target_kind: TargetKind
    resolved_count: int
    created_at: UtcDatetime
    finished_at: UtcDatetime | None


class HostJob(BaseModel):
    job_id: UUID
    state: JobState
    retry_of: UUID | None
    dispatched_at: UtcDatetime | None
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None


class HostSummary(BaseModel):
    """#145 (b), #120: effective counts; `score` in [0, 1], null = "n/a"."""

    agent_id: UUID
    hostname: str
    jobs: list[HostJob]  # the original first, then its retry
    passed: int
    failed: int
    errors: int
    not_run: int
    score: float | None


class ScanDetailItem(ScanItem):
    target: dict[str, Any]  # as requested, without resolved_agents
    hosts: list[HostSummary]  # by hostname, then agent_id


class ScanResultItem(BaseModel):
    """#144 (a), the viewer model: no stdout or stderr field. `result` is the
    effective verdict (null = Not run, TS §4.4 L585), `original_result` the
    stored one (TS §4.5 L603)."""

    agent_id: UUID
    hostname: str
    job_id: UUID | None
    retry: bool
    plugin_uuid: UUID
    plugin_name: str
    result: ResultCode | None
    eval_detail: str | None
    original_result: ResultCode | None
    original_eval_detail: str | None
    reeval_policy_version: int | None
    reevaluated_by: int | None
    reevaluated_at: UtcDatetime | None
    operator: str
    expected: str
    execute: str
    exit_code: int | None
    timed_out: bool | None
    truncated: bool | None
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    received_at: UtcDatetime | None


class ScanResultItemWithOutput(ScanResultItem):
    """Operator and admin only (#144 (b)); NULL is possible in the DDL."""

    stdout: str | None
    stderr: str | None


class CsvResponse(Response):
    media_type = "text/csv"  # Starlette adds "; charset=utf-8" (#146 (c))


_CSV_CONTENT: Final = {"text/csv": {"schema": {"type": "string"}}}


@router.get("/scans", responses=problem_responses(_BASE))
def list_scans(
    principal: VIEWER,
    runtime: RUNTIME,
    page: PAGE,
    policy_id: Annotated[int | None, Query(ge=1, le=_JSON_SAFE_MAX)] = None,
    agent_id: AGENT_ID = None,
    state: ScanState | None = None,
    created_after: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
) -> Page[ScanItem]:
    """Newest first; `created_after` inclusive, `created_before` exclusive;
    `agent_id` matches the scan's resolved target (REQ-264)."""
    raise _not_yet()


@router.get("/scans/{id}", responses=problem_responses((*_BASE, 404)))
def get_scan(id: SCAN_ID, principal: VIEWER, runtime: RUNTIME) -> ScanDetailItem:
    """Scan state and per-host summary, in one read-only snapshot (REQ-265)."""
    raise _not_yet()


@router.get("/scans/{id}/results", responses=problem_responses((*_BASE, 404)))
def list_results(
    id: SCAN_ID,
    principal: VIEWER,
    runtime: RUNTIME,
    page: PAGE,
    status: StatusFilter | None = None,
    agent_id: AGENT_ID = None,
) -> Page[ScanResultItem] | Page[ScanResultItemWithOutput]:
    """One item per planned plugin of each host, by agent_id then payload
    position (REQ-267); output only for operator and admin (REQ-268)."""
    raise _not_yet()


@router.get(
    "/scans/{id}/results.csv",
    response_class=CsvResponse,
    responses={
        200: {"description": "Successful Response", "content": _CSV_CONTENT},
        **problem_responses((*_BASE, 404)),
    },
)
def results_csv(
    id: SCAN_ID,
    principal: VIEWER,
    runtime: RUNTIME,
    status: StatusFilter | None = None,
    agent_id: AGENT_ID = None,
) -> Response:
    """The whole REQ-267 set for the filters, at most 100,000 rows (REQ-269)."""
    raise _not_yet()


@router.get("/agents/{id}/scans", responses=problem_responses((*_BASE, 404)))
def agent_scans(
    id: str, principal: VIEWER, runtime: RUNTIME, page: PAGE
) -> Page[ScanItem]:
    """Scans whose resolved target holds the agent, newest first (REQ-266); a
    malformed id is 404, as on the other /agents/{id} routes."""
    raise _not_yet()
