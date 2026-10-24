"""The default redaction patterns and the removed-default alert (TS §8.6
L1324, L1329–L1339, §8.4 L1290; REQ-084; PD-23).

Each pattern in a patch is compiled with RE2 by store.validate_patch (one
compile, log_errors off); this module only knows the five defaults and which
of them a patch removes.
"""

from collections.abc import Sequence
from typing import Final

# TS §8.6 L1332–L1336, one per line, exactly as written.
DEFAULT_PATTERNS: Final[tuple[str, ...]] = (
    r"\$(?:1|2[abxy]?|5|6|7|y|gy|sha1|md5)\$[^:\s]+",
    r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\z)",  # noqa: E501 - spec line kept verbatim
    r"\bbs[aeku]_[A-Za-z0-9_-]{20,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"(?i)(?:password|secret|api[_-]?key|token)\s*[=:]\s*\S+",
)


def removed_defaults(before: Sequence[str], after: Sequence[str]) -> list[str]:
    """The defaults present before and missing after, in spec order. A default
    removed by an earlier patch is not reported again."""
    kept = set(after)
    present = set(before)
    return [p for p in DEFAULT_PATTERNS if p in present and p not in kept]
