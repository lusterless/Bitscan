# TASK-043 REVIEW: `/users` routes

Reviewer: reviewer. Date: 2026-10-22. REQ-052, REQ-046 (1), (3), (5), (6), REQ-054 (3), (4). Spec: TS §6.2 L1084 (managing users is a sensitive action), L1085–L1091, L1125 (CRUD `/users`, delete means disable, admin, TOTP session); TS §5.3 L1050, L1051. Decisions: #47 (c), #48, #52, #53 (f), (g), (h); 2026-10-22 "Lead rulings on TASK-043" (exactly one change per PATCH, 201 on create, disable only through DELETE); the TASK-041 follow-up assigned here.

Inputs:
- `work/reports/TASK-043-impl.md`, including revision 1;
- `work/reports/TASK-043-test.md`: PASS, plus a "Revision 1" re-test PASS; rows CHK-M2-230 to -236, -045-r043, -216-r043 and -230-r1;
- CHK-M2-305-w9r1 (Linux, alone): 1511 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/api/user/users.py`;
- `manager/bitscan_manager/api/user/__init__.py`;
- `manager/bitscan_manager/auth/dependencies.py` (`admin_totp`);
- `manager/bitscan_manager/api/user/api_tokens.py`;
- `manager/openapi.json`.

Verdict: APPROVED (round 2)

**This task needs a second approval from the user (TS §8.2, auth).**

## Round 1 finding (fixed in revision 1)

1. **should-fix, fixed: an explicit `null` in a `PATCH` body ran the action.**
   - **The defect.** The dispatch used `body.model_fields_set`, which also contains fields sent as `null`. So `{"revoke_tokens": null}` revoked every token of the user, `{"disabled": null}` re-enabled a disabled user, and `{"role": null}` reached the service as `"None"`. That broke #47 (c) and the lead's ruling (a).
   - **The fix.** After the exactly-one-field check, the field must carry its documented value: `role` one of the three roles (a `Literal`, so not-None is enough), `disabled is False`, `revoke_tokens is True`, or `totp` present. `null` is the documented value only for `totp`. Anything else gets 400 `invalid_request` naming the field, before any transaction, so nothing changes and nothing is audited.
   - **Tests.** `test_patch_null_is_refused_unless_it_is_the_documented_value` covers each null body against enabled and disabled targets that hold TOTP, a session and an API token: each gets 400 with rows, revocations and the audit count unchanged. `{totp: null}` still resets and `{disabled: false}` still re-enables with `user.enable`. The planted old "presence counts" behaviour is red. `null-role-accepted` is equivalent, because the service refuses `"None"` with the same 400.

## What was checked

- **TOTP-session route (REQ-046 (1), (3), (5), (6); security invariants).** Every `/users` method uses `require_totp_session()`, so it needs an admin `bsu_` session with `totp_verified`.
  - An admin `bsk_` gets 403 `totp_session_required`, even while the same admin holds a verified session.
  - A restricted admin gets `totp_enrolment_required`, and operators and viewers get `forbidden`.
  - After 15 minutes of sink outage the answer is 503 `audit_sink_unavailable`, checked last, so nothing runs (REQ-054 (3)).
  - The route walk finds `totp_session`, admin and `sink_gate=True` on every `/users` route.
- **My TASK-041 follow-up.** `POST /api-tokens` now uses `require_session(admin_totp=True)`, and the route walk sees `admin_totp=True` (CHK-M2-216-r043). The check in the route body is gone and behaviour is unchanged.
- **Responses (REQ-052 (9)).** `UserItem` lists exactly `{user_id, username, role, disabled, totp_enrolled, created_at}`, built field by field, so no hash or seed can be serialised.
- **One transaction per request (REQ-052 (8)).** It holds the change, its single audit or alert entry (counter after commit) and the token revocations. A rule failure rolls back before the problem is raised. `POST` hashes under `VERIFY_GATE`.
- **Error mapping.** `Rule` maps to 404, 409 or 400 with fixed detail text. `PasswordRejected` names the rule only. The ruled answers hold: 201 on create; `{disabled: true}` gets 400; zero or several fields get 400.
- **Create (#53 (f)).** `role` is `viewer` or `operator` only, and the service refuses `admin` as well.
- **OpenAPI.** Every refusal is documented as problem+json; there is no 422.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 120 files. The users, auth, API-token and OpenAPI tests pass on Windows, and the pg cases ran in WSL.
- **Scope.** 5 files, about 210 lines after revision 1. Accepted.

## Findings (round 2)

None block approval.

## For the user (second approval)

The round 1 defect is fixed: a `PATCH` body that sends `null` for `revoke_tokens`, `disabled` or `role` is now refused with 400 and changes nothing. Everything else follows your earlier decisions:
- one change per PATCH;
- 201 on create;
- disable only through DELETE;
- API tokens refused on every `/users` method;
- refusal during a sink outage.

Nothing needs a decision.
