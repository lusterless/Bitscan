"""TASK-064: inventory ingestion with fake stores (TP-M3-18, unit half).

Checks CHK-M3-170 to CHK-M3-175 of tests/m3/test-plan.md without PostgreSQL
(the database half is tests/test_inventory_ingest_pg.py). Expected values come
from the spec and the answered questions, not from the code: TS §3.4 L241
(every upload replaces os_info and sets last_inventory_at; when list_sha256
differs from the last snapshot, upsert agent_package, delete rows no longer
listed, write a snapshot of what was added and removed), L242 (more than
1,000 previously unseen packages in a day alerts), #60 (an empty source is
stored as NULL), #65 (e) (new to the fleet = package rows the agent's uploads
created, rolling 24 h, once per agent per 24 h), #69 (diff on the four
list_sha256 fields, an upgrade or status change is the old line in removed and
the new line in added, the first snapshot lists everything in added,
collected_at = receive time), #71 (alert kind new_packages_burst, action
alert.new_packages_burst, actor agent:<id>, no package list in detail), and
the carry-over: an agent revoked since its token check writes nothing.
"""

import gzip
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories.agents import AgentRow
from bitscan_manager.repositories.inventory import (
    AgentPackageRow,
    OsInfoRow,
    PackageIds,
    PackageRow,
    SnapshotRow,
)
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.inventory.decode import DecodedInventory, decode_inventory
from bitscan_manager.services.inventory.ingest import (
    NEW_PACKAGES_PER_DAY,
    AgentGone,
    IngestResult,
    ingest,
)

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
INSTALLED = "install ok installed"

Pkg = tuple[str, str, str, str, str, int | None]  # name, ver, arch, status, src, kb


# ------------------------------------------------------------ builders


def oracle_sha256(pkgs: Sequence[Pkg]) -> str:
    """TS §6.5 L1186, #33: sorted UTF-8 lines name\\tversion\\tarch\\tstatus\\n."""
    lines = sorted(f"{n}\t{v}\t{a}\t{s}\n".encode() for n, v, a, s, _, _ in pkgs)
    return hashlib.sha256(b"".join(lines)).hexdigest()


def os_info(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "os_pretty_name": "Ubuntu 24.04.1 LTS",
        "kernel_release": "6.8.0-45-generic",
        "architecture": "x86_64",
        "cpu_count": 4,
        "memory_mb": 7962,
        "ip_addresses": ["10.0.0.5", "fe80::1"],
        "uptime_s": 12345,
        "raw": {"os-release": {"ID": "ubuntu"}, "nproc": 4},
    }
    base.update(over)
    return base


def body(pkgs: Sequence[Pkg], **os_over: Any) -> bytes:
    doc = {
        "os_info": os_info(**os_over),
        "packages": [
            {
                "name": n,
                "version": v,
                "architecture": a,
                "status": s,
                "source": src,
                "installed_size_kb": kb,
            }
            for n, v, a, s, src, kb in pkgs
        ],
        "list_sha256": oracle_sha256(pkgs),
    }
    return gzip.compress(json.dumps(doc).encode())


def decoded(pkgs: Sequence[Pkg], **os_over: Any) -> DecodedInventory:
    """A real decoder result, so ingest sees exactly what TASK-074 hands it."""
    return decode_inventory(body(pkgs, **os_over))


def pkg(
    name: str,
    version: str = "1.0-1",
    arch: str = "amd64",
    status: str = INSTALLED,
    source: str = "",
    kb: int | None = 10,
) -> Pkg:
    return (name, version, arch, status, source, kb)


def many(prefix: str, n: int) -> list[Pkg]:
    return [pkg(f"{prefix}{i:05d}") for i in range(n)]


def line(p: Pkg) -> dict[str, str]:
    return {"name": p[0], "version": p[1], "architecture": p[2], "status": p[3]}


