# TASK-068 TEST report: fleet threshold alerts

**Verdict: PASS** (2026-10-23, tester-b). REQ-079 (1) to (5). Plan checks: CHK-M3-210 to -214. Code tested: `bm/services/scheduler/fleet_alerts.py`, and the touched approved files `bm/services/audit/thresholds.py` (TASK-056: `due`/`mark`) and `bm/repositories/jobs.py` (TASK-054: `default_partition_has_rows`) (`work/reports/TASK-068-impl.md`).

## Tests added
- `manager/tests/test_fleet_alerts_pg.py`: 17 tests (marker `pg`). Fleet-wide counts are controlled exactly: inside one rolled-back `bitscan_app` transaction every pre-existing agent is set `decommissioned`, and each check runs as a savepoint. Default-partition rows are planted as owner and removed.
- `manager/tests/test_thresholds.py`: 3 tests for the two-phase window methods.

## Commands
- W (`CI=true`): G33 set plus the TASK-054, -056 and agent-repo suites: 163 passed, 0 skipped, no container left.
- L: `test_thresholds.py` 22 passed; ruff, format, mypy clean (175 files).
- Plants (WSL copies, control 38 passed): 18 of 18 red (tests/m3/report.md CHK-M3-210-mut).

## Acceptance criteria
- 5 of 100 offline raise nothing, 6 raise one entry, repeats follow #65: CHK-M3-210 PASS.
- Queue-age (#66) and stale-inventory boundaries of REQ-079: CHK-M3-211, -212 PASS.
- A row planted as owner in `scan_result_default` raises one entry: CHK-M3-213 PASS.
- Each alert is one entry with its kind, counted after its commit only: CHK-M3-214 PASS.

## Carry-overs
- Lead: a failed alert commit leaves each window unmarked so the next run alerts: CHK-M3-214 PASS for all four checks. TASK-054 and TASK-056 suites re-run: PASS.
- For TASK-071: build `FleetAlerts` once per process and run it after `run_sweep`; TASK-071 TEST checks that wiring.
