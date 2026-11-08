"""TP-M11-09: the results service on PostgreSQL, as bitscan_app through
AppDatabase, with the canaries (TASK-241 TEST, tester-m11c; REQ-267 to
REQ-269; CHK-M11-165 to -170).

Expected values come from the spec and the approved answers, not the code:
#144 (a) (the 22 item keys and their sources: the result's snapshots, or the
original job's eval_spec and payload when not run), (b) (stdout and stderr
only for operator and admin, by the caller's current role whatever the token
kind; for a viewer the keys are absent, not null), (c) (one item per plugin
of each host's original payload, in payload order; Not run = no result in
the unit), (d) (status PASS, FAIL, ERROR, NOT_RUN on the effective result;
agent_id; AND), (e) (ordered by agent_id then position; keyset [agent_id,
position]); #119 (effective = highest reeval_id); #146 (the CSV header and
order, stdout and stderr columns for operator and admin only, null as an
empty cell, true/false, RFC 3339 UTC times, every cell through M5's
escape_cell, UTF-8 without BOM, CRLF, at most 100,000 rows, refused before
any CSV text); TS §6.3 L1144 (formula triggers =, +, -, @, tab, CR, or
whitespace followed by one of these get a leading '); REQ-268 (the canary
reaches no viewer answer and no log record).

The world is ``m11_pg_fixtures.results_world`` (its docstring is the
description the oracle below is written from).
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import result_reads
from bitscan_manager.services.jobs import results_read as rr
from bitscan_manager.services.jobs import results_view, scan_views
from bitscan_manager.services.jobs.results_view import parse_query

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

KEYS = (
    "agent_id",
    "hostname",
    "job_id",
    "retry",
    "plugin_uuid",
    "plugin_name",
    "result",
    "eval_detail",
    "original_result",
    "original_eval_detail",
    "reeval_policy_version",
    "reevaluated_by",
    "reevaluated_at",
    "operator",
    "expected",
    "execute",
    "exit_code",
    "timed_out",
    "truncated",
    "started_at",
    "finished_at",
    "received_at",
)
CSV_COLUMNS = (
    "hostname",
    "agent_id",
    "plugin_uuid",
    "plugin_name",
    "result",
    "eval_detail",
    "original_result",
    "original_eval_detail",
    "reevaluated_at",
    "reeval_policy_version",
    "exit_code",
    "timed_out",
    "truncated",
    "started_at",
    "finished_at",
    "job_id",
    "retry",
)
TIME_COLUMNS = frozenset({"reevaluated_at", "started_at", "finished_at"})
ALL = parse_query(None, None)
ROLES_WITH = ("operator", "admin")
ROLES_WITHOUT = ("viewer", "auditor", "Admin", "")
ADMIN_ID = 7


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-results-read")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with m.app_database(server, max_size=4) as d:
        yield d


@pytest.fixture(scope="module")
def world(server: PgServer) -> m.ResultsWorld:
    with m.owner(server) as c:
        return m.results_world(c, admin_id=ADMIN_ID)


@pytest.fixture(scope="module")
def names(server: PgServer, world: m.ResultsWorld) -> dict[str, str]:
    with m.owner(server) as c:
        return {
            k: str(
                f9.one(
                    c, "SELECT hostname FROM agent WHERE agent_id = %s", (h.agent_id,)
                )
            )
            for k, h in world.hosts.items()
        }


# ----- the oracle (from the results_world description) ----------------------------


def expected_items(
    w: m.ResultsWorld, names: dict[str, str], *, with_output: bool
) -> list[dict[str, Any]]:
    p, pol, j = w.p, w.pol, w.jobs
    at = f9.T0

    def stored(
        host: str,
        job: m.JobRow,
        pd: m.PluginDef,
        code: int,
        *,
        detail: str | None = None,
        stdout: str = "ok",
        stderr: str = "",
        exit_code: int | None = 0,
        truncated: bool = False,
        reeval: tuple[int, str, int, datetime] | None = None,
    ) -> dict[str, Any]:
        when = job.created_at + timedelta(minutes=5)
        verdict = {0: "PASS", 1: "FAIL", 2: "ERROR"}
        out: dict[str, Any] = {
            "agent_id": w.hosts[host].agent_id,
            "hostname": names[host],
            "job_id": job.job_id,
            "retry": job.retry_of is not None,
            "plugin_uuid": pd.plugin_uuid,
            "plugin_name": pol.display(pd),
            "result": verdict[code if reeval is None else reeval[0]],
            "eval_detail": detail if reeval is None else reeval[1],
            "original_result": verdict[code],
            "original_eval_detail": detail,
            "reeval_policy_version": None if reeval is None else reeval[2],
            "reevaluated_by": None if reeval is None else ADMIN_ID,
            "reevaluated_at": None if reeval is None else reeval[3],
            "operator": pd.operator,
            "expected": pd.expected,
            "execute": pd.execute,
            "exit_code": exit_code,
            "timed_out": False,
            "truncated": truncated,
            "started_at": when - timedelta(seconds=2),
            "finished_at": when - timedelta(seconds=1),
            "received_at": when,
        }
        if with_output:
            out |= {"stdout": stdout, "stderr": stderr}
        return out

    def not_run(host: str, pd: m.PluginDef) -> dict[str, Any]:
        out: dict[str, Any] = dict.fromkeys(KEYS)
        out |= {
            "agent_id": w.hosts[host].agent_id,
            "hostname": names[host],
            "retry": False,
            "plugin_uuid": pd.plugin_uuid,
            "plugin_name": pol.display(pd),
            "operator": pd.operator,
            "expected": pd.expected,
            "execute": pd.execute,
        }
        if with_output:
            out |= {"stdout": None, "stderr": None}
        return out

    per_host = {
        "a": [
            stored("a", j["a"], p[0], 0, stdout=m.OUT, stderr=m.ERR),
            stored(
                "a",
                j["a"],
                p[1],
                1,
                stdout="no",
                reeval=(0, "high", 1, at + timedelta(hours=1)),
            ),
            stored(
                "a",
                j["a"],
                p[2],
                2,
                detail="runner_unavailable",
                stdout="",
                exit_code=None,
            ),
            stored("a", j["a_retry"], p[3], 1, stdout="retry-fail"),
            not_run("a", p[4]),
        ],
        "b": [not_run("b", pd) for pd in p],
        "c": [
            stored("c", j["c"], p[0], 0, stdout=m.C0_STDOUT),
            stored("c", j["c"], p[1], 0, detail=m.C1_DETAIL, stdout=m.C1_STDOUT),
            stored("c", j["c"], p[2], 1, stdout="c-fail", truncated=True),
            stored("c", j["c"], p[3], 0),
            stored("c", j["c"], p[4], 2, detail="oversize", stdout=""),
        ],
    }
    order = sorted(per_host, key=lambda k: w.hosts[k].agent_id.int)
    return [item for k in order for item in per_host[k]]


def matching(
    items: list[dict[str, Any]], status: str | None, agent: UUID | None
) -> list[dict[str, Any]]:
    want = None if status == "NOT_RUN" else status
    return [
        i
        for i in items
        if (status is None or i["result"] == want)
        and (agent is None or i["agent_id"] == agent)
    ]


def all_pages(
    db: AppDatabase, scan_id: UUID, query: Any, role: str, limit: int
) -> list[rr.ResultPage]:
    pages: list[rr.ResultPage] = []
    after: tuple[UUID, int] | None = None
    for _ in range(100):
        page = rr.results_page(db, scan_id, query, role, limit, after)
        pages.append(page)
        if page.next_after is None:
            return pages
        after = page.next_after
    raise AssertionError("paging did not end")


# ----- CHK-M11-165: who sees output -----------------------------------------------


def test_results_page_signature_takes_the_role_only() -> None:
    """The role argument alone decides; there is no token-kind parameter."""
    assert list(inspect.signature(rr.results_page).parameters) == [
        "db",
        "scan_id",
        "query",
        "role",
        "limit",
        "after",
    ]
    assert list(inspect.signature(rr.results_csv).parameters) == [
        "db",
        "scan_id",
        "query",
        "role",
    ]


@pytest.mark.parametrize("role", ROLES_WITHOUT)
def test_no_output_keys_or_canary_for_a_viewer_or_unknown_role(
    db: AppDatabase, world: m.ResultsWorld, role: str
) -> None:
    """Every page and every filter: exactly the 22 keys, no OUT or ERR byte;
    an unknown role fails closed."""
    texts: list[str] = []
    for status in (None, "PASS", "FAIL", "ERROR", "NOT_RUN"):
        for agent in (None, world.hosts["a"].agent_id):
            for page in all_pages(
                db, world.scan_id, parse_query(status, agent), role, 2
            ):
                assert page.with_output is False
                for item in page.items:
                    assert tuple(item) == KEYS, tuple(item)
                texts.append(json.dumps(page.items, default=str))
    assert m.hits(texts, m.OUTPUT_CANARIES) == []
    assert m.hits(texts, (m.EXEC, m.EXP)) == [m.EXEC, m.EXP]  # catalog text is allowed


@pytest.mark.parametrize("role", ROLES_WITH)
def test_operator_and_admin_get_output(
    db: AppDatabase, world: m.ResultsWorld, names: dict[str, str], role: str
) -> None:
    page = rr.results_page(db, world.scan_id, ALL, role, 500, None)
    assert page.with_output is True
    assert [tuple(i) for i in page.items] == [(*KEYS, "stdout", "stderr")] * 15
    assert page.items == expected_items(world, names, with_output=True)
    assert m.hits([json.dumps(page.items, default=str)], m.OUTPUT_CANARIES) == [
        m.ERR,
        m.OUT,
    ]


def test_viewer_statement_never_reads_stdout_or_stderr(
    db: AppDatabase, world: m.ResultsWorld
) -> None:
    """REQ-268: a viewer's page and CSV read no stdout or stderr column (the
    output never leaves the database); the operator's statement does."""
    seen: dict[str, list[str]] = {}
    for role in ("viewer", "operator"):
        spy = m.RoleSpy()
        with pytest.MonkeyPatch.context() as mp:
            spy.install(mp)
            rr.results_page(db, world.scan_id, ALL, role, 50, None)
            rr.results_csv(db, world.scan_id, ALL, role)
        seen[role] = spy.statements
    assert not [
        s for s in seen["viewer"] if "stdout" in s.lower() or "stderr" in s.lower()
    ]
    assert any("r.stdout" in s for s in seen["operator"])


