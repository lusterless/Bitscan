"""TASK-076: GET /api/v1/agents, /agents/{id} and /agents/{id}/packages on
PostgreSQL (TP-M3-30).

Checks CHK-M3-275 to CHK-M3-278 of tests/m3/test-plan.md. Expected values come
from the spec and the answers, not from the code: TS §6.2 L1108-L1110 (viewer;
hosts with status, OS, last heartbeat and inventory; host detail; per-host
packages, paginated), TS §7.3 L1225 (the host page shows os_info and the
latest snapshot's added and removed), TS §6.3 L1134 (cursor pagination,
limit up to 500), L1139 (RFC 3339 UTC), L1141 (stored text rendered as text),
TS §7.2 (Debian version order), #68 (item fields, order hostname then
agent_id; packages ordered by name, architecture, version; lists are
{items, next_cursor}), #69 (last_snapshot {snapshot_id, collected_at,
package_count, added, removed} or null; items {name, version, architecture,
status}), REQ-081 (1)-(5), REQ-063 (5).
"""

import json
import math
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from bitscan_manager.api.ratelimit import RateLimiter
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

from .conftest import PgServer
from .test_contract_agent import RFC3339
from .test_totp_enrol import Cipher, Gate

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
ITEM_KEYS = [
    "agent_id",
    "hostname",
    "status",
    "agent_version",
    "os_id",
    "os_version_id",
    "os_pretty_name",
    "last_heartbeat_at",
    "last_inventory_at",
    "tags",
    "runner_helpers",
]
DETAIL_EXTRA = [
    "machine_id",
    "enrolled_at",
    "last_seen_ip",
    "token_issued_at",
    "token_expires_at",
    "token_revoked_at",
    "os_info",
    "last_snapshot",
]
OS_KEYS = [
    "os_id",
    "os_version_id",
    "os_pretty_name",
    "kernel_release",
    "architecture",
    "cpu_count",
    "memory_mb",
    "ip_addresses",
    "uptime_s",
    "raw",
    "collected_at",
]
SNAP_KEYS = ["snapshot_id", "collected_at", "package_count", "added", "removed"]
LINE_KEYS = ["name", "version", "architecture", "status"]
PKG_KEYS = [
    "name",
    "version",
    "architecture",
    "status",
    "source_name",
    "installed_size_kb",
    "first_seen_at",
    "last_seen_at",
]
SCRIPT = "<script>alert('x')</script>"


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def now(self) -> datetime:
        return self.at


@dataclass
class Host:
    agent_id: UUID
    token: str
    prev: str
    hostname: str


