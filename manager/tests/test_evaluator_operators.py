"""TP-M8-03: the 14 operators on normalised text (TASK-177; REQ-188 to REQ-191).

`compare(operator, expected, stdout) -> bool` takes text that is already
normalised (REQ-187) and raises only `NotNumeric` (stdout not one #13 number)
or `CannotEvaluate` (the comparison cannot be made). Expected values come from
SR §2.4 (the operator table, L153 numbers), TS §4.5 L595 and L600 (RE2, linear
time), and the approved answers #11, #13, #112. CHK-M8-020 to -051
(tests/m8/test-plan.md).
"""

from __future__ import annotations

import ast
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.evaluator import operators
from bitscan_manager.services.evaluator.operators import (
    CannotEvaluate,
    NotNumeric,
    compare,
)
from bitscan_manager.services.importer import model as importer_model
from bitscan_manager.services.importer import values

NUMERIC = ("eq", "ne", "gt", "ge", "lt", "le")
SSHD = (
    "Port 22\n"
    "#PermitRootLogin yes\n"
    "PermitRootLogin no\n"
    "PasswordAuthentication no\n"
    "MaxAuthTries 4"
)


# CHK-M8-020
def test_dispatch_is_exactly_the_14() -> None:
    assert tuple(operators.COMPARISONS) == importer_model.OPERATORS
    assert len(operators.COMPARISONS) == 14
    with pytest.raises(TypeError):
        operators.COMPARISONS["bogus"] = lambda e, s: True  # type: ignore[index]


@pytest.mark.parametrize("op", importer_model.OPERATORS)
def test_each_operator_returns_a_bool(op: str) -> None:
    presence = op in ("empty", "not_empty")
    expected = "1" if op in NUMERIC else ("" if presence else "x")
    stdout = "1" if op in NUMERIC else "x"
    assert compare(op, expected, stdout) in (True, False)
    assert type(compare(op, expected, stdout)) is bool


@pytest.mark.parametrize(
    "op",
    [
        "EQUALS",
        "Equals",
        "equal",
        "",
        " equals",
        "equals ",
        "equals\x00",
        "regexp",
        "!=",
        "==",
        "eq ",
        "EQ",
        "NOT_REGEX",
        "not-regex",
        "notregex",
        "ne\n",
        "еquals",  # Cyrillic e
        "empty​",
    ],
)
def test_unknown_operator_cannot_evaluate(op: str) -> None:
    for expected, stdout in (("x", "x"), ("1", "1"), ("", "")):
        with pytest.raises(CannotEvaluate):
            compare(op, expected, stdout)


# CHK-M8-021 to -024: REQ-188 text operators
TEXT_ROWS: list[tuple[str, str, str, bool]] = [
    # equals
    ("equals", "install ok installed", "install ok installed", True),
    ("equals", "install ok installed", "deinstall ok config-files", False),
    ("equals", "a\nb", "a\nb", True),
    ("equals", "install ok installed", "Install ok installed", False),
    ("equals", "Ünïcødé ✓", "Ünïcødé ✓", True),
    ("equals", "abc", "abcd", False),
    ("equals", "abcd", "abc", False),
    ("equals", "a\nb", "a\nb\nc", False),
    ("equals", "", "", True),
    ("equals", "x", "", False),
    # not_equals
    ("not_equals", "disabled", "enabled", True),
    ("not_equals", "disabled", "disabled", False),
    ("not_equals", "disabled", "Disabled", True),
    ("not_equals", "a\nb", "a\nb", False),
    ("not_equals", "a\nb", "a\nc", True),
    ("not_equals", "ä", "a", True),
    ("not_equals", "", "x", True),
    # contains
    ("contains", "PermitRootLogin no", SSHD, True),
    ("contains", "permitrootlogin no", SSHD, False),
    ("contains", "Port 22", SSHD, True),  # at the start
    ("contains", "MaxAuthTries 4", SSHD, True),  # at the end
    ("contains", "PermitRootLogin maybe", SSHD, False),
    ("contains", "ö", "Größe ö", True),
    ("contains", "ö", "ö", False),  # no Unicode normalisation
    ("contains", "", "anything", True),
    ("contains", "x", "", False),
    # not_contains
    ("not_contains", "nullok", "auth required pam_unix.so nullok_secure", False),
    ("not_contains", "nullok", "auth required pam_unix.so", True),
    ("not_contains", "NULLOK", "auth required pam_unix.so nullok", True),
    ("not_contains", "nullok", "nullok", False),
    ("not_contains", "é", "cafe", True),
    ("not_contains", "é", "café", False),
    ("not_contains", "x", "", True),
]


