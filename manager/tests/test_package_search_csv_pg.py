"""TASK-114: GET /api/v1/packages/search.csv on PostgreSQL (TP-M5-07).

Checks CHK-M5-150 to CHK-M5-160 of tests/m5/test-plan.md through create_app()
with a real runtime, as bitscan_app, on the package_fleet fixture fleet plus
one host of formula-trigger names (a database of this module's own).
Expected values: TS §6.2 L1117 (viewer; JSON or CSV), §6 (user routes take
bsu_ and bsk_ only), §6.3 L1136 (600 per minute per user), L1140 (the four
headers, no CORS), L1142 (formula escape, every export), §7.3 L1224 (the
current result set), REQ-115, REQ-116, #84 (a)-(d) as approved 2026-10-24
(whole result set, no limit or cursor, at most 100,000 data rows else 400
before any byte; header = the JSON field names in TS §7.1 order; text/csv;
charset=utf-8, attachment; filename="packages.csv", UTF-8 without BOM, CRLF,
RFC 4180), and the lead's TASK-111 r1 ruling (a leading whitespace run that
holds a tab or CR is prefixed too).

Expected CSV bytes are built here from the JSON items by an escape and
quoting oracle written from those rules (oracle_escape is the TASK-111 test's
independent rule), never by the code under test.
"""

import csv
import inspect
import io
import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.api.webui import WebUi
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.packages import (
    HostGroup,
    PackageGroup,
    PackageRow,
    PackageSearchRepo,
)
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.packages import parse_search
from bitscan_manager.services.packages import search as service

from . import package_fleet as pf
from .conftest import PgServer, own_migrated_server
from .test_csv_export import oracle_escape
from .test_inventory_ingest import T0, Clock
from .test_package_search_pg import (
    CANARY,
    HOST_KEYS,
    PKG_KEYS,
    REFUSALS,
    ROW_KEYS,
    TABLES,
    Env,
    digest,
    hosts_of,
    packages_of,
    problem_400,
    rows_of,
)
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

CSV_URL = "/api/v1/packages/search.csv"
JSON_URL = "/api/v1/packages/search"
DOCUMENT_FILE = Path(__file__).resolve().parents[1] / "openapi.json"
HEADER_LINE = {
    None: "name,version,architecture,status,agent_id,hostname",
    "package": "name,version,architecture,host_count",
    "host": "agent_id,hostname,package_count",
}
SHAPE_KEYS = {None: ROW_KEYS, "package": PKG_KEYS, "host": HOST_KEYS}
SHAPES = (None, "package", "host")
TS_HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "content-security-policy": "default-src 'self'; frame-ancestors 'none';"
    " object-src 'none'; base-uri 'none'; form-action 'self'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
BOM = b"\xef\xbb\xbf"

# ------------------------------------------------- the formula-trigger host
#
# Each name with the CSV field it must become (written by hand from TS §6.3
# L1142, #84 (c)/(d) and the TASK-111 r1 ruling, not from any code).
CSV_TAG = "csvx"
CSV_HOSTNAME = "=cmd|' /C calc'!A0"
CSV_HOST_FIELD = "'=cmd|' /C calc'!A0"
WEIRD_STATUS = "-weird status"
WEIRD_PKG = ("status-pkg", "1.0", "all")
CSV_NAMES: dict[str, str] = {
    "-x": "'-x",
    "+x": "'+x",
    "@x": "'@x",
    "=x": "'=x",
    "\tx": "'\tx",
    "\rx": '"\'\rx"',
    " =x": "' =x",
    "  @x": "'  @x",
    "\u00a0-x": "'\u00a0-x",
    " \tx": "' \tx",
    "\n-x": '"\'\n-x"',
    "-1,2": '"\'-1,2"',
    "x,y": '"x,y"',
    'a"b': '"a""b"',
    "cr\r\nlf": '"cr\r\nlf"',
    "'=x": "'=x",
    "a=b": "a=b",
    "x\t=": "x\t=",
    "plain-csv": "plain-csv",
}
CSV_HOST = pf._host(
    "csvx",
    CSV_HOSTNAME,
    "online",
    pf.U24,
    [CSV_TAG],
    [((n, "1.0", "all"), pf.INSTALLED) for n in CSV_NAMES]
    + [(WEIRD_PKG, WEIRD_STATUS)],
    base=False,
)
_FLEET_HOSTS = pf.hosts


