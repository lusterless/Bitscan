"""REQ-021 (and REQ-027 method): schema part 1, the policy catalog (TP-M1-05).

Checks CHK-M1-070 to CHK-M1-074. Written from TS §5.2 L638-L707 before reading
the migration. Behaviour cases run as bitscan_owner inside a transaction that is
always rolled back; each statement gets its own savepoint.
"""

import uuid
from collections.abc import Iterator
from typing import Any, LiteralString

import psycopg
import pytest

from .conftest import REFERENCE_DB, Conn, PgServer
from .schema_diff import Scope, diff, dump, reference_sql

CATALOG = Scope.of(
    tables=("family", "policy", "plugin", "policy_plugin", "bit_import"),
    types=("policy_status", "plugin_state", "plugin_operator"),
)
SHA = "a" * 64
OPERATORS = [
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "empty",
    "not_empty",
]

# --- unit: helper and spec extraction (no Docker) -----------------------------


def test_reference_sql_is_the_spec_blocks() -> None:
    ddl, view = reference_sql()
    lines = [line for line in ddl.split("\n") if line.strip()]
    assert lines[0] == "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
    assert "CREATE TABLE family (" in ddl
    assert "CREATE TABLE bit_import (" in ddl
    assert lines[-1].startswith("GRANT DELETE ON policy_plugin")
    assert view.split("\n")[0] == "CREATE VIEW v_plugin AS"
    assert "GRANT SELECT ON v_plugin TO bitscan_app;" in view


def test_diff_reports_each_kind_of_difference() -> None:
    ref: dict[str, dict[str, Any]] = {
        "table": {"a": {"owner": "o"}, "b": {"owner": "o"}},
        "index": {"i": 1},
    }
    assert diff(ref, ref) == []
    got: dict[str, dict[str, Any]] = {
        "table": {"a": {"owner": "x"}, "c": {"owner": "o"}},
        "index": {},
    }
    problems = diff(ref, got)
    assert "missing table b" in problems
    assert "extra table c" in problems
    assert "missing index i" in problems
    assert any(p.startswith("different table a:") and "'x'" in p for p in problems)
    assert len(problems) == 4


def test_scope_of_leaves_acls_out() -> None:
    assert CATALOG.acls is False
    assert CATALOG.tables is not None and "plugin" in CATALOG.tables
    assert Scope().tables is None and Scope().acls is True


# --- PostgreSQL ----------------------------------------------------------------


@pytest.fixture
def cat(migrated_db: PgServer, owner_conn: Conn) -> Iterator[Conn]:
    with owner_conn.transaction(force_rollback=True):
        yield owner_conn


def state(conn: Conn, query: LiteralString, params: tuple[Any, ...] = ()) -> str | None:
    """SQLSTATE of the statement, or None if it succeeded (savepoint)."""
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


def family(conn: Conn, name: str = "CIS Ubuntu 24.04") -> int:
    return int(
        one(
            conn,
            "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
            (name,),
        )
    )


def policy(conn: Conn, fam: int, name: str = "p1", source: str = "a.bit") -> int:
    return int(
        one(
            conn,
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256) VALUES (%s, 'enabled', 'enabled', %s, %s, %s)"
            " RETURNING policy_id",
            (name, fam, source, SHA),
        )
    )


def plugin(conn: Conn, fam: int, owner: int, **extra: Any) -> uuid.UUID:
    pid = uuid.uuid4()
    cols = [
        "plugin_uuid",
        "family_id",
        "owner_policy_id",
        "plugin_name",
        "execute",
        "execute_sha256",
        "operator",
    ]
    vals: list[Any] = [pid, fam, owner, "1.1 - x", "true", SHA, "equals"]
    for k, v in extra.items():
        if k in cols:
            vals[cols.index(k)] = v
        else:
            cols.append(k)
            vals.append(v)
    from psycopg import sql

    q = sql.SQL("INSERT INTO plugin ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)),
    )
    conn.execute(q, vals)
    return pid