# ------------------------------------------------------------ fakes


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Fleet:
    """The shared tables: package rows are fleet-wide."""

    packages: dict[tuple[str, str, str], tuple[int, str | None]] = field(
        default_factory=dict
    )
    next_id: int = 1


@dataclass
class FakeInventory:
    fleet: Fleet
    calls: list[str] = field(default_factory=list)
    os: dict[UUID, OsInfoRow] = field(default_factory=dict)
    ap: dict[UUID, dict[int, list[Any]]] = field(default_factory=dict)
    snaps: dict[UUID, list[SnapshotRow]] = field(default_factory=dict)
    next_snap: int = 1

    def upsert_os_info(self, agent_id: UUID, row: OsInfoRow) -> None:
        self.calls.append("upsert_os_info")
        self.os[agent_id] = row

    def insert_packages(self, rows: Sequence[PackageRow]) -> PackageIds:
        self.calls.append("insert_packages")
        ids: dict[tuple[str, str, str], int] = {}
        new: set[tuple[str, str, str]] = set()
        for r in rows:
            key = (r.name, r.version, r.architecture)
            if key not in self.fleet.packages:
                self.fleet.packages[key] = (self.fleet.next_id, r.source_name)
                self.fleet.next_id += 1
                new.add(key)
            ids[key] = self.fleet.packages[key][0]
        return PackageIds(ids, frozenset(new))

    def _key_of(self, package_id: int) -> tuple[str, str, str]:
        return next(k for k, (i, _) in self.fleet.packages.items() if i == package_id)

    def agent_packages(self, agent_id: UUID) -> list[AgentPackageRow]:
        self.calls.append("agent_packages")
        out = []
        for pid, (status, kb, first, last) in self.ap.get(agent_id, {}).items():
            n, v, a = self._key_of(pid)
            src = self.fleet.packages[(n, v, a)][1]
            out.append(AgentPackageRow(pid, n, v, a, status, src, kb, first, last))
        return out

    def upsert_agent_packages(
        self, agent_id: UUID, rows: Sequence[tuple[int, str, int | None]], now: datetime
    ) -> None:
        self.calls.append("upsert_agent_packages")
        mine = self.ap.setdefault(agent_id, {})
        for pid, status, kb in rows:
            first = mine[pid][2] if pid in mine else now
            mine[pid] = [status, kb, first, now]

    def delete_not_listed(self, agent_id: UUID, keep_ids: Sequence[int]) -> int:
        self.calls.append("delete_not_listed")
        mine = self.ap.setdefault(agent_id, {})
        gone = [pid for pid in mine if pid not in set(keep_ids)]
        for pid in gone:
            del mine[pid]
        return len(gone)

    def insert_snapshot(
        self,
        agent_id: UUID,
        list_sha256: str,
        package_count: int,
        added: list[dict[str, Any]],
        removed: list[dict[str, Any]],
        collected_at: datetime,
    ) -> int:
        self.calls.append("insert_snapshot")
        snap = SnapshotRow(
            self.next_snap, list_sha256, package_count, added, removed, collected_at
        )
        self.next_snap += 1
        self.snaps.setdefault(agent_id, []).append(snap)
        return snap.snapshot_id

    def latest_snapshot(self, agent_id: UUID) -> SnapshotRow | None:
        self.calls.append("latest_snapshot")
        mine = self.snaps.get(agent_id, [])
        return mine[-1] if mine else None


def agent_row(agent_id: UUID, revoked: datetime | None = None) -> AgentRow:
    fields = AgentRow.__dataclass_fields__
    values: dict[str, Any] = dict.fromkeys(fields)
    values.update(
        agent_id=agent_id,
        machine_id="0" * 32,
        hostname="h",
        agent_version="1",
        token_hash="a" * 64,
        token_issued_at=T0 - DAY,
        token_expires_at=T0 + 300 * DAY,
        token_revoked_at=revoked,
        status="online",
    )
    return AgentRow(**{k: values[k] for k in fields})


