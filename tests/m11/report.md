# M11 test report

Phase report for M11 (results and end-to-end). The lead folds in each section unchanged from the tester's per-task report `work/reports/<id>-test.md`, which is the source, with headings demoted one level. The harness refuses report-file writes from tester sub-agents, as in M9 and M10.

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-233 | TASK-233 TEST: PASS | `work/reports/TASK-233-test.md` |
| TASK-236 | TASK-236 TEST: PASS | `work/reports/TASK-236-test.md` |

## TASK-236 (retention rules, pure)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-040 | `test_constants_are_the_spec_values` | PASS | 400, 180, 90, 90, 30 days; 3 years; 5 min; 1 day; chunks 100, 1,000, 10,000, 10,000 |
| CHK-M11-041 | `test_each_cutoff_is_now_minus_its_age` (4 instants, incl. aware non-UTC and a DST day) | PASS | each cutoff = now − age, UTC; a row at the cutoff is not older than it, 1 µs older is |
| CHK-M11-042 | `test_audit_cutoff_is_three_calendar_years` (7 cases), `test_calendar_years_are_taken_on_the_utc_instant`, `test_audit_cutoff_is_not_a_fixed_number_of_days` | PASS | 2029-03-01Z → 2026-03-01Z; 2028-02-29 → 2025-02-28; 2028-02-29T05:00+08:00 → 2025-02-28T21:00Z through `cutoffs` and `minus_years`; 1,096 / 1,095 days across / not across a leap day |
| CHK-M11-043 | `test_a_naive_datetime_raises_value_error` (8 calls) | PASS | `ValueError` for a naive `now`, `cutoff`, row `at`, `manager_now`, `db_now`, `newest`; no value in the message |
| CHK-M11-044 | `test_audit_prefix` (13 cases) | PASS | old, old, new, old → 2; all new → None; gaps → 9; cursor 1 → 1; no cursor → None; ids 5, 8 with cursor 7 → 5 (a stored id); cursor below first id → None; `limit` 2 and 1 respected |
| CHK-M11-045 | `test_audit_prefix_boundary_is_strict`, `test_audit_prefix_accepts_aware_non_utc_times` | PASS | an entry at the cutoff stops the prefix; 1 µs older continues |
| CHK-M11-046 | `test_clock_doubt_is_more_than_five_minutes_either_way` (7 gaps × 3 forms) | PASS | 5 min → False; 5 min + 1 µs and 5 min 1 s → True; manager ahead and behind |
| CHK-M11-047 | `test_future_rows_is_more_than_one_day_ahead` (8 cases) | PASS | +1 d → False; +1 d + 1 µs → True; None → False |
| CHK-M11-048 | `test_rules_are_pure`, `test_package_exports_nothing_with_side_effects` | PASS | AST: imports only `collections.abc`, `dataclasses`, `datetime`, `typing`; no clock read, I/O or logging; the package `__init__` is a docstring |
| CHK-M11-080 | `test_audit_prefix_property` (hypothesis, 600 examples) | PASS | the answer equals the largest stored id N ≤ cursor within `limit` with every entry up to N old, else None |
| (extra) | `test_guards_fail_closed` | PASS | implementer additions, not spec: `limit` 0, ids out of order, negative years raise `ValueError` |

### Plants (throwaway copies `/root/m11t/mut-<id>`, deleted after each row; runner `plant.py`, log `/root/m11t/logs/plants-236.jsonl`)

20 plants, 20 red. Each row was applied once (exact text found once) to a copy of the synced tree and run with `tests/test_retention_rules.py`.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-351 | scan age 399 days | constants, each cutoff (5 failed) |
| CHK-M11-352 | tokens at expiry (age 0) | constants, each cutoff (5 failed) |
| snapshot 179, request 91, inventory job 31 days | each age off by one day | each cutoff (5 failed each) |
| scan chunk 1,000 | chunk constant | constants (1 failed) |
| CHK-M11-396 (rules part) | prefix stops at `at > cutoff` instead of `>=` | prefix boundary (2 failed) |
| CHK-M11-397 | `clock_doubt` with `>=` | clock doubt at 5 min (1 failed) |
| clock one way | `gap > 5 min` without `abs` | clock doubt, manager behind (4 failed) |
| CHK-M11-398 | `future_rows` with `>=` | +1 d case (1 failed) |
| CHK-M11-399a | prefix not capped at the cursor | prefix, property (4 failed) |
| CHK-M11-399b | prefix returns the cursor itself (7, not stored) | prefix (3 failed) |
| CHK-M11-349 (rules part) | no cursor treated as "everything shipped" | prefix, property (2 failed) |
| CHK-M11-348 (rules part) | prefix skips new entries (a hole in the chain) | prefix, boundary (4 failed) |
| limit ignored | `rows[:limit]` → `rows` | prefix `limit` cases, property (3 failed), **after strengthening** |
| CHK-M11-400 | years as 365-day steps | calendar years, fixed days (6 failed) |
| Feb 29 → Mar 1 | wrong leap fallback | calendar years (2 failed) |
| local years | calendar step on the caller's zone | UTC instant (1 failed), **after strengthening** |
| naive accepted | naive treated as UTC | naive (1 failed) |
| `import time` | impurity | purity (1 failed) |

