# TASK-082 TEST report: every attempt counts on enrol and sign-in

**Verdict: PASS** (2026-10-23, tester-d). REQ-065 (2), REQ-068, REQ-047; TS §6.3 L1136, #55 (c). Decisions 2026-10-23 "TASK-067 second approval given" and "TASK-082 design" (option (B)). Plan checks: CHK-M3-380 to -384 (TP-M3-36, added to the plan). Code: `bm/api/attempt_limits.py`, `bm/api/agent/enrol.py`, and `bm/api/user/auth.py` (M2 file) (`work/reports/TASK-082-impl.md`).

## Commands
- W (CI=true), 14 files: 435 passed, 4 failed. The 2 `test_openapi_error_contract` failures belong to TASK-074. The 2 others were my own zero-bytes check, which was wrong and has been replaced (CHK-M3-382).
- W plant control: `test_attempt_limits_pg.py` 18 of 18.
- L: the M2 login operation compared with `git show HEAD`; ruff, format and mypy are clean.
- Plants: 5 of 5 red.

## Acceptance criteria
- 11 non-JSON or malformed attempts from one IP give 10 × 400 then 429 `rate_limited`, on each route: CHK-M3-380 PASS.
- Every attempt counts (well-formed ones too), the limits are separate, and nothing is used or created on a 429: CHK-M3-381 PASS.
- Decided before the body is parsed; the 413 cap still applies first: CHK-M3-382 PASS.
- OpenAPI unchanged for login, request schemas documented, no 422: CHK-M3-383 PASS.
- M2 sign-in suites and G25 re-run: CHK-M3-384 PASS.

## Observation
A body over 1 MiB is refused by the middleware before the route and does not count toward the per-IP limit. This follows the design ruling ("the body-cap middleware still runs before the route").

## Test files
- New: `manager/tests/test_attempt_limits_pg.py`.
