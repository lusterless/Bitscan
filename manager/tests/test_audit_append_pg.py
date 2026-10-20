"""REQ-030 on PostgreSQL: audit append (TP-M1-14 pg; G23).

Checks CHK-M1-203 to CHK-M1-209. Each test gets a container of its own (the
chain must start empty) migrated through the CLI. Rows are re-hashed with the
independent #38 reference from test_audit_chain, reading ``detail::text`` and
the UTC ``at`` text from the server.
"""

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import IsolationLevel, sql

from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.audit import AuditError, append_entry

from .conftest import Conn, PgServer, run_cli, write_dsn_file
from .test_audit_chain import GENESIS, reference

# The #38 at_text, read back from the stored row (fixed SQL text, no parameters).
ROWS = (
    "SELECT audit_id, actor, action, target, detail::text,"
    " to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
    " prev_hash, row_hash FROM audit_log ORDER BY audit_id"
)
NOW_UTC = (
    "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
)


@pytest.fixture
def db(fresh_pg_server: PgServer, tmp_path: Path) -> PgServer:
    env = {
        "BITSCAN_MIGRATE_DSN_FILE": str(
            write_dsn_file(tmp_path, "m", fresh_pg_server.dsn("bitscan_migrate"))
        )
    }
    proc = run_cli(["db", "migrate"], env)
    assert proc.returncode == 0, proc.stderr
    return fresh_pg_server


def tx_conn(server: PgServer, role: str = "bitscan_app") -> Conn:
    return psycopg.connect(server.dsn(role), autocommit=False)


def append(conn: Conn, **kw: Any) -> Any:
    entry = append_entry(PgAuditRepo(conn), **kw)
    conn.commit()
    return entry


def rows(server: PgServer) -> list[tuple[Any, ...]]:
    with server.connect("bitscan_migrate") as c:
        return [tuple(r) for r in c.execute(ROWS).fetchall()]


def assert_one_chain(server: PgServer, n: int) -> None:
    got = rows(server)
    assert len(got) == n
    prev = GENESIS
    for audit_id, actor, action, target, detail, at, p, h in got:
        assert p == prev, f"broken link at {audit_id}"
        assert h == reference(p, audit_id, actor, action, target, detail, at), audit_id
        prev = h
    assert len({r[6] for r in got}) == n  # no two entries share a prev_hash


# --- (1) a chain of N appends ---


@pytest.mark.pg
def test_appends_form_one_chain_with_server_time_and_canonical_detail(
    db: PgServer,
) -> None:
    detail = {
        "z": 1,
        "a": {"y": [1, 2.50, "x"], "b": None},
        "u": "na" + chr(0xEF) + "ve",
        "big": 10**20,
        "e": 1e2,
    }
    with tx_conn(db) as conn:
        first = append(
            conn, actor="alice", action="policy.import", target="cis.bit", detail=detail
        )
        append(conn, actor="system", action="scan.create")
        append(conn, actor="bob", action="x", target="", detail={})
    assert first.prev_hash == GENESIS
    assert_one_chain(db, 3)
    stored = rows(db)
    with db.connect("bitscan_migrate") as c:
        canonical = c.execute(
            "SELECT CAST(%s AS jsonb)::text", (json.dumps(detail),)
        ).fetchone()
    assert canonical is not None and stored[0][4] == canonical[0]  # jsonb's own text
    assert stored[0][4].index('"a"') < stored[0][4].index('"z"')  # jsonb key order
    assert "na" + chr(0xEF) + "ve" in stored[0][4]  # unicode kept, not escaped
    assert stored[0][5] == first.at_text and first.at_text.endswith("Z")
    assert (stored[1][3], stored[1][4]) == (None, None)
    assert (stored[2][3], stored[2][4]) == ("", "{}")
    with db.connect("bitscan_migrate") as c:
        utc = c.execute(NOW_UTC).fetchone()
    assert utc is not None and stored[0][5][:10] == utc[0][:10]


# --- (2) concurrency ---


@pytest.mark.pg
def test_eight_concurrent_writers_keep_one_chain(db: PgServer) -> None:
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def writer(n: int) -> None:
        try:
            with tx_conn(db) as conn:
                start.wait()
                for i in range(25):
                    append(conn, actor=f"w{n}", action="t.write", detail={"i": i})
        except BaseException as exc:  # noqa: BLE001  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)
    assert errors == []
    assert_one_chain(db, 200)


# --- (3) the lock: a held append blocks the next ---