@dataclass
class FakeAgents:
    rows: dict[UUID, AgentRow] = field(default_factory=dict)
    gets: list[tuple[UUID, bool]] = field(default_factory=list)
    inventory_at: dict[UUID, datetime] = field(default_factory=dict)

    def get(self, agent_id: UUID, *, lock: bool = False) -> AgentRow | None:
        self.gets.append((agent_id, lock))
        return self.rows.get(agent_id)

    def set_last_inventory(self, agent_id: UUID, now: datetime) -> bool:
        self.inventory_at[agent_id] = now
        return True


@dataclass
class FakeAudit:
    alerts: list[tuple[str, str, str, str, dict[str, object]]] = field(
        default_factory=list
    )

    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None:
        self.alerts.append((kind, actor, action, target, dict(detail)))


class World:
    """One manager process: one fleet, one burst window, many agents."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.fleet = Fleet()
        self.inv = FakeInventory(self.fleet)
        self.agents = FakeAgents()
        self.audit = FakeAudit()
        self.pending = 0
        # The window TASK-074 builds once per process (impl report, #65 (e)).
        self.burst: SlidingCount[object] = SlidingCount(
            self.clock, DAY, DAY, NEW_PACKAGES_PER_DAY
        )

    def agent(self) -> UUID:
        a = uuid4()
        self.agents.rows[a] = agent_row(a)
        return a

    def upload(
        self, a: UUID, pkgs: Sequence[Pkg], *, commit: bool = True, **os_over: Any
    ) -> IngestResult:
        """commit=False drops the registered on-commit hooks (a rollback)."""
        hooks: list[Callable[[], None]] = []
        got = ingest(
            self.inv,
            self.agents,
            self.audit,
            self.burst,
            hooks.append,
            agent_id=a,
            decoded=decoded(pkgs, **os_over),
            now=self.clock.at,
        )
        self.pending = len(hooks)
        if commit:
            for hook in hooks:
                hook()
        return got

    def lines(self, a: UUID) -> set[tuple[str, str, str, str]]:
        return {
            (r.name, r.version, r.architecture, r.status)
            for r in self.inv.agent_packages(a)
        }


@pytest.fixture
def w() -> World:
    return World()


# ------------------------------------------------------------ CHK-M3-170


def test_first_upload_writes_os_info_packages_and_a_full_snapshot(w: World) -> None:
    a = w.agent()
    pkgs = [
        pkg("zlib1g", "1:1.3", source="zlib"),
        pkg("libc6", "2.39-0ubuntu8", "amd64", source="glibc", kb=13000),
        pkg("libc6", "2.39-0ubuntu8", "i386", source="glibc", kb=None),
        pkg("adduser", "3.137", "all"),  # empty source
    ]
    got = w.upload(a, pkgs)
    assert got == IngestResult(True, 4, 0, 4)
    # os_info: every field from the upload, collected_at = receive time (#69)
    row = w.inv.os[a]
    assert row == OsInfoRow(
        "ubuntu",
        "24.04",
        "Ubuntu 24.04.1 LTS",
        "6.8.0-45-generic",
        "x86_64",
        4,
        7962,
        ["10.0.0.5", "fe80::1"],
        12345,
        {"os-release": {"ID": "ubuntu"}, "nproc": 4},
        T0,
    )
    assert w.agents.inventory_at == {a: T0}
    # agent_package: one row per package, first = last = now
    stored = {
        (r.name, r.version, r.architecture): (r.status, r.installed_size_kb)
        for r in w.inv.agent_packages(a)
    }
    assert stored == {(p[0], p[1], p[2]): (p[3], p[5]) for p in pkgs}
    assert all(r.first_seen_at == T0 == r.last_seen_at for r in w.inv.agent_packages(a))
    # snapshot: every line in added, nothing removed, items of exactly 4 keys
    [snap] = w.inv.snaps[a]
    assert snap.list_sha256 == oracle_sha256(pkgs)
    assert snap.package_count == 4
    assert snap.collected_at == T0
    assert snap.removed == []
    assert sorted(snap.added, key=lambda d: sorted(d.items())) == sorted(
        (line(p) for p in pkgs), key=lambda d: sorted(d.items())
    )
    assert all(
        set(item) == {"name", "version", "architecture", "status"}
        for item in snap.added
    )


def test_empty_source_is_stored_as_null_and_a_real_one_kept(w: World) -> None:
    """#60: the decoder passes "" through; ingest stores NULL."""
    a = w.agent()
    w.upload(a, [pkg("adduser", source=""), pkg("libc6", source="glibc")])
    assert w.fleet.packages[("adduser", "1.0-1", "amd64")][1] is None
    assert w.fleet.packages[("libc6", "1.0-1", "amd64")][1] == "glibc"


