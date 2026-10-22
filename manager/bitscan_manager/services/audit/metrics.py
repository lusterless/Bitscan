"""Prometheus metrics (TS §8.4). M2 has only bitscan_alerts_total{kind}, in its
own registry so a later metrics route can serve exactly this (#5: no route in
M2)."""

from typing import Final

from prometheus_client import CollectorRegistry, Counter

REGISTRY: Final = CollectorRegistry()

ALERTS_TOTAL: Final = Counter(
    "bitscan_alerts",
    "Alerts raised, by kind (every alert is also an audit entry).",
    ["kind"],
    registry=REGISTRY,
)
