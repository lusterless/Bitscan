"""Value helpers shared by the importer and M8's evaluator (SR §2.3, §2.4;
TS §4.5; open questions #13, #17, #109).

BIT012 and BIT013 at import and `evaluate()` at scan time use these same
functions, so a value accepted at import is read the same way when results
arrive. Pure: no I/O, no logging, nothing written to stderr.

Every check takes the value already trimmed and never trims it itself, so each
caller keeps its own rule: the importer trims with `trim_xml` (#17), the
evaluator applies its CRLF and whitespace normalisation (SR §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

import re2  # type: ignore[import-untyped]

from bitscan_manager.services.importer.model import CONTROL_REF_MAX, Code

# XML whitespace (XML 1.0 production S). Other Unicode spaces such as U+00A0
# are content and stay (#17).
XML_WHITESPACE: Final = " \t\r\n"

_HEX_LOWER: Final = frozenset("0123456789abcdef")
_UUID_HYPHENS: Final = (8, 13, 18, 23)
_UUID_LENGTH: Final = 36

# RE2 must never write a refused pattern to stderr (REQ-153 (6)).
_RE2_OPTIONS: Final = re2.Options()
_RE2_OPTIONS.log_errors = False
# SR §2.4: `regex` matches "multiline; use ^/$ to anchor". In RE2's default
# (Perl) syntax ^ and $ match only at the ends of the text unless (?m) is set.
_MULTILINE: Final = "(?m)"


def trim_xml(text: str) -> str:
    """`text` without leading and trailing space, tab, CR and LF (#17)."""
    return text.strip(XML_WHITESPACE)


def _ascii_digits(text: str) -> bool:
    # str.isdigit alone accepts other scripts' digits; isascii limits it to 0-9.
    return text.isascii() and text.isdigit()


def is_number(text: str) -> bool:
    """The #13 grammar `[+-]?[0-9]+(\\.[0-9]+)?`, ASCII digits only: no
    exponent, `nan`, `inf`, `_`, hexadecimal, leading or trailing point."""
    body = text[1:] if text[:1] in ("+", "-") else text
    whole, point, fraction = body.partition(".")
    return _ascii_digits(whole) and (not point or _ascii_digits(fraction))


def parse_number(text: str) -> Decimal | None:
    """The exact decimal value of a #13 number, or None if `text` is not one.
    Decimal construction from a string is exact at any length, so numbers are
    compared exactly (#13), never as binary floats."""
    return Decimal(text) if is_number(text) else None


class Pattern(Protocol):
    """The part of a compiled google-re2 pattern the evaluator uses."""

    def search(self, text: str, /) -> object | None: ...


class PatternError(ValueError):
    """`ExpectedResult` is not a pattern RE2 compiles (BIT013). The message is
    fixed: RE2's own error text is never carried (REQ-153)."""

    def __init__(self) -> None:
        super().__init__("not a valid RE2 pattern")


def compile_pattern(pattern: str) -> Pattern:
    """Compile `pattern` exactly as `regex` and `not_regex` evaluate it (RE2,
    multiline, UTF-8, case-sensitive), or raise PatternError. RE2 runs in
    linear time, so no pattern can hang the manager (TS §4.5)."""
    try:
        compiled: Pattern = re2.compile(_MULTILINE + pattern, _RE2_OPTIONS)
    except (UnicodeEncodeError, re2.error):
        # A lone surrogate cannot be encoded as UTF-8; RE2 refused the rest.
        raise PatternError() from None
    return compiled


def is_valid_pattern(pattern: str) -> bool:
    """True when `compile_pattern` accepts `pattern` (BIT013)."""
    try:
        compile_pattern(pattern)
    except PatternError:
        return False
    return True


def is_plugin_uuid(text: str) -> bool:
    """The #109 `PluginId` form: exactly 8-4-4-4-12 lowercase hexadecimal.
    Uppercase, braces, `urn:uuid:` and the unhyphenated form are BIT004;
    version and variant bits are not checked."""
    if len(text) != _UUID_LENGTH:
        return False
    return all(
        ch == "-" if i in _UUID_HYPHENS else ch in _HEX_LOWER
        for i, ch in enumerate(text)
    )


@dataclass(frozen=True, slots=True)
class ControlRef:
    """`plugin.control_ref` (SR §3.3) and the warning it raises, if any:
    BIT101 with no leading reference, BIT103 when it is over 32 characters.
    `value` is None whenever `warning` is set."""

    value: str | None
    warning: Code | None


def control_ref(plugin_name: str) -> ControlRef:
    """The leading ASCII `[0-9]+(\\.[0-9]+)*` of a trimmed `PluginName`
    (REQ-154): `1.3.1.1 - Ensure ...` gives `1.3.1.1`. A point not followed by
    a digit ends the reference."""
    end = _digits_end(plugin_name, 0)
    if end == 0:
        return ControlRef(None, Code.BIT101)
    while end < len(plugin_name) and plugin_name[end] == ".":
        after = _digits_end(plugin_name, end + 1)
        if after == end + 1:
            break
        end = after
    if end > CONTROL_REF_MAX:
        return ControlRef(None, Code.BIT103)
    return ControlRef(plugin_name[:end], None)


def _digits_end(text: str, start: int) -> int:
    """Index after the run of ASCII digits that starts at `start`."""
    end = start
    while end < len(text) and "0" <= text[end] <= "9":
        end += 1
    return end
