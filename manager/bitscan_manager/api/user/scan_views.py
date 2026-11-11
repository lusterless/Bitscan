"""GET /api/v1/scans, /scans/{id}, /scans/{id}/results, /scans/{id}/results.csv
and /agents/{id}/scans (viewer, `bsu_` or `bsk_`; TS §6.2 L1113, L1120,
L1122, L1123, §6.3 L1135–L1136, L1141, §4.5 L603–L604; REQ-264 to REQ-269,
REQ-273; open questions #144 to #146; plan work/plans/TASK-232.md).

The handlers only validate, authorise and call services; this module imports
no repository (REQ-272 (2)). `stdout` and `stderr` exist only in
ScanResultItemWithOutput, the operator and admin model (TS §6.2 L1123), so a
viewer's items have no such keys: the page model is chosen from the flag
the service built the items with. Every problem detail is fixed text.

The decorators, signatures and handler docstrings are TASK-232's contract
(G6); TASK-244 filled the bodies only. Cursors hold ids only (#89) and are
bound to a scope built from the filters, ids as `str(UUID)`, so upper- and
lower-case spellings of one id share it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import AwareDatetime, BaseModel

from bitscan_manager.api.agent.schemas import UUID_PATTERN
from bitscan_manager.api.pagination import (
    CursorKey,
    Page,
    PageParams,
    decode_cursor,
    encode_cursor,
    page_of,
    page_params,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.jobs import results_read, results_view
from bitscan_manager.services.jobs import scan_views as views
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
_BAD_CURSOR: Final = "Invalid request: query.cursor"
_NO_SCAN: Final = "No such scan."
_NO_AGENT: Final = "No such agent."
# Fixed text: names the cap, never a client value (#146 (e)).
_TOO_MANY: Final = (
    f"Invalid request: more than {results_view.CSV_MAX_ROWS} rows; narrow the filters"
)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)

TargetKind = Literal["agents", "tags", "all"]
ResultCode = Literal["PASS", "FAIL", "ERROR"]
StatusFilter = Literal["PASS", "FAIL", "ERROR", "NOT_RUN"]


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


def _opt(value: object) -> str:
    return "" if value is None else str(value)


def _instant(value: datetime | None) -> str:
    """Exact microseconds since the epoch, so one instant written with two
    offsets shares a scope; never overflows, unlike astimezone()."""
    return "" if value is None else str((value - _EPOCH) // _MICROSECOND)


def _canonical(value: object) -> UUID | None:
    """The UUID whose str() is exactly `value` (what this module wrote)."""
    if not isinstance(value, str):
        return None
    try:
        found = uuid.UUID(value)
    except ValueError:
        return None
    return found if str(found) == value else None


def _scan_after(scope: str, cursor: str | None) -> UUID | None:
    """[str(scan_id)], or 400."""
    if cursor is None:
        return None
    match decode_cursor(scope, cursor):
        case [str() as raw] if (found := _canonical(raw)) is not None:
            return found
    raise Problem(400, "invalid_request", _BAD_CURSOR)


def _result_after(scope: str, cursor: str | None) -> tuple[UUID, int] | None:
    """[str(agent_id), position], or 400."""
    if cursor is None:
        return None
    match decode_cursor(scope, cursor):
        case [str() as raw, int() as position] if (
            type(position) is int
            and 1 <= position <= _JSON_SAFE_MAX
            and (found := _canonical(raw)) is not None
        ):
            return found, position
    raise Problem(400, "invalid_request", _BAD_CURSOR)


def _scan_key(row: Any) -> CursorKey:
    return [str(row.scan_id)]


def _scan_fields(row: Any) -> dict[str, Any]:
    return {f: getattr(row, f) for f in ScanItem.model_fields}


def _scan_page(rows: list[Any], limit: int, scope: str) -> Page[ScanItem]:
    """rows holds limit + 1 rows; the extra one only sets the cursor."""
    found = page_of(rows, limit, scope, _scan_key)
    return Page[ScanItem](
        items=[ScanItem.model_validate(_scan_fields(r)) for r in found.items],
        next_cursor=found.next_cursor,
    )


def _host(h: views.HostView) -> HostSummary:
    return HostSummary(
        agent_id=h.agent_id,
        hostname=h.hostname,
        jobs=[HostJob.model_validate(j, from_attributes=True) for j in h.jobs],
        passed=h.host.passed,
        failed=h.host.failed,
        errors=h.host.errors,
        not_run=h.host.not_run,
        score=h.host.score,
    )


def _result_query(
    scan_id: UUID, status: str | None, agent_id: str | None
) -> tuple[results_view.ResultQuery, str]:
    """The service query and the cursor scope bound to it."""
    agent = None if agent_id is None else uuid.UUID(agent_id)
    try:
        query = results_view.parse_query(status, agent)
    except results_view.InvalidResultQuery:
        raise Problem(400, "invalid_request", "Invalid request: query.status") from None
    return query, f"scan_results:{scan_id}:{_opt(query.status)}:{_opt(agent)}"


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
    agent = None if agent_id is None else uuid.UUID(agent_id)
    scope = ":".join(
        (
            "scans",
            _opt(policy_id),
            _opt(agent),
            _opt(state),
            _instant(created_after),
            _instant(created_before),
        )
    )
    after = _scan_after(scope, page.cursor)
    filters = views.ScanFilters(policy_id, agent, state, created_after, created_before)
    try:
        rows = views.list_scans(runtime.db, filters, page.limit + 1, after)
    except views.AnchorGone:
        raise Problem(400, "invalid_request", _BAD_CURSOR) from None
    return _scan_page(rows, page.limit, scope)


@router.get("/scans/{id}", responses=problem_responses((*_BASE, 404)))
def get_scan(id: SCAN_ID, principal: VIEWER, runtime: RUNTIME) -> ScanDetailItem:
    """Scan state and per-host summary, in one read-only snapshot (REQ-265)."""
    try:
        detail = views.scan_detail(runtime.db, UUID(id))
    except views.ScanNotFound:
        raise Problem(404, "not_found", _NO_SCAN) from None
    return ScanDetailItem.model_validate(
        {
            **_scan_fields(detail.scan),
            "target": detail.target,
            "hosts": [_host(h) for h in detail.hosts],
        }
    )


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
    scan_id = UUID(id)
    query, scope = _result_query(scan_id, status, agent_id)
    after = _result_after(scope, page.cursor)
    try:
        found = results_read.results_page(
            runtime.db, scan_id, query, principal.role, page.limit, after
        )
    except results_read.ScanNotFound:
        raise Problem(404, "not_found", _NO_SCAN) from None
    next_cursor = None
    if found.next_after is not None:
        agent, position = found.next_after
        next_cursor = encode_cursor(scope, [str(agent), position])
    # The concrete model from the flag the items were built with (REQ-268).
    if found.with_output:
        return Page[ScanResultItemWithOutput](
            items=[ScanResultItemWithOutput.model_validate(i) for i in found.items],
            next_cursor=next_cursor,
        )
    return Page[ScanResultItem](
        items=[ScanResultItem.model_validate(i) for i in found.items],
        next_cursor=next_cursor,
    )


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
    scan_id = UUID(id)
    query, _ = _result_query(scan_id, status, agent_id)
    failure: Problem | None = None
    try:
        body = results_read.results_csv(runtime.db, scan_id, query, principal.role)
    except results_read.ScanNotFound:
        failure = Problem(404, "not_found", _NO_SCAN)
    except results_read.TooManyRows:
        failure = Problem(400, "invalid_request", _TOO_MANY)
    if failure is not None:
        raise failure
    # Built in full before the response starts: a refusal sends no CSV byte.
    name = f'attachment; filename="scan-{scan_id}-results.csv"'
    return CsvResponse(body.encode("utf-8"), headers={"Content-Disposition": name})


@router.get("/agents/{id}/scans", responses=problem_responses((*_BASE, 404)))
def agent_scans(
    id: str, principal: VIEWER, runtime: RUNTIME, page: PAGE
) -> Page[ScanItem]:
    """Scans whose resolved target holds the agent, newest first (REQ-266); a
    malformed id is 404, as on the other /agents/{id} routes."""
    try:
        agent = uuid.UUID(id)
    except ValueError:
        raise Problem(404, "not_found", _NO_AGENT) from None
    scope = f"agent_scans:{agent}"
    after = _scan_after(scope, page.cursor)
    failure: Problem | None = None
    try:
        rows = views.agent_scans(runtime.db, agent, page.limit + 1, after)
    except views.AgentNotFound:
        failure = Problem(404, "not_found", _NO_AGENT)
    except views.AnchorGone:
        failure = Problem(400, "invalid_request", _BAD_CURSOR)
    if failure is not None:
        raise failure
    return _scan_page(rows, page.limit, scope)
