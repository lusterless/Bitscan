"""TP-M11-15: the M11 security suite (G83; tester-m11g; CHK-M11-240 to -250).

Written at the M11 gate as one file. Its rows were first tested inside the
task suites (TASK-232 to TASK-245); this file is the whole-milestone check
and reuses their builders, not their tests.

Expected values come from the spec and the approved answers, not the code:
TS §2.2 L114 and §4.5 L603 (results immutable; re-evaluation adds rows, through
the admin route only), §3.3 (no ad-hoc command), §5.2 L1001–L1013 and §5.3
L1049–L1054 (bitscan_retention deletes only the retention tables, never
inventory; a checkpoint precedes the audit delete; no results in logs), §6
(bsa_ and bse_ never on user routes, bsu_ and bsk_ never on agent routes),
§6.2 L1083, L1086, L1123, L1125 (raw output for operator and admin only;
re-evaluate is a sensitive action: admin, TOTP-verified session, no API
token), §5.3 L1053 (sensitive actions refused after 15 minutes of sink
outage), §8.1 (parameterised SQL, RE2), §8.4 (no output, command or token in
logs); `.claude/rules/security-invariants.md`; REQ-268, REQ-271 to REQ-273,
REQ-275, REQ-278; the M11 rules in `work/tasks.md` (frozen files, layering,
"nothing writes scan_result_reeval except M8's reevaluate_scan through
TASK-243"); #144 (a), (b), #147, #148.

The frozen-file pins are the sha256 of each file at main ``6efe0fb`` (taken
with ``git show 6efe0fb:<path> | sha256sum`` on 2026-11-09), so the check
needs no git in the test environment.
"""

from __future__ import annotations

import ast
import csv
import dataclasses
import hashlib
import io
import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.services.scheduler.runner import SchedulerRunner

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .agent_sim import ApiEnv, SimAgent, api_env
from .conftest import PgServer, own_migrated_server
from .test_auth_dependencies import api_routes, markers
from .test_reevaluate_api_pg import build, new_entries, post, problem, state
from .test_results_api_pg import BASE_AT, OUTPUT_KEYS, VIEWER_KEYS, get, walk
from .test_retention_pg import STEPS, old_at

MANAGER = Path(__file__).resolve().parents[1]
BM = MANAGER / "bitscan_manager"
V1 = "/api/v1"

# ---------------------------------------------------------------- the M11 code

M11_ROUTES = ("api/user/scan_views.py", "api/user/reevaluate.py")
M11_REPOS = (
    "repositories/scan_reads.py",
    "repositories/result_reads.py",
    "repositories/retention.py",
    "repositories/retention_audit.py",
)
M11_SERVICES = (
    "services/jobs/results_view.py",
    "services/jobs/results_read.py",
    "services/jobs/scan_views.py",
    "services/retention/__init__.py",
    "services/retention/rules.py",
    "services/retention/task.py",
)
M11_NEW = (*M11_ROUTES, *M11_REPOS, *M11_SERVICES)
RETENTION_CODE = (
    "repositories/retention.py",
    "repositories/retention_audit.py",
    "services/retention/__init__.py",
    "services/retention/rules.py",
    "services/retention/task.py",
)
# TS §5.2 L1002–L1006: what bitscan_retention may delete.
RETENTION_TABLES = {
    "scan",
    "scan_job",
    "scan_result",
    "scan_result_reeval",
    "inventory_snapshot",
    "enrollment_request",
    "user_token",
    "audit_log",
    "package",
}

M11_OPS = {
    ("GET", V1 + "/scans"),
    ("GET", V1 + "/scans/{id}"),
    ("GET", V1 + "/scans/{id}/results"),
    ("GET", V1 + "/scans/{id}/results.csv"),
    ("GET", V1 + "/agents/{id}/scans"),
    ("POST", V1 + "/scans/{id}/reevaluate"),
}
# TS §6.2: every scan operation of the app after M11 (M9 + M11).
SCAN_OPS = {
    ("POST", V1 + "/scans"),
    ("POST", V1 + "/scans/{id}/cancel"),
    *M11_OPS,
}
COMMAND_WORDS = {"execute", "command", "commands", "cmd", "script", "shell"}

