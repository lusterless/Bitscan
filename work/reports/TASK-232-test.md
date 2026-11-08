# TASK-232 TEST: PASS

Tester: tester-m11, 2026-11-08. High risk (the lead's second look, PD-47). REQ-264 to REQ-270 and REQ-273 at contract level; PD-48; plan `work/plans/TASK-232.md` §3, §4, §7; #144 to #147; TS §6.2 L1086, L1113, L1120, L1122, L1123, L1125, §5.3 L1053, §6.3 L1136, L1141. Code under test (impl-manager-a, `work/reports/TASK-232-impl.md`): `bm/api/user/scan_views.py` (sha256 `9eb9b0d55451e9a4…`), `bm/api/user/reevaluate.py` (`f3571108dcfaa6ca…`), `bm/api/user/__init__.py` (`88a4f4d243b1e398…`), `manager/openapi.json` (`336f3e6995215fe4…`). The lead approved the model names `ScanResultItem` / `ScanResultItemWithOutput`; the plan called them `ResultItem`.

New test files: `manager/tests/test_m11_contract.py` (28 tests, CODE) and `manager/tests/test_m11_contract_api_pg.py` (67 tests, APP). Changed test file: `manager/tests/test_invariants_m3.py`. Its query-parameter allow-list now holds the four M11 read paths with their exact parameter sets (`M11_QUERY`), because REQ-088 changes in M11 to include the six operations. The inventory-switch assertion is unchanged. Plan rows: CHK-M11-230 to -235 ([test plan](../../tests/m11/test-plan.md), "TASK-232"). The expected values came from the plan and the spec before the route modules were read.

## Runs (W = WSL Ubuntu 24.04, `/root/m11t`, `CI=true`)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 2 test_m11_contract.py test_m11_contract_api_pg.py test_openapi.py test_invariants_m3.py test_auth_dependencies.py` | 166/167 passed, 1 failed, 0 errors, 0 skipped. Failure: `test_invariants_m3.py::test_no_query_parameter_can_switch_inventory_off`, an M3 allow-list that predates M11 (expected `{limit, cursor, state, job_id}`; actual also holds `policy_id, agent_id, created_after, created_before, status`). This was a test update owed to the REQ-088 change, not a product fault. |
| 2 | `pytest -n 0 "tests/test_invariants_m3.py::test_no_query_parameter_can_switch_inventory_off"` after the extension | 1/1 passed |
| 3 | run 1's files plus `test_scans_api_pg.py`, `test_agents_api_pg.py` (the M9 scan routes and the `/agents/{id}` routes that share the router) | 208/208 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on the three test files | clean |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-230 | `test_m11_contract.py::test_exactly_the_six_operations_are_added`, `::test_scan_list_parameters`, `::test_scan_id_operations_parameters` (4), `::test_host_history_parameters`, `::test_success_schemas_and_declared_refusals` (5), `::test_results_csv_is_text_csv` | PASS | The six operations, all under `/api/v1/`. The paths without them equal the 6efe0fb digest `094aaf0f…` (`POST /scans` is byte-identical). `limit` 1–500 default 50; `policy_id` ≥ 1; `agent_id` uuid; `state` = the six scan states; dates are `date-time`. Path ids use the hyphenated UUID pattern. Results take `status` (4 values) and `agent_id`; the CSV has no cursor; re-evaluate has no `requestBody`. 200 schemas as planned; refusals {400, 401, 403, 429, 503} plus 404, plus 409 for re-evaluate; CSV is `text/csv` string. |
| CHK-M11-231 | `::test_model_properties_are_exactly_the_plan` (10), `::test_model_value_types`, `::test_output_fields_only_in_the_operator_model` | PASS | Every M11 model has exactly the plan's properties, all required. `stdout` / `stderr` appear only in `ScanResultItemWithOutput`. No `resolved_agents`, `execute` or `expected` in the scan models. `score` is a number or null; `HostJob.state` has the eight job states. |
| CHK-M11-232 | `::test_earlier_components_are_byte_identical` | PASS | 80 earlier component schemas, digest `23f9503a…` = 6efe0fb (agent `ResultItem` included); M11 adds exactly 10 |
| CHK-M11-233 | `test_m11_contract_api_pg.py::test_reads_answer_501_after_auth_for_any_role` (15), `::test_reads_refuse_missing_wrong_group_and_revoked_tokens` (20), `::test_reevaluate_refusals_come_before_the_handler` (10), `::test_reevaluate_admin_session_reaches_the_501`, `::test_reevaluate_sink_gate_at_15_minutes` | PASS | Reads: viewer and admin, session or API token → 501 `about:blank`; no token, `bsa_`, `bse_`, revoked → 401 `unauthorized`. Re-evaluate: viewer and operator sessions → 403 `forbidden`; admin API token → 403 `totp_session_required`; viewer and operator API tokens → 403; restricted admin → 403 `totp_enrolment_required`; 401 for the four token cases; admin TOTP session → 501. Sink outage at 14 min 59 s → 501, at 15 min → 503 `audit_sink_unavailable` (reads unaffected), after the drain → 501. No `scan_result_reeval` row and no `scan.reevaluate` entry at any point. |
| CHK-M11-234 | `test_m11_contract.py::test_results_csv_is_its_own_route`; `test_m11_contract_api_pg.py::test_malformed_scan_ids_are_400` (5), `::test_malformed_reevaluate_id_is_400_for_an_admin`, `::test_upper_case_scan_id_passes_the_pattern`, `::test_invalid_query_values_are_400` (12), `::test_limit_500_and_an_offset_date_pass_validation` | PASS (contract part) | `/results.csv`, `/results` and `/{id}` each match only their own route. Non-UUID, unhyphenated and suffixed ids → 400 `invalid_request`; an upper-case id is accepted. `limit` 0/501, `state` `expired`/`dispatched`, `policy_id` 0, malformed `agent_id`, a date without an offset, `status` `pass`/`NOTRUN`/`OK` → 400, never 422. The 404 for `/agents/not-a-uuid/scans` belongs to the handler, so it is checked in TASK-244 TEST. |
| CHK-M11-235 | `test_m11_contract.py::test_route_walk_markers`; `test_openapi.py` (6); `test_invariants_m3.py` (33, incl. the spec-route allow-list); `test_auth_dependencies.py` route walks | PASS | Markers: five reads `("role", "viewer", restricted=False, sink_gate=False)`; re-evaluate `("totp_session", "admin", False, True)`. G6: committed file = fresh export. G34 green. |

## Plants (throwaway copies `/root/m11t/mut-<id>`, deleted after each row; log `/root/m11t/logs/plants-232.jsonl`)

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

## Acceptance (TASK-232: "G6 is green and the exported document holds exactly the plan TASK-232 operations, parameters, schemas and auth markers, and each handler answers 501 only after its auth dependency ran")

- G6: CHK-M11-235 (`test_openapi.py`). Operations and parameters: CHK-M11-230. Schemas: CHK-M11-231, -232. Auth markers: CHK-M11-235. 501 after auth: CHK-M11-233 (viewer on re-evaluate 403; no token 401).
- G16 stays red until TASK-239, as planned. It was not run here.

## Notes

- **W1-only rows.** The 501 assertions in `test_m11_contract_api_pg.py` hold only until the handlers are filled (PD-48). TASK-243 TEST and TASK-244 TEST will replace them with the filled answers. The refusal rows stay.
- **Question for `main` (recorded, not asserted).** The query `agent_id` on `/scans`, `/results` and `/results.csv` is typed `UUID`, as plan §3 says. It therefore also accepts the 32-hex, braced and `urn:uuid:` forms, while the path ids accept only the hyphenated form. The spec (TS §6.3 L1141, "IDs are UUID strings") does not say which. This report asserts only clearly malformed values (400).
- **For TASK-244.** `list_results` declares `Page[ScanResultItem] | Page[ScanResultItemWithOutput]`, so FastAPI validates the returned page against the union. TASK-244 TEST must show that operator items keep `stdout` / `stderr` through that union, and that a viewer page never carries them (CHK-M11-222).

---

# TASK-232 r1 TEST: PASS

Tester: tester-m11, 2026-11-08. r1 follows the decision of 2026-11-08 ("Correction: M11 query agent_id is hyphenated-only"). The query `agent_id` on `GET /scans`, `/scans/{id}/results` and `/results.csv` is now `Annotated[str | None, Query(pattern=UUID_PATTERN)]`. Code under test: `bm/api/user/scan_views.py` (sha256 `1e2b527addbebed2…`), `manager/openapi.json` (`126c54291c52c098…`); impl report section "r1" of `work/reports/TASK-232-impl.md`. This supersedes the "Question for main" note above.

## Changes to the tests

- `test_m11_contract.py`: the expected query `agent_id` schema is now `{"pattern": <8-4-4-4-12>, "type": "string"}` (`AGENT_ID_SCHEMA`), in `test_scan_list_parameters` and `test_scan_id_operations_parameters`; it was `format: uuid`.
- `test_m11_contract_api_pg.py`, new:
  - `test_query_agent_id_is_hyphenated_only`: 3 paths × 7 values. The 32-hex form (both cases), the braced `{…}` and `urn:uuid:` forms, a trailing LF, a leading space and a short id each get 400 `invalid_request`. This is row (a).
  - `test_query_agent_id_hyphenated_any_case_is_accepted`: 3 paths × lower and upper case pass validation (501 on W1). This is row (b).

## Runs (W, `CI=true`, `-n 2`)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest test_m11_contract.py test_m11_contract_api_pg.py test_openapi.py test_invariants_m3.py test_auth_dependencies.py test_scans_api_pg.py test_agents_api_pg.py` | 235/235 passed, 0 failed, 0 errors, 0 skipped (the first attempt did not collect: a literal line break that my edit script wrote into a test string; fixed before any test ran) |
| Plant (c) | `AGENT_ID = UUID \| None` in a throwaway copy, `pytest -n 2 tests/test_m11_contract_api_pg.py` | RED: 12 failed, 82 passed. The 32-hex, upper 32-hex, braced and `urn:uuid:` forms are accepted on each of the 3 paths. Padded and short values fail under both types. |
| Lint | ruff, ruff format, mypy --strict on both test files | clean |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-230 (r1) | `test_m11_contract.py::test_scan_list_parameters`, `::test_scan_id_operations_parameters` | PASS | query `agent_id` declared with the hyphenated pattern on the three paths |
| CHK-M11-234 (r1 a) | `test_m11_contract_api_pg.py::test_query_agent_id_is_hyphenated_only` (21) | PASS | 400 `invalid_request` for each non-hyphenated form |
| CHK-M11-234 (r1 b) | `::test_query_agent_id_hyphenated_any_case_is_accepted` (6) | PASS | lower and upper case pass validation |
| CHK-M11-234 (r1 c) | plant `P232r1-agent-id-uuid-type` | RED | 12 failed (log `/root/m11t/logs/plants-232r1.jsonl`) |
