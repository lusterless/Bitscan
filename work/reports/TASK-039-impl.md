# TASK-039 IMPL report: TOTP enrolment and replacement

REQ: REQ-049, REQ-043. Spec: TS §6.2 L1085, L1087, L1089, L1096; TS §8.4 L1290. Decisions:
- #49 (b): two calls; the pending seed is held in memory only, bound to the session, for 10 minutes;
- #53 (b): replacing ends the user's other sessions;
- #58: vault down answers 503;
- #50: actions and kinds;
- lead carry-overs: no seed, secret or URI in logs; the gated password wrappers; `UtcDatetime`; problem+json.

Plan: `work/plans/TASK-038.md`, TASK-039 part. **Two approvals (TS §8.2, auth).**

## Files (4)

- `manager/bitscan_manager/auth/totp_enrol.py`: new, 143 non-blank lines.
- `manager/bitscan_manager/api/user/auth.py`: adds the `POST /api/v1/auth/totp/enrol` route, the `EnrolRequest`/`EnrolStartResponse` models and the per-app `_pending(request)` store. Logout now also drops the session's pending seed (#49 (b)).
- `manager/bitscan_manager/auth/principal.py`: `Principal` gains `expires_at`, the token's own expiry, set by `resolve()`. The re-issued session needs the old session's expiry, and only the principal carries the token. This is the 4th file and a one-field change.
- `manager/openapi.json`: regenerated.

## Route `POST /api/v1/auth/totp/enrol`

The route uses `require_session(allow_restricted=True)`. So a `bsk_` token gets 403 `session_required`, and a restricted admin may enrol. The body is `extra="forbid"`; the call is chosen by which fields are present:

| Body | Call | Answer |
| --- | --- | --- |
| `{}` (no TOTP yet) or `{current_password, current_code}` (replacement) | `start` | 200 `{secret, otpauth_uri}` |
| `{totp_code}` | `confirm` | 200 `{token, expires_at, role, totp_enrolled: true, totp_verified: true}` (the TASK-038 `LoginResponse`, `expires_at` as `UtcDatetime`) |
| `totp_code` together with `current_*` | none | 400 `invalid_request` |

Refusals:
- 403 `forbidden`, "The password or code is not valid.";
- 409 `conflict`, "No TOTP enrolment is in progress.";
- 503 `about:blank` for a vault outage;
- plus the TASK-037 401, 403 and 429 answers.

All are documented as problem+json.

## `auth/totp_enrol.py`

**`PendingEnrolments`** holds the pending seeds in a lock-protected dict, keyed by session `token_id`. Each entry holds the user id, the seed and the expiry (`now + 10 min`). The store lives on `app.state`, one per app.
- `put` also discards expired entries.
- `take` pops the entry, so two racing confirms get it at most once. It returns `None` when the entry is absent, expired or belongs to another user.
- `restore` puts a taken seed back after a vault failure.
- `drop` is called on logout.

**`start`** reads the user. If the user already has a seed, this is a replacement and it needs both `current_password` and `current_code`:
- **Password.** It is checked with the **gated** `login.verify_password`. If the code is missing but a password was sent, `login.dummy_verify` runs instead.
- **Code.** The code is decrypted and checked with `match_step`. `VaultUnavailable` propagates and the app answers 503. The step is then consumed with `claim_totp_step` in its own transaction, so the same code cannot be replayed at sign-in.

Any failure raises `EnrolRefused`, and the stored seed is unchanged. If the checks pass, a new seed goes into the pending store and is returned base32-encoded with the `otpauth://` URI. **Nothing is written to the database for the new seed.**