@pytest.mark.parametrize(("op", "expected", "stdout", "result"), TEXT_ROWS)
def test_text_operators(op: str, expected: str, stdout: str, result: bool) -> None:
    assert compare(op, expected, stdout) is result


def test_text_pairs_are_exact_negations() -> None:
    for _, expected, stdout, _ in TEXT_ROWS:
        assert compare("equals", expected, stdout) is not compare(
            "not_equals", expected, stdout
        )
        assert compare("contains", expected, stdout) is not compare(
            "not_contains", expected, stdout
        )


# CHK-M8-030 to -037: REQ-189 RE2 operators
PEP = r"^\s*PermitEmptyPasswords\s+yes"  # SR §2.4 example
REGEX_ROWS: list[tuple[str, str, str, bool]] = [
    ("regex", r"^MaxAuthTries\s+[1-4]$", "Port 22\nMaxAuthTries 3\nX", True),
    ("regex", r"^MaxAuthTries\s+[1-4]$", "MaxAuthTries 6", False),
    ("not_regex", PEP, "PermitEmptyPasswords no", True),
    ("not_regex", PEP, "PermitEmptyPasswords yes", False),
    ("not_regex", PEP, "a\n  PermitEmptyPasswords yes", False),
    # REQ-189 (2): a search, multiline
    ("regex", "foo", "xfoo", True),
    ("regex", "foo", "xfoox", True),
    ("regex", "^foo$", "a\nfoo\nb", True),
    ("regex", "^foo", "xfoo", False),
    ("regex", "foo$", "foox", False),
    ("regex", "^b$", "a\nb", True),
    ("regex", "^a$", "a\nb", True),
    ("not_regex", "^foo$", "a\nfoo\nb", False),
    # \A and \z keep their whole-text meaning under (?m)
    ("regex", r"\Afoo\z", "foo", True),
    ("regex", r"\Afoo\z", "a\nfoo", False),
    # REQ-189 (3): `.` does not match a newline
    ("regex", "^a.b$", "a\nb", False),
    ("regex", "a.b", "a\nb", False),
    ("regex", "a.b", "axb", True),
    # case-sensitive by default, and (?i) is the author's choice
    ("regex", "^permitrootlogin", "PermitRootLogin no", False),
    ("regex", "(?i)^permitrootlogin", "PermitRootLogin no", True),
    # non-ASCII
    ("regex", "^Gr..e$", "Größe", True),
    ("regex", "^.$", "😀", True),
    ("not_regex", "x", "", True),
    ("regex", "^$", "", True),
    ("regex", "", "anything", True),
]


@pytest.mark.parametrize(("op", "pattern", "stdout", "result"), REGEX_ROWS)
def test_regex_operators(op: str, pattern: str, stdout: str, result: bool) -> None:
    assert compare(op, pattern, stdout) is result


def test_regex_pair_is_an_exact_negation() -> None:
    for _, pattern, stdout, _ in REGEX_ROWS:
        assert compare("regex", pattern, stdout) is not compare(
            "not_regex", pattern, stdout
        )


# REQ-189 (4): patterns RE2 refuses (and import would refuse) are never
# PASS or FAIL, for either operator: the false-PASS hunt for not_regex.
REFUSED_PATTERNS = [
    "(?=x)",
    "(?!x)",
    "(?<=x)",
    "(?<!x)",
    r"(a)\1",
    "[",
    "(",
    ")",
    "a{2,1}",
    "*",
    "x**",
    r"\p{NoSuchClass}",
    "(?P<n>a)(?P=n)",
    "a{1001}",
]


@pytest.mark.parametrize("pattern", REFUSED_PATTERNS)
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_refused_pattern_cannot_evaluate(op: str, pattern: str) -> None:
    for stdout in ("x", "", "a", "aa\nx"):
        with pytest.raises(CannotEvaluate):
            compare(op, pattern, stdout)


def test_refused_patterns_are_refused_by_the_shared_helper() -> None:
    # The rows above are only meaningful if values.compile_pattern refuses them.
    for pattern in REFUSED_PATTERNS:
        with pytest.raises(values.PatternError):
            values.compile_pattern(pattern)


# CHK-M8-034: a lone surrogate RE2 cannot encode
@pytest.mark.parametrize("op", ["regex", "not_regex"])
@pytest.mark.parametrize("stdout", ["\ud800", "a\udfffb", "x\ud83d"])
def test_lone_surrogate_stdout_cannot_evaluate(op: str, stdout: str) -> None:
    with pytest.raises(CannotEvaluate):
        compare(op, "a", stdout)
    with pytest.raises(CannotEvaluate):
        compare(op, "^$", stdout)


