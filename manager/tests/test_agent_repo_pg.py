"""TASK-051: agent, agent_ip_seen and agent_tag repository on PostgreSQL.

Checks CHK-M3-050 to CHK-M3-055 of tests/m3/test-plan.md (TP-M3-05), plus the
repository half of the sweep statements (REQ-078 (1), (2), (4); the service and
clock part is CHK-M3-180 to -188 in TASK-065). Every call runs as bitscan_app on
a freshly migrated database. Expected values: TS §5.2 L712-L746 and the grants
(UPDATE agent, agent_ip_seen; DELETE agent_tag; never DELETE agent), TS §3.2
L183-L191 (hash only; revoke; rotation overlap), TS §3.3 L218, L220 (online
below 10 min, stale 10 to 30 min, offline above 30 min; decommission after N
days, token revoked), #25 (record the IP on every accepted call; age base
enrolled_at or the approval time), #62 (rotation states), #64 (relink),
#68 (GET /agents item, (hostname, agent_id) order), #73 (a) (heartbeat sets
online at once). Fleet-wide statements run in rolled-back transactions.
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

from bitscan_manager.repositories.agents import AgentListRow, AgentRepo, AgentRow

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
SEC = timedelta(seconds=1)
STALE = timedelta(minutes=10)
OFFLINE = timedelta(minutes=30)
LIST_FIELDS = {
    "agent_id",
    "hostname",
    "status",
    "agent_version",
    "os_id",
    "os_version_id",
    "os_pretty_name",
    "last_heartbeat_at",
    "last_inventory_at",
    "tags",
    "runner_helpers",
}


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def thash() -> str:
    return hashlib.sha256(f"bsa_{secrets.token_urlsafe(32)}".encode()).hexdigest()


def add(
    repo: AgentRepo,
    *,
    status: str = "enrolled",
    now: datetime = T0,
    hostname: str | None = None,
    token_hash: str | None = None,
) -> tuple[UUID, str, str]:
    """Inserts an agent; returns (agent_id, machine_id, token_hash)."""
    machine = secrets.token_hex(16)
    h = token_hash or thash()
    aid = repo.insert(
        machine_id=machine,
        hostname=hostname or f"h-{secrets.token_hex(4)}",
        agent_version="1.0.0",
        token_hash=h,
        issued_at=now,
        expires_at=now + timedelta(days=365),
        status=status,
        now=now,
    )
    assert aid is not None
    return aid, machine, h


def heartbeat_at(conn: Conn, agent: UUID, when: datetime | None, status: str) -> None:
    """Sets the heartbeat time and status directly (app UPDATE on agent)."""
    conn.execute(
        "UPDATE agent SET last_heartbeat_at = %s, status = CAST(%s AS agent_status)"
        " WHERE agent_id = %s",
        (when, status, agent),
    )


def status_of(conn: Conn, agent: UUID) -> str:
    row = conn.execute(
        "SELECT status::text FROM agent WHERE agent_id = %s", (agent,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def add_request(
    conn: Conn, agent: UUID, *, decision: str | None, decided_at: datetime | None
) -> None:
    tok = conn.execute(
        "INSERT INTO enrollment_token (token_hash, expires_at, created_by)"
        " VALUES (%s, %s, 1) RETURNING token_id",
        (thash(), T0 + timedelta(days=1)),
    ).fetchone()
    assert tok is not None
    conn.execute(
        "INSERT INTO enrollment_request (kind, agent_id, enrollment_token_id, hostname,"
        " machine_id, agent_version, new_token_hash, token_expires_at, source_ip,"
        " requested_at, decision, decided_at) VALUES ('new', %s, %s, 'h', %s, '1',"
        " %s, %s, '192.0.2.1', %s, %s, %s)",
        (
            agent,
            tok[0],
            secrets.token_hex(16),
            thash(),
            T0 + timedelta(days=365),
            T0 - timedelta(days=30),
            decision,
            decided_at,
        ),
    )


# ------------------------------------------------------------ CHK-M3-050, -051


def test_insert_and_every_lookup(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, machine, h = add(repo, status="awaiting_approval", hostname="web-01")
    row = repo.get(aid)
    assert isinstance(row, AgentRow)
    assert (
        row.agent_id == aid and row.machine_id == machine and row.hostname == "web-01"
    )
    assert row.agent_version == "1.0.0" and row.status == "awaiting_approval"
    assert row.token_hash == h and row.prev_token_hash is None
    assert row.token_issued_at == T0 and row.token_expires_at == T0 + timedelta(
        days=365
    )
    assert row.token_revoked_at is None and row.last_rotation_at is None
    assert row.enrolled_at == T0  # from the Clock, not the database's now()
    assert row.last_seen_ip is None and row.runner_helpers == []
    assert repo.find_by_token_hash(h) == row
    assert repo.find_by_machine_id(machine) == row
    with conn.transaction():
        assert repo.get(aid, lock=True) == row
        assert repo.find_by_machine_id(machine, lock=True) == row


def test_unknown_values_return_none(conn: Conn) -> None:
    repo = AgentRepo(conn)
    assert repo.find_by_token_hash(thash()) is None
    assert repo.find_by_prev_hash(thash()) is None
    assert repo.find_by_machine_id(secrets.token_hex(16)) is None
    assert repo.get(UUID(int=0)) is None


def test_lookup_by_raw_token_finds_nothing(conn: Conn) -> None:
    """Only the hash is stored: the raw token string is not a key."""
    repo = AgentRepo(conn)
    raw = "bsa_" + secrets.token_urlsafe(32)
    with conn.transaction():
        add(repo, token_hash=hashlib.sha256(raw.encode()).hexdigest())
    assert repo.find_by_token_hash(raw) is None


def test_duplicate_machine_id_insert_returns_none_and_changes_nothing(
    conn: Conn,
) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, machine, _ = add(repo)
    before = repo.get(aid)
    with conn.transaction():
        again = repo.insert(
            machine_id=machine,
            hostname="other",
            agent_version="9",
            token_hash=thash(),
            issued_at=T0,
            expires_at=T0,
            status="enrolled",
            now=T0,
        )
    assert again is None
    assert repo.get(aid) == before


def test_row_repr_hides_hashes(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, h = add(repo)
    assert h not in repr(repo.get(aid))


def test_app_cannot_delete_agents(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute("DELETE FROM agent WHERE agent_id = %s", (aid,))


# ------------------------------------------------------------ token state (#62, #64)


def test_revoke_keeps_the_first_time(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
        assert repo.revoke(aid, T0) is True
        assert repo.revoke(aid, T0 + MIN) is True
    row = repo.get(aid)
    assert row is not None and row.token_revoked_at == T0


def test_rotation_states(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, old = add(repo, status="online")
    new, new2 = thash(), thash()
    t1 = T0 + timedelta(days=335)
    with conn.transaction():
        assert repo.rotate(aid, new, t1, t1 + timedelta(days=365)) is True
    r = repo.get(aid)
    assert r is not None
    assert (r.token_hash, r.prev_token_hash, r.prev_token_expires_at) == (
        new,
        old,
        None,
    )
    assert (r.token_issued_at, r.token_expires_at, r.last_rotation_at) == (
        t1,
        t1 + timedelta(days=365),
        t1,
    )
    assert repo.find_by_prev_hash(old) == r
    assert repo.find_by_token_hash(new) == r
    # lost-response retry while the new token is unused
    with conn.transaction():
        assert repo.replace_unused_token(aid, new2, t1 + MIN, t1 + timedelta(days=366))
    r = repo.get(aid)
    assert r is not None
    assert (r.token_hash, r.prev_token_hash) == (new2, old)
    assert r.last_rotation_at == t1  # a retry is not a new rotation
    assert repo.find_by_token_hash(new) is None  # the unused one is gone
    # first use: exactly once
    with conn.transaction():
        assert repo.mark_new_token_used(aid, t1 + 12 * MIN) is True
        assert repo.mark_new_token_used(aid, t1 + 20 * MIN) is False
    r = repo.get(aid)
    assert r is not None and r.prev_token_expires_at == t1 + 12 * MIN
    with conn.transaction():
        assert repo.replace_unused_token(aid, thash(), t1, t1) is False  # used now
    assert repo.get(aid) == r


def test_no_overlap_marking_without_a_rotation(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
        assert repo.mark_new_token_used(aid, T0) is False
        assert repo.replace_unused_token(aid, thash(), T0, T0) is False


def _first_use_race(db: PgServer) -> None:
    with db.connect("bitscan_app") as c, c.transaction():
        repo = AgentRepo(c)
        aid, _, _ = add(repo)
        repo.rotate(aid, thash(), T0, T0 + timedelta(days=365))
    barrier = threading.Barrier(4)
    wins: list[bool] = []
    lock = threading.Lock()

    def use() -> None:
        with db.connect("bitscan_app") as cx:
            barrier.wait(10)
            with cx.transaction():
                ok = AgentRepo(cx).mark_new_token_used(aid, T0 + 10 * MIN)
            with lock:
                wins.append(ok)

    threads = [threading.Thread(target=use) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(wins) == [False, False, False, True]


def test_first_use_is_marked_once_under_concurrency(db: PgServer) -> None:
    for _ in range(5):
        _first_use_race(db)


def test_relink_takes_the_request_token_and_clears_old_state(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, machine, old = add(repo, status="offline", hostname="old-name")
        repo.rotate(aid, thash(), T0, T0 + timedelta(days=365))
        repo.revoke(aid, T0 + MIN)
    req_hash = thash()
    asked = T0 + timedelta(days=2)
    with conn.transaction():
        assert repo.relink(
            aid,
            token_hash=req_hash,
            issued_at=asked,
            expires_at=asked + timedelta(days=365),
            hostname="new-name",
            agent_version="2.0.0",
        )
    r = repo.get(aid)
    assert r is not None
    assert r.agent_id == aid and r.machine_id == machine
    assert (r.token_hash, r.token_issued_at, r.token_expires_at) == (
        req_hash,
        asked,
        asked + timedelta(days=365),
    )
    assert r.token_revoked_at is None and r.prev_token_hash is None
    assert r.prev_token_expires_at is None and r.last_rotation_at is None
    assert (r.hostname, r.agent_version, r.status) == ("new-name", "2.0.0", "enrolled")
    assert repo.find_by_token_hash(old) is None and repo.find_by_prev_hash(old) is None


# ------------------------------------------------------------ CHK-M3-054


@pytest.mark.parametrize("current", ["awaiting_approval", "enrolled", "decommissioned"])
def test_set_status_only_from_named_statuses(conn: Conn, current: str) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo, status=current)
        ok = repo.set_status(aid, "enrolled", ("awaiting_approval",))
    assert ok is (current == "awaiting_approval")
    assert status_of(conn, aid) == (
        "enrolled" if current == "awaiting_approval" else current
    )


# ------------------------------------------------------------ heartbeat (#73 (a))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("enrolled", "online"),
        ("online", "online"),
        ("stale", "online"),
        ("offline", "online"),
        ("awaiting_approval", "awaiting_approval"),
        ("decommissioned", "decommissioned"),
    ],
)
def test_record_heartbeat(conn: Conn, before: str, after: str) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo, status=before)
        assert repo.record_heartbeat(aid, T0 + MIN, "1.2.3", ["zeta", "capread"])
    r = repo.get(aid)
    assert r is not None
    assert r.status == after
    assert (r.last_heartbeat_at, r.agent_version) == (T0 + MIN, "1.2.3")
    assert r.runner_helpers == ["zeta", "capread"]  # order kept as sent


def test_set_last_inventory(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
        assert repo.set_last_inventory(aid, T0 + MIN)
    r = repo.get(aid)
    assert r is not None and r.last_inventory_at == T0 + MIN


# ------------------------------------------------------------ CHK-M3-052


@pytest.mark.parametrize("ip", ["192.0.2.10", "2001:db8::7"])
def test_ip_seen_upsert_keeps_first_seen(conn: Conn, ip: str) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
    assert repo.ip_last_seen(aid, ip) is None
    with conn.transaction():
        repo.record_ip(aid, ip, T0)
    assert repo.ip_last_seen(aid, ip) == T0
    r = repo.get(aid)
    assert r is not None and r.last_seen_ip == ip
    later = T0 + timedelta(days=8)
    assert repo.ip_last_seen(aid, ip) == T0  # read before the upsert: the old value
    with conn.transaction():
        repo.record_ip(aid, ip, later)
    row = conn.execute(
        "SELECT first_seen_at, last_seen_at FROM agent_ip_seen"
        " WHERE agent_id = %s AND ip = CAST(%s AS inet)",
        (aid, ip),
    ).fetchone()
    assert row == (T0, later)


def test_ip_seen_rows_are_per_agent_and_ip(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        a, _, _ = add(repo)
        b, _, _ = add(repo)
        repo.record_ip(a, "192.0.2.1", T0)
        repo.record_ip(a, "192.0.2.2", T0 + MIN)
    assert repo.ip_last_seen(b, "192.0.2.1") is None
    assert repo.ip_last_seen(a, "192.0.2.2") == T0 + MIN
    r = repo.get(a)
    assert r is not None and r.last_seen_ip == "192.0.2.2"
    n = conn.execute("SELECT count(*) FROM agent_ip_seen WHERE agent_id = %s", (a,))
    assert n.fetchone() == (2,)


# ------------------------------------------------------------ CHK-M3-053


def test_tags_replace_and_clear(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
        repo.replace_tags(aid, ["prod-web", "db"])
    assert repo.tags(aid) == ["db", "prod-web"]
    with conn.transaction():
        repo.replace_tags(aid, ["x"])
    assert repo.tags(aid) == ["x"]
    with conn.transaction():
        repo.replace_tags(aid, [])
    assert repo.tags(aid) == []


@pytest.mark.parametrize(
    "bad", [["ok", "t" * 65], ["dup", "dup"]], ids=["65-chars", "duplicate"]
)
def test_tag_replace_is_all_or_nothing(conn: Conn, bad: list[str]) -> None:
    repo = AgentRepo(conn)
    with conn.transaction():
        aid, _, _ = add(repo)
        repo.replace_tags(aid, ["prod-web", "db"])
    with pytest.raises(psycopg.Error), conn.transaction():
        repo.replace_tags(aid, bad)
    assert repo.tags(aid) == ["db", "prod-web"]


# ------------------------------------------------------------ list and counts (#68)


def test_list_page_items_and_keyset_paging(conn: Conn) -> None:
    repo = AgentRepo(conn)
    prefix = f"zzlist-{secrets.token_hex(3)}-"
    with conn.transaction(force_rollback=True):
        mine = [add(repo, hostname=f"{prefix}{i:02d}")[0] for i in range(5)]
        # two hosts sharing a hostname are ordered by agent_id
        twin = [add(repo, hostname=f"{prefix}05")[0] for _ in range(2)]
        conn.execute(
            "INSERT INTO os_info (agent_id, os_id, os_version_id, os_pretty_name,"
            " raw, collected_at)"
            " VALUES (%s, 'ubuntu', '24.04', 'Ubuntu 24.04.1 LTS', '{}', %s)",
            (mine[0], T0),
        )
        repo.replace_tags(mine[0], ["web", "a-tag"])
        expected = mine + sorted(twin, key=str)
        seen: list[AgentListRow] = []
        # The cursor holds only the last row's agent_id (#89, REQ-143). Page
        # from an anchor agent whose hostname is the bare prefix, which sorts
        # just before this test's rows.
        start = add(repo, hostname=prefix)[0]
        after: UUID | None = start
        while True:
            assert after is not None
            page = repo.list_page(2, after)
            assert len(page) <= 2
            seen.extend(r for r in page if r.hostname.startswith(prefix))
            if len(page) < 2 or not page[-1].hostname.startswith(prefix):
                break
            after = page[-1].agent_id
        assert [r.agent_id for r in seen] == expected
        first = seen[0]
        assert set(first.__dataclass_fields__) == LIST_FIELDS
        assert (first.os_id, first.os_version_id, first.os_pretty_name) == (
            "ubuntu",
            "24.04",
            "Ubuntu 24.04.1 LTS",
        )
        assert first.tags == ["a-tag", "web"]
        assert seen[1].os_id is None and seen[1].tags == []
        assert repo.list_page(1, None)  # the first page needs no cursor


def test_count_by_status(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        base = repo.count_by_status()
        for s in ("online", "online", "offline", "awaiting_approval"):
            add(repo, status=s)
        got = repo.count_by_status()
        assert got["online"] - base["online"] == 2
        assert got["offline"] - base["offline"] == 1
        assert got["awaiting_approval"] - base["awaiting_approval"] == 1
        assert got["stale"] == base["stale"]


# ------------------------------------------------------------ sweep statements


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (STALE - SEC, "online"),
        (STALE, "stale"),
        (OFFLINE - SEC, "stale"),
        (OFFLINE, "stale"),
        (OFFLINE + SEC, "offline"),
    ],
    ids=["9m59s", "10m", "29m59s", "30m", "30m1s"],
)
@pytest.mark.parametrize("start", ["online", "stale", "offline"])
def test_status_from_heartbeat_age(
    conn: Conn, age: timedelta, expected: str, start: str
) -> None:
    """REQ-078 (1) at the repository: < 10 min online, 10-30 min stale, > 30 offline."""
    repo = AgentRepo(conn)
    now = T0 + timedelta(days=1)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, status="enrolled", now=T0)
        heartbeat_at(conn, aid, now - age, start)
        repo.apply_heartbeat_ages(now, STALE, OFFLINE)
        assert status_of(conn, aid) == expected
        assert (
            repo.apply_heartbeat_ages(now, STALE, OFFLINE) == 0
        )  # nothing left to change


def test_never_heartbeat_agent_ages_from_enrolled_at(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, status="enrolled", now=T0)
        for age, expected in [
            (STALE - SEC, "enrolled"),  # no heartbeat: not moved to online
            (STALE, "stale"),
            (OFFLINE + SEC, "offline"),
        ]:
            repo.apply_heartbeat_ages(T0 + age, STALE, OFFLINE)
            assert status_of(conn, aid) == expected, age


def test_never_heartbeat_approved_agent_ages_from_the_approval(conn: Conn) -> None:
    """#25 (c): an approved agent's base is the approval time, not enrolled_at."""
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, status="enrolled", now=T0 - timedelta(days=3))
        add_request(conn, aid, decision="approved", decided_at=T0)
        repo.apply_heartbeat_ages(T0 + 5 * MIN, STALE, OFFLINE)
        assert status_of(conn, aid) == "enrolled"
        repo.apply_heartbeat_ages(T0 + OFFLINE + SEC, STALE, OFFLINE)
        assert status_of(conn, aid) == "offline"