@dataclass
class Env:
    server: PgServer
    clock: Clock
    app: FastAPI
    db: AppDatabase
    clients: dict[str, TestClient] = field(default_factory=dict)

    def conn(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.server.dsn("bitscan_app"), autocommit=True)

    def client(self, ip: str = "10.76.0.1") -> TestClient:
        if ip not in self.clients:
            self.clients[ip] = TestClient(
                self.app, client=(ip, 1234), raise_server_exceptions=False
            )
        return self.clients[ip]

    def user(self, role: str = "viewer", kind: str = "api") -> str:
        tok = new_token(TokenKind.SESSION if kind == "session" else TokenKind.API)
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO app_user (username, password_hash, role, totp_secret_enc,"
                " totp_last_step, created_at) VALUES (%s, 'x', %s, 'enc', 1, %s)"
                " RETURNING user_id",
                (f"fl{secrets.token_hex(5)}", role, T0),
            ).fetchone()
            assert uid is not None
            c.execute(
                "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
                " expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    uid[0],
                    kind,
                    token_hash(tok),
                    kind == "session",
                    T0 + timedelta(days=30),
                    T0,
                ),
            )
        return tok

    def host(self, hostname: str | None = None, **cols: Any) -> Host:
        tok = new_agent_token(AgentTokenKind.AGENT)
        prev = new_agent_token(AgentTokenKind.AGENT)
        name = hostname or f"fl-{secrets.token_hex(4)}"
        values: dict[str, Any] = {
            "machine_id": secrets.token_hex(16),
            "hostname": name,
            "agent_version": "1.2.3",
            "token_hash": token_hash(tok),
            "token_issued_at": T0 - timedelta(days=10),
            "token_expires_at": T0 + timedelta(days=355),
            "prev_token_hash": token_hash(prev),
            "prev_token_expires_at": T0 + timedelta(minutes=5),
            "last_rotation_at": T0 - timedelta(minutes=1),
            "status": "online",
            "enrolled_at": T0 - timedelta(days=10),
            "last_heartbeat_at": T0 - timedelta(minutes=1),
            "last_seen_ip": "10.0.0.7",
            "runner_helpers": Jsonb(["capread"]),
        } | cols
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with self.conn() as c:
            row = c.execute(
                f"INSERT INTO agent ({names}) VALUES ({marks}) RETURNING agent_id",  # noqa: S608 - fixed column names
                list(values.values()),
            ).fetchone()
        assert row is not None
        return Host(UUID(str(row[0])), tok, prev, name)

    def tags(self, h: Host, *tags: str) -> None:
        with self.conn() as c:
            for t in tags:
                c.execute(
                    "INSERT INTO agent_tag (agent_id, tag) VALUES (%s, %s)",
                    (h.agent_id, t),
                )

    def os_info(self, h: Host, raw: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO os_info (agent_id, os_id, os_version_id, os_pretty_name,"
                " kernel_release, architecture, cpu_count, memory_mb, ip_addresses,"
                " uptime_s, raw, collected_at) VALUES (%s, 'ubuntu', '24.04',"
                " 'Ubuntu 24.04.1 LTS', '6.8.0-45-generic', 'x86_64', 4, 8192,"
                " %s, 3600, %s, %s)",
                (
                    h.agent_id,
                    ["10.0.0.5", "fe80::1"],
                    Jsonb(raw),
                    T0 - timedelta(minutes=3),
                ),
            )

    def package(
        self, h: Host, name: str, version: str = "1.0", arch: str = "amd64", **ap: Any
    ) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO package (name, version, architecture, source_name)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (name, version, arch, f"src-{name}"),
            )
            pid = c.execute(
                "SELECT package_id FROM package WHERE name = %s AND version = %s"
                " AND architecture = %s",
                (name, version, arch),
            ).fetchone()
            assert pid is not None
            c.execute(
                "INSERT INTO agent_package (agent_id, package_id, status,"
                " installed_size_kb, first_seen_at, last_seen_at) VALUES (%s, %s, %s,"
                " %s, %s, %s)",
                (
                    h.agent_id,
                    pid[0],
                    ap.get("status", "install ok installed"),
                    ap.get("size", 12),
                    T0 - timedelta(days=2),
                    T0 - timedelta(minutes=3),
                ),
            )

    def snapshot(
        self, h: Host, at: datetime, added: list[Any], removed: list[Any]
    ) -> int:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO inventory_snapshot (agent_id, list_sha256, package_count,"
                " added, removed, collected_at) VALUES (%s, %s, %s, %s, %s, %s)"
                " RETURNING snapshot_id",
                (h.agent_id, "a" * 64, len(added), Jsonb(added), Jsonb(removed), at),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def get(self, path: str, token: str | None, **params: Any) -> Any:
        h = {} if token is None else {"Authorization": f"Bearer {token}"}
        return self.client().get(path, headers=h, params=params)

    def walk(
        self, path: str, token: str, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        calls = 0
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            r = self.get(path, token, **params)
            calls += 1
            assert r.status_code == 200, r.text
            body = r.json()
            assert list(body) == ["items", "next_cursor"]
            assert len(body["items"]) <= limit
            items += body["items"]
            cursor = body["next_cursor"]
            if cursor is None:
                return items, calls
            assert calls < 550


@pytest.fixture
def env(migrated_db: PgServer) -> Iterator[Env]:
    clock = Clock()
    db = AppDatabase(
        SecretStr(migrated_db.dsn("bitscan_app")), max_size=6, connect_timeout_s=5
    )
    db.open()
    rt = Runtime(
        clock=clock,
        db=db,
        totp_cipher=Cipher(),
        sink_gate=Gate(),
        limits=RateLimiter(clock),
    )
    e = Env(migrated_db, clock, create_app(rt), db)
    yield e
    for c in e.clients.values():
        c.close()
    db.close()


def utc(text: str) -> datetime:
    assert RFC3339.match(text) and text.endswith("Z"), text
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def body_of(r: Any) -> Any:
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/json")
    return r.json()


def problem(r: Any, status: int, type_: str) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == type_, r.json()


# ------------------------------------------------------------ CHK-M3-275


def test_list_items_have_exactly_the_68_fields(env: Env) -> None:
    """REQ-081 (1), (2), #68: a viewer bsk_ lists hosts; each item has exactly
    the #68 keys with the stored values, timestamps RFC 3339 UTC."""
    viewer = env.user("viewer")
    h = env.host(last_inventory_at=T0 - timedelta(minutes=3))
    env.os_info(h, {"a": 1})  # the OS fields come from the host's os_info (#68)
    env.tags(h, "prod-web", "db")
    items, _ = env.walk("/api/v1/agents", viewer, 500)
    (mine,) = [i for i in items if i["agent_id"] == str(h.agent_id)]
    assert list(mine) == ITEM_KEYS
    assert mine["hostname"] == h.hostname and mine["status"] == "online"
    assert mine["agent_version"] == "1.2.3"
    assert (mine["os_id"], mine["os_version_id"], mine["os_pretty_name"]) == (
        "ubuntu",
        "24.04",
        "Ubuntu 24.04.1 LTS",
    )
    assert utc(mine["last_heartbeat_at"]) == T0 - timedelta(minutes=1)
    assert utc(mine["last_inventory_at"]) == T0 - timedelta(minutes=3)
    assert sorted(mine["tags"]) == ["db", "prod-web"]
    assert mine["runner_helpers"] == ["capread"]


def test_list_shows_every_status_and_nulls(env: Env) -> None:
    viewer = env.user("viewer")
    hosts = {
        s: env.host(status=s, last_heartbeat_at=None, runner_helpers=Jsonb([]))
        for s in ("awaiting_approval", "enrolled", "stale", "offline", "decommissioned")
    }
    items, _ = env.walk("/api/v1/agents", viewer, 500)
    by_id = {i["agent_id"]: i for i in items}
    for status, h in hosts.items():
        item = by_id[str(h.agent_id)]
        assert item["status"] == status
        assert item["last_heartbeat_at"] is None and item["os_id"] is None
        assert item["tags"] == [] and item["runner_helpers"] == []


def test_detail_has_the_item_os_info_and_latest_snapshot(env: Env) -> None:
    """REQ-081 (2), TS §7.3 L1225, #68, #69: the item keys plus the detail
    keys; os_info with raw verbatim; last_snapshot is the latest one, with
    added and removed as {name, version, architecture, status} lines."""
    viewer = env.user("viewer")
    h = env.host()
    raw = {"lsb": {"DISTRIB_ID": "Ubuntu"}, "n": [1, 2.5, None, True]}
    env.os_info(h, raw)
    line = {
        "name": "bash",
        "version": "5.2-1",
        "architecture": "amd64",
        "status": "install ok installed",
    }
    old = line | {"version": "5.1-6"}
    env.snapshot(h, T0 - timedelta(hours=7), [old], [])
    latest = env.snapshot(h, T0 - timedelta(minutes=3), [line], [old])
    d = body_of(env.get(f"/api/v1/agents/{h.agent_id}", viewer))
    assert list(d) == ITEM_KEYS + DETAIL_EXTRA
    assert d["machine_id"] and len(d["machine_id"]) == 32
    assert utc(d["enrolled_at"]) == T0 - timedelta(days=10)
    assert d["last_seen_ip"] == "10.0.0.7"
    assert utc(d["token_issued_at"]) == T0 - timedelta(days=10)
    assert utc(d["token_expires_at"]) == T0 + timedelta(days=355)
    assert d["token_revoked_at"] is None
    os_info = d["os_info"]
    assert list(os_info) == OS_KEYS
    assert os_info["raw"] == raw
    assert sorted(os_info["ip_addresses"]) == ["10.0.0.5", "fe80::1"]
    assert (os_info["cpu_count"], os_info["memory_mb"], os_info["uptime_s"]) == (
        4,
        8192,
        3600,
    )
    assert utc(os_info["collected_at"]) == T0 - timedelta(minutes=3)
    snap = d["last_snapshot"]
    assert list(snap) == SNAP_KEYS
    assert snap["snapshot_id"] == latest and isinstance(snap["snapshot_id"], int)
    assert utc(snap["collected_at"]) == T0 - timedelta(minutes=3)
    assert snap["package_count"] == 1
    assert snap["added"] == [line] and snap["removed"] == [old]
    for x in snap["added"] + snap["removed"]:
        assert list(x) == LINE_KEYS


def test_detail_without_inventory_has_nulls(env: Env) -> None:
    viewer = env.user("viewer")
    h = env.host(last_seen_ip=None)
    d = body_of(env.get(f"/api/v1/agents/{h.agent_id}", viewer))
    assert (
        d["os_info"] is None
        and d["last_snapshot"] is None
        and d["last_seen_ip"] is None
    )


def test_unknown_agent_is_404(env: Env) -> None:
    viewer = env.user("viewer")
    problem(env.get(f"/api/v1/agents/{uuid4()}", viewer), 404, "not_found")
    problem(env.get(f"/api/v1/agents/{uuid4()}/packages", viewer), 404, "not_found")
    for bad in ("not-a-uuid", "1"):
        r = env.get(f"/api/v1/agents/{bad}", viewer)
        assert r.status_code in (400, 404), r.text
        assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "who", ["none", "bsa", "bse", "viewer-session", "operator", "admin"]
)
def test_authentication_and_roles(env: Env, who: str) -> None:
    """REQ-081 (1): viewer and above read (session or API token); no token
    and agent or enrolment tokens get 401 on all three routes."""
    h = env.host()
    env.package(h, f"p{secrets.token_hex(3)}")
    tokens = {
        "none": None,
        "bsa": h.token,
        "bse": new_agent_token(AgentTokenKind.ENROLMENT),
        "viewer-session": env.user("viewer", "session"),
        "operator": env.user("operator"),
        "admin": env.user("admin"),
    }
    tok = tokens[who]
    for path in (
        "/api/v1/agents",
        f"/api/v1/agents/{h.agent_id}",
        f"/api/v1/agents/{h.agent_id}/packages",
    ):
        r = env.get(path, tok)
        if who in ("none", "bsa", "bse"):
            problem(r, 401, "unauthorized")
        else:
            body_of(r)


def test_packages_items_and_debian_order(env: Env) -> None:
    """#68, TS §7.2: package items have exactly the #68 keys; ordered by name,
    architecture, then version in Debian order (1.9 < 1.10, 1.0~rc1 < 1.0,
    an epoch sorts last)."""
    viewer = env.user("viewer")
    h = env.host()
    for v in ("1.10", "1:0.1", "1.9", "1.0", "1.0~rc1"):
        env.package(h, "zlib", v)
    env.package(h, "apt", "2.7", "arm64")
    env.package(h, "apt", "2.7", "amd64", status="deinstall ok config-files", size=None)
    items, _ = env.walk(f"/api/v1/agents/{h.agent_id}/packages", viewer, 500)
    assert [list(i) for i in items] == [PKG_KEYS] * 7
    assert [(i["name"], i["architecture"], i["version"]) for i in items] == [
        ("apt", "amd64", "2.7"),
        ("apt", "arm64", "2.7"),
        ("zlib", "amd64", "1.0~rc1"),
        ("zlib", "amd64", "1.0"),
        ("zlib", "amd64", "1.9"),
        ("zlib", "amd64", "1.10"),
        ("zlib", "amd64", "1:0.1"),
    ]
    first = items[0]
    assert first["status"] == "deinstall ok config-files"
    assert first["installed_size_kb"] is None and first["source_name"] == "src-apt"
    assert utc(first["first_seen_at"]) == T0 - timedelta(days=2)
    assert utc(first["last_seen_at"]) == T0 - timedelta(minutes=3)


@pytest.mark.parametrize("version", ["1 0", "1:", "x:1.0", "-1", "1.0-"])
def test_a_package_version_that_is_not_debian_syntax_never_breaks_the_page(
    env: Env, version: str
) -> None:
    """TS §6.3 / #48: a host's package page never answers 500. The agent
    contract (#60) accepts any version text of 1 to 255 characters, so a
    hostile or buggy agent can store a version debversion cannot parse."""
    viewer = env.user("viewer")
    h = env.host()
    env.package(h, "aaa", "1.0")
    env.package(h, "bogus", version)
    r = env.get(f"/api/v1/agents/{h.agent_id}/packages", viewer)
    assert r.status_code == 200, (r.status_code, r.text)
    names = [i["name"] for i in r.json()["items"]]
    assert sorted(names) == ["aaa", "bogus"]


# ------------------------------------------------------------ CHK-M3-276


def test_agent_paging_returns_each_once_in_order(env: Env) -> None:
    """REQ-081 (3), REQ-038 (4): walking the whole list with small limits
    returns every agent exactly once, ordered by (hostname, agent_id); hosts
    sharing a hostname are both returned."""
    mine = [env.host(f"fl-page-{secrets.token_hex(3)}") for _ in range(3)]
    twin = env.host(mine[0].hostname)
    with env.conn() as c:
        row = c.execute("SELECT count(*) FROM agent").fetchone()
    assert row is not None
    total = int(row[0])
    for limit in (max(1, math.ceil(total / 150)), 2 if total <= 300 else 50, 50):
        viewer = env.user("viewer")  # one user per walk (600 per minute each)
        items, _ = env.walk("/api/v1/agents", viewer, limit)
        ids = [i["agent_id"] for i in items]
        assert len(ids) == len(set(ids)) == total, (limit, total, len(ids))
        for h in [*mine, twin]:
            assert str(h.agent_id) in ids
        with env.conn() as c:
            want = [
                str(r[0])
                for r in c.execute(
                    "SELECT agent_id FROM agent ORDER BY hostname, agent_id"
                ).fetchall()
            ]
        assert ids == want  # #68 order, in the database's own collation


@pytest.mark.parametrize("limit", [1, 2, 50])
def test_package_paging_n_plus_one(env: Env, limit: int) -> None:
    """REQ-081 (3): N + 1 packages with limit N: each exactly once, in order,
    across pages (the cursor carries the Debian-ordered key)."""
    viewer = env.user("viewer")
    h = env.host()
    for i in range(limit + 1):
        env.package(h, "multi", f"1.{i}")  # 1.10 after 1.9: Debian order
    items, calls = env.walk(f"/api/v1/agents/{h.agent_id}/packages", viewer, limit)
    versions = [i["version"] for i in items]
    assert versions == [f"1.{i}" for i in range(limit + 1)]
    assert calls >= 2


def test_package_cursor_is_bound_to_its_agent_and_tamper_proof(env: Env) -> None:
    viewer = env.user("viewer")
    a, b = env.host(), env.host()
    for i in range(3):
        env.package(a, f"cur{i}")
        env.package(b, f"cur{i}")
    r = body_of(env.get(f"/api/v1/agents/{a.agent_id}/packages", viewer, limit=1))
    cursor = r["next_cursor"]
    assert cursor
    problem(
        env.get(
            f"/api/v1/agents/{b.agent_id}/packages", viewer, limit=1, cursor=cursor
        ),
        400,
        "invalid_request",
    )
    problem(
        env.get("/api/v1/agents", viewer, limit=1, cursor=cursor),
        400,
        "invalid_request",
    )
    flipped = cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]
    problem(
        env.get(
            f"/api/v1/agents/{a.agent_id}/packages", viewer, limit=1, cursor=flipped
        ),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize("limit", ["0", "501", "-1", "x"])
def test_limit_bounds(env: Env, limit: str) -> None:
    """TS §6.3 L1134: limit 1 to 500; anything else 400 (#48)."""
    viewer = env.user("viewer")
    problem(env.get("/api/v1/agents", viewer, limit=limit), 400, "invalid_request")


# ------------------------------------------------------------ CHK-M3-277


def test_script_values_come_back_verbatim(env: Env) -> None:
    """REQ-081 (4), TS §6.3 L1141: a <script> hostname, package name, tag and
    raw value come back unchanged as JSON strings."""
    viewer = env.user("viewer")
    h = env.host(f"{SCRIPT}-{secrets.token_hex(3)}")
    env.os_info(h, {"k": SCRIPT, SCRIPT: [SCRIPT]})
    env.package(h, SCRIPT, "1.0")
    items, _ = env.walk("/api/v1/agents", viewer, 500)
    (mine,) = [i for i in items if i["agent_id"] == str(h.agent_id)]
    assert mine["hostname"] == h.hostname
    d = body_of(env.get(f"/api/v1/agents/{h.agent_id}", viewer))
    assert d["hostname"] == h.hostname
    assert d["os_info"]["raw"] == {"k": SCRIPT, SCRIPT: [SCRIPT]}
    p = body_of(env.get(f"/api/v1/agents/{h.agent_id}/packages", viewer))
    assert [i["name"] for i in p["items"]] == [SCRIPT]


# ------------------------------------------------------------ CHK-M3-278


def test_no_response_holds_a_token_or_its_hash(env: Env) -> None:
    """REQ-081 (5), REQ-063 (5): no response of the three routes holds the
    agent's current or previous token, their hashes, or a token_hash key."""
    viewer = env.user("viewer")
    h = env.host()
    env.os_info(h, {"a": 1})
    env.package(h, "tok")
    env.snapshot(h, T0, [], [])
    texts = [
        env.get("/api/v1/agents", viewer, limit=500).text,
        env.get(f"/api/v1/agents/{h.agent_id}", viewer).text,
        env.get(f"/api/v1/agents/{h.agent_id}/packages", viewer).text,
    ]
    for text in texts:
        for secret in (
            h.token,
            h.prev,
            h.token[4:],
            token_hash(h.token),
            token_hash(h.prev),
            "token_hash",
            "prev_token",
            "last_rotation_at",
        ):
            assert secret not in text, secret


def test_openapi_has_no_token_hash_property() -> None:
    from .test_contract_agent import OPENAPI

    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    for path in (
        "/api/v1/agents",
        "/api/v1/agents/{id}",
        "/api/v1/agents/{id}/packages",
    ):
        assert set(doc["paths"][path]) >= {"get"}
        assert "422" not in doc["paths"][path]["get"]["responses"]
    for name, schema in doc["components"]["schemas"].items():
        assert not [p for p in schema.get("properties", {}) if "token_hash" in p], name
    assert "PackageItem" in doc["components"]["schemas"]
    assert "AgentPackageItem" in doc["components"]["schemas"]
