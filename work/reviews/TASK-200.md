# TASK-200 REVIEW: cancel service `cancel_scan()`

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-219, REQ-220, REQ-227. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-200-impl.md`: one new file, `manager/bitscan_manager/services/jobs/cancel.py` (51 lines). The impl report's open point (an entry for a no-op cancel) is settled by decisions 2026-10-30 "M9 builder rulings" (2): one entry per call, including `{cancelled_jobs: 0}`. The code does exactly that.

TEST: PASS (`work/reports/TASK-200-test.md`). 7/7 after a test fix (the race needed a 2-plugin policy), including a 20-round cancel-versus-post race with no deadlock. 4 plants are red: CHK-M9-359, -360, the derive step dropped, and job ids leaking into the detail.

Spec read: TS §4.4 L573, L579–L581, §6.2 L1122; #122 (g), #127 (d), (e), #129 (a).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suite runs on W.

## Checks
1. **Manager-side only (TS §4.4 L581, security invariant "no push").** There is no outbound call. A cancelled queued job is never pulled, and posts for cancelled dispatched or running jobs are refused with `own_cancelled=True`, so they don't count toward the flood (#124 (f), CHK-M9-185).
2. **Scope.** Only the scan's `queued`, `dispatched` and `running` compliance jobs change, originals and retries. Ended jobs, other scans and inventory jobs are byte-identical (CHK-M9-182, REQ-229).
3. **State at once (#127 (d), (e)).** The scan is derived in the same transaction after the cancel. No results gives `cancelled`; results give `partial`, or `completed` when every unit was complete. `finished_at` is set once, and a repeat cancel doesn't move it.
4. **Lock order.** It locks the scan row, then the open jobs. Intake and the sweep's job steps never lock a scan row. The sweep's `scan_states` step locks scan rows but no job rows, in a transaction of its own. So no cycle exists, and the barrier race confirms it.
5. **Audit (#129 (a), ruling (2)).** One `scan.cancel` per call, target `scan:<id>`, detail exactly `{cancelled_jobs}`. The chain verifies, and an unknown scan writes nothing.

## Findings
None blocking or should-fix.
