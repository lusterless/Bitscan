"""TP-M11-01: PostgreSQL fixture builder for the M11 suites (tester-m11;
REQ-264 to REQ-278; CHK-M11-100 to -104).

No M11 product code is used here. What the code under test reads but does not
write is written by the test, as owner (``bitscan_migrate`` + ``SET ROLE
bitscan_owner``) unless noted, never as a superuser, in the TS §5.2 shapes and
the shapes M3, M7, M8 and M9 store:

- a catalog (family, policy, plugins in ``policy_plugin.sort_order``), new
  versions and soft deletes (CHK-M11-100);
- scans whose ``target`` is the request plus the sorted ``resolved_agents``
  (as M9's ``targets.stored_target`` writes it), compliance jobs in every
  state, originals and retries, results with ``job_created_at`` equal to the
  job's ``created_at`` in two monthly partitions, re-evaluation rows with
  chosen ids and times, intake ERRORs, not-run plugins (CHK-M11-100);
- hosts with ``<script>`` hostnames, users of every role with sessions and
  API tokens, a restricted admin, wrong-group tokens (CHK-M11-101);
- four canaries, a clock double, a role-recording statement spy and a holder
  of M8's re-evaluation lock (CHK-M11-102);
- aged retention rows on both sides of every cutoff and an old audit chain
  (CHK-M11-103, -104).

Expected values in the suites come from the spec and the approved answers,
never from this module: the builders write *inputs* and label them (for
example "at" = exactly at a cutoff, "past" = 1 µs older); each test decides
from the spec which labels must survive.
"""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import reeval as m8_reeval
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.audit.chain import (
    GENESIS_PREV_HASH,
    HashInput,
    append_entry,
)
from bitscan_manager.services.audit.chain import compute_row_hash as m1_row_hash

from . import scan_pg_fixtures as f9
from .agent_sim import PW_HASH, ApiEnv
from .conftest import PgServer
from .evaluator_pg_fixtures import StatementSpy, add_reeval, reserve_reeval_ids
from .scan_pg_fixtures import (
    T0,
    AgentRow,
    Clock,
    JobRow,
    PluginDef,
    Pol,
    app,
    app_database,
    iso,
    next_month,
    owner,
)

Conn = psycopg.Connection[Any]

__all__ = [
    "ERR",
    "EXEC",
    "EXP",
    "IMG",
    "OUT",
    "SCRIPT",
    "T0",
    "AgentRow",
    "Clock",
    "JobRow",
    "PluginDef",
    "Pol",
    "StatementSpy",
    "add_reeval",
    "app",
    "app_database",
    "iso",
    "next_month",
    "owner",
    "reserve_reeval_ids",
]

# ----- canaries and hostile text ----------------------------------------------

_RUN = secrets.token_hex(6)
OUT = f"M11OUT-{_RUN}"  # stdout: operator and admin results only
ERR = f"M11ERR-{_RUN}"  # stderr: operator and admin results only
EXEC = f"M11EXEC-{_RUN}"  # execute: results items of every role, nowhere else
EXP = f"M11EXP-{_RUN}"  # an expected value: as EXEC
CANARIES = (OUT, ERR, EXEC, EXP)
OUTPUT_CANARIES = (OUT, ERR)
SCRIPT = "<script>alert('m11')</script>"
IMG = "<img src=x onerror=alert(1)>"


def hits(texts: Sequence[str], canaries: Sequence[str] = CANARIES) -> list[str]:
    """Every canary found in any of the texts."""
    return sorted({c for c in canaries for t in texts if c in t})


def now_utc() -> datetime:
    """The real current instant (retention compares it with the database's)."""
    return datetime.now(UTC)


def ztext(at: datetime) -> str:
    """The audit chain's at text: YYYY-MM-DDTHH:MM:SS.ffffffZ in UTC (#38)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ----- connections -------------------------------------------------------------


@contextmanager
def tx_conn(
    server: PgServer, role: str, *, set_role: str | None = None
) -> Iterator[Conn]:
    """A connection that is *not* autocommit (for transaction-level locks and
    the audit append's checks); the caller commits or the block rolls back."""
    conn = psycopg.connect(server.dsn(role))
    try:
        if set_role is not None:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(set_role)))
            conn.commit()
        yield conn
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def retention_database(server: PgServer, max_size: int = 2) -> Iterator[AppDatabase]:
    """A pool logged in as bitscan_retention (TS §5.3 L1051, §8.6 L1309)."""
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_retention")),
        max_size=max_size,
        connect_timeout_s=5,
    )
    db.open()
    try:
        yield db
    finally:
        db.close()


def refused(
    conn: Conn, statement: str | sql.SQL | sql.Composed, args: Sequence[Any] = ()
) -> str | None:
    """SQLSTATE of ``statement`` run in a rolled-back transaction on an
    autocommit connection; None when it was allowed (grant probes)."""
    try:
        with conn.transaction(force_rollback=True):
            conn.execute(statement, args)
    except psycopg.Error as exc:
        return exc.sqlstate or "?"
    return None


# ----- partitions --------------------------------------------------------------


def month_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(start: datetime, months: int) -> datetime:
    years, index = divmod(start.month - 1 + months, 12)
    return start.replace(year=start.year + years, month=index + 1)


def ensure_partition(conn: Conn, at: datetime) -> str:
    """The monthly ``scan_result`` partition holding ``at`` (as owner, in the
    ``db maintain`` naming), so old results never land in the default
    partition (which must stay empty, TS §5.3 L1049)."""
    lower = month_start(at)
    name = lower.strftime("scan_result_%Y_%m")
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} PARTITION OF scan_result"
            " FOR VALUES FROM ({}) TO ({})"
        ).format(
            sql.Identifier(name), sql.Literal(lower), sql.Literal(add_months(lower, 1))
        )
    )
    return name


def default_partition_rows(conn: Conn) -> int:
    return int(f9.one(conn, "SELECT count(*) FROM scan_result_default"))


