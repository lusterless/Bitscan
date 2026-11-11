"""TASK-237 and TASK-238 TEST: the retention repositories on PostgreSQL, as
bitscan_retention, and refused as bitscan_app (TP-M11-06; CHK-M11-135 to
-144).

Expected values: TS §5.3 L1049 (what is deleted: whole scans after 400 days,
snapshots after 180, decided requests and expired tokens after 90, inventory
jobs 30 days after they finish, unreferenced packages; audit after 3 years),
L1051 (bitscan_retention deletes only from the retention tables), TS §5.2
L1002-L1006 (grants; ON DELETE CASCADE from scan to jobs, results and
re-evaluations), #150 (a)-(g), (j), (k) (strict `<` cutoffs; chunks; pending
requests never deleted; tokens by expires_at, revoked or not; the future-row
probe columns, user_token.created_at by the lead's correction of 2026-11-08;
the per-scan M8 re-evaluation lock; no row lock in scan_chunk, lead's
correction 2026-11-08), #39 and #150 (d) (the audit prefix delete is by id
`<= N`). Each test starts from emptied retention tables (as owner), so
counts are exact; inputs come from the TP-M11-01 builder, expectations from
the rules above.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from bitscan_manager.repositories import reeval as m8_reeval
from bitscan_manager.repositories import retention as rt
from bitscan_manager.repositories import retention_audit as ra
from bitscan_manager.services.retention import rules

from . import m11_pg_fixtures as m
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

DELETES = (
    "delete_inventory_jobs",
    "delete_snapshots",
    "delete_requests",
    "delete_tokens",
)
RULE_OF = {
    "delete_inventory_jobs": "inventory_job",
    "delete_snapshots": "snapshot",
    "delete_requests": "request",
    "delete_tokens": "token",
}
# TS §5.3 L1049 / #150: which labels of m.aged_world each delete must remove
GONE = {
    "inventory_job": {"past", "old"},
    "snapshot": {"past", "old"},
    "request": {"past", "old"},
    "token": {"past", "old", "revoked_past"},
    "package": {"unreferenced", "unreferenced2"},
    "scan": {"past", "old"},
}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("retention-repo")) as s:
        yield s


@pytest.fixture
def fresh(server: PgServer) -> PgServer:
    """Empty retention tables (and what references them), as owner."""
    with m.owner(server) as c:
        c.execute(
            "TRUNCATE scan, scan_job, scan_result, scan_result_reeval,"
            " inventory_snapshot, enrollment_request, enrollment_token, user_token,"
            " package, agent_package, os_info, audit_log CASCADE"
        )
    return server


@pytest.fixture
def ret(fresh: PgServer) -> Iterator[m.Conn]:
    """A bitscan_retention connection in a transaction (the caller commits)."""
    with m.tx_conn(fresh, "bitscan_retention") as c:
        assert c.execute("SELECT current_user").fetchone() == ("bitscan_retention",)
        yield c


def aged(server: PgServer) -> m.AgedWorld:
    with m.owner(server) as c:
        return m.aged_world(c, m.now_utc())


def cutoff(w: m.AgedWorld, rule: str) -> datetime:
    return w.now - m.AGES[rule]


def survivors(server: PgServer, w: m.AgedWorld, rule: str) -> set[str]:
    with m.owner(server) as c:
        return {lab for (r, lab), ok in m.present(c, w).items() if r == rule and ok}


def labels(w: m.AgedWorld, rule: str) -> set[str]:
    return {lab for (r, lab) in w.rows if r == rule}


# ------------------------------------------------------------ CHK-M11-135


@pytest.mark.parametrize("fn", DELETES)
def test_each_delete_removes_exactly_the_rows_past_its_cutoff(
    fresh: PgServer, ret: m.Conn, fn: str
) -> None:
    w = aged(fresh)
    rule = RULE_OF[fn]
    with m.owner(fresh) as c:
        kept = m.checksums(c)
    n = getattr(rt, fn)(ret, cutoff(w, rule), 10_000)
    ret.commit()
    assert n == len(GONE[rule])
    assert survivors(fresh, w, rule) == labels(w, rule) - GONE[rule]
    # the boundary: exactly at the cutoff stays, 1 µs older goes (REQ-274 (1))
    assert "at" in survivors(fresh, w, rule)
    # nothing of another rule is touched (G2 data included)
    for other in ("scan", "inventory_job", "snapshot", "request", "token", "package"):
        if other != rule:
            assert survivors(fresh, w, other) == labels(w, other), other
    with m.owner(fresh) as c:
        assert m.checksums(c) == kept
    # a second call finds nothing left
    assert getattr(rt, fn)(ret, cutoff(w, rule), 10_000) == 0


def test_specific_keeps(fresh: PgServer, ret: m.Conn) -> None:
    """#150 (c), (b), (e) at a cutoff 10 years ahead: a pending request
    whatever its age, an unfinished inventory job and a compliance job
    finished long ago stay; every token goes, revoked or not. (The
    revoked-not-expired and live API tokens at the real cutoff: the
    `delete_tokens` case of the test above.)"""
    w = aged(fresh)
    for fn in DELETES:
        getattr(rt, fn)(ret, w.now + timedelta(days=3650), 10_000)  # a far cutoff
    ret.commit()
    with m.owner(fresh) as c:
        p = m.present(c, w)
    assert p[("request", "pending")]
    assert p[("inventory_job", "unfinished")]
    assert p[("inventory_job", "compliance")]
    # every token expires before now + 10 years: all go, revoked or not
    assert not any(ok for (r, _), ok in p.items() if r == "token")


def test_undecided_request_stays_even_with_a_decided_at(
    fresh: PgServer, ret: m.Conn
) -> None:
    """TS §5.3 L1049 deletes *decided* requests. The DDL does not tie
    `decided_at` to `decision`, so a row with an old `decided_at` and no
    decision is still undecided and stays (CHK-M11-401)."""
    now = m.now_utc()
    with m.owner(fresh) as c:
        a = m.host(c, at=now)
        tok = m.enrolment_token(c, at=now)
        odd = m.request(
            c,
            a.agent_id,
            tok,
            requested_at=now - timedelta(days=500),
            decided_at=now - timedelta(days=400),
        )
        done = m.request(
            c,
            a.agent_id,
            tok,
            requested_at=now - timedelta(days=500),
            decision="rejected",
            decided_at=now - timedelta(days=400),
        )
    assert rt.delete_requests(ret, now - timedelta(days=90), 10_000) == 1
    ret.commit()
    with m.owner(fresh) as c:
        left = {
            int(r[0])
            for r in c.execute("SELECT request_id FROM enrollment_request").fetchall()
        }
    assert left == {odd} and done not in left


@pytest.mark.parametrize("fn", [*DELETES, "delete_packages"])
def test_at_most_one_chunk_per_call(fresh: PgServer, ret: m.Conn, fn: str) -> None:
    w = aged(fresh)
    rule = "package" if fn == "delete_packages" else RULE_OF[fn]

    def call(n: int) -> int:
        if fn == "delete_packages":
            return int(rt.delete_packages(ret, n))
        return int(getattr(rt, fn)(ret, cutoff(w, rule), n))

    want = len(GONE[rule])
    assert want >= 2
    got = [call(1) for _ in range(want + 1)]
    assert got == [1] * want + [0]
    ret.commit()
    assert survivors(fresh, w, rule) == labels(w, rule) - GONE[rule]


def test_packages_only_unreferenced(fresh: PgServer, ret: m.Conn) -> None:
    w = aged(fresh)
    with m.owner(fresh) as c:
        kept = m.checksums(c, ("os_info", "agent_package"))
    assert rt.delete_packages(ret, 10_000) == 2
    ret.commit()
    assert survivors(fresh, w, "package") == {"referenced"}
    with m.owner(fresh) as c:
        assert m.checksums(c, ("os_info", "agent_package")) == kept


def test_refuses_a_naive_cutoff_and_a_chunk_below_one(ret: m.Conn) -> None:
    naive = datetime(2020, 1, 1)  # noqa: DTZ001 - the refused input
    aware = datetime(2020, 1, 1, tzinfo=UTC)
    for fn in DELETES:
        with pytest.raises(ValueError):
            getattr(rt, fn)(ret, naive, 10)
        for n in (0, -1):
            with pytest.raises(ValueError):
                getattr(rt, fn)(ret, aware, n)
    with pytest.raises(ValueError):
        rt.scan_chunk(ret, naive, 10)
    with pytest.raises(ValueError):
        rt.scan_chunk(ret, aware, 0)
    with pytest.raises(ValueError):
        rt.delete_packages(ret, 0)


# ------------------------------------------------------------ CHK-M11-136


def test_scan_chunk_oldest_first_at_most_n_no_row_lock(
    fresh: PgServer, ret: m.Conn
) -> None:
    w = aged(fresh)
    old, past = w.key("scan", "old"), w.key("scan", "past")
    with m.owner(fresh) as c:  # two scans tied on created_at, older still
        pol = m.make_policy(c, 1)
        tie_at = w.now - timedelta(days=700)
        ties = sorted(
            (
                m.scan(c, pol, [w.agents[0].agent_id], created_at=tie_at)
                for _ in range(2)
            ),
            key=lambda u: u.int,
        )
    cut = cutoff(w, "scan")
    assert rt.scan_chunk(ret, cut, 100) == [*ties, old, past]
    assert rt.scan_chunk(ret, cut, 1) == [ties[0]]
    assert rt.scan_chunk(ret, cut, 3) == [*ties, old]
    assert rt.scan_chunk(ret, w.now - timedelta(days=5000), 100) == []
    # no row lock held by the retention transaction: another session locks
    # the same rows at once (NOWAIT) while it is still open
    with m.tx_conn(fresh, "bitscan_migrate", set_role="bitscan_owner") as oc:
        oc.execute(
            "SELECT scan_id FROM scan WHERE scan_id = ANY(%s) FOR UPDATE NOWAIT",
            ([*ties, old, past],),
        )
    locks = ret.execute(
        "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()"
        " AND locktype = 'transactionid'"
    ).fetchone()
    assert locks == (0,)  # nothing written, no xid taken


# ------------------------------------------------------------ CHK-M11-137


def test_delete_scans_removes_whole_scans_only(fresh: PgServer, ret: m.Conn) -> None:
    w = aged(fresh)
    gone = [w.key("scan", lab) for lab in ("old", "past")]
    with m.owner(fresh) as c:
        before = {
            lab: m.scan_remains(c, w.key("scan", lab), w.scan_jobs[lab])
            for lab in ("inside", "at", "old", "past")
        }
    # each aged scan: 1 scan, 2 originals + 2 retries, 4 results in two
    # partitions, 2 re-evaluation rows
    whole = {"scan": 1, "scan_job": 4, "scan_result": 4, "scan_result_reeval": 2}
    assert all(v == whole for v in before.values()), before
    spy = m.RoleSpy()
    mp = pytest.MonkeyPatch()
    spy.install(mp)
    try:
        assert rt.delete_scans(ret, gone) == 2
    finally:
        mp.undo()
    assert len(spy.statements) == 1  # one statement: the cascades do the rest
    ret.commit()
    with m.owner(fresh) as c:
        for lab in ("old", "past"):
            assert m.scan_remains(
                c, w.key("scan", lab), w.scan_jobs[lab]
            ) == dict.fromkeys(
                ("scan", "scan_job", "scan_result", "scan_result_reeval"), 0
            )
        for lab in ("inside", "at"):
            assert (
                m.scan_remains(c, w.key("scan", lab), w.scan_jobs[lab]) == before[lab]
            )
    assert rt.delete_scans(ret, []) == 0
    assert rt.delete_scans(ret, [uuid4()]) == 0


def test_delete_scan_whose_partitions_were_dropped(
    fresh: PgServer, ret: m.Conn
) -> None:
    """#44: db maintain dropped the scan's result partitions; the scan row and
    its jobs still go."""
    now = m.now_utc()
    created = now - timedelta(days=900)
    with m.owner(fresh) as c:
        pol = m.make_policy(c, 2)
        a = m.host(c, at=now)
        parts = [
            m.ensure_partition(c, created),
            m.ensure_partition(c, created + timedelta(days=32)),
        ]
        assert len(set(parts)) == 2
        sid = m.scan(c, pol, [a.agent_id], created_at=created, state="completed")
        orig = m.job(c, sid, a.agent_id, pol, state="partial", created_at=created)
        retry = m.job(
            c,
            sid,
            a.agent_id,
            pol,
            pol.plugins[1:],
            state="completed",
            created_at=created + timedelta(days=32),
            retry_of=orig.job_id,
        )
        m.result(c, orig, pol, pol.plugins[0])
        m.result(c, retry, pol, pol.plugins[1])
        for p in parts:
            c.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(p)))
        jobs = [orig.job_id, retry.job_id]
        assert m.scan_remains(c, sid, jobs)["scan_result"] == 0
    assert rt.delete_scans(ret, [sid]) == 1
    ret.commit()
    with m.owner(fresh) as c:
        assert m.scan_remains(c, sid, jobs) == dict.fromkeys(
            ("scan", "scan_job", "scan_result", "scan_result_reeval"), 0
        )


def test_scans_step_runs_as_bitscan_retention(fresh: PgServer, ret: m.Conn) -> None:
    """Lead's correction (b), 2026-11-08: the scans step's statements (chunk,
    lock, delete) run fine as bitscan_retention in one transaction."""
    w = aged(fresh)
    ids = rt.scan_chunk(ret, cutoff(w, "scan"), 100)
    locked = [s for s in ids if rt.try_reeval_lock(ret, s)]
    assert locked == ids and len(ids) == 2
    assert rt.delete_scans(ret, locked) == 2
    ret.commit()
    assert survivors(fresh, w, "scan") == {"inside", "at"}


# ------------------------------------------------------------ CHK-M11-138


def test_try_reeval_lock(fresh: PgServer, ret: m.Conn) -> None:
    w = aged(fresh)
    held, other = w.key("scan", "old"), w.key("scan", "past")
    with m.holding_reeval_lock(fresh, held):  # M8's own lock_scan, another session
        assert rt.try_reeval_lock(ret, held) is False
        assert rt.try_reeval_lock(ret, other) is True  # per scan
    ret.rollback()
    assert rt.try_reeval_lock(ret, held) is True  # free again after release
    # held until the retention transaction ends: M8's lock_scan waits on it
    outcome: dict[str, Any] = {}

    def reevaluate() -> None:
        with m.tx_conn(fresh, "bitscan_app") as ac:
            ac.execute("SET lock_timeout = '300ms'")
            try:
                m8_reeval.lock_scan(ac, held)
                outcome["got"] = True
            except psycopg.errors.LockNotAvailable:
                outcome["got"] = False

    t = threading.Thread(target=reevaluate)
    t.start()
    t.join(10)
    assert outcome == {"got": False}
    ret.rollback()  # the lock ends with the transaction (xact-level)
    with m.tx_conn(fresh, "bitscan_app") as ac:
        ac.execute("SET lock_timeout = '2s'")
        assert m8_reeval.lock_scan(ac, held) is not None


def test_try_reeval_lock_refuses_autocommit(fresh: PgServer) -> None:
    with fresh.connect("bitscan_retention") as c:
        assert c.autocommit
        with pytest.raises(RuntimeError):
            rt.try_reeval_lock(c, uuid4())


# ------------------------------------------------------------ CHK-M11-139


def test_newest_per_probe_column(fresh: PgServer, ret: m.Conn) -> None:
    for table in (
        "scan",
        "scan_job",
        "inventory_snapshot",
        "enrollment_request",
        "user_token",
    ):
        assert rt.newest(ret, table) is None, table
    ret.rollback()
    w = aged(fresh)
    now = w.now
    with m.owner(fresh) as c:  # a compliance job finished 2 days ahead: not probed
        pol = m.make_policy(c, 1)
        sid = m.scan(c, pol, [w.agents[0].agent_id], created_at=now - timedelta(days=1))
        m.job(
            c,
            sid,
            w.agents[0].agent_id,
            pol,
            state="completed",
            created_at=now - timedelta(days=1),
            finished_at=now + timedelta(days=2),
        )
    assert rt.newest(ret, "scan") == now - timedelta(days=1)
    assert rt.newest(ret, "scan_job") == now - timedelta(days=29)  # inventory only
    assert rt.newest(ret, "inventory_snapshot") == now - timedelta(days=179)
    assert rt.newest(ret, "enrollment_request") == now - timedelta(days=89)
    # created_at (lead's correction (a)): the live tokens were created 65 days
    # ago; their expires_at (300 days ahead) is not the probe
    assert rt.newest(ret, "user_token") == now - timedelta(days=65)


def test_newest_unknown_table_raises_before_sql(
    ret: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    for bad in ("audit_log", "agent", "scan; DROP TABLE scan", "SCAN", ""):
        with pytest.raises(ValueError):
            rt.newest(ret, bad)  # type: ignore[arg-type]
    assert spy.statements == []


def test_token_probe_decides_the_tokens_step(fresh: PgServer, ret: m.Conn) -> None:
    """Lead's correction (a), with TASK-236's future_rows: a live API token
    (expiring in 300 days) does not skip the tokens step; a token created 2
    days ahead does."""
    w = aged(fresh)
    assert rules.future_rows(rt.newest(ret, "user_token"), w.now) is False
    ret.rollback()
    with m.future_row(fresh, "tokens", w.now, timedelta(days=2)):
        assert rules.future_rows(rt.newest(ret, "user_token"), w.now) is True
        ret.rollback()
    assert rules.future_rows(rt.newest(ret, "user_token"), w.now) is False


# ------------------------------------------------------------ CHK-M11-140


def test_db_now_is_the_transaction_clock(ret: m.Conn) -> None:
    server_now = ret.execute("SELECT now()").fetchone()
    first = rt.db_now(ret)
    assert server_now is not None and first == server_now[0]
    assert first.tzinfo is not None
    assert abs(first - m.now_utc()) < timedelta(minutes=1)
    assert rt.db_now(ret) == first  # transaction start time
    ret.rollback()


# ------------------------------------------------------------ CHK-M11-143


def test_tokens_91_days_deleted_89_kept_with_a_live_api_token(
    fresh: PgServer, ret: m.Conn
) -> None:
    now = m.now_utc()
    with m.owner(fresh) as c:
        uid = m.make_user(c, "operator", at=now)
        live = m.token_row(
            c,
            uid,
            kind="api",
            expires_at=now + timedelta(days=300),
            created_at=now - timedelta(days=65),
        )
        d91 = m.token_row(c, uid, expires_at=now - timedelta(days=91))
        d89 = m.token_row(c, uid, expires_at=now - timedelta(days=89))
    assert rules.future_rows(rt.newest(ret, "user_token"), now) is False
    assert rt.delete_tokens(ret, now - timedelta(days=90), 10_000) == 1
    ret.commit()
    with m.owner(fresh) as c:
        left = {
            int(r[0]) for r in c.execute("SELECT token_id FROM user_token").fetchall()
        }
    assert left == {live, d89} and d91 not in left


# ------------------------------------------------------------ CHK-M11-141


def ago(now: datetime, years: int = 0, days: int = 0) -> datetime:
    return rules.minus_years(now, years) - timedelta(days=days)


def test_audit_oldest_row_hash_and_delete_through(fresh: PgServer) -> None:
    now = m.now_utc()
    ats = [
        ago(now, 4),
        ago(now, 4, 1),
        ago(now, days=1),
        ago(now, 5),
        ago(now, 4),
        ago(now, 3, 2),
    ]
    ids = m.audit_chain(fresh, ats)
    with m.tx_conn(fresh, "bitscan_retention") as c:
        got = ra.oldest(c, 100)
        assert [i for i, _ in got] == ids
        assert [at for _, at in got] == ats
        assert ra.oldest(c, 2) == got[:2]
        with m.owner(fresh) as oc:
            for i in ids:
                assert ra.row_hash(c, i) == m.row_hash_of(oc, i)
        with pytest.raises(LookupError):
            ra.row_hash(c, ids[-1] + 1000)
        with pytest.raises(ValueError):
            ra.oldest(c, 0)
        assert ra.delete_through(c, ids[2]) == 3
        assert [i for i, _ in ra.oldest(c, 100)] == ids[3:]
        c.commit()
    with m.owner(fresh) as oc:
        assert m.audit_ids(oc) == ids[3:]


def test_audit_delete_through_with_gaps(fresh: PgServer) -> None:
    now = m.now_utc()
    first = m.audit_chain(fresh, [ago(now, 4)] * 2)
    with m.owner(fresh) as oc:  # a gap in ids (sequence moved on)
        oc.execute("SELECT setval('audit_log_audit_id_seq', %s)", (first[-1] + 50,))
    second = m.audit_chain(fresh, [ago(now, 4)] * 2)
    assert second[0] > first[-1] + 1
    with m.tx_conn(fresh, "bitscan_retention") as c:
        assert ra.delete_through(c, first[-1] + 10) == 2  # an id not stored
        assert [i for i, _ in ra.oldest(c, 10)] == second
        assert ra.delete_through(c, first[0] - 1) == 0
        c.commit()


def test_audit_delete_through_refuses_autocommit(fresh: PgServer) -> None:
    ids = m.audit_chain(fresh, [ago(m.now_utc(), 4)])
    with fresh.connect("bitscan_retention") as c:
        with pytest.raises(RuntimeError):
            ra.delete_through(c, ids[0])
    with m.owner(fresh) as oc:
        assert m.audit_ids(oc) == ids


# ------------------------------------------------------------ CHK-M11-142


def test_bitscan_app_is_refused_every_delete(fresh: PgServer) -> None:
    w = aged(fresh)
    ids = m.audit_chain(fresh, [ago(w.now, 4)])
    far = w.now + timedelta(days=3650)
    calls: dict[str, Any] = {
        "delete_scans": lambda c: rt.delete_scans(c, [w.key("scan", "old")]),
        "delete_inventory_jobs": lambda c: rt.delete_inventory_jobs(c, far, 10),
        "delete_snapshots": lambda c: rt.delete_snapshots(c, far, 10),
        "delete_requests": lambda c: rt.delete_requests(c, far, 10),
        "delete_tokens": lambda c: rt.delete_tokens(c, far, 10),
        "delete_packages": lambda c: rt.delete_packages(c, 10),
        "delete_through": lambda c: ra.delete_through(c, ids[0]),
    }
    with m.owner(fresh) as oc:
        before = m.checksums(oc, m.RETENTION_TABLES)
    refused: list[str] = []
    for name, call in calls.items():
        with m.tx_conn(fresh, "bitscan_app") as c:
            try:
                call(c)
            except psycopg.errors.InsufficientPrivilege:
                refused.append(name)
            c.rollback()
            # the reads need no more than SELECT (or no privilege at all)
            assert rt.db_now(c) is not None
            assert rt.newest(c, "scan") is not None
            assert rt.scan_chunk(c, far, 1) != []
            assert rt.try_reeval_lock(c, w.key("scan", "old")) is True
            assert ra.oldest(c, 1)[0][0] == ids[0]
    assert refused == list(calls)
    with m.owner(fresh) as oc:
        assert m.checksums(oc, m.RETENTION_TABLES) == before


# ------------------------------------------------------------ CHK-M11-144


def test_statements_parameterised_select_or_delete_only(
    fresh: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = aged(fresh)
    ids = m.audit_chain(fresh, [ago(w.now, 4)])
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    with m.tx_conn(fresh, "bitscan_retention") as c:
        rt.db_now(c)
        for t in (
            "scan",
            "scan_job",
            "inventory_snapshot",
            "enrollment_request",
            "user_token",
        ):
            rt.newest(c, t)
        chunk = rt.scan_chunk(c, cutoff(w, "scan"), 100)
        for s in chunk:
            rt.try_reeval_lock(c, s)
        rt.delete_scans(c, chunk)
        for fn in DELETES:
            getattr(rt, fn)(c, cutoff(w, RULE_OF[fn]), 10_000)
        rt.delete_packages(c, 10_000)
        ra.oldest(c, 10)
        ra.row_hash(c, ids[0])
        ra.delete_through(c, ids[0])
        c.rollback()
    monkeypatch.undo()
    assert len(chunk) == 2
    # db_now, 5 probes, the chunk, a lock per scan, the scan delete, 4 deletes,
    # packages, and the 3 audit statements
    assert len(spy.statements) == 1 + 5 + 1 + len(chunk) + 1 + 4 + 1 + 3
    assert set(spy.roles) == {"bitscan_retention"}
    secrets_in_sql = [str(s) for s in chunk]
    secrets_in_sql += [cutoff(w, r).isoformat()[:10] for r in m.AGES]
    for text in spy.statements:
        upper = text.upper()
        first = upper.split(None, 1)[0]
        assert first in {"SELECT", "DELETE"}, text[:60]
        words = set(upper.replace("(", " ").replace(")", " ").replace(",", " ").split())
        assert not words & {
            "INSERT",
            "UPDATE",
            "CREATE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "GRANT",
        }
        assert " FOR UPDATE" not in upper and " FOR SHARE" not in upper
        assert not [s for s in secrets_in_sql if s in text], text[:80]
