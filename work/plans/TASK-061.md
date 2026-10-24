# TASK-061 plan: inventory queueing, `offline_sweep`, fleet alerts and the scheduler

Covers TASK-061 (inventory run), TASK-065 (sweep core), TASK-068 (fleet alerts) and TASK-071 (APScheduler wiring in `serve`). REQs: REQ-077 to REQ-080, REQ-088. Owner: impl-manager. Second look recommended for TASK-071. Tests: TP-M3-15, TP-M3-19, TP-M3-22, TP-M3-25 (G33, G27, G29); mutation rows CHK-M3-352, 369, 373.

**Blocked on #67 and #36** (cadence, first job), **#25** (age base), **#73** (status details, audit), **#65** and **#66** (alerts).

## Spec quotes

- TS §3.4 L230: "Every `system_schedule.interval_s` for `inventory` (default 6 h), the scheduler queues one `kind = 'inventory'` job for every agent that is not decommissioned or awaiting approval and has no inventory job in `queued`, `dispatched` or `running`." L237: "Admins may change the interval (1–24 h) but cannot turn it off."
- TS §3.3 L218: "`online` if the last heartbeat is < 10 min old; `stale` at 10–30 min; `offline` after 30 min. The `offline_sweep` task (every 60 s) updates status, and also applies job timeouts and creates retries (§4.4)." L220: "A host offline for `decommission_after_days` (default 7; 0 = never) is marked `decommissioned` and its token is revoked."
- TS §4.4 L566: `queued` "with `pickup_by` = creation + 24 h"; L572: `expired` "Not picked up before `pickup_by`". L575: the sweep expires queued jobs past `pickup_by`.
- TS §3.4 L244: "dispatched but not uploaded within 30 minutes … becomes `failed` … Inventory jobs are never retried."
- TS §2.1 L103: "APScheduler, inside the manager process (one manager instance in v1)".

## Inventory run (TASK-061)

```sql
-- one statement; $1 = now, $2 = now + 24 h; serialised by pg_advisory_xact_lock(hashtext('inventory_queue'))
WITH due AS (
  SELECT a.agent_id FROM agent a
  WHERE a.status NOT IN ('decommissioned', 'awaiting_approval')
    AND NOT EXISTS (SELECT 1 FROM scan_job j WHERE j.agent_id = a.agent_id AND j.kind = 'inventory'
                    AND j.state IN ('queued', 'dispatched', 'running'))
), ids AS (SELECT agent_id, gen_random_uuid() AS job_id FROM due)
INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at, pickup_by)
SELECT job_id, 'inventory', agent_id, 'queued',
       jsonb_build_object('job_id', job_id, 'agent_id', agent_id, 'kind', 'inventory',
                          'pickup_by', to_char($2 AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
       $1, $2
FROM ids RETURNING job_id;
```

(Illustrative; the repository builds it with `psycopg.sql` and parameters, TASK-054.) The advisory lock makes two concurrent runs (a timer run and a #36 first-job call) give one job per agent (REQ-077 (3)); no unique index exists for it and none may be added. `queue_first_inventory(agent_id)` runs the same statement restricted to one agent, called from enrolment (auto-approve) and approval (#36). Cadence per #67: a run at start-up, then every `interval_s`. A `PATCH /settings` change is picked up by TASK-071's runner, which re-reads the inventory `interval_s` at every sweep run and reschedules the inventory timer when it changed, so a change takes effect within one sweep interval (60 s) and no service imports the scheduler or needs a new `Runtime` field.

`pickup_by` text: second precision UTC with `Z`, the same form the `UtcDatetime` type emits, so the payload's `pickup_by` equals the column to the second (the column keeps microseconds; the payload is what the agent sees, and the agent only compares with its clock).

## `offline_sweep` (TASK-065), each step its own transaction

1. **Status.** With `h` = `last_heartbeat_at`, or the #25 base for agents that never heartbeat (`enrolled_at`, or the approving request's `decided_at`): `online` if `now − h < 10 min`; `stale` if 10 min ≤ age ≤ 30 min; `offline` if age > 30 min. Only agents in `enrolled`, `online`, `stale`, `offline` are touched (`ix_agent_status`). An `enrolled` agent that never heartbeats moves to `stale` and `offline` by the same ages (#25 (c)); whether it should pass through `online` first is not in the spec, and the plan does not move it to `online` without a heartbeat.
2. **Decommission.** `offline` agents with age > `decommission_after_days` days (setting > 0): status `decommissioned`, `token_revoked_at = now`, one `agent.decommission` audit entry each (#73 (d)).
3. **Expire.** `queued` jobs with `pickup_by <= now` → `expired`, `finished_at = now`; `bitscan_jobs_expired_total` += count after commit.
4. **Inventory timeout.** `kind = 'inventory'`, `state = 'dispatched'`, `dispatched_at <= now − 30 min` → `failed`, `finished_at = now`. No retry row (CHK-M3-373).
5. **Fleet alerts (TASK-068),** after the steps above: offline share (#65 (b)), queue age (#66: oldest `queued` job whose agent is `online`, older than 1 h), stale inventory (online agents with `last_inventory_at` — or the #25 base — older than 2 × the inventory interval; #65 (c)), default-partition rows (`SELECT EXISTS (SELECT 1 FROM scan_result_default)`, #65 (g)). Each fires through a TASK-056 window and `raise_alert` in its own transaction.

Compliance steps of the sweep (deadline, 24 h never-started, retries) are M9; the sweep module leaves a clear seam (`steps` list) for them.

## Scheduler wiring (TASK-071)

- `BackgroundScheduler` (APScheduler 3.x, already in the runtime lock) with two jobs, `coalesce=True`, `max_instances=1`, `misfire_grace_time` = one interval; executor of two threads so a slow inventory run does not delay the sweep.
- Intervals read from `system_schedule` at start-up (as `bitscan_app`); the `offline_sweep` interval has no route (it is not a TS §8.6 setting) and changes only at restart; the inventory interval is re-read at every sweep run and the inventory job rescheduled when it changed.
- Each run calls the service with `runtime.clock.now()`, catches every exception, logs `scheduler run failed` with the job name and exception type only (as `FailedCheckFlusher`), and returns.
- `ServeLifecycle.start` starts the scheduler after the pool opens and before the first request; `stop` calls `shutdown(wait=True)` before the flusher, shipper and pool stop, so no run starts after the pool closed (REQ-080 (3); G27 plant).
- No OpenTelemetry: `create_app()` keeps `TELEMETRY_OFF`; APScheduler has no exporter. G29 re-runs in TASK-071 TEST.
- Retention (M11) is not scheduled; its `system_schedule` row stays for `/readyz`.

## Edge cases

- A manager down for longer than `pickup_by`: at start-up the first sweep expires stale queued jobs, then the start-up inventory run queues new ones (#67).
- Clock jumps: every rule reads the one `Clock`; a backwards jump only delays transitions. The heartbeat skew alert (TASK-072) is what reveals a wrong manager clock (the M2 `db maintain` residual).
- 10,000 agents: the status step is one `UPDATE … SET status = CASE …` per target status, using `ix_agent_status`; the inventory run is one `INSERT … SELECT`. The tester records their duration at 10,000 agent rows; no gate is set.