# ----- CHK-M11-166: items, filters, paging ---------------------------------------


def test_items_equal_the_oracle_for_a_viewer(
    db: AppDatabase, world: m.ResultsWorld, names: dict[str, str]
) -> None:
    """REQ-267 (1), (6): one item per planned plugin, effective from the
    highest reeval_id, originals unchanged, Not run from eval_spec; the
    other scan's rows never appear."""
    page = rr.results_page(db, world.scan_id, ALL, "viewer", 500, None)
    assert page.items == expected_items(world, names, with_output=False)
    assert page.next_after is None
    assert "other-scan" not in json.dumps(page.items, default=str)


@pytest.mark.parametrize("status", [None, "PASS", "FAIL", "ERROR", "NOT_RUN"])
@pytest.mark.parametrize("host", [None, "a", "b", "c"])
def test_filters_alone_and_together(
    db: AppDatabase,
    world: m.ResultsWorld,
    names: dict[str, str],
    status: str | None,
    host: str | None,
) -> None:
    agent = None if host is None else world.hosts[host].agent_id
    want = matching(expected_items(world, names, with_output=True), status, agent)
    page = rr.results_page(
        db, world.scan_id, parse_query(status, agent), "admin", 500, None
    )
    assert page.items == want


def test_unknown_agent_filter_is_empty(db: AppDatabase, world: m.ResultsWorld) -> None:
    page = rr.results_page(
        db, world.scan_id, parse_query(None, uuid4()), "admin", 50, None
    )
    assert (page.items, page.next_after) == ([], None)


