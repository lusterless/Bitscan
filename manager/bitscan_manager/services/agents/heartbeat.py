"""Heartbeat (TS §3.3 L202, L206, L211–L212, §3.7 L484, §6.5 L1163, §8.4
L1290–L1291; REQ-070, REQ-086, REQ-088; #25, #65 (a), #71, #73 (a)).

Records last_heartbeat_at, agent_version and runner_helpers (the source IP is
recorded by the route dependency, #25 (b)); an enrolled, stale or offline
agent becomes online at once (#73 (a)). The other heartbeat fields are
validated and dropped, except last_error, which is logged with the agent_id
and never audited (#25 (a)). A runner_helpers change writes one
runner_helper_changed alert entry (#71: one entry per event). A clock more
than 5 minutes from the server's alerts at most once per agent per hour
(#65 (a)). The answer is configuration only: never a job or a command, and
no job row is touched (TS §6.1 L1063, REQ-088).
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol
from uuid import UUID

from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.services.agents.versions import sends_parallel_jobs
from bitscan_manager.services.settings.store import SettingsReader, read_settings

log = logging.getLogger("bitscan_manager.agents")

MAX_SKEW: Final = timedelta(minutes=5)  # more than this alerts (TS §6.5 L1163)


class HeartbeatAgents(Protocol):  # repositories.agents.AgentRepo
    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None: ...

    def record_heartbeat(
        self, agent_id: UUID, now: datetime, agent_version: str, helpers: list[str]
    ) -> bool: ...


class Alerter(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


class SkewWindow(Protocol):  # services.audit.thresholds.OncePerPeriod
    def due(self, key: Any) -> bool: ...

    def mark(self, key: Any) -> None: ...


@dataclass(frozen=True)
class Beat:
    """The heartbeat fields the manager uses (the rest are dropped, #25)."""

    agent_version: str
    runner_helpers: list[str]
    clock: datetime
    last_error: str | None


@dataclass(frozen=True)
class HeartbeatAnswer:
    job_pull_seconds: int
    max_parallel_plugins: int
    server_time: datetime
    max_parallel_jobs: int | None  # None: the agent is older than 0.5.0


class AgentGone(Exception):
    """The agent row vanished after its token check."""


def heartbeat(
    agents: HeartbeatAgents,
    settings: SettingsReader,
    audit: Alerter,
    skew: SkewWindow,
    on_commit: Callable[[Callable[[], None]], None],
    *,
    agent_id: UUID,
    beat: Beat,
    now: datetime,
) -> HeartbeatAnswer:
    row = agents.get(agent_id, lock=True)  # a helper change is judged once
    if row is None:
        raise AgentGone
    agents.record_heartbeat(agent_id, now, beat.agent_version, beat.runner_helpers)
    actor = f"agent:{agent_id}"
    if set(row.runner_helpers) != set(beat.runner_helpers):  # TS §3.7 L484
        audit.alert(
            "runner_helper_changed",
            actor,
            "agent.runner_helpers_change",
            actor,
            {"old": list(row.runner_helpers), "new": list(beat.runner_helpers)},
        )
    offset = beat.clock - now
    if abs(offset) > MAX_SKEW and skew.due(agent_id):
        audit.alert(
            "clock_skew",
            actor,
            "alert.clock_skew",
            actor,
            {
                "agent_clock": beat.clock.isoformat(),
                "server_time": now.isoformat(),
                "skew_s": round(offset.total_seconds(), 3),
            },
        )
        on_commit(lambda: skew.mark(agent_id))  # the hour is taken on commit
    if beat.last_error is not None:  # #25 (a): logs only, at most 1,024 chars
        log.info("agent last_error", extra={"data": {"last_error": beat.last_error}})
    current = read_settings(settings)
    parallel_jobs = (
        current.max_parallel_jobs if sends_parallel_jobs(beat.agent_version) else None
    )
    return HeartbeatAnswer(
        current.job_pull_seconds, current.max_parallel_plugins, now, parallel_jobs
    )
