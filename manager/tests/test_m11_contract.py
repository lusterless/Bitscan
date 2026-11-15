"""TASK-232 TEST: the M11 API contract, static (CHK-M11-230 to -232, -235;
the CODE half of CHK-M11-234).

Expected values: plan TASK-232 §3, §4 (operations, parameters, models), the
lead-approved names ``ScanResultItem`` / ``ScanResultItemWithOutput``
(TASK-232 IMPL, 2026-11-08), TS §6.2 L1113, L1120, L1122, L1123, L1125 (min
roles; re-evaluation a TOTP-session admin route), L1086 (sensitive), §5.3
L1053 (sink gate), §6.3 L1136 (limit ≤ 500), L1141 (UUID ids); #144 to #147;
REQ-268 (3), REQ-273 (1), (3), (4).

The document at ``6efe0fb`` is pinned by digests (canonical JSON, sorted
keys) taken from ``git show 6efe0fb:manager/openapi.json`` on 2026-11-08, so
the check needs no git history in CI.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Match

from bitscan_manager.app import create_app

from .test_auth_dependencies import api_routes, markers

DOC = Path(__file__).resolve().parents[1] / "openapi.json"
PREFIX = "/api/v1"

# 6efe0fb: every component schema (80), and every path object with the six
# M11 operations taken out (the GET added beside the existing POST /scans).
BASE_SCHEMAS = "23f9503a3a3851e9d24b439f5f1b98af9d624ebc7759867a9ba1485911beeaff"
BASE_PATHS = "094aaf0f580d03c8196a6fb9abbf365c192904298803167c825304abaed63ca9"
BASE_SCHEMA_COUNT = 80

M11_OPS = {
    ("get", "/api/v1/scans"),
    ("get", "/api/v1/scans/{id}"),
    ("get", "/api/v1/scans/{id}/results"),
    ("get", "/api/v1/scans/{id}/results.csv"),
    ("get", "/api/v1/agents/{id}/scans"),
    ("post", "/api/v1/scans/{id}/reevaluate"),
}
M11_SCHEMAS = {
    "HostJob",
    "HostSummary",
    "Page_ScanItem_",
    "Page_ScanResultItem_",
    "Page_ScanResultItemWithOutput_",
    "ReevalItem",
    "ScanDetailItem",
    "ScanItem",
    "ScanResultItem",
    "ScanResultItemWithOutput",
}
# Owner-approved additions after release 0.2.0 (TS §6.2; work/decisions.md
# 2026-11-12): the session routes and their models, outside the M11 pins.
SESSION_OPS = {
    ("get", "/api/v1/auth/session"),
    ("get", "/api/v1/auth/sessions"),
    ("delete", "/api/v1/auth/sessions/{session_id}"),
}
SESSION_SCHEMAS = {"CurrentSession", "Page_SessionItem_", "SessionItem"}
UUID_RE = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SCAN_STATES = ["queued", "running", "completed", "partial", "failed", "cancelled"]
JOB_STATES = [
    "queued",
    "dispatched",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "expired",
]
STATUSES = ["PASS", "FAIL", "ERROR", "NOT_RUN"]
BASE_REFUSALS = {"400", "401", "403", "429", "503"}
# Query agent_id: hyphenated only (decisions 2026-11-08, TASK-232 r1).
AGENT_ID_SCHEMA = {"pattern": UUID_RE, "type": "string"}

SCAN_ITEM = {
    "scan_id",
    "policy_id",
    "policy_name",
    "policy_version",
    "trigger",
    "schedule_id",
    "requested_by",
    "state",
    "target_kind",
    "resolved_count",
    "created_at",
    "finished_at",
}
HOST_JOB = {
    "job_id",
    "state",
    "retry_of",
    "dispatched_at",
    "started_at",
    "finished_at",
    "cancel_reason",  # owner decision 2026-11-14 (TS §4.4, §6.4)
}
HOST_SUMMARY = {
    "agent_id",
    "hostname",
    "jobs",
    "passed",
    "failed",
    "errors",
    "not_run",
    "score",
}
RESULT_ITEM = {
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
REEVAL_ITEM = {
    "scan_id",
    "policy_id",
    "scan_policy_version",
    "policy_version",
    "rows_added",
    "not_in_version",
}


# The one owner-approved change to a 6efe0fb component (decision 2026-11-14,
# TS §6.5, §8.6): the max_parallel_jobs key in these three schemas. The pin
# is checked with exactly that key taken out, so any other change still fails.
PARALLEL_JOBS_SCHEMAS = ("HeartbeatResponse", "SettingsBody", "SettingsPatch")


def without_parallel_jobs(schemas: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schemas)
    for name in PARALLEL_JOBS_SCHEMAS:
        s = out[name]
        assert "max_parallel_jobs" in s["properties"], name
        del s["properties"]["max_parallel_jobs"]
        if "max_parallel_jobs" in s.get("required", []):
            s["required"].remove("max_parallel_jobs")
        if "description" in s:
            s["description"] = s["description"].replace("eight keys", "seven keys")
    return out


def digest(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DOC.read_text(encoding="utf-8"))
    return data


def op(doc: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    found: dict[str, Any] = doc["paths"][path][method]
    return found


def params(doc: dict[str, Any], method: str, path: str) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in op(doc, method, path).get("parameters", [])}


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """The non-null branch of an `anyOf: [X, null]` schema (or the schema)."""
    if "anyOf" in schema:
        rest = [s for s in schema["anyOf"] if s != {"type": "null"}]
        assert len(rest) == 1 and len(schema["anyOf"]) == 2, schema
        only: dict[str, Any] = rest[0]
        return only
    return schema


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


# ------------------------------------------------------------ CHK-M11-230


def test_exactly_the_six_operations_are_added(doc: dict[str, Any]) -> None:
    """REQ-273 (1): the six operations, once each, under /api/v1/; nothing
    else in the paths changed since 6efe0fb."""
    ops = {(m, p) for p, item in doc["paths"].items() for m in item}
    assert M11_OPS <= ops
    assert all(p.startswith(PREFIX + "/") for _, p in M11_OPS)
    rest: dict[str, dict[str, Any]] = {}
    for path, item in doc["paths"].items():
        added = M11_OPS | SESSION_OPS
        kept = {m: o for m, o in item.items() if (m, path) not in added}
        if kept:
            rest[path] = kept
    assert digest(rest) == BASE_PATHS


def test_scan_list_parameters(doc: dict[str, Any]) -> None:
    """REQ-264, plan §3: limit 1-500 default 50, cursor, policy_id >= 1,
    agent_id uuid, state the six scan states, created_after/before date-time;
    all optional; no body."""
    got = params(doc, "get", "/api/v1/scans")
    assert set(got) == {
        "limit",
        "cursor",
        "policy_id",
        "agent_id",
        "state",
        "created_after",
        "created_before",
    }
    assert all(p["in"] == "query" and not p.get("required") for p in got.values())
    lim = got["limit"]["schema"]
    assert (lim["type"], lim["minimum"], lim["maximum"], lim["default"]) == (
        "integer",
        1,
        500,
        50,
    )
    pol = nullable(got["policy_id"]["schema"])
    assert pol["type"] == "integer" and pol["minimum"] == 1
    assert nullable(got["agent_id"]["schema"]) == AGENT_ID_SCHEMA
    assert nullable(got["state"]["schema"])["enum"] == SCAN_STATES
    for name in ("created_after", "created_before"):
        assert nullable(got[name]["schema"]) == {
            "format": "date-time",
            "type": "string",
        }
    assert "requestBody" not in op(doc, "get", "/api/v1/scans")


@pytest.mark.parametrize(
    ("method", "path", "query"),
    [
        ("get", "/api/v1/scans/{id}", set()),
        (
            "get",
            "/api/v1/scans/{id}/results",
            {"limit", "cursor", "status", "agent_id"},
        ),
        ("get", "/api/v1/scans/{id}/results.csv", {"status", "agent_id"}),
        ("post", "/api/v1/scans/{id}/reevaluate", set()),
    ],
)
def test_scan_id_operations_parameters(
    doc: dict[str, Any], method: str, path: str, query: set[str]
) -> None:
    """Hyphenated UUID path id (either case); the results filters of #144
    (d); the CSV has no cursor (#146 (a)); re-evaluate reads no body (#147 (b))."""
    got = params(doc, method, path)
    assert got["id"]["in"] == "path" and got["id"]["required"] is True
    assert got["id"]["schema"]["pattern"] == UUID_RE
    assert set(got) - {"id"} == query
    if "status" in query:
        assert nullable(got["status"]["schema"])["enum"] == STATUSES
        assert nullable(got["agent_id"]["schema"]) == AGENT_ID_SCHEMA
    if "limit" in query:
        lim = got["limit"]["schema"]
        assert (lim["minimum"], lim["maximum"], lim["default"]) == (1, 500, 50)
    assert "requestBody" not in op(doc, method, path)


def test_host_history_parameters(doc: dict[str, Any]) -> None:
    """Plan §3: a plain string id (404 for a non-UUID is the handler's, as
    agents.py), limit and cursor only."""
    got = params(doc, "get", "/api/v1/agents/{id}/scans")
    assert set(got) == {"id", "limit", "cursor"}
    assert got["id"]["schema"] == {"title": "Id", "type": "string"}


@pytest.mark.parametrize(
    ("method", "path", "body", "extra"),
    [
        ("get", "/api/v1/scans", ref("Page_ScanItem_"), set()),
        ("get", "/api/v1/scans/{id}", ref("ScanDetailItem"), {"404"}),
        (
            "get",
            "/api/v1/scans/{id}/results",
            {
                "anyOf": [
                    ref("Page_ScanResultItem_"),
                    ref("Page_ScanResultItemWithOutput_"),
                ]
            },
            {"404"},
        ),
        ("get", "/api/v1/agents/{id}/scans", ref("Page_ScanItem_"), {"404"}),
        ("post", "/api/v1/scans/{id}/reevaluate", ref("ReevalItem"), {"404", "409"}),
    ],
)
def test_success_schemas_and_declared_refusals(
    doc: dict[str, Any], method: str, path: str, body: dict[str, Any], extra: set[str]
) -> None:
    responses = op(doc, method, path)["responses"]
    assert set(responses) == {"200"} | BASE_REFUSALS | extra
    schema = dict(responses["200"]["content"]["application/json"]["schema"])
    schema.pop("title", None)
    assert schema == body


def test_results_csv_is_text_csv(doc: dict[str, Any]) -> None:
    responses = op(doc, "get", "/api/v1/scans/{id}/results.csv")["responses"]
    assert set(responses) == {"200", "404"} | BASE_REFUSALS
    assert responses["200"]["content"] == {"text/csv": {"schema": {"type": "string"}}}


# ------------------------------------------------------------ CHK-M11-231


def props(doc: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = doc["components"]["schemas"][name]["properties"]
    return found


@pytest.mark.parametrize(
    ("name", "keys"),
    [
        ("ScanItem", SCAN_ITEM),
        ("HostJob", HOST_JOB),
        ("HostSummary", HOST_SUMMARY),
        ("ScanDetailItem", SCAN_ITEM | {"target", "hosts"}),
        ("ScanResultItem", RESULT_ITEM),
        ("ScanResultItemWithOutput", RESULT_ITEM | {"stdout", "stderr"}),
        ("ReevalItem", REEVAL_ITEM),
        ("Page_ScanItem_", {"items", "next_cursor"}),
        ("Page_ScanResultItem_", {"items", "next_cursor"}),
        ("Page_ScanResultItemWithOutput_", {"items", "next_cursor"}),
    ],
)
def test_model_properties_are_exactly_the_plan(
    doc: dict[str, Any], name: str, keys: set[str]
) -> None:
    """#144 (a), #145 (a), (b), #147 (c); every property required (the keys
    are always present; null where the plan allows it)."""
    schema = doc["components"]["schemas"][name]
    assert set(schema["properties"]) == keys
    assert set(schema["required"]) == keys


def test_model_value_types(doc: dict[str, Any]) -> None:
    item = props(doc, "ScanItem")
    assert item["state"]["enum"] == SCAN_STATES
    assert item["target_kind"]["enum"] == ["agents", "tags", "all"]
    assert item["trigger"]["enum"] == ["manual", "scheduled"]
    assert item["scan_id"]["format"] == "uuid"
    assert item["created_at"]["format"] == "date-time"
    assert nullable(item["finished_at"])["format"] == "date-time"
    assert props(doc, "HostJob")["state"]["enum"] == JOB_STATES
    assert nullable(props(doc, "HostSummary")["score"]) == {"type": "number"}
    hosts = props(doc, "ScanDetailItem")["hosts"]
    assert hosts["items"] == ref("HostSummary")
    assert props(doc, "HostSummary")["jobs"]["items"] == ref("HostJob")
    res = props(doc, "ScanResultItem")
    for k in ("result", "original_result"):
        assert nullable(res[k])["enum"] == ["PASS", "FAIL", "ERROR"]
    assert res["retry"]["type"] == "boolean"
    assert nullable(res["job_id"])["format"] == "uuid"
    for k in ("stdout", "stderr"):
        assert nullable(props(doc, "ScanResultItemWithOutput")[k]) == {"type": "string"}
    page = props(doc, "Page_ScanResultItemWithOutput_")
    assert page["items"]["items"] == ref("ScanResultItemWithOutput")
    assert props(doc, "Page_ScanResultItem_")["items"]["items"] == ref("ScanResultItem")


def test_output_fields_only_in_the_operator_model(doc: dict[str, Any]) -> None:
    """REQ-268 (3): of the M11 models only ScanResultItemWithOutput has stdout
    or stderr; scan models carry no resolved_agents, execute or expected."""
    for name in M11_SCHEMAS:
        keys = set(doc["components"]["schemas"][name].get("properties", {}))
        if name != "ScanResultItemWithOutput":
            assert not keys & {"stdout", "stderr"}, name
        if not name.startswith(("ScanResultItem", "Page_ScanResult")):
            assert not keys & {"resolved_agents", "execute", "expected"}, name


# ------------------------------------------------------------ CHK-M11-232


def test_earlier_components_are_byte_identical(doc: dict[str, Any]) -> None:
    """REQ-273 (3): every component schema present at 6efe0fb (the agent-route
    ones, ResultItem among them) is unchanged; M11 only adds."""
    schemas = doc["components"]["schemas"]
    added = M11_SCHEMAS | SESSION_SCHEMAS
    old = {k: v for k, v in schemas.items() if k not in added}
    assert len(old) == BASE_SCHEMA_COUNT
    assert digest(without_parallel_jobs(old)) == BASE_SCHEMAS
    assert set(schemas) & M11_SCHEMAS == M11_SCHEMAS


# ------------------------------------------------------------ CHK-M11-235


def test_route_walk_markers() -> None:
    """REQ-273 (4): role viewer for the five reads; totp_session admin with
    the sink gate for re-evaluate (TS §6.2 L1086, §5.3 L1053)."""
    walked = markers(create_app())
    for method, path in M11_OPS:
        marker = walked[(method.upper(), path)]
        assert marker is not None, path
        got = (marker.check, marker.minimum, marker.allow_restricted, marker.sink_gate)
        if path.endswith("/reevaluate"):
            assert got == ("totp_session", "admin", False, True)
        else:
            assert got == ("role", "viewer", False, False), path


# ------------------------------------------------------------ CHK-M11-234 (CODE)

SID = "0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11"


def endpoints_for(method: str, path: str) -> list[str]:
    scope = {"type": "http", "path": path, "method": method, "root_path": ""}
    out = []
    for route in api_routes(create_app().routes):
        if isinstance(route, APIRoute) or hasattr(route, "matches"):
            match, _ = route.matches(scope)
            if match is Match.FULL:
                out.append(route.path)
    return out


def test_results_csv_is_its_own_route() -> None:
    """Plan §7: /results.csv never reaches /results or /{id}; /{id}.csv is no
    route of this family."""
    assert endpoints_for("GET", f"{PREFIX}/scans/{SID}/results.csv") == [
        f"{PREFIX}/scans/{{id}}/results.csv"
    ]
    assert endpoints_for("GET", f"{PREFIX}/scans/{SID}/results") == [
        f"{PREFIX}/scans/{{id}}/results"
    ]
    assert endpoints_for("GET", f"{PREFIX}/scans/{SID}") == [f"{PREFIX}/scans/{{id}}"]
