"""The intake plan of one result batch (TS §6.1 L1071, §4.4 L578, §4.5 L587,
L596, L599, L603; REQ-214, REQ-215, REQ-216; open questions #12, #116 (d),
#121, #124 (a), (b)).

Given the job's `eval_spec`, its payload commands, the plugins its unit
already holds a result for, and the posted items, the plan lists exactly the
rows to insert, each with its verdict and snapshots, and how many items were
duplicates; or it refuses the whole batch when an item names a plugin
outside the job.

Pure: no I/O, no logging, no clock. Nothing here quotes stdout, stderr, a
command or an expected value in an error.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.services.evaluator.eval_spec import EvalSpec
from bitscan_manager.services.evaluator.evaluate import classify
from bitscan_manager.services.evaluator.model import Detail, ResultLike, Verdict
from bitscan_manager.services.evaluator.verdict import result_verdict

_REPLACEMENT: Final = 0xFFFD
# U+0000 and every surrogate code point (only lone ones survive json.loads,
# which joins escaped pairs) become U+FFFD (#121 (c)).
_UNSTORABLE: Final[dict[int, int]] = {0: _REPLACEMENT} | {
    c: _REPLACEMENT for c in range(0xD800, 0xE000)
}


class IntakeItem(ResultLike, Protocol):
    """A posted result item, as the M3 `ResultItem` has it."""

    @property
    def plugin_uuid(self) -> UUID: ...
    @property
    def started_at(self) -> datetime: ...
    @property
    def finished_at(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class ResultRow:
    """One `scan_result` INSERT row, values only."""

    plugin_uuid: UUID
    eval_code: int
    eval_detail: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    plugin_name_snap: str
    execute_snap: str
    operator_snap: str
    expected_snap: str
    started_at: datetime
    finished_at: datetime


class PluginNotInJob(Exception):
    """An item names a plugin that is not in the job (#124 (a)): the whole
    batch is refused."""

    def __init__(self) -> None:
        super().__init__("a result names a plugin that is not in the job")


@dataclass(frozen=True, slots=True)
class Plan:
    rows: tuple[ResultRow, ...]
    duplicates: int


def storable(text: str) -> str:
    """`text` with every U+0000 and lone surrogate replaced by U+FFFD
    (#121 (c)); unchanged when it holds neither."""
    if "\x00" not in text:
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            pass
        else:
            return text
    return text.translate(_UNSTORABLE)


def _verdict_on_stored(
    first: Verdict, operator: str, expected: str, item: IntakeItem, stdout: str
) -> Verdict:
    """The verdict of the text that is stored (#121 (c)). The caps were
    measured on the text as received (#121 (b)) and a runner error decides
    without the text (#12), so only a compared result is compared again, as
    re-evaluation compares stored text."""
    if item.error is not None or first.detail is Detail.OVERSIZE:
        return first
    return classify(
        operator, expected, stdout, item.exit_code, item.timed_out, item.truncated
    )


def plan(
    spec: EvalSpec,
    payload_plugins: Mapping[UUID, str],
    existing: Collection[UUID],
    items: Sequence[IntakeItem],
) -> Plan:
    """The rows to insert and the duplicates count. `payload_plugins` maps
    each plugin of the job's payload to its `execute`; `existing` holds the
    plugins the job or its sibling already has a result for. First in batch
    order wins within the batch (#124 (b))."""
    entries = []
    for item in items:  # membership first, for every item (#124 (a))
        entry = spec.get(item.plugin_uuid)
        if entry is None or item.plugin_uuid not in payload_plugins:
            raise PluginNotInJob
        entries.append(entry)
    seen = set(existing)
    rows: list[ResultRow] = []
    duplicates = 0
    for item, entry in zip(items, entries, strict=True):
        if item.plugin_uuid in seen:
            duplicates += 1
            continue
        seen.add(item.plugin_uuid)
        verdict = result_verdict(entry, item)  # caps on the received text
        if verdict.detail is Detail.OVERSIZE:
            stdout, stderr = "", ""  # #116 (d)
        else:
            stdout, stderr = storable(item.stdout), storable(item.stderr)
            if stdout != item.stdout:
                verdict = _verdict_on_stored(
                    verdict, entry.operator, entry.expected, item, stdout
                )
        rows.append(
            ResultRow(
                plugin_uuid=item.plugin_uuid,
                eval_code=verdict.code,
                eval_detail=None if verdict.detail is None else verdict.detail.value,
                exit_code=item.exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=item.timed_out,
                truncated=item.truncated,
                plugin_name_snap=entry.name,
                execute_snap=payload_plugins[item.plugin_uuid],
                operator_snap=entry.operator,
                expected_snap=entry.expected,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
        )
    return Plan(rows=tuple(rows), duplicates=duplicates)
