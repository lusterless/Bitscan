# TASK-193 REVIEW: scan queue repository

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-208 (3), REQ-211, REQ-230. High risk, full rigor. It isn't itself a PD-39 task, but it composes the payload that the PD-39 second look on TASK-189 and 198 covers.

Scope reviewed, per `work/reports/TASK-193-impl.md`: one new file, `manager/bitscan_manager/repositories/scan_queue.py` (215 lines).

TEST: PASS (`work/reports/TASK-193-test.md`). 15/15 (fixtures 5, repository 10), 0 skipped. All 9 plants are red: CHK-M9-352, -353, -354, -355, -356, -358 (two plants), -381 (rewritten) and -376. The grant probe CHK-M9-272 (part) passes.

Spec read: TS §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L550, §6.5 L1165–L1182, §5.2 L1011–L1012; #122 (c), #125 (a)–(f).

My re-run: ruff on `repositories/` is clean on Windows. The PostgreSQL suite runs on W.

## Checks
1. **Jobs only from the catalog (security invariant, TS §3.3 L213, REQ-212).**
   - `execute` comes only from the snapshot: active `v_plugin` rows listed in `policy_plugin`, in `sort_order`.
   - The payload is composed in SQL from the builder's `plugins` JSON and fixed keys. No function takes command text from a request.
   - The composed payload equals `build.payload()` for the same ids and validates as `ComplianceJob` (CHK-M9-112). Including a retired plugin is red (CHK-M9-352).
2. **Consistency with an import or delete (#125 (d), TS §4.1 L530, §4.3 L550).**
   - The per-policy advisory transaction lock is taken first, then `FOR SHARE` on the policy row.
   - Version, status, `deleted_at` and the plugins then come from one statement. That statement starts after the lock is granted, so under READ COMMITTED it sees either the whole import or delete, or none of it.
   - A later delete's `UPDATE policy` waits for this commit, and its queued-job cancel then sees the new jobs. Dropping `FOR SHARE` is red (CHK-M9-353).
   - Lock order: queue lock, then policy, then job rows. M7's delete takes policy, then job rows, so there is no cycle.
3. **Resolution (TS §4.4 L555, #122 (c)).** It excludes `decommissioned` and `awaiting_approval` and keeps offline agents. Tags match any of the given tags, unknown ids drop out, the result is sorted and distinct, and it is one fixed statement per kind (`sql.SQL` fragments only, never input).
4. **One INSERT for N jobs (#125 (f)).** It uses `unnest` over the job and agent id arrays, and every job gets the scan's `created_at`. The payload's `job_id` is the row id in lowercase text (checked at 10,000 jobs).
5. **Newer cancels older (TS §4.4 L558, #125 (e)).** It cancels only queued compliance jobs of earlier scans of the same policy for the listed agents, retries included. Dispatched jobs, other policies, other agents and inventory jobs are untouched (CHK-M9-113). That is three independent inventory guards (CHK-M9-381 note), so REQ-229 holds.
6. **Grants.** It only INSERTs `scan` and `scan_job` and updates `state` and `finished_at`. The non-progress columns are refused to `bitscan_app` (CHK-M9-272).

## Findings
None blocking or should-fix.

1. Observation, carried to TASK-204: `scan_queue.py` (and `scan_progress.py`, `job_intake.py`) import plain dataclasses from `services/jobs/*`, which the approved plan does by design. Combined with TASK-204's `services/jobs/__init__.py` re-exporting `intake`, importing this repository runs the package init, then `intake`, then `repositories.job_intake`: an import cycle between the repository and service layers. It works today because Python resolves submodules, but I'll grade it in TASK-204.
