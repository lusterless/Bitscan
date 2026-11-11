# TASK-241 REVIEW: results service (`results_page`, `results_csv`)

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/services/jobs/results_read.py` (new, about 100 lines, the only file). Checked against TS §6.2 L1083, L1123, §4.5 L603, §4.4 L585, §6.3 L1144, REQ-267, REQ-268, REQ-269, #144, #146 (as approved), plan `work/plans/TASK-235.md` §4 and `work/plans/TASK-232.md` §5. Reports: `work/reports/TASK-241-impl.md` and `work/reports/TASK-241-test.md` (PASS, 197/197 on PostgreSQL 16 in WSL, 9/9 plants red).

## Checks

- **Viewers never get stdout or stderr (security invariant):**
  - `with_output = results_view.include_output(role)` is decided once per call. The same flag picks the repository's statement variant (the viewer one selects NULL) and the item and CSV mapping (no keys, no columns).
  - `role` is the caller's current role. The service signatures take no token kind.
  - With the canary, the viewer and unknown-role pages and CSVs carry no output byte. The viewer statements name no `stdout`/`stderr` (spy). Plants -424 and -425 were red. The demoted-API-token row belongs to TASK-244 (CHK-M11-223).
- **One read-only transaction:** the first statement is `read_only_snapshot`, then `exists`. An unknown scan raises `ScanNotFound` (TASK-240's class, re-exported, so one 404 type) instead of returning an empty page. A scan without jobs gives an empty answer, which is correct.
- **CSV cap (#146 (e), as approved):** the export reads at most `CSV_MAX_ROWS + 1` rows. `TooManyRows` is raised before `csv_text` is called, so no text is built. Plants -334, -422 and -423 were red. The byte bound is #155, pending the user (decisions 2026-11-08). It is not part of this task, and any change will come back as a TASK-241/244 round.
- **Paging:** reads `limit + 1` rows. `next_after` is the last shown item's `(agent_id, position)` only when a further row exists, so the last page at exact multiples has no cursor (plants -426 and -427 red). Encoding the cursor under its HMAC scope is TASK-244's, which keeps cursors in the API layer.
- **`ResultPage`:** the plan only named it. The implementer's definition (`items`, `next_after`, `with_output`) is minimal. Returning `with_output` lets TASK-244 build the concrete page model from the same flag, which addresses my TASK-232 finding 2 (the union response model).
- **Layering and logs:** there is no SQL in the service and nothing is written or logged. Exceptions carry no result text (CHK-M11-170).
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the module and its test file are clean. The PostgreSQL suite is Linux-only, so I relied on the tester's WSL run. Its item oracle and CSV formula rule are written independently in the test.

## Findings

None.
