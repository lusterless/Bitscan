"""TASK-031: app_user and user_token repositories on PostgreSQL as bitscan_app.

Checks CHK-M2-091 to CHK-M2-096 of tests/m2/test-plan.md (TP-M2-09). Every
statement runs as bitscan_app on a freshly migrated database, so a missing
grant fails with 42501. Expected values: TS §5.2 L953-L979 (columns, CHECK),
TS §6.2 L1087-L1088 (single-use step, back-off), REQ-048 (3), (4), #56 (d).
"""

import hashlib
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import errors

from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import DuplicateUsername, UserRepo

from .conftest import PgServer

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo"


@pytest.fixture
def db(migrated_db: PgServer) -> PgServer:
    return migrated_db


@pytest.fixture
def conn(db: PgServer) -> Iterator[Conn]:
    with db.connect("bitscan_app") as c:
        assert c.execute("SELECT session_user::text").fetchone() == ("bitscan_app",)
        yield c


def uname(prefix: str = "u") -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def new_user(conn: Conn, role: str = "viewer", name: str | None = None) -> int:
    with conn.transaction():
        return UserRepo(conn).insert_user(name or uname(), HASH, role, T0)


def token_hash() -> str:
    return hashlib.sha256(f"bsu_{secrets.token_urlsafe(32)}".encode()).hexdigest()


def wait_until_blocked(db: PgServer, pid: int, timeout: float = 10) -> None:
    with db.connect("bitscan_app") as mon:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = mon.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,)
            ).fetchone()
            if row is not None and row[0] == "Lock":
                return
            time.sleep(0.05)
    raise AssertionError(f"backend {pid} never waited on a lock")


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(fn())
        except BaseException as exc:  # noqa: BLE001  # reported to the test
            out.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


# ------------------------------------------------------ CHK-M2-091 UserRepo


def test_insert_and_find_users(conn: Conn) -> None:
    name = uname("Alice")
    with conn.transaction():
        repo = UserRepo(conn)
        uid = repo.insert_user(name, HASH, "operator", T0)
        row = repo.find_by_username(name)
        assert row is not None
        assert (row.user_id, row.username, row.role) == (uid, name, "operator")
        assert row.password_hash == HASH
        assert row.totp_secret_enc is None and row.totp_last_step is None
        assert row.totp_enrolled is False
        assert row.disabled is False and row.failed_logins == 0
        assert row.next_login_at is None
        assert row.created_at == T0
        assert row.created_at.utcoffset() == timedelta(0)
        assert repo.get(uid) == row
        assert repo.get_for_update(uid) == row
        assert repo.get(10**12) is None
        assert repo.find_by_username("no-such-user-" + secrets.token_hex(4)) is None


def test_username_match_is_exact_and_case_sensitive(conn: Conn) -> None:
    """#56 (d)."""
    base = uname("case")
    upper = base.upper()
    with conn.transaction():
        repo = UserRepo(conn)
        a = repo.insert_user(base, HASH, "viewer", T0)
        b = repo.insert_user(upper, HASH, "viewer", T0)
        assert a != b
        found = repo.find_by_username(base)
        assert found is not None and found.user_id == a
        found = repo.find_by_username(upper)
        assert found is not None and found.user_id == b
        assert repo.find_by_username(base + " ") is None
        assert repo.find_by_username(base[:-1]) is None


def test_duplicate_username_raises_and_transaction_stays_usable(conn: Conn) -> None:
    name = uname("dup")
    with conn.transaction():
        repo = UserRepo(conn)
        uid = repo.insert_user(name, HASH, "viewer", T0)
        with pytest.raises(DuplicateUsername):
            repo.insert_user(name, "other", "admin", T0)
        row = repo.find_by_username(name)
        assert row is not None and row.user_id == uid and row.role == "viewer"
        assert row.password_hash == HASH


def test_user_row_repr_hides_secrets(conn: Conn) -> None:
    uid = new_user(conn)
    with conn.transaction():
        repo = UserRepo(conn)
        repo.set_totp(uid, "vault:v1:CANARY-cipher", 5)
        row = repo.get(uid)
    assert row is not None
    text = repr(row) + str(row)
    assert HASH not in text and "CANARY-cipher" not in text
    assert row.totp_enrolled is True


