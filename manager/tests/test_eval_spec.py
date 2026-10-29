"""TP-M8-06: the `eval_spec` contract (TASK-180; REQ-195).

#117: `{"plugins": [{"plugin_uuid", "name", "operator", "expected"}, ...]}`,
one entry per plugin of the job in payload order, 1 to 5,000 entries, a
lowercase unbraced uuid (unique), an operator of the 14, `name` 1-400
characters (`plugin_name_snap VARCHAR(400)`, TS §5.2), `expected` 0-4,000
(SR §3 ExpectedResult); no `execute` or `timeout_s` (TS §5.2 L880, §3.5
L248). The parser is strict and its message quotes nothing.
CHK-M8-110 to -116.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.evaluator.eval_spec import (
    EvalSpec,
    EvalSpecError,
    build_eval_spec,
    parse_eval_spec,
)
from bitscan_manager.services.evaluator.model import PluginSpec
from bitscan_manager.services.importer.model import OPERATORS

SR_UUID = uuid.UUID("3f1c2a4e-8b7d-4c1e-9a2f-5d6e7f8a9b0c")
SR_NAME = "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed"
CANARY = "M8CANARY-spec-9b27"


def _spec(n: int = 2, **over: Any) -> EvalSpec:
    plugins = tuple(
        PluginSpec(
            uuid.UUID(int=i + 1),
            over.get("name", f"Fam ü - plugin {i}"),
            OPERATORS[i % 14],
            over.get(
                "expected", "" if OPERATORS[i % 14] in ("empty", "not_empty") else "1"
            ),
        )
        for i in range(n)
    )
    return EvalSpec(plugins)


def _valid() -> dict[str, Any]:
    return {
        "plugins": [
            {
                "plugin_uuid": str(SR_UUID),
                "name": SR_NAME,
                "operator": "equals",
                "expected": "install ok installed",
            },
            {
                "plugin_uuid": "00000000-0000-0000-0000-000000000002",
                "name": "Fam - two",
                "operator": "empty",
                "expected": "",
            },
        ]
    }


def _keys(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(value, list):
        for v in value:
            out |= _keys(v)
    return out


# CHK-M8-110: REQ-195 (1) round trip, JSON-ready, order kept
@pytest.mark.parametrize("n", [1, 2, 14, 5_000])
def test_round_trip(n: int) -> None:
    spec = _spec(n)
    built = build_eval_spec(spec)
    text = json.dumps(built, allow_nan=False, ensure_ascii=False)
    back = parse_eval_spec(json.loads(text))
    assert back == spec
    assert [p.plugin_uuid for p in back.plugins] == [
        p.plugin_uuid for p in spec.plugins
    ]


def test_build_shape_is_the_117_json() -> None:
    built = build_eval_spec(parse_eval_spec(_valid()))
    assert built == _valid()
    assert list(built) == ["plugins"]
    for entry in built["plugins"]:
        assert set(entry) == {"plugin_uuid", "name", "operator", "expected"}
        assert all(type(v) is str for v in entry.values())
    # Lowercase hyphenated uuid text
    assert built["plugins"][0]["plugin_uuid"] == str(SR_UUID)


def test_parse_does_not_mutate_its_input() -> None:
    raw = _valid()
    before = copy.deepcopy(raw)
    parse_eval_spec(raw)
    assert raw == before


# CHK-M8-113: REQ-195 (3)
def test_get_returns_entry_or_none() -> None:
    spec = parse_eval_spec(_valid())
    entry = spec.get(SR_UUID)
    assert entry is not None
    assert entry.name == SR_NAME
    assert entry.expected == "install ok installed"
    second = spec.get(uuid.UUID("00000000-0000-0000-0000-000000000002"))
    assert second is not None and second.operator == "empty"
    assert spec.get(uuid.UUID(int=99)) is None


# CHK-M8-114: REQ-195 (4), the SR §1.1 plugin
def test_sr_1_1_entry_holds_no_execute_or_timeout() -> None:
    spec = EvalSpec((PluginSpec(SR_UUID, SR_NAME, "equals", "install ok installed"),))
    built = build_eval_spec(spec)
    entry = built["plugins"][0]
    assert entry["name"] == SR_NAME
    assert entry["operator"] == "equals"
    assert entry["expected"] == "install ok installed"
    keys = _keys(built)
    assert "execute" not in keys
    assert "timeout_s" not in keys
    assert keys == {"plugins", "plugin_uuid", "name", "operator", "expected"}


# CHK-M8-111: REQ-195 (2), one EvalSpecError per refusal
def _with(path: tuple[Any, ...], value: Any, *, delete: bool = False) -> Any:
    raw: Any = _valid()
    target = raw
    for p in path[:-1]:
        target = target[p]
    if delete:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return raw


def _entries(n: int) -> dict[str, Any]:
    return {
        "plugins": [
            {
                "plugin_uuid": str(uuid.UUID(int=i + 1)),
                "name": "F - p",
                "operator": "equals",
                "expected": "x",
            }
            for i in range(n)
        ]
    }


REFUSED: list[tuple[str, Any]] = [
    ("list", [_valid()["plugins"]]),
    ("str", json.dumps(_valid())),
    ("int", 1),
    ("none", None),
    ("bytes", b"{}"),
    ("empty object", {}),
    ("missing plugins", {"plugin": []}),
    ("extra top key", {**_valid(), "execute": "x"}),
    ("extra top key 2", {**_valid(), "version": 1}),
    ("plugins not list", {"plugins": {"a": 1}}),
    ("plugins tuple", {"plugins": tuple(_valid()["plugins"])}),
    ("empty list", {"plugins": []}),
    ("5001 entries", _entries(5_001)),
    ("entry not object", {"plugins": ["x"]}),
    ("entry list", {"plugins": [[1, 2, 3, 4]]}),
    ("missing plugin_uuid", _with(("plugins", 0, "plugin_uuid"), None, delete=True)),
    ("missing name", _with(("plugins", 0, "name"), None, delete=True)),
    ("missing operator", _with(("plugins", 0, "operator"), None, delete=True)),
    ("missing expected", _with(("plugins", 0, "expected"), None, delete=True)),
    ("extra execute", _with(("plugins", 0, "execute"), "dpkg-query -W")),
    ("extra timeout_s", _with(("plugins", 0, "timeout_s"), 60)),
    ("extra other", _with(("plugins", 0, "x"), "y")),
    (
        "duplicate uuid",
        {"plugins": [_valid()["plugins"][0], dict(_valid()["plugins"][0])]},
    ),
    (
        "duplicate uuid differing case",
        {
            "plugins": [
                _valid()["plugins"][0],
                {**_valid()["plugins"][1], "plugin_uuid": str(SR_UUID).upper()},
            ]
        },
    ),
    ("uppercase uuid", _with(("plugins", 0, "plugin_uuid"), str(SR_UUID).upper())),
    ("braced uuid", _with(("plugins", 0, "plugin_uuid"), "{" + str(SR_UUID) + "}")),
    ("urn uuid", _with(("plugins", 0, "plugin_uuid"), "urn:uuid:" + str(SR_UUID))),
    ("hex uuid", _with(("plugins", 0, "plugin_uuid"), SR_UUID.hex)),
    ("short uuid", _with(("plugins", 0, "plugin_uuid"), str(SR_UUID)[:-1])),
    ("not uuid", _with(("plugins", 0, "plugin_uuid"), "not-a-uuid")),
    (
        "36 chars not hex",
        _with(("plugins", 0, "plugin_uuid"), "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"),
    ),
    ("padded uuid", _with(("plugins", 0, "plugin_uuid"), " " + str(SR_UUID))),
    ("uuid int", _with(("plugins", 0, "plugin_uuid"), 5)),
    ("operator upper", _with(("plugins", 0, "operator"), "EQUALS")),
    ("operator empty", _with(("plugins", 0, "operator"), "")),
    ("operator unknown", _with(("plugins", 0, "operator"), "equal")),
    ("operator padded", _with(("plugins", 0, "operator"), "equals ")),
    ("name empty", _with(("plugins", 0, "name"), "")),
    ("name 401", _with(("plugins", 0, "name"), "n" * 401)),
    ("expected 4001", _with(("plugins", 0, "expected"), "e" * 4_001)),
    ("name int", _with(("plugins", 0, "name"), 7)),
    ("name none", _with(("plugins", 0, "name"), None)),
    ("name list", _with(("plugins", 0, "name"), ["a"])),
    ("name bool", _with(("plugins", 0, "name"), True)),
    ("operator int", _with(("plugins", 0, "operator"), 0)),
    ("operator none", _with(("plugins", 0, "operator"), None)),
    ("expected int", _with(("plugins", 0, "expected"), 0)),
    ("expected none", _with(("plugins", 0, "expected"), None)),
    ("expected list", _with(("plugins", 0, "expected"), [])),
    ("expected bool", _with(("plugins", 0, "expected"), False)),
    ("expected float", _with(("plugins", 0, "expected"), 1.5)),
    ("plugin_uuid none", _with(("plugins", 0, "plugin_uuid"), None)),
    ("plugin_uuid UUID obj", _with(("plugins", 0, "plugin_uuid"), SR_UUID)),
]


@pytest.mark.parametrize(("label", "value"), REFUSED, ids=[r[0] for r in REFUSED])
def test_parse_refuses(label: str, value: Any) -> None:
    with pytest.raises(EvalSpecError):
        parse_eval_spec(value)


def test_eval_spec_error_is_a_value_error() -> None:
    assert issubclass(EvalSpecError, ValueError)


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("5000 entries", _entries(5_000)),
        ("name 400", _with(("plugins", 0, "name"), "n" * 400)),
        ("name 400 non-ascii", _with(("plugins", 0, "name"), "ü" * 400)),
        ("name 1", _with(("plugins", 0, "name"), "n")),
        ("expected 4000", _with(("plugins", 0, "expected"), "e" * 4_000)),
        ("expected 4000 non-ascii", _with(("plugins", 0, "expected"), "€" * 4_000)),
        ("expected empty", _with(("plugins", 0, "expected"), "")),
        ("one entry", {"plugins": [_valid()["plugins"][0]]}),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_parse_accepts_the_boundaries(label: str, value: Any) -> None:
    spec = parse_eval_spec(value)
    assert build_eval_spec(spec) == value


@pytest.mark.parametrize("op", OPERATORS)
def test_every_operator_is_accepted(op: str) -> None:
    spec = parse_eval_spec(_with(("plugins", 0, "operator"), op))
    entry = spec.get(SR_UUID)
    assert entry is not None and entry.operator == op


# The constructor holds the same rules (build never writes what parse refuses).
@pytest.mark.parametrize(
    "plugins",
    [
        (),
        (PluginSpec(SR_UUID, "", "equals", "x"),),
        (PluginSpec(SR_UUID, "n" * 401, "equals", "x"),),
        (PluginSpec(SR_UUID, "F - p", "EQUALS", "x"),),
        (PluginSpec(SR_UUID, "F - p", "equals", "e" * 4_001),),
        (
            PluginSpec(SR_UUID, "F - p", "equals", "x"),
            PluginSpec(SR_UUID, "F - q", "equals", "y"),
        ),
        tuple(
            PluginSpec(uuid.UUID(int=i + 1), "F", "equals", "x") for i in range(5_001)
        ),
    ],
    ids=["empty", "name0", "name401", "opupper", "exp4001", "dup", "5001"],
)
def test_constructor_refuses_what_parse_refuses(
    plugins: tuple[PluginSpec, ...],
) -> None:
    with pytest.raises(EvalSpecError):
        EvalSpec(plugins)


# CHK-M8-112: the message holds none of the input
def _canary_inputs() -> list[Any]:
    c = CANARY
    return [
        c,
        [c],
        {c: 1},
        {"plugins": c},
        {"plugins": [c]},
        {"plugins": [], c: c},
        _with(("plugins", 0, "plugin_uuid"), c),
        _with(("plugins", 0, "operator"), c),
        _with(("plugins", 0, "name"), c * 50),
        _with(("plugins", 0, "expected"), c * 300),
        _with(("plugins", 0, c), c),
        _with(("plugins", 0, "name"), 5),
        # non-string values that hold the canary (a message quoting repr(value)
        # would carry it)
        _with(("plugins", 0, "name"), [c]),
        _with(("plugins", 0, "operator"), {c: c}),
        _with(("plugins", 0, "expected"), [c, c]),
        _with(("plugins", 0, "plugin_uuid"), [c]),
        {"plugins": [c, {"x": c}]},
        {"plugins": {c: c}},
    ]


@pytest.mark.parametrize(
    "variants",
    [
        [_with(("plugins", 0, "name"), v) for v in (5, 6, None, [1], {"a": 2}, 1.5)],
        [_with(("plugins", 0, "expected"), v) for v in (0, 7, None, ["z"], False)],
        [_with(("plugins", 0, "plugin_uuid"), v) for v in ("A", "nope", "{x}", 3)],
        [_with(("plugins", 0, "operator"), v) for v in ("EQUALS", "x", "", "eq ")],
        [_with(("plugins", 0, "name"), "n" * k) for k in (401, 402, 1_000)],
        [_with(("plugins", 0, "expected"), "e" * k) for k in (4_001, 4_002, 9_999)],
    ],
    ids=["name-type", "expected-type", "uuid", "operator", "name-len", "exp-len"],
)
def test_one_fixed_message_per_refusal(variants: list[Any]) -> None:
    """Different inputs refused for the same reason give the same message:
    nothing of the input is in it."""
    messages = set()
    for value in variants:
        with pytest.raises(EvalSpecError) as info:
            parse_eval_spec(value)
        messages.add(str(info.value))
    assert len(messages) == 1, messages


def test_messages_quote_nothing() -> None:
    messages: set[str] = set()
    for value in _canary_inputs():
        with pytest.raises(EvalSpecError) as info:
            parse_eval_spec(value)
        text = str(info.value) + repr(info.value) + repr(info.value.args)
        assert CANARY not in text
        assert info.value.__cause__ is None or CANARY not in str(info.value.__cause__)
        assert info.value.__context__ is None or CANARY not in str(
            info.value.__context__
        )
        messages.add(str(info.value))
    # Fixed messages: a small closed set, none holding any input.
    assert 1 <= len(messages) <= 12


# CHK-M8-115: lengths count characters, as VARCHAR does
def test_lengths_are_characters_not_bytes() -> None:
    name = "€" * 400  # 1,200 UTF-8 bytes
    spec = parse_eval_spec(_with(("plugins", 0, "name"), name))
    entry = spec.get(SR_UUID)
    assert entry is not None and entry.name == name


def test_lone_surrogate_text_never_crashes() -> None:
    value = _with(("plugins", 0, "name"), "a\ud800")
    try:
        spec = parse_eval_spec(value)
    except EvalSpecError:
        return
    assert spec.get(SR_UUID) is not None


# CHK-M8-116: parse raises only EvalSpecError
JSONISH = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=True),
        st.text(max_size=20),
        st.sampled_from(["plugins", "plugin_uuid", "name", "operator", "expected"]),
        st.sampled_from(OPERATORS),
        st.uuids().map(str),
    ),
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.dictionaries(
            st.one_of(
                st.sampled_from(
                    ["plugins", "plugin_uuid", "name", "operator", "expected"]
                ),
                st.text(max_size=5),
            ),
            inner,
            max_size=5,
        ),
    ),
    max_leaves=20,
)


@settings(max_examples=2_000, deadline=None)
@given(JSONISH)
def test_parse_raises_only_eval_spec_error(value: Any) -> None:
    try:
        spec = parse_eval_spec(value)
    except EvalSpecError:
        return
    assert isinstance(spec, EvalSpec)
    assert build_eval_spec(spec) == value


ENTRY = st.builds(
    lambda u, name, op, exp: {
        "plugin_uuid": str(u),
        "name": name,
        "operator": op,
        "expected": exp,
    },
    st.uuids(),
    st.text(min_size=1, max_size=400, alphabet=st.characters(codec="utf-8")),
    st.sampled_from(OPERATORS),
    st.text(max_size=200, alphabet=st.characters(codec="utf-8")),
)


@settings(max_examples=500, deadline=None)
@given(st.lists(ENTRY, min_size=1, max_size=50, unique_by=lambda e: e["plugin_uuid"]))
def test_generated_round_trip(entries: list[dict[str, str]]) -> None:
    raw = {"plugins": entries}
    spec = parse_eval_spec(raw)
    assert build_eval_spec(spec) == raw
    assert parse_eval_spec(json.loads(json.dumps(build_eval_spec(spec)))) == spec
