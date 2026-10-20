"""REQ-022: schema part 2, fleet and inventory (TP-M1-06).

Checks CHK-M1-080 to CHK-M1-084. Written from TS §5.2 L709-L825 before reading
the migration. Behaviour cases run as bitscan_owner in a transaction that is
always rolled back, with a savepoint per statement.
"""

import secrets
import uuid
from collections.abc import Iterator
from typing import Any, LiteralString

import psycopg
import pytest

from .conftest import REFERENCE_DB, Conn, PgServer
from .schema_diff import Scope, diff, dump

FLEET = Scope.of(
    tables=(
        "agent",
        "agent_ip_seen",
        "agent_tag",
        "enrollment_token",
        "enrollment_request",
        "os_info",
        "package",
        "agent_package",
        "inventory_snapshot",
    ),
    types=("agent_status",),
)
STATUSES = [
    "awaiting_approval",
    "enrolled",
    "online",
    "stale",
    "offline",
    "decommissioned",
]


def h64() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def fl(migrated_db: PgServer, owner_conn: Conn) -> Iterator[Conn]:
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


def agent(conn: Conn) -> uuid.UUID:
    return uuid.UUID(
        str(
            one(
                conn,
                "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
                " token_issued_at, token_expires_at)"
                " VALUES (%s, 'h1', '0.1.0', %s, now(),"
                " now() + interval '365 days') RETURNING agent_id",
                (secrets.token_hex(16), h64()),
            )
        )
    )


def enrol_token(conn: Conn, **cols: Any) -> int:
    values = {"token_hash": h64(), "expires_at": "2099-01-01", "created_by": 1} | cols
    names = list(values)
    from psycopg import sql

    q = sql.SQL(
        "INSERT INTO enrollment_token ({}) VALUES ({}) RETURNING token_id"
    ).format(
        sql.SQL(", ").join(map(sql.Identifier, names)),
        sql.SQL(", ").join(sql.Placeholder() * len(names)),
    )
    row = conn.execute(q, list(values.values())).fetchone()
    assert row is not None
    return int(row[0])


def request(conn: Conn, agent_id: uuid.UUID, token_id: int, **cols: Any) -> None:
    values = {
        "kind": "new",
        "agent_id": agent_id,
        "enrollment_token_id": token_id,
        "hostname": "h1",
        "machine_id": secrets.token_hex(16),
        "agent_version": "0.1.0",
        "new_token_hash": h64(),
        "token_expires_at": "2099-01-01",
        "source_ip": "192.0.2.1",
    } | cols
    from psycopg import sql

    q = sql.SQL("INSERT INTO enrollment_request ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    conn.execute(q, list(values.values()))


# --- diff ------------------------------------------------------------------------


@pytest.mark.pg
def test_fleet_and_inventory_are_diff_equal_to_the_spec(
    migrated_db: PgServer, reference_db: PgServer
) -> None:
    with (
        migrated_db.connect("bitscan_migrate") as got,
        reference_db.connect("bitscan_migrate", dbname=REFERENCE_DB) as ref,
    ):
        problems = diff(dump(ref, FLEET), dump(got, FLEET))
    assert problems == [], "\n".join(problems)


# --- tokens are hashes only --------------------------------------------------------


@pytest.mark.pg
def test_token_columns_are_hashes_only(fl: Conn) -> None:
    rows = fl.execute(
        "SELECT c.relname, a.attname,"
        " format_type(a.atttypid, a.atttypmod), a.attnotnull"
        " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0"
        " AND NOT a.attisdropped AND a.attname LIKE '%%token%%'"
    ).fetchall()
    textual = [r for r in rows if r[2].startswith(("character", "text"))]
    assert textual, "no token columns found"
    for table, col, typ, _ in textual:
        assert col.endswith("token_hash"), f"{table}.{col} could hold a raw token"
        assert typ == "character(64)", (table, col, typ)
    for table, col in (
        ("agent", "token_hash"),
        ("enrollment_token", "token_hash"),
        ("enrollment_request", "new_token_hash"),
    ):
        unique = one(
            fl,
            "SELECT count(*) FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid"
            " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(k.conkey)"
            " WHERE c.relname = %s AND a.attname = %s AND k.contype = 'u'"
            " AND array_length(k.conkey, 1) = 1",
            (table, col),
        )
        assert unique == 1, (table, col)
        notnull = [r[3] for r in rows if r[0] == table and r[1] == col]
        assert notnull == [True], (table, col)
    machine = fl.execute(
        "SELECT format_type(atttypid, atttypmod), attnotnull FROM pg_attribute"
        " WHERE attrelid = 'agent'::regclass AND attname = 'machine_id'"
    ).fetchone()
    assert machine == ("character(32)", True)


@pytest.mark.pg
def test_duplicate_hashes_and_machine_ids_are_rejected(fl: Conn) -> None:
    dup = h64()
    q: LiteralString = (
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at) VALUES (%s, 'h', 'v', %s, now(), now())"
    )
    assert state(fl, q, ("a" * 32, dup)) is None
    assert state(fl, q, ("b" * 32, dup)) == "23505"
    assert state(fl, q, ("a" * 32, h64())) == "23505"
    tok = h64()
    enrol_token(fl, token_hash=tok)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with fl.transaction():
            enrol_token(fl, token_hash=tok)
    a = agent(fl)
    t = enrol_token(fl)
    new = h64()
    request(fl, a, t, new_token_hash=new)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with fl.transaction():
            request(fl, a, t, new_token_hash=new)


