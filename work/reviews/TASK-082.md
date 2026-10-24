# TASK-082 REVIEW: every attempt counts on enrol and sign-in

Reviewer: reviewer. Date: 2026-10-23. REQ-065 (2), REQ-068, REQ-047. Spec: TS §6.3 L1136 (unauthenticated routes `/auth/login` and `/agent/enroll`: 10 requests per minute per source IP); #55 (c) ("every request to the route" counts). Decisions (`work/decisions.md`, 2026-10-23): the user ordered this follow-up when giving TASK-067 its second approval; the lead ruled the design as option (B): a custom `APIRoute` subclass on the two operations runs the per-IP limit before FastAPI's handler, then delegates unchanged. Inputs:
- `work/reports/TASK-082-impl.md`;
- `work/reports/TASK-082-test.md` (PASS: CHK-M3-380 to -384; `manager/tests/test_attempt_limits_pg.py`, 18 tests; 5 of 5 plants red; the M2 sign-in suites and G25 re-run green; CHK-M3-382 corrected by tester-d).

Files reviewed:
- `manager/bitscan_manager/api/attempt_limits.py` (new, 57 lines);
- `manager/bitscan_manager/api/agent/enrol.py`;
- `manager/bitscan_manager/api/user/auth.py` (an M2 file with the user's second approval).

Verdict: APPROVED

**Two approvals required** (TS §8.2; auth and enrolment). This is the first one; the user's second approval is still needed.

## What was checked (the option (B) checklist)

- **The limit runs in the route class, before any body parse.**
  - `limit_first(check)` subclasses `APIRoute`. Its `get_route_handler` wraps FastAPI's own handler and calls `check(request)` before delegating. FastAPI parses the JSON body only inside that handler (`fastapi/routing.py`), so a non-JSON, malformed or invalid-UTF-8 body now counts.
  - `per_ip_limit` keys by `peer_key()` (the TASK-067 normalisation) and raises `Problem(429, "rate_limited", …, Retry-After)`. The app's existing handler answers it as problem+json with the security headers.
  - 11 non-JSON or malformed attempts from one IP give 10 × 400 and then 429, on both routes (CHK-M3-380).
  - As tester-d corrected, "before any body read" can only mean before FastAPI's parse. The M2 `BodyLimit` middleware still buffers a normal-mode body (≤ 1 MiB) before every route, by design. A body over 1 MiB is refused 413 there and does not count, which the ruling accepts.
- **FastAPI's parsing, validation, problem bodies and the OpenAPI document are unchanged.**
  - The route functions still declare `LoginRequest` and `EnrolRequest`, so FastAPI parses and validates exactly as before. Field-error detail stays `Invalid request: body.<field>`.
  - The impl's 11-case capture of sign-in answers is identical apart from the intended 429. The document is byte-identical: my re-export matched the committed `manager/openapi.json` in the TASK-072 run on this tree, and tester-d compared the login operation with `git show HEAD`.
- **The limit no longer runs in `login_limit` or `enrolment_caller`.** `login_limit` is removed, and `login` now depends on `get_runtime` only. `enrolment_caller` keeps only the `bse_` shape and peer check, still counted as a failed check through `failed_check`, with its `bse_` marker unchanged. Each attempt therefore counts exactly once against the 10-per-minute limit (CHK-M3-381: separate limits, nothing used or created on a 429).
- **Everything else in order.**
  - Middleware (`RequestLog`, `SecurityHeaders`, `BodyLimit`), then the route-class limit, then FastAPI's handler (body parse, then the dependencies in their previous order), then the route.
  - Sign-in back-off, equal timing, the 4-slot Argon2id gate and the single 401 body live in `auth/login.py` and are untouched.
  - `/login` keeps its path, tag and position, now in a small `_sign_in` router included into `/auth`. No other route uses the class.
- **The M2 file.** In `api/user/auth.py`, only the sign-in limit moved from a dependency to the route class (plus the earlier, already-approved `peer_key` and `TotpEnrolRequest` changes from TASK-067). G25 and the M2 login, users and rate-limit suites are green (CHK-M3-384).
- **Tests (my run, Windows).** `test_attempt_limits_pg.py`, `test_login.py`, `test_login_pg.py`, `test_enrol_api_pg.py`, `test_ratelimit.py`, `test_security_m2.py` and `test_auth_dependencies.py`: 59 passed, 162 skipped (PostgreSQL; run in WSL by tester-d), 2 failed. The 2 are `test_login.py::test_openapi_error_contract`, broken by the in-progress TASK-074 inventory 422 in the same tree, as the lead and tester-d note. ruff and format are clean, and `mypy --strict` is clean on the whole tree (200 files).

## Findings

None.

## Note for the lead

The TASK-072 review raised the same parse-before-dependency gap for the `bsa_` JSON routes (heartbeat, and results in TASK-073): a non-JSON body gets 400 without a token check or failed-check count. If you want those counted too, `limit_first` can wrap a check that counts the failed attempt for unauthenticated non-JSON bodies. It would need its own ruling, because those routes are authenticated rather than per-IP-limited.
