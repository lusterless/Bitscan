"""REQ-024: schema part 4, system tables (TP-M1-09).

Checks CHK-M1-096 to CHK-M1-098. Written from TS §5.2 L827-L840 and L941-L990
before reading the migration. Behaviour cases run as bitscan_owner in a
transaction that is always rolled back (system_schedule rows are cleared inside
it first, so the cases hold before and after the m0005 seeds).
"""

import secrets
from collections.abc import Iterator
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import sql

from .conftest import REFERENCE_DB, Conn, PgServer, migrate_to
from .schema_diff import Scope, diff, dump

SYSTEM = Scope.of(
    tables=(
        "system_schedule",
        "setting",
        "task",
        "app_user",
        "user_token",
        "audit_log",
    ),
    types=("user_role",),
)


@pytest.fixture
def sy(migrated_db: PgServer, owner_conn: Conn) -> Iterator[Conn]:
    with owner_conn.transaction(force_rollback=True):
        yield owner_conn


def state(conn: Conn, query: LiteralString, params: tuple[Any, ...] = ()) -> str | None:
    try:
        with conn.transaction():
            conn.execute(query, params)
    except psycopg.Error as exc:
        return exc.sqlstate
    return None


def one(conn: Conn, query: LiteralString, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def coltype(conn: Conn, table: str, col: str) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT format_type(atttypid, atttypmod), attnotnull FROM pg_attribute"
        " WHERE attrelid = %s::regclass AND attname = %s",
        (table, col),
    ).fetchone()
    assert row is not None, (table, col)
    return (str(row[0]), bool(row[1]))


def user(conn: Conn, name: str = "alice") -> int:
    return int(
        one(
            conn,
            "INSERT INTO app_user (username, password_hash)"
            " VALUES (%s, 'argon2id$x') RETURNING user_id",
            (name,),
        )
    )


# --- diff --------------------------------------------------------------------------


