"""TP-M9-04: scan targets (TASK-188; REQ-208 (1), (2), (4)).

TS §4.4 L555, §5.2 L865, §6.4 L1151; open questions #122 (b)-(d), #68;
decisions 2026-10-30 "M9 early rulings" (1), (3). Expected values come from
the spec and the rulings. CHK-M9-025 to -032.
"""

from __future__ import annotations

import json
import string
import uuid
from dataclasses import FrozenInstanceError
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.services.agents import admin
from bitscan_manager.services.jobs import targets
from bitscan_manager.services.jobs.targets import (
    InvalidTarget,
    Target,
    parse_target,
    stored_target,
)

U1 = "6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f"
U2 = "0b2c4d6e-8f01-4234-9567-89abcdef0123"
CANARY = "M9CANARY-" + uuid.uuid4().hex
TAG_CHARS = string.ascii_letters + string.digits + "._:-"


def _uuids(n: int) -> list[str]:
    return [str(uuid.UUID(int=i + 1)) for i in range(n)]


# --- CHK-M9-025: the three forms --------------------------------------------


def test_agents_form() -> None:
    t = parse_target({"agents": [U1, U2]})
    assert t.kind == "agents"
    assert t.agents == (UUID(U1), UUID(U2))  # input order kept
    assert t.tags == ()


def test_uppercase_agent_ids_are_stored_lowercase() -> None:
    t = parse_target({"agents": [U1.upper(), U2]})
    assert stored_target(t, [UUID(U1)])["agents"] == [U1, U2]


def test_tags_form() -> None:
    t = parse_target({"tags": ["a", "b"]})
    assert t.kind == "tags"
    assert t.tags == ("a", "b")
    assert t.agents == ()


def test_all_form() -> None:
    t = parse_target({"all": True})
    assert t == Target("all")
    assert t.agents == () and t.tags == ()


# --- CHK-M9-026: boundaries -------------------------------------------------


def test_agent_count_bounds() -> None:
    assert len(parse_target({"agents": _uuids(1)}).agents) == 1
    assert len(parse_target({"agents": _uuids(10_000)}).agents) == 10_000
    with pytest.raises(InvalidTarget):
        parse_target({"agents": _uuids(10_001)})


def test_tag_count_and_length_bounds() -> None:
    assert len(parse_target({"tags": [f"t{i}" for i in range(32)]}).tags) == 32
    with pytest.raises(InvalidTarget):
        parse_target({"tags": [f"t{i}" for i in range(33)]})
    assert parse_target({"tags": ["x"]}).tags == ("x",)
    assert parse_target({"tags": ["x" * 64]}).tags == ("x" * 64,)
    for bad in ("x" * 65, ""):
        with pytest.raises(InvalidTarget):
            parse_target({"tags": [bad]})


def test_every_allowed_tag_character() -> None:
    assert len(TAG_CHARS) == 66
    both = [TAG_CHARS[:64], TAG_CHARS[64:]]
    assert parse_target({"tags": both}).tags == tuple(both)
    for ch in TAG_CHARS:
        assert parse_target({"tags": [ch]}).tags == (ch,)


@pytest.mark.parametrize(
    "bad",
    ["a b", "a/b", "a,b", "\u00e9", "a\x00", "a\t", "*", "a\n", "a+b", "a@b", "\ud800"],
)
def test_bad_tag_characters(bad: str) -> None:
    with pytest.raises(InvalidTarget):
        parse_target({"tags": [bad]})


# --- CHK-M9-027: refusals ---------------------------------------------------

REFUSED: list[Any] = [
    {},
    {"agents": [U1], "tags": ["a"]},
    {"all": True, "tags": ["a"]},
    {"host": "x"},
    {"ALL": True},
    {"all": False},
    {"all": 1},
    {"all": 1.0},
    {"all": "true"},
    {"all": None},
    {"all": [True]},
    {"agents": []},
    {"tags": []},
    {"agents": [U1, U1]},
    {"tags": ["a", "a"]},
    {"agents": ["x"]},
    {"agents": [U1.replace("-", "")]},  # 32-hex form
    {"agents": ["{" + U1 + "}"]},  # braced
    {"agents": ["urn:uuid:" + U1]},
    {"agents": [U1[:7] + "-" + U1[7] + U1[9:]]},  # hyphen moved
    {"agents": ["1234567_-1234-4234-9234-123456789abc"]},  # int() accepts "_"
    {"agents": [" " + U1[1:]]},
    {"agents": [U1[:-1] + "g"]},
    {"agents": "u"},
    {"tags": "a"},
    {"agents": {U1: 1}},
    {"agents": (U1,)},
    {"tags": [1]},
    {"agents": [1]},
    {"agents": [None]},
    {"tags": [None]},
    None,
    [],
    [{"all": True}],
    "all",
    1,
    True,
]


