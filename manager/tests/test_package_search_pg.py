"""TASK-113: GET /api/v1/packages/search on PostgreSQL (TP-M5-06).

Checks CHK-M5-120 to CHK-M5-134 of tests/m5/test-plan.md through create_app()
with a real runtime, as bitscan_app, on the fixture fleet of package_fleet
(a database of this module's own). Expected values: TS §6.2 L1117 (viewer),
§6 (user routes take bsu_ and bsk_ only), §6.3 L1133-L1136 (problem details,
cursor pagination 1-500 default 50, 600 per minute per user), §7.1 (the
parameters and the three shapes), REQ-113 to REQ-115, #48 (400
invalid_request), #83 (b) (order; cursor bound to the filters and group_by),
#88, #89 (cursors hold ids), REQ-038 (2) (no value echoed).
"""

import hashlib
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from bitscan_manager.api.pagination import encode_cursor
from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.api.webui import WebUi
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import (
    AgentTokenKind,
    TokenKind,
    new_agent_token,
    new_token,
    token_hash,
)
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime
from bitscan_manager.services.packages import parse_search

from . import package_fleet as pf
from .conftest import PgServer, own_migrated_server
from .test_inventory_ingest import T0, Clock
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

URL = "/api/v1/packages/search"
CANARY = "CANARY-" + secrets.token_hex(8)
ROW_KEYS = ["name", "version", "architecture", "status", "agent_id", "hostname"]
PKG_KEYS = ["name", "version", "architecture", "host_count"]
HOST_KEYS = ["agent_id", "hostname", "package_count"]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("pkgapi")) as s:
        yield s


@pytest.fixture(scope="module")
def fleet(server: PgServer) -> pf.Fleet:
    return pf.build(server)


