# TASK-037 REVIEW: principal and auth dependencies

Reviewer: reviewer. Date: 2026-10-22. REQ-044, REQ-045, REQ-046, REQ-047 (failed checks and the per-user limit). Spec: TS §2.3 L118, TS §6 L1056, TS §6.2 L1080–L1091 and the route table, TS §6.3 L1136, TS §5.3 L1051. Decisions: #48, #53 (i), #55 (d); 2026-10-21 "Correction to M2 test-plan answers (3)" (every token is checked first; a valid token from a limited IP always passes). Plan: `work/plans/TASK-037.md`. Inputs: `work/reports/TASK-037-impl.md`, `work/reports/TASK-037-test.md` (PASS; TP-M2-15, G25).

Files reviewed: `manager/bitscan_manager/auth/principal.py`, `manager/bitscan_manager/auth/dependencies.py`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Per-router token prefixes (security invariant).** `resolve` calls `parse_user_token` first, so `bsa_`, `bse_`, unknown prefixes and malformed bodies fail before any lookup. The agent and enrolment tables are never read; the tester planted matching hashes there to prove it. A token whose row kind differs from its prefix fails (REQ-040 (4)).
- **Validity (REQ-044).** A token is refused when it is revoked, when `expires_at <= now` (this gives the 24 h session maximum, set at login), when it is a session idle for 8 h or more (from `last_used_at`, or `created_at` if never used), when its user is disabled, or when the role is unknown. The role and TOTP flags are read from `app_user` on every request (REQ-044 (5), REQ-045 (3)). An API principal is never `totp_verified`. Lookup is by the SHA-256 of the token on a unique index, so no constant-time comparison is needed.
- **Header parsing.** Exactly one `Authorization` header is accepted, with scheme `Bearer` in any case, one space and no space inside the token. Query strings and cookies are never read. The IP is the TCP peer, so no proxy header is read (#55 (d)).
- **Failed checks (REQ-047, lead's correction).** The token is always resolved first, so a valid token from a limited IP passes. On failure, `blocked` is read before the failure is recorded, so the 21st failure gets 429 with `Retry-After`, and failures answered 429 still count. Every 401 has one fixed body. An admin `bsk_` token without TOTP gets 403 `totp_enrolment_required`, is not counted, and is not touched (#53 (i)). The per-user limit applies only after authentication.
- **Gates (`_gate`).** In order:
  1. a restricted admin session gets 403 `totp_enrolment_required` unless the route allows it;
  2. `session` routes refuse `bsk_` with `session_required`;
  3. `totp_session` routes refuse any `bsk_` and any unverified session with `totp_session_required`;
  4. a role below the minimum gets `forbidden`;
  5. last, the sink gate gives 503 `audit_sink_unavailable`, and only on `totp_session` routes.

  This matches #48, REQ-046 (a) to (d) and the security invariants: API tokens are refused on TOTP-session routes, and the 15-minute refusal is applied. Each factory marks its callable for the route walk, and an unknown role fails when the route is defined.
- **Secrets.** Debug logs carry only `user_id` and `token_id`; the tester's caplog test confirms no token or hash appears.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 100 files, and `test_auth_dependencies.py` passes (26 tests; the pg cases ran in WSL).
- **Scope.** 2 files, about 190 lines.

## Findings

None block approval.

1. **note, accepted by the lead (the tester's point).** Token resolution runs in its own short transaction, before the route's own. A role change or disable committed between the two takes effect on the next request. The window is milliseconds and the role is still read on every request. The reason is FastAPI's split of sync yield-dependency threads, which I agree with.
2. **carry-over to TASK-038 and TASK-043.** The route walk (REQ-045 (2), REQ-046 (6)) has nothing to walk until user routes exist. The TASK-038 and TASK-043 TEST steps must re-run it against the real routes. I will check that each `/users` method carries `totp_session` and that only `POST /auth/login` has no marker.
3. **should be addressed in TASK-038 (the first real route).** If the database is down during resolution, `DatabaseUnavailable` leaves `current_principal` (`dependencies.py:61`) and becomes a generic 500. It is correctly not counted as a failed check, but the answer should be 503. Register a handler for `DatabaseUnavailable` that answers 503 (`about:blank`, fixed detail), so clients and monitors see "unavailable" rather than a server error.
4. **nit.** `dependencies.py:57`: a request with no `client` uses the shared key `"unknown"`, so all such requests share one failed-check bucket. That cannot happen under uvicorn over TCP, so it matters only for tests.
5. **nit.** The plan called for a failure-reason enum in the debug log. The log says only "token check failed", which is safer (no reason at all) but less useful for diagnosis. Either is acceptable.

## For the user (second approval)

The point to look at is finding 1: the role is read in a transaction separate from the route's own. The effect is at most one request served with a role a few milliseconds old. All the security invariants in this area hold: the user router accepts only `bsu_` and `bsk_`, an API token is refused for sensitive actions and token creation, and a sink outage refuses TOTP-session routes.
