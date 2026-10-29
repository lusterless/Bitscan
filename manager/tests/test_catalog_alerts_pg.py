"""G60 (TP-M7-*, CHK-M7-286): every M7 catalog alert end to end.

TS §8.4 L1288–L1291 (policy imported, rebuilt or deleted; disabled policy
re-enabled; any rejected import; catalog integrity check failed), "Delivery"
(every alert is an audit entry with `detail.alert = true`, so it reaches
BITSCAN_AUDIT_SINK, and is counted in `bitscan_alerts_total{kind}`); REQ-162
(5); #101 (actions, kinds, actors; the import-failure metric). Each alert is
raised through its real path (pipeline, delete service, PATCH service,
rebuild, start-up) and checked for: one entry with the kind and actor, the
counter +1 exactly, and delivery of that entry to a sink through the audit
shipper (`Shipper.run_once`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.services.audit.disk_queue import DiskQueue
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import SinkRecord
from bitscan_manager.services.importer import rebuild as rb
from bitscan_manager.services.importer import uploads
from bitscan_manager.services.importer.delete import delete_policy
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.profiles import change_status
from bitscan_manager.services.importer.startup import run_once

from .catalog_rows import T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, doc, make_env, plug

pytestmark = pytest.mark.pg

ADMIN = Actor("user:61", 61)
KINDS = [
    "policy_imported", "policy_import_rejected", "policy_deleted", "policy_rebuilt",
    "policy_reenabled", "catalog_integrity_failed",
]  # fmt: skip


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[SinkRecord] = []

    def send(self, records: Sequence[SinkRecord]) -> None:
        self.records.extend(records)

    def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("catalog-alerts")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
    yield from make_env(server, tmp_path)


@pytest.fixture
def sink(env: Env, tmp_path: Path) -> Iterator[tuple[Shipper, RecordingSink]]:
    rec = RecordingSink()
    shipper = Shipper(
        PgAuditTail(env.db), DiskQueue(tmp_path / "q"), rec, env.clock,
        DbOutageAudit(env.db),
    )  # fmt: skip
    yield shipper, rec


def counts() -> dict[str, float]:
    return {
        k: REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": k}) or 0.0
        for k in KINDS
    } | {
        f"fail:{m}": REGISTRY.get_sample_value(
            "bitscan_import_failures_total", {"mode": m}
        )
        or 0.0
        for m in ("auto", "manual", "rebuild")
    }


def moved(before: dict[str, float]) -> dict[str, float]:
    return {k: v - before[k] for k, v in counts().items() if v != before[k]}


def alerts_after(e: Env, mark: int) -> list[dict[str, Any]]:
    out = []
    with app(e.server) as c:
        for aid, actor, action, target, detail in c.execute(
            "SELECT audit_id, actor, action, target, detail::text FROM audit_log"
            " WHERE audit_id > %s ORDER BY audit_id",
            (mark,),
        ).fetchall():
            d = json.loads(detail)
            if d.get("alert") is True:
                out.append(
                    {"id": aid, "actor": actor, "action": action, "target": target,
                     "kind": d["alert_kind"], "detail": d}
                )  # fmt: skip
    return out


def shipped(sh: tuple[Shipper, RecordingSink], alert: dict[str, Any]) -> None:
    shipper, rec = sh
    for _ in range(20):  # the shipper re-sends the history first; bounded
        shipper.run_once()
        if any(r.audit_id == alert["id"] for r in rec.records):
            break
    (r,) = [r for r in rec.records if r.audit_id == alert["id"]]
    assert (r.actor, r.action) == (alert["actor"], alert["action"])
    assert r.detail_text is not None
    d = json.loads(r.detail_text)
    assert (d["alert"], d["alert_kind"]) == (True, alert["kind"])


def one(e: Env, mark: int, kind: str) -> dict[str, Any]:
    hits = [a for a in alerts_after(e, mark) if a["kind"] == kind]
    assert len(hits) == 1, (kind, alerts_after(e, mark))
    return hits[0]


# -----------------------------------------------------------------------------------


def test_policy_imported(env: Env, sink: tuple[Shipper, RecordingSink]) -> None:
    m0, c0 = env.mark(), counts()
    out = env.imp(doc(f"I {tag()}", [plug("cat /etc/shadow")]), "i.bit", actor=ADMIN)
    a = one(env, m0, "policy_imported")
    assert (a["action"], a["target"], a["actor"]) == (
        "policy.import", f"policy:{out.policy_id}", "user:61",
    )  # fmt: skip
    (ce,) = a["detail"]["changed_executes"]
    assert ce["execute"] == "cat /etc/shadow" and ce["flags"] == ["shadow"]
    assert moved(c0) == {"policy_imported": 1.0}
    shipped(sink, a)


def test_policy_import_rejected_and_the_failure_metric(
    env: Env, sink: tuple[Shipper, RecordingSink]
) -> None:
    m0, c0 = env.mark(), counts()
    env.imp(doc(f"R {tag()}", [plug("rm x")]), "r.bit", mode="auto")
    a = one(env, m0, "policy_import_rejected")
    assert (a["action"], a["target"], a["actor"]) == (
        "policy.import_rejected", "r.bit", "system",
    )  # fmt: skip
    assert moved(c0) == {"policy_import_rejected": 1.0, "fail:auto": 1.0}
    shipped(sink, a)


def test_policy_deleted(env: Env, sink: tuple[Shipper, RecordingSink]) -> None:
    out = uploads.upload(
        env.db, env.clock, env.bits, doc(f"D {tag()}", [plug()]), b"d", ADMIN
    )
    m0, c0 = env.mark(), counts()
    delete_policy(env.db, out.policy_id or 0, actor="user:61", clock=env.clock,
                  bits_dir=env.bits)  # fmt: skip
    a = one(env, m0, "policy_deleted")
    assert (a["action"], a["target"], a["actor"]) == (
        "policy.delete", f"policy:{out.policy_id}", "user:61",
    )  # fmt: skip
    assert moved(c0) == {"policy_deleted": 1.0}
    shipped(sink, a)


def test_policy_reenabled_by_patch_and_by_file(
    env: Env, sink: tuple[Shipper, RecordingSink]
) -> None:
    name, p = f"E {tag()}", plug()
    out = env.imp(doc(name, [p], status="disabled"), "e.bit")
    pid = out.policy_id or 0
    m0, c0 = env.mark(), counts()
    with env.db.transaction() as tx:
        change_status(tx, pid, "enabled", actor="user:61", now=env.clock.now())
    a = one(env, m0, "policy_reenabled")
    assert (a["action"], a["actor"], a["detail"]["by"]) == (
        "policy.status_change", "user:61", "patch",
    )  # fmt: skip
    assert moved(c0) == {"policy_reenabled": 1.0}
    shipped(sink, a)
    q = env.imp(doc(f"F {tag()}", [plug()], status="disabled"), "f.bit")
    m1, c1 = env.mark(), counts()
    env.imp(doc(env.policy(q.policy_id or 0)["policy_name"], [plug()]), "f.bit")
    b = one(env, m1, "policy_reenabled")
    assert b["detail"]["by"] == "file"
    assert moved(c1) == {"policy_reenabled": 1.0, "policy_imported": 1.0}
    shipped(sink, b)


def test_policy_rebuilt(env: Env, sink: tuple[Shipper, RecordingSink]) -> None:
    (env.bits / "b.bit").write_bytes(doc(f"B {tag()}", [plug()]))
    m0, c0 = env.mark(), counts()
    tid = rb.start_task(env.db, env.clock, 61)
    assert rb.run(env.db, env.clock, env.bits, tid, ADMIN).state == "succeeded"
    a = one(env, m0, "policy_rebuilt")
    assert (a["action"], a["actor"], a["detail"]["task_id"]) == (
        "bits.rebuild", "user:61", str(tid),
    )  # fmt: skip
    assert moved(c0) == {"policy_rebuilt": 1.0, "policy_imported": 1.0}
    shipped(sink, a)


def test_catalog_integrity_failed(
    env: Env, sink: tuple[Shipper, RecordingSink]
) -> None:
    (env.bits / "c.bit").write_bytes(doc(f"C {tag()}", [plug(), plug()]))
    run_once(env.db, env.clock, env.bits)
    with owner(env.server) as c:
        c.execute("UPDATE plugin SET state = 'retired' WHERE plugin_uuid IN"
                  " (SELECT plugin_uuid FROM policy_plugin pp JOIN policy p USING"
                  " (policy_id) WHERE p.deleted_at IS NULL)")  # fmt: skip
    m0, c0 = env.mark(), counts()
    run_once(env.db, env.clock, env.bits)
    a = one(env, m0, "catalog_integrity_failed")
    assert (a["action"], a["actor"], a["target"]) == (
        "catalog.integrity_check", "system", None,
    )  # fmt: skip
    assert a["detail"]["difference_count"] >= 1
    assert moved(c0) == {"catalog_integrity_failed": 1.0}
    shipped(sink, a)


def test_a_clean_run_raises_no_alert(env: Env) -> None:
    (env.bits / "k.bit").write_bytes(doc(f"K {tag()}", [plug()]))
    run_once(env.db, env.clock, env.bits)
    m0, c0 = env.mark(), counts()
    run_once(env.db, env.clock, env.bits)  # unchanged: skipped, consistent
    assert alerts_after(env, m0) == [] and moved(c0) == {}