def test_setters_change_one_row(conn: Conn) -> None:
    uid = new_user(conn)
    other = new_user(conn)
    with conn.transaction():
        repo = UserRepo(conn)
        assert repo.set_role(uid, "admin") is True
        assert repo.set_disabled(uid, True) is True
        assert repo.set_password_hash(uid, "$argon2id$new") is True
        assert repo.set_totp(uid, "vault:v1:x", 77) is True
        row = repo.get(uid)
        assert row is not None
        assert (row.role, row.disabled, row.password_hash) == (
            "admin",
            True,
            "$argon2id$new",
        )
        assert (row.totp_secret_enc, row.totp_last_step) == ("vault:v1:x", 77)
        assert repo.clear_totp(uid) is True
        row = repo.get(uid)
        assert row is not None
        assert (row.totp_secret_enc, row.totp_last_step) == (None, None)
        untouched = repo.get(other)
        assert untouched is not None
        assert (untouched.role, untouched.disabled, untouched.password_hash) == (
            "viewer",
            False,
            HASH,
        )
        missing = 10**12
        assert repo.set_role(missing, "admin") is False
        assert repo.set_disabled(missing, True) is False
        assert repo.set_password_hash(missing, "x") is False
        assert repo.set_totp(missing, "x", 1) is False
        assert repo.clear_totp(missing) is False
        assert repo.reset_failures(missing) is False
        assert repo.record_failure(10**12, T0) is None


def test_bad_role_is_refused_by_the_enum(conn: Conn) -> None:
    with pytest.raises(errors.InvalidTextRepresentation), conn.transaction():
        UserRepo(conn).insert_user(uname(), HASH, "root", T0)


def test_list_page_walks_users_in_id_order(conn: Conn) -> None:
    made = [new_user(conn) for _ in range(5)]
    with conn.transaction():
        repo = UserRepo(conn)
        seen: list[int] = []
        after: int | None = made[0] - 1
        while True:
            page = repo.list_page(2, after)
            assert len(page) <= 2
            if not page:
                break
            seen += [u.user_id for u in page]
            after = page[-1].user_id
        assert made == [u for u in seen if u in made]
        assert seen == sorted(seen)
        first = repo.list_page(3, None)
        assert [u.user_id for u in first] == sorted(u.user_id for u in first)
        assert len(first) == 3


def test_lock_active_admins_lists_only_enabled_admins(conn: Conn) -> None:
    a = new_user(conn, "admin")
    b = new_user(conn, "admin")
    disabled = new_user(conn, "admin")
    op = new_user(conn, "operator")
    with conn.transaction():
        UserRepo(conn).set_disabled(disabled, True)
    with conn.transaction():
        ids = UserRepo(conn).lock_active_admins()
    assert a in ids and b in ids
    assert disabled not in ids and op not in ids
    assert ids == sorted(ids)


# --------------------------------------------- CHK-M2-092 TOTP step claim


def test_claim_totp_step_only_moves_forward(conn: Conn) -> None:
    uid = new_user(conn)
    with conn.transaction():
        repo = UserRepo(conn)
        assert repo.claim_totp_step(uid, 1000) is True
        assert repo.claim_totp_step(uid, 1000) is False
        assert repo.claim_totp_step(uid, 999) is False
        assert repo.claim_totp_step(uid, 1001) is True
        row = repo.get(uid)
        assert row is not None and row.totp_last_step == 1001


def test_concurrent_claim_of_one_step_deterministic(db: PgServer, conn: Conn) -> None:
    """REQ-042 (3): A holds its claim uncommitted; B waits; A commits; B loses."""
    uid = new_user(conn)
    with db.connect("bitscan_app") as a, db.connect("bitscan_app") as b:
        tx_a = a.transaction()
        tx_a.__enter__()
        assert UserRepo(a).claim_totp_step(uid, 5000) is True

        def claim_b() -> bool:
            with b.transaction():
                return UserRepo(b).claim_totp_step(uid, 5000)

        thread, out = in_thread(claim_b)
        wait_until_blocked(db, b.info.backend_pid)
        assert out == []
        tx_a.__exit__(None, None, None)
        thread.join(10)
        assert out == [False]
    with conn.transaction():
        row = UserRepo(conn).get(uid)
    assert row is not None and row.totp_last_step == 5000


