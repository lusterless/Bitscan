# TASK-244 TEST: PASS

Tester: tester-m11d, 2026-11-08. High risk with the user's second look (PD-47): which verdict and which output each role sees. Every security row and boundary is planted.

- **Scope:** TP-M11-12. REQ-264 (1)–(5), REQ-265 (3), (6), REQ-266 (1)–(4), REQ-267 (3), (5), REQ-268 (1)–(4), REQ-269 (2)–(4), REQ-272 (2), (4). Against TS §6.2 L1083, L1113, L1120–L1123 and §6.3 L1135–L1136, L1141, L1142, L1144; #89, #144, #145, #146 as approved (#155 is pending the user: the 100,000-row cap and a full build are tested as approved).
- **The lead's rows:** the five 501 rows replaced; upper- and lower-case `agent_id` share a cursor scope; one instant written with two offsets shares a time scope; the cursor is accepted only in its exact form; operator and admin pages keep `stdout`/`stderr` (CHK-M11-222); the CSV cap and headers; G6.
- **Code under test:** `bm/api/user/scan_views.py` (sha256 `69709aa51cb143a1…`), by impl-manager-a; see `work/reports/TASK-244-impl.md`. Services TASK-240 and TASK-241 are unchanged.

Test files:
- `manager/tests/test_scan_views_api_pg.py` (new): 44 items.
- `manager/tests/test_results_api_pg.py` (new): 29 items.
- `manager/tests/test_m11_contract_api_pg.py` (tester-m11b's): the five W1 501 rows now expect the filled answers. On the file's unknown SID and AID, `GET /scans` returns 200 with an empty page and the four id routes return 404 `not_found`. The rows are `test_reads_answer_after_auth_for_any_role`, the sink-gate read, the upper-case id, `limit=500`, and hyphenated any-case. The refusal rows are unchanged.

I drafted the tests from the REQs and the lead's rows, then bound them to the route's names. The forged-cursor rows sign with `encode_cursor` and the route's scope strings. Each test starts from emptied scan tables, cleared as owner. Every caller is real: a session and an API token for each role, plus revoked, `bsa_`, `bse_` and none from `m.callers`.

## Runs (WSL `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers, `--tb=short`, tokens masked)

| Run | Command | Result |
| --- | --- | --- |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on the three files | clean |
| 1 | `pytest -n 3 tests/test_scan_views_api_pg.py` | 43/44 passed, 1 failed (a test bug, below), 0 errors, 0 skipped |
| 2 | `pytest -n 0 …::test_detail_body_keys_target_and_hosts` (after the fix) | 1/1 passed |
| 3 | `pytest -n 3 tests/test_results_api_pg.py` | 29/29 passed, 0 failed, 0 errors, 0 skipped |
| 4 | `pytest -n 3` on the three files plus the affected files `test_m11_contract.py`, `test_openapi.py` (G6), `test_invariants_m3.py` (route walk), `test_app_hardening.py` and `test_results_view.py` | 405/405 passed, 0 failed, 0 errors, 0 skipped |
| G6 | `test_openapi.py::test_committed_file_matches_a_fresh_export` (in run 4), and `git diff --quiet HEAD -- manager/openapi.json` | equal; no diff |

**Run 1's failure was mine.** I sorted the expected host order in Python byte order (`<script>…` first). The route orders "by hostname, then agent_id" as PostgreSQL orders text in the database's default collation, which puts the `<script>` hostname by its letters, after `m9-…`. The test now takes the expected order from the database (`ORDER BY hostname, agent_id`). **For `main`:** the spec names no collation for this order (TS §5.2 sets none). The current behaviour follows the database collation. I don't see a defect, but I'm noting it in case the owner wants byte order.

No product bug found.

## Report rows (for tests/m11/report.md)

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

## Plants (throwaway copies; plants `/root/m11t/plants-244.json` from `m11t-scripts/tmp/mk_plants_244.py`; log `/root/m11t/logs/plants-244.jsonl`)

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

## Acceptance (TASK-244)

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

## Notes

- **Hostname collation** (above): the order follows the database collation, and the spec names none. Not a defect in my reading; it's for `main` to confirm with the owner if byte order was meant.
- The CSV route ignores a `cursor` parameter, as FastAPI ignores undeclared query parameters. The spec doesn't ask for it to be refused, so it isn't tested.
- **White-box reads:** the scope strings `scans:::::` and `scan_results:<id>::`, and `encode_cursor`, used only to sign the forged-form cursors.
- **#155 (CSV memory bound) is pending the user.** The cap rows test #146 as approved.
