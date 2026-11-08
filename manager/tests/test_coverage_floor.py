"""TASK-255 TEST: the services coverage floor in a real coverage run
(REQ-292; `.claude/rules/testing.md` "at least 85 % line coverage on
manager/services"; TS §8.3; G5).

The gate is pytest-cov's `--cov-fail-under=85` (as `manager.yml` runs it)
with the `[tool.coverage]` settings of `manager/pyproject.toml`. Each case
below runs the real pytest, pytest-cov and coverage.py in a subprocess over a
generated package whose covered share is chosen exactly, with
`--cov-config` pointing at the committed `manager/pyproject.toml`:

- 5,693 of 6,698 statements (84.9955 %, the M9 plant, printed as "85.00 %"
  at two decimals) must exit non-zero;
- 8,499 of 10,000 (84.99 %) must exit non-zero;
- 5,695 of 6,700 (exactly 85 %) must exit 0;
- 5,696 of 6,700 (85.0149 %) must exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def package(root: Path, covered: int, total: int) -> None:
    """A module with `total` statements of which a test runs `covered`:
    the two `def` lines run at import, `hot()` holds covered - 2 statements
    and is called, `cold()` holds the rest and is never called."""
    hot, cold = covered - 2, total - covered
    assert hot > 0 and cold > 0
    pkg = root / "floorpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    body = ["def hot():"] + ["    v = 1"] * hot + ["", "", "def cold():"]
    body += ["    v = 2"] * cold
    (pkg / "mod.py").write_text("\n".join(body) + "\n", encoding="utf-8")
    (root / "test_floor.py").write_text(
        "from floorpkg import mod\n\n\ndef test_hot():\n    mod.hot()\n",
        encoding="utf-8",
    )
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def gate(root: Path, config: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(root), CI="true")
    env.pop("COVERAGE_PROCESS_START", None)
    return subprocess.run(  # noqa: S603 - the test's own interpreter
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-c",
            str(root / "pytest.ini"),
            "--rootdir",
            str(root),
            "-q",
            "--cov=floorpkg",
            f"--cov-config={config}",
            "--cov-fail-under=85",
            "--cov-report=term",
            str(root / "test_floor.py"),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_committed_floor_is_85_at_four_digits() -> None:
    report = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["coverage"]
    assert report["report"]["fail_under"] == 85  # the gate is not lowered
    assert report["report"]["precision"] == 4
    assert report["run"]["branch"] is False  # line coverage (the 5/N argument)


@pytest.mark.parametrize(
    ("covered", "total", "passes", "shown"),
    [
        (5693, 6698, False, "84.9955"),
        (8499, 10000, False, "84.9900"),
        (5695, 6700, True, "85.0000"),
        (5696, 6700, True, "85.0149"),
    ],
    ids=["84.9955", "84.99", "85.00", "85.0149"],
)
def test_real_coverage_run_against_the_floor(
    tmp_path: Path, covered: int, total: int, passes: bool, shown: str
) -> None:
    package(tmp_path, covered, total)
    run = gate(tmp_path, PYPROJECT)
    out = run.stdout + run.stderr
    assert "1 passed" in out, out[-2000:]
    # the gate's decision first (the exit code), then how it is reported
    assert (run.returncode == 0) is passes, (run.returncode, out[-2000:])
    assert f"{shown}%" in out, out[-2000:]  # the TOTAL row at four digits
    if passes:
        assert "Coverage failure" not in out
    else:
        assert (
            f"Coverage failure: total of {shown} is less than fail-under=85.0000" in out
        )
