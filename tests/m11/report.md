# M11 test report

Phase report for M11 (results and end-to-end). The lead folds in each section unchanged from the tester's per-task report `work/reports/<id>-test.md`, which is the source, with headings demoted one level. The harness refuses report-file writes from tester sub-agents, as in M9 and M10.

| Report | Verdict line | Source |
| --- | --- | --- |
| M11 gate | M11 gate: PASS, except G39 NOT RUN (safety-check refusal) and CHK-M11-387 FAIL as the v1 limit (pending the user) | `work/reports/M11-gate-test.md` |
| CHK-M11-387 | #151 retention timing: FAIL as the v1 limit (pending the user) | `work/reports/CHK-M11-387-test.md` |
| TASK-232 | TASK-232 TEST (r0 and r1): PASS | `work/reports/TASK-232-test.md` |
| TASK-233 | TASK-233 TEST: PASS | `work/reports/TASK-233-test.md` |
| TASK-234 | TASK-234 TEST: PASS | `work/reports/TASK-234-test.md` |
| TASK-237 | TASK-237 TEST: PASS | `work/reports/TASK-237-test.md` |
| TASK-238 | TASK-238 TEST: PASS | `work/reports/TASK-238-test.md` |
| TASK-239 | TASK-239 TEST (W2 web batch): PASS | `work/reports/TASK-239-test.md` |
| TASK-235 | TASK-235 TEST: PASS | `work/reports/TASK-235-test.md` |
| TASK-236 | TASK-236 TEST: PASS | `work/reports/TASK-236-test.md` |
| TASK-240 | TASK-240 TEST: PASS | `work/reports/TASK-240-test.md` |
| TASK-241 | TASK-241 TEST: PASS | `work/reports/TASK-241-test.md` |
| TASK-242 | TASK-242 TEST: PASS | `work/reports/TASK-242-test.md` |
| TASK-243 | TASK-243 TEST: PASS | `work/reports/TASK-243-test.md` |
| TASK-246 | TASK-246 TEST (W3/W4 web batch): PASS | `work/reports/TASK-246-test.md` |
| TASK-247 | TASK-247 TEST (W3/W4 web batch): PASS | `work/reports/TASK-247-test.md` |
| TASK-248 | TASK-248 TEST (W3/W4 web batch): PASS | `work/reports/TASK-248-test.md` |
| TASK-249 | TASK-249 TEST (W3/W4 web batch): PASS | `work/reports/TASK-249-test.md` |
| TASK-250 | TASK-250 TEST (W3/W4 web batch): PASS | `work/reports/TASK-250-test.md` |
| TASK-256 | TASK-256 TEST (W3/W4 web batch): PASS | `work/reports/TASK-256-test.md` |
| TASK-251 | TASK-251 TEST (W3/W4 web batch): PASS | `work/reports/TASK-251-test.md` |
| TASK-257 | TASK-257 TEST: PASS | `work/reports/TASK-257-test.md` |
| TASK-258 | TASK-258 TEST (r0 and r1): PASS | `work/reports/TASK-258-test.md` |
| TASK-244 | TASK-244 TEST: PASS | `work/reports/TASK-244-test.md` |
| TASK-245 | TASK-245 TEST: PASS | `work/reports/TASK-245-test.md` |
| TASK-252 | TASK-252 TEST (with the 253/259 docs walks, TP-M11-16, -21): PASS | `work/reports/TASK-252-test.md` |
| TASK-253 | TASK-253 TEST: PASS | `work/reports/TASK-253-test.md` |
| TASK-259 | TASK-259 TEST: PASS | `work/reports/TASK-259-test.md` |
| TASK-255 | TASK-255 TEST: PASS | `work/reports/TASK-255-test.md` |
| TASK-261 | TASK-261 TEST (gate r1): PASS | `work/reports/M11-gate-test.md` (r1 section) |
| TASK-260 | TASK-260 TEST: PASS | `work/reports/TASK-260-test.md` |
| TP-M11-17 | TP-M11-17 (harness carries): PASS | `work/reports/TP-M11-17-test.md`; rows in `work/reports/M11-e2e-test.md` |
| TP-M11-18 | TP-M11-18 (nightly harness): PASS | `work/reports/TP-M11-18-test.md`; rows in `work/reports/M11-e2e-test.md` |
| TP-M11-19 | TP-M11-19 (N / N−1): PASS | `work/reports/TP-M11-19-test.md`; rows in `work/reports/M11-e2e-test.md` |
| TASK-254 | TASK-254 TEST (TP-M11-20): PASS on every row run; CHK-M11-373, -374 NOT RUN (awaiting the user) | `work/reports/TASK-254-test.md` |

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

## TASK-234 (scan reads repository)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-105 | `::test_no_filter_newest_first_with_scan_id_tiebreak`, `::test_scan_row_fields` | PASS | 5 scans in the window, in oracle order, including a tie on `created_at` broken by `scan_id` desc. Fields: policy id, name, version; state as stored; `target_kind` agents / tags / all; `resolved_count` = len(`resolved_agents`). |
| CHK-M11-106 | `::test_each_filter_alone_and_all_together`, `::test_date_bounds_inclusive_and_exclusive`, `::test_times_with_any_offset` | PASS | `policy_id`, `agent_id`, `state` (incl. `queued` → none), `created_after` (≥), `created_before` (<), and all together (one scan). A scan at `created_after` is included; one at `created_before` is excluded. A +18:00 instant selects by instant; a naive time raises `ValueError`. |
| CHK-M11-107 | `::test_keyset_limit_2_visits_every_scan_once` (4 filter sets × limit 1 and 2) | PASS | every scan once, in order, with the tie across a page boundary |
| CHK-M11-108 | `::test_agent_filter_matches_the_resolved_list_only` | PASS | a scan whose tag text equals agent A's id (resolved to C only) is not returned for A |
| CHK-M11-109 | `::test_a_deleted_anchor_raises_anchor_gone` | PASS | scan list and host history raise `AnchorGone` for a deleted anchor |
| CHK-M11-110 | `::test_scan_detail` | PASS | policy name; `target` = the request, no `resolved_agents`; a soft-deleted policy's scan still returned; unknown id → None |
| CHK-M11-111 | `::test_scan_jobs_with_hostnames_in_detail_order` | PASS | hostname, then `agent_id` (two hosts named `alpha`), original before retry; every state as stored; an inventory job of a host is not listed |
| CHK-M11-112 | `::test_agent_history`, `::test_decommissioned_agent_history` | PASS | agent A in 3 of 5: exactly those, newest first; `limit=1` visits each once; `agent_exists` true / false; a decommissioned agent's history returned |
| CHK-M11-113 | `::test_select_only_as_bitscan_app` | PASS | every statement starts with SELECT; no write, DDL or row lock (`FOR`); ids are parameters, never in the SQL text |
| CHK-M11-114 | `::test_select_only_as_bitscan_app`, `::test_wrong_grants_would_be_seen` | PASS | every statement is from login role `bitscan_app`; a page reads fine inside a READ ONLY transaction |

### Plants (throwaway copies; log `/root/m11t/logs/plants-234.jsonl`)

13 plants, 13 red.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-406 (a) | order by `scan_id` only | order and keyset (9 failed) |
| CHK-M11-406 (b) | `created_after` exclusive | bounds (6 failed) |
| `created_before` inclusive | `<=` | bounds (2 failed) |
| keyset `<=` | anchor repeated | keyset and host history (5 failed) |
| keyset on time only | tie dropped across pages | `limit=1` keyset walk (1 failed), **after strengthening** |
| agent matched in any target text | `strpos(target::text, …)` | resolved-list-only and filters (3 failed) |
| `policy_id` filter dropped | | filters (1 failed) |
| `state` filter dropped | | filters (1 failed) |
| `AnchorGone` not raised | paging restarts | deleted anchor (1 failed) |
| detail keeps `resolved_agents` | | detail (1 failed) |
| retry listed first | | jobs order (1 failed) |
| deleted policy hidden | `p.deleted_at IS NULL` in the join | detail (1 failed) |
| G1: f-string SQL | a planted `f"SELECT … '{x}'"` in `scan_reads.py` | `ruff check`: S608 (TASK-234 acceptance "G1 is red on a planted f-string") |

The keyset-on-time-only plant survived the first round. At `limit=2`, the two tied scans always fell on the same page. The keyset test now also runs at `limit=1`, and the plant is red.

### Acceptance (TASK-234: "each filter and the keyset return the expected rows in order, the target containment test uses a parameter, a deleted anchor raises AnchorGone, a spy sees SELECT only, and G1 is red on a planted f-string")

Filters and keyset: CHK-M11-105 to -107. Containment with a parameter: CHK-M11-108 and -113 (the id is not in the SQL text). AnchorGone: CHK-M11-109. SELECT only: CHK-M11-113. G1: plant P234-G1-fstring.

### Notes

- `scan_jobs` filters `kind = 'compliance'`. A plant removing that filter would be equivalent, because inventory jobs have `scan_id` NULL (TS §5.2 CHECK), so it was not planted.

## TASK-232 (API contract, r0 and r1)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-230 | `test_m11_contract.py::test_exactly_the_six_operations_are_added`, `::test_scan_list_parameters`, `::test_scan_id_operations_parameters` (4), `::test_host_history_parameters`, `::test_success_schemas_and_declared_refusals` (5), `::test_results_csv_is_text_csv` | PASS | The six operations, all under `/api/v1/`. The paths without them equal the 6efe0fb digest `094aaf0f…` (`POST /scans` is byte-identical). `limit` 1–500 default 50; `policy_id` ≥ 1; `agent_id` uuid; `state` = the six scan states; dates are `date-time`. Path ids use the hyphenated UUID pattern. Results take `status` (4 values) and `agent_id`; the CSV has no cursor; re-evaluate has no `requestBody`. 200 schemas as planned; refusals {400, 401, 403, 429, 503} plus 404, plus 409 for re-evaluate; CSV is `text/csv` string. |
| CHK-M11-231 | `::test_model_properties_are_exactly_the_plan` (10), `::test_model_value_types`, `::test_output_fields_only_in_the_operator_model` | PASS | Every M11 model has exactly the plan's properties, all required. `stdout` / `stderr` appear only in `ScanResultItemWithOutput`. No `resolved_agents`, `execute` or `expected` in the scan models. `score` is a number or null; `HostJob.state` has the eight job states. |
| CHK-M11-232 | `::test_earlier_components_are_byte_identical` | PASS | 80 earlier component schemas, digest `23f9503a…` = 6efe0fb (agent `ResultItem` included); M11 adds exactly 10 |
| CHK-M11-233 | `test_m11_contract_api_pg.py::test_reads_answer_501_after_auth_for_any_role` (15), `::test_reads_refuse_missing_wrong_group_and_revoked_tokens` (20), `::test_reevaluate_refusals_come_before_the_handler` (10), `::test_reevaluate_admin_session_reaches_the_501`, `::test_reevaluate_sink_gate_at_15_minutes` | PASS | Reads: viewer and admin, session or API token → 501 `about:blank`; no token, `bsa_`, `bse_`, revoked → 401 `unauthorized`. Re-evaluate: viewer and operator sessions → 403 `forbidden`; admin API token → 403 `totp_session_required`; viewer and operator API tokens → 403; restricted admin → 403 `totp_enrolment_required`; 401 for the four token cases; admin TOTP session → 501. Sink outage at 14 min 59 s → 501, at 15 min → 503 `audit_sink_unavailable` (reads unaffected), after the drain → 501. No `scan_result_reeval` row and no `scan.reevaluate` entry at any point. |
| CHK-M11-234 | `test_m11_contract.py::test_results_csv_is_its_own_route`; `test_m11_contract_api_pg.py::test_malformed_scan_ids_are_400` (5), `::test_malformed_reevaluate_id_is_400_for_an_admin`, `::test_upper_case_scan_id_passes_the_pattern`, `::test_invalid_query_values_are_400` (12), `::test_limit_500_and_an_offset_date_pass_validation` | PASS (contract part) | `/results.csv`, `/results` and `/{id}` each match only their own route. Non-UUID, unhyphenated and suffixed ids → 400 `invalid_request`; an upper-case id is accepted. `limit` 0/501, `state` `expired`/`dispatched`, `policy_id` 0, malformed `agent_id`, a date without an offset, `status` `pass`/`NOTRUN`/`OK` → 400, never 422. The 404 for `/agents/not-a-uuid/scans` belongs to the handler, so it is checked in TASK-244 TEST. |
| CHK-M11-235 | `test_m11_contract.py::test_route_walk_markers`; `test_openapi.py` (6); `test_invariants_m3.py` (33, incl. the spec-route allow-list); `test_auth_dependencies.py` route walks | PASS | Markers: five reads `("role", "viewer", restricted=False, sink_gate=False)`; re-evaluate `("totp_session", "admin", False, True)`. G6: committed file = fresh export. G34 green. |

### Plants (throwaway copies `/root/m11t/mut-<id>`, deleted after each row; log `/root/m11t/logs/plants-232.jsonl`)

12 plants: 11 red, 1 equivalent.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-346 | `POST /scans/{id}/rerun` with an `execute` body | `test_every_operation_is_a_spec_route`, `test_no_request_schema_carries_a_command`, `test_committed_file_matches_a_fresh_export` (4 failed) |
| CHK-M11-335 | re-evaluate on `require_role("admin")` (API tokens accepted) | route-walk markers, refusals (admin API token got 501) (3 failed) |
| CHK-M11-336 | `require_totp_session(sink_gate=False)` | markers, sink gate at 15 min (2 failed) |
| CHK-M11-337 | minimum role operator | markers, operator session refusal (2 failed) |
| no auth on re-evaluate | auth dependency removed | markers, every refusal row, M2 route walk (13 failed) |
| reads on operator | viewer refused | markers, the viewer 501 rows (31 failed) |
| stdout in viewer model | `stdout` added to `ScanResultItem` (re-exported) | model properties, output-fields walk (2 failed) |
| CHK-M11-392 | query parameter added without re-export | G6 `test_committed_file_matches_a_fresh_export`, M3 query allow-list (3 failed) |
| component rename | viewer model named `ResultItem` (collides with the agent component) | the export itself fails, so all of `test_openapi.py` is red (6 failed) |
| no id pattern | `SCAN_ID` without `pattern` | malformed ids reach the handler, and G6 (7 failed) |
| re-evaluate reads a body | a body parameter added (re-exported) | `test_scan_id_operations_parameters` (1 failed) |
| CSV 200 entry removed | the explicit `text/csv` 200 entry dropped (re-exported) | **equivalent**: FastAPI exports the same `text/csv` string content without the entry, so the document is unchanged and nothing can turn red |

### Acceptance (TASK-232: "G6 is green and the exported document holds exactly the plan TASK-232 operations, parameters, schemas and auth markers, and each handler answers 501 only after its auth dependency ran")

- G6: CHK-M11-235 (`test_openapi.py`). Operations and parameters: CHK-M11-230. Schemas: CHK-M11-231, -232. Auth markers: CHK-M11-235. 501 after auth: CHK-M11-233 (viewer on re-evaluate 403; no token 401).
- G16 stays red until TASK-239, as planned. It was not run here.

### Notes

- **W1-only rows.** The 501 assertions in `test_m11_contract_api_pg.py` hold only until the handlers are filled (PD-48). TASK-243 TEST and TASK-244 TEST will replace them with the filled answers. The refusal rows stay.
- **Question for `main` (recorded, not asserted).** The query `agent_id` on `/scans`, `/results` and `/results.csv` is typed `UUID`, as plan §3 says. It therefore also accepts the 32-hex, braced and `urn:uuid:` forms, while the path ids accept only the hyphenated form. The spec (TS §6.3 L1141, "IDs are UUID strings") does not say which. This report asserts only clearly malformed values (400).
- **For TASK-244.** `list_results` declares `Page[ScanResultItem] | Page[ScanResultItemWithOutput]`, so FastAPI validates the returned page against the union. TASK-244 TEST must show that operator items keep `stdout` / `stderr` through that union, and that a viewer page never carries them (CHK-M11-222).

---

## TASK-232 r1 TEST: PASS

Tester: tester-m11, 2026-11-08. r1 follows the decision of 2026-11-08 ("Correction: M11 query agent_id is hyphenated-only"). The query `agent_id` on `GET /scans`, `/scans/{id}/results` and `/results.csv` is now `Annotated[str | None, Query(pattern=UUID_PATTERN)]`. Code under test: `bm/api/user/scan_views.py` (sha256 `1e2b527addbebed2…`), `manager/openapi.json` (`126c54291c52c098…`); impl report section "r1" of `work/reports/TASK-232-impl.md`. This supersedes the "Question for main" note above.

### Changes to the tests

- `test_m11_contract.py`: the expected query `agent_id` schema is now `{"pattern": <8-4-4-4-12>, "type": "string"}` (`AGENT_ID_SCHEMA`), in `test_scan_list_parameters` and `test_scan_id_operations_parameters`; it was `format: uuid`.
- `test_m11_contract_api_pg.py`, new:
  - `test_query_agent_id_is_hyphenated_only`: 3 paths × 7 values. The 32-hex form (both cases), the braced `{…}` and `urn:uuid:` forms, a trailing LF, a leading space and a short id each get 400 `invalid_request`. This is row (a).
  - `test_query_agent_id_hyphenated_any_case_is_accepted`: 3 paths × lower and upper case pass validation (501 on W1). This is row (b).

### Runs (W, `CI=true`, `-n 2`)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest test_m11_contract.py test_m11_contract_api_pg.py test_openapi.py test_invariants_m3.py test_auth_dependencies.py test_scans_api_pg.py test_agents_api_pg.py` | 235/235 passed, 0 failed, 0 errors, 0 skipped (the first attempt did not collect: a literal line break that my edit script wrote into a test string; fixed before any test ran) |
| Plant (c) | `AGENT_ID = UUID \| None` in a throwaway copy, `pytest -n 2 tests/test_m11_contract_api_pg.py` | RED: 12 failed, 82 passed. The 32-hex, upper 32-hex, braced and `urn:uuid:` forms are accepted on each of the 3 paths. Padded and short values fail under both types. |
| Lint | ruff, ruff format, mypy --strict on both test files | clean |

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-230 (r1) | `test_m11_contract.py::test_scan_list_parameters`, `::test_scan_id_operations_parameters` | PASS | query `agent_id` declared with the hyphenated pattern on the three paths |
| CHK-M11-234 (r1 a) | `test_m11_contract_api_pg.py::test_query_agent_id_is_hyphenated_only` (21) | PASS | 400 `invalid_request` for each non-hyphenated form |
| CHK-M11-234 (r1 b) | `::test_query_agent_id_hyphenated_any_case_is_accepted` (6) | PASS | lower and upper case pass validation |
| CHK-M11-234 (r1 c) | plant `P232r1-agent-id-uuid-type` | RED | 12 failed (log `/root/m11t/logs/plants-232r1.jsonl`) |

## End-to-end and N / N−1 (tester-m11e)

