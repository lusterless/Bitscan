# TASK-061 IMPL report: inventory queueing

REQ: REQ-077, REQ-088. Spec: TS §3.4 L230 and L237, §4.4 L566, §6.2 L1129, §2.3 L145; #36, #67. Plan: `work/plans/TASK-061.md` ("Inventory run"). Depends on TASK-054 and TASK-055, both TEST PASS and REVIEW APPROVED.

## Files (2)

- `manager/bitscan_manager/services/scheduler/inventory.py`: new, 37 lines.
- `manager/bitscan_manager/services/scheduler/__init__.py`: new, re-exports.

## What it holds

- `PICKUP_WINDOW = 24 h` (TS §4.4 L566).
- `InventoryQueue` is a `Protocol` with one method, `queue_inventory(now, pickup_by, agent_id=None) -> list[UUID]`. TASK-054's `JobRepo` satisfies it; `mypy --strict` confirms this statically.
- `run_inventory(jobs, now) -> list[UUID]` makes one scheduled run, with `pickup_by = now + 24 h`. It returns the ids of the jobs it queued: one per eligible agent that has no open inventory job.
- `queue_first_inventory(jobs, agent_id, now) -> UUID | None` is the #36 first job when an agent becomes `enrolled`, by auto-approval (TASK-067) or approval (TASK-070). It uses the same statement, limited to that agent. It returns None when the agent already has an open inventory job or is not eligible.

**Where the rules live:**
- Eligibility, the payload and the advisory lock that serialises runs are TASK-054's single statement (`JobRepo.queue_inventory`). Two runs at the same moment, such as a timer run and a first-job call, therefore still give one open job per agent.
- This module adds only the Clock-driven `pickup_by` and the two entry points.

**Security:** there is no setting, parameter or flag that skips or disables a run (REQ-088 (2)), and the module opens no connection other than the caller's transaction.

**Cadence (#67):** a run at start-up, then every `interval_s`, re-reading the interval within one sweep. That is TASK-071's scheduler wiring. The caller opens the transaction, for example `with runtime.db.transaction() as tx: run_inventory(JobRepo(tx.conn), runtime.clock.now())`.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (145 files).
- Scratch probe with a fake queue:
  - `run_inventory` passed `pickup_by = now + 24 h` and no agent filter, and returned the queued ids.
  - `queue_first_inventory` passed the agent id and returned the one id, or None when nothing was queued.
- The PostgreSQL behaviour (statuses, open jobs, two simultaneous runs) is TP-M3-15 in WSL. It exercises the TASK-054 statement, which already passed TP-M3-08.

## Deviations

None.
