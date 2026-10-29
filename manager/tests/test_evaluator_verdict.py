"""TP-M8-05: `result_verdict()`, the intake verdict (TASK-179; REQ-194,
REQ-205 (2)).

Order (#112 (c), #116 (c), #12): `oversize` (stdout over 65,536 or stderr over
16,384 UTF-8 bytes, whatever the agent's flags say; TS §4.5 L599, #57, #116)
→ the runner `error` (`spool_overflow`, `runner_unavailable`; any other value
`cannot evaluate`) without calling `classify()` → `classify()` on stdout only
(SR §2.4 "Only stdout is compared"). CHK-M8-100 to -109.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.api.agent.schemas import ResultItem
from bitscan_manager.services.evaluator import verdict as verdict_module
from bitscan_manager.services.evaluator.eval_spec import (
    EvalSpec,
    build_eval_spec,
    parse_eval_spec,
)
from bitscan_manager.services.evaluator.evaluate import classify
from bitscan_manager.services.evaluator.model import Detail, PluginSpec, Verdict
from bitscan_manager.services.evaluator.verdict import result_verdict, utf8_size

SR_UUID = uuid.UUID("3f1c2a4e-8b7d-4c1e-9a2f-5d6e7f8a9b0c")
SR_SPEC = PluginSpec(
    SR_UUID,
    "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed",
    "equals",
    "install ok installed",
)


@dataclass(frozen=True)
class R:
    """A ResultLike with the six fields."""

    stdout: str = "install ok installed"
    stderr: str = ""
    exit_code: int | None = 0
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None


def _rv(result: R, spec: PluginSpec = SR_SPEC) -> Verdict:
    v = result_verdict(spec, result)
    assert isinstance(v, Verdict)
    return v


OVERSIZE = Verdict(2, Detail.OVERSIZE)


# CHK-M8-100: stdout cap in UTF-8 bytes
def test_utf8_size_counts_bytes() -> None:
    assert utf8_size("") == 0
    assert utf8_size("a") == 1
    assert utf8_size("é") == 2
    assert utf8_size("€") == 3
    assert utf8_size("😀") == 4
    assert utf8_size("a€😀") == 8


def test_stdout_exactly_at_the_cap_passes() -> None:
    spec = PluginSpec(SR_UUID, "F - p", "not_empty", "")
    assert _rv(R(stdout="a" * 65_536), spec) == Verdict(0, None)
    assert _rv(R(stdout="a" * 65_537), spec) == OVERSIZE


def test_stdout_cap_measured_in_bytes_not_characters() -> None:
    spec = PluginSpec(SR_UUID, "F - p", "not_empty", "")
    at_cap = "€" * 21_845 + "a"  # 65,536 bytes, 21,846 characters
    assert utf8_size(at_cap) == 65_536
    assert _rv(R(stdout=at_cap), spec) == Verdict(0, None)
    over = "€" * 21_846  # 65,538 bytes, 21,846 characters
    assert len(over) < 65_536 < utf8_size(over)
    assert _rv(R(stdout=over), spec) == OVERSIZE
    emoji = "😀" * 16_384  # 65,536 bytes, 16,384 characters
    assert _rv(R(stdout=emoji), spec) == Verdict(0, None)
    assert _rv(R(stdout=emoji + "a"), spec) == OVERSIZE


# CHK-M8-101: stderr cap in UTF-8 bytes; flags never avoid a cap
def test_stderr_cap() -> None:
    assert _rv(R(stderr="e" * 16_384)) == Verdict(0, None)
    assert _rv(R(stderr="e" * 16_385)) == OVERSIZE
    over = "€" * 5_462  # 16,386 bytes, 5,462 characters
    assert len(over) < 16_384 < utf8_size(over)
    assert _rv(R(stderr=over)) == OVERSIZE
    at = "€" * 5_461 + "a"  # 16,384 bytes
    assert utf8_size(at) == 16_384
    assert _rv(R(stderr=at)) == Verdict(0, None)


@pytest.mark.parametrize(
    "flags",
    [
        {},
        {"truncated": False},
        {"truncated": True},
        {"timed_out": True},
        {"exit_code": None},
        {"exit_code": 127},
        {"exit_code": -1},
    ],
)
def test_flags_do_not_avoid_the_caps(flags: dict[str, Any]) -> None:
    assert _rv(replace(R(stdout="a" * 65_537), **flags)) == OVERSIZE
    assert _rv(replace(R(stderr="e" * 16_385), **flags)) == OVERSIZE


def test_truncated_flag_alone_is_not_oversize() -> None:
    # The manager's own measurement decides oversize, not the agent's flag.
    assert _rv(R(truncated=True)) == Verdict(2, Detail.STDOUT_TRUNCATED)
    assert _rv(R(stdout="a" * 65_536, truncated=True)) == Verdict(
        2, Detail.STDOUT_TRUNCATED
    )


# CHK-M8-102: lone surrogates are counted without raising
def test_lone_surrogates_are_sized_and_never_raise() -> None:
    assert utf8_size("\ud800") == 3
    spec = PluginSpec(SR_UUID, "F - p", "not_empty", "")
    at = "\ud800" * 21_845 + "a"  # 65,536 under surrogatepass
    assert _rv(R(stdout=at), spec).detail is not Detail.OVERSIZE
    assert _rv(R(stdout="\ud800" * 21_846), spec) == OVERSIZE
    assert _rv(R(stderr="\udfff" * 5_462)) == OVERSIZE
    assert _rv(R(stderr="\udfff" * 5_461)) == Verdict(0, None)


# CHK-M8-103: REQ-194 (2) oversize before the runner error
@pytest.mark.parametrize("error", ["spool_overflow", "runner_unavailable", "bogus"])
def test_oversize_wins_over_the_runner_error(error: str) -> None:
    assert _rv(R(stdout="a" * 65_537, error=error)) == OVERSIZE
    assert _rv(R(stderr="e" * 16_385, error=error)) == OVERSIZE
    assert _rv(R(stderr="e" * 16_385, error=error, timed_out=True)) == OVERSIZE


# CHK-M8-104: REQ-194 (3) runner errors decided without classify
@pytest.fixture
def classify_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def spy(*args: Any) -> Verdict:
        calls.append(args)
        return classify(*args)

    monkeypatch.setattr(verdict_module, "classify", spy)
    return calls


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        ("spool_overflow", Detail.SPOOL_OVERFLOW),
        ("runner_unavailable", Detail.RUNNER_UNAVAILABLE),
    ],
)
def test_runner_error_without_classify(
    classify_spy: list[tuple[Any, ...]], error: str, detail: Detail
) -> None:
    assert _rv(R(error=error)) == Verdict(2, detail)
    assert _rv(R(error=error, stdout="", exit_code=None)) == Verdict(2, detail)
    assert _rv(R(error=error, timed_out=True)) == Verdict(2, detail)
    assert classify_spy == []


def test_no_error_calls_classify_once_with_the_six_values(
    classify_spy: list[tuple[Any, ...]],
) -> None:
    spec = PluginSpec(SR_UUID, "F - p", "eq", "42")
    r = R(stdout=" 42\n", stderr="warn", exit_code=3, timed_out=False, truncated=False)
    assert _rv(r, spec) == Verdict(0, None)
    assert classify_spy == [("eq", "42", " 42\n", 3, False, False)]


# CHK-M8-105: an error value outside the contract
@pytest.mark.parametrize(
    "error", ["bogus", "", "SPOOL_OVERFLOW", " spool_overflow", "timed out"]
)
def test_unknown_runner_error_cannot_evaluate(
    classify_spy: list[tuple[Any, ...]], error: str
) -> None:
    assert _rv(R(error=error)) == Verdict(2, Detail.CANNOT_EVALUATE)
    assert classify_spy == []


# CHK-M8-106: REQ-194 (4) stderr is never compared
def test_stderr_never_changes_the_verdict() -> None:
    noise = ("ERROR: permission denied\n" * 700)[:16_384]
    assert utf8_size(noise) == 16_384
    assert _rv(R(stderr=noise)) == Verdict(0, None)
    # The expected text in stderr does not turn a FAIL into a PASS...
    assert _rv(R(stdout="", stderr="install ok installed")) == Verdict(1, None)
    # ...nor make not_contains FAIL, nor feed a numeric operator.
    spec = PluginSpec(SR_UUID, "F - p", "not_contains", "nullok")
    assert _rv(R(stdout="ok", stderr="nullok"), spec) == Verdict(0, None)
    spec = PluginSpec(SR_UUID, "F - p", "eq", "0")
    assert _rv(R(stdout="abc", stderr="0"), spec) == Verdict(
        2, Detail.STDOUT_NOT_NUMERIC
    )
    spec = PluginSpec(SR_UUID, "F - p", "empty", "")
    assert _rv(R(stdout="", stderr="something"), spec) == Verdict(0, None)


# CHK-M8-107: REQ-194 (5), REQ-205 (2), through the spec build_eval_spec makes
def _sr_entry() -> PluginSpec:
    built = build_eval_spec(EvalSpec((SR_SPEC,)))
    spec = parse_eval_spec(built)
    entry = spec.get(SR_UUID)
    assert entry is not None
    return entry


def test_sr_1_1_through_result_verdict() -> None:
    entry = _sr_entry()
    assert entry.operator == "equals"
    assert entry.expected == "install ok installed"
    assert _rv(R(stdout="install ok installed", exit_code=0), entry) == Verdict(0, None)
    assert _rv(R(stdout="", exit_code=0), entry) == Verdict(1, None)
    assert _rv(R(stdout="", exit_code=1), entry) == Verdict(1, None)
    assert _rv(R(stdout="install ok installed\n", exit_code=0), entry) == Verdict(
        0, None
    )


# CHK-M8-108: REQ-194 (6) a real M3 ResultItem, and no api import
def _item(**over: Any) -> ResultItem:
    body: dict[str, Any] = {
        "plugin_uuid": str(SR_UUID),
        "exit_code": 0,
        "stdout": "install ok installed",
        "stderr": "",
        "started_at": "2026-10-29T10:00:00Z",
        "finished_at": "2026-10-29T10:00:01Z",
        "timed_out": False,
        "truncated": False,
        "error": None,
    }
    body.update(over)
    return ResultItem.model_validate(body)


def test_accepts_the_m3_result_item() -> None:
    assert result_verdict(SR_SPEC, _item()) == Verdict(0, None)
    assert result_verdict(SR_SPEC, _item(stdout="")) == Verdict(1, None)
    assert result_verdict(SR_SPEC, _item(error="spool_overflow")) == Verdict(
        2, Detail.SPOOL_OVERFLOW
    )
    assert result_verdict(SR_SPEC, _item(stdout="a" * 65_537)) == OVERSIZE
    assert result_verdict(SR_SPEC, _item(exit_code=None)) == Verdict(
        2, Detail.NO_EXIT_CODE
    )


def test_verdict_module_imports_nothing_from_api() -> None:
    tree = ast.parse(Path(verdict_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("bitscan_manager.api")
            assert not (node.module or "").startswith("bitscan_manager.repositories")
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("bitscan_manager.api")


# CHK-M8-109: inside the caps and with no error, result_verdict == classify
@pytest.mark.parametrize(
    "result",
    [
        R(),
        R(stdout=""),
        R(exit_code=None),
        R(exit_code=126),
        R(exit_code=127),
        R(exit_code=128),
        R(exit_code=-1),
        R(exit_code=1),
        R(timed_out=True),
        R(truncated=True),
        R(stdout="install ok installed\r\n"),
        R(stdout="\ud800"),
    ],
)
@pytest.mark.parametrize(
    "spec",
    [
        SR_SPEC,
        PluginSpec(SR_UUID, "F - p", "regex", "["),
        PluginSpec(SR_UUID, "F - p", "eq", "1"),
        PluginSpec(SR_UUID, "F - p", "BOGUS", "x"),
        PluginSpec(SR_UUID, "F - p", "not_empty", ""),
    ],
)
def test_agrees_with_classify(result: R, spec: PluginSpec) -> None:
    want = classify(
        spec.operator,
        spec.expected,
        result.stdout,
        result.exit_code,
        result.timed_out,
        result.truncated,
    )
    assert result_verdict(spec, result) == want


def test_result_verdict_never_quotes_input() -> None:
    canary = "M8CANARY-verdict-0d1e"
    spec = PluginSpec(SR_UUID, canary, "eq", "1")
    for r in (
        R(stdout=canary),
        R(stdout=canary * 5_000),
        R(stderr=canary * 2_000),
        R(error=canary),
    ):
        v = result_verdict(spec, r)
        assert v.code == 2
        assert canary not in str(v.detail)
        assert canary not in repr(v)
