"""TASK-242 TEST: the retention service with clock control on PostgreSQL
(TP-M11-10; CHK-M11-171, CHK-M11-175 to -192).

Expected values: TS §5.3 L1049 (what is deleted and when), L1051
(bitscan_retention only), L1053 (a checkpoint before the delete records the
last deleted id and its row_hash), L1054 (no results in logs); REQ-275 (1)-(6),
REQ-276 (1)-(6), REQ-278 (1), (2), (4); #150 (a)-(k); plan TASK-242 §4 (steps
in order, a transaction per chunk, the checkpoint through append_entry with
actor `system` and detail exactly {last_deleted_id, last_deleted_row_hash,
deleted} in the same transaction as the delete; a failing step logged by name
and exception type, the next step runs; counts-only logs); the lead's
corrections of 2026-11-08 (tokens probe on created_at; no row lock) and the
lead's TASK-237 review row (locked scans never stall the scans step).

Drafted from the plan and the REQs before task.py existed, then bound to its
names (`run_retention`, `StepResult(step, deleted, chunks, skipped)`, the
skip words `clock_doubt`, `future_rows`, `failed`, log fields in
`extra["data"]`). Each test starts from emptied retention tables (as owner).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.repositories import reeval as m8_reeval
from bitscan_manager.repositories import retention as rt
from bitscan_manager.repositories import retention_audit as ra
from bitscan_manager.repositories.agents import AgentRepo
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.inventory import InventoryRepo
from bitscan_manager.services.audit.thresholds import SlidingCount
from bitscan_manager.services.audit.verify import verify_chain
from bitscan_manager.services.inventory.ingest import NEW_PACKAGES_PER_DAY, ingest
from bitscan_manager.services.retention import rules, task
from bitscan_manager.services.users.accounts import TxAudit

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server
from .test_inventory_ingest import DAY, decoded, pkg

pytestmark = pytest.mark.pg

STEPS = (
    "scans",
    "inventory_jobs",
    "snapshots",
    "requests",
    "tokens",
    "audit",
    "packages",
)
RULE = {
    "scans": "scan",
    "inventory_jobs": "inventory_job",
    "snapshots": "snapshot",
    "requests": "request",
    "tokens": "token",
}
GONE = {
    "scan": {"past", "old"},
    "inventory_job": {"past", "old"},
    "snapshot": {"past", "old"},
    "request": {"past", "old"},
    "token": {"past", "old", "revoked_past"},
    "package": {"unreferenced", "unreferenced2"},
}
WHOLE = {"scan": 1, "scan_job": 4, "scan_result": 4, "scan_result_reeval": 2}
NONE_LEFT = dict.fromkeys(WHOLE, 0)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("retention-svc")) as s:
        yield s


@pytest.fixture
def fresh(server: PgServer) -> PgServer:
    with m.owner(server) as c:
        c.execute(
            "TRUNCATE scan, scan_job, scan_result, scan_result_reeval,"
            " inventory_snapshot, enrollment_request, enrollment_token, user_token,"
            " package, agent_package, os_info, audit_log CASCADE"
        )
    return server


@pytest.fixture
def rdb(fresh: PgServer) -> Iterator[Any]:
    with m.retention_database(fresh) as db:
        yield db


def run(
    db: Any, now: datetime | None = None, shipped: int | None = None, **kw: Any
) -> dict[str, task.StepResult]:
    out = task.run_retention(
        db, now or m.now_utc(), shipped_through=m.shipped(shipped), **kw
    )
    assert [r.step for r in out] == list(STEPS)  # every step, in order
    return {r.step: r for r in out}


def labels(w: m.AgedWorld) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for rule, label in w.rows:
        out.setdefault(rule, set()).add(label)
    return out


def survivors(server: PgServer, w: m.AgedWorld) -> dict[str, set[str]]:
    with m.owner(server) as c:
        p = m.present(c, w)
    out: dict[str, set[str]] = {r: set() for r in labels(w)}
    for (rule, label), ok in p.items():
        if ok:
            out[rule].add(label)
    return out


def expected(w: m.AgedWorld, skip: str | None = None) -> dict[str, set[str]]:
    return {
        r: labs if r == skip else labs - GONE.get(r, set())
        for r, labs in labels(w).items()
    }


def aged(server: PgServer) -> m.AgedWorld:
    with m.owner(server) as c:
        return m.aged_world(c, m.now_utc())


def old_at(now: datetime) -> datetime:
    return rules.minus_years(now, 3) - timedelta(days=5)


def scan_ids(server: PgServer) -> set[UUID]:
    with m.owner(server) as c:
        return {UUID(str(r[0])) for r in c.execute("SELECT scan_id FROM scan")}


def records(caplog: pytest.LogCaptureFixture, msg: str) -> list[dict[str, Any]]:
    return [
        dict(getattr(r, "data", {}))
        for r in caplog.records
        if r.name == task.__name__ and r.getMessage() == msg
    ]


# ------------------------------------------------- CHK-M11-175, -178, -180, -192


def test_one_run_deletes_exactly_the_expired_rows(fresh: PgServer, rdb: Any) -> None:
    w = aged(fresh)
    with m.owner(fresh) as c:
        kept = m.checksums(c)
    res = run(rdb, w.now)
    assert survivors(fresh, w) == expected(w)
    with m.owner(fresh) as c:
        for lab in ("old", "past"):
            assert m.scan_remains(c, w.key("scan", lab), w.scan_jobs[lab]) == NONE_LEFT
        for lab in ("inside", "at"):  # 399 days, exactly 400 days: whole
            assert m.scan_remains(c, w.key("scan", lab), w.scan_jobs[lab]) == WHOLE
        assert m.checksums(c) == kept  # G2: os_info, agent_package; and the rest
    got = {s: (r.deleted, r.skipped) for s, r in res.items()}
    assert got == {
        "scans": (2, None),
        "inventory_jobs": (2, None),
        "snapshots": (2, None),
        "requests": (2, None),
        "tokens": (3, None),
        "audit": (0, None),  # no shipper cursor yet
        "packages": (2, None),
    }
    s = survivors(fresh, w)
    # REQ-275 (4) and the lead's row: pending request, 89 days, revoked not
    # expired and the live API token stay; 91 days (revoked) goes
    assert {"pending", "at", "inside"} <= s["request"]
    assert s["token"] == {"inside", "at", "inside_89", "revoked_live", "live_api"}


# ------------------------------------------------------------------ CHK-M11-176


def test_every_statement_as_bitscan_retention(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = aged(fresh)
    ids = m.audit_chain(fresh, [old_at(w.now)] * 3)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    res = run(rdb, w.now, shipped=ids[-1])
    monkeypatch.undo()
    assert res["audit"].deleted == 3
    assert len(spy.statements) > 20 and set(spy.roles) == {"bitscan_retention"}


# ------------------------------------------------------------------ CHK-M11-179


def test_unreferenced_package_pruned_and_stored_again(
    fresh: PgServer, rdb: Any
) -> None:
    now = m.now_utc()
    name = f"m11-reup-{now.microsecond}"
    with m.owner(fresh) as c:
        a = m.host(c, at=now)
        ref = m.package(c)
        m.inventory(c, a.agent_id, [ref], at=now - DAY)
        lone = m.package(c, name)
    assert run(rdb, now)["packages"].deleted == 1
    with m.owner(fresh) as c:
        left = {int(r[0]) for r in c.execute("SELECT package_id FROM package")}
        assert left == {ref} and lone not in left
    clock = f9.Clock(now)
    burst: SlidingCount[object] = SlidingCount(clock, DAY, DAY, NEW_PACKAGES_PER_DAY)
    with f9.app_database(fresh) as adb, adb.transaction() as tx:
        ingest(
            InventoryRepo(tx.conn),
            AgentRepo(tx.conn),
            TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
            burst,
            tx.on_commit,
            agent_id=a.agent_id,
            decoded=decoded([pkg(name, "1.0-1", "amd64")]),
            now=now,
        )
    with m.owner(fresh) as c:
        row = c.execute(
            "SELECT count(*) FROM package p JOIN agent_package ap"
            " ON ap.package_id = p.package_id WHERE p.name = %s AND ap.agent_id = %s",
            (name, a.agent_id),
        ).fetchone()
    assert row == (1,)


# ------------------------------------------------------------------ CHK-M11-181


def test_chunks(fresh: PgServer, rdb: Any) -> None:
    now = m.now_utc()
    old = now - timedelta(days=500)
    with m.owner(fresh) as c:
        pol = m.make_policy(c, 1)
        a = m.host(c, at=now)
        for _ in range(250):
            m.scan(c, pol, [a.agent_id], created_at=old)
        c.execute(
            "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
            " pickup_by, dispatched_at, finished_at) SELECT gen_random_uuid(),"
            " 'inventory', %s, 'completed', '{}'::jsonb, %s, %s, %s, %s"
            " FROM generate_series(1, 2500)",
            (a.agent_id, old, old + timedelta(days=1), old, old),
        )
    res = run(rdb, now)
    # Chunks of 2 scans (TASK-261 r1, PD-51): 125 full chunks; the next one
    # finds nothing and is not counted.
    assert (res["scans"].deleted, res["scans"].chunks) == (250, 125)
    assert (res["inventory_jobs"].deleted, res["inventory_jobs"].chunks) == (2500, 3)


# ------------------------------------------------- CHK-M11-182, -183, -187


def test_audit_prefix_checkpoint_and_chain(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = m.now_utc()
    ids = m.audit_chain(fresh, [old_at(now)] * 10 + [now - DAY] * 5 + [old_at(now)])
    with m.owner(fresh) as c:
        hash10 = m.row_hash_of(c, ids[9])
    woken: list[bool] = []

    def wake() -> None:  # after commit: the checkpoint is visible elsewhere
        with m.owner(fresh) as c:
            woken.append(bool(m.checkpoints(c)))

    spy = m.RoleSpy()
    spy.install(monkeypatch)
    res = run(rdb, now, shipped=ids[-1], wake=wake)
    monkeypatch.undo()
    assert (res["audit"].deleted, res["audit"].chunks) == (10, 1)
    with m.owner(fresh) as c:
        cps = m.checkpoints(c)
        left = m.audit_ids(c)
        assert verify_chain(c).ok
    assert len(cps) == 1
    cp = cps[0]
    assert (cp["actor"], cp["target"]) == ("system", None)
    assert cp["detail"] == {
        "last_deleted_id": ids[9],
        "last_deleted_row_hash": hash10,
        "deleted": 10,
    }
    assert cp["audit_id"] > ids[-1]
    assert left == [*ids[10:], cp["audit_id"]]  # REQ-276 (2): prefix only
    assert woken == [True]
    # the checkpoint INSERT comes before the DELETE (same transaction: the
    # pool's; one chunk)
    upper = [s.upper() for s in spy.statements]
    ins = [i for i, s in enumerate(upper) if s.startswith("INSERT INTO AUDIT_LOG")]
    dels = [i for i, s in enumerate(upper) if s.startswith("DELETE FROM AUDIT_LOG")]
    assert len(ins) == 1 and len(dels) == 1 and ins[0] < dels[0]
    again = run(rdb, now, shipped=10**9)
    assert again["audit"].deleted == 0
    with m.owner(fresh) as c:
        assert m.checkpoints(c, cp["audit_id"]) == []


# ------------------------------------------------------------------ CHK-M11-185


def test_audit_capped_at_the_shipper_cursor(fresh: PgServer, rdb: Any) -> None:
    now = m.now_utc()
    ids = m.audit_chain(fresh, [old_at(now)] * 6)
    assert run(rdb, now, shipped=None)["audit"].deleted == 0
    with m.owner(fresh) as c:
        assert m.audit_ids(c) == ids and m.checkpoints(c) == []
    assert run(rdb, now, shipped=ids[2])["audit"].deleted == 3
    with m.owner(fresh) as c:
        assert m.audit_ids(c)[:3] == ids[3:]
        assert verify_chain(c).ok


# ------------------------------------------------------------------ CHK-M11-186


def test_25000_entries_three_chunks_three_checkpoints(
    fresh: PgServer, rdb: Any
) -> None:
    now = m.now_utc()
    ids = m.audit_chain(fresh, [old_at(now)] * 25_000)
    res = run(rdb, now, shipped=ids[-1])
    assert (res["audit"].deleted, res["audit"].chunks) == (25_000, 3)
    with m.owner(fresh) as c:
        cps = m.checkpoints(c)
        assert [cp["detail"]["deleted"] for cp in cps] == [10_000, 10_000, 5_000]
        assert [cp["detail"]["last_deleted_id"] for cp in cps] == [
            ids[9_999],
            ids[19_999],
            ids[-1],
        ]
        assert m.audit_ids(c) == [cp["audit_id"] for cp in cps]
        assert verify_chain(c).ok


# ------------------------------------------------------- CHK-M11-177 (faults)


def test_fault_in_the_second_scans_chunk(
    fresh: PgServer,
    rdb: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = m.now_utc()
    with m.owner(fresh) as c:
        pol = m.make_policy(c, 1)
        a = m.host(c, at=now)
        for _ in range(150):
            m.scan(c, pol, [a.agent_id], created_at=now - timedelta(days=500))
        m.snapshot(c, a.agent_id, now - timedelta(days=200))
    real = rt.delete_scans
    calls = {"n": 0}

    def flaky(conn: Any, ids: Any) -> int:
        calls["n"] += 1
        n = real(conn, ids)
        if calls["n"] == 2:
            raise RuntimeError(f"planted {ids[0]}")
        return n

    monkeypatch.setattr(rt, "delete_scans", flaky)
    caplog.set_level(logging.DEBUG)
    res = run(rdb, now)
    monkeypatch.undo()
    # The first chunk stays deleted, the second is rolled back (chunks of
    # rules.SCAN_CHUNK, pinned at 2 in test_retention_rules; TASK-261, PD-51).
    chunk = rules.SCAN_CHUNK
    assert 150 > 2 * chunk  # a second, full chunk exists
    assert len(scan_ids(fresh)) == 150 - chunk
    assert (res["scans"].deleted, res["scans"].skipped) == (chunk, "failed")
    assert res["snapshots"].deleted == 1  # the later steps ran
    assert records(caplog, "retention step failed") == [
        {"step": "scans", "exc_type": "RuntimeError"}
    ]
    assert "planted" not in caplog.text
    run(rdb, now)  # the next run finishes the work
    assert scan_ids(fresh) == set()


def test_fault_in_the_second_inventory_chunk(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction per chunk in the dated steps too: a fault in the
    second chunk keeps the first chunk's deletes and loses only its own."""
    now = m.now_utc()
    old = now - timedelta(days=60)
    with m.owner(fresh) as c:
        a = m.host(c, at=now)
        c.execute(
            "INSERT INTO scan_job (job_id, kind, agent_id, state, payload, created_at,"
            " pickup_by, dispatched_at, finished_at) SELECT gen_random_uuid(),"
            " 'inventory', %s, 'completed', '{}'::jsonb, %s, %s, %s, %s"
            " FROM generate_series(1, 2500)",
            (a.agent_id, old, old + timedelta(days=1), old, old),
        )
    real = rt.delete_inventory_jobs
    calls = {"n": 0}

    def flaky(conn: Any, cutoff: datetime, n: int) -> int:
        calls["n"] += 1
        got = int(real(conn, cutoff, n))
        if calls["n"] == 2:
            raise RuntimeError("planted")
        return got

    monkeypatch.setattr(rt, "delete_inventory_jobs", flaky)
    res = run(rdb, now)
    monkeypatch.undo()
    assert (res["inventory_jobs"].deleted, res["inventory_jobs"].skipped) == (
        1000,
        "failed",
    )
    with m.owner(fresh) as c:
        left = c.execute(
            "SELECT count(*) FROM scan_job WHERE kind = 'inventory'"
        ).fetchone()
    assert left == (1500,)


