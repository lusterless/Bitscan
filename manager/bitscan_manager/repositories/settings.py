"""setting and system_schedule SQL (TS §5.2, §8.6). Parameterised statements
only.

Runs inside the caller's transaction; never commits. bitscan_app has UPDATE on
both tables and DELETE on neither, so no setting or schedule row can be
removed, and system_schedule has no enabled column: inventory cannot be
switched off here (TS §3.4 L237). The database CHECKs still bound every
interval.
"""

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class SettingsRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def read_values(self) -> dict[str, Any]:
        """Every setting row's decoded JSON value, by key."""
        rows = self._conn.execute("SELECT key, value FROM setting").fetchall()
        return {str(key): value for key, value in rows}

    def schedule_interval(self, job_kind: str) -> int | None:
        row = self._conn.execute(
            "SELECT interval_s FROM system_schedule WHERE job_kind = %s", (job_kind,)
        ).fetchone()
        return None if row is None else int(row[0])

    def lock_settings(self) -> None:
        """Locks every setting row, so concurrent patches apply one at a time."""
        self._conn.execute("SELECT key FROM setting ORDER BY key FOR UPDATE")

    def write_value(
        self, key: str, value: object, updated_by: int | None, now: datetime
    ) -> bool:
        """Updates an existing (seeded) row; never inserts a new key."""
        cur = self._conn.execute(
            "UPDATE setting SET value = %s, updated_by = %s, updated_at = %s"
            " WHERE key = %s",
            (Jsonb(value), updated_by, now, key),
        )
        return cur.rowcount == 1

    def write_schedule_interval(self, job_kind: str, interval_s: int) -> bool:
        cur = self._conn.execute(
            "UPDATE system_schedule SET interval_s = %s WHERE job_kind = %s",
            (interval_s, job_kind),
        )
        return cur.rowcount == 1
