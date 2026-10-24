"""G5 unit half (no PostgreSQL) for the fleet services: heartbeat, tags and
revoke, job pull and the results refusal, the fleet threshold alerts and the
settings patch, each driven through its Protocol seams with fakes and a
fixed clock.

The database behaviour is in test_heartbeat_api_pg.py,
test_agents_admin_api_pg.py, test_jobs_api_pg.py, test_fleet_alerts_pg.py and
test_settings_api_pg.py; this file asserts the same outcomes at the service
boundary. Expected values come from the spec and the answers: TS §3.3 L202
(configuration-only heartbeat answer), §3.7 L484 (helper change audited and
alerted), §6.5 L1163 (skew over 5 minutes alerts), §6.2 L1112-L1113 (tags,
revoke), §6.1 L1064, L1071 (pull; 409 audit-logged), §8.4 L1291 (offline
share, queue age, 409 floods), §3.4 L242 (stale inventory), §5.3 L1047
(default partition), §8.6 (settings, removed default alerts), #25 (a), #54 (c),
#65, #66, #71, #73 and the lead ruling that a window is marked only on commit.
"""

import importlib
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.services.agents import admin as admin_mod
from bitscan_manager.services.agents import fleet as fleet_mod
from bitscan_manager.services.audit.thresholds import OncePerPeriod, SlidingCount
from bitscan_manager.services.jobs import pull as pull_mod
from bitscan_manager.services.scheduler.fleet_alerts import FleetAlerts, FleetStores
from bitscan_manager.services.settings import store as store_mod
from bitscan_manager.services.settings.redaction import DEFAULT_PATTERNS

from .test_enrolment_services_unit import NOW, SEEDED, Audit, Clock, Settings, agent_row

# the package re-exports a function named heartbeat, so take the module itself
hb_mod = importlib.import_module("bitscan_manager.services.agents.heartbeat")

# ----------------------------------------------------------------- heartbeat


@dataclass
class BeatAgents:
    row: AgentRow | None
    recorded: list[tuple[UUID, datetime, str, list[str]]] = field(default_factory=list)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        assert lock is True
        return self.row

    def record_heartbeat(
        self, agent_id: UUID, now: datetime, agent_version: str, helpers: list[str]
    ) -> bool:
        self.recorded.append((agent_id, now, agent_version, helpers))
        return True


@dataclass
class BeatWorld:
    row: AgentRow = field(default_factory=lambda: agent_row(runner_helpers=[]))
    clock: Clock = field(default_factory=Clock)
    settings: Settings = field(default_factory=Settings)
    audit: Audit = field(default_factory=Audit)
    hooks: list[Callable[[], None]] = field(default_factory=list)
    skew: OncePerPeriod[UUID] = field(init=False)
    agents: BeatAgents = field(init=False)

    def __post_init__(self) -> None:
        self.skew = OncePerPeriod(self.clock, timedelta(hours=1))
        self.agents = BeatAgents(self.row)

    def beat(
        self,
        offset: timedelta = timedelta(0),
        helpers: list[str] | None = None,
        **kw: Any,
    ) -> Any:
        b = hb_mod.Beat(
            kw.get("version", "1.1.0"),
            [] if helpers is None else helpers,
            self.clock.now() + offset,
            kw.get("last_error"),
        )
        return hb_mod.heartbeat(
            self.agents,
            self.settings,
            self.audit,
            self.skew,
            self.hooks.append,
            agent_id=self.row.agent_id,
            beat=b,
            now=self.clock.now(),
        )

    def commit(self) -> None:
        for hook in self.hooks:
            hook()
        self.hooks.clear()


def test_heartbeat_answers_only_the_current_configuration() -> None:
    w = BeatWorld()
    w.settings.values |= {"job_pull_seconds": 120, "max_parallel_plugins": 4}
    out = w.beat(version="1.2.0")
    assert out == hb_mod.HeartbeatAnswer(120, 4, NOW)
    assert w.agents.recorded == [(w.row.agent_id, NOW, "1.2.0", [])]
    assert w.audit.alerts == [] and w.audit.entries == []


def test_a_helper_change_alerts_with_old_and_new() -> None:
    """TS §3.7 L484: one runner_helper_changed entry per change; the same
    set in another order is no change."""
    w = BeatWorld(row=agent_row(runner_helpers=["capread"]))
    w.beat(helpers=["capread"])
    assert w.audit.alerts == []
    w.beat(helpers=[])
    actor = f"agent:{w.row.agent_id}"
    assert w.audit.alerts == [
        (
            "runner_helper_changed",
            actor,
            "agent.runner_helpers_change",
            actor,
            {"old": ["capread"], "new": []},
        )
    ]


