"""TASK-079: scrape() unit check (REQ-086 (2), TS §8.4 L1288).

The agents-by-status gauge must equal the database counts at every scrape,
including a status whose count fell to zero since the last scrape (a stale
gauge value would otherwise stay in the registry).
"""

from prometheus_client.parser import text_string_to_metric_families

from bitscan_manager.services.audit.metrics import scrape

STATUSES = (
    "awaiting_approval",
    "enrolled",
    "online",
    "stale",
    "offline",
    "decommissioned",
)


class Agents:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def count_by_status(self) -> dict[str, int]:
        return self.counts


class Jobs:
    def __init__(self, n: int) -> None:
        self.n = n

    def count_queued(self) -> int:
        return self.n


def gauges(body: bytes) -> dict[str, float]:
    out: dict[str, float] = {}
    for fam in text_string_to_metric_families(body.decode()):
        for s in fam.samples:
            if s.name == "bitscan_agents":
                out[s.labels["status"]] = s.value
            if s.name == "bitscan_jobs_queued":
                out["queued"] = s.value
    return out


def test_every_status_is_exported_and_falls_back_to_zero() -> None:
    first = gauges(scrape(Agents({"online": 7, "offline": 2}), Jobs(4)))
    assert {k: first[k] for k in STATUSES} == {
        "awaiting_approval": 0,
        "enrolled": 0,
        "online": 7,
        "stale": 0,
        "offline": 2,
        "decommissioned": 0,
    }
    assert first["queued"] == 4
    second = gauges(scrape(Agents({"stale": 3}), Jobs(0)))
    assert second["online"] == 0 and second["offline"] == 0 and second["stale"] == 3
    assert second["queued"] == 0
