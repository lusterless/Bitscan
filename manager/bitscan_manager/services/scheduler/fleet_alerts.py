"""Fleet threshold alerts run by offline_sweep (TS §8.4 L1291, §3.4 L242,
§5.3 L1047; REQ-079; #44, #65 (b), (c), (g), #66, #71; plan
work/plans/TASK-061.md, step 5).

Build FleetAlerts once per process (the scheduler, TASK-071): its windows
are in memory and reset on restart (#65). Each check reads and writes its
alert in its own transaction, and its window is marked only once that commit
succeeded, so a failed alert fires again on the next run (decisions
2026-10-23). A failing check is logged by name and exception type only, and
the other checks still run.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Clock, Database, Tx
from bitscan_manager.services.audit.thresholds import OncePerPeriod, ReArm
from bitscan_manager.services.settings.store import SettingsReader, read_settings
from bitscan_manager.services.users import TxAudit

log = logging.getLogger("bitscan_manager.scheduler")

OFFLINE_SHARE: Final = 0.05  # more than 5 % of agents offline
QUEUE_AGE: Final = timedelta(hours=1)
NOT_COUNTED: Final = frozenset({"decommissioned", "awaiting_approval"})  # #65 (b)


class FleetAgents(Protocol):
    def count_by_status(self) -> Mapping[str, int]: ...

    def stale_inventory(self, now: datetime, older_than: timedelta) -> list[UUID]: ...


class FleetJobs(Protocol):
    def oldest_queued_for_online(self) -> datetime | None: ...

    def default_partition_has_rows(self) -> bool: ...


class Alerter(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


@dataclass(frozen=True)
class FleetStores:
    tx: Tx
    agents: FleetAgents
    jobs: FleetJobs
    settings: SettingsReader
    audit: Alerter


def pg_fleet_stores(tx: Tx) -> FleetStores:
    return FleetStores(
        tx,
        AgentRepo(tx.conn),
        JobRepo(tx.conn),
        SettingsRepo(tx.conn),
        TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
    )


def _alert(
    s: FleetStores, kind: str, target: str, detail: Mapping[str, object]
) -> None:
    s.audit.alert(kind, "system", f"alert.{kind}", target, detail)


class FleetAlerts:
    def __init__(self, clock: Clock) -> None:
        self._offline: ReArm[str] = ReArm()  # #65 (b): again only after <= 5 %
        self._queue: OncePerPeriod[str] = OncePerPeriod(clock, timedelta(hours=1))
        self._stale: ReArm[UUID] = ReArm()  # #65 (c): once until the next upload
        self._partition: ReArm[str] = ReArm()  # #65 (g): again after it emptied

    def _offline_share(
        self, s: FleetStores, now: datetime
    ) -> Callable[[], None] | None:
        counts = s.agents.count_by_status()
        eligible = sum(n for status, n in counts.items() if status not in NOT_COUNTED)
        offline = counts.get("offline", 0)
        above = eligible > 0 and offline / eligible > OFFLINE_SHARE
        if not self._offline.due(["fleet"] if above else []):
            return None
        detail = {"offline": offline, "eligible": eligible, "over_share": OFFLINE_SHARE}
        _alert(s, "agents_offline", "fleet", detail)
        return lambda: self._offline.mark("fleet")

    def _queue_age(self, s: FleetStores, now: datetime) -> Callable[[], None] | None:
        oldest = s.jobs.oldest_queued_for_online()  # #66: online agents only
        if oldest is None or now - oldest <= QUEUE_AGE or not self._queue.due("queue"):
            return None
        age_s = int((now - oldest).total_seconds())
        _alert(s, "job_queue_age", "fleet", {"oldest_age_s": age_s})
        return lambda: self._queue.mark("queue")

    def _stale_inventory(
        self, s: FleetStores, now: datetime
    ) -> Callable[[], None] | None:
        interval = read_settings(s.settings).inventory_interval_s
        stale = s.agents.stale_inventory(now, timedelta(seconds=2 * interval))
        fresh = self._stale.due(stale)
        for agent_id in fresh:  # one entry per agent
            detail = {"older_than_s": 2 * interval}
            _alert(s, "inventory_stale", f"agent:{agent_id}", detail)
        if not fresh:
            return None

        def mark() -> None:
            for agent_id in fresh:
                self._stale.mark(agent_id)

        return mark

    def _default_partition(
        self, s: FleetStores, now: datetime
    ) -> Callable[[], None] | None:
        rows = s.jobs.default_partition_has_rows()
        if not self._partition.due(["default"] if rows else []):
            return None
        _alert(s, "default_partition_rows", "scan_result_default", {})
        return lambda: self._partition.mark("default")

    def run(
        self,
        db: Database,
        now: datetime,
        stores: Callable[[Tx], FleetStores] = pg_fleet_stores,
    ) -> list[str]:
        """Runs every check; returns the names of those that failed."""
        failed: list[str] = []
        checks = (
            ("agents_offline", self._offline_share),
            ("job_queue_age", self._queue_age),
            ("inventory_stale", self._stale_inventory),
            ("default_partition_rows", self._default_partition),
        )
        for name, check in checks:
            try:
                with db.transaction() as tx:
                    mark = check(stores(tx), now)
                if mark is not None:
                    mark()  # the alert committed: take the window's slot
            except Exception as exc:
                failed.append(name)
                log.error(
                    "fleet alert check failed",
                    extra={"data": {"check": name, "exc_type": type(exc).__name__}},
                )
        return failed
