"""TP-M9-05: job and retry builder (TASK-189; REQ-209 (1)-(4), (6), REQ-210
(1)-(4) for plugins given as values).

TS §3.5 L248, §6.5 L1165-L1182, §4.4 L566, L577, §4.1 L530; SR §1.1;
open questions #117, #125 (a)-(c), (g), #126 (a), (b). Expected values come
from the spec and the approved answers. CHK-M9-037 to -050.
"""

from __future__ import annotations

import inspect
import json
import uuid
from collections.abc import Collection
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
import re2  # type: ignore[import-untyped]
from pydantic import ValidationError

from bitscan_manager.api.agent.schemas import ComplianceJob, JobsResponse
from bitscan_manager.services.evaluator.eval_spec import EvalSpecError, parse_eval_spec
from bitscan_manager.services.jobs import build
from bitscan_manager.services.jobs.build import (
    BuiltPlugins,
    CatalogPlugin,
    UnstorableText,
    payload,
    pickup_text,
    plugins_and_spec,
    retry,
)
from tests.test_contract_agent import validator

CANARY = "M9CANARY-" + uuid.uuid4().hex
CREATED = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
JOB = UUID("c1a4c1a4-0000-4000-8000-000000000001")
AGENT = UUID("6f1c6f1c-0000-4000-8000-000000000002")
PICKUP_RE = re2.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FORBIDDEN_KEYS = {"operator", "expected", "expected_result", "eval_spec", "name"}
SR_EXECUTE = "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"


def plugin(n: int, **over: Any) -> CatalogPlugin:
    values: dict[str, Any] = {
        "plugin_uuid": UUID(int=(0xABCDEF << 96) + n),
        "display_name": f"Family - plugin {n} {CANARY}",
        "execute": f"echo {n}",
        "timeout_s": 10 + n % 590,  # 10-599: inside the TS §6.5 range 1-600
        "operator": "equals",
        "expected": f"expected {n} {CANARY}",
    }
    values.update(over)
    return CatalogPlugin(**values)


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            found |= _keys(v)
    elif isinstance(value, list):
        for v in value:
            found |= _keys(v)
    return found


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _schema_ok(job: dict[str, Any]) -> None:
    ComplianceJob.model_validate(job)
    JobsResponse.model_validate({"jobs": [job]})
    schema = JobsResponse.model_json_schema(mode="serialization")
    errors = list(
        validator(schema).iter_errors({"jobs": [json.loads(json.dumps(job))]})
    )
    assert errors == []


# --- CHK-M9-037 / -038: payload shape --------------------------------------


def test_payload_is_exactly_the_ts_6_5_job() -> None:
    built = plugins_and_spec([plugin(1), plugin(2)], ["secret=\\S+"])
    job = payload(JOB, AGENT, CREATED, built)
    assert set(job) == {
        "job_id",
        "agent_id",
        "kind",
        "pickup_by",
        "plugins",
        "redaction_patterns",
    }
    assert job["job_id"] == str(JOB)
    assert job["agent_id"] == str(AGENT)
    assert job["kind"] == "compliance"
    assert job["pickup_by"] == "2026-10-31T12:00:00Z"
    assert job["plugins"] == [
        {
            "plugin_uuid": str(plugin(1).plugin_uuid),
            "execute": "echo 1",
            "timeout_s": 11,
        },
        {
            "plugin_uuid": str(plugin(2).plugin_uuid),
            "execute": "echo 2",
            "timeout_s": 12,
        },
    ]
    assert job["redaction_patterns"] == ["secret=\\S+"]
    _schema_ok(job)


def test_payload_ids_are_lowercase_strings() -> None:
    upper_job = UUID(str(JOB).upper())
    p = plugin(1, plugin_uuid=UUID("ABCDEF01-2345-4678-9ABC-DEF012345678"))
    job = payload(upper_job, AGENT, CREATED, plugins_and_spec([p], []))
    assert job["job_id"] == str(JOB)
    assert job["plugins"][0]["plugin_uuid"] == "abcdef01-2345-4678-9abc-def012345678"
    assert all(s == s.lower() for s in (job["job_id"], job["agent_id"]))