# sha256 at 6efe0fb (M1, M2, M5, M8, M9 files frozen for M11; the migrations).
FROZEN = {
    "api/user/scan_schedules.py": (
        "0bd6c34d3d638eff6c632a21df6a9da62285d39b8a4a6e7048f27ca40e03cd32"
    ),
    "api/user/scans.py": (
        "023c333faa270b04b73a3ac2d407c103e5fad2586764a254f4fa5a32f8ed782a"
    ),
    "auth/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "auth/api_tokens.py": (
        "0b2043a7c92db6708869e0576553f9ab98e3452e67c9cdc6483ee43d3323465f"
    ),
    "auth/dependencies.py": (
        "1dfc6ef504308e331e9e2b39cc631e322ef831a99c97b7417190406252dda299"
    ),
    "auth/login.py": (
        "a2b0cbdaad4e9930266ab891e48fbee9eac06aa454b34cece7037ac0dd032233"
    ),
    "auth/password_change.py": (
        "3586ba756352db10200a53e76991c50127123ce24f9bbe19ae97bb71ae7b77ec"
    ),
    "auth/passwords.py": (
        "9510f5298c7aa7aec2f29b29a123ba69eb997fdad26fe441b85feb4002aa9382"
    ),
    "auth/principal.py": (
        "209badc5db2003b8386e635d2f550fb31ac5971c1c158166934a8ae654816bae"
    ),
    "auth/tokens.py": (
        "e99af11b548a1dad3b1035820ca7ee56d7b9a42e6fdaae37df4b0bb4ef656b7b"
    ),
    "auth/totp.py": (
        "de2cd01735f3f2d66fa914a0c991b2c0a51e4e067ceb053973884a3d156d8c2c"
    ),
    "auth/totp_enrol.py": (
        "a26dfcb2ee45a5cdece14d23d3189f8a78962fe5fab805569ee7f13876827d9f"
    ),
    "auth/vault.py": (
        "7332a1070be2268a2913006a80a16af7c11d6e74771c44ef308b9d22ea0ca8d9"
    ),
    "db/migrations/versions/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "db/migrations/versions/m0001_catalog.py": (
        "440086244187fd021678235184535c55e515a3fcd45543404ff30eedfaf206a4"
    ),
    "db/migrations/versions/m0002_fleet_inventory.py": (
        "f97b4d42eed5cb666f3b85bbd9b26195e5d608e6a3fd8e8a85145b4bd8e872ab"
    ),
    "db/migrations/versions/m0003_scanning.py": (
        "4c5a0cd1da3a5e1bb364c9477448dd5ca5532bcab38a7d83ff17b25be9db81db"
    ),
    "db/migrations/versions/m0004_system.py": (
        "df630bdfb2e43f5a614b01e65ebb52304bf249ed4861ff611220a42dc3e45a88"
    ),
    "db/migrations/versions/m0005_privileges_seeds.py": (
        "2b66bd92d94df7d419d34b661f1e258b99459e135a0133a1641d42aac93921b2"
    ),
    "repositories/reeval.py": (
        "b0f2d96aa1063a1925a0bef6528073d6773239bc580478b694aa21334a834ecb"
    ),
    "repositories/results.py": (
        "101e918293e108f2c9c7559d881e8fa4eafdaa7c2681057db24bf0c59c1ada61"
    ),
    "repositories/scan_progress.py": (
        "aef027ce83c7e333fb6b5744da7f6ae84f9ebcc8c08ea9519841f7dcc263fcc5"
    ),
    "services/audit/chain.py": (
        "1f95c5c8d64c43252fcfb863714129cd0a64965e492255f8e35a206684487a76"
    ),
    "services/audit/verify.py": (
        "f719acc89271208bcb45f629135c4bc33f5168b5f13ff84b9f3b0f219081f6da"
    ),
    "services/evaluator/reevaluate.py": (
        "9dd3afac34d7f336c29f536d9eea26b2a8e3aab633452a717340a5250a6af76b"
    ),
    "services/evaluator/score.py": (
        "50343088881f1317e27e7204b892454022ded935a9ae4fdf9b541d9de52fe194"
    ),
    "services/evaluator/scores.py": (
        "9a4256c65e4228bed3c192683b435dcb0717406468559faa1df5566f36b30bbd"
    ),
    "services/jobs/__init__.py": (
        "0f261e2aa57dfeb14656ecef5573d518115661517b4e144380fb4251cdd47d3b"
    ),
    "services/jobs/build.py": (
        "fd339fbcf84aac922bac025089f3b6b36c420384fd446d0423ac33b54d92a2bf"
    ),
    "services/jobs/cancel.py": (
        "9dd2f03e8a56dd0b54815a93cf8ac3e021075544f97c5ce4e3f2f94108d7bd26"
    ),
    "services/jobs/intake.py": (
        "549b9a6aaaa48b0189d09f40138d92c7b9020854684717e3af896871b6baaef9"
    ),
    "services/jobs/intake_plan.py": (
        "89a13f83aef30f8bc96c3e9ca835bc4de35f198828785c6b31af5745f5d842d6"
    ),
    "services/jobs/pull.py": (
        "20a1d324a1624b6db60e079e48190fa3cad8a0650dcb6026238a43979e3045ae"
    ),
    "services/jobs/queue.py": (
        "85a52859445d3dc81313d134f1fc9f32404afd5febbf57a263ecdaa3495ed517"
    ),
    "services/jobs/scan_state.py": (
        "6d78e8235b72af8ebf05d4936a72506fcda3c84afbe22941e09e4411df4f277a"
    ),
    "services/jobs/states.py": (
        "57d2f6ed1463afee56b74cf2e1e0951b9405f687c4c80a85d69b16843da9b2cc"
    ),
    "services/jobs/targets.py": (
        "d3c1180cef98390de67604345e2b18586b02ffbdbed3ef27014a2b7e01a184a7"
    ),
    "services/packages/csv_export.py": (
        "738fc8432756e3b7c8ef70f153e1a46f562254747ad66207e28438720007580d"
    ),
}
# Folders frozen as a whole: no file added (the three M11 jobs modules aside).
FROZEN_DIRS = ("auth", "services/jobs", "db/migrations/versions")
M11_JOBS = {
    "services/jobs/results_view.py",
    "services/jobs/results_read.py",
    "services/jobs/scan_views.py",
}


