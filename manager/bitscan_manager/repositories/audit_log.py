"""audit_log SQL (TS §5.2, §5.3). Parameterised statements only."""

from collections.abc import Generator
from typing import Any

import psycopg
from psycopg import IsolationLevel, sql
from psycopg.pq import TransactionStatus


class AuditError(Exception):
    """The audit append or chain read was refused before anything was done."""


def _utc_text(moment: sql.Composable) -> sql.Composed:
    """YYYY-MM-DDTHH:MM:SS.ffffffZ in UTC, rendered by the server (#38)."""
    return sql.SQL(
        """to_char({} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')"""
    ).format(moment)


# Same text form in allocate() (of now()) and in iter_entries() (of at).
AT_TEXT = _utc_text(sql.SQL("now()"))

# (audit_id, actor, action, target, detail_text, at_text, prev_hash, row_hash)
ChainRow = tuple[int, str, str, str | None, str | None, str, str, str]

_READ_CHAIN = sql.SQL(
    "SELECT audit_id, actor, action, target, detail::text, {}, prev_hash, row_hash"
    " FROM audit_log ORDER BY audit_id"
).format(_utc_text(sql.Identifier("at")))


_TAIL = sql.SQL(
    "SELECT audit_id, actor, action, target, detail::text, {}, prev_hash, row_hash"
    " FROM audit_log WHERE audit_id > %s ORDER BY audit_id LIMIT %s"
).format(_utc_text(sql.Identifier("at")))


def entries_after(
    conn: psycopg.Connection[Any], audit_id: int, limit: int
) -> list[ChainRow]:
    """Committed rows after audit_id, in id order, in the text form that was
    hashed. Appends hold the chain lock until commit, so ids commit in order
    and reading past a cursor never skips a later-committed lower id."""
    rows = conn.execute(_TAIL, (audit_id, limit)).fetchall()
    return [
        (
            int(r[0]),
            str(r[1]),
            str(r[2]),
            None if r[3] is None else str(r[3]),
            None if r[4] is None else str(r[4]),
            str(r[5]),
            str(r[6]),
            str(r[7]),
        )
        for r in rows
    ]


class PgAuditRepo:
    """AuditRepo over one psycopg connection, inside the caller's transaction."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def _check_transaction(self) -> None:
        # In autocommit the xact lock ends with each statement; in REPEATABLE
        # READ or SERIALIZABLE a writer that waited would not see the entry it
        # waited for. Either way the chain could fork.
        if self._conn.autocommit:
            raise AuditError("audit append needs a transaction, not autocommit")
        level = self._conn.isolation_level
        if level is not None and level != IsolationLevel.READ_COMMITTED:
            raise AuditError("audit append needs READ COMMITTED isolation")
        row = self._conn.execute("SHOW transaction_isolation").fetchone()
        if row is None or row[0] != "read committed":
            raise AuditError("audit append needs READ COMMITTED isolation")

    def lock_chain(self) -> None:
        self._check_transaction()
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")

    def head_row_hash(self) -> str | None:
        row = self._conn.execute(
            "SELECT row_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1"
        ).fetchone()
        return None if row is None else str(row[0])

    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]:
        row = self._conn.execute(
            sql.SQL(
                "SELECT nextval('audit_log_audit_id_seq'), {}, CAST(%s AS jsonb)::text"
            ).format(AT_TEXT),
            (detail_json,),
        ).fetchone()
        if row is None:
            raise AuditError("could not allocate an audit_log id")
        return int(row[0]), str(row[1]), None if row[2] is None else str(row[2])

    def insert(
        self,
        audit_id: int,
        actor: str,
        action: str,
        target: str | None,
        detail_text: str | None,
        at_text: str,
        prev_hash: str,
        row_hash: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_log"
            " (audit_id, actor, action, target, detail, at, prev_hash, row_hash)"
            " VALUES (%s, %s, %s, %s, CAST(%s AS jsonb), CAST(%s AS timestamptz),"
            " %s, %s)",
            (
                audit_id,
                actor,
                action,
                target,
                detail_text,
                at_text,
                prev_hash,
                row_hash,
            ),
        )


def iter_entries(conn: psycopg.Connection[Any]) -> Generator[ChainRow, None, None]:
    """Yield audit_log rows in audit_id order from one REPEATABLE READ, READ ONLY
    snapshot, so appends made during the walk are not seen.

    The connection must have no open transaction. Close the generator (or
    exhaust it) to end the read-only transaction.
    """
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise AuditError("audit chain read needs a connection with no open transaction")
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with conn.cursor(name="audit_chain_read") as cur:
            cur.itersize = 1000
            cur.execute(_READ_CHAIN)
            for row in cur:
                yield (
                    int(row[0]),
                    str(row[1]),
                    str(row[2]),
                    None if row[3] is None else str(row[3]),
                    None if row[4] is None else str(row[4]),
                    str(row[5]),
                    str(row[6]),
                    str(row[7]),
                )