# --- enrolment tokens ---------------------------------------------------------------


@pytest.mark.pg
def test_enrollment_token_limits_and_defaults(fl: Conn) -> None:
    for bad in (0, 10001):
        with pytest.raises(psycopg.errors.CheckViolation):
            with fl.transaction():
                enrol_token(fl, max_uses=bad)
    for good in (1, 10000):
        enrol_token(fl, max_uses=good)
    tid = enrol_token(fl)
    row = fl.execute(
        "SELECT max_uses, uses, auto_approve, allowed_cidrs, revoked_at"
        " FROM enrollment_token WHERE token_id = %s",
        (tid,),
    ).fetchone()
    assert row == (1, 0, False, None, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        with fl.transaction():
            enrol_token(fl, max_uses=2, uses=3)
    enrol_token(fl, max_uses=2, uses=2)
    with pytest.raises(psycopg.errors.NotNullViolation):
        with fl.transaction():
            enrol_token(fl, expires_at=None)
    assert (
        state(fl, "UPDATE enrollment_token SET uses = 2 WHERE token_id = %s", (tid,))
        == "23514"
    )


# --- agent status, requests, cascades --------------------------------------------


@pytest.mark.pg
def test_agent_status_default_and_labels(fl: Conn) -> None:
    assert one(fl, "SELECT enum_range(NULL::agent_status)::text[]") == STATUSES
    a = agent(fl)
    assert one(fl, "SELECT status::text FROM agent WHERE agent_id = %s", (a,)) == (
        "awaiting_approval"
    )
    row = fl.execute(
        "SELECT runner_helpers, enrolled_at IS NOT NULL, last_heartbeat_at"
        " FROM agent WHERE agent_id = %s",
        (a,),
    ).fetchone()
    assert row == ([], True, None)


@pytest.mark.pg
@pytest.mark.parametrize(
    ("cols", "expected"),
    [
        ({"kind": "new"}, None),
        ({"kind": "reenrol"}, None),
        ({"kind": "renew"}, "23514"),
        ({"kind": "NEW"}, "23514"),
        ({"decision": "approved"}, None),
        ({"decision": "rejected"}, None),
        ({"decision": None}, None),
        ({"decision": "pending"}, "23514"),
    ],
)
def test_enrollment_request_kind_and_decision(
    fl: Conn, cols: dict[str, Any], expected: str | None
) -> None:
    a = agent(fl)
    t = enrol_token(fl)
    try:
        with fl.transaction():
            request(fl, a, t, **cols)
        got = None
    except psycopg.Error as exc:
        got = exc.sqlstate
    assert got == expected


@pytest.mark.pg
def test_agent_delete_restricted_by_requests_and_cascades_the_rest(fl: Conn) -> None:
    a = agent(fl)
    t = enrol_token(fl)
    request(fl, a, t)
    # PostgreSQL reports RESTRICT and NO ACTION alike (23503); confdeltype tells
    # them apart ('r' = RESTRICT).
    assert state(fl, "DELETE FROM agent WHERE agent_id = %s", (a,)) == "23503"
    deltype = one(
        fl,
        "SELECT confdeltype FROM pg_constraint WHERE conrelid = 'enrollment_request'"
        "::regclass AND confrelid = 'agent'::regclass AND contype = 'f'",
    )
    assert deltype == "r"

    b = agent(fl)
    fl.execute("INSERT INTO agent_tag VALUES (%s, 'web')", (b,))
    fl.execute(
        "INSERT INTO agent_ip_seen (agent_id, ip) VALUES (%s, '192.0.2.7')", (b,)
    )
    fl.execute(
        "INSERT INTO os_info (agent_id, raw, collected_at) VALUES (%s, '{}', now())",
        (b,),
    )
    pkg = one(
        fl,
        "INSERT INTO package (name, version, architecture) VALUES"
        " ('openssl', '3.0.13-0ubuntu3', 'amd64') RETURNING package_id",
    )
    fl.execute(
        "INSERT INTO agent_package (agent_id, package_id, status, first_seen_at,"
        " last_seen_at) VALUES (%s, %s, 'install ok installed', now(), now())",
        (b, pkg),
    )
    snap = fl.execute(
        "INSERT INTO inventory_snapshot (agent_id, list_sha256, package_count,"
        " collected_at) VALUES (%s, %s, 1, now()) RETURNING added, removed",
        (b, h64()),
    ).fetchone()
    assert snap == ([], [])
    fl.execute("DELETE FROM agent WHERE agent_id = %s", (b,))
    for table in (
        "agent_tag",
        "agent_ip_seen",
        "os_info",
        "agent_package",
        "inventory_snapshot",
    ):
        from psycopg import sql

        n = fl.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE agent_id = %s").format(
                sql.Identifier(table)
            ),
            (b,),
        ).fetchone()
        assert n == (0,), table
    # package rows are shared, not owned by the agent: they stay (retention task).
    assert one(fl, "SELECT count(*) FROM package WHERE package_id = %s", (pkg,)) == 1