def test_ten_concurrent_claims_give_exactly_one_success(
    db: PgServer, conn: Conn
) -> None:
    uid = new_user(conn)
    barrier = threading.Barrier(10)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        with db.connect("bitscan_app") as c:
            barrier.wait()
            with c.transaction():
                won = UserRepo(c).claim_totp_step(uid, 7777)
            with lock:
                results.append(won)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results) == [False] * 9 + [True]


def test_rolled_back_claim_does_not_consume_the_step(conn: Conn) -> None:
    uid = new_user(conn)
    with pytest.raises(RuntimeError), conn.transaction():
        assert UserRepo(conn).claim_totp_step(uid, 42) is True
        raise RuntimeError("rollback")
    with conn.transaction():
        assert UserRepo(conn).claim_totp_step(uid, 42) is True


# ---------------------------------------------------- CHK-M2-093 back-off


def test_backoff_sequence_doubles_to_900(conn: Conn) -> None:
    """REQ-048 (3): after n failures next_login_at = now + min(2^(n-1), 900) s."""
    uid = new_user(conn)
    now = T0
    for n in range(1, 14):
        with conn.transaction():
            repo = UserRepo(conn)
            assert repo.record_failure(uid, now) == n
            row = repo.get(uid)
        assert row is not None
        assert row.failed_logins == n
        assert row.next_login_at == now + timedelta(seconds=min(2 ** (n - 1), 900)), n
        now = now + timedelta(seconds=1000)
    with conn.transaction():
        repo = UserRepo(conn)
        assert repo.reset_failures(uid) is True
        row = repo.get(uid)
    assert row is not None and (row.failed_logins, row.next_login_at) == (0, None)


def test_backoff_uses_the_given_now_not_the_database_clock(conn: Conn) -> None:
    uid = new_user(conn)
    past = datetime(2001, 1, 1, tzinfo=UTC)
    with conn.transaction():
        repo = UserRepo(conn)
        repo.record_failure(uid, past)
        row = repo.get(uid)
    assert row is not None and row.next_login_at == past + timedelta(seconds=1)


def test_failed_logins_never_overflows_smallint(conn: Conn) -> None:
    """REQ-048 (4): even from the SMALLINT maximum the counter stays valid."""
    uid = new_user(conn)
    for start in (998, 999, 1000, 32766, 32767):
        with conn.transaction():
            conn.execute(
                "UPDATE app_user SET failed_logins = %s WHERE user_id = %s",
                (start, uid),
            )
            count = UserRepo(conn).record_failure(uid, T0)
            row = UserRepo(conn).get(uid)
        assert count is not None and count <= 32767
        assert count == min(start + 1, 1000) or count == 1000
        assert row is not None
        assert row.next_login_at == T0 + timedelta(seconds=900)


def test_backoff_is_atomic_under_ten_concurrent_failures(
    db: PgServer, conn: Conn
) -> None:
    uid = new_user(conn)
    barrier = threading.Barrier(10)
    counts: list[int | None] = []
    lock = threading.Lock()

    def worker() -> None:
        with db.connect("bitscan_app") as c:
            barrier.wait()
            with c.transaction():
                got = UserRepo(c).record_failure(uid, T0)
            with lock:
                counts.append(got)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(c for c in counts if c is not None) == list(range(1, 11))
    with conn.transaction():
        row = UserRepo(conn).get(uid)
    assert row is not None and row.failed_logins == 10
    assert row.next_login_at == T0 + timedelta(seconds=512)


# -------------------------------------------- CHK-M2-094, -095 tokens


def test_insert_and_find_token_by_hash_only(conn: Conn) -> None:
    uid = new_user(conn, "operator")
    raw = "bsu_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        tid = tokens.insert(
            user_id=uid,
            kind="session",
            token_hash=digest,
            expires_at=T0 + timedelta(hours=24),
            now=T0,
            totp_verified=True,
        )
        owner = tokens.find_by_hash(digest)
        assert owner is not None
        assert (owner.token_id, owner.kind, owner.totp_verified) == (
            tid,
            "session",
            True,
        )
        assert owner.expires_at == T0 + timedelta(hours=24)
        assert owner.created_at == T0
        assert (owner.last_used_at, owner.revoked_at) == (None, None)
        assert (owner.user_id, owner.role, owner.disabled) == (uid, "operator", False)
        assert owner.totp_enrolled is False
        assert tokens.find_by_hash(raw) is None
        assert tokens.find_by_hash(digest.upper()) is None
        stored = conn.execute(
            "SELECT token_hash FROM user_token WHERE token_id = %s", (tid,)
        ).fetchone()
    assert stored == (digest,)


