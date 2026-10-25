"""TASK-111: CSV writer with formula escaping (TP-M5-04, REQ-116).

Checks CHK-M5-080 to CHK-M5-086 of tests/m5/test-plan.md. Expected values:
TS §6.3 L1142 ("any cell starting with =, +, -, @, a tab, a carriage return
or whitespace followed by one of these is prefixed with '"), testing.md Unit
("CSV formula escaping for every export"), #84 (c) (UTF-8 without BOM, CRLF,
RFC 4180 quoting) and #84 (d) (any run of leading str.isspace() whitespace
followed by =, +, -, @; a tab or CR first is prefixed in any case; the prefix
is added before quoting, header cells too), as tightened by the lead's ruling
on TASK-111 revision 1 (TS §6.3 L1142 read literally): a leading whitespace
run that holds a tab or CR is "whitespace followed by" a trigger, so
" \\tabc", " \\rabc" and "\\n\\tx" are prefixed too.
"""

import csv
import io

import pytest

from bitscan_manager.services.packages.csv_export import (
    csv_line,
    escape_cell,
    write_csv,
)

TRIGGERS = ("=", "+", "-", "@")
# Whitespace kinds str.isspace() accepts (#84 (d)): ASCII, C0 separators,
# NBSP, EM SPACE, IDEOGRAPHIC SPACE, LINE SEPARATOR.
WHITESPACE = (
    " ", "  ", "\t ", " \t", "\n", "\r\n", "\x0b", "\x0c",
    "\x1c", "\x1d", "\x1e", "\x1f", "\x85", " ", " ", "　", " ",
)  # fmt: skip


def oracle_escape(cell: str) -> str:
    """The rule written from TS §6.3 L1142, #84 (d) and the TASK-111 r1
    ruling, independent of the code: the six triggers are =, +, -, @, tab and
    CR; a cell is prefixed when it starts with one, or when a run of leading
    whitespace is followed by one (tab and CR are whitespace themselves, so a
    run holding either one qualifies)."""
    for c in cell:
        if c in TRIGGERS or c in ("\t", "\r"):
            return "'" + cell
        if not c.isspace():
            return cell
    return cell


# ---------------------------------------------------------------- CHK-M5-080


@pytest.mark.parametrize(
    "cell", ["=1", "+1", "-1", "@a", "\t1", "\r1", "=", "-", "@", "\t", "\r"]
)
def test_each_trigger_gets_one_leading_quote(cell: str) -> None:
    assert escape_cell(cell) == "'" + cell


@pytest.mark.parametrize(
    "cell", ["=SUM(A1:A2)", "+cmd|' /C calc'!A0", "-2+3", "@SUM(1)"]
)
def test_formula_payloads_are_prefixed(cell: str) -> None:
    assert escape_cell(cell) == "'" + cell


# ---------------------------------------------------------------- CHK-M5-081


@pytest.mark.parametrize("ws", WHITESPACE)
@pytest.mark.parametrize("trigger", TRIGGERS)
def test_whitespace_then_trigger_gets_one_quote(ws: str, trigger: str) -> None:
    cell = ws + trigger + "1"
    assert ws.isspace()
    assert escape_cell(cell) == "'" + cell


def test_long_whitespace_run_then_trigger() -> None:
    cell = " \t\n " * 50 + "=1"
    assert escape_cell(cell) == "'" + cell


@pytest.mark.parametrize(
    "cell",
    [" \tabc", " \rabc", "\n\tx", "  \t", " \r1", "　\t=", " \t1", "\n\r"],
)
def test_a_leading_whitespace_run_holding_a_tab_or_cr_is_prefixed(cell: str) -> None:
    """TASK-111 r1 ruling: tab and CR count as triggers after whitespace too."""
    assert escape_cell(cell) == "'" + cell


@pytest.mark.parametrize("cell", ["a\tb", "1\r2", "x \t", "abc\t"])
def test_a_tab_or_cr_after_text_is_no_trigger(cell: str) -> None:
    assert escape_cell(cell) == cell


def test_a_quote_is_added_once_only() -> None:
    once = escape_cell("=1")
    assert once == "'=1"
    # The escaped cell starts with ', which is no trigger: no second prefix.
    assert escape_cell(once) == once


# ---------------------------------------------------------------- CHK-M5-082


@pytest.mark.parametrize(
    "cell",
    ["a=b", "1-2", "'=x", "", "plain", "  plain", "x@y", " ", "   ", "\n", "\n1",
     " 1", "openssl", "1:3.0.13-0ubuntu3.5", "0f8fad5b-d9cb-469f-a165-70867728950e",
     "42", "é=1", "_=1", "#=1", "!=1", "​=1"],
)  # fmt: skip
def test_non_trigger_cells_are_unchanged(cell: str) -> None:
    assert escape_cell(cell) == cell