def test_rejected_request_is_not_an_age_base(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, status="enrolled", now=T0 - timedelta(days=3))
        add_request(conn, aid, decision="rejected", decided_at=T0)
        add_request(conn, aid, decision=None, decided_at=None)
        repo.apply_heartbeat_ages(T0, STALE, OFFLINE)
        assert status_of(conn, aid) == "offline"


@pytest.mark.parametrize("held", ["awaiting_approval", "decommissioned"])
def test_sweep_never_touches_held_or_decommissioned(conn: Conn, held: str) -> None:
    """REQ-078 (4)."""
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, status=held, now=T0 - timedelta(days=30))
        heartbeat_at(conn, aid, T0 - timedelta(days=20), held)
        repo.apply_heartbeat_ages(T0, STALE, OFFLINE)
        assert status_of(conn, aid) == held
        assert aid not in repo.decommission_offline(T0, timedelta(days=7))
        assert status_of(conn, aid) == held


def test_decommission_after_days(conn: Conn) -> None:
    """REQ-078 (2): offline longer than N days → decommissioned, token revoked."""
    repo = AgentRepo(conn)
    days = timedelta(days=7)
    with conn.transaction(force_rollback=True):
        over, _, _ = add(repo, now=T0 - timedelta(days=30))
        exact, _, _ = add(repo, now=T0 - timedelta(days=30))
        online_old, _, _ = add(repo, now=T0 - timedelta(days=30))
        heartbeat_at(conn, over, T0 - days - SEC, "offline")
        heartbeat_at(conn, exact, T0 - days, "offline")
        heartbeat_at(
            conn, online_old, T0 - timedelta(days=9), "stale"
        )  # not yet offline
        gone = repo.decommission_offline(T0, days)
        assert over in gone and exact not in gone and online_old not in gone
        r = repo.get(over)
        assert r is not None
        assert (r.status, r.token_revoked_at) == ("decommissioned", T0)
        assert status_of(conn, exact) == "offline"
        assert status_of(conn, online_old) == "stale"
        assert over not in repo.decommission_offline(T0 + MIN, days)  # once


