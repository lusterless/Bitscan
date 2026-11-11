# TASK-232 IMPL: the M11 API contract (six operations declared, 501 until filled)

Implementer: impl-manager-a. REQ-264 to REQ-270, REQ-273. Risk high (the lead's second look, PD-47). Spec: TS §6.2 L1086, L1113, L1120, L1122, L1123, L1125; §6.3 L1135–L1136, L1141; §4.5 L603–L604; §5.3 L1053. Answers applied: #144, #145, #146, #147, PD-48. Plan: `work/plans/TASK-232.md`.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/scan_views.py` (new, 201 lines) | the five read operations (viewer) and the models `ScanItem`, `HostJob`, `HostSummary`, `ScanDetailItem`, `ScanResultItem`, `ScanResultItemWithOutput`; `CsvResponse`; bodies raise 501 |
| `manager/bitscan_manager/api/user/reevaluate.py` (new, 49 lines) | `POST /scans/{id}/reevaluate` on `require_totp_session()` (admin, sink gate) and `ReevalItem`; body raises 501 |
| `manager/bitscan_manager/api/user/__init__.py` | the two modules imported, and their routers included after `scans.router` (+4 lines) |
| `manager/openapi.json` | re-exported (see G6 below) |

No other file changed. No auth, service, repository, migration or dependency change.

## Operations (plan §3, final)

| Operation | Auth | Parameters | 200 | Declared refusals |
| --- | --- | --- | --- | --- |
| `GET /api/v1/scans` | `require_role("viewer")` | `limit`, `cursor` (`page_params`); `policy_id` int 1 to 2^53 − 1; `agent_id` UUID; `state` `ScanState` (the six scan states); `created_after`, `created_before` `AwareDatetime` | `Page[ScanItem]` | 400, 401, 403, 429, 503 |
| `GET /api/v1/scans/{id}` | viewer | `{id}` hyphenated UUID pattern (`UUID_PATTERN`, either case) | `ScanDetailItem` | as above, plus 404 |
| `GET /api/v1/scans/{id}/results` | viewer | `{id}` pattern; `limit`, `cursor`; `status` `PASS`/`FAIL`/`ERROR`/`NOT_RUN`; `agent_id` UUID | `Page[ScanResultItem] \| Page[ScanResultItemWithOutput]` | as above, plus 404 |
| `GET /api/v1/scans/{id}/results.csv` | viewer | `{id}` pattern; `status`; `agent_id` | `text/csv`, string schema (as `/packages/search.csv`) | as above, plus 404 |
| `GET /api/v1/agents/{id}/scans` | viewer | `{id}` plain string (TASK-244 answers 404 for a non-UUID, as `agents.py`); `limit`, `cursor` | `Page[ScanItem]` | as above, plus 404 |
| `POST /api/v1/scans/{id}/reevaluate` | `require_totp_session()` (admin, `sink_gate=True`) | `{id}` pattern; no body parameter, so no body is read (#147 (b)) | `ReevalItem` | as above, plus 404, 409 |

- The 400 entry on every operation comes from the app's `_problem_openapi` (input-taking operations). There is no 422.
- The 501 (`about:blank`, "Not implemented yet.") is raised inside the handler body. FastAPI solves the auth dependency (a handler parameter) first, so an auth refusal always comes before it. The 501 is not declared in the document: it exists only on the M11 branch until TASK-243 and TASK-244 fill the bodies (PD-48).
- The query parameters are on the handler signatures, not in a dependency, so TASK-244 fills the bodies only: it builds TASK-240's `ScanFilters` and TASK-241's `ResultQuery` there.
- `JobState` is M9's `services.jobs.states.JobState` and `ScanState` is M9's `services.jobs.scan_state.ScanState`. Both are imported, not copied, and have the same values as plan §4.
- Neither module imports a `bitscan_manager.repositories` module (REQ-272 (2), REQ-270 (5)).
- `stdout` and `stderr` are fields of `ScanResultItemWithOutput` only. No other new model has them (REQ-268 (3)).

## Deviation from plan TASK-232 §4 (approved by main, 2026-11-08)

The plan names the viewer results model `ResultItem`. That is already the agent-route component (`api/agent/schemas.py`, the results-batch item). With two models of that name, FastAPI would rename both components with module paths, changing the agent schemas (REQ-273 (3), builder checklist 13).

- The models are therefore named `ScanResultItem` and `ScanResultItemWithOutput`. Only the names changed: the fields are exactly the plan's.
- Main recorded the names for TASK-239.
- Also renamed: the plan's local `Verdict` Literal is `ResultCode`, so it isn't confused with M8's frozen `Verdict` class. It is a type alias only and does not appear in the document.
- Reviewer: please confirm that the agent `ResultItem` component in `openapi.json` is byte-identical to main.

## OpenAPI (G6)

Command (Windows, see "Environment" below):

```
python -m bitscan_manager.app manager/openapi.json
```

- Two consecutive exports are byte-identical (`cmp`).
- The line diff shows `+2778 −971`. The "deletions" are alignment artifacts of the sorted keys.
- A semantic comparison with `HEAD` (`6efe0fb`) shows the following.
  - `info` and `openapi` are unchanged.
  - No path was removed and no existing operation changed. Added: `GET /api/v1/scans`, `/api/v1/scans/{id}`, `/api/v1/scans/{id}/results`, `/api/v1/scans/{id}/results.csv`, `/api/v1/agents/{id}/scans` and `POST /api/v1/scans/{id}/reevaluate`.
  - No component was removed or changed. Added: `HostJob`, `HostSummary`, `Page_ScanItem_`, `Page_ScanResultItem_`, `Page_ScanResultItemWithOutput_`, `ReevalItem`, `ScanDetailItem`, `ScanItem`, `ScanResultItem`, `ScanResultItemWithOutput`.
  - Every other components section is unchanged. The agent-route components (including `ResultItem`) are unchanged.
- `policy_id` `maximum` is 9007199254740991 (checklist 3).

## Commands run

All from the worktree root. `PYTHONPATH` and `MYPYPATH` point at `manager/` of this worktree.

| Command | Result |
| --- | --- |
| `ruff check manager` | All checks passed |
| `ruff format --check manager` | 392 files already formatted |
| `mypy --strict --config-file manager/pyproject.toml manager` | Success: no issues found in 392 source files |
| `python -m bitscan_manager.app manager/openapi.json`, twice, then `cmp` | byte-stable |

Environment:
- `Bitscan/manager/.venv` lacks `python-multipart`, so `create_app()` cannot import there. WSL `~/venv` also lacks it.
- I therefore used `Bitscan-m9/manager/.venv`. Its versions match `requirements-dev.txt`: fastapi 0.148.0, pydantic 2.14.1, pydantic-core 2.50.1, starlette 1.9.0, python-multipart 0.0.32, psycopg 3.3.6, mypy 2.4.0, ruff 0.17.1.
- That venv's editable install points at the m9 tree. `PYTHONPATH` and `MYPYPATH` were set so this worktree's code is the one imported and checked; this was verified with `bitscan_manager.__file__`.
- No tests were run (tester's job).

## For the tester (tester-m11)

- Acceptance: G6 green, and the document holds exactly the operations above. A viewer on re-evaluate gets 403, and no token gets 401, before any 501. An admin TOTP session on re-evaluate and any viewer on the five reads gets 501 `about:blank` until W2/W3.
- The route allow-list in `manager/tests/test_invariants_m3.py` already lists the six operations.
- G16 is red from this task until TASK-239 regenerates `web/src/api/schema.d.ts` (as planned).
- `agent_id` (query): r0 typed it `UUID`. r1 makes it hyphenated-only; see the r1 section below.
- `created_after` and `created_before` are `AwareDatetime`, as plan §3 says. A value without an offset is 400. Pydantic also accepts a numeric Unix timestamp, which it reads as UTC.
- Files outside the task list: none. `e2e/m6/doubles.py` is modified in the working tree, but not by me.

## r1 (2026-11-08): query `agent_id` hyphenated-only

Main's correction in `work/decisions.md`, "Correction: M11 query agent_id is hyphenated-only", following the reviewer's nit (1) on r0.

### Change

- `manager/bitscan_manager/api/user/scan_views.py`: a new alias, `AGENT_ID = Annotated[str | None, Query(pattern=UUID_PATTERN)]`. The `agent_id` query parameter of `GET /scans`, `GET /scans/{id}/results` and `GET /scans/{id}/results.csv` uses it instead of `UUID | None` (+4 lines, 3 changed).
  - Only the 8-4-4-4-12 form is accepted, in either case.
  - Every other form is a validation error, which the app answers as 400 `invalid_request` in the existing problem shape.
  - TASK-244 converts the accepted string with `UUID()`.
- It reuses the existing `UUID_PATTERN` from `api/agent/schemas.py`. That is the constant the path ids here and `rebuild.py` and `policy_import.py` already import into user routes, so it crosses no new boundary. No new pattern or parser was written.
- Path ids are unchanged: `{id}` on the scan routes keeps `UUID_PATTERN`, and `/agents/{id}/scans` stays a plain string, 404 when it is not a UUID.

### Checks

- I checked the pattern with pydantic's own validator, which is what FastAPI applies:
  - accepted: the lowercase form and the uppercase form;
  - refused: the 32-hex, braced and `urn:uuid:` forms, a trailing `\n`, a leading space and a non-hex character.
  - pydantic-core's `$` does not match before a trailing newline.

### OpenAPI

- I re-exported `manager/openapi.json`. Two exports are byte-identical.
- r0 → r1, exactly three changes: in the `agent_id` query parameter schema of those three operations, `format: uuid` became `pattern: ^[0-9a-fA-F]{8}-…{12}$`.
- Every path, operation and component of `6efe0fb` is still unchanged, including the agent `ResultItem`.

### Commands (r1)

| Command | Result |
| --- | --- |
| `ruff check` / `ruff format --check` on `scan_views.py` | clean |
| `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` | Success, 187 files |
| export twice, then `cmp` | byte-stable |

### For the tester

- REQ-264 (3) and the results rows: a 32-hex, braced or `urn:` `agent_id` query now gets 400. It no longer reaches the 501.
- G16 needs TASK-239's regeneration from this document. The schema change is a string with a pattern instead of a `uuid` format.