def _hosts_with_csv_host() -> list[pf.Host]:
    return [*_FLEET_HOSTS(), CSV_HOST]


# ------------------------------------------------------------------ fixtures


@dataclass
class CsvEnv(Env):
    db: AppDatabase | None = None

    def csv(self, token: str | None, **params: Any) -> Any:
        return self.get(token, CSV_URL, **params)

    def csv_ok(self, token: str, **params: Any) -> bytes:
        r = self.csv(token, **params)
        assert r.status_code == 200, (r.status_code, r.text[:300])
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        body: bytes = r.content
        assert not body.startswith(BOM)
        body.decode("utf-8", errors="strict")
        return body

    def walk_shape(
        self, token: str, group_by: str | None, **params: Any
    ) -> list[dict[str, Any]]:
        g = {"group_by": group_by} if group_by else {}
        return self.walk(token, 500, **params, **g)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("pkgcsv")) as s:
        yield s


@pytest.fixture(scope="module")
def fleet(server: PgServer) -> pf.Fleet:
    with mock.patch.object(pf, "hosts", _hosts_with_csv_host):
        built = pf.build(server)
    assert built.hosts["csvx"].hostname == CSV_HOSTNAME
    return built


@pytest.fixture(scope="module")
def env(server: PgServer, fleet: pf.Fleet) -> Iterator[CsvEnv]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(server.dsn("bitscan_app")), max_size=4, connect_timeout_s=5
    )
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    client = TestClient(create_app(rt, webui=WebUi()), raise_server_exceptions=False)
    e = CsvEnv(server, clock, client, fleet, db=db)
    yield e
    client.close()
    db.close()


@pytest.fixture
def viewer(env: CsvEnv) -> str:
    """A fresh viewer API token per test: each has its own 600-per-minute budget."""
    return env.user("viewer")


# ------------------------------------------------------------------ oracle


def oracle_field(cell: str) -> str:
    """TS §6.3 L1142 prefix first, then RFC 4180: a field holding a comma, a
    double quote, CR or LF is quoted and its quotes doubled (#84 (c), (d))."""
    escaped = oracle_escape(cell)
    if any(c in escaped for c in ',"\r\n'):
        return '"' + escaped.replace('"', '""') + '"'
    return escaped


def as_text(value: Any) -> str:
    """A JSON value as a CSV cell: strings as they are, counts in decimal."""
    if isinstance(value, bool):
        raise AssertionError("no boolean field in any shape")
    if isinstance(value, int):
        return str(value)
    assert isinstance(value, str), value
    return value


def oracle_csv(group_by: str | None, items: list[dict[str, Any]]) -> bytes:
    keys = SHAPE_KEYS[group_by]
    lines = [list(keys)] + [[as_text(i[k]) for k in keys] for i in items]
    text = "".join(",".join(oracle_field(c) for c in line) + "\r\n" for line in lines)
    return text.encode("utf-8")


def records(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body.decode("utf-8"), newline="")))


# ------------------------------------------------------------ CHK-M5-150

FILTER_SETS: list[tuple[dict[str, str], pf.Want]] = [
    ({}, pf.Want()),
    ({"status": "any"}, pf.Want(statuses=None)),
    ({"tag": CSV_TAG, "status": "any"}, pf.Want(tag=CSV_TAG, statuses=None)),
    ({"q": "ssl", "os": "ubuntu"}, pf.Want(q="ssl", os_id="ubuntu")),
    ({"host": "WEB"}, pf.Want(host="WEB")),
    ({"name": pf.FORMULA}, pf.Want(name=pf.FORMULA)),
    (
        {"version": "1.0", "version_op": "ge", "arch": "amd64"},
        pf.Want(version="1.0", version_op="ge", arch="amd64"),
    ),
    (
        {"os": "ubuntu:22.04", "tag": "db", "status": "any"},
        pf.Want(os_id="ubuntu", os_version_id="22.04", tag="db", statuses=None),
    ),
    ({"name": "pkg-tilde"}, pf.Want(name="pkg-tilde")),
]
ORACLE = {None: rows_of, "package": packages_of, "host": hosts_of}


