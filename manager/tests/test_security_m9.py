"""TP-M9-18: the M9 security and boundary suite (tester-m9b; CHK-M9-270 to
-276; G69).

Expected values: TS §3.3 L210–L213 and §6.2 L1129 (jobs only from the
catalog; no ad-hoc command; no inventory switch), §2.2 L111 (pull-only),
§5.2 L1005–L1013 (bitscan_app grants), §5.3 L1052, §8.4 L1287 (no plugin
output or command in logs or audit), §8.1 L1239, L1252; the security
invariants in .claude/rules/security-invariants.md; REQ-212, REQ-227 (4),
REQ-229, REQ-230.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.services.jobs import queue
from bitscan_manager.services.jobs.cancel import cancel_scan
from bitscan_manager.services.jobs.targets import parse_target
from bitscan_manager.services.scheduler import schedules_admin as sa
from bitscan_manager.services.scheduler.scan_schedules import run_due_schedules
from bitscan_manager.services.scheduler.sweep import run_sweep

from . import scan_pg_fixtures as f
from .agent_sim import SCANS, ApiEnv, api_env, batch, item
from .conftest import PgServer, own_migrated_server
from .evaluator_pg_fixtures import result_partitions
from .test_contract_agent import OPENAPI

BM = Path(__file__).resolve().parents[1] / "bitscan_manager"
PURE = [
    "services/jobs/states.py",
    "services/jobs/scan_state.py",
    "services/jobs/targets.py",
    "services/jobs/build.py",
    "services/jobs/intake_plan.py",
    "services/scheduler/cron.py",
    "api/user/idempotency.py",
]
ROUTES = ["api/user/scans.py", "api/user/scan_schedules.py"]
M9_ACTIONS = {
    "scan.create",
    "scan.cancel",
    "scan_schedule.create",
    "scan_schedule.update",
    "scan_schedule.delete",
    "agent.result_refused",
    "alert.result_409_flood",
}
COMMAND_WORDS = {
    "execute",
    "plugins",
    "command",
    "payload",
    "eval_spec",
    "operator",
    "expected",
    "expected_result",
    "script",
    "cmd",
}


def imports_of(rel: str) -> set[str]:
    tree = ast.parse((BM / rel).read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


# ------------------------------------------------------------ CHK-M9-271


@pytest.mark.parametrize("rel", PURE)
def test_pure_modules_import_no_database_repository_or_api_code(rel: str) -> None:
    """REQ-206 (5) and the M9 rule "the pure modules take plain values": no
    import of db, repositories, api (other than the idempotency store's own
    package), psycopg or the runtime."""
    bad = {
        m
        for m in imports_of(rel)
        if m.startswith(
            (
                "psycopg",
                "bitscan_manager.db",
                "bitscan_manager.repositories",
                "bitscan_manager.runtime",
            )
        )
        or (m.startswith("bitscan_manager.api") and not rel.startswith("api/"))
    }
    assert bad == set(), bad


def test_importing_the_pure_modules_loads_no_database_code() -> None:
    """TASK-204 r1: importing any pure jobs module (through its package)
    loads neither psycopg nor a repository, in a fresh interpreter."""
    mods = [
        "bitscan_manager." + p.removesuffix(".py").replace("/", ".")
        for p in PURE
        if not p.startswith("api/")
    ]
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in mods)
        + "bad = sorted(m for m in sys.modules if m.startswith(('psycopg',"
        " 'bitscan_manager.repositories', 'bitscan_manager.db')))\n"
        "print(bad)\n"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout


@pytest.mark.parametrize("rel", ROUTES)
def test_the_m9_routes_import_no_repository(rel: str) -> None:
    """REQ-221 (5), api → services → repositories."""
    assert not {
        m for m in imports_of(rel) if "repositories" in m or m.startswith("psycopg")
    }


# ------------------------------------------------------------ CHK-M9-274


def test_only_the_builder_and_two_repositories_write_a_compliance_payload() -> None:
    """REQ-212 (3): the INSERTs into scan_job are in repositories/jobs.py
    (inventory only), scan_queue.py and job_sweep.py; a compliance Job body
    ("kind": "compliance" with plugins) is composed only in services/jobs/
    build.py and the scan_queue.py SQL. No other file writes scan_job."""
    inserts, bodies = set(), set()
    for path in BM.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(BM).as_posix()
        if re2.search(r"INSERT\s+INTO\s+scan_job\b", text):
            inserts.add(rel)
        if re2.search(r"""["']kind["']\s*[:,]\s*["']compliance["']""", text) and (
            "plugins" in text
        ):
            bodies.add(rel)
    assert inserts == {
        "repositories/jobs.py",
        "repositories/scan_queue.py",
        "repositories/job_sweep.py",
    }, inserts
    jobs_sql = (BM / "repositories/jobs.py").read_text(encoding="utf-8")
    for m in re2.finditer(r"INSERT\s+INTO\s+scan_job[^;]*?VALUES[^)]*\)", jobs_sql):
        assert "compliance" not in m.group(0)
    assert bodies <= {"services/jobs/build.py", "repositories/scan_queue.py"}, bodies
    assert "services/jobs/build.py" in bodies


