# TASK-075 TEST report: agent token rotation

**Verdict: PASS on revision 1** (2026-10-23, tester-e). REQ-071 (1)–(8), REQ-063 (2), (3), REQ-060; #60, #62; user ruling 2026-10-23 (30-day cap); lead rulings 2026-10-23 on my Q1 (the 24 h check before the window) and Q2 (the retry counts for the new-IP alert). Plan checks CHK-M3-265 to -273, the route walk and matrix (CHK-M3-169-075), mutation rows CHK-M3-342, -343 and -344. Code: `bm/services/enrolment/rotation.py` (r1), `bm/api/agent/rotate.py`, `bm/api/agent/__init__.py` (`work/reports/TASK-075-impl.md`). Tree copies: 10:04:13Z (suite) and about 10:12Z and 10:35Z (plants), all with r1.

## Round 1 (before r1)
Not a FAIL round. Before running I asked `main` two spec questions:
- **Q1:** the window check ran first, so the 24 h rule could never answer (a fresh token's window opens at least 30 days later).
- **Q2:** the retry skipped the new-IP alert.

Both were ruled as I recommended and built as r1. My tests were written to the rulings and pass on r1.

## Commands
- W (CI=true), with 4 other route files: `test_rotation_api_pg.py` 44 of 44 passed. The retry-TTL test added after the plants is green in the 45-test control.
- W plants: 23 of 23 red. One plant (the retry's `expires_at` fixed at 365 d) survived the first run because every retry test used the default TTL 365. I added `test_the_retry_token_lives_for_the_current_ttl`; the plant is now red.
- L: ruff, format and mypy clean.

## Acceptance criteria
- TTL 365 window: day 334 refused with the alert, day 335 rotates; Rotate schema; `expires_at` = now + current TTL: CHK-M3-265 PASS.
- Window edges for TTL 60 (and 61, 100, 730): CHK-M3-266 PASS.
- Lost-response retry: fresh token, the unused one dies, the old one works, `last_rotation_at` kept so the 30-day cap cannot be extended: CHK-M3-267 PASS.
- Overlap and reuse at 9 min 59 s and 10 min; rotate with the old token after first use is reuse: CHK-M3-268 PASS.
- 24 h rule → 429 with `Retry-After` (r1); after an unused rotation allowed: CHK-M3-269 PASS.
- New-IP alert never, 6 d, 8 d, and on the retry (r1): CHK-M3-270 PASS.
- After `expires_at`: 401 `token_expired`: CHK-M3-271 PASS.
- TTL change only affects later tokens: CHK-M3-272 PASS.
- Body empty or `{}` only, `null` refused; only hashes stored; concurrency; OpenAPI: CHK-M3-273 PASS.
- Route walk and matrix: CHK-M3-169-075 PASS.

## Test changes
- New: `manager/tests/test_rotation_api_pg.py` (45 tests).

## Notes for the reviewer
1. A rotation refused outside the window alerts on every attempt (an immediate alert, TS §8.4 L1290). The new-IP alert is written only for a successful rotation or retry, not for a refused one.
2. Concurrent rotations with the same token: the losers are answered by the window check (403 plus a `rotation_outside_window` alert), because their token is no longer current once the winner commits. That is a refusal with a false-positive alert. Only "exactly one 200, no 500" is asserted.

## Revision 2 (2026-10-23, tester-f): PASS
Ruling: user, 2026-10-23, "TASK-075 revision 2 ordered". Code: `bm/services/enrolment/rotation.py` only (impl report "Revision 2"). Tree copies: 14:13:42Z (suite) and about 14:15Z (plants).
- W: rotation, token check, alerts and agent auth files: 168 passed, 0 skipped. Plants: control 49 passed, 28 of 28 red (4 new r2 plants plus the 24 r1 plants).
- L: ruff, format and mypy clean.
- The race is made deterministic: the agent row is held `FOR UPDATE` until both requests wait on a lock, so both token checks see the token as current. Two simultaneous rotates → one rotation plus one lost-response retry, both 200, no `rotation_outside_window`, and the new-IP rule applied (CHK-M3-273-r2). The plant "no post-lock re-check" is red (CHK-M3-265-mut-r2).
- Test changes in `manager/tests/test_rotation_api_pg.py`: 4 new tests; the r1 test `test_concurrent_rotations_issue_one_token` is replaced by `test_concurrent_rotations_are_one_rotation_and_retries` (4 × 200), because r2 changes that expectation.
- Note for the reviewer and the user: a waiting call whose concurrent rotation's new token was **already used** answers 429 (the 24 h rule), as the impl report states. The ruling covers only the unused case. The test pins 429, with no token, no entry and no change, which is the conservative outcome: the token check passed while the token was current. Plant R2-2 (treating it as reuse, revoking both) is red against that pin. If you rule it should be reuse, that is a code change, and the test changes with it.