@dataclass
class Env:
    server: PgServer
    clock: Clock
    client: TestClient
    fleet: pf.Fleet
    tokens: dict[str, str] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return self.server.connect("bitscan_app")

    def user(self, role: str = "viewer", kind: str = "api", totp: bool = True) -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', %s, %s, %s, %s)"
                " RETURNING user_id",
                (
                    f"ps{secrets.token_hex(5)}",
                    role,
                    "enc" if totp else None,
                    1 if totp else None,
                    T0,
                ),
            ).fetchone()
            assert uid is not None
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uid[0],
                    kind,
                    token_hash(tok),
                    kind == "session" and totp,
                    T0 + timedelta(days=30),
                    T0,
                ),
            )
        return tok

    def get(self, token: str | None, path: str = URL, **params: Any) -> Any:
        h = {} if token is None else {"Authorization": f"Bearer {token}"}
        return self.client.get(path, headers=h, params=params)

    def ok(self, token: str, **params: Any) -> dict[str, Any]:
        r = self.get(token, **params)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.headers["content-type"].startswith("application/json")
        body: dict[str, Any] = r.json()
        assert list(body) == ["items", "next_cursor"]
        return body

    def walk(self, token: str, limit: int, **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(2000):
            extra: dict[str, str] = {"cursor": cursor} if cursor else {}
            body = self.ok(token, limit=limit, **params, **extra)
            assert len(body["items"]) <= limit
            items += body["items"]
            cursor = body["next_cursor"]
            if cursor is None:
                return items
            assert len(cursor) <= 512
        raise AssertionError("paging did not end")


@pytest.fixture(scope="module")
def env(server: PgServer, fleet: pf.Fleet) -> Iterator[Env]:
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
    e = Env(server, clock, client, fleet)
    yield e
    client.close()
    db.close()


@pytest.fixture
def viewer(env: Env) -> str:
    """A fresh viewer API token per test: each has its own 600-per-minute budget."""
    return env.user("viewer")


def problem_400(r: Any, *params: str) -> dict[str, Any]:
    assert r.status_code == 400, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == "invalid_request"
    assert body["status"] == 400
    for p in params:
        assert f"query.{p}" in body["detail"], body
    return body


def rows_of(fleet: pf.Fleet, w: pf.Want) -> list[dict[str, Any]]:
    return [
        {
            "name": n,
            "version": v,
            "architecture": a,
            "status": s,
            "agent_id": str(aid),
            "hostname": h,
        }
        for _, n, v, a, s, aid, h in pf.want_rows(fleet, w)
    ]


def packages_of(fleet: pf.Fleet, w: pf.Want) -> list[dict[str, Any]]:
    return [
        {"name": n, "version": v, "architecture": a, "host_count": c}
        for _, n, v, a, c in pf.want_packages(fleet, w)
    ]


def hosts_of(fleet: pf.Fleet, w: pf.Want) -> list[dict[str, Any]]:
    return [
        {"agent_id": str(a), "hostname": h, "package_count": c}
        for a, h, c in pf.want_hosts(fleet, w)
    ]


# ------------------------------------------------------------ CHK-M5-120

REFUSALS: list[tuple[dict[str, str], tuple[str, ...]]] = [
    ({"q": "ab"}, ("q",)),
    ({"q": "abc", "name": "abc"}, ("name", "q")),
    ({"version_op": "lt"}, ("version",)),
    ({"version_op": "ne", "version": "1.0"}, ("version_op",)),
    ({"version_op": "LT", "version": "1.0"}, ("version_op",)),
    ({"status": "removed"}, ("status",)),
    ({"group_by": "name"}, ("group_by",)),
    ({"os": ":24.04"}, ("os",)),
    ({"os": "ubuntu:"}, ("os",)),
    ({"os": "a:b:c"}, ("os",)),
    ({"agent_id": "not-a-uuid"}, ("agent_id",)),
    ({"agent_id": "{0f8fad5b-d9cb-469f-a165-70867728950e}"}, ("agent_id",)),
    ({"agent_id": "0f8fad5bd9cb469fa16570867728950e"}, ("agent_id",)),
    ({"name": ""}, ("name",)),
    ({"host": ""}, ("host",)),
    ({"q": ""}, ("q",)),
    ({"tag": ""}, ("tag",)),
    ({"agent_id": ""}, ("agent_id",)),
    ({"group_by": ""}, ("group_by",)),
    ({"status": ""}, ("status",)),
    ({"version": "1.0 beta"}, ("version",)),
    ({"version": "a1", "version_op": "ge"}, ("version",)),
    ({"q": "x" * 256}, ("q",)),
    ({"name": "x" * 256}, ("name",)),
    ({"version": "1" + "0" * 255}, ("version",)),
    ({"host": "x" * 256}, ("host",)),
    ({"arch": "x" * 17}, ("arch",)),
    ({"tag": "x" * 65}, ("tag",)),
    ({"os": "u" * 33 + ":" + "1" * 16}, ("os",)),
]


@pytest.mark.parametrize(
    ("params", "named"), REFUSALS, ids=[str(p) for p, _ in REFUSALS]
)
def test_each_refusal_is_a_400_problem_naming_the_parameter(
    env: Env, viewer: str, params: dict[str, str], named: tuple[str, ...]
) -> None:
    for shape in ({}, {"group_by": "package"}, {"group_by": "host"}):
        if "group_by" in params:
            shape = {}
        problem_400(env.get(viewer, **(shape | params)), *named)


@pytest.mark.parametrize("param", ["q", "name", "version", "arch", "os", "tag", "host"])
def test_a_value_is_never_echoed(env: Env, viewer: str, param: str) -> None:
    value = {"version": "1.0 " + CANARY, "os": CANARY + ":" + CANARY}.get(
        param, CANARY * 12
    )
    body = problem_400(env.get(viewer, **{param: value}), param)
    assert CANARY not in str(body)
    assert CANARY[:12] not in env.get(viewer, **{param: value}).text


@pytest.mark.parametrize("param", ["version_op", "status", "group_by", "agent_id"])
def test_an_enum_value_is_never_echoed(env: Env, viewer: str, param: str) -> None:
    r = env.get(viewer, **{param: CANARY, "version": "1.0"})
    problem_400(r, param)
    assert CANARY not in r.text


@pytest.mark.parametrize("param", ["q", "name", "host", "tag", "arch", "os", "version"])
def test_at_the_limit_is_accepted(env: Env, viewer: str, param: str) -> None:
    n = {"arch": 16, "tag": 64, "os": 49}.get(param, 255)
    value = {"version": "1" + "0" * (n - 1), "os": "u" * 32 + ":" + "1" * 16}.get(
        param, "é" * n
    )
    assert env.ok(viewer, **{param: value})["items"] == []


# ------------------------------------------------------------ CHK-M5-121


@pytest.mark.parametrize("limit", ["0", "501", "-1", "abc", "1.5", ""])
def test_bad_limits_are_refused(env: Env, viewer: str, limit: str) -> None:
    problem_400(env.get(viewer, limit=limit), "limit")


def test_default_limit_is_50_and_500_is_allowed(env: Env, viewer: str) -> None:
    total = len(pf.want_rows(env.fleet, pf.Want(statuses=None)))
    assert total > 60
    assert len(env.ok(viewer, status="any")["items"]) == 50
    big = env.ok(viewer, status="any", limit=500)
    assert len(big["items"]) == min(500, total)


# ------------------------------------------------------------ CHK-M5-122


def test_three_shapes_have_exactly_their_keys_and_the_oracle_items(
    env: Env, viewer: str
) -> None:
    w = pf.Want(q="ssl", os_id="ubuntu")
    rows = env.walk(viewer, 500, q="ssl", os="ubuntu")
    assert rows == rows_of(env.fleet, w)
    assert all(list(i) == ROW_KEYS for i in rows)
    pk = env.walk(viewer, 500, q="ssl", os="ubuntu", group_by="package")
    assert pk == packages_of(env.fleet, w)
    assert all(list(i) == PKG_KEYS for i in pk)
    hs = env.walk(viewer, 500, q="ssl", os="ubuntu", group_by="host")
    assert hs == hosts_of(env.fleet, w)
    assert all(list(i) == HOST_KEYS for i in hs)


@pytest.mark.parametrize(
    ("params", "want"),
    [
        ({}, pf.Want()),
        ({"status": "any"}, pf.Want(statuses=None)),
        (
            {"name": "pkg-tilde", "status": "any"},
            pf.Want(name="pkg-tilde", statuses=None),
        ),
        (
            {"version": "1.0", "version_op": "le", "name": "pkg-tilde"},
            pf.Want(version="1.0", version_op="le", name="pkg-tilde"),
        ),
        ({"arch": "i386"}, pf.Want(arch="i386")),
        (
            {"os": "ubuntu:22.04", "tag": "db"},
            pf.Want(os_id="ubuntu", os_version_id="22.04", tag="db"),
        ),
        ({"host": "WEB"}, pf.Want(host="WEB")),
        ({"q": "b_u", "status": "any"}, pf.Want(q="b_u", statuses=None)),
    ],
)
def test_filters_through_the_api_equal_the_oracle(
    env: Env, viewer: str, params: dict[str, str], want: pf.Want
) -> None:
    assert env.walk(viewer, 500, **params) == rows_of(env.fleet, want)
    assert env.walk(viewer, 500, group_by="package", **params) == packages_of(
        env.fleet, want
    )
    assert env.walk(viewer, 500, group_by="host", **params) == hosts_of(env.fleet, want)


def test_agent_id_in_either_case(env: Env, viewer: str) -> None:
    a = env.fleet.agent_ids["mail01"]
    lower = env.walk(viewer, 500, agent_id=str(a))
    upper = env.walk(viewer, 500, agent_id=str(a).upper())
    assert lower == upper == rows_of(env.fleet, pf.Want(agent_id=a))
    assert all(i["agent_id"] == str(a) for i in lower)


# ------------------------------------------------------------ CHK-M5-123


@pytest.mark.parametrize("n", [1, 2, 7])
@pytest.mark.parametrize("group_by", [None, "package", "host"])
def test_paging_n_plus_one_returns_each_item_once_in_order(
    env: Env, n: int, group_by: str | None
) -> None:
    token = env.user("viewer")
    params = {"status": "any"} | ({"group_by": group_by} if group_by else {})
    full = env.walk(token, 500, **params)
    want = {None: rows_of, "package": packages_of, "host": hosts_of}[group_by](
        env.fleet, pf.Want(statuses=None)
    )
    assert full == want
    assert env.walk(token, n, **params) == want


def test_long_non_ascii_names_on_a_boundary_page_and_cursors_stay_short(
    env: Env, viewer: str
) -> None:
    lengths = set()
    for params in ({"name": pf.LONG_NAME}, {"host": "ホ"}, {"q": "üüü"}):
        for group_by in (None, "package", "host"):
            p = params | ({"group_by": group_by} if group_by else {})
            cursor = None
            seen = []
            for _ in range(50):
                body = env.ok(
                    viewer, limit=1, **p, **({"cursor": cursor} if cursor else {})
                )
                seen += body["items"]
                cursor = body["next_cursor"]
                if cursor is None:
                    break
                lengths.add(len(cursor))
            assert len({str(i) for i in seen}) == len(seen)
    assert lengths and max(lengths) < 200  # ids only, never the 255-character text


def test_equal_debian_versions_page_once(env: Env, viewer: str) -> None:
    groups = env.walk(
        viewer, 1, name="pkg-tilde", arch="amd64", status="any", group_by="package"
    )
    assert [g["version"] for g in groups] == [
        "1.0~rc1",
        "1.0",
        "1.0-0",
        "1.0+b1",
        "2.0",
        "1:0.5",
    ]


# ------------------------------------------------------------ CHK-M5-124


def first_cursor(env: Env, token: str, **params: Any) -> str:
    body = env.ok(token, limit=1, **params)
    assert body["next_cursor"]
    return str(body["next_cursor"])


@pytest.mark.parametrize(
    "change",
    [
        {"q": "lib"},
        {"name": "bash"},
        {"version": "1.0"},
        {"version": "1.0", "version_op": "ge"},
        {"arch": "amd64"},
        {"status": "any"},
        {"os": "ubuntu"},
        {"os": "ubuntu:24.04"},
        {"tag": "db"},
        {"host": "-"},
    ],
)
def test_a_cursor_reused_with_one_filter_changed_is_refused(
    env: Env, viewer: str, change: dict[str, str]
) -> None:
    base = {"status": "any"} if "status" not in change else {}
    cursor = first_cursor(env, viewer, **base)
    problem_400(env.get(viewer, limit=1, cursor=cursor, **base, **change), "cursor")
    assert env.get(viewer, limit=1, cursor=cursor, **base).status_code == 200


def test_a_cursor_reused_with_agent_id_or_group_by_changed_is_refused(
    env: Env, viewer: str
) -> None:
    a = str(env.fleet.agent_ids["web01"])
    cursor = first_cursor(env, viewer, agent_id=a)
    other = str(env.fleet.agent_ids["web02"])
    problem_400(env.get(viewer, limit=1, cursor=cursor, agent_id=other), "cursor")
    problem_400(
        env.get(viewer, limit=1, cursor=cursor, agent_id=a, group_by="package"),
        "cursor",
    )
    pc = first_cursor(env, viewer, group_by="package")
    problem_400(env.get(viewer, limit=1, cursor=pc, group_by="host"), "cursor")
    problem_400(env.get(viewer, limit=1, cursor=pc), "cursor")
    hc = first_cursor(env, viewer, group_by="host")
    problem_400(env.get(viewer, limit=1, cursor=hc, group_by="package"), "cursor")


def test_a_cursor_from_another_route_is_refused(env: Env, viewer: str) -> None:
    r = env.get(viewer, "/api/v1/agents", limit=1)
    assert r.status_code == 200
    agents_cursor = r.json()["next_cursor"]
    assert agents_cursor
    problem_400(env.get(viewer, limit=1, cursor=agents_cursor), "cursor")


@pytest.mark.parametrize(
    "how", ["flip", "truncate", "append", "pad", "garbage", "long"]
)
def test_a_tampered_cursor_is_refused(env: Env, viewer: str, how: str) -> None:
    c = first_cursor(env, viewer)
    bad = {
        "flip": c[:-3] + ("A" if c[-3] != "A" else "B") + c[-2:],
        "truncate": c[:-4],
        "append": c + "A",
        "pad": c + "==",
        "garbage": "not-a-cursor",
        "long": "A" * 513,
    }[how]
    problem_400(env.get(viewer, limit=1, cursor=bad), "cursor")


@pytest.mark.parametrize(
    ("group_by", "key"),
    [
        (None, [True, "0f8fad5b-d9cb-469f-a165-70867728950e"]),
        (None, [1, "nope"]),
        (None, [1]),
        (None, ["1", "0f8fad5b-d9cb-469f-a165-70867728950e"]),
        ("package", [True]),
        ("package", ["1"]),
        ("package", [1.5]),
        ("package", [1, 2]),
        ("host", ["nope"]),
        ("host", [1]),
        ("host", []),
        (None, "x"),
    ],
)
def test_a_well_signed_cursor_with_a_wrong_key_shape_is_400_not_500(
    env: Env, viewer: str, group_by: str | None, key: Any
) -> None:
    params = {"group_by": group_by} if group_by else {}
    raw = {k: v for k, v in params.items()}
    scope = parse_search(raw | {"status": "installed"}).cursor_scope()
    cursor = encode_cursor(scope, key)
    problem_400(env.get(viewer, limit=1, cursor=cursor, **params), "cursor")


def test_a_cursor_whose_anchor_was_removed_is_refused(env: Env, viewer: str) -> None:
    """The anchor package is removed between pages (bitscan_app removes the
    agent_package rows, bitscan_retention the package, as retention would). A
    dedicated host and package are used and removed or decommissioned after."""
    with env.server.connect("bitscan_app") as c:
        agent = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status, enrolled_at) VALUES"
            " (%s, 'zz-anchor', '0.5.0', %s, %s, %s, 'online', %s) RETURNING agent_id",
            (
                secrets.token_hex(16),
                secrets.token_hex(32),
                T0,
                T0 + timedelta(days=9),
                T0,
            ),
        ).fetchone()
        assert agent is not None
        ids = []
        for v in ("1.0", "2.0", "3.0"):
            pid = c.execute(
                "INSERT INTO package (name, version, architecture) VALUES"
                " ('zz-anchor-pkg', %s, 'amd64') RETURNING package_id",
                (v,),
            ).fetchone()
            assert pid is not None
            ids.append(pid[0])
            c.execute(
                "INSERT INTO agent_package (agent_id, package_id, status,"
                " first_seen_at, last_seen_at)"
                " VALUES (%s, %s, 'install ok installed', now(), now())",
                (agent[0], pid[0]),
            )
    try:
        rc = first_cursor(env, viewer, name="zz-anchor-pkg")
        pc = first_cursor(env, viewer, name="zz-anchor-pkg", group_by="package")
        with env.server.connect("bitscan_app") as c:
            c.execute("DELETE FROM agent_package WHERE package_id = %s", (ids[0],))
        with env.server.connect("bitscan_retention") as c:
            c.execute("DELETE FROM package WHERE package_id = %s", (ids[0],))
        problem_400(env.get(viewer, limit=1, cursor=rc, name="zz-anchor-pkg"), "cursor")
        problem_400(
            env.get(
                viewer, limit=1, cursor=pc, name="zz-anchor-pkg", group_by="package"
            ),
            "cursor",
        )
    finally:
        with env.server.connect("bitscan_app") as c:
            c.execute("DELETE FROM agent_package WHERE agent_id = %s", (agent[0],))
            c.execute(
                "UPDATE agent SET status = 'decommissioned' WHERE agent_id = %s",
                (agent[0],),
            )
        with env.server.connect("bitscan_retention") as c:
            c.execute("DELETE FROM package WHERE name = 'zz-anchor-pkg'")