@pytest.mark.pg
def test_catalog_is_diff_equal_to_the_spec(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with (
        migrated_db.connect("bitscan_migrate") as got,
        reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref,
    ):
        problems = diff(dump(ref, CATALOG), dump(got, CATALOG))
    assert problems == [], "\n".join(problems)


@pytest.mark.pg
def test_reference_database_is_separate(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref:
        assert one(ref, "SELECT current_database()") == REFERENCE_DB
        assert one(ref, "SELECT to_regclass('alembic_version') IS NULL") is True
    with migrated_db.connect("bitscan_migrate") as got:
        assert one(got, "SELECT current_database()") == "bitscan"


@pytest.mark.pg
def test_enum_labels_are_in_spec_order(cat: Conn) -> None:
    assert one(cat, "SELECT enum_range(NULL::plugin_operator)::text[]") == OPERATORS
    assert one(cat, "SELECT enum_range(NULL::policy_status)::text[]") == [
        "enabled",
        "disabled",
    ]
    assert one(cat, "SELECT enum_range(NULL::plugin_state)::text[]") == [
        "active",
        "retired",
    ]


@pytest.mark.pg
def test_plugin_timeout_bounds_and_default(cat: Conn) -> None:
    fam = family(cat)
    owner = policy(cat, fam)
    for bad in (0, 601, -1):
        with pytest.raises(psycopg.errors.CheckViolation):
            with cat.transaction():
                plugin(cat, fam, owner, timeout_s=bad)
    for good in (1, 600):
        plugin(cat, fam, owner, timeout_s=good)
    pid = plugin(cat, fam, owner)
    assert one(cat, "SELECT timeout_s FROM plugin WHERE plugin_uuid = %s", (pid,)) == 60


@pytest.mark.pg
@pytest.mark.parametrize(
    ("mode", "outcome", "expected"),
    [
        ("auto", "success", None),
        ("manual", "skipped", None),
        ("rebuild", "rejected", None),
        ("upload", "success", "23514"),
        ("AUTO", "success", "23514"),
        ("auto", "failed", "23514"),
        ("auto", "Success", "23514"),
    ],
)
def test_bit_import_mode_and_outcome(
    cat: Conn, mode: str, outcome: str, expected: str | None
) -> None:
    got = state(
        cat,
        "INSERT INTO bit_import (file_name, file_sha256, mode, outcome)"
        " VALUES ('a.bit', %s, %s, %s)",
        (SHA, mode, outcome),
    )
    assert got == expected


@pytest.mark.pg
def test_catalog_defaults(cat: Conn) -> None:
    fam = family(cat)
    pid = policy(cat, fam)
    row = cat.execute(
        "SELECT status_overridden, format_version, version, policy_description,"
        " deleted_at, imported_at IS NOT NULL, updated_at IS NOT NULL"
        " FROM policy WHERE policy_id = %s",
        (pid,),
    ).fetchone()
    assert row == (False, "1.0", 1, "", None, True, True)
    plug = plugin(cat, fam, pid)
    row = cat.execute(
        "SELECT state::text, expected_result, plugin_description, control_ref"
        " FROM plugin WHERE plugin_uuid = %s",
        (plug,),
    ).fetchone()
    assert row == ("active", "", "", None)
    imp = one(
        cat,
        "INSERT INTO bit_import (file_name, file_sha256, mode, outcome)"
        " VALUES ('a.bit', %s, 'auto', 'success') RETURNING import_id",
        (SHA,),
    )
    row = cat.execute(
        "SELECT errors, plugins_added, plugins_updated, plugins_retired,"
        " policy_version, imported_by FROM bit_import WHERE import_id = %s",
        (imp,),
    ).fetchone()
    assert row == ([], 0, 0, 0, None, None)


@pytest.mark.pg
def test_uniqueness_and_foreign_keys(cat: Conn) -> None:
    fam = family(cat, "F1")
    assert state(cat, "INSERT INTO family (family_name) VALUES ('F1')") == "23505"
    p1 = policy(cat, fam, "p1", "a.bit")
    assert (
        state(
            cat,
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256)"
            " VALUES ('p1', 'enabled', 'enabled', %s, 'b.bit', %s)",
            (fam, SHA),
        )
        == "23505"
    )
    assert (
        state(
            cat,
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256)"
            " VALUES ('p2', 'enabled', 'enabled', %s, 'a.bit', %s)",
            (fam, SHA),
        )
        == "23505"
    )
    assert (
        state(
            cat,
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256)"
            " VALUES ('p3', 'enabled', 'enabled', %s, 'c.bit', %s)",
            (fam + 999, SHA),
        )
        == "23503"
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with cat.transaction():
            plugin(cat, fam, p1 + 999)
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        with cat.transaction():
            plugin(cat, fam, p1, operator="matches")


@pytest.mark.pg
def test_deleting_a_policy_deletes_its_policy_plugin_rows(cat: Conn) -> None:
    fam = family(cat)
    owner = policy(cat, fam, "owner", "owner.bit")
    member = policy(cat, fam, "member", "member.bit")
    plug = plugin(cat, fam, owner)
    for pol, order in ((owner, 1), (member, 2)):
        cat.execute(
            "INSERT INTO policy_plugin (policy_id, plugin_uuid, sort_order)"
            " VALUES (%s, %s, %s)",
            (pol, plug, order),
        )
    assert (
        state(cat, "INSERT INTO policy_plugin VALUES (%s, %s, 3)", (member, plug))
        == "23505"
    )
    cat.execute("DELETE FROM policy WHERE policy_id = %s", (member,))
    assert (
        one(cat, "SELECT count(*) FROM policy_plugin WHERE policy_id = %s", (member,))
        == 0
    )
    assert (
        one(cat, "SELECT count(*) FROM policy_plugin WHERE policy_id = %s", (owner,))
        == 1
    )
    # The owning policy cannot go while its plugin exists
    # (owner_policy_id has no ON DELETE action).
    assert state(cat, "DELETE FROM policy WHERE policy_id = %s", (owner,)) == "23503"
