"""TASK-069 code checks (CHK-M3-218; REQ-084 (3)): one RE2 compile of the
redaction patterns, in services/settings/store.py, with RE2's log_errors off
(lead ruling 2026-10-23), and the G1 ban on stdlib `re` in the new module.
The G1 plant runs ruff with the project configuration on a temporary copy,
never in the tree.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from bitscan_manager.services.settings import redaction

from .test_settings_service import DEFAULT_PATTERNS

MANAGER = Path(__file__).resolve().parents[1]
SETTINGS = MANAGER / "bitscan_manager" / "services" / "settings"


def test_defaults_are_the_spec_lines() -> None:
    assert [p.encode() for p in redaction.DEFAULT_PATTERNS] == [
        p.encode() for p in DEFAULT_PATTERNS
    ]


def test_removed_defaults() -> None:
    d = list(DEFAULT_PATTERNS)
    assert redaction.removed_defaults(d, d[:2] + d[3:]) == [d[2]]
    assert redaction.removed_defaults(d, list(reversed(d))) == []
    assert redaction.removed_defaults(d[1:], d[2:]) == [d[1]]  # d[0] gone before
    assert redaction.removed_defaults(d, []) == d
    assert redaction.removed_defaults([], []) == []


def test_one_re2_compile_only() -> None:
    text = (SETTINGS / "redaction.py").read_text(encoding="utf-8")
    assert "re2" not in text and "compile(" not in text
    users = [
        p.name for p in SETTINGS.glob("*.py") if "re2.compile(" in p.read_text("utf-8")
    ]
    assert users == ["store.py"]
    store = (SETTINGS / "store.py").read_text(encoding="utf-8")
    assert store.count("re2.compile(") == 1
    assert "log_errors = False" in store


def _ruff(root: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, the test's own interpreter
        [sys.executable, "-m", "ruff", "check", "--no-cache", str(target)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_g1_plant_import_re_in_redaction_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "manager"
    pkg = root / "bitscan_manager" / "services" / "settings"
    pkg.mkdir(parents=True)
    shutil.copy(MANAGER / "pyproject.toml", root / "pyproject.toml")
    clean = (SETTINGS / "redaction.py").read_text(encoding="utf-8")
    target = pkg / "redaction.py"
    target.write_text(clean, encoding="utf-8", newline="\n")
    control = _ruff(root, target)
    assert control.returncode == 0, control.stdout + control.stderr
    target.write_text(
        clean + "\nimport re  # planted\n", encoding="utf-8", newline="\n"
    )
    planted = _ruff(root, target)
    assert planted.returncode == 1, planted.stdout + planted.stderr
    assert "TID251" in planted.stdout, planted.stdout
