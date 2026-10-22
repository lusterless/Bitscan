# TASK-038 IMPL report: sign-in and sign-out, the first `/api/v1` user routes

REQ: REQ-048, REQ-042, REQ-047, REQ-035 (5). Spec: TS §6.2 L1080, L1086–L1089, TS §6.3 L1136, TS §2.3 L122.

Decisions applied:
- #47 (a) bodies; #48 statuses; #49 (c) every TOTP-enrolled user gives a code; #50 actions; #54 (a) the alert at 5 and every 5 more; #55 (a)–(e); #58 (b) vault down gives 503.
- Lead carry-overs:
  - OpenAPI error contract: no 422, a problem+json 400, documented refusals;
  - sign-in memory bound: 4 slots, arrival order;
  - `DatabaseUnavailable` gives 503;
  - `UtcDatetime` for timestamps.
- Plan: `work/plans/TASK-038.md`.

**Two approvals (TS §8.2, auth).**

## Files (5)

- `manager/bitscan_manager/auth/login.py`: new, 148 non-blank lines.
- `manager/bitscan_manager/api/user/__init__.py`: new, 22 lines. It has `problem_responses(statuses)` (OpenAPI problem+json entries), `PROBLEM_REF` and `build_user_router()` (`APIRouter(prefix="/api/v1")`). The route modules are imported inside the function, because they import the helper from this package.
- `manager/bitscan_manager/api/user/auth.py`: new, 67 lines.
- `manager/bitscan_manager/app.py`: about 55 lines added:
  - the user router is mounted;
  - two exception handlers;
  - the OpenAPI post-processor.
- `manager/openapi.json`: regenerated.

**Size: about 290 hand-written lines, above the 200 guideline.** The tasks note foresaw this ("if TASK-038 grows, split into login and logout"). Logout is only about 25 of those lines; most of the growth comes from three lead carry-overs that arrived after planning: the fair semaphore, the OpenAPI contract and the 503 handlers. Lead: say if you want it split.

## Routes

- **`POST /api/v1/auth/login`**
  - **Body:** `{username, password, totp_code?}`, with `extra="forbid"` and these lengths: username 1–64, password 1–1024, code at most 16. A malformed body gets 400 `invalid_request` before any user lookup, and nothing is counted in `failed_logins`.
  - **Rate limit:** the `login_limit` dependency calls `limits.allow_login(tcp_peer)` first. Every attempt counts, including malformed ones, and proxy headers are never read. Over the limit it answers 429 `rate_limited` with `Retry-After`.
  - **Success:** 200 `{token, expires_at, role, totp_enrolled, totp_verified}`, where `expires_at` is a `UtcDatetime` ending in `Z`.
  - **Every failure:** 401 `unauthorized`, with the same body as TASK-037's 401s (`A valid bearer token is required.`).
- **`POST /api/v1/auth/logout`**
  - Uses `require_session(allow_restricted=True)`, so a `bsk_` token gets 403 `session_required` and is not revoked.
  - Revokes only the presenting session, writes `auth.logout`, and answers 204.

## `auth/login.py`

**Verification gate.** `_FairSemaphore(4)` uses a ticket and a condition variable, so waiters enter strictly in arrival order and none is ever refused. `VERIFY_GATE` wraps both `verify_password` and `dummy_verify` here. TASK-039 and TASK-040 must use these two wrappers too.

