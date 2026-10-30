# TASK-198 REVIEW: queue service `queue_scan()` (design note D1)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-209, REQ-211, REQ-212, REQ-227. High risk, full rigor. **PD-39: the user's second look follows this review** (this task builds the commands every host runs). It is applied under the pre-authorisation on this approval and the clean TEST PASS.

Scope reviewed, per `work/reports/TASK-198-impl.md`:
- `manager/bitscan_manager/services/jobs/queue.py` (new, 138 lines);
- `manager/bitscan_manager/services/audit/alerts.py` (+4: `M9_ALERT_KINDS`, added to the task by decisions 2026-10-30 "M9 builder rulings" (1)).

Ruling (6) of the same row covers the departure from plan §4 (no `settings` parameter; settings are read inside the transaction).

TEST: PASS (`work/reports/TASK-198-test.md`). 8/8 plus the 5/5 race file. Plants CHK-M9-351, -352, -353, -357, -366 (two variants) and -381 are red. In `test_alerts.py` the old CHK-M7 "34 kinds" oracle is replaced by CHK-M9-232 "35 kinds", listed old to new under PD-40 rule (3).

Spec read: TS §2.3 L133, §3.3 L213, §3.5 L248, §4.4 L555–L560, L566, §4.1 L530, §4.3 L547, L550, §6.5, §8.4 L1290; #3, #18, #122 (f), #125, #129 (a), (b).

My re-run: ruff and `mypy --strict` are clean on Windows. The PostgreSQL suites run on W.

## Checks
1. **No ad-hoc command (security invariant, TS §3.3 L213, REQ-212).**
   - `queue_scan` takes no command text. `execute` comes only from `policy_snapshot`, meaning the active plugins of the enabled, non-deleted policy.
   - Every `execute` of every queued job equals an active plugin's command (CHK-M9-160).
   - Disabled (TS §4.4 L559), deleted (#122 (f)) and plugin-less (#125 (h)) policies are refused before any write.
2. **Operator and ExpectedResult never sent (TS §3.5 L248).** The payload has exactly the six TS §6.5 keys, with no evaluation key at any depth (CHK-M9-157). `eval_spec` stays on the row.
3. **One consistent snapshot (#125 (d), TS §4.1 L530, §4.3 L550).** The order is queue lock, policy `FOR SHARE`, one statement. The delete race (CHK-M9-150) never leaves a queued job of a deleted policy, and the import race (CHK-M9-151) gives one version for the command, `eval_spec` and recorded version alike. Two concurrent scans of one policy and agent leave one queued job (CHK-M9-152).
4. **Refusals write nothing (REQ-211 (2)).** All five refusals and `UnstorableText` raise before `insert_scan`, and the counts are unchanged (CHK-M9-154, -158).
5. **Targets (TS §4.4 L555).** Offline agents are included, decommissioned and awaiting agents left out, and `scan.target` holds the request plus the sorted `resolved_agents`. The newer scan cancels older queued jobs, retries included, while dispatched jobs, other policies and inventory jobs are untouched (CHK-M9-155, REQ-229 (2)).
6. **Audit and alert (#129 (a), (b), TS §8.4 L1290).** One `scan.create` per scan with exactly the seven detail keys. There is no target list, `execute` or expected value. With `{"all": true}` and a `bsk_` token, the entry is the alert (`detail.alert`, `bitscan_alerts_total` on commit). A session, a tags target or a scheduled `system` scan gives no alert. A rollback leaves no entry or count. The kind is registered in `ALERT_KINDS` and exported from zero.

## Findings
None blocking or should-fix.

1. Confirmed from the TASK-189 nit: the only `BuiltPlugins` comes from `build.plugins_and_spec`, so the unstorable-text check always runs before `insert_jobs`.
