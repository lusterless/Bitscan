"""The normaliser applied to stdout and the expected value before any
comparison (TS §4.5 L597; SR §2.4; open questions #11, #115). Pure."""

from __future__ import annotations

from typing import Final

# C-locale ASCII whitespace (#115). `str.strip()` with no argument would also
# remove Unicode spaces such as U+00A0, which are content here.
WHITESPACE: Final = " \t\n\v\f\r"


def normalise(text: str) -> str:
    """Every CRLF becomes LF, then `WHITESPACE` is trimmed at both ends.
    Nothing else changes: no case folding, no Unicode normalisation, and a
    lone CR inside the text stays."""
    return text.replace("\r\n", "\n").strip(WHITESPACE)
