# TASK-068 REVIEW: fleet threshold alerts

Reviewer: reviewer. Date: 2026-10-23. REQ-079. Spec: TS §8.4 L1291 (> 5 % agents offline; job queue age > 1 h; a heartbeating host whose inventory is older than twice the interval), §3.4 L242, §5.3 L1047 and §8.4 L1290 (rows in the default `scan_result` partition alert); #44 (the manager's alert code raises the default-partition alert), #65 (b), (c), (g), #66 (queue age counts only online agents' jobs), #71. Rulings (`work/decisions.md`, 2026-10-23):
- "Threshold alerts consume their once-per-period slot only on commit";
- "TASK-068 may touch two approved files": `due()`/`mark()` in TASK-056 `thresholds.py`, `default_partition_has_rows()` in TASK-054 `jobs.py`; the `inventory_stale` reading accepted.

Plan: `work/plans/TASK-061.md`, step 5. Inputs:
- `work/reports/TASK-068-impl.md`;
- tester-b's TEST PASS (message 2026-10-23: `test_fleet_alerts_pg.py`, 17 tests; `test_thresholds.py`, 3 added; 163 passed in WSL including the TASK-054 and TASK-056 suites; 18 of 18 plants red; report `work/reports/TASK-068-test.md` to be written by `main`).

Files reviewed:
- `manager/bitscan_manager/services/scheduler/fleet_alerts.py` (new, 165 lines);
- the `OncePerPeriod.due/mark` and `ReArm.due/mark` additions in `manager/bitscan_manager/services/audit/thresholds.py`;
- `JobRepo.default_partition_has_rows` in `manager/bitscan_manager/repositories/jobs.py`;
- the tester-b tests.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec and decision conformance.** `FleetAlerts` is built once per process with four windows. Each check runs in its own transaction.
  - **`agents_offline` (#65 (b)).** Fires when `offline / eligible > 5 %`, where eligible excludes `decommissioned` and `awaiting_approval` agents, so 5 of 100 is silent and 6 of 100 alerts. A `ReArm` window fires again only after the share was at or below 5 %. The boundary is exact in floating point, since `n / 20n` rounds to the same value as `0.05`. The detail holds counts only.
  - **`job_queue_age` (#66).** The oldest `queued` job of an **online** agent, older than 1 h (exactly 1 h is silent), at most once per hour.
  - **`inventory_stale` (#65 (c), lead's reading).** Online agents whose `last_inventory_at` (or enrolment base) is more than 2 × the current `inventory_interval_s` old, with the interval read each run. One entry per agent, re-armed when the agent leaves the stale set. An offline agent never alerts.
  - **`default_partition_rows` (#44, #65 (g)).** Fires when rows first appear, and again only after the partition was empty. A row planted as owner alerts once.
- **Commit-only marking (ruling).** Every check returns a `mark` callable, run only after its `with db.transaction()` exits cleanly. A failed or rolled-back alert therefore leaves its window free and fires on the next run (tested). Each alert is one `raise_alert` entry (`detail.alert = true`, actor `system`, action `alert.<kind>`). The counter rises on commit. A failing check is logged by name and exception type only, and the others still run.
- **Approved-file changes.**
  - `thresholds.py`: `OncePerPeriod.fire()` is now `due()` plus `mark()`, unchanged in behaviour. `ReArm.due()` re-arms the keys no longer above, returns the newly-above keys unrecorded, and `mark()` records one. `update()` and `sync()` are unchanged. The TASK-056 suite passes, with 3 tests added for the new methods.
  - `jobs.py`: one constant `SELECT EXISTS (SELECT 1 FROM scan_result_default)`, which needs only the app's SELECT grant. It is S608-clean, and the TASK-054 suite re-ran in WSL.
- **Security invariants.** Alert details hold counts, intervals or ages only, never hostnames or tokens. There are no writes other than audit entries, and no connection beyond the database.
- **Scope.** The new file plus the two lead-approved additions. The package `__init__` is unchanged.
- **Tests (my run, Windows).** `test_fleet_alerts_pg.py`, `test_thresholds.py`, `test_jobs_repo_pg.py` and `test_alerts.py`: 67 passed, 48 skipped (PostgreSQL; run in WSL by tester-b). ruff and format are clean, and `mypy --strict` is clean on the whole tree (175 files). The fleet-wide checks are tested with exact control inside a rolled-back transaction.

## Findings

None.

## Carry-overs

- **TASK-071.** Build `FleetAlerts(runtime.clock)` once, and call `.run(runtime.db, now)` after `run_sweep()` in the same scheduled job. Log a whole-run failure by type only.
- **TASK-067.** As already ruled, move the TASK-063 `agent_auth_failures` window to `count_and_check` plus an on-commit `mark_fired`, and build it once in `create_app()`.
