"""REQ-026: seeds and the initial scan_result partitions (TP-M1-11).

Checks CHK-M1-140 to CHK-M1-146. Values from TS §5.2 L832-L833, TS §8.6
L1317-L1339 (patterns read from the spec at test time) and questions #42, #43.
"""

import importlib
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from .conftest import (
    Conn,
    PgServer,
    _role_conn,
    migrate_to,
    own_migrated_server,
)
from .spec_sql import redaction_patterns


# This module checks what the migration seeds, so it runs on a freshly
# migrated database of its own: later tests change settings and add rows in
# the session database (M3 gate fix, lead ruling 2026-10-23).
@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("seeds-credentials")) as server:
        yield server


@pytest.fixture
def app_conn(migrated_db: PgServer) -> Iterator[Conn]:
    yield from _role_conn(migrated_db, "bitscan_app")


@pytest.fixture
def owner_conn(migrated_db: PgServer) -> Iterator[Conn]:
    yield from _role_conn(migrated_db, "bitscan_migrate", set_role="bitscan_owner")


NUMERIC = {
    "agent_token_ttl_days": "365",
    "job_pull_seconds": "300",
    "decommission_after_days": "7",
    "max_parallel_plugins": "2",
    "enrolment_alert_per_hour": "50",
    "max_parallel_jobs": "2",  # m0007, owner decision 2026-11-14 (TS §8.6)
}
APP_RETENTION_ACL = {
    ("bitscan_app", "SELECT"),
    ("bitscan_app", "INSERT"),
    ("bitscan_retention", "SELECT"),
}


def add_months(start: datetime, n: int) -> datetime:
    month = start.month - 1 + n
    return start.replace(year=start.year + month // 12, month=month % 12 + 1)


def utc_month_start(conn: Conn) -> datetime:
    row = conn.execute(
        "SELECT date_trunc('month', now() AT TIME ZONE 'UTC')"
    ).fetchone()
    assert row is not None
    value: datetime = row[0]
    return value


def partitions(conn: Conn) -> list[tuple[str, str, str]]:
    conn.execute("SET TimeZone = 'UTC'")
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid),"
            " pg_get_userbyid(c.relowner)"
            " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
            " WHERE i.inhparent = 'scan_result'::regclass ORDER BY 1"
        ).fetchall()
    ]


# --- seeds ----------------------------------------------------------------------------


@pytest.mark.pg
def test_system_schedule_seeds(migrated_db: PgServer, app_conn: Conn) -> None:
    rows = set(
        app_conn.execute("SELECT job_kind, interval_s FROM system_schedule").fetchall()
    )
    assert rows == {("inventory", 21600), ("offline_sweep", 60), ("retention", 86400)}


@pytest.mark.pg
def test_setting_seeds_are_exactly_the_seven_defaults(
    migrated_db: PgServer, app_conn: Conn
) -> None:
    rows = {
        r[0]: r[1:]
        for r in app_conn.execute(
            "SELECT key, value::text, jsonb_typeof(value), updated_by FROM setting"
        ).fetchall()
    }
    assert set(rows) == {*NUMERIC, "redaction_patterns"}
    for key, text in NUMERIC.items():
        assert rows[key] == (text, "number", None), key
    assert rows["redaction_patterns"][1:] == ("array", None)
    assert not any("inventory" in k or "enable" in k or "disable" in k for k in rows)


@pytest.mark.pg
def test_redaction_patterns_are_the_spec_lines_and_compile_with_re2(
    migrated_db: PgServer, app_conn: Conn
) -> None:
    spec = redaction_patterns()
    assert len(spec) == 5
    row = app_conn.execute(
        "SELECT value FROM setting WHERE key = 'redaction_patterns'"
    ).fetchone()
    assert row is not None
    stored: Any = row[0]
    assert isinstance(stored, list) and all(isinstance(p, str) for p in stored)
    assert stored == spec  # order and every byte
    assert [p.encode() for p in stored] == [s.encode() for s in spec]
    re2: Any = importlib.import_module("re2")
    for pattern in stored:
        re2.compile(pattern)
    assert re2.search(stored[2], "token bsa_" + "A" * 24) is not None
    assert re2.search(stored[3], "key AKIA" + "B" * 16 + " end") is not None


# --- partitions -----------------------------------------------------------------------


