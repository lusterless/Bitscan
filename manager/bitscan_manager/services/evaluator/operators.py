"""The 14 SR §2.4 operators on normalised text (TS §4.5; open questions #11,
#13, #112 (a)). Pure: no I/O, no logging; the only module state is the
read-only dispatch table.

Numbers use the importer's #13 grammar (`values.parse_number`), so BIT012 at
import and the numeric operators read them the same way, and compare as exact
decimals (never `int()` or `float()`). Patterns compile only through
`values.compile_pattern` (RE2, multiline, RE2 error log silenced), so a bad
pattern cannot hang the manager and Python `re` is never used.
"""

from __future__ import annotations

import operator as op
from collections.abc import Callable, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from bitscan_manager.services.importer import values


class NotNumeric(Exception):
    """A numeric operator's stdout is not one #13 number (ERROR
    `stdout not numeric`). Carries no text."""


class CannotEvaluate(Exception):
    """The comparison cannot be made (ERROR `cannot evaluate`, #112 (a)): an
    operator outside the 14, a non-numeric expected value for a numeric
    operator, a pattern RE2 refuses, or stdout RE2 cannot encode. Carries no
    text."""


_Compare = Callable[[str, str], bool]  # (expected, stdout) -> holds


def _equals(expected: str, stdout: str) -> bool:
    return stdout == expected


def _not_equals(expected: str, stdout: str) -> bool:
    return stdout != expected


def _contains(expected: str, stdout: str) -> bool:
    return expected in stdout


def _not_contains(expected: str, stdout: str) -> bool:
    return expected not in stdout


def _matches(expected: str, stdout: str) -> bool:
    """A search (not a full match): `^`/`$` anchor at each line (SR §2.4)."""
    try:
        pattern = values.compile_pattern(expected)
    except values.PatternError:
        raise CannotEvaluate() from None
    try:
        return pattern.search(stdout) is not None
    except UnicodeEncodeError:
        # A lone surrogate in stdout cannot be passed to RE2 as UTF-8.
        raise CannotEvaluate() from None


def _regex(expected: str, stdout: str) -> bool:
    return _matches(expected, stdout)


def _not_regex(expected: str, stdout: str) -> bool:
    # A signal from _matches propagates, so not_regex never passes on a
    # pattern or text it could not check.
    return not _matches(expected, stdout)


def _numeric(test: Callable[[Decimal, Decimal], bool]) -> _Compare:
    """`test(stdout, expected)` on the two #13 numbers. The expected value is
    checked first: it was refused at import (BIT012), so its failure is the
    spec's, not the host's."""

    def compare(expected: str, stdout: str) -> bool:
        want = values.parse_number(expected)
        if want is None:
            raise CannotEvaluate()
        got = values.parse_number(stdout)
        if got is None:
            raise NotNumeric()
        return test(got, want)

    return compare


def _empty(expected: str, stdout: str) -> bool:
    return stdout == ""


def _not_empty(expected: str, stdout: str) -> bool:
    return stdout != ""


# In the order of `importer.model.OPERATORS` (a test holds the two equal).
COMPARISONS: Final[Mapping[str, _Compare]] = MappingProxyType(
    {
        "equals": _equals,
        "not_equals": _not_equals,
        "contains": _contains,
        "not_contains": _not_contains,
        "regex": _regex,
        "not_regex": _not_regex,
        "eq": _numeric(op.eq),
        "ne": _numeric(op.ne),
        "gt": _numeric(op.gt),
        "ge": _numeric(op.ge),
        "lt": _numeric(op.lt),
        "le": _numeric(op.le),
        "empty": _empty,
        "not_empty": _not_empty,
    }
)


def compare(operator: str, expected: str, stdout: str) -> bool:
    """True when `stdout` satisfies `operator` against `expected`; both are
    already normalised. Operator names are case-sensitive: the importer stores
    them lowercase (SR §2.3). Raises NotNumeric or CannotEvaluate, never
    anything else."""
    test = COMPARISONS.get(operator)
    if test is None:
        raise CannotEvaluate()
    return test(expected, stdout)
