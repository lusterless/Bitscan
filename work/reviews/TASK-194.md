# TASK-194 REVIEW: scan progress repository

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-219, REQ-220, REQ-230. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-194-impl.md`: one new file, `manager/bitscan_manager/repositories/scan_progress.py` (134 lines). It imports the pure `Unit` from TASK-187, so the facts and `derive()` share one shape.

TEST: PASS (`work/reports/TASK-194-test.md`). 6/6, and the fixture self-test is 5/5. Plants CHK-M9-359, -363, -361 (repository side, which closes TASK-187's NOT RUN row) and -376 are red.

Spec read: TS §4.4 L573, L579–L581, §5.2 L1012; #127 (d)–(f).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suite runs on W only.

## Checks
1. **Unit facts (#127 (d)).**
   - One statement and one read of `scan_job` (no `scan_id` index, #127 (f)).
   - Units are grouped by `COALESCE(retry_of, job_id)`. `complete` compares the original's payload plugins with the distinct results across the unit, so an original `partial` plus a completing retry counts as one complete unit. Results are joined on `job_created_at`, so partitions are pruned.
   - Grouping by `job_id` instead is red (CHK-M9-361).
2. **Refresh candidates (#127 (f)).** Unfinished scans, plus non-completed scans created within 8 days (the 7-day late window plus 24 h pickup). Finished non-completed scans stay candidates, so late results still move them (CHK-M9-363).
3. **Scan update (#127 (e), TS §5.2 L1012).**
   - Only `state` and `finished_at` are written. `finished_at` uses `COALESCE`, so it is set once and never moved or cleared. Unchanged rows aren't written.
   - `dispatched`, `expired` and unknown states are refused before the SQL (`jobs-and-scans.md:37`).
   - Could a finished scan be reopened (finished_at kept, state back to `running`)? A retry is only ever created in the same transaction that ends its original (TASK-196 and 202), so the refresh never sees a closed unit reopen.
4. **Cancel (TS §4.4 L581).** One UPDATE of the scan's `queued`, `dispatched` and `running` compliance jobs, originals and retries. Inventory jobs and other states are untouched. The lock argument holds: a unit has at most one open job, so this UPDATE holds at most one row per unit and can't form a cycle with intake's root-then-job order.
5. **SQL safety.** Literal statements with parameters. S608 is red on the plant.

## Findings
None blocking or should-fix.
