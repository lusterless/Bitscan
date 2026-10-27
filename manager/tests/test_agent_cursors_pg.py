"""TASK-131: host-list cursors carry only ids (TP-M6-07, G53; REQ-143, #89).

Checks CHK-M6-120 to CHK-M6-123 of tests/m6/test-plan.md. Expected values
come from the spec and the answers, not from the code: TS §6.3 L1134 (cursor
pagination, limit 1 to 500), TS §6.2 L1108/L1110 (hosts and per-host packages
paginated), TS §5.2 (hostname and package name VARCHAR(255); package_id
BIGSERIAL; bitscan_retention may DELETE from package), #68 (hosts ordered by
hostname then agent_id; packages by name, architecture, version), TS §7.2 and
TASK-053 r1 (version in Debian order, then as text), #89 and REQ-143 (each
cursor holds only the last row's id; a vanished or foreign anchor is 400
invalid_request, never 500; a cursor is at most 512 characters whatever the
stored text), #48 (cursor errors are 400 invalid_request).

The module runs on a database of its own (own_migrated_server) so the whole
host list is known and its order can be compared exactly. The order oracle is
the database's own collation for text (collation_rank) and the dpkg comparator
for versions (package_fleet.deb_cmp), never the route.
"""

import base64
import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cmp_to_key
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bitscan_manager.api.pagination import encode_cursor
from bitscan_manager.api.ratelimit import RateLimiter
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import TokenKind, new_token, token_hash
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.runtime import Runtime

from . import package_fleet as pf
from .conftest import PgServer, own_migrated_server
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

Conn = psycopg.Connection[Any]
T0 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
CURSOR_MAX = 512
# 255 characters, non-ASCII, each needing \\uXXXX in an ensure_ascii JSON
# cursor (6 bytes per character): the #89 failure case.
LONG_HOST = ("ü" + "主机" + "é") * 63 + "ñöß"
LONG_PKG = ("ž" + "包" + "ø") * 85
assert len(LONG_HOST) == 255 and len(LONG_PKG) == 255
BAD = "Invalid request: query.cursor"


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Env:
    server: PgServer
    app: FastAPI
    clients: list[TestClient] = field(default_factory=list)

    def conn(self, role: str = "bitscan_app") -> Conn:
        return psycopg.connect(self.server.dsn(role), autocommit=True)

    def client(self) -> TestClient:
        if not self.clients:
            self.clients.append(
                TestClient(
                    self.app, client=("10.86.0.1", 1234), raise_server_exceptions=False
                )
            )
        return self.clients[0]

    def viewer(self) -> str:
        tok = new_token(TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', 'viewer', 'enc', 1, %s)"
                " RETURNING user_id",
                (f"cur{secrets.token_hex(5)}", T0),
            ).fetchone()
            assert uid is not None
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, 'api', %s, false, %s, %s)",
                (uid[0], token_hash(tok), T0 + timedelta(days=30), T0),
            )
        return tok

    def host(self, hostname: str) -> UUID:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
                " token_issued_at, token_expires_at, status, enrolled_at)"
                " VALUES (%s, %s, '0.1.0-1', %s, %s, %s, 'online', %s)"
                " RETURNING agent_id",
                (
                    secrets.token_hex(16),
                    hostname,
                    secrets.token_hex(32),
                    T0 - timedelta(days=1),
                    T0 + timedelta(days=364),
                    T0 - timedelta(days=1),
                ),
            ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def package(self, agent: UUID, name: str, version: str, arch: str) -> int:
        with self.conn() as c:
            c.execute(
                "INSERT INTO package (name, version, architecture) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (name, version, arch),
            )
            pid = c.execute(
                "SELECT package_id FROM package WHERE name = %s AND version = %s"
                " AND architecture = %s",
                (name, version, arch),
            ).fetchone()
            assert pid is not None
            c.execute(
                "INSERT INTO agent_package (agent_id, package_id, status,"
                " first_seen_at, last_seen_at) VALUES (%s, %s,"
                " 'install ok installed', %s, %s)",
                (agent, pid[0], T0, T0),
            )
        return int(pid[0])

    def get(self, path: str, token: str, **params: Any) -> Any:
        return self.client().get(
            path, headers={"Authorization": f"Bearer {token}"}, params=params
        )

    def walk(
        self, path: str, token: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items: list[dict[str, Any]] = []
        cursors: list[str] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor is not None:
                params["cursor"] = cursor
            r = self.get(path, token, **params)
            assert r.status_code == 200, (r.status_code, r.text, len(cursors))
            body = r.json()
            assert list(body) == ["items", "next_cursor"]
            assert len(body["items"]) <= limit
            items += body["items"]
            cursor = body["next_cursor"]
            if cursor is None:
                return items, cursors
            cursors.append(cursor)
            assert len(cursors) < 600


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("cursors")) as s:
        yield s