# ------------------------------------------------------------ CHK-M9-276


def test_no_m9_route_takes_command_text_or_names_inventory() -> None:
    """REQ-212 (1), (4), REQ-229 (4), TS §6.2 L1129: the seven M9 operations
    are exactly POST /scans, POST /scans/{id}/cancel and the five
    /scan-schedules operations; their request bodies are closed
    (additionalProperties false) and hold no command-like property; no M9
    path, parameter or property names inventory or a disable switch."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    m9 = {
        (p, m)
        for p, ops in doc["paths"].items()
        for m in ops
        if p.startswith(("/api/v1/scans", "/api/v1/scan-schedules"))
    }
    assert m9 == {
        ("/api/v1/scans", "post"),
        ("/api/v1/scans/{id}/cancel", "post"),
        ("/api/v1/scan-schedules", "post"),
        ("/api/v1/scan-schedules", "get"),
        ("/api/v1/scan-schedules/{id}", "get"),
        ("/api/v1/scan-schedules/{id}", "patch"),
        ("/api/v1/scan-schedules/{id}", "delete"),
    }, m9
    comps = doc["components"]["schemas"]
    for path, method in m9:
        op = doc["paths"][path][method]
        names = [p["name"].lower() for p in op.get("parameters", [])]
        assert not [
            n for n in names if "inventory" in n or "disable" in n or "skip" in n
        ]
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body is None:
            continue
        ref = body["schema"]["$ref"].rsplit("/", 1)[1]
        schema = comps[ref]
        assert schema.get("additionalProperties") is False, ref
        props = {k.lower() for k in schema["properties"]}
        assert not props & COMMAND_WORDS, (ref, props & COMMAND_WORDS)
        assert not [k for k in props if "inventory" in k], ref


# ------------------------------------------------------------ PostgreSQL rows

pg = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sec-m9")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


# ------------------------------------------------------------ CHK-M9-272


@pg
def test_grant_probes_on_results_jobs_and_scans(env: ApiEnv, tmp_path: Path) -> None:
    """REQ-230 (3), TS §5.2 L1005–L1013, TS §8.3 grant probes: as bitscan_app,
    UPDATE and DELETE of scan_result (parent, the current partition, the
    default partition) are refused; UPDATE of scan_job agent_id, scan_id,
    payload, eval_spec, retry_of and of scan policy_id, policy_version,
    target are refused; DELETE of scan and scan_job is refused."""
    cat = f.make_catalog(env.db, env.clock, tmp_path)
    pol = cat.policy(1)
    a = env.agent()
    with f.owner(env.server) as o:
        s = f.owner_scan(o, pol, state="running")
        j = f.owner_job(o, s, a.agent_id, pol, state="running")
        f.owner_result(o, j, pol, pol.plugins[0])
        parts = result_partitions(o)
    default = [p for p in parts if p.endswith("default")]
    targets = ["scan_result", *default, parts[0]]
    probes: list[tuple[str, tuple[Any, ...]]] = []
    for t in targets:
        probes.append((f"UPDATE {t} SET eval_code = 0 WHERE job_id = %s", (j.job_id,)))  # noqa: S608
        probes.append((f"DELETE FROM {t} WHERE job_id = %s", (j.job_id,)))  # noqa: S608
    job_cols: list[tuple[str, object]] = [
        ("agent_id", str(a.agent_id)),
        ("scan_id", str(s)),
        ("payload", "{}"),
        ("eval_spec", "{}"),
        ("retry_of", None),
    ]
    for col, val in job_cols:
        q = f"UPDATE scan_job SET {col} = %s WHERE job_id = %s"  # noqa: S608
        probes.append((q, (val, j.job_id)))
    scan_cols: list[tuple[str, object]] = [
        ("policy_id", pol.policy_id),
        ("policy_version", 7),
        ("target", "{}"),
    ]
    for col, val in scan_cols:
        q = f"UPDATE scan SET {col} = %s WHERE scan_id = %s"  # noqa: S608
        probes.append((q, (val, s)))
    probes.append(("DELETE FROM scan_job WHERE job_id = %s", (j.job_id,)))
    probes.append(("DELETE FROM scan WHERE scan_id = %s", (s,)))
    for q, args in probes:
        with (
            f.app(env.server) as c,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            c.execute(q, args)


# ------------------------------------------------------------ CHK-M9-270, -273


def _set_columns(statement: str, table: str) -> set[str] | None:
    m = re2.search(
        rf"(?is)^\s*UPDATE\s+{table}(?:\s+\w+)?\s+SET\s+(.*?)\s+(?:FROM|WHERE)\s",
        statement,
    )
    if m is None:
        return None
    cols = set()
    depth, cur = 0, ""
    for ch in m.group(1):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            cols.add(cur.split("=", 1)[0].strip().split(".")[-1])
            cur = ""
        else:
            cur += ch
    cols.add(cur.split("=", 1)[0].strip().split(".")[-1])
    return cols


@pg
def test_every_m9_path_writes_only_progress_columns_and_leaks_no_canary(
    env: ApiEnv,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-230 (2), (5), REQ-227 (4), TS §5.3 L1052, CHK-M9-270, -273: one
    flow through every M9 path (POST /scans, pull, start notice, a result
    batch, a duplicate, a refused batch, the sweep ending a job and making
    its retry, the scan refresh, cancel, schedule create and a scheduled
    run) with a canary in execute, expected, stdout and stderr. A statement
    spy sees no UPDATE or DELETE of scan_result, UPDATEs of scan_job only on
    state, dispatched_at, started_at, deadline_at, finished_at, and of scan
    only on state, finished_at; the canary is in no log record, no audit
    detail and no answer other than a pull (which carries the command)."""
    caplog.set_level(logging.DEBUG)
    cat = f.make_catalog(env.db, env.clock, tmp_path)
    loud = f.CANARY
    pol = cat.policy(
        [
            f.plugin(execute=f"printf '%s' {loud}", expected=loud),
            f.plugin(execute="echo two"),
        ]
    )
    a, b = env.agent(), env.agent()
    spy = f.StatementSpy()
    spy.install(monkeypatch)
    uid, tok = env.caller("operator")
    answers: list[str] = []
    r = env.call(
        "POST",
        SCANS,
        tok,
        body={
            "policy_id": pol.policy_id,
            "target": {"agents": [str(a.agent_id), str(b.agent_id)]},
        },
    )
    answers.append(r.text)
    assert r.status_code == 202, r.text
    sid = UUID(r.json()["scan_id"])
    (ja,) = a.pulled()
    (jb,) = b.pulled()
    env.clock.advance(seconds=5)
    answers.append(a.start(ja["job_id"]).text)
    for _ in range(2):
        env.clock.advance(seconds=5)
        answers.append(
            a.post(
                ja["job_id"],
                batch(item(pol.uuids[0], stdout=loud, stderr=loud), final=False),
            ).text
        )
    env.clock.advance(seconds=5)
    answers.append(a.post(ja["job_id"], batch(item(uuid4(), stdout=loud))).text)
    env.clock.advance(seconds=5)
    answers.append(b.start(jb["job_id"]).text)
    later = env.clock.advance(hours=2)
    out = run_sweep(env.db, later)
    assert out.failed_steps == [] and out.retries == 2
    with env.db.transaction() as tx:
        cancel_scan(tx, scan_id=sid, actor=f"user:{uid}", now=later)
    with env.db.transaction() as tx:
        sa.create(
            tx,
            name="sec",
            policy_id=pol.policy_id,
            target={"agents": [str(a.agent_id)]},
            cron="0 3 * * *",
            user_id=uid,
            now=later,
        )
    due = later.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tick = run_due_schedules(env.db, due, lambda: None)
    assert tick.queued == 1
    with env.db.transaction() as tx:
        queue.queue_scan(
            tx,
            policy_id=pol.policy_id,
            target=parse_target({"all": True}),
            trigger="manual",
            schedule_id=None,
            requested_by=uid,
            actor=f"user:{uid}",
            via_api_token=False,
            now=due,
        )
    sts = list(spy.statements)
    monkeypatch.undo()
    for st in sts:
        up = st.lstrip().upper()
        assert not re2.search(r"(?is)^\s*(UPDATE|DELETE\s+FROM)\s+scan_result", st), st
        assert not up.startswith("TRUNCATE"), st
        jobs = _set_columns(st, "scan_job")
        if jobs is not None:
            assert jobs <= {
                "state",
                "dispatched_at",
                "started_at",
                "deadline_at",
                "finished_at",
            }, (jobs, st)
        scans = _set_columns(st, "scan")
        if scans is not None:
            assert scans <= {"state", "finished_at"}, (scans, st)
    assert any(_set_columns(s, "scan_job") for s in sts)
    assert any(_set_columns(s, "scan") for s in sts)
    assert f.canary_hits(f.log_texts(caplog.records)) == []
    assert f.canary_hits(answers) == []
    with env.conn() as c:
        m9 = [e for e in f.audit_after(c, 0) if e["action"] in M9_ACTIONS]
    assert {e["action"] for e in m9} >= {
        "scan.create",
        "scan.cancel",
        "scan_schedule.create",
        "agent.result_refused",
    }
    # The import alert carries the changed Execute by spec (TS §8.4); M9's
    # own entries carry no command, expected value or output.
    assert f.canary_hits([json.dumps(e["detail"]) for e in m9]) == []
