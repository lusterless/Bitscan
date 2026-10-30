"""TP-M9-01: PostgreSQL fixture builder for the M9 scan-engine suites
(tester-m9b; REQ-208 to REQ-230; CHK-M9-100 to -103).

No product M9 code is used here. What the code under test reads but does not
write is built by the test:

- the catalog through M7's real upload and delete paths
  (``services.importer.uploads.upload``, ``services.importer.delete.delete_policy``)
  from ``.bit`` documents written here, so families, policies, plugins,
  ``policy_plugin.sort_order`` and ``v_plugin`` are exactly what an import
  stores (CHK-M9-100);
- agents in all six statuses, with tags and real ``bsa_`` tokens, inserted
  as ``bitscan_app`` (the app may INSERT ``agent`` and ``agent_tag``)
  (CHK-M9-101);
- scans, jobs (originals and retries, every state) and results written as
  owner (``bitscan_migrate`` + ``SET ROLE bitscan_owner``), never as a
  superuser, in the TS §5.2 / §6.5 / #117 shapes (CHK-M9-102);
- a clock double, the canary, row checksums, a statement spy and a lock-wait
  probe (CHK-M9-103).

Expected values in the suites come from the spec and the approved answers,
never from this module's own builders: the builders write *inputs*.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.db.pool import AppDatabase

from .conftest import PgServer
from .evaluator_pg_fixtures import StatementSpy
from .evaluator_pg_fixtures import checksum as _m8_checksum

Conn = psycopg.Connection[Any]

__all__ = [
    "CANARY",
    "Clock",
    "Conn",
    "StatementSpy",
    "checksum",
]


# ----- time --------------------------------------------------------------------


def month_anchor(now: datetime | None = None) -> datetime:
    """Day 15, 12:00:00 UTC of the current month: inside the scan_result
    partition the migration created for this month, whatever day the suite
    runs, with two weeks either side for offsets."""
    now = now or datetime.now(UTC)
    return now.replace(day=15, hour=12, minute=0, second=0, microsecond=0)


def next_month(at: datetime) -> datetime:
    """Day 15 of the month after ``at`` (the next partition, also created)."""
    return (at.replace(day=1) + timedelta(days=32)).replace(day=15)


T0 = month_anchor()
CANARY = "M9CANARY-" + str(uuid4())


def iso(at: datetime) -> str:
    """RFC 3339 with Z, microseconds kept when present."""
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def zsec(at: datetime) -> str:
    """The #125 (c) pickup_by text form: YYYY-MM-DDTHH:MM:SSZ (sub-second dropped)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock:
    """The runtime clock double (decisions 2026-10-26: time is moved, never waited)."""

    def __init__(self, at: datetime = T0) -> None:
        self.at = at
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self.at

    def advance(self, **delta: float) -> datetime:
        with self._lock:
            self.at += timedelta(**delta)
            return self.at

    def set(self, at: datetime) -> None:
        with self._lock:
            self.at = at


# ----- connections -------------------------------------------------------------


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


@contextmanager
def app_database(server: PgServer, max_size: int = 8) -> Iterator[AppDatabase]:
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=max_size, connect_timeout_s=5
    )
    db.open()
    try:
        yield db
    finally:
        db.close()


def backend_pid(conn: Conn) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return int(row[0])


def wait_until_lock_waiting(
    server: PgServer, pid: int, *, bound_s: float = 10.0
) -> None:
    """Polls (20 ms) until backend ``pid`` waits on a heavyweight lock (a
    ``granted = false`` row in ``pg_locks``, which every role can read;
    ``pg_stat_activity`` hides other roles' wait events); fails after
    ``bound_s``. A probe, not an ordering sleep (test-plan conventions)."""
    deadline = time.monotonic() + bound_s
    with owner(server) as probe:
        while time.monotonic() < deadline:
            if _waiting(probe, pid):
                return
            time.sleep(0.02)
    raise AssertionError(f"backend {pid} never waited on a lock within {bound_s} s")