@pytest.mark.parametrize("value", REFUSED, ids=lambda v: repr(v)[:60])
def test_refused(value: Any) -> None:
    with pytest.raises(InvalidTarget) as info:
        parse_target(value)
    assert isinstance(info.value, ValueError)


# --- CHK-M9-030: one UUID in two letter cases is a duplicate (ruling (3)) ---


def test_case_variant_of_one_uuid_is_a_duplicate() -> None:
    with pytest.raises(InvalidTarget):
        parse_target({"agents": [U1, U1.upper()]})
    upper_first = U1[:4].upper() + U1[4:]
    with pytest.raises(InvalidTarget):
        parse_target({"agents": [upper_first, U1]})


def test_tags_are_case_sensitive_distinct() -> None:
    # The M3 tag rule (#68) compares tags as text.
    assert parse_target({"tags": ["Prod", "prod"]}).tags == ("Prod", "prod")


# --- CHK-M9-028: fixed messages, no input -----------------------------------


@pytest.mark.parametrize(
    "value",
    [
        {"tags": [CANARY + " x"]},
        {"agents": [CANARY]},
        {CANARY: True},
        {"agents": [U1, CANARY]},
        {"all": CANARY},
        {"tags": [CANARY, CANARY]},
    ],
)
def test_messages_name_target_and_quote_no_input(value: Any) -> None:
    with pytest.raises(InvalidTarget) as info:
        parse_target(value)
    text = str(info.value)
    assert "target" in text
    assert CANARY not in text and CANARY not in repr(info.value)
    assert CANARY not in str(info.value.args)


def test_message_set_is_small_and_fixed() -> None:
    messages = set()
    for value in REFUSED:
        with pytest.raises(InvalidTarget) as info:
            parse_target(value)
        messages.add(str(info.value))
    assert all(m.startswith("Invalid request: target") for m in messages), messages
    assert len(messages) <= 4, messages


# --- CHK-M9-029: stored_target ----------------------------------------------


def test_stored_target_agents() -> None:
    t = parse_target({"agents": [U2.upper(), U1]})
    got = stored_target(t, [UUID(U2), UUID(U1)])
    assert got == {"agents": [U2, U1], "resolved_agents": sorted([U1, U2])}


def test_stored_target_tags_and_all() -> None:
    a, b, c = (str(uuid.UUID(int=n)) for n in (3, 1, 2))
    resolved = [UUID(a), UUID(b), UUID(c)]
    assert stored_target(parse_target({"tags": ["web", "db"]}), resolved) == {
        "tags": ["web", "db"],
        "resolved_agents": [b, c, a],
    }
    assert stored_target(parse_target({"all": True}), resolved) == {
        "all": True,
        "resolved_agents": [b, c, a],
    }


def test_stored_target_resolved_is_lowercase_sorted_distinct() -> None:
    ids = [UUID(x) for x in ("ffffffff-0000-4000-8000-000000000000", U2, U1, U2)]
    got = stored_target(parse_target({"all": True}), ids)
    assert got["resolved_agents"] == sorted(
        {U1, U2, "ffffffff-0000-4000-8000-000000000000"}
    )
    assert all(x == x.lower() and len(x) == 36 for x in got["resolved_agents"])


def test_stored_target_round_trips_through_json() -> None:
    for value in ({"agents": [U1]}, {"tags": ["a"]}, {"all": True}):
        got = stored_target(parse_target(value), [UUID(U1)])
        assert json.loads(json.dumps(got)) == got
        assert set(got) == {next(iter(value)), "resolved_agents"}


def test_stored_target_does_not_alias_the_target() -> None:
    t = parse_target({"tags": ["a"]})
    got = stored_target(t, [])
    got["tags"].append("b")
    assert t.tags == ("a",)
    assert stored_target(t, [])["resolved_agents"] == []


def test_target_is_frozen() -> None:
    t = parse_target({"all": True})
    with pytest.raises(FrozenInstanceError):
        t.kind = "tags"  # type: ignore[misc]


# --- CHK-M9-032: the copied tag rule equals M3's (ruling (1)) ---------------


def test_copied_tag_constants_equal_admin() -> None:
    assert targets.TAGS_MAX == admin.MAX_TAGS == 32
    assert targets.MAX_TAG_LENGTH == admin.MAX_TAG_LENGTH == 64
    assert targets.TAG_CHARACTERS == admin.TAG_CHARACTERS
    assert targets.TAG_CHARACTERS == frozenset(TAG_CHARS)
    assert targets.AGENTS_MAX == 10_000


def test_tag_rule_agrees_with_admin_validator() -> None:
    """Every tag the M3 rule accepts, a target accepts, and the reverse, over
    single characters 0-0x2FF and the length bounds."""
    for code in range(0x300):
        tag = chr(code)
        ok_target = True
        try:
            parse_target({"tags": [tag]})
        except InvalidTarget:
            ok_target = False
        assert ok_target is (tag in admin.TAG_CHARACTERS), repr(tag)
