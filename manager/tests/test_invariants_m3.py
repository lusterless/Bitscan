"""TP-M3-35 (G34): the M3 pull-only and mandatory-inventory invariants.

Checks CHK-M3-300 and CHK-M3-305 of tests/m3/test-plan.md, and the G34 halves
of the mutation rows CHK-M3-345, -352, -353 and -374. No database: these run on
the Windows box (L) and in CI.

Expected values come from the spec, not from the code: TS §6.1 L1060-L1067 and
§6.2 L1093-L1127 (the route tables), §6.2 L1129 ("deliberately no endpoint to
disable inventory collection or to run an ad-hoc command"), §2.2 L111 and
§3.3 L210-L213 (pull only: the manager never opens a connection to an agent),
§3.4 L230 (inventory cannot be disabled in the UI, API or agent config), §6.5
L1163 (the heartbeat response is exactly three keys), §8.6 L1319-L1327 (the
seven runtime settings and their ranges), #70 (GET /api/v1/metrics) and
REQ-088 (1)-(4).
"""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.api.agent import schemas
from bitscan_manager.app import create_app
from bitscan_manager.services.settings import (
    INT_RANGES,
    KEYS,
    SettingsInvalid,
    validate_patch,
)

from .test_auth_dependencies import api_routes

PKG = Path(__file__).resolve().parents[1] / "bitscan_manager"
V1 = "/api/v1"


def _crud(path: str) -> set[tuple[str, str]]:
    """TS §6.2 "CRUD": create and list on the collection; read, replace,
    update and delete on one item."""
    item = path + "/{}"
    return {("GET", path), ("POST", path)} | {
        (m, item) for m in ("GET", "PUT", "PATCH", "DELETE")
    }


# TS §6.1 L1062-L1067: exactly these six agent operations.
AGENT_OPS = {
    ("POST", V1 + "/agent/enroll"),
    ("POST", V1 + "/agent/{}/heartbeat"),
    ("GET", V1 + "/agent/{}/jobs"),
    ("POST", V1 + "/agent/{}/jobs/{}/results"),
    ("PUT", V1 + "/agent/{}/inventory"),
    ("POST", V1 + "/agent/{}/token/rotate"),
}
# TS §6.2 L1095-L1127, every milestone (later milestones add routes from here).
USER_OPS = {
    (m, V1 + p)
    for m, p in [
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/totp/enrol"),
        ("POST", "/auth/password"),
        ("POST", "/api-tokens"),
        ("GET", "/api-tokens"),
        ("DELETE", "/api-tokens"),
        ("DELETE", "/api-tokens/{}"),
        ("GET", "/policies"),
        ("GET", "/policies/{}"),
        ("PATCH", "/policies/{}"),
        ("POST", "/policies/import"),
        ("DELETE", "/policies/{}"),
        ("POST", "/policies/rebuild"),
        ("GET", "/tasks/{}"),
        ("GET", "/imports"),
        ("GET", "/agents"),
        ("GET", "/agents/{}"),
        ("GET", "/agents/{}/packages"),
        ("GET", "/agents/{}/scans"),
        ("PUT", "/agents/{}/tags"),
        ("POST", "/agents/{}/revoke"),
        ("GET", "/enrollment-requests"),
        ("POST", "/enrollment-requests/{}/approve"),
        ("POST", "/enrollment-requests/{}/reject"),
        ("GET", "/packages/search"),
        ("GET", "/packages/search.csv"),
        ("GET", "/scans"),
        ("POST", "/scans"),
        ("GET", "/scans/{}"),
        ("GET", "/scans/{}/results"),
        ("GET", "/scans/{}/results.csv"),
        ("POST", "/scans/{}/cancel"),
        ("POST", "/scans/{}/reevaluate"),
        ("GET", "/settings"),
        ("PATCH", "/settings"),
        ("GET", "/audit-log"),
        ("GET", "/metrics"),  # #70
    ]
}
USER_OPS |= _crud(V1 + "/enrollment-tokens")
USER_OPS |= _crud(V1 + "/scan-schedules")
USER_OPS |= _crud(V1 + "/users")
HEALTH_OPS = {("GET", "/healthz"), ("GET", "/readyz")}  # #5
# M5 (REQ-118, REQ-088 (1) as changed for M5; #6 M5 half, decisions 2026-10-24):
# the built web UI, served without a token and not in the OpenAPI document.
STATIC_OPS = {("GET", "/"), ("GET", "/assets/{}")}
SPEC_OPS = AGENT_OPS | USER_OPS | HEALTH_OPS | STATIC_OPS
# TS §7.1 L1198-L1210: the package search parameters (REQ-113).
SEARCH_PARAMS = {"q", "name", "version", "version_op", "arch", "status", "os",
                 "tag", "host", "agent_id", "group_by"}  # fmt: skip
