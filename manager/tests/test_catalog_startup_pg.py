"""TP-M7-18 (TASK-158): the catalog start-up sequence and the #103 integrity
check, on PostgreSQL with temporary folders (Linux only).

CHK-M7-230 (tests/m7/test-plan.md). Expected values come from the spec and
the approved answers, not from the code: TS §4.1 L528 (before anything else,
finish interrupted uploads; then reconcile both folders), §4.2 L540 (tasks
still `running` at start-up are marked `failed`), L542 (an integrity check
compares row counts and a hash per policy with the files, and alerts if they
differ), §8.4 L1291; REQ-165 (1)–(4), (6); #27 (the check runs after the
reconcile), #102 (d) (retry every 10 s while the database is unreachable),
#103 (the checks; one alert listing up to 100 differences; a clean catalog
raises nothing; a leftover of an interrupted delete is one difference), #98
(g) (fixed task error text); the crash-window ruling.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.importer import folders, integrity, uploads
from bitscan_manager.services.importer import rebuild as rb
from bitscan_manager.services.importer import startup as su
from bitscan_manager.services.importer.folders import LEFTOVER
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.pipeline import import_one as real_import_one
from bitscan_manager.services.importer.startup import (
    TASK_INTERRUPTED,
    StartupReport,
    run,
    run_once,
)

from .catalog_rows import T0, T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, doc, make_env, plug, sha

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(os.name != "posix", reason="Linux file semantics (W only)"),
]

ADMIN = Actor("user:41", 41)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("startup")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    # Each test owns its folders; earlier tests' live policies are
    # soft-deleted, and earlier running tasks finished, first.
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
        imports_repo.fail_running_tasks(c, {"error": "earlier test"}, T2)
    yield from make_env(server, tmp_path)


def put(e: Env, rel: str, data: bytes) -> Path:
    p = e.bits / rel
    p.write_bytes(data)
    return p


def upload(e: Env, data: bytes) -> int:
    out = uploads.upload(e.db, e.clock, e.bits, data, b"c.bit", ADMIN)
    assert out.outcome == "success"
    return out.policy_id or 0


def integrity_alerts(e: Env, mark: int) -> list[dict[str, Any]]:
    return [
        x["detail"] for x in e.entries(mark) if x["action"] == "catalog.integrity_check"
    ]


def diffs(report: StartupReport) -> list[tuple[str, str]]:
    return [(d.subject, d.check) for d in report.differences]


def lock_free(e: Env) -> bool:
    with app(e.server) as c:
        row = c.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
        if row == (True,):
            c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    return row == (True,)


# Order and lock ------------------------------------------------------------------


def test_the_steps_run_in_order_under_one_lock(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(env, "a.bit", doc(f"A {tag()}", [plug()]))
    run_once(env.db, env.clock, env.bits)
    with owner(env.server) as c:  # one difference, so the alert step runs
        c.execute("UPDATE plugin SET state = 'retired'")
    log: list[tuple[str, bool]] = []

    def spy(name: str, fn: Any) -> Any:
        def wrapped(*a: Any, **k: Any) -> Any:
            log.append((name, lock_free(env)))
            return fn(*a, **k)

        return wrapped

    for name in ("finish_interrupted", "fail_running_tasks", "reconcile", "check",
                 "alert"):  # fmt: skip
        monkeypatch.setattr(su, name, spy(name, getattr(su, name)))
    run_once(env.db, env.clock, env.bits)
    assert log == [
        ("finish_interrupted", False), ("fail_running_tasks", False),
        ("reconcile", False), ("check", False), ("alert", False),
    ]  # fmt: skip
    assert lock_free(env)  # released at the end


# REQ-165 (1), (2), (3) ------------------------------------------------------------


def test_interrupted_uploads_are_finished_first(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = upload(env, doc(f"Fin {tag()}", [plug()]))
    v2 = doc(env.policy(pid)["policy_name"], [plug()], desc="v2")

    def broken(src: Any, dst: Any) -> None:
        raise OSError("rename failed")

    with monkeypatch.context() as mp:
        mp.setattr(os, "replace", broken)
        with pytest.raises(OSError):
            uploads.upload(env.db, env.clock, env.bits, v2, b"c.bit", ADMIN)
    up = env.bits / "uploaded"
    (up / f".tmp-{pid}-{sha(b'never committed')}").write_bytes(b"never committed")
    (up / ".tmp-x").write_bytes(b"x")
    outside = env.bits.parent / "out.bit"
    outside.write_bytes(v2)
    (up / f".tmp-{pid}-{'b' * 64}").symlink_to(outside)
    report = run_once(env.db, env.clock, env.bits)
    assert (report.finished.renamed, report.finished.deleted) == (1, 3)
    assert (up / f"policy-{pid}.bit").read_bytes() == v2
    assert sorted(p.name for p in up.iterdir()) == [f"policy-{pid}.bit"]
    assert outside.read_bytes() == v2
    assert report.differences == ()  # the finished upload matches its catalog


def test_running_tasks_are_marked_failed(env: Env) -> None:
    with app(env.server) as c, c.transaction():
        running = imports_repo.insert_task(c, 41, T0)
        done = imports_repo.insert_task(c, None, T0)
        imports_repo.finish_task(c, done, "succeeded", {"files": []}, T0)
    report = run_once(env.db, env.clock, env.bits)
    assert report.failed_tasks == (running,)
    with app(env.server) as c:
        r = imports_repo.get_task(c, running)
        d = imports_repo.get_task(c, done)
    assert r is not None and d is not None
    assert (r.state, r.result, r.finished_at) == (
        "failed", {"error": TASK_INTERRUPTED}, env.clock.now(),
    )  # fmt: skip
    assert (d.state, d.result) == ("succeeded", {"files": []})


def test_files_added_and_removed_while_down(env: Env) -> None:
    gone = put(env, "gone.bit", doc(f"Gone {tag()}", [plug()]))
    run_once(env.db, env.clock, env.bits)
    gid = (env.policy_by_name(gone.read_text().split("<PolicyName>")[1].split("<")[0])
           or {})["policy_id"]  # fmt: skip
    gone.unlink()
    put(env, "new.bit", doc(f"New {tag()}", [plug()]))
    m0 = env.mark()
    report = run_once(env.db, env.clock, env.bits)
    assert report.reconciled.deleted == [gid]
    assert [rel for rel, o in report.reconciled.outcomes if o.outcome == "success"] == [
        "new.bit"
    ]
    assert integrity_alerts(env, m0) == []  # consistent afterwards


# REQ-165 (4), #103 ----------------------------------------------------------------


def test_a_clean_catalog_raises_no_alert(env: Env) -> None:
    put(env, "c1.bit", doc(f"C1 {tag()}", [plug()]))
    upload(env, doc(f"C2 {tag()}", [plug()]))
    run_once(env.db, env.clock, env.bits)
    m0 = env.mark()
    report = run_once(env.db, env.clock, env.bits)
    assert report.differences == () and integrity_alerts(env, m0) == []


def test_owner_corruptions_raise_one_alert_naming_them(env: Env) -> None:
    t = tag()
    pa, pb, pc = (
        [plug(), plug()],
        [plug(), plug()],
        [plug(), plug()],
    )
    put(env, "pa.bit", doc(f"PA {t}", pa))
    put(env, "pb.bit", doc(f"PB {t}", pb))
    put(env, "pc.bit", doc(f"PC {t}", pc))
    run_once(env.db, env.clock, env.bits)
    ids = {k: (env.policy_by_name(f"{k} {t}") or {})["policy_id"] for k in ("PA", "PB")}
    with owner(env.server) as c:
        c.execute("DELETE FROM policy_plugin WHERE policy_id = %s AND plugin_uuid = %s",
                  (ids["PA"], pa[1].uuid))  # fmt: skip
        c.execute("UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
                  (pb[0].uuid,))  # fmt: skip
    m0 = env.mark()
    report = run_once(env.db, env.clock, env.bits)
    assert sorted(diffs(report)) == sorted([
        (f"policy:{ids['PA']}", integrity.COUNT),
        (f"policy:{ids['PB']}", integrity.PLUGINS),
    ])  # fmt: skip
    (detail,) = integrity_alerts(env, m0)
    assert (detail["alert"], detail["alert_kind"]) == (True, "catalog_integrity_failed")
    assert detail["difference_count"] == 2
    assert sorted((d["subject"], d["check"]) for d in detail["differences"]) == sorted(
        diffs(report)
    )
    actors = {
        x["actor"] for x in env.entries(m0) if x["action"] == "catalog.integrity_check"
    }
    assert actors == {"system"}


def test_a_changed_source_sha256_is_repaired_by_the_reconcile(env: Env) -> None:
    # Lead's ruling "TASK-158 test questions" (1): with the check after the
    # reconcile (#27), the reconcile re-imports the file whose hash no longer
    # equals source_sha256: a success row, version +1 and its policy_imported
    # alert (TS L530); the integrity check then finds nothing.
    name = f"PS {tag()}"
    put(env, "ps.bit", doc(name, [plug()]))
    run_once(env.db, env.clock, env.bits)
    pol = env.policy_by_name(name)
    assert pol is not None
    with owner(env.server) as c:
        c.execute("UPDATE policy SET source_sha256 = repeat('0', 64)"
                  " WHERE policy_id = %s", (pol["policy_id"],))  # fmt: skip
    m0, i0 = env.mark(), env.last_import()
    report = run_once(env.db, env.clock, env.bits)
    assert [(r["file_name"], r["outcome"]) for r in env.imports_after(i0)] == [
        ("ps.bit", "success")
    ]
    after = env.policy(pol["policy_id"])
    assert after["version"] == pol["version"] + 1
    assert after["source_sha256"] == pol["source_sha256"]
    imported = [x for x in env.entries(m0) if x["action"] == "policy.import"]
    assert [x["target"] for x in imported] == [f"policy:{pol['policy_id']}"]
    assert imported[0]["detail"]["alert_kind"] == "policy_imported"
    assert report.differences == () and integrity_alerts(env, m0) == []


def test_a_file_that_is_neither_a_policy_nor_rejected_is_reported(env: Env) -> None:
    name = f"Managed {tag()}"
    put(env, "managed.bit", doc(name, [plug()]))
    put(env, "uploaded/copy.bit", doc(name, [plug()], desc="copy"))  # refused
    put(env, "bad.bit", doc(f"Bad {tag()}", [plug("rm x")]))  # rejected row: fine
    m0 = env.mark()
    report = run_once(env.db, env.clock, env.bits)
    assert diffs(report) == [("uploaded/copy.bit", integrity.UNKNOWN)]
    assert len(integrity_alerts(env, m0)) == 1


def test_the_crash_window_leftover_is_one_difference(env: Env) -> None:
    pid = upload(env, doc(f"Left {tag()}", [plug()]))
    keep = upload(env, doc(f"Keep {tag()}", [plug()]))
    left = env.bits / "uploaded" / f"policy-{pid}.bit"
    with app(env.server) as c, c.transaction():
        assert adm.soft_delete_effects(c, pid, T2) is not None  # crash before unlink
    m0, i0 = env.mark(), env.last_import()
    report = run_once(env.db, env.clock, env.bits)
    assert not left.exists() and env.policy(pid)["deleted_at"] is not None
    assert [
        r for r in env.imports_after(i0) if r["file_name"].endswith(left.name)
    ] == []
    assert diffs(report) == [(f"uploaded/policy-{pid}.bit", LEFTOVER)]
    (detail,) = integrity_alerts(env, m0)
    assert detail["differences"] == [
        {"subject": f"uploaded/policy-{pid}.bit", "check": LEFTOVER}
    ]
    assert env.policy(keep)["deleted_at"] is None


def test_only_live_uploads_raise_no_alert(env: Env) -> None:
    upload(env, doc(f"L1 {tag()}", [plug()]))
    upload(env, doc(f"L2 {tag()}", [plug()]))
    m0 = env.mark()
    assert run_once(env.db, env.clock, env.bits).differences == ()
    assert integrity_alerts(env, m0) == []


# REQ-165 (6), #102 (d): retry; the TASK-156 carry ------------------------------------


def test_run_retries_while_the_database_refuses(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    put(env, "r.bit", doc(f"R {tag()}", [plug()]))
    real = env.db.session
    fails = [2]

    def refusing() -> Any:
        if fails[0]:
            fails[0] -= 1
            raise psycopg.OperationalError("connection refused")
        return real()

    monkeypatch.setattr(env.db, "session", refusing)
    stop = threading.Event()
    report = run(env.db, env.clock, env.bits, stop, retry_s=0.05)
    assert report is not None and fails == [0]
    assert caplog.text.count("catalog start-up failed, retrying: OperationalError") == 2
    assert "connection refused" not in caplog.text


def test_run_returns_none_once_stopped(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> Any:
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(env.db, "session", down)
    stop = threading.Event()
    out: dict[str, Any] = {}

    def go() -> None:
        out["r"] = run(env.db, env.clock, env.bits, stop, retry_s=30)

    t = threading.Thread(target=go)
    t.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    stop.set()
    t.join(5)
    assert not t.is_alive() and time.monotonic() - t0 < 2.0
    assert out["r"] is None


def test_a_failed_import_pass_deletes_nothing_and_the_retry_completes(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = tag()
    gone = put(env, "g.bit", doc(f"G {t}", [plug()]))
    run_once(env.db, env.clock, env.bits)
    gid = (env.policy_by_name(f"G {t}") or {})["policy_id"]
    gone.unlink()
    put(env, "n1.bit", doc(f"N1 {t}", [plug()]))
    put(env, "n2.bit", doc(f"N2 {t}", [plug()]))
    seen: list[str] = []
    at_failure: list[Any] = []

    def flaky(*a: Any, **k: Any) -> Any:
        seen.append(a[3].file_name)
        if len(seen) == 2:
            at_failure.append(env.policy(gid)["deleted_at"])
            raise psycopg.OperationalError("injected")
        return real_import_one(*a, **k)

    monkeypatch.setattr(folders, "import_one", flaky)
    report = run(env.db, env.clock, env.bits, threading.Event(), retry_s=0.05)
    assert report is not None
    assert at_failure == [None]  # nothing deleted in the failed attempt
    assert env.policy(gid)["deleted_at"] is not None  # the retry deleted it
    for name in ("N1", "N2"):
        assert env.policy_by_name(f"{name} {t}") is not None


# The reviewer's race: a CLI rebuild's task row, then the start-up ---------------------


def test_a_rebuild_whose_task_the_start_up_failed_changes_nothing(env: Env) -> None:
    # The reviewer's race (TASK-157 r2, ruling "TASK-158 test questions" (2)):
    # a CLI rebuild wrote its running task row, then the start-up took the
    # lock first and marked it failed. rebuild.run re-reads the task after
    # taking the lock and, as it is no longer running, changes nothing.
    name = f"X {tag()}"
    put(env, "x.bit", doc(name, [plug()]))
    run_once(env.db, env.clock, env.bits)
    tid = rb.start_task(env.db, env.clock, None)  # running, no lock yet
    report = run_once(env.db, env.clock, env.bits)  # the start-up wins the lock
    assert tid in report.failed_tasks
    put(env, "x.bit", doc(name, [plug()], desc="changed"))  # a rebuild would store it
    cat0, i0, m0 = env.catalog(), env.last_import(), env.mark()
    r0 = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": "policy_rebuilt"})
    result = rb.run(env.db, env.clock, env.bits, tid, Actor("cli:root", None))
    assert result.state == "failed" and result.reason
    with app(env.server) as c:
        final = imports_repo.get_task(c, tid)
    assert final is not None
    assert (final.state, final.result) == ("failed", {"error": TASK_INTERRUPTED})
    assert env.catalog() == cat0  # no catalog change
    assert env.imports_after(i0) == [] and env.entries(m0) == []  # no bits.rebuild
    r1 = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": "policy_rebuilt"})
    assert r1 == r0  # no policy_rebuilt alert


def test_a_rebuild_of_an_unknown_task_changes_nothing(env: Env) -> None:
    put(env, "y.bit", doc(f"Y {tag()}", [plug()]))
    cat0, i0, m0 = env.catalog(), env.last_import(), env.mark()
    result = rb.run(env.db, env.clock, env.bits, uuid4(), Actor("cli:root", None))
    assert result.state == "failed" and result.reason
    assert env.catalog() == cat0 and env.imports_after(i0) == []
    assert env.entries(m0) == []