def test_plugin_order_is_the_given_order() -> None:
    order = [5, 1, 4, 2, 3]
    built = plugins_and_spec([plugin(n) for n in order], [])
    job = payload(JOB, AGENT, CREATED, built)
    assert [p["plugin_uuid"] for p in job["plugins"]] == [
        str(plugin(n).plugin_uuid) for n in order
    ]
    assert [e["plugin_uuid"] for e in built.eval_spec_json["plugins"]] == [
        p["plugin_uuid"] for p in job["plugins"]
    ]


@pytest.mark.parametrize(
    "execute",
    [
        SR_EXECUTE,
        "awk -F: '($3 == 0) { print $1 }' /etc/passwd",
        'grep -E "^\\s*PermitRootLogin" /etc/ssh/sshd_config',
        "line1\nline2\ttab \\ back",
        "echo \u00fcn\u00efc\u00f8d\u00e9 \u2713 \U0001f600",
        "x" * 16_384,
    ],
    ids=["sr_1_1", "awk", "grep", "control_chars", "non_ascii", "long_16384"],
)
def test_execute_is_copied_byte_for_byte(execute: str) -> None:
    job = payload(
        JOB, AGENT, CREATED, plugins_and_spec([plugin(1, execute=execute)], [])
    )
    assert job["plugins"][0]["execute"] == execute
    assert json.loads(json.dumps(job))["plugins"][0]["execute"] == execute


@pytest.mark.parametrize("timeout", [1, 600])
def test_timeout_is_copied(timeout: int) -> None:
    job = payload(
        JOB, AGENT, CREATED, plugins_and_spec([plugin(1, timeout_s=timeout)], [])
    )
    assert job["plugins"][0]["timeout_s"] == timeout
    _schema_ok(job)


# --- CHK-M9-039: pickup_by --------------------------------------------------


@pytest.mark.parametrize(
    ("created", "text"),
    [
        (CREATED, "2026-10-31T12:00:00Z"),
        (datetime(2026, 10, 30, 12, 0, 0, 999_999, tzinfo=UTC), "2026-10-31T12:00:00Z"),
        (
            datetime(2026, 12, 31, 23, 59, 59, 500_000, tzinfo=UTC),
            "2027-01-01T23:59:59Z",
        ),
        (datetime(2028, 2, 28, 1, 2, 3, tzinfo=UTC), "2028-02-29T01:02:03Z"),
        (
            datetime(2026, 10, 31, 3, 0, 0, tzinfo=timezone(timedelta(hours=8))),
            "2026-10-31T19:00:00Z",
        ),
        (
            datetime(2026, 10, 30, 20, 0, 0, tzinfo=timezone(timedelta(hours=-5))),
            "2026-11-01T01:00:00Z",
        ),
    ],
)
def test_pickup_by_text(created: datetime, text: str) -> None:
    assert pickup_text(created) == text
    job = payload(JOB, AGENT, created, plugins_and_spec([plugin(1)], []))
    assert job["pickup_by"] == text
    assert PICKUP_RE.search(text)
    # never later than the column value created_at + 24 h, at most 1 s earlier
    as_dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    column = created + timedelta(hours=24)
    assert column - timedelta(seconds=1) < as_dt <= column


def test_pickup_window_is_24_hours() -> None:
    assert build.PICKUP_WINDOW == timedelta(hours=24)


def test_naive_created_at_is_refused() -> None:
    with pytest.raises(ValueError):
        pickup_text(datetime(2026, 10, 30, 12, 0, 0))  # noqa: DTZ001


# --- CHK-M9-040: no evaluation data in any payload --------------------------


def _all_payloads() -> list[dict[str, Any]]:
    many = [plugin(n) for n in range(5_000)]
    built = plugins_and_spec(many, [CANARY])
    original = payload(JOB, AGENT, CREATED, built)
    small = plugins_and_spec([plugin(n) for n in range(5)], [])
    original5 = payload(JOB, AGENT, CREATED, small)
    retry_payload, _ = retry(
        original5,
        small.eval_spec_json,
        {plugin(0).plugin_uuid, plugin(3).plugin_uuid},
        job_id=uuid.uuid4(),
        created_at=CREATED,
        original_is_retry=False,
    )
    return [original, original5, retry_payload]


