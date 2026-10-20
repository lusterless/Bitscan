"""REQ-009: the PostgreSQL 16 harness has the three extensions and debversion works.

Checks CHK-M0-050 and CHK-M0-051 of tests/m0/test-plan.md.
"""

import pytest

from .conftest import Connect

pytestmark = pytest.mark.pg

EXTENSIONS = {"pg_trgm", "pgcrypto", "debversion"}


def test_server_is_postgresql_16(pg_connect: Connect) -> None:
    with pg_connect() as conn:
        row = conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    assert 160000 <= int(row[0]) <= 169999


def test_required_extensions_are_available(pg_connect: Connect) -> None:
    with pg_connect() as conn:
        rows = conn.execute(
            "SELECT name FROM pg_available_extensions WHERE name = ANY(%s)",
            (sorted(EXTENSIONS),),
        ).fetchall()
    assert {r[0] for r in rows} == EXTENSIONS


def test_debversion_orders_like_dpkg(pg_connect: Connect) -> None:
    with pg_connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS debversion")
        row = conn.execute(
            "SELECT '1.0~rc1'::debversion < '1.0'::debversion,"
            " '1.0'::debversion < '1.0~rc1'::debversion,"
            " '1.0~rc1' < '1.0'"
        ).fetchone()
    assert row == (True, False, False)
