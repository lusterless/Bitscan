"""Change your own password (TS §6.2 L1086, L1087, L1097; REQ-050; #53 (a);
decisions 2026-10-22 "Rulings on TASK-039").

The current password is checked like a sign-in: not at all during the
account's back-off (one dummy verification instead), and a wrong one is
counted (back-off and the login_failures alert). On success every session of
the user ends, the presenting one too; API tokens keep working. Argon2id work
runs under the sign-in gate. Nothing here logs or audits a password or hash.
"""

from bitscan_manager.auth import login, passwords
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import UserRepo
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.audit import append_entry


class PasswordChangeRefused(Exception):
    """The current password did not check out; nothing changed."""


def change_password(
    runtime: Runtime, principal: Principal, *, current_password: str, new_password: str
) -> None:
    """Raises passwords.PasswordRejected (the rule only) or PasswordChangeRefused."""
    passwords.check_new_password(new_password)  # before anything is verified
    now = runtime.clock.now()
    with runtime.db.transaction() as tx:
        user = UserRepo(tx.conn).get(principal.user_id)
    if user is None:
        raise PasswordChangeRefused
    if user.next_login_at is not None and now < user.next_login_at:
        login.dummy_verify(current_password)
        raise PasswordChangeRefused
    if not login.verify_password(user.password_hash, current_password):
        login._fail(runtime, user.user_id, now)
        raise PasswordChangeRefused
    with login.VERIFY_GATE:  # hashing costs the same memory as a verification
        new_hash = passwords.hash_password(new_password)
    with runtime.db.transaction() as tx:
        UserRepo(tx.conn).set_password_hash(user.user_id, new_hash)
        UserTokenRepo(tx.conn).revoke_for_user(user.user_id, {"session"}, now)
        append_entry(
            PgAuditRepo(tx.conn),
            actor=f"user:{user.user_id}",
            action="auth.password_change",
            target=f"user:{user.user_id}",
        )
        tx.on_commit(runtime.sink_gate.wake)
