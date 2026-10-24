# TASK-052 TEST report: enrolment repository

**Verdict: PASS** (2026-10-23, tester). REQ-067, REQ-068 (1), (2), (5) and REQ-069 (1), (5) at the repository level. Plan checks: CHK-M3-060 to -065. Code tested: `bm/repositories/enrolment.py` (`work/reports/TASK-052-impl.md`).

## Tests added
- `manager/tests/test_enrolment_repo_pg.py`: 40 tests (marker `pg`).

## Commands
- W (`CI=true`): in the 109-passed run above.
- Plants: 11 in WSL copies, all red, including CHK-M3-332, -333, -334 and -335 (the mutation-table rows owned by TASK-052).

## Acceptance criteria
- "20 concurrent uses of a `max_uses` 5 token succeed exactly 5 times": CHK-M3-060 PASS (5 rounds).
- "an expired, revoked or out-of-CIDR use returns none without incrementing `uses`": CHK-M3-061, -062 PASS.
- "two concurrent decisions on one request succeed once": CHK-M3-063 PASS.
- "matches list every other agent sharing the hostname or machine-id": CHK-M3-064 PASS.

## Notes for later tasks
- IPv4-mapped IPv6 peers do not match IPv4 CIDRs in SQL. TASK-067 must convert them (plan), and TASK-067 TEST checks it.
- A CIDR with host bits makes the database raise. TASK-066 must refuse it with 400 first (CHK-M3-191).
