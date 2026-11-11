# TASK-233 REVIEW: results view (pure): status parse, `include_output`, item mapping, results CSV

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/services/jobs/results_view.py` (new, 159 lines, the only file). The `ResultRow` type it imports belongs to TASK-235 and is reviewed there. Checked against TS §6.2 L1083, L1123, §6.3 L1144, §4.5 L603, §4.4 L585, REQ-267, REQ-268, REQ-269, #144 (a)–(d), #146 (b), (c), (e), plan `work/plans/TASK-235.md` §2. Reports: `work/reports/TASK-233-impl.md` and `work/reports/TASK-233-test.md` (PASS, 261/261, 100 % line coverage, 20/21 plants red, 1 equivalent).

## Checks

- **Viewers never get raw output (security invariant, TS §6.2 L1123):** `include_output` is an exact match against `{"operator", "admin"}`. Every other value is False, including case variants, padded values and unknown roles. `item(..., with_output=False)` builds the 22 `ScanResultItem` keys and never adds `stdout`/`stderr`, so the keys are absent rather than null (#144 (b)). The viewer CSV header and records stop at the 17 #146 columns. The output values are read only inside `if with_output`. The plants CHK-M11-320, -322, -323, "viewer item leaks" and "viewer CSV leaks values" all went red.
- **CSV escaping (TS §6.3 L1144):** every cell, header included, goes through M5's `write_csv` and so through `escape_cell` and then RFC 4180 quoting. The `csv` module is not imported. The plants CHK-M11-324 and -325 went red, and a spy on `escape_cell` saw every cell.
- **#146 (b) header order and cell forms:** the order matches the answer exactly. Nulls are empty, booleans are `true`/`false`, and times are converted to UTC with a `Z`. A Not run `result` is empty. `reevaluated_by` is in the JSON item but not in the CSV, as #146 (b) lists.
- **#144 (a) effective and original verdicts:** `result` comes from `code` (the effective verdict) and `original_result` from `original_code`. Both are null for Not run. `retry` is the row property.
- **`InvalidResultQuery`:** the match is exact and case-sensitive, and the message is the parameter name only (builder checklist 12).
- **Purity and layering:** the module's own imports are the standard library, `csv_export.write_csv` and `ResultRow`. There is no I/O, logging, clock read or `re`. A service importing a repository type is the allowed direction.
- **Frozen files:** `git diff 6efe0fb` over `services/packages/` (including `csv_export.py`), `services/jobs/` (tracked files) and `repositories/results.py` is empty.
- **Re-run:** on Windows (m9 venv, `PYTHONPATH` on this worktree), `test_results_view.py` and `test_csv_export.py` give 261 passed. `ruff check`, `ruff format --check` and `mypy --strict` are clean. The tests parse the CSV back with their own strict reader and compare against literals, so they are not tautological.

## Findings

1. nit, `results_view.py:79`: `_verdict` maps any code other than 0 and 1 to `ERROR`, as the generated `scan_result.result` column does. The DDL `CHECK (eval_code IN (0, 1, 2))` means no other code can reach it, which is why the tester's plant there was equivalent. No change.