Two plants survived the first round, and both showed test gaps, not product faults: (1) the property test drew random boolean lists that seldom held a leading run of old entries longer than `limit`, so ignoring `limit` passed it (the table cases already failed). It now builds a leading run of 0–40 old entries plus a random tail. (2) `cutoffs()` converts to UTC before calling `minus_years`, so a local-zone `minus_years` was not reached. The test now also asserts `minus_years(local, 3)` directly. Both plants were re-run and are red.

### Acceptance (TASK-236: "REQ-274 (1)–(4) hold and the clock-doubt decision is true at 5 min 1 s of skew and false at 5 min")

- REQ-274 (1): CHK-M11-041, -045. (2): CHK-M11-044, -080. (3): CHK-M11-042. (4): CHK-M11-043.
- Clock doubt: CHK-M11-046 (5 min False; 5 min 1 s True; also 5 min + 1 µs True).
- Future rows (REQ-278 rule level): CHK-M11-047.

### Notes

- Strict `<` on every cutoff is asserted at rule level here and again at repository level in TASK-237 (CHK-M11-135, plant CHK-M11-396).
- Nothing in the spec was found open.

## TASK-233 (results view and CSV, pure)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-001 | `::test_include_output_only_for_operator_and_admin` (11) | PASS | True only for `operator`, `admin`; False for `viewer`, `""`, `Admin`, `OPERATOR`, padded, `root`, `api`, `session` |
| CHK-M11-002 | `::test_viewer_item_has_no_output_keys`, `::test_operator_item_has_both_output_keys`, `::test_item_values_effective_and_original`, `::test_never_reevaluated_both_verdicts_equal` (3) | PASS | Viewer item: exactly 22 keys, no `stdout` / `stderr` key, no OUT / ERR canary. Operator item: 24 keys. `result` = effective (PASS, "re detail"), `original_result` = stored (FAIL, "orig detail"); never re-evaluated: both equal, `reeval_*` null. |
| CHK-M11-003 | `::test_not_run_item` | PASS | `result`, `job_id`, `original_*`, flags, times, `reeval_*`, output all null; name, operator, expected, execute are the planned values; `retry` false |
| CHK-M11-004 | `::test_retry_true_only_for_a_result_in_the_retry` | PASS | original false, retry job true, Not run false |
| CHK-M11-005 | `::test_items_validate_against_the_route_models` | PASS | viewer items validate as `ScanResultItem`, operator items as `ScanResultItemWithOutput`; a viewer item fails the output model |
| CHK-M11-006 | `::test_csv_constants` | PASS | the #146 (b) 17 names in order; output columns last; cap 100,000 |
| CHK-M11-007 | `::test_viewer_csv_has_no_output_column`, `::test_operator_csv_has_output_columns_last` | PASS | Viewer CSV: 17 columns on every record, no canary, no `stdout` / `stderr` in the text. Operator CSV: 19 columns, canaries in the last two. |
| CHK-M11-008 | `::test_csv_cell_forms`, `::test_csv_times_are_utc_whatever_the_zone`, `::test_csv_text_is_bom_free_and_crlf_only` | PASS | null → empty; `true` / `false`; times end in `Z` and equal the instant (also from a +08:00 value); `PASS` / `FAIL`; Not run `result` empty; no BOM; CRLF |
| CHK-M11-009 | `::test_formula_cells_get_a_quote_in_every_text_column` (66), `::test_safe_cells_are_unchanged` (5), `::test_every_cell_of_a_row_passes_through_escape_cell` | PASS | `=`, `+`, `-`, `@`, tab, CR, and whitespace (incl. NBSP) before a trigger get `'` in hostname, plugin name, both details, stdout and stderr; `a=b`, `1-2`, `x@y`, empty unchanged; exit code −9 → `'-9` |
| CHK-M11-010 | `::test_rfc4180_quoting_round_trips` | PASS | commas, quotes, LF, CRLF in stdout round-trip exactly |
| CHK-M11-011 | `::test_every_cell_goes_through_m5_escape_cell`, `::test_results_view_does_not_use_the_csv_module` | PASS | a recording `escape_cell` saw 19 × 3 cells (header first); no `csv` or `re` import |
| CHK-M11-012 | `::test_status_values_accepted` (4), `::test_no_filter_is_none`, `::test_unknown_status_raises_naming_the_parameter_only` (9) | PASS | the four values exact; `pass`, `Pass`, `NOTRUN`, `NOT RUN`, `""`, `OK`, padded → `InvalidResultQuery`, `str()` = `status`, no value echoed |
| CHK-M11-013 | `::test_hostile_text_is_returned_verbatim` | PASS | `<script>`, `<img onerror>`, U+202E, U+FFFD verbatim in items and CSV |
| CHK-M11-014 | `::test_module_imports_only_the_allowed_names`, `::test_row_type_is_a_plain_value` | PASS | Own imports only: `csv_export`, `ResultRow` (the one name from `result_reads`) and standard library modules; no logging, clock or database call. The transitive reading cannot hold (the IMPL report is right: the `csv_export` package already loads psycopg), so the row checks the module's own import statements. |

