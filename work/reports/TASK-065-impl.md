# TASK-065 IMPL report: `offline_sweep` core

REQ: REQ-078. Spec: TS §3.3 L218 and L220, §3.4 L244, §4.4 L572 and L575; #25, #73 (b), (d). Plan: `work/plans/TASK-061.md` ("`offline_sweep`", steps 1–4). Depends on TASK-051, 054, 055, 056 and 061, all approved. The reviewer carry-overs are applied: decommission is skipped at 0, there is one audit entry per decommissioned id, and the jobs-expired metric is raised after commit.

## Files (1)

- `manager/bitscan_manager/services/scheduler/sweep.py`: new, about 150 lines. The package `__init__` is unchanged, since it is not in the task's file list; import from `services.scheduler.sweep`.

## API

- `run_sweep(db: Database, now: datetime, stores=pg_stores) -> SweepResult`.
- `SweepResult(statuses_changed, decommissioned, expired, inventory_failed, failed_steps)`.
- `Stores(tx, agents, jobs, settings, audit)` is built per transaction by `pg_stores(tx)` from the real repositories. `mypy` checks this against the `SweepAgents`, `SweepJobs`, `SettingsReader` and `Auditor` protocols. Tests can pass their own factory.
- Constants: `STALE_AFTER = 10 min`, `OFFLINE_AFTER = 30 min`, `INVENTORY_UPLOAD_WINDOW = 30 min`.

## Steps (each in its own transaction)

1. **`statuses`**: `AgentRepo.apply_heartbeat_ages(now, 10 min, 30 min)`.
   - The status is `online` below 10 min (and only after a heartbeat since enrolment or approval, per TASK-051 r1), `stale` from 10 min to 30 min inclusive, and `offline` above 30 min.
   - It uses the GREATEST age base, and touches only `enrolled`, `online`, `stale` and `offline` agents.
2. **`decommission`**: reads `decommission_after_days` with `read_settings`.
   - **0 means never: the step returns without calling the repository.**
   - Otherwise `decommission_offline(now, N days)` revokes the token and sets `decommissioned`.
   - It writes **one `agent.decommission` audit entry per agent**: actor `system`, target `agent:<id>`, detail `{"after_days": N}`. This is not an alert (#71, #73 (d)).
3. **`expire`**: `expire_past_pickup(now)`. `bitscan_jobs_expired_total` is increased by the count through `tx.on_commit`, so a rollback adds nothing.
4. **`inventory_timeout`**: `fail_dispatched_inventory(now − 30 min, now)`. That is inventory jobs dispatched **more than** 30 minutes ago (strict `<`, REQ-078 (3)), which become `failed` with `finished_at`. **No retry row is ever made.**

**Failure handling:** each step is `with db.transaction(): step(...)` inside `try/except Exception`.
- A failure rolls back that step only and is recorded in `failed_steps`.
- It is logged as `sweep step failed`, with `{"step", "exc_type"}` and never the message.
- The remaining steps still run, and the next sweep runs the failed step again (REQ-078 (5)).

**Not here:** the sweep creates no job and opens no connection other than the caller's database. The fleet alerts (TASK-068), the scheduler wiring (TASK-071) and the compliance steps (M9) are separate.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (159 files).
- `pytest -q` (run after TASK-063): 2003 passed, 0 failed.
- Scratch probe with a fake database (counting commits and rollbacks, running hooks on commit) and fake stores:
  - Normal run: 4 commits. The repositories were called with 10 min and 30 min, 7 days, and a 30-minute cut-off. Two decommissioned ids gave two `("system", "agent.decommission", "agent:<id>")` entries. `bitscan_jobs_expired_total` rose by 2, after commit.
  - `decommission_after_days = 0`: `decommission_offline` was not called and no entry was written.
  - The status step raising: `failed_steps == ["statuses"]`, 1 rollback and 3 commits. Expire and the inventory timeout still ran, and the metric still rose by 2.
- PostgreSQL boundaries (TP-M3-19, G33): **NOT RUN locally**; WSL.

## For the tester

- `decommission_offline` measures "offline for N days" from the same GREATEST age base (#73 (b)): more than N days since the last heartbeat, or since the enrolment base for an agent that never sent one.

## Deviations

None.