# ------------------------------------------------------------ CHK-M5-125


def test_empty_result_is_exactly_items_empty_and_null(env: Env, viewer: str) -> None:
    for params in (
        {"name": "nope"},
        {"agent_id": str(uuid4())},
        {"agent_id": str(env.fleet.agent_ids["decom"])},
    ):
        for g in (None, "package", "host"):
            r = env.get(viewer, **params, **({"group_by": g} if g else {}))
            assert r.status_code == 200
            assert r.json() == {"items": [], "next_cursor": None}


def test_last_page_has_a_null_cursor(env: Env, viewer: str) -> None:
    n = len(rows_of(env.fleet, pf.Want(name="pkg-tilde")))
    body = env.ok(viewer, name="pkg-tilde", limit=n)
    assert len(body["items"]) == n and body["next_cursor"] is None
    body = env.ok(viewer, name="pkg-tilde", limit=n - 1)
    assert body["next_cursor"] is not None


# ------------------------------------------------------------ CHK-M5-126


def test_token_groups(env: Env) -> None:
    bsa = new_agent_token(AgentTokenKind.AGENT)
    bse = new_agent_token(AgentTokenKind.ENROLMENT)
    for tok in (None, bsa, bse, "garbage", "bsu_" + "A" * 43, "bsk_" + "A" * 43):
        r = env.get(tok, name="openssl")
        assert r.status_code == 401, (tok and tok[:4], r.status_code)
        assert r.json()["type"] == "unauthorized"
        assert "openssl" not in r.text
    for role in ("viewer", "operator", "admin"):
        for kind in ("api", "session"):
            assert env.get(env.user(role, kind), name="openssl").status_code == 200


