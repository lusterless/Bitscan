# TASK-064 TEST report: inventory ingestion

**Verdict: PASS** (2026-10-23, tester-b), on revision 1. REQ-075 (1) to (7). Plan checks: CHK-M3-170 to -175 (CHK-M3-176, the G5 plant, is sized at the M3 gate). Code tested: `bm/services/inventory/ingest.py`, `bm/services/audit/thresholds.py` (r1 two-phase `count_and_check`/`mark_fired`) (`work/reports/TASK-064-impl.md`).

## Tests added
- `manager/tests/test_inventory_ingest.py`: 20 unit tests with fake stores, real decoder output and a real `SlidingCount` on a fake clock.
- `manager/tests/test_inventory_ingest_pg.py`: 13 tests (marker `pg`) as `bitscan_app` through `AppDatabase` transactions, with the real repositories, audit chain and alert counter.

## Commands
- W (`CI=true`): `tester2_m3run.sh t064r1` with both files, `test_thresholds.py` and `test_inventory_repo_pg.py`: 70 passed, 0 skipped, no container left.
- L: 39 passed (unit + thresholds); ruff, format and mypy clean (166 files); coverage of `ingest.py` and `thresholds.py` 100 %.
- Plants (WSL copies, control 52 passed): 16 of 16 red (tests/m3/report.md CHK-M3-170-mut).

## Acceptance criteria
- First upload, same list, upgrade plus removal: CHK-M3-170, -171, -172 PASS.
- Forced mid-transaction failure leaves exactly the earlier rows: CHK-M3-173 PASS.
- Two agents with one new package make one `package` row: CHK-M3-174 PASS.
- More than 1,000 new packages in the #65 window alert once: CHK-M3-175 PASS.
- Runs as `bitscan_app` with the TS §5.2 grants (no UPDATE on `package`): every pg test asserts `session_user` = `bitscan_app` inside the transaction.

## Carry-overs
- Empty `source` stored as NULL (#60): CHK-M3-170 PASS.
- Burst alert once per agent per 24 h above 1,000: CHK-M3-175 PASS.
- An upload by an agent revoked since its token check writes nothing: CHK-M3-170-revoked PASS (also while the revoke holds the row lock).

## Round history
- Round 0: the rolled-back burst alert used the day's slot, so a retried upload got no alert (`test_rolled_back_burst_alert_does_not_use_the_daily_slot`: `assert 0 == 1`). Ruling 2026-10-23 (a); fixed in r1 (fired marked on commit). Plant P6 survived round 0; the reverse status-change test was added.

## For TASK-074
- Build the burst window once per process as `SlidingCount(clock, 24 h, 24 h, NEW_PACKAGES_PER_DAY)` and pass `tx.on_commit`; TASK-074 TEST checks the route's window parameters, which these tests cannot see.
- `AgentGone` → 401 `token_revoked`.
