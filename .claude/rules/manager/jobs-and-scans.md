---
paths:
  - "manager/**/services/jobs/**"
  - "manager/**/services/scheduler/**"
---

# Jobs, scans and the scheduler

Spec: TS §3.3 (status, decommission), §3.4 (inventory), §4.4 (scans and job states), §6.5 (job payload). The scheduler is APScheduler inside the manager process (TS §2.1); jobs reach agents only through their own pulls.

## Building jobs

- Build compliance jobs only from active plugins of enabled, non-deleted policies: one job per resolved host, from the policy's current plugins, after a role check. Each job carries `job_id`, `agent_id`, `kind`, `pickup_by` (creation + 24 h) and the plugins (`plugin_uuid`, `execute`, `timeout_s`) and `redaction_patterns`. Operator and ExpectedResult stay in `eval_spec` on the manager and are never sent.
- A target is exactly one of `{"agents": […]}`, `{"tags": […]}` (any of the tags) or `{"all": true}`; reject anything else. Resolve it at queue time to agents that are not decommissioned or awaiting approval (offline agents still get jobs), and store the request and the resolved list in `scan.target`.
- Each scan records the `policy.version` it was built from. Jobs queued after an import use the new version; queued jobs keep their commands.
- A disabled policy returns 409; disabling hides it from selection and blocks new scans, while running scans finish. A newer queued job for the same agent and policy cancels the older queued one. Deleting a policy cancels its queued jobs and disables its schedules.
- **Open spec question:** whether disabling a policy cancels its jobs that are still `queued`; TS §4.3 says only "Running scans finish" (`work/open-questions.md` #18).
- Manual scans are picked up at each agent's next job pull (≤ `job_pull_seconds` + 30 s); there is no way to push a job sooner (TS §4.4). An all-hosts scan started with an API token alerts.
- Scheduled scans use cron in the schedule's `timezone` (default UTC); users may enable or disable schedules. Runs missed while the manager was down are not back-filled. Skip, and log, a run if the previous scan from that schedule has `finished_at IS NULL` or the policy is disabled.

## Job states

`queued → dispatched → running → completed | partial | failed`; `queued → expired`; `dispatched → failed` (never started, 24 h); `queued | dispatched | running → cancelled`; `failed | partial → completed | partial` (late results); inventory jobs: `dispatched → completed` (upload) or `dispatched → failed` (not uploaded within 30 min, or upload rejected with 413 or 422) (TS §3.4).

- `queued` at creation; `dispatched` when returned by a pull; `completed` when every plugin has a result; `partial` when the final batch arrives, or the deadline passes, with plugins missing; `failed` when the deadline passes with no results; `expired` when not picked up before `pickup_by`; `cancelled` by an operator or a newer job.
- `running` starts on the agent's first start notice (an empty results batch) or its first result batch. Set `started_at` and `deadline_at` once, on that transition; later start notices change nothing.
- Deadline = start + ceil(Σ `timeout_s` ÷ `max_parallel_plugins` setting) + 10 min. A dispatched job that never starts fails 24 h after dispatch and gets the same single retry.
- `offline_sweep` (every 60 s) does four things:
  - updates agent status: `online` if the last heartbeat is < 10 min old, `stale` at 10–30 min, `offline` after 30 min; a host offline for `decommission_after_days` (default 7, 0 = never) becomes `decommissioned` and its token is revoked;
  - expires queued jobs past `pickup_by`;
  - fails, or marks `partial`, jobs past their deadline; fails compliance jobs dispatched more than 24 h ago that never started, and inventory jobs dispatched more than 30 min ago without an upload (TS §3.4, §4.4);
  - creates the single retry for a job that ended `failed` or `partial` because its deadline passed (TS §3.3, §4.4).
- A job that fails or ends `partial` after its deadline gets exactly one retry: a new row with `retry_of`, holding only the plugins with no result. A retry is never retried.
- Results are accepted until `dispatched_at` + 7 days, even for `failed` or `partial` jobs; they are evaluated normally and move the job to `completed` or `partial`. Final states that never change: `completed`, `expired`, `cancelled`.
- First result wins per host and plugin across the original and its retry: lock `COALESCE(retry_of, job_id)` with `SELECT … FOR UPDATE` while inserting.
- Cancel is manager-side only. Queued jobs become `cancelled` and are never returned by a pull; dispatched or running jobs become `cancelled`, and later result posts for them get 409 `job_not_acceptable` and are not stored (TS §4.4).
- A scan is finished (`finished_at` set) once none of its jobs is `queued`, `dispatched` or `running`; late results can still update its state and score. Scan state: `completed` when every job completed; `partial` when at least one job produced results and at least one did not complete; `failed` when no job produced results; `cancelled` when cancelled before any result; otherwise `queued` or `running`. A scan never takes `dispatched` or `expired`; those `scan_state` values (TS §5.2) are for jobs.
- **Open spec question:** TS §4.4 says only "otherwise `queued` or `running`"; ask when a scan moves from `queued` to `running` (`work/open-questions.md` #22).
- **Open spec question:** a target can resolve to zero agents (an unused tag, or every host decommissioned); TS §4.4 and §6.4 do not say whether `POST /scans` refuses it or what state the scan gets (`work/open-questions.md` #3).
- **Open spec question:** TS §4.4 does not state the scan state when it is cancelled after some results arrived; ask before choosing.

## Inventory (mandatory, G2)

- Every `system_schedule` inventory interval (default 6 h), queue one `kind = 'inventory'` job per agent that is not decommissioned or awaiting approval and has no inventory job in `queued`, `dispatched` or `running`.
- An inventory job not uploaded within 30 min of dispatch, or whose upload is rejected, becomes `failed`. Inventory jobs are never retried. A late upload carrying the `job_id` is stored as an unscheduled snapshot.
- Accept at most one unscheduled upload (no `job_id`) per agent per 10 min; answer 429 otherwise.
- Never add any way to stop, skip or disable inventory jobs.

## Threshold alerts raised here

- More than 5 % of agents offline; job queue age > 1 h; a heartbeating host whose `last_inventory_at` is older than twice the inventory interval.

Tests (TS §8.3): Unit (deadline, state transitions, scan-state derivation, cron with timezones; TS §4.4), Integration (sweep, retries, late results, cancel, schedules with clock control; TS §3.3, §4.4), Security (first result wins under concurrent retries), End-to-end (inventory → import → scan → results).