@pytest.fixture(scope="module")
def env(server: PgServer) -> Iterator[Env]:
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
    e = Env(server, create_app(rt))
    yield e
    for c in e.clients:
        c.close()
    db.close()


@pytest.fixture(scope="module")
def fleet(env: Env) -> list[UUID]:
    """Hosts for /agents: the long non-ASCII hostname, ASCII neighbours on
    both sides, two pairs of twins (agent_id tie-break), a hostile name."""
    names = [
        "a-first",
        LONG_HOST,
        LONG_HOST,  # twin of the long name: the tie-break on a boundary
        "m-middle",
        "m-middle",
        "<script>alert(1)</script>",
        "z-last",
        "é-accent",
        "Mixed-Case",
    ]
    return [env.host(n) for n in names]


def payload(cursor: str) -> list[Any]:
    """The cursor's signed JSON (scope, key): the MAC is 16 bytes."""
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    out = json.loads(raw[16:])
    assert isinstance(out, list)
    return out


def problem_400(r: Any) -> None:
    assert r.status_code == 400, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == "invalid_request", body
    assert body["detail"] == BAD, body


def expected_hosts(env: Env) -> list[str]:
    with env.conn() as c:
        rows = c.execute("SELECT agent_id::text, hostname FROM agent").fetchall()
        rank = pf.collation_rank(c, {h for _, h in rows})
    return [a for a, _ in sorted(rows, key=lambda r: (rank[r[1]], r[0]))]


# ------------------------------------------------------------ CHK-M6-120, -122


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 500])
def test_agents_every_item_once_in_order_with_long_hostname(
    env: Env, fleet: list[UUID], limit: int
) -> None:
    """REQ-143 (1), (2): with limit N, every host appears exactly once in the
    #68 order (hostname in the database collation, then agent_id), the long
    non-ASCII hostname lands on page boundaries for small N, and every
    cursor is at most 512 characters and holds only [agent_id]."""
    viewer = env.viewer()
    items, cursors = env.walk("/api/v1/agents", viewer, limit)
    ids = [i["agent_id"] for i in items]
    assert ids == expected_hosts(env)
    assert len(ids) == len(set(ids))
    if limit < len(ids):
        assert cursors
    for cur in cursors:
        assert len(cur) <= CURSOR_MAX, len(cur)
        scope, key = payload(cur)
        assert scope == "agents"
        assert isinstance(key, list) and len(key) == 1, key
        assert str(UUID(key[0])) == key[0]
        assert key[0] in ids
    if limit == 1:
        # each long-hostname host was the last row of a page
        long_ids = {
            str(a)
            for a, n in zip(fleet, _names(env, fleet), strict=True)
            if n == LONG_HOST
        }
        anchored = {payload(c)[1][0] for c in cursors}
        assert long_ids <= anchored


