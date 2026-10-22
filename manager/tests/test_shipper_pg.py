"""REQ-053 (2), (5), (6) on PostgreSQL: the shipper sends committed rows only,
picks up other-process (CLI) entries by polling, and delivers within 5 s
(TASK-034; CHK-M2-127 to CHK-M2-129, #51). A fake HTTPS sink is not needed: a
recording transport stands in for it, so this tests the read side.
"""

import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import SystemClock
from bitscan_manager.services.audit.chain import (
    HashInput,
    append_entry,
    compute_row_hash,
)
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import SinkRecord

from .conftest import PgServer

pytestmark = pytest.mark.pg


class Recorder:
    def __init__(self) -> None:
        self.received: list[SinkRecord] = []
        self.at: dict[int, float] = {}
        self.lock = threading.Lock()

    def send(self, records: Sequence[SinkRecord]) -> None:
        with self.lock:
            for r in records:
                self.received.append(r)
                self.at.setdefault(r.audit_id, time.monotonic())

    def close(self) -> None:
        return None


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    d.open()
    yield d
    d.close()


@pytest.fixture
def shipped(db: AppDatabase, tmp_path: Path) -> Iterator[tuple[Shipper, Recorder]]:
    rec = Recorder()
    s = Shipper(
        PgAuditTail(db),
        DiskQueue(tmp_path / "q"),
        rec,
        SystemClock(),
        DbOutageAudit(db),
    )
    yield s, rec
    s.stop(timeout_s=5)


def wait_for(pred: object, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(pred) and pred():
            return True
        time.sleep(0.05)
    return False


def actions(rec: Recorder) -> list[str]:
    return [r.action for r in rec.received]


def test_rolled_back_entries_are_never_sent(
    db: AppDatabase, shipped: tuple[Shipper, Recorder]
) -> None:
    """CHK-M2-127."""
    shipper, rec = shipped
    with db.transaction() as tx:
        append_entry(PgAuditRepo(tx.conn), actor="system", action="test.ship_before")
    with pytest.raises(LookupError):
        with db.transaction() as tx:
            append_entry(
                PgAuditRepo(tx.conn), actor="system", action="test.ship_rolled"
            )
            raise LookupError("rollback")
    with db.transaction() as tx:
        append_entry(PgAuditRepo(tx.conn), actor="system", action="test.ship_after")
    shipper.start()
    assert wait_for(lambda: "test.ship_after" in actions(rec))
    assert "test.ship_before" in actions(rec)
    assert "test.ship_rolled" not in actions(rec)
    got = [r.audit_id for r in rec.received]
    assert got == sorted(got) and len(got) == len(set(got))
    for r in rec.received:  # delivered rows re-hash (REQ-053 (3))
        again = compute_row_hash(
            r.prev_hash,
            HashInput(
                r.audit_id, r.actor, r.action, r.target, r.detail_text, r.at_text
            ),
        )
        assert again == r.row_hash


def test_other_process_entries_arrive_by_polling_within_5_s(
    migrated_db: PgServer, shipped: tuple[Shipper, Recorder]
) -> None:
    """CHK-M2-128: an entry written on another connection, with no wake()."""
    shipper, rec = shipped
    shipper.start()
    time.sleep(1.5)
    with psycopg.connect(migrated_db.dsn("bitscan_app")) as other:
        with other.transaction():
            entry = append_entry(
                PgAuditRepo(other), actor="cli:root", action="test.ship_cli"
            )
    committed = time.monotonic()
    assert wait_for(lambda: entry.audit_id in rec.at, timeout=10)
    assert rec.at[entry.audit_id] - committed < 5.0


def test_in_process_entries_arrive_within_5_s(
    db: AppDatabase, shipped: tuple[Shipper, Recorder]
) -> None:
    """CHK-M2-129: 20 entries, each woken on commit as serve will wire it."""
    shipper, rec = shipped
    shipper.start()
    delays = []
    for i in range(20):
        with db.transaction() as tx:
            entry = append_entry(
                PgAuditRepo(tx.conn), actor="system", action=f"test.ship_fast_{i}"
            )
            tx.on_commit(shipper.wake)
        committed = time.monotonic()
        assert wait_for(lambda e=entry: e.audit_id in rec.at, timeout=10)
        delays.append(rec.at[entry.audit_id] - committed)
    print(f"max delivery delay {max(delays):.3f} s")
    assert max(delays) < 5.0


def test_outage_alert_is_written_and_shipped_after_recovery(
    db: AppDatabase, tmp_path: Path, migrated_db: PgServer
) -> None:
    """DbOutageAudit writes audit.sink_unreachable (alert) and
    audit.sink_recovered (no alert) as real chained entries."""
    import json

    class Down(Recorder):
        up = False

        def send(self, records: Sequence[SinkRecord]) -> None:
            from bitscan_manager.services.audit.sink_transport import DeliveryError

            if not self.up:
                raise DeliveryError("ConnectionRefusedError", 0)
            super().send(records)

    rec = Down()
    s = Shipper(
        PgAuditTail(db),
        DiskQueue(tmp_path / "q2"),
        rec,
        SystemClock(),
        DbOutageAudit(db),
    )
    with db.transaction() as tx:
        append_entry(PgAuditRepo(tx.conn), actor="system", action="test.ship_outage")
    s.run_once()
    rec.up = True
    for _ in range(40):
        s.run_once()
        if "audit.sink_recovered" in actions(rec):
            break
        time.sleep(0.25)
    acts = actions(rec)
    assert "test.ship_outage" in acts and "audit.sink_unreachable" in acts
    assert acts.index("audit.sink_unreachable") < len(acts)
    alert = next(r for r in rec.received if r.action == "audit.sink_unreachable")
    assert alert.actor == "system"
    assert json.loads(alert.detail_text or "{}") == {
        "alert": True,
        "alert_kind": "audit_sink_unreachable",
    }
    with migrated_db.connect("bitscan_app") as c:
        recovered = c.execute(
            "SELECT detail::text FROM audit_log WHERE action = 'audit.sink_recovered'"
            " ORDER BY audit_id DESC LIMIT 1"
        ).fetchone()
    assert recovered is not None
    assert recovered[0] is None or '"alert"' not in recovered[0]