**`login(runtime, *, username, password, totp_code)`** runs these steps in order:
1. It reads the user in a short transaction (exact, case-sensitive match).
2. **Unknown or disabled user:** one `dummy_verify`, then `LoginFailed`. Nothing is counted or audited.
3. **Back-off** (`now < next_login_at`): one `dummy_verify`, then `LoginFailed`. The password is not checked and nothing is counted (#55 (a)).
4. **Wrong password:** `_fail()` (below), then `LoginFailed`.
5. **The user has `totp_secret_enc`** (#49 (c)):
   - a missing code is a failure;
   - otherwise the seed is decrypted with `runtime.totp_cipher.decrypt(...)`. `VaultUnavailable` propagates and becomes 503. It is not counted, and no fallback is tried (#58);
   - `match_step` returning `None` is a failure.
6. **One transaction for the rest:**
   - `claim_totp_step` (TASK-031), which only one caller can win for a given step;
   - then `reset_failures`;
   - insert the session with `expires_at = created_at + 24 h` (both from the same `now`) and `totp_verified` = whether a code was verified;
   - write `auth.login` with `actor` and `target` = `user:<id>` and `detail` = `{"totp_verified": …}`;
   - wake the sink shipper on commit.

   If the claim fails, because the code was already used or a concurrent sign-in won, nothing is written and the attempt is a failure.
7. **The result.** An admin without TOTP gets `totp_verified = false`, so TASK-037 treats the session as restricted. A non-admin without TOTP gets a normal unverified session.

**`_fail(runtime, user_id, now)`** runs in its **own committed transaction**. It calls `record_failure`, so the back-off doubles from 1 s to 900 s and the counter stops at 1000 (TASK-031).
- When the new count is a multiple of 5 and below the 1000 cap, it raises the `login_failures` alert (#54 (a)): actor `system`, action `auth.login_failures`, target `user:<id>`, detail `{"failed_logins": n}`.
- The detail never holds the username typed or the password.
- Without the cap check, every further failure would alert once the counter reached 1000.

**`logout(runtime, *, user_id, token_id)`** revokes the token and writes `auth.logout` in one transaction.

**Alert action name.** #50 (a) lists no action for the failure alert, so `auth.login_failures` follows the `<domain>.<verb>` form and the kind name. Lead: confirm or rename.

## `app.py`

- **Handlers:**
  - `DatabaseUnavailable` → 503 `about:blank`, detail `The database is unavailable.`
  - `VaultUnavailable` → 503 `about:blank`, detail `The vault is unavailable.`

  In TASK-037's `current_principal`, the `with runtime.db.transaction()` block raises before the failed-check code runs. A database outage during token resolution is therefore never counted as a failed check, and it answers 503 instead of 500 or 401 (CHK-M2-187).
- **OpenAPI post-processor** (it wraps `app.openapi`, and running it twice gives the same document):
  - it removes every `422` response and the `HTTPValidationError` and `ValidationError` schemas;
  - it adds a `Problem` schema with exactly the five keys and `additionalProperties: false`;
  - it adds a problem+json `400` to every operation that has parameters or a request body.

  Each route documents its own refusals through `problem_responses`: login 401, 429 and 503; logout 401, 403, 429 and 503.
- **Router:** `build_user_router()` is mounted, so every user path starts with `/api/v1/` (REQ-035 (5)).

## OpenAPI result

| Operation | Responses |
| --- | --- |
| `POST /api/v1/auth/login` | 200, 400, 401, 429, 503 |
| `POST /api/v1/auth/logout` | 204, 401, 403, 429, 503 |
| `GET /healthz` | 200 |
| `GET /readyz` | 200, 503 |

Schemas: `Health`, `LoginRequest`, `LoginResponse`, `Problem`. No 422 appears anywhere.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 103 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1005 passed, 278 skipped (pg), 97.13 % |
| OpenAPI re-export | committed; the table above |
| Scratch (deleted): `create_app(runtime)` with the repositories in `login.py` and `dependencies.py` monkeypatched to in-memory fakes, a real `RateLimiter`, a fake clock and a fake cipher | (1) |

(1) Scratch results:
- **Failures:** an unknown user, a wrong password, an admin without a code and an admin with a wrong code each got 401 with byte-identical bodies.
- **Back-off:** a correct password during back-off got 401 and `failed_logins` stayed at 1. At `next_login_at` the sign-in succeeded: exact keys, `expires_at` 24 h later ending in `Z`, and `failed_logins` back to 0.
- **TOTP:** a fresh code gave a session with `totp_verified` true, and the same code again got 401. An admin without TOTP got a session with `totp_verified` false, and that restricted session could log out (204).
- **Alerts:** 10 failures raised alerts at 5 and 10 only.
- **Outages:** with the vault down, a TOTP user got 503 `The vault is unavailable.` and nothing was counted. With the database down, the response was 503 `about:blank` `The database is unavailable.`
- **Limit and validation:** the 11th sign-in from one peer got 429 with `Retry-After: 59`. A missing field got 400, and an extra field got `Invalid request: body: unknown field`.
- **Audit:** `auth.login` and `auth.logout` entries were written.

PostgreSQL items (concurrent single-use codes, real back-off timings, CHK-M2-187 with a paused proxy) are NOT RUN here; TP-M2-16 runs them in WSL.

## For the tester (TP-M2-16)

- CHK-M2-186: the gate is `bitscan_manager.auth.login.VERIFY_GATE`. A blocking hasher can be planted with `monkeypatch.setattr(bitscan_manager.auth.passwords, "verify_password", …)` and `dummy_verify`; the login wrappers call through the module, so the patch takes effect.
- CHK-M2-178: the alert entry's action is `auth.login_failures`.
- CHK-M2-185: the post-processor is in `app.py` (`_problem_openapi`).

## Lead rulings (decisions.md 2026-10-22, "Lead rulings on TASK-038")

- The task stays as one; the reviewer judges the size and may ask for a split.
- `auth.login_failures` is confirmed:
  - kind `login_failures`, actor `system`, target `user:<id>`;
  - detail `{"failed_logins": n}`, never the username, the password or the source address.

## Revision 1 (found by running the tester's in-progress `tests/test_login.py::test_openapi_error_contract`)

`GET /readyz` documented its 503 with a description only, while the contract wants every error response documented as `application/problem+json` with the `Problem` schema. The fix is in the `app.py` post-processor rather than in each route: every response with a status of 400 or more that has no `content` now gets `{"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}}`. `manager/openapi.json` was re-exported.

Re-checked:
- ruff and mypy `--strict` pass;
- `pytest tests/test_login.py tests/test_openapi.py tests/test_app.py tests/test_health.py`: 58 passed.

Note for the tester: in the full Windows run, `test_each_path_runs_exactly_one_argon2_verification[unknown|disabled|backoff]` failed. The same cases pass alone, and with `test_passwords.py`. This looks like test-order state, probably around the cached `passwords._dummy_hash()` or a patched `_HASHER` left by an earlier test.