def _waiting(probe: Conn, pid: int) -> bool:
    row = probe.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s AND NOT granted)",
        (pid,),
    ).fetchone()
    return bool(row and row[0])


def wait_until_any_waiter(server: PgServer, *, bound_s: float = 10.0) -> None:
    """Polls until some backend waits on a heavyweight lock (for a session
    the test cannot name, such as a pooled connection inside product code).
    Use on a database of the module's own, where no one else waits."""
    deadline = time.monotonic() + bound_s
    with owner(server) as probe:
        while time.monotonic() < deadline:
            row = probe.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE NOT granted)"
            ).fetchone()
            if row and row[0]:
                return
            time.sleep(0.02)
    raise AssertionError(f"no backend waited on a lock within {bound_s} s")


def is_lock_waiting(server: PgServer, pid: int) -> bool:
    with owner(server) as probe:
        return _waiting(probe, pid)


# ----- catalog through M7 ------------------------------------------------------


def escape(text: str) -> str:
    """XML text escaping for element content (&, <, >)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class PluginDef:
    """One `<Plugin>` as written into a `.bit` file (SR §2.3)."""

    plugin_uuid: UUID
    name: str
    execute: str
    operator: str = "equals"
    expected: str = "ok"
    timeout_s: int = 30


def plugin(
    execute: str | None = None,
    *,
    operator: str = "equals",
    expected: str | None = None,
    timeout_s: int = 30,
    name: str | None = None,
    uuid: UUID | None = None,
) -> PluginDef:
    """A plugin; ExpectedResult defaults to "ok", or "" for the presence
    operators (BIT014: empty and not_empty take no ExpectedResult)."""
    t = secrets.token_hex(3)
    if expected is None:
        expected = "" if operator in ("empty", "not_empty") else "ok"
    return PluginDef(
        uuid or uuid4(),
        name or f"9.{t} - Check {t}",
        execute or f"printf '%s' ok-{t}",
        operator,
        expected,
        timeout_s,
    )


def bit_doc(
    policy_name: str,
    family: str,
    plugins: Sequence[PluginDef],
    *,
    status: str = "enabled",
) -> bytes:
    """A valid SR §1.1-shaped document. Text is XML-escaped; Execute is CDATA."""
    body = []
    for p in plugins:
        assert "]]>" not in p.execute
        body.append(
            "    <Plugin>\n"
            f"      <PluginName>{escape(p.name)}</PluginName>\n"
            "      <PluginDescription>M9 test check.</PluginDescription>\n"
            f"      <PluginId>{p.plugin_uuid}</PluginId>\n"
            f'      <Execute timeout="{p.timeout_s}">'
            f"<![CDATA[{p.execute}]]></Execute>\n"
            f"      <Operator>{p.operator}</Operator>\n"
            f"      <ExpectedResult>{escape(p.expected)}</ExpectedResult>\n"
            "    </Plugin>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Policy formatVersion="1.0">\n'
        f"  <PolicyName>{escape(policy_name)}</PolicyName>\n"
        "  <PolicyDescription>Generated by tester-m9b.</PolicyDescription>\n"
        f"  <PolicyStatus>{status}</PolicyStatus>\n"
        "  <Family>\n"
        f"    <FamilyName>{escape(family)}</FamilyName>\n"
        "  </Family>\n"
        "  <PluginsGroups>\n"
        f"{''.join(body)}"
        "  </PluginsGroups>\n"
        "</Policy>\n"
    ).encode()


SR_PLUGIN_NAME = "1.3.1.1 - Ensure AppArmor is installed"
SR_FAMILY = "CIS Ubuntu 24.04"
SR_EXECUTE = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"


def sr_plugin(uuid: UUID | None = None) -> PluginDef:
    """The SR §1.1 plugin, with a fresh PluginId (BIT015: one owner per id)."""
    return PluginDef(
        uuid or uuid4(),
        SR_PLUGIN_NAME,
        SR_EXECUTE,
        "equals",
        "install ok installed",
        30,
    )


@dataclass
class Pol:
    policy_id: int
    name: str
    family: str
    plugins: list[PluginDef]
    version: int
    status: str = "enabled"

    def display(self, p: PluginDef) -> str:
        return f"{self.family} - {p.name}"

    @property
    def uuids(self) -> list[UUID]:
        return [p.plugin_uuid for p in self.plugins]


@dataclass
class Catalog:
    """M7's upload and delete, called as the API would (actor = an admin)."""

    db: AppDatabase
    clock: Clock
    bits: Path
    actor_user: int = 1

    def _actor(self) -> Any:
        from bitscan_manager.services.importer.pipeline_record import Actor

        return Actor(f"user:{self.actor_user}", self.actor_user)

    def upload_doc(self, data: bytes) -> int:
        from bitscan_manager.services.importer.uploads import upload

        out = upload(self.db, self.clock, self.bits, data, "m9.bit", self._actor())
        assert out.outcome == "success", out
        assert out.policy_id is not None
        return int(out.policy_id)

    def policy(
        self,
        plugins: Sequence[PluginDef] | int = 1,
        *,
        status: str = "enabled",
        family: str | None = None,
        name: str | None = None,
    ) -> Pol:
        defs = (
            [plugin() for _ in range(plugins)]
            if isinstance(plugins, int)
            else list(plugins)
        )
        t = secrets.token_hex(4)
        pol_name = name or f"M9 policy {t}"
        fam = family or f"M9 Family {t}"
        pid = self.upload_doc(bit_doc(pol_name, fam, defs, status=status))
        version = self.version_of(pid)
        return Pol(pid, pol_name, fam, defs, version, status)

    def reimport(
        self,
        pol: Pol,
        plugins: Sequence[PluginDef] | None = None,
        *,
        status: str | None = None,
    ) -> Pol:
        """A new upload of the same PolicyName (same family): a new version
        when anything changed (TS §4.1)."""
        defs = list(plugins) if plugins is not None else list(pol.plugins)
        st = status or pol.status
        pid = self.upload_doc(bit_doc(pol.name, pol.family, defs, status=st))
        assert pid == pol.policy_id
        pol.plugins = defs
        pol.status = st
        pol.version = self.version_of(pid)
        return pol

    def bump_to(self, pol: Pol, version: int) -> Pol:
        """Re-import with a changed command until the version is reached."""
        while pol.version < version:
            first = pol.plugins[0]
            changed = PluginDef(
                first.plugin_uuid,
                first.name,
                f"printf '%s' v{pol.version + 1}-{secrets.token_hex(2)}",
                first.operator,
                first.expected,
                first.timeout_s,
            )
            self.reimport(pol, [changed, *pol.plugins[1:]])
        assert pol.version == version, pol.version
        return pol

    def delete(self, pol: Pol) -> Any:
        from bitscan_manager.services.importer.delete import delete_policy

        return delete_policy(
            self.db,
            pol.policy_id,
            actor=f"user:{self.actor_user}",
            clock=self.clock,
            bits_dir=self.bits,
        )

    def version_of(self, policy_id: int) -> int:
        with self.db.transaction() as tx:
            row = tx.conn.execute(
                "SELECT version FROM policy WHERE policy_id = %s", (policy_id,)
            ).fetchone()
        assert row is not None
        return int(row[0])


