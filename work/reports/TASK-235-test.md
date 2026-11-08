# TASK-235 TEST: PASS

Tester: tester-m11b (took over from tester-m11), 2026-11-08. High risk, full rigor: a plant for every security row, boundary and race the checks name. REQ-267, REQ-269, REQ-272 at repository level; #119, #144 (a)–(e), #146 (e), PD-46; TS §4.5 L603, §4.4 L585, §6.2 L1123. Code under test: `bm/repositories/result_reads.py` (sha256 `5e9f78b4f16e75f0…`), impl-manager-a, `work/reports/TASK-235-impl.md`. M8 `bm/repositories/results.py` sha256 `101e918293e108f2…`, equal to `6efe0fb`.

Test files (new):
- `manager/tests/test_result_reads_pg.py`: 18 functions, 21 items. CHK-M11-118 to -131.
- `manager/tests/test_results_property_pg.py`: 1 item. CHK-M11-082.

Plan rows: [test plan](../../tests/m11/test-plan.md), "TP-M11-04". The tests bind to the impl's interface: `results_page(conn, scan_id, *, status, agent_id, with_output, after, limit)`, `results_export(…, max_rows)`, `exists`, `read_only_snapshot` and `ResultRow`. The expected rows are built from the world description, meaning the inputs the TP-M11-01 builder wrote: stored results, the job's stored `eval_spec` and payload. They are never taken from the repository. The property oracle is M8's pure `score.effective()` over the stored rows, plus M8's `results.host_counts`.

## Runs (W, `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 3 tests/test_result_reads_pg.py tests/test_results_property_pg.py` | 21/22 passed, 1 failed, 0 errors, 0 skipped. The failure was a test bug: `test_select_only_as_bitscan_app` expected 6 statements; the calls it makes are 7. |
| 2 | `pytest -n 0 tests/test_result_reads_pg.py::test_select_only_as_bitscan_app`, after the fix | 1/1 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on both files | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

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

## Plants (throwaway copies; log `/root/m11t/logs/plants-235.jsonl`; plants file `/root/m11t/plants-235.json`)

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

## Acceptance (TASK-235: "REQ-267 (1), (2), (4), (6) hold at repository level, a not-run row takes its name from `eval_spec`, `results.py` is byte-unchanged, and `EXPLAIN` shows `scan_result_reeval` read once per page")

- REQ-267 (1): CHK-M11-118, -119, -121.
- REQ-267 (2): CHK-M11-122.
- REQ-267 (4): CHK-M11-082.
- REQ-267 (6): CHK-M11-124.
- Not-run name: CHK-M11-120.
- `results.py` byte-unchanged: CHK-M11-129.
- EXPLAIN: CHK-M11-130.
- Also covered: REQ-269's repository part (CHK-M11-126) and REQ-272 (CHK-M11-131, plant -344).

## Notes

- `results_page` returns `[]` for an unknown scan and `exists` tells the two cases apart, as the plan says. The 404 is TASK-241 and 244's.
- The impl's `specs` CTE, which joins `eval_spec` entries by `(job_id, plugin_uuid)`, departs from plan §3's sketch, as the impl report says. CHK-M11-120 confirms the outcome the plan requires.
- Test-id ranges: the lead's message today gives me -310 to -369. I use `CHK-M11-405` because tester-m11's test plan already assigns it (tester extras -390 to -406). `main` decides whether those keep their ids.
