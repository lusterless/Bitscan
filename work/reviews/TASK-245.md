# TASK-245 REVIEW: retention wiring

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

**Files reviewed** (diff against `6efe0fb`, +108 / −29):
- `manager/bitscan_manager/services/scheduler/runner.py`
- `manager/bitscan_manager/cli/serve.py`
- `manager/bitscan_manager/services/audit/shipper.py`
- `manager/bitscan_manager/db/pool.py`
- The tester's PD-51 edits in `manager/tests/test_serve_scheduler_linux.py` and `manager/tests/test_scheduler_runner.py`.

**Checked against:** TS §2.1 L103, §5.2 L829–L835, §5.3 L1051, §8.6 L1309; REQ-275 (2), REQ-277; #150 (d), (h); PD-51; plan `work/plans/TASK-242.md` §5.

**Reports:** `work/reports/TASK-245-impl.md`, `work/reports/TASK-245-test.md` (PASS: wiring 36/36, real `serve` 8/8, affected suites 304/304, G41 23/23, 21/21 plants red).

## Checks

- **Retention role only (REQ-275 (2), TS §5.3 L1051):**
  - `build_runtime` builds the pool from `config.retention_dsn`: M2's `BITSCAN_RETENTION_DSN_FILE`, read through the existing loader, which reads no environment value.
  - It uses `bounded_dsn` with `min_size=0, max_size=1` and `name="bitscan_retention"`. The pool name is a label only; the DSN picks the role.
  - The pool goes only to `SchedulerRunner(retention_db=…)` and `ServeLifecycle`. Only `run_retention` uses it. The `retention` interval read uses the app pool, a SELECT on `system_schedule`.
  - The tester's `current_user` spy and `pg_stat_activity` probe show `bitscan_retention`, and the app-pool plants -342 and -342b are red. No grant changed.
- **Inventory and retention cannot be switched off (security invariant: no setting, role or option disables inventory):**
  - Inventory is untouched.
  - The optional `retention_db` / `shipped_through` pair is internal to the runner's constructor, which keeps the existing positional test builds working. The pair is checked: one without the other raises `ValueError`.
  - `build_runtime` has no conditional and always passes both.
  - No environment variable, setting field or route names retention or the scheduler. A PATCH with a retention field is 400.
  - The real `serve` with made-up toggles still has four jobs (CHK-M11-450, plant -356).
- **The job (#150 (h), REQ-277 (1)):**
  - `interval` trigger with the interval from the `retention` row. On a failed start-up read, all three intervals fall back to the seeded values, retention's being 86,400.
  - `max_instances=1`, `coalesce=True`, `misfire_grace_time` = the interval.
  - The first run is at start + 10 min.
  - `_guarded("retention", …)` logs only the job and exception type.
  - The executor grows from 3 to 4 threads, so a long retention run doesn't delay inventory, the sweep or the 30 s schedule tick.
- **Stop (REQ-277 (2), checklist 10):**
  - The retention pool is wrapped in the same `_StoppableDatabase` with the same flag, so the next chunk after `stop()` raises `SchedulerStopping`. `shutdown(wait=True)` waits for the run.
  - The lifecycle closes the retention pool straight after `scheduler.stop()`, then everything else, with the app pool last.
  - The SIGTERM-during-run row and the plants for an unwrapped pool, close after the app pool, no close and no open are all red.
- **Cursor (#150 (d)):**
  - `shipped_through()` reads `self._state.cursor` under the shipper's lock and returns None while it is 0. Nothing else in the shipper changed.
  - The cursor advances only after `queue.append` succeeds (`_read`, then `_save`), so it never passes an entry that isn't in the durable disk queue. That is what #150 (d) approved ("not yet queued for the sink stays").
  - The read-only, None-not-0 and cap-bypass plants are red.
- **PD-51 edits:**
  - `test_serve_scheduler_linux.py` now expects two "pool closed" events, both after the one "scheduler stopping" and after the running sweep ended, and nothing after the last. The "no run starts after the signal" assertion is kept.
  - `test_scheduler_runner.py` changes only a docstring, because the three-argument runner's job set is unchanged.
  - Old to new is listed in the test report, and every other assertion stays.
- **Logs (checklist 11):** no DSN or password is logged, and pool errors go through the existing filter. The wrong-password row (CHK-M11-454) shows only `{job, exc_type}`.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the four files and the two new test files are clean. The PostgreSQL and real-`serve` rows run only on Linux, so I relied on the tester's WSL run and G41.

## Findings

1. **nit, for the #151 measurement at the gate (`serve.py` `bounded_dsn(config.retention_dsn)`).**
   - The retention pool inherits the app pool's `statement_timeout` of 300 s.
   - A scans chunk is one `DELETE` of 100 whole scans. With no index on `scan_job.scan_id`, `retry_of` or `scan_result_reeval.job_id` (#151), a chunk at fleet size could take longer than 300 s. It would then fail every night and the scans step would never move on, though each failure is logged and isolated.
   - The gate's #151 timing (CHK-M11-387) should record a full 100-scan chunk against that 300 s. If it doesn't fit, the chunk size or the timeout is an owner decision.
   - No change in TASK-245.
