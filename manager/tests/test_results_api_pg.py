"""TASK-244 TEST: the results routes through the API on PostgreSQL
(TP-M11-12; CHK-M11-220 to -226, and -459 to -462).

Expected values, from the spec and the criteria first: TS §6.2 L1083, L1123
(raw output for operator and admin only), §6.3 L1135-L1136, L1141, L1144
(CSV: formula cells escaped); REQ-267 (3), (5); REQ-268 (1)-(4); REQ-269
(2)-(4); REQ-272 (2), (4); #144 (a), (b), (d), #146 (c), (e), (f): `text/csv`
UTF-8, no BOM, CRLF, `Content-Disposition: attachment;
filename="scan-<scan_id>-results.csv"`, at most 100,000 rows, otherwise 400
"Invalid request: more than 100000 rows; narrow the filters" before any CSV
byte. The lead's TASK-244 rows: operator and admin pages keep `stdout` and
`stderr`, a viewer's have neither key (CHK-M11-222); the upper- and
lower-case `agent_id` share one cursor scope; a cursor is accepted only in its
exact form. Then bound to the names (the results scope string, to sign forged
cursors; M5's `escape_cell` and the #146 header from `results_view` for the
CSV-equals-JSON row).

Each test starts from emptied scan tables (TRUNCATE as owner).
"""

from __future__ import annotations

import ast
import csv
import io
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.api.pagination import encode_cursor
from bitscan_manager.api.user import scan_views as route_mod
from bitscan_manager.services.jobs import results_view
from bitscan_manager.services.packages.csv_export import escape_cell

from . import m11_pg_fixtures as m
from .agent_sim import ApiEnv, api_env
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

BASE_AT = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
BAD_CURSOR = "Invalid request: query.cursor"
TOO_MANY = "Invalid request: more than 100000 rows; narrow the filters"
VIEWER_KEYS = {
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
}
OUTPUT_KEYS = {"stdout", "stderr"}
VIEWERS = ("viewer:session", "viewer:api")
OUTPUT_ROLES = ("operator:session", "operator:api", "admin:session", "admin:api")
# CSV column → JSON item key (#146; the CSV has no operator, expected,
# execute, reevaluated_by or received_at columns).
CSV_TO_ITEM = {c: c for c in results_view.CSV_HEADER} | {
    "stdout": "stdout",
    "stderr": "stderr",
}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-results-api")) as s:
        yield s


@pytest.fixture
def clean(server: PgServer) -> PgServer:
    with m.owner(server) as c:
        c.execute("TRUNCATE scan, scan_job, scan_result, scan_result_reeval CASCADE")
    return server