def test_no_payload_holds_evaluation_data() -> None:
    for job in _all_payloads():
        assert _keys(job) & FORBIDDEN_KEYS == set()
        for text in _strings(job):
            # the canary is in every expected value and display name
            assert not (text.startswith("expected ") or text.startswith("Family - ")), (
                text
            )
        _schema_ok(job)


# --- CHK-M9-041: eval_spec matches the payload ------------------------------


def test_eval_spec_parses_and_matches_payload_order() -> None:
    order = [3, 1, 2]
    built = plugins_and_spec(
        [
            plugin(n, operator=op)
            for n, op in zip(order, ["regex", "eq", "empty"], strict=True)
        ],
        [],
    )
    spec = parse_eval_spec(built.eval_spec_json)
    job = payload(JOB, AGENT, CREATED, built)
    assert [str(p.plugin_uuid) for p in spec.plugins] == [
        p["plugin_uuid"] for p in job["plugins"]
    ]
    for entry, n, op in zip(spec.plugins, order, ["regex", "eq", "empty"], strict=True):
        assert entry.name == f"Family - plugin {n} {CANARY}"
        assert entry.operator == op
        assert entry.expected == f"expected {n} {CANARY}"
    for e in built.eval_spec_json["plugins"]:
        assert set(e) == {"plugin_uuid", "name", "operator", "expected"}
    assert set(built.eval_spec_json) == {"plugins"}


# --- CHK-M9-042: redaction patterns -----------------------------------------


@pytest.mark.parametrize("count", [0, 1, 50])
def test_redaction_patterns_copied_in_order(count: int) -> None:
    patterns = [f"p{i}={CANARY}" for i in range(count)]
    built = plugins_and_spec([plugin(1)], patterns)
    job = payload(JOB, AGENT, CREATED, built)
    assert job["redaction_patterns"] == patterns
    _schema_ok(job)


def test_built_payload_does_not_alias_inputs() -> None:
    patterns = ["a"]
    built = plugins_and_spec([plugin(1)], patterns)
    job = payload(JOB, AGENT, CREATED, built)
    patterns.append("b")
    job["redaction_patterns"].append("c")
    job["plugins"][0]["execute"] = "changed"
    again = payload(JOB, AGENT, CREATED, built)
    assert again["redaction_patterns"] == ["a"]
    assert again["plugins"][0]["execute"] == "echo 1"


def test_patterns_beyond_fifty_are_recorded(record_property: Any) -> None:
    # Not asserted: the setting itself caps at 50 (#125 (b)).
    try:
        plugins_and_spec([plugin(1)], ["p"] * 51)
        record_property("patterns_51", "accepted")
    except ValueError as exc:
        record_property("patterns_51", type(exc).__name__)


# --- CHK-M9-043: unstorable text (#125 (g)) ---------------------------------

BAD_TEXT = ["a\x00b", "\ud800", "x\udfff", "\udc00\ud800"]


def _unstorable_cases() -> list[tuple[str, str]]:
    return [
        (field, bad)
        for field in ("execute", "display_name", "expected", "pattern")
        for bad in BAD_TEXT
    ]


@pytest.mark.parametrize(("field", "bad"), _unstorable_cases())
def test_unstorable_text_is_refused(field: str, bad: str) -> None:
    text = CANARY + bad
    with pytest.raises(UnstorableText) as info:
        if field == "pattern":
            plugins_and_spec([plugin(1)], ["ok", text])
        else:
            plugins_and_spec([plugin(1), plugin(2, **{field: text})], [])
    assert CANARY not in str(info.value) and CANARY not in repr(info.value)
    assert isinstance(info.value, ValueError)


def test_unstorable_message_is_one_fixed_text() -> None:
    messages = set()
    for field, bad in _unstorable_cases():
        try:
            if field == "pattern":
                plugins_and_spec([plugin(1)], [bad])
            else:
                plugins_and_spec([plugin(1, **{field: bad})], [])
        except UnstorableText as exc:
            messages.add(str(exc))
    assert len(messages) == 1