def test_oracle_and_code_agree_on_a_generated_corpus() -> None:
    starts = ["", *WHITESPACE, "a", "1", "'", '"', ",", "​"]
    seconds = ["", *TRIGGERS, "\t", "\r", "a", " ", "\n"]
    for s in starts:
        for t in seconds:
            for rest in ("", "1", ",x", '"q"'):
                cell = s + t + rest
                assert escape_cell(cell) == oracle_escape(cell), repr(cell)
    for first in ("\t", "\r"):
        for rest in ("", "1", "=1", " "):
            assert escape_cell(first + rest) == "'" + first + rest


# ---------------------------------------------------------------- CHK-M5-083


def test_hyperlink_example_is_prefixed_then_quoted() -> None:
    assert csv_line(['=HYPERLINK("http://x")']) == '"\'=HYPERLINK(""http://x"")"\r\n'


@pytest.mark.parametrize(
    ("cell", "field"),
    [
        ("a,b", '"a,b"'),
        ('say "hi"', '"say ""hi"""'),
        ("x\ny", '"x\ny"'),
        ("x\ry", '"x\ry"'),
        ("x\r\ny", '"x\r\ny"'),
        ("-1,2", '"\'-1,2"'),
        ("\r1", '"\'\r1"'),
        ("\n=1", '"\'\n=1"'),
        ('"', '""""'),
        (",", '","'),
        ("plain", "plain"),
        ("", ""),
        ("'=x", "'=x"),
    ],
)
def test_rfc4180_quoting_after_the_prefix(cell: str, field: str) -> None:
    assert csv_line([cell]) == field + "\r\n"


def test_cells_are_joined_with_commas() -> None:
    assert csv_line(["a", "=b", "c,d", ""]) == 'a,\'=b,"c,d",\r\n'


def test_quoting_never_hides_a_trigger_from_the_escape() -> None:
    # A cell that needs quoting and starts with a trigger: the field must
    # start with "' (prefix inside the quotes), never with "= .
    for trigger in TRIGGERS:
        line = csv_line([trigger + 'x,"y"'])
        assert line.startswith("\"'" + trigger), line


# ---------------------------------------------------------------- CHK-M5-084


def test_write_csv_header_then_rows_with_crlf() -> None:
    text = write_csv(("name", "version"), [("openssl", "3.0"), ("=x", "-1")])
    assert text == "name,version\r\nopenssl,3.0\r\n'=x,'-1\r\n"
    assert not text.startswith("﻿")


def test_header_cells_are_escaped_too() -> None:
    assert write_csv(("=h", "+h", "ok"), []) == "'=h,'+h,ok\r\n"


def test_every_record_ends_with_crlf_and_no_bare_lf_between_records() -> None:
    text = write_csv(("a",), [("1",), ("2",), ("3",)])
    assert text.endswith("\r\n")
    assert text.count("\r\n") == 4
    assert "\n" not in text.replace("\r\n", "")


def test_no_rows_is_the_header_only() -> None:
    assert write_csv(("agent_id", "hostname", "package_count"), []) == (
        "agent_id,hostname,package_count\r\n"
    )


def test_non_ascii_text_survives_utf8_encoding() -> None:
    text = write_csv(("name",), [("пакет-ü-日本",)])
    data = text.encode("utf-8")
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.decode("utf-8") == "name\r\nпакет-ü-日本\r\n"


# ---------------------------------------------------------------- CHK-M5-085


CORPUS = [
    "openssl",
    '=HYPERLINK("http://x")',
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "@SUM(1+1)*cmd|' /C calc'!A0",
    "-x",
    "+x",
    "\t1",
    "\r1",
    " =1",
    "a,b",
    'q"uote',
    "multi\nline",
    "crlf\r\nline",
    "é" * 255,
    "",
    "'=already",
]


def test_round_trip_through_a_csv_reader() -> None:
    rows = [(c, str(i)) for i, c in enumerate(CORPUS)]
    text = write_csv(("cell", "i"), rows)
    parsed = list(csv.reader(io.StringIO(text, newline="")))
    assert parsed[0] == ["cell", "i"]
    assert len(parsed) == len(CORPUS) + 1
    for (cell, i), got in zip(rows, parsed[1:], strict=True):
        assert got == [oracle_escape(cell), i]


def test_round_trip_cells_that_were_triggers_start_with_the_quote() -> None:
    # Two columns, so a record with an empty cell is not an empty line.
    text = write_csv(("c", "i"), [(c, "0") for c in CORPUS])
    parsed = list(csv.reader(io.StringIO(text, newline="")))[1:]
    assert len(parsed) == len(CORPUS)
    for got in parsed:
        cell = got[0]
        stripped = cell.lstrip()
        assert not (cell[:1] in ("\t", "\r") or stripped[:1] in TRIGGERS), repr(cell)


# ---------------------------------------------------------------- CHK-M5-086


def test_the_writer_uses_the_shared_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    import bitscan_manager.services.packages.csv_export as mod

    seen: list[str] = []

    def spy(cell: str) -> str:
        seen.append(cell)
        return "X"

    monkeypatch.setattr(mod, "escape_cell", spy)
    assert mod.write_csv(("h",), [("=a",), ("b",)]) == "X\r\nX\r\nX\r\n"
    assert seen == ["h", "=a", "b"]