PACKAGE_PATHS = {V1 + "/packages/search", V1 + "/packages/search.csv"}

# The M3 head (REQ-062 to REQ-086): the operations that must exist now.
M3_USER_OPS = {
    (m, V1 + p)
    for m, p in [
        ("GET", "/agents"),
        ("GET", "/agents/{}"),
        ("GET", "/agents/{}/packages"),
        ("PUT", "/agents/{}/tags"),
        ("POST", "/agents/{}/revoke"),
        ("GET", "/enrollment-requests"),
        ("POST", "/enrollment-requests/{}/approve"),
        ("POST", "/enrollment-requests/{}/reject"),
        ("GET", "/enrollment-tokens"),
        ("POST", "/enrollment-tokens"),
        ("GET", "/enrollment-tokens/{}"),
        ("DELETE", "/enrollment-tokens/{}"),
        ("GET", "/settings"),
        ("PATCH", "/settings"),
        ("GET", "/audit-log"),
        ("GET", "/metrics"),
        # M5 (REQ-113, REQ-116)
        ("GET", "/packages/search"),
        ("GET", "/packages/search.csv"),
    ]
}

BANNED_FIELDS = {"command", "commands", "cmd", "script", "execute", "plugins", "shell"}
# a query parameter or setting that could switch inventory off or skip it
INVENTORY_SWITCH = re2.compile(r"(?i)inventor|disable|enable|skip|pause|suspend")
HEARTBEAT_KEYS = {"job_pull_seconds", "max_parallel_plugins", "server_time"}
SPEC_SETTINGS = {
    "agent_token_ttl_days",
    "job_pull_seconds",
    "decommission_after_days",
    "redaction_patterns",
    "max_parallel_plugins",
    "enrolment_alert_per_hour",
    "inventory_interval_s",
}


def norm(path: str) -> str:
    return str(re2.sub(r"\{[^}]+\}", "{}", path))


def operations(app: Any) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in api_routes(app.routes):
        for method in route.methods or ():
            if method in ("HEAD", "OPTIONS"):
                continue
            out.add((method, norm(route.path)))
    return out


