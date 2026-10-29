"""TP-M8-01: PostgreSQL fixture builder for the M8 evaluator suites
(tester-owned; REQ-198 to REQ-201, REQ-204).

No M8 code writes scans, jobs or results, so this module writes them as owner
(``bitscan_migrate`` + ``SET ROLE bitscan_owner``), never as a superuser, in
the TS §5.2 shapes: a ``scan``; original and retry ``scan_job`` rows whose
payload is the TS §6.5 job body (``plugins: [{plugin_uuid, execute,
timeout_s}]``) and whose ``eval_spec`` is the #117 JSON; ``scan_result`` rows
with ``job_created_at`` equal to the job's ``created_at`` (the trigger checks
it) and the four NOT NULL snapshots; ``scan_result_reeval`` rows with chosen
ids. Plus row checksums and the canary. CHK-M8-140 to -143.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .conftest import PgServer

Conn = psycopg.Connection[Any]
CANARY = "M8CANARY-" + secrets.token_hex(6)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def owner(server: PgServer) -> Iterator[Conn]:
    with server.connect("bitscan_migrate") as conn:
        conn.execute("SET ROLE bitscan_owner")
        yield conn


@contextmanager
def app(server: PgServer, *, autocommit: bool = True) -> Iterator[Conn]:
    with server.connect("bitscan_app") as conn:
        row = conn.execute(
            "SELECT session_user::text, rolsuper FROM pg_roles"
            " WHERE rolname = session_user"
        ).fetchone()
        assert row == ("bitscan_app", False), row
        conn.autocommit = autocommit
        yield conn


# ----- catalog -----------------------------------------------------------------


@dataclass
class Plugin:
    plugin_uuid: UUID
    name: str  # plugin_name
    operator: str
    expected: str
    execute: str = "printf 'x'"
    timeout_s: int = 60


@dataclass
class Policy:
    policy_id: int
    family_id: int
    family_name: str
    version: int
    plugins: list[Plugin] = field(default_factory=list)

    def display(self, p: Plugin) -> str:
        return f"{self.family_name} - {p.name}"


def make_policy(
    conn: Conn,
    plugins: Sequence[tuple[str, str]],
    *,
    status: str = "enabled",
    version: int = 1,
) -> Policy:
    """A family, a policy and one active plugin per (operator, expected),
    each listed in ``policy_plugin`` in order (as owner)."""
    t = secrets.token_hex(4)
    fam = conn.execute(
        "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
        (f"Fam {t}",),
    ).fetchone()
    assert fam is not None
    pol = conn.execute(
        "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
        " version, source_file, source_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " RETURNING policy_id",
        (f"Pol {t}", status, status, fam[0], version, f"m8/{t}.bit", sha(t)),
    ).fetchone()
    assert pol is not None
    policy = Policy(int(pol[0]), int(fam[0]), f"Fam {t}", version)
    for i, (op, expected) in enumerate(plugins):
        p = Plugin(uuid4(), f"{i + 1}.1 - check {t}", op, expected)
        conn.execute(
            "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
            " execute, execute_sha256, operator, expected_result, timeout_s)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s::plugin_operator, %s, %s)",
            (
                p.plugin_uuid,
                policy.family_id,
                policy.policy_id,
                p.name,
                p.execute,
                sha(p.execute),
                p.operator,
                p.expected,
                p.timeout_s,
            ),
        )
        conn.execute(
            "INSERT INTO policy_plugin (policy_id, plugin_uuid, sort_order)"
            " VALUES (%s, %s, %s)",
            (policy.policy_id, p.plugin_uuid, i),
        )
        policy.plugins.append(p)
    return policy


def import_change(
    conn: Conn,
    policy: Policy,
    *,
    expected: dict[UUID, str] | None = None,
    operator: dict[UUID, str] | None = None,
    drop: Sequence[UUID] = (),
) -> int:
    """What an import that edits the policy does, in one transaction (as
    owner): version + 1, changed ExpectedResult / Operator, dropped plugins
    no longer listed (and retired). Returns the new version."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE policy SET version = version + 1, updated_at = now()"
            " WHERE policy_id = %s RETURNING version",
            (policy.policy_id,),
        ).fetchone()
        assert row is not None
        for u, e in (expected or {}).items():
            conn.execute(
                "UPDATE plugin SET expected_result = %s WHERE plugin_uuid = %s", (e, u)
            )
        for u, o in (operator or {}).items():
            conn.execute(
                "UPDATE plugin SET operator = %s::plugin_operator"
                " WHERE plugin_uuid = %s",
                (o, u),
            )
        for u in drop:
            conn.execute(
                "DELETE FROM policy_plugin WHERE policy_id = %s AND plugin_uuid = %s",
                (policy.policy_id, u),
            )
            conn.execute(
                "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s", (u,)
            )
    policy.version = int(row[0])
    return policy.version


