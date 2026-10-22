# TASK-043 IMPL report: `/users` routes

REQ: REQ-052, REQ-046 (1), (3), (5), (6), REQ-054 (3), (4). Spec: TS §6.2 L1085–L1091, L1125; TS §5.3 L1050, L1051. Decisions:
- #47 (c): the routes and the PATCH sub-actions;
- #48: statuses;
- #52: integer ids;
- #53 (f), (g), (h);
- TASK-042 rulings: one alert entry per event, and a raise of a role writes `role_granted`;
- lead carry-over from the TASK-041 review: the admin TOTP-session check for `POST /api-tokens` becomes a dependency marker.

The routes run over the TASK-042 service. **Two approvals (TS §8.2, auth).**

## Files (5)

- `manager/bitscan_manager/api/user/users.py`: new, 178 non-blank lines.
- `manager/bitscan_manager/api/user/__init__.py`: also mounts the `users` router.
- `manager/bitscan_manager/auth/dependencies.py`: `AuthMarker` gains `admin_totp: bool = False`, and `require_session(..., admin_totp=False)` gains the same flag. When it is set, the marker implies `allow_restricted`, and `_gate` refuses an admin whose session is not TOTP-verified with 403 `totp_session_required`. That check runs after the session-kind check and before the role check.
- `manager/bitscan_manager/api/user/api_tokens.py`: **carry-over.** `POST /api-tokens` now uses `require_session(admin_totp=True)`, and its in-route check is gone, so the route walk sees the rule through `.bitscan_auth.admin_totp`. Behaviour is unchanged:
  - a `bsk_` token still gets `session_required`;
  - a restricted or unverified admin still gets `totp_session_required`;
  - viewers, operators and verified admins are still accepted.
- `manager/openapi.json`: regenerated.

## Routes (`/api/v1/users`)

**Every method** uses `require_totp_session()`. That means an admin with a `bsu_` session that has `totp_verified = true`, checked with the sink gate last. A `bsk_` token gets 403 `totp_session_required`, even while the same admin holds a verified session. A restricted admin gets 403 `totp_enrolment_required`. Operators and viewers get 403 `forbidden`. After 15 minutes of sink outage the answer is 503 `audit_sink_unavailable`. Nothing changes in any of these cases.

