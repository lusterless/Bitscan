"""Prometheus metrics (TS §8.4 L1288-L1289), in one registry that the metrics
route serves (#70). Every label value comes from a fixed set: alert kinds,
agent statuses, import modes and result verdicts only, never a hostname,
token or agent id (REQ-086 (3)).
"""

from collections.abc import Mapping
from typing import Final, Protocol

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY: Final = CollectorRegistry()

ALERTS_TOTAL: Final = Counter(
    "bitscan_alerts",
    "Alerts raised, by kind (every alert is also an audit entry).",
    ["kind"],
    registry=REGISTRY,
)

# The agent_status enum (TS §5.2 L710).
AGENT_STATUSES: Final = (
    "awaiting_approval",
    "enrolled",
    "online",
    "stale",
    "offline",
    "decommissioned",
)

AGENTS_BY_STATUS: Final = Gauge(
    "bitscan_agents",
    "Agents by status, counted from the database at scrape time.",
    ["status"],
    registry=REGISTRY,
)
for _status in AGENT_STATUSES:
    AGENTS_BY_STATUS.labels(status=_status)  # every status is exported, from zero

HEARTBEAT_LATENCY: Final = Histogram(
    "bitscan_heartbeat_latency_seconds",
    "Time the manager took to answer an agent heartbeat.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

JOBS_QUEUED: Final = Gauge(
    "bitscan_jobs_queued",
    "Jobs in state queued, counted from the database at scrape time.",
    registry=REGISTRY,
)

JOBS_EXPIRED: Final = Counter(
    "bitscan_jobs_expired",
    "Jobs that expired because nobody picked them up before pickup_by.",
    registry=REGISTRY,
)


# bit_import.mode (TS §5.2 L699).
IMPORT_MODES: Final = ("auto", "manual", "rebuild")

IMPORT_FAILURES: Final = Counter(
    "bitscan_import_failures",
    "Rejected .bit imports, by mode, counted when the import record commits.",
    ["mode"],
    registry=REGISTRY,
)
for _mode in IMPORT_MODES:
    IMPORT_FAILURES.labels(mode=_mode)  # every mode is exported, from zero

# scan_result.result (TS §5.2 check_result); the plugin ERROR rate (TS §8.4
# L1288, #129 (c)) is rate(ERROR) / rate(all).
PLUGIN_RESULT_LABELS: Final = ("PASS", "FAIL", "ERROR")

PLUGIN_RESULTS: Final = Counter(
    "bitscan_plugin_results",
    "Stored plugin results, by verdict, counted when their batch commits.",
    ["result"],
    registry=REGISTRY,
)
for _result in PLUGIN_RESULT_LABELS:
    PLUGIN_RESULTS.labels(result=_result)  # every verdict is exported, from zero


class FleetCounts(Protocol):  # repositories.agents.AgentRepo
    def count_by_status(self) -> Mapping[str, int]: ...


class QueueCounts(Protocol):  # repositories.jobs.JobRepo
    def count_queued(self) -> int: ...


def scrape(agents: FleetCounts, jobs: QueueCounts) -> bytes:
    """The registry in Prometheus text format (#70), with the two gauges set
    from database counts at scrape time (REQ-086 (2)). Every status is always
    exported, at 0 when no agent has it; no label is unbounded."""
    counts = agents.count_by_status()
    for status in AGENT_STATUSES:
        AGENTS_BY_STATUS.labels(status=status).set(counts.get(status, 0))
    JOBS_QUEUED.set(jobs.count_queued())
    return generate_latest(REGISTRY)
