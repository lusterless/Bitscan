"""Inventory queueing, the system job (TS §3.4 L230, L237; #36, #67).

Each run gives every agent that is not decommissioned or awaiting approval,
and has no inventory job queued, dispatched or running, one inventory job
with pickup_by = creation + 24 h (TS §4.4 L566). Nothing can stop or skip a
run: there is no setting, parameter or route for it (TS §6.2 L1129). Runs
are serialised by the repository's transaction lock, so a timer run and a
first-job call at the same moment still give one open job per agent.
"""

from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

PICKUP_WINDOW: Final = timedelta(hours=24)


class InventoryQueue(Protocol):
    def queue_inventory(
        self, now: datetime, pickup_by: datetime, agent_id: UUID | None = None
    ) -> list[UUID]: ...


def run_inventory(jobs: InventoryQueue, now: datetime) -> list[UUID]:
    """One scheduled run (#67): the ids of the jobs it queued."""
    return jobs.queue_inventory(now, now + PICKUP_WINDOW)


def queue_first_inventory(
    jobs: InventoryQueue, agent_id: UUID, now: datetime
) -> UUID | None:
    """The first job when an agent becomes enrolled (#36), unless it already
    has an open inventory job or is not eligible; None then."""
    queued = jobs.queue_inventory(now, now + PICKUP_WINDOW, agent_id)
    return queued[0] if queued else None
