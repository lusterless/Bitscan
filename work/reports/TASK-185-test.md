# TASK-185 TEST: PASS (revision 1)

Tester: tester-m8, 2026-10-29. Full rigor. REQ-200 (1)–(9), REQ-201 (1)–(5), REQ-202 (2), REQ-204 (2); TS §4.5 L601, §2.2 L114, §5.2 L929–L938, L1005–L1006, §5.3 L1049; #12, #118 (a)–(h), #119. Rulings applied (2026-10-29): NULL stdout fails closed; "Re-evaluation fails closed on an unrecognised stored ERROR detail"; order: intake detail → unknown ERROR detail → NULL stdout → `classify()`. Code under test: `bm/services/evaluator/reevaluate.py` r1 over `bm/repositories/reeval.py` r1 (impl-manager-m8b, `work/reports/TASK-185-impl.md`, "Revision 1"). New test files: `manager/tests/test_reevaluate_pg.py` (own migrated container, so the audit chain check sees only this module's writes), `manager/tests/test_reevaluate_race_pg.py`. Plan rows: CHK-M8-190 to -201, -210 to -214, -222.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, PostgreSQL 16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_reevaluate_pg.py tests/test_reevaluate_race_pg.py` | 30/38 passed, 8 failed: a **test bug** (mine): `make_job(state="succeeded")` is not a `scan_state` value (TS §5.2: `completed`) |
| r1 re-run | `pytest tests/test_reevaluate_pg.py` (the 8 failures were all in this file; the race file was 7/7 in r1) | **31/31 passed**, so **38/38** overall, 0 skipped, 0 containers left |
| all M8 | the 14 M8 test files together | **1,345/1,345 passed**, 0 skipped |
| plants | 16 plants (15 in one batch, plus the race form of -354) | 16/16 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on both files | clean |

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-190 | APP | W | r1 re-run | PASS | REQ-200 (1): 6 results (PASS, FAIL, `stdout not numeric`, `oversize`, `runner_unavailable`, since-dropped) after an import (v2: P2 expected → `y`, P3 operator → `not_empty`, P6 dropped) → `ReevalResult(…, scan_policy_version=1, policy_version=2, rows_added=5, not_in_version=1)`. Rows: P1, P2, P3 → (0, None); P4 → (2, `oversize`), even though `empty` would PASS; P5 → (2, `runner_unavailable`); P6 → none; all v2 and user 4242 | 2026-10-29 |
| CHK-M8-191, -198 | APP | W | r1 re-run | PASS | REQ-200 (2), (9): `scan_result` checksums (parent and every partition), `scan` and `scan_job` are identical before and after; earlier `scan_result_reeval` rows are unchanged and 5 are appended; the statement spy sees no UPDATE/DELETE/TRUNCATE/MERGE (whole words) | 2026-10-29 |
| CHK-M8-192 | APP | W | r1 re-run | PASS | REQ-200 (3): after a second import (v3), the second run adds 5 more (10 in all). `effective_results` shows run 2's ids, v3 and user 4243 for every re-evaluated result (P1 now FAIL, original PASS beside it); the dropped P6 keeps its original | 2026-10-29 |
| CHK-M8-193 | APP | W | r1 re-run | PASS | REQ-200 (4): one entry with actor `user:4242`, action `scan.reevaluate`, target `scan:<id>`, detail exactly `{policy_id, scan_policy_version: 1, policy_version: 2, rows_added: 5, not_in_version: 1}`; `audit_log` +1 exactly, no `alert` key; `verify_chain` ok | 2026-10-29 |
| CHK-M8-194 | APP | W | r1 re-run | PASS | REQ-200 (5): a deleted policy → `PolicyDeleted`; an unknown id → `ScanNotFound` (the message carries no id). Neither writes a row or an audit entry; `wake` is not called | 2026-10-29 |
| CHK-M8-195 | APP | W | r1 re-run | PASS | REQ-200 (6): chunks forced to 2, the second `insert_reevals` raises after the first chunk really inserted → the exception propagates, with no row, no audit entry and no `wake` | 2026-10-29 |
| CHK-M8-196, -197 | APP | W | r1 re-run | PASS | REQ-200 (7): a scan with no results writes the audit entry (`rows_added` 0) and no row. (8): a disabled policy's scan → 5 rows | 2026-10-29 |
| CHK-M8-200 | APP | W | r1 re-run | PASS | `wake` runs exactly once, after commit (inside it, another session already sees the entry) | 2026-10-29 |
| CHK-M8-199, -201, r1 rows | APP | W | r1 re-run | PASS | 19 stored rows under `empty`. Intake details kept (`oversize`, `spool_overflow`, `runner_unavailable`, also with NULL stdout: the intake detail wins). An ERROR with NULL, `' Oversize '`, `'OVERSIZE'`, `'oversize '` or unknown detail → `cannot evaluate`, never PASS. NULL stdout with code 0 or 1 → `cannot evaluate`. Known details re-classified on the stored values: `timed out` (timed_out), `stdout truncated`, `not found` (127) stay ERROR; `cannot evaluate`/`stdout not numeric` with stdout `""` → PASS; FAIL `x` → FAIL. None raises | 2026-10-29 |
| CHK-M8-222 | APP | W | r1 re-run | PASS | REQ-202 (2): with the canary in stdout, stderr, expected and a pattern, caplog at DEBUG over a run, `effective_results` and a `PolicyDeleted` run: the canary is in no log message or args, no exception, no audit detail and no re-evaluation row; the details are only #112 constants. `reevaluate.py` holds no `logging`/`print(` | 2026-10-29 |
| CHK-M8-210 | APP | W | r1 | PASS | REQ-201 (1): A pauses after reading its definitions (v1, holding the lock); an import commits v2; B starts and waits on the advisory lock (`pg_locks` probe) and has no result; A is released. Both commit: A's 6 rows v1/FAIL, B's 6 rows v2/PASS, `min(B ids) > max(A ids)`; every effective verdict is B's (PASS, user 2, v2) | 2026-10-29 |
| CHK-M8-211 | APP | W | r1 | PASS | REQ-201 (2): an import committing after `lock_scan` → every row v2/PASS; after `current_definitions` → every row v1/FAIL; and between the first `FROM policy` statement and the rest → still consistent. No row records one version while using the other's definitions | 2026-10-29 |
| CHK-M8-212 | APP | W | r1 | PASS | REQ-201 (3): a result stored by another session after the first chunk was read and before the commit gets no row (`rows_added` 1); the next run includes it (2, the late one FAIL) | 2026-10-29 |
| CHK-M8-213 | APP | W | r1 | PASS | REQ-201 (4): 20,000 results with 4,000-byte stdout (80 MB if held at once) → `rows_added` 20,000; every insert ≤ 1,000 rows; peak `tracemalloc` < 64 MiB | 2026-10-29 |
| CHK-M8-214 | APP | W | r1 | PASS | REQ-201 (5): B on another scan completes (6 rows) while A is paused holding its own scan's lock | 2026-10-29 |
| CHK-M8-353 | APP | W | plant: an `UPDATE scan_result …` in the run | PASS (red) | 34 failed with `InsufficientPrivilege: permission denied for table scan_result`: the grant refuses it and the tests see the failure (G64, G65) | 2026-10-29 |
| CHK-M8-355 | APP | W | plant: intake step removed | PASS (red) | 6 failed: `oversize` and so on become PASS under `empty` (or `cannot evaluate` when stdout is NULL) | 2026-10-29 |
| CHK-M8-356 | APP | W | plant: rows for dropped plugins | PASS (red) | 5 failed: 6 rows, `rows_added` 6 | 2026-10-29 |
| CHK-M8-357 | APP | W | plant: deleted policy allowed | PASS (red) | 2 failed: DID NOT RAISE `PolicyDeleted` | 2026-10-29 |
| CHK-M8-359 | APP | W | plants: audit entry missing; written in its own earlier transaction | PASS (red) | 3 failed / 5 failed, including the fault row (the entry survived the fault) | 2026-10-29 |
| CHK-M8-360 (service) | APP | W | plant: all chunks merged into one | PASS (red) | 2 failed: the 20,000 row (20,000 > 1,000), the fault row | 2026-10-29 |
| CHK-M8-358 (race) | APP | W | plant: lock replaced by `concat(…)` | PASS (red) | 1 failed: "B is not waiting on the lock" | 2026-10-29 |
| CHK-M8-354 (race) | APP | W | plant: version read in its own statement and then used (two replacements) | PASS (red) | 1 failed: `test_import_inside_the_definitions_read_never_mixes_versions`, a row recording v1 with v2's PASS. (The batch's one-replacement variant left the version taken from the combined statement, so it changed nothing and stayed green, as expected; the repository half of -354 is red in TASK-183.) | 2026-10-29 |
| CHK-M8-362 (service) | APP | W | plant: `logging…warning("re-evaluating %s", row.stdout)` | PASS (red) | 3 failed: the canary row, the no-logging row, and the memory row (logging every stdout pushed the peak to 341 MB) | 2026-10-29 |
| r1 order swap | APP | W | plant: NULL stdout checked before intake | PASS (red) | 2 failed: NULL + `oversize`/`spool_overflow` → `cannot evaluate` | 2026-10-29 |
| r1 drop step 2 | APP | W | plant: the unknown-detail step off | PASS (red) | 5 failed: NULL, `' Oversize '`, `'OVERSIZE'`, `'oversize '` and unknown ERRORs PASS under `empty` | 2026-10-29 |
| r1 COALESCE | APP | W | plant: `COALESCE(r.stdout, '')` in the repository | PASS (red) | 2 failed: NULL-stdout PASS/FAIL rows become PASS | 2026-10-29 |
| extra x185-wake-early / x185-version | APP | W | plants: `wake()` inside the transaction; the scan's version recorded instead of the current one | PASS (red) | 1 / 4 failed | 2026-10-29 |

## Acceptance (TASK-185 row)

REQ-200 (1)–(9) → -190 to -198 (and -199 to -201); REQ-201 (1)–(5) → -210 to -214; REQ-202 (2) → -222; REQ-204 (2) → -191, -198. Every security row (S: -353, -354, -355, -358, -359, -362) has a plant that went red. The coordinator's must-hold rows (NULL/unknown/case or whitespace intake values fail closed and never PASS; `timed out` re-classified; intake details kept; NULL stdout + intake detail keeps the intake detail) and both requested plants (order swap, drop step 2) are in the r1 rows.
