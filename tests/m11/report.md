# M11 test report

Phase report for M11 (results and end-to-end). The lead folds in each section unchanged from the tester's per-task report `work/reports/<id>-test.md`, which is the source, with headings demoted one level. The harness refuses report-file writes from tester sub-agents, as in M9 and M10.

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-232 | TASK-232 TEST (r0 and r1): PASS | `work/reports/TASK-232-test.md` |
| TASK-233 | TASK-233 TEST: PASS | `work/reports/TASK-233-test.md` |
| TASK-234 | TASK-234 TEST: PASS | `work/reports/TASK-234-test.md` |
| TASK-237 | TASK-237 TEST: PASS | `work/reports/TASK-237-test.md` |
| TASK-238 | TASK-238 TEST: PASS | `work/reports/TASK-238-test.md` |
| TASK-239 | TASK-239 TEST (W2 web batch): PASS | `work/reports/TASK-239-test.md` |
| TASK-235 | TASK-235 TEST: PASS | `work/reports/TASK-235-test.md` |
| TASK-236 | TASK-236 TEST: PASS | `work/reports/TASK-236-test.md` |
| TASK-255 | TASK-255 TEST: PASS | `work/reports/TASK-255-test.md` |
| TP-M11-17 | TP-M11-17 (harness carries): PASS | `work/reports/TP-M11-17-test.md`; rows in `work/reports/M11-e2e-test.md` |

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
