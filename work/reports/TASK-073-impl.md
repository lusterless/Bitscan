# TASK-073 IMPL report: job pull and the M3 results route

REQ: REQ-072, REQ-073, REQ-066, REQ-087, REQ-088. Spec: TS §6.1 L1064–L1065 and L1071–L1072, §6.3 L1138, §6.5 L1165–L1184, §3.3 L210–L214, §8.4 L1291; #54 (c), #65 (f), #71. It depends on TASK-054, 056, 060 and 063, all approved. **Two approvals** (TS §8.2).

Carry-overs applied:
- The results route uses the after-auth cap (1.5 MiB), declares no FastAPI body parameter, reads 0 body bytes before a 401, and uses `gunzip_capped`.
- Every well-formed post gets 409 `job_not_acceptable`, writes one audit entry and stores nothing.
- The 409-flood alert fires at more than 20 per agent in 10 minutes, once an hour, marked only on commit. Its window is built once in `create_app()`.
- The pull returns at most 10 of the agent's own queued inventory jobs before `pickup_by`, each dispatched once, and never `eval_spec` or `operator`.

**Export order:** `manager/openapi.json` had to be re-exported in the tree now. The tree's code includes these routes, so without the re-export G6 would be red for every task in test. The hand-off order still follows TASK-072 and TASK-082.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/pull.py` | new, 82 lines |
| `manager/bitscan_manager/services/jobs/__init__.py` | new, re-exports |
| `manager/bitscan_manager/api/agent/jobs.py` | new, 123 lines |
| `manager/bitscan_manager/api/agent/__init__.py` | `AgentWindows.result_409` (`SlidingCount(10 min, 1 h, 20)`); jobs router included; `documented_request_bodies()` returns `(ResultsRequest,)` |
| `manager/bitscan_manager/app.py` (TASK-049 file, outside the file list) | the results `RouteCap`, and the OpenAPI hook for self-read bodies |
| `manager/openapi.json` | re-exported, byte-stable |

The `app.py` change has two parts:
1. **Results `RouteCap` in `ROUTE_BODY_CAPS`:** template `/api/v1/agent/{id}/jobs/{job_id}/results`, class `result_batch`, 1.5 MiB, `after_auth=True`. `create_app()` computes the cap registry before it includes the agent router, and a route module cannot register at import time without a circular import (app → `api.agent` → route → app). So the registry entry lives with the registry. TASK-074 adds the inventory line the same way.
2. **The OpenAPI hook (`_problem_openapi`)** also merges the components of `documented_request_bodies()`, through `pydantic.json_schema.models_json_schema(..., ref_template="#/components/schemas/{model}")` in validation mode, as FastAPI does for bodies. A route that reads its own body still documents its request schema, so REQ-060 holds. The results operation refers to it through `openapi_extra`. TASK-074 adds `InventoryBody` to the same tuple.

In the document, the new paths are:
- `GET /api/v1/agent/{id}/jobs` → `JobsResponse`; refusals 400, 401, 403, 429 and 503.
- `POST /api/v1/agent/{id}/jobs/{job_id}/results`: `requestBody` → `#/components/schemas/ResultsRequest`, 200 → `ResultsResponse` (for M9), plus 400, 401, 403, 409, 413, 429 and 503.

The components `ResultsRequest` and `ResultItem` are present, no `$ref` is dangling, and there is no 422. No job schema has `eval_spec`, `operator` or `expected`.

## Behaviour

**Pull** (`current_agent`, then one transaction): `JobRepo.pull` (TASK-054).
- At most `PULL_LIMIT` = 10 jobs, this agent's only, `queued`, `pickup_by > now`, `kind = 'inventory'`.
- Rows are locked and skipped if already locked, and the state is re-checked, so each job is dispatched once. They come back oldest first.
- The stored payloads are validated as `JobsResponse`, so the contract is enforced on output too, and returned as `{"jobs": […]}`.
- An empty queue gives `{"jobs": []}` and changes nothing.
- **Note:** `pickup_by` is re-serialised through the contract's `Timestamp` type. The stored `…T12:00:00Z` goes out as `…T12:00:00.000000Z`: same value, RFC 3339 UTC.

**Results** (`current_agent`, then an async handler that sets `job_id_var`):
1. `job_id` must be a UUID, otherwise 400.
2. `read_capped` reads the body only after the token check (TASK-049/063).
   - Over 1.5 MiB as sent gives 413 `too_large` with `Connection: close`, plus one `agent.result_refused` entry `{reason: "too_large"}`.
   - With an invalid token, the dependency answers 401 first and no body byte is read.
3. `Content-Encoding: gzip` inflates through `gunzip_capped(…, 1.5 MiB)`.
   - Past 1.5 MiB inflated: 413 plus the same entry.
   - A bad gzip stream: 400.
   - Any encoding other than gzip, identity or none: 400.
4. The body must parse as JSON and validate as `ResultsRequest` (TASK-048: at most 50 items, exact keys), otherwise 400 `invalid_request` "Invalid request: body". The detail never echoes the body.
5. **Every well-formed batch**, the empty start notice included: one `agent.result_refused` entry (actor `agent:<id>`, target `job:<job_id>`, detail `{reason: "job_not_acceptable", results: <count>, final}`, never stdout or stderr), the flood window counted, then **409 `job_not_acceptable`**.
   - Nothing is stored and no job changes, whether the job is the agent's own inventory job, unknown, another agent's, or anything else.
   - When the flood window passes 20 within 10 minutes, one `result_409_flood` alert entry is written (actor and target `agent:<id>`). Its hour is marked on commit.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (94 files).
- `pytest -q`: 2191 passed, 1044 skipped, 0 failed.
- **Route probe** (`create_app()`, fake database and repositories, the real dependency chain and caps):

  | Case | Result |
  | --- | --- |
  | pull | 200 with the payload |
  | well-formed batch | 409 `job_not_acceptable` and one entry `{reason, results: 1, final: true}` |
  | start notice | 409 |
  | gzip well-formed | 409 |
  | malformed | 400 |
  | non-UUID `job_id` | 400 |
  | 1.5 MiB + 1 as sent | 413, `Connection: close`, one `too_large` entry |
  | 2 KB gzip that inflates past 1.5 MiB | 413, one entry |
  | `br` encoding | 400 |
  | 2 MB body with a bad token | 401, no entry |
  | 21 refusals in 10 min | exactly one flood alert |
  | 21 more within the hour | none |
  | logs and audit | the access record carries `job_id` and `agent_id`; the planted stdout appears in no log record and no entry |

- Through the API on PostgreSQL (TP-M3-27, including concurrent pulls and a compliance row planted as owner): **NOT RUN locally**; WSL.

## Deviations

The `app.py` touch, and the export made now; both explained above.
