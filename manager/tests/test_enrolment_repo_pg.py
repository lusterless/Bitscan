"""TASK-052: enrollment_token and enrollment_request repository on PostgreSQL.

Checks CHK-M3-060 to CHK-M3-065 of tests/m3/test-plan.md (TP-M3-06). Every call
runs as bitscan_app on a freshly migrated database. Expected values: TS §3.2
L181-L192 (max_uses with an atomic increment; not expired or revoked; source IP
inside allowed_cidrs when set, NULL = any source; matches by hostname or
machine-id), TS §5.2 L748-L777 (CHECK uses <= max_uses; no DELETE grant),
#59 (one refusal for every cause), #64 (requests decided once each), #68
(states pending, decided, all), #26 (rejected new enrolment).
"""

import hashlib
import secrets
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import errors

from bitscan_manager.repositories.enrolment import (
    EnrolmentRepo,
    EnrolmentTokenRow,
    MatchRow,
    RequestRow,
)

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def h() -> str:
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def token(
    conn: Conn,
    *,
    max_uses: int = 1,
    cidrs: list[str] | None = None,
    expires: datetime = T0 + timedelta(hours=24),
    auto: bool = False,
) -> tuple[int, str]:
    th = h()
    with conn.transaction():
        tid = EnrolmentRepo(conn).insert_token(
            token_hash=th,
            max_uses=max_uses,
            auto_approve=auto,
            allowed_cidrs=cidrs,
            expires_at=expires,
            created_by=1,
            now=T0,
        )
    return tid, th


def uses(conn: Conn, tid: int) -> int:
    row = conn.execute("SELECT uses FROM enrollment_token WHERE token_id = %s", (tid,))
    got = row.fetchone()
    assert got is not None
    return int(got[0])


