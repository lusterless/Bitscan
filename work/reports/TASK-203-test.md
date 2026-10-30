# TASK-203 TEST: PASS (incl. r1)

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-225, REQ-227; TS §4.4 L557, §4.3 L550, §2.1 L103; #3, #128 (d)–(g); decisions "M9 builder rulings" (the tick never waits for a policy while it holds its schedule row). Code under test: `bm/services/scheduler/scan_schedules.py`, `bm/services/scheduler/runner.py` (impl-manager-m9b, `work/reports/TASK-203-impl.md`, incl. r1). Test files: `manager/tests/test_scan_schedules_pg.py` (new). Under the ruling's PD-40 rule: `manager/tests/test_scheduler_runner.py` job-set checks, old **CHK-M3-230** `{inventory, offline_sweep}` → new **CHK-M9-218** `{inventory, offline_sweep, scan_schedules}` (30 s, run at start, one instance), plus the failing-run row for `scan_schedules`; and `manager/tests/test_serve_scheduler_linux.py` stop records, old **CHK-M3-233-r1** jobs `(offline_sweep, inventory)` → new **CHK-M9-219** (plus `scan_schedules`). Every other assertion in both files is unchanged. Plan rows: CHK-M9-195 to -202.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_schedules_pg.py tests/test_scheduler_runner.py` (8-file batch) | **11/11** and **16/16 passed**, 0 skipped; 0 containers left |
| serve | `pytest tests/test_serve_scheduler_linux.py` | run at the gate (G18); the change is one allowed job name |
| plants | 5 (370 also on TASK-201's file) | 5/5 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-195 / -202 | PASS | at 03:00 one scan: `scheduled`, the schedule's id, `requested_by` NULL, `queued`, `created_at` = now, the policy version; one `scan.create` by `system` with `trigger` `scheduled` and the `schedule_id`, no alert (even for `{"all": true}`), the alert counter unchanged; `last_run_at` = now, `next_run_at` = the next day 03:00; a tick 30 s later queues nothing |
| CHK-M9-196 | PASS | previous scan unfinished → `previous_unfinished`; disabled policy → `policy_disabled`; tag with no agent → `no_target_agents`; no scan, no audit entry (counts equal); each: `last_run_at` kept (NULL), `next_run_at` → next day 03:00; the skip line carries exactly `{schedule_id, reason}` and no canary from the policy's command or the schedule name |
| CHK-M9-197 | PASS | hourly schedule due 01:00, the clock jumps to 03:00:10 → no scan, `missed`, `next_run_at` 04:00 (future), `last_run_at` NULL; a tick 1 min 59 s late runs; 2 min 1 s late → `missed` |
| CHK-M9-198 | PASS | a disabled schedule never runs over five ticks; two ticks at one barrier (10 rounds, one due schedule each) → exactly one scan per round, no error |
| CHK-M9-199 | PASS | `0 9 * * *` Asia/Kolkata: `next_run_at` 03:30 UTC; nothing at 03:29:59; one scan at 03:30; next 03:30 the day after; nothing at 09:00 UTC |
| CHK-M9-200 | PASS | a row whose run raises → `failed` 1, one record `scheduled run failed` with exactly `{schedule_id, exc_type: ValueError}` and no canary, the row still due; the next tick runs it. `SchedulerRunner` (real BackgroundScheduler, fake tick): job `scan_schedules`, `max_instances` 1; a raising tick is logged by job name and type only; `stop()` returns only after the running 1.5 s tick ended and no tick starts after |
| CHK-M9-201 | PASS | an owner-written row with cron `61 * * * *` → `invalid`, still enabled, `next_run_at` + 1 day, no scan |
| r1 deadlock race | PASS | the tick parks holding its due schedule row; M7's policy delete, started then, locks the policy and waits for that row (probe); released, the tick finds the policy held → `busy` 1, nothing written; the delete completes and disables the schedule; later ticks (30 s, a day) run nothing (no back-fill) |
| CHK-M9-370 | PASS (red) | time zone ignored (UTC) → 5 failed (Kolkata rows here and in TASK-201's file) |
| CHK-M9-371 | PASS (red) | missed check removed (back-fill) → the missed row |
| CHK-M9-372 | PASS (red) | unfinished-previous skip removed → the skip row |
| CHK-M9-373 | PASS (red) | (repo) `SKIP LOCKED` removed → the repo row. At service level two ticks still make one scan: the waiting tick re-checks the updated row (READ COMMITTED), so the repo row is the one that shows it |
| 203r1 | PASS (red) | `try_share_policy` replaced by a plain `FOR SHARE` → the deadlock race row fails (see note) |

## Acceptance (TASK-203 row)

REQ-225 (1)–(8) → CHK-M9-195 to -200. `SchedulerRunner` starts the 30 s tick and still waits for a running job on `stop()` → CHK-M9-200, -218.

## Notes

- 203r1 plant: with the plain `FOR SHARE`, the tick and the delete each wait on the other's row. The race test fails on that run (details in the M9 gate record).
