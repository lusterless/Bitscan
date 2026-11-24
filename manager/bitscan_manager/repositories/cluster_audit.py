"""SQL for cluster_audit jobs: the one kubeconfig fetch and the ClusterMAX
files (TS §3.8, §5.2, §6.1; owner decision 2026-11-23). Parameterised
statements only; runs inside the caller's transaction. bitscan_app has
INSERT (never UPDATE or DELETE) on kubeconfig_fetch and scan_file.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import psycopg

type Conn = psycopg.Connection[Any]

FILE_NAMES: Final = ("report.txt", "run.log", "audit.out", "audit.values.json")


@dataclass(frozen=True)
class ClusterJob:
    job_id: UUID
    kind: str
    state: str
    dispatched_at: datetime | None
    scan_id: UUID
    kubeconfig_id: int | None


def job_for_agent(conn: Conn, job_id: UUID, agent_id: UUID) -> ClusterJob | None:
    """The job only if it is addressed to agent_id, with its scan's kubeconfig
    choice (scan.clustermax), locked for this transaction."""
    row = conn.execute(
        "SELECT j.job_id, j.kind, j.state::text, j.dispatched_at, j.scan_id,"
        " CAST(s.clustermax ->> 'kubeconfig_id' AS bigint) FROM scan_job j"
        " JOIN scan s ON s.scan_id = j.scan_id"
        " WHERE j.job_id = %s AND j.agent_id = %s FOR UPDATE OF j",
        (job_id, agent_id),
    ).fetchone()
    if row is None:
        return None
    return ClusterJob(
        UUID(str(row[0])), str(row[1]), str(row[2]), row[3], UUID(str(row[4])), row[5]
    )


def kubeconfig_secret(conn: Conn, kubeconfig_id: int) -> tuple[str, str] | None:
    """(name, content_enc) of a kubeconfig that is not deleted."""
    row = conn.execute(
        "SELECT name, content_enc FROM kubeconfig WHERE kubeconfig_id = %s"
        " AND deleted_at IS NULL AND content_enc <> ''",
        (kubeconfig_id,),
    ).fetchone()
    return None if row is None else (str(row[0]), str(row[1]))


def insert_fetch(
    conn: Conn, job_id: UUID, kubeconfig_id: int, source_ip: str, now: datetime
) -> bool:
    """True only for the job's first fetch (the primary key keeps it once)."""
    return (
        conn.execute(
            "INSERT INTO kubeconfig_fetch (job_id, kubeconfig_id, fetched_at,"
            " source_ip) VALUES (%s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING",
            (job_id, kubeconfig_id, now, source_ip),
        ).rowcount
        == 1
    )


def insert_file(
    conn: Conn,
    *,
    job_id: UUID,
    name: str,
    size_bytes: int,
    sha256: str,
    truncated: bool,
    content_gz: bytes,
    now: datetime,
) -> bool:
    """True only for the first upload of this name for this job."""
    return (
        conn.execute(
            "INSERT INTO scan_file (job_id, name, size_bytes, sha256, truncated,"
            " content_gz, received_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (job_id, name) DO NOTHING",
            (job_id, name, size_bytes, sha256, truncated, content_gz, now),
        ).rowcount
        == 1
    )


@dataclass(frozen=True)
class FileRow:
    job_id: UUID
    agent_id: UUID
    name: str
    size_bytes: int
    sha256: str
    truncated: bool
    received_at: datetime


def files_of_scan(conn: Conn, scan_id: UUID) -> list[FileRow] | None:
    """The scan's files (no content), or None when the scan does not exist."""
    if (
        conn.execute("SELECT 1 FROM scan WHERE scan_id = %s", (scan_id,)).fetchone()
        is None
    ):
        return None
    rows = conn.execute(
        "SELECT f.job_id, j.agent_id, f.name, f.size_bytes, f.sha256, f.truncated,"
        " f.received_at FROM scan_file f JOIN scan_job j ON j.job_id = f.job_id"
        " WHERE j.scan_id = %s ORDER BY j.agent_id, f.job_id, f.name",
        (scan_id,),
    ).fetchall()
    return [
        FileRow(
            UUID(str(r[0])),
            UUID(str(r[1])),
            str(r[2]),
            int(r[3]),
            str(r[4]),
            bool(r[5]),
            r[6],
        )
        for r in rows
    ]


def file_content(conn: Conn, scan_id: UUID, job_id: UUID, name: str) -> bytes | None:
    row = conn.execute(
        "SELECT f.content_gz FROM scan_file f JOIN scan_job j ON j.job_id = f.job_id"
        " WHERE j.scan_id = %s AND f.job_id = %s AND f.name = %s",
        (scan_id, job_id, name),
    ).fetchone()
    return None if row is None else bytes(row[0])
