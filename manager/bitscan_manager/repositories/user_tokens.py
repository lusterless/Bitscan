"""user_token SQL (TS §5.2, §6.2). Parameterised statements only.

Only SHA-256 token hashes reach this module, never tokens. Runs inside the
caller's transaction; never commits. bitscan_app has no DELETE on user_token:
tokens end by setting revoked_at.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

KINDS = frozenset({"session", "api"})


@dataclass(frozen=True)
class TokenOwner:
    """A user_token row and its owner, for resolving a presented token."""

    token_id: int
    kind: str
    totp_verified: bool
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    user_id: int
    username: str
    role: str
    disabled: bool
    totp_enrolled: bool


@dataclass(frozen=True)
class ApiTokenRow:
    token_id: int
    name: str | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def _kinds(kinds: Collection[str]) -> list[str]:
    chosen = sorted(set(kinds))
    if not chosen or not KINDS.issuperset(chosen):
        raise ValueError("token kinds must be a non-empty subset of session, api")
    return chosen


class UserTokenRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def find_by_hash(self, token_hash: str) -> TokenOwner | None:
        row = self._conn.execute(
            "SELECT t.token_id, t.kind, t.totp_verified, t.expires_at,"
            " t.last_used_at, t.revoked_at, t.created_at, u.user_id, u.username,"
            " u.role, u.disabled, u.totp_secret_enc IS NOT NULL"
            " FROM user_token t JOIN app_user u ON u.user_id = t.user_id"
            " WHERE t.token_hash = %s",
            (token_hash,),
        ).fetchone()
        # The select list is in TokenOwner field order.
        return None if row is None else TokenOwner(*row)

    def insert(
        self,
        *,
        user_id: int,
        kind: str,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
        name: str | None = None,
        totp_verified: bool = False,
    ) -> int:
        _kinds([kind])
        row = self._conn.execute(
            "INSERT INTO user_token (user_id, kind, name, token_hash, totp_verified,"
            " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " RETURNING token_id",
            (user_id, kind, name, token_hash, totp_verified, expires_at, now),
        ).fetchone()
        if row is None:
            raise RuntimeError("user_token insert returned no id")
        return int(row[0])

    def _update(self, query: str, params: tuple[Any, ...]) -> int:
        return self._conn.execute(query, params).rowcount

    def touch(self, token_id: int, now: datetime) -> bool:
        """Set last_used_at, skipping the write when it is under 60 s old."""
        return 1 == self._update(
            "UPDATE user_token SET last_used_at = %s WHERE token_id = %s"
            " AND (last_used_at IS NULL"
            " OR last_used_at < CAST(%s AS timestamptz) - interval '60 seconds')",
            (now, token_id, now),
        )

    def revoke(self, token_id: int, now: datetime) -> bool:
        return 1 == self._update(
            "UPDATE user_token SET revoked_at = %s"
            " WHERE token_id = %s AND revoked_at IS NULL",
            (now, token_id),
        )

    def revoke_own_api(self, user_id: int, token_id: int, now: datetime) -> bool:
        """False whether the id is unknown, another user's, a session or
        already revoked, so the caller cannot tell those apart."""
        return 1 == self._update(
            "UPDATE user_token SET revoked_at = %s WHERE token_id = %s"
            " AND user_id = %s AND kind = 'api' AND revoked_at IS NULL",
            (now, token_id, user_id),
        )

    def revoke_for_user(
        self, user_id: int, kinds: Collection[str], now: datetime
    ) -> int:
        return self._update(
            "UPDATE user_token SET revoked_at = %s WHERE user_id = %s"
            " AND kind = ANY(%s) AND revoked_at IS NULL",
            (now, user_id, _kinds(kinds)),
        )

    def list_api(
        self, user_id: int, limit: int, after_id: int | None
    ) -> list[ApiTokenRow]:
        rows = self._conn.execute(
            "SELECT token_id, name, created_at, expires_at, last_used_at, revoked_at"
            " FROM user_token WHERE user_id = %s AND kind = 'api'"
            " AND (%s::bigint IS NULL OR token_id > %s)"
            " ORDER BY token_id LIMIT %s",
            (user_id, after_id, after_id, limit),
        ).fetchall()
        return [ApiTokenRow(*r) for r in rows]
