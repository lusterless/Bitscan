"""Scan targets (TS §4.4 L555, §5.2 `scan.target`, §6.4; REQ-208; open
questions #122 (b)–(d), #68).

A target is exactly one of `{"agents": [...]}`, `{"tags": [...]}` (hosts
with any of the tags) or `{"all": true}`. It is resolved by the repository
at queue time; `stored_target()` gives the `scan.target` value: the request
plus the resolved agents.

Pure: no I/O, no logging. `InvalidTarget` names the field with fixed words
and never quotes the input.
"""

from __future__ import annotations

import string
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

TargetKind = Literal["agents", "tags", "all"]
AGENTS_MAX: Final = 10_000  # #122 (b)
# Copies of the M3 tag rule in services/agents/admin.py (MAX_TAGS,
# MAX_TAG_LENGTH, TAG_CHARACTERS; #68): importing that module would pull
# repositories.agents and psycopg into this pure module (decisions
# 2026-10-30, M9 early rulings (1)). A test pins them equal.
TAGS_MAX: Final = 32
MAX_TAG_LENGTH: Final = 64
TAG_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "._:-")

_KEYS: Final = frozenset({"agents", "tags", "all"})
_HYPHENS: Final = (8, 13, 18, 23)
_HEX: Final = frozenset(string.hexdigits)


class InvalidTarget(ValueError):
    def __init__(self, field: str = "target") -> None:
        super().__init__(f"Invalid request: {field}")
        self.field = field


@dataclass(frozen=True, slots=True)
class Target:
    kind: TargetKind
    agents: tuple[UUID, ...] = ()  # distinct, input order kept
    tags: tuple[str, ...] = ()  # distinct, input order kept


def _agent_id(value: object) -> UUID:
    """The hyphenated 8-4-4-4-12 form only, either case. `UUID()` alone also
    takes braced, `urn:` and 32-hex forms, and `int()` underneath accepts
    `_`, so every other character is checked to be a hex digit."""
    if not isinstance(value, str) or len(value) != 36:
        raise InvalidTarget("target.agents")
    for i, ch in enumerate(value):
        if (ch == "-") != (i in _HYPHENS) or (ch != "-" and ch not in _HEX):
            raise InvalidTarget("target.agents")
    return UUID(value)


def _agents(value: object) -> Target:
    if type(value) is not list or not 1 <= len(value) <= AGENTS_MAX:
        raise InvalidTarget("target.agents")
    ids = [_agent_id(v) for v in value]
    if len(set(ids)) != len(ids):  # by value: a case variant is a duplicate
        raise InvalidTarget("target.agents")
    return Target("agents", agents=tuple(ids))


def _tags(value: object) -> Target:
    if type(value) is not list or not 1 <= len(value) <= TAGS_MAX:
        raise InvalidTarget("target.tags")
    for tag in value:
        if (
            not isinstance(tag, str)
            or not 1 <= len(tag) <= MAX_TAG_LENGTH
            or not TAG_CHARACTERS.issuperset(tag)
        ):
            raise InvalidTarget("target.tags")
    if len(set(value)) != len(value):
        raise InvalidTarget("target.tags")
    return Target("tags", tags=tuple(value))


def parse_target(value: object) -> Target:
    """The decoded JSON `target` value as a Target, or InvalidTarget."""
    if type(value) is not dict or len(value) != 1:
        raise InvalidTarget
    ((key, inner),) = value.items()
    if key not in _KEYS:
        raise InvalidTarget
    if key == "all":
        if inner is not True:  # also refuses 1 and "true"
            raise InvalidTarget("target.all")
        return Target("all")
    return _agents(inner) if key == "agents" else _tags(inner)


def stored_target(target: Target, resolved: Sequence[UUID]) -> dict[str, Any]:
    """The `scan.target` value (#122 (d)): the request, agent ids lowercase,
    plus `resolved_agents`, distinct and sorted."""
    request: dict[str, Any]
    if target.kind == "agents":
        request = {"agents": [str(a) for a in target.agents]}
    elif target.kind == "tags":
        request = {"tags": list(target.tags)}
    else:
        request = {"all": True}
    request["resolved_agents"] = sorted({str(a) for a in resolved})
    return request
