"""audit_log retention SQL (TS §5.3 L1049, L1053; #39, #150 (d); plan TASK-242
§3). Parameterised statements only.

Run as bitscan_retention, which may read audit_log, delete from it and insert
the checkpoint entries (TS §5.2 L1002–L1006); bitscan_app is refused the
delete by the grants. Each function runs in the caller's transaction and never
commits. The checkpoint itself is appended through the chain
(services.audit.chain.append_entry), before delete_through, in the same
transaction.
"""

from datetime import datetime
from typing import Any

import psycopg

type Conn = psycopg.Connection[Any]


def oldest(conn: Conn, n: int) -> list[tuple[int, datetime]]:
    """The n oldest entries as (audit_id, at), in ascending id order."""
    if n < 1:
        raise ValueError("n must be at least 1")
    rows = conn.execute(
        "SELECT audit_id, at FROM audit_log ORDER BY audit_id LIMIT %s", (n,)
    ).fetchall()
    result: list[tuple[int, datetime]] = []
    for r in rows:
        at = r[1]
        if not isinstance(at, datetime):
            raise TypeError("audit_log.at is not a timestamp")
        result.append((int(r[0]), at))
    return result


def row_hash(conn: Conn, audit_id: int) -> str:
    """The stored row_hash of one entry; LookupError when it does not exist."""
    row = conn.execute(
        "SELECT row_hash FROM audit_log WHERE audit_id = %s", (audit_id,)
    ).fetchone()
    if row is None:
        raise LookupError("audit entry not found")
    return str(row[0])


def delete_through(conn: Conn, audit_id: int) -> int:
    """Delete every entry with id <= audit_id; returns the number deleted.
    Needs a transaction: the checkpoint and the delete commit together."""
    if conn.autocommit:
        raise RuntimeError("delete_through needs a transaction, not autocommit")
    return conn.execute(
        "DELETE FROM audit_log WHERE audit_id <= %s", (audit_id,)
    ).rowcount
