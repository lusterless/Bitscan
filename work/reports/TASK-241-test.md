# TASK-241 TEST: PASS

Tester: tester-m11c, 2026-11-08. High risk, full rigor, and the user's second look (PD-47). Every security row, boundary and race is planted. REQ-267 (1)–(4), REQ-268 (1), (2) and REQ-269 (2), (3) at service level, with the canaries. Spec: TS §6.2 L1083 and L1123, §4.5 L603, §4.4 L585, §6.3 L1144. Answers: #119, #144 (a)–(e), #146. Code under test: `bm/services/jobs/results_read.py` (sha256 `b7c1d876195de97d…`), by impl-manager-a, `work/reports/TASK-241-impl.md`. It is built on TASK-233's `results_view`, TASK-235's `result_reads` and TASK-240's `ScanNotFound`.

Test file (new): `manager/tests/test_results_read_pg.py`, 57 items. CHK-M11-165 to -170. It runs as `bitscan_app` through `AppDatabase` on `m11_pg_fixtures.results_world` (owner-written; the fixtures were not edited). The item oracle is written in the test from that world's docstring: 15 items, host a with the original and its retry, the twice re-evaluated FAIL, the intake ERROR and Not run; host b queued; host c with hostile stdout and formula cells. The CSV formula rule is re-implemented in the test from TS §6.3 L1144, not taken from M5.

## Runs (W: WSL Ubuntu 24.04, `/root/m11c`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 4 tests/test_results_read_pg.py` | 57/57 passed, 0 failed, 0 errors, 0 skipped |
| 2 | `pytest -n 4` with the dependency suites: `test_results_read_pg.py` (57), `test_results_view.py` (118), `test_result_reads_pg.py` (21), `test_results_property_pg.py` (1) | **197/197 passed**, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on the file, from the repository root | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-165 | `test_results_read_pg.py::test_results_page_signature_takes_the_role_only`, `::test_no_output_keys_or_canary_for_a_viewer_or_unknown_role[viewer,auditor,Admin,""]`, `::test_operator_and_admin_get_output[operator,admin]`, `::test_viewer_statement_never_reads_stdout_or_stderr` | PASS | Both service signatures take `role` and no token-kind parameter. Viewer and unknown roles, across 5 statuses × 2 agent values on every `limit=2` page, get exactly the 22 keys in #144 (a) order, `with_output` false, and no OUT or ERR byte. EXEC and EXP (catalog text) are present. Operator and admin get the 24 keys and the oracle items, with OUT and ERR. **The viewer's page and CSV statements name no `stdout` or `stderr`** (statement spy); the operator's statement selects `r.stdout`. |
| CHK-M11-166 | `::test_items_equal_the_oracle_for_a_viewer`, `::test_filters_alone_and_together[*]` (20), `::test_unknown_agent_filter_is_empty`, `::test_paging_visits_every_item_once[1,2,4,5,7,14,15,16]`, `::test_paging_with_a_filter` | PASS | The items equal the oracle exactly: p1 shows PASS "high" from the higher `reeval_id` against original FAIL; p3 is answered by the retry (`retry` true); p4 and every host-b plugin are Not run, named from `eval_spec`. `other-scan` never appears. 5 statuses × 4 host values equal the oracle subset, and an unknown agent gives an empty page. Paging visits every item once. `next_after` is set only when a further item exists: at limits 1, 5 and 15 (exact multiples of 15) the last page has no cursor. The NOT_RUN walk gives the 6 Not-run items. |
| CHK-M11-167 | `::test_csv_rows_equal_the_json_items[*]` (9), `::test_csv_escapes_and_quotes_output`, `::test_viewer_csv_has_no_output_column_or_canary` | PASS | For viewer, operator and admin, and the statuses all, FAIL and NOT_RUN: the header is exactly #146 (plus `stdout, stderr` for operator and admin), and each record equals its JSON item. Null is an empty cell, booleans are `true`/`false`, times are UTC with `Z` and equal the item's, and every text cell is escaped per TS §6.3. There is no BOM and the text ends in CRLF. `=1+2` becomes `'=1+2` and `@SUM(1)` becomes `'@SUM(1)`. Stdout with commas, quotes, LF and CRLF round-trips exactly. The viewer CSV has no output column and no OUT or ERR byte. |
| CHK-M11-168 | `::test_100000_rows_export`, `::test_over_the_cap_refused_before_any_text[one_over,over]` | PASS | 100,000 Not-run rows export: 100,001 records including the header, `csv_text` called once. At 100,001 and 100,005 rows, `TooManyRows` is raised and `csv_text` is **never called** (spy). The repository returned exactly 100,001 rows each time (spy), so the read is bounded. The exception holds no canary. |
| CHK-M11-169 | `::test_unknown_scan_raises_scan_not_found`, `::test_scan_without_jobs_is_an_empty_answer`, `::test_each_call_is_one_read_only_snapshot` | PASS | An unknown scan raises `ScanNotFound` for both calls, and it is the same class as `scan_views.ScanNotFound`. A scan with no jobs gives an empty page and a header-only CSV, not 404. For each call, the first `bitscan_app` statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`. Every statement is SET, SELECT or WITH, with no write verb. |
| CHK-M11-170 | `::test_no_canary_or_token_in_logs_or_exceptions` | PASS | caplog at DEBUG, with capture proven by a probe record, over pages and CSVs for 3 roles × 4 statuses, plus `ScanNotFound` and `TooManyRows`. No canary appears in any log record (message, args, every attribute). No canary appears in any exception or its chain. No `bitscan_manager.*` record other than the probe exists, so the service logs nothing. OUT and ERR appear only in the operator and admin answers. |

## Plants (throwaway copies, each deleted after its row; plants file `/root/m11c/plants-241.json`, log `/root/m11c/plants-241.out.jsonl`)

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

## Acceptance (TASK-241: "REQ-267 (1)–(4), REQ-268 (1), (2) and REQ-269 (2), (3) hold with the canary")

- REQ-267 (1): CHK-M11-166.
- REQ-267 (2): CHK-M11-166 (filters).
- REQ-267 (3): CHK-M11-166 (paging; cursors from another scan or filter set are the route's HMAC scope, TASK-244).
- REQ-267 (4): the 200-scan property agreement is TP-M11-04's `test_results_property_pg.py` on the same repository, re-run green here (1/1).
- REQ-268 (1): CHK-M11-165, -167, -170.
- REQ-268 (2): at service level, `role` alone decides on every call (CHK-M11-165, signature and roles). The demoted-API-token row is a route row (TP-M11-12, CHK-M11-223).
- REQ-269 (2): CHK-M11-167.
- REQ-269 (3): CHK-M11-168.
- Also covered: the read-only snapshot and SELECT only (CHK-M11-169), and the canary in logs and exceptions (CHK-M11-170).

## Notes

- The CSV time format is `YYYY-MM-DDTHH:MM:SS.ffffffZ`. The test asserts only RFC 3339 UTC with `Z` and value equality, as #146 (b) requires, not the digit count.
- CHK-M11-428 covers `results_page`. `results_csv` has its own snapshot call, which `test_each_call_is_one_read_only_snapshot` also checks.
