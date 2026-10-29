"""TP-M8-04: `classify()` and `evaluate()` (TASK-178; REQ-186, REQ-192,
REQ-193, REQ-205; REQ-187 (3), (5) and REQ-190 (4) end to end).

Expected values: TS §4.5 L589-L600 (return codes, ERROR cases, normalisation,
"the exit code does not decide", the six-parameter signature), SR §1.1 L87 and
§2.4, and the approved answers #112 (vocabulary and order), #113 (truncated is
ERROR for every operator), #114 (None and negative exit codes are ERROR).
CHK-M8-060 to -077 (tests/m8/test-plan.md).
"""

from __future__ import annotations

import inspect
import logging
import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest

from bitscan_manager.services.evaluator import evaluate as evaluate_module
from bitscan_manager.services.evaluator.evaluate import classify, evaluate
from bitscan_manager.services.evaluator.model import Detail, Verdict
from bitscan_manager.services.importer.model import OPERATORS

PASS_INPUT: dict[str, tuple[str, str]] = {
    # operator -> (expected, stdout) that PASS with exit 0 and no flags
    "equals": ("install ok installed", "install ok installed"),
    "not_equals": ("disabled", "enabled"),
    "contains": ("PermitRootLogin no", "Port 22\nPermitRootLogin no"),
    "not_contains": ("nullok", "auth required pam_unix.so"),
    "regex": (r"^MaxAuthTries\s+[1-4]$", "Port 22\nMaxAuthTries 3\nX"),
    "not_regex": (r"^\s*PermitEmptyPasswords\s+yes", "PermitEmptyPasswords no"),
    "eq": ("0", "0"),
    "ne": ("0", "1"),
    "gt": ("13", "14"),
    "ge": ("14", "14"),
    "lt": ("91", "90"),
    "le": ("90", "90"),
    "empty": ("", ""),
    "not_empty": ("", "x"),
}
FAIL_INPUT: dict[str, tuple[str, str]] = {
    "equals": ("install ok installed", ""),
    "not_equals": ("disabled", "disabled"),
    "contains": ("PermitRootLogin no", "PermitRootLogin yes"),
    "not_contains": ("nullok", "pam_unix.so nullok_secure"),
    "regex": (r"^MaxAuthTries\s+[1-4]$", "MaxAuthTries 6"),
    "not_regex": (r"^\s*PermitEmptyPasswords\s+yes", "PermitEmptyPasswords yes"),
    "eq": ("0", "1"),
    "ne": ("0", "0"),
    "gt": ("13", "13"),
    "ge": ("14", "13"),
    "lt": ("91", "91"),
    "le": ("90", "91"),
    "empty": ("", "x"),
    "not_empty": ("", ""),
}


def V(op: str, expected: str, stdout: str, exit_code: int | None = 0,
      timed_out: bool = False, truncated: bool = False) -> Verdict:  # fmt: skip
    """classify, after checking evaluate agrees (REQ-186 (1))."""
    v = classify(op, expected, stdout, exit_code, timed_out, truncated)
    assert isinstance(v, Verdict)
    code = evaluate(op, expected, stdout, exit_code, timed_out, truncated)
    assert code == v.code
    assert code in (0, 1, 2)
    assert type(code) is int
    return v


def test_tables_are_complete() -> None:
    assert tuple(PASS_INPUT) == OPERATORS
    assert tuple(FAIL_INPUT) == OPERATORS


# CHK-M8-060: REQ-186 (2)
@pytest.mark.parametrize("fn", [evaluate, classify])
def test_signature_is_the_six_parameters(fn: Any) -> None:
    params = list(inspect.signature(fn).parameters.values())
    assert [p.name for p in params] == [
        "operator",
        "expected",
        "stdout",
        "exit_code",
        "timed_out",
        "truncated",
    ]
    for p in params:
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert p.default is inspect.Parameter.empty