def soft_delete(conn: Conn, policy: Policy) -> None:
    conn.execute(
        "UPDATE policy SET deleted_at = now(), source_file = %s WHERE policy_id = %s",
        (f"deleted/{policy.policy_id}", policy.policy_id),
    )


# ----- fleet and scans ---------------------------------------------------------


def make_agent(conn: Conn) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status)"
        " VALUES (%s, %s, '1.0.0', %s, now(), now() + interval '30 days', 'online')"
        " RETURNING agent_id",
        (secrets.token_hex(16), f"host-{secrets.token_hex(3)}", secrets.token_hex(32)),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def make_scan(conn: Conn, policy: Policy, *, version: int | None = None) -> UUID:
    row = conn.execute(
        "INSERT INTO scan (policy_id, policy_version, trigger, target, state)"
        " VALUES (%s, %s, 'manual', %s, 'running') RETURNING scan_id",
        (
            policy.policy_id,
            policy.version if version is None else version,
            Jsonb({"all": True}),
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


@dataclass(frozen=True)
class Job:
    job_id: UUID
    created_at: datetime
    agent_id: UUID
    plugins: tuple[UUID, ...]


def make_job(
    conn: Conn,
    scan_id: UUID,
    agent_id: UUID,
    policy: Policy,
    plugins: Sequence[Plugin],
    *,
    retry_of: UUID | None = None,
    state: str = "running",
    created_at: datetime | None = None,
) -> Job:
    """A compliance job: TS §6.5 payload and #117 eval_spec, in payload order."""
    jid = uuid4()
    payload = {
        "job_id": str(jid),
        "kind": "compliance",
        "plugins": [
            {
                "plugin_uuid": str(p.plugin_uuid),
                "execute": p.execute,
                "timeout_s": p.timeout_s,
            }
            for p in plugins
        ],
    }
    eval_spec = {
        "plugins": [
            {
                "plugin_uuid": str(p.plugin_uuid),
                "name": policy.display(p),
                "operator": p.operator,
                "expected": p.expected,
            }
            for p in plugins
        ]
    }
    row = conn.execute(
        "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, retry_of, state,"
        " payload, eval_spec, created_at, pickup_by)"
        " VALUES (%s, 'compliance', %s, %s, %s, %s, %s, %s, COALESCE(%s, now()),"
        " now() + interval '1 day') RETURNING created_at",
        (
            jid,
            scan_id,
            agent_id,
            retry_of,
            state,
            Jsonb(payload),
            Jsonb(eval_spec),
            created_at,
        ),
    ).fetchone()
    assert row is not None
    return Job(jid, row[0], agent_id, tuple(p.plugin_uuid for p in plugins))


def make_inventory_job(conn: Conn, agent_id: UUID) -> UUID:
    jid = uuid4()
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, agent_id, payload, pickup_by)"
        " VALUES (%s, 'inventory', %s, %s, now() + interval '1 day')",
        (jid, agent_id, Jsonb({"job_id": str(jid), "kind": "inventory"})),
    )
    return jid


def add_result(
    conn: Conn,
    job: Job,
    policy: Policy,
    plugin: Plugin,
    *,
    code: int,
    detail: str | None = None,
    stdout: str | None = "",
    stderr: str | None = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    truncated: bool = False,
) -> None:
    """One scan_result row (as owner) with the snapshots of its job."""
    conn.execute(
        "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
        " eval_detail, exit_code, stdout, stderr, timed_out, truncated,"
        " plugin_name_snap, execute_snap, operator_snap, expected_snap,"
        " started_at, finished_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s::plugin_operator, %s, now(), now())",
        (
            job.job_id,
            job.created_at,
            plugin.plugin_uuid,
            code,
            detail,
            exit_code,
            stdout,
            stderr,
            timed_out,
            truncated,
            policy.display(plugin),
            plugin.execute,
            plugin.operator,
            plugin.expected,
        ),
    )