def spec_violations(ops: set[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(ops - SPEC_OPS)


# ------------------------------------------------------------ CHK-M3-300


def test_every_operation_is_a_spec_route() -> None:
    """REQ-088 (1): each operation of create_app() is a TS §6.1 or §6.2 route,
    a health route or the #70 metrics route; nothing else."""
    ops = operations(create_app())
    assert spec_violations(ops) == []
    assert M3_USER_OPS <= ops, M3_USER_OPS - ops  # the walk sees the real routes


def test_exactly_the_six_agent_operations() -> None:
    """REQ-062 (1): exactly the six TS §6.1 operations under /api/v1/agent/."""
    ops = operations(create_app())
    agent = {op for op in ops if op[1].startswith(V1 + "/agent/")}
    assert agent == AGENT_OPS


def test_the_documented_operations_are_the_app_operations() -> None:
    """The OpenAPI document lists the same operations as the route walk, so
    the schema checks below see every request body."""
    app = create_app()
    doc = app.openapi()
    documented = {
        (method.upper(), norm(path))
        for path, ops in doc["paths"].items()
        for method in ops
    }
    # The two static UI routes are the only operations not in the document.
    assert STATIC_OPS <= operations(app)
    assert documented == operations(app) - STATIC_OPS


def test_the_static_routes_take_no_input_but_the_file_name() -> None:
    """REQ-088 (1) as changed for M5: GET / and GET /assets/{name} read no
    query parameter, header, cookie or body; the only input is the path
    segment `name`, which is a dictionary key (REQ-118)."""
    static = [
        r for r in api_routes(create_app().routes) if r.path in ("/", "/assets/{name}")
    ]
    assert sorted((r.path, sorted(r.methods)) for r in static) == [
        ("/", ["GET"]),
        ("/assets/{name}", ["GET"]),
    ]
    for r in static:
        d = r.dependant
        assert d.query_params == [] and d.header_params == [], r.path
        assert d.cookie_params == [] and d.body_params == [], r.path
        assert d.dependencies == [], r.path
        assert [p.name for p in d.path_params] == (["name"] if r.path != "/" else [])


def schema_properties(doc: dict[str, Any], schema: Any) -> Iterator[str]:
    """Every property name reachable from a schema ($ref, combinators, items,
    additionalProperties and nested properties), each component once."""
    seen: set[str] = set()
    stack = [schema]
    comps = doc.get("components", {}).get("schemas", {})
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                stack.append(comps[name])
        for key, value in node.get("properties", {}).items():
            yield key
            stack.append(value)
        for key in ("items", "additionalProperties", "anyOf", "oneOf", "allOf"):
            if key in node:
                stack.append(node[key])
        if "$defs" in node:
            stack.extend(node["$defs"].values())


def request_fields(doc: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            names: set[str] = set()
            for media in op.get("requestBody", {}).get("content", {}).values():
                names |= set(schema_properties(doc, media.get("schema", {})))
            out[(method.upper(), path)] = names
    return out


def test_no_request_schema_carries_a_command() -> None:
    """REQ-088 (1), TS §6.2 L1129: no request body anywhere has a command,
    script, execute or plugins field (the Job's own `execute` and `plugins`
    are response fields, sent only by the manager)."""
    doc = create_app().openapi()
    fields = request_fields(doc)
    assert any(fields.values())  # bodies were found and walked
    assert "results" in fields[("POST", V1 + "/agent/{id}/jobs/{job_id}/results")]
    assert "stdout" in fields[("POST", V1 + "/agent/{id}/jobs/{job_id}/results")]
    hits = {op: sorted(names & BANNED_FIELDS) for op, names in fields.items()}
    assert {op: h for op, h in hits.items() if h} == {}


def test_no_query_parameter_can_switch_inventory_off() -> None:
    """REQ-088 (2): no query parameter disables or skips inventory. The only
    query parameters in M3 are paging, the request state filter and the
    inventory upload's job_id."""
    doc = create_app().openapi()
    params = {
        (method.upper(), path, p["name"])
        for path, ops in doc["paths"].items()
        for method, op in ops.items()
        for p in op.get("parameters", [])
        if p.get("in") == "query"
    }
    assert ("PUT", V1 + "/agent/{id}/inventory", "job_id") in params
    names = {name for _, path, name in params if path not in PACKAGE_PATHS}
    assert names <= {"limit", "cursor", "state", "job_id"}, names
    # M5: the two package routes take exactly the TS §7.1 filters; the JSON
    # route also pages, the CSV export does not (#84 (a)).
    search = {n for _, p, n in params if p == V1 + "/packages/search"}
    csv = {n for _, p, n in params if p == V1 + "/packages/search.csv"}
    assert search == SEARCH_PARAMS | {"limit", "cursor"}
    assert csv == SEARCH_PARAMS
    assert [p for p in params if INVENTORY_SWITCH.search(p[2])] == []


def test_settings_have_no_inventory_switch() -> None:
    """REQ-088 (2), TS §3.4 L230, §8.6: exactly the seven TS §8.6 keys; the
    only inventory key is its interval, bounded 3,600-86,400 s."""
    assert set(KEYS) == SPEC_SETTINGS
    assert [k for k in KEYS if INVENTORY_SWITCH.search(k)] == ["inventory_interval_s"]
    assert INT_RANGES["inventory_interval_s"] == (3600, 86400)
    doc = create_app().openapi()
    patch = doc["components"]["schemas"]["SettingsPatch"]
    assert set(patch["properties"]) == SPEC_SETTINGS
    assert patch.get("additionalProperties") is False
    ranged = patch["properties"]["inventory_interval_s"]
    bounds = [s for s in ranged.get("anyOf", [ranged]) if s.get("type") == "integer"]
    assert [(b["minimum"], b["maximum"]) for b in bounds] == [(3600, 86400)]


@pytest.mark.parametrize(
    "patch",
    [
        {"inventory_enabled": False},
        {"inventory_enabled": True},
        {"inventory_disabled": True},
        {"skip_inventory": True},
        {"inventory_interval_s": 0},
        {"inventory_interval_s": 3599},
        {"inventory_interval_s": 86401},
        {"inventory_interval_s": None},
        {"job_pull_seconds": 300, "inventory_enabled": False},
    ],
)
def test_no_setting_disables_inventory(patch: dict[str, Any]) -> None:
    """REQ-088 (2): the service refuses every switch and out-of-range
    interval, as a whole patch."""
    with pytest.raises(SettingsInvalid):
        validate_patch(patch)


def test_the_interval_bounds_are_accepted() -> None:
    """Control for the refusals above: the bounds themselves pass."""
    for value in (3600, 86400):
        assert validate_patch({"inventory_interval_s": value}) == {
            "inventory_interval_s": value
        }


def string_constants(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_no_code_reads_an_inventory_switch() -> None:
    """REQ-088 (2) (CHK-M3-352, "honoured by the inventory run"): no module of
    the manager names a setting that would turn inventory off."""
    switch = re2.compile(
        r"(?i)inventory_(enabled|disabled|paused|off)|(disable|skip|pause)_inventory"
    )
    hits = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text in string_constants(tree):
            # re2 needs encodable text; a lone surrogate literal (M5 query.py
            # checks for them) is replaced, never skipped.
            text = text.encode("utf-8", "replace").decode("utf-8")
            if switch.search(text):
                hits.append((path.relative_to(PKG).as_posix(), text[:60]))
        for node in ast.walk(tree):
            name = getattr(node, "attr", None) or getattr(node, "id", None)
            if isinstance(name, str) and switch.search(name):
                hits.append((path.relative_to(PKG).as_posix(), name))
    assert hits == []


# ------------------------------------------------------- REQ-088 (4), CHK-M3-345


def test_the_heartbeat_response_is_only_configuration() -> None:
    """TS §3.3 L202, §6.5 L1163: exactly three keys, nothing else allowed."""
    assert set(schemas.HeartbeatResponse.model_fields) == HEARTBEAT_KEYS
    doc = create_app().openapi()
    resp = doc["components"]["schemas"]["HeartbeatResponse"]
    assert set(resp["properties"]) == HEARTBEAT_KEYS
    assert set(resp["required"]) == HEARTBEAT_KEYS
    assert resp.get("additionalProperties") is False
    op = doc["paths"][V1 + "/agent/{id}/heartbeat"]["post"]
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/HeartbeatResponse"}


# ------------------------------------------------------------ CHK-M3-305

# REQ-088 (3): the five packages that serve agents or schedule their work.
CLIENT_FREE = ["agents", "enrolment", "jobs", "scheduler", "inventory"]
BANNED_MODULES = (
    "httpx",
    "requests",
    "urllib.request",
    "urllib3",
    "http.client",
    "socket",
    "aiohttp",
    "websockets",
    "paramiko",
    "asyncssh",
    "pycurl",
)
BANNED_CALLS = {"wrap_socket", "open_connection", "create_connection", "urlopen"}


def banned(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in BANNED_MODULES)


def client_uses(source: str) -> list[str]:
    """Every import, dynamic import or call that opens a network connection."""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if banned(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if banned(node.module):
                found.append(node.module)
            found += [
                f"{node.module}.{a.name}"
                for a in node.names
                if banned(f"{node.module}.{a.name}")
            ]
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in BANNED_CALLS:
                found.append(str(name))
            if name in ("__import__", "import_module") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if banned(arg.value):
                        found.append(arg.value)
    return sorted(set(found))


def test_no_network_client_in_the_agent_facing_services() -> None:
    """REQ-088 (3), TS §2.2 L111: the manager never opens a connection to an
    agent; no HTTP or raw-socket client in the five service packages."""
    files = []
    hits: dict[str, list[str]] = {}
    for pkg in CLIENT_FREE:
        mods = sorted((PKG / "services" / pkg).rglob("*.py"))
        assert len(mods) >= 2, pkg  # the package exists and has its modules
        for path in mods:
            files.append(path)
            uses = client_uses(path.read_text(encoding="utf-8"))
            if uses:
                hits[path.relative_to(PKG).as_posix()] = uses
    assert hits == {}
    assert any(p.name == "heartbeat.py" for p in files)


@pytest.mark.parametrize(
    ("source", "want"),
    [
        ("import httpx\n", ["httpx"]),
        ("def f():\n    import httpx\n    httpx.post('https://h')\n", ["httpx"]),
        ("from http import client\n", ["http.client"]),
        ("from http.client import HTTPSConnection\n", ["http.client"]),
        ("import urllib.request\n", ["urllib.request"]),
        ("from urllib import request\n", ["urllib.request"]),
        ("import socket as s\n", ["socket"]),
        ("import ssl\nssl.wrap_socket(x)\n", ["wrap_socket"]),
        ("import asyncio\nasyncio.open_connection('h', 1)\n", ["open_connection"]),
        ("__import__('requests')\n", ["requests"]),
        ("import importlib\nimportlib.import_module('aiohttp')\n", ["aiohttp"]),
        ("import json, hashlib\nfrom urllib.parse import quote\n", []),
    ],
)
def test_the_static_check_can_fail(source: str, want: list[str]) -> None:
    got = client_uses(source)
    assert [w for w in want if not any(w in g for g in got)] == []
    if not want:
        assert got == []


def test_the_route_walk_can_fail() -> None:
    """A planted ad-hoc command route (CHK-M3-353) and a planted inventory
    switch parameter are both seen."""
    app = create_app()

    @app.post("/api/v1/agents/{id}/run")
    def run(id: str) -> dict[str, str]:  # noqa: A002
        return {}

    @app.get("/api/v1/agents/{id}/x")
    def x(id: str, inventory: bool = True) -> dict[str, str]:  # noqa: A002
        return {}

    assert ("POST", V1 + "/agents/{}/run") in spec_violations(operations(app))
    doc = app.openapi()
    names = {
        p["name"]
        for op in doc["paths"][V1 + "/agents/{id}/x"].values()
        for p in op.get("parameters", [])
    }
    assert any(INVENTORY_SWITCH.search(n) for n in names)
