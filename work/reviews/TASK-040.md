# TASK-040 REVIEW: change own password

Reviewer: reviewer. Date: 2026-10-22. REQ-050, REQ-041 (2). Spec: TS §6.2 L1086 (a password change ends the user's sessions), L1087 (Argon2id, at least 12 characters), L1088 (back-off), L1097 (`POST /auth/password`, current password required, session only). Decisions:
- #53 (a), #50, #56 (b);
- 2026-10-22 "Rulings on TASK-039" (c): the same counting rule applies to the current-password check;
- 2026-10-22 "Lead rulings on TASK-040": 204 with no body; 403 `forbidden` for a wrong current password or during back-off; new-password hashing under the 4-slot gate.

Inputs:
- `work/reports/TASK-040-impl.md`;
- `work/reports/TASK-040-test.md`: PASS, rows CHK-M2-200 to -205 in `tests/m2/report.md`, 11 of 11 mutations red, including the old "not counted" behaviour and new-password hashing outside the gate;
- the CHK-M2-305-w7 run (Linux, alone): 1410 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/auth/password_change.py`;
- `manager/bitscan_manager/api/user/auth.py` (`POST /api/v1/auth/password` and `PasswordChangeRequest`);
- `manager/openapi.json`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **Session only (REQ-050 (1)).** `require_session()`: a `bsk_` token gets 403 `session_required`, which keeps the invariant that an API token cannot change credentials. An admin session restricted for want of TOTP gets 403 `totp_enrolment_required`, because the route is not `allow_restricted` (TS §6.2 L1089 allows only enrol and logout).
- **New-password rules first (REQ-050 (3), REQ-041 (2)).** `check_new_password` runs before anything is verified: 12 to 1,024 code points and valid Unicode. So a bad new password gets 400 with the rule only, verifies nothing and counts nothing.
- **Current password, the TASK-039 ruling (REQ-050 (2)).** During back-off, one gated `dummy_verify` runs and the request is refused, even with the right password. A wrong current password goes through `login._fail`: back-off and the `login_failures` alert, in its own committed transaction. Either way the answer is 403 `forbidden` and nothing changes. So a stolen session cannot use this route to guess the password faster than sign-in allows. The tester asserts that during back-off only the dummy hash is verified; the "real password verified during back-off" mutant is red.
- **Memory bound.** Verification goes through the gated wrappers, and the new hash is computed under `login.VERIFY_GATE` (CHK-M2-205), so all Argon2id work shares the 4 slots.
- **Success (REQ-050 (4), (5); #53 (a)).** One transaction holds three things:
  - `set_password_hash`;
  - `revoke_for_user(user_id, {"session"})`, which ends every session, the presenting one included;
  - one `auth.password_change` entry with no detail, so no password or hash is ever audited.

  API tokens keep working, as REQ-050 (4) requires. The answer is 204 with no body (lead ruling). The shipper is woken on commit.
- **OpenAPI.** The route documents 204, 400, 401, 403, 429 and 503, all errors as problem+json, with no 422.
- **Gates (my run, Windows).** ruff, format and `mypy --strict` are clean on 112 files. The task tests pass, and the pg cases ran in WSL. The full suite has 1028 passed and 348 skipped, with G5 at 97.13 %.
- **Scope.** 3 files, about 70 lines. Small.

## Findings

None block approval.

1. **nit.** After a successful change, a TOTP enrolment that the presenting session had started is still in the in-memory pending store until it expires. The session is revoked, so it can never be confirmed, and it is dropped within 10 minutes. Calling `pending.drop(token_id)` would tidy it up, but nothing depends on it.
2. **note.** `failed_logins` is not reset after a successful change, because the spec gives no rule. The next successful sign-in resets it, as for a successful TOTP replacement.
3. **note.** A user with TOTP changes their password without giving a code. TS §6.2 L1097 asks only for the current password, and the caller already holds a session. That session is TOTP-verified for anyone who has TOTP, because sign-in requires the code (#49 (c)). This matches the spec.

## For the user (second approval)

Two behaviours, both as approved:
- a successful password change signs the user out everywhere, the current session included, while their API tokens keep working;
- a wrong current password counts toward the sign-in back-off.

Nothing needs a decision.