def agent(
    conn: Conn,
    *,
    hostname: str = "h",
    machine: str | None = None,
    status: str = "awaiting_approval",
) -> UUID:
    row = conn.execute(
        "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
        " token_issued_at, token_expires_at, status) VALUES (%s, %s, '1', %s, %s, %s,"
        " CAST(%s AS agent_status)) RETURNING agent_id",
        (
            machine or secrets.token_hex(16),
            hostname,
            h(),
            T0,
            T0 + timedelta(days=365),
            status,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def request(
    conn: Conn,
    agent_id: UUID,
    tid: int,
    *,
    kind: str = "new",
    hostname: str = "h",
    machine: str | None = None,
    new_hash: str | None = None,
) -> int:
    return EnrolmentRepo(conn).insert_request(
        kind=kind,
        agent_id=agent_id,
        token_id=tid,
        hostname=hostname,
        machine_id=machine or secrets.token_hex(16),
        os_pretty_name="Ubuntu 24.04.1 LTS",
        agent_version="1.0.0",
        new_token_hash=new_hash or h(),
        token_expires_at=T0 + timedelta(days=365),
        source_ip="2001:db8::5",
        now=T0,
    )


# ------------------------------------------------------------ token rows


def test_insert_and_read_token_without_hash(conn: Conn) -> None:
    tid, th = token(conn, max_uses=7, cidrs=["10.0.0.0/8", "2001:db8::/32"], auto=True)
    row = EnrolmentRepo(conn).get_token(tid)
    assert isinstance(row, EnrolmentTokenRow)
    assert (row.token_id, row.max_uses, row.uses, row.auto_approve) == (tid, 7, 0, True)
    assert row.allowed_cidrs == ["10.0.0.0/8", "2001:db8::/32"]
    assert (row.expires_at, row.revoked_at, row.created_by, row.created_at) == (
        T0 + timedelta(hours=24),
        None,
        1,
        T0,
    )
    assert "token_hash" not in EnrolmentTokenRow.__dataclass_fields__
    assert th not in repr(row)
    stored = conn.execute(
        "SELECT token_hash FROM enrollment_token WHERE token_id = %s", (tid,)
    ).fetchone()
    assert stored == (th,)
    assert EnrolmentRepo(conn).get_token(-1) is None


def test_null_cidrs_read_back_as_none(conn: Conn) -> None:
    tid, _ = token(conn)
    row = EnrolmentRepo(conn).get_token(tid)
    assert row is not None and row.allowed_cidrs is None


def test_token_page_keyset(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    with conn.transaction(force_rollback=True):
        ids = [token(conn)[0] for _ in range(5)]
        got: list[int] = []
        after = ids[0] - 1
        while True:
            page = repo.token_page(2, after)
            got.extend(r.token_id for r in page if r.token_id in ids)
            if len(page) < 2:
                break
            after = page[-1].token_id
        assert got == ids
        assert repo.token_page(1, None)


def test_revoke_keeps_the_row_and_the_first_time(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    tid, th = token(conn, max_uses=3)
    with conn.transaction():
        assert repo.revoke_token(tid, T0) is True
        assert repo.revoke_token(tid, T0 + SEC) is True  # a second DELETE: still ok
        assert repo.revoke_token(-1, T0) is False
    row = repo.get_token(tid)
    assert row is not None and row.revoked_at == T0
    with conn.transaction():
        assert repo.use_token(th, "192.0.2.1", T0) is None
    assert uses(conn, tid) == 0


def test_revoke_active_token_is_true_only_for_the_call_that_revoked(
    conn: Conn,
) -> None:
    """TASK-066 r1: the conditional revoke the service audits on."""
    repo = EnrolmentRepo(conn)
    tid, th = token(conn, max_uses=3)
    with conn.transaction():
        assert repo.revoke_active_token(tid, T0) is True
        assert repo.revoke_active_token(tid, T0 + SEC) is False
        assert repo.revoke_active_token(-1, T0) is False
    row = repo.get_token(tid)
    assert row is not None and row.revoked_at == T0  # the first time is kept
    with conn.transaction():
        assert repo.use_token(th, "192.0.2.1", T0) is None


# ------------------------------------------------------------ CHK-M3-060


def _race(db: PgServer, threads: int, max_uses: int) -> tuple[int, int]:
    with db.connect("bitscan_app") as c:
        tid, th = token(c, max_uses=max_uses)
    barrier = threading.Barrier(threads)
    wins: list[bool] = []
    lock = threading.Lock()
    errs: list[BaseException] = []

    def go() -> None:
        try:
            with db.connect("bitscan_app") as cx:
                barrier.wait(15)
                with cx.transaction():
                    got = EnrolmentRepo(cx).use_token(th, "192.0.2.50", T0)
                with lock:
                    wins.append(got is not None)
        except BaseException as e:  # noqa: BLE001 - reported below
            errs.append(e)

    ts = [threading.Thread(target=go) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert not errs, errs
    with db.connect("bitscan_app") as c:
        return wins.count(True), uses(c, tid)


def test_twenty_concurrent_uses_of_a_five_use_token(db: PgServer) -> None:
    """REQ-068 (2): exactly 5 succeed, uses ends at 5 (repeated)."""
    for _ in range(5):
        assert _race(db, 20, 5) == (5, 5)


def test_single_use_token_under_a_race(db: PgServer) -> None:
    assert _race(db, 10, 1) == (1, 1)


def test_use_returns_the_token_id_and_auto_approve(conn: Conn) -> None:
    tid, th = token(conn, max_uses=2, auto=True)
    with conn.transaction():
        got = EnrolmentRepo(conn).use_token(th, "192.0.2.1", T0)
    assert got is not None and (got.token_id, got.auto_approve) == (tid, True)
    assert uses(conn, tid) == 1


# ------------------------------------------------------------ CHK-M3-061


@pytest.mark.parametrize(
    "case",
    ["at-expiry", "after-expiry", "revoked", "exhausted", "unknown", "outside-cidr"],
)
def test_refused_uses_return_none_and_do_not_increment(conn: Conn, case: str) -> None:
    repo = EnrolmentRepo(conn)
    expires = T0 + timedelta(hours=1)
    tid, th = token(
        conn,
        max_uses=2,
        expires=expires,
        cidrs=["10.0.0.0/8"] if case == "outside-cidr" else None,
    )
    now, ip, key = T0, "10.1.2.3", th
    if case == "at-expiry":
        now = expires
    elif case == "after-expiry":
        now = expires + SEC
    elif case == "revoked":
        with conn.transaction():
            repo.revoke_token(tid, T0)
    elif case == "exhausted":
        with conn.transaction():
            assert repo.use_token(th, ip, T0) and repo.use_token(th, ip, T0)
    elif case == "unknown":
        key = h()
    elif case == "outside-cidr":
        ip = "192.168.1.1"
    before = uses(conn, tid)
    with conn.transaction():
        assert repo.use_token(key, ip, now) is None
    assert uses(conn, tid) == before


def test_accepted_one_second_before_expiry(conn: Conn) -> None:
    expires = T0 + timedelta(hours=1)
    tid, th = token(conn, expires=expires)
    with conn.transaction():
        assert EnrolmentRepo(conn).use_token(th, "192.0.2.1", expires - SEC) is not None
    assert uses(conn, tid) == 1


def test_lookup_by_raw_token_is_no_match(conn: Conn) -> None:
    raw = "bse_" + secrets.token_urlsafe(32)
    th = hashlib.sha256(raw.encode()).hexdigest()
    with conn.transaction():
        EnrolmentRepo(conn).insert_token(
            token_hash=th,
            max_uses=1,
            auto_approve=False,
            allowed_cidrs=None,
            expires_at=T0 + SEC * 99,
            created_by=1,
            now=T0,
        )
        assert EnrolmentRepo(conn).use_token(raw, "192.0.2.1", T0) is None


# ------------------------------------------------------------ CHK-M3-062


@pytest.mark.parametrize(
    ("cidrs", "ip", "ok"),
    [
        (["10.0.0.0/8"], "10.255.0.1", True),
        (["10.0.0.0/8"], "11.0.0.1", False),
        (["192.0.2.0/24"], "192.0.2.255", True),
        (["192.0.2.7/32"], "192.0.2.7", True),
        (["192.0.2.7/32"], "192.0.2.8", False),
        (["2001:db8::/32"], "2001:db8:ffff::1", True),
        (["2001:db8::/32"], "2001:db9::1", False),
        (["10.0.0.0/8", "2001:db8::/32"], "2001:db8::1", True),
        (["10.0.0.0/8", "2001:db8::/32"], "10.0.0.1", True),
        (["10.0.0.0/8", "2001:db8::/32"], "172.16.0.1", False),
        (["2001:db8::/32"], "10.0.0.1", False),
        (["10.0.0.0/8"], "2001:db8::1", False),
        # an IPv4-mapped peer does not match an IPv4 entry at this layer: the
        # service converts it first (plan TASK-067); TASK-067 TEST checks that
        (["10.0.0.0/8"], "::ffff:10.0.0.1", False),
        (None, "203.0.113.9", True),
        (None, "2001:db8::9", True),
    ],
)
def test_cidr_condition(conn: Conn, cidrs: list[str] | None, ip: str, ok: bool) -> None:
    tid, th = token(conn, cidrs=cidrs)
    with conn.transaction():
        got = EnrolmentRepo(conn).use_token(th, ip, T0)
    assert (got is not None) is ok
    assert uses(conn, tid) == (1 if ok else 0)


def test_cidr_with_host_bits_is_refused_by_the_database(conn: Conn) -> None:
    """The column is CIDR[]: the service must validate first (plan, edge cases)."""
    with pytest.raises(errors.InvalidTextRepresentation), conn.transaction():
        EnrolmentRepo(conn).insert_token(
            token_hash=h(),
            max_uses=1,
            auto_approve=False,
            allowed_cidrs=["10.0.0.1/8"],
            expires_at=T0,
            created_by=1,
            now=T0,
        )


# ------------------------------------------------------------ CHK-M3-065 requests


def test_insert_and_find_request(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    tid, _ = token(conn)
    nh = h()
    with conn.transaction():
        aid = agent(conn, hostname="web-9")
        rid = request(conn, aid, tid, hostname="web-9", machine="a" * 32, new_hash=nh)
    row = repo.find_by_new_token_hash(nh)
    assert isinstance(row, RequestRow)
    assert (row.request_id, row.kind, row.agent_id, row.enrollment_token_id) == (
        rid,
        "new",
        aid,
        tid,
    )
    assert (row.hostname, row.machine_id, row.os_pretty_name, row.agent_version) == (
        "web-9",
        "a" * 32,
        "Ubuntu 24.04.1 LTS",
        "1.0.0",
    )
    assert (row.new_token_hash, row.source_ip, row.requested_at) == (
        nh,
        "2001:db8::5",
        T0,
    )
    assert row.token_expires_at == T0 + timedelta(days=365)
    assert (row.decision, row.decided_by, row.decided_at) == (None, None, None)
    assert nh not in repr(row)
    assert repo.find_by_new_token_hash(h()) is None


def test_request_pages_by_state(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    with conn.transaction(force_rollback=True):
        tid, _ = token(conn)
        aid = agent(conn)
        ids = [request(conn, aid, tid) for _ in range(5)]
        for rid in ids[:2]:
            assert repo.decide(rid, "approved" if rid == ids[0] else "rejected", 3, T0)

        def walk(state: str) -> list[int]:
            out: list[int] = []
            after = ids[0] - 1
            while True:
                page = repo.request_page(state, 2, after)  # type: ignore[arg-type]
                out.extend(r.request_id for r in page if r.request_id in ids)
                if len(page) < 2:
                    return out
                after = page[-1].request_id

        assert walk("pending") == ids[2:]
        assert walk("decided") == ids[:2]
        assert walk("all") == ids


def test_rejected_new_for_agent(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    tid, _ = token(conn, max_uses=10)
    with conn.transaction():
        rejected_new = agent(conn)
        repo.decide(request(conn, rejected_new, tid), "rejected", 1, T0)
        rejected_re = agent(conn, status="online")
        repo.decide(request(conn, rejected_re, tid, kind="reenrol"), "rejected", 1, T0)
        approved = agent(conn, status="enrolled")
        repo.decide(request(conn, approved, tid), "approved", 1, T0)
        pending = agent(conn)
        request(conn, pending, tid)
    assert repo.rejected_new_for_agent(rejected_new) is True
    assert repo.rejected_new_for_agent(rejected_re) is False  # #26: old row unaffected
    assert repo.rejected_new_for_agent(approved) is False
    assert repo.rejected_new_for_agent(pending) is False


def test_app_cannot_delete_tokens_or_requests(conn: Conn) -> None:
    for stmt in ("DELETE FROM enrollment_token", "DELETE FROM enrollment_request"):
        with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
            conn.execute(stmt)


# ------------------------------------------------------------ CHK-M3-063


def test_decide_once(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    tid, _ = token(conn)
    with conn.transaction():
        rid = request(conn, agent(conn), tid)
        assert repo.decide(rid, "approved", 5, T0) is True
        assert repo.decide(rid, "rejected", 6, T0 + SEC) is False
    row = repo.get_request_for_update(rid)
    assert row is not None
    assert (row.decision, row.decided_by, row.decided_at) == ("approved", 5, T0)


def test_concurrent_decisions_one_wins_deterministic(db: PgServer) -> None:
    """A holds the row lock; B waits on it and then sees A's decision."""
    with db.connect("bitscan_app") as c:
        tid, _ = token(c)
        with c.transaction():
            rid = request(c, agent(c), tid)
    b_result: list[bool] = []
    b_saw: list[str | None] = []
    with db.connect("bitscan_app") as ca:
        with ca.transaction():
            ra = EnrolmentRepo(ca)
            assert ra.get_request_for_update(rid) is not None

            def b() -> None:
                with db.connect("bitscan_app") as cb, cb.transaction():
                    rb = EnrolmentRepo(cb)
                    row = rb.get_request_for_update(rid)  # blocks until A commits
                    b_saw.append(None if row is None else row.decision)
                    b_result.append(rb.decide(rid, "rejected", 2, T0))

            t = threading.Thread(target=b)
            t.start()
            t.join(2)
            assert t.is_alive(), "B did not wait for A's row lock"
            assert ra.decide(rid, "approved", 1, T0) is True
        t.join(30)
    assert b_saw == ["approved"] and b_result == [False]


def test_ten_concurrent_decisions_exactly_one(db: PgServer) -> None:
    with db.connect("bitscan_app") as c:
        tid, _ = token(c)
        with c.transaction():
            rid = request(c, agent(c), tid)
    barrier = threading.Barrier(10)
    wins: list[bool] = []
    lock = threading.Lock()

    def go(n: int) -> None:
        with db.connect("bitscan_app") as cx:
            barrier.wait(15)
            with cx.transaction():
                repo = EnrolmentRepo(cx)
                repo.get_request_for_update(rid)
                ok = repo.decide(rid, "approved" if n % 2 else "rejected", n, T0)
            with lock:
                wins.append(ok)

    ts = [threading.Thread(target=go, args=(n,)) for n in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert wins.count(True) == 1 and len(wins) == 10


# ------------------------------------------------------------ CHK-M3-064


def test_matches_by_hostname_and_machine_id(conn: Conn) -> None:
    repo = EnrolmentRepo(conn)
    host = f"clone-{secrets.token_hex(3)}"
    other = f"orig-{secrets.token_hex(3)}"
    machine = secrets.token_hex(16)
    with conn.transaction(force_rollback=True):
        tid, _ = token(conn, max_uses=10)
        existing = agent(conn, hostname=other, machine=machine, status="online")
        same_host_1 = agent(conn, hostname=host, status="online")
        same_host_2 = agent(conn, hostname=host, status="offline")
        agent(conn, hostname=host.upper(), status="online")  # exact match only
        # a cloned host re-enrols onto the existing machine-id under its own name
        rid = request(
            conn, existing, tid, kind="reenrol", hostname=host, machine=machine
        )
        req = repo.get_request_for_update(rid)
        assert req is not None
        got = repo.matches(req)
        assert all(isinstance(m, MatchRow) for m in got)
        assert [m.agent_id for m in got] == sorted([same_host_1, same_host_2], key=str)
        assert existing not in [m.agent_id for m in got]  # the request's own agent
        assert {m.status for m in got} == {"online", "offline"}
        # a new host whose name equals the existing agent's: that agent matches
        newcomer = agent(conn, hostname=other)
        rid2 = request(conn, newcomer, tid, hostname=other)
        req2 = repo.get_request_for_update(rid2)
        assert req2 is not None
        m2 = repo.matches(req2)
        assert [(m.agent_id, m.hostname, m.machine_id) for m in m2] == [
            (existing, other, machine)
        ]


def test_matches_by_machine_id_alone(conn: Conn) -> None:
    """A new-kind request whose machine-id belongs to another agent row."""
    repo = EnrolmentRepo(conn)
    machine = secrets.token_hex(16)
    with conn.transaction(force_rollback=True):
        tid, _ = token(conn)
        owner = agent(conn, hostname=f"a-{secrets.token_hex(3)}", machine=machine)
        newcomer = agent(conn, hostname=f"b-{secrets.token_hex(3)}")
        rid = request(
            conn,
            newcomer,
            tid,
            hostname="unrelated-" + secrets.token_hex(3),
            machine=machine,
        )
        req = repo.get_request_for_update(rid)
        assert req is not None
        assert [m.agent_id for m in repo.matches(req)] == [owner]
