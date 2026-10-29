"""TP-M7-20 (TASK-159): the folder watcher on Linux with temporary folders and
PostgreSQL.

CHK-M7-237, -238 (tests/m7/test-plan.md). Expected values come from the spec
and the approved answers, not from the code: TS §4.1 L528 (both folders
watched with inotify, `*.bit` only, no subfolders), L526 (each import under
the catalog lock); REQ-164 (1) to (5) (import within 5 s, re-import an edit,
delete within 5 s with its alert; a chunked write imported once and complete;
an upload's own temp write and rename add no row; without inotify one line
and the manager runs); #102 (a) (`IN_CLOSE_WRITE` and `IN_MOVED_TO` import,
`IN_DELETE` and `IN_MOVED_FROM` delete; a replaced folder → full reconcile),
(b) (names), (c) (the manager's own changes for 60 s, by hash); decisions
"W6 pre-read rulings" (2) (TASK-159 r1: in a batch, incoming paths first, so
`mv a.bit c.bit` is a move). "Within 5 s" is a bound polled every 50 ms.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import folders, inotify, uploads
from bitscan_manager.services.importer import watcher as wmod
from bitscan_manager.services.importer.delete import delete_policy
from bitscan_manager.services.importer.own_changes import OWN_CHANGES, OwnChanges
from bitscan_manager.services.importer.pipeline import Actor
from bitscan_manager.services.importer.watcher import Watcher

from . import catalog_rows as cr
from .catalog_rows import T2, app, owner, tag
from .conftest import PgServer, own_migrated_server
from .test_import_pipeline_pg import Env, counters, delta, doc, make_env, plug, sha
from .test_uploads_pg import MKFIFO, REAL_OPEN

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(not inotify.available(), reason="inotify (Linux, W only)"),
]

ADMIN = Actor("user:31", 31)
BOUND = 5.0


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("watcher")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[Env]:
    with app(server) as c, c.transaction():  # each test owns its folders
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        from bitscan_manager.repositories import catalog_admin as adm

        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)
    yield from make_env(server, tmp_path)


class Running:
    def __init__(self, w: Watcher) -> None:
        self.w, self.stop = w, threading.Event()
        self.t = threading.Thread(target=lambda: w.run(self.stop, poll=0.05))

    def __enter__(self) -> Running:
        self.t.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop.set()
        self.t.join(30)
        assert not self.t.is_alive()


@pytest.fixture
def watching(env: Env) -> Iterator[Watcher]:
    w = Watcher(env.db, env.clock, env.bits)
    assert w.open()
    with Running(w):
        yield w


def until(pred: Callable[[], Any], bound: float = BOUND) -> float:
    """Seconds until pred() is truthy; fails after `bound`."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < bound:
        if pred():
            return time.monotonic() - t0
        time.sleep(0.05)
    pytest.fail(f"not within {bound} s")


def rows(e: Env, i0: int, name: str | None = None) -> list[dict[str, Any]]:
    return [r for r in e.imports_after(i0) if name is None or r["file_name"] == name]


def settle(e: Env, i0: int) -> None:
    """Write a sentinel after the events under test and wait for its row, so
    everything queued before it has been handled."""
    name = f"zz-sentinel-{tag()}.bit"
    (e.bits / name).write_bytes(doc(f"Sentinel {tag()}", [plug()]))
    until(lambda: rows(e, i0, name))


def live(e: Env, name: str) -> dict[str, Any] | None:
    p = e.policy_by_name(name)
    return p if p is not None and p["deleted_at"] is None else None


# CHK-M7-237: REQ-164 (1) -----------------------------------------------------------


def test_copy_edit_and_remove_within_5_s(env: Env, watching: Watcher) -> None:
    name, p = f"W {tag()}", plug()
    i0 = env.last_import()
    src = env.bits.parent / "n.bit"
    src.write_bytes(doc(name, [p]))
    shutil.copy(src, env.bits / "n.bit")
    until(lambda: rows(env, i0, "n.bit"))
    (row,) = rows(env, i0, "n.bit")
    assert (row["outcome"], row["mode"], row["imported_by"]) == (
        "success",
        "auto",
        None,
    )
    pol = live(env, name)
    assert pol is not None and pol["source_file"] == "n.bit"
    (env.bits / "n.bit").write_bytes(doc(name, [p], desc="edited"))
    until(lambda: len(rows(env, i0, "n.bit")) == 2)
    assert env.policy(pol["policy_id"])["version"] == pol["version"] + 1
    m0, c0 = env.mark(), counters()
    (env.bits / "n.bit").unlink()
    until(lambda: env.policy(pol["policy_id"])["deleted_at"] is not None)
    dels = [e for e in env.entries(m0) if e["action"] == "policy.delete"]
    assert len(dels) == 1 and dels[0]["detail"]["reason"] == "file removed"
    assert dels[0]["actor"] == "system"
    assert delta(c0).get("policy_deleted") == 1.0