@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_lone_surrogate_pattern_cannot_evaluate(op: str) -> None:
    with pytest.raises(CannotEvaluate):
        compare(op, "\ud800", "x")


# CHK-M8-035: REQ-189 (5), linear time
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_catastrophic_pattern_runs_in_linear_time(op: str) -> None:
    stdout = "a" * 65_536
    start = time.perf_counter()
    result = compare(op, "(a*)*b", stdout)
    elapsed = time.perf_counter() - start
    assert result is (op == "not_regex")
    assert elapsed < 1.0, elapsed


def test_many_lines_anchor() -> None:
    stdout = "\n".join(["x"] * 65_536)
    start = time.perf_counter()
    assert compare("regex", "^y$", stdout) is False
    assert compare("not_regex", "^y$", stdout) is True
    assert time.perf_counter() - start < 1.0


# CHK-M8-036: REQ-189 (6), compile_pattern is the one compile call
def test_compile_pattern_is_the_only_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = values.compile_pattern

    def spy(pattern: str) -> Any:
        calls.append(pattern)
        return real(pattern)

    monkeypatch.setattr(values, "compile_pattern", spy)
    assert compare("regex", "^a$", "a") is True
    assert compare("not_regex", "^b$", "a") is True
    with pytest.raises(CannotEvaluate):
        compare("regex", "[", "a")
    assert calls == ["^a$", "^b$", "["]

    import re2  # type: ignore[import-untyped]

    def no_direct_compile(*_a: object, **_k: object) -> Any:
        raise AssertionError("re2.compile called directly")

    monkeypatch.setattr(values, "compile_pattern", real)
    monkeypatch.setattr(re2, "compile", no_direct_compile)
    # With re2.compile poisoned, compare goes only through values (which then
    # fails): it must surface as CannotEvaluate or AssertionError from values,
    # never succeed through a private compile.
    try:
        compare("regex", "^z$", "z")
    except (CannotEvaluate, AssertionError):
        pass
    else:
        pytest.fail("compare matched without re2.compile: a second compile path")


OPERATORS_PY = Path(operators.__file__)


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def test_operators_imports_no_re_or_re2() -> None:
    names = _imported_names(OPERATORS_PY)
    for bad in ("re", "re2", "regex", "logging", "psycopg"):
        assert bad not in names, bad
    forbidden = (
        "bitscan_manager.db",
        "bitscan_manager.repositories",
        "bitscan_manager.api",
    )
    assert not any(n.startswith(forbidden) for n in names)


# CHK-M8-040 to -044: REQ-190 numeric operators
NUMERIC_ROWS: list[tuple[str, str, str, bool]] = [
    # REQ-190 (1)
    ("eq", "0", "0", True),
    ("eq", "0", "-0", True),
    ("eq", "1", "1.0", True),
    ("gt", "13", "14", True),
    ("ge", "14", "14", True),
    ("lt", "91", "90.999", True),
    ("eq", "7", "007", True),
    ("le", "90", "90.0001", False),
    ("ne", "0", "+0", False),
    # boundaries for each operator
    ("gt", "14", "14", False),
    ("gt", "14", "13.9999", False),
    ("ge", "14", "13.9999", False),
    ("lt", "14", "14", False),
    ("le", "14", "14", True),
    ("le", "14", "14.0", True),
    ("ne", "1", "2", True),
    ("ne", "1", "1.000", False),
    ("lt", "-1", "-2", True),
    ("gt", "-1", "-0.5", True),
    ("eq", "-0.0", "0", True),
    ("eq", "+5", "5", True),
    ("eq", "0.1", "0.10", True),
    ("eq", "0.3", "0.30000000000000004", False),
    ("gt", "0.3", "0.30000000000000004", True),
    # REQ-190 (2): no float rounding
    ("eq", "9007199254740992", "9007199254740993", False),
    ("gt", "9007199254740992", "9007199254740993", True),
    ("ne", "9007199254740992", "9007199254740993", True),
    ("lt", "9007199254740993", "9007199254740992", True),
]


@pytest.mark.parametrize(("op", "expected", "stdout", "result"), NUMERIC_ROWS)
def test_numeric_operators(op: str, expected: str, stdout: str, result: bool) -> None:
    assert compare(op, expected, stdout) is result


def test_numeric_matches_a_decimal_oracle_on_the_table() -> None:
    import operator as o

    ops: dict[str, Callable[[Decimal, Decimal], bool]] = {
        "eq": o.eq,
        "ne": o.ne,
        "gt": o.gt,
        "ge": o.ge,
        "lt": o.lt,
        "le": o.le,
    }
    for _, expected, stdout, _ in NUMERIC_ROWS:
        for op, fn in ops.items():
            oracle = fn(Decimal(stdout), Decimal(expected))
            assert compare(op, expected, stdout) is oracle


