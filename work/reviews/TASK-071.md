# TASK-071 REVIEW: scheduler wiring in `serve`

Reviewer: reviewer. Date: 2026-10-23. REQ-080. Spec: TS §2.1 L103 (APScheduler inside the manager process, one instance), §3.3 L218 (`offline_sweep` every 60 s), §3.4 L230 (inventory every `system_schedule` interval), §8.7 L1343; #67 (one run at start-up, then every interval; a change takes effect within one sweep); REQ-088 (no knob that stops or skips inventory); decisions 2026-10-20 (FastAPI telemetry off, G29), 2026-10-22 (no DSN text in logs). Ruling (`work/decisions.md`, 2026-10-23, TASK-071 r1): a stop flag checked before every step and transaction, so `serve` exits 0 within the G27 bound with the database down; stop still waits for an executing run; nothing touches the pool after close. Plan: `work/plans/TASK-061.md` ("Scheduler wiring"). Inputs:
- `work/reports/TASK-071-impl.md`, including revision 1;
- `work/reports/TASK-071-test.md`: round 1 FAIL (`SIGTERM` took 46 s with the database refusing; G27 red), then PASS on r1 (201 passed in WSL as root and as `bstester`; `SIGTERM` with the database refusing 4.0–4.2 s against a 10 s bound; 14 + 2 + 3 plants red).

Files reviewed:
- `manager/bitscan_manager/services/scheduler/runner.py` (new);
- `manager/bitscan_manager/cli/serve.py` (lifecycle wiring);
- the tester's `test_scheduler_runner.py` and `test_serve_scheduler_linux.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. The M3 owner notes recommend a second look (the `serve` lifecycle).

## What was checked

- **Jobs (REQ-080 (1), (2), #67).**
  - `BackgroundScheduler` (APScheduler 3.11, already in the runtime lock) runs two jobs, each with `max_instances=1`, `coalesce=True`, `misfire_grace_time` = one interval, and `next_run_time` = start, on a two-thread executor:
    - `inventory`: `run_inventory`, at start-up and then every `system_schedule` interval;
    - `offline_sweep`: `run_sweep`, then `FleetAlerts.run` (built once per process), then a re-read of the inventory interval, with `reschedule_job` when it changed, so a `PATCH /settings` change takes effect within one sweep.
  - Retention is not scheduled.
  - Every job transaction registers the shipper's `wake` on commit, which resolves my TASK-065 nit.
- **Failures.** `_guarded` logs `scheduler run failed` with the job name and exception type only, and the next run still happens. The sweep steps and fleet checks keep their own per-step logging, also by type only. No message or DSN text reaches a log.
- **Stop (r1 ruling, REQ-080 (3), G27).**
  - `stop()` sets a `threading.Event` first. The jobs see the database only through `_StoppableDatabase`, whose `transaction()` raises `SchedulerStopping` before touching the pool once the flag is set. That covers every sweep step, fleet check, interval read and inventory run.
  - `shutdown(wait=True)` then joins a run that is already executing.
  - `ServeLifecycle.stop` stops the scheduler **before** the flusher, the shipper, the vault client and the pool, so nothing touches the pool after it closes (G27 plant red).
  - With the database refusing, `SIGTERM` now exits 0 in about 4 s, inside the 10 s bound. The M2 refused-DSN test is green again as root and as `bstester`.
- **No knob (REQ-088).** `runner.py` reads intervals only from `system_schedule`, falling back to the seeded values (TS §5.2 L832) if the read fails at start-up. `serve.py` gained no option, environment variable or setting. The shorter intervals in the Linux tests come from a launcher hook in the test file only (checked by the lead and tester-d).
- **Security invariants.** No connection other than the manager's database. No route, flag or setting that skips inventory. The scheduler never pushes anything to agents (TS §2.2).
- **OpenTelemetry (G29).** `create_app()` still passes `telemetry=TELEMETRY_OFF`. The runtime lock holds `opentelemetry-api`, which came with FastAPI in M2, and no SDK or exporter.
- **Scope.** Two files, as the task row lists.
- **Tests (my run, Windows).** `test_scheduler_runner.py`, `test_serve_scheduler_linux.py`, `test_serve_linux.py`, `test_app_hardening.py` and `test_serve_flusher.py`: 73 passed, 2 skipped (Linux-only; run in WSL by tester-d as root and as `bstester`). ruff and format are clean, and `mypy --strict` is clean on the whole tree (194 files).

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/scheduler/runner.py:128-136` (`start`). `start()` reads both intervals synchronously inside the async lifespan start. With the database down, this blocks the event loop for the pool's connect timeout before the seeded values are used, so `serve` takes that long to begin answering `/healthz`. It is not a correctness issue, and `SIGTERM` is unaffected. Optional fix: schedule with the seeded values and let the first sweep read and apply both intervals, which it already does for inventory.
2. **nit**, `manager/bitscan_manager/cli/serve.py` (`ServeLifecycle.stop`). `self._scheduler.stop()` is a blocking call inside an `async` method, so the event loop waits up to one run while the scheduler shuts down. That is acceptable at shutdown. `await asyncio.to_thread(...)` would keep the loop responsive if that ever matters.

## Carry-overs

- **TASK-080 (README).** Document the scheduler: inventory at start-up and every interval, the sweep every 60 s, the fleet alerts, interval changes taking effect within one sweep, and no way to stop inventory.
- **M11.** Retention will be the third job and must go through the same `_StoppableDatabase` (with the retention DSN) and stop order.
