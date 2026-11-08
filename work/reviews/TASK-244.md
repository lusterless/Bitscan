# TASK-244 REVIEW: read routes (the five `scan_views.py` handler bodies)

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

**Scope reviewed:** `manager/bitscan_manager/api/user/scan_views.py`, diffed against HEAD (TASK-232 r1 as committed), +198 −16. `manager/openapi.json` has no diff. The tester's replacement of the W1 501 rows in `manager/tests/test_m11_contract_api_pg.py` is also covered.

**Checked against:**
- TS §6.2 L1083, L1113, L1120–L1123; §6.3 L1135–L1136, L1141, L1142, L1144.
- REQ-264 to REQ-269, REQ-272.
- #89, #144 to #146 (as approved; #155 is pending the user).
- Plans `work/plans/TASK-232.md` §5 and `work/plans/TASK-235.md` §4.

**Reports:** `work/reports/TASK-244-impl.md` and `work/reports/TASK-244-test.md` (PASS: 405/405 on PostgreSQL 16 in WSL, G6 equal, 19/19 plants red).

## Checks

- **Viewers never get stdout or stderr (security invariant, TS §6.2 L1123):**
  - `list_results` passes `principal.role`, the role read in this request, to TASK-241. It then builds the concrete `Page[ScanResultItemWithOutput]` only when `ResultPage.with_output`, and `Page[ScanResultItem]` otherwise. This closes my TASK-232 finding 2: an operator page no longer depends on the union choice.
  - `results_csv` passes the same role.
  - On every page and filter, viewer session and API-token responses carry no output key, column or canary byte. A demoted operator's API token loses the output on the next call.
  - The plants for the token kind as role (-321), the CSV forced to admin, `stdout: null` for viewers (-322) and an operator downgraded to the viewer page (-222) are all red.
- **Cursors (#89, plan §5):**
  - The scopes are `scans:<policy>:<agent>:<state>:<after>:<before>`, `agent_scans:<agent>` and `scan_results:<scan>:<status>:<agent>`.
  - Ids in the scopes are `str(UUID)`, so the upper- and lower-case spellings share one scope (CHK-M11-455, my TASK-232 note).
  - Times are exact epoch microseconds, so one instant written with two offsets shares a scope, and the conversion can't overflow (CHK-M11-456).
  - Keys are accepted only in the form this module writes: a canonical lowercase UUID, and an int position from 1 to 2^53 − 1 that is not a bool (CHK-M11-457).
  - The HMAC and scope check stays M2's `decode_cursor`.
  - A deleted anchor (`AnchorGone`) gives 400 "Invalid request: query.cursor".
- **Errors and CSV:**
  - Problems: `ScanNotFound` gives 404 "No such scan.". A malformed or unknown `/agents/{id}/scans` id gives 404 "No such agent.", matching the other `/agents/{id}` routes. `TooManyRows` gives 400 with the fixed text "Invalid request: more than 100000 rows; narrow the filters".
  - Every problem is built from constants and never echoes client input (checklist 12). Each is raised outside the `except` block or with `from None`, so no driver text is chained.
  - The CSV body is built in full by the service before the response object exists, so a refusal sends no CSV byte.
  - The CSV response is `text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="scan-<canonical id>-results.csv"`, UTF-8 with no BOM and CRLF. The rows equal the JSON items, and every cell goes through `escape_cell` (CHK-M11-225).
- **Layering (REQ-272 (2)):**
  - The route imports `services.jobs.scan_views`, `results_read` and `results_view`, with no repository and no `logging`.
  - The handlers only validate, map and call. Cursor scopes, keys and model mapping are API concerns.
  - The read paths run SELECT only, apart from M2's token `last_used_at` bookkeeping, and the scan tables are unchanged after every read.
- **Contract:** decorators, signatures, response models and handler docstrings are unchanged from TASK-232 r1. `git diff --quiet HEAD -- manager/openapi.json` is clean, and a fresh export matches (G6).
- **Host order:** the detail orders hosts by `hostname` in the database's default collation, then `agent_id`. TS §5.2 and REQ-265 name no collation. This is consistent with how the other host lists are ordered in SQL, so I agree with the tester's reading. If the owner wants byte order, that is a new decision, not a defect here.
- **The replaced 501 rows:** in `test_m11_contract_api_pg.py`, `GET /scans` now returns 200 with an empty page on that file's unknown ids, and the four id routes return 404. The refusal table is unchanged.
- **Re-run (Windows):**
  - `ruff check`, `ruff format --check` and `mypy --strict` on the route and the three test files are clean.
  - `test_openapi.py`, `test_m11_contract.py` and `test_invariants_m3.py` give 67 passed.
  - The PostgreSQL API suites run only on Linux, so I relied on the tester's WSL run.

## Findings

None.