# ------------------------------------------------------------------ helpers


def source(rel: str) -> str:
    return (BM / rel).read_text(encoding="utf-8")


def module_name(rel: str) -> str:
    name = "bitscan_manager." + rel.removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def module_file(name: str) -> Path | None:
    if not name.startswith("bitscan_manager"):
        return None
    base = MANAGER / Path(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def top_level_imports(path: Path) -> set[str]:
    """Modules imported at module level (an import inside a function, as in
    ``build_user_router``, runs only when called). ``from a import b`` adds
    ``a`` and ``a.b`` (b may be a module)."""
    out: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return {n for n in out if module_file(n) is not None or not n.startswith("bitscan")}


def all_imports(path: Path) -> set[str]:
    """Every module named by any import statement in the file."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def sql_strings(rel: str) -> list[str]:
    """Every string constant of a module except docstrings (SQL text)."""
    tree = ast.parse(source(rel))
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                docs.add(id(body[0].value))
    return [
        # RE2 takes UTF-8 only; a lone surrogate (a decoder test value) is no SQL.
        n.value.encode("utf-8", "replace").decode("utf-8")
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docs
    ]


def product_files() -> Iterator[tuple[str, str]]:
    for path in sorted(BM.rglob("*.py")):
        rel = path.relative_to(BM).as_posix()
        if rel.startswith("db/migrations/"):
            continue  # the DDL itself
        yield rel, path.read_text(encoding="utf-8")


def ruff(rel: str, text: str) -> subprocess.CompletedProcess[str]:
    """`ruff check` of ``text`` as if it were ``bitscan_manager/<rel>`` (the
    tree's own configuration and per-file rules apply), the tree untouched."""
    return subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "concise",
            "--stdin-filename",
            f"bitscan_manager/{rel}",
            "-",
        ],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",  # ruff reads and writes UTF-8 on every platform
        errors="replace",
        cwd=MANAGER,
        timeout=120,
    )


def log_texts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Each record's message and every attribute (args, extra data)."""
    return [r.getMessage() for r in caplog.records] + [
        str(r.__dict__) for r in caplog.records
    ]


# ============================================================ CODE rows


# ------------------------------------------------------------ CHK-M11-240


def test_the_scan_operations_are_exactly_the_spec_routes_with_their_markers() -> None:
    """TS §6.2, REQ-273 (4), G34: the app's scan operations are exactly M9's
    two and M11's six (no rerun, no ad-hoc command); the five reads need the
    viewer role, re-evaluate a TOTP-verified admin session with the sink
    gate; no M11 operation takes a request body."""
    app = create_app()
    walked = markers(app)
    scan_ops = {
        k
        for k in walked
        if k[1].startswith(V1 + "/scans") or k[1] == V1 + "/agents/{id}/scans"
    }
    assert scan_ops == SCAN_OPS, scan_ops ^ SCAN_OPS
    for method, path in M11_OPS:
        marker = walked[(method, path)]
        assert marker is not None, path
        got = (marker.check, marker.minimum, marker.allow_restricted, marker.sink_gate)
        if path.endswith("/reevaluate"):
            assert got == ("totp_session", "admin", False, True), got
        else:
            assert got == ("role", "viewer", False, False), (path, got)
    doc = app.openapi()
    for method, path in M11_OPS:
        op = doc["paths"][path][method.lower()]
        assert "requestBody" not in op, path


def test_no_operation_of_the_app_takes_command_text() -> None:
    """TS §3.3, security invariants: no request body of any app operation
    (the live app, not the committed document) has a command-like field."""
    doc = create_app().openapi()
    comps = doc["components"]["schemas"]
    found = []
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            for content in op.get("requestBody", {}).get("content", {}).values():
                ref = content.get("schema", {}).get("$ref", "")
                schema = comps.get(ref.rsplit("/", 1)[-1], {})
                bad = {k.lower() for k in schema.get("properties", {})} & COMMAND_WORDS
                if bad:
                    found.append((method, path, sorted(bad)))
    assert found == []
    routes = [r.path for r in api_routes(create_app().routes)]
    assert not [p for p in routes if re2.search(r"(?i)rerun|/run\b|exec|shell", p)]


# ------------------------------------------------------------ CHK-M11-241


def test_only_the_operator_results_model_carries_output() -> None:
    """REQ-268 (3), #144 (b): of the M11 response models only
    ScanResultItemWithOutput has stdout or stderr; scan models carry no
    command, expected value, operator or resolved target."""
    comps = create_app().openapi()["components"]["schemas"]

    def props(name: str) -> set[str]:
        return set(comps[name]["properties"])

    assert {"stdout", "stderr"} <= props("ScanResultItemWithOutput")
    assert not {"stdout", "stderr"} & props("ScanResultItem")
    banned = {"stdout", "stderr", "execute", "expected", "operator", "resolved_agents"}
    for name in ("ScanItem", "ScanDetailItem", "HostSummary", "HostJob", "ReevalItem"):
        assert not props(name) & banned, (name, props(name) & banned)
    with_output = [
        n
        for n, s in comps.items()
        if {"stdout", "stderr"} & set(s.get("properties", {}))
    ]
    m11 = {"ScanItem", "ScanDetailItem", "HostSummary", "HostJob", "ReevalItem"}
    assert not set(with_output) & m11