def test_the_agent_row_is_locked_before_anything_is_written(w: World) -> None:
    a = w.agent()
    w.upload(a, [pkg("a")])
    assert w.agents.gets == [(a, True)]


def test_empty_package_list_is_a_valid_first_upload(w: World) -> None:
    a = w.agent()
    got = w.upload(a, [])
    assert got == IngestResult(True, 0, 0, 0)
    [snap] = w.inv.snaps[a]
    assert (snap.package_count, snap.added, snap.removed) == (0, [], [])
    assert snap.list_sha256 == hashlib.sha256(b"").hexdigest()


# ------------------------------------------------------------ CHK-M3-171


def test_same_list_again_replaces_os_info_only(w: World) -> None:
    a = w.agent()
    pkgs = [pkg("a"), pkg("b")]
    w.upload(a, pkgs)
    before = {r.package_id: r for r in w.inv.agent_packages(a)}
    w.clock.at = T0 + HOUR
    w.inv.calls.clear()
    got = w.upload(
        a, list(reversed(pkgs)), os_pretty_name="Ubuntu 24.04.2 LTS", uptime_s=99
    )
    assert got == IngestResult(False, 0, 0, 0)
    assert len(w.inv.snaps[a]) == 1  # no new snapshot
    assert w.inv.os[a].os_pretty_name == "Ubuntu 24.04.2 LTS"
    assert w.inv.os[a].uptime_s == 99
    assert w.inv.os[a].collected_at == T0 + HOUR
    assert w.agents.inventory_at[a] == T0 + HOUR
    assert {r.package_id: r for r in w.inv.agent_packages(a)} == before
    # nothing touches package or agent_package when the hash is unchanged
    assert {
        "insert_packages",
        "upsert_agent_packages",
        "delete_not_listed",
        "insert_snapshot",
    }.isdisjoint(w.inv.calls)


def test_size_or_source_change_alone_is_not_a_new_list(w: World) -> None:
    """#33: source and installed_size_kb are not in list_sha256."""
    a = w.agent()
    w.upload(a, [pkg("a", source="s1", kb=1)])
    got = w.upload(a, [pkg("a", source="s2", kb=2)])
    assert got.snapshot_written is False
    assert len(w.inv.snaps[a]) == 1


# ------------------------------------------------------------ CHK-M3-172


