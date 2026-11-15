"""REQ-060, REQ-061 (3), (4), REQ-088 (1), (4): agent wire contract (TP-M3-02, G30).

Checks CHK-M3-011 to CHK-M3-019 of tests/m3/test-plan.md. Every shared fixture
(tests/contract/fixtures, written from TS §6.5 and #60, not from the code) is
checked against its Pydantic model in ``bitscan_manager.api.agent.schemas`` and
against that model's JSON Schema; the document half (CHK-M3-016) checks the
same fixtures against ``manager/openapi.json`` for every agent operation it
holds.

JSON Schema validation uses Draft 2020-12 with a format checker that asserts
``date-time`` (RFC 3339 §5.6, offset required) and ``uuid`` (RFC 9562
hyphenated form), so "format" is part of the contract the Go agent shares.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest
import re2  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from bitscan_manager.api import agent as agent_pkg
from bitscan_manager.api.agent import schemas
from tests.contract import loader

OPENAPI = Path(__file__).resolve().parents[1] / "openapi.json"
RFC3339 = re2.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})$"
)
UUID_RE = re2.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
FORBIDDEN_JOB_KEYS = {"operator", "expected_result", "expected", "eval_spec"}
TS_6_5_TYPES = {
    "pending_approval",
    "enrollment_rejected",
    "token_revoked",
    "token_expired",
    "machine_id_mismatch",
    "job_not_acceptable",
    "too_large",
    "rate_limited",
}

FORMATS = jsonschema.FormatChecker(formats=())


def _date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not RFC3339.search(value):
        return False
    try:
        datetime.fromisoformat(value.replace("z", "Z").replace("t", "T"))
    except ValueError:
        return False
    return True


def _uuid(value: object) -> bool:
    return not isinstance(value, str) or bool(UUID_RE.search(value))


FORMATS.checks("date-time")(_date_time)
FORMATS.checks("uuid")(_uuid)


def model_for(fx: loader.Fixture) -> type[BaseModel] | None:
    spec = loader.manifest()["routes"][fx.route][fx.direction]
    if spec is None or spec["model"] is None:
        return None
    model = getattr(schemas, spec["model"])
    assert isinstance(model, type) and issubclass(model, BaseModel)
    return model


def model_fixtures() -> Iterator[loader.Fixture]:
    for fx in loader.fixtures():
        if model_for(fx) is not None:
            yield fx


def validator(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=FORMATS)


def model_schema(model: type[BaseModel], direction: str) -> dict[str, Any]:
    if direction == "request":
        return model.model_json_schema(mode="validation")
    return model.model_json_schema(mode="serialization")


FX = list(model_fixtures())


# ------------------------------------------------------------ CHK-M3-011


@pytest.mark.parametrize("fx", FX, ids=lambda f: f.id)
def test_model_accepts_valid_refuses_invalid(fx: loader.Fixture) -> None:
    model = model_for(fx)
    assert model is not None
    data = fx.body_bytes()
    if fx.valid:
        model.model_validate_json(data)
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(data)


# ------------------------------------------------------------ CHK-M3-012


@pytest.mark.parametrize("fx", FX, ids=lambda f: f.id)
def test_model_json_schema_agrees(fx: loader.Fixture) -> None:
    model = model_for(fx)
    assert model is not None
    errors = list(validator(model_schema(model, fx.direction)).iter_errors(fx.body()))
    if fx.schema_gap is not None:
        # main rulings 2026-10-23: lone surrogates and NaN/inf are model-only (manifest
        # "schema_gaps"); the schema accepts them, the model refuses (CHK-M3-011)
        assert fx.schema_gap in {"lone surrogate", "nan_inf"} and not fx.valid
        assert not errors, "a schema_gap fixture is now refused: drop the gap mark"
        return
    if fx.valid:
        assert not errors, [e.message for e in errors][:3]
    else:
        assert errors, f"schema accepted invalid fixture ({fx.cls}: {fx.reason})"


# ------------------------------------------------------------ schema walk helpers


def resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/"), ref
        target: Any = schema
        for part in ref[2:].split("/"):
            target = target[part]
        node = target
    return node


def objects(schema: dict[str, Any], node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every object schema reachable from node (properties, items, unions)."""
    seen: set[int] = set()
    stack = [node]
    while stack:
        n = resolve(schema, stack.pop())
        if id(n) in seen:
            continue
        seen.add(id(n))
        if n.get("type") == "object" or "properties" in n:
            yield n
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            stack.extend(n.get(key, []))
        if isinstance(n.get("items"), dict):
            stack.append(n["items"])
        stack.extend(n.get("properties", {}).values())
        if isinstance(n.get("additionalProperties"), dict):
            stack.append(n["additionalProperties"])