def make_catalog(db: AppDatabase, clock: Clock, tmp: Path) -> Catalog:
    bits = tmp / "bits"
    (bits / "uploaded").mkdir(parents=True, exist_ok=True)
    return Catalog(db, clock, bits)


# ----- fleet -------------------------------------------------------------------

STATUSES = (
    "awaiting_approval",
    "enrolled",
    "online",
    "stale",
    "offline",
    "decommissioned",
)
ELIGIBLE = ("enrolled", "online", "stale", "offline")  # TS §4.4 L555; #122 (c)


@dataclass(frozen=True)
class AgentRow:
    agent_id: UUID
    token: str
    machine_id: str
    status: str
    tags: tuple[str, ...] = ()

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Bitscan-Machine-Id": self.machine_id,
        }


def make_agent(
    conn: Conn,
    status: str = "online",
    *,
    tags: Sequence[str] = (),
    version: str = "1.0.0",
    at: datetime = T0,
    agent_id: UUID | None = None,
    **cols: Any,
) -> AgentRow:
    """One agent row as bitscan_app, with a real bsa_ token (hash stored)."""
    tok = new_agent_token(AgentTokenKind.AGENT)
    machine = secrets.token_hex(16)
    heartbeat = {
        "online": at - timedelta(minutes=1),
        "stale": at - timedelta(minutes=15),
        "offline": at - timedelta(hours=2),
        "decommissioned": at - timedelta(days=30),
    }.get(status)
    values: dict[str, Any] = (
        {
            "machine_id": machine,
            "hostname": f"m9-{secrets.token_hex(3)}",
            "agent_version": version,
            "token_hash": token_hash(tok),
            "token_issued_at": at - timedelta(days=10),
            "token_expires_at": at + timedelta(days=355),
            "status": status,
            "enrolled_at": at - timedelta(days=10),
            "last_heartbeat_at": heartbeat,
        }
        | ({"agent_id": agent_id} if agent_id else {})
        | cols
    )
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    row = conn.execute(
        f"INSERT INTO agent ({names}) VALUES ({marks}) RETURNING agent_id",  # noqa: S608 - fixed column names
        list(values.values()),
    ).fetchone()
    assert row is not None
    aid = UUID(str(row[0]))
    for t in tags:
        conn.execute("INSERT INTO agent_tag (agent_id, tag) VALUES (%s, %s)", (aid, t))
    return AgentRow(aid, tok, machine, status, tuple(tags))


