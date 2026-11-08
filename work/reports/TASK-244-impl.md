# TASK-244 IMPL: read routes (the five `scan_views.py` handler bodies)

Implementer: impl-manager-a. REQ-264 to REQ-269, REQ-272. Risk high (second look, PD-47). Spec: TS §6.2 L1083, L1113, L1120, L1122, L1123; §6.3 L1135–L1136, L1141, L1144. Answers applied: #89, #144 to #146. Plans: `work/plans/TASK-232.md` §5 (cursor scopes) and `work/plans/TASK-235.md` §4. Built on TASK-240 (`services/jobs/scan_views.py`), TASK-241 (`services/jobs/results_read.py`) and TASK-233 (`results_view`), all unchanged.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/scan_views.py` | `+198 −16`. Handler bodies, helpers, imports, constants and the module docstring. Decorators, signatures and handler docstrings are byte-identical to TASK-232 r1 |
| `manager/openapi.json` | re-exported; **no diff** against `HEAD` (G6) |

The 501 helper (`_not_yet`) is gone.

## Handlers

| Route | Calls | Answers |
| --- | --- | --- |
| `GET /scans` | `views.list_scans(db, ScanFilters(...), limit + 1, after)`, then `page_of` | 200 `Page[ScanItem]`; `AnchorGone` → 400 `invalid_request` "Invalid request: query.cursor" |
| `GET /scans/{id}` | `views.scan_detail(db, UUID(id))` | 200 `ScanDetailItem` (scan fields, `target`, `hosts` from `HostView`: jobs, `passed`, `failed`, `errors`, `not_run`, `score`); `ScanNotFound` → 404 "No such scan." |
| `GET /scans/{id}/results` | `results_read.results_page(db, scan_id, query, principal.role, limit, after)` | 200, as the concrete `Page[ScanResultItemWithOutput]` when `ResultPage.with_output`, else `Page[ScanResultItem]`; `ScanNotFound` → 404 |
| `GET /scans/{id}/results.csv` | `results_read.results_csv(db, scan_id, query, principal.role)` | 200 `text/csv; charset=utf-8`, UTF-8 body, `Content-Disposition: attachment; filename="scan-<scan_id>-results.csv"`; `TooManyRows` → 400 `invalid_request` "Invalid request: more than 100000 rows; narrow the filters"; `ScanNotFound` → 404 |
| `GET /agents/{id}/scans` | `views.agent_scans(db, agent, limit + 1, after)`, then `page_of` | 200 `Page[ScanItem]`; a non-UUID id or `AgentNotFound` → 404 "No such agent."; `AnchorGone` → 400 |

## Rules followed

- **Role.** It is `principal.role`, the role read in this request, never the token kind. The service derives `with_output` once. The route picks the page model from that same flag, so an operator or admin page keeps `stdout` and `stderr` and a viewer page has neither key (reviewer's TASK-232 and TASK-241 notes; CHK-M11-222). FastAPI 0.148 validates the returned instance against the union without dumping it first, so the concrete instance matches its own member exactly.
- **Query `agent_id`.** It is already pattern-checked (TASK-232 r1) and converted with `uuid.UUID()`. Scopes and filters use the `UUID`, so `str(UUID)` is lowercase and upper- and lower-case spellings share one scope.
- **Cursor scopes and keys** (plan §5).
  - The scopes are `scans:<policy_id>:<agent_id>:<state>:<after>:<before>`, `agent_scans:<agent_id>` and `scan_results:<scan_id>:<status>:<agent_id>`. An absent filter is the empty string.
  - The two times are written as exact integer microseconds since the epoch. The same instant written with two offsets therefore shares a scope, and the conversion never overflows: `astimezone` would overflow at year 1 with a positive offset.
  - Keys are `[str(scan_id)]` and `[str(agent_id), position]`. The decoder accepts only the exact form this module writes: a canonical lowercase UUID string, and a position that is an int (not a bool) from 1 to 2^53 − 1. Anything else is 400 "Invalid request: query.cursor", as are a tampered cursor and one from another scope (`decode_cursor`'s HMAC and scope check).
- **Status.** It goes through `results_view.parse_query`. The route's `Literal` already refuses anything else; `InvalidResultQuery` would be 400 "Invalid request: query.status".
- **CSV.** The body is built in full by the service before the response object exists, so a refusal sends no CSV byte (#146 (e), (f)).
- **Layering.**
  - The module imports `services.jobs.scan_views`, `results_read` and `results_view`, and no `bitscan_manager.repositories` module (REQ-272 (2)).
  - The handlers parse, map and call. The only work in them is API work: cursor scopes, keys and model mapping.
- **No text from the client.** Every problem detail is a fixed string, and nothing is logged.

## Smoke check (throwaway, not a test file)

I ran a script outside the tree on Windows (deleted afterwards). It used FastAPI's `TestClient` on the user router, with `current_principal` and `get_runtime` overridden and the service functions replaced by fakes. No PostgreSQL. Results:
- **`GET /scans` paging and cursors:**
  - `limit=2` gives 2 items and a cursor.
  - That cursor works again with the lowercase `agent_id` and the same instant written with another offset (`+18:00`), and passes the right anchor to the service.
  - With other filters the same cursor is 400.
  - A 32-hex `agent_id` is 400, and an anchor-gone cursor is 400.
- **Detail and host history:** the detail gives `score` 0.5 (1 PASS, 1 FAIL, 2 ERROR), and an unknown scan is 404. `/agents/{id}/scans` is 200 for a known agent, and 404 for `nope` and for an unknown UUID.
- **Results by role:**
  - A viewer's items have no `stdout`/`stderr` keys, and its CSV header no such columns.
  - Operator and admin get both keys and both columns.
  - `result` (effective) and `original_result` (stored) are both present.
  - The next cursor round-trips to `(agent_id, position)`. With another `status` it is 400.
  - An unknown scan is 404, and `status=pass` is 400.
- **CSV:** `text/csv; charset=utf-8` and `attachment; filename="scan-<id>-results.csv"`. Over the cap it is 400 `application/problem+json` with the fixed detail.

## Commands run

`PYTHONPATH` and `MYPYPATH` point at this worktree's `manager/`. I used the `Bitscan-m9/manager/.venv` tools; see TASK-232 for why.

| Command | Result |
| --- | --- |
| `ruff check` / `ruff format --check` on the file | clean |
| `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` | Success, 190 files |
| `python -m bitscan_manager.app manager/openapi.json`, then `git diff --quiet HEAD -- manager/openapi.json` | unchanged (G6) |

## For the tester (tester-m11d)

- The W1 501 rows in `test_m11_contract_api_pg.py` now get real answers (tester-m11 said they are replaced at TASK-244 TEST).
- Files outside the task list: none. No PostgreSQL run by me.