@pytest.mark.parametrize("group_by", SHAPES)
@pytest.mark.parametrize(
    ("params", "want"), FILTER_SETS, ids=[str(p) for p, _ in FILTER_SETS]
)
def test_csv_rows_equal_the_json_pages_in_order(
    env: CsvEnv,
    viewer: str,
    params: dict[str, str],
    want: pf.Want,
    group_by: str | None,
) -> None:
    items = env.walk_shape(viewer, group_by, **params)
    # The JSON pages are the fleet oracle (TASK-113), so the CSV is checked
    # against both the API's JSON and the independent fleet description.
    assert items == ORACLE[group_by](env.fleet, want)
    assert items, "every filter set is chosen to match something"
    g = {"group_by": group_by} if group_by else {}
    body = env.csv_ok(viewer, **params, **g)
    assert body == oracle_csv(group_by, items)
    parsed = records(body)
    assert len(parsed) == len(items) + 1
    for item, rec in zip(items, parsed[1:], strict=True):
        assert rec == [oracle_escape(as_text(item[k])) for k in SHAPE_KEYS[group_by]]
        if "agent_id" in item:
            assert rec[SHAPE_KEYS[group_by].index("agent_id")] == str(
                UUID(item["agent_id"])
            )  # lower-case hyphenated, as in JSON


def test_hostile_and_long_text_is_kept_byte_for_byte(env: CsvEnv, viewer: str) -> None:
    body = env.csv_ok(viewer, host="<", group_by="host").decode("utf-8")
    assert pf.SCRIPT in body and pf.IMG in body  # never HTML-escaped
    assert "&lt;" not in body
    long = env.csv_ok(viewer, name=pf.LONG_NAME).decode("utf-8")
    assert long.count(pf.LONG_NAME) == len(
        rows_of(env.fleet, pf.Want(name=pf.LONG_NAME))
    )
    assert pf.LONG_HOST in long


# ------------------------------------------------------------ CHK-M5-151


@pytest.mark.parametrize("group_by", SHAPES)
def test_header_row_is_the_json_field_names_in_ts_order(
    env: CsvEnv, viewer: str, group_by: str | None
) -> None:
    g = {"group_by": group_by} if group_by else {}
    body = env.csv_ok(viewer, status="any", **g)
    first = body.split(b"\r\n", 1)[0].decode()
    assert first == HEADER_LINE[group_by]
    assert first.split(",") == SHAPE_KEYS[group_by]
    assert service.CSV_HEADERS[group_by or "rows"] == tuple(SHAPE_KEYS[group_by])


# ------------------------------------------------------------ CHK-M5-152


def test_hyperlink_name_comes_out_prefixed_and_quoted(env: CsvEnv, viewer: str) -> None:
    body = env.csv_ok(viewer, name=pf.FORMULA)
    lines = body.split(b"\r\n")
    assert lines[-1] == b""
    data = lines[1:-1]
    assert len(data) == len(rows_of(env.fleet, pf.Want(name=pf.FORMULA))) == 2
    for line in data:
        assert line.startswith(
            b'"\'=HYPERLINK(""http://x"")",1.0,amd64,install ok installed,'
        ), line
    # One host of the two is named <img ...=alert(1)>: no trigger, not quoted.
    assert any(line.endswith(b"," + pf.IMG.encode()) for line in data)


