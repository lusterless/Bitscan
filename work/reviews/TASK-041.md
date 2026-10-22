# TASK-041 REVIEW: API tokens (create, list, revoke)

Reviewer: reviewer. Date: 2026-10-22. REQ-051, REQ-040 (3), (5), REQ-046 (2), (e). Spec: TS §6.2 L1081 (created only from a web session, TOTP-verified for admins; default 90 days, maximum 365; shown once), L1083, L1085 (an API token can never create API tokens), L1098–L1099; TS §8.4 L1290 (API token created alerts). Decisions:
- #8: an API token may revoke its own user's API tokens;
- #47 shapes, #48 statuses, #50 actions, #52 integer ids, #53 (i);
- lead ruling 2026-10-22: 201 Created; the token is shown once.

Plan: `work/plans/TASK-041.md`. Inputs:
- `work/reports/TASK-041-impl.md`;
- `work/reports/TASK-041-test.md`: PASS, rows CHK-M2-210 to -219 and -021-r041 in `tests/m2/report.md`, 12 of 12 mutations red;
- the CHK-M2-305-w8 run (Linux, alone): 1441 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/auth/api_tokens.py`;
- `manager/bitscan_manager/api/user/api_tokens.py`;
- `manager/bitscan_manager/api/user/__init__.py`;
- `manager/openapi.json`.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **No token creation with tokens (security invariant, REQ-046 (2)).** `POST /api-tokens` uses `require_session`, so a `bsk_` token gets 403 `session_required`.
- **Admins need a TOTP session (REQ-046 (e), TS §6.2 L1081).** An admin whose session is not TOTP-verified, a restricted admin included, gets 403 `totp_session_required`.
- **Not sensitive.** Creation has no sink gate, so it still works during a sink outage (REQ-054 (4)).
- **Format and storage (REQ-040 (3), (5); REQ-051 (2), (7)).** The token comes from `new_token(API)`, and only its SHA-256 is stored. It is returned once, in the 201 body, and never again: list items have exactly `{token_id, name, created_at, expires_at, last_used_at, revoked_at}`, with no hash. The row has `kind = 'api'` and `totp_verified = false`, which the database CHECK also enforces.
- **Lifetime (REQ-051 (1)).** The default is 90 days and the range 1–365. The route uses `StrictInt`, so `1.5`, `"30"`, `true`, 0, 366 and −1 all get 400. The service re-checks the range and refuses bools, so the CLI (TASK-046) gets the same rule. The name is at most 64 characters.
- **Alert (REQ-051 (5), TS §8.4).** Each creation writes exactly one `api_token_created` entry, `api_token.create`, in the same transaction, and the counter rises on commit. Its detail is `{token_id, name, expires_at}`. On the tester's point: `name` is chosen by the user and `expires_at` is derived; neither is a secret, and the token and its hash are never in it.
- **Ownership (REQ-051 (3), (4), (6)).**
  - `GET` lists only the caller's API tokens, with the TASK-026 cursor (its own scope, integer key).
  - `DELETE /{token_id}` revokes only the caller's own live API token. The same 404 answers an unknown id, another user's token, a session id and a token already revoked, so ids cannot be probed.
  - A `bsk_` may revoke its own user's tokens, itself included (#8); its next request then gets 401.
  - A revoke writes `api_token.revoke`.
- **OpenAPI.** It has 201, 200 and 204, plus problem+json errors, with no 422. The export is ASCII here. The tester's earlier `test_openapi.py` failure was a test defect (it compared with ASCII escaping while the export writes UTF-8), now fixed, with an ASCII-escaping mutant red.
- **Gates (my run, Windows).** ruff, format and `mypy --strict` are clean on 115 files. `test_api_tokens.py` and `test_openapi.py` pass; the pg cases ran in WSL. The full suite has 1029 passed and 378 skipped, with G5 at 97.13 %.
- **Scope.** 4 files, about 190 lines.

## Findings

None block approval.

1. **should be followed up in TASK-043 or the M2 gate: the route walk misses the admin rule on `POST /api-tokens`.** This is the tester's point. The admin TOTP-session check is written in the route body (`api_tokens.py:58-61`), not in a dependency factory. The route walk therefore records it as `session` with a viewer minimum, and REQ-046 (6) cannot see the extra rule. The behaviour is correct and tested (CHK-M2-216). But a later edit that drops those four lines would not show up in the walk. Fix later: move the check into a small dependency, for example `require_session(..., admin_totp=True)`, whose marker records it. Or make TP-M2-25 assert the refusal itself, which it already does through CHK-M2-216. Not blocking.
2. **nit.** `api_tokens.py:87-88`: a cursor holding a non-integer key gets 400. `decode_cursor` only ever returns keys this process signed, so this branch cannot run in practice; it is defensive.
3. **nit.** The service's `ApiTokenInvalid` cannot be reached from the route, because Pydantic validates first. It exists for the CLI. That is fine.

## For the user (second approval)

1. **201 Created.** `POST /api/v1/api-tokens` answers 201, not 200. #47 named no status, and the lead ruled 201 on 2026-10-22. Sign-in still answers 200.
2. **An admin's API tokens after a TOTP reset.** Under #53 (i) as approved, the admin's existing API tokens are refused with 403 `totp_enrolment_required` from the moment TOTP is reset until it is re-enrolled. They are not revoked, so they work again once the admin re-enrols TOTP. If you would rather have them revoked at the reset, that is a change to TASK-042's `reset_totp`, not to this task.
3. **An API token can revoke tokens.** A token can revoke its own user's API tokens, itself included (#8). It still cannot create one.

Nothing else needs a decision.
