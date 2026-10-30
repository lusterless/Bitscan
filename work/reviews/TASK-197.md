# TASK-197 REVIEW: schedules repository

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-224, REQ-225, REQ-230. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-197-impl.md` (with r1): one new file, `manager/bitscan_manager/repositories/schedules.py` (196 lines).

TEST: PASS including r1 (`work/reports/TASK-197-test.md`). 9/9. Plants CHK-M9-373, 197r1-share, 197r1-skip and -376 are red.

Spec read: TS §5.2 L846–L857, L864, L1013, §4.4 L557, §4.3 L550; #122 (h), #128 (d), (e); decisions 2026-10-30 "M9 builder rulings" (5).

My re-run: ruff is clean on Windows. The PostgreSQL suite runs on W.

## Checks
1. **CRUD (#122 (h)).**
   - `update` takes column names from a fixed set through `sql.Identifier`, and `policy_id` and `created_by` can never change. An empty or foreign key raises before the SQL.
   - DELETE is granted on `scan_schedule` only, and the FK sets the scans' `schedule_id` to NULL (L864).
   - Paging is by `schedule_id`.
2. **Due rows (#128 (e)).** `enabled AND next_run_at <= now … FOR UPDATE SKIP LOCKED`, so a second tick skips held rows (CHK-M9-373).
3. **Previous unfinished (TS §4.4 L557).** The latest scan by `created_at` decides. `scan` has no `schedule_id` index, which is accepted as a small table.
4. **r1, create versus delete (ruling (5), TS §4.3 L550).**
   - `policy_state(lock=True)` reads `FOR SHARE`, so a racing delete's "disable schedules" sees the new schedule, or the create sees `deleted_at`.
   - `try_share_policy` is `FOR SHARE SKIP LOCKED`, for the tick, which already holds a schedule row. That avoids the cycle: tick holds schedule, waits on policy; delete holds policy, waits on schedule. Both plants are red.
5. **Run bookkeeping (#128 (d)).** `last_run_at` changes only when a scan was queued.
6. **SQL safety.** Literal statements and `sql.Identifier` only. S608 is red on the plant.

## Findings
None blocking or should-fix. Whether the tick calls `try_share_policy` before `queue_scan`'s own policy lock is TASK-203's to show; I'll check it there.
