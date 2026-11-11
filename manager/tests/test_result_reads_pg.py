"""TASK-235 TEST: the result reads repository on PostgreSQL, as bitscan_app
(TP-M11-04; CHK-M11-118 to -131).

Expected values: REQ-267 (one item per planned plugin of each host's
original job payload, in payload order; the unit's stored result, else Not
run named from the original job's eval_spec; `result` effective, from the
highest reeval_id, and `original_result` the stored one; filters on the
effective code and agent_id; order agent_id then position; keyset
`[agent_id, position]`; another scan's rows never appear), #119 (latest =
highest reeval_id, whatever reevaluated_at says), #144 (a)-(e), TS §4.5 L603
(plugins no longer in the version keep their verdict), TS §4.4 L585 (Not
run), TS §6.2 L1123 (stdout and stderr only for operator and admin: the
viewer statement never reads them), #146 (e) (the CSV read: the whole set,
`CSV_MAX_ROWS + 1` rows at most), plan TASK-235 §3 (read-only repeatable-read
snapshot first; `exists`; PD-46 composition of M8's `_EFFECTIVE`;
`scan_result_reeval` read once per statement). Expected rows are built here
from the world description (the inputs the fixture wrote), never from the
repository.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterator, Sequence
from dataclasses import fields
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from bitscan_manager.repositories import result_reads as rr
from bitscan_manager.repositories import results as m8

from . import m11_pg_fixtures as m
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

# sha256 of manager/bitscan_manager/repositories/results.py at 6efe0fb
# (`git show 6efe0fb:manager/bitscan_manager/repositories/results.py | sha256sum`).
RESULTS_PY_6EFE0FB = "101e918293e108f2c9c7559d881e8fa4eafdaa7c2681057db24bf0c59c1ada61"
STATUSES: tuple[str | None, ...] = (None, "PASS", "FAIL", "ERROR", "NOT_RUN")
CODES = {"PASS": 0, "FAIL": 1, "ERROR": 2}

Row = dict[str, Any]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("result-reads")) as s:
        yield s


@pytest.fixture
def conn(server: PgServer) -> Iterator[m.Conn]:
    with m.app(server) as c:
        yield c


# ----- expected rows (from the world description) ------------------------------


def as_dict(r: rr.ResultRow) -> Row:
    return {f.name: getattr(r, f.name) for f in fields(r)} | {"retry": r.retry}


def hostnames(conn: m.Conn, agents: Sequence[UUID]) -> dict[UUID, str]:
    rows = conn.execute(
        "SELECT agent_id, hostname FROM agent WHERE agent_id = ANY(%s)",
        (list(agents),),
    ).fetchall()
    return {UUID(str(a)): str(h) for a, h in rows}


def stored(
    pol: m.Pol,
    names: dict[UUID, str],
    orig: m.JobRow,
    jr: m.JobRow,
    p: m.PluginDef,
    code: int,
    detail: str | None = None,
    *,
    stdout: str | None = "ok",
    stderr: str | None = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    truncated: bool = False,
) -> Row:
    """An item for a result the fixture stored with ``m.result`` defaults
    (received 5 min after the job's creation; started 2 s and finished 1 s
    earlier; snapshots from the plugin)."""
    when = jr.created_at + timedelta(minutes=5)
    position = [q.plugin_uuid for q in orig.plugins].index(p.plugin_uuid) + 1
    return {
        "agent_id": orig.agent_id,
        "hostname": names[orig.agent_id],
        "position": position,
        "plugin_uuid": p.plugin_uuid,
        "orig_job_id": orig.job_id,
        "job_id": jr.job_id,
        "original_code": code,
        "original_detail": detail,
        "code": code,
        "detail": detail,
        "reeval_policy_version": None,
        "reevaluated_by": None,
        "reevaluated_at": None,
        "plugin_name": pol.display(p),
        "operator": p.operator,
        "expected": p.expected,
        "execute": p.execute,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "truncated": truncated,
        "started_at": when - timedelta(seconds=2),
        "finished_at": when - timedelta(seconds=1),
        "received_at": when,
        "stdout": stdout,
        "stderr": stderr,
        "retry": jr.job_id != orig.job_id,
    }


def not_run(names: dict[UUID, str], orig: m.JobRow, plugin_uuid: UUID) -> Row:
    """Not run: name, operator and expected from the original job's stored
    eval_spec, execute from its stored payload (#144 (c); CHK-M11-120)."""
    key = str(plugin_uuid)
    spec = next(e for e in orig.eval_spec["plugins"] if e["plugin_uuid"] == key)
    planned = [e["plugin_uuid"] for e in orig.payload["plugins"]]
    item = orig.payload["plugins"][planned.index(key)]
    nulls = (
        "job_id original_code original_detail code detail reeval_policy_version"
        " reevaluated_by reevaluated_at exit_code timed_out truncated started_at"
        " finished_at received_at stdout stderr"
    ).split()
    return {
        "agent_id": orig.agent_id,
        "hostname": names[orig.agent_id],
        "position": planned.index(key) + 1,
        "plugin_uuid": plugin_uuid,
        "orig_job_id": orig.job_id,
        "plugin_name": spec["name"],
        "operator": spec["operator"],
        "expected": spec["expected"],
        "execute": item["execute"],
        "retry": False,
    } | dict.fromkeys(nulls)


def ordered(rows: list[Row]) -> list[Row]:
    """REQ-267: agent_id (PostgreSQL uuid order = byte order = int order),
    then payload position."""
    return sorted(rows, key=lambda r: (r["agent_id"].int, r["position"]))


def viewer(rows: list[Row]) -> list[Row]:
    return [r | {"stdout": None, "stderr": None} for r in rows]


def expected_world(conn: m.Conn, w: m.ResultsWorld) -> list[Row]:
    """REQ-267 (1) for ``m.results_world`` (its docstring is the input)."""
    p, j = w.p, w.jobs
    names = hostnames(conn, [h.agent_id for h in w.hosts.values()])
    pol = w.pol
    a, ar, b, c = j["a"], j["a_retry"], j["b"], j["c"]
    p1 = stored(pol, names, a, a, p[1], 1, stdout="no")
    p1 |= {
        "code": 0,
        "detail": "high",
        "reeval_policy_version": 1,
        "reevaluated_by": w.admin_id,
        "reevaluated_at": a.created_at + timedelta(hours=1),
    }
    rows = [
        stored(pol, names, a, a, p[0], 0, stdout=m.OUT, stderr=m.ERR),
        p1,
        stored(
            pol, names, a, a, p[2], 2, "runner_unavailable", stdout="", exit_code=None
        ),
        stored(pol, names, a, ar, p[3], 1, stdout="retry-fail"),
        not_run(names, a, p[4].plugin_uuid),
        *(not_run(names, b, q.plugin_uuid) for q in p),
        stored(pol, names, c, c, p[0], 0, stdout=m.C0_STDOUT),
        stored(pol, names, c, c, p[1], 0, m.C1_DETAIL, stdout=m.C1_STDOUT),
        stored(pol, names, c, c, p[2], 1, stdout="c-fail", truncated=True),
        stored(pol, names, c, c, p[3], 0, stdout="ok"),
        stored(pol, names, c, c, p[4], 2, "oversize", stdout=""),
    ]
    return ordered(rows)


def matches(row: Row, status: str | None, agent: UUID | None) -> bool:
    if agent is not None and row["agent_id"] != agent:
        return False
    if status is None:
        return True
    if status == "NOT_RUN":
        return row["job_id"] is None
    return row["job_id"] is not None and row["code"] == CODES[status]


def page(
    conn: m.Conn,
    scan_id: UUID,
    *,
    status: str | None = None,
    agent_id: UUID | None = None,
    with_output: bool = True,
    after: tuple[UUID, int] | None = None,
    limit: int = 10_000,
) -> list[Row]:
    return [
        as_dict(r)
        for r in rr.results_page(
            conn,
            scan_id,
            status=status,
            agent_id=agent_id,
            with_output=with_output,
            after=after,
            limit=limit,
        )
    ]


def walk(
    conn: m.Conn,
    scan_id: UUID,
    limit: int,
    *,
    status: str | None = None,
    agent_id: UUID | None = None,
    with_output: bool = True,
) -> list[Row]:
    """Keyset paging as the service will do it: after = (agent_id, position)
    of the last item of the previous page."""
    out: list[Row] = []
    after: tuple[UUID, int] | None = None
    for _ in range(1000):
        got = page(
            conn,
            scan_id,
            status=status,
            agent_id=agent_id,
            with_output=with_output,
            after=after,
            limit=limit,
        )
        assert len(got) <= limit
        out.extend(got)
        if len(got) < limit:
            return out
        after = (got[-1]["agent_id"], got[-1]["position"])
    raise AssertionError("paging did not end")


def world(server: PgServer) -> tuple[m.ResultsWorld, list[Row]]:
    with m.owner(server) as c:
        w = m.results_world(c)
        return w, expected_world(c, w)


# ------------------------------------------------------------ CHK-M11-118


def test_req267_1_one_item_per_planned_plugin(server: PgServer, conn: m.Conn) -> None:
    w, want = world(server)
    got = page(conn, w.scan_id)
    assert len(got) == 3 * 5
    for g, e in zip(got, want, strict=True):
        assert g == e, (g["agent_id"], g["position"])
    # spot checks of the REQ-267 (1) rules, stated directly
    a = [g for g in got if g["agent_id"] == w.hosts["a"].agent_id]
    assert [g["position"] for g in a] == [1, 2, 3, 4, 5]
    assert [g["plugin_uuid"] for g in a] == w.pol.uuids
    assert (a[1]["code"], a[1]["original_code"]) == (0, 1)  # highest reeval_id
    assert a[1]["detail"] == "high" and a[1]["original_detail"] is None
    assert a[3]["retry"] and a[3]["job_id"] == w.jobs["a_retry"].job_id
    assert a[4]["job_id"] is None and a[4]["code"] is None
    b = [g for g in got if g["agent_id"] == w.hosts["b"].agent_id]
    assert all(g["job_id"] is None for g in b) and len(b) == 5
    assert m.SCRIPT in b[0]["hostname"]  # returned verbatim
    for g in got:
        if g["reeval_policy_version"] is None and g["job_id"] is not None:
            assert (g["code"], g["detail"]) == (
                g["original_code"],
                g["original_detail"],
            )


def test_viewer_variant_same_items_without_output(
    server: PgServer, conn: m.Conn
) -> None:
    w, want = world(server)
    assert page(conn, w.scan_id, with_output=False) == viewer(want)


# ------------------------------------------------------------ CHK-M11-119


def test_results_in_two_partitions_both_read(server: PgServer, conn: m.Conn) -> None:
    w, want = world(server)
    with m.owner(server) as c:
        parts = {
            str(r[0])
            for r in c.execute(
                "SELECT DISTINCT tableoid::regclass::text FROM scan_result"
                " WHERE job_id = ANY(%s)",
                ([w.jobs["a"].job_id, w.jobs["a_retry"].job_id],),
            ).fetchall()
        }
        assert len(parts) == 2 and "scan_result_default" not in parts, parts
    got = page(conn, w.scan_id, agent_id=w.hosts["a"].agent_id)
    assert {g["job_id"] for g in got if g["job_id"]} == {
        w.jobs["a"].job_id,
        w.jobs["a_retry"].job_id,
    }
    assert got == [r for r in want if r["agent_id"] == w.hosts["a"].agent_id]


# ------------------------------------------------------------ CHK-M11-120


def test_not_run_named_from_eval_spec_never_the_catalog(
    server: PgServer, conn: m.Conn
) -> None:
    """The job's stored eval_spec and payload differ from the catalog on
    purpose; then the catalog is renamed, re-versioned, a plugin retired and
    the policy soft-deleted. The Not-run items keep the job's values."""
    with m.owner(server) as c:
        pol = m.make_policy(c, 3)
        h = m.host(c)
        sid = m.scan(c, pol, [h.agent_id])
        snap = [
            m.PluginDef(p.plugin_uuid, p.name, f"printf snap-{i} {m.EXEC}")
            for i, p in enumerate(pol.plugins)
        ]
        spec = {
            "plugins": [
                {
                    "plugin_uuid": str(p.plugin_uuid),
                    "name": f"Snapshot Family - snapshot name {i}",
                    "operator": "contains",
                    "expected": f"snap-{i}-{m.EXP}",
                }
                for i, p in enumerate(pol.plugins)
            ]
        }
        jr = m.job(c, sid, h.agent_id, pol, snap, state="dispatched", eval_spec=spec)
        names = hostnames(c, [h.agent_id])
        want = [not_run(names, jr, p.plugin_uuid) for p in pol.plugins]
        before = page(conn, sid)
        m.new_version(
            c,
            pol,
            expected={pol.plugins[0].plugin_uuid: "catalog-new"},
            rename={pol.plugins[1].plugin_uuid: "catalog renamed"},
            drop=[pol.plugins[2].plugin_uuid],
        )
        m.soft_delete(c, pol)
        catalog = c.execute(
            "SELECT plugin_name, execute, expected_result FROM plugin"
            " WHERE plugin_uuid = %s",
            (pol.plugins[0].plugin_uuid,),
        ).fetchone()
    assert catalog is not None and catalog[1] != snap[0].execute
    after = page(conn, sid)
    assert before == want and after == want
    assert [g["plugin_name"] for g in after] == [
        f"Snapshot Family - snapshot name {i}" for i in range(3)
    ]
    assert {g["operator"] for g in after} == {"contains"}
    assert all(m.EXP in g["expected"] and m.EXEC in g["execute"] for g in after)


# ------------------------------------------------------------ CHK-M11-121


def test_dropped_plugin_keeps_its_reevaluation_and_oversize_error(
    server: PgServer, conn: m.Conn
) -> None:
    w, want = world(server)
    with m.owner(server) as c:
        m.new_version(c, w.pol, drop=[w.p[1].plugin_uuid])
        m.soft_delete(c, w.pol)  # TS §4.3 L553: results stay readable
    got = page(conn, w.scan_id)
    assert got == want
    a1 = got[[g["agent_id"] for g in got].index(w.hosts["a"].agent_id) + 1]
    assert (a1["plugin_uuid"], a1["code"], a1["detail"]) == (
        w.p[1].plugin_uuid,
        0,
        "high",
    )
    c4 = next(
        g
        for g in got
        if g["agent_id"] == w.hosts["c"].agent_id
        and g["plugin_uuid"] == w.p[4].plugin_uuid
    )
    assert (c4["code"], c4["original_code"], c4["detail"]) == (2, 2, "oversize")
    assert (c4["stdout"], c4["stderr"]) == ("", "")


# ------------------------------------------------------------ CHK-M11-122


def test_filters_alone_and_together(server: PgServer, conn: m.Conn) -> None:
    w, want = world(server)
    agents: list[UUID | None] = [None, *(h.agent_id for h in w.hosts.values())]
    agents.append(uuid4())  # an agent not in the scan: empty
    for status, agent in itertools.product(STATUSES, agents):
        expect = [r for r in want if matches(r, status, agent)]
        assert page(conn, w.scan_id, status=status, agent_id=agent) == expect, (
            status,
            agent,
        )
    a = w.hosts["a"].agent_id
    p1 = w.p[1].plugin_uuid
    # the effective code decides: a FAIL re-evaluated to PASS is PASS only
    assert p1 in [
        g["plugin_uuid"] for g in page(conn, w.scan_id, status="PASS", agent_id=a)
    ]
    assert p1 not in [
        g["plugin_uuid"] for g in page(conn, w.scan_id, status="FAIL", agent_id=a)
    ]
    # NOT_RUN gives only planned plugins without a result; none for host c
    nr = page(conn, w.scan_id, status="NOT_RUN")
    assert len(nr) == 6 and all(g["job_id"] is None for g in nr)
    assert page(conn, w.scan_id, status="NOT_RUN", agent_id=w.hosts["c"].agent_id) == []


def test_unknown_status_refused_before_any_statement(
    conn: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    for bad in ("pass", "Pass", "NOTRUN", "", "OK", "ERROR "):
        with pytest.raises(ValueError):
            rr.results_page(
                conn,
                uuid4(),
                status=bad,
                agent_id=None,
                with_output=True,
                after=None,
                limit=10,
            )
        with pytest.raises(ValueError):
            rr.results_export(
                conn, uuid4(), status=bad, agent_id=None, with_output=False, max_rows=5
            )
    assert spy.statements == []


# ------------------------------------------------------------ CHK-M11-123


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_keyset_visits_every_item_once(
    server: PgServer, conn: m.Conn, limit: int
) -> None:
    w, want = world(server)
    agents: list[UUID | None] = [None, *(h.agent_id for h in w.hosts.values())]
    for status, agent in itertools.product(STATUSES, agents):
        expect = [r for r in want if matches(r, status, agent)]
        got = walk(conn, w.scan_id, limit, status=status, agent_id=agent)
        assert got == expect, (status, agent, limit)


def test_keyset_after_a_filtered_out_anchor(server: PgServer, conn: m.Conn) -> None:
    """The anchor need not match the filter: strictly after (agent, position)."""
    w, want = world(server)
    a = w.hosts["a"].agent_id
    for anchor in want:
        key = (anchor["agent_id"].int, anchor["position"])
        expect = [
            r
            for r in want
            if (r["agent_id"].int, r["position"]) > key and matches(r, "FAIL", None)
        ]
        got = page(
            conn,
            w.scan_id,
            status="FAIL",
            after=(anchor["agent_id"], anchor["position"]),
        )
        assert got == expect, anchor["position"]
    # an anchor position past the end of host a's payload moves to the next host
    assert page(conn, w.scan_id, after=(a, 99)) == [
        r for r in want if r["agent_id"].int > a.int
    ]


# ------------------------------------------------------------ CHK-M11-124


def test_another_scans_rows_never_appear(server: PgServer, conn: m.Conn) -> None:
    """A third scan on the same hosts and plugins whose jobs are created in
    the same microsecond as host a's original (same partition, same
    job_created_at), answering every plugin, with re-evaluations."""
    w, want = world(server)
    pol, p = w.pol, w.p
    ja = w.jobs["a"]
    with m.owner(server) as c:
        third = m.scan(c, pol, [w.hosts["a"].agent_id, w.hosts["b"].agent_id])
        tj = {
            k: m.job(
                c,
                third,
                w.hosts[k].agent_id,
                pol,
                state="completed",
                created_at=ja.created_at,
            )
            for k in ("a", "b")
        }
        for k in ("a", "b"):
            for q in p:
                m.result(c, tj[k], pol, q, code=1, stdout="third-scan", stderr="third")
        base = m.reserve_reeval_ids(c, 5)
        for i, q in enumerate((p[1], p[3], p[4])):
            m.add_reeval(
                c,
                tj["a"].job_id,
                q.plugin_uuid,
                code=2,
                detail="third",
                reeval_id=base + 1 + i,
            )
        names = hostnames(c, [w.hosts["a"].agent_id, w.hosts["b"].agent_id])
        third_want = ordered(
            [
                stored(
                    pol, names, tj[k], tj[k], q, 1, stdout="third-scan", stderr="third"
                )
                for k in ("a", "b")
                for q in p
            ]
        )
    assert tj["a"].created_at == ja.created_at
    assert page(conn, w.scan_id) == want
    for status in STATUSES:
        assert page(conn, w.scan_id, status=status) == [
            r for r in want if matches(r, status, None)
        ]
    got3 = page(conn, third)
    own = {tj["a"].job_id, tj["b"].job_id}
    assert {g["job_id"] for g in got3} == own
    reeval = {(tj["a"].job_id, q.plugin_uuid) for q in (p[1], p[3], p[4])}
    for g, e in zip(got3, third_want, strict=True):
        if (g["job_id"], g["plugin_uuid"]) in reeval:
            assert (g["code"], g["detail"], g["original_code"]) == (2, "third", 1)
            continue
        assert g == e
    other = page(conn, w.other_scan)
    assert len(other) == 10 and all(g["stdout"] == "other-scan" for g in other)
    assert not {g["job_id"] for g in other} & {j.job_id for j in w.jobs.values()}


# ------------------------------------------------------------ CHK-M11-125


def test_viewer_statement_never_reads_the_output(
    server: PgServer, conn: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The raw rows psycopg fetches for the viewer variant hold no OUT or ERR
    byte (plan TASK-235 §3: NULL selected), while the operator variant's do
    (so the capture is real)."""
    w, _ = world(server)
    raw: list[str] = []
    real_fetchall = psycopg.Cursor.fetchall

    def fetchall(cur: Any) -> Any:
        rows = real_fetchall(cur)
        raw.append(repr(rows))
        return rows

    monkeypatch.setattr(psycopg.Cursor, "fetchall", fetchall)
    for status in STATUSES:
        rows = rr.results_page(
            conn,
            w.scan_id,
            status=status,
            agent_id=None,
            with_output=False,
            after=None,
            limit=100,
        )
        assert all(r.stdout is None and r.stderr is None for r in rows)
    rows = rr.results_export(
        conn, w.scan_id, status=None, agent_id=None, with_output=False, max_rows=100
    )
    assert len(rows) == 15 and all(r.stdout is None for r in rows)
    assert raw and m.hits(raw, m.OUTPUT_CANARIES) == []
    assert m.hits(raw, (m.EXEC, m.EXP)) == [m.EXEC, m.EXP]  # catalog text: allowed
    raw.clear()
    rr.results_page(
        conn,
        w.scan_id,
        status=None,
        agent_id=None,
        with_output=True,
        after=None,
        limit=100,
    )
    assert m.hits(raw, m.OUTPUT_CANARIES) == sorted(m.OUTPUT_CANARIES)


# ------------------------------------------------------------ CHK-M11-126


def test_export_equals_the_pages_and_reads_one_extra_row(
    server: PgServer, conn: m.Conn
) -> None:
    w, want = world(server)
    agents: list[UUID | None] = [None, w.hosts["a"].agent_id]
    for status, agent, out in itertools.product(STATUSES, agents, (True, False)):
        rows = rr.results_export(
            conn,
            w.scan_id,
            status=status,
            agent_id=agent,
            with_output=out,
            max_rows=1000,
        )
        assert [as_dict(r) for r in rows] == walk(
            conn, w.scan_id, 2, status=status, agent_id=agent, with_output=out
        )
    # LIMIT max_rows + 1: 15 items
    for cap, n in ((3, 4), (13, 14), (14, 15), (15, 15), (16, 15)):
        got = rr.results_export(
            conn, w.scan_id, status=None, agent_id=None, with_output=False, max_rows=cap
        )
        assert len(got) == n, cap
        assert [as_dict(r) for r in got] == viewer(want)[:n]


@pytest.mark.parametrize(
    ("layout", "n"),
    [((5000,) * 20, 100_000), ((5000,) * 20 + (1,), 100_001)],
    ids=["100000", "100001"],
)
def test_export_at_the_csv_cap(
    server: PgServer, conn: m.Conn, layout: tuple[int, ...], n: int
) -> None:
    """#146 (e): 100,000 planned rows read back 100,000; 100,001 read back
    100,001 (the service refuses that one before building any text)."""
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        sid, _ = m.wide_scan(c, pol, layout)
    rows = rr.results_export(
        conn, sid, status=None, agent_id=None, with_output=False, max_rows=100_000
    )
    assert len(rows) == n
    assert all(r.job_id is None for r in rows)
    keys = [(r.agent_id.int, r.position) for r in rows]
    assert keys == sorted(keys) and len(set(keys)) == n


# ------------------------------------------------------------ CHK-M11-127


def test_read_only_snapshot(server: PgServer) -> None:
    w, want = world(server)
    p4 = w.p[4].plugin_uuid
    a = w.hosts["a"].agent_id
    with m.tx_conn(server, "bitscan_app") as rc:
        rr.read_only_snapshot(rc)
        level = rc.execute("SHOW transaction_isolation").fetchone()
        ro = rc.execute("SHOW transaction_read_only").fetchone()
        assert level == ("repeatable read",) and ro == ("on",)
        first = page(rc, w.scan_id)
        assert first == want
        with m.owner(server) as oc:  # another session commits a late result
            m.result(oc, w.jobs["a_retry"], w.pol, w.p[4], code=0, stdout="late")
        assert page(rc, w.scan_id) == first  # one snapshot
        rc.commit()
        late = [g for g in page(rc, w.scan_id) if g["agent_id"] == a]
        assert (late[4]["plugin_uuid"], late[4]["code"], late[4]["retry"]) == (
            p4,
            0,
            True,
        )
        rc.rollback()
        rr.read_only_snapshot(rc)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            rc.execute(
                "UPDATE agent SET hostname = hostname WHERE agent_id = %s", (uuid4(),)
            )
        rc.rollback()
        rc.execute("SELECT 1")
        with pytest.raises(psycopg.errors.ActiveSqlTransaction):
            rr.read_only_snapshot(rc)  # refused when not the first statement


# ------------------------------------------------------------ CHK-M11-128


def test_exists(server: PgServer, conn: m.Conn) -> None:
    w, _ = world(server)
    with m.owner(server) as c:
        empty = m.scan(c, w.pol, [w.hosts["a"].agent_id])  # no jobs yet
    assert rr.exists(conn, w.scan_id) is True
    assert rr.exists(conn, empty) is True
    assert page(conn, empty) == []
    unknown = uuid4()
    assert rr.exists(conn, unknown) is False
    assert page(conn, unknown) == []
    assert (
        rr.results_export(
            conn, unknown, status=None, agent_id=None, with_output=True, max_rows=10
        )
        == []
    )


# ------------------------------------------------------------ CHK-M11-129


def test_pd46_results_py_frozen_and_composed() -> None:
    path = Path(m8.__file__)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == RESULTS_PY_6EFE0FB
    assert getattr(rr, "_m8") is m8  # noqa: B009 - private, pinned on purpose
    effective = m8._EFFECTIVE.as_string(None)
    for statement in (rr._PAGE, rr._PAGE_VIEWER):
        assert isinstance(statement, sql.Composed)
        assert list(statement)[0] is m8._EFFECTIVE  # the object, not a copy
        assert statement.as_string(None).startswith(effective)


# ------------------------------------------------------------ CHK-M11-130


def plan_nodes(
    node: dict[str, Any], under_subplan: bool = False
) -> Iterator[tuple[dict[str, Any], bool]]:
    sub = under_subplan or node.get("Parent Relationship") == "SubPlan"
    yield node, sub
    for child in node.get("Plans", []):
        yield from plan_nodes(child, sub)


def test_explain_reads_reeval_once(
    server: PgServer, conn: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, _ = world(server)
    captured: list[tuple[Any, Any]] = []
    real_execute = psycopg.Cursor.execute

    def execute(cur: Any, query: Any, params: Any = None, **kw: Any) -> Any:
        captured.append((query, params))
        return real_execute(cur, query, params, **kw)

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    a = w.hosts["a"].agent_id
    for status, agent, after, out in (
        (None, None, None, True),
        ("FAIL", a, None, False),
        ("NOT_RUN", None, (a, 2), True),
    ):
        rr.results_page(
            conn,
            w.scan_id,
            status=status,
            agent_id=agent,
            with_output=out,
            after=after,
            limit=50,
        )
    rr.results_export(
        conn, w.scan_id, status="PASS", agent_id=None, with_output=True, max_rows=10
    )
    monkeypatch.undo()
    assert len(captured) == 4
    for query, params in captured:
        explained = conn.execute(
            sql.SQL("EXPLAIN (FORMAT JSON) {}").format(query), params
        ).fetchone()
        assert explained is not None
        doc = (
            explained[0]
            if not isinstance(explained[0], str)
            else json.loads(explained[0])
        )
        nodes = list(plan_nodes(doc[0]["Plan"]))
        reeval = [n for n, _ in nodes if n.get("Relation Name") == "scan_result_reeval"]
        assert len(reeval) == 1, len(reeval)
        assert not [
            n
            for n, sub in nodes
            if sub and n.get("Relation Name") == "scan_result_reeval"
        ]


# ------------------------------------------------------------ CHK-M11-131


def test_select_only_as_bitscan_app(
    server: PgServer, conn: m.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, _ = world(server)
    a = w.hosts["a"].agent_id
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    for out in (True, False):
        rr.results_page(
            conn,
            w.scan_id,
            status="FAIL",
            agent_id=a,
            with_output=out,
            after=(a, 1),
            limit=5,
        )
        rr.results_export(
            conn, w.scan_id, status="NOT_RUN", agent_id=a, with_output=out, max_rows=5
        )
    rr.exists(conn, w.scan_id)
    with m.tx_conn(server, "bitscan_app") as tc:
        rr.read_only_snapshot(tc)
        rr.results_page(
            tc,
            w.scan_id,
            status=None,
            agent_id=None,
            with_output=True,
            after=None,
            limit=5,
        )
    monkeypatch.undo()
    # 2 pages, 2 exports, exists, the snapshot and its page (the app
    # connection's identity probe in m.app ran before the spy)
    assert len(spy.statements) == 7
    assert set(spy.roles) == {"bitscan_app"}
    for text in spy.statements:
        upper = text.upper()
        assert upper.startswith(("WITH ", "SELECT ", "SET TRANSACTION ")), text[:40]
        words = set(upper.replace("(", " ").replace(")", " ").replace(",", " ").split())
        assert not words & {"INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "COPY"}
        assert " FOR UPDATE" not in upper and " FOR SHARE" not in upper
        assert str(w.scan_id) not in text and str(a) not in text  # parameters only
