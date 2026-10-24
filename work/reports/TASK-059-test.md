# TASK-059 TEST report: agent token check service

**Verdict: PASS** (2026-10-23, tester). REQ-064 (1) to (8) at the service level, and REQ-071 (4) (overlap and reuse). Two approvals are needed. Plan checks: CHK-M3-120 to -127. Code tested: `bm/services/enrolment/{__init__,token_check}.py` (`work/reports/TASK-059-impl.md`).

## Tests added
- `manager/tests/test_token_check.py`: 44 tests at the base revision (49 with the r1 cap cases). It uses fake repositories with the real `AgentRow` and `RequestRow` types, real `bsa_` tokens, and `now` passed in.

## Commands (L)
- 44 passed; ruff, format and mypy clean.
- Plants (throwaway copies; control 44 passed): 13 of 14 red:
  - CHK-M3-339, -340, -341, -342, -344;
  - 403 counted;
  - order swap (expiry after the mismatch);
  - overlap 9 min;
  - no first-use mark;
  - rejected-new check removed;
  - no alert on a pending-request mismatch;
  - a replaced approved request treated as pending;
  - the token in the alert detail.

  The survivor (case-insensitive machine-id comparison) is equivalent: see CHK-M3-123.

## Acceptance criteria
- "every row of the plan's outcome table … gives its outcome and writes exactly the stated revoke and alert": CHK-M3-120 PASS.
- "no pending outcome is counted as a failed check": CHK-M3-124 PASS.
- The route-level matrix on PostgreSQL is TASK-063 (CHK-M3-160 to -169).

## Finding raised (resolved)
- At the base revision, a previous token whose new token was never used had no expiry bound. The user ruled the 30-day cap (work/decisions.md 2026-10-23), implemented as revision 1 and re-tested below.

## Revision 1 re-test (2026-10-23): PASS
- The 30-day cap on an unused rotation, as ruled.
- 5 cap tests added: the boundary at 29 d 23:59:59 / 30 d; a retry not moving the cap; the new token and a used rotation unaffected; NULL fails closed; the cap before the mismatch check.
- The two older fixtures were corrected (`last_rotation_at` set, as `rotate()` does).
- 49 passed. 6 cap plants red, including "no cap"; the earlier plants still red.
