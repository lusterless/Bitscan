"""TP-M7-04: value helpers shared with M8 (TASK-142; REQ-152, REQ-153, REQ-154).

Expected values come from SR §2.3, §2.4 (numbers; regex "multiline"), §3.3
(``control_ref``, 32), TS §4.5 (RE2) and the approved answers #13 (number
grammar), #17 (XML-whitespace trimming) and #109 (UUID form). CHK-M7-040 to
-045; plant CHK-M7-325 (tests/m7/test-plan.md). Owner: tester-m7b.

Contract (TASK-142 report, consistent with #17 and SR §2.4): the checks take
already-trimmed text; the importer calls them on ``trim_xml(value)``.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest
import re2  # type: ignore[import-untyped]
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.importer import values
from bitscan_manager.services.importer.model import Code
from bitscan_manager.services.importer.values import (
    ControlRef,
    PatternError,
    compile_pattern,
    control_ref,
    is_number,
    is_plugin_uuid,
    is_valid_pattern,
    parse_number,
    trim_xml,
)

VALUES_PY = Path(values.__file__)

# Independent oracles, written from the approved grammars (RE2, never `re`).
NUMBER_RX = re2.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
UUID_RX = re2.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
REF_RX = re2.compile(r"[0-9]+(?:\.[0-9]+)*")


# CHK-M7-040: the #13 number grammar -----------------------------------------

NUMBERS_OK = ["0", "-1", "+2.5", "14", "007", "-0", "-0.0", "+0", "3.14159",
              "123456789012345678901234567890.000000000000000000001"]  # fmt: skip
NUMBERS_BAD = [
    "abc", "1e3", "1E3", "1e-3", "nan", "NaN", "inf", "-inf", "Infinity",
    "1_000", "0x10", "0b1", "0o7", ".5", "5.", "+", "-", "", "1.2.3", "--1",
    "+-1", "-+1", "1-", "1+", "١", "١٢", "１", "²", "1 000", "1,5", "1.5.",
    " 14", "14 ", "\t1", "1\n", " 1", "1 ", "0.", ".", "+.5", "-.5",
    "1..2", "∞",
]  # fmt: skip


@pytest.mark.parametrize("text", NUMBERS_OK)
def test_numbers_accepted(text: str) -> None:
    assert is_number(text) is True
    assert parse_number(text) == Decimal(text)


@pytest.mark.parametrize("text", NUMBERS_BAD)
def test_non_numbers_refused(text: str) -> None:
    assert is_number(text) is False
    assert parse_number(text) is None


def test_padded_number_accepted_after_trim() -> None:
    # CHK-M7-040 " 14 " (trimmed): the importer trims first (#17).
    assert is_number(trim_xml(" 14 ")) is True
    assert is_number(trim_xml("\r\n\t-2.5 \n")) is True
    assert is_number(trim_xml(" 14")) is False  # U+00A0 is not trimmed


def test_numbers_compare_as_exact_decimals() -> None:
    # #13: "compare as exact decimals" (no binary float rounding).
    big = parse_number("9007199254740993")
    assert big is not None and big > Decimal(9007199254740992)
    assert parse_number("0.1") == Decimal("0.10")
    tiny, zero = parse_number("0.0000000000000000000001"), parse_number("0")
    assert tiny is not None and zero is not None and tiny > zero
    assert parse_number("-0") == parse_number("0")
    assert isinstance(parse_number("1"), Decimal)


@settings(max_examples=2_000, deadline=None)
@given(st.text(alphabet="0123456789+-.eE_x \t١１a", max_size=12))
def test_number_grammar_matches_the_oracle(text: str) -> None:
    assert is_number(text) is (NUMBER_RX.fullmatch(text) is not None)


# CHK-M7-041: RE2, the evaluator's form, nothing on stderr --------------------

PATTERNS_OK = [
    r"^MaxAuthTries\s+[1-4]$",
    r"^\s*PermitEmptyPasswords\s+yes",
    r"install ok installed",
    r"(?i)permitrootlogin\s+no",
    r"(?P<n>a)b",
    r"(a+)+$",  # catastrophic for backtracking engines, linear in RE2
    r"\bnullok\b",
    r"[[:digit:]]+",
    "é+",
]
PATTERNS_BAD = [
    r"(?=x)", r"(?!x)", r"(?<=a)b", r"(?<!a)b", r"(a)\1", r"[", r"(", r")",
    r"a{2,1}", r"*", r"\8", r"(?P<n>a)(?P=n)", r"a++", r"\Z(", "\ud800",
]  # fmt: skip


@pytest.mark.parametrize("pattern", PATTERNS_OK)
def test_re2_patterns_compile(pattern: str) -> None:
    assert is_valid_pattern(pattern) is True
    compile_pattern(pattern)


@pytest.mark.parametrize("pattern", PATTERNS_BAD)
def test_non_re2_patterns_refused(pattern: str) -> None:
    # Red for CHK-M7-325 (Python `re` accepts (?=x), (a)\1, (?<!a)b).
    assert is_valid_pattern(pattern) is False
    with pytest.raises(PatternError) as info:
        compile_pattern(pattern)
    assert str(info.value) == "not a valid RE2 pattern"
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_python_re_would_accept_what_re2_refuses() -> None:
    # Guard on the oracle: these differ between the engines, so the plant
    # CHK-M7-325 (Python `re`) is detectable.
    probe = "import re; [re.compile(p) for p in ('(?=x)', '(a)\\\\1', '(?<!a)b')]"
    argv = [sys.executable, "-I", "-c", probe]
    proc = subprocess.run(argv, check=False)  # noqa: S603  # fixed argv
    assert proc.returncode == 0


def test_compiled_pattern_is_multiline() -> None:
    # SR §2.4: regex is "multiline; use ^/$ to anchor".
    rx = compile_pattern(r"^MaxAuthTries\s+[1-4]$")
    assert rx.search("Port 22\nMaxAuthTries 3\nX 1") is not None
    assert rx.search("Port 22\nMaxAuthTries 5\n") is None
    assert compile_pattern(r"^b").search("a\nb") is not None
    assert compile_pattern("a.b").search("a\nb") is None  # `.` is not newline


def test_compiled_pattern_is_case_sensitive_and_unicode() -> None:
    # SR §2.4: "Comparison is case-sensitive"; text is UTF-8.
    assert compile_pattern("yes").search("YES") is None
    assert compile_pattern("é+").search("caféé") is not None


def test_4000_char_pattern_checked_within_1_s() -> None:
    # REQ-153 (5). Distinct patterns, so no LRU cache hit (TASK-142 note).
    for i, unit in enumerate(["(a|b)*c", "[a-z]{3}", "x?y+", "a{1000}"]):
        pattern = f"p{i}" + unit * (4_000 // len(unit))
        pattern = pattern[:4_000]
        start = time.perf_counter()
        is_valid_pattern(pattern)
        assert time.perf_counter() - start < 1.0, unit


def test_pathological_pattern_compiles_or_refuses_within_1_s() -> None:
    start = time.perf_counter()
    is_valid_pattern("((a{1000}){1000}){1000}")
    is_valid_pattern("(" * 1_000 + "a" + ")" * 1_000)
    assert time.perf_counter() - start < 1.0


def test_refused_patterns_write_nothing_to_stderr_or_logs(
    capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for i, pattern in enumerate(PATTERNS_BAD + ["a{2,1}x" * (i + 1) for i in range(3)]):
        is_valid_pattern(pattern + f"(?:{i})" if pattern != "\ud800" else pattern)
    out, err = capfd.readouterr()
    assert (out, err) == ("", "")
    assert caplog.records == []


def test_refused_patterns_write_nothing_to_fd2_in_a_fresh_process() -> None:
    # RE2 logs from C++ to fd 2; a fresh process sees the first compile.
    code = (
        "from bitscan_manager.services.importer.values import is_valid_pattern\n"
        "for p in ['(?=x)', '(a)\\\\1', '[', '(?<!a)b', 'a{2,1}']:\n"
        "    assert not is_valid_pattern(p)\n"
    )
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, check=False, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == b"" and proc.stdout == b""


def test_stock_re2_does_log_to_stderr() -> None:
    # Guard on the oracle: without log_errors=False RE2 writes to fd 2, so the
    # two tests above can fail.
    code = "import re2\ntry:\n    re2.compile('(?=x)')\nexcept re2.error:\n    pass\n"
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, check=False, timeout=60
    )
    assert proc.stderr != b""


# CHK-M7-042: the #109 PluginId form -----------------------------------------

UUIDS_OK = [
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",  # SR §1.1
    "00000000-0000-0000-0000-000000000000",  # nil
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "3f6c2a9e-8b1d-0e57-0a3c-2d7f0e6b1c48",  # version 0, variant 0: not checked
    "3f6c2a9e-8b1d-fe57-fa3c-2d7f0e6b1c48",
]
UUIDS_BAD = [
    "3F6C2A9E-8B1D-4E57-9A3C-2D7F0E6B1C48",
    "3f6c2a9e-8b1d-4E57-9a3c-2d7f0e6b1c48",
    "{3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48}",
    "urn:uuid:3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",
    "3f6c2a9e8b1d4e579a3c2d7f0e6b1c48",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c489",
    "3f6c2a9e8-b1d-4e57-9a3c-2d7f0e6b1c48",
    "3f6c2a9e-8b1d-4e57-9a3c2-d7f0e6b1c48",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4g",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4١",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c4０",
    "3f6c2a9e_8b1d_4e57_9a3c_2d7f0e6b1c48",
    " 3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",
    "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48\n",
    "------------------------------------",
    "",
]


@pytest.mark.parametrize("text", UUIDS_OK)
def test_uuid_forms_accepted(text: str) -> None:
    assert is_plugin_uuid(text) is True


@pytest.mark.parametrize("text", UUIDS_BAD)
def test_uuid_forms_refused(text: str) -> None:
    assert is_plugin_uuid(text) is False


@settings(max_examples=2_000, deadline=None)
@given(
    st.one_of(
        st.uuids().map(str),
        st.uuids().map(lambda u: str(u).upper()),
        st.text(alphabet="0123456789abcdefABG-", min_size=30, max_size=40),
    )
)
def test_uuid_check_matches_the_oracle(text: str) -> None:
    assert is_plugin_uuid(text) is (UUID_RX.fullmatch(text) is not None)


# CHK-M7-043: trimming (#17) -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "trimmed"),
    [
        (" \t\r\n x  \n", "x"),
        ("\n\n  a b  \t", "a b"),
        ("a\n\tb", "a\n\tb"),
        (" x ", " x "),
        (" x ", " x "),
        ("﻿x﻿", "﻿x﻿"),
        ("\x0bx\x0c", "\x0bx\x0c"),
        ("\x85x ", "\x85x "),
        ("   ", " "),
        (" \t\r\n", ""),
        ("", ""),
    ],
)
def test_trim_removes_only_xml_whitespace(raw: str, trimmed: str) -> None:
    assert trim_xml(raw) == trimmed


def test_trim_constant() -> None:
    assert values.XML_WHITESPACE == " \t\r\n"


# CHK-M7-044: control_ref (SR §3.3, REQ-154 (1)) -----------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("1.3.1.1 - Ensure AppArmor is installed", ControlRef("1.3.1.1", None)),
        ("Ensure AppArmor is installed", ControlRef(None, Code.BIT101)),
        ("1.3.1.1Ensure", ControlRef("1.3.1.1", None)),
        ("1.3. - x", ControlRef("1.3", None)),
        ("1..2 x", ControlRef("1", None)),
        ("1", ControlRef("1", None)),
        ("007.01 x", ControlRef("007.01", None)),
        ("5 - x", ControlRef("5", None)),
        (".1 x", ControlRef(None, Code.BIT101)),
        ("- 1.2", ControlRef(None, Code.BIT101)),
        ("١.٣ x", ControlRef(None, Code.BIT101)),  # Arabic-Indic
        ("１.２ x", ControlRef(None, Code.BIT101)),  # fullwidth
        ("²", ControlRef(None, Code.BIT101)),
        ("1١", ControlRef("1", None)),
        ("", ControlRef(None, Code.BIT101)),
    ],
)
def test_control_ref_cases(name: str, expected: ControlRef) -> None:
    assert control_ref(name) == expected


def test_control_ref_32_kept_33_is_bit103() -> None:
    ref32 = "1." * 15 + "12"  # 32 characters
    assert len(ref32) == 32
    assert control_ref(ref32 + " - x") == ControlRef(ref32, None)
    ref33 = ref32 + "3"
    assert control_ref(ref33 + " - x") == ControlRef(None, Code.BIT103)
    assert control_ref("1" * 32) == ControlRef("1" * 32, None)
    assert control_ref("1" * 33) == ControlRef(None, Code.BIT103)
    # The dot that ends a reference is not part of it.
    assert control_ref(ref32 + ".") == ControlRef(ref32, None)


def test_control_ref_warning_never_carries_a_value() -> None:
    for name in ("x", "1" * 40, "١"):
        ref = control_ref(name)
        assert ref.value is None and ref.warning in (Code.BIT101, Code.BIT103)


def test_control_ref_is_frozen() -> None:
    ref = control_ref("1 x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.value = "2"  # type: ignore[misc]


@settings(max_examples=3_000, deadline=None)
@given(st.text(alphabet="0123456789.- x١", max_size=48))
def test_control_ref_matches_the_oracle(name: str) -> None:
    m = REF_RX.match(name)
    ref = control_ref(name)
    if m is None:
        assert ref == ControlRef(None, Code.BIT101)
    elif len(m.group(0)) > 32:
        assert ref == ControlRef(None, Code.BIT103)
    else:
        assert ref == ControlRef(m.group(0), None)


# CHK-M7-045: module shape -----------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_values_module_imports_no_re_and_no_io() -> None:
    names = _imports(VALUES_PY)
    assert "re2" in names
    banned = {"re", "regex", "logging", "os", "io", "subprocess", "socket",
              "pathlib", "time", "datetime", "sys", "xml", "lxml"}  # fmt: skip
    assert not (names & banned), names & banned


def test_values_exports_the_helpers_m8_imports() -> None:
    names = ("is_number", "parse_number", "compile_pattern", "is_valid_pattern",
             "PatternError", "trim_xml", "is_plugin_uuid", "control_ref")  # fmt: skip
    for name in names:
        assert callable(getattr(values, name)), name
