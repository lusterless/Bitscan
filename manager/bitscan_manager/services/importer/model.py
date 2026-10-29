"""Importer model: findings, the validation code table, the SR §2 limits and
the parsed forms of a `.bit` file (SR §2, §3.5, §4; open questions #57, #105).

Pure data. Nothing here reads files, the database or the clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, TypedDict


class Severity(StrEnum):
    REJECT = "reject"
    WARN = "warn"


class Code(StrEnum):
    """SR §4.1 codes. BIT006, BIT009 and BIT018-BIT020 are retired (SR §4)
    and must never be added back."""

    BIT001 = "BIT001"
    BIT002 = "BIT002"
    BIT003 = "BIT003"
    BIT004 = "BIT004"
    BIT005 = "BIT005"
    BIT007 = "BIT007"
    BIT008 = "BIT008"
    BIT010 = "BIT010"
    BIT011 = "BIT011"
    BIT012 = "BIT012"
    BIT013 = "BIT013"
    BIT014 = "BIT014"
    BIT015 = "BIT015"
    BIT016 = "BIT016"
    BIT017 = "BIT017"
    BIT101 = "BIT101"
    BIT102 = "BIT102"
    BIT103 = "BIT103"


# Severity is per rule, not by number range (SR §4): BIT102 rejects.
SEVERITY: Final[Mapping[Code, Severity]] = MappingProxyType(
    {
        code: Severity.WARN if code in (Code.BIT101, Code.BIT103) else Severity.REJECT
        for code in Code
    }
)

# SR §2 limits, in characters (code points), as VARCHAR(n) counts them.
MAX_BIT_BYTES: Final = 5 * 1_048_576  # "5 MB" read as MiB (#57)
FORMAT_VERSIONS: Final = ("1.0",)
FORMAT_VERSION_DEFAULT: Final = "1.0"
POLICY_STATUSES: Final = ("enabled", "disabled")
PLUGINS_MIN: Final = 1
PLUGINS_MAX: Final = 5_000
TIMEOUT_MIN: Final = 1
TIMEOUT_MAX: Final = 600
TIMEOUT_DEFAULT: Final = 60
CONTROL_REF_MAX: Final = 32  # SR §3.3; longer is BIT103 and stored as NULL

# Element name -> (min, max) length after trimming (#17).
LENGTH_LIMITS: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "PolicyName": (1, 128),
        "PolicyDescription": (0, 4_000),
        "FamilyName": (1, 128),
        "PluginName": (1, 255),
        "PluginDescription": (0, 4_000),
        "Execute": (1, 16_384),
        "ExpectedResult": (0, 4_000),
    }
)

# SR §2.4: the 14 operators, in the order of the `plugin_operator` enum.
NUMERIC_OPERATORS: Final = ("eq", "ne", "gt", "ge", "lt", "le")
REGEX_OPERATORS: Final = ("regex", "not_regex")
PRESENCE_OPERATORS: Final = ("empty", "not_empty")
OPERATORS: Final = (
    ("equals", "not_equals", "contains", "not_contains")
    + REGEX_OPERATORS
    + NUMERIC_OPERATORS
    + PRESENCE_OPERATORS
)

QUOTE_MAX: Final = 64  # characters of file content a message may hold (#105 (g))


class FindingJSON(TypedDict):
    line: int | None
    element: str | None
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One `bit_import.errors` item (SR §3.5). `line` is 1-based or None;
    `element` is the #105 (g) path or None for a file-level finding."""

    line: int | None
    element: str | None
    code: Code
    message: str

    def __post_init__(self) -> None:
        # Code() refuses any string outside the table, retired codes included.
        object.__setattr__(self, "code", Code(self.code))

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.code]

    @property
    def rejects(self) -> bool:
        return self.severity is Severity.REJECT

    def to_json(self) -> FindingJSON:
        return {
            "line": self.line,
            "element": self.element,
            "code": self.code.value,
            "message": self.message,
        }


def quote(value: str) -> str:
    """Quote at most QUOTE_MAX characters of a file value for a message,
    with C0 controls, DEL and backslash escaped (#105 (g))."""
    cut = value[:QUOTE_MAX]
    out: list[str] = []
    for ch in cut:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\x{cp:02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"' + ("..." if len(value) > QUOTE_MAX else "")


def plugin_path(index: int, element: str | None = None) -> str:
    """`Policy/PluginsGroups/Plugin[<index>]` (1-based), optionally with a
    child element or `Execute/@timeout` appended (#105 (g))."""
    base = f"Policy/PluginsGroups/Plugin[{index}]"
    return base if element is None else f"{base}/{element}"


@dataclass(frozen=True, slots=True)
class Node:
    """One XML element as the parser saw it. `name` is the raw tag;
    `attributes` keep document order; `text` is the element's own
    character data (CDATA and text joined, comments excluded)."""

    name: str
    line: int
    attributes: tuple[tuple[str, str], ...]
    text: str
    children: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class RawValue:
    """A value as written in the file (not trimmed), with the line of its
    start tag and its #105 (g) path. Attribute values use the line of the
    element that holds them."""

    text: str
    line: int
    path: str


@dataclass(frozen=True, slots=True)
class ParsedPlugin:
    """One `<Plugin>` after the structure check. `operator` and
    `expected_result` are None when the element is missing (#2: BIT010 and
    BIT011); `timeout` is None when the attribute is absent."""

    index: int  # 1-based position in PluginsGroups = sort_order
    line: int
    plugin_name: RawValue
    plugin_description: RawValue
    plugin_id: RawValue
    execute: RawValue
    timeout: RawValue | None
    operator: RawValue | None
    expected_result: RawValue | None

    @property
    def path(self) -> str:
        return plugin_path(self.index)


@dataclass(frozen=True, slots=True)
class ParsedPolicy:
    """A structurally valid file (BIT001 and BIT002 passed), raw values only;
    the content rules (TASK-144) trim and check them."""

    line: int
    format_version: RawValue | None  # None when `@formatVersion` is absent
    policy_name: RawValue
    policy_description: RawValue
    policy_status: RawValue
    family_name: RawValue
    plugins: tuple[ParsedPlugin, ...]
