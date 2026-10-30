# TASK-203 REVIEW: scheduled runs and the scheduler tick (design note D4)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-225, REQ-227. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-203-impl.md` (with r1):
- `manager/bitscan_manager/services/scheduler/scan_schedules.py` (new, 155 lines);
- `manager/bitscan_manager/services/scheduler/runner.py` (+30/−9).

TEST: PASS including r1 (`work/reports/TASK-203-test.md`). 11/11 plus 16/16 runner, including the r1 tick-versus-delete race. Plants CHK-M9-370, -371, -372, -373 and 203r1 are red. Under PD-40 rule (3), CHK-M3-230 is replaced by CHK-M9-218 and CHK-M3-233-r1 by CHK-M9-219. `test_serve_scheduler_linux.py` runs at the gate (G18).

Spec read: TS §4.4 L557, §4.3 L550, §2.1 L103; #3, #128 (d)–(g); decisions 2026-10-30 "M9 builder rulings" (4), (5).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suites run on W.

## Checks
1. **TS §4.4 L557 rules.**
   - The cron is read in the schedule's zone (Kolkata 03:30 UTC, CHK-M9-199).
   - No back-fill: a due time more than 2 minutes old is `missed` and `next_run_at` moves into the future (CHK-M9-197).
   - Skipped and logged when the previous scan is unfinished or the policy is disabled, plus `no_target_agents` (#3) and `policy_has_no_plugins` (ruling (4)).
   - Users can disable schedules, and a disabled schedule never runs.
2. **Once per due time (#128 (e)).** One transaction per row, taken by `due()` `FOR UPDATE SKIP LOCKED`. `next_run_at` always moves strictly past `now`, so the loop ends within the tick. Two ticks at a barrier make one scan (CHK-M9-198).
3. **r1, no deadlock with a policy delete (ruling (5), TS §4.3 L550).**
   - The tick holds the schedule row, so it takes the policy with `try_share_policy` (`SKIP LOCKED`) and never waits.
   - A held policy gives `busy`: nothing is written and the row is retried next tick (a missed run once more than 2 minutes late).
   - `queue_scan`'s own `FOR SHARE` is then already held.
   - I checked the other lock holders for a cycle and found none:
     - a manual scan (advisory lock, then a share that is compatible with the tick's share);
     - an enabling PATCH (policy share, then schedule row, which waits on the tick and needs nothing the tick waits for);
     - M7's delete (policy, then schedule, which waits on the tick's share).
4. **Refusals contained.** `queue_scan` runs in a savepoint, so a refusal undoes only the attempt and the bookkeeping still commits. Any other exception rolls back that row only, which is logged by `schedule_id` and exception type and retried next tick. One bad row can't block the others (CHK-M9-200). A bad stored cron, zone or target gives `invalid`, retried a day later, and the schedule is not disabled.
5. **What a scheduled scan records (#128 (g)).** `trigger = 'scheduled'`, `schedule_id`, `requested_by` NULL, actor `system`, one `scan.create`, and never the API-token alert, even for `{"all": true}` (CHK-M9-195).
6. **Runner (REQ-225 (8), builder checklist item 10).** A third job every 30 s, `max_instances=1`, through `_guarded` and the stoppable database. `stop()` waits for a running tick, and three worker threads keep a long sweep from starving the tick. No `system_schedule` row is added (no migration).
7. **Logs.** Skips and failures carry only `schedule_id`, the reason word and the exception type. No canary appears (CHK-M9-196).

## Findings
None blocking or should-fix.

1. nit, `scan_schedules.py:137-148`: a row that fails every tick (for example `UnstorableText` from a corrupted catalog row) logs an error every 30 s until fixed. That's acceptable (it's visible and doesn't block others). Unlike `invalid`, it isn't backed off. No change required.
