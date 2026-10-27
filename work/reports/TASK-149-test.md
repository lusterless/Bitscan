# TASK-149 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-160, REQ-166, REQ-173; SR §3.5, §3.6; TS §4.1 L520, §4.2 L540, §5.2; #98 (g), (h), #110. File under test: `bm/repositories/imports.py`. Checks CHK-M7-160 to -164, plants CHK-M7-378 to -380 and extras. Test file: `manager/tests/test_imports_repo_pg.py` (22 tests), as `bitscan_app` on a database of its own.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t149, `CI=true`, `-n 0`) | `pytest tests/test_imports_repo_pg.py tests/test_grants.py` | 47/47 passed (22 + 25 M1 grant probes), 0 failed, 0 skipped |
| r1 (W, label m7t-t147r1) | `tests/test_imports_repo_pg.py` after a **test fix** (the paging walk had no progress bound, so plant 380 looped instead of failing) | 22/22 passed (in the 69/69 run) |
| static (L) | ruff, ruff format, mypy (CI form) | clean |

## Checks

| Check | Result |
| --- | --- |
| CHK-M7-160 every column written, `imported_at` = now; defaults (no version, counts 0, `imported_by` NULL); `errors` (warnings + rejects + a file-level null finding with `é`, backslash, RTL, tab, LF) round-trip in order; `[]` for none; CHECK refuses unknown or mis-cased mode and outcome; a record committed on another connection survives a sibling catalog rollback; on one pinned connection, tx1 rolls back and tx2 keeps the record (D4); the function never commits the caller's transaction | PASS |
| CHK-M7-161 newest-first walk with `limit + 1` for N = 1, 2, 3, 7: every row once, strictly decreasing, our rows in order, cursor always moves; the first page is newest and the keyset is strict; a page row equals the stored row (hostile `file_name`, `errors`, every column) | PASS |
| CHK-M7-162 task insert (user and CLI), get, finish once (a second finish returns False and changes nothing), unknown id; `fail_running_tasks` fails exactly the running rows with result and `finished_at` and leaves succeeded and failed rows alone; a finish racing the start-up fail changes the row once (the UPDATE waits for the row lock and then skips) | PASS |
| CHK-M7-163 `bitscan_app` cannot UPDATE or DELETE `bit_import`, nor DELETE `task`; the M1 grant probes (`test_grants.py`, 25) pass | PASS |
| CHK-M7-164 ruff S608 clean; a planted f-string is red (L113) | PASS |

## Plants (W, throwaway copies)

| Plant | Red |
| --- | --- |
| CHK-M7-379 `fail_running_tasks` without `state = 'running'` | 2 failed |
| CHK-M7-380 keyset `import_id <= cursor` | 5 failed ("cursor did not move", duplicates), after the test fix; before the fix it looped (killed, recorded) |
| `finish_task` without the `running` condition | red (`test_task_insert_get_finish`: a second finish returned True) |
| `ORDER BY import_id ASC` | 6 failed |
| CHK-M7-378 (record on the caller's transaction) | not a repository plant: the function takes the caller's connection and never opens a transaction, so "its own transaction" is TASK-154's duty; the D4 rows above (two rollback cases) are the evidence on this side, and CHK-M7-339 is planted at TASK-154 |

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-160..163 | APP | W | `pytest -q -n 0 tests/test_imports_repo_pg.py tests/test_grants.py` (m7t-t149) | PASS | 47/47 passed (22 + 25) | 2026-10-27 |
| CHK-M7-161-r1 | APP | W | `tests/test_imports_repo_pg.py` after the paging-loop bound (test fix) (m7t-t147r1) | PASS | 22/22 passed | 2026-10-27 |
| CHK-M7-164 | CODE | L | `ruff check`; plant f-string in imports.py | PASS | clean; plant S608 at imports.py:113, exit 1 | 2026-10-27 |
| CHK-M7-379 | APP | W | plant: fail_running_tasks without state filter | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-380 | APP | W | plant: keyset <= | PASS (red) | 5 failed after the test fix (first attempt looped: test bug, killed, fixed) | 2026-10-27 |
| CHK-M7-149-fin | APP | W | plant: finish_task without the running condition | PASS (red) | test_task_insert_get_finish failed | 2026-10-27 |
| CHK-M7-149-asc | APP | W | plant: ORDER BY ASC | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-378 | APP | W | record written on the caller's transaction | NOT RUN (moved) | the repository never opens a transaction; planted at TASK-154 as CHK-M7-339; D4 rollback rows pass here | 2026-10-27 |
