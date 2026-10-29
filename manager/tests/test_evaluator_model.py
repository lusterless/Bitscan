"""TP-M8-02: evaluator model (TASK-176; REQ-193, REQ-202).

Expected values come from TS §4.5 L589-L593 and L599, SR §2.4, and the
approved answers #12, #112 (a), #116 (a). CHK-M8-001 to -008 and -014
(tests/m8/test-plan.md).
"""

from __future__ import annotations

import ast
import dataclasses
import typing
import uuid
from pathlib import Path

import pytest

from bitscan_manager.services.evaluator import model
from bitscan_manager.services.evaluator.model import (
    ERROR,
    FAIL,
    INTAKE_DETAILS,
    PASS,
    STDERR_CAP,
    STDOUT_CAP,
    Detail,
    PluginSpec,
    Verdict,
)
from bitscan_manager.services.importer import model as importer_model

EVALUATOR = Path(model.__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
SPEC_PYPROJECT = REPO / "manager" / "pyproject.toml"

# #112 (a), in the #112 (c) order.
DETAILS_112 = (
    "oversize",
    "spool_overflow",
    "runner_unavailable",
    "timed out",
    "no exit code",
    "cannot run",
    "not found",
    "killed by signal",
    "stdout truncated",
    "cannot evaluate",
    "stdout not numeric",
)
# SR §2.4, in the SR table order (text, RE2, numeric, presence).
SR_OPERATORS = (
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "empty",
    "not_empty",
)


# CHK-M8-001
def test_operator_literal_equals_importer_tuple_in_order() -> None:
    assert typing.get_args(model.Operator) == importer_model.OPERATORS
    assert typing.get_args(model.Operator) == SR_OPERATORS
    assert len(set(typing.get_args(model.Operator))) == 14


# CHK-M8-002
def test_verdict_codes() -> None:
    assert (PASS, FAIL, ERROR) == (0, 1, 2)
    assert typing.get_args(model.VerdictCode) == (0, 1, 2)
    for code in (PASS, FAIL, ERROR):
        assert type(code) is int


# CHK-M8-003
def test_detail_is_exactly_the_112_vocabulary() -> None:
    assert [d.value for d in Detail] == list(DETAILS_112)
    for d in Detail:
        assert isinstance(d, str)
        assert d == d.value
        assert d.value.isascii()
        assert d.value == d.value.lower()
    # Exactly eleven, no aliases.
    assert len(Detail.__members__) == 11


def test_intake_details_is_the_frozen_12_set() -> None:
    assert isinstance(INTAKE_DETAILS, frozenset)
    assert {d.value for d in INTAKE_DETAILS} == {
        "oversize",
        "spool_overflow",
        "runner_unavailable",
    }
    assert all(isinstance(d, Detail) for d in INTAKE_DETAILS)
    # The wire `error` values of the M3 contract are intake details (#12).
    assert "spool_overflow" in INTAKE_DETAILS
    assert "runner_unavailable" in INTAKE_DETAILS
    assert "timed out" not in INTAKE_DETAILS


# CHK-M8-004
def test_caps_in_bytes() -> None:
    assert STDOUT_CAP == 64 * 1024 == 65_536
    assert STDERR_CAP == 16 * 1024 == 16_384


# CHK-M8-005
@pytest.mark.parametrize("code", [PASS, FAIL])
def test_pass_and_fail_take_no_detail(code: int) -> None:
    v = Verdict(code, None)  # type: ignore[arg-type]
    assert v.code == code
    assert v.detail is None


@pytest.mark.parametrize("detail", list(Detail))
def test_error_takes_each_detail(detail: Detail) -> None:
    v = Verdict(ERROR, detail)
    assert v.code == 2
    assert v.detail is detail


@pytest.mark.parametrize(
    ("code", "detail"),
    [
        (0, Detail.TIMED_OUT),
        (1, Detail.OVERSIZE),
        (0, Detail.STDOUT_NOT_NUMERIC),
        (1, Detail.CANNOT_EVALUATE),
        (2, None),
        (3, None),
        (3, Detail.TIMED_OUT),
        (-1, None),
        (-1, Detail.TIMED_OUT),
        (255, Detail.KILLED_BY_SIGNAL),
        (True, None),
        (False, None),
        (True, Detail.OVERSIZE),
        (2.0, Detail.OVERSIZE),
        ("2", Detail.OVERSIZE),
        (None, None),
        (2, "oversize"),
        (2, "timed out"),
        (2, "bogus"),
        (2, ""),
        (0, ""),
        (1, "stdout not numeric"),
    ],
)
def test_verdict_invariant_refuses(code: object, detail: object) -> None:
    with pytest.raises(ValueError) as info:
        Verdict(code, detail)  # type: ignore[arg-type]
    # Fixed message, quoting nothing of the input.
    assert "bogus" not in str(info.value)
    assert repr(code) not in str(info.value) or code in (0, 1, 2)


# CHK-M8-006
def test_verdict_and_pluginspec_are_frozen() -> None:
    v = Verdict(PASS, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.code = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.detail = Detail.OVERSIZE  # type: ignore[misc]
    s = PluginSpec(uuid.uuid4(), "F - p", "equals", "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.expected = "y"  # type: ignore[misc]
    assert [f.name for f in dataclasses.fields(PluginSpec)] == [
        "plugin_uuid",
        "name",
        "operator",
        "expected",
    ]
    assert [f.name for f in dataclasses.fields(Verdict)] == ["code", "detail"]


def test_verdict_equality_is_by_value() -> None:
    assert Verdict(ERROR, Detail.OVERSIZE) == Verdict(2, Detail.OVERSIZE)
    assert Verdict(ERROR, Detail.OVERSIZE) != Verdict(ERROR, Detail.TIMED_OUT)
    assert Verdict(PASS, None) != Verdict(FAIL, None)


def test_result_like_protocol_has_the_six_fields() -> None:
    members = {
        name
        for name, value in vars(model.ResultLike).items()
        if isinstance(value, property)
    }
    assert members == {
        "exit_code",
        "stdout",
        "stderr",
        "timed_out",
        "truncated",
        "error",
    }


# CHK-M8-008
def test_package_init_is_docstring_only() -> None:
    tree = ast.parse((EVALUATOR / "__init__.py").read_text(encoding="utf-8"))
    assert len(tree.body) == 1
    node = tree.body[0]
    assert isinstance(node, ast.Expr)
    assert isinstance(node.value, ast.Constant)
    assert isinstance(node.value.value, str)


# CHK-M8-014 (model and normalise; the full graph is in test_security_m8.py)
FORBIDDEN_PREFIXES = (
    "logging",
    "re",
    "psycopg",
    "bitscan_manager.db",
    "bitscan_manager.repositories",
    "bitscan_manager.api",
    "bitscan_manager.runtime",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports hide the graph"
            names.add(node.module or "")
    return names


@pytest.mark.parametrize("module", ["model.py", "normalise.py"])
def test_pure_modules_import_nothing_forbidden(module: str) -> None:
    for name in _imports(EVALUATOR / module):
        for bad in FORBIDDEN_PREFIXES:
            assert name != bad and not name.startswith(bad + "."), name
        assert not name.startswith("bitscan_manager"), name


# CHK-M8-007: an M3 ResultItem is a ResultLike under mypy --strict, and an
# object missing one of the six fields is not (so the probe can fail).
PROBE_OK = """
from bitscan_manager.api.agent.schemas import ResultItem
from bitscan_manager.services.evaluator.model import ResultLike

def take(r: ResultLike) -> ResultLike:
    return r

def probe(item: ResultItem) -> ResultLike:
    return take(item)
"""
PROBE_BAD = """
from dataclasses import dataclass
from bitscan_manager.services.evaluator.model import ResultLike

@dataclass(frozen=True)
class NoError:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool

def take(r: ResultLike) -> ResultLike:
    return r

def probe(item: NoError) -> ResultLike:
    return take(item)
"""


def _mypy(tmp_path: Path, name: str, text: str) -> tuple[int, str]:
    from mypy import api

    src = tmp_path / name
    src.write_text(text, encoding="utf-8")
    out, err, status = api.run(
        [
            "--strict",
            "--config-file",
            str(SPEC_PYPROJECT),
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            "--no-error-summary",
            str(src),
        ]
    )
    return status, out + err


def test_result_item_is_result_like_under_mypy_strict(tmp_path: Path) -> None:
    status, output = _mypy(tmp_path, "probe_ok.py", PROBE_OK)
    assert status == 0, output
    status, output = _mypy(tmp_path, "probe_bad.py", PROBE_BAD)
    assert status == 1, output
    assert "probe_bad.py" in output
    assert "error" in output
