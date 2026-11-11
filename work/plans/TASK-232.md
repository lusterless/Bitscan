# TASK-232 plan: the M11 API contract (design note D1)

Covers TASK-232 (declare), TASK-234 and TASK-240 (the scan reads they serve), TASK-243 and TASK-244 (the handler fills) and TASK-239 (the client generated from it). Planner-m11, 2026-11-08. Answers used: #144, #145, #146, #147, PD-48. `bm/` = `manager/bitscan_manager/`.

## 1. Spec quotes

- TS §6.2 L1113: `GET /agents/{id}/scans` "Scan history of one host", viewer.
- TS §6.2 L1120: `GET /scans` "List scans (filter by policy, host, state, date)", viewer.
- TS §6.2 L1122: `GET /scans/{id}` "Scan state + per-host summary", viewer.
- TS §6.2 L1123: `GET /scans/{id}/results`, `/results.csv` "Results, filterable by status and host. `stdout` and `stderr` are included only for operator and admin.", viewer.
- TS §6.2 L1125: `POST /scans/{id}/reevaluate` "Re-evaluate against the policy's current version", admin, TOTP session.
- TS §6.2 L1086: re-evaluation is a sensitive action (TOTP-verified session, refused for API tokens); TS §5.3 L1053: sensitive actions refused after 15 minutes of sink outage.
- TS §4.5 L603: "The API returns both `result` and `original_result`." L604: score, errors beside, "n/a".
- TS §6.3 L1135–L1136, L1141: problem details, cursor pagination (limit ≤ 500), RFC 3339 UTC, UUID ids.

## 2. Files and what TASK-232 writes

| File | TASK-232 | Filled later by |
| --- | --- | --- |
| `bm/api/user/scan_views.py` | router (no prefix), the five read operations with their dependencies, query parameters and response models; handler bodies `raise _NOT_YET` | TASK-244 (bodies only) |
| `bm/api/user/reevaluate.py` | router, the operation with `require_totp_session()`, its response model; body `raise _NOT_YET` | TASK-243 (body only) |
| `bm/api/user/__init__.py` | `include_router(scan_views.router)` and `include_router(reevaluate.router)` after `scans.router` | none |
| `manager/openapi.json` | re-exported | none (G6 guards it) |

`_NOT_YET = Problem(501, ABOUT_BLANK, "Not implemented yet.")`, raised only after the auth dependency has run (it is a parameter of the handler, so FastAPI resolves it first). The 501 exists only on the M11 branch (PD-48).

## 3. Operations (final; later tasks may not change them)

| Operation | Auth dependency | Query | Path id | Success | Refusals declared |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/scans` | `require_role("viewer")` | `limit`, `cursor` (`page_params`), `policy_id: int ≥ 1`, `agent_id: UUID`, `state: ScanState`, `created_after: AwareDatetime`, `created_before: AwareDatetime` | — | 200 `Page[ScanItem]` | 400, 401, 403, 429, 503 |
| `GET /api/v1/scans/{id}` | viewer | — | hyphenated UUID pattern (as `scans.py` `SCAN_ID`) | 200 `ScanDetailItem` | + 404 |
| `GET /api/v1/scans/{id}/results` | viewer | `limit`, `cursor`, `status: Literal["PASS","FAIL","ERROR","NOT_RUN"]`, `agent_id: UUID` | as above | 200 `Page[ResultItem] \| Page[ResultItemWithOutput]` | + 404 |
| `GET /api/v1/scans/{id}/results.csv` | viewer | `status`, `agent_id` | as above | 200 `text/csv` (string schema, as `/packages/search.csv`) | + 404 |
| `GET /api/v1/agents/{id}/scans` | viewer | `limit`, `cursor` | `str`, 404 when not a UUID (as `agents.py` `_agent_id`) | 200 `Page[ScanItem]` | + 404 |
| `POST /api/v1/scans/{id}/reevaluate` | `require_totp_session()` (admin, sink gate) | — (no body parameter) | `SCAN_ID` pattern | 200 `ReevalItem` | + 404, 409 |

`ScanState` is M9's `services.jobs.scan_state.ScanState` (the six scan states). `UtcDatetime` from `bm/api/timestamps.py` for every time. Unknown query parameters are ignored by FastAPI as elsewhere; invalid values are 400 through the existing validation handler (#47).

## 4. Response models (in `scan_views.py` and `reevaluate.py`)

```python
TargetKind = Literal["agents", "tags", "all"]
JobState = Literal["queued", "dispatched", "running", "completed", "partial",
                   "failed", "cancelled", "expired"]
