"""CSV writing with formula escaping (TS §6.3 L1142; #84 (c), (d)).

The one escaping function for every export (package search now, results CSV
later): a cell that a spreadsheet could run as a formula is prefixed with
'. The prefix is added first, then RFC 4180 quoting; header cells too. Lines
end with CRLF; encoding the text (UTF-8, no BOM) is the caller's job.
"""

from collections.abc import Iterable, Sequence
from typing import Final

_TRIGGERS: Final = frozenset("=+-@")
_ALWAYS: Final = frozenset("\t\r")
_NEEDS_QUOTES: Final = frozenset(',"\r\n')


def escape_cell(cell: str) -> str:
    """' before a cell that starts with a trigger (=, +, -, @, tab, CR), or
    with any run of leading whitespace (str.isspace, #84 (d)) followed by
    one, " \\tabc" included (TS §6.3 L1142, lead ruling); others unchanged.
    Tab and CR are whitespace themselves, so they are found in the run."""
    rest = cell.lstrip()
    lead = cell[: len(cell) - len(rest)]
    if rest[:1] in _TRIGGERS or any(c in _ALWAYS for c in lead):
        return "'" + cell
    return cell


def _quote(cell: str) -> str:
    """RFC 4180: a cell holding a comma, a double quote, CR or LF is quoted,
    with each double quote doubled."""
    if any(c in _NEEDS_QUOTES for c in cell):
        return '"' + cell.replace('"', '""') + '"'
    return cell


def csv_line(cells: Sequence[str]) -> str:
    """One record: every cell escaped, then quoted; CRLF at the end."""
    return ",".join(_quote(escape_cell(c)) for c in cells) + "\r\n"


def write_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """The header record, then one record per row."""
    return csv_line(header) + "".join(csv_line(r) for r in rows)
