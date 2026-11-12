"""A user's own web sessions (TS §6.2: GET /auth/sessions and
DELETE /auth/sessions/{id}; owner decision 2026-11-12).

Lists only sessions that still authenticate (not revoked, not expired, not
idle for 8 h). Ending one revokes it and writes one auth.session_revoke audit
entry. A user can see and end only their own sessions; there is no admin view.
"""

from datetime import datetime

from bitscan_manager.auth.principal import SESSION_IDLE
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import SessionRow, UserTokenRepo
from bitscan_manager.runtime import Tx
from bitscan_manager.services.audit import append_entry


def list_own(
    tx: Tx, *, user_id: int, now: datetime, limit: int, after_id: int | None
) -> list[SessionRow]:
    return UserTokenRepo(tx.conn).list_active_sessions(
        user_id, now, now - SESSION_IDLE, limit, after_id
    )


def end_own(tx: Tx, *, user_id: int, token_id: int, now: datetime) -> bool:
    """False alike for an unknown id, another user's token, an API token or a
    session already ended."""
    if not UserTokenRepo(tx.conn).revoke_own_session(user_id, token_id, now):
        return False
    append_entry(
        PgAuditRepo(tx.conn),
        actor=f"user:{user_id}",
        action="auth.session_revoke",
        target=f"user:{user_id}",
        detail={"token_id": token_id},
    )
    return True
