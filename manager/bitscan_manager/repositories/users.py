"""app_user SQL (TS §5.2, §6.2). Parameterised statements only.

Runs inside the caller's transaction; never commits. bitscan_app has SELECT,
INSERT and UPDATE on app_user and no DELETE (users are only disabled).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

_COLS = sql.SQL(
    "user_id, username, password_hash, totp_secret_enc, totp_last_step, role,"
    " disabled, failed_logins, next_login_at, created_at"
)
_BY_USERNAME = sql.SQL("SELECT {} FROM app_user WHERE username = %s").format(_COLS)
_BY_ID = sql.SQL("SELECT {} FROM app_user WHERE user_id = %s").format(_COLS)
_BY_ID_FOR_UPDATE = sql.SQL(
    "SELECT {} FROM app_user WHERE user_id = %s FOR UPDATE"
).format(_COLS)
_PAGE = sql.SQL(
    "SELECT {} FROM app_user WHERE %s::bigint IS NULL OR user_id > %s"
    " ORDER BY user_id LIMIT %s"
).format(_COLS)

# Back-off after n consecutive failures: min(2^(n-1), 900) s from the failure
# (REQ-048 (3)). The counter stops at 1000 so the SMALLINT never overflows.
_RECORD_FAILURE = (
    "UPDATE app_user SET failed_logins = LEAST(failed_logins + 1, 1000),"
    " next_login_at = CAST(%s AS timestamptz) + make_interval(secs =>"
    " LEAST(900, power(2, LEAST(failed_logins + 1, 11) - 1)))"
    " WHERE user_id = %s RETURNING failed_logins"
)


class DuplicateUsername(Exception):
    """The username is already taken; nothing was inserted."""


@dataclass(frozen=True)
class UserRow:
    user_id: int
    username: str
    password_hash: str = field(repr=False)
    totp_secret_enc: str | None = field(repr=False)
    totp_last_step: int | None
    role: str
    disabled: bool
    failed_logins: int
    next_login_at: datetime | None
    created_at: datetime

    @property
    def totp_enrolled(self) -> bool:
        return self.totp_secret_enc is not None


def _row(row: tuple[Any, ...] | None) -> UserRow | None:
    # _COLS lists the columns in UserRow field order.
    return None if row is None else UserRow(*row)


class UserRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def _one(self, query: sql.Composed, params: tuple[Any, ...]) -> UserRow | None:
        return _row(self._conn.execute(query, params).fetchone())

    def find_by_username(self, username: str) -> UserRow | None:
        return self._one(_BY_USERNAME, (username,))

    def get(self, user_id: int) -> UserRow | None:
        return self._one(_BY_ID, (user_id,))

    def get_for_update(self, user_id: int) -> UserRow | None:
        return self._one(_BY_ID_FOR_UPDATE, (user_id,))

    def list_page(self, limit: int, after_id: int | None) -> list[UserRow]:
        rows = self._conn.execute(_PAGE, (after_id, after_id, limit)).fetchall()
        return [u for u in map(_row, rows) if u is not None]

    def insert_user(
        self, username: str, password_hash: str, role: str, now: datetime
    ) -> int:
        row = self._conn.execute(
            "INSERT INTO app_user (username, password_hash, role, created_at)"
            " VALUES (%s, %s, CAST(%s AS user_role), %s)"
            " ON CONFLICT (username) DO NOTHING RETURNING user_id",
            (username, password_hash, role, now),
        ).fetchone()
        if row is None:
            raise DuplicateUsername
        return int(row[0])

    def lock_active_admins(self) -> list[int]:
        """Lock every active admin row in user_id order (no deadlock) and
        return their ids, so the last-admin rule holds under concurrency."""
        rows = self._conn.execute(
            "SELECT user_id FROM app_user WHERE role = 'admin' AND NOT disabled"
            " ORDER BY user_id FOR UPDATE"
        ).fetchall()
        return [int(r[0]) for r in rows]

    def _update(self, query: str, params: tuple[Any, ...]) -> bool:
        return self._conn.execute(query, params).rowcount == 1

    def set_role(self, user_id: int, role: str) -> bool:
        return self._update(
            "UPDATE app_user SET role = CAST(%s AS user_role) WHERE user_id = %s",
            (role, user_id),
        )

    def set_disabled(self, user_id: int, disabled: bool) -> bool:
        return self._update(
            "UPDATE app_user SET disabled = %s WHERE user_id = %s", (disabled, user_id)
        )

    def set_password_hash(self, user_id: int, password_hash: str) -> bool:
        return self._update(
            "UPDATE app_user SET password_hash = %s WHERE user_id = %s",
            (password_hash, user_id),
        )

    def set_totp(self, user_id: int, secret_enc: str, last_step: int) -> bool:
        return self._update(
            "UPDATE app_user SET totp_secret_enc = %s, totp_last_step = %s"
            " WHERE user_id = %s",
            (secret_enc, last_step, user_id),
        )

    def clear_totp(self, user_id: int) -> bool:
        return self._update(
            "UPDATE app_user SET totp_secret_enc = NULL, totp_last_step = NULL"
            " WHERE user_id = %s",
            (user_id,),
        )

    def claim_totp_step(self, user_id: int, step: int) -> bool:
        """True for exactly one caller per step: the step must be newer than the
        stored one, and the check and the write are one statement."""
        return self._update(
            "UPDATE app_user SET totp_last_step = %s WHERE user_id = %s"
            " AND (totp_last_step IS NULL OR totp_last_step < %s)",
            (step, user_id, step),
        )

    def record_failure(self, user_id: int, now: datetime) -> int | None:
        """Count one failed sign-in atomically; returns the new count."""
        row = self._conn.execute(_RECORD_FAILURE, (now, user_id)).fetchone()
        return None if row is None else int(row[0])

    def reset_failures(self, user_id: int) -> bool:
        return self._update(
            "UPDATE app_user SET failed_logins = 0, next_login_at = NULL"
            " WHERE user_id = %s",
            (user_id,),
        )
