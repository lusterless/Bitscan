"""Who is calling: resolve a user bearer token to a Principal (TS §2.3, §6.2;
REQ-044; plan work/plans/TASK-037.md).

Only bsu_ and bsk_ tokens are accepted, and only when the row's kind matches
the prefix, it is neither revoked nor expired, a session has been used in the
last 8 hours, and the user is enabled. The role is the user's current one,
read on every request. resolve() returns None for every failed check, so the
caller cannot tell the causes apart.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from bitscan_manager.auth.tokens import TokenKind, parse_user_token, token_hash
from bitscan_manager.repositories.user_tokens import UserTokenRepo

ROLE_ORDER: Final[Mapping[str, int]] = {"viewer": 0, "operator": 1, "admin": 2}
SESSION_IDLE: Final = timedelta(hours=8)


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str  # app_user.role, read in this request
    kind: TokenKind
    token_id: int
    totp_verified: bool  # always False for API tokens
    totp_enrolled: bool  # app_user.totp_secret_enc IS NOT NULL
    expires_at: datetime  # the token's own expiry (a re-issue keeps it)

    @property
    def restricted(self) -> bool:
        """REQ-046 (d): an admin session that is not TOTP-verified."""
        return (
            self.role == "admin"
            and self.kind is TokenKind.SESSION
            and not self.totp_verified
        )

    @property
    def admin_api_without_totp(self) -> bool:
        """#53 (i): an admin's API token is refused while the admin has no TOTP."""
        return (
            self.role == "admin"
            and self.kind is TokenKind.API
            and not self.totp_enrolled
        )

    def at_least(self, minimum: str) -> bool:
        return ROLE_ORDER[self.role] >= ROLE_ORDER[minimum]


def resolve(tokens: UserTokenRepo, raw_token: str, now: datetime) -> Principal | None:
    kind = parse_user_token(raw_token)
    if kind is None:
        return None
    row = tokens.find_by_hash(token_hash(raw_token))
    if (
        row is None
        or row.kind != kind.value
        or row.revoked_at is not None
        or row.expires_at <= now
        or row.disabled
        or row.role not in ROLE_ORDER
    ):
        return None
    if kind is TokenKind.SESSION:
        last_use = row.last_used_at or row.created_at
        if last_use + SESSION_IDLE <= now:
            return None
    return Principal(
        user_id=row.user_id,
        username=row.username,
        role=row.role,
        kind=kind,
        token_id=row.token_id,
        totp_verified=row.totp_verified and kind is TokenKind.SESSION,
        totp_enrolled=row.totp_enrolled,
        expires_at=row.expires_at,
    )