def reserve_reeval_ids(conn: Conn, n: int = 1000) -> int:
    """A block of n unused reeval_id values: returns the base; the sequence is
    moved past the block so product inserts never collide."""
    row = conn.execute("SELECT nextval('scan_result_reeval_reeval_id_seq')").fetchone()
    assert row is not None
    base = int(row[0])
    conn.execute("SELECT setval('scan_result_reeval_reeval_id_seq', %s)", (base + n,))
    return base


def add_reeval(
    conn: Conn,
    job_id: UUID,
    plugin_uuid: UUID,
    *,
    code: int,
    detail: str | None = None,
    policy_version: int = 1,
    by: int = 1,
    reeval_id: int | None = None,
    at: datetime | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO scan_result_reeval (reeval_id, job_id, plugin_uuid,"
        " policy_version, eval_code, eval_detail, reevaluated_by, reevaluated_at)"
        " VALUES (COALESCE(%s, nextval('scan_result_reeval_reeval_id_seq')),"
        " %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) RETURNING reeval_id",
        (reeval_id, job_id, plugin_uuid, policy_version, code, detail, by, at),
    ).fetchone()
    assert row is not None
    return int(row[0])


# ----- checksums and reads -----------------------------------------------------

KEYS = {
    "scan": "scan_id",
    "scan_job": "job_id",
    "scan_result": "job_id, plugin_uuid, job_created_at",
    "scan_result_reeval": "reeval_id",
    "audit_log": "audit_id",
    "policy": "policy_id",
    "plugin": "plugin_uuid",
    "policy_plugin": "policy_id, plugin_uuid",
}


def checksum(conn: Conn, table: str) -> str:
    """md5 over every row of a table (or partition) in key order."""
    key = KEYS[
        "scan_result"
        if table.startswith("scan_result_") and table != "scan_result_reeval"
        else table
    ]
    query = sql.SQL(
        "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY {k}), '')) FROM {t} t"
    ).format(k=sql.SQL(key), t=sql.Identifier(table))
    row = conn.execute(query).fetchone()
    assert row is not None
    return str(row[0])


def result_partitions(conn: Conn) -> list[str]:
    rows = conn.execute(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
        " JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'scan_result'"
        " ORDER BY 1"
    ).fetchall()
    return [str(r[0]) for r in rows]


def result_checksums(conn: Conn) -> dict[str, str]:
    """scan_result parent and every partition."""
    out = {"scan_result": checksum(conn, "scan_result")}
    for part in result_partitions(conn):
        out[part] = checksum(conn, part)
    return out


def next_month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    first = now.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    return (first + timedelta(days=32)).replace(day=1, hour=12)


def reevals_of(conn: Conn, job_ids: Sequence[UUID]) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT reeval_id, job_id, plugin_uuid, policy_version, eval_code, eval_detail,"
        " reevaluated_by FROM scan_result_reeval WHERE job_id = ANY(%s)"
        " ORDER BY reeval_id",
        (list(job_ids),),
    ).fetchall()


def audit_rows(conn: Conn, action: str) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT audit_id, actor, action, target, detail FROM audit_log"
        " WHERE action = %s ORDER BY audit_id",
        (action,),
    ).fetchall()


class StatementSpy:
    """Records every SQL text a psycopg connection executes (client side)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def install(self, monkeypatch: Any) -> None:
        spy = self
        real_execute = psycopg.Cursor.execute
        real_executemany = psycopg.Cursor.executemany

        def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
            spy.statements.append(_text(cur, query))
            return real_execute(cur, query, params, **kw)

        def executemany(cur: Any, query: Any, params_seq: Any, **kw: Any) -> Any:
            spy.statements.append(_text(cur, query))
            return real_executemany(cur, query, params_seq, **kw)

        monkeypatch.setattr(psycopg.Cursor, "execute", execute)
        monkeypatch.setattr(psycopg.Cursor, "executemany", executemany)
        monkeypatch.setattr(psycopg.ServerCursor, "execute", _server_execute(spy))

    def verbs(self) -> list[str]:
        return [_verb(s) for s in self.statements]


def _server_execute(spy: StatementSpy) -> Any:
    real = psycopg.ServerCursor.execute

    def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
        spy.statements.append(_text(cur, query))
        return real(cur, query, params, **kw)

    return execute


def _text(cur: Any, query: Any) -> str:
    if isinstance(query, str):
        return query
    if isinstance(query, bytes):
        return query.decode()
    return str(query.as_string(cur.connection))


def _verb(statement: str) -> str:
    words = statement.strip().split(None, 1)
    return words[0].upper() if words else ""
