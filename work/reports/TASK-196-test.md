# TASK-196 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-218, REQ-230; TS §4.4 L575, L577, §3.3 L218, §5.2 L1011; #126, #127 (b), #124 (c). Code under test: `bm/repositories/job_sweep.py` (impl-manager-m9b, `work/reports/TASK-196-impl.md`). Test file: `manager/tests/test_job_sweep_repo_pg.py` (new). Plan rows: CHK-M9-120, -121.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_job_sweep_repo_pg.py` (W1 batch) | **9/9 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 5 (4 pytest, 1 ruff) | 5/5 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-120 | PASS | Deadline candidates: `deadline_at = now` is not, `now − 1 µs` is; a dispatched job past its deadline is; `now + 1 µs`, completed/partial/failed jobs and an inventory job are not. Never-started: `dispatched_at = now − 24 h` is not, `− 24 h − 1 s` is; a job created 5 days ago but dispatched 1 h ago is not (from `dispatched_at`); a started, a running and an inventory job are not |
| CHK-M9-121 | PASS | `lock_for_sweep(retry)` reads job, root, `retry_of`, scan, agent, payload, `eval_spec`, state, times, and the flags (policy deleted through M7's delete; agent decommissioned); unknown → None; `unit_result_uuids` of a retry covers the retry and its original. With the root or the job held by another session (`FOR UPDATE`), it returns None **at once** (the session has `lock_timeout = 2s`, so a wait would raise), and the lock after release succeeds. `end_job`: first call True (state and `finished_at` only), second False and unchanged; queued/ended/inventory jobs untouched; a non-ending state → `ValueError`; two sessions racing `end_job` give `[True, False]` (the second waits, then re-checks). `insert_retry` writes the given payload/`eval_spec` (job_id = row id), the original's scan and agent, `retry_of`, `queued`, the given times; the original's row is unchanged; a retry of a retry and a payload whose `job_id` differs from the row → `ValueError` before SQL. `UPDATE scan_job SET payload` as `bitscan_app` → `InsufficientPrivilege` |
| CHK-M9-339 | PASS (red) | plant `deadline_at <= %s` → 1 failed |
| CHK-M9-340 | PASS (red) | plant `created_at < %s` → 1 failed |
| CHK-M9-346 | PASS (red) | plant: `end_job` state guard dropped → 2 failed (end-once rows) |
| CHK-M9-377 | PASS (red) | plant: `UPDATE scan_job SET payload` in `end_job` → 2 failed, the grant refusal surfaces (`InsufficientPrivilege`) |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

## Acceptance (TASK-196 row)

Candidates follow the strict boundaries → CHK-M9-120. A root held by another session is skipped; the retry row has the given payload, `eval_spec` and `retry_of`; only progress columns of the original change → CHK-M9-121.

## Notes (no defect)

- `unit_result_uuids` reads the sibling only for a retry. For a sweep candidate that is an original, no retry can exist yet, because a retry is made only when its original leaves dispatched/running. Unlike TASK-195's completed-original case, this holds for the sweep: its candidates are always dispatched or running.
