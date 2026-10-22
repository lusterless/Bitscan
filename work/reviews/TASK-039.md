# TASK-039 REVIEW: TOTP enrolment and replacement

Reviewer: reviewer. Date: 2026-10-22. REQ-049, REQ-043. Spec: TS §6.2 L1085 ("Replacing TOTP also needs the current password and a current code"), L1087, L1088 (per-account back-off), L1089, L1096; TS §8.4 L1290. Decisions: #49 (b), #53 (b), #58, #50; 2026-10-22 carry-over (the gated password wrappers); 2026-10-22 "Rulings on TASK-039": (a) one alert entry per event, (b) 403 `forbidden` and 409 `conflict`, (c) **the user's decision: failed replacement attempts count**. Plan: `work/plans/TASK-038.md`, the TASK-039 part.

Inputs:
- `work/reports/TASK-039-impl.md`, including revision 1;
- `work/reports/TASK-039-test.md`: PASS in round 2 on revision 1, after a round 1 FAIL on ruling (c). Rows CHK-M2-190 to -199, -192a and -185-r039 in `tests/m2/report.md`; 20 of 20 mutations red;
- the CHK-M2-305-w7 run (Linux, alone): 1410 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/auth/totp_enrol.py`;
- `manager/bitscan_manager/api/user/auth.py` (the enrol route, the pending store, and logout dropping the pending seed);
- `manager/bitscan_manager/auth/principal.py` (`expires_at`);
- `manager/openapi.json`.

Verdict: APPROVED (round 2)

**This task needs a second approval from the user (TS §8.2, auth).**

## Round 1 finding (fixed in revision 1, as the user ruled)

1. **should-fix, fixed: replacement turned a stolen session into a password-guessing channel with no back-off.** In round 1, the replacement `start` checked the current password with no back-off and counted no failures. Someone holding a stolen session could therefore guess the password at the per-user limit of 600 a minute. The vault decrypt, which ran only after a correct password, also let the response time show which factor had failed.

   Revision 1 (`totp_enrol.py:104-123`) follows the sign-in rules:
   - **During back-off** (`now < next_login_at`), or when `current_password` or `current_code` is missing, one gated `dummy_verify` runs and the attempt is refused. Nothing is checked and nothing is counted (#55 (a)).
   - **A wrong password**, **a wrong code** or **a code already used** (`claim_totp_step` returns False) each go through `login._fail`. That is `record_failure` in its own committed transaction (back-off from 1 s doubling to 900 s), plus the `login_failures` alert at every 5 failures below the cap.
   - A vault outage while the old seed is decrypted is still 503 and is not counted (#58).

   With back-off in place, the timing difference is worth no more than a sign-in attempt: each guess costs a doubling back-off for the account. CHK-M2-192a checks that failures raise `failed_logins` and set `next_login_at`, that five failures raise one alert, and that during back-off a counting hasher sees exactly one verification, against the dummy hash only. The mutant "real password verified during back-off" is now red; it survived until the tester added that last assertion.

## Rulings (a) and (b), accepted as built

- (a) One `raise_alert` entry per event: `auth.totp_enrol` with kind `totp_enrolled`, or `auth.totp_replace` with kind `totp_replaced`, with no detail.
- (b) A wrong password or code on a replacement, and a wrong confirmation code, answer 403 `forbidden`; a confirm with nothing pending answers 409 `conflict`. A 401 would read as "token invalid" to the UI.

## What was checked

- **Session only.** `require_session(allow_restricted=True)`, so a `bsk_` token gets 403 `session_required` (REQ-049 (1); invariant: an API token can never enrol or replace TOTP). An admin who has no TOTP yet can enrol (TS §6.2 L1089).
- **Pending seed (#49 (b)).**
  - It is held in memory only, keyed by the session `token_id` and checked against the user, for 10 minutes.
  - `take` pops it, so two racing confirms get it at most once.
  - A wrong confirmation code discards it.
  - A vault failure at confirm puts it back, so the user can retry.
  - Logout drops it, and a restart loses it, as #49 (b) intends (the tester's point).
  - Nothing reaches the database before confirm (REQ-049 (4)).
- **Confirm, in one transaction (REQ-049 (2), (5), (6)).** `set_totp` with the vault ciphertext and the confirming step. Every session of the user is revoked (#53 (b)). The new session gets `totp_verified = true` and the old session's `expires_at`, so a re-issue never extends the 24 h maximum. The alert entry is written and the shipper woken on commit.
- **Single use.** The replacement's `current_code` step is consumed with `claim_totp_step`, so it cannot be replayed at sign-in.
- **Secrets (my TASK-029 and TASK-038 carry-overs).** The module never logs. The secret and the URI appear only in the start response. Every password check uses the gated `login.verify_password` and `login.dummy_verify`.
- **Body and OpenAPI.** `extra="forbid"`, and a body mixing `totp_code` with `current_*` gets 400. The route documents 200, 400, 401, 403, 409, 429 and 503, all errors as problem+json, with no 422.
- **Gates (my run, Windows).** ruff, format and `mypy --strict` are clean on 112 files. The enrolment, password, login and OpenAPI tests give 23 passed and 40 skipped (pg, run in WSL). The full suite has 1028 passed and 348 skipped, with G5 at 97.13 %.
- **Scope.** 4 files, about 210 lines after revision 1. Accepted.

## Findings (round 2)

None block approval.

1. **nit.** In `start`, missing `current_password` or `current_code` is refused without being counted, as the ruling says. Nothing is checked in that case, so it reveals nothing.
2. **note.** `login._fail` is a private name used across modules, here and in TASK-040. Renaming it `record_failed_sign_in` (public) would make the shared rule explicit. This is optional.

## For the user (second approval)

Finding 1 is fixed as you ruled: failed TOTP-replacement attempts now count toward the account's sign-in back-off and alert, exactly like failed sign-ins. Nothing else needs a decision.