@pytest.mark.parametrize(
    ("offset", "alerts"),
    [
        (timedelta(minutes=5), False),
        (-timedelta(minutes=5), False),
        (timedelta(minutes=5, seconds=1), True),
        (-timedelta(minutes=5, seconds=1), True),
        (timedelta(hours=3), True),
    ],
)
def test_clock_skew_over_5_minutes_alerts(offset: timedelta, alerts: bool) -> None:
    w = BeatWorld()
    w.beat(offset)
    assert w.audit.kinds() == (["clock_skew"] if alerts else [])
    if alerts:
        detail = w.audit.alerts[0][4]
        assert detail == {
            "agent_clock": (NOW + offset).isoformat(),
            "server_time": NOW.isoformat(),
            "skew_s": round(offset.total_seconds(), 3),
        }


def test_clock_skew_once_per_agent_per_hour_marked_on_commit() -> None:
    """#65: once per agent per hour while it lasts; a rolled-back alert
    leaves the hour free."""
    w = BeatWorld()
    late = timedelta(minutes=6)
    w.beat(late)
    w.hooks.clear()  # rolled back
    w.beat(late)
    assert w.audit.kinds() == ["clock_skew", "clock_skew"]
    w.commit()
    w.clock.at += timedelta(minutes=59)
    w.beat(late)
    assert len(w.audit.alerts) == 2
    w.clock.at += timedelta(minutes=2)
    w.beat(late)
    assert len(w.audit.alerts) == 3


def test_last_error_goes_to_one_info_record_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#25 (a): last_error is logged at INFO, never audited."""
    w = BeatWorld()
    with caplog.at_level(logging.INFO, logger="bitscan_manager.agents"):
        w.beat(last_error="runner down CANARY-hb-1")
        w.beat()
    recs = [r for r in caplog.records if "CANARY-hb-1" in str(getattr(r, "data", ""))]
    assert len(recs) == 1 and recs[0].levelno == logging.INFO
    assert w.audit.entries == [] and w.audit.alerts == []


def test_heartbeat_of_a_vanished_agent() -> None:
    w = BeatWorld()
    w.agents.row = None
    with pytest.raises(hb_mod.AgentGone):
        w.beat()
    assert w.agents.recorded == []


# ------------------------------------------------------------- fleet reads


ITEM: Any = object()
OS: Any = object()
SNAP: Any = object()
PKG: Any = object()


@dataclass
class FleetAgentsFake:
    row: AgentRow | None
    pages: list[Any] = field(default_factory=list)

    def list_page(self, limit: int, after: Any) -> list[Any]:
        self.pages.append((limit, after))
        return [ITEM]

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        return self.row

    def tags(self, agent_id: UUID) -> list[str]:
        return ["db", "prod"]


@dataclass
class FleetInventoryFake:
    asked: list[Any] = field(default_factory=list)

    def get_os_info(self, agent_id: UUID) -> Any:
        return OS

    def latest_snapshot(self, agent_id: UUID) -> Any:
        return SNAP

    def package_page(self, agent_id: UUID, limit: int | None, after: Any) -> list[Any]:
        self.asked.append((agent_id, limit, after))
        return [PKG]


def test_fleet_reads() -> None:
    """#68, #69: detail joins tags, os_info and the latest snapshot; an
    unknown agent is None for detail and packages."""
    a = agent_row()
    agents, inv = FleetAgentsFake(a), FleetInventoryFake()
    assert fleet_mod.list_agents(agents, 50, None) == [ITEM]
    d = fleet_mod.agent_detail(agents, inv, a.agent_id)
    assert d is not None
    assert (d.agent, d.tags, d.os_info, d.last_snapshot) == (
        a,
        ["db", "prod"],
        OS,
        SNAP,
    )
    assert fleet_mod.agent_packages(agents, inv, a.agent_id, 2, None) == [PKG]
    assert inv.asked == [(a.agent_id, 2, None)]
    gone = FleetAgentsFake(None)
    assert fleet_mod.agent_detail(gone, inv, a.agent_id) is None
    assert fleet_mod.agent_packages(gone, inv, a.agent_id, 2, None) is None
    assert len(inv.asked) == 1


# ------------------------------------------------------------ tags, revoke