@pytest.mark.pg
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
def test_held_append_blocks_the_next_writer(db: PgServer, outcome: str) -> None:
    with tx_conn(db) as base:
        append(base, actor="a", action="seed")
    holder = tx_conn(db)
    append_entry(PgAuditRepo(holder), actor="holder", action="held")
    done = threading.Event()

    def second() -> None:
        with tx_conn(db) as c:
            append(c, actor="second", action="after")
        done.set()

    t = threading.Thread(target=second)
    t.start()
    waited = False
    with db.connect("bitscan_migrate") as watch:
        for _ in range(100):
            row = watch.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                " AND NOT granted"
            ).fetchone()
            if row and row[0] > 0:
                waited = True
                break
            time.sleep(0.05)
    assert waited, "second writer did not wait on the advisory lock"
    assert not done.is_set()
    if outcome == "commit":
        holder.commit()
    else:
        holder.rollback()
    holder.close()
    t.join(timeout=60)
    assert done.is_set()
    got = rows(db)
    actions = [r[2] for r in got]
    assert actions == (
        ["seed", "held", "after"] if outcome == "commit" else ["seed", "after"]
    )
    assert_one_chain(db, len(got))


# --- (4) roles ---


@pytest.mark.pg
@pytest.mark.parametrize("role", ["bitscan_app", "bitscan_retention"])
def test_app_and_retention_can_append_without_update_or_delete(
    db: PgServer, role: str
) -> None:
    with tx_conn(db, role) as conn:
        append(
            conn,
            actor="system",
            action="audit.checkpoint" if role.endswith("n") else "x",
            detail={"last_deleted_id": 0, "last_deleted_row_hash": GENESIS},
        )
        for stmt in (
            "UPDATE audit_log SET actor = actor",
            "DELETE FROM audit_log WHERE false",
            "TRUNCATE audit_log",
        ):
            if role == "bitscan_retention" and stmt.startswith("DELETE"):
                continue  # retention may delete expired entries (TS §5.2 L1001)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)
            conn.rollback()
    assert_one_chain(db, 1)


# --- (5) isolation and autocommit are refused before the insert ---


@pytest.mark.pg
@pytest.mark.parametrize(
    "level", [IsolationLevel.REPEATABLE_READ, IsolationLevel.SERIALIZABLE]
)
def test_connection_isolation_other_than_read_committed_is_refused(
    db: PgServer, level: IsolationLevel
) -> None:
    with tx_conn(db) as conn:
        conn.isolation_level = level  # psycopg sets it per connection, not in connect()
        with pytest.raises(AuditError):
            append_entry(PgAuditRepo(conn), actor="a", action="x")
        conn.rollback()
    assert rows(db) == []


@pytest.mark.pg
def test_autocommit_is_refused(db: PgServer) -> None:
    with db.connect("bitscan_app") as conn:  # autocommit=True
        with pytest.raises(AuditError):
            append_entry(PgAuditRepo(conn), actor="a", action="x")
    assert rows(db) == []


@pytest.mark.pg
@pytest.mark.parametrize("default", ["repeatable read", "serializable"])
def test_session_default_isolation_is_refused(db: PgServer, default: str) -> None:
    """A server or role default the driver does not know about (SHOW check)."""
    with tx_conn(db) as conn:
        conn.execute(
            sql.SQL("SET default_transaction_isolation = {}").format(
                sql.Literal(default)
            )
        )
        conn.commit()
        with pytest.raises(AuditError):
            append_entry(PgAuditRepo(conn), actor="a", action="x")
        conn.rollback()
    assert rows(db) == []


# --- (6) column limits ---


@pytest.mark.pg
@pytest.mark.parametrize(
    ("field", "limit"), [("actor", 128), ("action", 64), ("target", 255)]
)
def test_values_over_the_column_limits_insert_nothing(
    db: PgServer, field: str, limit: int
) -> None:
    def values(length: int) -> dict[str, Any]:
        base: dict[str, Any] = {"actor": "a", "action": "x", "target": None}
        return base | {field: "y" * length}

    with tx_conn(db) as conn:
        append(conn, **values(limit))  # at the limit: accepted
        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            append_entry(PgAuditRepo(conn), **values(limit + 1))
        conn.rollback()
    assert_one_chain(db, 1)
    assert len(rows(db)[0][{"actor": 1, "action": 2, "target": 3}[field]]) == limit


# --- (7) nothing printed or logged ---


@pytest.mark.pg
def test_append_prints_and_logs_nothing(
    db: PgServer, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    secret = f"DETAIL-{secrets.token_hex(6)}"
    with tx_conn(db) as conn:
        append(conn, actor="a", action="x", detail={"note": secret})
    out = capsys.readouterr()
    assert secret not in out.out + out.err + caplog.text


@pytest.mark.pg
def test_rolled_back_append_leaves_a_gap_that_does_not_break_the_chain(
    db: PgServer,
) -> None:
    from bitscan_manager.services.audit.verify import StoredEntry, verify_rows

    with tx_conn(db) as conn:
        append(conn, actor="a", action="one")
        append_entry(PgAuditRepo(conn), actor="a", action="rolled back")
        conn.rollback()
        append(conn, actor="a", action="two")
    got = rows(db)
    assert [r[2] for r in got] == ["one", "two"]
    assert got[1][0] - got[0][0] == 2  # the rolled-back id left a gap
    assert_one_chain(db, 2)
    res = verify_rows([StoredEntry(*r) for r in got])
    assert res.ok and res.checked == 2