# ----- catalog (owner-written) -------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_policy(
    conn: Conn,
    plugins: Sequence[PluginDef] | int = 3,
    *,
    status: str = "enabled",
    family: str | None = None,
    name: str | None = None,
) -> Pol:
    """A family, a policy (version 1) and one active plugin per definition,
    listed in ``policy_plugin`` in the given order."""
    defs = (
        [f9.plugin() for _ in range(plugins)]
        if isinstance(plugins, int)
        else list(plugins)
    )
    t = secrets.token_hex(4)
    fam_name = family or f"M11 Family {t}"
    pol_name = name or f"M11 policy {t}"
    fam = f9.one(
        conn,
        "INSERT INTO family (family_name) VALUES (%s) RETURNING family_id",
        (fam_name,),
    )
    pid = f9.one(
        conn,
        "INSERT INTO policy (policy_name, policy_status, file_status, family_id,"
        " version, source_file, source_sha256) VALUES (%s, %s, %s, %s, 1, %s, %s)"
        " RETURNING policy_id",
        (pol_name, status, status, fam, f"m11/{t}.bit", _sha(t)),
    )
    for i, p in enumerate(defs):
        conn.execute(
            "INSERT INTO plugin (plugin_uuid, family_id, owner_policy_id, plugin_name,"
            " execute, execute_sha256, operator, expected_result, timeout_s)"
            " VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS plugin_operator), %s, %s)",
            (
                p.plugin_uuid,
                fam,
                pid,
                p.name,
                p.execute,
                _sha(p.execute),
                p.operator,
                p.expected,
                p.timeout_s,
            ),
        )
        conn.execute(
            "INSERT INTO policy_plugin (policy_id, plugin_uuid, sort_order)"
            " VALUES (%s, %s, %s)",
            (pid, p.plugin_uuid, i),
        )
    return Pol(int(pid), pol_name, fam_name, defs, 1, status)


def canary_plugin(name: str | None = None) -> PluginDef:
    """A plugin whose Execute holds EXEC and whose ExpectedResult is EXP."""
    t = secrets.token_hex(3)
    return PluginDef(
        uuid4(), name or f"1.{t} - Canary {t}", f"printf '%s' {EXEC}", "equals", EXP
    )


def new_version(
    conn: Conn,
    pol: Pol,
    *,
    expected: Mapping[UUID, str] | None = None,
    rename: Mapping[UUID, str] | None = None,
    drop: Sequence[UUID] = (),
) -> Pol:
    """What an import that edits the policy stores, in one transaction:
    version + 1, changed ExpectedResult or plugin name, dropped plugins
    unlisted and retired."""
    with conn.transaction():
        pol.version = int(
            f9.one(
                conn,
                "UPDATE policy SET version = version + 1, updated_at = now()"
                " WHERE policy_id = %s RETURNING version",
                (pol.policy_id,),
            )
        )
        for u, e in (expected or {}).items():
            conn.execute(
                "UPDATE plugin SET expected_result = %s WHERE plugin_uuid = %s", (e, u)
            )
        for u, n in (rename or {}).items():
            conn.execute(
                "UPDATE plugin SET plugin_name = %s WHERE plugin_uuid = %s", (n, u)
            )
        for u in drop:
            conn.execute(
                "DELETE FROM policy_plugin WHERE policy_id = %s AND plugin_uuid = %s",
                (pol.policy_id, u),
            )
            conn.execute(
                "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s", (u,)
            )
    return pol


def soft_delete(conn: Conn, pol: Pol) -> None:
    """TS §4.3 L552: marked deleted, source_file freed, plugins retired."""
    with conn.transaction():
        conn.execute(
            "UPDATE policy SET deleted_at = now(), source_file = %s"
            " WHERE policy_id = %s",
            (f"deleted/{pol.policy_id}", pol.policy_id),
        )
        conn.execute(
            "UPDATE plugin SET state = 'retired' WHERE owner_policy_id = %s",
            (pol.policy_id,),
        )


# ----- fleet -------------------------------------------------------------------


def host(
    conn: Conn,
    hostname: str | None = None,
    status: str = "online",
    *,
    at: datetime = T0,
    tags: Sequence[str] = (),
) -> AgentRow:
    """One agent (as the connection's role) with a real bsa_ token."""
    cols: dict[str, Any] = {} if hostname is None else {"hostname": hostname}
    return f9.make_agent(conn, status, at=at, tags=tags, **cols)


def script_host(conn: Conn, *, at: datetime = T0) -> AgentRow:
    return host(conn, f"{SCRIPT}-{secrets.token_hex(2)}", at=at)


# ----- users and tokens --------------------------------------------------------


@dataclass(frozen=True)
class Caller:
    """Who calls: a role and a token kind (session, api, restricted, revoked,
    agent, enrol or none)."""

    user_id: int | None
    role: str | None
    kind: str
    token: str | None

    def headers(self) -> dict[str, str]:
        return {} if self.token is None else {"Authorization": f"Bearer {self.token}"}


def make_user(
    conn: Conn,
    role: str = "viewer",
    *,
    totp: bool = True,
    disabled: bool = False,
    at: datetime = T0,
) -> int:
    return int(
        f9.one(
            conn,
            "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
            " totp_last_step, disabled, created_at) VALUES (%s, %s,"
            " CAST(%s AS user_role), %s, %s, %s, %s) RETURNING user_id",
            (
                f"m11-{secrets.token_hex(5)}",
                PW_HASH,
                role,
                "enc:00" if totp else None,
                5 if totp else None,
                disabled,
                at - timedelta(days=1),
            ),
        )
    )


def make_token(
    conn: Conn,
    user_id: int,
    kind: str = "session",
    *,
    verified: bool = True,
    at: datetime = T0,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
    revoked_at: datetime | None = None,
    name: str | None = None,
) -> str:
    """A bsu_ (session) or bsk_ (api) token; only its SHA-256 is stored.
    ``verified`` applies to sessions only (the DDL forbids it for API tokens)."""
    tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
    conn.execute(
        "INSERT INTO user_token (user_id, kind, name, token_hash, totp_verified,"
        " expires_at, created_at, revoked_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            user_id,
            kind,
            name,
            token_hash(tok),
            verified and kind == "session",
            expires_at or at + timedelta(days=30),
            created_at or at - timedelta(minutes=1),
            revoked_at,
        ),
    )
    return tok


