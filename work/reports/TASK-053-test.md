# TASK-053 TEST report: inventory repository

**Verdict: PASS** (2026-10-23, tester). REQ-075 (2), (3), (5), (6) and REQ-081 at the repository level. Plan checks: CHK-M3-070 to -074. Code tested: `bm/repositories/inventory.py` (`work/reports/TASK-053-impl.md`).

## Tests added
- `manager/tests/test_inventory_repo_pg.py`: 16 tests (marker `pg`). The 50,000-row cases run in rolled-back transactions.

## Commands
- W (`CI=true`): in the 109-passed run above. Durations, recorded with no gate: 50,000 package inserts 1.26 s; 50,000 agent_package upserts 0.60 s; delete-not-listed 0.04 s.
- Plants: 7 in WSL copies, all red.

## Acceptance criteria
- "50,000 packages insert in batches using only INSERT on `package`": CHK-M3-070 PASS.
- "a second call reports no new rows": CHK-M3-070 PASS.
- "two concurrent inserts of one new package give one row": CHK-M3-071 PASS.
- "the `agent_package` upsert keeps `first_seen_at`": CHK-M3-072 PASS.
- "delete-not-listed removes exactly the missing rows": CHK-M3-073 PASS.

## Revision 1 re-test (2026-10-23): PASS
- Change: `package_page` orders and pages on `name, architecture, version::debversion, version` (the reviewer's finding).
- Test gap closed: my original CHK-M3-074 data could not tell text order from Debian order. Two tests were added (`test_package_page_uses_debian_version_order`, `test_package_page_debian_order_within_name_and_architecture`), with the expected order written by hand from the dpkg rules: tilde, numeric parts, revision, epoch, and the `1.0`/`1.00` tie.
- W (`CI=true`): 18 passed. Plants: text order, no tie-break, and Debian ORDER BY with a text keyset → all 3 red; control green.
- Probe: PostgreSQL `debversion` accepts every odd string tried (21 cases), so the cast cannot fail on stored data.