# ------------------------------------------------------------ CHK-M11-242


def test_reevaluate_scan_is_the_one_writer_of_reevaluations() -> None:
    """REQ-271 (1), TS §2.2 L114: rows enter scan_result_reeval only through
    repositories/reeval.py; nothing updates or deletes results or
    re-evaluations directly; only retention deletes scans (the cascade);
    M8's reevaluate_scan is used only by the re-evaluate route."""
    inserts: set[str] = set()
    writes: list[tuple[str, str]] = []
    scan_deletes: set[str] = set()
    callers: set[str] = set()
    for rel, text in product_files():
        sql_text = "\n".join(sql_strings(rel))  # SQL only, not docstrings
        if re2.search(r"(?is)INSERT\s+INTO\s+scan_result_reeval\b", sql_text):
            inserts.add(rel)
        for hit in re2.findall(
            r"(?is)\b((?:UPDATE|DELETE\s+FROM|TRUNCATE)\s+scan_result\w*)", sql_text
        ):
            writes.append((rel, hit))
        if re2.search(r"(?is)DELETE\s+FROM\s+scan\b", sql_text):
            scan_deletes.add(rel)
        for node in ast.walk(ast.parse(text)):
            named = (
                (isinstance(node, ast.Name) and node.id == "reevaluate_scan")
                or (isinstance(node, ast.Attribute) and node.attr == "reevaluate_scan")
                or (isinstance(node, ast.alias) and node.name == "reevaluate_scan")
            )
            if named:
                callers.add(rel)
    assert inserts == {"repositories/reeval.py"}, inserts
    assert writes == [], writes
    assert scan_deletes == {"repositories/retention.py"}, scan_deletes
    # Referenced only by the route; defined (not referenced) in M8's module.
    assert callers == {"api/user/reevaluate.py"}, callers
    defined = [
        n.name
        for n in ast.walk(ast.parse(source("services/evaluator/reevaluate.py")))
        if isinstance(n, ast.FunctionDef)
    ]
    assert "reevaluate_scan" in defined


# ------------------------------------------------------------ CHK-M11-243


def reached(rel: str) -> set[str]:
    """Modules a file imports at module level, descending through bm.api."""
    seen: set[str] = set()
    todo = [module_name(rel)]
    found: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = module_file(name)
        if path is None:
            continue
        imports = top_level_imports(path)
        found |= imports
        todo.extend(i for i in imports if i.startswith("bitscan_manager.api"))
    return found


@pytest.mark.parametrize("rel", M11_ROUTES)
def test_the_m11_routes_reach_no_repository(rel: str) -> None:
    """REQ-272 (2), REQ-270 (5): api → services → repositories; an M11 route
    module, and every bm.api module it reaches, imports no repository and
    no psycopg; it does import its service."""
    found = reached(rel)
    assert sorted(i for i in found if ".repositories" in i or "psycopg" in i) == []
    assert any(i.startswith("bitscan_manager.services.") for i in found), found


@pytest.mark.parametrize("rel", M11_SERVICES + M11_REPOS)
def test_the_m11_layers_point_down_only(rel: str) -> None:
    """Services import no api module; repositories import no service and no
    api module; the pure modules (results view, retention rules) import no
    database code, except the results view's row type (CHK-M11-014)."""
    found = all_imports(BM / rel)
    assert not [i for i in found if i.startswith("bitscan_manager.api")], found
    if rel.startswith("repositories/"):
        assert not [i for i in found if i.startswith("bitscan_manager.services")]
    if rel in ("services/jobs/results_view.py", "services/retention/rules.py"):
        row_type = {
            "bitscan_manager.repositories.result_reads",
            "bitscan_manager.repositories.result_reads.ResultRow",
        }
        allowed = row_type if rel.endswith("results_view.py") else set()
        assert not [
            i
            for i in found - allowed
            if i.startswith(
                ("psycopg", "bitscan_manager.repositories", "bitscan_manager.db")
            )
        ], found


# ------------------------------------------------------------ CHK-M11-244, -245, -367


def test_the_frozen_files_are_byte_unchanged() -> None:
    """REQ-272 (3), (5), PD-46: every M1, M2, M5, M8 and M9 file M11 reuses,
    and every migration, is byte-identical to 6efe0fb."""
    changed = {
        rel: hashlib.sha256((BM / rel).read_bytes()).hexdigest()
        for rel in FROZEN
        if not (BM / rel).is_file()
        or hashlib.sha256((BM / rel).read_bytes()).hexdigest() != FROZEN[rel]
    }
    assert changed == {}, sorted(changed)


