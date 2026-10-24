"""REQ-025: privileges and v_plugin (TP-M1-10; G20).

Checks CHK-M1-130 to CHK-M1-137. The expected matrix is TS §5.2 L992-L1013
written out by hand. Every probe is a real statement run as the role on the
migrated database (success or SQLSTATE 42501), inside a transaction that is
rolled back; UPDATE/DELETE use ``WHERE false`` (privileges are checked at plan
time), TRUNCATE runs for real and is rolled back. The matrix is generated from
the catalog, so a table added later is probed too.
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

from .conftest import Conn, PgServer

APP_UPDATE = frozenset(
    {
        "policy",
        "family",
        "plugin",
        "agent",
        "enrollment_token",
        "enrollment_request",
        "os_info",
        "agent_package",
        "agent_ip_seen",
        "scan_schedule",
        "setting",
        "system_schedule",
        "app_user",
        "user_token",
        "task",
    }
)
APP_UPDATE_COLUMNS = {
    "scan_job": frozenset(
        {"state", "dispatched_at", "started_at", "deadline_at", "finished_at"}
    ),
    "scan": frozenset({"state", "finished_at"}),
}
APP_DELETE = frozenset(
    {"policy_plugin", "agent_tag", "agent_package", "agent_ip_seen", "scan_schedule"}
)
RETENTION_DELETE = frozenset(
    {
        "scan",
        "scan_job",
        "scan_result",
        "scan_result_reeval",
        "inventory_snapshot",
        "enrollment_request",
        "user_token",
        "audit_log",
        "package",
    }
)
NEVER_APP_WRITE = (
    "audit_log",
    "scan_result",
    "scan_result_default",
    "scan_result_reeval",
    "bit_import",
)
NEVER_APP_DELETE = ("scan", "scan_job", "agent", "policy", "system_schedule")
LATER_PARTITION = "scan_result_2100_01"


@pytest.fixture(scope="module")
def tables(migrated_db: PgServer) -> list[str]:
    """Every table and partition in public (views are probed separately)."""
    with migrated_db.connect("bitscan_migrate") as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid ="
                " c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY 1"
            ).fetchall()
            if r[0] != LATER_PARTITION
        ]


def monthly(tables: list[str]) -> list[str]:
    return [t for t in tables if t.startswith("scan_result_2")]


def columns(conn: Conn, table: str) -> list[tuple[str, str]]:
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT attname, attgenerated FROM pg_attribute WHERE attrelid ="
            " %s::regclass"
            " AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
            (table,),
        ).fetchall()
    ]


def probe(conn: Conn, statement: sql.Composed) -> str | None:
    """SQLSTATE of the statement as this role, or None; always rolled back."""
    try:
        with conn.transaction(force_rollback=True):
            conn.execute(statement)
    except psycopg.Error as exc:
        return exc.sqlstate
    return None


def stmt(
    kind: str, table: str, cols: list[tuple[str, str]], col: str = ""
) -> sql.Composed:
    t = sql.Identifier(table)
    if kind == "SELECT":
        return sql.SQL("SELECT 1 FROM {} LIMIT 0").format(t)
    if kind == "INSERT":
        plain = [sql.Identifier(c) for c, gen in cols if not gen]
        return sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} WHERE false").format(
            t, sql.SQL(", ").join(plain), sql.SQL(", ").join(plain), t
        )
    if kind == "UPDATE":
        c = sql.Identifier(col)
        return sql.SQL("UPDATE {} SET {} = {} WHERE false").format(t, c, c)
    if kind == "DELETE":
        return sql.SQL("DELETE FROM {} WHERE false").format(t)
    if kind == "TRUNCATE":
        return sql.SQL("TRUNCATE {}").format(t)
    raise ValueError(kind)


def ok(code: str | None) -> bool:
    assert code in (None, "42501"), code
    return code is None


@pytest.fixture
def later_partition(migrated_db: PgServer) -> Iterator[str]:
    """A partition that bitscan_owner creates after the migration (REQ-025 (2), (7))."""
    with migrated_db.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        conn.execute(
            sql.SQL(
                "CREATE TABLE {} PARTITION OF scan_result"
                " FOR VALUES FROM ('2100-01-01 00:00:00+00') TO ('2100-02-01"
                " 00:00:00+00')"
            ).format(sql.Identifier(LATER_PARTITION))
        )
        try:
            yield LATER_PARTITION
        finally:
            conn.execute(
                sql.SQL("DROP TABLE {}").format(sql.Identifier(LATER_PARTITION))
            )


# --- bitscan_app ---


@pytest.mark.pg
def test_app_can_read_and_append_everything(
    tables: list[str], app_conn: Conn, later_partition: str
) -> None:
    for table in [*tables, later_partition]:
        cols = columns(app_conn, table)
        assert ok(probe(app_conn, stmt("SELECT", table, cols))), table
        assert ok(probe(app_conn, stmt("INSERT", table, cols))), table


@pytest.mark.pg
def test_app_update_matrix(
    tables: list[str], app_conn: Conn, later_partition: str
) -> None:
    wrong = []
    for table in [*tables, later_partition]:
        for col, _ in columns(app_conn, table):
            if col == "result" and table.startswith("scan_result"):
                continue  # generated column: no UPDATE target at all
            expected = table in APP_UPDATE or col in APP_UPDATE_COLUMNS.get(table, ())
            got = ok(probe(app_conn, stmt("UPDATE", table, [], col)))
            if got != expected:
                wrong.append((table, col, "allowed" if got else "refused"))
    assert wrong == []


@pytest.mark.pg
def test_app_delete_and_truncate_matrix(
    tables: list[str], app_conn: Conn, later_partition: str
) -> None:
    for table in [*tables, later_partition]:
        got = ok(probe(app_conn, stmt("DELETE", table, [])))
        assert got == (table in APP_DELETE), table
        assert ok(probe(app_conn, stmt("TRUNCATE", table, []))) is False, table


@pytest.mark.pg
def test_app_never_changes_results_audit_or_imports(
    tables: list[str], app_conn: Conn, later_partition: str
) -> None:
    targets = [*NEVER_APP_WRITE, *monthly(tables), later_partition]
    assert len(monthly(tables)) == 4
    for table in targets:
        for kind in ("DELETE", "TRUNCATE"):
            assert probe(app_conn, stmt(kind, table, [])) == "42501", (kind, table)
        for col, gen in columns(app_conn, table):
            if not gen:
                assert probe(app_conn, stmt("UPDATE", table, [], col)) == "42501", (
                    table,
                    col,
                )


@pytest.mark.pg
def test_app_cannot_delete_core_rows(app_conn: Conn) -> None:
    for table in NEVER_APP_DELETE:
        assert probe(app_conn, stmt("DELETE", table, [])) == "42501", table


@pytest.mark.pg
@pytest.mark.parametrize(
    ("table", "col", "expected"),
    [
        ("scan_job", "agent_id", "42501"),
        ("scan_job", "scan_id", "42501"),
        ("scan_job", "kind", "42501"),
        ("scan_job", "payload", "42501"),
        ("scan_job", "eval_spec", "42501"),
        ("scan", "policy_id", "42501"),
        ("scan_job", "state", None),
        ("scan_job", "dispatched_at", None),
        ("scan_job", "started_at", None),
        ("scan_job", "deadline_at", None),
        ("scan_job", "finished_at", None),
        ("scan", "state", None),
        ("scan", "finished_at", None),
    ],
)
def test_app_cannot_move_jobs_or_scans(
    app_conn: Conn, table: str, col: str, expected: str | None
) -> None:
    assert probe(app_conn, stmt("UPDATE", table, [], col)) == expected


@pytest.mark.pg
def test_app_uses_every_sequence(app_conn: Conn) -> None:
    seqs = [
        r[0]
        for r in app_conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid ="
            " c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind = 'S'"
        ).fetchall()
    ]
    assert "audit_log_audit_id_seq" in seqs
    for seq in seqs:
        assert ok(
            probe(app_conn, sql.SQL("SELECT nextval({})").format(sql.Literal(seq)))
        ), seq


# --- bitscan_retention ---


@pytest.mark.pg
def test_retention_matrix(
    tables: list[str], retention_conn: Conn, later_partition: str
) -> None:
    wrong = []
    for table in [*tables, later_partition]:
        cols = columns(retention_conn, table)
        if not ok(probe(retention_conn, stmt("SELECT", table, cols))):
            wrong.append((table, "SELECT refused"))
        if ok(probe(retention_conn, stmt("DELETE", table, []))) != (
            table in RETENTION_DELETE
        ):
            wrong.append((table, "DELETE"))
        if ok(probe(retention_conn, stmt("INSERT", table, cols))) != (
            table == "audit_log"
        ):
            wrong.append((table, "INSERT"))
        if ok(probe(retention_conn, stmt("TRUNCATE", table, []))):
            wrong.append((table, "TRUNCATE allowed"))
        for col, gen in cols:
            if not gen and ok(probe(retention_conn, stmt("UPDATE", table, [], col))):
                wrong.append((table, f"UPDATE {col} allowed"))
    assert wrong == []


@pytest.mark.pg
def test_retention_writes_an_audit_checkpoint(retention_conn: Conn) -> None:
    with retention_conn.transaction(force_rollback=True):
        row = retention_conn.execute(
            "INSERT INTO audit_log (audit_id, actor, action, prev_hash, row_hash)"
            " VALUES (nextval('audit_log_audit_id_seq'), 'system', 'audit.checkpoint',"
            " %s, %s) RETURNING action",
            ("0" * 64, "1" * 64),
        ).fetchone()
        assert row == ("audit.checkpoint",)
    for seq in ("policy_policy_id_seq", "package_package_id_seq"):
        assert (
            probe(
                retention_conn, sql.SQL("SELECT nextval({})").format(sql.Literal(seq))
            )
            == "42501"
        ), seq


# --- v_plugin, later tables, privileges nobody else holds ---


@pytest.mark.pg
def test_v_plugin_display_name_as_app(migrated_db: PgServer, app_conn: Conn) -> None:
    view_cols = [
        r[0]
        for r in app_conn.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = 'v_plugin'::regclass"
            " AND attnum > 0 ORDER BY attnum"
        ).fetchall()
    ]
    plugin_cols = [c for c, _ in columns(app_conn, "plugin")]
    assert view_cols == [*plugin_cols, "display_name"]
    with app_conn.transaction(force_rollback=True):
        fam = app_conn.execute(
            "INSERT INTO family (family_name) VALUES ('CIS Ubuntu 24.04')"
            " RETURNING family_id"
        ).fetchone()
        assert fam is not None
        pol = app_conn.execute(
            "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
            " source_file, source_sha256) VALUES ('p', 'enabled', 'enabled', %s,"
            " 'p.bit',"
            " %s) RETURNING policy_id",
            (fam[0], "a" * 64),
        ).fetchone()
        assert pol is not None
        app_conn.execute(
            "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
            " execute, execute_sha256, operator) VALUES (gen_random_uuid(), %s, %s,"
            " '1.1.1 - Ensure x', 'true', %s, 'equals')",
            (fam[0], pol[0], "b" * 64),
        )
        # only this test's plugin: the session database is shared (M3 gate fix)
        name = app_conn.execute(
            "SELECT display_name FROM v_plugin WHERE family_id = %s", (fam[0],)
        ).fetchone()
        assert name == ("CIS Ubuntu 24.04 - 1.1.1 - Ensure x",)


def acl(conn: Conn, rel: str) -> set[tuple[str, str]]:
    return {
        (r[0], r[1])
        for r in conn.execute(
            "SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE"
            " pg_get_userbyid(a.grantee) END,"
            " a.privilege_type FROM pg_class c, aclexplode(c.relacl) a"
            " WHERE c.oid = %s::regclass AND a.grantee <> c.relowner",
            (rel,),
        ).fetchall()
    }


@pytest.mark.pg
def test_table_created_later_gets_only_the_default_privileges(
    migrated_db: PgServer, later_partition: str
) -> None:
    expected = {
        ("bitscan_app", "SELECT"),
        ("bitscan_app", "INSERT"),
        ("bitscan_retention", "SELECT"),
    }
    with migrated_db.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        with conn.transaction(force_rollback=True):
            conn.execute("CREATE TABLE later_table (x int)")
            assert acl(conn, "later_table") == expected
        assert acl(conn, later_partition) == expected


@pytest.mark.pg
def test_only_the_owner_holds_truncate_references_trigger(
    migrated_db: PgServer,
) -> None:
    with migrated_db.connect("bitscan_migrate") as conn:
        rows = conn.execute(
            "SELECT c.relname, pg_get_userbyid(a.grantee), a.privilege_type"
            " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,"
            " aclexplode(c.relacl) a WHERE n.nspname = 'public'"
            " AND c.relkind IN ('r', 'p', 'v', 'S') AND a.grantee <> c.relowner"
        ).fetchall()
        assert [r for r in rows if r[2] in ("TRUNCATE", "REFERENCES", "TRIGGER")] == []
        assert [r for r in rows if r[1] == "bitscan_migrate"] == []
        direct = conn.execute(
            "SELECT count(*) FROM information_schema.table_privileges"
            " WHERE grantee = 'bitscan_migrate'"
        ).fetchone()
        assert direct == (0,)


@pytest.mark.pg
def test_public_schema_usage_on_pg16(migrated_db: PgServer) -> None:
    """PG15+: PUBLIC keeps USAGE (not CREATE) on public, so the spec's GRANT USAGE
    has no visible effect; only CREATE matters for the app roles."""
    with migrated_db.connect("bitscan_migrate") as conn:
        row = conn.execute(
            "SELECT has_schema_privilege('bitscan_app', 'public', 'CREATE'),"
            " has_schema_privilege('bitscan_retention', 'public', 'CREATE'),"
            " has_schema_privilege('bitscan_app', 'public', 'USAGE')"
        ).fetchone()
        assert row == (False, False, True)
        public: list[Any] = conn.execute(
            "SELECT a.privilege_type FROM pg_namespace n, aclexplode(n.nspacl) a"
            " WHERE n.nspname = 'public' AND a.grantee = 0"
        ).fetchall()
        assert ("CREATE",) not in public
