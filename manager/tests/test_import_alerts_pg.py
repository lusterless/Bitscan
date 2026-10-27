"""TASK-153 r2 on PostgreSQL: the rejected alert of a long uploaded/ file name
fits ``audit_log.target`` VARCHAR(255) (TS §5.2) and keeps the whole name in
``detail.file_name`` (reviewer-m7 should-fix). CHK-M7-187 (PG half)."""

import json
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.services.importer import alerts as ia
from bitscan_manager.services.importer.model import Code, Finding

from .conftest import PgServer

pytestmark = pytest.mark.pg


@pytest.fixture
def db(migrated_db: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(SecretStr(migrated_db.dsn("bitscan_app")), connect_timeout_s=3)
    d.open()
    yield d
    d.close()


@pytest.mark.parametrize("name", ["uploaded/" + "a" * 250 + ".bit", "é" * 300 + ".bit"])
def test_long_name_rejected_alert_is_stored(
    db: AppDatabase, migrated_db: PgServer, name: str
) -> None:
    ev = ia.rejected(
        import_id=1, mode="manual", file_name=name, file_sha256="f" * 64,
        policy_id=None, findings=[Finding(1, None, Code.BIT001, "x")],
    )  # fmt: skip
    with db.transaction() as tx:
        entry = ia.emit(PgAuditRepo(tx.conn), tx.on_commit, ev, actor="user:1")
    with migrated_db.connect("bitscan_app") as c:
        row = c.execute(
            "SELECT target, detail::text FROM audit_log WHERE audit_id = %s",
            (entry.audit_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == name[:255]
    detail = json.loads(row[1])
    assert (
        detail["file_name"] == name and detail["alert_kind"] == "policy_import_rejected"
    )