def test_restricted_admin_session_gets_403(env: Env) -> None:
    tok = env.user("admin", "session", totp=False)
    r = env.get(tok, name="openssl")
    assert r.status_code == 403
    assert r.json()["type"] == "totp_enrolment_required"


def test_a_real_agent_token_is_refused(env: Env) -> None:
    """A bsa_ that is valid on the agent routes (stored hash) still gets 401."""
    tok = new_agent_token(AgentTokenKind.AGENT)
    with env.conn() as c:
        c.execute(
            "UPDATE agent SET token_hash = %s WHERE agent_id = %s",
            (token_hash(tok), env.fleet.agent_ids["u2410"]),
        )
    assert env.get(tok).status_code == 401


# ------------------------------------------------------------ CHK-M5-127


def test_hostile_names_come_back_verbatim(env: Env, viewer: str) -> None:
    for name in (pf.SCRIPT, pf.IMG, pf.FORMULA, pf.LONG_NAME, pf.INJ[0]):
        items = env.walk(viewer, 500, name=name)
        assert items and {i["name"] for i in items} == {name}
    hosts = {i["hostname"] for i in env.walk(viewer, 500, host="<", group_by="host")}
    assert hosts == {pf.SCRIPT, pf.IMG}
    raw = env.get(viewer, name=pf.SCRIPT).content
    assert b"<script>" in raw or b"\\u003cscript" in raw


