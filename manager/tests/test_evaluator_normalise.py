"""TP-M8-02: the normaliser (TASK-176; REQ-187).

TS §4.5 L597 and SR §2.4: CRLF becomes LF, then leading and trailing
whitespace is trimmed; comparison is case-sensitive. #115: the whitespace is
the C-locale ASCII set (space, tab, LF, VT, FF, CR); a lone interior CR, Unicode
spaces, case and Unicode forms are kept. CRLF inputs are in-code literals
(.claude/rules/testing.md), never read from fixture files.
CHK-M8-010 to -013 (tests/m8/test-plan.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.evaluator.normalise import WHITESPACE, normalise

ASCII_WS = " \t\n\v\f\r"
# Characters Python's str.strip() or str.isspace() treat as whitespace that
# #115 keeps as content.
UNICODE_SPACES = (
    "\x1c",
    "\x1d",
    "\x1e",
    "\x1f",
    "\x85",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    " ",
    "　",
    "﻿",
)


def test_whitespace_constant_is_the_115_set() -> None:
    assert set(WHITESPACE) == set(ASCII_WS)
    assert len(WHITESPACE) == 6


# CHK-M8-010: REQ-187 (1)
def test_req187_install_ok_installed_forms_agree() -> None:
    a = normalise("install ok installed\r\n")
    b = normalise("\r\n  install ok installed \n")
    c = normalise("install ok installed")
    assert a == b == c == "install ok installed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\rb"),
        ("\v\fx\t", "x"),
        ("", ""),
        (" ", ""),
        ("\r", ""),
        ("\n", ""),
        ("\r\n", ""),
        ("\r\r\n", ""),
        (" \r\n\t", ""),
        ("x\r", "x"),
        ("\rx", "x"),
        ("a\r\r\nb", "a\r\nb"),
        ("a\r\n\r\nb", "a\n\nb"),
        ("a\n\rb", "a\n\rb"),
        ("a  b\t\tc", "a  b\t\tc"),
        ("  a \n b  ", "a \n b"),
        ("ABC", "ABC"),
        ("Install OK", "Install OK"),
        ("line1\r\nline2\r\nline3\r\n", "line1\nline2\nline3"),
        ("\x00x\x00", "\x00x\x00"),
        ("\ud800", "\ud800"),
        (" \ud800 ", "\ud800"),
    ],
)
def test_normalise_table(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize("space", UNICODE_SPACES)
def test_unicode_spaces_are_kept_at_both_edges(space: str) -> None:
    assert normalise(space + "x") == space + "x"
    assert normalise("x" + space) == "x" + space
    assert normalise(space) == space
    # Kept even when ASCII whitespace surrounds it.
    assert normalise(" \t" + space + "x" + space + "\r\n") == space + "x" + space


def test_req187_named_unicode_rows() -> None:
    # REQ-187 (1): " x" and "x " with U+00A0 and U+2003 are unchanged.
    assert normalise(" x") == " x"
    assert normalise("x ") == "x "
    assert normalise(" x") == " x"
    assert normalise("x ") == "x "


def test_no_unicode_normalisation_and_no_case_fold() -> None:
    decomposed = "é"
    composed = "é"
    assert normalise(decomposed) == decomposed
    assert normalise(composed) == composed
    assert normalise(decomposed) != normalise(composed)
    assert normalise("ﬁ") == "ﬁ"  # ligature, not NFKC
    assert normalise("Straße") == "Straße"  # no casefold to "strasse"


# CHK-M8-011: this file holds no CR byte; every CR above is an escape.
def test_this_file_has_no_carriage_return_bytes() -> None:
    assert b"\r" not in Path(__file__).read_bytes()


PIECE = st.one_of(
    st.sampled_from(list(ASCII_WS) + list(UNICODE_SPACES) + ["\r\n", "a", "Z"]),
    st.characters(codec=None),
)
TEXT = st.lists(PIECE, max_size=40).map("".join)
# Ruling 2026-10-29 (work/decisions.md, "Normaliser: one-pass CRLF -> LF"):
# the replace is one pass, so a CR right before a CRLF ("\r\r\n") becomes a
# new CRLF; idempotence and "no CRLF survives" are claimed only without it.
TEXT_NO_CR_CRLF = TEXT.filter(lambda s: "\r\r\n" not in s)


# The one-pass rows the ruling makes must-hold.
def test_one_pass_crlf_rows() -> None:
    assert normalise("a\r\r\nb") == "a\r\nb"
    assert normalise("a\r\nb") == "a\nb"
    assert normalise("a\rb") == "a\rb"
    # So the first pass on CR CR LF is not a fixed point (documented, not a bug).
    assert normalise(normalise("a\r\r\nb")) == "a\nb"


# CHK-M8-012: REQ-187 (2), narrowed by the ruling
@settings(max_examples=10_000, deadline=None)
@given(TEXT_NO_CR_CRLF)
def test_normalise_is_idempotent(s: str) -> None:
    once = normalise(s)
    assert normalise(once) == once


# CHK-M8-013: only the #115 set is trimmed, and only at the edges.
@settings(max_examples=3_000, deadline=None)
@given(TEXT_NO_CR_CRLF)
def test_trim_set_and_interior_are_exact(s: str) -> None:
    out = normalise(s)
    lf = s.replace("\r\n", "\n")
    # The result is a contiguous slice of the CRLF-folded text.
    assert out in lf
    start = lf.find(out) if out else 0
    if out:
        head, tail = lf[:start], lf[start + len(out) :]
        # Everything removed is #115 whitespace...
        assert set(head) <= set(ASCII_WS)
        assert set(tail) <= set(ASCII_WS)
        # ...and the kept edges are not.
        assert out[0] not in ASCII_WS
        assert out[-1] not in ASCII_WS
    else:
        assert set(lf) <= set(ASCII_WS)
    # No CRLF survives.
    assert "\r\n" not in out