def test_find_by_hash_reports_owner_state(conn: Conn) -> None:
    uid = new_user(conn, "viewer")
    digest = token_hash()
    with conn.transaction():
        users, tokens = UserRepo(conn), UserTokenRepo(conn)
        tokens.insert(
            user_id=uid, kind="api", token_hash=digest, expires_at=T0, now=T0, name="ci"
        )
        users.set_role(uid, "admin")
        users.set_disabled(uid, True)
        users.set_totp(uid, "vault:v1:y", 3)
        owner = tokens.find_by_hash(digest)
    assert owner is not None
    assert (owner.kind, owner.role, owner.disabled, owner.totp_enrolled) == (
        "api",
        "admin",
        True,
        True,
    )


def test_api_token_can_never_be_totp_verified(conn: Conn) -> None:
    """CHK-M2-095: REQ-051 (7), TS §5.2 L977."""
    uid = new_user(conn)
    with pytest.raises(errors.CheckViolation), conn.transaction():
        UserTokenRepo(conn).insert(
            user_id=uid,
            kind="api",
            token_hash=token_hash(),
            expires_at=T0,
            now=T0,
            totp_verified=True,
        )


@pytest.mark.parametrize("kind", ["admin", "", "Session", "agent"])
def test_unknown_token_kind_is_refused(conn: Conn, kind: str) -> None:
    uid = new_user(conn)
    with pytest.raises(ValueError), conn.transaction():
        UserTokenRepo(conn).insert(
            user_id=uid, kind=kind, token_hash=token_hash(), expires_at=T0, now=T0
        )


def test_duplicate_token_hash_is_refused(conn: Conn) -> None:
    uid = new_user(conn)
    digest = token_hash()
    with conn.transaction():
        UserTokenRepo(conn).insert(
            user_id=uid, kind="api", token_hash=digest, expires_at=T0, now=T0
        )
    with pytest.raises(errors.UniqueViolation), conn.transaction():
        UserTokenRepo(conn).insert(
            user_id=uid, kind="session", token_hash=digest, expires_at=T0, now=T0
        )


def test_touch_skips_writes_under_60_seconds(conn: Conn) -> None:
    uid = new_user(conn)
    digest = token_hash()
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        tid = tokens.insert(
            user_id=uid,
            kind="session",
            token_hash=digest,
            expires_at=T0 + timedelta(days=1),
            now=T0,
        )
        assert tokens.touch(tid, T0) is True
        assert tokens.touch(tid, T0 + timedelta(seconds=59)) is False
        assert tokens.touch(tid, T0 + timedelta(seconds=60)) is False
        assert tokens.touch(tid, T0 + timedelta(seconds=61)) is True
        owner = tokens.find_by_hash(digest)
    assert owner is not None and owner.last_used_at == T0 + timedelta(seconds=61)


def test_revoke_presenting_token(conn: Conn) -> None:
    uid = new_user(conn)
    digest = token_hash()
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        tid = tokens.insert(
            user_id=uid, kind="session", token_hash=digest, expires_at=T0, now=T0
        )
        assert tokens.revoke(tid, T0 + timedelta(minutes=1)) is True
        assert tokens.revoke(tid, T0 + timedelta(minutes=2)) is False
        owner = tokens.find_by_hash(digest)
    assert owner is not None and owner.revoked_at == T0 + timedelta(minutes=1)


def test_revoke_own_api_refuses_every_other_case_alike(conn: Conn) -> None:
    """REQ-051 (3): another user's id, a session, unknown and revoked all False."""
    alice, bob = new_user(conn), new_user(conn)
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        a_api = tokens.insert(
            user_id=alice, kind="api", token_hash=token_hash(), expires_at=T0, now=T0
        )
        a_sess = tokens.insert(
            user_id=alice,
            kind="session",
            token_hash=token_hash(),
            expires_at=T0,
            now=T0,
        )
        assert tokens.revoke_own_api(bob, a_api, T0) is False
        assert tokens.revoke_own_api(alice, a_sess, T0) is False
        assert tokens.revoke_own_api(alice, 10**12, T0) is False
        assert tokens.revoke_own_api(alice, a_api, T0) is True
        assert tokens.revoke_own_api(alice, a_api, T0) is False
        revoked = conn.execute(
            "SELECT token_id FROM user_token"
            " WHERE user_id = %s AND revoked_at IS NOT NULL",
            (alice,),
        ).fetchall()
    assert revoked == [(a_api,)]