def _names(env: Env, ids: list[UUID]) -> list[str]:
    with env.conn() as c:
        got = dict(
            c.execute(
                "SELECT agent_id, hostname FROM agent WHERE agent_id = ANY(%s)", (ids,)
            ).fetchall()
        )
    return [str(got[i]) for i in ids]


def test_agents_long_hostname_comes_back_verbatim(env: Env, fleet: list[UUID]) -> None:
    viewer = env.viewer()
    items, _ = env.walk("/api/v1/agents", viewer, 1)
    assert sum(1 for i in items if i["hostname"] == LONG_HOST) == 2


# ------------------------------------------------------------ CHK-M6-121, -122


@pytest.fixture(scope="module")
def pkg_host(env: Env) -> tuple[UUID, list[tuple[str, str, str]]]:
    """One host's packages: the long non-ASCII name on boundaries, 1.0 and
    1.0-0 (equal in Debian order, different text), multi-arch, epochs."""
    agent = env.host("pkg-host")
    rows = [
        ("aa", "1.0", "amd64"),
        (LONG_PKG, "1.0", "amd64"),
        (LONG_PKG, "1.0-0", "amd64"),
        (LONG_PKG, "1.0", "i386"),
        ("multi", "1.0", "amd64"),
        ("multi", "1.0-0", "amd64"),
        ("multi", "1.0~rc1", "amd64"),
        ("multi", "1:0.1", "amd64"),
        ("multi", "1.10", "amd64"),
        ("multi", "1.9", "amd64"),
        ("multi", "1.0", "all"),
        ("zz", "2.0", "amd64"),
    ]
    for n, v, a in rows:
        env.package(agent, n, v, a)
    return agent, rows


def expected_packages(
    env: Env, rows: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    with env.conn() as c:
        rank = pf.collation_rank(c, {x for r in rows for x in (r[0], r[2], r[1])})

    def cmp(x: tuple[str, str, str], y: tuple[str, str, str]) -> int:
        for a, b in ((x[0], y[0]), (x[2], y[2])):
            if rank[a] != rank[b]:
                return -1 if rank[a] < rank[b] else 1
        d = pf.sign(pf.deb_cmp(x[1], y[1]))
        if d:
            return d
        return (rank[x[1]] > rank[y[1]]) - (rank[x[1]] < rank[y[1]])

    return sorted(rows, key=cmp_to_key(cmp))


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 500])
def test_packages_every_item_once_in_order_with_long_name(
    env: Env, pkg_host: tuple[UUID, list[tuple[str, str, str]]], limit: int
) -> None:
    agent, rows = pkg_host
    viewer = env.viewer()
    items, cursors = env.walk(f"/api/v1/agents/{agent}/packages", viewer, limit)
    got = [(i["name"], i["version"], i["architecture"]) for i in items]
    assert got == expected_packages(env, rows)
    with env.conn() as c:
        ids = {
            int(r[0])
            for r in c.execute(
                "SELECT package_id FROM agent_package WHERE agent_id = %s", (agent,)
            ).fetchall()
        }
    for cur in cursors:
        assert len(cur) <= CURSOR_MAX, len(cur)
        scope, key = payload(cur)
        assert scope == f"agent_packages:{agent}"
        assert isinstance(key, list) and len(key) == 1, key
        assert type(key[0]) is int and key[0] in ids
    if limit == 1:
        assert len(cursors) == len(rows) - 1


def test_package_removed_between_pages_paging_continues(env: Env) -> None:
    """Plan TASK-131: the anchor comes from package, so a package the agent
    no longer has (a new inventory between page loads) still anchors."""
    agent = env.host("pkg-gone-from-agent")
    for n in ("p1", "p2", "p3", "p4"):
        env.package(agent, f"rm-{n}", "1.0", "amd64")
    viewer = env.viewer()
    path = f"/api/v1/agents/{agent}/packages"
    r = env.get(path, viewer, limit=2)
    assert r.status_code == 200, r.text
    cur = r.json()["next_cursor"]
    anchor = payload(cur)[1][0]
    with env.conn() as c:
        c.execute(
            "DELETE FROM agent_package WHERE agent_id = %s AND package_id = %s",
            (agent, anchor),
        )
    r2 = env.get(path, viewer, limit=2, cursor=cur)
    assert r2.status_code == 200, r2.text
    assert [i["name"] for i in r2.json()["items"]] == ["rm-p3", "rm-p4"]