# CHK-M8-061, -069
@pytest.mark.parametrize("op", OPERATORS)
def test_every_operator_pass_and_fail(op: str) -> None:
    assert V(op, *PASS_INPUT[op]) == Verdict(0, None)
    assert V(op, *FAIL_INPUT[op]) == Verdict(1, None)


# CHK-M8-062: REQ-192 (1) and #114
@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 100, 124, 125])
@pytest.mark.parametrize("op", OPERATORS)
def test_ordinary_exit_codes_never_decide(op: str, exit_code: int) -> None:
    assert V(op, *PASS_INPUT[op], exit_code=exit_code) == Verdict(0, None)
    assert V(op, *FAIL_INPUT[op], exit_code=exit_code) == Verdict(1, None)


@pytest.mark.parametrize(
    ("exit_code", "detail"),
    [
        (126, Detail.CANNOT_RUN),
        (127, Detail.NOT_FOUND),
        (128, Detail.KILLED_BY_SIGNAL),
        (129, Detail.KILLED_BY_SIGNAL),
        (137, Detail.KILLED_BY_SIGNAL),
        (143, Detail.KILLED_BY_SIGNAL),
        (255, Detail.KILLED_BY_SIGNAL),
        (256, Detail.KILLED_BY_SIGNAL),
        (2**31 - 1, Detail.KILLED_BY_SIGNAL),
        (-1, Detail.KILLED_BY_SIGNAL),
        (-9, Detail.KILLED_BY_SIGNAL),
        (-(2**31), Detail.KILLED_BY_SIGNAL),
        (None, Detail.NO_EXIT_CODE),
    ],
)
@pytest.mark.parametrize("op", OPERATORS)
def test_error_exit_codes(op: str, exit_code: int | None, detail: Detail) -> None:
    assert V(op, *PASS_INPUT[op], exit_code=exit_code) == Verdict(2, detail)
    assert V(op, *FAIL_INPUT[op], exit_code=exit_code) == Verdict(2, detail)


def test_exit_code_boundaries_around_126_to_128() -> None:
    e, s = PASS_INPUT["equals"]
    assert V("equals", e, s, 125).code == 0
    assert V("equals", e, s, 126).detail is Detail.CANNOT_RUN
    assert V("equals", e, s, 127).detail is Detail.NOT_FOUND
    assert V("equals", e, s, 128).detail is Detail.KILLED_BY_SIGNAL
    assert V("equals", e, s, 0).code == 0
    assert V("equals", e, s, -1).detail is Detail.KILLED_BY_SIGNAL


# CHK-M8-063: REQ-192 (2)
@pytest.mark.parametrize("op", OPERATORS)
def test_timed_out_is_error_for_every_operator(op: str) -> None:
    assert V(op, *PASS_INPUT[op], timed_out=True) == Verdict(2, Detail.TIMED_OUT)
    assert V(op, *FAIL_INPUT[op], timed_out=True) == Verdict(2, Detail.TIMED_OUT)


# CHK-M8-064: REQ-192 (2), #113
@pytest.mark.parametrize("op", OPERATORS)
def test_truncated_is_error_for_every_operator(op: str) -> None:
    pass_v = V(op, *PASS_INPUT[op], truncated=True)
    assert pass_v == Verdict(2, Detail.STDOUT_TRUNCATED)
    fail_v = V(op, *FAIL_INPUT[op], truncated=True)
    assert fail_v == Verdict(2, Detail.STDOUT_TRUNCATED)


def test_truncated_contains_with_expected_inside_kept_text() -> None:
    stdout = "x" * 1000 + "PermitRootLogin no" + "y" * 1000
    assert V("contains", "PermitRootLogin no", stdout).code == 0
    assert V("contains", "PermitRootLogin no", stdout, truncated=True) == Verdict(
        2, Detail.STDOUT_TRUNCATED
    )


# CHK-M8-065: REQ-192 (3), the grep shape
def test_grep_exit_1_with_empty_output() -> None:
    assert V("empty", "", "", 1) == Verdict(0, None)
    assert V("not_empty", "", "", 1) == Verdict(1, None)
    assert V("not_contains", "nullok", "", 1) == Verdict(0, None)
    assert V("equals", "", "", 1) == Verdict(0, None)