@pytest.mark.pg
def test_package_identity_and_indexes(fl: Conn) -> None:
    q: LiteralString = (
        "INSERT INTO package (name, version, architecture) VALUES (%s, %s, %s)"
    )
    assert state(fl, q, ("bash", "5.2-1", "amd64")) is None
    assert state(fl, q, ("bash", "5.2-1", "amd64")) == "23505"
    assert state(fl, q, ("bash", "5.2-1", "arm64")) is None
    assert state(fl, q, ("bash", "5.2-2", "amd64")) is None
    defs = dict(
        fl.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
            " AND indexname IN ('ix_package_name_debver', 'ix_package_name_trgm',"
            " 'ix_agent_hostname_trgm', 'ix_agent_status', 'ix_agent_package_pkg')"
        ).fetchall()
    )
    assert set(defs) == {
        "ix_package_name_debver",
        "ix_package_name_trgm",
        "ix_agent_hostname_trgm",
        "ix_agent_status",
        "ix_agent_package_pkg",
    }
    assert (
        "USING btree (name, ((version)::debversion))" in defs["ix_package_name_debver"]
    )
    assert "USING gin (name gin_trgm_ops)" in defs["ix_package_name_trgm"]
    assert "USING gin (hostname gin_trgm_ops)" in defs["ix_agent_hostname_trgm"]
    assert "USING btree (status, last_heartbeat_at)" in defs["ix_agent_status"]
    assert "USING btree (package_id)" in defs["ix_agent_package_pkg"]
