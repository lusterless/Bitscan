"""TASK-084: every bitscan_manager module imports on its own, first, in a fresh
interpreter (`python -I`), so no entry point or script can hit an import
cycle that the usual import order hides (the services.inventory cycle found at
the M3 gate: inventory/__init__ -> decode -> api.agent -> inventory.ingest ->
decode half-initialised).

Alembic's env.py and its version scripts run only inside Alembic (they need
its context) and are left out.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "bitscan_manager"
MANAGER = PKG.parent
SKIP = ("bitscan_manager.db.migrations.env", "bitscan_manager.db.migrations.versions")


# sys.modules, not the attribute: a package may re-export a function under
# its submodule's name (services.agents.heartbeat)
PROBE = (
    "import importlib, sys; sys.path.insert(0, {root!r}); "
    "importlib.import_module({name!r}); "
    "assert sys.modules[{name!r}].__file__.startswith({root!r})"
)


def module_names() -> list[str]:
    names = []
    for path in sorted(PKG.rglob("*.py")):
        parts = path.relative_to(MANAGER).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts)
        if not name.startswith(SKIP):
            names.append(name)
    return names


def import_alone(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, module names from the tree
        # -I drops PYTHONPATH and the cwd, so the tree this test belongs to
        # is put first explicitly (a copy under test, not an installed one)
        [
            sys.executable,
            "-I",
            "-c",
            PROBE.format(root=str(MANAGER), name=name),
        ],
        cwd=MANAGER,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_walk_sees_the_modules() -> None:
    names = module_names()
    assert len(names) >= 90
    for wanted in (
        "bitscan_manager.services.inventory",
        "bitscan_manager.services.inventory.decode",
        "bitscan_manager.services.inventory.ingest",
        "bitscan_manager.services.inventory.upload",
        "bitscan_manager.api.agent",
        "bitscan_manager.app",
    ):
        assert wanted in names


@pytest.mark.parametrize("name", module_names())
def test_module_imports_first_in_a_fresh_interpreter(name: str) -> None:
    done = import_alone(name)
    assert done.returncode == 0, done.stderr[-2000:]