| Route | Body | Service call | Answer |
| --- | --- | --- | --- |
| `GET /api/v1/users` | `?limit`, `?cursor` (scope `users`, key `user_id`) | `list_users` | 200 `{items, next_cursor}` |
| `POST /api/v1/users` | `{username, password, role?}`; `role` is `viewer` (default) or `operator` only (#53 (f): an admin comes from promotion or the CLI); `extra="forbid"` | `create_user`, then `get_user` | **201** user item |
| `GET /api/v1/users/{user_id}` | none | `get_user` | 200 user item |
| `PATCH /api/v1/users/{user_id}` | **exactly one** of `{role: viewer\|operator\|admin}`, `{disabled: false}`, `{totp: null}`, `{revoke_tokens: true}` | `change_role`, `enable_user`, `reset_totp` (`actor_id` = the caller), `revoke_user_tokens` | 200 user item after the change |
| `DELETE /api/v1/users/{user_id}` | none | `disable_user` (delete means disable) | 204 |

- **User item:** exactly `{user_id, username, role, disabled, totp_enrolled, created_at}` (#47 (c)), with `created_at` as a `UtcDatetime`. There is never a hash or seed.
- **One transaction per request.** It holds the change, its single audit or alert entry and the token revocations, through `TxAudit(PgAuditRepo(tx.conn), tx.on_commit)`, so the counter goes up after commit. A `UserRuleError` or `PasswordRejected` rolls the transaction back. The sink shipper is woken on commit.
- **`POST`** runs under `login.VERIFY_GATE`, because creating a user hashes the password with Argon2id (the sign-in memory bound).
- **Error mapping:**
  - `not_found` → 404 `not_found`;
  - `duplicate`, `last_admin`, `needs_totp` and `self_reset` → 409 `conflict`, each with a detail naming the rule;
  - `invalid_username`, `invalid_role`, `PasswordRejected` and any validation error → 400 `invalid_request`. That includes `{disabled: true}` (use `DELETE`), a `PATCH` with zero or more than one field, and an unknown field.
- Each route documents only the refusals it can give, as problem+json (401, 403, 429, 503, plus 404 and 409 where they apply). There is no 422 anywhere.

**Choices for the lead to confirm:**
- **(a)** `PATCH` takes exactly one change per request. #47 says "any of", which I read as one of them; combining them would make one request write several audit entries with unclear order.
- **(b)** `POST` answers 201, as `POST /api-tokens` does.
- **(c)** `{disabled: true}` is refused with 400, because disabling is `DELETE` (TS §6.2 L1125).

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 116 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1029 passed, 378 skipped (pg), 97.13 %, no failures. The TASK-041 tests pass with the marker change |
| OpenAPI | 5 operations under `/api/v1/users`, with problem+json refusals; no 422 |
| Scratch (deleted): fake repositories under the real TASK-042 service, and a fake gate | (1) |

(1) Scratch results:
- The list item had exactly the keys above and a `Z` timestamp.
- Refusals: the admin's `bsk_` got 403 `totp_session_required`, and a viewer session got 403 `forbidden`.
- Create: 201 with a viewer item. A duplicate got 409. `role: admin` got 400. An 11-character password got 400 with the rule.
- Role changes: promotion to admin without TOTP got 409 `Promotion to admin needs TOTP.`. Promotion to operator gave `role_granted`. Two fields at once got 400.
- Self-reset of TOTP got 409. Disabling the last admin got 409.
- Disable, enable and revoke-tokens worked. `{disabled: true}` got 400. An unknown id got 404.
- With the gate refusing: 503 `audit_sink_unavailable`.
- Entries: one per change, `user.create` (`user_created`), `user.role_change` (`role_granted`), `user.disable`, `user.enable` and `user.tokens_revoke`.
- No `password_hash` appeared in any body.

## For the tester (TP-M2-20, API part)

- CHK-M2-231 route walk: every `/users` dependency has `.bitscan_auth.check == "totp_session"` and `sink_gate=True`. `POST /api-tokens` now shows `check == "session"` with `admin_totp=True`.
- CHK-M2-234: after `PATCH {totp: null}` by another admin, that admin's next sign-in is restricted (the TASK-038 rule).

## Lead rulings (decisions.md 2026-10-22, "Lead rulings on TASK-043")

All three choices are confirmed:
- **(a)** exactly one change per `PATCH`; anything else gets 400 `invalid_request`;
- **(b)** `POST /users` answers 201;
- **(c)** `PATCH {disabled: true}` answers 400, because `DELETE` is the only way to disable a user.

## Revision 1 (review CHANGES_REQUESTED, `work/reviews/TASK-043.md` finding 1)

**Cause.** `PATCH /users/{id}` chose the sub-action from `body.model_fields_set`, and that set also contains fields sent as `null`. As a result:
- `{"revoke_tokens": null}` revoked all of the user's tokens;
- `{"disabled": null}` re-enabled a disabled user;
- `{"role": null}` reached the service as the string `"None"` and was refused only by accident.

**Fix** (`api/user/users.py`). After the exactly-one-field check, the field must carry its documented value, or the request gets 400 `invalid_request` with `Invalid request: body.<field>`. This happens before any transaction, so nothing changes and no audit entry is written. The documented values are:
- `role`: one of the three roles;
- `disabled`: `false`;
- `revoke_tokens`: `true`;
- `totp`: `null`, the one field where null is the documented value.

The handler then runs the checked field's action. The OpenAPI document is unchanged.

**Re-checked.**
- ruff and mypy `--strict` are clean.
- Scratch with fakes (deleted): `{"revoke_tokens": null}`, `{"disabled": null}` and `{"role": null}` each got 400 naming the field. No repository call and no audit entry was made. A valid `{"disabled": false}` still re-enabled the user and wrote `user.enable`.

**For the tester.** The reviewer asks for a test per null body: each must get 400 and change nothing, with no audit entry.