def fleet(conn: Conn, tags: Sequence[str] = ()) -> dict[str, AgentRow]:
    """One agent per status (TS §5.2 agent_status), each holding ``tags``."""
    return {s: make_agent(conn, s, tags=tags) for s in STATUSES}


def new_tag() -> str:
    return f"m9.{secrets.token_hex(4)}"


# ----- owner-written scans, jobs, results --------------------------------------


@dataclass(frozen=True)
class JobRow:
    job_id: UUID
    scan_id: UUID | None
    agent_id: UUID
    created_at: datetime
    plugins: tuple[PluginDef, ...]
    payload: dict[str, Any]
    eval_spec: Any
    retry_of: UUID | None = None

    @property
    def uuids(self) -> list[UUID]:
        return [p.plugin_uuid for p in self.plugins]


def payload_of(
    job_id: UUID,
    agent_id: UUID,
    created_at: datetime,
    plugins: Sequence[PluginDef],
    patterns: Sequence[str] = (),
) -> dict[str, Any]:
    """The TS §6.5 compliance Job body (#125 (a)–(c)), as the tests expect it."""
    return {
        "job_id": str(job_id),
        "agent_id": str(agent_id),
        "kind": "compliance",
        "pickup_by": zsec(created_at + timedelta(hours=24)),
        "plugins": [
            {
                "plugin_uuid": str(p.plugin_uuid),
                "execute": p.execute,
                "timeout_s": p.timeout_s,
            }
            for p in plugins
        ],
        "redaction_patterns": list(patterns),
    }


def eval_spec_of(pol: Pol, plugins: Sequence[PluginDef]) -> dict[str, Any]:
    """#117: one entry per plugin, in payload order; name = family - plugin."""
    return {
        "plugins": [
            {
                "plugin_uuid": str(p.plugin_uuid),
                "name": pol.display(p),
                "operator": p.operator,
                "expected": p.expected,
            }
            for p in plugins
        ]
    }