@pytest.mark.pg
def test_four_utc_monthly_partitions_from_the_current_month(
    migrated_db: PgServer, owner_conn: Conn
) -> None:
    parts = partitions(owner_conn)
    monthly = [p for p in parts if p[0] != "scan_result_default"]
    assert ("scan_result_default", "DEFAULT", "bitscan_owner") in parts
    assert len(parts) == 5 and len(monthly) == 4
    start = utc_month_start(owner_conn)
    expected = []
    for n in range(4):
        lo, hi = add_months(start, n), add_months(start, n + 1)
        expected.append(
            (
                f"scan_result_{lo:%Y_%m}",
                f"FOR VALUES FROM ('{lo:%Y-%m-%d} 00:00:00+00')"
                f" TO ('{hi:%Y-%m-%d} 00:00:00+00')",
                "bitscan_owner",
            )
        )
    assert monthly == expected


@pytest.mark.pg
def test_partitions_have_the_default_acl(
    migrated_db: PgServer, owner_conn: Conn
) -> None:
    for name, _, _ in partitions(owner_conn):
        got = {
            (r[0], r[1])
            for r in owner_conn.execute(
                "SELECT pg_get_userbyid(a.grantee), a.privilege_type"
                " FROM pg_class c, aclexplode(c.relacl) a"
                " WHERE c.relname = %s AND a.grantee <> c.relowner",
                (name,),
            ).fetchall()
        }
        assert got == APP_RETENTION_ACL, name


@pytest.mark.pg
def test_current_month_row_lands_in_its_partition(
    migrated_db: PgServer, app_conn: Conn
) -> None:
    c = app_conn
    with c.transaction(force_rollback=True):
        fam = c.execute(
            "INSERT INTO family (family_name) VALUES ('F') RETURNING family_id"
        ).fetchone()
        assert fam is not None
        pol = c.execute(
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256) VALUES ('p', 'enabled', 'enabled', %s,"
            " 'p.bit',"
            " %s) RETURNING policy_id",
            (fam[0], "a" * 64),
        ).fetchone()
        assert pol is not None
        plug = c.execute(
            "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
            " execute, execute_sha256, operator) VALUES (gen_random_uuid(), %s, %s,"
            " 'x',"
            " 'true', %s, 'equals') RETURNING plugin_uuid",
            (fam[0], pol[0], "b" * 64),
        ).fetchone()
        agent = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at) VALUES (%s, 'h', 'v', %s, now(),"
            " now())"
            " RETURNING agent_id",
            ("c" * 32, "d" * 64),
        ).fetchone()
        assert plug is not None and agent is not None
        scan = c.execute(
            "INSERT INTO scan (policy_id, policy_version, trigger, target)"
            " VALUES (%s, 1, 'manual', '{}') RETURNING scan_id",
            (pol[0],),
        ).fetchone()
        assert scan is not None
        job = c.execute(
            "INSERT INTO scan_job (kind, scan_id, agent_id, payload, eval_spec,"
            " pickup_by)"
            " VALUES ('compliance', %s, %s, '{}', '[]', now()) RETURNING job_id,"
            " created_at",
            (scan[0], agent[0]),
        ).fetchone()
        assert job is not None
        c.execute(
            "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
            " plugin_name_snap, execute_snap, operator_snap, expected_snap, started_at,"
            " finished_at) VALUES (%s, %s, %s, 0, 'F - x', 'true', 'equals', '', now(),"
            " now())",
            (job[0], job[1], plug[0]),
        )
        where = c.execute("SELECT tableoid::regclass::text FROM scan_result").fetchone()
        start = utc_month_start(c)
        assert where == (f"scan_result_{start:%Y_%m}",)


@pytest.mark.pg
def test_default_partition_is_empty(migrated_db: PgServer, app_conn: Conn) -> None:
    assert app_conn.execute("SELECT count(*) FROM scan_result_default").fetchone() == (
        0,
    )


@pytest.mark.pg
def test_seeds_and_partitions_come_only_with_m0005(fresh_pg_server: PgServer) -> None:
    migrate_to(fresh_pg_server, "m0004")
    with fresh_pg_server.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        assert conn.execute("SELECT count(*) FROM system_schedule").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM setting").fetchone() == (0,)
        assert [p[0] for p in partitions(conn)] == ["scan_result_default"]