@pytest.fixture
def env(clean: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(clean, tmp_path) as e:
        yield e


@pytest.fixture
def who(env: ApiEnv) -> dict[str, m.Caller]:
    with env.conn() as c:
        return m.callers(c, at=env.clock.now())


@pytest.fixture
def rw(env: ApiEnv) -> m.ResultsWorld:
    with m.owner(env.server) as c:
        admin = m.make_user(c, "admin", at=BASE_AT)
        return m.results_world(c, at=BASE_AT, admin_id=admin)


def get(env: ApiEnv, caller: m.Caller, path: str, **params: Any) -> Any:
    return env.client.get(path, params=params or None, headers=caller.headers())


def ok(r: Any) -> Any:
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def problem(r: Any, status: int, type_: str, detail: str | None = None) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "content-disposition" not in r.headers
    body = r.json()
    assert body["status"] == status and body["type"] == type_, body
    if detail is not None:
        assert body["detail"] == detail, body


def results_path(scan_id: Any) -> str:
    return f"/api/v1/scans/{scan_id}/results"


def walk(
    env: ApiEnv, caller: m.Caller, path: str, **params: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every page (items, and each page's raw text)."""
    items: list[dict[str, Any]] = []
    texts: list[str] = []
    cursor: str | None = None
    for _ in range(500):
        q = dict(params)
        if cursor is not None:
            q["cursor"] = cursor
        r = get(env, caller, path, **q)
        body = ok(r)
        texts.append(r.text)
        assert set(body) == {"items", "next_cursor"}
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items, texts
    raise AssertionError("paging did not end")


def key(item: dict[str, Any]) -> tuple[str, str]:
    return item["agent_id"], item["plugin_uuid"]


FILTERS: list[dict[str, str]] = [
    {},
    {"status": "PASS"},
    {"status": "FAIL"},
    {"status": "ERROR"},
    {"status": "NOT_RUN"},
]


def all_filters(rw: m.ResultsWorld) -> list[dict[str, str]]:
    out = list(FILTERS)
    for h in rw.hosts.values():
        out.append({"agent_id": str(h.agent_id)})
        out.append({"agent_id": str(h.agent_id), "status": "PASS"})
    return out


# ------------------------------------------------------------ CHK-M11-220


def test_limit_2_paging_visits_every_item_once(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """REQ-267 (3): limit=2 visits every item once, in the unpaged order
    (agent_id, then payload position): 3 hosts × 5 planned plugins."""
    v = who["viewer:session"]
    whole = ok(get(env, v, results_path(rw.scan_id), limit="500"))
    assert whole["next_cursor"] is None and len(whole["items"]) == 15
    paged, _ = walk(env, v, results_path(rw.scan_id), limit="2")
    assert paged == whole["items"]
    assert [i["agent_id"] for i in paged] == sorted(i["agent_id"] for i in paged)
    for f in all_filters(rw):
        one = ok(get(env, v, results_path(rw.scan_id), limit="500", **f))["items"]
        assert walk(env, v, results_path(rw.scan_id), limit="2", **f)[0] == one, f


def test_items_and_filters(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """REQ-267 (2) at the route: the effective result after two
    re-evaluations, the original beside it; the retry's result; a planned
    plugin never run is a Not-run item; each status filter gives its subset;
    the other scan's rows never appear."""
    v = who["viewer:api"]
    items = ok(get(env, v, results_path(rw.scan_id), limit="500"))["items"]
    by = {key(i): i for i in items}
    a, c = str(rw.hosts["a"].agent_id), str(rw.hosts["c"].agent_id)
    p = [str(x.plugin_uuid) for x in rw.p]
    assert (by[(a, p[1])]["result"], by[(a, p[1])]["original_result"]) == (
        "PASS",
        "FAIL",
    )
    assert by[(a, p[1])]["eval_detail"] == "high"
    assert by[(a, p[1])]["reevaluated_by"] == rw.admin_id
    assert by[(a, p[3])]["retry"] is True and by[(a, p[3])]["result"] == "FAIL"
    assert by[(a, p[4])]["result"] is None and by[(a, p[4])]["original_result"] is None
    assert by[(c, p[2])]["result"] == by[(c, p[2])]["original_result"] == "FAIL"
    for status in ("PASS", "FAIL", "ERROR"):
        sub = ok(get(env, v, results_path(rw.scan_id), status=status, limit="500"))
        assert [key(i) for i in sub["items"]] == [
            key(i) for i in items if i["result"] == status
        ], status
    nr = ok(get(env, v, results_path(rw.scan_id), status="NOT_RUN", limit="500"))
    assert [key(i) for i in nr["items"]] == [
        key(i) for i in items if i["result"] is None
    ]
    assert len(nr["items"]) == 6  # a's p4 and the queued host b's five
    jobs = {str(j.job_id) for j in rw.jobs.values()}
    assert {i["job_id"] for i in items if i["job_id"]} <= jobs
    assert "other-scan" not in str(items)


def test_results_cursor_scope(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """REQ-267 (3): a cursor from another scan or another filter set is 400;
    the lead's row: the upper- and lower-case agent_id share one scope."""
    v = who["viewer:session"]
    c = ok(get(env, v, results_path(rw.scan_id), limit="2"))["next_cursor"]
    assert c
    for other in ({"status": "PASS"}, {"agent_id": str(rw.hosts["a"].agent_id)}):
        r = get(env, v, results_path(rw.scan_id), limit="2", cursor=c, **other)
        problem(r, 400, "invalid_request", BAD_CURSOR)
    problem(
        get(env, v, results_path(rw.other_scan), limit="2", cursor=c),
        400,
        "invalid_request",
        BAD_CURSOR,
    )
    scans_c = ok(get(env, v, "/api/v1/scans", limit="1"))["next_cursor"]
    problem(
        get(env, v, results_path(rw.scan_id), cursor=scans_c),
        400,
        "invalid_request",
        BAD_CURSOR,
    )
    low = str(rw.hosts["c"].agent_id)
    up = low.upper()
    c1 = ok(get(env, v, results_path(rw.scan_id), limit="2", agent_id=low))
    assert c1["next_cursor"]
    a = ok(
        get(
            env,
            v,
            results_path(rw.scan_id),
            limit="2",
            agent_id=low,
            cursor=c1["next_cursor"],
        )
    )
    b = ok(
        get(
            env,
            v,
            results_path(rw.scan_id),
            limit="2",
            agent_id=up,
            cursor=c1["next_cursor"],
        )
    )
    assert a == b and a["items"]


@pytest.mark.parametrize(
    "position",
    [0, -1, 2**53, True, "1", 1.5, None, "UPPER", "SHORT", "EXTRA"],
)
def test_a_results_cursor_is_accepted_only_in_its_exact_form(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld, position: Any
) -> None:
    """The lead's row: [canonical agent_id, position 1..2^53-1] only; a
    cursor signed for the right scope with anything else is 400 (white box:
    the scope string, to sign it). [agent_id, 1] is accepted."""
    scope = f"scan_results:{rw.scan_id}::"
    agent = str(rw.hosts["a"].agent_id)
    if position == "UPPER":
        k: list[Any] = [agent.upper(), 1]
    elif position == "SHORT":
        k = [agent]
    elif position == "EXTRA":
        k = [agent, 1, 2]
    else:
        k = [agent, position]
    v = who["viewer:session"]
    r = get(env, v, results_path(rw.scan_id), cursor=encode_cursor(scope, k))
    problem(r, 400, "invalid_request", BAD_CURSOR)
    good = get(
        env, v, results_path(rw.scan_id), cursor=encode_cursor(scope, [agent, 1])
    )
    assert ok(good)["items"][0]["agent_id"] >= agent


# ------------------------------------------------------------ CHK-M11-221


@pytest.mark.parametrize("suffix", ["", ".csv"])
def test_unknown_and_malformed(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld, suffix: str
) -> None:
    """REQ-267 (5), REQ-269 (4): unknown scan 404 not_found (a problem, never
    a CSV); malformed id, unknown status and malformed agent_id 400."""
    v = who["viewer:session"]
    unknown = "0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11"
    problem(get(env, v, results_path(unknown) + suffix), 404, "not_found")
    problem(get(env, v, results_path("nope") + suffix), 400, "invalid_request")
    for q in (
        {"status": "pass"},
        {"status": "NOTRUN"},
        {"status": "SKIPPED"},
        {"agent_id": "nope"},
        {"agent_id": str(rw.hosts["a"].agent_id).replace("-", "")},
    ):
        problem(
            get(env, v, results_path(rw.scan_id) + suffix, **q), 400, "invalid_request"
        )


# ------------------------------------------------------------ CHK-M11-222


@pytest.mark.parametrize("kind", VIEWERS)
def test_viewer_responses_hold_no_output(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld, kind: str
) -> None:
    """REQ-268 (1): a viewer (session and API token), JSON and CSV, every page
    and every filter: no stdout or stderr key or column, no OUT or ERR byte;
    the items carry exactly the viewer keys."""
    v = who[kind]
    for f in all_filters(rw):
        items, texts = walk(env, v, results_path(rw.scan_id), limit="2", **f)
        for i in items:
            assert set(i) == VIEWER_KEYS, (f, set(i) ^ VIEWER_KEYS)
        assert m.hits(texts, m.OUTPUT_CANARIES) == [], f
        r = get(env, v, results_path(rw.scan_id) + ".csv", **f)
        assert r.status_code == 200
        header = next(csv.reader(io.StringIO(r.text, newline="")))
        assert not ({"stdout", "stderr"} & set(header)), f
        assert tuple(header) == results_view.CSV_HEADER
        assert m.hits([r.text], m.OUTPUT_CANARIES) == [], f


@pytest.mark.parametrize("kind", OUTPUT_ROLES)
def test_operator_and_admin_pages_keep_stdout_and_stderr(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld, kind: str
) -> None:
    """CHK-M11-222, the lead's row: every operator and admin page (session
    and API token) has stdout and stderr on every item, and the CSV has the
    two columns; host a's p0 output (OUT, ERR) is there."""
    caller = who[kind]
    items, texts = walk(env, caller, results_path(rw.scan_id), limit="2")
    assert len(items) == 15
    for i in items:
        assert set(i) == VIEWER_KEYS | OUTPUT_KEYS
    a, p0 = str(rw.hosts["a"].agent_id), str(rw.p[0].plugin_uuid)
    mine = next(i for i in items if key(i) == (a, p0))
    assert (mine["stdout"], mine["stderr"]) == (m.OUT, m.ERR)
    not_run = [i for i in items if i["result"] is None]
    assert not_run and all(i["stdout"] is None for i in not_run)
    r = get(env, caller, results_path(rw.scan_id) + ".csv")
    header = next(csv.reader(io.StringIO(r.text, newline="")))
    assert tuple(header) == results_view.CSV_HEADER + ("stdout", "stderr")
    assert m.OUT in r.text and m.ERR in r.text


# ------------------------------------------------------------ CHK-M11-223


def test_a_demoted_operator_loses_output_on_the_next_call(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """REQ-268 (2): the role is read per request, never from the token kind:
    an operator's API token gets output; demoted to viewer, the same token
    gets none (JSON and CSV); promoted back, it gets it again."""
    op = who["operator:api"]
    assert op.user_id is not None
    path = results_path(rw.scan_id)

    def has_output() -> tuple[bool, bool]:
        js = ok(get(env, op, path, limit="500"))["items"]
        cs = get(env, op, path + ".csv").text
        return all(OUTPUT_KEYS <= set(i) for i in js), m.OUT in cs

    assert has_output() == (True, True)
    with env.conn() as c:
        m.set_role(c, op.user_id, "viewer")
    assert has_output() == (False, False)
    js = ok(get(env, op, path, limit="500"))["items"]
    assert all(not (OUTPUT_KEYS & set(i)) for i in js)
    with env.conn() as c:
        m.set_role(c, op.user_id, "operator")
    assert has_output() == (True, True)


# ------------------------------------------------------------ CHK-M11-224


def test_no_canary_or_token_in_logs_or_problems(
    env: ApiEnv,
    who: dict[str, m.Caller],
    rw: m.ResultsWorld,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-268 (4), REQ-272 (4): across viewer and operator calls (JSON, CSV,
    paging, refusals and errors), no log record (DEBUG) holds any of the four
    canaries or a token, and no problem detail does either."""
    caplog.set_level(logging.DEBUG)
    details: list[str] = []
    path = results_path(rw.scan_id)
    for kind in ("viewer:session", "operator:api", "admin:session"):
        caller = who[kind]
        walk(env, caller, path, limit="3")
        get(env, caller, path + ".csv")
        for bad in (
            get(env, caller, path, status="pass"),
            get(env, caller, path, cursor="x" * 40),
            get(env, caller, results_path("0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11")),
        ):
            details.append(bad.text)
    texts = [caplog.text, *details]
    texts += [str(r.__dict__) for r in caplog.records]
    assert m.hits(texts) == []
    tokens = [c.token for c in who.values() if c.token]
    assert not [t for t in tokens if any(t in x for x in texts)]


# ------------------------------------------------------------ CHK-M11-225


def _cell(value: Any) -> str:
    """#146 (b) as the spec says it: null empty, booleans true/false, times
    RFC 3339 UTC with microseconds and Z; then M5's escape_cell."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
        if text and "T" in text and text[:4].isdigit() and text[4:5] == "-":
            at = datetime.fromisoformat(text.replace("Z", "+00:00"))
            text = at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return escape_cell(text)


@pytest.mark.parametrize("kind", ["viewer:session", "operator:session"])
def test_csv_rows_equal_the_json_items(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld, kind: str
) -> None:
    """REQ-269 (2): for the same filters the CSV rows are the JSON items, in
    order, both verdicts included, every cell escaped (the `=1+2` stdout and
    `@SUM(1)` eval detail of host c are formula cells)."""
    caller = who[kind]
    for f in all_filters(rw):
        items = ok(get(env, caller, results_path(rw.scan_id), limit="500", **f))[
            "items"
        ]
        r = get(env, caller, results_path(rw.scan_id) + ".csv", **f)
        rows = list(csv.reader(io.StringIO(r.text, newline="")))
        header, body = rows[0], rows[1:]
        assert len(body) == len(items), f
        want = [[_cell(i[CSV_TO_ITEM[col]]) for col in header] for i in items]
        assert body == want, f
    text = get(env, caller, results_path(rw.scan_id) + ".csv").text
    assert "'@SUM(1)" in text and "@SUM(1)" not in text.replace("'@SUM(1)", "")


def test_csv_headers_encoding_and_line_endings(
    env: ApiEnv, who: dict[str, m.Caller], rw: m.ResultsWorld
) -> None:
    """REQ-269, #146 (c): text/csv (UTF-8), the attachment name with the
    canonical lower-case id even when asked with upper case, no BOM, CRLF
    record ends; embedded LF and CRLF stay inside quoted cells."""
    caller = who["operator:session"]
    upper = str(rw.scan_id).upper()
    r = get(env, caller, f"/api/v1/scans/{upper}/results.csv")
    assert r.status_code == 200
    ctype = r.headers["content-type"].lower().replace(" ", "")
    assert ctype.startswith("text/csv")
    assert "charset" not in ctype or "charset=utf-8" in ctype
    assert r.headers["content-disposition"] == (
        f'attachment; filename="scan-{rw.scan_id}-results.csv"'
    )
    raw = r.content
    assert not raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")
    assert raw.endswith(b"\r\n")
    records = list(csv.reader(io.StringIO(r.text, newline="")))
    lines_ending = raw.count(b"\r\n")
    assert lines_ending >= len(records)
    head = raw.split(b"\r\n", 1)[0]
    assert b"\n" not in head
    c0 = next(
        row
        for row in records[1:]
        if row[2] == str(rw.p[0].plugin_uuid) and row[1] == str(rw.hosts["c"].agent_id)
    )
    assert m.C0_STDOUT in c0  # LF and CRLF kept inside the quoted cell


# ------------------------------------------------------------ CHK-M11-226


@pytest.mark.parametrize("extra", [0, 1])
def test_csv_cap_100000_rows(env: ApiEnv, who: dict[str, m.Caller], extra: int) -> None:
    """REQ-269 (3), #146 (e): 100,000 rows export (operator, with output
    columns); 100,001 are 400 invalid_request with the fixed text and a
    problem body, no CSV byte and no Content-Disposition, for a viewer and an
    operator; narrowing with agent_id then exports."""
    with m.owner(env.server) as c:
        pol = m.make_policy(c, 1)
        layout = [5_000] * 20 + ([1] if extra else [])
        sid, agents = m.wide_scan(c, pol, layout, at=BASE_AT)
    path = results_path(sid) + ".csv"
    if not extra:
        r = get(env, who["operator:session"], path)
        assert r.status_code == 200, r.text[:300]
        rows = list(csv.reader(io.StringIO(r.text, newline="")))
        assert len(rows) == 1 + 100_000
        assert r.headers["content-disposition"].startswith("attachment;")
        return
    for kind in ("viewer:session", "operator:api"):
        r = get(env, who[kind], path)
        problem(r, 400, "invalid_request", TOO_MANY)
        assert not r.text.startswith("hostname")
    narrow = get(env, who["viewer:session"], path, agent_id=str(agents[0].agent_id))
    assert narrow.status_code == 200
    assert len(list(csv.reader(io.StringIO(narrow.text, newline="")))) == 1 + 5_000


# ------------------------------------------------------------ CHK-M11-459


def test_the_route_module_imports_no_repository() -> None:
    """REQ-272 (2): bm/api/user/scan_views.py imports no
    bitscan_manager.repositories module."""
    tree = ast.parse(Path(route_mod.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    assert not [n for n in names if n.startswith("bitscan_manager.repositories")]
    assert "logging" not in names  # the module logs nothing