def test_decommission_keeps_an_earlier_revoke_time(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid, _, _ = add(repo, now=T0 - timedelta(days=30))
        heartbeat_at(conn, aid, T0 - timedelta(days=10), "offline")
        repo.revoke(aid, T0 - timedelta(days=9))
        assert aid in repo.decommission_offline(T0, timedelta(days=7))
        r = repo.get(aid)
        assert r is not None and r.token_revoked_at == T0 - timedelta(days=9)


def test_stale_inventory(conn: Conn) -> None:
    """#65 (c): online hosts only; base enrolled_at when never uploaded."""
    repo = AgentRepo(conn)
    bound = timedelta(hours=12)
    with conn.transaction(force_rollback=True):
        over, _, _ = add(repo, status="online", now=T0 - timedelta(days=2))
        exact, _, _ = add(repo, status="online", now=T0 - timedelta(days=2))
        never, _, _ = add(repo, status="online", now=T0 - bound - SEC)
        fresh_never, _, _ = add(repo, status="online", now=T0 - bound)
        offline, _, _ = add(repo, status="offline", now=T0 - timedelta(days=2))
        repo.set_last_inventory(over, T0 - bound - SEC)
        repo.set_last_inventory(exact, T0 - bound)
        got = set(repo.stale_inventory(T0, bound))
        assert over in got and never in got
        assert exact not in got and fresh_never not in got and offline not in got


# ------------------------------------------------------------ CHK-M3-055 (G1)


def test_module_has_no_string_built_sql() -> None:
    """S608 is the gate (ruff); this also checks no % or f-string formatting of SQL."""
    from pathlib import Path

    from bitscan_manager.repositories import agents

    text = Path(agents.__file__).read_text(encoding="utf-8")
    for prefix in ('f"SELECT', 'f"UPDATE', 'f"INSERT', 'f"DELETE', '" % ('):
        assert prefix not in text, prefix


# ------------------------------------------------------------ age base ruling
# work/decisions.md 2026-10-23 (TASK-051 age base, user): GREATEST stays. An
# agent whose last heartbeat is older than decommission_after_days, re-linked
# by an approved re-enrolment now, is not set offline or decommissioned by the
# next sweep, and ages from the approval time. Lead ruling (TS §3.3 L218,
# "online if the last heartbeat is < 10 min old"): it stays enrolled until its
# first heartbeat after the approval; a heartbeat makes it online (TASK-051 r1).


def _relinked_agent(conn: Conn, repo: AgentRepo) -> UUID:
    aid, _, _ = add(repo, status="enrolled", now=T0 - timedelta(days=60))
    heartbeat_at(conn, aid, T0 - timedelta(days=10), "offline")  # > 7 days old
    add_request(conn, aid, decision="approved", decided_at=T0)
    assert repo.relink(
        aid,
        token_hash=thash(),
        issued_at=T0,
        expires_at=T0 + timedelta(days=365),
        hostname="relinked",
        agent_version="2.0.0",
    )
    return aid


def test_approved_reenrolment_ages_from_the_approval(conn: Conn) -> None:
    repo = AgentRepo(conn)
    days = timedelta(days=7)
    with conn.transaction(force_rollback=True):
        aid = _relinked_agent(conn, repo)
        # the next sweep: still enrolled (no heartbeat since the approval)
        repo.apply_heartbeat_ages(T0 + MIN, STALE, OFFLINE)
        assert status_of(conn, aid) == "enrolled"
        assert aid not in repo.decommission_offline(T0 + MIN, days)
        r = repo.get(aid)
        assert r is not None and r.token_revoked_at is None
        assert r.last_heartbeat_at == T0 - timedelta(days=10)  # relink keeps it
        # ages from the approval: stale at 10 min, offline only after 30 min
        repo.apply_heartbeat_ages(T0 + STALE - SEC, STALE, OFFLINE)
        assert status_of(conn, aid) == "enrolled"
        repo.apply_heartbeat_ages(T0 + OFFLINE, STALE, OFFLINE)
        assert status_of(conn, aid) == "stale"
        repo.apply_heartbeat_ages(T0 + OFFLINE + SEC, STALE, OFFLINE)
        assert status_of(conn, aid) == "offline"
        # decommission counts from the approval too: not at 7 days, after it
        assert aid not in repo.decommission_offline(T0 + days, days)
        assert aid in repo.decommission_offline(T0 + days + SEC, days)


def test_relinked_agent_goes_online_after_a_heartbeat(conn: Conn) -> None:
    repo = AgentRepo(conn)
    with conn.transaction(force_rollback=True):
        aid = _relinked_agent(conn, repo)
        repo.apply_heartbeat_ages(T0 + MIN, STALE, OFFLINE)
        assert status_of(conn, aid) == "enrolled"
        assert repo.record_heartbeat(aid, T0 + 2 * MIN, "2.0.0", [])
        assert status_of(conn, aid) == "online"  # #73 (a): at once
        repo.apply_heartbeat_ages(T0 + 3 * MIN, STALE, OFFLINE)
        assert status_of(conn, aid) == "online"  # the sweep keeps it online
        repo.apply_heartbeat_ages(T0 + 2 * MIN + STALE, STALE, OFFLINE)
        assert status_of(conn, aid) == "stale"  # aged from the new heartbeat