# CHK-M8-066: REQ-192 (4)
@pytest.mark.parametrize("op", ["EQUALS", "equal", "", "Equals", " equals", "regexp"])
def test_unknown_operator_cannot_evaluate(op: str) -> None:
    assert V(op, "x", "x") == Verdict(2, Detail.CANNOT_EVALUATE)
    assert V(op, "1", "1") == Verdict(2, Detail.CANNOT_EVALUATE)
    assert V(op, "", "") == Verdict(2, Detail.CANNOT_EVALUATE)


# CHK-M8-067: REQ-193 (1), one case per evaluation detail
@pytest.mark.parametrize(
    ("args", "detail"),
    [
        (("equals", "x", "x", 0, True, False), Detail.TIMED_OUT),
        (("equals", "x", "x", None, False, False), Detail.NO_EXIT_CODE),
        (("equals", "x", "x", 126, False, False), Detail.CANNOT_RUN),
        (("equals", "x", "x", 127, False, False), Detail.NOT_FOUND),
        (("equals", "x", "x", 137, False, False), Detail.KILLED_BY_SIGNAL),
        (("equals", "x", "x", 0, False, True), Detail.STDOUT_TRUNCATED),
        (("regex", "(?=x)", "x", 0, False, False), Detail.CANNOT_EVALUATE),
        (("eq", "0", "zero", 0, False, False), Detail.STDOUT_NOT_NUMERIC),
    ],
)
def test_one_case_per_detail(args: tuple[Any, ...], detail: Detail) -> None:
    v = V(*args)
    assert v == Verdict(2, detail)
    assert v.detail is not None
    assert v.detail.value == detail.value


# CHK-M8-068: REQ-193 (2) and the #112 (c) order
@pytest.mark.parametrize(
    ("args", "detail"),
    [
        # REQ-193 (2)
        (("equals", "x", "x", 137, True, True), Detail.TIMED_OUT),
        (("equals", "x", "x", 127, False, True), Detail.NOT_FOUND),
        (("eq", "0", "zero", 0, False, True), Detail.STDOUT_TRUNCATED),
        # the rest of the order
        (("equals", "x", "x", None, True, True), Detail.TIMED_OUT),
        (("equals", "x", "x", None, False, True), Detail.NO_EXIT_CODE),
        (("equals", "x", "x", 126, True, False), Detail.TIMED_OUT),
        (("equals", "x", "x", 126, False, True), Detail.CANNOT_RUN),
        (("equals", "x", "x", 128, False, True), Detail.KILLED_BY_SIGNAL),
        (("equals", "x", "x", -1, False, True), Detail.KILLED_BY_SIGNAL),
        (("BOGUS", "x", "x", 128, False, False), Detail.KILLED_BY_SIGNAL),
        (("BOGUS", "x", "x", 0, False, True), Detail.STDOUT_TRUNCATED),
        (("BOGUS", "x", "x", 0, True, False), Detail.TIMED_OUT),
        (("BOGUS", "x", "abc", 0, False, False), Detail.CANNOT_EVALUATE),
        (("eq", "abc", "abc", 0, False, False), Detail.CANNOT_EVALUATE),
        (("regex", "[", "\ud800", 0, False, False), Detail.CANNOT_EVALUATE),
        (("eq", "abc", "abc", 0, False, True), Detail.STDOUT_TRUNCATED),
        (("eq", "1", "abc", 127, False, False), Detail.NOT_FOUND),
    ],
)
def test_detail_order(args: tuple[Any, ...], detail: Detail) -> None:
    assert V(*args) == Verdict(2, detail)