@pytest.mark.parametrize("limit", [1, 2, 4, 5, 7, 14, 15, 16])
def test_paging_visits_every_item_once(
    db: AppDatabase, world: m.ResultsWorld, names: dict[str, str], limit: int
) -> None:
    """limit + 1 read: next_after only when a further item exists (15 items:
    limit 5 gives three full pages and no cursor on the third; limit 15 one
    page without a cursor)."""
    pages = all_pages(db, world.scan_id, ALL, "viewer", limit)
    got = [i for p in pages for i in p.items]
    assert got == expected_items(world, names, with_output=False)
    assert [len(p.items) for p in pages[:-1]] == [limit] * (len(pages) - 1)
    assert len(pages) == max(1, -(-15 // limit))
    for p in pages[:-1]:
        last = p.items[-1]
        assert p.next_after is not None and p.next_after[0] == last["agent_id"]
    assert pages[-1].next_after is None


def test_paging_with_a_filter(
    db: AppDatabase, world: m.ResultsWorld, names: dict[str, str]
) -> None:
    q = parse_query("NOT_RUN", None)
    pages = all_pages(db, world.scan_id, q, "operator", 2)
    got = [i for p in pages for i in p.items]
    assert got == matching(
        expected_items(world, names, with_output=True), "NOT_RUN", None
    )
    assert len(got) == 6


# ----- CHK-M11-167: CSV -------------------------------------------------------------


def escaped(text: str) -> str:
    """TS §6.3 L1144, written from the spec: a cell starting with =, +, -,
    @, a tab or a CR, or whitespace followed by one of these, gets a '."""
    triggers = ("=", "+", "-", "@", "\t", "\r")
    stripped = text.lstrip(" \t\r\n")
    if text.startswith(triggers) or (
        stripped != text and stripped.startswith(triggers)
    ):
        return "'" + text
    return text


def parse_csv(text: str) -> list[list[str]]:
    assert not text.startswith("﻿")
    assert text.endswith("\r\n")
    return list(csv.reader(io.StringIO(text, newline="")))


def csv_record(item: dict[str, Any], header: list[str], actual: list[str]) -> list[str]:
    out: list[str] = []
    for col, got in zip(header, actual, strict=True):
        v = item[col]
        if col in TIME_COLUMNS and v is not None:
            assert got.endswith("Z") and datetime.fromisoformat(got) == v, (col, got)
            out.append(got)
        elif v is None:
            out.append("")
        elif isinstance(v, bool):
            out.append("true" if v else "false")
        else:
            out.append(escaped(str(v)))
    return out


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
@pytest.mark.parametrize("status", [None, "FAIL", "NOT_RUN"])
def test_csv_rows_equal_the_json_items(
    db: AppDatabase, world: m.ResultsWorld, role: str, status: str | None
) -> None:
    q = parse_query(status, None)
    items = rr.results_page(db, world.scan_id, q, role, 500, None).items
    rows = parse_csv(rr.results_csv(db, world.scan_id, q, role))
    header = list(CSV_COLUMNS) + (["stdout", "stderr"] if role != "viewer" else [])
    assert rows[0] == header
    assert len(rows) == len(items) + 1
    for item, actual in zip(items, rows[1:], strict=True):
        assert actual == csv_record(item, header, actual)


def test_csv_escapes_and_quotes_output(db: AppDatabase, world: m.ResultsWorld) -> None:
    text = rr.results_csv(db, world.scan_id, ALL, "operator")
    rows = parse_csv(text)
    by_stdout = {r[17]: r for r in rows[1:]}
    assert m.C0_STDOUT in by_stdout  # commas, quotes, LF and CRLF round-trip
    assert "'" + m.C1_STDOUT in by_stdout
    assert by_stdout["'" + m.C1_STDOUT][5] == "'" + m.C1_DETAIL
    assert m.OUT in text and m.ERR in text
    assert "other-scan" not in text


def test_viewer_csv_has_no_output_column_or_canary(
    db: AppDatabase, world: m.ResultsWorld
) -> None:
    text = rr.results_csv(db, world.scan_id, ALL, "viewer")
    assert parse_csv(text)[0] == list(CSV_COLUMNS)
    assert m.hits([text], m.OUTPUT_CANARIES) == []


# ----- CHK-M11-168: the 100,000-row cap --------------------------------------------


@pytest.fixture(scope="module")
def cap_scans(server: PgServer) -> dict[str, UUID]:
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        at_cap, _ = m.wide_scan(c, pol, [1000] * 100)
        over, _ = m.wide_scan(c, pol, [1000] * 100 + [5])
        one_over, _ = m.wide_scan(c, pol, [1000] * 100 + [1])
    return {"at": at_cap, "over": over, "one_over": one_over}


class Recorder:
    def __init__(self, real: Any) -> None:
        self.real = real
        self.calls = 0
        self.lengths: list[int] = []

    def __call__(self, *a: Any, **kw: Any) -> Any:
        self.calls += 1
        out = self.real(*a, **kw)
        if isinstance(out, list):
            self.lengths.append(len(out))
        return out


def test_100000_rows_export(
    db: AppDatabase, cap_scans: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    build = Recorder(results_view.csv_text)
    monkeypatch.setattr(results_view, "csv_text", build)
    rows = parse_csv(rr.results_csv(db, cap_scans["at"], ALL, "viewer"))
    assert len(rows) == 100_001  # header + 100,000
    assert build.calls == 1


@pytest.mark.parametrize("which", ["one_over", "over"])
def test_over_the_cap_refused_before_any_text(
    db: AppDatabase,
    cap_scans: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    which: str,
) -> None:
    """100,001 and 100,005 rows: TooManyRows, csv_text never called, and at
    most 100,001 rows read."""
    build = Recorder(results_view.csv_text)
    read = Recorder(result_reads.results_export)
    monkeypatch.setattr(results_view, "csv_text", build)
    monkeypatch.setattr(result_reads, "results_export", read)
    with pytest.raises(rr.TooManyRows) as exc:
        rr.results_csv(db, cap_scans[which], ALL, "operator")
    assert build.calls == 0
    assert read.lengths == [100_001]
    assert m.hits([str(exc.value), repr(exc.value)]) == []


# ----- CHK-M11-169: unknown scan; snapshot; select only ----------------------------


def test_unknown_scan_raises_scan_not_found(db: AppDatabase) -> None:
    assert rr.ScanNotFound is scan_views.ScanNotFound  # one 404 type
    with pytest.raises(rr.ScanNotFound):
        rr.results_page(db, uuid4(), ALL, "admin", 10, None)
    with pytest.raises(rr.ScanNotFound):
        rr.results_csv(db, uuid4(), ALL, "admin")


def test_scan_without_jobs_is_an_empty_answer(
    server: PgServer, db: AppDatabase
) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        sid = m.scan(c, pol, [m.host(c).agent_id])
    page = rr.results_page(db, sid, ALL, "admin", 10, None)
    assert (page.items, page.next_after) == ([], None)
    assert parse_csv(rr.results_csv(db, sid, ALL, "viewer")) == [list(CSV_COLUMNS)]


def test_each_call_is_one_read_only_snapshot(
    db: AppDatabase, world: m.ResultsWorld
) -> None:
    for call in (
        lambda: rr.results_page(db, world.scan_id, ALL, "viewer", 3, None),
        lambda: rr.results_csv(db, world.scan_id, ALL, "admin"),
    ):
        spy = m.RoleSpy()
        with pytest.MonkeyPatch.context() as mp:
            spy.install(mp)
            call()
        app = spy.by_role("bitscan_app")
        first = app[0].upper()
        assert first.startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"), (
            first
        )
        assert "READ ONLY" in first
        assert not [s for s in spy.statements if m.verb(s) in m.WRITE_VERBS]
        assert {m.verb(s) for s in spy.statements} <= {"SET", "SELECT", "WITH"}


# ----- CHK-M11-170: the canary in logs and exceptions ------------------------------


def test_no_canary_in_logs_or_exceptions(
    db: AppDatabase,
    world: m.ResultsWorld,
    cap_scans: dict[str, UUID],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("bitscan_manager.m11c_probe").debug("probe")
    returned: list[str] = []
    for role in ("viewer", "operator", "admin"):
        for status in (None, "PASS", "ERROR", "NOT_RUN"):
            q = parse_query(status, None)
            returned.append(
                json.dumps(
                    rr.results_page(db, world.scan_id, q, role, 3, None).items,
                    default=str,
                )
            )
            returned.append(rr.results_csv(db, world.scan_id, q, role))
    errors: list[str] = []
    for call in (
        lambda: rr.results_page(db, uuid4(), ALL, "admin", 3, None),
        lambda: rr.results_csv(db, cap_scans["one_over"], ALL, "admin"),
    ):
        try:
            call()
        except Exception as exc:  # the chain of every raised exception
            e: BaseException | None = exc
            while e is not None:
                errors += [str(e), repr(e)]
                e = e.__cause__ or e.__context__
    assert errors  # both raised
    records = [
        " ".join([r.getMessage(), repr(r.args), repr(vars(r))]) for r in caplog.records
    ]
    assert any("probe" in t for t in records)  # the capture works at DEBUG
    assert m.hits(records) == []
    assert m.hits(errors) == []
    assert [r.name for r in caplog.records if r.name.startswith("bitscan_manager")] == [
        "bitscan_manager.m11c_probe"
    ]
    assert m.hits(returned, m.OUTPUT_CANARIES) == [m.ERR, m.OUT]  # admin/operator only