@dataclass
class AdminAgents:
    row: AgentRow | None
    current: list[str] = field(default_factory=lambda: ["old"])
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        assert lock is True
        return self.row

    def tags(self, agent_id: UUID) -> list[str]:
        return sorted(self.current)

    def replace_tags(self, agent_id: UUID, tags: list[str]) -> None:
        self.calls.append(("tags", tags))
        self.current = list(tags)

    def revoke(self, agent_id: UUID, now: datetime) -> bool:
        self.calls.append(("revoke", now))
        return True


@pytest.mark.parametrize(
    "tags",
    [
        [f"t{i}" for i in range(33)],
        ["a", "a"],
        [""],
        ["x" * 65],
        ["a b"],
        ["prod/web"],
        ["é"],
    ],
)
def test_bad_tags_refused_before_anything_is_written(tags: list[str]) -> None:
    agents, audit = AdminAgents(agent_row()), Audit()
    with pytest.raises(admin_mod.InvalidTags):
        admin_mod.set_tags(agents, audit, agent_id=uuid4(), tags=tags, user_id=1)
    assert agents.calls == [] and audit.entries == []


def test_set_tags_replaces_and_audits_old_and_new() -> None:
    a = agent_row()
    agents, audit = AdminAgents(a), Audit()
    limit = [f"t{i}" for i in range(31)] + ["A.b_c:d-" + "x" * 56]
    out = admin_mod.set_tags(agents, audit, agent_id=a.agent_id, tags=limit, user_id=6)
    assert agents.calls == [("tags", limit)] and out == sorted(limit)
    assert audit.entries == [
        (
            "user:6",
            "agent.tags_set",
            f"agent:{a.agent_id}",
            {"old": ["old"], "new": sorted(limit)},
        )
    ]
    admin_mod.set_tags(agents, audit, agent_id=a.agent_id, tags=[], user_id=6)
    assert agents.current == [] and audit.entries[-1][3]["new"] == []


def test_tags_and_revoke_of_an_unknown_agent() -> None:
    agents, audit = AdminAgents(None), Audit()
    with pytest.raises(admin_mod.AgentNotFound):
        admin_mod.set_tags(agents, audit, agent_id=uuid4(), tags=["a"], user_id=1)
    with pytest.raises(admin_mod.AgentNotFound):
        admin_mod.revoke_agent(agents, audit, agent_id=uuid4(), user_id=1, now=NOW)
    assert agents.calls == [] and audit.entries == []


def test_revoke_once() -> None:
    """TS §6.2 L1113: the token is revoked with one entry; an already revoked
    token keeps its revoked_at and writes nothing."""
    a = agent_row()
    agents, audit = AdminAgents(a), Audit()
    admin_mod.revoke_agent(agents, audit, agent_id=a.agent_id, user_id=2, now=NOW)
    assert agents.calls == [("revoke", NOW)]
    assert audit.entries == [("user:2", "agent.revoke", f"agent:{a.agent_id}", {})]
    done = AdminAgents(agent_row(token_revoked_at=NOW - timedelta(days=1)))
    admin_mod.revoke_agent(done, audit, agent_id=a.agent_id, user_id=2, now=NOW)
    assert done.calls == [] and len(audit.entries) == 1


# ---------------------------------------------------------- pull, results


@dataclass
class Puller:
    asked: list[tuple[UUID, datetime]] = field(default_factory=list)

    def pull(self, agent_id: UUID, now: datetime) -> list[dict[str, Any]]:
        self.asked.append((agent_id, now))
        return [{"job_id": "j", "agent_id": str(agent_id), "kind": "inventory"}]


def test_pull_returns_the_repository_payloads_for_this_agent() -> None:
    a, p = uuid4(), Puller()
    assert pull_mod.pull_jobs(p, a, NOW) == [
        {"job_id": "j", "agent_id": str(a), "kind": "inventory"}
    ]
    assert p.asked == [(a, NOW)]


@dataclass
class FloodWorld:
    clock: Clock = field(default_factory=Clock)
    audit: Audit = field(default_factory=Audit)
    hooks: list[Callable[[], None]] = field(default_factory=list)
    flood: SlidingCount[UUID] = field(init=False)

    def __post_init__(self) -> None:
        self.flood = SlidingCount(
            self.clock, timedelta(minutes=10), timedelta(hours=1), 20
        )

    def refuse(self, agent: UUID, reason: str = "job_not_acceptable") -> None:
        pull_mod.refuse_results(
            self.audit,
            self.flood,
            self.hooks.append,
            agent_id=agent,
            job_id=UUID(int=3),
            reason=reason,
            detail={"final": True},
        )

    def commit(self) -> None:
        for hook in self.hooks:
            hook()
        self.hooks.clear()