# CHK-M8-070, -071: normalisation through classify (REQ-187 (3), (5); REQ-190 (4))
@pytest.mark.parametrize(
    ("args", "code"),
    [
        (("equals", "install ok installed", "Install ok installed"), 1),
        (("equals", "x\r\n", "x"), 0),
        (("equals", "  x\t", "\r\nx\r\n"), 0),
        (("equals", "a\r\nb", "a\nb"), 0),
        (("equals", "a\nb", "a\r\nb\r\n"), 0),
        (("eq", "42", " 42\r\n"), 0),
        (("eq", " 42 ", "42"), 0),
        (("gt", "\t13\n", "14\r\n"), 0),
        (("regex", "^x$", "x\r\n"), 0),
        (("regex", "^a$", "a\r\nb"), 0),
        (("regex", "^a\\r$", "a\r\nb"), 1),
        (("empty", "", "\r\n"), 0),
        (("empty", "", " \r\n\t"), 0),
        (("empty", "", " "), 0),
        (("not_empty", "", " \t"), 1),
        (("not_empty", "", " "), 0),  # REQ-191 (1): U+00A0 is content
        (("empty", "", " "), 1),
        (("not_empty", "", "0"), 0),
        (("contains", "ok\r\n", "install ok"), 0),
        (("not_contains", "x", "\r\n"), 0),
    ],
)
def test_normalisation_before_comparison(args: tuple[str, str, str], code: int) -> None:
    assert V(*args).code == code


# CHK-M8-072: the false-PASS hunt through classify
@pytest.mark.parametrize(
    ("op", "expected", "stdout"),
    [
        ("not_regex", "(?=x)", "y"),
        ("not_regex", "[", "y"),
        ("not_regex", r"(a)\1", "b"),
        ("not_regex", "a", "\ud800"),
        ("not_regex", "a", "b\udfff"),
        ("ne", "0", "abc"),
        ("ne", "0", ""),
        ("ne", "0", "1e3"),
        ("ne", "0", "nan"),
        ("ne", "abc", "1"),
        ("ne", "", "1"),
        ("NOT_EQUALS", "a", "b"),
        ("NOT_CONTAINS", "a", "b"),
        ("NOT_EMPTY", "", "x"),
        ("not_empty ", "", "x"),
        ("Empty", "", ""),
    ],
)
def test_negated_operators_never_pass_on_uncomparable_input(
    op: str, expected: str, stdout: str
) -> None:
    v = V(op, expected, stdout)
    assert v.code == 2
    assert v.detail in (Detail.CANNOT_EVALUATE, Detail.STDOUT_NOT_NUMERIC)


@pytest.mark.parametrize("op", ["eq", "ne", "gt", "ge", "lt", "le"])
@pytest.mark.parametrize(
    "stdout", ["abc", "", "1e3", "nan", "inf", "1_000", "0x10", ".5", "5.", "5 6"]
)
def test_numeric_non_numeric_stdout(op: str, stdout: str) -> None:
    assert V(op, "0", stdout) == Verdict(2, Detail.STDOUT_NOT_NUMERIC)


def test_numeric_multi_line_stdout_is_not_numeric() -> None:
    assert V("eq", "5", "5\n6") == Verdict(2, Detail.STDOUT_NOT_NUMERIC)
    assert V("eq", "5", "5\r\n6") == Verdict(2, Detail.STDOUT_NOT_NUMERIC)


# CHK-M8-073: REQ-205 (1), the SR §1.1 canonical example
def test_sr_1_1_canonical_example() -> None:
    e = "install ok installed"
    assert evaluate("equals", e, "install ok installed", 0, False, False) == 0
    assert evaluate("equals", e, "", 0, False, False) == 1
    assert evaluate("equals", e, "install ok installed\n", 0, False, False) == 0
    assert evaluate("equals", e, "", 1, False, False) == 1
    assert classify("equals", e, "", 1, False, False) == Verdict(1, None)


# CHK-M8-074: REQ-186 (4) purity
@pytest.fixture
def audit_events() -> Iterator[list[str]]:
    events: list[str] = []
    active = [True]
    watched = (
        "open",
        "socket.connect",
        "socket.__new__",
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "shutil.",
        "os.remove",
        "os.rename",
    )

    def hook(event: str, _args: tuple[Any, ...]) -> None:
        if active[0] and event.startswith(watched):
            events.append(event)

    sys.addaudithook(hook)
    yield events
    active[0] = False  # audit hooks cannot be removed


