# TASK-245 IMPL: retention wiring

Implementer: impl-manager-b, 2026-11-08. REQ-275, REQ-277. Spec: TS §2.1 L103 (the scheduler runs retention), §5.2 L829–L835 (`system_schedule`, the seeded `('retention', 86400)`), §5.3 L1051 (`bitscan_retention`), §8.6 L1309 (`BITSCAN_RETENTION_DSN_FILE`). Open items: #150 (d), (h), PD-51. Plan: `work/plans/TASK-242.md` §5. It depends on TASK-242 (in TEST); `run_retention`'s signature is used as written there. High risk (the user's second look, PD-47).

## Files (+108 / −29)

- `manager/bitscan_manager/db/pool.py` (+4 / −2): `AppDatabase(..., name: str = "bitscan_app")` passes the pool name to `ConnectionPool`. The docstring now names the retention use. Nothing else changed; the role always comes from the DSN.
- `manager/bitscan_manager/services/audit/shipper.py` (+8): `Shipper.shipped_through() -> int | None`.
  - It returns the cursor, the id of the last entry already written to the disk queue (`QueueState.cursor`, set by `_save` after a successful `queue.append`), read under the shipper's lock as `refusing()` does.
  - It returns None while the cursor is 0: nothing queued yet, a fresh install with no state file.
  - It is read-only; nothing else in the shipper changed.
- `manager/bitscan_manager/services/scheduler/runner.py` (+60 / −20):
  - Adds the constants `RETENTION = "retention"` and `DEFAULT_INTERVAL_S[RETENTION] = 86_400` (the seeded row), and `RETENTION_DELAY = 10 min`.
  - The constructor gains two keyword-only arguments after `scheduler`, `retention_db: Database | None` and `shipped_through: Callable[[], int | None] | None`. They come together; one without the other raises `ValueError`.
  - The retention pool is wrapped in the same `_StoppableDatabase` with the same stop flag.
  - New `run_retention()` method: `_guarded("retention", …)` around `retention_task.run_retention(retention_db, clock.now(), shipped_through=…, wake=self._wake)`.
  - `start()`: when retention is configured, it reads the `retention` interval with the other two at start-up (seeded 86,400 if the read fails), and adds the fourth job: `interval` trigger, `max_instances=1`, `coalesce=True`, `misfire_grace_time` = the interval, and `next_run_time = start + 10 min`.
  - The executor grows from 3 to 4 threads.
  - The docstring describes the fourth job; "Retention is not scheduled until M11" is gone.
- `manager/bitscan_manager/cli/serve.py` (+36 / −7): `build_runtime` creates the retention pool and passes it to the runner and the lifecycle:

  ```python
  retention_db = AppDatabase(bounded_dsn(config.retention_dsn), min_size=0, max_size=1, name="bitscan_retention")
  SchedulerRunner(db, clock, shipper.wake, retention_db=retention_db, shipped_through=shipper.shipped_through)
  ServeLifecycle(..., retention_db=retention_db)
  ```

  - `ServeLifecycle` gains a keyword-only `retention_db`.
  - `start()` opens it straight after the app pool (no wait for the database, `min_size=0`, so no connection until the first run).
  - `stop()` closes it straight after `scheduler.stop()` returns (only the scheduler uses it), before the flusher, shipper, cipher and app pool.
  - The module docstring is updated.

## Choices to review

1. **Retention is optional in the runner's constructor.**
   - Why: existing tests build `SchedulerRunner(db, clock, wake)` and `SchedulerRunner(db, clock, wake, scheduler)` positionally (`test_scheduler_runner.py` L194, L439; `test_serve_scheduler_linux.py` L488; `test_scan_schedules_pg.py` L405). Required arguments would break every one of those tests, not only the PD-51 rows.
   - Behaviour: without the pool, the runner schedules the three M9 jobs and reads only their two intervals, exactly as before. `serve` always passes both, so the running manager always has four jobs.
   - What this is not: no setting, flag or route can leave the job out. The parameters are internal.
   - Inventory is unaffected (security invariant).