def job_variants(schema: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = resolve(schema, schema["properties"]["jobs"])
    items = resolve(schema, jobs["items"])
    variants = items.get("oneOf") or items.get("anyOf")
    assert variants, "Job is a union of two variants"
    return [resolve(schema, v) for v in variants]


def kind_value(schema: dict[str, Any], variant: dict[str, Any]) -> str:
    k = resolve(schema, variant["properties"]["kind"])
    if "const" in k:
        return str(k["const"])
    assert k.get("enum") and len(k["enum"]) == 1, k
    return str(k["enum"][0])


# ------------------------------------------------------------ CHK-M3-013


def test_job_variants_exact() -> None:
    schema = schemas.JobsResponse.model_json_schema(mode="serialization")
    variants = {kind_value(schema, v): v for v in job_variants(schema)}
    assert set(variants) == {"inventory", "compliance"}
    base = {"job_id", "agent_id", "kind", "pickup_by"}
    inv, comp = variants["inventory"], variants["compliance"]
    assert set(inv["properties"]) == base
    assert set(inv.get("required", [])) == base
    assert set(comp["properties"]) == base | {"plugins", "redaction_patterns"}
    assert set(comp.get("required", [])) == base | {"plugins", "redaction_patterns"}
    plugins = resolve(schema, comp["properties"]["plugins"])
    item = resolve(schema, plugins["items"])
    assert set(item["properties"]) == {"plugin_uuid", "execute", "timeout_s"}
    assert set(item.get("required", [])) == {"plugin_uuid", "execute", "timeout_s"}
    for v in (inv, comp, item):
        assert v.get("additionalProperties") is False


def test_no_object_open_or_forbidden_key_in_job_pull() -> None:
    schema = schemas.JobsResponse.model_json_schema(mode="serialization")
    found = list(objects(schema, schema))
    assert len(found) >= 4  # response, two variants, plugin item
    for obj in found:
        assert obj.get("additionalProperties") is False, obj.get("title")
        assert not FORBIDDEN_JOB_KEYS & set(obj.get("properties", {})), obj.get("title")
    text = json.dumps(schema)
    for key in FORBIDDEN_JOB_KEYS:
        assert f'"{key}"' not in text


# ------------------------------------------------------------ CHK-M3-014


def test_heartbeat_response_exact() -> None:
    schema = schemas.HeartbeatResponse.model_json_schema(mode="serialization")
    keys = {"job_pull_seconds", "max_parallel_plugins", "server_time"}
    # max_parallel_jobs: optional, sent only to agents 0.5.0 or later (TS §6.5)
    assert set(schema["properties"]) == keys | {"max_parallel_jobs"}
    assert set(schema.get("required", [])) == keys
    assert schema.get("additionalProperties") is False


# ------------------------------------------------------------ CHK-M3-015


def test_results_contract_exact() -> None:
    schema = schemas.ResultsRequest.model_json_schema(mode="validation")
    assert set(schema["properties"]) == {"results", "final"}
    results = resolve(schema, schema["properties"]["results"])
    assert results.get("maxItems") == 50
    item = resolve(schema, results["items"])
    assert set(item["properties"]) == {
        "plugin_uuid",
        "exit_code",
        "stdout",
        "stderr",
        "started_at",
        "finished_at",
        "timed_out",
        "truncated",
        "error",
    }
    v = validator(schema)
    ok_item = next(
        f.body()["results"][0]
        for f in loader.select("results", "request")
        if f.valid and f.body()["results"]
    )
    for err in (None, "spool_overflow", "runner_unavailable"):
        assert v.is_valid({"results": [{**ok_item, "error": err}], "final": True})
    for bad in ("", "timeout", "ERROR", 0, False):
        assert not v.is_valid({"results": [{**ok_item, "error": bad}], "final": True})
    resp = schemas.ResultsResponse.model_json_schema(mode="serialization")
    assert set(resp["properties"]) == {"accepted", "duplicates"}
    assert resp.get("additionalProperties") is False


# ------------------------------------------------------------ CHK-M3-018


def test_agent_problem_types() -> None:
    """TS §6.5 L1190 exactly, and the #59 generic values for the other statuses."""
    assert set(agent_pkg.AGENT_PROBLEM_TYPES) == TS_6_5_TYPES
    assert set(agent_pkg.AGENT_GENERIC_PROBLEM_TYPES) == {
        "unauthorized",
        "forbidden",
        "invalid_request",
        "about:blank",
    }


# ------------------------------------------------------------ output form


def test_responses_serialise_timestamps_in_utc_with_z() -> None:
    """TS §6.3 L1139: RFC 3339 UTC on the wire, whatever offset came in."""
    body = schemas.EnrolResponse.model_validate(
        {
            "agent_id": "6F1C2B3A-4D5E-4F60-8A7B-9C0D1E2F3A4B",
            "agent_token": loader.manifest()["fake_token"],
            "issued_at": "2026-10-19T16:00:00+08:00",
            "expires_at": "2027-10-19T03:00:00.5-05:00",
            "status": "enrolled",
        }
    )
    out = json.loads(body.model_dump_json())
    assert out["agent_id"] == "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
    assert out["issued_at"].endswith("Z")
    assert datetime.fromisoformat(out["issued_at"]) == datetime.fromisoformat(
        "2026-10-19T08:00:00+00:00"
    )
    assert datetime.fromisoformat(out["expires_at"]) == datetime.fromisoformat(
        "2027-10-19T08:00:00.5+00:00"
    )
    # and the output validates against the same response schema and the model
    schema = schemas.EnrolResponse.model_json_schema(mode="serialization")
    assert validator(schema).is_valid(out)
    schemas.EnrolResponse.model_validate_json(body.model_dump_json())


# ------------------------------------------------------------ CHK-M3-019


def test_no_command_field_in_any_request_model() -> None:
    banned = {"command", "script", "execute", "plugins"}
    for name in ("EnrolRequest", "HeartbeatRequest", "ResultsRequest", "InventoryBody"):
        model = getattr(schemas, name)
        schema = model.model_json_schema(mode="validation")
        for obj in objects(schema, schema):
            assert not banned & set(obj.get("properties", {})), (name, obj.get("title"))


def test_every_request_object_refuses_unknown_keys() -> None:
    for name in ("EnrolRequest", "HeartbeatRequest", "ResultsRequest", "InventoryBody"):
        model = getattr(schemas, name)
        schema = model.model_json_schema(mode="validation")
        for obj in objects(schema, schema):
            if "properties" not in obj:
                continue  # free-form objects such as os_info.raw
            assert obj.get("additionalProperties") is False, (name, obj.get("title"))


# ------------------------------------------------------------ CHK-M3-016 / -017


def agent_operations() -> dict[tuple[str, str], dict[str, Any]]:
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    ops = {}
    for path, item in doc.get("paths", {}).items():
        if path.startswith("/api/v1/agent/"):
            for method, op in item.items():
                ops[(method.upper(), path)] = op
    return ops


def test_document_fixtures_against_openapi() -> None:
    """Document half: runs for every agent operation already in openapi.json."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    ops = agent_operations()
    for route, spec in loader.manifest()["routes"].items():
        op = ops.get((spec["method"], spec["path"]))
        if op is None:
            continue  # not exported yet; required at the M3 head (gate)
        for direction in ("request", "response"):
            node = None
            if direction == "request" and "requestBody" in op:
                node = op["requestBody"]["content"]["application/json"]["schema"]
            if direction == "response":
                ok = [s for s in op["responses"] if s.startswith("2")]
                content = op["responses"][ok[0]].get("content")
                if content:
                    node = content["application/json"]["schema"]
            if node is None:
                continue
            schema = {**doc, **node}
            v = validator(schema)
            for fx in loader.select(route, direction):
                errs = list(v.iter_errors(fx.body()))
                if fx.schema_gap is not None:
                    # lead rulings 2026-10-23: lone surrogates and NaN/inf are
                    # model-only; the document accepts them, the model refuses
                    # them (CHK-M3-011), as in test_model_json_schema_agrees
                    assert fx.schema_gap in {"lone surrogate", "nan_inf"}
                    assert not fx.valid
                    assert not errs, (fx.id, "gap fixture now refused: drop the mark")
                    continue
                assert bool(errs) is (not fx.valid), (fx.id, fx.reason)


RAW_NUL_FIXTURES = {
    "inventory/request_invalid_nul_raw_top_key",
    "inventory/request_invalid_nul_raw_top_value",
    "inventory/request_invalid_nul_raw_nested_value",
    "inventory/request_invalid_nul_raw_nested_key",
}


def test_raw_fixtures_against_the_rawvalue_component() -> None:
    """CHK-M3-016 carry-over (decisions 2026-10-23, TASK-048 r1 round 3): with
    the whole manager/openapi.json as the validation root, the os_info.raw value
    of every inventory request fixture is checked against
    components/schemas/RawValue (and its object form OsInfo.raw). A raw with
    NUL in a key or a value is refused (the four NUL fixtures); every other raw
    (the valid ones, the size fixtures whose limit is the decoder's, and the
    model-only lone-surrogate and NaN/Infinity gaps) is accepted. The ref
    resolves recursively from the document root (no dangling or dynamic ref)."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    comps = doc["components"]["schemas"]
    assert "RawValue" in comps
    assert "$dynamicRef" not in json.dumps(doc) and "$dynamicAnchor" not in json.dumps(
        doc
    )
    value = validator({**doc, "$ref": "#/components/schemas/RawValue"})
    field = validator({**doc, **comps["OsInfo"]["properties"]["raw"]})
    seen: set[str] = set()
    checked = 0
    for fx in loader.select("inventory", "request"):
        body = fx.body()
        os_info = body.get("os_info") if isinstance(body, dict) else None
        if not isinstance(os_info, dict) or "raw" not in os_info:
            continue
        raw = os_info["raw"]
        checked += 1
        refused = bool(list(value.iter_errors(raw)))
        if fx.id in RAW_NUL_FIXTURES:
            seen.add(fx.id)
            assert refused, fx.id
            assert list(field.iter_errors(raw)), fx.id
        else:
            assert not refused, (fx.id, fx.reason)
            if isinstance(raw, dict):
                assert not list(field.iter_errors(raw)), (fx.id, fx.reason)
    assert seen == RAW_NUL_FIXTURES
    assert checked >= 20
    # and directly: nested NUL keys and values at depth, and plain JSON values
    deep: Any = "ok"
    for _ in range(20):
        deep = {"k": [deep]}
    assert value.is_valid(deep) and value.is_valid([1, 2.5, True, None, "x"])
    bad: Any = "a\u0000b"
    for _ in range(20):
        bad = {"k": [bad]}
    assert not value.is_valid(bad)
    assert not value.is_valid({"x": {"a\u0000": 1}})


def test_document_integer_bounds_are_json_safe_and_exact() -> None:
    """TASK-048 r2 (user ruling 2026-10-23): FastAPI exports bounds as floats,
    so every numeric bound in the document must be an integer value no larger
    than 2^53 - 1 (exactly representable) and equal to its model's bound;
    a 2^63 - 1 bound would be exported as 2^63 and let 2^63 through."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    found = 0

    def walk(node: Any, where: str) -> None:
        nonlocal found
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {
                    "maximum",
                    "minimum",
                    "exclusiveMaximum",
                    "exclusiveMinimum",
                }:
                    found += 1
                    assert float(value) == int(value), (where, key, value)
                    assert abs(int(value)) <= 2**53 - 1, (where, key, value)
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    walk(doc["components"]["schemas"], "components/schemas")
    assert found > 0
    hb = doc["components"]["schemas"]["HeartbeatRequest"]["properties"]
    for name in ("uptime_s", "spool_bytes"):
        assert hb[name]["maximum"] == 2**53 - 1 and hb[name]["minimum"] == 0
        model_max = schemas.HeartbeatRequest.model_json_schema()["properties"][name]
        assert model_max["maximum"] == 2**53 - 1


def test_document_holds_the_enrol_operation() -> None:
    """TASK-067: POST /api/v1/agent/enroll is exported (G6) with the agent
    contract's EnrolRequest and EnrolResponse, and the M2 TOTP enrol body
    keeps its own component under the new name TotpEnrolRequest (lead ruling
    2026-10-23 (1)); no module-path component names leak into the document."""
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    op = doc["paths"]["/api/v1/agent/enroll"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/EnrolRequest"}
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/EnrolResponse"}
    assert {"401", "429"} <= set(op["responses"])
    schemas_ = doc["components"]["schemas"]
    assert set(schemas_["EnrolRequest"]["properties"]) == {
        "hostname",
        "machine_id",
        "agent_version",
        "os_id",
        "os_version_id",
        "os_pretty_name",
    }
    # the M2 component (manager/openapi.json at M2: EnrolRequest), renamed only
    totp_component = schemas_["TotpEnrolRequest"]
    assert totp_component["title"] == "TotpEnrolRequest"
    assert totp_component["additionalProperties"] is False
    assert totp_component["properties"] == {
        "current_code": {
            "anyOf": [{"maxLength": 16, "type": "string"}, {"type": "null"}],
            "title": "Current Code",
        },
        "current_password": {
            "anyOf": [{"maxLength": 1024, "type": "string"}, {"type": "null"}],
            "title": "Current Password",
        },
        "totp_code": {
            "anyOf": [{"maxLength": 16, "type": "string"}, {"type": "null"}],
            "title": "Totp Code",
        },
    }
    assert "required" not in totp_component
    totp = doc["paths"]["/api/v1/auth/totp/enrol"]["post"]["requestBody"]
    assert totp["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TotpEnrolRequest"
    }
    assert not [n for n in schemas_ if "__" in n or "bitscan_manager" in n]


def test_format_checker_asserts_date_time_and_uuid() -> None:
    """The checker the suite relies on can fail (format is asserted, not noted)."""
    v = validator({"type": "string", "format": "date-time"})
    assert v.is_valid("2026-10-19T08:00:00Z")
    assert v.is_valid("2026-10-19T16:00:00.123+08:00")
    for bad in ("2026-10-19T08:00:00", "2026-10-19", "2026-02-30T00:00:00Z", "x"):
        assert not v.is_valid(bad), bad
    u = validator({"type": "string", "format": "uuid"})
    assert u.is_valid("6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b")
    for bad in (
        "6f1c2b3a4d5e4f608a7b9c0d1e2f3a4b",
        "urn:uuid:6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b",
    ):
        assert not u.is_valid(bad), bad


# ------------------------------------------------------------ TASK-048 r1 round 3
# os_info.raw is a recursive RawValue. A too-deep raw is a validation error
# (400 on a route), never a crash or a 500. Observed limits: 100 object levels
# (raw included) and 98 list levels; they belong to pydantic-core, so only
# "a moderate depth passes" and "101 levels are refused" are pinned. Deep JSON
# is built as text, since json.dumps itself recurses.

ZERO_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _body(raw: Any) -> dict[str, Any]:
    os_info: dict[str, Any] = {
        k: None
        for k in (
            "os_id",
            "os_version_id",
            "os_pretty_name",
            "kernel_release",
            "architecture",
            "cpu_count",
            "memory_mb",
            "uptime_s",
        )
    }
    os_info["ip_addresses"] = []
    os_info["raw"] = raw
    return {"os_info": os_info, "packages": [], "list_sha256": ZERO_SHA}


def _objects(levels: int) -> Any:
    """raw as `levels` nested objects, raw itself included."""
    node: Any = "leaf"
    for _ in range(levels - 1):
        node = {"k": node}
    return node


def _lists(levels: int) -> Any:
    node: Any = "leaf"
    for _ in range(levels):
        node = [node]
    return {"a": node}


def _deep_text(levels: int, kind: str = "object") -> str:
    """The inventory body as JSON text with raw nested `levels` deep."""
    if kind == "object":
        raw = '{"k": ' * (levels - 1) + '"leaf"' + "}" * (levels - 1)
    else:
        raw = '{"a": ' + "[" * levels + '"leaf"' + "]" * levels + "}"
    head = json.dumps(_body({}))
    return head.replace('"raw": {}', '"raw": ' + raw)


def test_raw_depth_limit_at_the_model() -> None:
    """The limit is pydantic-core's recursion guard, which differs by platform
    (about 100 levels on Windows, higher on Linux: TASK-067 TEST found 101
    accepted in WSL). Lead ruling 2026-10-23: a too-deep raw may be refused,
    always as a validation error; the behaviour is pinned, not the number."""
    schemas.InventoryBody.model_validate(_body(_objects(50)))
    schemas.InventoryBody.model_validate(_body(_lists(50)))
    for levels in (101, 300):  # either side of the guard, by platform
        for build in (_objects, _lists):
            try:
                schemas.InventoryBody.model_validate(_body(build(levels)))
            except ValidationError:
                pass  # refused as a validation error, never anything else
    for levels in (1000, 50_000):
        with pytest.raises(ValidationError):
            schemas.InventoryBody.model_validate(_body(_objects(levels)))
        with pytest.raises(ValidationError):
            schemas.InventoryBody.model_validate(_body(_lists(levels)))


def test_raw_depth_limit_through_json() -> None:
    """pydantic-core's JSON-mode guard is higher than its Python-mode one (about
    198 levels against 100), so only a pathological depth is pinned here; the
    route (Python mode, as FastAPI validates) is pinned at 101 below."""
    schemas.InventoryBody.model_validate_json(_deep_text(50))
    for kind in ("object", "list"):
        with pytest.raises(ValidationError):
            schemas.InventoryBody.model_validate_json(_deep_text(5000, kind))


def _deep_route_client() -> Any:
    from fastapi.testclient import TestClient

    from bitscan_manager.app import create_app

    app = create_app()

    @app.post("/t/inventory-body")
    def take(body: schemas.InventoryBody) -> dict[str, int]:
        return {"packages": len(body.packages)}

    return TestClient(app, raise_server_exceptions=False)


def _post(client: Any, text: str) -> Any:
    return client.post(
        "/t/inventory-body", content=text, headers={"Content-Type": "application/json"}
    )


def test_too_deep_raw_is_400_on_a_route() -> None:
    client = _deep_route_client()
    assert _post(client, _deep_text(50)).status_code == 200
    for levels in (101, 300):  # pydantic's guard is platform-dependent here
        for kind in ("object", "list"):
            r = _post(client, _deep_text(levels, kind))
            assert r.status_code in (200, 400), (levels, kind, r.status_code)
    for levels in (1000, 5000):
        for kind in ("object", "list"):
            r = _post(client, _deep_text(levels, kind))
            assert r.status_code == 400, (levels, kind, r.status_code)
            assert r.json()["type"] == "invalid_request"


def test_pathologically_deep_json_body_is_not_a_500() -> None:
    """Deeper than Python's own json recursion: still a client error."""
    client = _deep_route_client()
    for levels in (10_000, 200_000):
        r = _post(client, _deep_text(levels, "list"))
        assert r.status_code == 400, (levels, r.status_code, r.text[:200])