def test_upgrade_and_removal_diff_follows_69(w: World) -> None:
    a = w.agent()
    keep, old_a, gone = pkg("keep"), pkg("a", "1"), pkg("b", "1")
    w.upload(a, [keep, old_a, gone])
    first_keep = next(r for r in w.inv.agent_packages(a) if r.name == "keep")
    w.clock.at = T0 + HOUR
    new_a = pkg("a", "2")
    got = w.upload(a, [keep, new_a])
    assert got == IngestResult(True, 1, 2, 1)
    snap = w.inv.snaps[a][-1]
    assert len(w.inv.snaps[a]) == 2
    assert snap.added == [line(new_a)]
    assert snap.removed == [line(old_a), line(gone)]  # sorted
    assert snap.package_count == 2
    assert snap.collected_at == T0 + HOUR
    assert w.lines(a) == {keep[:4], new_a[:4]}
    # the removed and the old version's package rows stay (retention prunes them)
    assert ("b", "1", "amd64") in w.fleet.packages
    assert ("a", "1", "amd64") in w.fleet.packages
    # first_seen_at kept for an unchanged package, last_seen_at moved
    now_keep = next(r for r in w.inv.agent_packages(a) if r.name == "keep")
    assert now_keep.first_seen_at == first_keep.first_seen_at == T0
    assert now_keep.last_seen_at == T0 + HOUR


def test_status_change_is_old_line_removed_new_line_added(w: World) -> None:
    a = w.agent()
    w.upload(a, [pkg("a"), pkg("b")])
    changed = pkg("b", status="deinstall ok config-files")
    got = w.upload(a, [pkg("a"), changed])
    assert got.snapshot_written
    snap = w.inv.snaps[a][-1]
    assert snap.added == [line(changed)]
    assert snap.removed == [line(pkg("b"))]
    assert w.lines(a) == {pkg("a")[:4], changed[:4]}
    # a status change is not a new package row
    assert got.new_packages == 0


def test_status_change_back_to_installed_uses_the_stored_status(w: World) -> None:
    """The previous line carries the status stored for the agent, whatever it is."""
    a = w.agent()
    half = pkg("b", status="deinstall ok config-files")
    w.upload(a, [pkg("a"), half])
    got = w.upload(a, [pkg("a"), pkg("b")])
    assert (got.added, got.removed) == (1, 1)
    snap = w.inv.snaps[a][-1]
    assert snap.added == [line(pkg("b"))]
    assert snap.removed == [line(half)]


def test_back_to_an_earlier_list_writes_a_snapshot(w: World) -> None:
    """The comparison is with the LAST snapshot, not any earlier one."""
    a = w.agent()
    w.upload(a, [pkg("a")])
    w.upload(a, [pkg("a"), pkg("b")])
    got = w.upload(a, [pkg("a")])
    assert got.snapshot_written
    assert len(w.inv.snaps[a]) == 3
    assert w.inv.snaps[a][-1].removed == [line(pkg("b"))]
    assert w.inv.snaps[a][-1].added == []


def test_agents_are_independent(w: World) -> None:
    a, b = w.agent(), w.agent()
    w.upload(a, [pkg("x")])
    got = w.upload(b, [pkg("x")])
    # b's first upload: its own snapshot lists everything, though x is not new
    assert got == IngestResult(True, 1, 0, 0)
    w.upload(b, [])
    assert w.lines(a) == {pkg("x")[:4]}
    assert w.lines(b) == set()


# ------------------------------------------------------------ carry-over: revoked


@pytest.mark.parametrize("state", ["revoked", "missing"])
def test_agent_revoked_since_token_check_writes_nothing(w: World, state: str) -> None:
    a = w.agent()
    if state == "revoked":
        w.agents.rows[a] = agent_row(a, revoked=T0 - SEC)
    else:
        del w.agents.rows[a]
    with pytest.raises(AgentGone):
        w.upload(a, many("p", 1001))
    assert w.inv.calls == []
    assert w.agents.inventory_at == {}
    assert w.fleet.packages == {}
    assert w.audit.alerts == []
    assert w.burst.count(a) == 0


# ------------------------------------------------------------ CHK-M3-175


