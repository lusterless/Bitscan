"""REQ-052 (5), (8) on PostgreSQL: the last-admin race and rollback of a
change with its audit entry (TASK-042; CHK-M2-228, CHK-M2-229)."""

import secrets
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.user_tokens import UserTokenRepo
from bitscan_manager.repositories.users import UserRepo
from bitscan_manager.services.users.accounts import (
    Rule,
    TxAudit,
    UserRuleError,
    change_role,
)

from .conftest import PgServer

pytestmark = pytest.mark.pg
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
Conn = psycopg.Connection[Any]


@pytest.fixture
def server(migrated_db: PgServer) -> Iterator[PgServer]:
    """Every existing active admin is demoted first, so each test controls the
    admin set (done directly as bitscan_app, which may UPDATE app_user)."""
    with migrated_db.connect("bitscan_app") as c:
        c.execute("UPDATE app_user SET role = 'operator' WHERE role = 'admin'")
    yield migrated_db


def tx_conn(server: PgServer) -> Conn:
    """A non-autocommit bitscan_app connection (the audit append refuses
    autocommit, M1); conftest's connect() is autocommit."""
    return psycopg.connect(server.dsn("bitscan_app"))


def add_admin(c: Conn) -> int:
    with c.transaction():
        uid = UserRepo(c).insert_user(
            f"adm-{secrets.token_hex(4)}", "$argon2id$x", "admin", NOW
        )
        UserRepo(c).set_totp(uid, "vault:v1:x", 1)
    return uid


def demote(c: Conn, uid: int, hold: threading.Event | None = None) -> None:
    """The service call in one transaction; optionally hold before commit."""
    with c.transaction():
        audit = TxAudit(PgAuditRepo(c), lambda hook: None)
        change_role(
            UserRepo(c),
            UserTokenRepo(c),
            audit,
            actor="user:0",
            user_id=uid,
            role="operator",
            now=NOW,
        )
        if hold is not None:
            hold.wait(10)


def active_admins(c: Conn) -> list[int]:
    rows = c.execute(
        "SELECT user_id FROM app_user WHERE role = 'admin' AND NOT disabled"
    ).fetchall()
    return sorted(r[0] for r in rows)


def test_two_admins_demoting_each_other_leave_one(server: PgServer) -> None:
    """CHK-M2-228, deterministic: A holds its demotion of b uncommitted, B's
    demotion of a waits on the admin lock, A commits, B must then be refused."""
    with server.connect("bitscan_app") as setup:
        a, b = add_admin(setup), add_admin(setup)
    release = threading.Event()
    results: dict[str, BaseException | None] = {}
    with tx_conn(server) as ca, tx_conn(server) as cb:

        def run(
            name: str, conn: Conn, target: int, hold: threading.Event | None
        ) -> None:
            try:
                demote(conn, target, hold)
                results[name] = None
            except BaseException as exc:  # noqa: BLE001  checked below
                results[name] = exc

        ta = threading.Thread(target=run, args=("A", ca, b, release))
        ta.start()
        time.sleep(0.5)  # A has locked the admin rows and demoted b
        tb = threading.Thread(target=run, args=("B", cb, a, None))
        tb.start()
        with server.connect("bitscan_app") as mon:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                row = mon.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                    (cb.info.backend_pid,),
                ).fetchone()
                if row and row[0] == "Lock":
                    break
                time.sleep(0.05)
            else:
                pytest.fail("B never waited on the admin lock")
        release.set()
        ta.join(15)
        tb.join(15)
    assert results["A"] is None
    err = results["B"]
    assert isinstance(err, UserRuleError) and err.rule == Rule.LAST_ADMIN
    with server.connect("bitscan_app") as c:
        assert active_admins(c) == [a]


def test_ten_concurrent_demotions_keep_at_least_one_admin(server: PgServer) -> None:
    with server.connect("bitscan_app") as setup:
        admins = [add_admin(setup) for _ in range(3)]
    barrier = threading.Barrier(len(admins))
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(uid: int) -> None:
        with tx_conn(server) as c:
            barrier.wait(10)
            try:
                demote(c, uid)
                result = "ok"
            except UserRuleError as exc:
                result = exc.rule.value
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, args=(u,)) for u in admins]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert outcomes.count("ok") == 2 and outcomes.count("last_admin") == 1
    with server.connect("bitscan_app") as c:
        assert len(active_admins(c)) == 1


def test_forced_rollback_leaves_neither_change_nor_entry(server: PgServer) -> None:
    """CHK-M2-229."""
    with tx_conn(server) as c:
        a, b = add_admin(c), add_admin(c)
        before = c.execute("SELECT count(*) FROM audit_log").fetchone()
        c.commit()
        with pytest.raises(LookupError), c.transaction():
            audit = TxAudit(PgAuditRepo(c), lambda hook: None)
            change_role(
                UserRepo(c),
                UserTokenRepo(c),
                audit,
                actor="user:0",
                user_id=b,
                role="viewer",
                now=NOW,
            )
            raise LookupError("forced rollback after the change")
        assert c.execute(
            "SELECT role::text FROM app_user WHERE user_id = %s", (b,)
        ).fetchone() == ("admin",)
        assert c.execute("SELECT count(*) FROM audit_log").fetchone() == before
        assert sorted(active_admins(c)) == sorted([a, b])
