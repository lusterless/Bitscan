"""User accounts and roles (TS §6.2 L1085-L1091, §5.3 L1050, §8.4 L1290;
#7, #50, #53, #56; plan work/plans/TASK-042.md).

Every function runs in the caller's transaction, so a change and its audit
entry commit together or not at all. Users are never deleted. Each change
writes one audit entry; creating a user, raising a role, creating an admin
and resetting TOTP write it as an alert.
"""

import string
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from bitscan_manager.auth.passwords import hash_password
from bitscan_manager.repositories.users import DuplicateUsername, UserRow
from bitscan_manager.services.audit.alerts import raise_alert
from bitscan_manager.services.audit.chain import AuditRepo, append_entry

ROLES: Final = ("viewer", "operator", "admin")  # ascending
USERNAME_MAX: Final = 64
_USERNAME_CHARS: Final = frozenset(string.ascii_letters + string.digits + "._@-")
_ALL: Final = frozenset({"session", "api"})


class Rule(StrEnum):
    DUPLICATE = "duplicate"
    LAST_ADMIN = "last_admin"
    NEEDS_TOTP = "needs_totp"
    SELF_RESET = "self_reset"
    NOT_FOUND = "not_found"
    INVALID_USERNAME = "invalid_username"
    INVALID_ROLE = "invalid_role"


class UserRuleError(Exception):
    def __init__(self, rule: Rule) -> None:
        super().__init__(rule.value)
        self.rule = rule


class UserStore(Protocol):  # repositories.users.UserRepo
    def insert_user(
        self, username: str, password_hash: str, role: str, now: datetime
    ) -> int: ...
    def get(self, user_id: int) -> UserRow | None: ...
    def get_for_update(self, user_id: int) -> UserRow | None: ...
    def list_page(self, limit: int, after_id: int | None) -> list[UserRow]: ...
    def lock_active_admins(self) -> list[int]: ...
    def set_role(self, user_id: int, role: str) -> bool: ...
    def set_disabled(self, user_id: int, disabled: bool) -> bool: ...
    def clear_totp(self, user_id: int) -> bool: ...


class TokenStore(Protocol):  # repositories.user_tokens.UserTokenRepo
    def revoke_for_user(
        self, user_id: int, kinds: Collection[str], now: datetime
    ) -> int: ...


class AuditSink(Protocol):
    """append_entry and raise_alert bound to the caller's transaction."""

    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


class TxAudit:
    """AuditSink over the transaction's AuditRepo and on-commit registrar."""

    def __init__(
        self, repo: AuditRepo, on_commit: Callable[[Callable[[], None]], None]
    ) -> None:
        self._repo, self._on_commit = repo, on_commit

    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None:
        append_entry(
            self._repo,
            actor=actor,
            action=action,
            target=target,
            detail=dict(detail) or None,
        )

    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None:
        raise_alert(
            self._repo,
            self._on_commit,
            kind=kind,
            actor=actor,
            action=action,
            target=target,
            detail=detail,
        )


def check_username(username: str) -> None:
    """#56 (d) and the user's answer: 1-64 of ASCII letters, digits, ._@-"""
    if not 1 <= len(username) <= USERNAME_MAX or not _USERNAME_CHARS.issuperset(
        username
    ):
        raise UserRuleError(Rule.INVALID_USERNAME)


def _target(user_id: int) -> str:
    return f"user:{user_id}"


def _load(users: UserStore, user_id: int) -> UserRow:
    row = users.get_for_update(user_id)
    if row is None:
        raise UserRuleError(Rule.NOT_FOUND)
    return row


def _guard_last_admin(admins: list[int], row: UserRow) -> None:
    if row.role == "admin" and not row.disabled and admins == [row.user_id]:
        raise UserRuleError(Rule.LAST_ADMIN)


def _create(
    users: UserStore, username: str, password: str, role: str, now: datetime
) -> int:
    check_username(username)
    password_hash = hash_password(password)  # PasswordRejected names the rule
    try:
        return users.insert_user(username, password_hash, role, now)
    except DuplicateUsername:
        raise UserRuleError(Rule.DUPLICATE) from None