Counted runs (tester-m11e, 2026-11-09):
- Hosted e2e run **42488215323** on `5671c82` (an `[e2e]` push): build success; nightly **19/19 PASS**; compat-a **10/10 PASS** (8 expected rows plus the extra -295 and -300; CHK-M11-306 is ERROR `runner_unavailable`, exit_code null, score null, errors 1); compat-b **8/8 PASS**; every gate green; 0 token-shaped strings in the artifacts.
- Upgrade walk (CHK-M11-307) in WSL on `5671c82` with the CI `.deb`: **16/16 PASS** (196/196 installed files match the wheel's hashes; the 0.1.0 agent heartbeats and sends inventory after the manager upgrade without re-enrolment; after the agent upgrade, scan:after PASS).
- Plants CHK-M11-370 (the runner never sends its result), -371 (a results route keeps only the first host) and -372 (a manager refusing `0.1.*` heartbeats): each red at exactly its row.
- Check (c), a push without `[e2e]`: run 42485349317, every job skipped: PASS.
- NOT RUN: CHK-M11-373 and -374 (the hosted plant branches; awaiting the user's OK to push throwaway branches; local equivalents red); actionlint (not installed).
- Known gaps: no Hyper-V form of `guests.sh`, so the user's standing local-VM fallback cannot run; `test_serve_linux.py::env_for` creates no `BITSCAN_BITS_DIR` (REQ-291 is met through the walk).


The rows are kept by tester-m11e in `work/reports/M11-e2e-test.md` (CHK-M11-290 to -309, plants -370 to -374). TP-M11-17 verdict: `work/reports/TP-M11-17-test.md`.

## TASK-239 (web client, Score, ResultBadge, CSV download)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-260 | G16 regen-to-temp + `cmp`; `npm run typecheck`; `npm run lint`; `npm run format:check` (from `web/`, L) | PASS | identical sha256 `e7ffd8c4…c30a`; tsc, eslint (0 warnings) and prettier exit 0; six M11 paths present |
| CHK-M11-261 | `npx vitest run src/components/Score.test.tsx` | PASS | 26/26 (part of 51/51) |
| CHK-M11-262 | `npx vitest run src/components/ResultBadge.test.tsx` | PASS | 10/10 (part of 51/51) |
| CHK-M11-263 | `npx vitest run src/app/download.test.ts` | PASS | 7 M11 tests + 5 M5 kept (15/15 with -264) |
| CHK-M11-264 | `npx vitest run src/app/download.test.ts` | PASS | 3/3 refusal tests (400 cap detail, 404, 401 ends session) |
| TASK-239 affected | `npx vitest run` on the 11 importer test files | PASS | 197/197 |
| CHK-M11-363 | plant in throwaway copy | PASS (red as required) | 3 failed / 26 |
| CHK-M11-364 | plant in throwaway copy | PASS (red as required) | 6 failed / 26 |
| CHK-M11-365 (W2 half) | plant in throwaway copy, two variants | PASS (red as required) | 4 failed / 10; variant "only when differs" 2 failed / 10 |
| CHK-M11-377 | plant in throwaway copy | PASS (red as required) | 7 failed / 26 |
| CHK-M11-378 | plant in throwaway copy | PASS (red as required) | 1 failed / 15, not a Blob |
| G16 plant | hand edit to `schema.d.ts` in the copy | PASS (red as required) | `cmp` exit 1 |

## TASK-235 (result reads repository)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-118 | `test_result_reads_pg.py::test_req267_1_one_item_per_planned_plugin`, `::test_viewer_variant_same_items_without_output` | PASS | `results_world` gives exactly 15 items, all 26 fields equal. **Host a:** p1's `result` comes from the higher `reeval_id` (PASS "high", whose `reevaluated_at` is earlier); `original_result` FAIL is unchanged; p3 is answered in the retry (`retry` true, one item); p4 is Not run. **Host b:** queued, so all 5 are Not run; the `<script>` hostname is returned verbatim. **Host c:** all stored. Positions are 1–5 in payload order; never re-evaluated means both verdicts are equal. The viewer variant gives the same items with `stdout`/`stderr` None. |
| CHK-M11-119 | `::test_results_in_two_partitions_both_read` | PASS | results of the original and the retry sit in two monthly partitions (not the default), and both are read |
| CHK-M11-120 | `::test_not_run_named_from_eval_spec_never_the_catalog` | PASS | The job's stored `eval_spec` (name, operator `contains`, expected) and payload `execute` differ from the catalog. After a rename, a new expected value, a dropped plugin and a soft delete, the Not-run items still carry the job's values, before and after. |
| CHK-M11-121 | `::test_dropped_plugin_keeps_its_reevaluation_and_oversize_error` | PASS | p1 is dropped from the version and the policy is soft-deleted: host a's p1 keeps its re-evaluation (PASS "high"), and every item is unchanged. The `oversize` ERROR keeps both verdicts as ERROR, with empty streams. |
| CHK-M11-122 | `::test_filters_alone_and_together`, `::test_unknown_status_refused_before_any_statement` | PASS | 5 statuses × 5 agent values (incl. an agent not in the scan) equal the oracle. A FAIL re-evaluated to PASS appears under PASS only. NOT_RUN gives the 6 planned plugins with no result, and NOT_RUN for host c gives []. `pass`, `Pass`, `NOTRUN`, `""`, `OK` and `ERROR ` raise `ValueError` before any statement (spy empty). |
| CHK-M11-123 | `::test_keyset_visits_every_item_once[1,2,3]`, `::test_keyset_after_a_filtered_out_anchor` | PASS | At `limit` 1, 2 and 3, under 25 filter sets, the walk equals the oracle: every item once, in order. An anchor the filter excludes still pages strictly after `(agent_id, position)`. A position past a host's payload moves on to the next host. |
| CHK-M11-124 | `::test_another_scans_rows_never_appear` | PASS | A third scan on the same hosts and plugins, with jobs created in the **same microsecond** as host a's original (same partition and `job_created_at`), answers every plugin and has re-evaluations. The scan's items are unchanged under every status. The third scan and `other_scan` show only their own jobs' rows. |
| CHK-M11-125 | `::test_viewer_statement_never_reads_the_output` | PASS | A capture of the raw rows psycopg fetched shows no OUT or ERR byte for the viewer variant, for pages under every status and for the export. It holds EXEC and EXP, catalog text that is allowed. The operator variant's raw rows hold OUT and ERR, so the capture is real. |
| CHK-M11-126 | `::test_export_equals_the_pages_and_reads_one_extra_row`, `::test_export_at_the_csv_cap[100000,100001]` | PASS | The export equals the `limit=2` page walk for 5 statuses × 2 agents × both variants. It reads `max_rows + 1`: caps 3, 13, 14, 15 and 16 give 4, 14, 15, 15 and 15 of the 15 items. `wide_scan` with 100,000 planned plugins returns 100,000; with 100,001 it returns 100,001, keys unique and in order. |
| CHK-M11-127 | `::test_read_only_snapshot` | PASS | `transaction_isolation` = repeatable read and `transaction_read_only` = on. A late result committed by another session is not seen within the snapshot; after commit it is (p4 PASS, `retry` true). An UPDATE inside the snapshot is refused with `ReadOnlySqlTransaction` (25006). Called after a SELECT, the snapshot is refused with `ActiveSqlTransaction`, so it has to be the transaction's first statement. |
| CHK-M11-128 | `::test_exists` | PASS | true for the scan and for a scan with no jobs (page []); false for an unknown id (page [], export []) |
| CHK-M11-129 | `::test_pd46_results_py_frozen_and_composed` | PASS | `results.py` sha256 equals `git show 6efe0fb:…` (`101e9182…`). `result_reads._m8 is results`. `_PAGE` and `_PAGE_VIEWER` are `sql.Composed`, and their first part **is** the `results._EFFECTIVE` object, not a copy; their text begins with its text. |
| CHK-M11-130 | `::test_explain_reads_reeval_once` | PASS | `EXPLAIN (FORMAT JSON)` of the four captured statements (no filter; FAIL with agent; NOT_RUN with keyset; export) shows `scan_result_reeval` exactly once per plan, and never under a SubPlan |
| CHK-M11-131 | `::test_select_only_as_bitscan_app` | PASS | 7 statements, all from login role `bitscan_app`: `WITH`/`SELECT`/`SET TRANSACTION` only, no write verb, no `FOR UPDATE`/`FOR SHARE`; the scan id and agent id are parameters, never in the text |
| CHK-M11-082 | `test_results_property_pg.py::test_200_random_scans_agree_with_m8` (seed 235082) | PASS | Over 200 random scans: one item per planned plugin of each original, in order; every stored result appears once; effective code, detail and re-evaluation fields equal `score.effective()`; `original_*` equal the stored row. Per-host PASS, FAIL, ERROR and Not-run counts of the items equal `results.host_counts`, and a random filter per scan is the matching subset. Branch counter: not run, original, re-evaluated, retry and in-original all > 0. |

### Plants (throwaway copies; log `/root/m11t/logs/plants-235.jsonl`; plants file `/root/m11t/plants-235.json`)

29 plants, 29 red, 0 survived. Each copy was deleted after its row (`ls /root/m11t/mut-*` is empty). Mutation-table ids are from `work/tasks.md`; `CHK-M11-405` is the tester extra from the test plan; `P235-*` are this task's own.

| Plant | Fault | Red tests (count failed) |
| --- | --- | --- |
| CHK-M11-326 | `result` from the original verdict, not the latest re-evaluation | REQ-267 (1), property, filters, keysets … (12) |
| CHK-M11-327 | in M8 `_EFFECTIVE` (composed): latest by `reevaluated_at` instead of `reeval_id` | REQ-267 (1), property, PD-46 hash (14) |
| CHK-M11-328 | `original_result` filled from the effective verdict | REQ-267 (1), property (12) |
| CHK-M11-329 | Not-run plugins left out (`JOIN eff`) | (15) |
| CHK-M11-330 | Not-run name from the current catalog | eval_spec row, REQ-267 (1) (13) |
| P235-notrun-operator-catalog / -expected- / -execute- | Not-run operator, expected or execute from the catalog | eval_spec row (1 each) |
| CHK-M11-331 | back-join to `scan_result` without the job key | another-scan row, REQ-267 (1) (13) |
| P235-planned-any-scan | planned plugins from every `scan_job`, not the scan's jobs | another-scan row (17) |
| P235-viewer-reads-output | viewer statement selects `r.stdout, r.stderr` | raw-row capture, viewer variant (3) |
| P235-variant-ignored | `_PAGE` used for every caller | (3) |
| P235-filter-original-code | status filter on the original code | filters, keysets (6) |
| P235-notrun-filter-inverted | NOT_RUN selects answered plugins | (5) |
| P235-agent-filter-dropped | `agent_id` filter ignored | (5) |
| CHK-M11-405 | keyset `>=` | keysets (5) |
| P235-keyset-position-only | keyset on position only | keysets (5) |
| P235-order-position-first | `ORDER BY ord, agent_id` | (10) |
| P235-position-0-based | `ord - 1` | (13) |
| P235-retry-flag | `retry` true for every stored result | (12) |
| P235-export-no-extra-row | export reads `max_rows`, not `max_rows + 1` | export rows, cap `[100001]` (2) |
| P235-exists-always | `exists` always true | (1) |
| P235-snapshot-writable | snapshot without `READ ONLY` | snapshot (1) |
| P235-snapshot-read-committed | snapshot `READ COMMITTED` (race: late result seen) | snapshot (1) |
| P235-status-unchecked | unknown status not refused | (1) |
| CHK-M11-367 | frozen `results.py` edited (one comment) | PD-46 hash (1); the G83 source check comes with TP-M11-15 |
| P235-pd46-copied | `_EFFECTIVE` text copied into a new `sql.SQL`, not composed | PD-46 composition (1) |
| CHK-M11-368 | a correlated subquery on `scan_result_reeval` per result (same values) | EXPLAIN row (1), and only that row |
| CHK-M11-344 | f-string SQL in `result_reads.py` | `ruff check`: S608 (G1) |

### Acceptance (TASK-235: "REQ-267 (1), (2), (4), (6) hold at repository level, a not-run row takes its name from `eval_spec`, `results.py` is byte-unchanged, and `EXPLAIN` shows `scan_result_reeval` read once per page")

- REQ-267 (1): CHK-M11-118, -119, -121.
- REQ-267 (2): CHK-M11-122.
- REQ-267 (4): CHK-M11-082.
- REQ-267 (6): CHK-M11-124.
- Not-run name: CHK-M11-120.
- `results.py` byte-unchanged: CHK-M11-129.
- EXPLAIN: CHK-M11-130.
- Also covered: REQ-269's repository part (CHK-M11-126) and REQ-272 (CHK-M11-131, plant -344).

### Notes

- `results_page` returns `[]` for an unknown scan and `exists` tells the two cases apart, as the plan says. The 404 is TASK-241 and 244's.
- The impl's `specs` CTE, which joins `eval_spec` entries by `(job_id, plugin_uuid)`, departs from plan §3's sketch, as the impl report says. CHK-M11-120 confirms the outcome the plan requires.
- Test-id ranges: the lead's message today gives me -310 to -369. I use `CHK-M11-405` because tester-m11's test plan already assigns it (tester extras -390 to -406). `main` decides whether those keep their ids.

## TASK-255 (coverage floor precision)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-255 (a) | `test_coverage_floor.py::test_committed_floor_is_85_at_four_digits` | PASS | `fail_under` = 85 (not lowered), `precision` = 4, `branch` = false (lines) |
| TASK-255 (b): 84.99 % exits non-zero | `::test_real_coverage_run_against_the_floor[84.9955]`, `[84.99]` | PASS | 5,693 / 6,698 (the M9 plant, which prints as "85.00 %" at two digits) exits non-zero with "Coverage failure: total of 84.9955 is less than fail-under=85.0000". 8,499 / 10,000 also exits non-zero (84.9900). |
| TASK-255 (c): exactly 85.00 % passes | `::test_real_coverage_run_against_the_floor[85.00]`, `[85.0149]` | PASS | 5,695 / 6,700 = 85.0000 % exits 0, with no "Coverage failure" line. 5,696 / 6,700 = 85.0149 % exits 0. |

### Plants (throwaway copies; log `/root/m11t/logs/plants-255.jsonl`)

3 plants, 3 red.

| Plant | Fault | Red tests |
| --- | --- | --- |
| P255-precision-2 | `precision = 2`, the old value | All 5. The `[84.9955]` run **exits 0** (`assert (0 == 0) is False`): the original defect, caught on the exit code. |
| P255-precision-3 | `precision = 3` | the config row, and all 4 runs on the printed form |
| P255-floor-lowered | `fail_under = 84.99` | the config row. The runs stay green, because the CLI's `--cov-fail-under=85` overrides the config, as in CI. |

Plant finding: in the first round the precision-2 plant was red only because of the printed form ("85.00%" against "84.9955%"). The test now checks the exit code before the text, and the plant is red for the right reason.

### Acceptance (lead's brief: "in a real coverage run, a total of 84.99 % must exit non-zero, and exactly 85.00 % must pass")

Rows (b) and (c), with the precision-2 plant showing the old configuration let 84.9955 % through.

### Notes

- The runs use a generated package, not `bm/services/`. A full-suite G5 run sized to 84.99 % would take the whole manager suite twice. The gate under test is the same: the same pytest-cov `--cov-fail-under` path, the same config file, and coverage.py's `should_fail_under`. The real G5 figure on the services tree is CHK-M11-311, at the wave end (reported to four digits).
- The impl report says nothing parses the coverage output. That matches what I saw: no test or harness file reads the TOTAL line.

## TASK-237 (retention repository, with TP-M11-22 grant probes)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-135 | `test_retention_repo_pg.py::test_each_delete_removes_exactly_the_rows_past_its_cutoff[4 deletes]`, `::test_specific_keeps`, `::test_undecided_request_stays_even_with_a_decided_at`, `::test_at_most_one_chunk_per_call[5]`, `::test_packages_only_unreferenced`, `::test_refuses_a_naive_cutoff_and_a_chunk_below_one` | PASS | As `bitscan_retention`, each delete with `now − age` removes exactly "past" and "old"; "at the cutoff" and "inside" stay. Inventory jobs: compliance jobs and unfinished jobs stay. Requests: pending ones stay, and so does one with an old `decided_at` but no decision. Tokens: past, old and revoked-past go; 89 days, revoked-not-expired and the live API token stay. Packages: only the two unreferenced go. The other rules' rows and the `NEVER_DELETED` checksums are unchanged (`os_info`, `agent_package` included). `n = 1` removes one row per call, then 0. A naive cutoff or `n < 1` raises `ValueError`. |
| CHK-M11-136 | `::test_scan_chunk_oldest_first_at_most_n_no_row_lock` | PASS | ids of scans with `created_at <` cutoff, oldest first; ties are ordered by `scan_id`; at most `n`. While the retention transaction is still open, another session locks the same rows with `FOR UPDATE NOWAIT`, so no row lock is held, and no transaction id is taken. |
| CHK-M11-137 | `::test_delete_scans_removes_whole_scans_only`, `::test_delete_scan_whose_partitions_were_dropped` | PASS | One statement (spy) removes the 2 expired scans, their 4 originals and retries, the results in two partitions, and the re-evaluation rows. The 399-day scan and the scan at 400 days are whole. A scan whose two result partitions were dropped (#44) still goes with its jobs. An empty list or an unknown id gives 0. |
| CHK-M11-192 (repository part) | `::test_scans_step_runs_as_bitscan_retention` | PASS | Lead correction (b): chunk, then `try_reeval_lock` per scan, then `delete_scans`, all in one transaction as `bitscan_retention`, with no error; 2 deleted, "inside" and "at" kept |
| CHK-M11-138 | `::test_try_reeval_lock`, `::test_try_reeval_lock_refuses_autocommit` | PASS | **Race.** False while another session holds M8's lock, taken by M8's own `reeval.lock_scan`; true for a different scan; true again after release. While the retention transaction holds the lock, M8's `lock_scan` in another session waits and times out (`lock_timeout` 300 ms); after rollback it gets the lock. An autocommit connection raises `RuntimeError`. |
| CHK-M11-139 | `::test_newest_per_probe_column`, `::test_newest_unknown_table_raises_before_sql` | PASS | None on empty tables. `scan.created_at` max; inventory-only `scan_job.finished_at` (a compliance job finished 2 days ahead is not probed); `collected_at`; `decided_at`. **`user_token.created_at`** gives now − 65 d, the live tokens' creation, not their `expires_at` of now + 300 d. `audit_log`, `agent`, an injection string, `SCAN` and `""` raise `ValueError` with no statement run. |
| CHK-M11-140 | `::test_db_now_is_the_transaction_clock` | PASS | equals `SELECT now()` in the same transaction; aware; stable within the transaction; within 1 min of the real clock |
| CHK-M11-142 (TASK-237 part) | `::test_bitscan_app_is_refused_every_delete` | PASS | As `bitscan_app`, all six deletes (scans, inventory jobs, snapshots, requests, tokens, packages) raise `InsufficientPrivilege`. Checksums of the nine retention tables are unchanged. The reads (`db_now`, `newest`, `scan_chunk`, `try_reeval_lock`) work with SELECT. |
| CHK-M11-143 | `::test_tokens_91_days_deleted_89_kept_with_a_live_api_token`, `::test_token_probe_decides_the_tokens_step` | PASS | **Lead's row:** with a live API token expiring in 300 days present, the probe does not skip (`future_rows` false). The token expired 91 days ago is deleted; the one expired 89 days ago and the live one stay. **Lead's row:** a token whose `created_at` is 2 days ahead makes `future_rows(newest("user_token"))` true, so the tokens step is skipped; once it is removed, false again. The service-level skip is TASK-242's CHK-M11-189. |
| CHK-M11-144 | `::test_statements_parameterised_select_or_delete_only` | PASS | All 18 statements are from `bitscan_retention` and are SELECT or DELETE only. They contain no INSERT, UPDATE or DDL word and no `FOR UPDATE`/`FOR SHARE`. No scan id or cutoff date appears in the SQL text. |
| CHK-M11-150 | `test_retention_grants_pg.py::test_delete_exactly_on_the_nine_tables`, `::test_select_on_every_table` | PASS | Over every public table (partitions excluded), DELETE is allowed on exactly the nine. DELETE is refused (`42501`) on `agent`, `policy`, `agent_package`, `os_info`, `enrollment_token`, `setting`, `family`, `plugin`, `policy_plugin`, `scan_schedule`, `system_schedule`, `app_user`, `task`, `bit_import`, `agent_tag` and `agent_ip_seen`. SELECT works on every table. |
| CHK-M11-151 | `::test_insert_only_on_audit_log_and_no_update_anywhere`, `::test_sequence_usage_only_on_the_audit_sequence` | PASS | INSERT is refused on every table but `audit_log`; a checkpoint-shaped insert is allowed. UPDATE is refused on every table. `nextval` works only on `audit_log_audit_id_seq`; every other sequence gives `42501`. |
| CHK-M11-152 | `::test_no_row_lock_on_scan[FOR UPDATE, FOR UPDATE SKIP LOCKED, FOR NO KEY UPDATE, FOR SHARE, FOR KEY SHARE]` | PASS | **Lead's row:** the plan's chunk form with each locking clause is `42501` as `bitscan_retention`; the same SELECT without the clause works |
| CHK-M11-153 | `::test_a_new_partition` | PASS | A partition created after the migration (2099-01) holds a result. `bitscan_retention` deletes it through the parent (1 row, rolled back) and can read the partition. `bitscan_app` gets `42501` for DELETE and UPDATE through the parent, the default partition and the new partition. The row remains. |
| CHK-M11-154 | `::test_no_ddl`, `::test_probe_connection_is_not_a_superuser` | PASS | `42501` for DROP and DETACH of a partition, TRUNCATE of `scan`, `audit_log` and a partition, `ALTER TABLE … ADD COLUMN`, `CREATE TABLE` and `CREATE INDEX`; the partition still exists. The role is not a superuser and has no CREATEROLE, CREATEDB or BYPASSRLS. |

### Plants (throwaway copies; log `/root/m11t/logs/plants-237.jsonl`; plants `/root/m11t/plants-237.json`, `plants-237b.json`)

TASK-237 and TP-M11-22: 29 plants (24 + 5), 29 red, 0 survived (no copy left behind). The TASK-238 plants are in its report.

| Plant | Fault | Red tests (count failed) |
| --- | --- | --- |
| CHK-M11-394 | tokens probe back on `expires_at` | `newest` row, the token-probe row, the 91/89-day row (3) |
| CHK-M11-395 | `FOR UPDATE SKIP LOCKED` back in `scan_chunk` | scan chunk, scans step, statements (3): permission denied |
| CHK-M11-396 (×5) | `<=` instead of `<`, for scans, inventory jobs, snapshots, requests and tokens in turn | each rule's boundary row (3, 2, 2, 2, 2) |
| CHK-M11-350 | pending requests deleted by `requested_at` | requests row, specific keeps (3) |
| CHK-M11-401 | `delete_requests` without `decision IS NOT NULL` | the undecided-with-`decided_at` row (1); without that row the plant is equivalent, see Notes |
| CHK-M11-402 | `delete_inventory_jobs` without `kind = 'inventory'` | inventory row, specific keeps (3) |
| CHK-M11-341 | retention deletes `agent_package` rows | packages rows (4): refused by the grants |
| CHK-M11-354 | a scan's jobs deleted, the scan row kept | whole-scan rows (3) |
| CHK-M11-355 | the re-evaluation lock not tried (always true) | lock row (1) |
| P237-lock-wrong-key | another advisory key than M8's | lock row (1) |
| P237-lock-session-level | `pg_try_advisory_lock` (session) instead of xact | lock row (1) |
| P237-lock-autocommit-allowed | autocommit guard removed | (1) |
| CHK-M11-369 | DDL in a delete (`DROP TABLE … scan_result_default`) | whole-scan row (4): refused, not owner |
| P237-chunk-ignored-tokens / -packages | `LIMIT n + 5` | one-chunk rows (1 each) |
| P237-chunk-order | chunk ordered by `scan_id` only | chunk row (1) |
| P237-unknown-table | unknown probe table composed instead of refused | (1) |
| P237-naive-cutoff / P237-chunk-zero | input guards removed | (1 each) |
| CHK-M11-345 | f-string SQL in `retention.py` | `ruff check`: S608 (G1) |
| P22-update-column-on-scan | a throwaway migration grants `UPDATE (state) ON scan` | all 5 lock clauses, because locks become possible (5) |
| P22-delete-agent-package | DELETE on `agent_package` granted | nine-tables row (1) |
| P22-update-audit-log | UPDATE on `audit_log` granted | no-update row (1) |
| P22-insert-scan | INSERT on `scan` granted | insert-only row (1) |
| P22-other-sequence | USAGE on the re-evaluation sequence granted | sequence row (1) |

### Acceptance (TASK-237: "PostgreSQL as bitscan_retention: each delete removes exactly the rows past the cutoff it is given, at most one chunk per call, a scan whose lock another session holds is skipped, and as bitscan_app every delete is refused by the grants")

- Exact rows: CHK-M11-135 and -137.
- One chunk per call: CHK-M11-135.
- Lock held by another session gives false, so the scan is left out: CHK-M11-138. The skip itself is the service's (TASK-242, CHK-M11-193).
- `bitscan_app` refused: CHK-M11-142.
- The lead's three rows: CHK-M11-143 (both) and CHK-M11-152.

### Notes

- `delete_requests` relies on `decision IS NOT NULL`. The DDL does not tie `decided_at` to `decision` (TS §5.2 L775–L777), so I added a row with an old `decided_at` and no decision. Without it, dropping the clause would be an equivalent mutant on every row the app writes.
- The package-prune race (#150 (f)) and the stop flag are service-level (TASK-242: CHK-M11-195, -197). The repository holds no state between calls.
- #151 measurement (CHK-M11-387) is for the gate.

## TASK-238 (audit retention repository)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-141 | `test_retention_repo_pg.py::test_audit_oldest_row_hash_and_delete_through`, `::test_audit_delete_through_with_gaps`, `::test_audit_delete_through_refuses_autocommit` | PASS | `oldest(n)` gives `(audit_id, at)` in id order, at most `n`; the `at` values equal the chosen ones, out of time order (4 y, 4 y + 1 d, 1 d, 5 y …). `row_hash(id)` equals the stored hash for every entry; a missing id raises `LookupError`; `n = 0` raises `ValueError`. `delete_through(N)` removes exactly the ids ≤ N (3 of 6), including a recent entry inside the prefix: the repository deletes by id, and the prefix choice is TASK-236's. With a gap in ids, a non-stored N between two blocks removes the first block only, and N below the first id removes 0. On an autocommit connection `delete_through` raises `RuntimeError` and nothing is deleted. |
| CHK-M11-142 (TASK-238 part) | `::test_bitscan_app_is_refused_every_delete` | PASS | As `bitscan_app`, `delete_through` raises `InsufficientPrivilege` and `audit_log`'s checksum is unchanged; `oldest` works with SELECT |

### Plants (throwaway copies; log `/root/m11t/logs/plants-237.jsonl`)

7 plants, 7 red, 0 survived.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-403 | `delete_through` with `<` instead of `<=` | `test_audit_oldest_row_hash_and_delete_through` |
| CHK-M11-348 | audit delete by `at` (`at <=` the entry's time), a hole in the chain | the same test, plus the gaps test (2) |
| P238-oldest-by-at | `oldest` ordered by `at` instead of id | (1) |
| P238-row-hash-prev | `row_hash` returns `prev_hash` | (1) |
| P238-row-hash-missing | a missing id gives `""` instead of `LookupError` | (1) |
| P238-autocommit-allowed | autocommit guard removed | (1) |
| P238-n-zero | `n = 0` accepted | (1) |

### Acceptance (TASK-238: "PostgreSQL as bitscan_retention: the prefix read returns ids in order with their ages, the delete removes exactly ids ≤ N, and as bitscan_app the delete is refused")

- Prefix read: CHK-M11-141.
- Delete ≤ N: CHK-M11-141, plants -403 and -348.
- App refused: CHK-M11-142.

### Notes

- The checkpoint (written before the delete, in the same transaction, through `append_entry`) and `verify_chain()` after a run are TASK-242's: CHK-M11-182 to -187 and -194. This repository writes no checkpoint.
- The grant that lets `bitscan_retention` insert the checkpoint (INSERT on `audit_log`, USAGE on its sequence) is probed in TP-M11-22, CHK-M11-151 (`TASK-237-test.md`).

## TASK-243 (re-evaluate route)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-200 | `test_reevaluate_api_pg.py::test_admin_totp_session_reevaluates`, `::test_entry_reaches_the_sink_on_the_wake`, `::test_each_call_adds_rows_and_the_latest_wins`, `::test_disabled_policy_is_reevaluated` | PASS | An admin TOTP session gets 200 with exactly `{scan_id, policy_id, scan_policy_version: 1, policy_version: 2, rows_added: 3, not_in_version: 1}`. It adds three rows: p0 FAIL, p1 PASS, p3 ERROR `runner_unavailable`, all `policy_version` 2 and `reevaluated_by` the admin. p2 gets no row and the other scan gets none. `scan_result` is byte-unchanged. There is exactly one new audit entry, `scan.reevaluate`, with actor `user:<id>`, target `scan:<id>` and detail exactly the five counts. The wake runs once, after the entry is committed (another session sees it), and one shipper cycle at that moment delivers it to the recording sink. A statement spy sees no UPDATE or DELETE on `scan_result` or `scan_result_reeval`. A second call adds three rows with higher ids. A disabled policy gets 200 (#118 (c)). |
| CHK-M11-201 | `::test_refusal_writes_nothing_and_reads_no_scan[*]` (12 rows) | PASS | Refused: admin `bsk_` 403 `totp_session_required`; operator and viewer `bsk_` 403; operator and viewer sessions 403 `forbidden`; restricted admin and an admin's session that is not TOTP-verified 403 `totp_enrolment_required` (REQ-046 (d)); an expired admin session, a revoked session, no token, `bsa_` and `bse_` 401 `unauthorized`. Each refusal leaves the `scan_result_reeval` and `audit_log` checksums and counts unchanged and wakes nobody. |
| CHK-M11-202 | `::test_sink_outage_gate_at_15_minutes_and_after_the_drain` | PASS | Under clock control: 14 min 59 s gives 200 (rows added). At 15 min the answer is 503 `audit_sink_unavailable`, with both checksums unchanged. After the drain it is 200 again (6 rows in all). |
| CHK-M11-203 | `::test_unknown_scan_is_404_with_fixed_words`, `::test_deleted_policy_is_409_with_fixed_words`, `::test_malformed_id_is_400_for_an_admin[*]` (6), `::test_upper_case_id_is_accepted`, `::test_viewer_on_an_unknown_scan_is_403_not_404` | PASS | The 404 body is exactly `{type: not_found, title, status: 404, detail: "No such scan.", instance}`, and the 409 body is exactly `{type: conflict, …, detail: "The policy is deleted."}`. Neither holds the id, `Traceback`, an exception class, `psycopg` or SQL. Neither writes or wakes. Not-a-uuid, 32-hex, too long, too short, braced and `urn:uuid:` ids are 400 `invalid_request` with nothing written. An upper-case id gets 200. A viewer on an unknown id gets 403, so there is no existence oracle. |
| CHK-M11-204 | `::test_a_body_never_changes_the_answer[garbage,execute,fields]`, `::test_a_2_mib_body_is_refused_before_any_work` | PASS | Garbage, `{"execute": EXEC…, "scan_id": other}` and unrelated fields all give the same 200 and rows. There is one entry with no canary, and the other scan is untouched. 2 MiB of JSON is 413 `too_large` from the M2 body cap, with nothing written. |
| CHK-M11-205 | `::test_two_concurrent_calls_are_serialised` | PASS | With M8's lock held by another session, call A then call B queue on it. A `pg_locks` probe shows 1, then 2 waiters (20 ms polls, 10 s bound). On release both answer 200. Every one of B's reeval ids is above every one of A's. The latest row of each plugin is B's, and the audit actors are A then B. |
| CHK-M11-206 | `::test_reevaluation_raises_no_alert` | PASS | The one new entry has no `detail.alert`. No entry after the call has `detail ->> 'alert' = 'true'`. Every `bitscan_alerts_total{kind}` sample is unchanged (all kinds exported). |
| CHK-M11-207 | `::test_refusal_writes_nothing_and_reads_no_scan[*]` (the spy half) | PASS | For each of the 12 refusals, a statement spy sees no statement naming `scan`, `audit_log` or an advisory lock. Only the token check ran. |
| CHK-M11-208 | `::test_no_canary_or_token_in_answers_logs_or_audit` | PASS | The calls give 200, 404, 409, 403 (API token), 403 (viewer) and 401 (`bsa_`). No OUT, ERR, EXEC or EXP canary and no caller token appears in any answer, log record (message, args and every attribute, at DEBUG; capture proven by the `token accepted` record), audit detail or sink record. |
| CHK-M11-209 | `::test_route_imports_no_repository` | PASS | AST walk of `reevaluate.py` and the module-level imports of every `bm.api` module it reaches: there is no `bitscan_manager.repositories` import, and `services.evaluator.reevaluate` is found. |
| CHK-M11-413 | `::test_reevaluate_scan_has_one_caller` | PASS | REQ-271 (1): an AST scan of `bitscan_manager/` finds `reevaluate_scan` only in `api/user/reevaluate.py` and in its own module. The whole G83 source check stays with TP-M11-15. |
| CHK-M11-233 (replaced rows) | `test_m11_contract_api_pg.py::test_reevaluate_admin_session_reaches_the_handler`, `::test_reevaluate_sink_gate_at_15_minutes` | PASS | 404 `not_found` on the unknown SID at 14:59 and after the drain; 503 at 15 min; the refusal table unchanged (94/94 in the file) |
| G6 | `python -m bitscan_manager.app` + `cmp` | PASS | byte-identical |

### Plants (throwaway copies `/root/m11c/mut-<id>`, each deleted after its row; plants file `/root/m11c/plants-243.json`, log `/root/m11c/plants-243.out.jsonl`)

13 plants: 13 red, 0 survived. Each one ran the whole of `test_reevaluate_api_pg.py` (`-n 4`), and every expected test failed for the planted reason. The clean tree is run 5.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-335 | `require_totp_session()` swapped for `require_role("admin")` | `refusal[admin:api]` (200), sink gate (no 503), canary sweep (the API-token call got 200): 3 |
| CHK-M11-414 | `require_role("admin", allow_restricted=True)` | `refusal[admin:api]`, `[admin:restricted]`, `[admin:unverified]`, sink gate, canary sweep: 5 |
| CHK-M11-336 | `require_totp_session(sink_gate=False)` | sink gate: 1 |
| CHK-M11-337 | `require_totp_session("operator")` | `refusal[operator:session]`: 1 |
| CHK-M11-338 | `wake=runtime.sink_gate.wake` removed | success row (no wake), immediate-delivery row: 2 |
| CHK-M11-410 | the wake called before the service, not on commit | success and delivery rows (the entry was not yet visible), plus the 404 and 409 rows (they woke the shipper): 4 |
| CHK-M11-340 | alert flag added to M8's `scan.reevaluate` detail | no-alert row, success (exact detail), delivery: 3 |
| CHK-M11-407 | the route raises its own alert (`raise_alert`, kind `policy_rebuilt`) | no-alert row, success, adds-rows and body rows (an extra entry): 6 |
| CHK-M11-408 | a `bm.repositories` import added to the route | import-graph row: 1 |
| CHK-M11-409 | the 404 detail echoes the id and the exception name | 404 row: 1 |
| CHK-M11-411 | the `PolicyDeleted` mapping removed (500) | 409 row, canary sweep: 2 |
| CHK-M11-412 | M8's lock taken shared (`pg_advisory_xact_lock_shared`) | concurrency row (no waiter: the calls were not serialised): 1 |
| CHK-M11-413 | a second import of `reevaluate_scan` (in `services/jobs/scan_views.py`) | one-caller row: 1 |

CHK-M11-335 note: the brief expected the no-TOTP rows to turn red under `require_role("admin")`. They don't, because M2's `_gate` refuses a restricted principal (an admin without TOTP, or an admin session that is not TOTP-verified) under every factory unless `allow_restricted` is set. The API-token row and the sink-gate row are what tell `require_totp_session()` apart from `require_role("admin")`. CHK-M11-414 adds `allow_restricted=True`, and the no-TOTP rows go red.

### Acceptance (TASK-243: "Through the API on PostgreSQL: REQ-270 (1)–(5) and REQ-271 (1), (3) hold, each refusal row leaving no `scan_result_reeval` row and no audit entry")

- REQ-270 (1): CHK-M11-200.
- REQ-270 (2): CHK-M11-201, -202, -207.
- REQ-270 (3): CHK-M11-203.
- REQ-270 (4): CHK-M11-205.
- REQ-270 (5): CHK-M11-209.
- REQ-271 (1): CHK-M11-413 (route part).
- REQ-271 (3): CHK-M11-206.
- Also covered: REQ-271 (2) on this route (the spy in CHK-M11-200), #147 (b) (CHK-M11-204), REQ-272 (4) (CHK-M11-208) and G6.

### Notes

- In run 2, an assertion failure printed fixture tokens (test-only tokens on a throwaway container) into `/root/m11c/logs/r243b.log`. Every `bs[uaek]_` string in my logs has since been masked. `run.sh` now uses `--tb=short` and masks tokens after each run.
- Shared fixtures: none edited.

## TASK-240 (scan views service)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-155 | `test_scan_views_pg.py::test_counts_and_score_per_host` | PASS | Host A has PASS, a FAIL re-evaluated to PASS, a FAIL and an ERROR in the original, and PASS plus Not run in its retry: (3, 1, 1, 1, 0.75). An all-ERROR host gives (0, 0, 6, 0, None), a queued host (0, 0, 0, 6, None), and a host whose higher `reeval_id` is FAIL (its later-dated row PASS) gives (0, 6, 0, 0, 0.0). There are 4 hosts: the retry joins A, with its jobs listed original first. |
| CHK-M11-156 | `::test_fifty_random_scans_agree_with_m8` (seed 24311) | PASS | Over 50 `random_scan`s, every host's `HostScore` equals M8's `scores.scan_host_scores()`, with the same agent set. At least 50 hosts were compared. |
| CHK-M11-157 | `::test_hosts_by_hostname_then_agent_id_and_jobs_original_first` | PASS | Hostnames `aa`, 3× `mm`, `zz` come back in hostname order, ties by `agent_id`. Two retries were created a day *before* their originals and are still listed second, with `retry_of` = the original. Job state and times equal the stored row. |
| CHK-M11-158 | `::test_state_is_scan_state_as_stored[*]` (4) | PASS | Stored `running` with every job completed; `completed` with a running and a queued job; `queued` with failed and expired jobs; `partial` with completed jobs. In each case the detail and the list return the stored state. |
| CHK-M11-159 | `::test_scan_of_a_deleted_policy_is_returned`, `::test_late_result_then_reevaluation_change_the_next_answer` | PASS | A soft-deleted policy's scan is returned by the detail (with the policy name and counts) and by the list. A late result changes the next answer from (0, 1, 0, 1, 0.0) to (1, 1, 0, 0, 0.5), and a re-evaluation then gives (2, 0, 0, 0, 1.0). |
| CHK-M11-160 | `::test_detail_reads_one_read_only_snapshot`, `::test_service_runs_select_only` | PASS | A hook inside the service's transaction, after the jobs read, commits a result and a re-evaluation from another session. The counts read still gives the pre-commit (0, 1, 0, 1, 0.0), and the next call sees both. The first statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`. Across detail, list and history, every statement comes from `bitscan_app` and is SELECT, WITH or SET only. |
| CHK-M11-161 | `::test_unknown_scan_and_unknown_agent`, `::test_agent_history_three_of_five_newest_first[online,decommissioned]` | PASS | An unknown scan raises `ScanNotFound` and an unknown agent `AgentNotFound`. An agent in 3 of 5 scans gets exactly those, newest first. `limit=1` visits each once. A scan whose request names the agent but whose resolved target does not hold it is not listed. A decommissioned agent gets the same history. |
| CHK-M11-162 | `::test_list_scans_filters_keyset_and_anchor_gone`, `::test_detail_target_is_the_request_without_resolved_agents[agents,tags,all]` | PASS | Each filter alone and all together (policy, agent, state, `created_after` inclusive, `created_before` exclusive) equal the oracle, newest first with the `scan_id` tie. A `limit=2` keyset walk visits every scan once. A deleted anchor raises `AnchorGone`, re-exported by the service. The detail target equals the request, has no `resolved_agents`, and `resolved_count` and `target_kind` are right. |

### Plants (throwaway copies, each deleted after its row; plants file `/root/m11c/plants-240.json`, log `/root/m11c/plants-240.out.jsonl`)

9 plants: 9 red, 0 survived. Each one ran the whole file (`-n 4`), and every expected test failed for the planted reason.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-332 | the score counts ERROR as FAIL | counts and score; 50-scan agreement: 2 |
| CHK-M11-333 | the detail re-derives the state from the jobs | `state[running-…]`, `state[partial-…]`: 2 |
| CHK-M11-415 | `read_only_snapshot` removed from `scan_detail` | snapshot row (the late commit was seen): 1 |
| CHK-M11-416 | `agent_exists` leaves out decommissioned agents (in `scan_reads`) | `history[decommissioned]`: 1 |
| CHK-M11-417 | the `AgentNotFound` check removed | unknown agent: 1 |
| CHK-M11-418 | hosts ordered by `agent_id` only | host order: 1 |
| CHK-M11-419 | hosts grouped by job, so a retry is not joined to its host | host order; counts and score: 2 |
| CHK-M11-420 | the detail read filters out deleted policies (in `scan_reads`) | deleted policy: 1 |
| CHK-M11-421 | the detail target carries `resolved_agents` | target rows ×3: 3 |

### Acceptance (TASK-240: "REQ-265 (1), (2), (4), (5) and REQ-266 (1), (3) hold, and the scan state returned equals `scan.state` even when a derivation would differ")

- REQ-265 (1): CHK-M11-155.
- REQ-265 (2): CHK-M11-156.
- REQ-265 (4) and (5): CHK-M11-159.
- REQ-266 (1) and (3): CHK-M11-161.
- Stored state: CHK-M11-158.
- Also covered: the one-snapshot read (CHK-M11-160), SELECT only (REQ-264 (5) at service level), host and job order (CHK-M11-157), and the list filters, keyset, `AnchorGone` and target (CHK-M11-162).

### Notes

- `_hosts` skips a unit made only of retries. Under M9's invariants every retry has an original for the same agent, so that branch cannot occur in a valid database. No test reaches it, and none is needed.
- REQ-265 (3) (the 404 and the non-hyphenated 400), REQ-265 (6) and REQ-266 (2) and (4) are route rows, for TASK-244 (TP-M11-12).

## TASK-242 (retention service)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-171 | `test_retention_pg.py::test_locked_scans_at_the_head_do_not_stall_the_step` | PASS | **Lead's row.** 101 scans (`SCAN_CHUNK` + 1) are the oldest, and one session holds M8's re-evaluation lock on all of them; 50 deletable scans sit behind them. One run (a) ends inside the 120 s bound with `chunks` = 1, within ⌈151/100⌉ = 2; (b) deletes all 50; (c) leaves the 101 locked scans and the young scan. After release, the next run deletes the 101. Bound note: `chunks` counts committed transactions that deleted rows, so the bound is the number of chunks, with no extra probe chunk. |
| CHK-M11-175, -180, -192 | `::test_one_run_deletes_exactly_the_expired_rows` | PASS | One run over `aged_world` leaves exactly the spec's survivors for every rule. For the old and past scans, no rows remain anywhere (jobs, results in two partitions, re-evaluations). The 399-day scan and the scan at exactly 400 days are whole. The `NEVER_DELETED` checksums are unchanged (G2: `os_info`, `agent_package`). Per step, `(deleted, skipped)`: scans (2, None), inventory jobs (2, None), snapshots (2, None), requests (2, None), tokens (3, None), audit (0, None, no cursor), packages (2, None). |
| CHK-M11-176 | `::test_every_statement_as_bitscan_retention` | PASS | Every statement of a full run, more than 20 of them including the audit step, comes from login role `bitscan_retention`. The run is given only the retention pool. |
| CHK-M11-177 | `::test_fault_in_the_second_scans_chunk`, `::test_fault_in_the_second_inventory_chunk` | PASS | **Scans:** 150 expired scans, and the second chunk raises after its delete. The first chunk's 100 stay deleted; the step reports `(100, "failed")`; the snapshot step still runs. The log record is exactly `{step: scans, exc_type: RuntimeError}`, without the exception text. The next run deletes the remaining 50. **Inventory:** 2,500 jobs, and the second chunk raises. 1,000 stay deleted and 1,500 remain, so each dated step also uses one transaction per chunk. |
| CHK-M11-178 | `::test_one_run_deletes_exactly_the_expired_rows`, `::test_a_live_api_token_does_not_skip_the_tokens_step` | PASS | **Lead's row, service level.** With a live API token expiring in 300 days present, the tokens step runs and deletes 3: the token expired 91 days ago, a revoked one also 91 days ago, and the old one. The 89-day, revoked-not-expired and live tokens stay, as does the pending request. |
| CHK-M11-179 | `::test_unreferenced_package_pruned_and_stored_again` | PASS | The unreferenced package is pruned and the referenced one kept. An M3 `ingest` of the same name, version and architecture afterwards stores the package again with its `agent_package` row. |
| CHK-M11-181 | `::test_chunks` | PASS | 250 expired scans take 3 chunks, and 2,500 inventory jobs take 3 chunks |
| CHK-M11-182, -183, -187 | `::test_audit_prefix_checkpoint_and_chain` | PASS | Entries in order: 10 expired, 5 recent, 1 expired. The run deletes 10 in one chunk. One checkpoint: actor `system`, target null, detail exactly `{last_deleted_id: id 10, last_deleted_row_hash: its stored hash, deleted: 10}`. Its id is above every other id. The expired entry after the recent ones stays. `verify_chain()` is OK. The checkpoint INSERT comes before the DELETE (statement spy). Wake ran once, after commit: the checkpoint was visible from another session. A second run deletes nothing and writes no checkpoint. |
| CHK-M11-184 | `::test_fault_in_the_audit_delete_leaves_no_checkpoint[raise, count_mismatch]` | PASS | When the delete raises, or deletes one row more than the checkpoint counted, both the checkpoint and the delete roll back. Every entry stays, there is no checkpoint, the chain verifies, wake is never called, the step is `failed`, and packages still run. |
| CHK-M11-185 | `::test_audit_capped_at_the_shipper_cursor` | PASS | Nothing is deleted while `shipped_through()` is None. With the cursor on the third entry, exactly 3 are deleted. The chain verifies. |
| CHK-M11-186 | `::test_25000_entries_three_chunks_three_checkpoints` | PASS | 25,000 entries take 3 chunks with 3 checkpoints (10,000, 10,000 and 5,000). Each `last_deleted_id` is the last id of its chunk. Only the 3 checkpoints remain, and M1's verifier accepts the chain. |
| CHK-M11-188 | `::test_clock_doubt[1h-ahead, 1h-behind, 4min-ahead]`, `::test_a_failing_clock_check_propagates` | PASS | With the manager clock 1 h ahead or behind, nothing is deleted at all (audit included). Every step is `clock_doubt`, with exactly one WARNING "retention refused: clock_doubt" and no "step done" lines. At 4 min ahead the run goes ahead. If `db_now` raises, the error propagates and nothing is deleted. The 5 min 0 s and 5 min 1 s boundary is TASK-236's CHK-M11-046. |
| CHK-M11-189 | `::test_a_future_row_skips_only_its_step[scans, inventory_jobs, snapshots, requests, tokens]` | PASS | A row dated 2 days ahead in each probe column, including the **token created 2 days ahead** (lead's row), sets that step to `future_rows` with 0 deleted. Every other step runs and deletes exactly its expired rows. |
| CHK-M11-190, -191 | `::test_no_ddl_no_other_writes_counts_only_logs` | PASS | No DDL, no UPDATE, and the only INSERT is into `audit_log`. Afterwards the audit log holds only `audit.checkpoint` entries. There is one "retention step done" record per step, in order, with exactly `{step, deleted, chunks, skipped}`. No OUT, ERR, EXEC or EXP canary, and no deleted scan or job id, appears in any log record (message or attributes). |
| CHK-M11-193 | `test_retention_race_pg.py::test_a_scan_under_reevaluation_is_skipped_then_deleted` | PASS | While another session holds M8's lock on one expired scan, the run deletes the other expired scan and leaves this one whole. After release, the next run deletes it. A re-evaluation of it afterwards raises `ScanNotFound`. |
| CHK-M11-194 | `::test_app_writers_during_the_audit_step_never_fork_the_chain` | PASS | Two app writers start inside the audit transaction, after the delete; the probe sees both parked on the chain lock. After the commit both append after the checkpoint. No entry is lost, and `verify_chain()` is OK. |
| CHK-M11-195 | `::test_upload_racing_the_package_prune_loses_nothing` | PASS | An upload's uncommitted `agent_package` row references an unreferenced package. The prune waits on it, the upload commits, and the prune's chunk fails and rolls back: the step is logged `failed` (seen in the log). The package and its reference stay. The next run prunes only the package that is still unreferenced. |

### Plants (throwaway copies; log `/root/m11t/logs/plants-242.jsonl`; plants `/root/m11t/plants-242.json`)

15 plants, 15 red, 0 survived, and no copy left.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-172 | the scans loop stops on the first chunk that deletes nothing | locked-head row (b) |
| P242-skipped-not-carried | each chunk asks for `SCAN_CHUNK` rows only (the stranding bug) | locked-head row |
| CHK-M11-349 | the audit prefix is not capped at the shipper's cursor | cursor row |
| CHK-M11-343 | audit rows deleted without a checkpoint | checkpoint and 25,000 rows (5 failed) |
| CHK-M11-347 | checkpoint after the delete (delete moved first, hash read before it) | statement-order assertion |
| P242-count-check-removed | count mismatch not refused | `[count_mismatch]` |
| P242-wake-removed | no wake after commit | checkpoint row |
| CHK-M11-353 | no clock check | `[1h-ahead]`, `[1h-behind]` |
| P242-future-check-removed | future-row probe skipped | all 5 future rows |
| CHK-M11-394 (service) | tokens probe back on `expires_at` (in `retention.py`) | live-token row, one-run row (6 failed) |
| P242-failure-not-isolated | a step failure re-raised | fault rows (5 failed) |
| CHK-M11-357 | scan ids logged | counts-only row |
| P242-log-exception-text | exception text added to the failure log | scans fault row (exact log record) |
| CHK-M11-355 (service) | re-evaluation lock not tried | race -193 and the locked-head row |
| P242-one-tx-per-step | one transaction for a whole dated step | inventory fault row; added because chunk counts alone cannot show this |

### Acceptance (TASK-242: "Clock control on PostgreSQL with the retention pool: REQ-275 (1)–(6), REQ-276 (1)–(6) and REQ-278 (1), (2), (4) hold")

| Requirement | Parts | Rows |
| --- | --- | --- |
| REQ-275 | (1) | -175 |
| | (2) | -176 |
| | (3) | -177 |
| | (4) | -178 |
| | (5) | -179, -195 |
| | (6) | -180 |
| REQ-276 | (1) | -182 |
| | (2) | -183 |
| | (3) | -194 |
| | (4) | -184 |
| | (5) | -185 |
| | (6) | -186 |
| REQ-278 | (1) | -188, -189 |
| | (2) | -193, -171 |
| | (4) | -190 |

The lead's points:

| Point | Rows |
| --- | --- |
| Locked scans don't stall the step | -171 |
| No delete while the cursor is None | -185 |
| Count-mismatch rollback | -184 |
| 25,000 entries in 3 chunks, chain verifies | -186 |
| One clock-doubt warning; a failing clock check propagates | -188 |
| A failing step is logged by name and type, and the next step runs | -177 |

### Notes

- **Equivalent mutant, not planted:** removing `repo.lock_chain()` before `oldest()`. `append_entry` takes the same lock before the checkpoint insert, so a writer that commits between the read and the checkpoint appends only recent entries, which change neither the prefix nor the chain. The early lock is defence in depth. CHK-M11-194 shows the chain lock is held until commit.
- **Scope:** stopping the scheduler mid-run (CHK-M11-197) is tested with the wiring, in TASK-245. The #151 timing (CHK-M11-387) is for the gate.

## TASK-241 (results service)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-165 | `test_results_read_pg.py::test_results_page_signature_takes_the_role_only`, `::test_no_output_keys_or_canary_for_a_viewer_or_unknown_role[viewer,auditor,Admin,""]`, `::test_operator_and_admin_get_output[operator,admin]`, `::test_viewer_statement_never_reads_stdout_or_stderr` | PASS | Both service signatures take `role` and no token-kind parameter. Viewer and unknown roles, across 5 statuses × 2 agent values on every `limit=2` page, get exactly the 22 keys in #144 (a) order, `with_output` false, and no OUT or ERR byte. EXEC and EXP (catalog text) are present. Operator and admin get the 24 keys and the oracle items, with OUT and ERR. **The viewer's page and CSV statements name no `stdout` or `stderr`** (statement spy); the operator's statement selects `r.stdout`. |
| CHK-M11-166 | `::test_items_equal_the_oracle_for_a_viewer`, `::test_filters_alone_and_together[*]` (20), `::test_unknown_agent_filter_is_empty`, `::test_paging_visits_every_item_once[1,2,4,5,7,14,15,16]`, `::test_paging_with_a_filter` | PASS | The items equal the oracle exactly: p1 shows PASS "high" from the higher `reeval_id` against original FAIL; p3 is answered by the retry (`retry` true); p4 and every host-b plugin are Not run, named from `eval_spec`. `other-scan` never appears. 5 statuses × 4 host values equal the oracle subset, and an unknown agent gives an empty page. Paging visits every item once. `next_after` is set only when a further item exists: at limits 1, 5 and 15 (exact multiples of 15) the last page has no cursor. The NOT_RUN walk gives the 6 Not-run items. |
| CHK-M11-167 | `::test_csv_rows_equal_the_json_items[*]` (9), `::test_csv_escapes_and_quotes_output`, `::test_viewer_csv_has_no_output_column_or_canary` | PASS | For viewer, operator and admin, and the statuses all, FAIL and NOT_RUN: the header is exactly #146 (plus `stdout, stderr` for operator and admin), and each record equals its JSON item. Null is an empty cell, booleans are `true`/`false`, times are UTC with `Z` and equal the item's, and every text cell is escaped per TS §6.3. There is no BOM and the text ends in CRLF. `=1+2` becomes `'=1+2` and `@SUM(1)` becomes `'@SUM(1)`. Stdout with commas, quotes, LF and CRLF round-trips exactly. The viewer CSV has no output column and no OUT or ERR byte. |
| CHK-M11-168 | `::test_100000_rows_export`, `::test_over_the_cap_refused_before_any_text[one_over,over]` | PASS | 100,000 Not-run rows export: 100,001 records including the header, `csv_text` called once. At 100,001 and 100,005 rows, `TooManyRows` is raised and `csv_text` is **never called** (spy). The repository returned exactly 100,001 rows each time (spy), so the read is bounded. The exception holds no canary. |
| CHK-M11-169 | `::test_unknown_scan_raises_scan_not_found`, `::test_scan_without_jobs_is_an_empty_answer`, `::test_each_call_is_one_read_only_snapshot` | PASS | An unknown scan raises `ScanNotFound` for both calls, and it is the same class as `scan_views.ScanNotFound`. A scan with no jobs gives an empty page and a header-only CSV, not 404. For each call, the first `bitscan_app` statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`. Every statement is SET, SELECT or WITH, with no write verb. |
| CHK-M11-170 | `::test_no_canary_or_token_in_logs_or_exceptions` | PASS | caplog at DEBUG, with capture proven by a probe record, over pages and CSVs for 3 roles × 4 statuses, plus `ScanNotFound` and `TooManyRows`. No canary appears in any log record (message, args, every attribute). No canary appears in any exception or its chain. No `bitscan_manager.*` record other than the probe exists, so the service logs nothing. OUT and ERR appear only in the operator and admin answers. |

### Plants (throwaway copies, each deleted after its row; plants file `/root/m11c/plants-241.json`, log `/root/m11c/plants-241.out.jsonl`)

9 plants: 9 red, 0 survived. Each one ran the whole file (`-n 4`), and every expected test failed for the planted reason.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-334 | CSV cap removed | over-cap rows [one_over, over]: 2 |
| CHK-M11-422 | cap checked only after `csv_text` built the text | over-cap rows (spy: text built): 2 |
| CHK-M11-423 | export read unbounded (`max_rows=10**9`) | over-cap [over] (read 100,005): 1 |
| CHK-M11-424 | the viewer page reads `stdout`/`stderr` (`with_output=True` to the repository) but keeps the keys out of the items | viewer-statement row: 1, and only that row |
| CHK-M11-425 | `include_output` true for the viewer (in `results_view`) | viewer keys, viewer statement, oracle, paging, viewer CSV and more: 16 |
| CHK-M11-426 | `next_after` set when `len(rows) >= limit` | paging at limits 1, 5 and 15: 3 |
| CHK-M11-427 | `limit` rows read, not `limit + 1` | paging at every limit < 15, filtered paging: 7 |
| CHK-M11-428 | `read_only_snapshot` removed from `results_page` | snapshot row: 1 |
| CHK-M11-429 | `ScanNotFound` not raised by `results_csv` | unknown-scan row: 1 |

### Acceptance (TASK-241: "REQ-267 (1)–(4), REQ-268 (1), (2) and REQ-269 (2), (3) hold with the canary")

- REQ-267 (1): CHK-M11-166.
- REQ-267 (2): CHK-M11-166 (filters).
- REQ-267 (3): CHK-M11-166 (paging; cursors from another scan or filter set are the route's HMAC scope, TASK-244).
- REQ-267 (4): the 200-scan property agreement is TP-M11-04's `test_results_property_pg.py` on the same repository, re-run green here (1/1).
- REQ-268 (1): CHK-M11-165, -167, -170.
- REQ-268 (2): at service level, `role` alone decides on every call (CHK-M11-165, signature and roles). The demoted-API-token row is a route row (TP-M11-12, CHK-M11-223).
- REQ-269 (2): CHK-M11-167.
- REQ-269 (3): CHK-M11-168.
- Also covered: the read-only snapshot and SELECT only (CHK-M11-169), and the canary in logs and exceptions (CHK-M11-170).

### Notes

- The CSV time format is `YYYY-MM-DDTHH:MM:SS.ffffffZ`. The test asserts only RFC 3339 UTC with `Z` and value equality, as #146 (b) requires, not the digit count.
- CHK-M11-428 covers `results_page`. `results_csv` has its own snapshot call, which `test_each_call_is_one_read_only_snapshot` also checks.

## TASK-246 (Scans and Run scan; W3 batch evidence)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-265 | `npx vitest run src/screens/Scans.test.tsx` | PASS | 15/15 |
| CHK-M11-266 | `npx vitest run src/screens/RunScan.test.tsx` | PASS | 17/17 |
| CHK-M11-272 (Scans, Run scan) | the same files | PASS | plain-text rows green; no `script`/`img` nodes |
| CHK-M11-366 (screen half) | plant in a throwaway copy | PASS (red as required) | 1 failed / 15 |
| CHK-M11-432, -433, -438 | plants in a throwaway copy | PASS (red as required) | 1 failed / 17; 1 failed / 17; 1 failed / 15 |
| W3+W4 batch full run | `npx vitest run` | PASS | 741/741, 0 skipped |
| W3+W4 G12–G14, G16 | lint, typecheck, format:check, regen `cmp` | PASS | all exit 0; no diff |
| Flake observation | full run under load | NOT RUN as a gate (observation) | 2 M5 paging tests hit the 5 s default timeout once; 2.0–3.2 s alone; sent to main |

## TASK-247 (scan detail)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-267 | `npx vitest run src/screens/ScanDetail.test.tsx` | PASS | 19/19 |
| CHK-M11-272 (scan detail) | the same | PASS | plain-text row green |
| CHK-M11-361 | plant | PASS (red as required) | eslint exit 1 on the `fetch` line |
| CHK-M11-362 | plants (a) and (b) | PASS (red as required) | (a) 1 failed / 19; (b) eslint exit 1 (storage ban) |
| CHK-M11-375 (detail) | plant | PASS (red as required) | eslint exit 1; 1 failed / 19 |
| CHK-M11-434, -436 | plants | PASS (red as required) | 1 failed / 19; 4 failed / 19 |

## TASK-248 (results screen)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-268 | `npx vitest run src/screens/ScanResults.test.tsx` | PASS | 14/14 |
| CHK-M11-272 (results) | the same | PASS | plain-text rows green |
| CHK-M11-360 | plant | PASS (red as required) | eslint exit 1; 1 failed / 14 |
| CHK-M11-365 (screen half) | plant | PASS (red as required) | 2 failed / 14 |
| CHK-M11-375 (results), -376, -437 | plants | PASS (red as required) | eslint exit 1 + 1 failed; 1 failed; 1 failed (each / 14) |

## TASK-249 (schedules)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-269 (screen half) | `npx vitest run src/screens/Schedules.test.tsx` | PASS | 17/17 |
| CHK-M11-272 (schedules) | the same | PASS | plain-text row green |
| CHK-M11-435 | plant | PASS (red as required) | 4 failed / 17 |

## TASK-250 (host scan history)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-270 | `npx vitest run src/screens/HostScans.test.tsx src/screens/HostDetail.test.tsx` | PASS | 8/8 and 9/9 (existing HostDetail unchanged) |
| CHK-M11-272 (host scans) | the same | PASS | plain-text row green |

## TASK-256 (ScanTable and TargetPicker)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-273 | `npx vitest run src/components/TargetPicker.test.tsx` | PASS | 37/37 (with -274) |
| CHK-M11-274 | the same | PASS | round-trip and describe rows green |
| CHK-M11-275 | `npx vitest run src/components/ScanTable.test.tsx` | PASS | 5/5 |
| CHK-M11-375 (table, picker) | plants | PASS (red as required) | eslint exit 1 each; 3 and 2 tests red |
| CHK-M11-379 | plants (a), (b) | PASS (red as required) | 1 failed / 37; 4 failed / 54 |

## TASK-251 (routing and navigation)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-271 | `npx vitest run src/app/router.test.ts src/app/App.test.tsx src/screens/ProfileDetail.test.tsx` | PASS | 148/148, 44/44, 25/25 |
| CHK-M11-269 (viewer half), REQ-282 (3) | the App gating row | PASS | 0 requests per hash; no `scan-schedules` |
| CHK-M11-272 (session) | App `afterEach` leak check | PASS | no leak |
| CHK-M5-280 → CHK-M5-280 (M11) | PD-51 replacement | PASS | old → new above |
| CHK-M11-366 (shell, profile) | plants (b), (c), (d) | PASS (red as required) | 1, 2 and 1 failed |
| CHK-M11-430, -431 | plants | PASS (red as required) | 15 and 8 failed / 148 |

## TASK-257 (vitest testTimeout)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-257 run 1 | `npx vitest run` (testTimeout 20000) | PASS | 741/741; slowest 3673 ms |
| TASK-257 run 2 | `npx vitest run` (testTimeout 20000) | PASS | 741/741; slowest 3089 ms |
| TASK-257 gates | lint, typecheck, prettier on `vite.config.ts` | PASS | all exit 0 |
| TASK-257 plant (5000) | 3 full runs in a throwaway copy | PASS (the setting shown to matter) | the M5 paging tests reached 4939 and 4784 ms of 5000; observed timing out in the earlier W3 run |

## TASK-258 (unrecognised stored target fails closed)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-258 (CHK-M11-274 extended) | `npx vitest run src/components/TargetPicker.test.tsx` | PASS | 48/48 |
| TASK-258 (CHK-M11-269 extended) | `npx vitest run src/screens/Schedules.test.tsx` | PASS | 20/20 |
| TASK-258 affected | RunScan, App | PASS | 17/17, 44/44 |
| CHK-M11-439 | plant | PASS (red as required) | 12 failed / 68 |
| CHK-M11-440 | plant | PASS (red as required) | 2 failed / 68 |

### r1 re-run (2026-11-08): punctuation only

The r1 change (reviewer nit): a full stop now follows `<strong>Unknown target</strong>`, outside the `<strong>` (`TargetPicker.tsx` L179). The `<strong>` text is still exactly "Unknown target". No behaviour changes and no test was edited.

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-258 r1 | `npx vitest run src/components/TargetPicker.test.tsx src/screens/Schedules.test.tsx` | PASS | 68/68 (48 + 20), 0 failed, 0 skipped |
| TASK-258 r1 gates | lint, typecheck, format:check | PASS | all exit 0 |

Verdict r1: **PASS**.

## TASK-245 (retention wiring)

### Report rows (for tests/m11/report.md)

`W` = `manager/tests/test_retention_wiring.py`, `L` = `manager/tests/test_serve_retention_linux.py`.

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-196 | `W::test_four_jobs_and_retention_ten_minutes_after_start_on_its_row`, `::test_a_changed_retention_row_is_the_interval[60,43200,86400]`, `::test_a_missing_retention_row_gives_86400`, `::test_an_unreadable_database_gives_86400_and_logs_the_type_only`, `::test_the_real_scheduler_holds_the_retention_job`, `::test_the_retention_row_is_read_at_start_up_from_the_database` | PASS | The job set is exactly `{inventory, offline_sweep, scan_schedules, retention}`, four jobs. Retention runs `run_retention`; its interval is the row (3,600; 60, 43,200 and 86,400 at both CHECK ends) and `misfire_grace_time` equals it; `max_instances` 1, `coalesce` true; next run start + 10 min, while the other three run at start. The row is read once, at start-up, on the app pool, and the retention pool is untouched. Missing row → 86,400; read failure → 86,400 with the seeded 21,600, 60 and 30, logged as `{exc_type: ConnectionError}` only, no canary. The real `BackgroundScheduler` holds the same job. On PostgreSQL: seeded row 86,400, owner-changed row 43,200, deleted row 86,400. |
| CHK-M11-196 (later steps) | `W::test_a_failing_step_leaves_the_later_steps_run_through_the_runner` | PASS | REQ-277 (1), (4) through `SchedulerRunner.run_retention()` on PostgreSQL: the snapshots step raises. Its rows stay; scans, inventory jobs, requests (2), tokens (3) and packages (2) are deleted. One `retention step failed` record `{step: snapshots, exc_type: RuntimeError}`, no `scheduler run failed`, no canary. |
| CHK-M11-196 (serve, lead's row (a)) | `L::test_serve_schedules_four_jobs_with_retention_from_its_row[plain]` | PASS | The real serve: after `start()` the scheduler holds exactly the four jobs, each `max_instances` 1. Retention: the interval is the owner-changed row (43,200, misfire 43,200), `coalesce` true, next run start + 600 to 630 s; no retention run during the test. |
| CHK-M11-196 (runner wiring) | `W::test_run_retention_gets_the_retention_pool_the_clock_cursor_and_wake`, `::test_a_failing_retention_run_is_logged_by_type_and_the_next_run_happens`, `::test_unconfigured_run_retention_does_nothing` | PASS | The run's transaction opens on the retention pool (retention 1, app 0); `now` is the clock's; `shipped_through` is the given function itself; `wake` is the shipper's. A run that raises gives one `{job: retention, exc_type: ValueError}`, `exc_info` none, no canary, and the next run happens. |
| CHK-M11-197 | `W::test_stop_during_a_retention_run_gives_up_at_its_next_transaction`, `W::test_stop_during_a_real_retention_run_gives_up_at_the_next_transaction`, `L::test_sigterm_during_a_retention_run_waits_then_closes_the_retention_pool` | PASS | **Unit, real scheduler:** stop() between two transactions sets the flag and waits; the next transaction raises `SchedulerStopping` without reaching the retention pool (opened 1); stop() returns after the run ended; one `{job: retention, exc_type: SchedulerStopping}`; no run after. **PostgreSQL, real `run_retention`:** stop() during the scans step's first chunk. That chunk commits (2 scans); each of the six later steps logs `{step, exc_type: SchedulerStopping}` once; no `bitscan_retention` statement after the flag; every other row stays; stop() returns in under 10 s. **Serve:** SIGTERM during a run → the run ends after the signal, then `pool closed bitscan_retention`, then the app pool; exit 0. Exactly one retention failure, `SchedulerStopping`, with only job and type; no step ran; no run started after the signal; no `PoolClosed`. |
| CHK-M11-198 | `L::test_serve_runs_retention_as_bitscan_retention`, `L::test_an_unusable_retention_dsn_file_fails_start_up[missing,directory,empty]` | PASS | Serve's retention run gets the pool named `bitscan_retention`. Its transaction's `current_user` is `bitscan_retention`, and while serve runs, `pg_stat_activity` shows a `bitscan_retention` session, gone after stop. The run deletes the `old` row and keeps the `inside` row for each of scans, inventory jobs, snapshots, requests and tokens, and prunes the unreferenced package. The aged audit prefix (3 entries) is deleted under one checkpoint with `last_deleted_id` = its last id, so the cap is the live shipper's cursor. All seven steps have `skipped` none. Seven retention log lines, each with only step, deleted, chunks, skipped and exc_type; no canary in the output (REQ-277 (4)). Pools open app, then retention, before the job set; close retention, then app, after `scheduler stopped`, with nothing after. An unusable file exits 2 before binding, with `serve: BITSCAN_RETENTION_DSN_FILE: cannot read the file it points to` (missing, a directory) or `…: file is empty`. The output has no DSN or password of either role and no traceback. |
| CHK-M11-199 | `W::test_shipped_through_is_none_before_anything_is_queued`, `::…_is_the_last_id_written_to_the_disk_queue`, `::…_moves_one_batch_at_a_time`, `::…_stays_when_the_disk_queue_refuses`, `::…_after_a_restart_is_the_saved_cursor`, `::…_is_read_only`, `W::test_the_shippers_cursor_caps_the_audit_delete` | PASS | None when fresh, after an empty read and while the database is down. 3 once 1–3 are queued with the sink down (nothing delivered); still 3 after delivery; 5 after 4–5. 500, then 600, for a 600-entry backlog. None while the disk queue refuses, 2 after. 3 after a restart, before any cycle. Five calls change nothing: queue folder bytes and mtimes, depth, tail reads, sink sends, gate, wake. **As the cap, on PostgreSQL through the real shipper and runner:** the shipper has queued 3 expired entries, and 2 more expired entries lie above its cursor. The run deletes exactly the 3, with checkpoint `last_deleted_id` = the cursor and `deleted` 3. After the shipper queues the rest, the next run deletes the 2; `verify_chain` OK. |
| CHK-M11-450 | `W::test_build_runtime_always_gives_the_runner_the_retention_pool_and_cursor`, `::test_no_variable_toggles_the_retention_job`, `::test_no_setting_toggles_the_retention_job[4 bodies]`, `::test_no_route_touches_retention_or_the_scheduler`, `::test_patch_settings_refuses_a_retention_field`, `L::test_serve_schedules_four_jobs_with_retention_from_its_row[toggles]` | PASS | **Lead's row (b).** `build_runtime` has no `if`, conditional or `try`. Its one `SchedulerRunner` gets `retention_db` (the `AppDatabase(bounded_dsn(config.retention_dsn), …, name='bitscan_retention')`) and `shipper.shipped_through`, and `ServeLifecycle` gets the same pool. Neither module reads `os.environ` or `getenv`. `load_serve_config` reads exactly the ten TS §8.6 names. `SettingsBody` and `SettingsPatch` have no retention field, and the patch refuses `retention_interval_s`, `retention_enabled`, `retention` and `scheduler_jobs`. No `openapi.json` path or operation names retention or the scheduler. Through the API, PATCH with a retention field is 400 `invalid_request`, settings unchanged. The real serve with four made-up switches (`BITSCAN_RETENTION_DISABLED=1`, etc.) still has the four jobs. |
| CHK-M11-451 | `W::test_serve_build_runtime_runs_retention_on_a_bitscan_retention_pool`, `W::test_every_statement_of_a_runner_run_is_bitscan_retention` | PASS | **Lead's row (d).** Serve's own `build_runtime`, in-process: the retention pool is not the app pool. It is named `bitscan_retention`, with min 0 and max 1, and its DSN's user is `bitscan_retention` (asserted, never printed). The runner wraps exactly that pool, and the app pool separately. The runner's cursor equals the runtime shipper's `shipped_through`. `SELECT current_user` on it gives `bitscan_retention`. A statement spy over a whole run through that runner sees only `bitscan_retention` (more than 10 statements), and the expired rows go. |
| CHK-M11-452 | `W::test_one_retention_argument_without_the_other_raises[retention_db,shipped_through]` | PASS | **Lead's row (c).** Either one alone raises `ValueError` ("…go together"). |
| CHK-M11-453 | `W::test_slow_retention_runs_never_overlap` | PASS | **Lead's row (e), one at a time:** a real scheduler with a 1 s interval and 1.6 s runs (first run moved to start): peak 1 and at least 2 runs. |
| CHK-M11-454 | `L::test_a_refused_retention_login_is_logged_by_type_only` | PASS | The retention DSN carries a wrong password (a canary). Serve still starts; the run fails as `{job: retention, exc_type: DatabaseUnavailable}` with nothing else; SIGTERM exits 0; the output has neither the canary nor the DSN, and no traceback. |
| CHK-M11-342 | plants CHK-M11-342 and -342b below | PASS (plant red) | Retention through the app pool, in serve or in the runner, turns `W` and `L` red. |
| CHK-M11-356 | plants CHK-M11-356 and -356b below | PASS (plant red) | Retention not scheduled, in serve (the brief's plant) or in the runner, turns `L` (a) and `W` red. |

#### PD-51: earlier checks replaced by requirement, old → new

| Old check | File and lines | New | Result |
| --- | --- | --- | --- |
| CHK-M3-233 / CHK-M9-219 (stop record: one "pool closed") | `test_serve_scheduler_linux.py` L441–L451 | Two "pool closed" events, both after the single "scheduler stopping" and after the running sweep ended; nothing after the last. The pool names and order (retention, then app) are CHK-M11-198 in `L`. | PASS in run 4 (`test_sigterm_waits_for_the_running_sweep_and_nothing_runs_after_close`) |
| CHK-M9-218 (job set, from CHK-M3-230) | `test_scheduler_runner.py` L210, L235 | Unchanged for the three-argument runner (docstring updated); the four-job row is CHK-M11-196, plus `W::test_without_the_retention_pool_three_jobs_and_no_retention_read` (and the retention row is not read). | PASS in runs 1 and 4 |
| CHK-M9-219 (failure job names) | `test_serve_scheduler_linux.py` L461, `traced` L395–L399 | Unchanged: retention first runs at + 10 min, after any of these serve runs end. | PASS in run 4 |
| TASK-232's M11 query-parameter sets | `test_invariants_m3.py` L114–L312 | Unchanged by this task. | PASS in run 4 |

### Plants (throwaway copies; plants `/root/m11t/plants-245.json` from `m11t-scripts/tmp/mk_plants_245.py`; log `/root/m11t/logs/plants-245.jsonl`)

21 of 21 red. None missing an expected test. No copy was left (`/root/m11t/mut-*`: 0), and the four product files' hashes are unchanged.

| Plant | Change | Red tests (all expected) |
| --- | --- | --- |
| CHK-M11-356 | serve: `SchedulerRunner(db, clock, shipper.wake)`, without the retention arguments (the brief's plant) | `L::…four_jobs…[plain,toggles]`, `W::test_build_runtime_always…`, `W::test_serve_build_runtime…` (4) |
| CHK-M11-356b | runner: the retention job never appended (`if False:`) | `W::four_jobs`, `W::real_scheduler`, `L::four_jobs` ×2 (4) |
| CHK-M11-342 | serve: `retention_db=db` (the app pool) | `W::build_runtime_always`, `W::serve_build_runtime`, `L::runs_retention_as_bitscan_retention` (3) |
| CHK-M11-342b | runner: `run_retention(self._db, …)` | `W::run_retention_gets…`, `W::every_statement…bitscan_retention`, `L::runs_retention…` (3) |
| P245-delay-0 | `RETENTION_DELAY = timedelta(0)` | four_jobs, changed_row ×3, unreadable, real_scheduler, `L::four_jobs` ×2 (8) |
| P245-delay-9min | `RETENTION_DELAY = timedelta(minutes=9)` (boundary) | four_jobs, real_scheduler (2) |
| P245-fallback-86399 | seeded fallback 86,399 | missing_row, unreadable, PG row read (3) |
| P245-row-ignored | retention interval forced to the seeded value | four_jobs, changed_row [60, 43200], real_scheduler, PG row read, `L::four_jobs` ×2 (7; changed_row[86400] rightly green) |
| P245-max-instances-2 | retention `max_instances=2` | four_jobs, real_scheduler, slow_never_overlap, `L::four_jobs` ×2 (5) |
| CHK-M11-197-unwrapped | retention pool not behind the stop flag | unit stop, PG real stop, build_runtime, `L::sigterm` (4) |
| P245-no-valueerror | the pair check removed | both `one_retention_argument…` (2) |
| P245-close-after-app | retention pool closed after the app pool | lifecycle, `L::four_jobs` ×2 (3) |
| P245-no-close | retention pool never closed | lifecycle, `L::four_jobs` ×2 (3) |
| P245-no-open | retention pool never opened | lifecycle, `L::runs_retention…` (2) |
| P245-name-app | pool named `bitscan_app` | build_runtime_always, serve_build_runtime, `L::four_jobs` ×2 (4) |
| P245-cap-not-shippers | serve passes `shipped_through=lambda: 2**62` (#150 (d) cap bypassed) | build_runtime_always, serve_build_runtime (2) |
| CHK-M11-199-zero | `shipped_through` returns 0 instead of None | none_before_queued, stays_when_disk_queue_refuses (2) |
| CHK-M11-199-writes | `shipped_through` saves the state file | read_only (1) |
| CHK-M11-199-wakes | `shipped_through` wakes the shipper | read_only (1) |
| P245-unguarded | `run_retention` without `_guarded` | failing_run_logged, unit stop, `L::sigterm` (3) |
| P245-wake-none | the run gets `wake=None` | run_retention_gets… (1) |

### Acceptance (TASK-245: "REQ-277 (1)-(4) hold with a clock-controlled scheduler and a real `serve` in WSL, and the M3 and M9 scheduler suites pass except the PD-51 job-set rows")

| Criterion | Met | Rows |
| --- | --- | --- |
| REQ-277 (1): four jobs; the interval is the row; an exception in one step leaves the later steps run | yes | CHK-M11-196 (all four rows), -453 |
| REQ-277 (2): stop() during a run gives up at its next transaction and returns | yes | CHK-M11-197 (unit, PostgreSQL, serve) |
| REQ-277 (3): serve opens the pool from `BITSCAN_RETENTION_DSN_FILE` and closes it at stop; a missing file fails start-up (M2) | yes | CHK-M11-198, -451, -454 |
| REQ-277 (4): retention log lines hold step names, counts and exception types only | yes | CHK-M11-196 (later steps), -198 (serve log lines), -454 |
| REQ-275 (2): every retention statement as `bitscan_retention`, never the app pool | yes | CHK-M11-451, -198; plants CHK-M11-342, -342b |
| #150 (d): the cap is the shipper's cursor, read-only | yes | CHK-M11-199; plant P245-cap-not-shippers |
| Lead's rows (a)-(e) | yes | (a) CHK-M11-196 serve, plant CHK-M11-356; (b) CHK-M11-450; (c) CHK-M11-452; (d) CHK-M11-451, -198; (e) CHK-M11-196, -453 |
| M3 and M9 scheduler suites pass, except the PD-51 rows | yes | run 4 (304/304), PD-51 table |
| G41 after the `serve` wiring change | yes | 23/23 rows |

### Notes

- **White-box reads, kept small:** `runner._stopping` (only to release a run once stop() set the flag), `runner._scheduler`, `lifecycle._scheduler` and `_retention_db`, `pool._pool` and `_dsn` (asserted, never printed), `shipper._queue` and `_wake` (the read-only row).
- **For the reviewer:** the interval read is all-or-nothing (`start()` reads the three rows in one try). One failing read gives the seeded values for all three, as M3 did for two. That matches REQ-277's "86,400 s if it cannot be read" and is tested.
- **Not in this task:** the README walks (`test_readme_*_walk_linux.py`) also start serve. They were not re-run here, because TASK-252 rewrites the README under PD-51 and they belong to that walk. The full suite runs at the wave end.
- `deploy/tests/check_manager_host.sh` and `e2e/m6/*` were already modified in the tree; I did not touch them.

## TASK-244 (read routes)

### Report rows (for tests/m11/report.md)

`A` = `manager/tests/test_scan_views_api_pg.py`, `B` = `manager/tests/test_results_api_pg.py`, `C` = `manager/tests/test_m11_contract_api_pg.py`.

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-213 | `A::test_each_filter_alone_and_together_in_order`, `::test_the_scan_item_body`, `::test_limit_2_paging_visits_every_scan_once`, `::test_default_limit_is_50` | PASS | **Data:** two policies, three hosts, eight scans in four states over two days with overlapping targets, including two at one instant. **Filters:** each filter alone (policy, agent, two states, after, before) and all five together give exactly the expected scans, newest first by `created_at` then `scan_id`. `created_after` is inclusive and `created_before` exclusive at the same instant, also when written as `+08:00` and `-05:00`. **Items:** item keys exactly #145 (a); state, target kind and resolved count as stored. **Paging:** `limit=2` visits every scan once, also under `agent_id`. 51 scans give 50 + cursor, then 1 + none; `limit=500` gives 51. |
| CHK-M11-214 | `A::test_every_role_and_token_kind_reads_all_five[6]`; `C::test_reads_refuse_missing_wrong_group_and_revoked_tokens`, `C::test_reads_answer_after_auth_for_any_role` | PASS | Viewer, operator and admin, each with a session and with an API token, get 200 on all five reads of a real scan; the CSV comes back as `text/csv`. No token, a revoked token, `bsa_` and `bse_` get 401 on all five (C). |
| CHK-M11-215 | `A::test_bad_cursors_are_400`, `::test_query_boundaries[8]`, `C::test_invalid_query_values_are_400` | PASS | Each of these is 400 `invalid_request` "Invalid request: query.cursor": a tampered cursor (flipped MAC byte, extra character); a cursor from other filters (policy, none, state, agent); a cursor from `/agents/{id}/scans` used on `/scans` and back; and a cursor whose anchor scan was deleted (AnchorGone). Unknown state, malformed `agent_id`, a date without an offset, and `limit` 0 and 501 are 400; 1 and 500 are 200. |
| CHK-M11-216 | `A::test_no_scan_item_holds_output_execute_or_expected[viewer:session, operator:session, admin:api]` | PASS | With the four canaries stored (stdout, stderr, execute, expected) in the REQ-267 world: no list, detail or host-history response holds a `resolved_agents`, `stdout`, `stderr`, `execute` or `expected` key at any depth, or any canary byte, for any role. |
| CHK-M11-217 | `A::test_the_reads_run_select_only`, `A::test_no_scan_table_is_written_and_tables_unchanged` | PASS | **Spy:** a statement spy over the five reads sees only reads (SELECT, WITH, SET) as `bitscan_app`, apart from M2's `UPDATE user_token SET last_used_at` (auth bookkeeping, not a read path); no INSERT, UPDATE, DELETE, MERGE or TRUNCATE on any scan table. **Checksums:** `scan`, `scan_job`, `scan_result` and `scan_result_reeval` are unchanged after every read for three roles (REQ-271 (2)). |
| CHK-M11-218 | `A::test_detail_body_keys_target_and_hosts`, `::test_detail_of_a_deleted_policy_and_a_late_change`, `::test_detail_unknown_404_and_malformed_400[4]`, `::test_detail_upper_case_id_is_the_same_scan` | PASS | **Body:** keys are exactly the scan item plus `target` and `hosts`. `target` is the request, `{agents: [...]}` with no `resolved_agents`. Hosts are ordered by hostname then `agent_id`, in database order. Host and job keys are exact; the original job comes first, then its retry (`retry_of`). **Counts:** host a has 2/1/1/1 with score 2/3 (a FAIL re-evaluated to PASS counts as PASS; the retry's FAIL counts); queued host b has 0/0/0/5, score null; host c has 3/1/1/0, score 0.75. **Changes:** after a late re-evaluation and a policy soft delete, the next answer gives c 4/0, score 1.0, and the scan is still returned. **Ids:** unknown 404 `not_found`; 32-hex, braced and `nope` 400; an upper-case id gives the same body. |
| CHK-M11-219 | `A::test_host_history`, `A::test_host_history_id_forms_as_the_other_agent_routes` | PASS | An agent in 3 of 5 scans gets exactly those 3, newest first, with no cursor. `limit=1` visits each once. After it is decommissioned, the same 3 come back. Unknown uuid, `nope` and `1` are 404 `not_found`. Each spelling of a real id (lower, upper, 32-hex, braced, `urn:uuid:`) gets the same status on `/agents/{id}/scans` as on `/agents/{id}`. |
| CHK-M11-220 | `B::test_limit_2_paging_visits_every_item_once`, `B::test_items_and_filters`, `B::test_results_cursor_scope` | PASS | 15 items: 3 hosts × 5 planned plugins. `limit=2` equals the unpaged list, by `agent_id` then position, under all 11 filter sets. Effective `result` PASS ("high", the higher `reeval_id`), `original_result` FAIL, `reevaluated_by` the admin. The retry item has `retry` true. A not-run item has both verdicts null. PASS, FAIL and ERROR give their subsets; NOT_RUN gives the 6 planned plugins without a result. Another scan's rows never appear. A cursor from another filter set, from another scan, or from `/scans` is 400 "Invalid request: query.cursor". |
| CHK-M11-221 | `B::test_unknown_and_malformed[json, csv]` | PASS | JSON and CSV alike. Unknown scan: 404 `not_found` as a problem, with no `Content-Disposition`. Malformed id: 400. `status` of `pass`, `NOTRUN` or `SKIPPED`: 400. `agent_id` of `nope` or 32-hex: 400. |
| CHK-M11-222 | `B::test_viewer_responses_hold_no_output[viewer:session, viewer:api]`, `B::test_operator_and_admin_pages_keep_stdout_and_stderr[4]` | PASS | **Viewer:** session and API token, every page (`limit=2`) of all 11 filter sets. Items carry exactly the 22 viewer keys, with no `stdout` or `stderr` key and no OUT or ERR byte. The CSV header is exactly #146 with no output columns, and the CSV has no OUT or ERR. **Lead's row:** for operator and admin, session and API, every item on every page has both keys. Host a's p0 has `(OUT, ERR)`; not-run items have null stdout. The CSV header is #146 + `stdout, stderr` and holds OUT and ERR. |
| CHK-M11-223 | `B::test_a_demoted_operator_loses_output_on_the_next_call` | PASS | The same operator API token gets output in JSON and CSV. After a demotion to viewer, the next call has neither the keys nor the bytes. After promotion back, it has them again. |
| CHK-M11-224 | `B::test_no_canary_or_token_in_logs_or_problems` | PASS | Viewer, operator API and admin sessions: paged JSON, CSV, a bad status, a garbage cursor and an unknown scan. At DEBUG, no log record (text and `__dict__`) and no problem body holds any of the four canaries or any caller token. |
| CHK-M11-225 | `B::test_csv_rows_equal_the_json_items[viewer:session, operator:session]`, `B::test_csv_headers_encoding_and_line_endings` | PASS | **Rows:** for all 11 filter sets, the CSV rows equal the JSON items in order. Each cell is checked per #146 (b): null empty, true/false, RFC 3339 UTC with µs and Z, M5 `escape_cell`. Both verdicts are included; `@SUM(1)` becomes `'@SUM(1)`. **Headers:** `text/csv; charset=utf-8`. `Content-Disposition: attachment; filename="scan-<id>-results.csv"`, with the canonical lower-case id even when asked in upper case. **Bytes:** no BOM, valid UTF-8, records end in CRLF, and the header line has no bare LF. Host c's stdout keeps its LF and CRLF inside the quoted cell. |
| CHK-M11-226 | `B::test_csv_cap_100000_rows[0, 1]` | PASS | 20 hosts × 5,000 planned plugins: exactly 100,000 data rows export (operator, with output columns). One more host (100,001 rows): viewer and operator API both get 400 `invalid_request` "Invalid request: more than 100000 rows; narrow the filters", as a problem body, with no CSV byte and no `Content-Disposition`. Narrowed by `agent_id`, it exports 5,000. |
| CHK-M11-227 | `A::test_csv_path_is_separate_and_headers_are_set` | PASS | `/scans/{id}.csv` is 400 and never CSV; `/results` is JSON. |
| CHK-M11-228 | `A::test_csv_path_is_separate_and_headers_are_set` | PASS | Eight responses (200 JSON, CSV, 400, 401, and the 404/400 problems) all carry HSTS (`max-age=`), CSP, `nosniff` and `no-referrer`. The problem body has type, title, status and detail. |
| CHK-M11-229 | run 4 / G6 row | PASS | `openapi.json` is byte-equal to a fresh export and unchanged from HEAD. |
| CHK-M11-455 | `A::test_upper_and_lower_case_agent_id_share_one_cursor_scope`, `B::test_results_cursor_scope` | PASS | **Reviewer's TASK-232 note.** A cursor made with the lower-case `agent_id` continues with the upper-case one, and back, giving the same next page, on `/scans` and on `/results`. |
| CHK-M11-456 | `A::test_one_instant_with_two_offsets_shares_a_time_scope` | PASS | **Lead's row.** A cursor made with `created_after` `…10:00:00Z` continues under `…18:00:00+08:00` with the same page. One µs later is another scope (400). |
| CHK-M11-457 | `A::test_a_scan_cursor_is_accepted_only_in_its_exact_form[8]`, `B::test_a_results_cursor_is_accepted_only_in_its_exact_form[10]` | PASS | **Lead's row.** These are signed for the right scope and still refused with 400 "Invalid request: query.cursor". Scan cursors: upper-case, 32-hex and braced ids, a number, null, an empty key, an extra element, a nested list. Results cursors: position 0, −1, 2^53, `true`, `"1"`, 1.5, null; an upper-case agent id; a short key; an extra element. `[scan_id]` and `[agent_id, 1]` are accepted. |
| CHK-M11-459 | `B::test_the_route_module_imports_no_repository` | PASS | REQ-272 (2). `scan_views.py` imports no `bitscan_manager.repositories` module and no `logging`. |

### Plants (throwaway copies; plants `/root/m11t/plants-244.json` from `m11t-scripts/tmp/mk_plants_244.py`; log `/root/m11t/logs/plants-244.jsonl`)

19 of 19 red. None missing an expected test. No copy was left (`/root/m11t/mut-*`: 0).

| Plant | Change | Red tests (all expected) |
| --- | --- | --- |
| CHK-M11-222-page | the lead's plant: `Page[ScanResultItem]` for an operator too (`if found.with_output:` → `if False:`) | `B::operator_and_admin…` ×4, `B::demoted…` (5) |
| CHK-M11-455-scans-raw | the lead's plant: the `/scans` scope from the raw `agent_id` string | `A::upper_and_lower_case…` (1) |
| CHK-M11-455-results-raw | the lead's plant: the results scope from the raw `agent_id` string | `B::results_cursor_scope` (1) |
| CHK-M11-456-time | the time in the scope as written (`str`), not as an instant | `A::one_instant_with_two_offsets…` (1) |
| CHK-M11-457-canonical | the cursor's id accepted in any form `UUID()` reads | scan `[key0]` (upper), `[key1]` (hex), `[key2]` (braced); results `[UPPER]` (4) |
| CHK-M11-457-pos-zero | position bound `0 <= position`, no upper bound | results `[0]`, `[9007199254740992]` (2) |
| CHK-M11-457-pos-bool | the `type(position) is int` check removed | results `[True]` (1) |
| CHK-M11-321 | the role taken from the token kind (an API token reads as operator) | `B::viewer…[viewer:api]`, `B::demoted…` (2) |
| CHK-M11-321-csv | the CSV route passes `"admin"` as the role | `B::viewer…` ×2, `B::demoted…` (3) |
| CHK-M11-322-route | viewer items carry `stdout: null`, `stderr: null` | `B::viewer…` ×2 (2) |
| CHK-M11-358 | the results route logs the items at DEBUG | `B::no_canary_or_token…`, `B::route_module_imports…` (2) |
| CHK-M11-359 | the route module imports `repositories.result_reads` | `B::route_module_imports…` (1) |
| CHK-M11-334 | the 100,000-row cap removed (in `results_read.py`) | `B::csv_cap[1]` (1) |
| CHK-M11-458-cap-text | the cap's detail text changed | `B::csv_cap[1]` (1) |
| CHK-M11-458-filename | the attachment name from the raw path id (upper case kept) | `B::csv_headers…` (1) |
| CHK-M11-458-anchor | AnchorGone not mapped (a deleted anchor gives 500) | `A::bad_cursors` (1) |
| CHK-M11-458-history-400 | a malformed `/agents/{id}/scans` id gives 400, not 404 | `A::host_history` (1) |
| CHK-M11-458-resolved | the detail's `target` keeps `resolved_agents` | `A::no_scan_item_holds…` ×3, `A::detail_body…` (4) |
| CHK-M11-458-write | a read path runs an UPDATE (in the scan views service) | `A::the_reads_run_select_only` (1) |

### Acceptance (TASK-244)

| Criterion | Met | Rows |
| --- | --- | --- |
| REQ-264 (1)–(5) | yes | CHK-M11-213 to -217, -455, -456, -457 |
| REQ-265 (3), (6) (and (4), (5) at the route) | yes | CHK-M11-218 |
| REQ-266 (1)–(4) | yes | CHK-M11-219, -214 |
| REQ-267 (3), (5) | yes | CHK-M11-220, -221, -455, -457 |
| REQ-268 (1)–(4) | yes | CHK-M11-222, -223, -224, -216 |
| REQ-269 (2)–(4) | yes | CHK-M11-225, -226, -221 |
| REQ-272 (2), (4) | yes | CHK-M11-459, -224, -217 |
| `openapi.json` unchanged (G6) | yes | CHK-M11-229 |
| The W1 501 rows replaced | yes | C, run 4 |

### Notes

- **Hostname collation** (above): the order follows the database collation, and the spec names none. Not a defect in my reading; it's for `main` to confirm with the owner if byte order was meant.
- The CSV route ignores a `cursor` parameter, as FastAPI ignores undeclared query parameters. The spec doesn't ask for it to be refused, so it isn't tested.
- **White-box reads:** the scope strings `scans:::::` and `scan_results:<id>::`, and `encode_cursor`, used only to sign the forged-form cursors.
- **#155 (CSV memory bound) is pending the user.** The cap rows test #146 as approved.

## TASK-253 (manager-operations runbook and changelog)

## TASK-253 TEST: PASS

Tester: tester-m11d, 2026-11-09. Docs (`deploy/runbooks/manager-operations.md` §1, §6, §7; `deploy/debian/changelog` `0.2.0~pre2-1`). REQ-289, REQ-290. Walked together with TASK-252 and TASK-259; full evidence in `work/reports/TASK-252-test.md`.

| Check | Result | Evidence (details in TASK-252-test.md) |
| --- | --- | --- |
| CHK-M11-384 | PASS | `dpkg-parsechangelog -S Version` → `0.2.0~pre2-1`. `check_debian_meta.py` OK 82/82, with CHK-M10-318 and -319 green. `dpkg --compare-versions`: `0.1.0-1` < `0.2.0~pre1-1` < `0.2.0~pre2-1` < `0.2.0-1` |
| CHK-M11-383 | PASS | Against a real WSL `serve`: §1's agent-version SQL runs. §6's journal grep on the serve log gives the seven `retention step done` lines in order, `skipped` null, shaped as the example line; the first run comes 10 min after start (602 s by the log); the checkpoint SQL runs (none on a young database). §7 checked statically against `release.yml` and `e2e.yml`; its `gh` and `git` commands were not run (the release owner's) |
| CHK-M11-382 | PASS | `check_runbook_text.py`: `OK 24 sh blocks, 0 findings`; no secret, token, DSN or process note |

The M6 harness indexes into §1 were not re-run here; impl-deploy checked them against the `ops_walk.sh` regex (blocks 0–2 unchanged), and the new block is fourth. They belong to the M11 gate's full run.

## TASK-259 (agent-install.md pre-release version)

## TASK-259 TEST: PASS

Tester: tester-m11d, 2026-11-09. Docs (`deploy/runbooks/agent-install.md` L7, L178). Walked with TASK-252 and TASK-253; evidence in `work/reports/TASK-252-test.md`.

| Check | Result | Evidence |
| --- | --- | --- |
| L7 and L178 agree with the changelog | PASS | L7 names `0.2.0~pre2-1`, the changelog's top entry (`dpkg-parsechangelog` → `0.2.0~pre2-1`). L178: `dpkg --compare-versions 0.1.0-1 lt 0.2.0~pre2-1` and `0.2.0~pre1-1 lt 0.2.0~pre2-1` are both true, so both hosts upgrade in place as written. The real package upgrade is G38 at the M11 gate |
| CHK-M11-382 (this file) | PASS | `check_runbook_text.py`: the same two known findings as before (L79, L123, the `bse_REPLACE…` placeholders), nothing new |
| No other `pre1` mention | PASS | grep: only L178's `0.1.0~pre1-1 sorts below 0.1.0-1` (unchanged) and the upgrade sentence |

## TASK-252 (README; the TP-M11-16 docs walk)

### Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-380 | M11 walk W2 (`m11t-scripts/walk/test_readme_m11_walk_linux.py`, 46 rows; rows `/root/m11t/logs/m11walk-rows.jsonl`) | PASS | **46/46 rows OK in W2** (W1: 45/46, the one bad row being my monotonic-clock measurement, since fixed). Rows are in the table below. |
| CHK-M11-381 | `docs_static.sh` greps; m9 walk PD-51 row | PASS | README L679: "Compliance jobs past their deadline end `partial`, `failed` or `completed`". No "not part of this version", "later version" or "three scheduled" in the README or either runbook. "four scheduled jobs" is stated. |
| CHK-M11-382 | `check_runbook_text.py` ×3; M11 walk last row | PASS | README `OK 11 sh blocks, 0 findings`; manager-operations.md `OK 24 sh blocks, 0 findings`; agent-install.md has only its 2 known placeholder findings (L79, L123, the `bse_REPLACE…` placeholders, present before TASK-259), nothing new. The m9 walk's no-process-note row (no TASK/REQ/CHK id, tester or M-number in the Scans section) passes in R3. No walk secret is in the serve log. |
| CHK-M11-383 | M11 walk §1 and §6 rows; static §7 review | PASS | **§1:** the runbook's own agent-version SQL (extracted from the block) runs and lists the fleet. **§6:** the runbook's journal grep pattern, applied to the serve log, gives exactly seven `retention step done` lines in the documented order with `skipped` null; a step line has exactly the keys and logger of the runbook's example line; the first run came 10 minutes after start-up (602 s by the log); the checkpoint SQL runs and returns none on a young database; young data stays. **§7** is static only: its `gh` and `git tag` commands were not run (the release owner's steps). `release.yml` matches the checklist: tag or manual dispatch with `version`; tag, `pyproject.toml` and changelog must agree; the double agent build is compared with `cmp`; SHA256SUMS written and checked; draft release only; refuses `~`. `e2e.yml` has `workflow_dispatch`. |
| CHK-M11-384 | `docs_static.sh` | PASS | `dpkg-parsechangelog -S Version` → `0.2.0~pre2-1` (Date `Sun, 08 Nov 2026 00:00:00 +0000`, `unstable`). `check_debian_meta.py --root .` → **OK 82/82**, including CHK-M10-318 (`version 0.2.0~pre2-1 is X.Y.Z-R or X.Y.Z~preN-R`, weekday and strictly decreasing dates) and CHK-M10-319 (`release.yml` refuses a `~` version, and the guard tests the `dpkg-parsechangelog` value). Version order: `0.1.0-1 lt 0.2.0~pre2-1`, `0.2.0~pre1-1 lt 0.2.0~pre2-1` and `0.2.0~pre2-1 lt 0.2.0-1` are all true. |
| CHK-M11-386 | `test_readme_m9_walk_linux.py` (R2 → R3) | PASS | **PD-51, old → new.** CHK-M9-285's README-text row ("results routes 'not part of this version yet'; keys 'in memory, for 24 hours'…; scan state lags") becomes: the Scans section has `### Scan results` and no "not part of this version"; the keys and lag clauses are kept unchanged. Every other row of the four README walks is unchanged (R3, 4/4). |
| CHK-M11-385 | see `work/reports/TASK-245-test.md` | PASS | Done in TASK-245 TEST (the PD-51 job-set and stop-record rows). |

#### The M11 walk rows (W2: 46/46 OK)

| Section | Rows (each with the expected answer taken from the text) |
| --- | --- |
| README "Listing scans" | **List:** `GET /scans` newest first with exactly the 12 documented item keys; `target_kind` `agents`, `resolved_count` 2. **Filters:** `agent_id` (upper case accepted), `state`, `created_after` (inclusive) and `created_before` (exclusive), each with an offset, and `policy_id`; 400 for a 32-hex `agent_id` and for a time without an offset. **Cursor:** one made under other filters is 400 `Invalid request: query.cursor`. **Host history:** `GET /agents/{id}/scans` lists the host's scans; an unknown host is 404. |
| README "One scan" | **Body:** the item plus `target` as requested (no resolved list) and `hosts`, by hostname, with the documented host and job keys. **Score:** A1 has 2/1/0/0, score 2/3 (passed ÷ (passed + failed)); A2 has 1/0/0/2, score 1.0, with `not_run` counting the checks with no result. **Ids:** unknown 404, not hyphenated 400. **Deleted profile:** a scan of a profile deleted later is still returned. |
| README "Results" | **Items:** one per check of each host's job, by `agent_id` then place, with exactly the 22 documented keys for a viewer and no `stdout`/`stderr`. **Not run:** `result` null and the result fields null. **Output:** stdout and stderr for an operator session and an admin API token. **Filters:** PASS 3, FAIL 1, ERROR 0, NOT_RUN 2; `status=pass` is 400. |
| README "CSV export" | **Response:** `text/csv; charset=utf-8`, no BOM, CRLF, `attachment; filename="scan-<id>-results.csv"`. **Columns:** exactly the 17 listed for a viewer; operator gets `stdout`, `stderr` added. **Cells:** a stdout `=1+2` becomes `'=1+2`; a not-run check has an empty `result`; `false` and UTC times ending in `Z`. |
| README "Re-evaluation" | **The README's curl command,** run as written with a real admin TOTP session (after the folder policy was edited to version 2, with check 2's ExpectedResult changed and check 3 dropped): 200 with exactly the documented keys, `scan_policy_version` 1, `policy_version` 2, `rows_added` 3, `not_in_version` 1. **Verdicts:** `result` is the new verdict (PASS) with `original_result` FAIL and `reeval_policy_version` 2; the unlisted check keeps its verdict. **Refusals:** 403 for an admin API token; unknown scan 404; deleted profile 409 `conflict`. **Repeat:** a second call adds another set; one `scan.reevaluate` audit entry each, neither with an alert. |
| README "Scheduler" / "Retention" and runbook §6 | **Timing:** the first retention run at start + 602 s (by the log), steps in the documented order, and the log lines are exactly as described. **Data:** nothing young deleted; reads still answer after the run. |
| Runbook §1 | the agent-version query runs and returns the fleet's versions |

#### Statements checked against the code or other suites, not walked here

- **Nightly section (r1)** against `.github/workflows/e2e.yml` and `e2e/m11/README.md`: cron `40 1 * * *` and `workflow_dispatch`; a push runs only with `[e2e]` in the head commit message; three machines (the manager container installed by manager-install.md with the OpenBao and sink doubles, plus jammy and noble QEMU/KVM cloud-image guests); matrix `[nightly, compat-a, compat-b]`, each on its own `ubuntu-24.04` runner; compat-a and compat-b as described; artifacts `e2e-report-<run>` with `report.json` and `report.md`; tables in `$GITHUB_STEP_SUMMARY`; red on a FAIL or missing row (`--check-report`). All match. The run itself is the lead's hosted e2e (37/37), not re-run here.
- **Retention table, batches, guards, never-deleted list and the audit-prefix rule:** these match `services/retention/rules.py` and `task.py`, and are pinned by the TASK-242 and TASK-245 suites (clock_doubt, future_rows, the cursor cap, chunk sizes 100, 1,000 and 10,000, one checkpoint per batch, SIGTERM stopping at the next batch).
- **Results cap text, viewer key absence and the role read per request:** TASK-244 TEST (CHK-M11-222, -223, -226).
- **Web UI bullets** (Scans, Run scan, Scan detail with "75.0 %" / "n/a" and the errors beside it, Cancel and Re-evaluate with confirmation, Scan results, Schedules, host history, the role table): these match REQ-279 to REQ-284 and the web suites (TASK-239 and 246–251, tester-m11w). There is no browser in this harness, so they were not clicked through.
- **agent-install.md:** L7 names `0.2.0~pre2-1`; L178 says `0.1.0-1` and `0.2.0~pre1-1` hosts upgrade in place, since `0.2.0~pre2-1` sorts above both (`dpkg --compare-versions`, above). The real install-upgrade of the `0.2.0~pre2-1` package is G38 (maintainer scripts `0.1.0-1` → `0.2.0~pre2-1`) at the M11 gate; it is not part of a docs walk.
- The agent-install.md upgrade sentence and the README's pre-release block agree with the changelog's top entry.

### Not run

- **§7's `gh workflow run`, `gh run list`, `git tag` and `git push`:** the release owner's steps (no tag or release in M11). Static check only.
- **The README's Web UI bullets in a browser:** covered by the web suites.

No product or docs defect found. The two test changes (the PD-51 row and the flaky bound) are mine.

## TASK-260 (#155 CSV memory: documented known v1 limit)

## TASK-260 TEST: PASS

Tester: tester-m11d, 2026-11-09. This is docs only: the #155 results CSV memory limit is documented as a known v1 limit, by the user's decision (decisions.md 2026-11-09 (1), option (a), no code change).
- `README.md` +1 line: Scan results → CSV export, the "Memory (a known limit of this version)" bullet, from impl-manager-a.
- `deploy/runbooks/manager-operations.md` +6 lines: a new §8 "Known limits", from impl-deploy.

See `work/reports/TASK-260-impl.md`.

### Checks

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Factual, against the code and spec | read both notes against `services/jobs/results_view.py`, `results_read.py`, `services/evaluator/model.py`, TS §4.5 L601 and the decision | PASS | See the factual check below. |
| `check_runbook_text.py`: no new findings | `m11t-scripts/tmp/docs_static.sh` (WSL) | PASS | README.md `OK 11 sh blocks, 0 findings`. manager-operations.md `OK 24 sh blocks, 0 findings`; §8 adds no sh block. agent-install.md (unchanged) still has only its 2 known placeholder findings. |
| The README walk tests still pass | `m11t-scripts/tmp/readme_walks.sh readme260 -n 2` on the four `test_readme_*_walk_linux.py` (WSL, `CI=true`, PostgreSQL 16, with the M11 web UI build copied into the WSL copy only) | PASS | **4/4 passed**, 0 failed, 0 errors, 0 skipped (254 s) |
| The two notes agree | read side by side | PASS | Same facts and the same advice. The README says "64 KiB / 16 KiB" (exact for the 65,536 / 16,384-byte caps); the runbook says "64 KB / 16 KB" as the spec does. |

**Factual check of both notes:**
- **The whole file is built in memory before it is sent.** True: `results_read.results_csv` reads every row, then `csv_text` builds the text, before the route makes the response.
- **The 100,000-row cap.** True: `CSV_MAX_ROWS = 100_000`.
- **Operator and admin rows carry stdout up to 64 KiB and stderr up to 16 KiB.** True: `STDOUT_CAP = 65_536` and `STDERR_CAP = 16_384`; the manager stores over-cap results as ERROR `oversize` with empty streams (TS §4.5 L601).
- **"About 8 GB" in the worst case.** True: 100,000 × 80 KiB ≈ 8.2 GB, before the text and bytes copies; the runbook says "and more while the file is written".
- **A viewer's export has no output columns and stays small.** True: `include_output` is false for viewers, and `csv_header(with_output=False)` has no `stdout` or `stderr` (TASK-244 TEST CHK-M11-222).
- **The advice to narrow with the `status` and `agent_id` filters.** True: both filters exist on `results.csv`.
- **Neither note claims what the code doesn't do:** no streaming, no setting, no other cap.

### Notes

- **No secret or process note:** neither note has a token, DSN, task id or process note, and the checker agrees.
- **Container:** a container labelled `m11t-timing` was running in WSL during this check. It isn't from any of my runs, so I left it alone.

## M11 gate (tester-m11g)

## M11 gate (TP-M11-15, -23, -24): PASS, except G39 NOT RUN (safety-check refusal; CI covers it on the PR). The merge is held by the open CHK-M11-387 finding (REQ-275, REQ-276 at fleet size), pending the user

Tester: tester-m11g, 2026-11-09. Tree: worktree `Bitscan-m11`, branch `m11-results` at **`c090303`** (all 28 M11 tasks committed) plus this gate's test changes (uncommitted): the new `manager/tests/test_security_m11.py` (TP-M11-15) and the CHK-M9-276 (M11) rewrite in `manager/tests/test_security_m9.py` (PD-51, approved by main). The lead's later commit **`c62da73`** (TASK-260) changes only `README.md` (+1 line) and `deploy/runbooks/manager-operations.md` (+6 lines) among the files tests read, so the tests that read them were re-run on `c62da73` (below). No product file was edited. Every plant was made in a throwaway copy that was deleted after its row, and the worktree holds none (`git status`: those two test files, `tests/m11/test-plan.md` (the TP-M11-15 binding note), this report, and the lead's `work/decisions.md` and `work/status.md`).

**Summary.** Every gate run is green on a clean tree and red on its planted violation: G1–G6, G12–G16, G18 (**11,908/11,908**, 0 skipped, after the PD-51 rewrite of CHK-M9-276 and one environment timing flake re-run alone), G19, G30–G34, G37, G38, G40, G41 (23/23), G80–G84, and G85–G87 (cited: hosted run 42488215323; G87's plants -373 and -374 red in runs 42594910837 and 42594935136). Services coverage (G5) is **98.5920 %**. TP-M11-15 is written: `test_security_m11.py`, **45/45**, with 24 of its 25 plants red; -322 stays green there by design. The mutation table holds every row from CHK-M11-320 onwards; all are red where the table names them, and no gate was lowered. **NOT RUN:** G39, the reproducible double build. A safety check refused the network step its fresh-cache builds need, and nothing was worked around; it is covered by M10's identical builds of the unchanged agent, 95/95 other build checks, and the PR's CI job. **Open, pending the user:** CHK-M11-387 (tester-m11t's #151 timing). Retention cannot delete a scan of more than about 600 hosts, or any inventory job, within `statement_timeout` at fleet size (no index on `scan_job.retry_of` or `scan_result_reeval.job_id`). It is recorded, neither passed nor failed, and it holds the merge. **Process note:** no M11 manager full suite ran between waves, so the stale CHK-M9-276 was first seen at this gate.

User decisions applied (decisions 2026-11-09): (1) #155 stays as built, so the 100,000-row CSV cap is tested as approved; (2) the G87 plant branches were allowed, and main pushed, ran and deleted them; (3) if the #151 timing changes `SCAN_CHUNK`, the retention suites are re-run for that fix round; (4) this report is the merge evidence.

Environments:
- **L:** Windows 11, worktree; web gates from `web/` with the worktree's `node_modules`.
- **W:** WSL Ubuntu 24.04 (14 vCPU, 3.9 GB, shared with tester-m11t's CHK-M11-387 timing database), `CI=true`, PostgreSQL 16 by Testcontainers. Own folder `/root/m11g`: `tree/` rsync'd from the worktree (no `.git`, venv, `node_modules` or caches), `venv/` from `pip install --require-hashes -r manager/requirements-dev.txt` then `-e tree/manager`, `venv-g41/` (the same lock) for G41, whose harness re-points the editable install. Scripts in `C:\Users\kaiquan.koh\Documents\m11g-scripts\`; `bs[uaek]_` strings masked in every log before reading.
- **Web UI for the M5 walk:** built outside the tree (a temp copy of `web/` with a junction to `node_modules`, `vite build --outDir m11g-scripts/webui`) and copied into the WSL copy only. Its bytes equal tester-m11d's build (`index-C0l5idKQ.js` `b2953f67…`, `index-BJT0iK-w.css` `ffe816ca…`).
- **Zscaler:** WSL's `/etc/ssl/certs/ca-certificates.crt` mounted read-only into every container that needs the network.

### TP-M11-15: the M11 security suite, `manager/tests/test_security_m11.py` (G83)

Written at this gate as one file (45 tests: 39 CODE, 6 PostgreSQL; the `-m "not pg"` plant runs show "39 passed, 6 deselected"). It reuses the task suites' builders: `m11_pg_fixtures` (callers of every role and kind, `results_world`, `aged_world`, the audit chain, `RoleSpy`, checksums, the sink outage), the re-evaluate world and state probes of `test_reevaluate_api_pg.py`, the page walker of `test_results_api_pg.py` and the route-walk markers of `test_auth_dependencies.py`. Lint: `ruff check`, `ruff format --check` and `mypy --strict` on the file are clean (W).

| Check | Tests | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-240 route walk | `test_the_scan_operations_are_exactly_the_spec_routes_with_their_markers`, `test_no_operation_of_the_app_takes_command_text` | PASS | The live app's scan operations are exactly M9's two and M11's six; markers `role viewer` ×5 and `totp_session admin` with the sink gate for re-evaluate; no M11 operation takes a body; no request schema of any operation has a command-like field; no rerun, run, exec or shell path |
| CHK-M11-241 response models | `test_only_the_operator_results_model_carries_output` | PASS | Only `ScanResultItemWithOutput` has `stdout`/`stderr`; `ScanItem`, `ScanDetailItem`, `HostSummary`, `HostJob`, `ReevalItem` have no output, `execute`, `expected`, `operator` or `resolved_agents` |
| CHK-M11-242 one writer | `test_reevaluate_scan_is_the_one_writer_of_reevaluations`; the spy in `test_viewers_never_receive_output_and_reads_write_nothing` | PASS | SQL text of every product module (migrations aside): `INSERT INTO scan_result_reeval` only in `repositories/reeval.py`; no UPDATE, DELETE or TRUNCATE of `scan_result*`; `DELETE FROM scan` only in `repositories/retention.py`; `reevaluate_scan` referenced only by `api/user/reevaluate.py` (defined in M8's module). Every M11 read route, every role, JSON and CSV: no write to `scan`, `scan_job`, `scan_result*` |
| CHK-M11-243 import graph | `test_the_m11_routes_reach_no_repository[2]`, `test_the_m11_layers_point_down_only[10]` | PASS | `scan_views.py` and `reevaluate.py`, and every `bm.api` module they reach at module level, import no repository and no psycopg; M11 services import no `bm.api`; M11 repositories import no service or api; the pure modules import no database code (the results view only its row type, CHK-M11-014) |
| CHK-M11-244, -245 frozen files | `test_the_frozen_files_are_byte_unchanged`, `test_no_file_was_added_to_a_frozen_folder[3]` | PASS | 38 files pinned by sha256 at `6efe0fb`: `auth/*` (11), `services/jobs/*` (11, M9), the five migrations and `versions/__init__.py`, `services/evaluator/{score,scores,reevaluate}.py`, `repositories/{results,reeval,scan_progress}.py`, `api/user/{scans,scan_schedules}.py`, `services/packages/csv_export.py`, `services/audit/{chain,verify}.py`; each byte-identical (also checked with `git show 6efe0fb:<path>` against the worktree on L). No file added to `auth/` or the migrations; `services/jobs/` gains exactly the three M11 modules |
| CHK-M11-246 agent components | `test_m11_contract.py::test_earlier_components_are_byte_identical` (kept there) | PASS | in G18 |
| CHK-M11-247 token groups | `test_tokens_are_refused_outside_their_route_group` | PASS | `bsa_` (an agent's real one, and one whose hash a `user_token` row holds) and `bse_` (likewise) get 401 `unauthorized` on all six M11 operations; a `bsk_` with its row gets 200 on the five reads (control). On an agent route, `bsk_` and `bsu_` whose hash an `agent` row holds get 401, and an operator session and an admin API token get 401; the agent's own `bsa_` pulls 200 (control) |
| re-evaluate refusals | `test_reevaluate_refuses_everyone_but_a_totp_admin_session`, `test_reevaluate_is_refused_from_15_minutes_of_sink_outage_until_the_drain` | PASS | admin API token 403 `totp_session_required`; restricted admin (no TOTP) and an admin whose session is not TOTP-verified 403 `totp_enrolment_required`; operator and viewer sessions 403 `forbidden`; operator and viewer API tokens 403; revoked token, `bsa_`, `bse_`, no token 401. Each refusal leaves the `scan_result_reeval`, `audit_log` and `scan_result` checksums unchanged. The admin TOTP session then gets 200, 3 rows, one `scan.reevaluate` entry. Clock control: 14 min 59 s into a sink outage 200; at 15 min 503 `audit_sink_unavailable`, nothing written; after the drain 200 again |
| CHK-M11-248 canary sweep | `test_no_canary_or_token_leaves_through_logs_problems_or_audit` | PASS | One flow at DEBUG over every M11 operation: 6 callers (viewer, operator, admin; session and API token) × every page (limit 2), every status filter, the CSV per filter, list, detail, host history; 5 bad requests each; the re-evaluation and 4 refusals. No log record (message, args, every attribute) holds OUT, ERR, EXEC, EXP or any caller's or agent's token; no problem body and no new audit detail holds a canary |
| CHK-M11-249 retention role limits | `test_retention_code_cannot_update_alter_or_insert`, `test_only_the_scheduler_runs_retention`, `test_serve_gives_retention_its_own_bitscan_retention_pool`, `test_retention_runs_as_bitscan_retention_within_its_role` | PASS | Static: the retention SQL has no UPDATE, row lock, DDL or INSERT, and deletes only the nine TS §5.2 retention tables; the service is imported only by the scheduler runner; serve gives the runner `AppDatabase(bounded_dsn(config.retention_dsn), name='bitscan_retention')`. APP: a `SchedulerRunner` built as serve builds it (an app pool and the retention pool) runs retention over the aged world: every statement is `bitscan_retention`'s, none the app pool's; no DDL, UPDATE or `FOR UPDATE`; INSERT only `INTO audit_log` (the checkpoint); all seven steps done with `skipped` null and no failure; the never-deleted tables (`os_info`, `agent_package`, `agent`, catalog, …) checksum-identical; the old scan gone, the inside one kept; the log holds no canary and no deleted scan or job id |
| CHK-M11-250 S608 and `re` | `test_s608_is_green_as_is_and_red_on_an_f_string_query[4]`, `test_the_re_ban_is_green_as_is_and_red_on_an_re_import[12]` | PASS | `ruff check` on stdin under the tree's configuration (`--stdin-filename`): each new repository is clean as it is and S608 on an appended f-string query; each of the 12 new modules is clean as it is and TID251 "`re` is banned" with `import re` |
| G83 run | `run.sh sec4 -n 2 tests/test_security_m11.py` (W) | **PASS** | **45/45 passed, 0 failed, 0 errors, 0 skipped** (33 s). First run 42/45: three test bugs, fixed in the test (the results view's allowed row-type import, CHK-M11-014; a lone surrogate in a product string constant that RE2 cannot encode; the auth-failure rate limit answering 429 before the token check, so each refused call now comes from its own address). Then the fixed `writer` row re-ran alone, 1/1 passed, and the whole file 45/45. Also in G18 |

G83 plants (throwaway copies, the whole file run each time; logs `g83code.jsonl` with `-m "not pg"` for the CODE-only rows, `g83pg.jsonl`):

| Plant | Red rows | Result |
| --- | --- | --- |
| CHK-M11-320 | viewer row | red |
| CHK-M11-321, -321-csv | viewer row (each) | red ×2 |
| CHK-M11-322 | none: survives by design (the route's viewer model drops the planted key) | green (expected; not a G83 row) |
| CHK-M11-323 | viewer row (CSV header) | red |
| CHK-M11-331 | viewer row (item count, another scan's rows) | red |
| CHK-M11-335 | markers, refusals, sink outage (and the clean-ruff row: an unused import) | red |
| CHK-M11-336 | markers, 15-minute row | red |
| CHK-M11-337 | markers, refusals | red |
| CHK-M11-339 | one-writer row, viewer row (the read spy saw the INSERT) | red |
| CHK-M11-341 | retention static row, retention run row (the packages step failed: permission denied) | red |
| CHK-M11-342 (serve), -342b (runner) | serve wiring row; retention run row (app-pool statements, every delete refused) | red ×2 |
| CHK-M11-344, -345 | S608 row for that repository | red ×2 |
| CHK-M11-346 | scan operations, command body | red |
| CHK-M11-357 | retention run row (a deleted scan id in the log) | red |
| CHK-M11-358 | canary sweep row | red |
| CHK-M11-359 | import-graph row | red |
| CHK-M11-367 | frozen-file row | red |
| CHK-M11-369 | retention static row, retention run row | red |
| CHK-M11-390 | re-ban row for `services/retention/task.py` | red |
| SEC-tok-user: the user parser takes `bsa_`/`bse_` as API tokens | token-group row, frozen-file row | red |
| SEC-tok-agent: the agent check takes `bsk_`/`bsu_` | token-group row, frozen-file row | red |
| SEC-reads-operator-only | markers row | red |

**25 plants: 24 red, 1 green by design (-322, red in G80 and G82 where it belongs).** Every S row of the mutation table marked G83 is red in G83.

### Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check .` from `manager/` (W, `static.sh`) | **PASS** | "All checks passed!". Plants red (`static.jsonl`): -344 and -345 (S608, `Found 1 error`), -390 (TID251 in `task.py`) |
| G2 | `ruff format --check .` (W) | **PASS** | "419 files already formatted" (420 with this gate's file). Plant red: one misformatted line in `results_read.py`, "1 file would be reformatted" |
| G3 | `mypy --strict .` (W) | **PASS** | "Success: no issues found in 419 source files"; this gate's file alone: no issues. Plant red: an untyped function in `results_read.py`, "results_read.py:19: error: Function is missing a type annotation [no-untyped-def]", "Found 1 error in 1 file (checked 420 source files)" |
| G4 | `pip install --require-hashes -r manager/requirements-dev.txt` (the venv) and `-r manager/requirements.txt` (a fresh venv) (W) | **PASS** | both rc 0 (the runtime lock: 35 pinned packages, 678 hashes). `git diff 6efe0fb` of the locks is empty; `pyproject.toml` changed only `precision` 2 → 4 (TASK-255). Plant red: the alembic entry with wrong hashes, `pip download --require-hashes` rc 1 "THESE PACKAGES DO NOT MATCH THE HASHES"; the unplanted entry rc 0 (control) |
| G5 | services coverage in G18 (`[tool.coverage.report]` `fail_under = 85`, `precision = 4`) | **PASS** | **98.5920 %** (6,022 of 6,108 statements; CHK-M11-311: 98.59 % to two decimals, not rounded up; gate 85). The M11 modules: `services/retention/task.py` 102/102, `rules.py` 62/62, `__init__.py` 0/0, `services/jobs/results_read.py` 34/34, `results_view.py` 54/54, `scan_views.py` 56/57 (line 115). Plant -391 red: 982 untested statements appended to `task.py` in a throwaway copy, the G18 data remapped onto the copy (control on the copy before the plant: 98.5920 %, rc 0), then "Coverage failure: total of 84.9246 is less than fail-under=85.0000", rc 2 (`cov.sh`) |
| G6 | `tests/test_openapi.py` in G18 | **PASS** | 6/6 in G18, including `test_committed_file_matches_a_fresh_export`. Plant -392 red (TASK-232) |
| G12 | `npm run lint` (L) | **PASS** | eslint `--max-warnings 0` exit 0. Plants -360, -361, -362 (b), -375 red (eslint exit 1; TASK-247, -248, -256) |
| G13 | `npm run typecheck` (L) | **PASS** | `tsc --noEmit` exit 0 |
| G14 | `npm run format:check` (L) | **PASS** | "All matched files use Prettier code style!" |
| G15 | `npx vitest run` (L; `testTimeout` 20000, TASK-257) | **PASS** | **755/755 passed in 31 files**, 0 failed, 0 skipped (42.8 s). Plants -360 to -366 red (G84 below) |
| G16 | in a temp folder: `openapi-typescript ../manager/openapi.json`, then Prettier with `--stdin-filepath src/api/schema.d.ts`; `cmp` with the worktree file (L) | **PASS** | byte-identical (sha256 `e7ffd8c4…c30a` both). Plant: a hand edit of line 2323 (`stdout: string \| null` → `string \| number \| null`) makes the regenerated file differ (`cmp` rc 1) |
| G18 | full manager suite: `pytest -n 2 -rfEs --tb=short --cov=bitscan_manager/services --cov-fail-under=85` (W, `CI=true`, `g18.sh`) | **PASS** (after the CHK-M9-276 (M11) rewrite) | Run 1 (57 min 20 s, 212 files): **11,906/11,908 passed, 2 failed, 0 errors, 0 skipped**; `Required test coverage of 85% reached`. The 2 failures: (a) `test_bit_parse.py::test_35015_elements_is_bit002_bounded`, an M7 timing bound ("2.878 s < 2.0 s" false) under the shared WSL load; **environment flake**, not a product change: re-run alone 1/1 passed, and 1/1 again later under lighter load. (b) `test_security_m9.py::test_no_m9_route_takes_command_text_or_names_inventory` (CHK-M9-276), deterministic (alone 1/1 failed): it asserted the `/api/v1/scans*` and `/scan-schedules*` operations are exactly M9's seven, and the extra items were exactly M11's five (`GET /scans`, `GET /scans/{id}`, `GET …/results`, `GET …/results.csv`, `POST …/reevaluate`). A test that M11's approved contract outdates (red since TASK-232, W1), not a product bug. **No M11 manager full suite ran between waves** (the speed rules ask for one per wave end; only targeted runs and the web full runs were recorded), which is why it was not seen until this gate. Rewritten under PD-51 with main's approval (old → new table): still an equality, M9's seven plus exactly M11's five, the M11 five checked to take no body, every body and parameter check kept. Re-run: `test_security_m9.py` **14/14** with the timing row **1/1** (15 passed); plant: a sixth, unknown operation `POST /api/v1/scans/{id}/rerun` in a throwaway `openapi.json` turns the row red. Final count: 11,908/11,908 (11,906 in run 1 plus the two node ids re-run green), 0 skipped. The web UI build and `README.md` were in the WSL copy (the M5 walk 1/1) |
| G19 | `pytest -m pg tests/test_schema_diff.py` (in G18) | **PASS** | **2/2** in G18 (no migration in M11; `db/migrations/versions/` byte-identical to `6efe0fb`, G83). Plant -393 red: a throwaway `m0006` adding `ix_reeval_job ON scan_result_reeval (job_id)`, `test_migrated_schema_equals_the_spec` failed (1 failed, 1 passed); G83's frozen-folder row also catches a new migration file |
| G30 | `tests/test_contract_agent.py` (in G18) | **PASS** | **569/569** in G18. Plant red: `stdout` added to `HeartbeatResponse`, `test_heartbeat_response_exact` (1 failed, 568 passed). My first form of the plant, an optional `stdout` on `HeartbeatRequest`, kept G30 green (569/569: the contract pins the request through the shared fixtures, which stay valid), and **G6 turns red on it** (`test_committed_file_matches_a_fresh_export`, 2 failed): recorded so the reviewer sees where each form is caught |
| G31 | `tests/test_agent_auth_pg.py tests/test_security_m3.py` (in G18) | **PASS** | **32/32** in G18. Plant red: the agent-route token check accepting `bsk_`/`bsu_` (`auth/tokens.py`, as G83's SEC-tok-agent), `test_wrong_prefix_refused_when_its_hash_is_an_agent_row[bsk_]`, `[bsu_]` (2 failed, 30 passed) |
| G32 | `tests/test_inventory_fuzz.py tests/test_inventory_decode.py` (in G18) | **PASS** | **129/129** in G18. Plant red: `DECOMPRESSED_CAP` 64 → 640 MiB, `test_64_mib_plus_one_is_413_after_at_most_cap_plus_one`, `test_gzip_bomb_is_refused_within_the_bounds` (2 failed, 127 passed) |
| G33 | `tests/test_sweep_pg.py tests/test_inventory_queue_pg.py tests/test_fleet_alerts_pg.py` (in G18) | **PASS** | **54/54** in G18. Plant red: the inventory upload window 30 min → 30 h in `sweep.py` (M3's G33 plant), 5 failed (`test_expiry_and_inventory_timeout`, the failing-step rows). The gate table's CHK-M11-341 as a G33 plant **stays green there (54/54)**, as expected: the sweep and inventory suites never run retention. -341 is red in G81 and G83, where it belongs. A table note for the planner, not a gap |
| G34 | `tests/test_invariants_m3.py` (in G18) | **PASS** | **33/33** in G18 (the six M11 operations in the spec route set, the M11 query-parameter sets). Plant -346 red: `test_every_operation_is_a_spec_route`, `test_no_request_schema_carries_a_command` (2 failed, 31 passed) |
| `.deb` | `deploy/debian/build-deb.sh` in `m4b-build-u24` from a copy of the tree (`pkg.sh build`) | **built** | `dpkg-parsechangelog` `0.2.0~pre2-1`; `bitscan-agent_0.2.0~pre2-1_amd64.deb` sha256 `800dc172…ea76`, `sha256sum -c` OK; binaries `bitscan-agent` `1d2c41a1…455e`, `bitscan-runner` `886cd319…0a13`, `bitscan-capread` `7d001846…e06e` (capread equals M10's; agent and runner carry the version string). The agent source is unchanged since `6efe0fb` (`git diff --stat 6efe0fb c62da73 -- agent deploy/debian deploy/systemd deploy/dbus`: only `changelog`) |
| G37 | `test_build_deb.sh --deb <that .deb> all`, lintian part (`pkg.sh g37`) | **PASS** | lintian **4/4**: `lintian --fail-on error,warning` passes, no E:/W: tag, no unused or mismatched override, every override has a reason. Plant red: a unit packaged 0666 (repacked copy), "W: bitscan-agent: non-standard-file-perm 0666 != 0644 [lib/systemd/system/bitscan-agent.service]", 2/4 |
| G38 | `test_maintainer_scripts.sh --deb <that .deb> all`, then `--from 0.1.0-1 upgradefrom`, in a privileged `m4b-sysd-u24` container (`pkg.sh g38`) | **PASS** | `all`: **OK 547/547** (install, missing, installenv, envvars, reinstall, upgrade, purge, reenrol, invalid, etcperm, stringpreseed, symlink, static), rc 0. `upgradefrom 0.1.0-1 -> 0.2.0~pre2-1`: **OK 20/20**, rc 0 (the 0.1.0-1 `.deb` checked against `SHA256SUMS-0.1.0` first). Plant red: postinst that refuses a second run (repacked copy), `reinstall` "exits 0 (got '100')", "half-configured" ×2 |
| G39 | `test_build_deb.sh … all`, repro part | **NOT RUN** (safety-check refusal) | The two repro builds each use a fresh Go module cache, so they download from `proxy.golang.org`. In the build container Go dialled only the IPv6 address ("connect: network is unreachable") for `santhosh-tekuri/jsonschema/v6@v6.0.3`, so both builds failed before compiling (3 FAIL rows, setup, not product). My next step, pinning the Go hosts to IPv4 in the container, **was refused by a safety check**, so per the brief it was not retried or worked around. Cover: the agent source is unchanged since M10, whose G39 found two builds identical (`.deb`, `.sha256`, three binaries, SBOMs); this gate's single build passed every other check (95/95: contents 24, static 14, SBOM 21, sha256 4, flags 28 with `-trimpath`, `CGO_ENABLED=0`, no VCS stamp, empty build id, lintian 4); and CI's `package.yml` job "Double build is byte-identical" runs on the pull request |
| G40 | `test_build_deb.sh … all`, SBOM part | **PASS** | **21/21**: each CycloneDX SBOM lists exactly the modules `go version -m` prints, with their versions and the Go version (runner and capread list `golang.org/x/sys v0.49.0`). Plant red: the runner SBOM says `v0.48.0`, "module golang.org/x/sys v0.49.0 … is in the SBOM (SBOM has ['v0.48.0'])", 20/21 |
| G41 | `e2e/agent_manager.sh /root/m11g/tree /root/m11g/pkg/out … m4b-sysd-u24` with the `0.2.0~pre2-1` `.deb` (`800dc172…ea76`) against a real `serve` from the M11 tree (W, `g41.sh`, `venv-g41`) | **PASS** | **OK 23/23 rows, rc 0** (about 20 min): serve ready (PostgreSQL 16, HTTPS, private CA); clean systemd host; admin by the CLI; TOTP session; `bse_` token (201); install with preseed `0.2.0~pre2-1 install ok installed active`; no `bse_` in debconf, `/etc` or logs; enrolment held (kind new); waits while held; approve 200; online; first inventory (`os_info` and the snapshot); package search; a dpkg change gives one unscheduled upload after the 60 s quiet time; a second change during the hold-off is not sent for the manager's 10 minutes (571 s watched) and is sent when it ends; revoke 204; the 401 stops the loops (journal line once); no agent call in 400 s after the 401; no `bse_`/`bsa_` in the agent journal or `serve.log`. Plant red (the reverse-order `list_sha256` `.deb`, built from a throwaway copy whose only diff is `slices.SortFunc(lines, func(a, b []byte) int { return bytes.Compare(b, a) })` in `agent/internal/inventory/dpkg.go`, `.deb` `8bf4ec8f…5d52`): **FAIL 12/13 rows, rc 1**, at "the first inventory job is uploaded": `refused: [{reason: hash_mismatch, status: 422}, …]`, no `os_info`, and the chain stops there |
| G80 | `test_results_view.py`, `test_retention_rules.py` (in G18) | **PASS** | **167/167** in G18. Plants: the TASK-233 and TASK-236 rows of the mutation table, red |
| G81 | the TP-M11-01, -03 to -06, -08 to -10, -13, -22 files (in G18) | **PASS** | **237/237** in G18 (12 files: `test_m11_fixtures_pg`, `test_scan_reads_pg`, `test_result_reads_pg`, `test_results_property_pg`, `test_retention_repo_pg`, `test_retention_grants_pg`, `test_scan_views_pg`, `test_results_read_pg`, `test_retention_pg`, `test_retention_race_pg`, `test_retention_wiring`, `test_serve_retention_linux`). Plants: the TASK-234, 235, 237, 238, 240, 241, 242, 245 rows, red |
| G82 | `test_scan_views_api_pg.py`, `test_results_api_pg.py`, `test_reevaluate_api_pg.py`, with `test_m11_contract.py` and `test_m11_contract_api_pg.py` (in G18) | **PASS** | **231/231** in G18 (5 files). Plants: the TASK-232, 243, 244 rows, red |
| G83 | `test_security_m11.py` | **PASS** | 45/45 (above), and in G18; 24 of 25 plants red, -322 green by design |
| G84 | the M11 web suites (inside G15) | **PASS** | in G15's 755/755. Plants -360 to -366 red (TASK-239, -246, -247, -248, -251), and tester extras -375 to -379, -430 to -440 red |
| G85 | nightly end to end (`e2e/m11/nightly.py` through `e2e.yml`) | **PASS** (cited) | Hosted e2e run **42488215323** on `5671c82`: `nightly` 19/19 PASS (both hosts: install held, approve, online, inventory 598 = 598 and 665 = 665, SR §1.1 import, scan `completed`, score 1.0, the plugin PASS, `results.csv`, the viewer without output, sweep 0 hits). Plants -370 (16/19) and -371 (18/19) red. Source: `work/reports/M11-e2e-test.md`. Not re-run, per the brief |
| G86 | N / N−1 (`e2e/m11/compat.py`) | **PASS** (cited) | Run 42488215323: `compat-a` 10/10 (agent 0.1.0 with manager N; every plugin ERROR `runner_unavailable`, score null), `compat-b` 8/8 (agent N with manager 0.1.0; no compliance job). The upgrade walk CHK-M11-307 16/16 (WSL, `5671c82`). Plant -372 red. Source: M11-e2e |
| G87 | `e2e.yml` itself | **PASS** | Scheduled and dispatch triggers, `[e2e]` push runs (42488215323 green) and a plain push skipped (run 42485349317, `skipped`). Plants: -373 run **42594910837** red ("FAIL CHK-M11-303 all", "FAIL CHK-M11-309 sweep:a", "sweep:b"); -374 run **42594935136** red ("missing CHK-M11-302 viewer"; compat-a and compat-b green as controls). Both throwaway branches deleted (main, 2026-11-09, under the user's decision (2)) |

Re-runs on `c62da73` (TASK-260: README +1 line, `manager-operations.md` +6 lines, docs only): the four README walks `test_readme_walk_linux.py`, `test_readme_m5_walk_linux.py`, `test_readme_m7_walk_linux.py`, `test_readme_m9_walk_linux.py` **4/4 passed** (3 min 32 s, W); `check_runbook_text.py`: `README.md` "OK 11 sh blocks, 0 findings", `manager-operations.md` "OK 24 sh blocks, 0 findings", `agent-install.md` its two known M6 placeholder findings (unchanged since M10). `e2e/m11/compat.py` walks `manager-operations.md` §1, which TASK-260 did not touch (the new §8 has no shell block).

### Open finding, pending the user: CHK-M11-387 (#151, retention at fleet size)

**Recorded, neither PASS nor FAIL** (CHK-M11-387 was planned as "recorded, not a gate"; main, 2026-11-09). tester-m11t's measurement (`work/status.md`, 2026-11-09 FINDING): on data set A (10,000 hosts, 1.82 M `scan_job` rows), retention runs past `statement_timeout` 300 s **per deleted job**, not per scan. 100 single-host scans took 105–108 s (fits); 1,000 inventory jobs (one `JOB_CHUNK`) were cancelled at 300 s; one scan of 1,000 hosts (1,019 jobs, a chunk of one scan) was cancelled at 300 s. Cause, confirmed by the lead against TS §5.2: no index on `scan_job.retry_of` (the self-reference) or on `scan_result_reeval.job_id` (FK, `ON DELETE CASCADE`), so each deleted job seq-scans both tables. Consequences: a fleet scan of more than about 600 hosts can never be deleted, and, as the oldest, it blocks every later scan; inventory jobs are never deleted. **An open finding against REQ-275 and REQ-276 at fleet size**, beyond the slow-but-working retention the user accepted for v1 (decisions 2026-11-08 (2)). **It holds the merge until the user decides**, and tester-m11t is measuring the options. The retention suites here (G81 237/237, G83's retention rows) pass at test size and say nothing about fleet size. If the fix changes `SCAN_CHUNK` or the retention code, the retention suites (G80, G81, G83's retention rows, G5) are re-run for that round (decisions 2026-11-09 (3)).

### NOT RUN at the M11 gate, with reason and cover

| Row | Reason | Cover |
| --- | --- | --- |
| G39 (reproducible double build) | **Safety-check refusal.** The repro builds need module downloads from `proxy.golang.org` into fresh caches; the build container's Go dialled only IPv6 ("network is unreachable"), and the step that would have pinned the Go hosts to IPv4 was refused. Not retried or worked around | The agent source is unchanged since `6efe0fb` (only the changelog), and M10's G39 found the two builds identical. This gate's build passed the other 95 build checks. The CI `package.yml` job "Double build is byte-identical" runs on the pull request; main checks it there |
| G7 to G11, G17, G35, G36 | Not re-run beyond CI, by the gate plan: M11 changes no agent or unit file (`git diff --stat 6efe0fb c62da73 -- agent deploy/systemd deploy/dbus` empty) | CI `agent.yml`, `units.yml` on the PR |
| CHK-M11-387 | Not a gate, and tester-m11t's row (run in parallel, not run here, per the brief): the open finding above | tester-m11t's report |
| Load tests (TS §8.3 L1284) | Deferred by the user | none |
| Debian 12, arm64 rows (TS §8.3) | Not supported (decisions 2026-10-24) | none |

REQ-288 (agent N with manager N−1) is built and passed (the user answered the N / N−1 marker "both ways", decisions 2026-11-08 (1)): G86 `compat-b` 8/8.

### Old → new check ids at this gate (PD-51)

| Old | New | Rule | Source |
| --- | --- | --- | --- |
| CHK-M3-233 / CHK-M9-219 (stop record: one "pool closed") | the TASK-245 rewrite in `test_serve_scheduler_linux.py` | two "pool closed" events (retention, then app), both after the single "scheduler stopping" and after the running sweep ended; the pool names are CHK-M11-198 | TASK-245 (CHK-M11-385) |
| CHK-M9-218 (job set, from CHK-M3-230) | unchanged for the three-argument runner; the four-job row is CHK-M11-196 | plus `test_without_the_retention_pool_three_jobs_and_no_retention_read` | TASK-245 |
| CHK-M9-285 (README text: results routes "not part of this version yet") | CHK-M11-386 | the Scans section has `### Scan results` and no "not part of this version"; the keys and lag clauses kept | TASK-252 |
| CHK-M5-280 (nav entries) | CHK-M5-280 (M11) | Scans after Profiles for every role; Schedules after Scans for operator and admin; everything else unchanged | TASK-251 |
| CHK-M9-276 (the operations under `/scans` and `/scan-schedules` are exactly M9's seven) | **CHK-M9-276 (M11)** | still an equality: M9's seven plus exactly M11's five under `/scans` (TS §6.2, plan TASK-232 §3); the five checked to take no request body; every body and parameter check kept for all twelve. `manager/tests/test_security_m9.py` (`M9_OPS`, `M11_SCAN_OPS`), approved by main 2026-11-09 under PD-51. Re-run 14/14; plant (a sixth operation in a throwaway `openapi.json`) red | this gate |

### Files of this gate

- `manager/tests/test_security_m11.py` (new, TP-M11-15, G83).
- `manager/tests/test_security_m9.py` (CHK-M9-276 (M11), above).
- `tests/m11/test-plan.md`: one note under TP-M11-15 binding CHK-M11-240 to -250 to the test names.
- This report. Scripts and logs outside the tree: `C:\Users\kaiquan.koh\Documents\m11g-scripts\` and `/root/m11g/logs/`.

### M11 mutation table (CHK-M11-320 onwards)

Every row was planted in a throwaway copy and turned its named check red for the planted reason, unless the row says otherwise. "Gate" in the Source column means planted at this gate (logs `/root/m11g/logs/g83code.jsonl`, `g83pg.jsonl`, `static.jsonl`, `gates2.jsonl`; runner `m11g-scripts/plant.py`, plants `plants-gate*.json`, `plants-static.json` from the `mk_plants_*.py` generators). Otherwise the source is the per-task report (folded into `tests/m11/report.md`). S = security row.

| CHK | Plant | Red in | Result | Source |
| --- | --- | --- | --- | --- |
| -320 S | `include_output` true for viewer | G80 (role table); **G83** (viewer row) | red | TASK-233; gate |
| -321 S | role read from the token kind (a viewer API token reads as operator); CSV variant passes `"admin"` | G82 (`viewer:api`, demoted); **G83** (viewer row) ×2 | red | TASK-244; gate |
| -322 S | viewer items carry `stdout: null` | G80 (viewer keys); G82 (the route-level variant `-322-route`) | red | TASK-233, TASK-244. At this gate the view-level plant **survives G83, as it should**: the route's viewer model `ScanResultItem` has no `stdout` field and pydantic drops extra keys, so no key or byte reaches a viewer (45/45 green). Not a G83 row in `work/tasks.md` |
| -323 S | viewer CSV keeps the two columns (empty) | G80; **G83** (CSV header row, through the API) | red | TASK-233; gate |
| -324 S | `csv` module instead of `write_csv` | G80 (70 failed) | red | TASK-233 |
| -325 S | `escape_cell` skipped for stdout and stderr | G80 (23 failed) | red | TASK-233 |
| -326 S | original verdict instead of the latest re-evaluation | G81 (12) | red | TASK-235 |
| -327 S | latest by `reevaluated_at`, not `reeval_id` | G81 (14) | red | TASK-235 |
| -328 S | `original_result` from the effective verdict | G80 (view part), G81 (12) | red | TASK-233, TASK-235 |
| -329 | not-run plugins left out | G81 (15) | red | TASK-235 |
| -330 | not-run name from the current catalog | G81 (13) | red | TASK-235 |
| -331 S | back-join without the job key (another scan's rows) | G81 (13); **G83** (15 items, no `other-scan`) | red | TASK-235; gate |
| -332 | score counts ERROR as FAIL | G81 (2) | red | TASK-240 |
| -333 | detail re-derives the state | G81 (2) | red | TASK-240 |
| -334 | CSV cap removed | G81 (2), G82 (1) | red | TASK-241, TASK-244 |
| -335 S | re-evaluate on `require_role("admin")` | G82 (TASK-232: 3; TASK-243: 3); **G83** (markers, refusals, sink outage) | red | TASK-232, TASK-243; gate |
| -336 S | `sink_gate=False` | G82 (2; 1); **G83** (markers, 15-minute row) | red | TASK-232, TASK-243; gate |
| -337 S | minimum role operator | G82 (2; 1); **G83** (markers, `operator:session` refusal) | red | TASK-232, TASK-243; gate |
| -338 | shipper's wake removed | G82 (2) | red | TASK-243 |
| -339 S | a second caller of `reevaluate_scan` (from the results route) | **G83** (one-writer static row; the read-route spy saw the INSERT) | red | gate (also TASK-243's -413, a second import, red in G82) |
| -340 | alert raised on re-evaluation | G82 (3) | red | TASK-243 |
| -341 S | retention deletes `agent_package` rows | G81 (4: refused by the grants); **G83** (static DELETE-target row; the scheduler run row: the packages step failed with permission denied) ; in G33 it stays green (54/54), as expected: those suites never run retention (see G33) | red | TASK-237; gate |
| -342 S | retention through the app pool: serve `retention_db=db` (-342), runner `run_retention(self._db, …)` (-342b) | G81 (3; 3); **G83** (serve wiring row; the scheduler run row) | red ×2 | TASK-245; gate |
| -343 S | audit rows deleted without a checkpoint | G81 (5) | red | TASK-242 |
| -344 S | f-string SQL in `result_reads.py` | **G1** (S608); **G83** (S608 row) | red | TASK-235; gate |
| -345 S | f-string SQL in `retention.py` | **G1** (S608); **G83** (S608 row) | red | TASK-237; gate |
| -346 S | `POST /scans/{id}/rerun` with an `execute` body | G34 (TASK-232: 4); **G34** (2 failed at this gate); **G83** (scan operations, command body) | red | TASK-232; gate |
| -347 S | checkpoint after the delete | G81 | red | TASK-242 |
| -348 S | audit delete by `at` (a hole) | G80 (4), G81 (2) | red | TASK-236, TASK-238 |
| -349 S | audit rows above the shipper's cursor | G80 (2), G81 | red | TASK-236, TASK-242 |
| -350 S | pending requests deleted | G81 (3) | red | TASK-237 |
| -351 | a scan deleted at 399 days | G80 (5) | red | TASK-236 |
| -352 | user tokens deleted at expiry | G80 (5) | red | TASK-236 |
| -353 S | clock guard removed | G81 (1 h ahead, 1 h behind) | red | TASK-242 |
| -354 | jobs deleted without the scan | G81 (3) | red | TASK-237 |
| -355 | re-evaluation lock not tried | G81 (repository 1; service race) | red | TASK-237, TASK-242 |
| -356 | retention not scheduled (serve; runner) | G81 (4; 4) | red | TASK-245 |
| -357 S | retention logs a deleted row's content (scan ids) | G81 (counts-only row); **G83** (the scheduler run row: a deleted scan id in the log) | red | TASK-242; gate |
| -358 S | results route logs the items at DEBUG | G82 (2); **G83** (the canary and token sweep row) | red | TASK-244; gate |
| -359 | route module imports a repository | G82 (1); **G83** (import-graph row) | red | TASK-244; gate |
| -360 S | `dangerouslySetInnerHTML` for stdout | G12 (eslint exit 1), G84 (1 failed / 14) | red | TASK-248 |
| -361 S | a `fetch(` in `ScanDetail.tsx` | G12 (eslint exit 1) | red | TASK-247 |
| -362 S | API-token fallback; token in `sessionStorage` | G84 (1 failed / 19); G12 (storage ban) | red ×2 | TASK-247 |
| -363 | `Score` 0 % for null | G84 (3 failed / 26) | red | TASK-239 |
| -364 | 0.9996 → "100.0 %" | G84 (6 failed / 26) | red | TASK-239 |
| -365 | `original_result` hidden | G84 (component 4 / 10, variant 2 / 10; screen 2 / 14) | red | TASK-239, TASK-248 |
| -366 | a viewer offered Run scan or Schedules | G84 (screen 1 / 15; shell and profile 1, 2, 1) | red | TASK-246, TASK-251 |
| -367 S | frozen `results.py` edited | G81 (PD-46 hash); **G83** (frozen-file row) | red | TASK-235; gate |
| -368 | correlated subquery on `scan_result_reeval` | G81 (EXPLAIN row only) | red | TASK-235 |
| -369 S | retention runs DDL (`DROP TABLE … scan_result_default`) | G81 (4: refused, not owner); **G83** (static DDL row; the scheduler run row: the scans step failed) | red | TASK-237; gate |
| -370 E2E | agent `.deb` whose runner returns no results | G85 (CHK-M11-302 ×3 FAIL, 16/19) | red | `work/reports/M11-e2e-test.md` (n5 r2, WSL dev run) |
| -371 E2E | results route leaves out a host | G85 (CHK-M11-302 u2204 FAIL, 18/19) | red | M11-e2e (n6) |
| -372 E2E | manager refuses the 0.1.0 heartbeat body | G86 (CHK-M11-305 heartbeat FAIL) | red | M11-e2e (TP-M11-19 r3) |
| -373 E2E | a FAIL row in the report | G87: e2e run **42594910837** red ("FAIL CHK-M11-303 all", "FAIL CHK-M11-309 sweep:a", "sweep:b") | red | main, 2026-11-09 (throwaway branch, deleted); local form red in M11-e2e |
| -374 E2E | an expected row removed | G87: e2e run **42594935136** red ("missing CHK-M11-302 viewer"; compat-a and compat-b green as controls) | red | main, 2026-11-09 (throwaway branch, deleted); local form red in M11-e2e |

Tester extras:

| CHK | Plant | Red in | Result | Source |
| --- | --- | --- | --- | --- |
| -375 S | a `<script>` hostname rendered as HTML (detail, results, table, picker) | G12 + G84 in each file | red | TASK-247, TASK-248, TASK-256 |
| -376 S | output column shown for viewer items | G84 (1 / 14) | red | TASK-248 |
| -377 | score formatter `floor(s*100*10)` | G84 (7 / 26) | red | TASK-239 |
| -378 | CSV download without `parseAs: "blob"` | G84 (1 / 15) | red | TASK-239 |
| -379 | tag check relaxed (a), (b) | G84 (1 / 37; 4 / 54) | red | TASK-256 |
| -390 | `import re` in a new module (`services/retention/task.py`) | **G1** (TID251); **G83** (re-ban row) | red | gate |
| -391 | untested function in `services/retention/task.py`, sized from the clean report | **G5** (84.9246 %, rc 2) | red | gate |
| -392 | route parameter without re-export | G6, M3 query allow-list (3) | red | TASK-232 |
| -393 | throwaway migration adding `ix_reeval_job` | **G19** (`test_migrated_schema_equals_the_spec`) | red | gate |
| -394 | tokens probe back on `expires_at` | G81 (3; 6) | red | TASK-237, TASK-242 |
| -395 | `FOR UPDATE SKIP LOCKED` back | G81 (3: permission denied) | red | TASK-237 |
| -396 | `<=` for `<`, each rule | G80 (2), G81 (3, 2, 2, 2, 2) | red | TASK-236, TASK-237 |
| -397 | `clock_doubt` with `>=` | G80 (1) | red | TASK-236 |
| -398 | `future_rows` with `>=` | G80 (1) | red | TASK-236 |
| -399 | prefix not capped; returns the cursor itself | G80 (4; 3) | red | TASK-236 |
| -400 | years as 365-day steps | G80 (6) | red | TASK-236 |
| -401 | `delete_requests` without `decision IS NOT NULL` | G81 (1) | red | TASK-237 |
| -402 | `delete_inventory_jobs` without `kind = 'inventory'` | G81 (3) | red | TASK-237 |
| -403 | `delete_through` with `<` | G81 | red | TASK-238 |
| -404 | `include_output` true for an unknown role | G80 (8) | red | TASK-233 |
| -405 | results keyset `>=` | G81 (5) | red | TASK-235 |
| -406 | scan list by `scan_id` only; `created_after` exclusive | G81 (9; 6) | red | TASK-234 |
| -407 to -412, -414 | re-evaluate: own alert, repository import, 404 echo, wake before commit, `PolicyDeleted` unmapped, shared lock, `allow_restricted=True` | G82 (6, 1, 1, 4, 2, 1, 5) | red | TASK-243 |
| -413 | a second import of `reevaluate_scan` | G82 (1) | red | TASK-243 |
| -415 to -421 | scan views: snapshot removed, decommissioned agents left out, `AgentNotFound` removed, host order, retry grouping, deleted policies filtered, `resolved_agents` in the target | G81 (1, 1, 1, 1, 2, 1, 3) | red | TASK-240 |
| -422 to -429 | results service: cap after the text, unbounded read, viewer statement reads output, `include_output` for viewer, `next_after` at `>=`, `limit` rows, snapshot removed, `ScanNotFound` for CSV | G81 (2, 1, 1, 16, 3, 7, 1, 1) | red | TASK-241 |
| -430, -431 | router: any scan id; any Run scan profile id | G84 (15; 8 / 148) | red | TASK-251 |
| -432, -433, -438 | double click; new key per send; host filter untrimmed | G84 (1 / 17; 1 / 17; 1 / 15) | red | TASK-246 |
| -434, -436 | Cancel for viewers; reload after a refusal | G84 (1 / 19; 4 / 19) | red | TASK-247 |
| -435 | edit always sends `cron` | G84 (4 / 17) | red | TASK-249 |
| -437 | CSV export drops the filters | G84 (1 / 14) | red | TASK-248 |
| -439, -440 | unknown stored target as All hosts; passed to `toTarget` | G84 (12; 2 / 68) | red | TASK-258 |
| -455 to -458 | read routes: raw-id cursor scopes, written-time scope, any-form cursor id, cursor position bounds, cap text, filename case, `AnchorGone` unmapped | G82 (1 each; 4; 2; 1, 1, 1) | red | TASK-244 |
| SEC-tok-user (gate) S | user-route parser accepts `bsa_`/`bse_` as API tokens | **G83** (token-group row: a `bsa_` whose hash a `user_token` row holds got 200; frozen-file row) | red | gate |
| SEC-tok-agent (gate) S | agent-route check accepts `bsk_`/`bsu_` | **G83** (token-group row: a `bsk_` whose hash an `agent` row holds pulled 200; frozen-file row) | red | gate |
| SEC-reads-operator-only (gate) | the five reads on `require_role("operator")` | **G83** (markers row) | red | gate |

CHK-M11-441 to -449 are unused ids. CHK-M11-450 to -454 and -459 are checks (TASK-245, TASK-244), not plants; all PASS in their reports.

**No gate lowered.** Since `6efe0fb`: `fail_under` stays 85 and `precision` went from 2 to 4 (TASK-255, stricter); the only workflow change is the new `e2e.yml`; `vite.config.ts` gained only `testTimeout: 20000` (TASK-257, no assertion changed); ruff, mypy, eslint, tsconfig and Prettier configurations are unchanged; the added test lines hold no `skip`, `xfail`, `.only` or `.todo` except the Windows-only `pytest.skip` guard of `test_serve_retention_linux.py`, the same as M9's `test_serve_scheduler_linux.py`, which never fires on Linux (G18: 0 skipped).

## CHK-M11-387 (#151 retention timing, tester-m11t)

## CHK-M11-387: retention chunk cost at fleet size (#151)

tester-m11t, 2026-11-09. Tree: `m11-results` at `c090303`. HEAD is now `c62da73`, but the retention code, the repositories, the pool, `serve.py` and the spec are unchanged since then (`git diff --stat c090303 HEAD` is empty for them). Gate items: `work/decisions.md`, 2026-11-08, "Gate item: the retention chunk against `statement_timeout`", and the lead's requests of 2026-11-09 (options (1) to (4)).

### Verdict: FAIL as the v1 limit. This is a finding for the user, not a product bug

The product code works as specified, and no code or setting was changed. But at fleet size, two retention steps cannot finish one chunk inside the inherited `statement_timeout` of 300 s, so they delete nothing, every night:

- **Inventory jobs:** one 1,000-job chunk takes **407 s** uncapped (data set A) and about 497 s (data set B). Under the real pool it is cancelled at 300.0 s.
- **Scans:** any scan of more than about **600 hosts** cannot be deleted in 300 s, even as a chunk of one scan. That scan is the oldest eligible one, so it heads every later chunk and the step never moves on. Halving `SCAN_CHUNK` (the user's 2026-11-09 remedy) does not help: the cost is per deleted **job**, not per scan.

The cause is the three missing indexes of #151. For each deleted `scan_job` row, PostgreSQL makes one full sequential scan of `scan_job` (the `retry_of` self-reference check) and one of `scan_result_reeval` (the `job_id` cascade). On this host that costs 0.41 to 0.50 s per job. With the three indexes, created on the test database only, the same chunks take 0.25 to 18 s, and a full nightly pass takes 25 to 33 s.

The snapshots, requests, tokens, audit (with checkpoint) and packages steps fit easily, at 0.03 to 1.7 s per chunk.

### Method

- WSL Ubuntu-24.04 with `CI=true`, in its own folder `/root/m11timing` and its own hashed venv (`pip install --require-hashes -r manager/requirements-dev.txt`, then the tree installed editable).
- PostgreSQL 16.15 from the test image `bitscan-test-postgres:16-d38e4c141225`, TLS on.
- The TS §5.2 Bootstrap ran through the harness (`tests.conftest._run_bootstrap`), then the real `bitscan-manager db migrate` to head `m0005`. There were 0 audit rows after the migration.
- Data was written as owner (`bitscan_migrate` with `SET ROLE bitscan_owner`), never as a superuser after the bootstrap. `VACUUM (ANALYZE)` ran after each bulk load, as autovacuum would.
- Every timed delete ran as `bitscan_retention`, through the real repository functions, on a pool built as `serve` builds it: `AppDatabase(bounded_dsn(...), min_size=0, max_size=1)`. Checked on the pool: `current_user = bitscan_retention`, `statement_timeout = 5min`, not a superuser.
- **One chunk** is one `db.transaction()` holding exactly the body of `task.py`'s loop:
  - scans: `scan_chunk(cutoff, 100)`, then `try_reeval_lock` per scan, then `delete_scans`;
  - inventory jobs: `delete_inventory_jobs(cutoff, 1000)`;
  - snapshots, requests, tokens and packages: their `delete_*` with 10,000;
  - audit: `lock_chain`, `oldest(10000)`, `audit_prefix`, `append_entry(audit.checkpoint)`, `delete_through`.
  Each time is wall time, commit included.
- **Full pass:** the real `run_retention(db, now, shipped_through=<max audit id>)`. Per-step times come from its own "retention step done" log lines.
- **Uncapped:** `EXPLAIN (ANALYZE, BUFFERS)` of the real statement as `bitscan_retention`, with `SET LOCAL statement_timeout = 0`, then rolled back.
- **Indexes for option (b):** `CREATE INDEX` on `scan_job(retry_of)`, `scan_job(scan_id)` and `scan_result_reeval(job_id)` on the throwaway database only (lead, 2026-11-09). They were dropped again before stage B was grown, and created again for B-idx.
- **Host:** Intel Core Ultra 7 155U (14 vCPU), WSL2 capped at 4 GB and shared with tester-m11g's concurrent full suite. The container was capped at 1.4 GB, with `shared_buffers` at 128 MB (the image default).
- Script and logs, outside the tree: `C:\Users\kaiquan.koh\Documents\m11t-timing\m11t.py` and `...\m11t-timing\logs\` (`results.jsonl`, `explain-*.txt`). The container has been removed. No `bs[uaek]_` value appears in any log (checked).

### Data set

The planning model is scaled from TS §7 L1196 (10,000 hosts × 2,000 packages) and the seeded schedules (inventory every 21,600 s). TS gives no scan frequency or plugin count, so these are my assumptions:

- a 200-plugin policy, about the size of CIS Ubuntu 24.04 L1 Server (the samples have 16);
- one fleet-wide scheduled scan per **week** (data set A, the lighter case) or per **day** (data set B);
- 2 % of compliance jobs have one retry;
- one fleet scan re-evaluated once in 400 days;
- one snapshot per host per day (unattended upgrades).

| Table | A (rows, heap) | B (rows, heap) | Notes |
| --- | --- | --- | --- |
| `agent` | 10,000 | 10,000 | |
| `scan` | 2,057 | 2,400 | A: 57 weekly fleet scans plus 2,000 manual single-host scans over 400 days. B: 399 fleet scans (daily) |
| `scan_job` | **1,816,379, 463 MB** (255 B/row) | **5,305,457, 1,125 MB** | Inventory: 1,233,000 (30 days × 4 a day × 10,000, plus a day past the cutoff). Compliance: A 583,379 (11,379 retries); B 4,072,457 (79,457 retries) |
| `scan_result` | 700,000 background, plus each test scan's own | 900,088 | 18 partitions, `2025_10` to `2027_02` plus the default, as `db maintain` keeps them (#44). Each scan being deleted has its full 200 results per job |
| `scan_result_reeval` | 2,000,000 | 2,200,088 | One re-evaluated fleet scan (10,000 × 200) |
| `inventory_snapshot` | 1,830,000 (40,000 past the cutoff) | 1,790,000 | 180 days × 10,000 |
| `enrollment_request` | 22,100 (20,100 past) | 2,000 | |
| `user_token` | 50,200 (30,200 past) | 20,000 | |
| `audit_log` | 1,100,000 (41,000 older than 3 years) | 1,059,005 | A valid chain, COPY-loaded through `m11_pg_fixtures.audit_chain` |
| `package` / `agent_package` | 81,000 (31,000 unreferenced) / 2,000,000 | 50,000 / 2,000,000 | |
| Database | 2,373 MB | 4,727 MB | |

**Scaled down, and by how much:**

- **`scan_result` background:** 50,000 rows per partition, against hundreds of millions in production. This only changes the depth of the per-partition primary-key probes in the results cascade: 3.6 to 8.3 ms per job without indexes, negligible beside the sequential scans. The deleted scans' own results are at full size.
- **`agent_package`:** 2 M rows, 10 % of TS §7's 20 M. This affects the packages step only (0.4 s).
- **Background compliance payloads:** `payload` and `eval_spec` are 18-byte JSONB placeholders, the inline width of a TOAST pointer, so the heap width is realistic (255 B per row). The scans being deleted use the real TS §6.5 payload and eval_spec of the 200-plugin policy (TOASTed), so their TOAST deletion is included.

### Timings, one chunk, against `statement_timeout` 300 s

Values are median / max over the repetitions (n). "Cancelled" means `QueryCanceled` at 300.0 s under the real pool.

| Step and chunk | A, as built | B, as built | A, three test indexes | B, three test indexes |
| --- | --- | --- | --- | --- |
| scans: 100 single-host scans (100 to 105 jobs, 20,000 results) | 107.7 / 108.3 s (3) | 132.5 / 138.5 s (3) | 0.28 / 0.35 s (3) | 0.42 / 0.56 s (3) |
| scans: 1 scan × 1,000 hosts (about 1,020 jobs, 200,000 results, 200,000 re-evaluation rows) | **cancelled in 4 of 4 reps** (note 1); uncapped **481.3 s** | not run (A is already over) | 0.86 / 0.96 s (2) | (in the full pass) |
| scans: 1 scan × 10,000 hosts (about 10,210 jobs, 2.0 M results) | **cancelled** inside the full pass (below); uncapped about 80 min, estimated (note 2) | uncapped about 85 min, estimated | 16.05 / 17.87 s (2) | 11.80 / 12.84 s (2) |
| inventory jobs: 1,000 | **cancelled** (1); uncapped **407.2 s** | **cancelled** (1); uncapped about 497 s (a 100-job run took 49.7 s) | 0.49 / 1.19 s (3) | 0.28 / 1.03 s (3) |
| snapshots: 10,000 | 0.08 / 0.12 s (3) | | | |
| tokens: 10,000 | 0.04 / 0.06 s (3) | | | |
| requests: 10,000 | 0.05 / 0.06 s (2) | | | |
| audit: 10,000 plus checkpoint | 0.12 / 0.15 s (3) | | | |
| packages: 10,000 | 0.42 / 0.45 s (3) | | | |

**Index build time** (option (b)'s migration cost here): 1.6, 0.7 and 0.5 s at A (12.4, 12.2 and 14.4 MB); 1.9, 2.0 and 0.9 s at B (37.0, 35.7 and 14.4 MB). The extra write cost on `scan_job` inserts was not measured.

#### Full `run_retention` passes (one day's backlog)

| Pass | Backlog | Result |
| --- | --- | --- |
| A, as built | 22 scans (one fleet scan, one 1,000-host scan, 20 manual; 11,227 jobs), 43,000 inventory jobs, 10,000 snapshots, 100 requests, 200 tokens, 11,000 audit entries, 1,000 unreferenced packages | **602.6 s.** **scans FAILED** after 300.1 s (`QueryCanceled`), 0 deleted. **inventory_jobs FAILED** after 300.3 s, 0 deleted. snapshots 10,000 in 1.65 s; requests 100 in 0.04 s; tokens 200 in 0.03 s; audit 11,000 (2 chunks) in 0.34 s; packages 1,000 in 0.10 s |
| A, three test indexes | the same 22 scans (11,227 jobs) and 40,000 inventory jobs (the small steps were already empty) | **33.0 s.** scans 22 in 1 chunk, 25.95 s; inventory 40,000 in 40 chunks, 5.72 s; the rest 1.3 s |
| B, three test indexes | 22 scans (one fleet scan; 11,246 jobs), 40,000 inventory jobs | **25.4 s.** scans 12.57 s; inventory (40 chunks) 11.65 s; the rest 1.1 s |

A full pass at B as built was not run. A already shows both steps failing, and B's per-job cost is higher.

### Where the time goes: `EXPLAIN (ANALYZE, BUFFERS)`, uncapped

A, 1,000-job inventory chunk (the real `delete_inventory_jobs` statement):

```text
Delete on scan_job  (actual time=1007.849..1007.868 rows=0 loops=1)
  Buffers: shared hit=12609 read=27070 dirtied=38
  ->  Nested Loop  (actual time=387.587..993.715 rows=1000 loops=1)
        ->  ... Seq Scan on scan_job scan_job_1  (rows=1000; Rows Removed by Filter: 1100187)
        ->  Index Scan using scan_job_pkey on scan_job  (loops=1000)
Trigger for constraint scan_job_retry_of_fkey: time=238362.510 calls=1000
Trigger for constraint scan_result_job_id_fkey: time=3641.600 calls=1000
Trigger for constraint scan_result_reeval_job_id_fkey: time=164158.095 calls=1000
Execution Time: 407176.133 ms
```

A, one 1,000-host scan (the real `delete_scans` statement); the delete itself takes 4 ms:

```text
Delete on scan  (actual time=4.416..4.427 rows=0 loops=1)
Trigger for constraint scan_job_scan_id_fkey on scan: time=373.118 calls=1
Trigger for constraint scan_job_retry_of_fkey on scan_job: time=278841.502 calls=1019
Trigger for constraint scan_result_job_id_fkey on scan_job: time=8497.756 calls=1019
Trigger for constraint scan_result_reeval_job_id_fkey on scan_job: time=193621.645 calls=1019
Execution Time: 481345.123 ms
```

The same statement with the three test indexes (1,022 jobs): `retry_of` 183.5 ms, `scan_result` 543.6 ms, `reeval` 115.9 ms, `scan_id` 93.5 ms; **Execution Time 940 ms**.

The query each trigger call runs, without indexes. It is a full sequential scan every time; inside the trigger it runs single-threaded, because `FOR KEY SHARE` prevents parallelism:

```text
-- SELECT 1 FROM ONLY scan_job x WHERE retry_of = $1   (A; run directly, so parallel)
Parallel Seq Scan on scan_job x (actual time=606.218..606.219 rows=0 loops=3)
  Filter: (retry_of = '...'::uuid)   Rows Removed by Filter: 605799
  Buffers: shared hit=7685 read=51565
-- SELECT 1 FROM ONLY scan_result_reeval x WHERE job_id = $1
Parallel Seq Scan on scan_result_reeval x (loops=3)  Rows Removed by Filter: 733359
-- SELECT 1 FROM scan_result x WHERE job_id = $1  -> Index Only Scan on each partition's PK, 5.7 ms
```

Per trigger call, from these plans:

| RI trigger, per deleted row | A inventory (1,000) | A scan (1,019) | B inventory (100) | A scan, indexed (1,022) |
| --- | --- | --- | --- | --- |
| `scan_job_retry_of_fkey` (seq scan of `scan_job`) | 238.4 ms | 273.6 ms | 385.0 ms | 0.18 ms |
| `scan_result_reeval_job_id_fkey` (seq scan of re-evaluations) | 164.2 ms | 190.0 ms | 106.0 ms | 0.11 ms |
| `scan_result_job_id_fkey` (PK probes, every partition) | 3.6 ms | 8.3 ms | 4.4 ms | 0.53 ms |
| `scan_job_scan_id_fkey`, per deleted scan | | 373 ms | | 93 ms |
| **per deleted job** | **0.407 s** | **0.472 s** | **0.497 s** | **0.9 ms** |

The cost is linear in the number of deleted jobs: every call is one full scan, and the three sizes measured (100, 1,000 and 1,019 jobs) agree. The largest chunk that fits in 300 s without indexes is about 740 jobs (A) and about 600 jobs (B). It falls as `scan_job` grows, and `scan_job` grows by 40,000 rows a day while the inventory step fails.

### Nightly retention time at steady state

One day's backlog is 40,000 inventory jobs (10,000 hosts, every 6 h), plus the day's compliance jobs: one fleet scan of about 10,200 jobs per week (A) or per day (B). The small steps take under 3 s together.

| | A (weekly fleet scan) | B (daily fleet scan) |
| --- | --- | --- |
| As built (300 s) | **never completes.** Both the scans and inventory steps fail on their first chunk, and `scan_job` grows 40,000 rows a day | the same |
| No indexes, timeout lifted (estimate: per-job cost × jobs) | inventory 40,000 × 0.407 s = 4.5 h; plus the fleet scan 10,200 × 0.472 s ≈ 80 min one night in 7. **About 4.5 h, or 5.9 h on the fleet-scan night** | inventory 40,000 × 0.497 s = 5.5 h; plus the fleet scan ≈ 85 min (note 2). **About 6.9 h a night** |
| Three indexes (measured full pass) | **33.0 s** | **25.4 s** |

### Options for the user

| Option | Change needed | One fleet-scan chunk (1 × 10,000 hosts) | One 1,000-job inventory chunk | Nightly time (steady state) | Fits 300 s? |
| --- | --- | --- | --- | --- | --- |
| (a) As built: no indexes, 300 s | none | cancelled at 300 s (true time about 80 to 85 min, estimated) | cancelled at 300 s (true time 407 s at A, about 497 s at B) | never completes; nothing is deleted from scans or inventory jobs | **No** |
| (a1) Halve `SCAN_CHUNK` (the 2026-11-09 remedy) | a constant | unchanged: one scan of more than about 600 hosts is over 300 s even at `SCAN_CHUNK` = 1 | unchanged | as (a) | **No** |
| (a2) Smaller `JOB_CHUNK` (about 300) | a constant | not addressed: a scan's jobs go in the scan's one statement (TS §5.3 "deleted together") | about 120 to 150 s per 300 jobs (estimated) | inventory 4.5 to 5.5 h; scans still blocked by any scan of more than about 600 hosts | inventory only |
| (b) The #151 indexes: `scan_job(retry_of)`, `scan_job(scan_id)`, `scan_result_reeval(job_id)` | TS §5.2 edit and one migration (builds in 0.5 to 2.0 s here, 12 to 37 MB) | **10.8 to 17.9 s** | **0.25 to 1.19 s** | **25 to 33 s** (measured) | **Yes** at steady state. A backlog chunk of 100 fleet scans would take about 20 to 27 min (estimated: 100 × 12 to 16 s) and would not. With (b), `SCAN_CHUNK` would have to be about 12 or less to bound that case |
| (c) No indexes; lift `statement_timeout` for the retention session only | a retention-pool setting | about 80 to 85 min (estimated) | 407 s (A, measured); about 497 s (B, estimated) | about 4.5 to 5.9 h (A), about 6.9 h (B), estimated; grows with fleet size and scan frequency | n/a: the bound would have to be at least about 1.5 h per fleet-scan chunk, and each chunk holds its transaction and locks that long |

### Notes and limits

1. **A labelling slip of mine.** In the A as-built run, the two reps labelled "1 scan × 10,000 hosts" ran on the 1,000-host scan. That scan was still eligible after its own two cancelled reps, so my builder did not add the fleet scan. They are counted above as reps 3 and 4 of the 1,000-host scan (both cancelled at 300.0 s). The fleet scan was then built for the A full pass, whose scans chunk (22 scans, 11,227 jobs) was cancelled at 300.1 s. The builder was fixed before the indexed and B runs, which did time the 10,000-host scan.
2. **Estimates.** The uncapped fleet-scan chunk (about 85 min) was not run, to save time. It is extrapolated from the per-job costs above, which are linear because every trigger call is one full scan. B's compliance per-job cost uses B's inventory per-job cost (the same two sequential scans). I can run the real uncapped fleet chunk (about 1.5 h) on request.
3. **Hardware and cache.** The sequential scans read mostly from the OS cache (`shared read`), with a 1.4 GB container cap and `shared_buffers` 128 MB. The same re-evaluation scan took 164 ms (A) and 106 ms (B), so treat per-call costs as ±40 %. A production server with more memory and a faster core might be up to about 2× faster per scan (my estimate, not measured). That would put the inventory chunk near 300 s, not well under it, and the per-job cost still grows with `scan_job`.
4. **Assumptions:** the scan frequency, the plugin count (200), the 2 % retry rate and one re-evaluated fleet scan are mine (TS is silent). The re-evaluation cascade cost scales with the size of `scan_result_reeval`.
5. Nothing in the tree was edited. The test indexes existed only on the throwaway database, which has been removed.

## TASK-261 (retention indexes m0006, SCAN_CHUNK 12; gate r1)

The test report is the "r1" section of `work/reports/M11-gate-test.md` (tester-m11g): G19 matches the TS §5.2 DDL of `68d3881`, 6/6 plants red; targeted run 289/289; G18 11,909/11,909; G5 98.5920 %; G83 46/46. The CHK-M11-387 re-measurement on the real migration follows in `work/reports/CHK-M11-387-test.md` (r1).
