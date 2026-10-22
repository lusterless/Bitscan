"""TOTP enrolment and replacement (TS §6.2 L1085, L1089; REQ-049; #49 (b),
#53 (b), #58; plan work/plans/TASK-038.md, TASK-039 part).

Two calls on POST /auth/totp/enrol. start() makes a new seed and keeps it in
memory only, bound to the caller's session, for 10 minutes; replacing an
existing seed first needs the current password and a current code. confirm()
takes the pending seed, checks a code from it, stores it through the vault
cipher and re-issues the session as TOTP-verified with the same expiry; every
other session of the user ends. Nothing here logs the seed, the secret, the
provisioning URI or a code.
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from bitscan_manager.auth import login, totp
from bitscan_manager.auth.principal import Principal
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.auth.vault import VaultUnavailable
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import UserRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import raise_alert

PENDING_FOR: Final = timedelta(minutes=10)


class EnrolRefused(Exception):
    """The credentials or the code did not check out; nothing was stored."""


class NoPendingEnrolment(Exception):
    """confirm() without a live start() on this session."""


@dataclass(frozen=True)
class _Pending:
    user_id: int
    seed: bytes
    expires_at: datetime


class PendingEnrolments:
    """Pending seeds by session token_id (one manager instance, TS §2.1)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_token: dict[int, _Pending] = {}

    def put(self, token_id: int, user_id: int, seed: bytes, now: datetime) -> datetime:
        expires_at = now + PENDING_FOR
        with self._lock:
            self._by_token = {
                k: v for k, v in self._by_token.items() if v.expires_at > now
            }
            self._by_token[token_id] = _Pending(user_id, seed, expires_at)
        return expires_at

    def take(self, token_id: int, user_id: int, now: datetime) -> _Pending | None:
        with self._lock:
            pending = self._by_token.pop(token_id, None)
        if pending is None or pending.user_id != user_id or pending.expires_at <= now:
            return None
        return pending

    def restore(self, token_id: int, pending: _Pending) -> None:
        with self._lock:
            self._by_token.setdefault(token_id, pending)

    def drop(self, token_id: int) -> None:
        with self._lock:
            self._by_token.pop(token_id, None)


@dataclass(frozen=True)
class EnrolStart:
    secret: str  # base32, shown once to the caller
    otpauth_uri: str


@dataclass(frozen=True)
class EnrolDone:
    token: str  # the re-issued session, shown once
    expires_at: datetime
    role: str


def start(
    runtime: Runtime,
    pending: PendingEnrolments,
    principal: Principal,
    *,
    current_password: str | None,
    current_code: str | None,
) -> EnrolStart:
    now = runtime.clock.now()
    with runtime.db.transaction() as tx:
        user = UserRepo(tx.conn).get(principal.user_id)
    if user is None:
        raise EnrolRefused
    if user.totp_secret_enc is not None:  # a replacement (TS §6.2 L1085)
        # Same rules as sign-in (decisions 2026-10-22, "Rulings on TASK-039"):
        # during back-off nothing is checked; a wrong password, wrong code or
        # reused code counts as a failed sign-in (back-off and alert).
        in_backoff = user.next_login_at is not None and now < user.next_login_at
        if in_backoff or not current_password or not current_code:
            login.dummy_verify(current_password or "")
            raise EnrolRefused
        if not login.verify_password(user.password_hash, current_password):
            login._fail(runtime, user.user_id, now)
            raise EnrolRefused
        seed = runtime.totp_cipher.decrypt(user.totp_secret_enc)  # 503 if down
        step = totp.match_step(seed, current_code, now)
        claimed = False
        if step is not None:
            with runtime.db.transaction() as tx:
                claimed = UserRepo(tx.conn).claim_totp_step(user.user_id, step)
        if not claimed:  # a wrong code, or one already used
            login._fail(runtime, user.user_id, now)
            raise EnrolRefused
    new_seed = totp.new_seed()
    pending.put(principal.token_id, user.user_id, new_seed, now)
    return EnrolStart(
        secret=totp.seed_to_base32(new_seed),
        otpauth_uri=totp.provisioning_uri(new_seed, user.username),
    )


def confirm(
    runtime: Runtime, pending: PendingEnrolments, principal: Principal, *, code: str
) -> EnrolDone:
    now = runtime.clock.now()
    taken = pending.take(principal.token_id, principal.user_id, now)
    if taken is None:
        raise NoPendingEnrolment
    step = totp.match_step(taken.seed, code, now)
    if step is None:
        raise EnrolRefused  # the pending seed is discarded; start again
    try:
        ciphertext = runtime.totp_cipher.encrypt(taken.seed)
    except VaultUnavailable:
        pending.restore(principal.token_id, taken)  # the user may retry (#58)
        raise
    token = new_token(TokenKind.SESSION)
    with runtime.db.transaction() as tx:
        users, tokens = UserRepo(tx.conn), UserTokenRepo(tx.conn)
        user = users.get_for_update(principal.user_id)
        if user is None:
            raise EnrolRefused
        replacing = user.totp_secret_enc is not None
        users.set_totp(user.user_id, ciphertext, step)
        tokens.revoke_for_user(user.user_id, {"session"}, now)  # #53 (b)
        tokens.insert(
            user_id=user.user_id,
            kind=TokenKind.SESSION.value,
            token_hash=token_hash(token),
            expires_at=principal.expires_at,  # the 24 h maximum is kept
            now=now,
            totp_verified=True,
        )
        raise_alert(
            PgAuditRepo(tx.conn),
            tx.on_commit,
            kind="totp_replaced" if replacing else "totp_enrolled",
            actor=f"user:{user.user_id}",
            action="auth.totp_replace" if replacing else "auth.totp_enrol",
            target=f"user:{user.user_id}",
        )
        tx.on_commit(runtime.sink_gate.wake)
    return EnrolDone(token=token, expires_at=principal.expires_at, role=user.role)