def set_role(conn: Conn, user_id: int, role: str) -> None:
    """A role change as the users route would store it (the app may UPDATE
    app_user); the suites use it to demote between two calls."""
    conn.execute(
        "UPDATE app_user SET role = CAST(%s AS user_role) WHERE user_id = %s",
        (role, user_id),
    )


ROLES = ("viewer", "operator", "admin")


def callers(conn: Conn, *, at: datetime = T0) -> dict[str, Caller]:
    """Every caller the M11 refusal tables need, keyed ``<role>:<kind>``:
    each role with a TOTP-verified session and with an API token; a
    restricted admin (no TOTP enrolled, unverified session); a revoked
    operator session; a bsa_ and a bse_ token; no token."""
    out: dict[str, Caller] = {}
    for role in ROLES:
        uid = make_user(conn, role, at=at)
        out[f"{role}:session"] = Caller(
            uid, role, "session", make_token(conn, uid, at=at)
        )
        out[f"{role}:api"] = Caller(
            uid, role, "api", make_token(conn, uid, "api", at=at)
        )
    rid = make_user(conn, "admin", totp=False, at=at)
    out["admin:restricted"] = Caller(
        rid, "admin", "restricted", make_token(conn, rid, verified=False, at=at)
    )
    vid = make_user(conn, "operator", at=at)
    out["operator:revoked"] = Caller(
        vid,
        "operator",
        "revoked",
        make_token(conn, vid, at=at, revoked_at=at - timedelta(seconds=1)),
    )
    out["agent"] = Caller(None, None, "agent", new_agent_token(AgentTokenKind.AGENT))
    out["enrol"] = Caller(
        None, None, "enrol", new_agent_token(AgentTokenKind.ENROLMENT)
    )
    out["none"] = Caller(None, None, "none", None)
    return out


# ----- the audit sink outage (clock control, TS §5.3 L1053) --------------------


def sink_down(env: ApiEnv, seconds: float) -> None:
    """The sink unreachable from now, then the clock moved ``seconds`` on.
    The shipper sees an outage only when it has something to deliver, so one
    entry is appended first."""
    with tx_conn(env.server, "bitscan_app") as c:
        append_entry(PgAuditRepo(c), actor="m11-test", action="m11.outage_probe")
        c.commit()
    env.sink.up = False
    env.shipper.run_once()  # the first failed delivery starts the outage
    env.clock.advance(seconds=seconds)


def sink_up(env: ApiEnv, *, bound: int = 400) -> None:
    """The sink back, and the queue drained (cycles bounded; failing the
    bound fails the test)."""
    env.sink.up = True
    for _ in range(bound):
        env.clock.advance(seconds=31)
        env.shipper.run_once()
        if not env.shipper.refusing():
            return
    raise AssertionError(f"audit queue not drained in {bound} cycles")


# ----- scans, jobs, results, re-evaluations ------------------------------------


def scan(
    conn: Conn,
    pol: Pol,
    agents: Sequence[UUID],
    *,
    request: Mapping[str, Any] | None = None,
    state: str = "running",
    created_at: datetime = T0,
    finished_at: datetime | None = None,
    trigger: str = "manual",
    schedule_id: int | None = None,
    requested_by: int | None = None,
    version: int | None = None,
) -> UUID:
    """A scan row as M9 stores it: ``target`` = the request (default
    ``{"agents": [...]}``) plus ``resolved_agents``, distinct and sorted."""
    req = dict(request) if request is not None else {"agents": [str(a) for a in agents]}
    target = req | {"resolved_agents": sorted({str(a) for a in agents})}
    return UUID(
        str(
            f9.one(
                conn,
                "INSERT INTO scan (policy_id, policy_version, trigger, schedule_id,"
                " target, requested_by, state, created_at, finished_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS scan_state), %s, %s)"
                " RETURNING scan_id",
                (
                    pol.policy_id,
                    pol.version if version is None else version,
                    trigger,
                    schedule_id,
                    Jsonb(target),
                    requested_by,
                    state,
                    created_at,
                    finished_at,
                ),
            )
        )
    )


def job(
    conn: Conn,
    scan_id: UUID,
    agent_id: UUID,
    pol: Pol,
    plugins: Sequence[PluginDef] | None = None,
    **kw: Any,
) -> JobRow:
    """A compliance job (TS §6.5 payload, #117 eval_spec; M9's builder)."""
    return f9.owner_job(conn, scan_id, agent_id, pol, plugins, **kw)


def result(
    conn: Conn,
    jr: JobRow,
    pol: Pol,
    p: PluginDef,
    *,
    code: int = 0,
    detail: str | None = None,
    stdout: str | None = "ok",
    stderr: str | None = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    truncated: bool = False,
    at: datetime | None = None,
) -> None:
    """One scan_result with the job's snapshots and job_created_at."""
    when = at or jr.created_at + timedelta(minutes=5)
    conn.execute(
        "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid, eval_code,"
        " eval_detail, exit_code, stdout, stderr, timed_out, truncated,"
        " plugin_name_snap, execute_snap, operator_snap, expected_snap,"
        " started_at, finished_at, received_at) VALUES (%s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, CAST(%s AS plugin_operator), %s, %s, %s, %s)",
        (
            jr.job_id,
            jr.created_at,
            p.plugin_uuid,
            code,
            detail,
            exit_code,
            stdout,
            stderr,
            timed_out,
            truncated,
            pol.display(p),
            p.execute,
            p.operator,
            p.expected,
            when - timedelta(seconds=2),
            when - timedelta(seconds=1),
            when,
        ),
    )


def runner_unavailable(conn: Conn, jr: JobRow, pol: Pol, p: PluginDef) -> None:
    """The intake ERROR a 0.1.0 agent produces (#28, #74): empty streams."""
    result(
        conn,
        jr,
        pol,
        p,
        code=2,
        detail="runner_unavailable",
        stdout="",
        stderr="",
        exit_code=None,
    )


