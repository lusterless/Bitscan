"""TP-M7-18 (TASK-158): the catalog start-up sequence and the integrity check
on PostgreSQL with temporary bits folders.

CHK-M7-230 (tests/m7/test-plan.md) and mutation rows CHK-M7-355 (no alert on
a corrupted catalog) and CHK-M7-368 (integrity check before the reconcile),
plus the TASK-158 row's Crash-window extra tests. Expected values come from
the spec and the approved rulings, not from the code:

- TS §4.1 L526 (the catalog lock), L528 (at start-up, before anything else,
  finish interrupted uploads, then reconcile both folders); TS §4.2 L540
  (tasks still ``running`` at start are marked ``failed``), L542 (the
  start-up integrity check alerts if catalog and files differ); TS §8.4
  L1291 (an alert is an audit entry with ``detail.alert = true`` and is
  counted in ``bitscan_alerts_total{kind}``).
- REQ-165 (1)-(4) and (6); #27 (the check runs after the reconcile); #98 (g)
  (a failed task's result is ``{"error": "<fixed text>"}``); #102 (d) (retry
  every 10 s while the database is unreachable); #103 (the checks, one
  ``catalog_integrity_failed`` alert listing up to 100 differences, none on a
  clean catalog; it never repairs).
- decisions.md from "Crash window ruling" to the end: a deleted policy's
  ``uploaded/policy-<id>.bit`` is a leftover (removed, nothing imported, no
  row, one difference "leftover of an interrupted delete"); stray and
  renamed uploads are skipped and listed by the check; Folder guard (an
  unreadable folder is listed, nothing is read through it, its policies are
  kept, and the wording never says "missing"); W6 rulings and residuals.

Owner: tester-m7-158. The reconcile and the check work on the whole catalog,
so the autouse ``clean`` fixture soft-deletes, as owner, every policy that is
still live. Code under test runs as ``bitscan_app``; results are read as
owner.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase, DatabaseUnavailable
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer import delete as dl
from bitscan_manager.services.importer import folders, integrity, startup, uploads
from bitscan_manager.services.importer.alerts import Difference
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.pipeline import Actor, FileInput, ImportOutcome

from .catalog_rows import T1, owner, tag
from .conftest import PgServer, own_migrated_server
from .pipeline_rows import (
    FixedClock,
    P,
    audits_since,
    bit,
    counter_delta,
    imports_since,
    policy_by_name,
    policy_row,
    sha,
    snap,
)

pytestmark = pytest.mark.pg

ADMIN = Actor("user:7", 7)
STEPS = ["finish_uploads", "fail_running_tasks", "reconcile", "integrity_check"]
LOGGERS = (
    "bitscan_manager.services.importer.startup",
    "bitscan_manager.services.importer.integrity",
)
KIND = "catalog_integrity_failed"
# The #103 check texts as the rulings and #103 name them. The leftover text is
# fixed by the user's Crash window ruling; the others are this task's fixed
# texts, asserted through the module's constants so a changed text is caught
# by the wording tests below.
LEFTOVER = "leftover of an interrupted delete"


# ----------------------------------------------------------------------------
# fixtures and helpers
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("startup")) as s:
        yield s


@pytest.fixture(scope="module")
def db(server: PgServer) -> Iterator[AppDatabase]:
    d = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=3
    )
    d.open()
    try:
        yield d
    finally:
        d.close()


@pytest.fixture(autouse=True)
def clean(request: pytest.FixtureRequest) -> None:
    """No live policy and no running task at the start of a PG test."""
    if "server" not in request.fixturenames:
        return
    srv: PgServer = request.getfixturevalue("server")
    with owner(srv) as c:
        c.execute(
            "UPDATE policy SET deleted_at = now(),"
            " source_file = 'deleted/' || policy_id WHERE deleted_at IS NULL"
        )
        c.execute("UPDATE task SET state = 'succeeded' WHERE state = 'running'")


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    folder = tmp_path / "bits"
    (folder / "uploaded").mkdir(parents=True)
    return folder


def put(bits: Path, rel: str, data: bytes) -> Path:
    path = bits / rel
    path.write_bytes(data)
    return path


def run(db: AppDatabase, bits: Path) -> startup.StartupResult:
    return startup.run_once(db, FixedClock(), bits)


def upload(db: AppDatabase, bits: Path, data: bytes) -> int:
    with db.session() as s, catalog_lock(s):
        out: ImportOutcome = uploads.import_upload(
            s, FixedClock(), bits, data, "client.bit", actor=ADMIN
        )
    assert out.outcome == "success", out
    assert out.policy_id is not None
    return int(out.policy_id)


def reconcile(db: AppDatabase, bits: Path) -> None:
    with db.session() as s, catalog_lock(s):
        folders.reconcile(s, FixedClock(), bits)


def server_policy(
    server: PgServer, db: AppDatabase, bits: Path, rel: str, data: bytes
) -> int:
    """A server-folder policy imported by an earlier start-up."""
    put(bits, rel, data)
    reconcile(db, bits)
    return int(policy_of_file(server, rel)["policy_id"])


def policy_of_file(server: PgServer, rel: str) -> dict[str, Any]:
    with owner(server) as c:
        row = c.execute(
            "SELECT policy_id FROM policy WHERE source_file = %s"
            " AND deleted_at IS NULL",
            (rel,),
        ).fetchone()
    assert row is not None, rel
    return policy_row(server, int(row[0]))


def alerts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e["action"] == "catalog.integrity_check"]


def diffs(entry: dict[str, Any]) -> list[tuple[str, str]]:
    return [(d["subject"], d["check"]) for d in entry["detail"]["differences"]]


def one_alert(server: PgServer, s: Any) -> dict[str, Any]:
    """Exactly one integrity entry since `s`, a proper alert, counted once."""
    got = alerts(audits_since(server, s))
    assert len(got) == 1, got
    e = got[0]
    assert e["actor"] == "system"
    assert e["detail"]["alert"] is True
    assert e["detail"]["alert_kind"] == KIND
    assert counter_delta(s).get(f"alert:{KIND}") == 1
    return e


def no_alert(server: PgServer, s: Any) -> None:
    assert alerts(audits_since(server, s)) == []
    assert f"alert:{KIND}" not in counter_delta(s)


def lock_is_held_elsewhere(server: PgServer) -> bool:
    with owner(server) as c:
        row = c.execute("SELECT pg_try_advisory_lock(hashtext('catalog'))").fetchone()
        assert row is not None
        if row[0]:
            c.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        return not bool(row[0])


def add_task(server: PgServer, state: str, result: str | None = None) -> UUID:
    with owner(server) as c:
        row = c.execute(
            "INSERT INTO task (kind, state, result, finished_at) VALUES"
            " ('rebuild', %s, %s::jsonb,"
            " CASE WHEN %s = 'running' THEN NULL ELSE now() END) RETURNING task_id",
            (state, result, state),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def task_row(server: PgServer, task_id: UUID) -> tuple[Any, ...]:
    with owner(server) as c:
        row = c.execute(
            "SELECT state, result, finished_at, started_at, requested_by, xmin::text"
            " FROM task WHERE task_id = %s",
            (task_id,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def records(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == name]


def steps(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(r.args[0]) if isinstance(r.args, tuple) else ""
        for r in records(caplog, LOGGERS[0])
        if r.msg == "catalog start-up step: %s"
    ]


def read_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every file the check and the reconcile read."""
    reads: list[str] = []
    real = folders.read_input

    def spy(bits_dir: Path, rel: str) -> FileInput | None:
        reads.append(rel)
        return real(bits_dir, rel)

    monkeypatch.setattr(folders, "read_input", spy)
    monkeypatch.setattr(integrity, "read_input", spy)
    return reads