@pytest.mark.parametrize("folder", FROZEN_DIRS)
def test_no_file_was_added_to_a_frozen_folder(folder: str) -> None:
    """No M11 file under bm/auth/ or the migrations (no migration in M11);
    services/jobs/ gains exactly the three M11 modules."""
    now = {
        p.relative_to(BM).as_posix() for p in (BM / folder).glob("*.py") if p.is_file()
    }
    pinned = {r for r in FROZEN if r.startswith(folder + "/")}
    allowed = M11_JOBS if folder == "services/jobs" else set()
    assert now == pinned | allowed, sorted(now ^ (pinned | allowed))


# ------------------------------------------------------------ CHK-M11-249 (static)


def test_retention_code_cannot_update_alter_or_insert() -> None:
    """TS §5.3 L1051, REQ-278 (4): the retention SQL has no UPDATE, no row
    lock, no DDL and no INSERT (the checkpoint goes through append_entry);
    it deletes only from the TS §5.2 retention tables."""
    for rel in RETENTION_CODE:
        for text in sql_strings(rel):
            assert not re2.search(r"(?i)\bUPDATE\b", text), (rel, text)
            assert not re2.search(
                r"(?i)\b(CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|VACUUM)\b", text
            ), (rel, text)
            assert not re2.search(r"(?i)\bINSERT\b", text), (rel, text)
            for found in re2.findall(r"(?i)DELETE\s+FROM\s+(\w+)", text):
                assert found.lower() in RETENTION_TABLES, (rel, found)
    task = source("services/retention/task.py")
    assert "append_entry(" in task
    deletes = {
        t.lower()
        for rel in RETENTION_CODE
        for s in sql_strings(rel)
        for t in re2.findall(r"(?i)DELETE\s+FROM\s+(\w+)", s)
    }
    assert deletes, "the check must see the retention deletes"
    assert not deletes & {"agent_package", "os_info", "agent", "enrollment_token"}


def test_only_the_scheduler_runs_retention() -> None:
    """REQ-277: the retention service is imported only by the scheduler
    runner (no route, CLI or setting reaches it)."""
    users = set()
    for rel, _ in product_files():
        if rel.startswith("services/retention/"):
            continue
        if any(
            i.startswith("bitscan_manager.services.retention")
            for i in all_imports(BM / rel)
        ):
            users.add(rel)
    assert users == {"services/scheduler/runner.py"}, users


def test_serve_gives_retention_its_own_bitscan_retention_pool() -> None:
    """REQ-275 (2), TS §8.6 L1309: serve's SchedulerRunner gets a pool built
    from config.retention_dsn, never the app pool."""
    fn = next(
        n
        for n in ast.walk(ast.parse(source("cli/serve.py")))
        if isinstance(n, ast.FunctionDef) and n.name == "build_runtime"
    )
    (runner,) = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "SchedulerRunner"
    ]
    kw = {k.arg: ast.unparse(k.value) for k in runner.keywords}
    pools = {
        ast.unparse(n.targets[0]): ast.unparse(n.value)
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
    }
    made = pools.get(kw.get("retention_db", ""), "")
    assert made.startswith("AppDatabase(") and "config.retention_dsn" in made, made
    assert "name='bitscan_retention'" in made, made


# ------------------------------------------------------------ CHK-M11-250


SQL_PLANT = '\n\n_PLANTED = f"SELECT x FROM {__name__} WHERE y = 1"\n'


@pytest.mark.parametrize("rel", M11_REPOS)
def test_s608_is_green_as_is_and_red_on_an_f_string_query(rel: str) -> None:
    """TS §8.1, CHK-M11-344, -345: each M11 repository passes ruff as it is,
    and the same file with a string-built query fails with S608."""
    text = source(rel)
    clean = ruff(rel, text)
    assert clean.returncode == 0, clean.stdout
    planted = ruff(rel, text + SQL_PLANT)
    assert planted.returncode != 0 and "S608" in planted.stdout, planted.stdout


@pytest.mark.parametrize("rel", M11_NEW)
def test_the_re_ban_is_green_as_is_and_red_on_an_re_import(rel: str) -> None:
    """TS §4.5, CHK-M11-390: each new M11 module passes ruff as it is, and
    fails with the TID251 `re` ban once it imports re."""
    text = source(rel)
    clean = ruff(rel, text)
    assert clean.returncode == 0, clean.stdout
    planted = ruff(rel, "import re  # noqa: F401\n" + text)
    assert planted.returncode != 0, planted.stdout
    assert "TID251" in planted.stdout and "`re` is banned" in planted.stdout


# ============================================================ PostgreSQL rows

pg = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sec-m11")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def who(env: ApiEnv) -> dict[str, m.Caller]:
    """The m11 callers, plus an admin who has TOTP but whose session is not
    TOTP-verified."""
    at = env.clock.now()
    with env.conn() as c:
        out = m.callers(c, at=at)
        uid = m.make_user(c, "admin", at=at)
        out["admin:unverified"] = m.Caller(
            uid, "admin", "unverified", m.make_token(c, uid, verified=False, at=at)
        )
    return out


@pytest.fixture
def rw(env: ApiEnv) -> m.ResultsWorld:
    with m.owner(env.server) as c:
        admin = m.make_user(c, "admin", at=BASE_AT)
        return m.results_world(c, at=BASE_AT, admin_id=admin)


