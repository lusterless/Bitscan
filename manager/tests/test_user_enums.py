"""TASK-108: status and kind enums in the user-route contract (TP-M5-01, REQ-117).

Checks CHK-M5-001, -002, -004 and -005 of tests/m5/test-plan.md (CHK-M5-003
is the unchanged M3 suites, run alongside). Expected values are read from the
spec text itself: TS §5.2 L710 (`CREATE TYPE agent_status AS ENUM (...)`),
L763 (`kind ... CHECK (kind IN (...))`) and L774 (`decision ... CHECK
(decision IN (...))`), with PD-29 (a) as approved 2026-10-24 (the roles stay
plain strings).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bitscan_manager.api.user.agents import AgentItem
from bitscan_manager.api.user.enrolment import MatchItem, RequestItem
from bitscan_manager.app import create_app

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "spec" / "Technical_Specification.md"
DOCUMENT = ROOT / "manager" / "openapi.json"


def _quoted_list(text: str) -> list[str]:
    """'a','b' , 'c' -> [a, b, c] (plain string handling, no regex)."""
    return [part.strip().strip("'") for part in text.split(",") if part.strip()]


def spec_agent_status() -> list[str]:
    for line in SPEC.read_text(encoding="utf-8").split("\n"):
        if line.startswith("CREATE TYPE agent_status AS ENUM ("):
            inner = line.split("(", 1)[1].rsplit(")", 1)[0]
            return _quoted_list(inner)
    raise AssertionError("agent_status not found in the spec")


def spec_check(column: str) -> list[str]:
    marker = f"CHECK ({column} IN ("
    for line in SPEC.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if stripped.startswith(column + " ") and marker in stripped:
            inner = stripped.split(marker, 1)[1].split(")", 1)[0]
            return _quoted_list(inner)
    raise AssertionError(f"CHECK on {column} not found in the spec")


STATUSES = spec_agent_status()


def test_spec_values_are_what_the_spec_says() -> None:
    assert STATUSES == [
        "awaiting_approval", "enrolled", "online", "stale", "offline", "decommissioned",
    ]  # fmt: skip
    assert spec_check("kind") == ["new", "reenrol"]
    assert spec_check("decision") == ["approved", "rejected"]


@pytest.fixture(params=["file", "live"])
def doc(request: pytest.FixtureRequest) -> dict[str, Any]:
    if request.param == "file":
        return dict(json.loads(DOCUMENT.read_text(encoding="utf-8")))
    return create_app().openapi()


def prop(doc: dict[str, Any], schema: str, name: str) -> dict[str, Any]:
    found: dict[str, Any] = doc["components"]["schemas"][schema]["properties"][name]
    return found


def string_enum(p: dict[str, Any]) -> tuple[list[str], bool]:
    """The enum values of a property and whether null is allowed."""
    if "anyOf" in p:
        branches = p["anyOf"]
        enums = [b for b in branches if "enum" in b]
        nulls = [b for b in branches if b.get("type") == "null"]
        assert len(enums) == 1 and len(enums) + len(nulls) == len(branches), p
        assert enums[0].get("type") == "string"
        return list(enums[0]["enum"]), bool(nulls)
    assert p.get("type") == "string", p
    return list(p["enum"]), False


# ---------------------------------------------------------------- CHK-M5-001


@pytest.mark.parametrize("schema", ["AgentItem", "AgentDetailItem", "MatchItem"])
def test_status_is_the_six_value_agent_status_enum(
    doc: dict[str, Any], schema: str
) -> None:
    values, nullable = string_enum(prop(doc, schema, "status"))
    assert values == STATUSES  # same values, same order, nothing extra
    assert not nullable
    assert "status" in doc["components"]["schemas"][schema]["required"]


# ---------------------------------------------------------------- CHK-M5-002


def test_request_kind_enum(doc: dict[str, Any]) -> None:
    values, nullable = string_enum(prop(doc, "RequestItem", "kind"))
    assert values == spec_check("kind")
    assert not nullable


def test_request_decision_enum_or_null(doc: dict[str, Any]) -> None:
    values, nullable = string_enum(prop(doc, "RequestItem", "decision"))
    assert values == spec_check("decision")
    assert nullable


# ---------------------------------------------------------------- CHK-M5-004


@pytest.mark.parametrize("schema", ["LoginResponse", "UserItem"])
def test_roles_stay_plain_strings(doc: dict[str, Any], schema: str) -> None:
    p = prop(doc, schema, "role")
    assert p.get("type") == "string"
    assert "enum" not in p and "anyOf" not in p


def test_file_equals_a_fresh_export() -> None:
    fresh = create_app().openapi()
    stored = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    assert fresh == stored


# ---------------------------------------------------------------- CHK-M5-005


AGENT_ITEM: dict[str, Any] = {
    "agent_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "hostname": "h",
    "agent_version": "0.5.0",
    "os_id": None,
    "os_version_id": None,
    "os_pretty_name": None,
    "last_heartbeat_at": None,
    "last_inventory_at": None,
    "tags": [],
    "runner_helpers": [],
}


@pytest.mark.parametrize("status", STATUSES)
def test_each_status_validates(status: str) -> None:
    item = AgentItem.model_validate({**AGENT_ITEM, "status": status})
    assert item.model_dump(mode="json")["status"] == status


@pytest.mark.parametrize("status", ["revoked", "ONLINE", "", "approved"])
def test_a_seventh_status_is_refused(status: str) -> None:
    with pytest.raises(ValidationError):
        AgentItem.model_validate({**AGENT_ITEM, "status": status})


def test_match_and_request_models_refuse_unknown_values() -> None:
    match_fields = MatchItem.model_fields
    assert "status" in match_fields
    with pytest.raises(ValidationError):
        MatchItem.model_validate(
            {name: "x" for name in match_fields} | {"status": "revoked"}
        )
    kind = RequestItem.model_fields["kind"].annotation
    decision = RequestItem.model_fields["decision"].annotation
    assert set(getattr(kind, "__args__", ())) == {"new", "reenrol"}
    assert "approved" in str(decision) and "rejected" in str(decision)
