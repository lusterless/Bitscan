"""The `scan_job.eval_spec` contract (TS §5.2 L880, §4.5 L587, L603; #117).

    {"plugins": [{"plugin_uuid": "<lowercase uuid>",
                  "name": "<family name> - <plugin name>",
                  "operator": "<one of the 14>", "expected": "<ExpectedResult>"},
                 ...]}

One entry per plugin of the job, in payload order. M9 writes it with
`build_eval_spec()` when it queues a job; intake reads it with
`parse_eval_spec()`. It never holds `execute` or `timeout_s` (they are in the
payload), and it is never sent to an agent (TS §3.5 L248).

Pure: no I/O, no logging. Errors carry fixed text only, never the input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from bitscan_manager.services.evaluator.model import PluginSpec
from bitscan_manager.services.importer.model import (
    LENGTH_LIMITS,
    OPERATORS,
    PLUGINS_MAX,
    PLUGINS_MIN,
)

NAME_MAX: Final = 400  # scan_result.plugin_name_snap VARCHAR(400)
EXPECTED_MAX: Final = LENGTH_LIMITS["ExpectedResult"][1]  # 4,000
_TOP_KEYS: Final = frozenset({"plugins"})
_ENTRY_KEYS: Final = frozenset({"plugin_uuid", "name", "operator", "expected"})


class EvalSpecError(ValueError):
    """The eval_spec is not the #117 shape. The message never quotes input."""


@dataclass(frozen=True, slots=True)
class EvalSpec:
    """The job's evaluation entries, in payload order. Construction checks the
    #117 rules, so a spec that builds always parses."""

    plugins: tuple[PluginSpec, ...]
    _by_uuid: Mapping[UUID, PluginSpec] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not PLUGINS_MIN <= len(self.plugins) <= PLUGINS_MAX:
            raise EvalSpecError("eval_spec must list 1 to 5,000 plugins")
        index: dict[UUID, PluginSpec] = {}
        for p in self.plugins:
            if p.operator not in OPERATORS:
                raise EvalSpecError("eval_spec has an unknown operator")
            if not 1 <= len(p.name) <= NAME_MAX:
                raise EvalSpecError("eval_spec name must be 1 to 400 characters")
            if len(p.expected) > EXPECTED_MAX:
                raise EvalSpecError("eval_spec expected is over 4,000 characters")
            if p.plugin_uuid in index:
                raise EvalSpecError("eval_spec has a duplicate plugin_uuid")
            index[p.plugin_uuid] = p
        object.__setattr__(self, "_by_uuid", MappingProxyType(index))

    def get(self, plugin_uuid: UUID) -> PluginSpec | None:
        return self._by_uuid.get(plugin_uuid)


def build_eval_spec(spec: EvalSpec) -> dict[str, Any]:
    """The JSON-ready value for `scan_job.eval_spec`, in payload order."""
    return {
        "plugins": [
            {
                "plugin_uuid": str(p.plugin_uuid),
                "name": p.name,
                "operator": p.operator,
                "expected": p.expected,
            }
            for p in spec.plugins
        ]
    }


def _uuid(value: object) -> UUID:
    """Only the lowercase hyphenated 8-4-4-4-12 form; UUID() alone would also
    take uppercase, braced, urn: and 32-hex forms."""
    if not isinstance(value, str) or len(value) != 36:
        raise EvalSpecError("eval_spec plugin_uuid is not a lowercase uuid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise EvalSpecError("eval_spec plugin_uuid is not a lowercase uuid") from None
    if str(parsed) != value:
        raise EvalSpecError("eval_spec plugin_uuid is not a lowercase uuid")
    return parsed


def _text(entry: dict[Any, Any], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str):
        raise EvalSpecError("eval_spec values must be strings")
    return value


def _entry(item: object) -> PluginSpec:
    if not isinstance(item, dict) or item.keys() != _ENTRY_KEYS:
        raise EvalSpecError("eval_spec entry must have exactly the four keys")
    return PluginSpec(
        plugin_uuid=_uuid(item["plugin_uuid"]),
        name=_text(item, "name"),
        operator=_text(item, "operator"),
        expected=_text(item, "expected"),
    )


def parse_eval_spec(value: object) -> EvalSpec:
    """Strict parse of a decoded eval_spec (a JSONB value as psycopg returns
    it, or json.loads output). Raises EvalSpecError on anything else."""
    if not isinstance(value, dict) or value.keys() != _TOP_KEYS:
        raise EvalSpecError("eval_spec must be an object with only plugins")
    items = value["plugins"]
    if not isinstance(items, list):
        raise EvalSpecError("eval_spec plugins must be a list")
    if not PLUGINS_MIN <= len(items) <= PLUGINS_MAX:
        raise EvalSpecError("eval_spec must list 1 to 5,000 plugins")
    return EvalSpec(tuple(_entry(item) for item in items))
