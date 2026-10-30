"""Scan state derivation (TS §4.4 L579–L580; REQ-207; open questions #22,
#127 (d), (e)).

A scan is derived over its units: one per host, the original job and its
retry, if any (#127 (d)). This answers two spec-internal points: an original
that ended `partial` stays `partial` after its retry fills the missing
plugins, so "every job completed" is read per unit; and a scan cancelled
after some results is `partial` (or `completed`), never `cancelled`.

Pure: no I/O, no logging, no clock. Never gives `dispatched` or `expired`,
which are job states only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Unit:
    """The facts of one host's unit that the derivation reads."""

    open: bool  # a job of the unit is queued, dispatched or running
    complete: bool  # every plugin of the original's payload has a result in the unit
    has_results: bool  # any scan_result row exists for a job of the unit
    any_cancelled: bool  # a job of the unit is cancelled
    all_queued: bool  # every job of the unit is still queued


ScanState = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]


def derive(units: Sequence[Unit]) -> tuple[ScanState, bool]:
    """(state, finished). Finished exactly when no unit is open (#127 (e)).
    A scan always has at least one job (#3), so an empty list raises."""
    if not units:
        raise ValueError("a scan has at least one unit")
    if any(u.open for u in units):
        # #22: `running` once any job has left `queued`.
        return ("queued" if all(u.all_queued for u in units) else "running"), False
    if all(u.complete for u in units):
        return "completed", True
    if any(u.has_results for u in units):
        return "partial", True
    if any(u.any_cancelled for u in units):
        return "cancelled", True
    return "failed", True
