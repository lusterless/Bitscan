# TASK-073 REVIEW: job pull and the M3 results route

Reviewer: reviewer. Date: 2026-10-23. REQ-072, REQ-073, REQ-066, REQ-087, REQ-088. Spec: TS §6.1 L1064 (pull up to 10 queued jobs, mark them `dispatched`), L1065, L1071 (results accepted only for a job addressed to the agent, within 7 days, for its plugins; anything else 409 and audit-logged), L1072 (the manager re-checks every cap), §6.3 L1138 (result batch 1.5 MB after decompression; 413), §6.5 L1165–L1184 (Job and Results contract), §3.3 L210–L214 (pull-only; at most 10 per pull), §8.4 L1287 (logs with `agent_id` and `job_id`), L1291 (floods of 409 result posts alert); #54 (c), #65 (f), #71. Rulings (`work/decisions.md`, 2026-10-23):
- the tester's notes 2 (case-sensitive `Content-Encoding`) and 3 (non-hyphenated UUID path ids) go to TASK-083, so they are not findings here;
- notes 1 (two simultaneous 21st 409s may write two flood alerts) and 4 (the pull validates payloads after its commit) are accepted.

Inputs:
- `work/reports/TASK-073-impl.md`;
- `work/reports/TASK-073-test.md` (PASS: `manager/tests/test_jobs_api_pg.py`, 93 tests; 25 of 25 plants red, CHK-M3-346 to -351 and -359 included).

Files reviewed:
- `manager/bitscan_manager/services/jobs/pull.py` (new, 82 lines);
- `manager/bitscan_manager/services/jobs/__init__.py`;
- `manager/bitscan_manager/api/agent/jobs.py` (new, 123 lines);
- `manager/bitscan_manager/api/agent/__init__.py` (`result_409` window, router include, `documented_request_bodies`);
- `manager/bitscan_manager/app.py` (the results `RouteCap` and the OpenAPI hook for self-read bodies);
- `manager/openapi.json`;
- the tester-e tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent routes). This is the first one; the user's second approval is still needed.

## What was checked

- **Pull (REQ-072).**
  - `current_agent` runs first, then one transaction with `JobRepo.pull` (TASK-054): at most 10 of this agent's own `queued` inventory jobs with `pickup_by > now`, oldest first. Rows are locked with SKIP LOCKED and their state re-checked, so each job is dispatched once.
  - The stored payloads are validated as `JobsResponse` on output, so the contract holds both ways.
  - An empty queue gives `{"jobs": []}` and changes nothing.
  - No schema reachable from the response has `eval_spec`, `operator` or `expected` (checked in the export; CHK-M3-346). A compliance row planted as owner is never returned (CHK-M3-351).
  - `pickup_by` is re-serialised as `…T12:00:00.000000Z`, the same instant in RFC 3339 UTC.
- **Results (REQ-073, REQ-066).**
  - The route declares **no** FastAPI body parameter. `current_agent` runs first, so an invalid token gets 401 with 0 body bytes read (REQ-066 (3)).
  - The body is read through `read_capped` under the after-auth `RouteCap` (`result_batch`, 1.5 MiB, `after_auth=True`), which now lives in the registry in `app.py`.
  - Over the cap as sent: 413 `too_large` with `Connection: close` and one `agent.result_refused {reason: too_large}` entry.
  - `Content-Encoding: gzip` inflates through `gunzip_capped(…, 1.5 MiB)`. Past the cap that is 413 plus the entry, while a bad stream or another encoding gets 400.
  - The body is then `json.loads` plus `ResultsRequest`: at most 50 items, exact keys, otherwise 400 `invalid_request` "Invalid request: body", which never echoes the body.
  - **Every well-formed batch**, the start notice included, writes one `agent.result_refused` entry (actor `agent:<id>`, target `job:<id>`, detail `{reason, results, final}`, never stdout or stderr) and answers 409 `job_not_acceptable`. Nothing is stored and no job changes, whatever the job (CHK-M3-359 red).
  - More than 20 such 409s for one agent in 10 minutes write one `result_409_flood` alert, at most once per hour, marked on commit (#54 (c), #65 (f)).
- **Logs (REQ-087).** `job_id_var` is set after the UUID parse, so the route's records and access record carry `agent_id` and `job_id`. A planted stdout canary appears in no log record and no entry.
- **`app.py` (TASK-049/063 file, outside the file list).**
  - The `RouteCap` entry sits with the registry, to avoid the circular import that route-module registration would cause.
  - The OpenAPI hook merges `documented_request_bodies()` through `models_json_schema(..., ref_template="#/components/schemas/{model}")` in validation mode, and raises if two models claim one component name. A self-read body is therefore still documented (REQ-060 (1)): the results operation's `requestBody` refers to `#/components/schemas/ResultsRequest`, with no dangling `$ref`.
  - The 422 rule keeps a route-declared 422 (for TASK-074 option (a)) and still drops FastAPI's validation 422.
  - Both changes are necessary and minimal.
- **OpenAPI (G6).** My re-export is byte-identical.
  - `GET /api/v1/agent/{id}/jobs` lists 200, 400, 401, 403, 429 and 503.
  - `POST …/jobs/{job_id}/results` lists 200, 400, 401, 403, 409, 413, 429 and 503.
  - Neither lists a 422.
- **Security invariants (REQ-088).** No route queues or runs a command. Jobs come only from the scheduler, and the pull hands back stored payloads only. No stdout or stderr reaches a log or audit entry.
- **Tests (my run, Windows).** `test_jobs_api_pg.py`, `test_contract_agent.py`, `test_body_caps.py` and `test_openapi.py`: 613 passed, 93 skipped (PostgreSQL; run in WSL by tester-e). A first run hit transient ImportErrors while another edit was landing in the same working tree; the clean re-run passes. ruff and format are clean, and `mypy --strict` is clean on the whole tree (201 files).

## Findings

None. tester-e's notes 2 and 3 are ruled into TASK-083, and notes 1 and 4 are accepted (decisions 2026-10-23).

## Carry-overs

- **TASK-083.** Compare `Content-Encoding` case-insensitively, and accept only the hyphenated 8-4-4-4-12 form for `{id}`, `{job_id}` and `?job_id` (ruling). Put the token check before body parsing on `bsa_` routes that declare a JSON body. Re-run this suite.
- **M9 (result intake).** Replace the blanket 409 with the TS §6.1 L1071 acceptance rules (the agent's own job, within `dispatched_at` + 7 days, listed plugins, first result wins), and decide the NUL and lone-surrogate rule for `stdout` and `stderr` (W1 ruling).
