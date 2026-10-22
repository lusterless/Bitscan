# TASK-038 REVIEW: sign-in and sign-out, the first `/api/v1` user routes

Reviewer: reviewer. Date: 2026-10-22. REQ-048, REQ-042, REQ-047, REQ-035 (5). Spec: TS §6.2 L1080, L1086–L1089, TS §6.3 L1136, TS §2.3 L122.

Decisions and carry-overs:
- #47 (a), #48, #49 (c), #50, #54 (a), #55 (a) to (e), #58 (b);
- 2026-10-21: the sign-in memory bound (4 slots, fair), the OpenAPI error contract, `DatabaseUnavailable` mapped to 503;
- 2026-10-22, "Lead rulings on TASK-038": one task; the `auth.login_failures` alert carries only the count.

Plan: `work/plans/TASK-038.md`.

Inputs:
- `work/reports/TASK-038-impl.md`, including revision 1 (every error response documented as problem+json);
- `work/reports/TASK-038-test.md`: PASS on revision 1, rows CHK-M2-170 to -187 and -045-r038;
- the CHK-M2-305-w5 run (Linux, alone): 1367 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/auth/login.py`;
- `manager/bitscan_manager/api/user/__init__.py`, `manager/bitscan_manager/api/user/auth.py`;
- in `manager/bitscan_manager/app.py`: the user router, the two 503 handlers and `_problem_openapi`;
- `manager/openapi.json`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Identical failures (REQ-048 (1), TS §6.2 L1086).** Every failure raises `LoginFailed`, which the route answers with the same 401 body that TASK-037 uses. That covers an unknown or disabled user, back-off, a wrong password, a missing, wrong or reused code, and a lost single-use race. Validation errors (400) happen before any user lookup, so they reveal nothing about accounts.
- **Equal cost (REQ-048 (2)).** The unknown, disabled and back-off paths each run one `dummy_verify`. Every verification, real or dummy, goes through `VERIFY_GATE` (`login.py:37-77`): 4 slots, with a ticket and condition variable so waiters are served in arrival order and never refused. That is the memory bound the lead set (4 × 64 MiB). TASK-039 and TASK-040 must use these wrappers too.
- **Back-off (REQ-048 (3), (4); #55 (a)).** During back-off the password is not checked and nothing is counted. A failed password or code is counted by `_fail`, in its own committed transaction (the tester's review point), so the count stands even though the request ends in a 401. The counter's limits come from TASK-031 (1 s doubling to 900 s, capped at 1000). Success resets the counter in the same transaction as the session insert.
- **TOTP (REQ-042, #49 (c)).** Every enrolled user must give a code. The seed is decrypted through the vault. `claim_totp_step` sits in the same transaction as the session insert and the audit entry, so a reused code or a lost concurrent race writes nothing and counts as a failure. The tester checked the race on PostgreSQL.
- **Vault down (#58 (b)).** `VaultUnavailable` propagates and becomes 503 `about:blank`, `The vault is unavailable.`. It is not counted and there is no fallback. It surfaces only after a correct password, so it tells only someone who knows the password that the account has TOTP. Accepted under #58.
- **Sessions (REQ-048 (5)).** `kind = session` and `expires_at = created_at + 24 h`, both from one `now`. `totp_verified` is true only when a code was verified. An admin without TOTP gets the restricted session through TASK-037. The token is returned once and stored only as its SHA-256.
- **Logout (REQ-048 (6)).** `require_session(allow_restricted=True)`, so a `bsk_` token gets 403 and is not revoked. Only the presenting session is revoked. It writes `auth.logout`.
- **Rate limit.** `login_limit` counts every attempt per TCP peer before the body is processed and answers 429 with `Retry-After` (#55 (c), (e)).
- **Audit and alerts (#50, #54 (a), lead ruling).** `auth.login` carries `{"totp_verified"}`. The `login_failures` alert fires at 5 and at every further 5, stops at the 1000 cap, and carries only `{"failed_logins": n}`, with no username, password or address. Each commit wakes the shipper.
- **`DatabaseUnavailable` mapped to 503 (my TASK-037 carry-over).** Done in `app.py`. A database outage during token resolution therefore answers 503 and is never counted as a failed check (CHK-M2-187).
- **OpenAPI error contract (decisions 2026-10-21).** The exported document has no 422 and no `HTTPValidationError` or `ValidationError` schemas. There is a strict `Problem` schema, a problem+json 400 on every operation that takes input, and every response of 400 or above is documented as problem+json. Login has 200, 400, 401, 429 and 503; logout has 204, 401, 403, 429 and 503. Every user path starts with `/api/v1/` (REQ-035 (5)).
- **Route walk (my TASK-037 carry-over).** `test_route_walk_every_user_route_declares_a_requirement` now walks the real app. Only `POST /api/v1/auth/login` has no marker, and the planted counter-test is red.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 108 files. The full suite has 1028 passed and 308 skipped (pg, run in WSL), with G5 at 97.13 %. `test_login.py`, `test_openapi.py` and `test_cli.py` pass.

## Findings

None block approval.

1. **scope, accepted.** About 290 hand-written lines over 5 files, well above the ~200 guide. Following the lead's ruling, I do not ask for a split. The growth comes from three carry-overs added after planning (the fair semaphore, the OpenAPI post-processor, the 503 handlers), and logout is only about 25 lines. Each piece is small and separately tested.
2. **nit.** `login.py:115-116` reads the user with no row lock, and the back-off check uses that snapshot. Two parallel wrong-password attempts both pass the back-off check and both get counted. That costs at most one extra Argon2id run per parallel request, with the per-IP limit (10/min) and the semaphore on top. `record_failure` stays atomic, so the counter is right. Acceptable.
3. **nit.** The `login_limit` key falls back to `"unknown"` when there is no client address; this is the same note as for TASK-037, and it matters only in tests.
4. **note for TASK-039 and TASK-040.** Use `login.verify_password` and `login.dummy_verify` (the gated wrappers), never `passwords.*` directly. Otherwise the memory bound has a gap. The TASK-039 and TASK-040 reviews will check this.

## For the user (second approval)

Three behaviours to be aware of. All follow the decisions you approved:
- A user with TOTP who enters the correct password while the vault is down gets 503, not 401 (#58 (b)).
- A sign-in failure is counted even though the request ends in a 401, because it is written in its own transaction.
- Under load, at most four password checks run at once; others wait their turn.

Nothing needs a new decision.