# ------------------------------------------------------------ CHK-M6-123


def test_vanished_package_anchor_is_400(env: Env) -> None:
    """REQ-143 (3): the anchor's package row deleted (as bitscan_retention,
    the M11 prune) answers 400 invalid_request, never 500."""
    agent = env.host("pkg-anchor-pruned")
    for n in ("q1", "q2", "q3"):
        env.package(agent, f"pr-{secrets.token_hex(3)}-{n}", "1.0", "amd64")
    viewer = env.viewer()
    path = f"/api/v1/agents/{agent}/packages"
    r = env.get(path, viewer, limit=1)
    cur = r.json()["next_cursor"]
    anchor = payload(cur)[1][0]
    with env.conn() as c:  # the agent first loses it (as the app may)
        c.execute(
            "DELETE FROM agent_package WHERE agent_id = %s AND package_id = %s",
            (agent, anchor),
        )
    with env.conn("bitscan_retention") as c:
        assert c.execute("SELECT session_user::text").fetchone() == (
            "bitscan_retention",
        )
        assert (
            c.execute("DELETE FROM package WHERE package_id = %s", (anchor,)).rowcount
            == 1
        )
    problem_400(env.get(path, viewer, limit=1, cursor=cur))


def test_package_cursor_of_another_agent_is_400(
    env: Env, pkg_host: tuple[UUID, list[tuple[str, str, str]]]
) -> None:
    agent, _ = pkg_host
    other = env.host("pkg-other")
    env.package(other, "aa", "1.0", "amd64")
    viewer = env.viewer()
    cur = env.get(f"/api/v1/agents/{agent}/packages", viewer, limit=1).json()[
        "next_cursor"
    ]
    problem_400(
        env.get(f"/api/v1/agents/{other}/packages", viewer, limit=1, cursor=cur)
    )
    # a package_id the other agent does hold, signed for the wrong scope
    pid = payload(cur)[1][0]
    forged = encode_cursor(f"agent_packages:{agent}", [pid])
    problem_400(
        env.get(f"/api/v1/agents/{other}/packages", viewer, limit=1, cursor=forged)
    )
    # and the /agents cursor is not a package cursor, nor the reverse
    hc = env.get("/api/v1/agents", viewer, limit=1).json()["next_cursor"]
    problem_400(env.get(f"/api/v1/agents/{agent}/packages", viewer, cursor=hc))
    problem_400(env.get("/api/v1/agents", viewer, cursor=cur))


def test_tampered_cursors_are_400(
    env: Env, fleet: list[UUID], pkg_host: tuple[UUID, list[tuple[str, str, str]]]
) -> None:
    agent, _ = pkg_host
    viewer = env.viewer()
    for path in ("/api/v1/agents", f"/api/v1/agents/{agent}/packages"):
        cur = env.get(path, viewer, limit=1).json()["next_cursor"]
        assert cur
        for bad in (
            cur[:-2] + ("A" if cur[-2] != "A" else "B") + cur[-1],
            cur[:-1],
            cur + "A",
            "A" + cur[1:] if cur[0] != "A" else "B" + cur[1:],
            "not-a-cursor",
        ):
            problem_400(env.get(path, viewer, limit=1, cursor=bad))


