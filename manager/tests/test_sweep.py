"""TASK-065: offline_sweep orchestration with fakes (unit half of TP-M3-19).

The database behaviour is tests/test_sweep_pg.py; this file checks, without
PostgreSQL, what run_sweep asks of its stores: the TS §3.3 L218 thresholds
(10 and 30 minutes), the TS §3.4 L244 30-minute inventory window, the setting
for decommission (0 = never, TS §3.3 L220), one audit entry per decommissioned
agent (#73 (d)), the jobs-expired metric only on commit (REQ-086 (2)) and one
transaction per step (REQ-078 (5)).
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.scheduler.sweep import Stores, run_sweep

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEEDED = {
    "agent_token_ttl_days": 365,
    "job_pull_seconds": 300,
    "decommission_after_days": 7,
    "redaction_patterns": [],
    "max_parallel_plugins": 2,
    "enrolment_alert_per_hour": 50,
}


def expired_counted() -> float:
    return REGISTRY.get_sample_value("bitscan_jobs_expired_total") or 0.0


@dataclass
class FakeTx:
    hooks: list[Callable[[], None]] = field(default_factory=list)

    @property
    def conn(self) -> Any:
        raise AssertionError("the sweep reaches the database only through stores")

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


@dataclass
class FakeDb:
    commits: int = 0
    rollbacks: int = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        tx = FakeTx()
        try:
            yield tx
        except BaseException:
            self.rollbacks += 1
            raise
        self.commits += 1
        for hook in tx.hooks:
            hook()


@dataclass
class World:
    days: int = 7
    decommissioned: list[UUID] = field(default_factory=lambda: [uuid4(), uuid4()])
    expired: int = 2
    raise_in: str | None = None
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    entries: list[tuple[str, str, str, dict[str, object]]] = field(default_factory=list)

    def _maybe(self, name: str) -> None:
        if self.raise_in == name:
            raise RuntimeError("CANARY-0011223344556677")

    # agents
    def apply_heartbeat_ages(
        self, now: datetime, stale_after: timedelta, offline_after: timedelta
    ) -> int:
        self.calls.append(("ages", now, stale_after, offline_after))
        self._maybe("statuses")
        return 5

    def decommission_offline(self, now: datetime, after: timedelta) -> list[UUID]:
        self.calls.append(("decommission", now, after))
        self._maybe("decommission")
        return list(self.decommissioned)

    # jobs
    def expire_past_pickup(self, now: datetime) -> int:
        self.calls.append(("expire", now))
        self._maybe("expire")
        return self.expired

    def fail_dispatched_inventory(
        self, dispatched_before: datetime, now: datetime
    ) -> int:
        self.calls.append(("timeout", dispatched_before, now))
        self._maybe("inventory_timeout")
        return 1

    # settings
    def read_values(self) -> Mapping[str, Any]:
        return SEEDED | {"decommission_after_days": self.days}

    def schedule_interval(self, job_kind: str) -> int | None:
        return 21600 if job_kind == "inventory" else 60

    # audit
    def audit(
        self, actor: str, action: str, target: str, detail: Mapping[str, object]
    ) -> None:
        self.entries.append((actor, action, target, dict(detail)))

    def stores(self, tx: Any) -> Stores:
        return Stores(tx, self, self, self, self)


def test_one_sweep_asks_for_the_spec_thresholds() -> None:
    w, db = World(), FakeDb()
    counted = expired_counted()
    got = run_sweep(db, NOW, stores=w.stores)  # type: ignore[arg-type]
    assert w.calls == [
        ("ages", NOW, timedelta(minutes=10), timedelta(minutes=30)),
        ("decommission", NOW, timedelta(days=7)),
        ("expire", NOW),
        ("timeout", NOW - timedelta(minutes=30), NOW),
    ]
    assert (db.commits, db.rollbacks) == (4, 0)
    assert (got.statuses_changed, got.decommissioned, got.expired) == (5, 2, 2)
    assert (got.inventory_failed, got.failed_steps) == (1, [])
    assert w.entries == [
        ("system", "agent.decommission", f"agent:{a}", {"after_days": 7})
        for a in w.decommissioned
    ]
    assert expired_counted() == counted + 2


def test_zero_days_never_calls_decommission() -> None:
    w, db = World(days=0), FakeDb()
    got = run_sweep(db, NOW, stores=w.stores)  # type: ignore[arg-type]
    assert [c[0] for c in w.calls] == ["ages", "expire", "timeout"]
    assert w.entries == [] and got.decommissioned == 0


@pytest.mark.parametrize(
    "step", ["statuses", "decommission", "expire", "inventory_timeout"]
)
def test_one_failing_step_rolls_back_alone(
    step: str, caplog: pytest.LogCaptureFixture
) -> None:
    w, db = World(raise_in=step), FakeDb()
    counted = expired_counted()
    got = run_sweep(db, NOW, stores=w.stores)  # type: ignore[arg-type]
    assert got.failed_steps == [step]
    assert (db.commits, db.rollbacks) == (3, 1)
    assert len(w.calls) == 4  # every step was still attempted
    assert expired_counted() == counted + (0 if step == "expire" else 2)
    if step == "decommission":
        assert w.entries == []
    [record] = [r for r in caplog.records if r.getMessage() == "sweep step failed"]
    assert getattr(record, "data", None) == {"step": step, "exc_type": "RuntimeError"}
    assert all("CANARY" not in repr(vars(r)) for r in caplog.records)


def test_nothing_expired_counts_nothing() -> None:
    w, db = World(expired=0, decommissioned=[]), FakeDb()
    counted = expired_counted()
    run_sweep(db, NOW, stores=w.stores)  # type: ignore[arg-type]
    assert expired_counted() == counted
    assert w.entries == []