def oversize(conn: Conn, jr: JobRow, pol: Pol, p: PluginDef) -> None:
    """The server-side cap ERROR (TS §4.5): stored with empty streams."""
    result(
        conn, jr, pol, p, code=2, detail="oversize", stdout="", stderr="", exit_code=0
    )


JOB_STATES = (
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "expired",
)


def jobs_in_every_state(
    conn: Conn, pol: Pol, *, at: datetime = T0
) -> tuple[UUID, dict[str, JobRow]]:
    """One scan with one host per job state (TS §4.4 job states)."""
    agents = {s: host(conn, at=at).agent_id for s in JOB_STATES}
    sid = scan(conn, pol, list(agents.values()), created_at=at)
    return sid, {
        s: job(conn, sid, a, pol, state=s, created_at=at) for s, a in agents.items()
    }


@dataclass
class ResultsWorld:
    """REQ-267 (1)'s scan, plus a second scan on the same hosts and plugins.

    Policy plugins p[0]..p[4] (p[0] the canary plugin: EXEC, EXP).

    - host ``a``: original job ``a`` (partial, this month): p0 PASS with OUT
      and ERR; p1 FAIL then re-evaluated twice: ``reevals["low"]`` (lower id,
      later time, FAIL "low") and ``reevals["high"]`` (higher id, earlier
      time, PASS "high"); p2 ERROR runner_unavailable; p3 and p4 no result.
      Retry ``a_retry`` (next month, completed, plugins p3, p4): p3 FAIL.
      p4 is not run.
    - host ``b`` (hostname with ``<script>``): job ``b`` queued, no results.
    - host ``c``: job ``c`` completed: p0 PASS with IMG, commas, quotes, LF
      and CRLF in stdout; p1 PASS with formula stdout "=1+2" and eval detail
      "@SUM(1)"; p2 FAIL never re-evaluated; p3 PASS; p4 ERROR oversize.
    - ``other_scan``: the same policy, hosts a and c, every plugin FAIL with
      stdout "other-scan" (rows that must never leak into ``scan_id``).
    """

    pol: Pol
    scan_id: UUID
    other_scan: UUID
    hosts: dict[str, AgentRow]
    jobs: dict[str, JobRow]
    reevals: dict[str, int]
    admin_id: int

    @property
    def p(self) -> list[PluginDef]:
        return self.pol.plugins


C0_STDOUT = f'{IMG}, "quoted", a,b\nline2\r\nline3'
C1_STDOUT = "=1+2"
C1_DETAIL = "@SUM(1)"


def results_world(conn: Conn, *, at: datetime = T0, admin_id: int = 1) -> ResultsWorld:
    plugins = [canary_plugin(), *(f9.plugin() for _ in range(4))]
    pol = make_policy(conn, plugins)
    p = pol.plugins
    a, b, c = host(conn, at=at), script_host(conn, at=at), host(conn, at=at)
    sid = scan(
        conn,
        pol,
        [a.agent_id, b.agent_id, c.agent_id],
        created_at=at,
        requested_by=admin_id,
    )
    ja = job(conn, sid, a.agent_id, pol, state="partial", created_at=at)
    jar = job(
        conn,
        sid,
        a.agent_id,
        pol,
        [p[3], p[4]],
        state="completed",
        created_at=next_month(at),
        retry_of=ja.job_id,
    )
    jb = job(conn, sid, b.agent_id, pol, state="queued", created_at=at)
    jc = job(conn, sid, c.agent_id, pol, state="completed", created_at=at)
    result(conn, ja, pol, p[0], code=0, stdout=OUT, stderr=ERR)
    result(conn, ja, pol, p[1], code=1, stdout="no", stderr="")
    runner_unavailable(conn, ja, pol, p[2])
    result(conn, jar, pol, p[3], code=1, stdout="retry-fail", stderr="")
    result(conn, jc, pol, p[0], code=0, stdout=C0_STDOUT, stderr="", timed_out=False)
    result(conn, jc, pol, p[1], code=0, detail=C1_DETAIL, stdout=C1_STDOUT, stderr="")
    result(conn, jc, pol, p[2], code=1, stdout="c-fail", stderr="", truncated=True)
    result(conn, jc, pol, p[3], code=0, stdout="ok", stderr="")
    oversize(conn, jc, pol, p[4])
    base = reserve_reeval_ids(conn, 10)
    low = add_reeval(
        conn,
        ja.job_id,
        p[1].plugin_uuid,
        code=1,
        detail="low",
        policy_version=1,
        by=admin_id,
        reeval_id=base + 1,
        at=at + timedelta(hours=3),
    )
    high = add_reeval(
        conn,
        ja.job_id,
        p[1].plugin_uuid,
        code=0,
        detail="high",
        policy_version=1,
        by=admin_id,
        reeval_id=base + 2,
        at=at + timedelta(hours=1),
    )
    other = scan(
        conn, pol, [a.agent_id, c.agent_id], created_at=at + timedelta(minutes=1)
    )
    for h in (a, c):
        jo = job(
            conn,
            other,
            h.agent_id,
            pol,
            state="completed",
            created_at=at + timedelta(minutes=1),
        )
        for pd in p:
            result(conn, jo, pol, pd, code=1, stdout="other-scan", stderr="other-scan")
    return ResultsWorld(
        pol,
        sid,
        other,
        {"a": a, "b": b, "c": c},
        {"a": ja, "a_retry": jar, "b": jb, "c": jc},
        {"low": low, "high": high},
        admin_id,
    )


def wide_scan(
    conn: Conn, pol: Pol, layout: Sequence[int], *, at: datetime = T0
) -> tuple[UUID, list[AgentRow]]:
    """A scan whose hosts' original jobs plan ``layout[i]`` plugins each and
    have no results, so every planned plugin is one Not-run row: the CSV cap
    rows (100,000 and 100,001) without writing results. The planned plugins
    are synthetic (payload and eval_spec only; no catalog row is needed)."""
    agents = [host(conn, at=at) for _ in layout]
    sid = scan(conn, pol, [h.agent_id for h in agents], created_at=at)
    for h, n in zip(agents, layout, strict=True):
        defs = [
            PluginDef(uuid4(), f"9.{i} - wide", f"printf {i}", "equals", "ok")
            for i in range(n)
        ]
        job(conn, sid, h.agent_id, pol, defs, state="dispatched", created_at=at)
    return sid, agents