def test_a_file_moved_in_and_an_upload_folder_file(env: Env, watching: Watcher) -> None:
    i0 = env.last_import()
    outside = env.bits.parent / "m.bit"
    outside.write_bytes(doc(f"Moved {tag()}", [plug()]))
    os.rename(outside, env.bits / "m.bit")  # IN_MOVED_TO
    until(lambda: rows(env, i0, "m.bit"))
    data = doc(f"Foreign {tag()}", [plug()])
    (env.bits / "uploaded" / "foreign.bit").write_bytes(data)
    until(lambda: rows(env, i0, "uploaded/foreign.bit"))
    up = env.bits / "uploaded"
    until(lambda: not (up / "foreign.bit").exists())
    names = sorted(p.name for p in up.iterdir())
    assert len(names) == 1 and names[0].startswith("policy-")
    assert (up / names[0]).read_bytes() == data  # case (c) relocated


# REQ-164 (3) -----------------------------------------------------------------------


def test_a_chunked_write_over_2_s_is_imported_once_and_complete(
    env: Env, watching: Watcher
) -> None:
    ps = [plug() for _ in range(10)]
    data = doc(f"Chunks {tag()}", ps)
    i0 = env.last_import()
    step = -(-len(data) // 10)
    with open(env.bits / "c.bit", "wb") as f:
        for k in range(10):
            f.write(data[k * step : (k + 1) * step])
            f.flush()
            time.sleep(0.2)  # a slow writer (the behaviour under test)
    until(lambda: rows(env, i0, "c.bit"))
    settle(env, i0)
    (row,) = rows(env, i0, "c.bit")
    assert (row["outcome"], row["file_sha256"]) == ("success", sha(data))
    assert row["plugins_added"] == 10


# REQ-164 (4) and #102 (c) ----------------------------------------------------------


def test_an_upload_adds_no_row_of_its_own(env: Env, watching: Watcher) -> None:
    i0 = env.last_import()
    data = doc(f"Up {tag()}", [plug()])
    out = uploads.upload(env.db, env.clock, env.bits, data, b"u.bit", ADMIN)
    assert out.outcome == "success"
    v2 = doc(env.policy(out.policy_id or 0)["policy_name"], [plug()], desc="v2")
    uploads.upload(env.db, env.clock, env.bits, v2, b"u.bit", ADMIN)  # replace
    settle(env, i0)
    assert [
        r["mode"] for r in rows(env, i0) if not r["file_name"].startswith("zz-")
    ] == [
        "manual",
        "manual",
    ]  # only the two upload rows: no watcher row for the temp or the rename


def test_an_api_delete_and_a_finish_rename_add_nothing(
    env: Env, watching: Watcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    i0, m0 = env.last_import(), env.mark()
    out = uploads.upload(
        env.db, env.clock, env.bits, doc(f"D {tag()}", [plug()]), b"d", ADMIN
    )
    pid = out.policy_id or 0
    # finish rename (hook #2): a committed temp left by a failed rename
    v2 = doc(env.policy(pid)["policy_name"], [plug()], desc="v2")

    def broken(src: Any, dst: Any) -> None:
        raise OSError("rename failed")

    with monkeypatch.context() as mp:
        mp.setattr(os, "replace", broken)
        with pytest.raises(OSError):
            uploads.upload(env.db, env.clock, env.bits, v2, b"d", ADMIN)
    with env.db.session() as s, catalog_lock(s):
        assert uploads.finish_interrupted(s, env.bits).renamed == 1
    delete_policy(env.db, pid, actor="user:31", clock=env.clock, bits_dir=env.bits)
    settle(env, i0)
    assert [
        r["mode"] for r in rows(env, i0) if not r["file_name"].startswith("zz-")
    ] == [
        "manual",
        "manual",
    ]
    deletes = [e for e in env.entries(m0) if e["action"] == "policy.delete"]
    assert len(deletes) == 1  # only the API delete


def test_an_admin_edit_right_after_our_rename_is_still_imported(
    env: Env, watching: Watcher
) -> None:
    out = uploads.upload(
        env.db, env.clock, env.bits, doc(f"E {tag()}", [plug()]), b"e", ADMIN
    )
    pid = out.policy_id or 0
    own = env.bits / "uploaded" / f"policy-{pid}.bit"
    i0 = env.last_import()
    edited = doc(env.policy(pid)["policy_name"], [plug()], desc="admin edit")
    own.write_bytes(edited)  # another hash, within 60 s
    until(lambda: rows(env, i0, own.relative_to(env.bits).as_posix()))
    assert env.policy(pid)["source_sha256"] == sha(edited)


def test_own_changes_rules() -> None:
    clock = [100.0]
    own = OwnChanges(ttl=60.0, now=lambda: clock[0])
    calls: list[int] = []

    def current() -> str:
        calls.append(1)
        return "a" * 64

    assert not own.drop_write("uploaded/p.bit", current) and calls == []  # lazy
    own.wrote("uploaded/p.bit", "a" * 64)
    assert own.drop_write("uploaded/p.bit", current)
    assert not own.drop_write("uploaded/p.bit", current)  # used up once
    own.wrote("uploaded/p.bit", "b" * 64)
    assert not own.drop_write("uploaded/p.bit", current)  # another hash
    own.removed("uploaded/q.bit")
    own.removed("uploaded/q.bit")
    assert own.drop_removal("uploaded/q.bit") and own.drop_removal("uploaded/q.bit")
    assert not own.drop_removal("uploaded/q.bit")
    own.removed("uploaded/r.bit")
    clock[0] += 61
    assert not own.drop_removal("uploaded/r.bit")  # expired after 60 s


# CHK-M7-237: names and kinds that do nothing (REQ-164 (2), #102 (b)) ----------------


def test_ignored_names_and_kinds(
    env: Env, watching: Watcher, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    junk = doc(f"Junk {tag()}", [plug()])
    i0 = env.last_import()
    (env.bits / "n.txt").write_bytes(junk)
    (env.bits / ".n.bit").write_bytes(junk)
    (env.bits / "sub").mkdir()
    (env.bits / "sub" / "n.bit").write_bytes(junk)
    (env.bits / "uploaded" / ".tmp-1-x").write_bytes(junk)
    outside = env.bits.parent / "target.bit"
    outside.write_bytes(junk)
    (env.bits / "l.bit").symlink_to(outside)
    MKFIFO(env.bits / "f.bit")
    fd = REAL_OPEN(
        os.fsencode(env.bits) + b"/\xff.bit", os.O_WRONLY | os.O_CREAT, 0o600
    )
    os.write(fd, junk)
    os.close(fd)
    settle(env, i0)
    assert [r for r in rows(env, i0) if not r["file_name"].startswith("zz-")] == []
    assert "folder file skipped: its name cannot be stored" in caplog.text
    assert live(env, junk.decode().split("<PolicyName>")[1].split("<")[0]) is None


# r1: `mv a.bit c.bit` in one batch is a move ------------------------------------------


def test_mv_in_the_server_folder_keeps_the_policy(env: Env, watching: Watcher) -> None:
    name = f"Mv {tag()}"
    i0 = env.last_import()
    (env.bits / "a.bit").write_bytes(doc(name, [plug()]))
    until(lambda: rows(env, i0, "a.bit"))
    pol = live(env, name)
    assert pol is not None
    pid = pol["policy_id"]
    with owner(env.server) as c:
        _, jobs = cr.scan_with_jobs(c, pid, cr.agent(c), ["queued"])
        sched = cr.schedule(c, pid)
    m0, c0 = env.mark(), counters()
    os.rename(env.bits / "a.bit", env.bits / "c.bit")  # MOVED_FROM + MOVED_TO
    until(lambda: env.policy(pid)["source_file"] == "c.bit")
    settle(env, i0)
    assert env.policy(pid)["deleted_at"] is None
    actions = [e["action"] for e in env.entries(m0)]
    assert "policy.delete" not in actions and actions.count("policy.move") == 1
    assert "policy_deleted" not in delta(c0)
    with owner(env.server) as c:
        st = c.execute("SELECT state::text FROM scan_job WHERE job_id = %s",
                       (jobs["queued"],)).fetchone()  # fmt: skip
        en = c.execute("SELECT enabled FROM scan_schedule WHERE schedule_id = %s",
                       (sched,)).fetchone()  # fmt: skip
    assert st == ("queued",) and en == (True,)  # nothing cancelled or disabled


def test_delete_then_rewrite_keeps_the_policy(env: Env, watching: Watcher) -> None:
    name, p = f"Back {tag()}", plug()
    i0 = env.last_import()
    (env.bits / "b.bit").write_bytes(doc(name, [p]))
    until(lambda: rows(env, i0, "b.bit"))
    pol = live(env, name)
    assert pol is not None
    m0, c0 = env.mark(), counters()
    (env.bits / "b.bit").unlink()
    (env.bits / "b.bit").write_bytes(doc(name, [p], desc="rewritten"))
    until(lambda: env.policy(pol["policy_id"])["policy_description"] == "rewritten")
    settle(env, i0)
    assert env.policy(pol["policy_id"])["deleted_at"] is None
    assert "policy_deleted" not in delta(c0)
    assert "policy.delete" not in [e["action"] for e in env.entries(m0)]


# #102 (a): a replaced folder triggers a full reconcile and a re-watch -----------------


def test_a_recreated_upload_folder_is_watched_again(
    env: Env, watching: Watcher
) -> None:
    i0 = env.last_import()
    (env.bits / "uploaded").rmdir()
    (env.bits / "uploaded").mkdir()
    time.sleep(0.3)  # let the IN_CREATE batch be handled (re-watch)
    data = doc(f"Again {tag()}", [plug()])
    (env.bits / "uploaded" / "again.bit").write_bytes(data)
    until(lambda: rows(env, i0, "uploaded/again.bit"))


# A failed event: one line, then a reconcile after RETRY -------------------------------


def test_a_failed_event_is_logged_and_reconciled(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(wmod, "RETRY", 0.2)
    real = folders.import_path
    calls: list[str] = []

    def once(*a: Any, **k: Any) -> Any:
        calls.append(a[3])
        if len(calls) == 1:
            raise OSError("database down")
        return real(*a, **k)

    monkeypatch.setattr(folders, "import_path", once)
    w = Watcher(env.db, env.clock, env.bits)
    assert w.open()
    i0 = env.last_import()
    with Running(w):
        (env.bits / "r.bit").write_bytes(doc(f"Retry {tag()}", [plug()]))
        until(lambda: rows(env, i0, "r.bit"))
    assert "folder event failed: OSError" in caplog.text
    assert "database down" not in caplog.text


# Each file under the catalog lock -----------------------------------------------------


def test_an_event_waits_for_the_catalog_lock(env: Env, watching: Watcher) -> None:
    i0 = env.last_import()
    with app(env.server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        (env.bits / "lk.bit").write_bytes(doc(f"Lock {tag()}", [plug()]))
        time.sleep(1.0)
        assert rows(env, i0, "lk.bit") == []  # blocked behind the lock
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    until(lambda: rows(env, i0, "lk.bit"))


# CHK-M7-238: REQ-164 (5) without inotify ----------------------------------------------


def test_without_inotify_one_line_and_run_returns(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(inotify, "available", lambda: False)
    w = Watcher(env.db, env.clock, env.bits)
    assert w.open() is False
    t = threading.Thread(target=lambda: w.run(threading.Event()))
    t.start()
    t.join(5)
    assert not t.is_alive()  # returns at once
    lines = [r for r in caplog.records if "inotify is not available" in r.getMessage()]
    assert len(lines) == 2  # one per open attempt (open, and run's own)


def watcher_waiting_for_the_lock(e: Env) -> bool:
    with app(e.server) as c:
        row = c.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        ).fetchone()
    return row is not None and row[0] > 0


def test_a_created_upload_folder_is_watched(env: Env) -> None:
    # No uploaded/ when the watcher opens: only its IN_CREATE (IN_ISDIR) can
    # bring it into the watch (#102 (a), a replaced or new folder).
    (env.bits / "uploaded").rmdir()
    w = Watcher(env.db, env.clock, env.bits)
    assert w.open()
    i0 = env.last_import()
    with Running(w):
        (env.bits / "uploaded").mkdir()
        settle(env, i0)  # the folder event was handled before the sentinel
        (env.bits / "uploaded" / "new.bit").write_bytes(doc(f"New {tag()}", [plug()]))
        until(lambda: rows(env, i0, "uploaded/new.bit"))


def test_a_file_back_before_its_delete_is_handled_is_imported(
    env: Env, watching: Watcher
) -> None:
    name, p = f"Back2 {tag()}", plug()
    i0 = env.last_import()
    (env.bits / "k.bit").write_bytes(doc(name, [p]))
    until(lambda: rows(env, i0, "k.bit"))
    pol = live(env, name)
    assert pol is not None
    m0, c0 = env.mark(), counters()
    with app(env.server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        (env.bits / "k.bit").unlink()  # its batch blocks on the lock
        until(lambda: watcher_waiting_for_the_lock(env))
        (env.bits / "k.bit").write_bytes(doc(name, [p], desc="back"))
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    until(lambda: env.policy(pol["policy_id"])["policy_description"] == "back")
    settle(env, i0)
    assert env.policy(pol["policy_id"])["deleted_at"] is None
    assert "policy.delete" not in [e["action"] for e in env.entries(m0)]
    assert "policy_deleted" not in delta(c0)


def test_a_start_up_finish_rename_alone_adds_no_row(
    env: Env, watching: Watcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = uploads.upload(
        env.db, env.clock, env.bits, doc(f"Fin {tag()}", [plug()]), b"f", ADMIN
    )
    v2 = doc(env.policy(out.policy_id or 0)["policy_name"], [plug()], desc="v2")

    def broken(src: Any, dst: Any) -> None:
        raise OSError("rename failed")

    with monkeypatch.context() as mp:
        mp.setattr(os, "replace", broken)
        with pytest.raises(OSError):
            uploads.upload(env.db, env.clock, env.bits, v2, b"f", ADMIN)
    # A restart: the record the failed rename left (made just before it) is
    # gone, so only the finish's own record (hook #2) can drop its event.
    OWN_CHANGES._writes.clear()
    i0 = env.last_import()
    with env.db.session() as s, catalog_lock(s):
        assert uploads.finish_interrupted(s, env.bits).renamed == 1  # hook #2
    settle(env, i0)
    assert [r for r in rows(env, i0) if not r["file_name"].startswith("zz-")] == []


# The three race plants made deterministic (lead, 2026-10-28) ------------------------


def test_an_overflow_triggers_a_rewatch_and_a_full_reconcile(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(folders, "reconcile", lambda s, c, bits: calls.append(bits))
    w = Watcher(env.db, env.clock, env.bits)
    assert w.open()
    try:
        before = dict(w._prefix)
        assert w._handle([inotify.Event(-1, inotify.IN_Q_OVERFLOW, "")], False) is False
        assert calls == [env.bits]  # one full reconcile
        assert sorted(w._prefix.values()) == sorted(before.values())  # re-watched
    finally:
        assert w._ino is not None
        w._ino.close()


@pytest.mark.parametrize("order", ["record_then_rename", "rename_then_record"])
def test_our_own_rename_is_recognised_whatever_the_writer_order(
    env: Env, watching: Watcher, order: str
) -> None:
    # A writer stub holds the catalog lock across its rename into place. In
    # "rename_then_record" it renames, waits until the watcher is blocked on
    # the lock (pg_locks), and only then records. The watcher checks the record
    # after taking the lock, so either order is recognised: no row.
    out = uploads.upload(
        env.db, env.clock, env.bits, doc(f"Own {tag()}", [plug()]), b"o", ADMIN
    )
    rel = f"uploaded/policy-{out.policy_id}.bit"
    final = env.bits / rel
    data = final.read_bytes()
    settle(env, env.last_import())  # the upload's own events are done
    tmp = env.bits / "uploaded" / f".tmp-{out.policy_id}-{sha(data)}"
    tmp.write_bytes(data)  # the same bytes: an unrecognised event would be a row
    i0 = env.last_import()
    with env.db.session() as s, catalog_lock(s):
        if order == "record_then_rename":
            OWN_CHANGES.wrote(rel, sha(data))
        os.replace(tmp, final)
        until(lambda: watcher_waiting_for_the_lock(env))
        if order == "rename_then_record":
            OWN_CHANGES.wrote(rel, sha(data))
    settle(env, i0)
    assert [r for r in rows(env, i0) if not r["file_name"].startswith("zz-")] == []
