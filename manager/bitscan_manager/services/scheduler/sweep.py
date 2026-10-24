"""offline_sweep (TS §3.3 L218, L220, §3.4 L244, §4.4 L572, L575; REQ-078;
#25, #73; plan work/plans/TASK-061.md).

Each step runs in its own transaction, so a step that fails leaves the others
applied and the next sweep simply runs it again; a failure is logged by step
name and exception type only. The sweep never creates a job: inventory jobs
are never retried (TS §3.4 L244). The compliance steps (deadlines, the 24 h
never-started rule, retries) come with M9.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.jobs import JobRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Database, Tx
from bitscan_manager.services.audit.metrics import JOBS_EXPIRED
from bitscan_manager.services.settings.store import SettingsReader, read_settings
from bitscan_manager.services.users import TxAudit

log = logging.getLogger("bitscan_manager.scheduler")

STALE_AFTER: Final = timedelta(minutes=10)  # online below, stale from here
OFFLINE_AFTER: Final = timedelta(minutes=30)  # offline above
INVENTORY_UPLOAD_WINDOW: Final = timedelta(minutes=30)  # TS §3.4 L244


class SweepAgents(Protocol):
    def apply_heartbeat_ages(
        self, now: datetime, stale_after: timedelta, offline_after: timedelta
    ) -> int: ...

    def decommission_offline(self, now: datetime, after: timedelta) -> list[UUID]: ...


class SweepJobs(Protocol):
    def expire_past_pickup(self, now: datetime) -> int: ...

    def fail_dispatched_inventory(
        self, dispatched_before: datetime, now: datetime
    ) -> int: ...


class Auditor(Protocol):  # services.users.TxAudit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None: ...


@dataclass(frozen=True)
class Stores:
    """What one step's transaction works with."""

    tx: Tx
    agents: SweepAgents
    jobs: SweepJobs
    settings: SettingsReader
    audit: Auditor


def pg_stores(tx: Tx) -> Stores:
    return Stores(
        tx,
        AgentRepo(tx.conn),
        JobRepo(tx.conn),
        SettingsRepo(tx.conn),
        TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
    )


@dataclass
class SweepResult:
    statuses_changed: int = 0
    decommissioned: int = 0
    expired: int = 0
    inventory_failed: int = 0
    failed_steps: list[str] = field(default_factory=list)


def _statuses(s: Stores, now: datetime, out: SweepResult) -> None:
    out.statuses_changed = s.agents.apply_heartbeat_ages(
        now, STALE_AFTER, OFFLINE_AFTER
    )


def _decommission(s: Stores, now: datetime, out: SweepResult) -> None:
    days = read_settings(s.settings).decommission_after_days
    if days == 0:  # 0 = never (TS §3.3 L220)
        return
    ids = s.agents.decommission_offline(now, timedelta(days=days))
    for agent_id in ids:  # one entry per decommissioned agent (#73 (d))
        target = f"agent:{agent_id}"
        s.audit.audit("system", "agent.decommission", target, {"after_days": days})
    out.decommissioned = len(ids)


def _expire(s: Stores, now: datetime, out: SweepResult) -> None:
    count = s.jobs.expire_past_pickup(now)
    if count:
        s.tx.on_commit(lambda: JOBS_EXPIRED.inc(count))  # only once committed
    out.expired = count


def _inventory_timeout(s: Stores, now: datetime, out: SweepResult) -> None:
    out.inventory_failed = s.jobs.fail_dispatched_inventory(
        now - INVENTORY_UPLOAD_WINDOW, now
    )


STEPS: Final[
    tuple[tuple[str, Callable[[Stores, datetime, SweepResult], None]], ...]
] = (
    ("statuses", _statuses),
    ("decommission", _decommission),
    ("expire", _expire),
    ("inventory_timeout", _inventory_timeout),
)


def run_sweep(
    db: Database, now: datetime, stores: Callable[[Tx], Stores] = pg_stores
) -> SweepResult:
    out = SweepResult()
    for name, step in STEPS:
        try:
            with db.transaction() as tx:
                step(stores(tx), now, out)
        except Exception as exc:  # the other steps still run (REQ-078 (5))
            out.failed_steps.append(name)
            log.error(
                "sweep step failed",
                extra={"data": {"step": name, "exc_type": type(exc).__name__}},
            )
    return out
