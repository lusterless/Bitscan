# TASK-042 plan: users service

REQs: REQ-052, REQ-041, REQ-055. Owner: impl-manager. **Two approvals (TS §8.2, auth).** Depends on: TASK-028, TASK-031, TASK-035. Files: `bm/services/users/__init__.py`, `bm/services/users/accounts.py`. Routes are TASK-043; the CLI is TASK-046. Tests: TP-M2-20.

**Blocked on:** #7 (initial password), #53 (which sessions and tokens end; admins created directly; re-enable; self-actions), #50 (actions and alert kinds), #56 (username rules), #48 (conflict status).

## Spec quotes

- TS §6.2 L1125: "CRUD `/users` | Accounts, roles, revoke a user's tokens; delete means disable | admin, TOTP session".
- L1085: "Disabling or demoting a user, or revoking their tokens, revokes every API token they created."
- L1086: "A password change, role change or TOTP reset ends the user's sessions."
- L1089: "Promoting a user to admin in the UI or API requires that user to have TOTP enrolled already."
- L1090: "A lost TOTP device is reset by another admin or on the server with `bitscan-manager users reset-totp <user>`; both alert and are audit-logged. The last active admin cannot be disabled or demoted."
- L1091: "Admins can revoke any user's tokens; disabling a user revokes all of them at once."
- TS §5.3 L1050: "Users are never deleted, only disabled, so the `*_by` columns … always resolve." (`bitscan_app` has no DELETE on `app_user`.)
- TS §8.4 L1290: alerts for "user created, role granted or admin created; TOTP reset".

## Interface

```python
class UsersRepo(Protocol):          # implemented by repositories/users.py and user_tokens.py (TASK-031)
    def insert_user(self, username: str, password_hash: str, role: str) -> int: ...      # raises DuplicateUsername
    def get(self, user_id: int) -> UserRow | None: ...
    def get_for_update(self, user_id: int) -> UserRow | None: ...
    def lock_active_admins(self) -> list[int]: ...       # SELECT user_id … WHERE role='admin' AND NOT disabled ORDER BY user_id FOR UPDATE
    def set_role(self, user_id: int, role: str) -> None: ...
    def set_disabled(self, user_id: int, disabled: bool) -> None: ...
    def clear_totp(self, user_id: int) -> None: ...      # totp_secret_enc = NULL, totp_last_step = NULL
    def revoke_tokens(self, user_id: int, kinds: frozenset[str], now: datetime) -> int: ...
    def list_page(self, limit: int, after_id: int | None) -> list[UserRow]: ...

class AuditSink(Protocol):          # append_entry and raise_alert from services/audit, bound to the transaction
    def audit(self, action: str, target: str, detail: Mapping[str, object]) -> None: ...
    def alert(self, kind: str, action: str, target: str, detail: Mapping[str, object]) -> None: ...

class UserRuleError(Exception):     # .rule is an enum: duplicate, last_admin, needs_totp, self_reset, not_found
    ...

def create_user(repo, audit, *, actor: str, username: str, password: str, role: str = "viewer") -> int: ...
def change_role(repo, audit, *, actor: str, actor_id: int | None, user_id: int, role: str, now: datetime) -> None: ...
def disable_user(repo, audit, *, actor, actor_id, user_id, now) -> None: ...
def enable_user(repo, audit, *, actor, user_id) -> None: ...                     # only if #53 (g) says yes
def reset_totp(repo, audit, *, actor, actor_id: int | None, user_id, now) -> None: ...   # actor_id None = CLI
def revoke_user_tokens(repo, audit, *, actor, user_id, now) -> None: ...
def create_admin(repo, audit, *, username: str, password: str) -> int: ...       # CLI only (TASK-046)
```

## Rules, in the order they are checked

- Every function runs inside the caller's transaction (the route's `Tx` or the CLI's), so the change and its audit entry commit together or not at all (REQ-052 (8)).
- `create_user`: `check_new_password` (REQ-041), username rules (#56 (d)); `role` must be viewer or operator under #53 (f) default (admin only through `change_role` or the CLI); audit `user.create`, alert `user_created`.
- `change_role`: `get_for_update(user_id)`; same role → no-op (no audit). Promotion to admin: `totp_secret_enc` must be set, else `UserRuleError(needs_totp)`. Demotion of an active admin: `lock_active_admins()` first; if the target is the only id in the list, `UserRuleError(last_admin)`. Then `set_role`; revoke sessions (any role change, #53 (c)); on a demotion (#53 (d): any lower role) also revoke API tokens. Audit `user.role_change` with old and new role; alert `role_granted` on a promotion, plus `admin_created` when the new role is admin (#50 default).
- `disable_user` (`DELETE /users/{id}`): already disabled → no-op. If the target is an active admin: `lock_active_admins()` and the same last-admin rule. `set_disabled(True)`; revoke all tokens (`{"session", "api"}`). Audit `user.disable`.
- `reset_totp` (by another admin): `actor_id == user_id` → `UserRuleError(self_reset)` (#53 (h); the CLI passes `actor_id=None`). `clear_totp`; revoke sessions. Audit `user.totp_reset`, alert `totp_reset`. API tokens are untouched here; whether they still work while the admin has no TOTP is TASK-037 (#53 (i)).
- `revoke_user_tokens`: revoke API tokens, and sessions under #53 (e) default. Audit `user.tokens_revoke`.

## Concurrency: the last-admin rule

Two active admins A and B; A demotes B (T1) while B demotes A (T2), at the same time (REQ-052 (5)).
1. Both call `lock_active_admins()`, which locks every active admin row in `user_id` order. T1 gets the locks; T2 waits.
2. T1 sees {A, B}, so B is not the last admin; it demotes B, revokes B's sessions and API tokens, and commits.
3. T2 then gets the locks. Under READ COMMITTED, PostgreSQL re-checks the `WHERE role = 'admin' AND NOT disabled` condition on the locked rows, so T2 sees only {A}. Its target A is the last active admin: `UserRuleError(last_admin)`, nothing changes.

Locking in a fixed order means no deadlock. Disabling takes the same lock, so a mixed disable and demote race behaves the same way. The test runs T1 and T2 on two `bitscan_app` connections and asserts that at least one active admin remains whatever the interleaving.

## Edge cases

- The audit `target` is `user:<id>`; `detail` never holds a password, hash or seed (REQ-052 (9), canary).
- Role changes and TOTP resets on a disabled user: the spec has no rule either way, so the service adds none (no refusal is invented). If the lead wants one, it joins #53.
- Usernames are never changed (no rule says they can be; the route has no field for it, #47).
- `services/users` takes the repository and audit objects as protocols, so its unit tests run without PostgreSQL and count toward the 85 % gate (G5).
