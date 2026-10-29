"""TP-M8-13: M8 security and boundary suite (REQ-189 (6), REQ-202, REQ-204).

Static half (no database): the import graph of the pure evaluator modules
(REQ-202 (1): a verdict comes only from its inputs, never the current plugin
row, TS §4.5 L587), the `re` ban (security invariants "Data handling"; TS
§4.5 L600), and no logging call that formats a result field (REQ-202 (3); TS
§5.3, §8.4). The PostgreSQL half (grant probes, canary over the services)
lives in the PostgreSQL suites and is listed in tests/m8/test-plan.md.
CHK-M8-220 to -224, -228.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import bitscan_manager

BM = Path(bitscan_manager.__file__).resolve().parent
MANAGER = BM.parent
EV = BM / "services" / "evaluator"
PURE = ("model", "normalise", "operators", "evaluate", "verdict", "eval_spec", "score")
SERVICES = ("scores", "reevaluate")
REPOS = ("results", "reeval")
# REQ-202 (1): the only bm modules a pure module may reach.
ALLOWED_BM = {
    "bitscan_manager",
    "bitscan_manager.services",
    "bitscan_manager.services.evaluator",
    "bitscan_manager.services.importer",
    "bitscan_manager.services.importer.model",
    "bitscan_manager.services.importer.values",
} | {f"bitscan_manager.services.evaluator.{m}" for m in PURE}
FORBIDDEN_THIRD_PARTY = ("psycopg", "psycopg_pool", "fastapi", "starlette", "re")


def _module_path(name: str) -> Path | None:
    rel = name.split(".")[1:]
    base = MANAGER / "bitscan_manager" / Path(*rel) if rel else BM
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    return None


def _direct_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in {path}"
            mod = node.module or ""
            found.add(mod)
            # `from pkg import sub` may import a submodule
            for a in node.names:
                if _module_path(f"{mod}.{a.name}") is not None:
                    found.add(f"{mod}.{a.name}")
    return found


def _static_closure(start: str) -> set[str]:
    """Every module `start` reaches by import statements, following bm only
    (each package's `__init__` counts, as Python imports it)."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if not name.startswith("bitscan_manager"):
            continue
        parts = name.split(".")
        for i in range(1, len(parts)):
            todo.append(".".join(parts[:i]))
        path = _module_path(name)
        if path is None:
            continue
        todo.extend(_direct_imports(path))
    return seen


def _present(module: str) -> bool:
    return (EV / f"{module}.py").exists()


# CHK-M8-220: REQ-202 (1), static
@pytest.mark.parametrize("module", PURE)
def test_pure_module_static_import_graph(module: str) -> None:
    assert _present(module), f"{module}.py missing"
    reached = _static_closure(f"bitscan_manager.services.evaluator.{module}")
    bm = {m for m in reached if m.startswith("bitscan_manager")}
    assert bm <= ALLOWED_BM, sorted(bm - ALLOWED_BM)
    for name in reached:
        top = name.split(".")[0]
        assert top not in FORBIDDEN_THIRD_PARTY, name
        assert top != "logging", name


# CHK-M8-220: REQ-202 (1), at run time in a fresh interpreter
WHERE = "import bitscan_manager; print(bitscan_manager.__file__)"
PROBE = """
import json, sys
import importlib
before = set(sys.modules)
importlib.import_module(sys.argv[1])
print(json.dumps(sorted(set(sys.modules) - before)))
"""


@pytest.mark.parametrize("module", PURE)
def test_pure_module_runtime_import_graph(module: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(MANAGER) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", PROBE, f"bitscan_manager.services.evaluator.{module}"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    ).stdout
    loaded = set(json.loads(out))
    bm = {m for m in loaded if m.startswith("bitscan_manager")}
    assert bm <= ALLOWED_BM, sorted(bm - ALLOWED_BM)
    for bad in ("psycopg", "psycopg_pool", "fastapi", "starlette", "pydantic"):
        assert not any(m == bad or m.startswith(bad + ".") for m in loaded), bad
    # The child imported this tree, not another checkout (M7 lesson).
    child_file = subprocess.run(  # noqa: S603  # fixed argv
        [sys.executable, "-c", WHERE],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    ).stdout.strip()
    assert Path(child_file).resolve() == BM / "__init__.py"


# CHK-M8-221: the two services read definitions only through their repositories
@pytest.mark.parametrize("module", SERVICES)
def test_services_import_no_api_and_no_catalog_repositories(module: str) -> None:
    assert _present(module), f"{module}.py missing"
    names = _direct_imports(EV / f"{module}.py")
    for name in names:
        assert not name.startswith("bitscan_manager.api"), name
        assert not name.startswith("bitscan_manager.repositories.catalog"), name
        assert name.split(".")[0] not in ("re", "logging"), name


# CHK-M8-224: no Python `re` under the evaluator or the two M8 repositories
def _m8_files() -> list[Path]:
    files = sorted(EV.glob("*.py"))
    files += [BM / "repositories" / f"{r}.py" for r in REPOS]
    return [f for f in files if f.exists()]


@pytest.mark.parametrize("path", _m8_files(), ids=lambda p: p.name)
def test_no_python_re(path: Path) -> None:
    for name in _direct_imports(path):
        assert name != "re" and not name.startswith("re."), path.name
        assert name not in ("regex", "sre_compile", "sre_parse"), path.name


def test_ruff_bans_re_for_the_tree() -> None:
    text = (MANAGER / "pyproject.toml").read_text(encoding="utf-8")
    assert '"re".msg' in text


# CHK-M8-223: REQ-202 (3) no logging call formats a result field
LOG_METHODS = ("debug", "info", "warning", "error", "exception", "critical", "log")
RESULT_WORDS = ("stdout", "stderr", "expected", "pattern", "execute", "eval_spec")


@pytest.mark.parametrize("path", _m8_files(), ids=lambda p: p.name)
def test_no_logging_call_carries_a_result_field(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else ""
        if name not in LOG_METHODS:
            continue
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            for sub in ast.walk(arg):
                ident = (
                    sub.id
                    if isinstance(sub, ast.Name)
                    else sub.attr
                    if isinstance(sub, ast.Attribute)
                    else ""
                )
                assert not any(w in ident.lower() for w in RESULT_WORDS), (
                    f"{path.name}:{node.lineno} logs {ident}"
                )


@pytest.mark.parametrize("module", PURE)
def test_pure_modules_have_no_logging_at_all(module: str) -> None:
    src = (EV / f"{module}.py").read_text(encoding="utf-8")
    assert "logging" not in _direct_imports(EV / f"{module}.py")
    assert "getLogger" not in src
    assert "print(" not in src
