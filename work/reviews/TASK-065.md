# TASK-065 REVIEW: `offline_sweep` core

Reviewer: reviewer. Date: 2026-10-23. REQ-078 (and REQ-086 (2), the jobs-expired metric). Spec:
- TS §3.3 L218: `online` below 10 min, `stale` 10–30 min, `offline` above 30 min; the sweep runs every 60 s.
- TS §3.3 L220: decommission after `decommission_after_days`, 0 = never, and the token is revoked.
- TS §3.4 L244: inventory jobs not uploaded within 30 minutes fail and are never retried.
- TS §4.4 L572, L575: queued jobs past `pickup_by` expire.
- #25, #73 (b), (d).

Rulings (`work/decisions.md`, 2026-10-23): the GREATEST age base; `online` needs a fresh heartbeat (TASK-051 r1). Plan: `work/plans/TASK-061.md` (`offline_sweep`, steps 1–4). Inputs:
- `work/reports/TASK-065-impl.md`;
- `work/reports/TASK-065-test.md` (PASS: CHK-M3-180 to -188; 20 PostgreSQL tests and 7 unit tests; 145 passed in WSL; 19 of 19 plants red, CHK-M3-369 and -373 and the G33 plant included).

Files reviewed:
- `manager/bitscan_manager/services/scheduler/sweep.py` (new, about 140 lines);
- the tester-b test files.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance.** Four steps, each in its own `db.transaction()` inside `try/except Exception`:
  1. **Statuses.** `apply_heartbeat_ages(now, 10 min, 30 min)` (TASK-051) gives the REQ-078 (1) boundaries and never touches `awaiting_approval` or `decommissioned` agents (REQ-078 (4)).
  2. **Decommission.**
     - It reads `decommission_after_days` in the step's transaction.
     - **At 0 it returns without calling the repository.**
     - Otherwise the agent is decommissioned and its token revoked, with one `agent.decommission` audit entry per agent (actor `system`, detail `{"after_days": N}`, not an alert, #73 (d)).
     - The revoked token then gets 401 `token_revoked` (tested).
  3. **Expire.** `expire_past_pickup(now)`. `bitscan_jobs_expired_total` rises by the count only through `tx.on_commit`.
  4. **Inventory timeout.** `fail_dispatched_inventory(now − 30 min, now)`, strictly more than 30 minutes, with `finished_at` set. No job row is ever created (CHK-M3-373 red).
- **Failure handling (REQ-078 (5)).** A failing step rolls back alone. It is recorded in `SweepResult.failed_steps` and logged as `sweep step failed` with the step name and exception type only, never the message. The other steps still run, and the next sweep repeats the failed one.
- **Security invariants.** The sweep creates no job and opens no connection beyond the caller's database. It has no setting or flag that could skip inventory (REQ-088). Audit entries hold no token.
- **Scope.** One file, as the task row lists. The package `__init__` is unchanged.
- **Tests (my run, Windows).** `test_sweep.py` passes 7, and `test_sweep_pg.py` skips 20 locally (run in WSL by tester-b). ruff and format are clean, and `mypy --strict` is clean on the whole tree (168 files). The PostgreSQL tests commit through the real `AppDatabase` per step and assert only on their own rows. They cover:
  - the 9m59s, 10m, 29m59s, 30m and 30m1s boundaries;
  - decommission at 7 days, and never at 0;
  - expiry and inventory failure at their bounds;
  - a forced step failure;
  - a 10,000-agent timing, which has no gate.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/scheduler/sweep.py:67-74` (`pg_stores`). The decommission audit entries do not call `sink_gate.wake` on commit, as the M2 routes do. The shipper still finds them within its 1-second poll (#51), so nothing is lost. If TASK-071 passes the runtime's sink gate in, register `tx.on_commit(sink_gate.wake)` here too, so entries are shipped as promptly as the routes' entries.

## Carry-overs

- **TASK-068.** The fleet alerts run after these steps, each in its own transaction, with their windows marking "fired" only on commit (ruling 2026-10-23).
- **TASK-071.** Call `run_sweep(runtime.db, runtime.clock.now())` from the scheduler. Log a whole-run failure by type only. Re-read the inventory interval at each sweep (#67).
