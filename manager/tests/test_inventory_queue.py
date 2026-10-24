"""TASK-061: inventory queueing service, unit half (fake queue).

Checks CHK-M3-143 (pickup window), CHK-M3-145 (nothing skips a run) and
CHK-M3-146 (no network client in the scheduler package) of tests/m3/test-plan.md
(TP-M3-15). The PostgreSQL half is tests/test_inventory_queue_pg.py. Expected
values: TS §4.4 L566 (pickup_by = creation + 24 h), TS §3.4 L230, L237 and §6.2
L1129 (no way to disable or skip inventory), REQ-080 (5), REQ-088 (3).
"""

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from bitscan_manager.services import scheduler
from bitscan_manager.services.scheduler import (
    PICKUP_WINDOW,
    InventoryQueue,
    queue_first_inventory,
    run_inventory,
)

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
CLIENTS = {"httpx", "requests", "urllib", "http", "socket", "aiohttp", "ssl", "urllib3"}


class FakeQueue:
    def __init__(self, result: list[UUID]) -> None:
        self.result = result
        self.calls: list[tuple[datetime, datetime, UUID | None]] = []

    def queue_inventory(
        self, now: datetime, pickup_by: datetime, agent_id: UUID | None = None
    ) -> list[UUID]:
        self.calls.append((now, pickup_by, agent_id))
        return list(self.result)


def test_pickup_window_is_24_hours() -> None:
    assert PICKUP_WINDOW == timedelta(hours=24)


def test_run_queues_fleet_wide_with_pickup_now_plus_24h() -> None:
    ids = [uuid4(), uuid4()]
    q = FakeQueue(ids)
    jobs: InventoryQueue = q
    assert run_inventory(jobs, T0) == ids
    assert q.calls == [(T0, T0 + timedelta(hours=24), None)]


def test_first_inventory_is_for_one_agent() -> None:
    agent = uuid4()
    jid = uuid4()
    q = FakeQueue([jid])
    assert queue_first_inventory(q, agent, T0) == jid
    assert q.calls == [(T0, T0 + timedelta(hours=24), agent)]
    assert queue_first_inventory(FakeQueue([]), agent, T0) is None


def test_no_parameter_can_skip_or_disable_a_run() -> None:
    """CHK-M3-145, REQ-088 (2): the entry points take nothing but the queue,
    the agent (first job) and the time."""
    assert list(inspect.signature(run_inventory).parameters) == ["jobs", "now"]
    assert list(inspect.signature(queue_first_inventory).parameters) == [
        "jobs",
        "agent_id",
        "now",
    ]
    pkg = Path(scheduler.__file__).resolve().parent
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                low = node.value.lower()
                if "inventory" in low and ("enabled" in low or "disable" in low):
                    # docstrings may say that nothing disables it; keys may not
                    assert " " in low, (path.name, node.value)


def test_scheduler_package_opens_no_network_client() -> None:
    """CHK-M3-146, REQ-080 (5), REQ-088 (3): only the caller's transaction."""
    pkg = Path(scheduler.__file__).resolve().parent
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in CLIENTS, (path.name, name)