def test_every_trigger_name_and_the_hostname_are_escaped(
    env: CsvEnv, viewer: str
) -> None:
    agent = str(env.fleet.agent_ids["csvx"])
    body = env.csv_ok(viewer, tag=CSV_TAG, status="any").decode("utf-8")
    want = (
        "".join(
            f"{field},1.0,all,install ok installed,{agent},{CSV_HOST_FIELD}\r\n"
            for name, field in CSV_NAMES.items()
        )
        + f"status-pkg,1.0,all,'{WEIRD_STATUS},{agent},{CSV_HOST_FIELD}\r\n"
    )
    got_lines = body[len(HEADER_LINE[None]) + 2 :]
    assert body.startswith(HEADER_LINE[None] + "\r\n")
    # Order is the database's name order; compare as a multiset of records,
    # and the exact bytes against the JSON order below.
    assert sorted(records(got_lines.encode())) == sorted(records(want.encode()))
    items = env.walk_shape(viewer, None, tag=CSV_TAG, status="any")
    assert body.encode() == oracle_csv(None, items)
    hosts = env.csv_ok(viewer, tag=CSV_TAG, status="any", group_by="host")
    assert (
        hosts
        == (
            f"agent_id,hostname,package_count\r\n{agent},{CSV_HOST_FIELD},"
            f"{len(CSV_NAMES) + 1}\r\n"
        ).encode()
    )


def test_line_ends_are_crlf_and_there_is_no_bom(env: CsvEnv, viewer: str) -> None:
    body = env.csv_ok(viewer, status="any")
    assert not body.startswith(BOM)
    assert body.endswith(b"\r\n")
    # Outside quoted fields every LF follows a CR: strip the quoted fields
    # (records() parses them) and re-check the record separators.
    parsed = records(body)
    assert len(parsed) == len(rows_of(env.fleet, pf.Want(statuses=None))) + 1
    unquoted = body.decode("utf-8")
    inside = False
    for i, c in enumerate(unquoted):
        if c == '"':
            inside = not inside
        elif c == "\n" and not inside:
            assert unquoted[i - 1] == "\r", unquoted[max(0, i - 20) : i + 1]


# ------------------------------------------------------------ CHK-M5-153