def test_revoke_for_user_by_kind(conn: Conn) -> None:
    uid, other = new_user(conn), new_user(conn)
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        for kind in ("session", "session", "api", "api", "api"):
            tokens.insert(
                user_id=uid, kind=kind, token_hash=token_hash(), expires_at=T0, now=T0
            )
        tokens.insert(
            user_id=other, kind="api", token_hash=token_hash(), expires_at=T0, now=T0
        )
        assert tokens.revoke_for_user(uid, ["session"], T0) == 2
        assert tokens.revoke_for_user(uid, ["session"], T0) == 0
        assert tokens.revoke_for_user(uid, {"api", "session"}, T0) == 3
        with pytest.raises(ValueError):
            tokens.revoke_for_user(uid, [], T0)
        with pytest.raises(ValueError):
            tokens.revoke_for_user(uid, ["agent"], T0)
        live = conn.execute(
            "SELECT count(*) FROM user_token WHERE user_id = %s AND revoked_at IS NULL",
            (other,),
        ).fetchone()
    assert live == (1,)


def test_list_api_returns_own_api_rows_without_hash(conn: Conn) -> None:
    uid, other = new_user(conn), new_user(conn)
    with conn.transaction():
        tokens = UserTokenRepo(conn)
        mine = [
            tokens.insert(
                user_id=uid,
                kind="api",
                token_hash=token_hash(),
                expires_at=T0 + timedelta(days=90),
                now=T0,
                name=f"t{i}",
            )
            for i in range(5)
        ]
        tokens.insert(
            user_id=uid, kind="session", token_hash=token_hash(), expires_at=T0, now=T0
        )
        tokens.insert(
            user_id=other, kind="api", token_hash=token_hash(), expires_at=T0, now=T0
        )
        page1 = tokens.list_api(uid, 2, None)
        page2 = tokens.list_api(uid, 2, page1[-1].token_id)
        page3 = tokens.list_api(uid, 2, page2[-1].token_id)
        page4 = tokens.list_api(uid, 2, page3[-1].token_id)
    assert [r.token_id for r in page1 + page2 + page3] == mine
    assert page4 == []
    assert [r.name for r in page1] == ["t0", "t1"]
    for row in page1:
        assert set(vars(row)) == {
            "token_id",
            "name",
            "created_at",
            "expires_at",
            "last_used_at",
            "revoked_at",
        }


# ----------------------------------------------- CHK-M2-096 admin locking


def test_admin_lock_blocks_a_second_locker_until_commit(
    db: PgServer, conn: Conn
) -> None:
    new_user(conn, "admin")
    with db.connect("bitscan_app") as a, db.connect("bitscan_app") as b:
        tx_a = a.transaction()
        tx_a.__enter__()
        first = UserRepo(a).lock_active_admins()
        assert first

        def lock_b() -> list[int]:
            with b.transaction():
                return UserRepo(b).lock_active_admins()

        thread, out = in_thread(lock_b)
        wait_until_blocked(db, b.info.backend_pid)
        assert out == []
        tx_a.__exit__(None, None, None)
        thread.join(10)
        assert out == [first]


def test_get_for_update_blocks_a_concurrent_update(db: PgServer, conn: Conn) -> None:
    uid = new_user(conn)
    with db.connect("bitscan_app") as a, db.connect("bitscan_app") as b:
        tx_a = a.transaction()
        tx_a.__enter__()
        assert UserRepo(a).get_for_update(uid) is not None

        def update_b() -> bool:
            with b.transaction():
                return UserRepo(b).set_role(uid, "operator")

        thread, out = in_thread(update_b)
        wait_until_blocked(db, b.info.backend_pid)
        tx_a.__exit__(None, None, None)
        thread.join(10)
        assert out == [True]
