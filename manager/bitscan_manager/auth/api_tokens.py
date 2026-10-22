"""API tokens (TS §6.2 L1081, L1085, L1098-L1099; REQ-051; #8, #47, #50, #52).

Shared by POST /api-tokens and bitscan-manager users create-api-token
(TASK-046): both pass their own transaction. The token is returned once and
only its SHA-256 is stored; creation writes one api_token_created alert entry,
whose detail never holds the token or its hash.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import ApiTokenRow, UserTokenRepo
from bitscan_manager.runtime import Tx
from bitscan_manager.services.audit import append_entry, raise_alert

DEFAULT_DAYS: Final = 90
MAX_DAYS: Final = 365
NAME_MAX: Final = 64


class ApiTokenInvalid(ValueError):
    """Names the rule (lifetime or name), never a value."""


@dataclass(frozen=True)
class CreatedToken:
    token_id: int
    token: str  # shown once
    name: str | None
    expires_at: datetime


def create_api_token(
    tx: Tx,
    *,
    user_id: int,
    name: str | None,
    days: int | None,
    now: datetime,
    actor: str,
) -> CreatedToken:
    lifetime = DEFAULT_DAYS if days is None else days
    if isinstance(lifetime, bool) or not 1 <= lifetime <= MAX_DAYS:
        raise ApiTokenInvalid(f"the lifetime must be 1 to {MAX_DAYS} days")
    if name is not None and len(name) > NAME_MAX:
        raise ApiTokenInvalid(f"the name must be at most {NAME_MAX} characters")
    token = new_token(TokenKind.API)
    expires_at = now + timedelta(days=lifetime)
    token_id = UserTokenRepo(tx.conn).insert(
        user_id=user_id,
        kind=TokenKind.API.value,
        token_hash=token_hash(token),
        expires_at=expires_at,
        now=now,
        name=name,
    )
    raise_alert(
        PgAuditRepo(tx.conn),
        tx.on_commit,
        kind="api_token_created",
        actor=actor,
        action="api_token.create",
        target=f"user:{user_id}",
        detail={
            "token_id": token_id,
            "name": name,
            "expires_at": expires_at.isoformat(),
        },
    )
    return CreatedToken(token_id, token, name, expires_at)


def list_own(
    tx: Tx, *, user_id: int, limit: int, after_id: int | None
) -> list[ApiTokenRow]:
    return UserTokenRepo(tx.conn).list_api(user_id, limit, after_id)


def revoke_own(
    tx: Tx, *, user_id: int, token_id: int, now: datetime, actor: str
) -> bool:
    """False alike for an unknown id, another user's token, a session or a
    token already revoked (REQ-051 (3))."""
    if not UserTokenRepo(tx.conn).revoke_own_api(user_id, token_id, now):
        return False
    append_entry(
        PgAuditRepo(tx.conn),
        actor=actor,
        action="api_token.revoke",
        target=f"user:{user_id}",
        detail={"token_id": token_id},
    )
    return True
