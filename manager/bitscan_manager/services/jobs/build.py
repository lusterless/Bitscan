"""Compliance job and retry building (TS §3.5 L248, §6.5, §4.4 L566, L577,
§4.1 L530, §4.5 L587, L603; REQ-209, REQ-210, REQ-212; open questions #117,
#125 (a)–(c), (g), #126 (a), (b)).

A job's `execute` values come only from the catalog plugins handed in by the
queue service (the active plugins of the scanned policy), or, for a retry,
from its original's stored payload; nothing here takes command text from a
request. Operator and ExpectedResult go only into `eval_spec`, which stays on
the manager.

Pure: no I/O, no logging, no clock. Errors carry fixed text only.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from bitscan_manager.services.evaluator.eval_spec import (
    EvalSpec,
    build_eval_spec,
    parse_eval_spec,
)
from bitscan_manager.services.evaluator.model import PluginSpec

# Re-exported: the plan's interface lists it here (24 h, M3's value).
from bitscan_manager.services.scheduler.inventory import (
    PICKUP_WINDOW as PICKUP_WINDOW,
)

PICKUP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"  # as M3's inventory jobs (#125 (c))


@dataclass(frozen=True, slots=True)
class CatalogPlugin:
    """One active plugin of the policy, from the queue snapshot."""

    plugin_uuid: UUID
    display_name: str  # v_plugin.display_name: "<family name> - <plugin name>"
    execute: str
    timeout_s: int
    operator: str
    expected: str


class UnstorableText(ValueError):
    """A text the database cannot store (U+0000 or a lone surrogate) reached
    the builder (#125 (g)); the message never quotes it."""

    def __init__(self) -> None:
        super().__init__("job text holds a character the database cannot store")


@dataclass(frozen=True, slots=True)
class BuiltPlugins:
    """The parts every job of one scan shares."""

    plugins_json: list[dict[str, Any]]  # [{plugin_uuid, execute, timeout_s}], in order
    eval_spec_json: dict[str, Any]  # build_eval_spec() of the same plugins, same order
    patterns: list[str]  # the redaction_patterns setting at queue time


def _check_storable(text: str) -> None:
    if "\x00" in text:
        raise UnstorableText
    try:
        text.encode("utf-8")  # a lone surrogate cannot be encoded
    except UnicodeEncodeError:
        raise UnstorableText from None


def pickup_text(created_at: datetime) -> str:
    """`pickup_by` as the payload writes it: created_at + 24 h in UTC, to the
    second (#125 (c)). A naive time is refused rather than read as local."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be time-zone aware")
    return (created_at + PICKUP_WINDOW).astimezone(UTC).strftime(PICKUP_FORMAT)


def plugins_and_spec(
    plugins: Sequence[CatalogPlugin], patterns: Sequence[str]
) -> BuiltPlugins:
    """The payload plugins and `eval_spec` of one scan. Every text is checked
    before anything is built; `EvalSpec` enforces 1–5,000 distinct plugins,
    the operators and the lengths (an empty list raises ValueError)."""
    for p in plugins:
        for text in (p.execute, p.display_name, p.expected):
            _check_storable(text)
    for pattern in patterns:
        _check_storable(pattern)
    spec = EvalSpec(
        tuple(
            PluginSpec(
                plugin_uuid=p.plugin_uuid,
                name=p.display_name,
                operator=p.operator,
                expected=p.expected,
            )
            for p in plugins
        )
    )
    return BuiltPlugins(
        plugins_json=[
            {
                "plugin_uuid": str(p.plugin_uuid),
                "execute": p.execute,
                "timeout_s": p.timeout_s,
            }
            for p in plugins
        ],
        eval_spec_json=build_eval_spec(spec),
        patterns=list(patterns),
    )


def payload(
    job_id: UUID, agent_id: UUID, created_at: datetime, built: BuiltPlugins
) -> dict[str, Any]:
    """Exactly the TS §6.5 compliance Job. The reference the SQL-composed
    payloads of `repositories.scan_queue` are compared against."""
    return {
        "job_id": str(job_id),
        "agent_id": str(agent_id),
        "kind": "compliance",
        "pickup_by": pickup_text(created_at),
        "plugins": [dict(p) for p in built.plugins_json],
        "redaction_patterns": list(built.patterns),
    }


def retry(
    original_payload: Mapping[str, Any],
    original_eval_spec: Mapping[str, Any],
    missing: Collection[UUID],
    *,
    job_id: UUID,
    created_at: datetime,
    original_is_retry: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(payload, eval_spec) of the single retry (#126 (a), (b)): the
    original's items for the `missing` plugins, in the original order, with
    the original's commands, timeouts and redaction patterns; never the
    current catalog's. A retry is never retried."""
    if original_is_retry:
        raise ValueError("a retry is never retried")
    wanted = set(missing)
    if not wanted:
        raise ValueError("a retry needs at least one missing plugin")
    items = [
        {
            "plugin_uuid": item["plugin_uuid"],
            "execute": item["execute"],
            "timeout_s": item["timeout_s"],
        }
        for item in original_payload["plugins"]
        if UUID(item["plugin_uuid"]) in wanted
    ]
    kept = [UUID(item["plugin_uuid"]) for item in items]
    if set(kept) != wanted:
        raise ValueError("a missing plugin is not in the original job")
    spec = parse_eval_spec(original_eval_spec)
    entries = tuple(p for p in spec.plugins if p.plugin_uuid in wanted)
    if [p.plugin_uuid for p in entries] != kept:
        raise ValueError("the original eval_spec does not match its payload")
    new_payload = {
        "job_id": str(job_id),
        "agent_id": str(UUID(original_payload["agent_id"])),
        "kind": "compliance",
        "pickup_by": pickup_text(created_at),
        "plugins": items,
        "redaction_patterns": list(original_payload["redaction_patterns"]),
    }
    return new_payload, build_eval_spec(EvalSpec(entries))
