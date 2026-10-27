"""TASK-053: os_info, package, agent_package and inventory_snapshot repository.

Checks CHK-M3-070 to CHK-M3-074 of tests/m3/test-plan.md (TP-M3-07). Every call
runs as bitscan_app on a freshly migrated database. Expected values: TS §5.2
L780-L825 and the grants (INSERT and SELECT only on package and
inventory_snapshot; UPDATE os_info, agent_package; DELETE agent_package),
database rules ("INSERT … ON CONFLICT DO NOTHING and then a SELECT"), TS §3.4
L240-L241 (50,000 rows; upsert agent_package, delete rows no longer listed),
#68 (package page ordered by name, architecture, version), #69 (snapshot).
Large and fleet-wide statements run in rolled-back transactions.
"""

import secrets
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from psycopg import errors

from bitscan_manager.repositories.inventory import (
    AgentPackageRow,
    InventoryRepo,
    OsInfoRow,
    PackageIds,
    PackageRow,
)

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
DURATIONS: dict[str, float] = {}


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def agent(conn: Conn) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status) VALUES (%s, 'h', '1', %s, %s, %s,"
        " 'online') RETURNING agent_id",
        (secrets.token_hex(16), secrets.token_hex(32), T0, T0 + timedelta(days=365)),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def pkgs(prefix: str, n: int, arch: str = "amd64") -> list[PackageRow]:
    return [PackageRow(f"{prefix}{i:06d}", "1.0-1", arch, f"src-{i}") for i in range(n)]


class Capture:
    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self.statements: list[str] = []

    def execute(self, query: Any, params: Any = None) -> Any:
        text = query if isinstance(query, str) else query.as_string(self.conn)
        self.statements.append(text)
        return self.conn.execute(query, params)


# ------------------------------------------------------------ CHK-M3-070


def test_fifty_thousand_packages_insert_only(conn: Conn) -> None:
    """REQ-075 (5): batches, INSERT and SELECT only; a second call adds nothing."""
    prefix = f"bulk-{secrets.token_hex(3)}-"
    rows = pkgs(prefix, 50_000)
    cap = Capture(conn)
    repo = InventoryRepo(cap)  # type: ignore[arg-type]
    with conn.transaction(force_rollback=True):
        started = time.perf_counter()
        first = repo.insert_packages(rows)
        DURATIONS["insert_50000"] = time.perf_counter() - started
        assert isinstance(first, PackageIds)
        assert len(first.ids) == 50_000 and len(first.new) == 50_000
        assert len(set(first.ids.values())) == 50_000
        second = repo.insert_packages(list(reversed(rows)))
        assert second.new == frozenset() and second.ids == first.ids
        count = conn.execute(
            "SELECT count(*) FROM package WHERE name LIKE %s", (prefix + "%",)
        ).fetchone()
        assert count == (50_000,)
    for stmt in cap.statements:
        assert not re2.search(r"(?i)\bUPDATE\b|\bDELETE\b", stmt), stmt
        assert not re2.search(r"(?i)DO\s+UPDATE", stmt), stmt
    # batched: at least 50 inserts of at most 1,000 rows, not one per row
    inserts = [s for s in cap.statements if "INSERT INTO package" in s]
    assert 50 <= len(inserts) <= 2 * 50
    print(f"insert 50,000 packages: {DURATIONS['insert_50000']:.2f} s")


def test_new_reports_only_rows_this_call_created(conn: Conn) -> None:
    prefix = f"mix-{secrets.token_hex(3)}-"
    repo = InventoryRepo(conn)
    with conn.transaction(force_rollback=True):
        first = repo.insert_packages(pkgs(prefix, 3))
        both = repo.insert_packages(pkgs(prefix, 5))
        assert both.new == {(f"{prefix}{i:06d}", "1.0-1", "amd64") for i in (3, 4)}
        assert {k: v for k, v in both.ids.items() if k in first.ids} == first.ids


def test_multi_arch_rows_are_distinct(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    name = f"libc6-{secrets.token_hex(3)}"
    with conn.transaction(force_rollback=True):
        got = repo.insert_packages(
            [
                PackageRow(name, "2.39", "amd64", "glibc"),
                PackageRow(name, "2.39", "i386", "glibc"),
            ]
        )
        assert len(got.ids) == 2 and len(set(got.ids.values())) == 2


def test_source_name_of_the_first_writer_is_kept(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    name = f"src-{secrets.token_hex(3)}"
    with conn.transaction(force_rollback=True):
        repo.insert_packages([PackageRow(name, "1", "all", None)])
        repo.insert_packages([PackageRow(name, "1", "all", "later")])
        row = conn.execute("SELECT source_name FROM package WHERE name = %s", (name,))
        assert row.fetchone() == (None,)


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE package SET source_name = 'x'",
        "DELETE FROM package",
        "UPDATE inventory_snapshot SET package_count = 0",
        "DELETE FROM inventory_snapshot",
    ],
)
def test_app_cannot_change_packages_or_snapshots(conn: Conn, stmt: str) -> None:
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute(stmt)


# ------------------------------------------------------------ CHK-M3-071


def _same_package_race(db: PgServer) -> None:
    row = PackageRow(f"race-{secrets.token_hex(4)}", "1", "amd64", "s")
    key = (row.name, row.version, row.architecture)
    b_got: list[PackageIds] = []
    with db.connect("bitscan_app") as ca:
        with ca.transaction():
            a_got = InventoryRepo(ca).insert_packages([row])

            def b() -> None:
                with db.connect("bitscan_app") as cb, cb.transaction():
                    b_got.append(InventoryRepo(cb).insert_packages([row]))

            t = threading.Thread(target=b)
            t.start()
            t.join(2)
            assert t.is_alive(), "B did not wait for A's uncommitted row"
        t.join(30)
    assert a_got.new == {key} and b_got[0].new == frozenset()
    assert b_got[0].ids[key] == a_got.ids[key]
    with db.connect("bitscan_app") as c:
        n = c.execute("SELECT count(*) FROM package WHERE name = %s", (row.name,))
        assert n.fetchone() == (1,)


def test_concurrent_insert_of_one_new_package_gives_one_row(db: PgServer) -> None:
    """REQ-075 (6): deterministic interleave, repeated."""
    for _ in range(3):
        _same_package_race(db)


def test_overlapping_concurrent_batches_do_not_deadlock(db: PgServer) -> None:
    prefix = f"ovl-{secrets.token_hex(3)}-"
    rows = pkgs(prefix, 3000)
    barrier = threading.Barrier(4)
    results: list[PackageIds] = []
    errs: list[BaseException] = []
    lock = threading.Lock()

    def go(order: int) -> None:
        try:
            mine = rows if order % 2 else list(reversed(rows))
            with db.connect("bitscan_app") as cx:
                barrier.wait(15)
                with cx.transaction():
                    got = InventoryRepo(cx).insert_packages(mine)
            with lock:
                results.append(got)
        except BaseException as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    assert not errs, errs
    assert sum(len(r.new) for r in results) == 3000  # each row created once
    assert all(r.ids == results[0].ids for r in results)


# ------------------------------------------------------------ CHK-M3-072, -073


def _ids(repo: InventoryRepo, prefix: str, n: int) -> list[int]:
    got = repo.insert_packages(pkgs(prefix, n))
    return [got.ids[(f"{prefix}{i:06d}", "1.0-1", "amd64")] for i in range(n)]


def test_agent_package_upsert_keeps_first_seen(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        ids = _ids(repo, f"ap-{secrets.token_hex(3)}-", 2)
        repo.upsert_agent_packages(a, [(ids[0], "install ok installed", 10)], T0)
        repo.upsert_agent_packages(
            a,
            [
                (ids[0], "deinstall ok config-files", None),
                (ids[1], "install ok installed", 5),
            ],
            T0 + MIN,
        )
        rows = {r.package_id: r for r in repo.agent_packages(a)}
        assert all(isinstance(r, AgentPackageRow) for r in rows.values())
        r0 = rows[ids[0]]
        assert (r0.first_seen_at, r0.last_seen_at) == (T0, T0 + MIN)
        assert (r0.status, r0.installed_size_kb) == ("deinstall ok config-files", None)
        r1 = rows[ids[1]]
        assert (r1.first_seen_at, r1.last_seen_at, r1.installed_size_kb) == (
            T0 + MIN,
            T0 + MIN,
            5,
        )
        repo.upsert_agent_packages(a, [], T0 + 2 * MIN)  # nothing to do is fine


def test_delete_not_listed_is_exact(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    with conn.transaction(force_rollback=True):
        a, b = agent(conn), agent(conn)
        ids = _ids(repo, f"del-{secrets.token_hex(3)}-", 5)
        lines = [(i, "install ok installed", 1) for i in ids]
        repo.upsert_agent_packages(a, lines, T0)
        repo.upsert_agent_packages(b, lines, T0)
        assert repo.delete_not_listed(a, [ids[0], ids[2], ids[4]]) == 2
        assert sorted(r.package_id for r in repo.agent_packages(a)) == [
            ids[0],
            ids[2],
            ids[4],
        ]
        assert sorted(r.package_id for r in repo.agent_packages(b)) == sorted(ids)
        kept = conn.execute(
            "SELECT count(*) FROM package WHERE package_id = ANY(%s)", (ids,)
        ).fetchone()
        assert kept == (5,)  # package rows remain (retention prunes them, M11)
        assert repo.delete_not_listed(a, [ids[0], ids[2], ids[4]]) == 0
        assert repo.delete_not_listed(a, []) == 3  # an empty list removes them all
        assert repo.agent_packages(a) == []


def test_delete_not_listed_at_fifty_thousand(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        ids = _ids(repo, f"big-{secrets.token_hex(3)}-", 50_000)
        started = time.perf_counter()
        repo.upsert_agent_packages(a, [(i, "install ok installed", 1) for i in ids], T0)
        DURATIONS["upsert_50000"] = time.perf_counter() - started
        started = time.perf_counter()
        assert repo.delete_not_listed(a, ids[1:]) == 1
        DURATIONS["delete_not_listed_50000"] = time.perf_counter() - started
        assert len(repo.agent_packages(a)) == 49_999
    print(
        f"upsert 50,000: {DURATIONS['upsert_50000']:.2f} s;"
        f" delete-not-listed: {DURATIONS['delete_not_listed_50000']:.2f} s"
    )


# ------------------------------------------------------------ CHK-M3-074


def test_os_info_upsert_replaces_every_column(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    full = OsInfoRow(
        os_id="ubuntu",
        os_version_id="24.04",
        os_pretty_name="Ubuntu 24.04.1 LTS",
        kernel_release="6.8.0-45-generic",
        architecture="x86_64",
        cpu_count=4,
        memory_mb=7962,
        ip_addresses=["10.0.0.5/24", "fe80::1/64", "192.0.2.1", "2001:db8::7"],
        uptime_s=2**62,
        raw={"os_release": {"ID": "ubuntu"}, "n": [1, 2], "s": "<script>"},
        collected_at=T0,
    )
    empty = OsInfoRow(None, None, None, None, None, None, None, [], None, {}, T0 + MIN)
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        assert repo.get_os_info(a) is None
        repo.upsert_os_info(a, full)
        assert repo.get_os_info(a) == full  # stored order and text form kept
        repo.upsert_os_info(a, empty)
        assert repo.get_os_info(a) == empty


def test_snapshots_latest_by_insertion(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    line = {
        "name": "apt",
        "version": "2.7",
        "architecture": "amd64",
        "status": "install ok installed",
    }
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        assert repo.latest_snapshot(a) is None
        s1 = repo.insert_snapshot(a, "a" * 64, 1, [line], [], T0 + MIN)
        s2 = repo.insert_snapshot(
            a, "b" * 64, 0, [], [line], T0
        )  # earlier collected_at
        latest = repo.latest_snapshot(a)
        assert latest is not None and latest.snapshot_id == s2 > s1
        assert (latest.list_sha256, latest.package_count) == ("b" * 64, 0)
        assert (latest.added, latest.removed, latest.collected_at) == ([], [line], T0)
        other = agent(conn)
        assert repo.latest_snapshot(other) is None


def test_package_page_order_and_keyset(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    p = f"pg-{secrets.token_hex(3)}-"
    rows = [
        PackageRow(p + "b", "1.0", "amd64", None),
        PackageRow(p + "a", "2.0", "i386", None),
        PackageRow(p + "a", "1.0", "i386", None),
        PackageRow(p + "a", "9.0", "amd64", None),
        PackageRow(p + "c", "0.1", "all", None),
    ]
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        got = repo.insert_packages(rows)
        repo.upsert_agent_packages(
            a, [(i, "install ok installed", None) for i in got.ids.values()], T0
        )
        expected = [
            (p + "a", "amd64", "9.0"),
            (p + "a", "i386", "1.0"),
            (p + "a", "i386", "2.0"),
            (p + "b", "amd64", "1.0"),
            (p + "c", "all", "0.1"),
        ]
        whole = [
            (r.name, r.architecture, r.version)
            for r in repo.package_page(a, None, None)
        ]
        assert whole == expected
        for n in (1, 2, 4):
            seen: list[tuple[str, str, str]] = []
            after: int | None = None  # the last row's package_id (#89)
            while True:
                page = repo.package_page(a, n, after)
                seen.extend((r.name, r.architecture, r.version) for r in page)
                if len(page) < n:
                    break
                after = page[-1].package_id
            assert seen == expected, n


# ------------------------------------------------------------ CHK-M3-074-r1
# TASK-053 revision 1 (reviewer finding): versions are ordered in Debian order
# (TS §7.2 L1219; database rules "never compare Debian versions as text"), with
# the text as a tie-break so that equal Debian versions keep a total order.
# Expected order written by hand from the dpkg rules: "~" sorts before
# everything, numeric parts compare as numbers ("1.0" == "1.00"), a missing
# revision sorts before "-1", and an epoch outranks any version without one.
DEBIAN_ORDER = ["1.0~rc1", "1.0", "1.00", "1.9", "1.10", "2.0", "2.0-1", "1:0.1"]


def test_package_page_uses_debian_version_order(conn: Conn) -> None:
    repo = InventoryRepo(conn)
    name = f"deb-{secrets.token_hex(3)}"
    shuffled = ["1.10", "1:0.1", "1.0", "2.0-1", "1.9", "1.00", "2.0", "1.0~rc1"]
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        got = repo.insert_packages(
            [PackageRow(name, v, "amd64", None) for v in shuffled]
        )
        repo.upsert_agent_packages(
            a, [(i, "install ok installed", None) for i in got.ids.values()], T0
        )
        whole = [r.version for r in repo.package_page(a, None, None)]
        assert whole == DEBIAN_ORDER
        for n in (1, 2, 3):
            seen: list[str] = []
            after: int | None = None  # the last row's package_id (#89)
            while True:
                page = repo.package_page(a, n, after)
                seen.extend(r.version for r in page)
                if len(page) < n:
                    break
                after = page[-1].package_id
            assert seen == DEBIAN_ORDER, n


def test_package_page_debian_order_within_name_and_architecture(conn: Conn) -> None:
    """Name and architecture still come first; the version order is per pair."""
    repo = InventoryRepo(conn)
    p = f"deb2-{secrets.token_hex(3)}-"
    rows = [
        PackageRow(p + "a", "1.10", "i386", None),
        PackageRow(p + "a", "1.9", "i386", None),
        PackageRow(p + "a", "1.10", "amd64", None),
        PackageRow(p + "b", "0.1", "amd64", None),
        PackageRow(p + "a", "1.9", "amd64", None),
    ]
    with conn.transaction(force_rollback=True):
        a = agent(conn)
        got = repo.insert_packages(rows)
        repo.upsert_agent_packages(
            a, [(i, "install ok installed", None) for i in got.ids.values()], T0
        )
        first = repo.package_page(a, 2, None)
        seen = [(r.name, r.architecture, r.version) for r in first]
        seen += [
            (r.name, r.architecture, r.version)
            for r in repo.package_page(a, 10, first[-1].package_id)
        ]
        assert seen == [
            (p + "a", "amd64", "1.9"),
            (p + "a", "amd64", "1.10"),
            (p + "a", "i386", "1.9"),
            (p + "a", "i386", "1.10"),
            (p + "b", "amd64", "0.1"),
        ]
