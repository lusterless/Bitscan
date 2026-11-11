"""REQ-001 (1), REQ-004, REQ-005, REQ-008: manager/pyproject.toml settings.

Checks CHK-M0-001 and CHK-M0-011 of tests/m0/test-plan.md.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet

MANAGER = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    with (MANAGER / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


@pytest.mark.parametrize(
    ("version", "admitted"),
    [
        ("3.12.0", True),
        ("3.12.10", True),
        ("3.11.9", False),
        ("3.13.0", False),
        ("3.10.0", False),
    ],
)
def test_requires_python_is_312_only(
    pyproject: dict[str, Any], version: str, admitted: bool
) -> None:
    spec = SpecifierSet(pyproject["project"]["requires-python"])
    assert spec.contains(version) is admitted


def test_version_and_console_script(pyproject: dict[str, Any]) -> None:
    project = pyproject["project"]
    assert project["name"] == "bitscan-manager"
    assert project["version"] == "0.2.0"
    assert project["scripts"]["bitscan-manager"] == "bitscan_manager.cli:main"


def test_mypy_is_strict_for_312(pyproject: dict[str, Any]) -> None:
    mypy = pyproject["tool"]["mypy"]
    assert mypy["strict"] is True
    assert str(mypy["python_version"]) == "3.12"


def test_coverage_measures_only_services_at_85(pyproject: dict[str, Any]) -> None:
    coverage = pyproject["tool"]["coverage"]
    sources = [s.replace(".", "/").rstrip("/") for s in coverage["run"]["source"]]
    assert sources == ["bitscan_manager/services"]
    assert float(coverage["report"]["fail_under"]) == 85.0


def test_fail_under_is_not_in_pytest_addopts(pyproject: dict[str, Any]) -> None:
    ini = pyproject["tool"]["pytest"]["ini_options"]
    addopts = ini.get("addopts", "")
    joined = addopts if isinstance(addopts, str) else " ".join(addopts)
    assert "--cov-fail-under" not in joined
    assert any(str(m).startswith("pg") for m in ini["markers"])


def test_ruff_targets_312(pyproject: dict[str, Any]) -> None:
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"
