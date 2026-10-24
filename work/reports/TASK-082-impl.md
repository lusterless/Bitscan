# TASK-082 IMPL report: every attempt counts on enrol and sign-in

REQ: REQ-065, REQ-068, REQ-047. Spec: TS §6.3 L1136; #55 (c). User-ordered follow-up (decisions 2026-10-23); design **option (B)** per the lead's ruling. **Two approvals** (auth, enrolment).

**Touched M2 file:** `manager/bitscan_manager/api/user/auth.py`.

## Why

FastAPI 0.148 parses a JSON body before it solves any dependency (`fastapi/routing.py` L451–L491). A body that fails to parse (non-JSON, malformed JSON, invalid UTF-8) is therefore answered 400 before the per-IP limit dependency runs, and that attempt was never counted. A client could send unlimited unparseable sign-in or enrolment attempts.

## Files (3)

- `manager/bitscan_manager/api/attempt_limits.py`: new, 57 lines.
  - `limit_first(check)` returns an `APIRoute` subclass whose route handler runs `check(request)` **before** FastAPI's own handler reads or parses anything, then delegates unchanged.
  - `per_ip_limit(allow, detail)` builds a check. It takes the peer key from `api.peer.peer_key`, calls the limiter (every attempt counts), and raises `Problem(429, "rate_limited", detail, {"Retry-After": seconds to the end of the minute})`.
  - The `Problem` is answered by the app's existing handler, so the problem+json body, the title and the security headers are as before.
- `manager/bitscan_manager/api/agent/enrol.py`:
  - The enrol router is `APIRouter(route_class=limit_first(allow_enrol check))`.
  - The `allow_enrol` call moved out of `enrolment_caller`. The dependency now checks only the bearer token shape and the peer, and still counts a bad token as a failed check. Its marker `bitscan_agent_auth = "bse_"` is unchanged.
- `manager/bitscan_manager/api/user/auth.py` (**M2**):
  - `POST /login` moves to a small `_sign_in` router with `route_class=limit_first(allow_login check)`, included into the `/auth` router at the same position. The path and tag are unchanged.
  - `login_limit` is removed; `login` now depends on `get_runtime`.
  - Sign-in back-off, timing, the Argon2id gate and the 401 body are untouched, because they live in `auth/login.py`.

`manager/openapi.json`: **byte-identical** (G6). FastAPI still sees the same body parameter, so the request schemas `LoginRequest` and `EnrolRequest` are documented as before, and the export lists no 422.

## Order on each route (unchanged except for step 2)

1. `RequestLog`, `SecurityHeaders`, `BodyLimit` (1 MiB cap): middleware, before any route, as before.
2. **New:** the route-class check, which is the per-IP limit (10 per minute), counting every attempt, before the body is read.
3. FastAPI's handler: body parse, then dependencies in their current order. Enrol: `get_runtime`, then `enrolment_caller` (`bse_` shape), then body validation. Login: `get_runtime`, then body validation.
4. The route.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (91 files).
- `pytest -q`: 2189 passed, 955 skipped. The one failure is the known TASK-072 test `test_body_caps.py::test_other_agent_routes_keep_one_mib`.
- OpenAPI: `cmp` against the export taken before this task shows no difference.
- **Acceptance probe** on `create_app()`, with a fake database, a real `RateLimiter`, and the sign-in and enrol services faked. Eleven attempts from one IP within a minute, on each route:

  | Route | Body | Result |
  | --- | --- | --- |
  | `/api/v1/auth/login` | `text/plain` "hello" | 10 × 400, then 429 |
  | `/api/v1/auth/login` | malformed JSON `{"x":` | 10 × 400, then 429 |
  | `/api/v1/agent/enroll` | `text/plain` "hello" | 10 × 400, then 429 |
  | `/api/v1/agent/enroll` | malformed JSON `{"x":` | 10 × 400, then 429 |

  Every 429 had `rate_limited`, `Retry-After: 55`, `application/problem+json` and the CSP header.
- **Unchanged answers:**
  - A capture of 11 sign-in body cases (non-JSON, truncated, array, missing field, extra key, bad type, `text/plain`, no content-type, empty, valid, NaN) is byte-identical to before for the first 10. The 11th is now 429, which is the intended change: the earlier malformed attempts counted.
  - Field-error detail is still `Invalid request: body.username`.
  - A valid enrol gives 200; a `bsa_` on enrol gives 401.
  - A body over 1 MiB gives 413 `too_large` (`BodyLimit`, before the route).
  - The route walk (descending FastAPI 0.148's `_IncludedRouter`) shows `/login` and `/enroll` as `LimitFirstRoute`, with the enrol dependency marker `bse_` intact.
- PostgreSQL and the M2 sign-in suites (TP-M3-36, re-run of `test_login.py`): **NOT RUN locally**; WSL.

## Deviations

None from option (B).
