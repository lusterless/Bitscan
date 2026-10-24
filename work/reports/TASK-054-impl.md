# TASK-054 IMPL report: job repository (inventory jobs)

REQ: REQ-072, REQ-076, REQ-077, REQ-078, REQ-079. Spec: TS §5.2 L872–L890 (`scan_job`) and L994–L1013 (grants), §3.4 L230 and L244, §4.4 L566, L572 and L575, §6.1 L1064, §6.5 L1182. Plan: `work/plans/TASK-061.md` (the queueing statement).

## Files (1)

- `manager/bitscan_manager/repositories/jobs.py`: new, 157 lines (135 of code).

## What it holds (`JobRepo(conn)`, inside the caller's transaction)

| Function | SQL | Notes |
| --- | --- | --- |
| `queue_inventory(now, pickup_by, agent_id=None) -> list[UUID]` | `pg_advisory_xact_lock(hashtext('inventory_queue'))`, then one `WITH due AS MATERIALIZED (…) INSERT … SELECT … RETURNING job_id` | Eligible agents: status not `decommissioned` or `awaiting_approval`, and no inventory job `queued`, `dispatched` or `running` (TS §3.4 L230). The `job_id` comes from `gen_random_uuid()` in the materialised CTE and is used for both the row and `payload.job_id`. The payload has exactly `job_id`, `agent_id`, `kind`, `pickup_by` (TS §6.5). `agent_id` limits the run to one agent (#36, `queue_first_inventory`). Concurrent runs are serialised by the lock, so there is still one open job per agent. `pickup_by` in the payload is UTC to the second with `Z`; the column keeps the exact value (plan TASK-061). |
| `has_open_inventory(agent_id) -> bool` | `EXISTS` | The open-job check. |
| `pull(agent_id, now) -> list[dict]` | `UPDATE scan_job … FROM (SELECT … FOR UPDATE SKIP LOCKED LIMIT 10) … AND j.state = 'queued' RETURNING …` | Only this agent's jobs; `state = 'queued'`; `pickup_by > now`; **`kind = 'inventory'` (M3)**. At most `PULL_LIMIT` = 10 (a module constant, not a parameter), oldest first by `(created_at, job_id)`. Rows are locked and the state re-checked, so two concurrent pulls never return one job. Sets `state = 'dispatched'` and `dispatched_at`. Returns the stored payloads; `eval_spec` is never selected. |
| `get_for_agent(job_id, agent_id, *, lock=False) -> JobRow \| None` | `SELECT … WHERE job_id AND agent_id [FOR UPDATE]` | Another agent's job reads as None, the same as unknown. |
| `complete(job_id, now)` and `fail(job_id, now) -> bool` | `UPDATE … SET state, finished_at WHERE job_id AND state = 'dispatched'` | `dispatched` → `completed` or `failed`. |
| `expire_past_pickup(now) -> int` | `… SET state = 'expired', finished_at WHERE state = 'queued' AND pickup_by <= now` | Mirrors the pull's `pickup_by > now`. |
| `fail_dispatched_inventory(dispatched_before, now) -> int` | `… SET state = 'failed', finished_at WHERE kind = 'inventory' AND state = 'dispatched' AND dispatched_at < cutoff` | The caller passes `now − 30 min`: REQ-078 says "more than 30 minutes", so the bound is strict. No retry row is created. |
| `oldest_queued_for_online() -> datetime \| None` | `min(created_at)` of `queued` jobs whose agent is `online` | For #66. The caller computes the age with the Clock. |
| `count_queued() -> int` | `count(*) WHERE state = 'queued'` | For the TASK-079 gauge. |

**Grants:** every UPDATE writes only `state`, `dispatched_at` or `finished_at`, which are TS §5.2 progress columns. `SELECT … FOR UPDATE` needs only the app's column UPDATE privilege. Nothing changes `agent_id`, `payload`, `kind` or `scan_id`, and nothing deletes a job.

**Security:** no function accepts a payload or a command. A job body is built only by `queue_inventory`, from columns, so no path queues an ad-hoc command (TS §3.3).

## Local gates (Windows)

- `ruff check manager` (S608 included) and `ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: pass for `bitscan_manager`. The only errors are in the tests' `FakeLimits` (see TASK-057).
- `pytest -q`: 1198 passed, 451 skipped. The 2 failures are the M2 `test_alerts.py` assertions that TASK-056 changes on purpose.
- PostgreSQL behaviour: **NOT RUN locally**, because Docker is unavailable on Windows. The SQL has been reviewed but never executed. Please run TP-M3-08 in WSL first.

## For the tester

- `queue_inventory` takes an advisory transaction lock, so it must run inside a transaction (the app's `db.transaction()`).
- `pull` returns plain dicts (the stored JSONB). TASK-073 validates them with `JobsResponse`.
- The plan's `dispatched_at <= now − 30 min` is `dispatched_at < cutoff` here, following REQ-078 (3) "more than 30 minutes". At 30 min 1 s the job fails; at 29 min 59 s it does not.

## Deviations

None. One reading is stated above: the 30-minute bound is strict, per REQ-078.