def test_each_refused_result_writes_one_entry() -> None:
    w, a = FloodWorld(), uuid4()
    w.refuse(a)
    assert w.audit.entries == [
        (
            f"agent:{a}",
            "agent.result_refused",
            f"job:{UUID(int=3)}",
            {"reason": "job_not_acceptable", "final": True},
        )
    ]


def test_the_21st_409_in_10_minutes_alerts_once_an_hour() -> None:
    """#54 (c), #65 (f): more than 20 in 10 minutes from one agent; once per
    agent per hour, marked on commit; too_large never counts."""
    w, a = FloodWorld(), uuid4()
    for _ in range(30):
        w.refuse(a, "too_large")
    for _ in range(20):
        w.refuse(a)
        w.commit()
    assert w.audit.alerts == []
    w.refuse(a)
    actor = f"agent:{a}"
    assert w.audit.alerts == [
        (
            "result_409_flood",
            actor,
            "alert.result_409_flood",
            actor,
            {"over_per_10_min": 20},
        )
    ]
    w.hooks.clear()  # rolled back
    w.refuse(a)
    w.commit()
    w.refuse(a)
    w.commit()
    assert len(w.audit.alerts) == 2
    other = uuid4()
    for _ in range(20):
        w.refuse(other)
    assert len(w.audit.alerts) == 2
    assert len(w.audit.entries) == 30 + 20 + 3 + 20


# ---------------------------------------------------------- fleet alerts


@dataclass
class FakeTx:
    hooks: list[Callable[[], None]] = field(default_factory=list)

    @property
    def conn(self) -> Any:
        raise AssertionError("fleet alerts reach the database only through stores")

    def on_commit(self, hook: Callable[[], None]) -> None:
        self.hooks.append(hook)


@dataclass
class FakeDb:
    fail_commit: bool = False
    commits: int = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeTx]:
        tx = FakeTx()
        yield tx
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.commits += 1
        for hook in tx.hooks:
            hook()


@dataclass
class Fleet:
    counts: dict[str, int] = field(default_factory=dict)
    stale: list[UUID] = field(default_factory=list)
    oldest: datetime | None = None
    partition: bool = False
    raise_in: str | None = None
    asked_stale: list[tuple[datetime, timedelta]] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)
    audit: Audit = field(default_factory=Audit)

    def count_by_status(self) -> Mapping[str, int]:
        if self.raise_in == "offline":
            raise RuntimeError("boom")
        return self.counts

    def stale_inventory(self, now: datetime, older_than: timedelta) -> list[UUID]:
        self.asked_stale.append((now, older_than))
        return list(self.stale)

    def oldest_queued_for_online(self) -> datetime | None:
        return self.oldest

    def default_partition_has_rows(self) -> bool:
        return self.partition

    def stores(self, tx: Any) -> FleetStores:
        return FleetStores(tx, self, self, self.settings, self.audit)


def run(
    alerts: FleetAlerts, f: Fleet, db: FakeDb | None = None, at: datetime = NOW
) -> list[str]:
    return alerts.run(db or FakeDb(), at, f.stores)  # type: ignore[arg-type]


def offline(n: int, of: int, **extra: int) -> dict[str, int]:
    return {"offline": n, "online": of - n, **extra}


def test_offline_share_above_5_percent_alerts_and_rearms() -> None:
    """TS §8.4 L1291, #65 (b): 5 of 100 is nothing, 6 of 100 alerts once;
    again only after the share went back to 5 % or below. Decommissioned and
    awaiting-approval agents are not counted."""
    clock, f = Clock(), Fleet()
    alerts = FleetAlerts(clock)
    f.counts = offline(5, 100, decommissioned=50, awaiting_approval=50)
    assert run(alerts, f) == [] and f.audit.alerts == []
    f.counts = offline(6, 100, decommissioned=50)
    run(alerts, f)
    assert f.audit.alerts == [
        (
            "agents_offline",
            "system",
            "alert.agents_offline",
            "fleet",
            {"offline": 6, "eligible": 100, "over_share": 0.05},
        )
    ]
    run(alerts, f)
    assert len(f.audit.alerts) == 1
    f.counts = offline(5, 100)
    run(alerts, f)
    f.counts = offline(6, 100)
    run(alerts, f)
    assert f.audit.kinds() == ["agents_offline", "agents_offline"]


