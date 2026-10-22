# TASK-042 IMPL report: users service

REQ: REQ-052, REQ-041, REQ-055. Spec: TS §6.2 L1085–L1091 and L1125, TS §5.3 L1050, TS §8.4 L1290. Open-question answers, as approved:
- #7: `POST /users` takes an initial password of at least 12 characters, with no forced change.
- #50: actions and kinds.
- #53: (c) any role change ends sessions; (d) any lowering also ends API tokens; (e) revoking tokens covers both kinds; (f) no direct admin creation through `POST /users`; (g) re-enable is allowed; (h) self-actions follow the last-admin rule, and a TOTP reset needs another admin.
- #56 (d) with the user's answer: ASCII letters only.

Lead carry-over: lock the active admins before `get_for_update(target)`. Plan: `work/plans/TASK-042.md`. **Two approvals (TS §8.2, auth).**

## Files (2)

- `manager/bitscan_manager/services/users/accounts.py`: new, 242 non-blank lines after `ruff format`, which spreads the signatures over many lines.
- `manager/bitscan_manager/services/users/__init__.py`: new, re-exports.

**Size.** This is above the "about 200" guideline. The tasks note foresaw it ("TASK-042 at the limit; if it grows, split into create/read and change/disable"). I kept it as one task because each function is short and the change and disable rules share the lock and last-admin helpers. Lead: say if you want it split anyway.

## Interface

- **Protocols:**
  - `UserStore`: the subset of `repositories.users.UserRepo` the service uses;
  - `TokenStore`: `revoke_for_user`, from `UserTokenRepo`;
  - `AuditSink`: `audit(actor, action, target, detail)` and `alert(kind, actor, action, target, detail)`.

  The protocols keep the unit tests free of PostgreSQL, so they count toward G5.
- **`TxAudit(repo: AuditRepo, on_commit)`** is the production `AuditSink`. It calls `append_entry` or `raise_alert` with the transaction's `PgAuditRepo` and `tx.on_commit`, so each entry, and the alert counter increment after commit, belongs to the caller's transaction (REQ-052 (8), REQ-055 (2)). An empty detail is stored as NULL.
- **Errors:**
  - `UserRuleError(rule: Rule)`, where `Rule` is one of `duplicate`, `last_admin`, `needs_totp`, `self_reset`, `not_found`, `invalid_username` or `invalid_role`. TASK-043 maps these to 409 `conflict`, or 404 / 400.
  - `PasswordRejected` from TASK-028 propagates unchanged; it maps to 400.
- **Functions.** Every one runs in the caller's transaction and never commits:

| Function | Rules | Audit (actor as given: `user:<id>` or `cli:root`) |
| --- | --- | --- |
| `create_user(users, audit, *, actor, username, password, role="viewer", now)` | username check; password check and Argon2id hash; `role` must be viewer or operator (#53 (f)); duplicate → `duplicate` with no change (insert uses `ON CONFLICT DO NOTHING`) | alert `user_created`, `user.create`, `{"role"}` |
| `create_admin(users, audit, *, actor, username, password, now)` | as above, role admin, no TOTP (for the CLI, TASK-046) | alert `admin_created`, `user.create` |
| `get_user`, `list_users(limit, after_id)` | `not_found` if missing | none |
| `change_role(users, tokens, audit, *, actor, user_id, role, now)` | `lock_active_admins()` **first**, then `get_for_update(target)`, the same lock order everywhere; same role → no-op; to admin without TOTP → `needs_totp`; any lowering of the last active admin → `last_admin`; any change revokes sessions; a lowering also revokes API tokens | a raise: alert `role_granted`, `user.role_change`, `{"from", "to"}`; a lowering: plain `user.role_change` |
| `disable_user(...)` | lock admins first; already disabled → no-op; last active admin → `last_admin` (self included); `disabled = true`, every session and API token revoked | `user.disable` |
| `enable_user(users, audit, *, actor, user_id)` | `disabled = false`; tokens stay revoked (#53 (g)) | `user.enable` |
| `reset_totp(..., actor_id, user_id, now)` | `actor_id == user_id` → `self_reset`; the CLI passes `actor_id=None`; clears `totp_secret_enc` and `totp_last_step`, revokes sessions; API tokens untouched (TASK-037 refuses an admin API token without TOTP) | alert `totp_reset`, `user.totp_reset` |
| `revoke_user_tokens(...)` | revokes API tokens and sessions (#53 (e)) | `user.tokens_revoke`, `{"revoked": n}` |

- **Usernames:** 1–64 characters of ASCII `A–Z`, `a–z`, `0–9` and `._@-`, checked by set membership, so Unicode letters such as `é`, Cyrillic `а` and full-width `Ａ` are refused. They are case-sensitive: `Ab` and `ab` are different users.
- **Last-admin rule:** it applies to an active admin being lowered or disabled when the locked list of active admins is exactly that user. A disabled admin does not count, because the lock query excludes it.

**"Role granted" reading.** TS §8.4 L1290 lists "user created, role granted or admin created".
- **Role granted:** any raise of a role, to operator or to admin, is one entry: alert `role_granted`. A lowering is a plain audit entry.
- **Admin created:** `admin_created` is the CLI's `create_admin`. A promotion to admin is not counted twice, so each event writes exactly one entry, per REQ-055 (1).
- This answers the TP note on CHK-M2-226. Lead: say if a promotion to admin should be `admin_created` instead.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 93 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 925 passed, 237 skipped (pg); **gate FAILS at 80.64 %** until TP-M2-20 unit tests land, because `services/users` has 118 statements at 0 % |
| Scratch with fake stores (deleted) | (1) |
| PostgreSQL (two concurrent demotions; forced rollback) | NOT RUN here; CHK-M2-228/229 in WSL |

(1) Scratch results:
- Creation: the CLI admin, `Ab` and `ab` were created with `$argon2id$` hashes, and `repr(UserRow)` hides the hash.
- Refusals: bad usernames (empty, 65 characters, a space, `é`, `Ａ`, Cyrillic `а`, `a:b`); a duplicate `Ab` (`duplicate`); creating an admin directly (`invalid_role`); an 11-character password (`PasswordRejected`).
- Role and disable rules: promotion to admin without TOTP gave `needs_totp`; disabling or lowering the only admin gave `last_admin`.
- The call order was `lock_active_admins` and then `get_for_update`.
- Revocations: a raise revoked sessions only; a lowering revoked both kinds.
- TOTP reset: a self-reset gave `self_reset`, and a CLI reset was allowed.
- Disable was a no-op the second time; enable worked.
- The audit list held one entry per change, with the kinds as in the table.

## For the tester (TP-M2-20 unit part)

- Fakes need only the protocol methods. `TxAudit` needs a fake `AuditRepo` (the M1 protocol) and a list as `on_commit`.
- CHK-M2-226 rollback: production atomicity comes from the caller's single transaction (`TxAudit` writes through the same `tx`). In a unit test, a fake that raises after the change shows the exception propagating out of the service; it does not commit.

## Lead rulings (decisions.md 2026-10-21, "Lead rulings on TASK-042")

- The task stays as one; the reviewer judges the size.
- The "role granted" reading is confirmed. Any raise of a role writes one `role_granted` alert entry, including a promotion to admin. `admin_created` is only the CLI's create-admin (TASK-046), and `user_created` is `POST /users`. Each event writes one alert entry.