2. **Four worker threads, not three.** A retention run can be long (#151). With three threads it would hold one, and an inventory run, a sweep and the 30 s schedule tick that fall due together would queue behind it. Four keeps M9's timing.
3. **Through the retention pool only.** The retention run is the only user of `retention_db`; nothing else gets it. The `retention` interval is read through the app pool at start-up (SELECT on `system_schedule`, like the other two).
4. **Pool limits.** `bounded_dsn` applies the same keepalive and `statement_timeout` 300 s bounds as the app pool. One retention scans chunk of 100 whole scans must finish within that; otherwise the chunk fails, is logged, and the next run retries. That falls under the #151 timing the gate records.

## Earlier checks replaced by requirement (PD-51): old → new for `tests/m11/report.md`

| Old check | File and lines | Why it changes | New expectation (REQ-277) |
| --- | --- | --- | --- |
| CHK-M9-218 (job set, from CHK-M3-230) | `test_scheduler_runner.py` L210, L235 | Still true for a runner built without retention: those tests pass three positional arguments, so they need no change. REQ-277 (1) needs a new row. | Built with `retention_db` and `shipped_through`: the job set is `{inventory, offline_sweep, scan_schedules, retention}`; retention's interval is the `retention` row; its `next_run_time` is start + 10 min; `max_instances` 1; the seeded fallback is 86,400 when the read fails. |
| CHK-M3-233 / CHK-M9-219 (stop record: "pool closed") | `test_serve_scheduler_linux.py` L441–L445 | It patches `AppDatabase.close` and asserts `len(closed) == 1` and no event after it. serve now closes two pools: the retention pool after the scheduler stops, then the app pool. | Two "pool closed" events, both after the running sweep ended and after "scheduler stopping"; nothing after the last one; no run starts after the first. |
| CHK-M9-219 (failure job names) | `test_serve_scheduler_linux.py` L461 and the `traced` set L395–L399 | Unchanged in practice: retention first runs 10 minutes after start-up, later than any of these serve runs last. | Add `retention` to the allowed names only if a test shortens the first run. |

Every other assertion in those files is unchanged by this task.

## Behaviour the tester should know

- **REQ-277 (2), stop.** `stop()` sets the flag, so the running retention run's next chunk or probe transaction raises `SchedulerStopping`. TASK-242 logs each remaining step once, as failed, and returns. `shutdown(wait=True)` waits for it, and then the retention pool closes.
- **REQ-277 (3), start-up.** `serve` reads `BITSCAN_RETENTION_DSN_FILE` (M2, unchanged; a missing file still fails start-up). The pool is named `bitscan_retention`, and the DSN's role is whatever that file names.
- **REQ-275 (2), the role.** Every retention statement runs on this pool, and the app pool is never passed to `run_retention`. A spy on `current_user` should see `bitscan_retention` for each one.
- **The cursor (#150 (d)).** `shipped_through()` is None before the first queued entry. After that it equals the id of the newest entry written to the disk queue (not necessarily delivered; the queue is durable). After a restart it is the cursor loaded from the state file.
- **Logs.** The runner adds only its existing `scheduler run failed` line (job, exc_type) for a retention run that raises outside a step, for example a failed clock check.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check` and `ruff format --check` on the four files: clean.
  - The whole-tree ruff run reports 6 findings in `manager/tests/test_scan_views_pg.py`, a tester's file in progress (not mine), and nothing in product code.
- `mypy --strict` on the four files and `services/retention`: no error in them. The 10 reported are the known pre-existing ones in `api/user` (stale venv). The whole tree additionally shows mypy errors in `tests/test_scan_views_pg.py` (the tester's).
- An ad-hoc `python -I -c` run with fake database, clock and scheduler objects (nothing written to the tree):
  - without retention, the jobs are `inventory` 7,200, `offline_sweep` 90 and `scan_schedules` 30, all first run at start;
  - with retention, the same plus `retention` 3,600 (the row's value), first run at start + 10 min, `max_instances` 1;
  - `retention_db` alone raises `ValueError`.
- The real `serve` rows (`test_serve_retention_linux.py`), the runner rows (`test_retention_wiring.py`) and G41 are the tester's, in WSL.

## Builder checklist

| Item | How it is met |
| --- | --- |
| 7 | wake is registered on commit by TASK-242 |
| 10 | the retention pool is behind the same stop flag; `stop()` waits |
| 11 | no DSN or secret is logged (pool errors go through the existing `DriverLogFilter` and `_unavailable`) |
| 15 and 16 | don't apply: no pip step, and `serve`'s readiness is unchanged |
| 1–6, 8, 9, 12–14, 17–22 | don't apply |
