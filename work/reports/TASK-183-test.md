# TASK-183 TEST: PASS (revision 1)

Tester: tester-m8, 2026-10-29. Full rigor. REQ-200, REQ-201 (lock, one statement, chunks), REQ-204 (1); TS §4.5 L601, §5.2 L994–L1006; #118 (f), (h). Code under test: `bm/repositories/reeval.py` r1 (impl-manager-m8b, `work/reports/TASK-183-impl.md`, "Revision 1": `StoredResult.eval_code`; NULL stdout kept as None). New test file: `manager/tests/test_reeval_repo_pg.py`. Plan rows: CHK-M8-170 to -176, -225.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_reeval_repo_pg.py` | 39/40 passed, 1 failed: `test_no_update_delete_or_row_lock`. A **test bug** (mine): the substring `TRUNCATE` matched the column `truncated` |
| r1 re-run | `pytest "tests/test_reeval_repo_pg.py::test_no_update_delete_or_row_lock"` (whole-word check) | **1/1 passed**, so the file is **40/40** |
| plants | 8 plants (7 pytest, 1 ruff) | 8/8 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-170 | APP | W | r1 | PASS | As `bitscan_app` with only the TS §5.2 grants: `lock_scan` returns `ScanRef(scan, policy, 3)` (the scan's version, not the policy's 4); None for an unknown scan; `RuntimeError` in autocommit | 2026-10-29 |
| CHK-M8-171 | APP | W | r1 | PASS | After an owner "import" (v2, a changed expected, a changed operator, a dropped plugin): version 2, not deleted, exactly the two listed plugins with their current (operator, expected); a read-only mapping. Deleted → `deleted` True; no listed plugins → `{}` with v2; unknown → None. A statement spy sees exactly 1 SELECT | 2026-10-29 |
| CHK-M8-172 | APP | W | r1 | PASS | (2,500, chunk 1,000), (2,500, 3), (50, 1): every chunk ≤ size, only the last short, each result exactly once; `pg_cursors` shows the server-side cursor during iteration. Values carried: stdout (NULL kept as None, r1), exit code, flags, original `eval_code` and `eval_detail`. Retries are included (also across partitions); other scans and inventory jobs are excluded; an unknown scan gives none; `chunk=0` → `ValueError` | 2026-10-29 |
| CHK-M8-173 | APP | W | r1 | PASS | N = 0, 1, 7, 1,000: returns N and adds exactly N with the given version 42, user 77, codes and details; `reevaluated_at` is the column default (`now()` of the transaction) | 2026-10-29 |
| CHK-M8-174 | APP | W | r1 | PASS | Two sessions on one scan: the second waits (`pg_locks` advisory, not granted, polled at 20 ms) until the first commits. Two scans don't wait. The lock is released at rollback | 2026-10-29 |
| CHK-M8-175 | APP | W | r1 re-run | PASS | All four functions: verbs only SELECT/INSERT, no UPDATE/DELETE/TRUNCATE/MERGE (whole words) and no `FOR UPDATE`/`SHARE`/`NO KEY`/`KEY SHARE`; 5 statements in all (lock 2, definitions 1, cursor 1, insert 1) | 2026-10-29 |
| CHK-M8-225 | APP | W | r1 | PASS | REQ-204 (1): as `bitscan_app`, `UPDATE … SET eval_code`, `UPDATE … WHERE false`, `DELETE`, `DELETE … WHERE false` and `TRUNCATE` on `scan_result` (parent), the current-month partition, `scan_result_default` and `scan_result_reeval` all raise `InsufficientPrivilege` (20 rows). The app has SELECT on the 7 tables read, and INSERT but no UPDATE/DELETE on `scan_result_reeval` | 2026-10-29 |
| CHK-M8-350 | CODE | W | plant: an f-string `DELETE` query in `reeval.py` | PASS (red) | ruff `S608`, exit 1 | 2026-10-29 |
| CHK-M8-354 | APP | W | plant: an extra version-only statement before the definitions read | PASS (red) | 2 failed: one-statement spy (2 ≠ 1), statement count (6 ≠ 5). The race form is in TASK-185 | 2026-10-29 |
| CHK-M8-358 | APP | W | plant: the advisory lock replaced by `concat(…)` | PASS (red) | 1 failed: "not waiting" | 2026-10-29 |
| CHK-M8-360 | APP | W | plant: `fetchall()` | PASS (red) | 3 failed: every chunk-size row | 2026-10-29 |
| extra x183-session-lock | APP | W | plant: `pg_advisory_lock` (session level) | PASS (red) | 1 failed: release at rollback | 2026-10-29 |
| extra x183-coalesce | APP | W | plant: `COALESCE(r.stdout, '')` (the r1 plant) | PASS (red) | 1 failed: `'' is None` | 2026-10-29 |
| extra x183-noretry / x183-ownerpolicy | APP | W | plants: retries skipped; plugins by `owner_policy_id` instead of `policy_plugin` | PASS (red) | 1 / 2 failed | 2026-10-29 |

## Acceptance (TASK-183 row)

The functions work with only the TS §5.2 grants → -170 to -173, -225. One statement → -171. Chunks ≤ size and each result once → -172. Inserting N adds N → -173. Two sessions serialise and two scans don't → -174. S608 plus a planted f-string → -350.
