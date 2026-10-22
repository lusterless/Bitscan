# TASK-037 IMPL report: principal and auth dependencies

REQ: REQ-044, REQ-045, REQ-046, REQ-047 (the parts on failed checks and the per-user limit). Spec:
- TS §2.3 L118, TS §6 L1056, TS §6.2 L1080–L1091 and the route table, TS §6.3 L1136, TS §5.3 L1051;
- #48 (statuses and types), #53 (i) as decided ("M2 test-plan answers" (1)), #55 (d) (source IP is the TCP peer);
- the lead's correction of "M2 test-plan answers" (3) (2026-10-21) and the plan `work/plans/TASK-037.md`.

**Two approvals (TS §8.2, auth).**

## Files (2)

- `manager/bitscan_manager/auth/principal.py`: new, 70 non-blank lines.
- `manager/bitscan_manager/auth/dependencies.py`: new, 120 non-blank lines.

## `principal.py`

- `ROLE_ORDER = {viewer: 0, operator: 1, admin: 2}`, `SESSION_IDLE = 8 h`.
- `Principal(user_id, username, role, kind: TokenKind, token_id, totp_verified, totp_enrolled)` has three helpers:
  - `.restricted`: an admin session that is not TOTP-verified, REQ-046 (d);
  - `.admin_api_without_totp`: an admin's `bsk_` token while the admin has no TOTP, #53 (i);
  - `.at_least(minimum)`.
- `resolve(tokens: UserTokenRepo, raw_token, now) -> Principal | None` returns `None` for every failed check, so callers cannot tell the causes apart:
  - `parse_user_token` fails, which covers `bsa_`, `bse_`, unknown prefixes, and a wrong length or alphabet. The agent and enrolment tables are never read;
  - no row matches the token's SHA-256 (`find_by_hash`);
  - `row.kind` differs from the prefix kind;
  - `revoked_at` is set;
  - `expires_at <= now`;
  - the user is disabled, or has an unknown role;
  - a session whose `last_used_at`, or `created_at` if it was never used, plus 8 h is `<= now`.

  The role and the `totp_verified`/`totp_enrolled` values come from the row read on this request; an API principal is never `totp_verified`.

## `dependencies.py`

**`current_principal(request, runtime)`** works in this order:
1. **Source IP and header.** The IP is `request.client.host`, the TCP peer, so no proxy header is ever read. Exactly one `Authorization` header is accepted, with scheme `Bearer` in any case, then one space and a token with no spaces. Two headers, another scheme or an empty token is a failed check. Query strings and cookies are never read.
2. **Lookup.** Resolution runs in **its own short transaction** (`runtime.db.transaction()`). On success, and unless the principal is an admin API token without TOTP, `touch(token_id, now)` updates `last_used_at` (it skips the write if under 60 s old, TASK-031).
   - **Transaction split, accepted by the lead:** this transaction is separate from, and before, the route's own transaction. The plan wanted one shared transaction. But FastAPI runs a sync yield-dependency's enter and exit on different threadpool threads, which would break `AppDatabase`'s per-thread nesting guard and move one connection between threads.
   - The role is still read from `app_user` on every request (REQ-044 (5), REQ-045 (3)). The only effect is that a role change committed between this read and the route's own transaction takes effect on the next request.
3. **Failed check.** `blocked = limits.failed_check_blocked(ip)` is read first; then `limits.record_failed_check(ip)` runs. The request is answered 429 `rate_limited` with `Retry-After` if `blocked`, else 401 `unauthorized`. The 401 body is the same for every cause: detail `A valid bearer token is required.`, and the same `instance` for the same path.
   - Per the lead's correction 2026-10-21, **every token is checked first**. A valid token passes even from a limited IP. An invalid token from a limited IP gets 429 instead of 401, and it still counts toward the aggregate and its alert.
4. **Admin API token without TOTP.** 403 `totp_enrolment_required`. It is a genuine token, so it is not counted as a failed check, no alert follows, and `last_used_at` is not touched.
5. **Per-user limit.** `limits.allow_user(user_id)`; if refused, 429 `rate_limited` with `Retry-After`. The limit is counted only after authentication.
6. **Logging.** Debug log lines carry `user_id` and `token_id` only, never the token, its hash or the header.

`Retry-After` is computed here from `runtime.clock` (whole seconds to the end of the minute, 1–60), so the `RateLimits` protocol in `runtime.py` stays unchanged (lead, 2026-10-21).

**Factories.** Each returns a dependency marked with `.bitscan_auth = AuthMarker(check, minimum, allow_restricted, sink_gate)` for the route walk (REQ-045 (2), REQ-046 (6)). An unknown role raises `ValueError` when the route is defined.

| Factory | Check order after `current_principal` |
| --- | --- |
| `require_role(minimum, *, allow_restricted=False)` | restricted (unless allowed) → 403 `totp_enrolment_required`; role below `minimum` → 403 `forbidden` |
| `require_session(minimum="viewer", *, allow_restricted=False)` | restricted → 403 `totp_enrolment_required`; API token → 403 `session_required`; role → 403 `forbidden` |
| `require_totp_session(minimum="admin", *, sink_gate=True)` | restricted → 403 `totp_enrolment_required`; not a TOTP-verified session → 403 `totp_session_required`; role → 403 `forbidden`; then `runtime.sink_gate.refusing()` → 503 `audit_sink_unavailable` (checked last, so nothing runs either way) |

`allow_restricted=True` is for `POST /auth/totp/enrol` and `POST /auth/logout` only. `sink_gate=False` exists for M7's `DELETE /policies/{id}` under #1.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 89 files |
| `cd manager && pytest` (everything except the shipper tests); then `pytest tests/test_shipper.py` on its own | 900 passed, 231 skipped (pg); `test_shipper.py`: 25 passed, 2 skipped |
| Scratch (deleted): `create_app()` with test routes, a fake `Runtime` (fake clock, a fake db, a fake sink gate, a real `RateLimiter`) and `UserTokenRepo` monkeypatched with a fake | (1) |

(1) Scratch results:
- No header, `Basic`, a `bsa_` prefix and a `bsk_` prefix on a session row each got 401 `unauthorized`, and the body was the same on one path.
- A `bearer` scheme in lower case was accepted.
- A viewer `bsk_` on an operator route got 403 `forbidden`; an operator token passed.
- A `bsk_` on a session route got 403 `session_required`.
- A restricted admin got 403 `totp_enrolment_required`, except on the `allow_restricted` route.
- A verified admin passed the TOTP route, and got 503 `audit_sink_unavailable` while the gate refused.
- An admin `bsk_` with TOTP on the TOTP route got 403 `totp_session_required`. An admin `bsk_` without TOTP got 403 `totp_enrolment_required` and was not counted.
- Session idle: the session was accepted at 7 h 59 min and refused at 8 h.
- After 22 bad tokens: 429 with `Retry-After: 60`, while a valid token from the same IP got 200. The drained count included every failed request, the 429 ones too.

PostgreSQL is NOT RUN here; that is the TP-M2-15 matrix in WSL.

## For the tester (TP-M2-15, G25)

- Test routes look like `@app.get(...)` with `def r(p: Annotated[Principal, Depends(require_role("viewer"))])`. Set `app.state.runtime = Runtime(...)` with your fake clock and fake sink gate, the real `AppDatabase`, and `RateLimiter(clock)` from TASK-036.
- Route walk: for each `APIRoute`, read `getattr(dep.call, "bitscan_auth", None)` from `route.dependant.dependencies`.
- The 60 s `touch` skip (TASK-031) applies to CHK-M2-157.