def owner_scan(
    conn: Conn,
    pol: Pol,
    *,
    state: str = "queued",
    target: Mapping[str, Any] | None = None,
    created_at: datetime = T0,
    finished_at: datetime | None = None,
    schedule_id: int | None = None,
    trigger: str = "manual",
    version: int | None = None,
) -> UUID:
    row = conn.execute(
        "INSERT INTO scan (policy_id, policy_version, trigger, schedule_id, target,"
        " state, created_at, finished_at) VALUES (%s, %s, %s, %s, %s,"
        " CAST(%s AS scan_state), %s, %s) RETURNING scan_id",
        (
            pol.policy_id,
            pol.version if version is None else version,
            trigger,
            schedule_id,
            Jsonb(dict(target or {"all": True})),
            state,
            created_at,
            finished_at,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def owner_job(
    conn: Conn,
    scan_id: UUID,
    agent_id: UUID,
    pol: Pol,
    plugins: Sequence[PluginDef] | None = None,
    *,
    state: str = "queued",
    created_at: datetime = T0,
    dispatched_at: datetime | None = None,
    started_at: datetime | None = None,
    deadline_at: datetime | None = None,
    finished_at: datetime | None = None,
    retry_of: UUID | None = None,
    patterns: Sequence[str] = (),
    eval_spec: Any = None,
    pickup_by: datetime | None = None,
) -> JobRow:
    """A compliance job (as owner) whose payload and eval_spec are the TS §6.5
    and #117 shapes. Timestamps not given are filled for the state."""
    plugins = list(plugins if plugins is not None else pol.plugins)
    jid = uuid4()
    if state != "queued" and dispatched_at is None:
        dispatched_at = created_at + timedelta(minutes=1)
    if state in ("running", "completed", "partial") and started_at is None:
        started_at = (dispatched_at or created_at) + timedelta(seconds=10)
    if started_at is not None and deadline_at is None:
        deadline_at = started_at + timedelta(minutes=30)
    if state in ("completed", "partial", "failed", "expired", "cancelled"):
        finished_at = finished_at or (dispatched_at or created_at) + timedelta(
            minutes=20
        )
    payload = payload_of(jid, agent_id, created_at, plugins, patterns)
    spec = eval_spec_of(pol, plugins) if eval_spec is None else eval_spec
    row = conn.execute(
        "INSERT INTO scan_job (job_id, kind, scan_id, agent_id, retry_of, state,"
        " payload, eval_spec, created_at, pickup_by, dispatched_at, started_at,"
        " deadline_at, finished_at) VALUES (%s, 'compliance', %s, %s, %s,"
        " CAST(%s AS scan_state), %s, %s, %s, %s, %s, %s, %s, %s) RETURNING created_at",
        (
            jid,
            scan_id,
            agent_id,
            retry_of,
            state,
            Jsonb(payload),
            Jsonb(spec),
            created_at,
            pickup_by or created_at + timedelta(hours=24),
            dispatched_at,
            started_at,
            deadline_at,
            finished_at,
        ),
    ).fetchone()
    assert row is not None
    return JobRow(
        jid, scan_id, agent_id, row[0], tuple(plugins), payload, spec, retry_of
    )


def owner_inventory_job(
    conn: Conn,
    agent_id: UUID,
    *,
    state: str = "queued",
    created_at: datetime = T0,
    dispatched_at: datetime | None = None,
) -> UUID:
    jid = uuid4()
    if state != "queued" and dispatched_at is None:
        dispatched_at = created_at + timedelta(minutes=1)
    finished = (
        (dispatched_at or created_at) + timedelta(minutes=2)
        if state in ("completed", "failed", "expired", "cancelled")
        else None
    )
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
        " pickup_by, dispatched_at, finished_at) VALUES (%s, 'inventory', %s,"
        " CAST(%s AS scan_state), %s, %s, %s, %s, %s)",
        (
            jid,
            agent_id,
            state,
            Jsonb(
                {
                    "job_id": str(jid),
                    "agent_id": str(agent_id),
                    "kind": "inventory",
                    "pickup_by": zsec(created_at + timedelta(hours=24)),
                }
            ),
            created_at,
            created_at + timedelta(hours=24),
            dispatched_at,
            finished,
        ),
    )
    return jid


def owner_result(
    conn: Conn,
    job: JobRow,
    pol: Pol,
    p: PluginDef,
    *,
    code: int = 0,
    detail: str | None = None,
    stdout: str = "ok",
    stderr: str = "",
    exit_code: int | None = 0,
    at: datetime = T0,
) -> None:
    """One scan_result (as owner) with job_created_at = the job's created_at."""
    conn.execute(
        "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
        " eval_detail, exit_code, stdout, stderr, timed_out, truncated,"
        " plugin_name_snap, execute_snap, operator_snap, expected_snap,"
        " started_at, finished_at, received_at) VALUES (%s, %s, %s, %s, %s, %s,"
        " %s, %s, false, false, %s, %s, CAST(%s AS plugin_operator), %s, %s, %s, %s)",
        (
            job.job_id,
            job.created_at,
            p.plugin_uuid,
            code,
            detail,
            exit_code,
            stdout,
            stderr,
            pol.display(p),
            p.execute,
            p.operator,
            p.expected,
            at - timedelta(seconds=2),
            at - timedelta(seconds=1),
            at,
        ),
    )


def owner_schedule(
    conn: Conn,
    pol: Pol,
    *,
    cron: str = "0 3 * * *",
    timezone: str = "UTC",
    enabled: bool = True,
    target: Mapping[str, Any] | None = None,
    next_run_at: datetime | None = None,
    last_run_at: datetime | None = None,
    created_by: int = 1,
    name: str | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO scan_schedule (name, policy_id, target, cron, timezone, enabled,"
        " last_run_at, next_run_at, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s,"
        " %s, %s) RETURNING schedule_id",
        (
            name or f"m9 sched {secrets.token_hex(3)}",
            pol.policy_id,
            Jsonb(dict(target or {"all": True})),
            cron,
            timezone,
            enabled,
            last_run_at,
            next_run_at,
            created_by,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


# ----- reads -------------------------------------------------------------------

_KEYS = {
    "scan_schedule": "schedule_id",
    "agent": "agent_id",
    "agent_tag": "agent_id, tag",
    "setting": "key",
}


def checksum(conn: Conn, table: str) -> str:
    """md5 over every row of a table in key order (M8's helper plus the
    tables M9 suites compare)."""
    if table not in _KEYS:
        return _m8_checksum(conn, table)
    query = sql.SQL(
        "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY {k}), '')) FROM {t} t"
    ).format(k=sql.SQL(_KEYS[table]), t=sql.Identifier(table))
    row = conn.execute(query).fetchone()
    assert row is not None
    return str(row[0])


def one(conn: Conn, query: str, args: Sequence[Any] | Mapping[str, Any] = ()) -> Any:
    row = conn.execute(query, args).fetchone()
    assert row is not None, query
    return row[0] if len(row) == 1 else tuple(row)


def job_state(conn: Conn, job_id: UUID) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT state::text AS state, dispatched_at, started_at, deadline_at,"
        " finished_at, payload, eval_spec, agent_id, scan_id, retry_of, created_at,"
        " pickup_by, kind FROM scan_job WHERE job_id = %s",
        (job_id,),
    )
    cols = [d.name for d in cur.description or []]
    row = cur.fetchone()
    assert row is not None, job_id
    return dict(zip(cols, row, strict=True))


def scan_row(conn: Conn, scan_id: UUID) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT scan_id, policy_id, policy_version, trigger, schedule_id, target,"
        " requested_by, state::text AS state, created_at, finished_at"
        " FROM scan WHERE scan_id = %s",
        (scan_id,),
    )
    cols = [d.name for d in cur.description or []]
    row = cur.fetchone()
    assert row is not None, scan_id
    return dict(zip(cols, row, strict=True))


def jobs_of_scan(conn: Conn, scan_id: UUID) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT job_id, agent_id, retry_of, state::text AS state, payload, eval_spec,"
        " created_at, pickup_by, dispatched_at, started_at, deadline_at, finished_at"
        " FROM scan_job WHERE scan_id = %s ORDER BY agent_id, created_at, job_id",
        (scan_id,),
    )
    cols = [d.name for d in cur.description or []]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def results_of(conn: Conn, job_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT job_id, job_created_at, plugin_uuid, eval_code, result::text AS result,"
        " eval_detail, exit_code, stdout, stderr, timed_out, truncated,"
        " plugin_name_snap, execute_snap, operator_snap::text AS operator_snap,"
        " expected_snap, started_at, finished_at, received_at"
        " FROM scan_result WHERE job_id = ANY(%s) ORDER BY received_at, job_id,"
        " plugin_uuid",
        (list(job_ids),),
    )
    cols = [d.name for d in cur.description or []]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def counts(conn: Conn) -> tuple[int, int, int, int]:
    """(scan, scan_job, scan_result, audit_log) row counts."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM scan), (SELECT count(*) FROM scan_job),"
        " (SELECT count(*) FROM scan_result), (SELECT count(*) FROM audit_log)"
    ).fetchone()
    assert row is not None
    return (int(row[0]), int(row[1]), int(row[2]), int(row[3]))


def last_audit(conn: Conn) -> int:
    return int(one(conn, "SELECT coalesce(max(audit_id), 0) FROM audit_log"))


def audit_after(conn: Conn, mark: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT audit_id, actor, action, target, detail FROM audit_log"
        " WHERE audit_id > %s ORDER BY audit_id",
        (mark,),
    ).fetchall()
    return [
        {
            "audit_id": r[0],
            "actor": r[1],
            "action": r[2],
            "target": r[3],
            "detail": r[4],
        }
        for r in rows
    ]


def table_sums(conn: Conn, *tables: str) -> dict[str, str]:
    return {t: checksum(conn, t) for t in tables}


# ----- settings ----------------------------------------------------------------


def read_setting(conn: Conn, key: str) -> Any:
    return one(conn, "SELECT value FROM setting WHERE key = %s", (key,))


@contextmanager
def setting(server: PgServer, key: str, value: Any) -> Iterator[None]:
    """A setting changed as bitscan_app for the block, then restored."""
    with app(server) as c:
        old = read_setting(c, key)
        c.execute("UPDATE setting SET value = %s WHERE key = %s", (Jsonb(value), key))
    try:
        yield
    finally:
        with app(server) as c:
            c.execute("UPDATE setting SET value = %s WHERE key = %s", (Jsonb(old), key))


# ----- canary ------------------------------------------------------------------


def canary_hits(texts: Sequence[str], canary: str = CANARY) -> list[str]:
    return [t for t in texts if canary in t]


def log_texts(records: Sequence[Any]) -> list[str]:
    out: list[str] = []
    for r in records:
        out.append(str(r.getMessage()))
        out.append(repr(r.args))
        if r.exc_info and r.exc_info[1] is not None:
            out.append(repr(r.exc_info[1]))
            out.append(str(r.exc_info[1]))
        out.extend(str(v) for k, v in vars(r).items() if k not in ("msg", "args"))
    return out


# ----- threads -----------------------------------------------------------------


@dataclass
class Outcome:
    value: Any = None
    error: BaseException | None = None


def run_threads(
    fns: Sequence[Callable[[], Any]], *, join_s: float = 60.0
) -> list[Outcome]:
    outs = [Outcome() for _ in fns]

    def wrap(i: int) -> None:
        try:
            outs[i].value = fns[i]()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outs[i].error = exc

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(len(fns))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(join_s)
        assert not t.is_alive(), "a race thread did not finish"
    return outs


@dataclass
class Gate:
    """A one-shot gate: a thread parks at ``wait()`` until the test calls
    ``open()``; ``reached`` tells the test it is parked."""

    reached: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)

    def wait(self, bound_s: float = 30.0) -> None:
        self.reached.set()
        assert self.released.wait(bound_s), "gate never opened"

    def open(self) -> None:
        self.released.set()
