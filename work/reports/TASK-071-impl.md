# TASK-071 IMPL report: the scheduler in `serve`

REQ: REQ-080. Spec: TS §2.1 L103, §3.3 L218, §3.4 L230, §8.7 L1343; #67; decisions 2026-10-20 (FastAPI telemetry row). Plan: `work/plans/TASK-061.md` ("Scheduler wiring"). Depends on TASK-061, 065 and 068, all approved. A second look is recommended (the `serve` lifecycle).

Carry-overs applied:
- build `FleetAlerts` once and run it after `run_sweep`;
- log a whole-run failure by type only;
- re-read the inventory interval at each sweep;
- wake the shipper for the sweep's audit entries (the TASK-065 nit);
- G29 stays green.

## Files (2)

- `manager/bitscan_manager/services/scheduler/runner.py`: new, 126 lines.
- `manager/bitscan_manager/cli/serve.py`: 20 lines added, 5 removed.

## `SchedulerRunner(db, clock, wake, scheduler=None)`

- An APScheduler 3.11 `BackgroundScheduler`, UTC, with a `ThreadPoolExecutor(2)`, so a slow inventory run does not delay the sweep. Tests may pass their own scheduler object.
- `FleetAlerts(clock)` is built once, in the constructor.
- **`start()`:**
  - Reads both intervals from `system_schedule` (`inventory`, `offline_sweep`) through `SettingsRepo.schedule_interval`, as `bitscan_app`.
  - If the database cannot be read yet, it logs `scheduler intervals not read, using the seeded values` (exception type only) and uses 21,600 and 60 s.
  - Adds two interval jobs: `inventory` and `offline_sweep`. Each has `max_instances=1` (never two runs of one job at once), `coalesce=True`, `misfire_grace_time` of one interval, and `next_run_time = now`. So there is one inventory run at start-up (#67), and the first sweep runs at once.
- **`run_inventory()`:** one transaction, `run_inventory(JobRepo, clock.now())` (TASK-061).
- **`run_sweep()`:**
  1. `run_sweep(db, now, …)` (TASK-065).
  2. `FleetAlerts.run(db, now, …)` (TASK-068).
  3. Re-reads the inventory interval. If it changed (`PATCH /settings`), `reschedule_job("inventory", seconds=new)` restarts that timer, so the change takes effect within one sweep (#67).
  - The `offline_sweep` interval is read at start-up only; it is not a TS §8.6 setting.
- **Shipper wake:** every transaction a job opens (inventory, every sweep step, every fleet check) registers `wake` on commit. Audit entries such as `agent.decommission` and the alerts therefore reach the sink promptly.
- **Failures:** each run is wrapped. An exception is logged as `scheduler run failed` with `{"job", "exc_type"}`, never its message. The next run happens as scheduled. (The sweep and the fleet alerts also catch each step and check themselves.)
- **`stop()`:** `shutdown(wait=True)` waits for a running job, and no run starts afterwards.
- Retention is not scheduled (M11). No job opens any connection other than the manager's database pool.

## `serve` (`cli/serve.py`)

- `build_runtime` creates `SchedulerRunner(db, clock, shipper.wake)` and passes it to `ServeLifecycle`, as a new optional last argument, so existing constructions without it still work.
- **`start()`:** the pool opens, then the shipper, the flusher and **the scheduler**, before the first request.
- **`stop()`:** the scheduler stops **first** (`shutdown(wait=True)`), then the flusher, shipper, vault client and pool. No run can start after the pool has closed (REQ-080 (3); G27 plant).
- `create_app()` is unchanged, so `TELEMETRY_OFF` still applies. APScheduler has no exporter, and nothing is added to the runtime lock (REQ-080 (4); G29).

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (176 files). APScheduler is untyped, so its two imports carry `type: ignore[import-untyped]`.
- `pytest -q`: 2167 passed, 871 skipped, 0 failed. `tests/test_app_hardening.py -k telemetry` (G29): 3 passed.
- **Scratch probe**: a real `BackgroundScheduler`, a fake database, both intervals 1 s through a fake `SettingsRepo`, and stubbed job functions.
  - Both jobs ran at start-up and repeatedly: in about 7.7 s, 7 inventory runs, 4 sweeps and 4 fleet runs.
  - The second inventory run raised `ValueError("secret-message…")`. It was logged as `("inventory", "ValueError")`, the message appeared nowhere, and later runs continued.
  - A sweep slower (1.5 s) than its interval (1 s) never ran twice at once: maximum concurrency 1.
  - Changing the inventory interval to 2 s rescheduled the job (`interval[0:00:02]`).
  - After `stop()`, no job ran during the following 2 s.
  - The shipper wake was called.
- The Linux `serve` run (TP-M3-25: real `SIGTERM`, exit 0, no run after the pool closed, G27 as `bstester`): **NOT RUN locally**; WSL.

## For tester-c

- Short intervals can be set as owner in `system_schedule` before `serve` starts. The `offline_sweep` CHECK allows 60 s or more; the inventory interval 3,600 s or more.
- The plan's `misfire_grace_time` and `coalesce` mean a manager that was busy or paused runs a missed job once, not once per missed slot.

## Deviations

None.

## Revision 1 (tester-c FAIL round 1: CHK-M3-233-db; lead ruling 2026-10-23)

- **Defect:** with the database refusing, SIGTERM took about 46 s. `shutdown(wait=True)` waited for the start-up inventory run and the first sweep, and each transaction they opened waited the pool's 5 s connect timeout: four sweep steps, four fleet checks, the interval re-read and the inventory run.
- **Fix:** `services/scheduler/runner.py` only.
  - `SchedulerRunner` holds a stop flag (`threading.Event`). The jobs see the database through `_StoppableDatabase`: once the flag is set, every further `transaction()` raises `SchedulerStopping` at once, before touching the pool.
  - That covers every sweep step, every fleet check, the interval re-read and the inventory run, because each of them opens its own transaction.
  - `stop()` sets the flag first, then `shutdown(wait=True)`. A run that is waiting on the pool gives up at its next transaction, the scheduler still joins it, and no run starts afterwards. Nothing touches the pool after it closes, and no extra thread is left behind.
  - Given-up steps are logged as before, by name and exception type only (`SchedulerStopping`). There is no production setting for intervals or skipping.
- **Probe** (real `run_sweep`, real `FleetAlerts` and a real `BackgroundScheduler`, with a fake database whose every transaction waits 5 s and then refuses):
  - Stopped 2 s after start: **`stop()` returned in 3.0 s**, the remainder of the one connect wait in flight.
  - Nothing asked the database for a transaction after `stop()` returned (0).
  - The log shows each remaining sweep step and fleet check as `SchedulerStopping`, and no exception message.
  - With a working database and a sweep running, `stop()` waited for it (1.0 s), as before.
- **Observation, not changed (outside this ruling):**
  - `start()` reads the two intervals from `system_schedule` before scheduling. With the database down it waits one connect timeout (5 s) during the lifespan start-up, then uses the seeded values.
  - This was already so in round 0, and SIGTERM timing is not affected.
  - If the lead wants start-up not to wait, the first sweep could read the intervals instead.
- **Gates:** ruff, ruff format and `mypy --strict` pass. `pytest -q`: 2189 passed. The one failure is the known TASK-072 `test_body_caps` case.