@pytest.mark.pg
def test_system_objects_are_diff_equal_to_the_spec(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with (
        migrated_db.connect("bitscan_migrate") as got,
        reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref,
    ):
        problems = diff(dump(ref, SYSTEM), dump(got, SYSTEM))
    assert problems == [], "\n".join(problems)


@pytest.mark.pg
def test_system_schedule_and_setting_are_empty_at_m0004(
    fresh_pg_server: PgServer,
) -> None:
    migrate_to(fresh_pg_server, "m0004")
    with fresh_pg_server.connect("bitscan_migrate") as conn:
        assert one(conn, "SELECT version_num FROM alembic_version") == "m0004"
        assert one(conn, "SELECT count(*) FROM system_schedule") == 0
        assert one(conn, "SELECT count(*) FROM setting") == 0


# --- system_schedule (inventory cannot be disabled) ---------------------------------


@pytest.mark.pg
def test_system_schedule_has_no_enabled_column(sy: Conn) -> None:
    cols = [
        r[0]
        for r in sy.execute(
            "SELECT attname FROM pg_attribute"
            " WHERE attrelid = 'system_schedule'::regclass"
            " AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
        ).fetchall()
    ]
    assert cols == ["job_kind", "interval_s"]


@pytest.mark.pg
@pytest.mark.parametrize(
    ("kind", "interval", "expected"),
    [
        ("inventory", 3600, None),
        ("inventory", 86400, None),
        ("inventory", 3599, "23514"),
        ("inventory", 86401, "23514"),
        ("offline_sweep", 60, None),
        ("offline_sweep", 59, "23514"),
        ("retention", 86400, None),
        ("retention", 86401, "23514"),
        ("cleanup", 3600, "23514"),
        ("Inventory", 3600, "23514"),
    ],
)
def test_system_schedule_checks(
    sy: Conn, kind: str, interval: int, expected: str | None
) -> None:
    sy.execute("DELETE FROM system_schedule")
    assert (
        state(
            sy,
            "INSERT INTO system_schedule (job_kind, interval_s) VALUES (%s, %s)",
            (kind, interval),
        )
        == expected
    )


@pytest.mark.pg
def test_system_schedule_key_and_update_checks(sy: Conn) -> None:
    sy.execute("DELETE FROM system_schedule")
    sy.execute("INSERT INTO system_schedule VALUES ('inventory', 21600)")
    assert (
        state(sy, "INSERT INTO system_schedule VALUES ('inventory', 3600)") == "23505"
    )
    assert (
        state(
            sy,
            "UPDATE system_schedule SET interval_s = 60 WHERE job_kind = 'inventory'",
        )
        == "23514"
    )
    assert (
        state(sy, "INSERT INTO system_schedule VALUES ('retention', NULL)") == "23502"
    )


# --- setting, task ----------------------------------------------------------------


@pytest.mark.pg
def test_setting_shape(sy: Conn) -> None:
    sy.execute("DELETE FROM setting")
    sy.execute("INSERT INTO setting (key, value) VALUES ('k', '1')")
    row = sy.execute(
        "SELECT updated_by, updated_at IS NOT NULL FROM setting WHERE key = 'k'"
    ).fetchone()
    assert row == (None, True)
    assert state(sy, "INSERT INTO setting (key, value) VALUES ('k', '2')") == "23505"
    assert state(sy, "INSERT INTO setting (key, value) VALUES ('j', NULL)") == "23502"
    assert coltype(sy, "setting", "key") == ("character varying(64)", True)


@pytest.mark.pg
@pytest.mark.parametrize(
    ("kind", "state_", "expected"),
    [
        ("rebuild", "running", None),
        ("rebuild", "succeeded", None),
        ("rebuild", "failed", None),
        ("import", "running", "23514"),
        ("rebuild", "done", "23514"),
        ("rebuild", "Running", "23514"),
    ],
)
def test_task_kind_and_state(
    sy: Conn, kind: str, state_: str, expected: str | None
) -> None:
    assert (
        state(sy, "INSERT INTO task (kind, state) VALUES (%s, %s)", (kind, state_))
        == expected
    )


@pytest.mark.pg
def test_task_defaults(sy: Conn) -> None:
    row = sy.execute(
        "INSERT INTO task (kind) VALUES ('rebuild')"
        " RETURNING state, task_id IS NOT NULL, started_at IS NOT NULL, finished_at"
    ).fetchone()
    assert row == ("running", True, True, None)


# --- users and tokens ---------------------------------------------------------------


@pytest.mark.pg
def test_app_user_defaults_and_roles(sy: Conn) -> None:
    assert one(sy, "SELECT enum_range(NULL::user_role)::text[]") == [
        "viewer",
        "operator",
        "admin",
    ]
    uid = user(sy)
    row = sy.execute(
        "SELECT role::text, disabled, failed_logins, totp_secret_enc, next_login_at"
        " FROM app_user WHERE user_id = %s",
        (uid,),
    ).fetchone()
    assert row == ("viewer", False, 0, None, None)
    assert (
        state(
            sy, "INSERT INTO app_user (username, password_hash) VALUES ('alice', 'h')"
        )
        == "23505"
    )
    assert (
        state(
            sy,
            "INSERT INTO app_user (username, password_hash, role)"
            " VALUES ('bob', 'h', 'root')",
        )
        == "22P02"
    )


@pytest.mark.pg
@pytest.mark.parametrize(
    ("kind", "totp", "expected"),
    [
        ("session", False, None),
        ("session", True, None),
        ("api", False, None),
        ("api", True, "23514"),
        ("bearer", False, "23514"),
    ],
)
def test_user_token_kind_and_totp(
    sy: Conn, kind: str, totp: bool, expected: str | None
) -> None:
    uid = user(sy)
    assert (
        state(
            sy,
            "INSERT INTO user_token"
            " (user_id, kind, token_hash, totp_verified, expires_at)"
            " VALUES (%s, %s, %s, %s, now() + interval '1 day')",
            (uid, kind, secrets.token_hex(32), totp),
        )
        == expected
    )


@pytest.mark.pg
def test_user_token_hash_index_and_cascade(sy: Conn) -> None:
    uid = user(sy)
    h = secrets.token_hex(32)
    q: LiteralString = (
        "INSERT INTO user_token (user_id, kind, token_hash, expires_at)"
        " VALUES (%s, 'api', %s, now() + interval '1 day')"
    )
    assert state(sy, q, (uid, h)) is None
    assert state(sy, q, (uid, h)) == "23505"
    assert state(sy, q, (uid + 999, secrets.token_hex(32))) == "23503"
    assert coltype(sy, "user_token", "token_hash") == ("character(64)", True)
    assert (
        one(sy, "SELECT totp_verified FROM user_token WHERE token_hash = %s", (h,))
        is False
    )
    idx = one(
        sy, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_user_token_active'"
    )
    assert idx.endswith("USING btree (user_id) WHERE (revoked_at IS NULL)")
    sy.execute("DELETE FROM app_user WHERE user_id = %s", (uid,))
    assert one(sy, "SELECT count(*) FROM user_token WHERE user_id = %s", (uid,)) == 0


# --- audit_log columns ----------------------------------------------------------------


@pytest.mark.pg
def test_audit_log_columns(sy: Conn) -> None:
    expected = {
        "audit_id": ("bigint", True),
        "actor": ("character varying(128)", True),
        "action": ("character varying(64)", True),
        "target": ("character varying(255)", False),
        "detail": ("jsonb", False),
        "at": ("timestamp with time zone", True),
        "prev_hash": ("character(64)", True),
        "row_hash": ("character(64)", True),
    }
    for col, want in expected.items():
        assert coltype(sy, "audit_log", col) == want, col
    for missing in ("prev_hash", "row_hash"):
        cols = [c for c in ("actor", "action", "prev_hash", "row_hash") if c != missing]
        q = sql.SQL("INSERT INTO audit_log ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        )
        try:
            with sy.transaction():
                sy.execute(q, ["a", "b", "0" * 64][: len(cols)])
            got = None
        except psycopg.Error as exc:
            got = exc.sqlstate
        assert got == "23502", missing