def test_five_thousand_digit_numbers() -> None:
    big = "9" * 5_000
    bigger = "9" * 4_999 + "8"  # one less in the last digit
    assert compare("eq", big, big) is True
    assert compare("eq", big, bigger) is False
    assert compare("ne", big, bigger) is True
    assert compare("lt", big, bigger) is True
    assert compare("le", big, bigger) is True
    assert compare("gt", big, bigger) is False
    assert compare("ge", big, big) is True
    frac = "0." + "0" * 4_998 + "1"
    assert compare("gt", "0", frac) is True
    assert compare("eq", "0", frac) is False


NOT_NUMBERS = [
    "abc",
    "",
    "1e3",
    "1E3",
    "1e-3",
    "nan",
    "NaN",
    "inf",
    "-inf",
    "Infinity",
    "1_000",
    "0x10",
    "0b1",
    ".5",
    "5.",
    "5 6",
    "5\n6",
    "٣",  # Arabic-Indic three
    "１",  # full-width one
    "+",
    "-",
    "--1",
    "+-1",
    "1-",
    "1,000",
    "1.2.3",
    "12abc",
    " 1",  # normalise is the caller's job: compare gets normalised text
    "1 ",
    " 1",
]


@pytest.mark.parametrize("stdout", NOT_NUMBERS)
@pytest.mark.parametrize("op", NUMERIC)
def test_non_numeric_stdout_is_not_numeric(op: str, stdout: str) -> None:
    with pytest.raises(NotNumeric):
        compare(op, "0", stdout)


@pytest.mark.parametrize("expected", ["abc", "", "1e3", "nan", "inf", ".5", " 1"])
@pytest.mark.parametrize("op", NUMERIC)
def test_non_numeric_expected_cannot_evaluate(op: str, expected: str) -> None:
    with pytest.raises(CannotEvaluate):
        compare(op, expected, "1")
    # expected is checked first: both bad is CannotEvaluate, not NotNumeric
    with pytest.raises(CannotEvaluate):
        compare(op, expected, "abc")


def test_numeric_never_uses_int_or_float(monkeypatch: pytest.MonkeyPatch) -> None:
    src = OPERATORS_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("float", "int", "eval"), node.func.id


# CHK-M8-050: REQ-191 presence operators (on normalised text)
@pytest.mark.parametrize(
    ("stdout", "is_empty"),
    [
        ("", True),
        ("0", False),
        ("x", False),
        (" ", False),  # #115: a no-break space is content
        ("\n", False),  # not normalised here: normalise() runs first in classify
        ("false", False),
    ],
)
def test_presence(stdout: str, is_empty: bool) -> None:
    assert compare("empty", "", stdout) is is_empty
    assert compare("not_empty", "", stdout) is (not is_empty)
    # REQ-191 (3): a non-empty expected value does not change the result
    assert compare("empty", "something", stdout) is is_empty
    assert compare("not_empty", "1", stdout) is (not is_empty)


# CHK-M8-051: compare raises only its two signals
TEXT = st.text(alphabet=st.characters(codec=None), max_size=30)
OPS = st.one_of(
    st.sampled_from(importer_model.OPERATORS),
    st.sampled_from(["EQUALS", "", "equal", "Regex"]),
    TEXT,
)


@settings(max_examples=5_000, deadline=None)
@given(OPS, TEXT, TEXT)
def test_compare_raises_only_its_signals(op: str, expected: str, stdout: str) -> None:
    try:
        result = compare(op, expected, stdout)
    except (NotNumeric, CannotEvaluate):
        return
    assert type(result) is bool
    assert op in importer_model.OPERATORS


def test_signals_are_distinct_exceptions() -> None:
    assert issubclass(NotNumeric, Exception)
    assert issubclass(CannotEvaluate, Exception)
    assert not issubclass(NotNumeric, CannotEvaluate)
    assert not issubclass(CannotEvaluate, NotNumeric)


def test_signals_carry_no_input() -> None:
    canary = "M8CANARY-ops-7f3a"
    for op, expected, stdout in (
        ("eq", "1", canary),
        ("eq", canary, "1"),
        ("regex", "[" + canary, "x"),
        ("regex", "a", canary + "\ud800"),
        (canary, "x", "x"),
    ):
        with pytest.raises((NotNumeric, CannotEvaluate)) as info:
            compare(op, expected, stdout)
        assert canary not in str(info.value)
        assert canary not in repr(info.value)
        assert not any(canary in str(a) for a in info.value.args)