Verdict = Literal["PASS", "FAIL", "ERROR"]

class ScanItem(BaseModel):            # #145 (a)
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

class HostSummary(BaseModel):         # #145 (b), #120
    agent_id: UUID
    hostname: str
    jobs: list[HostJob]               # original first, then its retry
    passed: int
    failed: int
    errors: int
    not_run: int
    score: float | None               # [0, 1]; null = "n/a"

class ScanDetailItem(ScanItem):
    target: dict[str, Any]            # as requested, without resolved_agents
    hosts: list[HostSummary]          # by hostname, then agent_id

class ResultItem(BaseModel):          # #144 (a); the viewer model
    agent_id: UUID
    hostname: str
    job_id: UUID | None
    retry: bool
    plugin_uuid: UUID
    plugin_name: str
    result: Verdict | None            # null = Not run
    eval_detail: str | None
    original_result: Verdict | None
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

class ResultItemWithOutput(ResultItem):  # operator and admin (#144 (b))
    stdout: str | None                 # NULL is possible in the DDL (L905)
    stderr: str | None

class ReevalItem(BaseModel):          # #147 (c), M8 ReevalResult
    scan_id: UUID
    policy_id: int
    scan_policy_version: int
    policy_version: int
    rows_added: int
    not_in_version: int
```

The CSV header is TASK-233's constant (#146 (b)); TASK-232 declares only the `text/csv` response.

## 5. Services the handlers will call (signatures fixed here for TASK-240, 241)

```python
# bm/services/jobs/scan_views.py (TASK-240)
@dataclass(frozen=True) class ScanFilters: policy_id: int | None; agent_id: UUID | None;
    state: str | None; created_after: datetime | None; created_before: datetime | None
def list_scans(db: Database, filters: ScanFilters, limit: int, after: UUID | None) -> list[ScanRow]
def scan_detail(db: Database, scan_id: UUID) -> ScanDetail            # raises ScanNotFound
def agent_scans(db: Database, agent_id: UUID, limit: int, after: UUID | None) -> list[ScanRow]  # raises AgentNotFound
# AnchorGone (from the repository) for a deleted cursor anchor → 400

# bm/services/jobs/results_read.py (TASK-241)
def results_page(db: Database, scan_id: UUID, query: ResultQuery, role: str,
                 limit: int, after: tuple[UUID, int] | None) -> ResultPage  # raises ScanNotFound
def results_csv(db: Database, scan_id: UUID, query: ResultQuery, role: str) -> str  # raises ScanNotFound, TooManyRows
```

`role` is `principal.role` (the current role, TS §6.2 L1083), never the token kind. Cursor scopes (TASK-244): `scans:<policy_id>:<agent_id>:<state>:<after>:<before>`, `agent_scans:<agent_id>`, `scan_results:<scan_id>:<status>:<agent_id>`; keys `[str(scan_id)]` and `[str(agent_id), position]`.

## 6. The re-evaluate handler (TASK-243)

```python
@router.post("/scans/{id}/reevaluate", responses=problem_responses((*_BASE, 404, 409)))
def reevaluate(id: SCAN_ID, principal: TOTP_ADMIN, runtime: RUNTIME) -> ReevalItem:
    try:
        done = reevaluate_scan(runtime.db, UUID(id), user_id=principal.user_id,
                               wake=runtime.sink_gate.wake)
    except ScanNotFound: raise Problem(404, "not_found", "No such scan.")
    except PolicyDeleted: raise Problem(409, "conflict", "The policy is deleted.")
    return ReevalItem(...)
```

Raise outside the `except` blocks as the other routes do (no chained driver text). No body parameter, so no body is read (#147 (b)). Nothing is logged with result text.

## 7. Edge cases the tests must hit

- An auth refusal must come before the 501 in W1 and before any database work afterwards (a viewer on re-evaluate: 403, no `scan_result_reeval` read).
- `GET /scans/{id}` for an id in upper case: accepted by the pattern and compared as a UUID.
- `/scans/{id}/results.csv` and `/scans/{id}/results` are separate paths (no `{id}` swallowing `.csv`; the id pattern has no dot).
- `GET /agents/{id}/scans` with a non-UUID answers 404 (consistency with M5), not 400.
- The route walk (G34) must see six new operations, all in TS §6.2, and the re-evaluate marker `totp_session` with `sink_gate=True`.
