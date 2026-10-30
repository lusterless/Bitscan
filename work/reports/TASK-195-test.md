# TASK-195 TEST: PASS (r1; round 1 FAIL)

Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-215, REQ-216, REQ-217, REQ-230; TS §4.4 L568–L570, L575, L577, L578, L582, §4.5 L587, §5.2 L892–L913, L1011; #124 (c), #127 (a), (f). Code under test: `bm/repositories/job_intake.py` (impl-manager-m9b, `work/reports/TASK-195-impl.md`, incl. r1). Test file: `manager/tests/test_job_intake_repo_pg.py` (new). Plan rows: CHK-M9-117 to -119.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 (round 1) | `pytest tests/test_job_intake_repo_pg.py` | **18/20 passed, 2 failed**, 0 errors, 0 skipped |
| r1 service | `pytest tests/test_intake_pg.py` (TASK-199, same defect end to end) | 26/27 passed, 1 failed |
| re-run after r1 | the 3 failing node ids (below) | **3/3 passed** |
| r2 (r1 tree) | `pytest tests/test_job_intake_repo_pg.py` in the W1 batch | **20/20 passed**, 0 skipped; 0 containers left |
| plants | 7 (6 pytest, 1 ruff) in throwaway copies | 7/7 red |

## Round 1 failure (fixed in r1)

- `test_sibling_is_the_other_job_of_the_unit[completed-running-orig-retry]` and `[completed-completed-orig-retry]`: expected `(retry_id, retry_created_at)`, got `None`.
- End to end: `test_intake_pg.py::test_a_completed_original_still_sees_its_retrys_results`. The original failed and got a retry; the retry stored p2; a late batch to the original stored p1, so the original became `completed`. p2 posted again to the original was then **stored a second time** (`count == 2` in the unit). It should have been a duplicate.
- Diagnosis: `sibling()` searched `retry_of` only for `failed`/`partial` originals. But a late batch can move such an original to `completed` while its retry exists (TS §4.4 L577, L582), so TS §4.4 L578 ("skipping plugins that already have a result in the original job or its retry") broke. r1 searches for every original in `failed`, `partial` or `completed` (decisions "First result wins includes completed originals").

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-117 | PASS | `lock_unit(retry)` returns the posted job with payload, `eval_spec`, ids, state and times; unknown → None. For each of (orig, retry), (retry, orig), (retry, retry), (orig, orig), a second session locking a job of the same unit **waits** (pg_locks probe) until the first ends; a job of another unit does not wait |
| CHK-M9-118 | PASS | 3 rows in **one** INSERT (statement spy); stored exactly as given (verdict fields, streams, flags, the four snapshots, item times), `job_created_at` = the job's, `received_at` = the argument, `result` generated (PASS/FAIL/ERROR); `[]` → 0 with no SQL. An `IntakeJob` with `created_at` shifted by 1 µs is refused by the TS §5.2 trigger and stores nothing. `result_uuids` covers exactly the given (job, created_at) pairs |
| CHK-M9-119 | PASS | `start`: dispatched → running with `started_at`/`deadline_at`; a second call → False, unchanged; a failed (never-started) job is not started. `set_state`: running → completed, failed → partial, partial → completed (with `finished_at`); completed/expired/cancelled → False and unchanged; `failed`, `queued`, `cancelled`, `expired`, `dispatched` → `ValueError`; only progress columns change. `sibling`: 10 rows, incl. the two completed-original rows above (r1) |
| CHK-M9-320 | PASS (red) | plant: no `FOR UPDATE` on the job and the root → 5 failed (4 serialise rows + the 200-round race) |
| CHK-M9-321 | PASS (red) | plant: the root lock skipped for a retry → 3 failed (the serialise rows that post to the retry; the race) |
| CHK-M9-322 (repo) | PASS (red) | plant: `sibling` always None → 10 failed (sibling rows + intake first-result rows) |
| extra 322-fp | PASS (red) | plant: lookup restricted back to failed/partial (lead's ask) → 3 failed (2 sibling rows + the end-to-end row) |
| CHK-M9-334 (repo) | PASS (red) | plant: `start` guards dropped → 1 failed (start row) |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

## Acceptance (TASK-195 row)

A second session locking the same root waits → CHK-M9-117. N rows insert in one statement with `job_created_at` accepted by the trigger → CHK-M9-118. `started_at` and `deadline_at` are written only while NULL → CHK-M9-119. G1 red on a planted f-string → CHK-M9-376. The race suite (TASK-199) finishes with no deadlock.

## Notes

- The r1 docstring now states the right reason (a completed original can have a retry).
