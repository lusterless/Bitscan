# TASK-196 REVIEW: compliance sweep repository

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-218, REQ-230. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-196-impl.md`: one new file, `manager/bitscan_manager/repositories/job_sweep.py` (186 lines). It goes beyond plan §3 in three justified ways: `SweepJob` carries the times so the state can be re-checked under the lock (builder checklist item 9), `end_job` filters `kind`, and `insert_retry` has guards.

TEST: PASS (`work/reports/TASK-196-test.md`). 9/9. Plants CHK-M9-339, -340, -346, -377 and -376 are red.

Spec read: TS §4.4 L575, L577, §3.3 L218, §5.2 L1011; #124 (c), #126, #127 (b).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suite runs on W only.

## Checks
1. **Strict boundaries (#127 (b)).** A job is past its deadline when `deadline_at < now`, and never started when `dispatched_at < now − 24 h`, measured from `dispatched_at`, not `created_at` (CHK-M9-340). Both checks are compliance only, and inventory jobs keep the M3 step (REQ-229).
2. **Lock order and no waiting (#124 (c)).**
   - The function reads the root with no lock, then takes the root `FOR UPDATE SKIP LOCKED`, then the job (`FOR UPDATE OF j SKIP LOCKED`, so the policy and agent rows aren't locked).
   - This is intake's order, and the sweep never waits, so no deadlock is possible. A held row returns None at once, which the `lock_timeout` probe proves (CHK-M9-121).
3. **Once only (#126 (c), builder checklist item 8).** `end_job` is a conditional UPDATE (`state IN ('dispatched','running')`). The rowcount tells the caller that this sweep ended the job, so two sweeps make one retry (the race gives `[True, False]`).
4. **The retry row (TS §4.4 L577, TS §5.2 L1011).**
   - It is a new queued row with the given payload and `eval_spec`, the original's scan and agent, and `retry_of`.
   - The original's non-progress columns are never written, and a planted `SET payload` surfaces the grant refusal (CHK-M9-377).
   - A retry of a retry is refused before the SQL, and so is a payload whose `job_id` differs from the row's.
5. **Unit results.** The sibling is read only for a retry. That is correct here: a sweep candidate is always `dispatched` or `running`, and such an original cannot have a retry yet. TASK-195's completed-original case doesn't apply.
6. **SQL safety.** Literal statements with parameters. S608 is red on the plant.

## Findings
None blocking or should-fix.
