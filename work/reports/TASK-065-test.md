# TASK-065 TEST report: offline_sweep core

**Verdict: PASS** (2026-10-23, tester-b). REQ-078 (1) to (6); REQ-086 (2) (jobs-expired metric). Plan checks: CHK-M3-180 to -188; mutation rows CHK-M3-369, -373 and the G33 plant. Code tested: `bm/services/scheduler/sweep.py`, with the TASK-051/054 SQL it calls (`work/reports/TASK-065-impl.md`).

## Tests added
- `manager/tests/test_sweep_pg.py`: 20 tests (marker `pg`), `run_sweep` on the real `AppDatabase` as `bitscan_app`, the fake clock passed as `now`.
- `manager/tests/test_sweep.py`: 7 unit tests with fake stores and a fake database (G5 coverage on Windows).

## Commands
- W (`CI=true`): 145 passed, 0 skipped (with the queue, agent, job and ingest suites), no container left.
- L: 7 passed; ruff, format, mypy clean (168 files); `sweep.py` 98 %.
- Plants (WSL copies, control 20 passed): 19 of 19 red (tests/m3/report.md CHK-M3-180-mut).

## Acceptance criteria
- Statuses at the REQ-078 boundaries: CHK-M3-180, -181 PASS.
- Decommission at 7 days and never at 0, token revoked and then 401 `token_revoked`: CHK-M3-182 PASS.
- Expiry and inventory failure exactly as REQ-078, no job row created: CHK-M3-183 PASS.
- Held agents untouched: CHK-M3-184 PASS.
- A step forced to fail leaves the others applied, the next sweep completes: CHK-M3-185 PASS.
- Audit entries follow #73: CHK-M3-182, -186 PASS.

## Carry-overs
- Decommission skipped when the setting is 0: CHK-M3-182 PASS (the unit test also shows the repository is not called).
- One audit entry per decommissioned agent: CHK-M3-182 PASS.
- Jobs-expired metric only after commit: CHK-M3-187 PASS.
- A failing step leaves the others applied: CHK-M3-185 PASS.
- GREATEST age base and the fresh-heartbeat rule for `online`: CHK-M3-181 PASS.

## Notes
- The sweep is fleet-wide and commits, so the tests assert only on their own agents and jobs. The 10,000-agent timing runs in a rolled-back transaction.
- Observation (no defect): `expire_past_pickup` expires at `pickup_by <= now`, which matches the pull's `pickup_by > now` (TASK-054), so a job is never both pullable and expired; the equality instant itself is not asserted.