def _all_paths() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for op in OPERATORS:
        rows.append((op, *PASS_INPUT[op], 0, False, False))
        rows.append((op, *FAIL_INPUT[op], 0, False, False))
        rows.append((op, *PASS_INPUT[op], 0, True, False))
        rows.append((op, *PASS_INPUT[op], 0, False, True))
        for code in (None, 126, 127, 128, -1):
            rows.append((op, *PASS_INPUT[op], code, False, False))
    rows += [
        ("eq", "0", "abc", 0, False, False),
        ("eq", "abc", "0", 0, False, False),
        ("regex", "[", "x", 0, False, False),
        ("regex", "a", "\ud800", 0, False, False),
        ("BOGUS", "x", "x", 0, False, False),
    ]
    return rows


def test_pure_no_log_no_output_no_io(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    audit_events: list[str],
) -> None:
    rows = _all_paths()
    assert len(rows) >= 200 // 2
    # Warm up imports and the RE2 module outside the watched window.
    first = [classify(*r) for r in rows]
    audit_events.clear()
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        second = [classify(*r) for r in rows]
        codes = [evaluate(*r) for r in rows]
    assert first == second
    assert codes == [v.code for v in second]
    assert caplog.records == []
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""
    assert audit_events == []


# CHK-M8-076: no clock
def test_reads_no_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_clock(*_a: object) -> float:
        raise AssertionError("clock read")

    for name in ("time", "monotonic", "perf_counter", "time_ns", "monotonic_ns"):
        monkeypatch.setattr(time, name, no_clock)
    for r in _all_paths():
        classify(*r)


def test_module_keeps_no_state_between_calls() -> None:
    before = {k: id(v) for k, v in vars(evaluate_module).items()}
    for r in _all_paths():
        classify(*r)
    after = {k: id(v) for k, v in vars(evaluate_module).items()}
    assert before == after


# CHK-M8-075, CHK-M8-363: a detail never carries input
CANARY = "M8CANARY-eval-41c9"


@pytest.mark.parametrize(
    "args",
    [
        ("eq", "0", CANARY, 0, False, False),
        ("eq", CANARY, "0", 0, False, False),
        ("regex", "[" + CANARY, CANARY, 0, False, False),
        ("regex", CANARY, CANARY + "\ud800", 0, False, False),
        (CANARY, CANARY, CANARY, 0, False, False),
        ("equals", CANARY, CANARY, 0, True, False),
        ("equals", CANARY, CANARY, 127, False, False),
        ("equals", CANARY, CANARY, 0, False, True),
        ("equals", CANARY, CANARY, None, False, False),
    ],
)
def test_detail_never_quotes_input(args: tuple[Any, ...]) -> None:
    v = classify(*args)
    assert v.code == 2
    assert isinstance(v.detail, Detail)
    assert CANARY not in str(v.detail)
    assert CANARY not in repr(v)
    assert str(args[3]) not in str(v.detail) or args[3] in (0, None)


# CHK-M8-077: large inputs stay fast
@pytest.mark.parametrize("op", OPERATORS)
def test_one_mib_inputs_are_fast(op: str) -> None:
    big = "a" * (1 << 20)
    expected = "1" if op in ("eq", "ne", "gt", "ge", "lt", "le") else big
    if op in ("regex", "not_regex"):
        expected = "a{1000}$"
    start = time.perf_counter()
    v = classify(op, expected, big, 0, False, False)
    assert time.perf_counter() - start < 2.0
    assert v.code in (0, 1, 2)


def test_many_empty_lines_under_regex() -> None:
    stdout = "\n".join(["x"] * 65_536)
    start = time.perf_counter()
    assert classify("regex", "^$", "x\n\nx", 0, False, False).code == 0
    assert classify("regex", "^y$", stdout, 0, False, False).code == 1
    assert time.perf_counter() - start < 1.0
