# TASK-040 IMPL report: change own password

REQ: REQ-050, REQ-041 (2). Spec: TS §6.2 L1086, L1087, L1097. Decisions:
- #53 (a): every session ends, the presenting one too;
- #50: action `auth.password_change`;
- "Rulings on TASK-039" (2026-10-22): the current-password check respects the back-off and counts failures, and every password check uses the gated wrappers.

Plan: none; REQ-050 and TASK-038's flow.

## Files (3)

- `manager/bitscan_manager/auth/password_change.py`: new, 41 non-blank lines.
- `manager/bitscan_manager/api/user/auth.py`: adds the `POST /api/v1/auth/password` route and the `PasswordChangeRequest` model.
- `manager/openapi.json`: regenerated.

## Route `POST /api/v1/auth/password`

- **Who may call it.** `require_session()`, so any signed-in user with a web session:
  - a `bsk_` token gets 403 `session_required`;
  - a restricted admin session gets 403 `totp_enrolment_required` (CHK-M2-205), because it is not `allow_restricted`.
- **Body.** `{current_password, new_password}` with `extra="forbid"`. `current_password` is 1–1024 characters. `new_password` is checked by the service, so the 400 names the rule.
- **Answers:**
  - **204** on success. All of the caller's sessions, this one included, are ended, so the client must sign in again (#53 (a)). There is no body, because #47 gives none.
  - **400** `invalid_request` with the rule: `password must be at least 12 characters`, `… at most 1024 characters` or `password must be valid Unicode text`. This is checked **before** the current password, so a bad new password neither verifies nor counts anything.
  - **403** `forbidden`, "The current password is not valid.", for a wrong current password or during back-off. CHK-M2-201 allows 401 or 403; 403 matches TASK-039, because the caller's token is valid.
  - The TASK-037 401 and 429, and 503 when the database is down.

## `auth/password_change.py` — `change_password(runtime, principal, *, current_password, new_password)`

1. `passwords.check_new_password(new_password)` raises `PasswordRejected` with the rule only.
2. The user row is read.
3. **During back-off** (`now < next_login_at`): one gated `login.dummy_verify`, then refuse. Nothing is checked or counted.
4. **Wrong current password**, checked with the gated `login.verify_password`: `login._fail(...)` counts it in its own committed transaction (back-off and the `login_failures` alert at every 5), then refuse.
5. The new hash is computed under `login.VERIFY_GATE`. Hashing uses the same 64 MiB as a verification, so it shares the 4-slot memory bound.
6. One transaction does three things:
   - `set_password_hash`;
   - `revoke_for_user(user_id, {"session"})`, which ends every session, the presenting one included. API tokens are not touched (REQ-050 (4));
   - one `auth.password_change` entry, with actor and target `user:<id>` and **no detail**, so no password or hash is written.

   The shipper is woken on commit.

`failed_logins` is not reset on success, because the spec gives no rule. The next successful sign-in resets it as usual.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 111 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1028 passed, 332 skipped (pg), 97.13 %, no failures |
| OpenAPI re-export | `/api/v1/auth/password`: 204, 400, 401, 403, 429, 503, all problem+json; no 422 |
| Scratch with fakes (deleted) | (1) |

(1) Scratch results:
- An 11-character new password was rejected with the rule, before any check.
- A wrong current password counted one failure.
- During back-off, one dummy check ran and nothing was counted, even with the right password.
- Success:
  - the new hash verifies;
  - sessions only were revoked;
  - one `auth.password_change` entry was written, with no detail.

## For the tester (TP-M2-18)

- CHK-M2-201: the refusal is 403 `forbidden`. Hash and sessions are unchanged, and `failed_logins` goes up by one; that last part is new under the 2026-10-22 ruling.
- CHK-M2-203: after 204, the presenting token gets 401 too.

## Lead rulings (decisions.md 2026-10-22, "Lead rulings on TASK-040")

Accepted:
- **204 with no body** on success, since every session, the caller's included, is ended.
- **403 `forbidden`** for a wrong current password or an attempt during back-off, counted as a failed sign-in.
- **Hashing the new password** under the 4-slot gate.