def m11_reads(rw: m.ResultsWorld) -> dict[str, str]:
    sid, aid = rw.scan_id, rw.hosts["a"].agent_id
    return {
        "list": f"{V1}/scans",
        "detail": f"{V1}/scans/{sid}",
        "results": f"{V1}/scans/{sid}/results",
        "csv": f"{V1}/scans/{sid}/results.csv",
        "history": f"{V1}/agents/{aid}/scans",
    }


def csv_header(text: str) -> list[str]:
    return next(csv.reader(io.StringIO(text, newline="")))


VIEWERS = ("viewer:session", "viewer:api")
OUTPUT_ROLES = ("operator:session", "operator:api", "admin:session", "admin:api")
RESULT_WRITE = re2.compile(
    r"(?is)^\s*(WITH\b.*)?\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE)"
    r"\s+(scan_result\w*|scan_job|scan)\b"
)


# ------------------------------------------------------------ viewer output


@pg
def test_viewers_never_receive_output_and_reads_write_nothing(
    env: ApiEnv,
    who: dict[str, m.Caller],
    rw: m.ResultsWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TS §6.2 L1083, L1123, REQ-268 (1), #144 (b): a viewer (session or API
    token) gets results items without stdout and stderr keys and a CSV
    without those columns, on every page and every status filter, and the
    OUT and ERR canaries never reach it; operator and admin get both, for a
    session and an API token alike. Every item is this scan's (15: one per
    planned plugin of the three hosts; the other scan's rows never appear).
    REQ-271 (2): no read writes a result, a re-evaluation, a job or a scan."""
    paths = m11_reads(rw)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    for kind in VIEWERS + OUTPUT_ROLES:
        caller = who[kind]
        output = kind not in VIEWERS
        items, texts = walk(env, caller, paths["results"], limit="4")
        assert len(items) == 15, (kind, len(items))
        want = VIEWER_KEYS | OUTPUT_KEYS if output else VIEWER_KEYS
        assert {frozenset(i) for i in items} == {frozenset(want)}, kind
        for status in ("PASS", "FAIL", "ERROR", "NOT_RUN"):
            some, more = walk(env, caller, paths["results"], status=status)
            texts += more
            assert all(set(i) == want for i in some), (kind, status)
        r = get(env, caller, paths["csv"])
        assert r.status_code == 200, r.text
        texts.append(r.text)
        header = csv_header(r.text)
        assert (header[-2:] == ["stdout", "stderr"]) is output, (kind, header)
        assert not {"stdout", "stderr"} & set(header[:-2]), header
        joined = "".join(texts)
        assert "other-scan" not in joined, kind  # another scan's rows
        assert (m.hits([joined], m.OUTPUT_CANARIES) == sorted(m.OUTPUT_CANARIES)) is (
            output
        ), kind
        if not output:
            assert m.hits([joined], m.OUTPUT_CANARIES) == [], kind
        for name in ("list", "detail", "history"):
            got = get(env, caller, paths[name])
            assert got.status_code == 200, (name, got.text)
            # REQ-264 (4): scan items hold no output, command or expected value.
            assert m.hits([got.text]) == [], (kind, name)
            assert "resolved_agents" not in got.text, (kind, name)
    monkeypatch.undo()
    writes = [s for s in spy.statements if RESULT_WRITE.search(s)]
    assert writes == [], writes[:3]
    assert spy.statements, "the spy must see the reads"


# ------------------------------------------------------------ CHK-M11-247


def store_user_token(conn: Any, user_id: int, raw: str, at: datetime) -> None:
    """A live user_token row (kind api) whose stored hash is that of ``raw``,
    as if a token with the wrong prefix had been stored for a user."""
    conn.execute(
        "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
        " expires_at, created_at) VALUES (%s, 'api', %s, false, %s, %s)",
        (user_id, token_hash(raw), at + timedelta(days=30), at - timedelta(minutes=1)),
    )


@pg
def test_tokens_are_refused_outside_their_route_group(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """TS §6, security invariants: bsa_ and bse_ get 401 on all six M11
    operations, even when a user_token row holds their hash (the prefix is
    checked per router); bsu_ and bsk_ get 401 on an agent route even when
    the agent row holds their hash. The same calls with the right group's
    token succeed (so the refusals are the prefix, not the row)."""
    paths = m11_reads(rw)
    wrong = {
        "bsa_ real": rw.hosts["a"].token,
        "bse_ real": new_agent_token(AgentTokenKind.ENROLMENT),
        "bsa_ stored": new_agent_token(AgentTokenKind.AGENT),
        "bse_ stored": new_agent_token(AgentTokenKind.ENROLMENT),
    }
    right = new_token(TokenKind.API)
    at = env.clock.now()
    with env.conn() as c:
        uid = m.make_user(c, "admin", at=at)
        for raw in (wrong["bsa_ stored"], wrong["bse_ stored"], right):
            store_user_token(c, uid, raw, at)
    calls = [("GET", p) for p in paths.values()]
    calls.append(("POST", f"{V1}/scans/{rw.scan_id}/reevaluate"))
    for label, tok in wrong.items():
        for method, path in calls:
            # A fresh address per refused call: the auth-failure rate limit
            # (TS §6.3) would otherwise answer 429 before the token check.
            r = env.client_for(env.fresh_ip()).request(
                method, path, headers={"Authorization": f"Bearer {tok}"}
            )
            assert r.status_code == 401, (label, path, r.status_code)
            assert r.json()["type"] == "unauthorized", (label, path)
    for _, path in calls[:-1]:
        r = env.client.get(path, headers={"Authorization": f"Bearer {right}"})
        assert r.status_code == 200, (path, r.status_code)
    # The agent group: an agent row holding a user token's hash.
    agent_ok = env.agent()
    assert agent_ok.pull().status_code == 200
    for raw in (new_token(TokenKind.API), new_token(TokenKind.SESSION)):
        with env.conn() as c:
            row = f9.make_agent(c, at=env.clock.now(), token_hash=token_hash(raw))
        sim = SimAgent(env, dataclasses.replace(row, token=raw), env.fresh_ip())
        r = sim.pull()
        assert r.status_code == 401, (raw[:4], r.status_code, r.text)
    for caller in ("operator:session", "admin:api"):
        r = env.client.get(
            f"{V1}/agent/{agent_ok.agent_id}/jobs",
            headers=who[caller].headers()
            | {"X-Bitscan-Machine-Id": agent_ok.row.machine_id},
        )
        assert r.status_code == 401, (caller, r.status_code)


# ------------------------------------------------------------ re-evaluate


REFUSED = [
    ("admin:api", 403, "totp_session_required"),
    ("admin:restricted", 403, "totp_enrolment_required"),
    ("admin:unverified", 403, "totp_enrolment_required"),
    ("operator:session", 403, "forbidden"),
    ("operator:api", 403, "totp_session_required|forbidden"),
    ("viewer:session", 403, "forbidden"),
    ("viewer:api", 403, "totp_session_required|forbidden"),
    ("operator:revoked", 401, "unauthorized"),
    ("agent", 401, "unauthorized"),
    ("enrol", 401, "unauthorized"),
    ("none", 401, "unauthorized"),
]


@pg
def test_reevaluate_refuses_everyone_but_a_totp_admin_session(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """TS §6.2 L1086, L1125, REQ-270 (2): API tokens (an admin's too),
    operators, viewers, a restricted admin and an admin whose session is
    not TOTP-verified are refused, and so are tokens of no user; each
    refusal writes no re-evaluation row and no audit entry. Then the admin
    TOTP session is accepted (one scan.reevaluate entry, rows added)."""
    w = build(env)
    path = f"{V1}/scans/{w.scan_id}/reevaluate"
    before = state(env)
    for kind, status, type_ in REFUSED:
        r = post(env, path, who[kind])
        problem(r, status, type_)
        assert state(env) == before, kind
    ok = post(env, path, who["admin:session"])
    assert ok.status_code == 200, ok.text
    after = state(env)
    assert after.reeval_rows == before.reeval_rows + 3
    assert after.results == before.results  # originals unchanged
    assert [e["action"] for e in new_entries(env, before.audit_max)] == [
        "scan.reevaluate"
    ]


@pg
def test_reevaluate_is_refused_from_15_minutes_of_sink_outage_until_the_drain(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """TS §5.3 L1053, REQ-270 (2), clock control: 14 min 59 s into a sink
    outage the admin TOTP session is still accepted; at 15 min it gets 503
    audit_sink_unavailable and nothing is written; after the queue drains
    it is accepted again."""
    w = build(env)
    path = f"{V1}/scans/{w.scan_id}/reevaluate"
    admin = who["admin:session"]
    m.sink_down(env, 15 * 60 - 1)
    first = post(env, path, admin)
    assert first.status_code == 200, first.text
    env.clock.advance(seconds=1)
    before = state(env)
    refused = post(env, path, admin)
    problem(refused, 503, "audit_sink_unavailable")
    assert state(env) == before
    m.sink_up(env)
    again = post(env, path, admin)
    assert again.status_code == 200, again.text
    assert state(env).reeval_rows == before.reeval_rows + 3


# ------------------------------------------------------------ CHK-M11-248


@pg
def test_no_canary_or_token_leaves_through_logs_problems_or_audit(
    env: ApiEnv,
    who: dict[str, m.Caller],
    rw: m.ResultsWorld,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CHK-M11-248, REQ-268 (4), REQ-272 (4), TS §5.3 L1054, §8.4: one flow
    over every M11 operation (each role, session and API token; every page,
    filter and the CSV; bad filters, a bad cursor, an unknown scan; the
    re-evaluation and its refusals). At DEBUG, no log record holds any of
    the four canaries or any caller's or agent's token; no problem body and
    no new audit detail holds a canary."""
    caplog.set_level(logging.DEBUG)
    paths = m11_reads(rw)
    problems: list[str] = []
    with env.conn() as c:
        audit_from = int(f9.one(c, "SELECT coalesce(max(audit_id), 0) FROM audit_log"))
    for kind in VIEWERS + OUTPUT_ROLES:
        caller = who[kind]
        walk(env, caller, paths["results"], limit="2")
        for status in ("PASS", "FAIL", "ERROR", "NOT_RUN"):
            walk(env, caller, paths["results"], status=status)
            get(env, caller, paths["csv"], status=status)
        for name in ("list", "detail", "history", "csv"):
            assert get(env, caller, paths[name]).status_code == 200
        for bad in (
            get(env, caller, paths["results"], status="pass"),
            get(env, caller, paths["results"], cursor="x" * 40),
            get(env, caller, paths["list"], state="nope"),
            get(env, caller, f"{V1}/scans/0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11"),
            get(env, caller, f"{V1}/scans/not-a-uuid/results.csv"),
        ):
            assert bad.status_code in (400, 404), bad.text
            problems.append(bad.text)
    w = build(env)
    reeval = f"{V1}/scans/{w.scan_id}/reevaluate"
    for kind in ("admin:api", "operator:session", "viewer:api", "agent"):
        problems.append(post(env, reeval, who[kind]).text)
    assert post(env, reeval, who["admin:session"]).status_code == 200
    texts = log_texts(caplog)
    assert texts, "the sweep must see the app's log records"
    assert m.hits(texts) == []
    tokens = [c.token for c in who.values() if c.token]
    tokens += [h.token for h in rw.hosts.values()]
    assert not [t[:4] for t in tokens if any(t in x for x in texts)]
    assert m.hits(problems) == []
    details = [json.dumps(e["detail"]) for e in new_entries(env, audit_from)]
    assert details, "the re-evaluation must have written its entry"
    assert m.hits(details) == []


# ------------------------------------------------------------ CHK-M11-249 (APP)


class _RealClock:
    """Retention compares the manager clock with the database's own now()."""

    def now(self) -> datetime:
        return m.now_utc()


@pg
def test_retention_runs_as_bitscan_retention_within_its_role(
    server: PgServer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TS §5.3 L1049–L1054, REQ-275 (2), (6), REQ-278 (4), G2: a scheduler
    retention run (SchedulerRunner with an app pool and the
    bitscan_retention pool, as serve wires it) over the aged world: every
    statement runs as bitscan_retention, none on the app pool; no DDL, no
    UPDATE, no row lock, no INSERT but the audit checkpoint; no step fails;
    the expired rows go while os_info, agent_package and the other kept
    tables are unchanged; the log holds no canary and no deleted id."""
    with m.owner(server) as c:
        c.execute(
            "TRUNCATE scan, scan_job, scan_result, scan_result_reeval,"
            " inventory_snapshot, enrollment_request, enrollment_token, user_token,"
            " package, agent_package, os_info, audit_log CASCADE"
        )
        w = m.aged_world(c, m.now_utc())
    ids = m.audit_chain(server, [old_at(w.now)] * 3)
    with m.owner(server) as c:
        kept = m.checksums(c)
    spy = m.RoleSpy()
    caplog.set_level(logging.DEBUG)
    wakes: list[int] = []
    with (
        f9.app_database(server, max_size=2) as adb,
        m.retention_database(server) as rdb,
    ):
        runner = SchedulerRunner(
            adb,
            _RealClock(),
            lambda: wakes.append(1),
            retention_db=rdb,
            shipped_through=m.shipped(ids[-1]),
        )
        spy.install(monkeypatch)
        runner.run_retention()
        monkeypatch.undo()
    assert spy.by_role("bitscan_app") == [], spy.by_role("bitscan_app")[:3]
    mine = spy.by_role("bitscan_retention")
    assert any(m.verb(s) == "DELETE" for s in mine), "the run must have deleted"
    for text in mine:
        first = m.verb(text)
        assert first not in m.DDL_VERBS and first != "UPDATE", text[:80]
        assert "FOR UPDATE" not in text.upper(), text[:80]
        if first == "INSERT":
            assert text.upper().startswith("INSERT INTO AUDIT_LOG"), text[:80]
    with m.owner(server) as c:
        assert m.checksums(c) == kept  # G2 and the never-deleted tables
        present = m.present(c, w)
        actions = {str(r[0]) for r in c.execute("SELECT action FROM audit_log")}
    assert present[("scan", "old")] is False and present[("scan", "inside")] is True
    assert present[("package", "referenced")] is True
    assert actions == {"audit.checkpoint"}
    assert wakes, "the checkpoint's commit wakes the shipper"
    failed = [
        r for r in caplog.records if "failed" in r.getMessage() or r.levelno >= 40
    ]
    assert failed == [], [(r.getMessage(), getattr(r, "data", None)) for r in failed]
    done = [
        getattr(r, "data", {})
        for r in caplog.records
        if r.getMessage() == "retention step done"
    ]
    assert [d["step"] for d in done] == list(STEPS)
    assert all(d["skipped"] is None for d in done), done
    texts = log_texts(caplog)
    assert m.hits(texts) == []
    gone = [w.key("scan", "old"), w.key("scan", "past"), *w.scan_jobs["old"]]
    gone_ids = [str(UUID(str(g))) for g in gone]
    assert not [g for g in gone_ids if any(g in t for t in texts)]