**`confirm`**:
1. `take`. A missing pending seed raises `NoPendingEnrolment` (409).
2. `match_step`. A wrong code raises `EnrolRefused`, and the pending seed is discarded, so a later right code for it is refused (CHK-M2-193).
3. `totp_cipher.encrypt(seed)`. On `VaultUnavailable` the pending seed is restored and the error goes on to the 503 handler, so the user can retry before it expires.
4. One transaction:
   - `get_for_update` on the user, and `set_totp(ciphertext, last_step=step)`;
   - revoke **every** session of the user, the presenting one included, because a replacement ends the other sessions (#53 (b));
   - insert the new session with `totp_verified = true` and **the old session's `expires_at`**, so the 24 h maximum is kept;
   - one alert entry: `totp_enrolled` with action `auth.totp_enrol`, or `totp_replaced` with action `auth.totp_replace`, actor and target `user:<id>`, and no detail, so no seed or code is in it;
   - wake the shipper on commit.

The module never logs.

**Choices for the lead to confirm:**
- **(a) One entry per event.** Following the TASK-042 ruling, there is one alert entry that carries the `auth.totp_*` action, rather than an alert plus a separate audit entry. CHK-M2-194 says "plus … audit".
- **(b) Refusal statuses.** A wrong password or code in a replacement, and a wrong confirmation code, answer 403 `forbidden`. A 401 would read as "token invalid" to the UI. #48 gives no value for this case.
- **(c) Failures not counted.** A failed replacement attempt is not counted in `failed_logins`. The spec gives no rule, and the caller already holds a valid session that the per-user 600 requests per minute limit covers.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 109 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1027 passed, 308 skipped (pg), 97.13 %; 1 failure in a tester test (below) |
| OpenAPI re-export | `/api/v1/auth/totp/enrol` with 200 (`anyOf` the two response models), 400, 401, 403, 409, 429, 503; no 422 |
| Scratch with in-memory fakes and the JSON log handler (deleted) | (1) |

(1) Scratch results:
- A restricted admin's start returned `{otpauth_uri, secret}`.
- A wrong confirmation code got 403, and the same seed's right code then got 409 (discarded).
- A new start followed by confirm with the vault down got 503. A retry with the vault up returned the verified token with the old session's `expires_at`, and one `totp_enrolled` alert.
- The old token then got 401.
- These replacements were all refused: no fields, password only, wrong password, and a code that was already used.
- A valid replacement start got 200. After 11 minutes its confirmation got 409.
- A mixed body got 400.
- The secret and the URI did not appear in any log line.

**Failing tester test.** `tests/test_login.py::test_documented_400_matches_what_the_app_returns` sends a bad body **without a token** to every operation with a body, and expects 400. For the authenticated enrol route the app answers 401 first, because the auth dependency runs before the body error is reported. I think authenticating first is correct. The test should send a valid session for routes that need one, or accept 401 there.

## For the tester (TP-M2-17)

- The pending store is `app.state.totp_pending`. CHK-M2-197 can show that another session of the same user cannot confirm, because the store is keyed by `token_id` and `take` checks the user.
- The old token and every other session of the user are revoked at confirm.
- The new `expires_at` equals the old session's.

## Revision 1 (review finding 1; the user's ruling, decisions.md 2026-10-22 "Rulings on TASK-039")

The user decided choice (c) the other way, in line with the reviewer's finding 1: **replacement failures are counted.** Choices (a) and (b) are accepted as built.

**Cause.** The replacement `start` checked the current password with no back-off and no failure count. A stolen session could guess the password at 600 a minute, and the vault decrypt that ran only after a correct password let timing show which factor had failed.

**Fix** (`auth/totp_enrol.py`, `start`, replacement branch), the same rules as sign-in:
- **During back-off** (`now < next_login_at`), or with `current_password` or `current_code` missing: one gated `login.dummy_verify` runs, then the attempt is refused (403). Nothing else is checked and nothing is counted.
- **Wrong password:** `login._fail(runtime, user_id, now)`, then 403. That is `record_failure` in its own committed transaction: back-off from 1 s doubling to 900 s, and the `login_failures` alert at every 5 failures below the cap (TASK-038).
- **Wrong code, or a code already used** (`claim_totp_step` returns `False`): `login._fail(...)`, then 403.
- A vault outage while the seed is decrypted is still 503 and is not counted (#58).

The answer stays 403 `forbidden`. Every password check goes through the gated wrappers `login.verify_password` and `login.dummy_verify`.

Re-checked:
- ruff and mypy `--strict` are clean (110 files).
- `pytest tests/test_totp_enrol.py tests/test_login.py`: 18 passed, 21 skipped (pg).
- Scratch with fakes (deleted):
  - a wrong password, a wrong code and a reused code each counted one failure;
  - missing fields ran one dummy check and counted nothing;
  - during back-off one dummy check ran, nothing was counted, and the right password was refused;
  - after the back-off the replacement started.