# ----- random scans (property suites) ------------------------------------------


@dataclass
class RandomScan:
    scan_id: UUID
    jobs: list[JobRow] = field(default_factory=list)


def random_scan(
    conn: Conn,
    rng: random.Random,
    pol: Pol,
    agents: Sequence[UUID],
    *,
    at: datetime = T0,
    admin_id: int = 1,
) -> RandomScan:
    """A random scan that respects the stored invariants M9 guarantees: one
    original per host; at most one retry, holding only the plugins with no
    result in the original (TS §4.4 L578); at most one result per host and
    plugin in the unit (first result wins); re-evaluations only of stored
    results, with ids and times in independent random orders (#119)."""
    chosen = rng.sample(list(agents), rng.randint(1, len(agents)))
    sid = scan(
        conn,
        pol,
        chosen,
        created_at=at,
        state=rng.choice(["running", "partial", "completed"]),
    )
    out = RandomScan(sid)
    reevals: list[tuple[UUID, UUID, int]] = []
    for a in chosen:
        state = rng.choice(JOB_STATES)
        orig = job(conn, sid, a, pol, state=state, created_at=at)
        out.jobs.append(orig)
        answered: set[UUID] = set()
        if state not in ("queued", "expired", "dispatched"):
            for pd in pol.plugins:
                if rng.random() < 0.6:
                    result(
                        conn,
                        orig,
                        pol,
                        pd,
                        code=rng.choice((0, 1, 2)),
                        stdout=f"r{rng.random()}",
                    )
                    answered.add(pd.plugin_uuid)
                    for _ in range(rng.randint(0, 3)):
                        reevals.append(
                            (orig.job_id, pd.plugin_uuid, rng.choice((0, 1, 2)))
                        )
        missing = [pd for pd in pol.plugins if pd.plugin_uuid not in answered]
        if state in ("failed", "partial") and missing and rng.random() < 0.6:
            when = next_month(at) if rng.random() < 0.5 else at + timedelta(hours=2)
            retry = job(
                conn,
                sid,
                a,
                pol,
                missing,
                state=rng.choice(("completed", "partial", "running")),
                created_at=when,
                retry_of=orig.job_id,
            )
            out.jobs.append(retry)
            for pd in missing:
                if rng.random() < 0.5:
                    result(
                        conn, retry, pol, pd, code=rng.choice((0, 1, 2)), stdout="retry"
                    )
                    for _ in range(rng.randint(0, 2)):
                        reevals.append(
                            (retry.job_id, pd.plugin_uuid, rng.choice((0, 1, 2)))
                        )
    if reevals:
        base = reserve_reeval_ids(conn, len(reevals) + 1)
        ids = list(range(base, base + len(reevals)))
        rng.shuffle(ids)
        for (jid, pu, code), rid in zip(reevals, ids, strict=True):
            add_reeval(
                conn,
                jid,
                pu,
                code=code,
                detail=f"re{rid}",
                by=admin_id,
                reeval_id=rid,
                at=at + timedelta(seconds=rng.randint(0, 86_400)),
            )
    return out


# ----- spies and locks ---------------------------------------------------------


class RoleSpy(StatementSpy):
    """M8's statement spy, also recording the login role of each statement's
    connection (``roles[i]`` belongs to ``statements[i]``)."""

    def __init__(self) -> None:
        super().__init__()
        self.roles: list[str] = []

    def install(self, monkeypatch: Any) -> None:
        spy = self
        real_execute = psycopg.Cursor.execute
        real_executemany = psycopg.Cursor.executemany
        real_server = psycopg.ServerCursor.execute

        def _record(cur: Any, query: Any) -> None:
            if isinstance(query, bytes):
                text = query.decode()
            elif isinstance(query, str):
                text = query
            else:
                text = str(query.as_string(cur.connection))
            spy.statements.append(text)
            spy.roles.append(str(cur.connection.info.user))

        def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
            _record(cur, query)
            return real_execute(cur, query, params, **kw)

        def executemany(cur: Any, query: Any, params_seq: Any, **kw: Any) -> Any:
            _record(cur, query)
            return real_executemany(cur, query, params_seq, **kw)

        def server_execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
            _record(cur, query)
            return real_server(cur, query, params, **kw)

        monkeypatch.setattr(psycopg.Cursor, "execute", execute)
        monkeypatch.setattr(psycopg.Cursor, "executemany", executemany)
        monkeypatch.setattr(psycopg.ServerCursor, "execute", server_execute)

    def by_role(self, role: str) -> list[str]:
        return [
            s for s, r in zip(self.statements, self.roles, strict=True) if r == role
        ]


WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE", "COPY", "TRUNCATE"})
DDL_VERBS = frozenset(
    {"CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "COMMENT"}
)


def verb(statement: str) -> str:
    """The first keyword after any leading WITH … AS (…) list is not parsed:
    a CTE statement reports ``WITH``; callers that need the main verb search
    the text."""
    words = statement.strip().split(None, 1)
    return words[0].upper() if words else ""


@contextmanager
def holding_reeval_lock(server: PgServer, scan_id: UUID) -> Iterator[Conn]:
    """Another session holding M8's per-scan re-evaluation lock (taken by
    M8's own ``reeval.lock_scan``, so the key cannot drift from M8's) until
    the block ends; then rolled back."""
    with tx_conn(server, "bitscan_app") as conn:
        m8_reeval.lock_scan(conn, scan_id)
        yield conn


# ----- checksums ---------------------------------------------------------------

KEYS = {
    "agent": "agent_id",
    "agent_tag": "agent_id, tag",
    "agent_ip_seen": "agent_id, ip",
    "agent_package": "agent_id, package_id",
    "os_info": "agent_id",
    "package": "package_id",
    "inventory_snapshot": "snapshot_id",
    "enrollment_token": "token_id",
    "enrollment_request": "request_id",
    "user_token": "token_id",
    "app_user": "user_id",
    "family": "family_id",
    "policy": "policy_id",
    "plugin": "plugin_uuid",
    "policy_plugin": "policy_id, plugin_uuid",
    "bit_import": "import_id",
    "scan_schedule": "schedule_id",
    "setting": "key",
    "system_schedule": "job_kind",
    "task": "task_id",
    "scan": "scan_id",
    "scan_job": "job_id",
    "scan_result": "job_id, plugin_uuid, job_created_at",
    "scan_result_reeval": "reeval_id",
    "audit_log": "audit_id",
}

NEVER_DELETED = (
    "agent",
    "agent_tag",
    "os_info",
    "agent_package",
    "enrollment_token",
    "family",
    "policy",
    "plugin",
    "policy_plugin",
    "bit_import",
    "scan_schedule",
    "setting",
    "system_schedule",
    "task",
    "app_user",
)
RETENTION_TABLES = (
    "scan",
    "scan_job",
    "scan_result",
    "scan_result_reeval",
    "inventory_snapshot",
    "enrollment_request",
    "user_token",
    "audit_log",
    "package",
)


def checksum(conn: Conn, table: str) -> str:
    """md5 over every row of a table in key order; any one-byte change of
    any row changes it."""
    query = sql.SQL(
        "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY {k}), '')) FROM {t} t"
    ).format(k=sql.SQL(KEYS[table]), t=sql.Identifier(table))
    row = conn.execute(query).fetchone()
    assert row is not None
    return str(row[0])


def checksums(conn: Conn, tables: Sequence[str] = NEVER_DELETED) -> dict[str, str]:
    return {t: checksum(conn, t) for t in tables}


# ----- inventory, enrolment and token rows -------------------------------------


def package(conn: Conn, name: str | None = None) -> int:
    return int(
        f9.one(
            conn,
            "INSERT INTO package (name, version, architecture, source_name)"
            " VALUES (%s, '1.0-1', 'amd64', NULL) RETURNING package_id",
            (name or f"m11-pkg-{secrets.token_hex(4)}",),
        )
    )


def inventory(
    conn: Conn, agent_id: UUID, packages: Sequence[int], *, at: datetime
) -> None:
    """os_info and agent_package for one agent (the G2 data, TS §3.4)."""
    conn.execute(
        "INSERT INTO os_info (agent_id, os_id, os_version_id, os_pretty_name, raw,"
        " collected_at) VALUES (%s, 'ubuntu', '24.04', 'Ubuntu 24.04 LTS', %s, %s)",
        (agent_id, Jsonb({"id": "ubuntu"}), at),
    )
    for pid in packages:
        conn.execute(
            "INSERT INTO agent_package (agent_id, package_id, status, first_seen_at,"
            " last_seen_at) VALUES (%s, %s, 'install ok installed', %s, %s)",
            (agent_id, pid, at, at),
        )


def snapshot(conn: Conn, agent_id: UUID, collected_at: datetime) -> int:
    return int(
        f9.one(
            conn,
            "INSERT INTO inventory_snapshot (agent_id, list_sha256, package_count,"
            " collected_at) VALUES (%s, %s, 1, %s) RETURNING snapshot_id",
            (agent_id, secrets.token_hex(32), collected_at),
        )
    )


def enrolment_token(conn: Conn, *, at: datetime) -> int:
    return int(
        f9.one(
            conn,
            "INSERT INTO enrollment_token (token_hash, max_uses, expires_at,"
            " created_by, created_at) VALUES (%s, 10, %s, 1, %s) RETURNING token_id",
            (secrets.token_hex(32), at + timedelta(days=30), at - timedelta(days=1)),
        )
    )


def request(
    conn: Conn,
    agent_id: UUID,
    token_id: int,
    *,
    requested_at: datetime,
    decision: str | None = None,
    decided_at: datetime | None = None,
) -> int:
    return int(
        f9.one(
            conn,
            "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id,"
            " hostname, machine_id, agent_version, new_token_hash, token_expires_at,"
            " source_ip, requested_at, decision, decided_by, decided_at)"
            " VALUES ('new', %s, %s, 'm11-req', %s, '1.0.0', %s, %s, '192.0.2.11',"
            " %s, %s, %s, %s)"
            " RETURNING request_id",
            (
                agent_id,
                token_id,
                secrets.token_hex(16),
                secrets.token_hex(32),
                requested_at + timedelta(days=365),
                requested_at,
                decision,
                None if decision is None else 1,
                decided_at,
            ),
        )
    )


def token_row(
    conn: Conn,
    user_id: int,
    *,
    kind: str = "session",
    expires_at: datetime,
    created_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> int:
    """A user_token row by its times; returns token_id (no usable token kept)."""
    return int(
        f9.one(
            conn,
            "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
            " expires_at, created_at, revoked_at)"
            " VALUES (%s, %s, %s, false, %s, %s, %s) RETURNING token_id",
            (
                user_id,
                kind,
                secrets.token_hex(32),
                expires_at,
                created_at or expires_at - timedelta(days=30),
                revoked_at,
            ),
        )
    )


def inventory_job(
    conn: Conn,
    agent_id: UUID,
    *,
    created_at: datetime,
    finished_at: datetime | None,
    state: str = "completed",
) -> UUID:
    jid = uuid4()
    conn.execute(
        "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
        " pickup_by, dispatched_at, finished_at) VALUES (%s, 'inventory', %s,"
        " CAST(%s AS scan_state), %s, %s, %s, %s, %s)",
        (
            jid,
            agent_id,
            state,
            Jsonb({"job_id": str(jid), "agent_id": str(agent_id), "kind": "inventory"}),
            created_at,
            created_at + timedelta(hours=24),
            None if state == "queued" else created_at + timedelta(minutes=1),
            finished_at,
        ),
    )
    return jid


# ----- the aged retention world (relative to one now) --------------------------

# The rule ages (TS §5.3 L1049; #150 (a)-(e)). Labels: "inside" = well
# inside retention, "at" = exactly at the cutoff, "past" = 1 µs older,
# "old" = far older.
MICRO = timedelta(microseconds=1)
AGES = {
    "scan": timedelta(days=400),
    "inventory_job": timedelta(days=30),
    "snapshot": timedelta(days=180),
    "request": timedelta(days=90),
    "token": timedelta(days=90),
}


def offsets(age: timedelta) -> dict[str, timedelta]:
    return {
        "inside": age - timedelta(days=1),
        "at": age,
        "past": age + MICRO,
        "old": age + timedelta(days=100),
    }


@dataclass
class AgedWorld:
    now: datetime
    pol: Pol
    agents: list[AgentRow]
    rows: dict[tuple[str, str], Any] = field(default_factory=dict)
    scan_jobs: dict[str, list[UUID]] = field(default_factory=dict)

    def key(self, rule: str, label: str) -> Any:
        return self.rows[(rule, label)]


def aged_world(conn: Conn, now: datetime) -> AgedWorld:
    """Rows on both sides of every cutoff relative to ``now`` (as owner):

    - ``scan``: one scan per label, each with an original job (created with
      the scan), a retry created 32 days later, results in both (in old-month
      partitions created here) and one re-evaluation row;
    - ``inventory_job``: finished per label, plus ``unfinished`` (created
      far past, never finished) and ``compliance`` (a compliance job of the
      "inside" scan, finished long ago);
    - ``snapshot``: collected per label;
    - ``request``: decided per label, plus ``pending`` (requested far past,
      no decision);
    - ``token``: expired per label, plus ``inside_89`` (expired 89 days ago),
      ``revoked_live`` (revoked yesterday, expires in 300 days),
      ``live_api`` (an API token expiring in 300 days) and ``revoked_past``
      (revoked, expired 91 days ago);
    - ``package``: ``referenced`` (in agent_package) and ``unreferenced``,
      ``unreferenced2``; os_info and agent_package for both agents (G2).
    """
    pol = make_policy(conn, 2)
    agents = [host(conn, at=now), host(conn, at=now)]
    world = AgedWorld(now, pol, agents)
    admin = make_user(conn, "admin", at=now)
    for label, off in offsets(AGES["scan"]).items():
        created = now - off
        ensure_partition(conn, created)
        ensure_partition(conn, created + timedelta(days=32))
        sid = scan(
            conn,
            pol,
            [a.agent_id for a in agents],
            created_at=created,
            state="completed",
        )
        world.rows[("scan", label)] = sid
        ids: list[UUID] = []
        for a in agents:
            orig = job(conn, sid, a.agent_id, pol, state="partial", created_at=created)
            retry = job(
                conn,
                sid,
                a.agent_id,
                pol,
                pol.plugins[1:],
                state="completed",
                created_at=created + timedelta(days=32),
                retry_of=orig.job_id,
            )
            result(conn, orig, pol, pol.plugins[0], code=0, stdout=OUT, stderr=ERR)
            result(conn, retry, pol, pol.plugins[1], code=1, stdout=OUT)
            add_reeval(conn, orig.job_id, pol.plugins[0].plugin_uuid, code=1, by=admin)
            ids += [orig.job_id, retry.job_id]
        world.scan_jobs[label] = ids
    inside_scan = world.key("scan", "inside")
    ensure_partition(conn, now)
    for label, off in offsets(AGES["inventory_job"]).items():
        fin = now - off
        world.rows[("inventory_job", label)] = inventory_job(
            conn,
            agents[0].agent_id,
            created_at=fin - timedelta(minutes=5),
            finished_at=fin,
        )
    world.rows[("inventory_job", "unfinished")] = inventory_job(
        conn,
        agents[0].agent_id,
        created_at=now - timedelta(days=200),
        finished_at=None,
        state="dispatched",
    )
    world.rows[("inventory_job", "compliance")] = world.scan_jobs["inside"][0]
    for label, off in offsets(AGES["snapshot"]).items():
        world.rows[("snapshot", label)] = snapshot(conn, agents[0].agent_id, now - off)
    tok = enrolment_token(conn, at=now)
    for label, off in offsets(AGES["request"]).items():
        world.rows[("request", label)] = request(
            conn,
            agents[1].agent_id,
            tok,
            requested_at=now - off - timedelta(hours=1),
            decision="approved" if label != "old" else "rejected",
            decided_at=now - off,
        )
    world.rows[("request", "pending")] = request(
        conn, agents[1].agent_id, tok, requested_at=now - timedelta(days=1000)
    )
    uid = make_user(conn, "operator", at=now)
    for label, off in offsets(AGES["token"]).items():
        world.rows[("token", label)] = token_row(conn, uid, expires_at=now - off)
    world.rows[("token", "inside_89")] = token_row(
        conn, uid, expires_at=now - timedelta(days=89)
    )
    world.rows[("token", "revoked_live")] = token_row(
        conn,
        uid,
        expires_at=now + timedelta(days=300),
        created_at=now - timedelta(days=65),
        revoked_at=now - timedelta(days=1),
    )
    world.rows[("token", "live_api")] = token_row(
        conn,
        uid,
        kind="api",
        expires_at=now + timedelta(days=300),
        created_at=now - timedelta(days=65),
    )
    world.rows[("token", "revoked_past")] = token_row(
        conn,
        uid,
        expires_at=now - timedelta(days=91),
        revoked_at=now - timedelta(days=200),
    )
    referenced = package(conn)
    world.rows[("package", "referenced")] = referenced
    world.rows[("package", "unreferenced")] = package(conn)
    world.rows[("package", "unreferenced2")] = package(conn)
    for a in agents:
        inventory(conn, a.agent_id, [referenced], at=now - timedelta(days=1))
    assert inside_scan is not None
    return world


PRESENT_SQL = {
    "scan": "SELECT EXISTS (SELECT 1 FROM scan WHERE scan_id = %s)",
    "inventory_job": "SELECT EXISTS (SELECT 1 FROM scan_job WHERE job_id = %s)",
    "snapshot": (
        "SELECT EXISTS (SELECT 1 FROM inventory_snapshot WHERE snapshot_id = %s)"
    ),
    "request": (
        "SELECT EXISTS (SELECT 1 FROM enrollment_request WHERE request_id = %s)"
    ),
    "token": "SELECT EXISTS (SELECT 1 FROM user_token WHERE token_id = %s)",
    "package": "SELECT EXISTS (SELECT 1 FROM package WHERE package_id = %s)",
}


def present(conn: Conn, world: AgedWorld) -> dict[tuple[str, str], bool]:
    """Which labelled rows still exist."""
    return {
        k: bool(f9.one(conn, PRESENT_SQL[k[0]], (v,))) for k, v in world.rows.items()
    }


def scan_remains(conn: Conn, scan_id: UUID, job_ids: Sequence[UUID]) -> dict[str, int]:
    """What is left of a scan: its row, its jobs, results in any partition,
    re-evaluation rows."""
    return {
        "scan": int(
            f9.one(conn, "SELECT count(*) FROM scan WHERE scan_id = %s", (scan_id,))
        ),
        "scan_job": int(
            f9.one(
                conn,
                "SELECT count(*) FROM scan_job WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
        ),
        "scan_result": int(
            f9.one(
                conn,
                "SELECT count(*) FROM scan_result WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
        ),
        "scan_result_reeval": int(
            f9.one(
                conn,
                "SELECT count(*) FROM scan_result_reeval WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
        ),
    }


# Probe columns of the future-row guard (#150 (j); lead correction
# 2026-11-08: the tokens step reads user_token.created_at).
FUTURE_PROBES = {
    "scans": "scan.created_at",
    "inventory_jobs": "scan_job.finished_at (inventory)",
    "snapshots": "inventory_snapshot.collected_at",
    "requests": "enrollment_request.decided_at",
    "tokens": "user_token.created_at",
}


@contextmanager
def future_row(
    server: PgServer, step: str, now: datetime, ahead: timedelta
) -> Iterator[Any]:
    """One row dated ``now + ahead`` in the probe column of ``step``, removed
    again (as owner) when the block ends, so other tests are not skipped."""
    with owner(server) as conn:
        when = now + ahead
        a = host(conn, at=now)
        undo: list[tuple[str, Any]] = []
        if step == "scans":
            pol = make_policy(conn, 1)
            key: Any = scan(conn, pol, [a.agent_id], created_at=when)
            undo.append(("DELETE FROM scan WHERE scan_id = %s", key))
        elif step == "inventory_jobs":
            key = inventory_job(conn, a.agent_id, created_at=now, finished_at=when)
            undo.append(("DELETE FROM scan_job WHERE job_id = %s", key))
        elif step == "snapshots":
            key = snapshot(conn, a.agent_id, when)
            undo.append(("DELETE FROM inventory_snapshot WHERE snapshot_id = %s", key))
        elif step == "requests":
            tok = enrolment_token(conn, at=now)
            key = request(
                conn,
                a.agent_id,
                tok,
                requested_at=now,
                decision="approved",
                decided_at=when,
            )
            undo.append(("DELETE FROM enrollment_request WHERE request_id = %s", key))
        elif step == "tokens":
            uid = make_user(conn, "viewer", at=now)
            key = token_row(
                conn, uid, created_at=when, expires_at=when + timedelta(days=30)
            )
            undo.append(("DELETE FROM user_token WHERE token_id = %s", key))
        else:
            raise ValueError(step)
        try:
            yield key
        finally:
            for statement, arg in undo:
                conn.execute(statement, (arg,))


# ----- the audit chain with chosen times ---------------------------------------


def audit_chain(
    server: PgServer,
    ats: Sequence[datetime],
    *,
    actor: str = "m11-test",
    action: str = "m11.aged",
    detail: Mapping[str, object] | None = None,
) -> list[int]:
    """Append one entry per ``ats`` value, in order, to the existing chain, as
    bitscan_app under the chain lock, each hashed exactly as M1's
    ``compute_row_hash`` and stored with ``at`` = the chosen time; returns
    the new ids in order. ``verify_chain()`` accepts the result.

    Written in one transaction with COPY (25,000 entries in seconds); app
    writers wait on the chain lock meanwhile, so the chain cannot fork."""
    with tx_conn(server, "bitscan_app") as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")
        head = conn.execute(
            "SELECT row_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1"
        ).fetchone()
        prev = GENESIS_PREV_HASH if head is None else str(head[0])
        detail_text: str | None = None
        if detail is not None:
            detail_text = str(
                f9.one(
                    conn, "SELECT CAST(%s AS jsonb)::text", (json.dumps(dict(detail)),)
                )
            )
        ids = sorted(
            int(r[0])
            for r in conn.execute(
                "SELECT nextval('audit_log_audit_id_seq') FROM generate_series(1, %s)",
                (len(ats),),
            ).fetchall()
        )
        rows = []
        for audit_id, at in zip(ids, ats, strict=True):
            at_text = ztext(at)
            row_hash = m1_row_hash(
                prev, HashInput(audit_id, actor, action, None, detail_text, at_text)
            )
            rows.append(
                (audit_id, actor, action, None, detail_text, at_text, prev, row_hash)
            )
            prev = row_hash
        with conn.cursor().copy(
            "COPY audit_log (audit_id, actor, action, target, detail, at, prev_hash,"
            " row_hash) FROM STDIN"
        ) as cp:
            for r in rows:
                cp.write_row(r)
        conn.commit()
    return ids


def audit_ids(conn: Conn) -> list[int]:
    return [
        int(r[0])
        for r in conn.execute("SELECT audit_id FROM audit_log ORDER BY audit_id")
    ]


def checkpoints(conn: Conn, after: int = 0) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT audit_id, actor, target, detail FROM audit_log"
        " WHERE action = 'audit.checkpoint' AND audit_id > %s ORDER BY audit_id",
        (after,),
    ).fetchall()
    return [
        {"audit_id": r[0], "actor": r[1], "target": r[2], "detail": r[3]} for r in rows
    ]


def row_hash_of(conn: Conn, audit_id: int) -> str:
    return str(
        f9.one(conn, "SELECT row_hash FROM audit_log WHERE audit_id = %s", (audit_id,))
    )


def shipped(value: int | None) -> Callable[[], int | None]:
    """A ``shipped_through`` double: the shipper's cursor fixed at ``value``."""
    return lambda: value