# ------------------------------------------------------------ CHK-M5-128

TABLES = (
    "package",
    "agent_package",
    "agent",
    "agent_tag",
    "os_info",
    "inventory_snapshot",
    "audit_log",
    "scan_job",
    "user_token",
    "app_user",
)


def digest(env: Env) -> dict[str, str]:
    out = {}
    with env.conn() as c:
        for t in TABLES:
            rows = c.execute(
                sql.SQL("SELECT to_jsonb(x)::text FROM {} x ORDER BY 1").format(
                    sql.Identifier(t)
                )
            ).fetchall()
            out[t] = hashlib.sha256("\n".join(r[0] for r in rows).encode()).hexdigest()
    return out


def test_fifty_searches_write_nothing(env: Env) -> None:
    token = env.user("viewer")
    before = digest(env)
    calls = [
        {"q": "ssl"},
        {"group_by": "package"},
        {"group_by": "host", "status": "any"},
        {"q": "ab"},
        {"name": "openssl", "version": "1.0", "version_op": "gt"},
        {"limit": "0"},
        {"cursor": "garbage"},
        {"host": "web"},
        {"os": "ubuntu"},
        {"agent_id": str(uuid4())},
    ]
    for i in range(50):
        env.get(token, **calls[i % len(calls)])
    after = digest(env)
    # user_token.last_used_at may move on use (M2); everything else is fixed.
    assert {k: v for k, v in after.items() if k != "user_token"} == {
        k: v for k, v in before.items() if k != "user_token"
    }