def test_no_eligible_agents_is_no_alert() -> None:
    f = Fleet(counts={"decommissioned": 3, "awaiting_approval": 1})
    run(FleetAlerts(Clock()), f)
    assert f.audit.alerts == []


def test_queue_age_over_one_hour_at_most_once_an_hour() -> None:
    """TS §8.4 L1291, #66: the oldest queued job of an online agent older than
    1 h alerts, at most once per hour."""
    clock, f = Clock(), Fleet()
    alerts = FleetAlerts(clock)
    f.oldest = NOW - timedelta(hours=1)
    run(alerts, f)
    assert f.audit.alerts == []
    f.oldest = NOW - timedelta(hours=1, seconds=1)
    run(alerts, f)
    assert f.audit.alerts == [
        (
            "job_queue_age",
            "system",
            "alert.job_queue_age",
            "fleet",
            {"oldest_age_s": 3601},
        )
    ]
    clock.at += timedelta(minutes=59)
    run(alerts, f, at=clock.at)
    assert len(f.audit.alerts) == 1
    clock.at += timedelta(minutes=2)
    run(alerts, f, at=clock.at)
    assert len(f.audit.alerts) == 2


def test_stale_inventory_once_per_agent_until_it_uploads() -> None:
    """TS §3.4 L242, #65 (c): older than 2 x interval; one entry per agent;
    again only after the agent left the stale list."""
    f = Fleet()
    f.settings.interval = 7200
    alerts = FleetAlerts(Clock())
    a, b = uuid4(), uuid4()
    f.stale = [a, b]
    run(alerts, f)
    assert f.asked_stale == [(NOW, timedelta(seconds=14400))]
    assert sorted(x[3] for x in f.audit.alerts) == sorted([f"agent:{a}", f"agent:{b}"])
    assert {x[4]["older_than_s"] for x in f.audit.alerts} == {14400}
    run(alerts, f)
    assert len(f.audit.alerts) == 2
    f.stale = [b]
    run(alerts, f)
    f.stale = [a, b]
    run(alerts, f)
    assert [x[3] for x in f.audit.alerts[2:]] == [f"agent:{a}"]


def test_default_partition_rows_alert_again_only_after_it_emptied() -> None:
    """§5.3 L1047, #65 (g)."""
    f, alerts = Fleet(), FleetAlerts(Clock())
    run(alerts, f)
    f.partition = True
    run(alerts, f)
    run(alerts, f)
    assert f.audit.alerts == [
        (
            "default_partition_rows",
            "system",
            "alert.default_partition_rows",
            "scan_result_default",
            {},
        )
    ]
    f.partition = False
    run(alerts, f)
    f.partition = True
    run(alerts, f)
    assert f.audit.kinds() == ["default_partition_rows"] * 2


def test_a_failing_check_is_named_and_the_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    f = Fleet(raise_in="offline", partition=True, oldest=NOW - timedelta(hours=2))
    with caplog.at_level(logging.ERROR, logger="bitscan_manager.scheduler"):
        failed = run(FleetAlerts(Clock()), f)
    assert failed == ["agents_offline"]
    assert sorted(f.audit.kinds()) == ["default_partition_rows", "job_queue_age"]
    rec = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(rec) == 1
    assert getattr(rec[0], "data", None) == {
        "check": "agents_offline",
        "exc_type": "RuntimeError",
    }
    assert "boom" not in caplog.text


def test_a_failed_commit_leaves_every_window_free() -> None:
    """Decisions 2026-10-23: the slot is taken only once the alert committed,
    so the next run alerts again."""
    f = Fleet(counts=offline(10, 100), oldest=NOW - timedelta(hours=2), partition=True)
    f.stale = [uuid4()]
    alerts = FleetAlerts(Clock())
    failed = run(alerts, f, FakeDb(fail_commit=True))
    assert len(failed) == 4
    first = len(f.audit.alerts)
    assert first == 4
    run(alerts, f)
    assert len(f.audit.alerts) == 8
    run(alerts, f)
    assert len(f.audit.alerts) == 8


# ------------------------------------------------------------ settings patch


