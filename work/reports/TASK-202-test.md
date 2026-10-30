# TASK-202 TEST: PASS (r1)

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-218, REQ-219, REQ-228, REQ-229, REQ-210 (end to end); TS §3.3 L218, §4.4 L575, L577, L579–L582, §4.1 L530, §3.4 L244, §8.4 L1291; #18, #66, #126, #127 (a)–(f); REQ-078 (5). Code under test: `bm/services/scheduler/sweep.py` (impl-manager-m9, `work/reports/TASK-202-impl.md`), on TASK-186/187/189 (tester-m9), 194, 196. Test files: `manager/tests/test_sweep_compliance_pg.py` (new); `manager/tests/test_sweep.py` updated under decisions "M9 builder rulings" (PD-40's rule): old **CHK-M3-185** "4 commits / 3 + 1" → new **CHK-M9-217** "7 commits / 6 + 1". A fake `ComplianceRepos` with no candidates records the three new steps' calls (24 h never-started window asked); every other assertion is unchanged. Plan rows: CHK-M9-204 to -214, -216, -217.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_sweep_compliance_pg.py tests/test_sweep.py` | 14/15 + 10/10. 1 failed: **test bug** (my expired-count assertion counted only my job; earlier tests' retries expire too) |
| re-run | that node id after the fix | **1/1 passed** |
| r2 | both files in the 8-file batch | **15/15** and **10/10 passed**, 0 skipped; 0 containers left |
| M3 | `tests/test_sweep_pg.py`, `tests/test_metrics_api_pg.py` (with the M3 batch) | green (G33) |
| plants | 11 | 11/11 red |
| r1 | `pytest tests/test_sweep_compliance_pg.py tests/test_sweep.py tests/test_queue_scan_race_pg.py` on the r1 tree (per-job savepoints) | **33/33 passed** (sweep 18 incl. the 3 new rows, `test_sweep.py` 10, queue race 5), 0 skipped; 0 containers left |
| r1 plant | per-job savepoint dropped | red: 2 failed (the poison `eval_spec` row: the bad job ended `failed` without a retry; the fault row) |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-204 | PASS | at the deadline exactly: nothing. 1 µs later: 2 of 5 results → `partial` (`finished_at` now) + one retry with plugins 1, 3, 5. No result → `failed` + a retry with all 5. Each retry is the TS §6.5 body (job_id = row, original commands and patterns, `pickup_by` now + 24 h), with the matching `eval_spec` entries, `retry_of`, `queued`. A second sweep makes none. Every result by the deadline → `completed`, no retry |
| CHK-M9-205 | PASS | dispatched at D, never started: at D + 24 h nothing; D + 24 h + 1 s → `failed` (`started_at` NULL) + a retry with all plugins |
| CHK-M9-206 | PASS | a retry past its deadline → `failed` (or `partial` with a result), no retry of it; a dispatched retry that never started → `failed`, none; an original `partial` by a final batch is not a candidate (no retry) |
| CHK-M9-207 | PASS | two sweeps at one barrier over 10 jobs → exactly 10 retries in total, one per job, no failed step; 20 rounds of a sweep and a post to one retry: no error, no failed step, each result stored once, no retry of the retry, the retry `completed` |
| CHK-M9-208 | PASS | deleted policy, decommissioned agent → `failed`, no retry; a disabled policy → retry made (#18) |
| CHK-M9-209 | PASS | REQ-210 (1), (2) end to end: after an import changed plugin 3's Execute (timeout 99) and the redaction setting changed, the retry holds 1, 3, 5 with the original command, timeout and patterns and the original's three `eval_spec` entries |
| CHK-M9-210 | PASS | a fault in `insert_retry` rolls back that job's ending too (r1: its savepoint): the job stays `running` with no retry, never `failed` without one; the next sweep → `failed` + 1 retry |
| r1 poison row | PASS | one past-deadline job with an unreadable `eval_spec`, or with a payload that has no `plugins` (written as owner), next to a normal past-deadline job and a never-started job. The sweep raises nothing, `failed_steps == []`. The bad job is byte-identical (still running, no retry) and logged once as `sweep job failed` with exactly `{step, job_id, exc_type}`. The two normal jobs end `failed` and get their retries in the same sweep |
| REQ-228 (2) | PASS | with compliance jobs and results present for 10 eligible agents (1 offline): `agents_offline` once with `offline` 1, `eligible` 10. `inventory_stale` names exactly the online agent whose `last_inventory_at` is older than twice the inventory interval. Compliance results do not count as inventory |
| CHK-M9-211 | PASS | an inventory job 31 min after dispatch → `failed`, never retried; a queued compliance job past `pickup_by` → `expired`; `bitscan_jobs_expired_total` grows by exactly the step's count; with the deadline step failing, `failed_steps == ["compliance_deadline"]` and the other steps and the scan refresh still apply (the all-expired scan → `failed`) |
| CHK-M9-212 | PASS | all completed → `completed` + `finished_at`; completed + expired → `partial`; all expired → `failed`; completed + failed → `partial`, then the failed job's late result → `completed` at the next sweep with `finished_at` unchanged; M7's delete cancelling the last queued jobs → `cancelled` (no results) / `partial` (some), with `finished_at`; no scan `dispatched`/`expired` |
| CHK-M9-213 | PASS | the refresh step reads `scan_job` in **one** statement (spy) with one `unit_facts` call; a completed scan and a finished scan created 9 days ago are not among its ids; an unchanged scan is not written; `scans_refreshed` = UPDATEs = written scans |
| CHK-M9-214 | PASS | REQ-228 (1): a compliance job queued 2 h for an offline agent → no `job_queue_age`; for an online agent → one alert in the hour (second run 10 min later: none) |
| CHK-M9-216 | PASS | across a sweep that ends, retries and refreshes, every earlier job's payload, `eval_spec`, agent, scan and `retry_of` are byte-identical |
| CHK-M9-217 | PASS | `test_sweep.py` 10/10 (seven steps; each of the 7 failing alone rolls back alone) |
| CHK-M9-341 | PASS (red) | retry of a retry allowed → 7 failed (the step errors) |
| CHK-M9-342 | PASS (red) | partial jobs as candidates, the re-check widened, `end_job`'s answer ignored → 5 failed |
| CHK-M9-343 | PASS (red) | retry holds every plugin → 2 failed |
| CHK-M9-344 | PASS (red) | retry commands from the current catalog → the CHK-M9-209 row |
| CHK-M9-345 | PASS (red) | retry failure swallowed (as if a separate transaction) → the fault row |
| CHK-M9-339 / -340 / -346 / -363 / -377 | PASS (red) | repo plants also run on this file |
| extras | PASS (red) | retry for a deleted policy / decommissioned agent; unchanged scans written → 1 failed each |

## Acceptance (TASK-202 row)

REQ-218 (1)–(8) → CHK-M9-204 to -211; REQ-219 (1)–(5) → -212, -213; REQ-228 (1) → -214; REQ-228 (2) → the compliance-present row (added at the reviewer's request); REQ-229 (1), (2) → -211 and the M3 G33 suites green (scan-cancel effect on inventory: TASK-198/200).