### Plants (throwaway copies; log `/root/m11t/logs/plants-233.jsonl`)

21 plants: 20 red, 1 equivalent.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-320 | `include_output` true for viewer | role table (1 failed) |
| CHK-M11-404 | true for any role but `viewer` (unknown roles fail open) | role table (8 failed) |
| case-insensitive role | `role.strip().lower()` | role table (4 failed) |
| CHK-M11-322 | viewer items carry `stdout: null` | viewer keys (2 failed) |
| viewer item leaks | output keys always set | viewer keys (2 failed) |
| CHK-M11-323 | viewer CSV keeps the two columns (empty) | viewer CSV (3 failed) |
| viewer CSV leaks values | output values written for viewers | viewer CSV (2 failed) |
| CHK-M11-324 | Python's `csv` module instead of `write_csv` | formula, escape spy, no-`csv` (70 failed) |
| CHK-M11-325 | `escape_cell` skipped for stdout and stderr | formula cells in those columns (23 failed) |
| CHK-M11-328 (view part) | `original_result` from the effective code | effective and original (1 failed) |
| result from original | `result` from the stored code | effective and original (1 failed) |
| CSV result from original | CSV `result` from the stored code | cell forms (1 failed) |
| status case-folded | `status.upper().strip()` | unknown status (4 failed) |
| status message echoes value | `f"status {status!r}"` | unknown status (9 failed) |
| retry always false | `retry: False` | retry (1 failed) |
| local times | `isoformat()` instead of UTC `Z` | cell forms, UTC zone (2 failed) |
| Python booleans | `str(True)` | cell forms (1 failed) |
| null as `None` | `None` written as the text `None` | cell forms (1 failed) |
| header order | `retry` and `job_id` swapped | constants (5 failed) |
| cap 100,001 | cap constant | constants (1 failed) |
| codes > 2 as FAIL | fallback of `_verdict` | **equivalent**: `eval_code` is `CHECK (eval_code IN (0, 1, 2))` in TS §5.2, so no other code can reach the view |

### Acceptance (TASK-233: "viewer items have no stdout/stderr key and viewer CSV no such columns, operator and admin items and CSV have them, every CSV cell goes through escape_cell, and an unknown status raises InvalidResultQuery")

Viewer items and CSV: CHK-M11-002, -007. Operator and admin: CHK-M11-001, -002, -007. Every cell through `escape_cell`: CHK-M11-009, -011. Unknown status: CHK-M11-012.

### Notes

- `include_output` gets the role from its caller. "Current role, whatever the token kind" (REQ-268 (2), plant CHK-M11-321) is checked where the role is read: TASK-241 and TASK-244.
