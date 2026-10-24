"""Inventory ingestion (TS §3.4 L241–L243, §5.2 L780–L825, §8.4 L1291;
REQ-075; #65 (e), #69; plan work/plans/TASK-060.md, step 5).

Runs inside the caller's transaction, so an upload commits or rolls back as a
whole. Every upload replaces os_info (collected_at = receive time, #69) and
sets agent.last_inventory_at. If list_sha256 differs from the agent's last
snapshot, or there is none: unknown package rows are inserted (INSERT … ON
CONFLICT DO NOTHING, then selected: the app has no UPDATE on package),
agent_package is upserted (first_seen_at kept) and pruned to the listed
packages, and a snapshot records what was added and removed on the four
list_sha256 fields (#69: an upgrade or status change is the old line in
removed and the new line in added). Package rows stay; retention prunes them.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.inventory import (
    AgentPackageRow,
    OsInfoRow,
    PackageIds,
    PackageRow,
    SnapshotRow,
)
from bitscan_manager.services.inventory.decode import DecodedInventory

NEW_PACKAGES_PER_DAY: Final = 1000  # #65 (e): more than this alerts

Line = tuple[str, str, str, str]  # name, version, architecture, status


class InventoryStore(Protocol):  # repositories.inventory.InventoryRepo
    def upsert_os_info(self, agent_id: UUID, row: OsInfoRow) -> None: ...

    def insert_packages(self, rows: Sequence[PackageRow]) -> PackageIds: ...

    def agent_packages(self, agent_id: UUID) -> list[AgentPackageRow]: ...

    def upsert_agent_packages(
        self,
        agent_id: UUID,
        rows: Sequence[tuple[int, str, int | None]],
        now: datetime,
    ) -> None: ...

    def delete_not_listed(self, agent_id: UUID, keep_ids: Sequence[int]) -> int: ...

    def insert_snapshot(
        self,
        agent_id: UUID,
        list_sha256: str,
        package_count: int,
        added: list[dict[str, Any]],
        removed: list[dict[str, Any]],
        collected_at: datetime,
    ) -> int: ...

    def latest_snapshot(self, agent_id: UUID) -> SnapshotRow | None: ...


class AgentStore(Protocol):  # repositories.agents.AgentRepo
    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def set_last_inventory(self, agent_id: UUID, now: datetime) -> bool: ...


class Alerter(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


class BurstWindow(Protocol):  # services.audit.thresholds.SlidingCount
    def count_and_check(
        self, key: Any, weight: int = 1, threshold: int | None = None
    ) -> bool: ...

    def mark_fired(self, key: Any) -> None: ...


class AgentGone(Exception):
    """The agent's token was revoked, or the row vanished, after its token
    check; nothing was written. The route answers 401 token_revoked."""


@dataclass(frozen=True)
class IngestResult:
    snapshot_written: bool
    added: int
    removed: int
    new_packages: int  # package rows this upload created (fleet-new, #65 (e))


def _lines_json(lines: Sequence[Line]) -> list[dict[str, Any]]:
    keys = ("name", "version", "architecture", "status")
    return [dict(zip(keys, line, strict=True)) for line in sorted(lines)]


def ingest(
    inventory: InventoryStore,
    agents: AgentStore,
    audit: Alerter,
    burst: BurstWindow,
    on_commit: Callable[[Callable[[], None]], None],
    *,
    agent_id: UUID,
    decoded: DecodedInventory,
    now: datetime,
) -> IngestResult:
    agent = agents.get(agent_id, lock=True)  # serialises uploads of one agent
    if agent is None or agent.token_revoked_at is not None:
        raise AgentGone
    os = decoded.os_info
    inventory.upsert_os_info(
        agent_id,
        OsInfoRow(
            os.os_id,
            os.os_version_id,
            os.os_pretty_name,
            os.kernel_release,
            os.architecture,
            os.cpu_count,
            os.memory_mb,
            list(os.ip_addresses),
            os.uptime_s,
            os.raw,
            now,
        ),
    )
    agents.set_last_inventory(agent_id, now)
    last = inventory.latest_snapshot(agent_id)
    if last is not None and last.list_sha256 == decoded.list_sha256:
        return IngestResult(False, 0, 0, 0)

    packages = decoded.packages
    ids = inventory.insert_packages(
        [
            PackageRow(p.name, p.version, p.architecture, p.source or None)  # "" → NULL
            for p in packages
        ]
    )
    previous = {
        (r.name, r.version, r.architecture, r.status)
        for r in inventory.agent_packages(agent_id)
    }
    listed: set[Line] = {
        (p.name, p.version, p.architecture, p.status) for p in packages
    }
    rows = [
        (ids.ids[(p.name, p.version, p.architecture)], p.status, p.installed_size_kb)
        for p in packages
    ]
    inventory.upsert_agent_packages(agent_id, rows, now)
    inventory.delete_not_listed(agent_id, [package_id for package_id, _, _ in rows])
    added, removed = sorted(listed - previous), sorted(previous - listed)
    inventory.insert_snapshot(
        agent_id,
        decoded.list_sha256,
        len(packages),
        _lines_json(added),
        _lines_json(removed),
        now,
    )
    new = len(ids.new)
    if new and burst.count_and_check(agent_id, new):
        target = f"agent:{agent_id}"
        audit.alert(
            "new_packages_burst",
            target,
            "alert.new_packages_burst",
            target,
            {"new_packages": new, "over_per_day": NEW_PACKAGES_PER_DAY},
        )
        # The 24 h slot is taken only once this alert has committed.
        on_commit(lambda: burst.mark_fired(agent_id))
    return IngestResult(True, len(added), len(removed), new)
