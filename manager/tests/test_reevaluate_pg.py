"""TP-M8-12: re-evaluation service on PostgreSQL (TASK-185 r1; REQ-200,
REQ-202 (2), REQ-204 (2)).

As ``bitscan_app`` through ``AppDatabase``. Expected behaviour: TS §4.5 L601
(re-evaluate against the policy's current version; rows added, originals never
change; plugins no longer in the version get no row), §2.2 L114, §5.2
L1005-L1006, #12 (intake details stay ERROR), #118 (a)-(g) (dropped plugins,
deleted refused, disabled allowed, one `scan.reevaluate` audit entry in the
same transaction, no alert), and the lead's rulings of 2026-10-29: a NULL
stdout fails closed (`cannot evaluate`); a stored ERROR whose detail is not a
known value fails closed; order: intake detail, unknown ERROR detail, NULL
stdout, classify(). CHK-M8-190 to -201, -222.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import reeval, results
from bitscan_manager.services.audit.verify import verify_chain
from bitscan_manager.services.evaluator.reevaluate import (
    PolicyDeleted,
    ReevalResult,
    ScanNotFound,
    reevaluate_scan,
)

from . import evaluator_pg_fixtures as fx
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

USER = 4242


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("reeval")) as s:
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


@dataclass
class Six:
    policy: fx.Policy
    scan: UUID
    job: fx.Job


def build_six(server: PgServer, *, status: str = "enabled") -> Six:
    """REQ-200 (1): PASS, FAIL, `stdout not numeric`, `oversize`,
    `runner_unavailable` and a plugin since dropped; then an import that
    changes one ExpectedResult (P2) and one Operator (P3) and drops P6."""
    with fx.owner(server) as conn:
        pol = fx.make_policy(
            conn,
            [("equals", "x"), ("equals", "x"), ("eq", "5"), ("empty", ""),
             ("equals", "x"), ("equals", "x")],
            status=status,
        )  # fmt: skip
        p = pol.plugins
        scan = fx.make_scan(conn, pol)
        job = fx.make_job(conn, scan, fx.make_agent(conn), pol, p, state="completed")
        fx.add_result(conn, job, pol, p[0], code=0, stdout="x")
        fx.add_result(conn, job, pol, p[1], code=1, stdout="y")
        fx.add_result(conn, job, pol, p[2], code=2, detail="stdout not numeric",
                      stdout="abc")  # fmt: skip
        fx.add_result(conn, job, pol, p[3], code=2, detail="oversize", stdout="",
                      stderr="")  # fmt: skip
        fx.add_result(conn, job, pol, p[4], code=2, detail="runner_unavailable",
                      stdout="", exit_code=None)  # fmt: skip
        fx.add_result(conn, job, pol, p[5], code=0, stdout="x")
        fx.import_change(
            conn,
            pol,
            expected={p[1].plugin_uuid: "y"},
            operator={p[2].plugin_uuid: "not_empty"},
            drop=[p[5].plugin_uuid],
        )
    return Six(pol, scan, job)


def _rows(server: PgServer, job: fx.Job) -> dict[UUID, list[tuple[Any, ...]]]:
    with fx.owner(server) as conn:
        out: dict[UUID, list[tuple[Any, ...]]] = {}
        for r in fx.reevals_of(conn, [job.job_id]):
            out.setdefault(r[2], []).append(r)
        return out


def _audit(server: PgServer, scan: UUID) -> list[tuple[Any, ...]]:
    with fx.owner(server) as conn:
        return [
            r for r in fx.audit_rows(conn, "scan.reevaluate") if r[3] == f"scan:{scan}"
        ]


# CHK-M8-190: REQ-200 (1)
def test_six_results_after_an_import(server: PgServer, db: AppDatabase) -> None:
    s = build_six(server)
    p = s.policy.plugins
    out = reevaluate_scan(db, s.scan, user_id=USER)
    assert out == ReevalResult(
        scan_id=s.scan,
        policy_id=s.policy.policy_id,
        scan_policy_version=1,
        policy_version=2,
        rows_added=5,
        not_in_version=1,
    )
    rows = _rows(server, s.job)
    got = {u: [(r[3], r[4], r[5], r[6]) for r in v] for u, v in rows.items()}
    assert got == {
        p[0].plugin_uuid: [(2, 0, None, USER)],
        p[1].plugin_uuid: [(2, 0, None, USER)],  # new ExpectedResult: PASS
        p[2].plugin_uuid: [(2, 0, None, USER)],  # new Operator: PASS
        p[3].plugin_uuid: [(2, 2, "oversize", USER)],  # intake kept, not `empty` PASS
        p[4].plugin_uuid: [(2, 2, "runner_unavailable", USER)],
    }
    assert p[5].plugin_uuid not in rows  # dropped: no row (#118 (b))


# CHK-M8-191, -198: REQ-200 (2), (9)
def test_results_never_change_and_no_update_or_delete(
    server: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = build_six(server)
    with fx.owner(server) as conn:
        fx.add_reeval(conn, s.job.job_id, s.policy.plugins[0].plugin_uuid, code=1)
        before = fx.result_checksums(conn)
        before_reeval = fx.checksum(conn, "scan_result_reeval")
        before_jobs = (fx.checksum(conn, "scan"), fx.checksum(conn, "scan_job"))
        old = fx.reevals_of(conn, [s.job.job_id])
    spy = fx.StatementSpy()
    spy.install(monkeypatch)
    reevaluate_scan(db, s.scan, user_id=USER)
    monkeypatch.undo()
    words = " ".join(spy.statements).upper().replace("(", " ").replace(",", " ").split()
    for bad in ("UPDATE", "DELETE", "TRUNCATE", "MERGE"):
        assert bad not in words, bad
    with fx.owner(server) as conn:
        assert fx.result_checksums(conn) == before
        assert (fx.checksum(conn, "scan"), fx.checksum(conn, "scan_job")) == before_jobs
        assert fx.checksum(conn, "scan_result_reeval") != before_reeval
        now = fx.reevals_of(conn, [s.job.job_id])
    assert now[: len(old)] == old  # earlier rows unchanged
    assert len(now) == len(old) + 5


# CHK-M8-192: REQ-200 (3)
def test_second_run_adds_rows_and_wins(server: PgServer, db: AppDatabase) -> None:
    s = build_six(server)
    p = s.policy.plugins
    reevaluate_scan(db, s.scan, user_id=USER)
    with fx.owner(server) as conn:
        fx.import_change(conn, s.policy, expected={p[0].plugin_uuid: "z"})
    second = reevaluate_scan(db, s.scan, user_id=USER + 1)
    assert second.rows_added == 5 and second.policy_version == 3
    rows = _rows(server, s.job)
    assert sum(len(v) for v in rows.values()) == 10
    with fx.app(server) as conn:
        eff = {r.plugin_uuid: r for r in results.effective_results(conn, s.scan)}
    first_ids = {v[0][0] for v in rows.values()}
    for u, r in eff.items():
        if u == p[5].plugin_uuid:
            assert r.reeval_id is None  # never re-evaluated: original kept
            continue
        assert r.reeval_id == rows[u][1][0]
        assert r.reeval_id not in first_ids
        assert r.reeval_policy_version == 3
        assert r.reevaluated_by == USER + 1
    assert (eff[p[0].plugin_uuid].code, eff[p[0].plugin_uuid].original_code) == (1, 0)


# CHK-M8-193: REQ-200 (4)
def test_audit_entry_and_chain(server: PgServer, db: AppDatabase) -> None:
    s = build_six(server)
    with fx.owner(server) as conn:
        before = conn.execute("SELECT count(*) FROM audit_log").fetchone()
    reevaluate_scan(db, s.scan, user_id=USER)
    entries = _audit(server, s.scan)
    assert len(entries) == 1
    _, actor, action, target, detail = entries[0]
    assert (actor, action, target) == (
        f"user:{USER}",
        "scan.reevaluate",
        f"scan:{s.scan}",
    )
    assert detail == {
        "policy_id": s.policy.policy_id,
        "scan_policy_version": 1,
        "policy_version": 2,
        "rows_added": 5,
        "not_in_version": 1,
    }
    with fx.owner(server) as conn:
        after = conn.execute("SELECT count(*) FROM audit_log").fetchone()
        alerts = conn.execute(
            "SELECT count(*) FROM audit_log WHERE detail ? 'alert'"
            " AND audit_id > (SELECT max(audit_id) - 1 FROM audit_log)"
        ).fetchone()
    assert before is not None and after is not None
    assert after[0] == before[0] + 1  # one entry, no alert entry
    assert alerts == (0,)
    with fx.app(server) as conn:
        result = verify_chain(conn)
    assert result.ok, result


# CHK-M8-194, -200: REQ-200 (5) and wake
def test_deleted_policy_and_unknown_scan_write_nothing(
    server: PgServer, db: AppDatabase
) -> None:
    s = build_six(server)
    with fx.owner(server) as conn:
        fx.soft_delete(conn, s.policy)
        audit_before = conn.execute("SELECT count(*) FROM audit_log").fetchone()
    woken: list[int] = []
    with pytest.raises(PolicyDeleted):
        reevaluate_scan(db, s.scan, user_id=USER, wake=lambda: woken.append(1))
    unknown = uuid4()
    with pytest.raises(ScanNotFound) as info:
        reevaluate_scan(db, unknown, user_id=USER, wake=lambda: woken.append(1))
    assert str(unknown) not in str(info.value)
    assert woken == []
    assert _rows(server, s.job) == {}
    with fx.owner(server) as conn:
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone() == audit_before


def test_wake_runs_once_after_commit(server: PgServer, db: AppDatabase) -> None:
    s = build_six(server)
    seen: list[int] = []

    def wake() -> None:
        # committed already: another session sees the entry
        seen.append(len(_audit(server, s.scan)))

    reevaluate_scan(db, s.scan, user_id=USER, wake=wake)
    assert seen == [1]


# CHK-M8-195: REQ-200 (6) a fault after the first chunk's insert
def test_fault_after_first_chunk_leaves_nothing(
    server: PgServer, db: AppDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = build_six(server)
    real_stored, real_insert = reeval.stored_results, reeval.insert_reevals
    calls: list[int] = []

    def small_chunks(conn: Any, scan_id: UUID, *, chunk: int = 1000) -> Any:
        return real_stored(conn, scan_id, chunk=2)

    def insert(conn: Any, rows: Any, **kw: Any) -> int:
        calls.append(len(rows))
        if len(calls) == 2:
            raise RuntimeError("injected fault")
        return real_insert(conn, rows, **kw)

    monkeypatch.setattr(reeval, "stored_results", small_chunks)
    monkeypatch.setattr(reeval, "insert_reevals", insert)
    woken: list[int] = []
    with pytest.raises(RuntimeError, match="injected fault"):
        reevaluate_scan(db, s.scan, user_id=USER, wake=lambda: woken.append(1))
    assert calls[0] > 0  # the first chunk really inserted before the fault
    assert _rows(server, s.job) == {}
    assert _audit(server, s.scan) == []
    assert woken == []


# CHK-M8-196: REQ-200 (7)
def test_scan_without_results(server: PgServer, db: AppDatabase) -> None:
    with fx.owner(server) as conn:
        pol = fx.make_policy(conn, [("equals", "x")])
        scan = fx.make_scan(conn, pol)
        fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins, state="queued")
    out = reevaluate_scan(db, scan, user_id=USER)
    assert (out.rows_added, out.not_in_version) == (0, 0)
    entries = _audit(server, scan)
    assert len(entries) == 1 and entries[0][4]["rows_added"] == 0


# CHK-M8-197: REQ-200 (8)
def test_disabled_policy_is_reevaluated(server: PgServer, db: AppDatabase) -> None:
    s = build_six(server, status="disabled")
    assert reevaluate_scan(db, s.scan, user_id=USER).rows_added == 5


# CHK-M8-199, -201 and the r1 rulings
@pytest.mark.parametrize(
    ("stored", "want"),
    [
        # intake details keep their detail even where `empty` would PASS
        ({"code": 2, "detail": "oversize", "stdout": ""}, (2, "oversize")),
        ({"code": 2, "detail": "spool_overflow", "stdout": ""}, (2, "spool_overflow")),
        (
            {"code": 2, "detail": "runner_unavailable", "stdout": ""},
            (2, "runner_unavailable"),
        ),  # fmt: skip
        # NULL stdout with an intake detail: the intake detail wins (ruling)
        ({"code": 2, "detail": "oversize", "stdout": None}, (2, "oversize")),
        (
            {"code": 2, "detail": "spool_overflow", "stdout": None},
            (2, "spool_overflow"),
        ),
        # an unrecognised stored ERROR detail fails closed
        ({"code": 2, "detail": None, "stdout": ""}, (2, "cannot evaluate")),
        ({"code": 2, "detail": " Oversize ", "stdout": ""}, (2, "cannot evaluate")),
        ({"code": 2, "detail": "OVERSIZE", "stdout": ""}, (2, "cannot evaluate")),
        ({"code": 2, "detail": "oversize ", "stdout": ""}, (2, "cannot evaluate")),
        ({"code": 2, "detail": "something else", "stdout": ""}, (2, "cannot evaluate")),
        # NULL stdout without an intake detail fails closed, never PASS
        ({"code": 0, "detail": None, "stdout": None}, (2, "cannot evaluate")),
        ({"code": 1, "detail": None, "stdout": None}, (2, "cannot evaluate")),
        # a known evaluation detail is re-classified on the stored values
        (
            {"code": 2, "detail": "timed out", "stdout": "", "timed_out": True},
            (2, "timed out"),
        ),  # fmt: skip
        (
            {"code": 2, "detail": "stdout truncated", "stdout": "", "truncated": True},
            (2, "stdout truncated"),
        ),  # fmt: skip
        (
            {"code": 2, "detail": "not found", "stdout": "", "exit_code": 127},
            (2, "not found"),
        ),  # fmt: skip
        ({"code": 2, "detail": "cannot evaluate", "stdout": ""}, (0, None)),
        ({"code": 2, "detail": "stdout not numeric", "stdout": ""}, (0, None)),
        ({"code": 1, "detail": None, "stdout": "x"}, (1, None)),
        ({"code": 1, "detail": None, "stdout": ""}, (0, None)),
    ],
)
def test_stored_verdict_rules_under_empty(
    server: PgServer, db: AppDatabase, stored: dict[str, Any], want: tuple[Any, Any]
) -> None:
    with fx.owner(server) as conn:
        pol = fx.make_policy(conn, [("empty", "")])
        scan = fx.make_scan(conn, pol)
        job = fx.make_job(conn, scan, fx.make_agent(conn), pol, pol.plugins)
        fx.add_result(
            conn,
            job,
            pol,
            pol.plugins[0],
            code=stored["code"],
            detail=stored["detail"],
            stdout=stored["stdout"],
            exit_code=stored.get("exit_code", 0),
            timed_out=stored.get("timed_out", False),
            truncated=stored.get("truncated", False),
        )
    out = reevaluate_scan(db, scan, user_id=USER)  # never raises
    assert out.rows_added == 1
    rows = _rows(server, job)[pol.plugins[0].plugin_uuid]
    assert [(r[4], r[5]) for r in rows] == [want]


# CHK-M8-222: REQ-202 (2), the canary over the service path
def test_canary_leaves_no_trace(
    server: PgServer, db: AppDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    c = fx.CANARY
    with fx.owner(server) as conn:
        pol = fx.make_policy(conn, [("eq", c), ("regex", "[" + c), ("contains", c),
                                    ("eq", "1")])  # fmt: skip
        p = pol.plugins
        scan = fx.make_scan(conn, pol)
        job = fx.make_job(conn, scan, fx.make_agent(conn), pol, p)
        for plugin in p:
            fx.add_result(conn, job, pol, plugin, code=1, stdout=c, stderr=c)
    with caplog.at_level(logging.DEBUG):
        reevaluate_scan(db, scan, user_id=USER)
        with fx.app(server) as conn:
            eff = results.effective_results(conn, scan)
        with fx.owner(server) as conn:
            fx.soft_delete(conn, pol)
        with pytest.raises(PolicyDeleted) as info:
            reevaluate_scan(db, scan, user_id=USER)
    assert c not in str(info.value) and c not in repr(info.value)
    for record in caplog.records:
        assert c not in record.getMessage()
        assert c not in repr(record.args)
    # eq <canary> and regex [<canary>: cannot evaluate; contains: PASS;
    # eq 1 against the canary stdout: stdout not numeric
    details = sorted((r.code, r.detail or "") for r in eff)
    assert details == sorted(
        [
            (2, "cannot evaluate"),
            (2, "cannot evaluate"),
            (0, ""),
            (2, "stdout not numeric"),
        ]
    )
    for _, _, _, _, detail in _audit(server, scan):
        assert c not in repr(detail)
    rows = _rows(server, job)
    assert all(c not in repr(r) for v in rows.values() for r in v)


def test_reevaluate_module_has_no_logging() -> None:
    from bitscan_manager.services.evaluator import reevaluate

    src = Path(reevaluate.__file__).read_text(encoding="utf-8")
    assert "logging" not in src and "print(" not in src


# CHK-M8-353 support: the grant refuses an UPDATE the service might try
def test_app_update_of_a_result_is_refused(server: PgServer) -> None:
    with fx.app(server) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE scan_result SET eval_code = 0 WHERE false")
