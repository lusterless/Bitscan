"""REQ-055 (1), (2) on PostgreSQL: an alert commits with its transaction and
counts after COMMIT only (TASK-035; CHK-M2-135, -136)."""

import json
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.audit.alerts import raise_alert
from bitscan_manager.services.audit.metrics import REGISTRY

from .conftest import PgServer

pytestmark = pytest.mark.pg


def count(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    d.open()
    yield d
    d.close()


def rows(server: PgServer, action: str) -> list[dict[str, object]]:
    with server.connect("bitscan_app") as c:
        found = c.execute(
            "SELECT detail::text FROM audit_log WHERE action = %s ORDER BY audit_id",
            (action,),
        ).fetchall()
    return [json.loads(r[0]) for r in found]


def test_committed_alert_is_stored_and_counted(
    db: AppDatabase, migrated_db: PgServer
) -> None:
    before = count("api_token_created")
    with db.transaction() as tx:
        raise_alert(
            PgAuditRepo(tx.conn),
            tx.on_commit,
            kind="api_token_created",
            actor="user:1",
            action="test.alert_commit",
            detail={"token_id": 5},
        )
        assert count("api_token_created") == before
    assert count("api_token_created") == before + 1
    stored = rows(migrated_db, "test.alert_commit")
    assert stored == [{"alert": True, "alert_kind": "api_token_created", "token_id": 5}]


def test_rolled_back_alert_is_neither_stored_nor_counted(
    db: AppDatabase, migrated_db: PgServer
) -> None:
    before = count("user_created")
    with pytest.raises(LookupError):
        with db.transaction() as tx:
            raise_alert(
                PgAuditRepo(tx.conn),
                tx.on_commit,
                kind="user_created",
                actor="user:1",
                action="test.alert_rollback",
            )
            raise LookupError("forced rollback")
    assert count("user_created") == before
    assert rows(migrated_db, "test.alert_rollback") == []