def create_user(
    users: UserStore,
    audit: AuditSink,
    *,
    actor: str,
    username: str,
    password: str,
    role: str = "viewer",
    now: datetime,
) -> int:
    """POST /users: viewer or operator only; admins come from promotion (#53 (f))."""
    if role not in ("viewer", "operator"):
        raise UserRuleError(Rule.INVALID_ROLE)
    user_id = _create(users, username, password, role, now)
    audit.alert("user_created", actor, "user.create", _target(user_id), {"role": role})
    return user_id


def create_admin(
    users: UserStore,
    audit: AuditSink,
    *,
    actor: str,
    username: str,
    password: str,
    now: datetime,
) -> int:
    """bitscan-manager users create-admin: an admin with no TOTP yet."""
    user_id = _create(users, username, password, "admin", now)
    audit.alert(
        "admin_created", actor, "user.create", _target(user_id), {"role": "admin"}
    )
    return user_id


def get_user(users: UserStore, user_id: int) -> UserRow:
    row = users.get(user_id)
    if row is None:
        raise UserRuleError(Rule.NOT_FOUND)
    return row


def list_users(users: UserStore, limit: int, after_id: int | None) -> list[UserRow]:
    return users.list_page(limit, after_id)


def change_role(
    users: UserStore,
    tokens: TokenStore,
    audit: AuditSink,
    *,
    actor: str,
    user_id: int,
    role: str,
    now: datetime,
) -> None:
    if role not in ROLES:
        raise UserRuleError(Rule.INVALID_ROLE)
    admins = users.lock_active_admins()  # before the target row: fixed lock order
    row = _load(users, user_id)
    if row.role == role:
        return
    raised = ROLES.index(role) > ROLES.index(row.role)
    if role == "admin" and not row.totp_enrolled:
        raise UserRuleError(Rule.NEEDS_TOTP)
    if not raised:
        _guard_last_admin(admins, row)
    users.set_role(user_id, role)
    # Any role change ends sessions (#53 (c)); lowering ends API tokens (#53 (d)).
    tokens.revoke_for_user(user_id, {"session"} if raised else _ALL, now)
    detail = {"from": row.role, "to": role}
    if raised:
        audit.alert("role_granted", actor, "user.role_change", _target(user_id), detail)
    else:
        audit.audit(actor, "user.role_change", _target(user_id), detail)


def disable_user(
    users: UserStore,
    tokens: TokenStore,
    audit: AuditSink,
    *,
    actor: str,
    user_id: int,
    now: datetime,
) -> None:
    """DELETE /users/{id}: disable, never delete; all tokens end."""
    admins = users.lock_active_admins()
    row = _load(users, user_id)
    if row.disabled:
        return
    _guard_last_admin(admins, row)
    users.set_disabled(user_id, True)
    tokens.revoke_for_user(user_id, _ALL, now)
    audit.audit(actor, "user.disable", _target(user_id), {})


def enable_user(
    users: UserStore, audit: AuditSink, *, actor: str, user_id: int
) -> None:
    """#53 (g): re-enable; revoked tokens stay revoked."""
    row = _load(users, user_id)
    if not row.disabled:
        return
    users.set_disabled(user_id, False)
    audit.audit(actor, "user.enable", _target(user_id), {})


def reset_totp(
    users: UserStore,
    tokens: TokenStore,
    audit: AuditSink,
    *,
    actor: str,
    actor_id: int | None,
    user_id: int,
    now: datetime,
) -> None:
    """By another admin (actor_id) or the server CLI (actor_id None, #53 (h))."""
    if actor_id == user_id:
        raise UserRuleError(Rule.SELF_RESET)
    _load(users, user_id)
    users.clear_totp(user_id)
    tokens.revoke_for_user(user_id, {"session"}, now)
    audit.alert("totp_reset", actor, "user.totp_reset", _target(user_id), {})


def revoke_user_tokens(
    users: UserStore,
    tokens: TokenStore,
    audit: AuditSink,
    *,
    actor: str,
    user_id: int,
    now: datetime,
) -> None:
    """#53 (e): API tokens and sessions."""
    _load(users, user_id)
    revoked = tokens.revoke_for_user(user_id, _ALL, now)
    audit.audit(actor, "user.tokens_revoke", _target(user_id), {"revoked": revoked})
