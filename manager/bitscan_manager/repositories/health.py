"""Read-only readiness queries for /readyz (TS §8.4 L1292, §3.4; #41)."""

from typing import Any

import psycopg


def bound_statements(conn: psycopg.Connection[Any], milliseconds: int) -> None:
    """Server-side limit for the rest of this transaction."""
    conn.execute(
        "SELECT set_config('statement_timeout', %s, true)", (str(milliseconds),)
    )


def alembic_revisions(conn: psycopg.Connection[Any]) -> list[str]:
    rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    return [str(r[0]) for r in rows]


def schedule_kinds(conn: psycopg.Connection[Any]) -> set[str]:
    rows = conn.execute("SELECT job_kind FROM system_schedule").fetchall()
    return {str(r[0]) for r in rows}