def empty_result(unreadable: tuple[str, ...] = ()) -> folders.ReconcileResult:
    return folders.ReconcileResult((), (), (), (), (), unreadable)


def check(db: AppDatabase, bits: Path, r: folders.ReconcileResult) -> list[Difference]:
    with db.session() as s, catalog_lock(s):
        return integrity.differences(s, bits, r)


# ----------------------------------------------------------------------------
# CHK-M7-230: step order, the step log and the lock
# ----------------------------------------------------------------------------


def test_steps_run_in_order_under_one_lock_and_a_clean_catalog_raises_nothing(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_policy(server, db, bits, "a.bit", bit(f"Clean {tag()}")[0])
    upload(db, bits, bit(f"Up {tag()}")[0])
    calls: list[tuple[str, bool]] = []

    def wrap(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def inner(*a: Any, **k: Any) -> Any:
            calls.append((name, lock_is_held_elsewhere(server)))
            return fn(*a, **k)

        return inner

    for name, attr in zip(
        STEPS,
        [
            "finish_interrupted_uploads",
            "fail_running_tasks",
            "reconcile",
            "check_and_alert",
        ],
        strict=True,
    ):
        monkeypatch.setattr(startup, attr, wrap(name, getattr(startup, attr)))
    caplog.set_level(logging.INFO)
    s = snap(server)
    res = run(db, bits)
    assert calls == [(n, True) for n in STEPS]  # in order, each under the lock
    assert steps(caplog) == [*STEPS, "done"]
    assert not lock_is_held_elsewhere(server)  # released afterwards
    assert res.differences == ()
    no_alert(server, s)
    assert audits_since(server, s) == []
    assert [r["outcome"] for r in imports_since(server, s)] == ["skipped", "skipped"]


def test_finish_runs_before_the_reconcile_so_a_committed_upload_survives(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """A crash after commit and before the rename: the policy is live, its
    file is only the temp. If the reconcile ran first it would delete it."""
    data = bit(f"Committed {tag()}")[0]
    pid = upload(db, bits, data)
    final = bits / f"uploaded/policy-{pid}.bit"
    final.rename(bits / f"uploaded/.tmp-{pid}-{sha(data)}")
    s = snap(server)
    res = run(db, bits)
    assert final.read_bytes() == data
    assert policy_row(server, pid)["deleted_at"] is None
    assert res.uploads.renamed == 1 and res.reconciled.deleted == ()
    no_alert(server, s)


def test_the_check_runs_after_the_reconcile(
    server: PgServer, db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#27, CHK-M7-368 and REQ-165 (3): a file added and a file removed while
    the manager was down are imported and deleted, and the check that follows
    sees a consistent catalog."""
    gone = server_policy(server, db, bits, "gone.bit", bit(f"Gone {tag()}")[0])
    (bits / "gone.bit").unlink()
    name = f"New {tag()}"
    put(bits, "new.bit", bit(name)[0])
    caplog.set_level(logging.INFO)
    s = snap(server)
    res = run(db, bits)
    assert [
        (r["file_name"], r["outcome"], r["mode"]) for r in imports_since(server, s)
    ] == [("new.bit", "success", "auto")]
    new = policy_by_name(server, name)
    assert new is not None and new["source_file"] == "new.bit"
    assert policy_row(server, gone)["deleted_at"] == T1
    assert res.differences == ()
    no_alert(server, s)


# ----------------------------------------------------------------------------
# REQ-165 (1): interrupted uploads
# ----------------------------------------------------------------------------


def test_req165_1_the_four_temp_file_cases(
    server: PgServer, db: AppDatabase, bits: Path, tmp_path: Path
) -> None:
    data = bit(f"Committed {tag()}")[0]
    pid = upload(db, bits, data)
    up = bits / "uploaded"
    (up / f"policy-{pid}.bit").rename(up / f".tmp-{pid}-{sha(data)}")
    other = bit(f"Uncommitted {tag()}")[0]
    (up / f".tmp-{pid}-{sha(other)}").write_bytes(other)  # never committed
    (up / ".tmp-x").write_bytes(b"x")
    victim = tmp_path / "victim.bit"
    victim.write_bytes(data)
    (up / f".tmp-{pid}-{sha(data)}0").symlink_to(victim)
    s = snap(server)
    res = run(db, bits)
    assert sorted(os.listdir(up)) == [f"policy-{pid}.bit"]
    assert (up / f"policy-{pid}.bit").read_bytes() == data
    assert victim.read_bytes() == data  # not followed
    assert (res.uploads.renamed, res.uploads.deleted) == (1, 3)
    assert policy_row(server, pid)["deleted_at"] is None
    no_alert(server, s)


@pytest.mark.parametrize("how", ["missing", "file", "symlink"])
def test_an_unreadable_uploaded_folder_does_not_stop_start_up(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """Folder guard: nothing is read or deleted through it, its policies are
    kept, the server folder is reconciled, and one alert lists the folder as
    "could not be read safely", never "missing"."""
    data = bit(f"Kept {tag()}")[0]
    pid = upload(db, bits, data)
    before = policy_row(server, pid)
    real = tmp_path / "real-uploaded"
    (bits / "uploaded").rename(real)
    (real / f".tmp-{pid}-{sha(data)}").write_bytes(data)
    if how == "file":
        (bits / "uploaded").write_bytes(b"not a folder")
    elif how == "symlink":
        (bits / "uploaded").symlink_to(real)
    snapshot = {p.name: p.read_bytes() for p in real.iterdir()}
    name = f"Server {tag()}"
    put(bits, "s.bit", bit(name)[0])
    reads = read_spy(monkeypatch)
    caplog.set_level(logging.INFO)
    s = snap(server)
    res = run(db, bits)
    assert steps(caplog) == [*STEPS, "done"]
    assert (res.uploads.renamed, res.uploads.deleted) == (0, 0)
    assert policy_by_name(server, name) is not None  # server folder reconciled
    assert policy_row(server, pid) == before  # kept, untouched
    assert {p.name: p.read_bytes() for p in real.iterdir()} == snapshot
    assert [r for r in reads if r.startswith("uploaded/")] == []
    e = one_alert(server, s)
    assert diffs(e) == [("uploaded/", integrity.FOLDER_CHECK)]
    assert "missing" not in integrity.FOLDER_CHECK.casefold()
    assert "could not be read safely" in integrity.FOLDER_CHECK
    assert e["detail"]["difference_count"] == 1


@pytest.mark.parametrize("how", ["missing", "symlink"])
def test_an_unreadable_bits_folder_lists_both_folders_and_reads_nothing(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    spid = server_policy(server, db, bits, "s.bit", bit(f"S {tag()}")[0])
    upid = upload(db, bits, bit(f"U {tag()}")[0])
    frozen = {p: policy_row(server, p) for p in (spid, upid)}
    real = tmp_path / "real-bits"
    bits.rename(real)
    if how == "symlink":
        bits.symlink_to(real)
    reads = read_spy(monkeypatch)
    s = snap(server)
    res = run(db, bits)
    assert reads == []
    assert {p: policy_row(server, p) for p in (spid, upid)} == frozen
    assert res.reconciled.deleted == ()
    e = one_alert(server, s)
    assert diffs(e) == [
        ("./", integrity.FOLDER_CHECK),
        ("uploaded/", integrity.FOLDER_CHECK),
    ]


# ----------------------------------------------------------------------------
# REQ-165 (2): running tasks
# ----------------------------------------------------------------------------


def test_req165_2_running_tasks_are_failed_with_the_fixed_text(
    server: PgServer, db: AppDatabase, bits: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r1 = add_task(server, "running")
    r2 = add_task(server, "running", '{"files": []}')
    ok = add_task(server, "succeeded", '{"files": []}')
    bad = add_task(server, "failed", '{"error": "earlier"}')
    untouched = {t: task_row(server, t) for t in (ok, bad)}
    caplog.set_level(logging.INFO)
    res = run(db, bits)
    assert res.failed_tasks == 2
    for t in (r1, r2):
        state, result, finished, *_ = task_row(server, t)
        assert state == "failed"
        assert finished == T1
        assert result == startup.INTERRUPTED
    # #98 (g): {"error": "<fixed text>"}, the same text for every task.
    assert set(startup.INTERRUPTED) == {"error"}
    assert (
        isinstance(startup.INTERRUPTED["error"], str) and startup.INTERRUPTED["error"]
    )
    assert {t: task_row(server, t) for t in (ok, bad)} == untouched
    # A second start-up has nothing left to fail.
    assert run(db, bits).failed_tasks == 0
    assert task_row(server, r1)[1] == startup.INTERRUPTED


# ----------------------------------------------------------------------------
# REQ-165 (4) and #103: each difference kind, one alert
# ----------------------------------------------------------------------------


def test_req165_4_a_removed_policy_plugin_row_alerts_and_is_not_repaired(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    pid = server_policy(server, db, bits, "a.bit", bit(f"A {tag()}", [P(), P()])[0])
    with owner(server) as c:
        c.execute(
            "DELETE FROM policy_plugin WHERE policy_id = %s AND sort_order ="
            " (SELECT max(sort_order) FROM policy_plugin WHERE policy_id = %s)",
            (pid, pid),
        )
    s = snap(server)
    res = run(db, bits)
    e = one_alert(server, s)
    assert diffs(e) == [(f"policy:{pid}", integrity.COUNT_CHECK)]
    assert e["detail"]["difference_count"] == 1
    assert e["target"] is None
    assert res.differences == (Difference(f"policy:{pid}", integrity.COUNT_CHECK),)
    with owner(server) as c:  # never repaired by the check
        n = c.execute(
            "SELECT count(*) FROM policy_plugin WHERE policy_id = %s", (pid,)
        ).fetchone()
    assert n is not None and n[0] == 1


def test_req165_4_a_changed_source_sha256_alerts(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """REQ-165 (4) names this corruption explicitly."""
    pid = server_policy(server, db, bits, "b.bit", bit(f"B {tag()}")[0])
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s",
            ("0" * 64, pid),
        )
    s = snap(server)
    run(db, bits)
    e = one_alert(server, s)
    assert (f"policy:{pid}", integrity.HASH_CHECK) in diffs(e)


@pytest.mark.parametrize("how", ["retired", "foreign"])
def test_a_listed_plugin_not_active_or_foreign(
    server: PgServer, db: AppDatabase, bits: Path, how: str
) -> None:
    pid = server_policy(server, db, bits, "a.bit", bit(f"A {tag()}")[0])
    other = server_policy(server, db, bits, "o.bit", bit(f"O {tag()}")[0])
    with owner(server) as c:
        if how == "foreign":
            c.execute(
                "UPDATE plugin SET owner_policy_id = %s WHERE plugin_uuid IN"
                " (SELECT plugin_uuid FROM policy_plugin WHERE policy_id = %s)",
                (other, pid),
            )
        else:
            c.execute(
                "UPDATE plugin SET state = 'retired' WHERE plugin_uuid IN"
                " (SELECT plugin_uuid FROM policy_plugin WHERE policy_id = %s)",
                (pid,),
            )
    s = snap(server)
    run(db, bits)
    e = one_alert(server, s)
    assert diffs(e) == [(f"policy:{pid}", integrity.PLUGIN_CHECK)]


def test_a_rejected_edit_of_a_live_file_gives_the_hash_check_only(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """The file now differs from source_sha256 (its re-import is rejected),
    and has another Plugin count: only the hash check, not the count."""
    name = f"A {tag()}"
    pid = server_policy(server, db, bits, "a.bit", bit(name, [P(), P()])[0])
    put(bits, "a.bit", bit(name, [P(execute="rm -rf /tmp/x")])[0])  # BIT102
    s = snap(server)
    run(db, bits)
    assert [r["outcome"] for r in imports_since(server, s)] == ["rejected"]
    e = one_alert(server, s)
    assert diffs(e) == [(f"policy:{pid}", integrity.HASH_CHECK)]


def test_parse_and_count_checks_only_when_the_hash_matches(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """Owner points source_sha256 at the bytes now on disk: garbage gives the
    parse check; a valid file with another Plugin count gives the count
    check (no reconcile import: the hash equals source_sha256)."""
    g = server_policy(server, db, bits, "g.bit", bit(f"G {tag()}")[0])
    garbage = b"<Policy><not closed"
    put(bits, "g.bit", garbage)
    name = f"C {tag()}"
    c3 = server_policy(server, db, bits, "c.bit", bit(name, [P()])[0])
    three = bit(name, [P(), P(), P()])[0]
    put(bits, "c.bit", three)
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s",
            (sha(garbage), g),
        )
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s",
            (sha(three), c3),
        )
    s = snap(server)
    run(db, bits)
    # c.bit is skipped (same hash). g.bit has no readable name, so the
    # auto skip cannot match it: it is retried and rejected (TS §4.1 L532),
    # and the policy keeps its rows.
    assert [(r["file_name"], r["outcome"]) for r in imports_since(server, s)] == [
        ("c.bit", "skipped"),
        ("g.bit", "rejected"),
    ]
    e = one_alert(server, s)
    assert sorted(diffs(e)) == sorted(
        [
            (f"policy:{g}", integrity.PARSE_CHECK),
            (f"policy:{c3}", integrity.COUNT_CHECK),
        ]
    )


def test_an_oversize_file_whose_hash_matches_gives_the_parse_check(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    pid = server_policy(server, db, bits, "big.bit", bit(f"Big {tag()}")[0])
    big = b"<Policy>" + b" " * MAX_BIT_BYTES
    put(bits, "big.bit", big)
    with owner(server) as c:
        c.execute(
            "UPDATE policy SET source_sha256 = %s WHERE policy_id = %s",
            (sha(big), pid),
        )
    assert check(db, bits, empty_result()) == [
        Difference(f"policy:{pid}", integrity.PARSE_CHECK)
    ]


def test_a_missing_file_at_source_file(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """A file that disappears after the reconcile (the reconcile itself
    deletes such a policy): the check alone reports it."""
    pid = server_policy(server, db, bits, "a.bit", bit(f"A {tag()}")[0])
    (bits / "a.bit").unlink()
    assert check(db, bits, empty_result()) == [
        Difference(f"policy:{pid}", integrity.MISSING_CHECK)
    ]


def test_stray_renamed_and_leftover_uploads_each_listed_once(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    stray = "uploaded/policy-999999999.bit"
    put(bits, stray, bit(f"Stray {tag()}")[0])
    name = f"R {tag()}"
    rpid = upload(db, bits, bit(name)[0])
    rrel = f"uploaded/policy-{rpid}.bit"
    put(bits, rrel, bit(f"Edited {tag()}")[0])
    dpid = upload(db, bits, bit(f"D {tag()}")[0])
    drel = f"uploaded/policy-{dpid}.bit"
    kept = (bits / drel).read_bytes()
    dl.delete_policy(db, dpid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    put(bits, drel, kept)
    s = snap(server)
    run(db, bits)
    e = one_alert(server, s)
    got = diffs(e)
    assert got == [
        (drel, LEFTOVER),
        (stray, integrity.STRAY_CHECK),
        (rrel, integrity.RENAMED_CHECK),
        (f"policy:{rpid}", integrity.HASH_CHECK),  # impl Known limit: true too
    ]
    assert len({d[0] for d in got}) == len(got)  # no subject twice
    assert e["detail"]["difference_count"] == 4


def test_every_kind_in_one_alert(
    server: PgServer, db: AppDatabase, bits: Path, tmp_path: Path
) -> None:
    """One start-up, one alert, every kind the folders allow at once."""
    a = server_policy(server, db, bits, "a.bit", bit(f"A {tag()}", [P(), P()])[0])
    with owner(server) as c:
        c.execute(
            "DELETE FROM policy_plugin WHERE policy_id = %s AND sort_order ="
            " (SELECT max(sort_order) FROM policy_plugin WHERE policy_id = %s)",
            (a, a),
        )
    b_name = f"B {tag()}"
    b = server_policy(server, db, bits, "b.bit", bit(b_name)[0])
    put(bits, "b.bit", bit(b_name, [P(execute="rm -rf /tmp/x")])[0])
    c_ = server_policy(server, db, bits, "c.bit", bit(f"C {tag()}")[0])
    with owner(server) as c:
        c.execute(
            "UPDATE plugin SET state = 'retired' WHERE plugin_uuid IN"
            " (SELECT plugin_uuid FROM policy_plugin WHERE policy_id = %s)",
            (c_,),
        )
    stray = "uploaded/policy-999999998.bit"
    put(bits, stray, b"stray")
    dpid = upload(db, bits, bit(f"D {tag()}")[0])
    drel = f"uploaded/policy-{dpid}.bit"
    kept = (bits / drel).read_bytes()
    dl.delete_policy(db, dpid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    put(bits, drel, kept)
    s = snap(server)
    res = run(db, bits)
    e = one_alert(server, s)
    assert diffs(e) == [
        (drel, LEFTOVER),
        (stray, integrity.STRAY_CHECK),
        (f"policy:{a}", integrity.COUNT_CHECK),
        (f"policy:{b}", integrity.HASH_CHECK),
        (f"policy:{c_}", integrity.PLUGIN_CHECK),
    ]
    assert [(d.subject, d.check) for d in res.differences] == diffs(e)


def test_folder_side_untracked_file_without_a_rejected_row(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    """#103: a folder file that is no live source_file is fine only with a
    rejected row for its current hash."""
    put(bits, "bad.bit", b"<Policy>")
    reconcile(db, bits)  # writes the rejected row for this hash
    assert check(db, bits, empty_result()) == []
    put(bits, "bad.bit", b"<Policy> ")  # new hash, no row
    put(bits, "unknown.bit", bit(f"U {tag()}")[0])  # never imported
    assert check(db, bits, empty_result()) == [
        Difference("bad.bit", integrity.UNTRACKED_CHECK),
        Difference("unknown.bit", integrity.UNTRACKED_CHECK),
    ]


def test_the_alert_lists_100_differences_and_the_total(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    paths = [f"uploaded/policy-{900000000 + i}.bit" for i in range(150)]
    for p in paths:
        put(bits, p, b"stray")
    s = snap(server)
    res = run(db, bits)
    e = one_alert(server, s)
    assert e["detail"]["difference_count"] == 150
    assert len(res.differences) == 150
    listed = diffs(e)
    assert len(listed) == 100
    assert listed == [(p, integrity.STRAY_CHECK) for p in sorted(paths)][:100]


# ----------------------------------------------------------------------------
# Crash window extra tests (TASK-158 row)
# ----------------------------------------------------------------------------


def test_crash_window_a_committed_delete_with_its_file_left(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = upload(db, bits, bit(f"Del {tag()}")[0])
    rel = f"uploaded/policy-{pid}.bit"
    # The manager stops after the delete commits, before the file is removed.
    monkeypatch.setattr(dl, "remove_after_commit", lambda *a, **k: None)
    dl.delete_policy(db, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
    monkeypatch.undo()
    assert (bits / rel).exists()
    deleted = policy_row(server, pid)
    assert deleted["deleted_at"] is not None
    s = snap(server)
    run(db, bits)
    assert not (bits / rel).exists()
    assert policy_row(server, pid) == deleted  # still deleted, not revived
    assert imports_since(server, s) == []
    e = one_alert(server, s)
    assert diffs(e) == [(rel, LEFTOVER)]
    # The next start-up has nothing to report.
    s2 = snap(server)
    assert run(db, bits).differences == ()
    no_alert(server, s2)


def test_crash_window_a_restart_with_only_live_uploads_raises_nothing(
    server: PgServer, db: AppDatabase, bits: Path
) -> None:
    pids = [upload(db, bits, bit(f"Live {tag()}", [P()] * 1)[0]) for _ in range(3)]
    tree = {p.name: p.read_bytes() for p in (bits / "uploaded").iterdir()}
    for _ in range(2):
        s = snap(server)
        res = run(db, bits)
        assert res.differences == ()
        no_alert(server, s)
        assert [r["outcome"] for r in imports_since(server, s)] == ["skipped"] * 3
    assert {p.name: p.read_bytes() for p in (bits / "uploaded").iterdir()} == tree
    assert all(policy_row(server, p)["deleted_at"] is None for p in pids)


# ----------------------------------------------------------------------------
# Logs: no paths, content or tokens
# ----------------------------------------------------------------------------


def test_logs_and_alert_carry_no_content_or_tokens(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "bsa_" + "Q" * 43
    name = f"Canary {canary} {tag()}"
    pid = server_policy(server, db, bits, f"{canary}.bit", bit(name, [P(), P()])[0])
    put(bits, f"uploaded/policy-99999997{canary[-1]}.bit", canary.encode())
    with owner(server) as c:
        c.execute(
            "DELETE FROM policy_plugin WHERE policy_id = %s AND sort_order ="
            " (SELECT max(sort_order) FROM policy_plugin WHERE policy_id = %s)",
            (pid, pid),
        )
    put(bits, f"x-{canary}.bit", f"<Policy>{canary}".encode())
    caplog.set_level(logging.DEBUG)
    s = snap(server)
    run(db, bits)
    e = one_alert(server, s)
    text = str(e["detail"])
    assert f"<Policy>{canary}" not in text and name not in text
    for rec_ in caplog.records:
        if rec_.name not in LOGGERS:
            continue
        blob = rec_.getMessage() + repr(rec_.__dict__)
        assert canary not in blob
        assert str(bits) not in blob and ".bit" not in blob


# ----------------------------------------------------------------------------
# REQ-165 (6): run_until_done
# ----------------------------------------------------------------------------


class FakeStop:
    """A stop Event that never sleeps: records each wait."""

    def __init__(self, set_after: int | None = None, pre_set: bool = False) -> None:
        self.waits: list[float | None] = []
        self._set = pre_set
        self.set_after = set_after

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        if self.set_after is not None and len(self.waits) >= self.set_after:
            self._set = True
        return self._set


def _scripted(
    monkeypatch: pytest.MonkeyPatch, script: list[BaseException | None]
) -> list[int]:
    calls: list[int] = []
    result = startup.StartupResult(uploads.FinishedUploads(0, 0), 0, empty_result(), ())

    def fake(db: Any, clock: Any, bits_dir: Path) -> startup.StartupResult:
        calls.append(1)
        step = script[len(calls) - 1]
        if step is not None:
            raise step
        return result

    monkeypatch.setattr(startup, "run_once", fake)
    return calls


def test_run_until_done_retries_every_10_s_on_unavailable_and_operational(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = _scripted(
        monkeypatch,
        [
            DatabaseUnavailable("secret-dsn-canary"),
            psycopg.OperationalError("secret-dsn-canary"),
            None,
        ],
    )
    stop = FakeStop()
    caplog.set_level(logging.DEBUG)
    out = startup.run_until_done(
        None,  # type: ignore[arg-type]
        FixedClock(),
        Path("/nonexistent"),
        stop,  # type: ignore[arg-type]
    )
    assert out is not None and len(calls) == 3
    assert stop.waits == [10.0, 10.0]
    assert startup.RETRY_S == 10.0
    lines = records(caplog, LOGGERS[0])
    assert all("secret-dsn-canary" not in r.getMessage() for r in lines)
    assert [r.levelno for r in lines] == [logging.WARNING, logging.WARNING]


def test_run_until_done_stops_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _scripted(monkeypatch, [DatabaseUnavailable("x")] * 5)
    pre = FakeStop(pre_set=True)
    assert (
        startup.run_until_done(None, FixedClock(), Path("/x"), pre)  # type: ignore[arg-type]
        is None
    )
    assert calls == [] and pre.waits == []
    during = FakeStop(set_after=1)
    assert (
        startup.run_until_done(None, FixedClock(), Path("/x"), during)  # type: ignore[arg-type]
        is None
    )
    assert len(calls) == 1 and during.waits == [10.0]


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("boom"),
        OSError("disk"),
        ValueError("v"),
        psycopg.errors.UniqueViolation("u"),
        psycopg.ProgrammingError("p"),
    ],
    ids=["runtime", "oserror", "value", "integrity", "programming"],
)
def test_run_until_done_lets_other_errors_through(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    calls = _scripted(monkeypatch, [exc])
    stop = FakeStop()
    with pytest.raises(type(exc)):
        startup.run_until_done(None, FixedClock(), Path("/x"), stop)  # type: ignore[arg-type]
    assert len(calls) == 1 and stop.waits == []


def test_run_until_done_against_an_unreachable_database_then_a_real_one(
    server: PgServer,
    db: AppDatabase,
    bits: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real pool at a closed port: DatabaseUnavailable is retried, a real
    stop ends the 10 s wait at once. Then the real database: one pass."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    down = AppDatabase(
        SecretStr(f"postgresql://bitscan_app@127.0.0.1:{port}/x"),
        max_size=1,
        connect_timeout_s=1,
    )
    down.open()
    stop = threading.Event()
    try:
        timer = threading.Timer(1.5, stop.set)
        timer.start()
        t0 = time.monotonic()
        assert startup.run_until_done(down, FixedClock(), bits, stop) is None
        elapsed = time.monotonic() - t0
        timer.join()
    finally:
        down.close()
    assert elapsed < 6.0  # not the 10 s retry wait

    name = f"Up {tag()}"
    put(bits, "u.bit", bit(name)[0])
    real = startup.run_once
    seen: list[int] = []

    def once_down(d: Any, clock: Any, b: Path) -> startup.StartupResult:
        seen.append(1)
        if len(seen) == 1:
            raise DatabaseUnavailable("down")
        return real(d, clock, b)

    monkeypatch.setattr(startup, "run_once", once_down)
    fake = FakeStop()
    out = startup.run_until_done(db, FixedClock(), bits, fake)  # type: ignore[arg-type]
    assert out is not None and len(seen) == 2 and fake.waits == [10.0]
    assert policy_by_name(server, name) is not None


# ----------------------------------------------------------------------------
# The lock (TASK-154 review carry (a))
# ----------------------------------------------------------------------------


def test_a_concurrent_delete_waits_for_the_whole_sequence(
    server: PgServer, db: AppDatabase, bits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = upload(db, bits, bit(f"Del {tag()}")[0])
    other = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=1, connect_timeout_s=3
    )
    other.open()
    done = threading.Event()
    alive_during: list[bool] = []

    def deleter() -> None:
        dl.delete_policy(other, pid, actor="user:7", clock=FixedClock(), bits_dir=bits)
        done.set()

    t = threading.Thread(target=deleter)
    real = integrity.check_and_alert

    def at_check(*a: Any, **k: Any) -> list[Difference]:
        t.start()
        alive_during.append(not done.wait(1.0))
        return real(*a, **k)

    monkeypatch.setattr(startup, "check_and_alert", at_check)
    try:
        res = run(db, bits)
        t.join(10)
    finally:
        other.close()
    assert alive_during == [True]  # blocked while start-up held the lock
    assert done.is_set()
    assert res.differences == ()
    assert policy_row(server, pid)["deleted_at"] is not None
