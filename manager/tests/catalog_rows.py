"""Catalog test rows for the M7 repository and importer suites (tester-owned).

Values the app may write are built through the product repositories under
test; rows the app can never write (agents, scans, jobs, schedules, and
deliberate corruption) are written as owner (``bitscan_migrate`` +
``SET ROLE bitscan_owner``), never as a superuser.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from .conftest import PgServer

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 27, 12, 0, 0, 123450, tzinfo=UTC)  # trailing-zero µs on purpose
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)


def sha(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def tag() -> str:
    return secrets.token_hex(4)


@contextmanager
def owner(server: PgServer) -> Iterator[Conn]:
    with server.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        yield conn


@contextmanager
def app(server: PgServer) -> Iterator[Conn]:
    with server.connect("bitscan_app") as conn:
        row = conn.execute(
            "SELECT session_user::text, rolsuper FROM pg_roles"
            " WHERE rolname = session_user"
        ).fetchone()
        assert row == ("bitscan_app", False), row
        yield conn


def checksum(conn: Conn, table: str, key: str) -> str:
    """md5 over every row of a table in key order (read as owner or app)."""
    allowed = {
        "family": "family_id",
        "policy": "policy_id",
        "plugin": "plugin_uuid",
        "policy_plugin": "policy_id, plugin_uuid",
        "bit_import": "import_id",
        "task": "task_id",
        "scan": "scan_id",
        "scan_job": "job_id",
        "scan_schedule": "schedule_id",
        "agent": "agent_id",
        "audit_log": "audit_id",
    }
    assert allowed[table] == key, (table, key)
    from psycopg import sql

    query = sql.SQL(
        "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY {k}), '')) FROM {t} t"
    ).format(k=sql.SQL(key), t=sql.Identifier(table))
    row = conn.execute(query).fetchone()
    assert row is not None
    return str(row[0])


CATALOG = {
    "family": "family_id",
    "policy": "policy_id",
    "plugin": "plugin_uuid",
    "policy_plugin": "policy_id, plugin_uuid",
}


def catalog_checksums(conn: Conn) -> dict[str, str]:
    return {t: checksum(conn, t, k) for t, k in CATALOG.items()}


@dataclass(frozen=True)
class Fixture:
    policy_id: int
    scan_id: UUID
    jobs: dict[str, UUID]  # state -> job_id
    schedules: list[int]


def agent(conn: Conn) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at) VALUES (%s, 'h', 'v', %s, now(), now())"
        " RETURNING agent_id",
        (secrets.token_hex(16), secrets.token_hex(32)),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def scan_with_jobs(
    conn: Conn, policy_id: int, agent_id: UUID, states: Sequence[str]
) -> tuple[UUID, dict[str, UUID]]:
    """A scan of the policy with one compliance job per state (as owner)."""
    scan = conn.execute(
        "INSERT INTO scan (policy_id, policy_version, trigger, target)"
        " VALUES (%s, 1, 'manual', %s) RETURNING scan_id",
        (policy_id, Jsonb({"all": True})),
    ).fetchone()
    assert scan is not None
    jobs: dict[str, UUID] = {}
    for state in states:
        jid = uuid4()
        conn.execute(
            "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, state, payload,"
            " eval_spec, pickup_by) VALUES (%s, 'compliance', %s, %s, %s, %s, %s,"
            " now() + interval '1 day')",
            (jid, scan[0], agent_id, state, Jsonb({"job_id": str(jid)}), Jsonb([])),
        )
        jobs[state] = jid
    return UUID(str(scan[0])), jobs


def schedule(conn: Conn, policy_id: int, enabled: bool = True) -> int:
    row = conn.execute(
        "INSERT INTO scan_schedule (name, policy_id, target, cron, enabled,"
        " created_by) VALUES (%s, %s, %s, '0 * * * *', %s, 1) RETURNING schedule_id",
        (f"s-{tag()}", policy_id, Jsonb({"all": True}), enabled),
    ).fetchone()
    assert row is not None
    return int(row[0])