@pytest.mark.parametrize("ok", ["\U0001f600", "\ufffd", "\u00e9", "\x01", "tab\there"])
def test_storable_unusual_text_is_accepted(ok: str) -> None:
    built = plugins_and_spec(
        [plugin(1, execute=ok, expected=ok, display_name="N " + ok)], [ok]
    )
    job = payload(JOB, AGENT, CREATED, built)
    assert job["plugins"][0]["execute"] == ok
    assert parse_eval_spec(built.eval_spec_json).plugins[0].expected == ok


def test_unstorable_text_is_checked_before_anything_else() -> None:
    # An unknown operator would also fail; the text check comes first.
    with pytest.raises(UnstorableText):
        plugins_and_spec([plugin(1, operator="bogus", execute="\x00")], [])


# --- CHK-M9-044: M8 EvalSpec limits -----------------------------------------


def test_plugin_count_bounds() -> None:
    assert len(plugins_and_spec([plugin(1)], []).plugins_json) == 1
    assert (
        len(plugins_and_spec([plugin(n) for n in range(5_000)], []).plugins_json)
        == 5_000
    )
    for bad in ([], [plugin(n) for n in range(5_001)]):
        with pytest.raises(ValueError):
            plugins_and_spec(bad, [])


def test_duplicate_plugin_and_unknown_operator_are_refused() -> None:
    with pytest.raises(ValueError):
        plugins_and_spec([plugin(1), plugin(1)], [])
    with pytest.raises(ValueError):
        plugins_and_spec([plugin(1, operator="EQUALS")], [])
    with pytest.raises(ValueError):
        plugins_and_spec([plugin(1, display_name="")], [])


# --- CHK-M9-045: the SR §1.1 plugin -----------------------------------------


def test_sr_1_1_plugin_values() -> None:
    sr = CatalogPlugin(
        plugin_uuid=UUID("3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"),
        display_name="CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed",
        execute=SR_EXECUTE,
        timeout_s=30,
        operator="equals",
        expected="install ok installed",
    )
    built = plugins_and_spec([sr], [])
    assert built.eval_spec_json == {
        "plugins": [
            {
                "plugin_uuid": "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",
                "name": "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed",
                "operator": "equals",
                "expected": "install ok installed",
            }
        ]
    }
    job = payload(JOB, AGENT, CREATED, built)
    assert job["plugins"] == [
        {
            "plugin_uuid": "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48",
            "execute": SR_EXECUTE,
            "timeout_s": 30,
        }
    ]


# --- CHK-M9-046 to -049: retry ----------------------------------------------


def _original(n: int = 5) -> tuple[dict[str, Any], dict[str, Any], list[CatalogPlugin]]:
    plugins = [plugin(i, execute=f"original command {i}") for i in range(1, n + 1)]
    built = plugins_and_spec(plugins, ["orig-pattern-1", "orig-pattern-2"])
    return payload(JOB, AGENT, CREATED, built), built.eval_spec_json, plugins


def test_retry_holds_only_the_missing_plugins_in_original_order() -> None:
    original, spec, plugins = _original()
    new_id = UUID("aaaaaaaa-0000-4000-8000-00000000000a")
    later = CREATED + timedelta(hours=3, minutes=7, seconds=9)
    missing = {plugins[4].plugin_uuid, plugins[0].plugin_uuid, plugins[2].plugin_uuid}
    job, ev = retry(
        original,
        spec,
        missing,
        job_id=new_id,
        created_at=later,
        original_is_retry=False,
    )
    assert job["plugins"] == [
        original["plugins"][0],
        original["plugins"][2],
        original["plugins"][4],
    ]
    assert job["redaction_patterns"] == ["orig-pattern-1", "orig-pattern-2"]
    assert job["job_id"] == str(new_id)
    assert job["agent_id"] == str(AGENT)
    assert job["kind"] == "compliance"
    assert job["pickup_by"] == "2026-10-31T15:07:09Z"
    assert set(job) == set(original)
    assert ev == {
        "plugins": [spec["plugins"][0], spec["plugins"][2], spec["plugins"][4]]
    }
    assert [str(p.plugin_uuid) for p in parse_eval_spec(ev).plugins] == [
        p["plugin_uuid"] for p in job["plugins"]
    ]
    _schema_ok(job)


