"""Sign-in (TS §6.2 L1080, L1086-L1089; REQ-048; #47, #49, #50, #54, #55, #58;
plan work/plans/TASK-038.md).

Every failure raises LoginFailed, which the route answers with one 401 body.
An unknown or disabled user and an attempt during back-off cost one dummy
Argon2id verification, like a wrong password. At most four verifications run
at once, real and dummy alike, in arrival order. A failed password or TOTP
code is counted in its own committed transaction (back-off 1 s doubling to
15 min); an attempt during back-off is not. A vault failure is not a sign-in
failure: VaultUnavailable propagates and the app answers 503 (#58).
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import TracebackType
from typing import Final

from bitscan_manager.auth import passwords, totp
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import UserRepo, UserRow
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import append_entry, raise_alert

SESSION_MAX: Final = timedelta(hours=24)
ALERT_EVERY_FAILURES: Final = 5  # #54 (a): at 5 consecutive failures, then each 5 more
VERIFY_SLOTS: Final = 4
FAILURE_CAP: Final = 1000  # repositories.users caps failed_logins here


class LoginFailed(Exception):
    """One type for every sign-in failure; carries no reason."""


class _FairSemaphore:
    """Counting semaphore that admits waiters strictly in arrival order."""

    def __init__(self, slots: int) -> None:
        self._cond = threading.Condition()
        self._free = slots
        self._next_ticket = 0
        self._serving = 0

    def __enter__(self) -> None:
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            while ticket != self._serving or self._free == 0:
                self._cond.wait()
            self._serving += 1
            self._free -= 1
            self._cond.notify_all()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        with self._cond:
            self._free += 1
            self._cond.notify_all()


VERIFY_GATE: Final = _FairSemaphore(VERIFY_SLOTS)


def verify_password(stored: str, password: str) -> bool:
    with VERIFY_GATE:
        return passwords.verify_password(stored, password)


def dummy_verify(password: str) -> None:
    with VERIFY_GATE:
        passwords.dummy_verify(password)


@dataclass(frozen=True)
class LoginResult:
    token: str  # shown once
    expires_at: datetime
    role: str
    totp_enrolled: bool
    totp_verified: bool


def _fail(runtime: Runtime, user_id: int, now: datetime) -> LoginFailed:
    with runtime.db.transaction() as tx:
        count = UserRepo(tx.conn).record_failure(user_id, now)
        # The counter stops at FAILURE_CAP (TASK-031), so stop alerting there too.
        if (
            count is not None
            and count % ALERT_EVERY_FAILURES == 0
            and count < FAILURE_CAP
        ):
            raise_alert(
                PgAuditRepo(tx.conn),
                tx.on_commit,
                kind="login_failures",
                actor="system",
                action="auth.login_failures",
                target=f"user:{user_id}",
                detail={"failed_logins": count},
            )
            tx.on_commit(runtime.sink_gate.wake)
    return LoginFailed()


def login(
    runtime: Runtime, *, username: str, password: str, totp_code: str | None
) -> LoginResult:
    now = runtime.clock.now()
    with runtime.db.transaction() as tx:
        user: UserRow | None = UserRepo(tx.conn).find_by_username(username)
    if user is None or user.disabled:
        dummy_verify(password)
        raise LoginFailed
    if user.next_login_at is not None and now < user.next_login_at:
        dummy_verify(password)  # #55 (a): not checked and not counted
        raise LoginFailed
    if not verify_password(user.password_hash, password):
        raise _fail(runtime, user.user_id, now)
    step: int | None = None
    if user.totp_secret_enc is not None:  # #49 (c): every enrolled user
        if not totp_code:
            raise _fail(runtime, user.user_id, now)
        seed = runtime.totp_cipher.decrypt(user.totp_secret_enc)  # may raise 503
        step = totp.match_step(seed, totp_code, now)
        if step is None:
            raise _fail(runtime, user.user_id, now)
    token = new_token(TokenKind.SESSION)
    expires_at = now + SESSION_MAX
    with runtime.db.transaction() as tx:
        users = UserRepo(tx.conn)
        claimed = step is None or users.claim_totp_step(user.user_id, step)
        if claimed:
            users.reset_failures(user.user_id)
            UserTokenRepo(tx.conn).insert(
                user_id=user.user_id,
                kind=TokenKind.SESSION.value,
                token_hash=token_hash(token),
                expires_at=expires_at,
                now=now,
                totp_verified=step is not None,
            )
            append_entry(
                PgAuditRepo(tx.conn),
                actor=f"user:{user.user_id}",
                action="auth.login",
                target=f"user:{user.user_id}",
                detail={"totp_verified": step is not None},
            )
            tx.on_commit(runtime.sink_gate.wake)
    if not claimed:  # the code was already used (REQ-042 (2), (3))
        raise _fail(runtime, user.user_id, now)
    return LoginResult(
        token, expires_at, user.role, user.totp_enrolled, step is not None
    )


def logout(runtime: Runtime, *, user_id: int, token_id: int) -> None:
    now = runtime.clock.now()
    with runtime.db.transaction() as tx:
        UserTokenRepo(tx.conn).revoke(token_id, now)
        append_entry(
            PgAuditRepo(tx.conn),
            actor=f"user:{user_id}",
            action="auth.logout",
            target=f"user:{user_id}",
        )
        tx.on_commit(runtime.sink_gate.wake)
