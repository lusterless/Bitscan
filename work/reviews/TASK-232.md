# TASK-232 REVIEW: M11 API contract (six operations, 501 until filled)

Reviewer: reviewer-m11, 2026-11-08. Round 2 (r1). Second look: the lead's (PD-47).

Verdict: APPROVED

## Round 2 (r1): query `agent_id` hyphenated-only

The lead reversed the earlier `agent_id` decision on round 1 finding 1 ("Correction: M11 query agent_id is hyphenated-only", decisions 2026-11-08). r1 changes only `manager/bitscan_manager/api/user/scan_views.py`, with a re-export of `manager/openapi.json`. Reports: the r1 sections of `work/reports/TASK-232-impl.md` and `work/reports/TASK-232-test.md` (PASS, 235/235; the plant typing `agent_id` back to `UUID` is red, 12 failed).

- **Code:** `AGENT_ID = Annotated[str | None, Query(pattern=UUID_PATTERN)]` is used for the query `agent_id` of `GET /scans`, `/scans/{id}/results` and `/scans/{id}/results.csv`. `UUID_PATTERN` is the existing constant from `api/agent/schemas.py:45`. The user routes `rebuild.py` and the scan path ids already import it, so this crosses no new boundary. No new pattern or parser was written. Path ids are unchanged.
- **`openapi.json`, r0 to r1:**
  - I took the r1 file and put the r0 schema (`format: uuid`) back into the three `agent_id` parameters only. I then serialised it as `write_openapi` does (`indent=2, sort_keys=True`, trailing LF). Its SHA-256 is `336f3e6995215fe4…`, the r0 hash the tester recorded. The r0 to r1 delta is therefore exactly the three parameter schemas.
  - Against `6efe0fb`, re-checked: no path removed or changed except the added `GET` on `/api/v1/scans` (its `POST` is identical). No component schema changed, and the agent `ResultItem` is identical.
- **Re-run (Windows, m9 venv on this worktree):** `test_m11_contract.py`, `test_openapi.py` (G6) and `test_invariants_m3.py` give 67 passed. `ruff check`, `ruff format --check` and `mypy --strict` are clean. The hyphenated-only rows are PostgreSQL API rows, from the tester's WSL run.
- Round 1 finding 1 is resolved. For TASK-244: the handler converts the value with `UUID()`, and the cursor scope should use `str(UUID)` so the lower-case and upper-case forms share one scope.
- No new findings. Findings 2 and 3 of round 1 stay as nits.

## Round 1

Scope reviewed: `manager/bitscan_manager/api/user/scan_views.py` (new), `manager/bitscan_manager/api/user/reevaluate.py` (new), `manager/bitscan_manager/api/user/__init__.py` (+4), `manager/openapi.json` (re-export), and the tester's change to `manager/tests/test_invariants_m3.py`. Checked against TS §6.2 L1083, L1086, L1113, L1120, L1122, L1123, L1125, §6.3 L1136, L1141, §5.3 L1053, REQ-264 to REQ-270, REQ-273, #144 to #147, PD-48, plan `work/plans/TASK-232.md`, and decisions 2026-11-08 (model names; query `agent_id`). Reports: `work/reports/TASK-232-impl.md` and `work/reports/TASK-232-test.md` (PASS, 208/208, 11/12 plants red, 1 equivalent). The `manager/pyproject.toml` change in the tree belongs to TASK-255, not this task.

### Checks

- **Model names (decision 2026-11-08):** `ScanResultItem` / `ScanResultItemWithOutput`, with fields exactly as in plan §4. My own semantic diff of `openapi.json` against `6efe0fb`:
  - `info` and `openapi` are unchanged, and no path was removed.
  - The only changed path is `/api/v1/scans`, which gains `get`; its `post` is identical.
  - Five paths were added.
  - In `components.schemas`, nothing was removed or changed and 10 schemas were added. The agent `ResultItem` component is identical to main.

  The change is additions only.
- **Re-evaluate (sensitive action, TS §6.2 L1086, §5.3 L1053):**
  - It uses `Depends(require_totp_session())`: admin, TOTP session, API tokens refused, sink gate on. The route-walk marker is `("totp_session", "admin", False, True)`.
  - It has no body parameter, and the document has no `requestBody`.
  - Declared refusals: 400, 401, 403, 404, 409, 429, 503.
  - The plants for `require_role("admin")`, `sink_gate=False`, an operator minimum and removed auth are all red.
- **Reads:**
  - All five use `require_role("viewer")` on the user router (`bsu_`/`bsk_` only).
  - Parameters match plan §3: `limit` 1–500 with default 50, `policy_id` 1 to 2^53 − 1 (checklist 3), `state` = the six scan states, dates as `AwareDatetime`, `status` with its four values.
  - Path ids are hyphenated-only (`UUID_PATTERN`, as in `rebuild.py` and M9 `scans.py`). `/agents/{id}/scans` takes a plain `str`, so TASK-244 can answer 404.
  - `stdout`/`stderr` appear only in `ScanResultItemWithOutput`. No scan model has `resolved_agents`, `execute` or an expected value.
  - The 501 is raised in the body, after FastAPI has resolved the auth dependency.
- **Layering:** neither route module imports `bitscan_manager.repositories`. No auth, service, repository, migration or dependency change, and no frozen file touched.
- **Invariants:** no ad-hoc command path (plant CHK-M11-346 red), no inventory switch, and no route outside TS §6.2.
- **`test_invariants_m3.py`:** the M11 paths are excluded from the generic `{limit, cursor, state, job_id}` set and pinned instead to their exact parameter sets (`M11_QUERY`, asserted with `==`). The inventory-switch assertion and the package and policy rows are unchanged. This is the REQ-088 change M11 makes; nothing is loosened.
- **Re-run:** `test_m11_contract.py`, `test_openapi.py` (G6) and `test_invariants_m3.py` give 67 passed. `ruff check`, `ruff format --check` and `mypy --strict` on the three modules are clean.

### Findings

1. nit, resolved in r1, `scan_views.py`: the query `agent_id` was typed `UUID`, so it also accepted the 32-hex, braced and `urn:uuid:` forms. The decision's cited precedent (`agents.py:56`, `enrolment.py:181`, `packages.py:94`) consists of response-model fields. The only existing user-route query `agent_id`, package search (`api/user/packages.py:61`, parsed by `services/packages/query.py:129`), accepts only the hyphenated form (M3 ruling). The lead reversed the decision, and r1 applies it.
2. nit, for TASK-244, `scan_views.py` `list_results`: the response model is the union `Page[ScanResultItem] | Page[ScanResultItemWithOutput]`, and FastAPI re-validates the returned page against it.
   - An operator page validates against both members, and `ScanResultItem` silently drops extra keys. Keeping `stdout` therefore relies on pydantic's smart-union choice.
   - A viewer page cannot validate against the output model, because two required keys are missing, so that direction fails closed.
   - TASK-244 TEST must show that operator items keep `stdout`/`stderr` through the route (CHK-M11-222).
3. nit, `scan_views.py` handler docstrings: they become the public OpenAPI `description`, so REQ ids ship in `openapi.json`. There is precedent (`DELETE /policies/{id}`, `RequestItem`), so no change is asked.