# ------------------------------------------------------------ CHK-M5-129


def test_the_601st_request_in_a_minute_is_429(env: Env) -> None:
    token = env.user("viewer")
    env.clock.at += timedelta(minutes=5)
    statuses = [env.get(token, agent_id=str(uuid4())).status_code for _ in range(600)]
    assert statuses == [200] * 600
    r = env.get(token, agent_id=str(uuid4()))
    assert r.status_code == 429
    assert r.json()["type"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    env.clock.at += timedelta(minutes=1, seconds=1)
    assert env.get(token, agent_id=str(uuid4())).status_code == 200


# ------------------------------------------------------------ CHK-M5-130 / -131 / -132


@pytest.mark.parametrize(
    "value", ["%_\\'\";--", "a' OR '1'='1", "') OR TRUE --", "%(q)s", "%s%", "$1;"]
)
def test_injection_text_is_literal_through_the_api(
    env: Env, viewer: str, value: str
) -> None:
    assert env.walk(viewer, 500, q=value, status="any") == rows_of(
        env.fleet, pf.Want(q=value, statuses=None)
    )
    assert env.walk(viewer, 500, host=value, group_by="host") == hosts_of(
        env.fleet, pf.Want(host=value)
    )


def test_host_underscore_is_literal(env: Env, viewer: str) -> None:
    hosts = env.walk(viewer, 500, host="_", group_by="host")
    assert [h["hostname"] for h in hosts] == ["build_box"]


@pytest.mark.parametrize(
    "version", ["1.0 beta", "a1", "1:", "1.0-", "1:a1", "x:1.0", "~1"]
)
@pytest.mark.parametrize("op", [None, "lt", "eq", "gt"])
def test_an_invalid_version_is_400_never_500(
    env: Env, viewer: str, version: str, op: str | None
) -> None:
    params = {"version": version} | ({"version_op": op} if op else {})
    problem_400(env.get(viewer, **params), "version")


@pytest.mark.parametrize(
    "param", ["q", "name", "version", "arch", "os", "tag", "host", "agent_id"]
)
def test_nul_in_any_text_parameter_is_400_never_500(
    env: Env, viewer: str, param: str
) -> None:
    value = {"version": "1.0\x00", "os": "ubuntu\x00", "agent_id": "\x00" * 36}.get(
        param, "abc\x00"
    )
    r = env.get(viewer, **{param: value})
    problem_400(r, param)


# ------------------------------------------------------------ CHK-M5-133


def test_the_document_declares_the_route(env: Env) -> None:
    doc = create_app(webui=WebUi()).openapi()
    op = doc["paths"][URL]["get"]
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
        "limit",
        "cursor",
    }
    assert all(p["in"] == "query" and not p.get("required") for p in params.values())
    text = str(params)
    for n in ("lt", "le", "eq", "ge", "gt", "installed", "any", "package", "host"):
        assert f"'{n}'" in text
    assert set(op["responses"]) >= {"200", "400", "401", "403", "429", "503"}
    ok = str(op["responses"]["200"])
    for comp in ("PackageRowItem", "PackageGroupItem", "HostGroupItem"):
        assert comp in ok or comp in str(doc["components"]["schemas"])
    for comp, keys in (
        ("PackageRowItem", ROW_KEYS),
        ("PackageGroupItem", PKG_KEYS),
        ("HostGroupItem", HOST_KEYS),
    ):
        assert list(doc["components"]["schemas"][comp]["properties"]) == keys


def test_restored_state_after_anchor_test(env: Env) -> None:
    """Guard for the anchor test: its host is decommissioned and its packages
    are gone, so no other test's oracle sees them."""
    assert env.ok(env.user("viewer"), name="zz-anchor-pkg", status="any")["items"] == []
