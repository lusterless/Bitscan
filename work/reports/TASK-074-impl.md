# TASK-074 IMPL report: `PUT /api/v1/agent/{id}/inventory`

REQ: REQ-076, REQ-066. Spec: TS §6.1 L1066 and L1072, §3.4 L239–L244, §6.5 L1186, §6.3 L1138; #72. Plan: `work/plans/TASK-060.md` (route, service, job). It depends on TASK-054, 057, 060, 063 and 064, all approved. **Two approvals** (TS §8.2).

Carry-overs applied:
- the after-auth 10 MiB cap is registered through `RouteCap` in `app.py`;
- there is no FastAPI body parameter, so 0 bytes are read before a 401;
- gzip is required;
- answers carry `InventoryRefused.type`, never `.reason`;
- the burst window is built once in `create_app()` (24 h, 24 h, 1,000), and `tx.on_commit` is passed to `ingest()`;
- `AgentGone` becomes 401 `token_revoked`;
- the #72 `job_id` cases;
- the 10-minute window is asked before decoding;
- an over-cap or 422 upload that names a dispatched job fails it, with one audit entry;
- `InventoryBody` and `RawValue` are in the document.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/inventory/upload.py` | new, about 140 lines |
| `manager/bitscan_manager/api/agent/inventory.py` | new, 87 lines |
| `manager/bitscan_manager/api/agent/__init__.py` | `AgentWindows.new_packages`; the inventory router is included; `documented_request_bodies()` now returns `(ResultsRequest, InventoryBody)` |
| `manager/bitscan_manager/app.py` | the inventory `RouteCap` (10 MiB, after-auth) in `ROUTE_BODY_CAPS`; the OpenAPI hook keeps a route-declared 422 (lead ruling, option (a)) |
| `manager/openapi.json` | re-exported, byte-stable |

**The OpenAPI 422 ruling (option (a)).** The hook used to pop every `422`. It now removes only a 422 that refers to `HTTPValidationError`, which is FastAPI's request validation; the app answers those with 400. A problem+json 422 that a route declares itself is kept. In the document:
- only `PUT /api/v1/agent/{id}/inventory` lists 422 (the decoder's TS §3.4 L240 answer);
- `HTTPValidationError` and `ValidationError` appear nowhere;
- the components `InventoryBody`, `OsInfo`, `PackageItem` and `RawValue` are present, with no dangling `$ref`;
- `os_info.uptime_s` is documented with the exact integer `maximum: 9007199254740991`, because the components path keeps integers exact.

## Behaviour

Route, in order:
1. `current_agent`.
2. `?job_id`: a non-UUID gives 400 `invalid_request`. A valid one is set as the log context `job_id`.
3. `Content-Encoding` must be `gzip`, otherwise 400, plus one audit entry with reason `not_gzip`; the job is left to the sweep (#72 (a), (c)).
4. `read_capped` checks the 10 MiB cap as sent. Over it: 413 `too_large` with `Connection: close`, plus one audit entry; the job is failed if it is this agent's dispatched inventory job.
5. `store_upload`, which runs in the threadpool.

`store_upload`:
1. **Classify `job_id`** (#72 (d)) through `JobRepo.get_for_agent`:
   - this agent's dispatched inventory job: **completes**;
   - `failed` or `completed`: **unscheduled** (job unchanged);
   - unknown, another agent's, compliance, `queued`, `expired`, `cancelled`, `running`: **409 `job_not_acceptable`**, plus one audit entry, and nothing is decoded or stored.
2. **Unscheduled** (no `job_id`, or the failed or completed cases): `limits.allow_unscheduled_inventory(agent)` is asked before decoding (#72 (e)). If refused: **429 `rate_limited`** with `Retry-After`, the seconds until the agent's 10-minute window ends, and nothing is decoded. A dispatched job is exempt.
3. **Decode** (TASK-060). `InventoryRefused` is answered with **`exc.type`** and a fixed detail, plus one audit entry with `{reason: exc.reason, status, job_id}`. **A 413 or 422 also fails a dispatched job** it named; a 400 leaves the job to the 30-minute sweep (#72 (c)).
4. **Ingest** in one transaction (TASK-064, with the burst window and `tx.on_commit`). If completing, **`JobRepo.complete(job_id)` runs in the same transaction**, effective only while the job is still dispatched. `AgentGone` gives **401 `token_revoked`**, rolled back.
5. The answer is **204** with no body.

Audit entries: action `agent.inventory_refused`, actor and target `agent:<id>`, detail `{reason, status, job_id}`. They never hold a body, a package or `raw`.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (96 files).
- `pytest -q`: 2182 passed, 1044 skipped, **9 failed, all test-file updates for tester-d**:
  - `tests/test_login.py::test_openapi_error_contract[committed|fresh]`: the "no 422 anywhere" assertion narrows as ruled. The new rule: no 422 that refers to `HTTPValidationError`, and no 422 except on the inventory upload.
  - 7 cases in `tests/test_body_caps.py` mount test routes on the `/api/v1/agent/{id}/inventory` template. The real inventory route now matches first and answers 503 without a runtime. This is the same shadowing as the known heartbeat case (`test_other_agent_routes_keep_one_mib`); those tests need another template or the real route.
- **Probe** (`create_app()`, the real dependency chain, caps, limiter and decoder; fake database and jobs; ingest faked):

  | Case | Result |
  | --- | --- |
  | dispatched job | 204, job completed |
  | failed job | 204, the job stays failed |
  | queued, expired, cancelled, running, another agent's, compliance, unknown | 409 `job_not_acceptable`, one entry each, nothing ingested |
  | non-UUID `job_id` | 400 |
  | unscheduled, then 9 min 59 s later | 429 with `Retry-After: 1` |
  | 10 min 0 s after the first | 204 |
  | a completed `job_id` in the same window | 429, counted as unscheduled |
  | a dispatched job in the same window | 204, exempt |
  | dispatched + duplicate | 422 `about:blank`, job failed, one entry `duplicate_package` |
  | dispatched + hash mismatch | 422, job failed |
  | dispatched + bad gzip | 400, job not failed, one entry `bad_gzip` |
  | dispatched + no `Content-Encoding` | 400, job not failed, one entry `not_gzip` |
  | dispatched + 10 MiB + 1 | 413, `Connection: close`, job failed, one entry `too_large` |
  | 11 MiB with a bad token | 401, no entry, job untouched |
  | dispatched + 64 MiB + 1 inflated | 413, job failed |
  | agent revoked meanwhile | 401 `token_revoked` |

- Through the API on PostgreSQL (TP-M3-28): **NOT RUN locally**; WSL.

## Deviations

None beyond the accepted `app.py` registry and the 422 ruling.
