# TASK-199 REVIEW: result intake service and the plugin results counter

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-214 to REQ-217, REQ-226, REQ-227. High risk, full rigor. **PD-39: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-199-impl.md`: `manager/bitscan_manager/services/jobs/intake.py` (new, 138 lines) and `manager/bitscan_manager/services/audit/metrics.py` (+14). It builds on TASK-186, 190 and 195, M8's `parse_eval_spec` and M3's `read_settings`. `IntakeBatch` is a protocol, so the service imports no API code.

TEST: PASS on TASK-195 r1 (`work/reports/TASK-199-test.md`). The round-1 failure came from TASK-195's sibling bug. r2 gives 28/28 plus the 200-round first-result-wins race (1/1, no deadlock). 17 plants are red: CHK-M9-320, -321, -322, -324, -325, -327, -328, -329, -330 to -333, -374, -375 and others. Two plant variants were dropped with a sound reason (they're covered at repository level, or by the commit-failure test).

Spec read: TS §6.1 L1065, L1071, §4.4 L568–L570, L575, L577, L578, L581, L582, §4.5 L587, L596, L599, L603, §3.3 L222, §8.4 L1288, §8.3 Security; #12, #116 (d), #121, #124, #127 (a)–(c), #129 (c).

My re-run: ruff is clean on `services/jobs/`, and `mypy --strict` is clean on the module. The PostgreSQL suites run on W.

## Checks
1. **Acceptance under the lock (#124 (a), builder checklist item 9).** The job is read by `lock_unit` (root, then job, `FOR UPDATE`). The checks are then decided on the row read under the lock: agent, kind, state, and the 7-day window from `dispatched_at` (not `created_at`, CHK-M9-327). Unknown and foreign jobs both give a plain `job_not_acceptable`, so a job's existence isn't revealed to another agent.
2. **First result wins (TS §4.4 L578, §8.3 Security).**
   - `existing` covers the job and its sibling, and the plan adds in-batch duplicates. The 200-round barrier race stores exactly one row per round, and M8's `host_counts` counts it once.
   - With the root lock planted away, the duplicate shows as M8's double count (CHK-M9-320, -321).
   - The sweep uses the same lock order, with SKIP LOCKED, so there is no deadlock.
3. **Verdict against the queued `eval_spec` (TS §4.5 L587, L603).** An import that changes Execute and ExpectedResult after queueing doesn't change the verdict or the snapshots (CHK-M9-168, -329). An unreadable `eval_spec` fails closed and is logged by exception type only (#124 (h)).
4. **Transitions (REQ-217).**
   - A start notice sets `started_at` and `deadline_at` once, with `max_parallel_plugins` read at that moment.
   - A late batch on `failed` or `partial` moves the job to `partial` or `completed`.
   - `finished_at` is set on every entry into an ended state (#127 (c)).
   - Final states never change.
5. **All or nothing (REQ-214 (6)).** Refusals are raised inside the transaction, so it rolls back. A fault after the INSERT leaves no row and no counter move (CHK-M9-165).
6. **Metric (REQ-226, #129 (c)).** `bitscan_plugin_results_total{result}` has a fixed label set, each label exported from zero, and is incremented through `tx.on_commit` by stored rows only (CHK-M9-374).
7. **No output in logs or audit (REQ-227 (4), TS §5.3 L1052).** The canary through every path appears in no log record or audit detail (CHK-M9-172, -375).

## Findings
None blocking or should-fix.

1. nit, `intake.py:292-294`: the `eval_spec` refusal logs with a `%s` argument. The other M9 and M3 log lines put their fields in `extra={"data": {...}}`, so the structured JSON line carries the exception type as a field. Consider `extra={"data": {"exc_type": type(exc).__name__}}`. Not required.