def test_burst_alert_above_1000_new_packages_once_per_24h(w: World) -> None:
    a = w.agent()
    w.upload(a, many("p", 1000))
    assert w.audit.alerts == []  # exactly 1,000: not "more than"
    w.clock.at = T0 + HOUR
    w.upload(a, many("p", 1001))  # one more new row: 1,001 in 24 h
    assert w.audit.alerts == [
        (
            "new_packages_burst",
            f"agent:{a}",
            "alert.new_packages_burst",
            f"agent:{a}",
            {"new_packages": 1, "over_per_day": 1000},
        )
    ]
    # more new packages within 24 h of the alert: no second alert
    w.clock.at = T0 + HOUR + DAY - SEC
    w.upload(a, many("p", 1001) + many("q", 2000))
    assert len(w.audit.alerts) == 1
    # 24 h after the alert, another burst alerts again
    w.clock.at = T0 + HOUR + DAY
    w.upload(a, many("r", 1001))
    assert [x[0] for x in w.audit.alerts] == ["new_packages_burst"] * 2


def test_burst_counts_only_fleet_new_rows(w: World) -> None:
    """#65 (e): packages already in the fleet are not 'previously unseen'."""
    a, b = w.agent(), w.agent()
    w.upload(a, many("p", 1001))
    assert len(w.audit.alerts) == 1 and w.audit.alerts[0][1] == f"agent:{a}"
    got = w.upload(b, many("p", 1001))
    assert got.new_packages == 0
    assert len(w.audit.alerts) == 1  # nothing for b
    # new to b but not to the fleet still does not count, plus 1,000 new: no alert
    w.upload(b, many("p", 1001) + many("q", 1000))
    assert len(w.audit.alerts) == 1


def test_burst_window_is_rolling_24h_per_agent(w: World) -> None:
    a, b = w.agent(), w.agent()
    w.upload(a, many("p", 600))
    w.upload(b, many("x", 600))
    w.clock.at = T0 + DAY - SEC
    w.upload(a, many("p", 600) + many("q", 401))  # 1,001 within 24 h
    assert [x[1] for x in w.audit.alerts] == [f"agent:{a}"]
    assert w.audit.alerts[0][4] == {"new_packages": 401, "over_per_day": 1000}
    w.clock.at = T0 + DAY
    w.upload(b, many("x", 600) + many("y", 401))  # b's first 600 left the window
    assert len(w.audit.alerts) == 1


def test_burst_detail_never_holds_package_names(w: World) -> None:
    a = w.agent()
    w.upload(a, many("CANARY-0123456789abcdef-", 1001))
    [(_, _, _, _, detail)] = w.audit.alerts
    assert "CANARY" not in json.dumps(detail)
    assert set(detail) == {"new_packages", "over_per_day"}


def test_no_new_packages_never_touches_the_window(w: World) -> None:
    a = w.agent()
    w.upload(a, many("p", 10))
    w.upload(a, many("p", 10)[:5])  # changed list, no new rows
    assert w.burst.count(a) == 10


def test_rolled_back_alert_leaves_the_daily_slot_free(w: World) -> None:
    """Ruling 2026-10-23 (a): the window is marked only after commit."""
    a = w.agent()
    w.upload(a, many("p", 1001), commit=False)  # alert written, then rolled back
    assert len(w.audit.alerts) == 1 and w.pending == 1
    w.audit.alerts.clear()  # the rollback removed the entry
    w.fleet.packages.clear()  # and the package rows
    w.inv.ap.clear()
    w.inv.snaps.clear()
    w.clock.at = T0 + 10 * 60 * SEC
    w.upload(a, many("p", 1001))  # the retry: the same rows are new again
    assert [x[0] for x in w.audit.alerts] == ["new_packages_burst"]
    w.clock.at = T0 + HOUR
    w.upload(a, many("q", 1001))  # committed alert above: no second one in 24 h
    assert len(w.audit.alerts) == 1 and w.pending == 0


def test_only_an_alert_registers_an_on_commit_hook(w: World) -> None:
    a = w.agent()
    w.upload(a, many("p", 1000))
    assert w.pending == 0
    w.upload(a, many("p", 1001))
    assert w.pending == 1
