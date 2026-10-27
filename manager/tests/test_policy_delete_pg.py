"""TP-M7-13 (TASK-152): the policy delete service on PostgreSQL with a
temporary bits folder.

CHK-M7-224, -225 (tests/m7/test-plan.md). Expected values: TS §4.3 L550 (soft
delete: deleted_at, source_file deleted/<id>, queued jobs cancelled, schedules
disabled, plugins retired, the uploaded file deleted, 409 for server-folder
policies, every delete alerts and is audit-logged), TS §4.1 L526 (the catalog
lock is held until the file is deleted), REQ-167 (1), (2), (5), (6), REQ-161
(2); #98 (e), #101 (`policy.delete` = the `policy_deleted` alert, actor).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.importer import delete as dl
from bitscan_manager.services.importer import store
from bitscan_manager.services.importer import store_decide as sd

from . import catalog_rows as cr
from .catalog_rows import T1, T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_store_pg import cand, cp, ok, rules, server_t, upload_t

pytestmark = pytest.mark.pg


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("delete")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    (tmp_path / "uploaded").mkdir()
    return tmp_path


def alerts() -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": "policy_deleted"})
    return 0.0 if v is None else v


def committed(server: PgServer, upload: bool = True) -> store.StoreResult:
    with app(server) as s, s.transaction():
        target = upload_t() if upload else server_t(f"{tag()}.bit")
        return ok(s, cand([cp(), cp()]), target)


def entries(server: PgServer, target: str) -> list[dict[str, Any]]:
    with app(server) as c:
        rows = c.execute(
            "SELECT actor, action, target, detail::text FROM audit_log"
            " WHERE target = %s ORDER BY audit_id",
            (target,),
        ).fetchall()
    return [
        {"actor": a, "action": b, "target": t, "detail": json.loads(d)}
        for a, b, t, d in rows
    ]


def state(server: PgServer) -> dict[str, str]:
    with owner(server) as o:
        return {
            t: cr.checksum(o, t, k)
            for t, k in [
                ("policy", "policy_id"),
                ("plugin", "plugin_uuid"),
                ("policy_plugin", "policy_id, plugin_uuid"),
                ("scan_job", "job_id"),
                ("scan_schedule", "schedule_id"),
                ("audit_log", "audit_id"),
            ]
        }


def catalog_free(server: PgServer) -> bool:
    with app(server) as c:
        row = c.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
        assert row is not None
        if row[0]:
            c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        return bool(row[0])


# CHK-M7-224: REQ-167 (1) ------------------------------------------------------


def test_route_delete_has_exactly_the_req_167_effects(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    r = committed(server)
    upload = bits / "uploaded" / f"policy-{r.policy_id}.bit"
    upload.write_bytes(b"<Policy/>")
    keep = bits / "uploaded" / "policy-999999.bit"
    keep.write_bytes(b"other")
    with owner(server) as o:
        _, jobs = cr.scan_with_jobs(
            o, r.policy_id, cr.agent(o), ["queued", "dispatched", "running"]
        )
        s1, s2 = cr.schedule(o, r.policy_id), cr.schedule(o, r.policy_id)
    n0 = alerts()
    res = dl.delete_policy(
        db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
    )
    assert (res.policy_id, res.source_file) == (r.policy_id, r.source_file)
    assert res.effects.cancelled_job_ids == [jobs["queued"]]
    assert res.effects.disabled_schedule_ids == sorted([s1, s2])
    assert res.remove_after_commit == (r.source_file,)
    assert not upload.exists() and keep.read_bytes() == b"other"
    with owner(server) as o:
        states = dict(
            o.execute(
                "SELECT job_id, state::text FROM scan_job WHERE job_id = ANY(%s)",
                (list(jobs.values()),),
            ).fetchall()
        )
        assert states == {
            jobs["queued"]: "cancelled",
            jobs["dispatched"]: "dispatched",
            jobs["running"]: "running",
        }
        pol = o.execute(
            "SELECT deleted_at, source_file FROM policy WHERE policy_id = %s",
            (r.policy_id,),
        ).fetchone()
        assert pol == (T2, f"deleted/{r.policy_id}")
        plug = o.execute(
            "SELECT DISTINCT state::text FROM plugin WHERE owner_policy_id = %s",
            (r.policy_id,),
        ).fetchall()
        assert plug == [("retired",)]
        en = o.execute(
            "SELECT bool_or(enabled) FROM scan_schedule WHERE policy_id = %s",
            (r.policy_id,),
        ).fetchone()
        assert en == (False,)
    (entry,) = entries(server, f"policy:{r.policy_id}")[-1:]
    assert entry["actor"] == "user:1" and entry["action"] == "policy.delete"
    assert entry["detail"] == {
        "alert": True,
        "alert_kind": "policy_deleted",
        "policy_id": r.policy_id,
        "policy_name": r.policy_name,
        "source_file": r.source_file,
        "reason": "deleted through the API",
    }
    assert [e["action"] for e in entries(server, f"policy:{r.policy_id}")].count(
        "policy.delete"
    ) == 1
    assert alerts() == n0 + 1
    assert catalog_free(server)


# CHK-M7-224: REQ-167 (2) and #98 (e) ------------------------------------------


def test_server_folder_policy_is_refused_and_nothing_changes(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    r = committed(server, upload=False)
    on_disk = bits / r.source_file
    on_disk.write_bytes(b"server file")
    before, n0 = state(server), alerts()
    with pytest.raises(store.PolicyManagedOnServer) as info:
        dl.delete_policy(
            db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
        )
    assert info.value.policy_id == r.policy_id
    assert state(server) == before and alerts() == n0
    assert on_disk.read_bytes() == b"server file"
    assert catalog_free(server)


def test_unknown_and_already_deleted(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    with pytest.raises(dl.PolicyNotFound):
        dl.delete_policy(db, 2**62, actor="user:1", clock=Clock(T2), bits_dir=bits)
    r = committed(server)
    dl.delete_policy(db, r.policy_id, actor="user:1", clock=Clock(T1), bits_dir=bits)
    before, n0 = state(server), alerts()
    with pytest.raises(dl.PolicyAlreadyDeleted):
        dl.delete_policy(
            db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
        )
    assert state(server) == before and alerts() == n0
    assert catalog_free(server)


# REQ-167 (5), (6) -------------------------------------------------------------


def test_a_new_policy_can_claim_the_deleted_policys_plugins(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    with app(server) as s, s.transaction():
        shared = cp()
        old = ok(s, cand([shared]), upload_t())
    with app(server) as c:
        count0 = c.execute("SELECT count(*) FROM policy").fetchone()
    dl.delete_policy(db, old.policy_id, actor="user:1", clock=Clock(T1), bits_dir=bits)
    with app(server) as s, s.transaction(force_rollback=True):
        new = cand([shared])
        d = sd.decide(s, rules(new), upload_t(), lambda p: False)
        assert sd.check_ownership(s, d, rules(new)) == ()  # no BIT015
        r = store.apply(s, d, new, upload_t(), T2)
        owner_now = s.execute(
            "SELECT owner_policy_id FROM plugin WHERE plugin_uuid = %s",
            (shared.plugin_uuid,),
        ).fetchone()
        assert owner_now == (r.policy_id,)
    with app(server) as c:
        assert c.execute("SELECT count(*) FROM policy").fetchone() == count0  # (6)


# CHK-M7-225: faults -----------------------------------------------------------


def test_fault_before_commit_leaves_the_row_and_the_file(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = committed(server)
    upload = bits / "uploaded" / f"policy-{r.policy_id}.bit"
    upload.write_bytes(b"<Policy/>")
    before, n0 = state(server), alerts()

    def failing_emit(*a: Any, **k: Any) -> Any:
        raise psycopg.errors.DiskFull("fault before commit")

    monkeypatch.setattr(dl, "emit", failing_emit)
    with pytest.raises(psycopg.errors.DiskFull):
        dl.delete_policy(
            db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
        )
    assert state(server) == before and alerts() == n0
    assert upload.read_bytes() == b"<Policy/>"
    assert catalog_free(server)


def test_core_rolls_back_with_the_callers_transaction(
    server: PgServer, db: AppDatabase
) -> None:
    r = committed(server)
    with owner(server) as o:
        cr.scan_with_jobs(o, r.policy_id, cr.agent(o), ["queued"])
        cr.schedule(o, r.policy_id)
    before, n0 = state(server), alerts()
    with db.session() as session:
        with pytest.raises(RuntimeError), session.transaction() as tx:
            res = dl.delete_in_tx(
                tx, r.policy_id, actor="system", reason="file removed", now=T2
            )
            assert res.effects.cancelled_job_ids != []
            raise RuntimeError("the outer import fails later")
    assert state(server) == before and alerts() == n0


def test_core_without_refusal_deletes_a_server_policy_and_keeps_its_file(
    server: PgServer, db: AppDatabase
) -> None:
    r = committed(server, upload=False)
    with db.session() as session, session.transaction() as tx:
        res = dl.delete_in_tx(
            tx, r.policy_id, actor="system", reason="file removed", now=T2
        )
    assert (
        res.remove_after_commit == ()
    )  # a server file is never removed by the manager
    (entry,) = [
        e
        for e in entries(server, f"policy:{r.policy_id}")
        if e["action"] == "policy.delete"
    ]
    assert entry["actor"] == "system" and entry["detail"]["reason"] == "file removed"


# REQ-161 (2): the delete waits for the catalog lock ---------------------------


def test_delete_waits_while_an_import_holds_the_lock(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    r = committed(server)
    done = threading.Event()
    errors: list[BaseException] = []
    with app(server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")

        def run() -> None:
            try:
                dl.delete_policy(
                    db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
                )
            except BaseException as exc:
                errors.append(exc)
            done.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        assert not done.wait(1.0), "delete did not wait for the catalog lock"
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        assert done.wait(15)
    assert errors == []


def test_two_racing_deletes_one_wins_one_alert(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    r = committed(server)
    n0 = alerts()
    out: list[str] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait(10)
        try:
            dl.delete_policy(
                db, r.policy_id, actor="user:1", clock=Clock(T2), bits_dir=bits
            )
            out.append("deleted")
        except dl.PolicyAlreadyDeleted:
            out.append("already")

    ts = [threading.Thread(target=run, daemon=True) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert sorted(out) == ["already", "deleted"]
    assert alerts() == n0 + 1


# remove_after_commit ----------------------------------------------------------


def test_remove_after_commit_removes_only_upload_paths(
    bits: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "victim.bit"
    outside.write_bytes(b"victim")
    (bits / "x.bit").write_bytes(b"server")
    (bits / "uploaded" / "policy-7.bit").write_bytes(b"u")
    (bits / "uploaded" / "policy-8.bit").symlink_to(outside)
    (bits / "uploaded" / ".tmp-7-").write_bytes(b"t")
    dl.remove_after_commit(
        bits,
        [
            "x.bit",
            "uploaded/../x.bit",
            "uploaded/policy-7.bit/../../x.bit",
            "uploaded/policy-١.bit",
            "uploaded/policy-.bit",
            "uploaded/.tmp-7-",
            "deleted/7",
            "uploaded/policy-7.bit",
            "uploaded/policy-8.bit",
            "uploaded/policy-9.bit",  # missing: no error
        ],
    )
    assert (bits / "x.bit").read_bytes() == b"server"
    assert (bits / "uploaded" / ".tmp-7-").exists()
    assert not (bits / "uploaded" / "policy-7.bit").exists()
    assert not (bits / "uploaded" / "policy-8.bit").is_symlink()
    assert outside.read_bytes() == b"victim"  # the link went, never its target


def test_remove_after_commit_logs_no_path(
    bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        dl.remove_after_commit(bits, ["../../etc/CANARY-path-91"])
    assert "CANARY-path-91" not in caplog.text