@dataclass
class SettingsStore:
    values: dict[str, Any] = field(
        default_factory=lambda: SEEDED | {"redaction_patterns": list(DEFAULT_PATTERNS)}
    )
    interval: int = 21600
    locked: int = 0
    writes: list[tuple[Any, ...]] = field(default_factory=list)
    refuse: str | None = None

    def read_values(self) -> Mapping[str, Any]:
        return dict(self.values)

    def schedule_interval(self, job_kind: str) -> int | None:
        return self.interval if job_kind == "inventory" else 60

    def lock_settings(self) -> None:
        self.locked += 1

    def write_value(
        self, key: str, value: object, updated_by: int | None, now: datetime
    ) -> bool:
        self.writes.append(("setting", key, value, updated_by, now))
        if key == self.refuse:
            return False
        self.values[key] = value
        return True

    def write_schedule_interval(self, job_kind: str, interval_s: int) -> bool:
        self.writes.append(("schedule", job_kind, interval_s))
        if self.refuse == "inventory_interval_s":
            return False
        self.interval = interval_s
        return True


def patch(store: SettingsStore, audit: Audit, body: Mapping[str, object]) -> Any:
    return store_mod.apply_patch(store, audit, patch=body, user_id=8, now=NOW)


def test_patch_writes_each_key_and_alerts_once_with_old_and_new() -> None:
    """TS §8.6: every change audit-logged; #71: one settings_changed entry;
    inventory_interval_s goes to system_schedule."""
    store, audit = SettingsStore(), Audit()
    out = patch(store, audit, {"job_pull_seconds": 120, "inventory_interval_s": 3600})
    assert store.locked == 1
    assert sorted(store.writes, key=str) == sorted(
        [("setting", "job_pull_seconds", 120, 8, NOW), ("schedule", "inventory", 3600)],
        key=str,
    )
    assert (out.job_pull_seconds, out.inventory_interval_s) == (120, 3600)
    assert audit.alerts == [
        (
            "settings_changed",
            "user:8",
            "settings.change",
            "settings",
            {
                "old": {"job_pull_seconds": 300, "inventory_interval_s": 21600},
                "new": {"job_pull_seconds": 120, "inventory_interval_s": 3600},
            },
        )
    ]


def test_an_invalid_patch_writes_nothing() -> None:
    store, audit = SettingsStore(), Audit()
    with pytest.raises(store_mod.SettingsInvalid):
        patch(store, audit, {"job_pull_seconds": 120, "inventory_enabled": False})
    assert store.locked == 0 and store.writes == [] and audit.alerts == []


@pytest.mark.parametrize("key", ["job_pull_seconds", "inventory_interval_s"])
def test_a_missing_row_on_write_is_unavailable(key: str) -> None:
    store, audit = SettingsStore(refuse=key), Audit()
    value = 3600 if key == "inventory_interval_s" else 120
    with pytest.raises(store_mod.SettingsUnavailable):
        patch(store, audit, {key: value})
    assert audit.alerts == []


def test_removing_a_default_pattern_alerts_once() -> None:
    """TS §8.6 L1324: removing a default alerts redaction_default_removed
    (besides settings_changed); adding a pattern does not."""
    store, audit = SettingsStore(), Audit()
    kept = list(DEFAULT_PATTERNS[1:]) + [r"\bcorp-[0-9]{6}\b"]
    patch(store, audit, {"redaction_patterns": kept})
    assert audit.kinds() == ["settings_changed", "redaction_default_removed"]
    assert audit.alerts[1][4] == {"removed": [DEFAULT_PATTERNS[0]]}
    patch(store, audit, {"redaction_patterns": kept + [r"x{3}"]})
    assert audit.kinds()[2:] == ["settings_changed"]


@pytest.mark.parametrize(
    "stored",
    [
        {"job_pull_seconds": "300"},
        {"job_pull_seconds": True},
        {"redaction_patterns": "x"},
        {"redaction_patterns": [1]},
    ],
)
def test_corrupt_stored_values_are_unavailable(stored: dict[str, Any]) -> None:
    s = Settings()
    s.values |= stored
    with pytest.raises(store_mod.SettingsUnavailable):
        store_mod.read_settings(s)


def test_patterns_that_cannot_be_stored_or_compiled_are_refused() -> None:
    for bad in ("a\x00b", "\ud800", "(unclosed"):
        with pytest.raises(store_mod.SettingsInvalid):
            store_mod.validate_patch({"redaction_patterns": [bad]})
    assert store_mod.validate_patch({"redaction_patterns": ["ok+"]}) == {
        "redaction_patterns": ["ok+"]
    }
