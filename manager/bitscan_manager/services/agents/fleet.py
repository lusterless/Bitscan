"""Fleet reads: GET /agents, /agents/{id}, /agents/{id}/packages (TS §6.2
L1108–L1110, §7.3 L1225; REQ-081; #68, #69). Read-only; the routes shape the
#68 items and never carry a token or a token hash.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentListRow, AgentRow
from bitscan_manager.repositories.inventory import (
    AgentPackageRow,
    OsInfoRow,
    SnapshotRow,
)


class FleetAgents(Protocol):  # repositories.agents.AgentRepo
    def list_page(self, limit: int, after_id: UUID | None) -> list[AgentListRow]: ...

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def tags(self, agent_id: UUID) -> list[str]: ...


class FleetInventory(Protocol):  # repositories.inventory.InventoryRepo
    def get_os_info(self, agent_id: UUID) -> OsInfoRow | None: ...

    def latest_snapshot(self, agent_id: UUID) -> SnapshotRow | None: ...

    def package_page(
        self, agent_id: UUID, limit: int | None, after_package_id: int | None
    ) -> list[AgentPackageRow]: ...


@dataclass(frozen=True)
class AgentDetail:
    agent: AgentRow
    tags: list[str]
    os_info: OsInfoRow | None
    last_snapshot: SnapshotRow | None  # #69: shown on the host page (TS §7.3)


def list_agents(
    agents: FleetAgents, limit: int, after_id: UUID | None
) -> list[AgentListRow]:
    """In (hostname, agent_id) order (#68), after the agent after_id; every
    status is listed. AnchorGone (repositories.packages) passes through."""
    return agents.list_page(limit, after_id)


def agent_detail(
    agents: FleetAgents, inventory: FleetInventory, agent_id: UUID
) -> AgentDetail | None:
    agent = agents.get(agent_id)
    if agent is None:
        return None
    return AgentDetail(
        agent,
        agents.tags(agent_id),
        inventory.get_os_info(agent_id),
        inventory.latest_snapshot(agent_id),
    )


def agent_packages(
    agents: FleetAgents,
    inventory: FleetInventory,
    agent_id: UUID,
    limit: int,
    after_package_id: int | None,
) -> list[AgentPackageRow] | None:
    """By name, architecture and version in Debian order (TASK-053), after
    the package after_package_id; None for an unknown agent. AnchorGone
    (repositories.packages) passes through."""
    if agents.get(agent_id) is None:
        return None
    return inventory.package_page(agent_id, limit, after_package_id)
