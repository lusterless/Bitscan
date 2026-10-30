# TASK-201 REVIEW: schedule management service

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-224, REQ-227. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-201-impl.md` (with r1): one new file, `manager/bitscan_manager/services/scheduler/schedules_admin.py` (212 lines, about 150 of them code). The r1 change applies ruling (5) of decisions 2026-10-30 "M9 builder rulings" (`FOR SHARE` on create and enable).

TEST: PASS including r1 (`work/reports/TASK-201-test.md`). 26/26 after a test-helper fix, including the r1 race against M7's real delete for both create and enable. 5 plants are red.

Spec read: TS §6.2 L1124, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), (h), (i), #129 (a).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suite runs on W.

## Checks
1. **Validation before any write (builder checklist item 1).**
   - The name is 1–128 characters with no U+0000 or lone surrogate. The target goes through `parse_target`, and the cron and time zone through `parse_schedule`. `enabled` must be a bool.
   - Each value's type is checked again behind the route model.
   - Messages name the field only. All 18 bad fields are refused on both create and PATCH with nothing written (CHK-M9-189).
2. **Deleted versus disabled policy (#122 (h), TS §4.3 L550).** A deleted policy gives 409 on create and on enable, a disabled one is accepted, and an unknown one gives 404. With r1's `FOR SHARE`, a racing delete either commits first (409) or waits and then disables the new schedule. The race row and its plant prove it.
3. **Lock order.** An enabling PATCH takes the policy share lock first, then the schedule row, which is M7's delete order (policy, then schedules). The other PATCH paths and delete lock only the schedule row. The tick (TASK-203) uses SKIP LOCKED on the policy. No cycle.
4. **`next_run_at` (#128 (d)).** It is the next fire strictly after now, recomputed on create, on a cron or time-zone change and on enable. Disabling keeps it. A cron-only patch is checked against the stored time zone.
5. **Fixed `policy_id`, any operator (#122 (h), #128 (i)).** `policy_id` and `{}` are refused, and `created_by` is set once.
6. **Audit (#129 (a)).** One entry per change in the same transaction, actor `user:<id>`, target `scan_schedule:<id>`, with the changed fields. A schedule holds no command text.

## Findings
None blocking or should-fix.

1. nit, `schedules_admin.py:132-141, 186-189`: the create and update details carry the full `target`, up to 10,000 agent ids, about 370 KB in one audit entry. That's within #129 (a) ("the changed field names and new values"), but large for the sink. Recording `target_kind` and a count, as `scan.create` does, would keep entries small. No change required unless `main` wants it.