# Fixed ids (xdist needs the same parameter ids in every worker).
U = "3f2b8c1e-6d4a-4e7b-9a10-5c2d8e7f6a01"
AGENT_KEYS: list[Any] = [
    [],
    ["x"],
    [U.upper()],
    [U.replace("-", "")],
    ["{" + U + "}"],
    ["urn:uuid:" + U],
    [" " + U],
    [1],
    [True],
    [None],
    ["a-first", U],  # the old M3 two-element form
    "plain-string",
    7,
    [[U]],
]


@pytest.mark.parametrize("key", AGENT_KEYS, ids=lambda k: json.dumps(k)[:40])
def test_agents_cursor_with_wrong_payload_is_400(
    env: Env, fleet: list[UUID], key: Any
) -> None:
    viewer = env.viewer()
    problem_400(env.get("/api/v1/agents", viewer, cursor=encode_cursor("agents", key)))


def test_agents_cursor_naming_a_missing_agent_is_400(
    env: Env, fleet: list[UUID]
) -> None:
    """A well-formed, signed [agent_id] for no agent (bitscan_app cannot
    delete agents, so a forged one stands in for a vanished anchor)."""
    viewer = env.viewer()
    problem_400(
        env.get(
            "/api/v1/agents", viewer, cursor=encode_cursor("agents", [str(uuid4())])
        )
    )


PACKAGE_KEYS: list[Any] = [
    [],
    [-1],
    [2**63],
    [True],
    [False],
    [1.0],
    ["1"],
    [None],
    [1, 2],
    ["aa", "amd64", "1.0"],  # the old M3 three-element form
    1,
    [[1]],
]


@pytest.mark.parametrize("key", PACKAGE_KEYS, ids=lambda k: json.dumps(k)[:40])
def test_package_cursor_with_wrong_payload_is_400(
    env: Env, pkg_host: tuple[UUID, list[tuple[str, str, str]]], key: Any
) -> None:
    agent, _ = pkg_host
    viewer = env.viewer()
    cur = encode_cursor(f"agent_packages:{agent}", key)
    problem_400(env.get(f"/api/v1/agents/{agent}/packages", viewer, cursor=cur))


def test_package_cursor_for_a_missing_package_id_is_400(
    env: Env, pkg_host: tuple[UUID, list[tuple[str, str, str]]]
) -> None:
    agent, _ = pkg_host
    viewer = env.viewer()
    for pid in (0, 2**63 - 1):
        cur = encode_cursor(f"agent_packages:{agent}", [pid])
        problem_400(env.get(f"/api/v1/agents/{agent}/packages", viewer, cursor=cur))


def test_package_cursor_any_existing_package_id_anchors(
    env: Env, pkg_host: tuple[UUID, list[tuple[str, str, str]]]
) -> None:
    """A signed [package_id] of a package this agent never had still pages
    (the anchor's sort values come from package), with the remainder in
    order: the cursor's scope, not the id, binds it to the agent."""
    agent, rows = pkg_host
    other = env.host("pkg-anchor-source")
    pid = env.package(other, "m", "0", "amd64")
    viewer = env.viewer()
    cur = encode_cursor(f"agent_packages:{agent}", [pid])
    r = env.get(f"/api/v1/agents/{agent}/packages", viewer, limit=500, cursor=cur)
    assert r.status_code == 200, r.text
    with env.conn() as c:
        rank = pf.collation_rank(c, {"m", *(r[0] for r in rows)})
    # the anchor (m, amd64, 0): no row has the name m, so the rest is every
    # row whose name sorts after m in the database collation
    want = [x for x in expected_packages(env, rows) if rank[x[0]] > rank["m"]]
    assert want and len(want) < len(rows)
    got = [(i["name"], i["version"], i["architecture"]) for i in r.json()["items"]]
    assert got == want


def test_cursor_over_512_characters_is_400(env: Env, fleet: list[UUID]) -> None:
    viewer = env.viewer()
    r = env.get("/api/v1/agents", viewer, cursor="A" * 513)
    assert r.status_code == 400, r.text
    assert r.json()["type"] == "invalid_request"