def test_retry_with_every_plugin_missing() -> None:
    original, spec, plugins = _original()
    job, ev = retry(
        original,
        spec,
        [p.plugin_uuid for p in reversed(plugins)],
        job_id=uuid.uuid4(),
        created_at=CREATED,
        original_is_retry=False,
    )
    assert job["plugins"] == original["plugins"]
    assert ev == spec


def test_retry_keeps_original_values_not_any_catalog() -> None:
    """REQ-210 (1): the retry carries the original's commands and patterns.
    The function has no catalog input at all."""
    original, spec, plugins = _original()
    params = set(inspect.signature(retry).parameters)
    assert params == {
        "original_payload",
        "original_eval_spec",
        "missing",
        "job_id",
        "created_at",
        "original_is_retry",
    }
    job, _ = retry(
        original,
        spec,
        {plugins[2].plugin_uuid},
        job_id=uuid.uuid4(),
        created_at=CREATED,
        original_is_retry=False,
    )
    assert job["plugins"][0]["execute"] == "original command 3"
    assert job["plugins"][0]["timeout_s"] == plugins[2].timeout_s


def test_retry_of_a_retry_is_refused() -> None:
    original, spec, plugins = _original()
    with pytest.raises(ValueError):
        retry(
            original,
            spec,
            {plugins[0].plugin_uuid},
            job_id=uuid.uuid4(),
            created_at=CREATED,
            original_is_retry=True,
        )


def test_retry_with_nothing_missing_is_refused() -> None:
    original, spec, _ = _original()
    empties: tuple[Collection[UUID], ...] = (set(), [], ())
    for missing in empties:
        with pytest.raises(ValueError):
            retry(
                original,
                spec,
                missing,
                job_id=uuid.uuid4(),
                created_at=CREATED,
                original_is_retry=False,
            )


def test_retry_naming_a_plugin_outside_the_job_is_refused() -> None:
    original, spec, plugins = _original()
    with pytest.raises(ValueError):
        retry(
            original,
            spec,
            {plugins[0].plugin_uuid, uuid.uuid4()},
            job_id=uuid.uuid4(),
            created_at=CREATED,
            original_is_retry=False,
        )


def test_retry_with_a_mismatched_eval_spec_is_refused() -> None:
    original, spec, plugins = _original()
    swapped = {"plugins": list(reversed(spec["plugins"]))}
    with pytest.raises(ValueError):
        retry(
            original,
            swapped,
            {plugins[0].plugin_uuid, plugins[1].plugin_uuid},
            job_id=uuid.uuid4(),
            created_at=CREATED,
            original_is_retry=False,
        )
    with pytest.raises(EvalSpecError):
        retry(
            original,
            {"plugins": []},
            {plugins[0].plugin_uuid},
            job_id=uuid.uuid4(),
            created_at=CREATED,
            original_is_retry=False,
        )


def test_retry_does_not_alias_the_original() -> None:
    original, spec, plugins = _original()
    before = json.dumps(original, sort_keys=True), json.dumps(spec, sort_keys=True)
    job, ev = retry(
        original,
        spec,
        {plugins[1].plugin_uuid},
        job_id=uuid.uuid4(),
        created_at=CREATED,
        original_is_retry=False,
    )
    job["plugins"][0]["execute"] = "changed"
    job["redaction_patterns"].append("x")
    ev["plugins"][0]["expected"] = "changed"
    assert (
        json.dumps(original, sort_keys=True),
        json.dumps(spec, sort_keys=True),
    ) == before


# --- CHK-M9-050: types -------------------------------------------------------


def test_types_are_frozen() -> None:
    p = plugin(1)
    with pytest.raises(FrozenInstanceError):
        p.execute = "x"  # type: ignore[misc]
    built = plugins_and_spec([p], [])
    assert isinstance(built, BuiltPlugins)
    with pytest.raises(FrozenInstanceError):
        built.patterns = []  # type: ignore[misc]
    assert issubclass(UnstorableText, ValueError)


def test_compliance_job_model_refuses_an_operator_key() -> None:
    """Guard for CHK-M9-347: the strict model would catch an extra key."""
    job = payload(JOB, AGENT, CREATED, plugins_and_spec([plugin(1)], []))
    job["plugins"][0]["operator"] = "equals"
    with pytest.raises(ValidationError):
        ComplianceJob.model_validate(job)