class FakeStore:
    """An ExportStore that records every call; stream records when called."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls: list[tuple[Any, ...]] = []

    def count_capped(self, f: Any, shape: str, cap: int) -> int:
        self.calls.append(("count", shape, cap))
        return min(len(self.items), cap + 1)

    def stream(self, f: Any, shape: str) -> Iterator[Any]:
        self.calls.append(("stream", shape))
        return iter(list(self.items))


def _items(shape: str, n: int) -> list[Any]:
    a = UUID("0f8fad5b-d9cb-469f-a165-70867728950e")
    if shape == "rows":
        return [PackageRow(i, f"p{i}", "1.0", "amd64", "s", a, "h") for i in range(n)]
    if shape == "package":
        return [PackageGroup(i, f"p{i}", "1.0", "amd64", 1) for i in range(n)]
    return [HostGroup(a, f"h{i}", 1) for i in range(n)]


@pytest.mark.parametrize(
    ("group_by", "shape"), [(None, "rows"), ("package", "package"), ("host", "host")]
)
@pytest.mark.parametrize("cap", [1, 3, 7])
def test_at_the_cap_exports_and_one_over_refuses_before_reading(
    group_by: str | None, shape: str, cap: int
) -> None:
    query = parse_search({"group_by": group_by} if group_by else {})
    at = FakeStore(_items(shape, cap))
    text = service.export_csv(at, query, cap)
    assert at.calls == [("count", shape, cap), ("stream", shape)]
    assert text.count("\r\n") == cap + 1
    over = FakeStore(_items(shape, cap + 1))
    with pytest.raises(service.TooManyRows):
        service.export_csv(over, query, cap)
    assert over.calls == [("count", shape, cap)]  # stream never called


def test_the_cap_is_100000_data_rows_by_default() -> None:
    assert service.CSV_MAX_ROWS == 100_000
    default = inspect.signature(service.export_csv).parameters["cap"].default
    assert default == service.CSV_MAX_ROWS
    query = parse_search({})
    store = FakeStore(_items("rows", 2))
    service.export_csv(store, query)
    assert store.calls[0] == ("count", "rows", 100_000)


@pytest.mark.parametrize("group_by", SHAPES)
def test_real_repository_counts_and_caps_every_shape(
    env: CsvEnv, group_by: str | None
) -> None:
    """count_capped and export_csv on PostgreSQL with a small cap, every shape
    (the API test below reaches the real 100,000 for rows and packages)."""
    assert env.db is not None
    params = {"status": "any"} | ({"group_by": group_by} if group_by else {})
    query = parse_search(params)
    n = len(ORACLE[group_by](env.fleet, pf.Want(statuses=None)))
    assert n > 5
    shape = query.shape()
    with env.db.transaction() as tx:
        repo = PackageSearchRepo(tx.conn)
        repo.read_only_snapshot()
        for cap in (1, n - 1, n, n + 1, 10 * n):
            assert repo.count_capped(query.filter, shape, cap) == min(n, cap + 1)
        assert service.export_csv(repo, query, n).count("\r\n") >= n + 1
        with pytest.raises(service.TooManyRows):
            service.export_csv(repo, query, n - 1)


def _add_big_rows(env: CsvEnv, agent: UUID, first: int, last: int) -> None:
    with env.server.connect("bitscan_app") as c:
        c.execute(
            "INSERT INTO package (name, version, architecture)"
            " SELECT 'zz-big-' || lpad(g::text, 6, '0'), '1.0', 'amd64'"
            " FROM generate_series(%s::int, %s::int) g",
            (first, last),
        )
        c.execute(
            "INSERT INTO agent_package (agent_id, package_id, status,"
            " first_seen_at, last_seen_at)"
            " SELECT %s, package_id, 'install ok installed', now(), now()"
            " FROM package WHERE name LIKE 'zz-big-%%'"
            " AND package_id NOT IN"
            " (SELECT package_id FROM agent_package WHERE agent_id = %s)",
            (agent, agent),
        )


def test_the_api_exports_100000_rows_and_refuses_100001(
    env: CsvEnv, viewer: str
) -> None:
    with env.server.connect("bitscan_app") as c:
        row = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, enrolled_at) VALUES"
            " (%s, 'zz-big', '0.5.0', %s, %s, %s, 'online', %s) RETURNING agent_id",
            (
                secrets.token_hex(16),
                secrets.token_hex(32),
                T0,
                T0 + timedelta(days=9),
                T0,
            ),
        ).fetchone()
        assert row is not None
        agent = UUID(str(row[0]))
    try:
        _add_big_rows(env, agent, 1, 100_000)
        body = env.csv_ok(viewer, host="zz-big")
        want = (
            HEADER_LINE[None]
            + "\r\n"
            + "".join(
                f"zz-big-{i:06d},1.0,amd64,install ok installed,{agent},zz-big\r\n"
                for i in range(1, 100_001)
            )
        )
        assert body == want.encode()  # exactly 100,000 data rows, in order
        groups = env.csv_ok(viewer, host="zz-big", group_by="package")
        assert groups.count(b"\r\n") == 100_001
        assert groups.endswith(b"zz-big-100000,1.0,amd64,1\r\n")

        _add_big_rows(env, agent, 100_001, 100_001)
        for g in ({}, {"group_by": "package"}):
            r = env.csv(viewer, host="zz-big", **g)
            assert r.status_code == 400, (r.status_code, r.content[:200])
            assert r.headers["content-type"].startswith("application/problem+json")
            assert "content-disposition" not in r.headers
            problem = r.json()
            assert problem["type"] == "invalid_request"
            assert problem["status"] == 400
            assert "zz-big" not in r.text
            assert b"name,version" not in r.content and b"agent_id," not in r.content
            for k, v in TS_HEADERS.items():
                assert r.headers[k] == v
        # The JSON route is not capped: it still pages the 100,001 rows.
        last = env.ok(viewer, host="zz-big", limit=1)
        assert last["next_cursor"] is not None
    finally:
        with env.server.connect("bitscan_app") as c:
            c.execute("DELETE FROM agent_package WHERE agent_id = %s", (agent,))
            c.execute(
                "UPDATE agent SET status = 'decommissioned' WHERE agent_id = %s",
                (agent,),
            )
        with env.server.connect("bitscan_retention") as c:
            c.execute("DELETE FROM package WHERE name LIKE 'zz-big-%%'")


# ------------------------------------------------------------ CHK-M5-154


def test_response_headers_are_exactly_the_84_ones(env: CsvEnv, viewer: str) -> None:
    r = env.csv(viewer, name="openssl")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="packages.csv"'
    assert r.headers.get_list("content-disposition") == [
        'attachment; filename="packages.csv"'
    ]
    for k, v in TS_HEADERS.items():
        assert r.headers.get_list(k) == [v], k
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]
    pre = env.client.options(
        CSV_URL,
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert not [h for h in pre.headers if h.lower().startswith("access-control-")]


# ------------------------------------------------------------ CHK-M5-155


def test_limit_and_cursor_are_ignored(env: CsvEnv, viewer: str) -> None:
    json_cursor = env.ok(viewer, status="any", limit=1)["next_cursor"]
    assert json_cursor
    base = env.csv_ok(viewer, status="any")
    assert len(records(base)) > 60
    for extra in (
        {"limit": "1"},
        {"limit": "0"},
        {"limit": "501"},
        {"limit": "abc"},
        {"cursor": "garbage"},
        {"cursor": json_cursor},
        {"limit": "1", "cursor": json_cursor},
        {"unknown": "x"},
    ):
        assert env.csv_ok(viewer, status="any", **extra) == base, extra


# ------------------------------------------------------------ CHK-M5-156


@pytest.mark.parametrize(
    ("params", "named"), REFUSALS, ids=[str(p) for p, _ in REFUSALS]
)
def test_each_search_refusal_is_a_400_problem_on_the_csv_route(
    env: CsvEnv, viewer: str, params: dict[str, str], named: tuple[str, ...]
) -> None:
    for shape in ({}, {"group_by": "package"}, {"group_by": "host"}):
        if "group_by" in params:
            shape = {}
        r = env.csv(viewer, **(shape | params))
        problem_400(r, *named)
        assert "content-disposition" not in r.headers


@pytest.mark.parametrize(
    "param", ["q", "name", "version", "arch", "os", "tag", "host", "agent_id"]
)
def test_a_refused_value_is_never_echoed(env: CsvEnv, viewer: str, param: str) -> None:
    value = {
        "version": "1.0 " + CANARY,
        "os": CANARY + ":" + CANARY,
        "agent_id": CANARY,
    }.get(param, CANARY * 12)
    r = env.csv(viewer, **{param: value})
    problem_400(r, param)
    assert CANARY[:12] not in r.text


@pytest.mark.parametrize("param", ["q", "name", "version", "host"])
def test_nul_is_400_never_500(env: CsvEnv, viewer: str, param: str) -> None:
    value = "1.0\x00" if param == "version" else "abc\x00"
    problem_400(env.csv(viewer, **{param: value}), param)


# ------------------------------------------------------------ CHK-M5-157


def test_token_groups(env: CsvEnv) -> None:
    bsa = new_agent_token(AgentTokenKind.AGENT)
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    for tok in (None, bsa, bse, "garbage", "bsu_" + "A" * 43, "bsk_" + "A" * 43):
        r = env.csv(tok, name="openssl")
        assert r.status_code == 401, (tok and tok[:4], r.status_code)
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["type"] == "unauthorized"
        assert "content-disposition" not in r.headers
        assert b"name,version" not in r.content
    for role in ("viewer", "operator", "admin"):
        for kind in ("api", "session"):
            body = env.csv_ok(env.user(role, kind), name="openssl")
            assert body.startswith(HEADER_LINE[None].encode() + b"\r\n")


def test_restricted_admin_session_gets_403(env: CsvEnv) -> None:
    r = env.csv(env.user("admin", "session", totp=False), name="openssl")
    assert r.status_code == 403
    assert r.json()["type"] == "totp_enrolment_required"
    assert b"name,version" not in r.content


def test_a_stored_valid_agent_token_is_refused(env: CsvEnv) -> None:
    """A bsa_ that the agent routes accept (its hash is stored, sent with the
    host's machine-id header) gets 401 here, also when the agent's path id is
    sent as an (ignored) query parameter: the full agent credential set."""
    tok = new_agent_token(AgentTokenKind.AGENT)
    agent = env.fleet.agent_ids["u2410"]
    with env.conn() as c:
        row = c.execute(
            "UPDATE agent SET token_hash = %s WHERE agent_id = %s RETURNING machine_id",
            (token_hash(tok), agent),
        ).fetchone()
        assert row is not None
    creds = {"Authorization": f"Bearer {tok}", "X-Bitscan-Machine-Id": str(row[0])}
    pull = env.client.get(f"/api/v1/agent/{agent}/jobs", headers=creds)
    assert pull.status_code != 401, "the token must be valid on the agent routes"
    for params in ({"name": "openssl", "id": str(agent)}, {"name": "openssl"}):
        r = env.client.get(CSV_URL, headers=creds, params=params)
        assert r.status_code == 401, (params, r.status_code)
        assert r.json()["type"] == "unauthorized"
        assert b"openssl" not in r.content


# ------------------------------------------------------------ CHK-M5-158


def test_exports_write_nothing(env: CsvEnv) -> None:
    token = env.user("viewer")
    before = digest(env)
    calls: list[dict[str, str]] = [
        {},
        {"status": "any"},
        {"group_by": "package", "status": "any"},
        {"group_by": "host"},
        {"q": "ab"},
        {"name": pf.FORMULA},
        {"tag": CSV_TAG, "status": "any"},
        {"version": "a1"},
    ]
    for i in range(24):
        env.csv(token, **calls[i % len(calls)])
    after = digest(env)
    # user_token.last_used_at may move on use (M2); everything else is fixed.
    assert {k: v for k, v in after.items() if k != "user_token"} == {
        k: v for k, v in before.items() if k != "user_token"
    }
    assert set(before) == set(TABLES)


def test_an_export_counts_as_one_request_of_the_600(env: CsvEnv) -> None:
    token = env.user("viewer")
    env.clock.at += timedelta(minutes=5)
    statuses = [
        env.get(token, JSON_URL, agent_id=str(uuid4())).status_code for _ in range(599)
    ]
    assert statuses == [200] * 599
    assert env.csv(token, status="any").status_code == 200  # the 600th
    r = env.csv(token, status="any")
    assert r.status_code == 429
    assert r.json()["type"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert b"name,version" not in r.content
    assert env.get(token, JSON_URL).status_code == 429  # one shared budget
    env.clock.at += timedelta(minutes=1, seconds=1)
    assert env.csv(token).status_code == 200


# ------------------------------------------------------------ CHK-M5-159


def test_the_document_gives_the_200_as_text_csv_only(env: CsvEnv) -> None:
    doc = create_app(webui=WebUi()).openapi()
    op = doc["paths"][CSV_URL]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert set(params) == {
        "q",
        "name",
        "version",
        "version_op",
        "arch",
        "status",
        "os",
        "tag",
        "host",
        "agent_id",
        "group_by",
    }  # no limit or cursor (#84 (a))
    assert all(p["in"] == "query" and not p.get("required") for p in params.values())
    ok = op["responses"]["200"]
    assert ok["content"] == {"text/csv": {"schema": {"type": "string"}}}
    for code in ("400", "401", "403", "429", "503"):
        assert list(op["responses"][code]["content"]) == ["application/problem+json"]
    assert "422" not in op["responses"]
    stored = json.loads(DOCUMENT_FILE.read_text(encoding="utf-8"))
    assert stored["paths"][CSV_URL] == doc["paths"][CSV_URL]


# ------------------------------------------------------------ CHK-M5-160


@pytest.mark.parametrize("group_by", SHAPES)
def test_an_empty_result_is_the_header_row_only(
    env: CsvEnv, viewer: str, group_by: str | None
) -> None:
    g = {"group_by": group_by} if group_by else {}
    for params in (
        {"name": "nope"},
        {"agent_id": str(uuid4())},
        {"agent_id": str(env.fleet.agent_ids["decom"])},
        {"name": "decom-only"},
    ):
        body = env.csv_ok(viewer, **params, **g)
        assert body == (HEADER_LINE[group_by] + "\r\n").encode(), params


def test_restored_state_after_cap_test(env: CsvEnv) -> None:
    """Guard for the cap test: its host is decommissioned and its packages
    are gone, so no other test's oracle sees them."""
    assert env.ok(env.user("viewer"), host="zz-big", status="any")["items"] == []
