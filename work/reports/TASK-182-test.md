# TASK-182 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor. REQ-197, REQ-198 (1)–(5); TS §4.5 L601–L602, §4.4 L577–L583, §5.2 (no index on `scan_result_reeval`); #119. Code under test: `bm/repositories/results.py` (impl-manager-m8b, `work/reports/TASK-182-impl.md`). New test files: `manager/tests/evaluator_pg_fixtures.py` (TP-M8-01 builder), `manager/tests/test_results_repo_pg.py`. Plan rows: CHK-M8-140 to -142, -150 to -160.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_results_repo_pg.py` | **15/15 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 8 plants (7 pytest, 1 ruff) | 8/8 red |
| static (L) | whole-tree `ruff check manager` (after fixing my builder's E501s, which the reviewer flagged), `ruff format --check`, `mypy --strict` on both files | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-140, -142 | APP | W | r1 | PASS | The builder's rows (owner-written) read back as `bitscan_app`: 11 results whose `job_created_at` equals the job's; the TS §6.5 payload and the #117 `eval_spec` (no `execute`). Host B's retry was created next month: its results sit in a second monthly partition, and none in the default. The trigger refuses a `job_created_at` off by 1 s | 2026-10-29 |
| CHK-M8-141 | APP | W | r1 | PASS | Checksums are stable; one byte changed in one row changes the parent checksum, and a rollback restores it | 2026-10-29 |
| CHK-M8-150 | APP | W | r1 | PASS | REQ-198 (1a): `effective_results` returns exactly the scan's 11 results (originals and the retry), ordered by agent, job and plugin, each with its agent (a retry result carries the original's agent). A result without re-evaluation has the effective verdict = the original, with provenance None | 2026-10-29 |
| CHK-M8-151 | APP | W | r1 | PASS | Ids base+5 (ERROR, +1 h), base+9 (PASS, −5 h), base+7 (FAIL, +9 h) → effective PASS from base+9 with its `policy_version` 9, user 90 and time; original FAIL beside it | 2026-10-29 |
| CHK-M8-152 | APP | W | r1 | PASS | REQ-198 (1b): A (2,1,1,1) all four kinds; B (2,1,0,0), the retry fills the missing plugins; C (0,0,0,3) queued; D (2,0,0,0), FAIL re-evaluated to PASS; E (0,0,2,0) | 2026-10-29 |
| CHK-M8-153, -154 | APP | W | r1 | PASS | REQ-198 (2), (3): the second scan's job never appears. Its re-evaluation rows (higher ids, same agent and plugins) don't touch scan 1. The second scan alone gives 5 rows and (2,3,0,0) | 2026-10-29 |
| CHK-M8-155 | APP | W | r1 | PASS | A planted duplicate (original and retry both hold a plugin) is counted twice, (1,1,0,1), not hidden. A queued retry's plugins are not run once each, not twice | 2026-10-29 |
| CHK-M8-157 | APP | W | r1 | PASS | Unknown scan → `[]` for both. A scan with no jobs → `[]`. Jobs and no results → no rows, and counts (0,0,0,2) plus (0,0,0,0) for an empty payload | 2026-10-29 |
| CHK-M8-158 | APP | W | r1 | PASS | REQ-198 (5): `EXPLAIN (ANALYZE, FORMAT JSON)` of both statements has exactly one node on `scan_result_reeval`, `Actual Loops` = 1, and no SubPlan above it | 2026-10-29 |
| CHK-M8-159 | APP | W | r1 | PASS | Each function issues exactly one statement (`WITH … SELECT`), with no write or row-lock word, and the scan id bound as a parameter (not in the SQL text) | 2026-10-29 |
| CHK-M8-160 | APP | W | r1 | PASS | Agent A's inventory job adds no host | 2026-10-29 |
| CHK-M8-348 (SQL) | APP | W | plants: `reeval_id ASC`; `reevaluated_at DESC` | PASS (red) | 2 / 2 failed: highest-id row, host counts | 2026-10-29 |
| CHK-M8-349 | CODE | W | plant: an f-string query appended to `results.py` | PASS (red) | ruff `S608`, exit 1 | 2026-10-29 |
| CHK-M8-351 | APP | W | plant: `LEFT JOIN LATERAL (… FROM scan_result_reeval … LIMIT 1)` per result | PASS (red) | 2 failed: the EXPLAIN rows (`Actual Loops` > 1) | 2026-10-29 |
| CHK-M8-352 | APP | W | plants: counts ignore retry results; planned without DISTINCT and with retries | PASS (red) | 2 failed (B (2,0,0,2)) / 3 failed (retry plugins counted twice) | 2026-10-29 |
| extra x182-scanfilter / x182-kind | APP | W | plants: no scan filter; inventory jobs included | PASS (red) | 7 / 6 failed | 2026-10-29 |

## Acceptance (TASK-182 row)

REQ-198 (1)–(5) → the rows above; (4) is the S608 plant. The REQ-197 (3) property is in TASK-184.

## Notes (no defect)

- Impl note (3) confirmed: an original job with an empty `plugins` list gives its agent (0,0,0,0) rather than dropping it.
