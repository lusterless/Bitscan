"""TP-M11-22: grant probes for bitscan_retention on a freshly migrated
database (TS §8.3 L1280; TS §5.2 L996-L1006; TS §5.3 L1051; REQ-278 (3);
CHK-M11-150 to -154; TASK-237 TEST).

Expected values are the TS §5.2 grants: bitscan_retention has SELECT on every
table, DELETE on exactly scan, scan_job, scan_result, scan_result_reeval,
inventory_snapshot, enrollment_request, user_token, audit_log and package,
INSERT on audit_log only, USAGE on audit_log_audit_id_seq only, and no UPDATE
anywhere; so it can take no row lock (lead's correction 2026-11-08: the
plan's `FOR UPDATE SKIP LOCKED` fails) and runs no DDL. Each probe runs in a
rolled-back transaction (`m.refused` gives the SQLSTATE, or None).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from psycopg import sql

from . import m11_pg_fixtures as m
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NINE = frozenset(m.RETENTION_TABLES)
NEVER = (
    "agent",
    "policy",
    "agent_package",
    "os_info",
    "enrollment_token",
    "setting",
    "family",
    "plugin",
    "policy_plugin",
    "scan_schedule",
    "system_schedule",
    "app_user",
    "task",
    "bit_import",
    "agent_tag",
    "agent_ip_seen",
)
DENIED = "42501"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("retention-grants")) as s:
        yield s


@pytest.fixture
def ret(server: PgServer) -> Iterator[m.Conn]:
    with server.connect("bitscan_retention") as c:
        row = c.execute(
            "SELECT current_user::text, rolsuper FROM pg_roles"
            " WHERE rolname = current_user"
        ).fetchone()
        assert row == ("bitscan_retention", False)
        yield c


def tables(conn: m.Conn) -> list[str]:
    """Every table and partitioned parent in public, partitions excluded."""
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n"
            " ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
            " AND c.relkind IN ('r', 'p') AND NOT c.relispartition ORDER BY 1"
        ).fetchall()
    ]


def first_column(conn: m.Conn, table: str) -> str:
    row = conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = CAST(%s AS regclass)"
        " AND attnum > 0 AND NOT attisdropped AND attgenerated = ''"
        " ORDER BY attnum LIMIT 1",
        (table,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def ident(table: str) -> sql.Identifier:
    return sql.Identifier(table)


# ------------------------------------------------------------ CHK-M11-150


def test_delete_exactly_on_the_nine_tables(ret: m.Conn) -> None:
    every = tables(ret)
    assert NINE <= set(every) and set(NEVER) <= set(every)
    allowed = {
        t
        for t in every
        if m.refused(ret, sql.SQL("DELETE FROM {} WHERE false").format(ident(t)))
        is None
    }
    assert allowed == NINE
    for t in NEVER:
        assert m.refused(ret, sql.SQL("DELETE FROM {}").format(ident(t))) == DENIED, t


def test_select_on_every_table(ret: m.Conn) -> None:
    for t in tables(ret):
        assert (
            m.refused(ret, sql.SQL("SELECT 1 FROM {} LIMIT 1").format(ident(t))) is None
        ), t


# ------------------------------------------------------------ CHK-M11-151


def test_insert_only_on_audit_log_and_no_update_anywhere(ret: m.Conn) -> None:
    for t in tables(ret):
        insert = m.refused(
            ret, sql.SQL("INSERT INTO {} DEFAULT VALUES").format(ident(t))
        )
        if t == "audit_log":
            assert insert != DENIED  # allowed; the row itself fails NOT NULL
        else:
            assert insert == DENIED, t
        col = ident(first_column(ret, t))
        update = sql.SQL("UPDATE {} SET {} = {} WHERE false").format(ident(t), col, col)
        assert m.refused(ret, update) == DENIED, t
    ok = m.refused(
        ret,
        "INSERT INTO audit_log (actor, action, at, prev_hash, row_hash)"
        " VALUES ('system', 'audit.checkpoint', now(), %s, %s)",
        ("0" * 64, "1" * 64),
    )
    assert ok is None


def test_sequence_usage_only_on_the_audit_sequence(ret: m.Conn) -> None:
    seqs = [
        str(r[0])
        for r in ret.execute(
            # pg_class, not information_schema (which lists only the
            # sequences the caller already has a right on)
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n"
            " ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
            " AND c.relkind = 'S' ORDER BY 1"
        ).fetchall()
    ]
    assert "audit_log_audit_id_seq" in seqs and len(seqs) > 1
    for s in seqs:
        got = m.refused(ret, "SELECT nextval(CAST(%s AS regclass))", (s,))
        assert got == (None if s == "audit_log_audit_id_seq" else DENIED), s


# ------------------------------------------------------------ CHK-M11-152


@pytest.mark.parametrize(
    "clause",
    [
        "FOR UPDATE",
        "FOR UPDATE SKIP LOCKED",
        "FOR NO KEY UPDATE",
        "FOR SHARE",
        "FOR KEY SHARE",
    ],
)
def test_no_row_lock_on_scan(ret: m.Conn, clause: str) -> None:
    """Lead's correction (b), 2026-11-08: the plan's locking scan chunk is
    refused as bitscan_retention, so a reintroduced FOR UPDATE turns red."""
    statement = sql.SQL(
        "SELECT scan_id FROM scan WHERE created_at < now()"
        " ORDER BY created_at, scan_id LIMIT 100 {}"
    ).format(sql.SQL(clause))
    assert m.refused(ret, statement) == DENIED
    assert (
        m.refused(
            ret,
            "SELECT scan_id FROM scan WHERE created_at < now()"
            " ORDER BY created_at, scan_id LIMIT 100",
        )
        is None
    )


# ------------------------------------------------------------ CHK-M11-153


def test_a_new_partition(server: PgServer, ret: m.Conn) -> None:
    """A scan_result partition created after the migration (as owner): its
    rows are deleted by bitscan_retention through the parent and readable;
    bitscan_app can delete them through neither the parent, the default
    partition nor the new partition."""
    at = datetime(2099, 1, 15, 12, tzinfo=UTC)
    with m.owner(server) as c:
        part = m.ensure_partition(c, at)
        pol = m.make_policy(c, 1)
        a = m.host(c, at=at)
        sid = m.scan(c, pol, [a.agent_id], created_at=at)
        jr = m.job(c, sid, a.agent_id, pol, state="completed", created_at=at)
        m.result(c, jr, pol, pol.plugins[0], at=at + timedelta(minutes=5))
        where = c.execute(
            "SELECT tableoid::regclass::text FROM scan_result WHERE job_id = %s",
            (jr.job_id,),
        ).fetchone()
        assert where == (part,)
    with ret.transaction(force_rollback=True):
        gone = ret.execute(
            "DELETE FROM scan_result WHERE job_id = %s", (jr.job_id,)
        ).rowcount
        assert gone == 1
    assert (
        m.refused(ret, sql.SQL("SELECT count(*) FROM {}").format(ident(part))) is None
    )
    with server.connect("bitscan_app") as app:
        for target in ("scan_result", "scan_result_default", part):
            stmt = sql.SQL("DELETE FROM {} WHERE job_id = %s").format(ident(target))
            assert m.refused(app, stmt, (jr.job_id,)) == DENIED, target
            upd = sql.SQL("UPDATE {} SET eval_code = 0 WHERE job_id = %s").format(
                ident(target)
            )
            assert m.refused(app, upd, (jr.job_id,)) == DENIED, target
    with m.owner(server) as c:
        assert c.execute(
            "SELECT count(*) FROM scan_result WHERE job_id = %s", (jr.job_id,)
        ).fetchone() == (1,)


# ------------------------------------------------------------ CHK-M11-154


def test_no_ddl(server: PgServer, ret: m.Conn) -> None:
    with m.owner(server) as c:
        part = m.ensure_partition(c, datetime(2098, 6, 15, tzinfo=UTC))
    for statement in (
        sql.SQL("DROP TABLE {}").format(ident(part)),
        sql.SQL("ALTER TABLE scan_result DETACH PARTITION {}").format(ident(part)),
        sql.SQL("TRUNCATE scan"),
        sql.SQL("TRUNCATE audit_log"),
        sql.SQL("TRUNCATE {}").format(ident(part)),
        sql.SQL("ALTER TABLE scan ADD COLUMN m11_probe int"),
        sql.SQL("CREATE TABLE m11_probe (i int)"),
        sql.SQL("CREATE INDEX m11_probe_ix ON scan_result_reeval (job_id)"),
    ):
        got = m.refused(ret, statement)
        assert got == DENIED, (statement.as_string(ret), got)
    with m.owner(server) as c:
        assert c.execute("SELECT to_regclass(%s)", (part,)).fetchone() == (part,)


def test_probe_connection_is_not_a_superuser(server: PgServer) -> None:
    with server.connect("bitscan_retention") as c:
        row = c.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles"
            " WHERE rolname = current_user"
        ).fetchone()
    assert row == (False, False, False, False)