# ------------------------------------------------------- CHK-M11-184 (faults)


@pytest.mark.parametrize("fault", ["raise", "count_mismatch"])
def test_fault_in_the_audit_delete_leaves_no_checkpoint(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    now = m.now_utc()
    ids = m.audit_chain(fresh, [old_at(now)] * 5)
    real = ra.delete_through

    def broken(conn: Any, audit_id: int) -> int:
        n = real(conn, audit_id)
        if fault == "raise":
            raise RuntimeError("planted")
        return n - 1

    monkeypatch.setattr(ra, "delete_through", broken)
    res = run(rdb, now, shipped=ids[-1], wake=lambda: pytest.fail("woken"))
    monkeypatch.undo()
    assert (res["audit"].deleted, res["audit"].skipped) == (0, "failed")
    assert res["packages"].skipped is None
    with m.owner(fresh) as c:
        assert m.audit_ids(c) == ids and m.checkpoints(c) == []
        assert verify_chain(c).ok


# ------------------------------------------------- CHK-M11-188 (clock guard)


@pytest.mark.parametrize(
    ("ahead", "refused"),
    [
        (timedelta(hours=1), True),
        (-timedelta(hours=1), True),
        (timedelta(minutes=4), False),
    ],
    ids=["1h-ahead", "1h-behind", "4min-ahead"],
)
def test_clock_doubt(
    fresh: PgServer,
    rdb: Any,
    caplog: pytest.LogCaptureFixture,
    ahead: timedelta,
    refused: bool,
) -> None:
    w = aged(fresh)
    ids = m.audit_chain(fresh, [old_at(w.now)] * 2)
    caplog.set_level(logging.DEBUG)
    res = run(rdb, m.now_utc() + ahead, shipped=ids[-1])
    doubts = [
        r for r in caplog.records if r.getMessage() == "retention refused: clock_doubt"
    ]
    if refused:
        assert survivors(fresh, w) == labels(w)  # nothing deleted at all
        with m.owner(fresh) as c:
            assert m.audit_ids(c) == ids
        assert {r.skipped for r in res.values()} == {"clock_doubt"}
        assert len(doubts) == 1 and doubts[0].levelno == logging.WARNING
        assert records(caplog, "retention step done") == []
    else:
        assert doubts == [] and res["scans"].skipped is None
        assert res["scans"].deleted >= 2


def test_a_failing_clock_check_propagates(
    fresh: PgServer, rdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = aged(fresh)

    def down(conn: Any) -> datetime:
        raise RuntimeError("database clock unreadable")

    monkeypatch.setattr(rt, "db_now", down)
    with pytest.raises(RuntimeError):
        task.run_retention(rdb, w.now, shipped_through=m.shipped(None))
    monkeypatch.undo()
    assert survivors(fresh, w) == labels(w)


# ------------------------------------------------- CHK-M11-189 (future rows)


@pytest.mark.parametrize("step", list(RULE))
def test_a_future_row_skips_only_its_step(fresh: PgServer, rdb: Any, step: str) -> None:
    w = aged(fresh)
    with m.future_row(fresh, step, w.now, timedelta(days=2)):
        res = run(rdb, w.now)
    assert (res[step].skipped, res[step].deleted) == ("future_rows", 0)
    assert all(r.skipped is None for s, r in res.items() if s != step)
    assert survivors(fresh, w) == expected(w, skip=RULE[step])


def test_a_live_api_token_does_not_skip_the_tokens_step(
    fresh: PgServer, rdb: Any
) -> None:
    """Lead's correction (a): the probe is created_at, so a token expiring in
    300 days (live API token) never skips the step."""
    w = aged(fresh)
    res = run(rdb, w.now)
    assert (res["tokens"].skipped, res["tokens"].deleted) == (None, 3)


# ------------------------------------------------- CHK-M11-190, -191


def test_no_ddl_no_other_writes_counts_only_logs(
    fresh: PgServer,
    rdb: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = aged(fresh)
    ids = m.audit_chain(fresh, [old_at(w.now)] * 3)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    caplog.set_level(logging.DEBUG)
    run(rdb, w.now, shipped=ids[-1])
    monkeypatch.undo()
    for text in spy.statements:
        first = text.strip().split(None, 1)[0].upper()
        assert first not in m.DDL_VERBS and first != "UPDATE", text[:60]
        if first == "INSERT":
            assert text.upper().startswith("INSERT INTO AUDIT_LOG"), text[:60]
    with m.owner(fresh) as c:
        actions = {str(r[0]) for r in c.execute("SELECT action FROM audit_log")}
    assert actions == {"audit.checkpoint"}
    done = records(caplog, "retention step done")
    assert [d["step"] for d in done] == list(STEPS)
    assert all(set(d) == {"step", "deleted", "chunks", "skipped"} for d in done)
    texts = [r.getMessage() for r in caplog.records]
    texts += [str(r.__dict__) for r in caplog.records]
    assert m.hits(texts) == []  # OUT, ERR, EXEC, EXP planted in the deleted rows
    gone = [w.key("scan", "old"), w.key("scan", "past"), *w.scan_jobs["old"]]
    assert not [g for g in gone if any(str(g) in t for t in texts)]


# ------------------------------------------------------------------ CHK-M11-171


def test_locked_scans_at_the_head_do_not_stall_the_step(
    fresh: PgServer, rdb: Any
) -> None:
    """Lead's row from the TASK-237 review: more than a chunk of scans whose
    re-evaluation lock is held, oldest first, with deletable scans behind
    them. One run (a) ends within a bounded number of chunks, (b) deletes
    every deletable scan behind them, (c) leaves the locked ones for the
    next run."""
    now = m.now_utc()
    n_locked = rules.SCAN_CHUNK + 1
    with m.owner(fresh) as c:
        pol = m.make_policy(c, 1)
        a = m.host(c, at=now)
        oldest = now - timedelta(days=900)
        locked = [
            m.scan(c, pol, [a.agent_id], created_at=oldest + timedelta(seconds=i))
            for i in range(n_locked)
        ]
        behind = [
            m.scan(c, pol, [a.agent_id], created_at=now - timedelta(days=500 - i))
            for i in range(50)
        ]
        young = m.scan(c, pol, [a.agent_id], created_at=now - timedelta(days=10))
    out: dict[str, Any] = {}
    with m.tx_conn(fresh, "bitscan_app") as holder:
        for s in locked:  # M8's own lock, one session
            assert m8_reeval.lock_scan(holder, s) is not None

        def go() -> None:
            out["res"] = run(rdb, now)

        t = threading.Thread(target=go)
        t.start()
        t.join(120)
        assert not t.is_alive(), "(a) the scans step did not end"
        res = out["res"]["scans"]
        present = scan_ids(fresh)
        # (a) chunks counts committed deleting transactions: one here, as all
        # 50 fit in the chunk after the locked ones
        assert res.chunks <= -(-(n_locked + len(behind)) // rules.SCAN_CHUNK)
        assert not present & set(behind) and res.deleted == len(behind)  # (b)
        assert present == set(locked) | {young}  # (c)
    second = run(rdb, now)  # lock released
    assert second["scans"].deleted == n_locked
    assert scan_ids(fresh) == {young}
