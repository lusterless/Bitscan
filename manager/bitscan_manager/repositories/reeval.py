"""Re-evaluation SQL (TS §4.5 L601, §5.2 L929–L938; design note D4).
Parameterised statements only.

Each function runs in the caller's transaction and never commits. bitscan_app
needs SELECT on scan, scan_job, scan_result, policy, policy_plugin and plugin,
INSERT on scan_result_reeval and USAGE on its sequence. Nothing here updates,
deletes or row-locks anything: original results never change (TS §5.2
L1005–L1006).
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

import psycopg

type Conn = psycopg.Connection[Any]

CHUNK: Final = 1000  # REQ-201: read and insert at most 1,000 results at a time


@dataclass(frozen=True, slots=True)
class ScanRef:
    scan_id: UUID
    policy_id: int
    policy_version: int  # the version the scan was built from


@dataclass(frozen=True, slots=True)
class Definitions:
    policy_version: int  # policy.version now
    deleted: bool  # policy.deleted_at IS NOT NULL
    # plugin_uuid -> (operator, expected_result), for each plugin the current
    # version lists (a policy_plugin row)
    plugins: Mapping[UUID, tuple[str, str]]


@dataclass(frozen=True, slots=True)
class StoredResult:
    job_id: UUID
    plugin_uuid: UUID
    stdout: str | None  # NULL is kept: re-evaluation fails it closed (decisions)
    exit_code: int | None
    timed_out: bool
    truncated: bool
    eval_code: int  # the original code
    eval_detail: str | None  # the original detail (intake details are kept, #12)


@dataclass(frozen=True, slots=True)
class ReevalInsert:
    job_id: UUID
    plugin_uuid: UUID
    eval_code: int
    eval_detail: str | None


def lock_scan(conn: Conn, scan_id: UUID) -> ScanRef | None:
    """Take the per-scan re-evaluation lock, then read the scan; None for an
    unknown scan. The lock is transaction-level (#118 (h)): it is released at
    commit or rollback, and it blocks neither intake nor scan state updates."""
    if conn.autocommit:  # the lock would end with this statement
        raise RuntimeError("lock_scan needs a transaction, not autocommit")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('scan_reeval'),"
        " hashtext(CAST(CAST(%(scan_id)s AS uuid) AS text)))",
        {"scan_id": scan_id},
    )
    row = conn.execute(
        "SELECT scan_id, policy_id, policy_version FROM scan"
        " WHERE scan_id = %(scan_id)s",
        {"scan_id": scan_id},
    ).fetchone()
    return None if row is None else ScanRef(UUID(str(row[0])), int(row[1]), int(row[2]))


def current_definitions(conn: Conn, policy_id: int) -> Definitions | None:
    """The policy's version, deleted flag and listed plugins' Operator and
    ExpectedResult in one statement, so under READ COMMITTED they come from one
    snapshot even while an import of the policy commits (#118 (f)). None when
    the policy row does not exist."""
    rows = conn.execute(
        "SELECT p.version, p.deleted_at IS NOT NULL, pl.plugin_uuid,"
        " CAST(pl.operator AS text), pl.expected_result FROM policy p"
        " LEFT JOIN (policy_plugin pp JOIN plugin pl"
        " ON pl.plugin_uuid = pp.plugin_uuid) ON pp.policy_id = p.policy_id"
        " WHERE p.policy_id = %(policy_id)s",
        {"policy_id": policy_id},
    ).fetchall()
    if not rows:
        return None
    plugins = {
        UUID(str(r[2])): (str(r[3]), str(r[4])) for r in rows if r[2] is not None
    }
    return Definitions(int(rows[0][0]), bool(rows[0][1]), MappingProxyType(plugins))


_STORED: Final = (
    "SELECT r.job_id, r.plugin_uuid, r.stdout, r.exit_code, r.timed_out,"
    " r.truncated, r.eval_code, r.eval_detail FROM scan_job j JOIN scan_result r"
    " ON r.job_id = j.job_id AND r.job_created_at = j.created_at"
    " WHERE j.scan_id = %(scan_id)s AND j.kind = 'compliance'"
    " ORDER BY r.job_id, r.plugin_uuid"
)


def stored_results(
    conn: Conn, scan_id: UUID, *, chunk: int = CHUNK
) -> Iterator[list[StoredResult]]:
    """The scan's results (original jobs and retries) in lists of at most
    chunk, through a server-side cursor, so memory is bounded by the chunk
    (REQ-201 (4)). Consume it inside the transaction."""
    if chunk < 1:
        raise ValueError("chunk must be at least 1")
    with conn.cursor(name="reeval_results") as cur:
        cur.itersize = chunk
        cur.execute(_STORED, {"scan_id": scan_id})
        while rows := cur.fetchmany(chunk):
            yield [
                StoredResult(
                    job_id=UUID(str(r[0])),
                    plugin_uuid=UUID(str(r[1])),
                    stdout=None if r[2] is None else str(r[2]),
                    exit_code=None if r[3] is None else int(r[3]),
                    timed_out=bool(r[4]),
                    truncated=bool(r[5]),
                    eval_code=int(r[6]),
                    eval_detail=None if r[7] is None else str(r[7]),
                )
                for r in rows
            ]


def insert_reevals(
    conn: Conn,
    rows: Sequence[ReevalInsert],
    *,
    policy_version: int,
    reevaluated_by: int,
) -> int:
    """Add one scan_result_reeval row per item in one statement; returns the
    number added. reevaluated_at keeps its default, now()."""
    if not rows:
        return 0
    params = {
        "jobs": [r.job_id for r in rows],
        "plugins": [r.plugin_uuid for r in rows],
        "codes": [r.eval_code for r in rows],
        "details": [r.eval_detail for r in rows],
        "v": policy_version,
        "by": reevaluated_by,
    }
    return conn.execute(
        "INSERT INTO scan_result_reeval (job_id, plugin_uuid, policy_version,"
        " eval_code, eval_detail, reevaluated_by) SELECT t.j, t.p, %(v)s, t.c,"
        " t.d, %(by)s FROM unnest(CAST(%(jobs)s AS uuid[]),"
        " CAST(%(plugins)s AS uuid[]), CAST(%(codes)s AS smallint[]),"
        " CAST(%(details)s AS text[])) AS t(j, p, c, d)",
        params,
    ).rowcount
