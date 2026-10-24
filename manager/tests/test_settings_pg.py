"""TASK-055: settings repository and typed read on PostgreSQL as bitscan_app.

Checks CHK-M3-090 and CHK-M3-095 of tests/m3/test-plan.md (TP-M3-09). Expected
values: TS §8.6 L1317-L1339 (defaults), #42 (bare JSON numbers, an array of
five strings in spec order), TS §5.2 L827-L840 (system_schedule, setting,
grants: UPDATE only, no DELETE; the inventory CHECK 3,600-86,400).
Rows changed by a test are restored as owner, so later tests see the seeds.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.services.settings import read_settings

from .conftest import PgServer
from .test_settings_service import DEFAULT_PATTERNS, SPEC_DEFAULTS

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(migrated_db: PgServer) -> Iterator[Conn]:
    with migrated_db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


@pytest.fixture
def owner(migrated_db: PgServer) -> Iterator[Conn]:
    with migrated_db.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        yield c


@pytest.fixture
def restore(owner: Conn) -> Iterator[None]:
    settings = owner.execute(
        "SELECT key, value, updated_by, updated_at FROM setting"
    ).fetchall()
    sched = owner.execute("SELECT job_kind, interval_s FROM system_schedule").fetchall()
    yield
    for key, value, by, at in settings:
        owner.execute(
            "UPDATE setting SET value = %s, updated_by = %s, updated_at = %s"
            " WHERE key = %s",
            (Jsonb(value), by, at, key),
        )
    for kind, interval in sched:
        owner.execute(
            "UPDATE system_schedule SET interval_s = %s WHERE job_kind = %s",
            (interval, kind),
        )


# ------------------------------------------------------------ CHK-M3-090


def test_seeded_defaults_read_back_exactly(conn: Conn) -> None:
    """REQ-083 (1), #42."""
    s = read_settings(SettingsRepo(conn))
    assert s.as_dict() == {**SPEC_DEFAULTS, "redaction_patterns": DEFAULT_PATTERNS}
    # byte for byte, in spec order
    assert [p.encode() for p in s.redaction_patterns] == [
        p.encode() for p in DEFAULT_PATTERNS
    ]


def test_seed_json_shapes(conn: Conn) -> None:
    """#42: bare numbers for the five numeric keys, an array for the patterns."""
    rows = dict(conn.execute("SELECT key, jsonb_typeof(value) FROM setting").fetchall())
    assert rows == {
        "agent_token_ttl_days": "number",
        "job_pull_seconds": "number",
        "decommission_after_days": "number",
        "redaction_patterns": "array",
        "max_parallel_plugins": "number",
        "enrolment_alert_per_hour": "number",
    }


def test_inventory_interval_comes_from_system_schedule(
    conn: Conn, owner: Conn, restore: None
) -> None:
    owner.execute(
        "UPDATE system_schedule SET interval_s = 7200 WHERE job_kind = 'inventory'"
    )
    assert read_settings(SettingsRepo(conn)).inventory_interval_s == 7200
    repo = SettingsRepo(conn)
    assert repo.schedule_interval("inventory") == 7200
    assert repo.schedule_interval("offline_sweep") == 60
    assert repo.schedule_interval("retention") == 86_400
    assert repo.schedule_interval("nope") is None


# ------------------------------------------------------------ CHK-M3-095


def test_write_value_updates_only_seeded_keys(conn: Conn, restore: None) -> None:
    repo = SettingsRepo(conn)
    with conn.transaction():
        assert repo.write_value("job_pull_seconds", 120, 7, T0) is True
        assert repo.write_value("inventory_enabled", False, 7, T0) is False
    row = conn.execute(
        "SELECT value, updated_by, updated_at FROM setting"
        " WHERE key = 'job_pull_seconds'"
    ).fetchone()
    assert row == (120, 7, T0)
    keys = {r[0] for r in conn.execute("SELECT key FROM setting").fetchall()}
    assert "inventory_enabled" not in keys and len(keys) == 6
    assert read_settings(repo).job_pull_seconds == 120


def test_write_patterns_round_trip(conn: Conn, restore: None) -> None:
    repo = SettingsRepo(conn)
    with conn.transaction():
        assert repo.write_value("redaction_patterns", DEFAULT_PATTERNS[:3], None, T0)
    assert list(read_settings(repo).redaction_patterns) == DEFAULT_PATTERNS[:3]


def test_write_schedule_interval(conn: Conn, restore: None) -> None:
    repo = SettingsRepo(conn)
    with conn.transaction():
        assert repo.write_schedule_interval("inventory", 3600) is True
        assert repo.write_schedule_interval("nope", 3600) is False
    assert repo.schedule_interval("inventory") == 3600


@pytest.mark.parametrize("bad", [3599, 86_401, 0])
def test_database_check_still_bounds_the_inventory_interval(
    conn: Conn, restore: None, bad: int
) -> None:
    """Defence in depth: the CHECK refuses what the service would refuse first."""
    with pytest.raises(errors.CheckViolation), conn.transaction():
        SettingsRepo(conn).write_schedule_interval("inventory", bad)
    assert SettingsRepo(conn).schedule_interval("inventory") == 21_600


def test_lock_settings_runs_as_app(conn: Conn) -> None:
    with conn.transaction():
        SettingsRepo(conn).lock_settings()
        locked = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()"
            " AND locktype = 'transactionid'"
        ).fetchone()
        assert locked is not None and locked[0] >= 1


@pytest.mark.parametrize(
    "stmt",
    [
        "DELETE FROM setting WHERE key = 'job_pull_seconds'",
        "DELETE FROM system_schedule WHERE job_kind = 'inventory'",
        "TRUNCATE setting",
        "TRUNCATE system_schedule",
    ],
)
def test_app_cannot_remove_settings_or_schedules(conn: Conn, stmt: str) -> None:
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute(stmt)


def test_no_enabled_column_on_system_schedule(conn: Conn) -> None:
    cols = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'system_schedule'"
        ).fetchall()
    }
    assert cols and not any("enable" in c for c in cols)
