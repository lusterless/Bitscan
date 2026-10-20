"""REQ-032 (6), REQ-009 (4): the conftest skip/exit hook, tested with pytester.

Checks CHK-M1-030 of tests/m1/test-plan.md. Each inner session loads the real
``tests/conftest.py`` text with only ``_docker_problem`` (the Docker probe)
replaced by a stub, so the hook logic under test is the shipped one. The stub
records every call, which proves when Docker is (not) probed. No Docker needed.
"""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

CONFTEST = Path(__file__).resolve().parent / "conftest.py"
NOT_RUN = "not run: Docker unavailable"

STUB = """

def _docker_problem():
    import os
    with open(os.environ["HOOK_PROBE_LOG"], "a", encoding="utf-8") as log:
        log.write("probe\\n")
    if os.environ["HOOK_DOCKER"] == "up":
        return None
    return "DockerException: stubbed: daemon unreachable"
"""

INNER_TESTS = """
import pytest


@pytest.mark.pg
def test_needs_pg():
    pass


def test_unit():
    pass
"""

UNIT_ONLY = """
def test_unit():
    pass
"""


@pytest.fixture
def inner(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Path:
    text = CONFTEST.read_text(encoding="utf-8")
    assert "def _docker_problem(" in text
    assert "def pytest_collection_modifyitems(" in text
    pytester.makeconftest(text + STUB)
    pytester.makeini("[pytest]\nmarkers =\n    pg: needs PostgreSQL\n")
    log = pytester.path / "probe.log"
    monkeypatch.setenv("HOOK_PROBE_LOG", str(log))
    monkeypatch.delenv("CI", raising=False)
    return log


def _probes(log: Path) -> int:
    return log.read_text(encoding="utf-8").count("probe") if log.exists() else 0


def _output(result: pytest.RunResult) -> str:
    return "\n".join(result.outlines + result.errlines)


def test_no_docker_local_skips_pg_and_runs_the_rest(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "down")
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest("-rs")
    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == 0
    result.stdout.fnmatch_lines([f"SKIPPED * {NOT_RUN}"])
    assert _probes(inner) == 1


@pytest.mark.parametrize("ci", ["false", "1", ""])
def test_ci_other_than_true_still_skips(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path, ci: str
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "down")
    monkeypatch.setenv("CI", ci)
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest("-rs")
    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == 0


@pytest.mark.parametrize("ci", ["true", "TRUE", "True"])
def test_no_docker_with_ci_true_fails_the_session(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path, ci: str
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "down")
    monkeypatch.setenv("CI", ci)
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest()
    assert result.ret != 0
    out = _output(result)
    assert NOT_RUN in out
    assert "CI=true" in out
    assert "passed" not in out.splitlines()[-1]
    assert _probes(inner) == 1


def test_no_pg_test_collected_does_not_probe(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "down")
    monkeypatch.setenv("CI", "true")
    pytester.makepyfile(test_inner=UNIT_ONLY)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
    assert result.ret == 0
    assert _probes(inner) == 0


def test_pg_deselected_does_not_probe(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "down")
    monkeypatch.setenv("CI", "true")
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest("-m", "not pg")
    result.assert_outcomes(passed=1, deselected=1)
    assert result.ret == 0
    assert _probes(inner) == 0


def test_docker_up_leaves_pg_tests_alone(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, inner: Path
) -> None:
    monkeypatch.setenv("HOOK_DOCKER", "up")
    monkeypatch.setenv("CI", "true")
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest("-rs")
    result.assert_outcomes(passed=2)
    assert result.ret == 0
    assert _probes(inner) == 1
