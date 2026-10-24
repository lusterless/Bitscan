"""TASK-069: the redaction-pattern setting through PATCH /settings (TP-M3-23).

Checks CHK-M3-215 to CHK-M3-218 of tests/m3/test-plan.md on PostgreSQL with
the real app. Expected values come from the spec, not the code: TS §8.6 L1324
(RE2 patterns, at most 50; removing a default needs a TOTP session and
alerts), L1329-L1336 (the five defaults, exactly as written, read from the
spec file at test time), TS §8.4 L1290 ("settings or redaction list changed";
"a default redaction pattern removed"), #42 (seeded as a JSON array of the
five strings), #48 (400 invalid_request for every validation error), #71
(settings_changed and redaction_default_removed, one entry per event),
REQ-084 (1)-(4). Lead ruling 2026-10-23: one RE2 compile only, in store.py,
with RE2's log_errors off.
"""

import json
from typing import Any

import pytest

from bitscan_manager.services.settings import redaction

from . import test_settings_api_pg as settings_api
from .test_settings_api_pg import alerts, last_id, settings_entries, state
from .test_settings_service import DEFAULT_PATTERNS
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = settings_api.env  # the M2 users-API environment (admin, sink, clock)
restore = settings_api.restore  # autouse: seeded rows back after each test

ROUTE = "/api/v1/settings"
KEY = "redaction_patterns"


def patch(e: Env, tok: str, patterns: Any) -> Any:
    return e.call("PATCH", tok, ROUTE, json={KEY: patterns})


def stored(e: Env) -> Any:
    with e.conn() as c:
        row = c.execute(
            "SELECT value::text FROM setting WHERE key = 'redaction_patterns'"
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def kinds_after(e: Env, audit_id: int) -> list[tuple[str, Any, Any]]:
    """(action, alert kind, detail) of each entry after audit_id."""
    out: list[tuple[str, Any, Any]] = []
    for action, actor, target, detail in settings_entries(e, audit_id):
        assert actor.startswith("user:") and target == "settings"
        out.append((action, (detail or {}).get("alert_kind"), detail))
    return out


# ------------------------------------------------------------ CHK-M3-215


def test_fifty_valid_patterns_are_stored(env: Env) -> None:
    _, tok = env.admin()
    fifty = [*DEFAULT_PATTERNS, *(rf"\bsecret{i:02d}=\S+" for i in range(45))]
    assert len(fifty) == 50
    r = patch(env, tok, fifty)
    assert r.status_code == 200, r.text
    assert r.json()[KEY] == fifty
    assert stored(env) == fifty
    assert env.call("GET", tok, ROUTE).json()[KEY] == fifty


def test_an_empty_list_is_accepted_and_alerts_every_default(env: Env) -> None:
    """'max 50' gives no minimum; removing all five defaults alerts once."""
    _, tok = env.admin()
    after = last_id(env)
    r = patch(env, tok, [])
    assert r.status_code == 200, r.text
    assert stored(env) == []
    got = kinds_after(env, after)
    assert [(a, k) for a, k, _ in got] == [
        ("settings.change", "settings_changed"),
        ("settings.redaction_default_removed", "redaction_default_removed"),
    ]
    assert got[1][2]["removed"] == list(DEFAULT_PATTERNS)


def _refused() -> list[tuple[str, Any]]:
    good = list(DEFAULT_PATTERNS)
    return [
        ("51", [*good, *(f"p{i}" for i in range(46))]),
        ("backreference", [*good, r"(a)\1"]),
        ("lookahead", [*good, "(?=a)b"]),
        ("lookbehind", [*good, "(?<=a)b"]),
        ("named-backref", [*good, "(?P<n>a)(?P=n)"]),
        ("unclosed", [*good, "[abc"]),
        ("bad-repeat", [*good, "a{2,1}"]),
        ("repeat-over-1000", [*good, "a{1001}"]),
        ("int-item", [*good, 3]),
        ("null-item", [*good, None]),
        ("list-item", [*good, ["x"]]),
        ("object-item", [*good, {"p": "x"}]),
        ("bool-item", [*good, True]),
        ("not-a-list", r"\bbsa_\S+"),
        ("null", None),
        ("object", {"0": "x"}),
        ("nul-in-pattern", [*good, "a\u0000b"]),
    ]


@pytest.mark.parametrize(("name", "value"), _refused(), ids=[n for n, _ in _refused()])
def test_refused_patterns_change_nothing(env: Env, name: str, value: Any) -> None:
    _, tok = env.admin()
    before = state(env)
    counted = (alerts("settings_changed"), alerts("redaction_default_removed"))
    problem(patch(env, tok, value), 400, "invalid_request")
    assert state(env) == before, name
    assert stored(env) == list(DEFAULT_PATTERNS)
    assert (alerts("settings_changed"), alerts("redaction_default_removed")) == counted


def test_lone_surrogate_pattern_is_refused(env: Env) -> None:
    """A JSON lone-surrogate escape cannot be stored (jsonb, UTF-8): 400."""
    _, tok = env.admin()
    before = state(env)
    body = b'{"redaction_patterns": ["a\\ud800b"]}'
    r = env.client.patch(
        ROUTE,
        content=body,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    problem(r, 400, "invalid_request")
    assert state(env) == before


def test_one_bad_pattern_refuses_the_whole_patch(env: Env) -> None:
    _, tok = env.admin()
    before = state(env)
    r = env.call(
        "PATCH", tok, ROUTE, json={"job_pull_seconds": 120, KEY: ["ok", r"(a)\1"]}
    )
    problem(r, 400, "invalid_request")
    assert state(env) == before


def test_removing_a_default_needs_the_totp_session(env: Env) -> None:
    uid, _ = env.admin()
    before = state(env)
    for tok, type_ in (
        (env.token(uid, "api"), "totp_session_required"),
        (env.token(uid, "session", verified=False), "totp_enrolment_required"),
    ):
        problem(patch(env, tok, list(DEFAULT_PATTERNS[:4])), 403, type_)
    assert state(env) == before


# ------------------------------------------------------------ CHK-M3-216


def test_removing_default_three_writes_both_alerts(env: Env) -> None:
    uid, tok = env.admin()
    after = last_id(env)
    counted = (alerts("settings_changed"), alerts("redaction_default_removed"))
    without3 = [p for i, p in enumerate(DEFAULT_PATTERNS) if i != 2]
    r = patch(env, tok, without3)
    assert r.status_code == 200, r.text
    assert r.json()[KEY] == without3
    got = kinds_after(env, after)
    assert [(a, k) for a, k, _ in got] == [
        ("settings.change", "settings_changed"),
        ("settings.redaction_default_removed", "redaction_default_removed"),
    ]
    change, removed = got[0][2], got[1][2]
    assert change["alert"] is True and removed["alert"] is True
    assert change["old"][KEY] == list(DEFAULT_PATTERNS)
    assert change["new"][KEY] == without3
    assert removed["removed"] == [DEFAULT_PATTERNS[2]]
    assert (alerts("settings_changed"), alerts("redaction_default_removed")) == (
        counted[0] + 1,
        counted[1] + 1,
    )
    with env.conn() as c:
        actors = c.execute(
            "SELECT DISTINCT actor FROM audit_log WHERE audit_id > %s", (after,)
        ).fetchall()
    assert actors == [(f"user:{uid}",)]
    # adding a pattern while 3 is still gone: only the settings alert
    after = last_id(env)
    r = patch(env, tok, [*without3, r"\bghp_[A-Za-z0-9]{36}\b"])
    assert r.status_code == 200, r.text
    assert [k for _, k, _ in kinds_after(env, after)] == ["settings_changed"]
    # restoring the five: only the settings alert
    after = last_id(env)
    assert patch(env, tok, list(DEFAULT_PATTERNS)).status_code == 200
    assert [k for _, k, _ in kinds_after(env, after)] == ["settings_changed"]


def test_an_edited_default_counts_as_removed(env: Env) -> None:
    _, tok = env.admin()
    after = last_id(env)
    edited = list(DEFAULT_PATTERNS)
    edited[3] = edited[3].replace("{16}", "{17}")
    assert patch(env, tok, edited).status_code == 200
    got = kinds_after(env, after)
    assert [k for _, k, _ in got] == ["settings_changed", "redaction_default_removed"]
    assert got[1][2]["removed"] == [DEFAULT_PATTERNS[3]]


def test_reordering_the_defaults_removes_nothing(env: Env) -> None:
    _, tok = env.admin()
    after = last_id(env)
    assert patch(env, tok, list(reversed(DEFAULT_PATTERNS))).status_code == 200
    assert [k for _, k, _ in kinds_after(env, after)] == ["settings_changed"]
    assert stored(env) == list(reversed(DEFAULT_PATTERNS))


def test_a_patch_without_the_key_never_alerts_a_removal(env: Env) -> None:
    _, tok = env.admin()
    assert patch(env, tok, list(DEFAULT_PATTERNS[1:])).status_code == 200
    after = last_id(env)
    r = env.call("PATCH", tok, ROUTE, json={"job_pull_seconds": 120})
    assert r.status_code == 200, r.text
    assert [k for _, k, _ in kinds_after(env, after)] == ["settings_changed"]


# ------------------------------------------------------------ CHK-M3-217


def test_defaults_round_trip_byte_for_byte(env: Env) -> None:
    _, tok = env.admin()
    spec = [p.encode() for p in DEFAULT_PATTERNS]  # read from the spec file
    assert [p.encode() for p in redaction.DEFAULT_PATTERNS] == spec
    got = env.call("GET", tok, ROUTE).json()[KEY]
    assert [p.encode() for p in got] == spec
    assert [p.encode() for p in stored(env)] == spec
    r = patch(env, tok, got)  # PATCH back exactly what GET gave
    assert r.status_code == 200, r.text
    assert [p.encode() for p in r.json()[KEY]] == spec
    assert [p.encode() for p in env.call("GET", tok, ROUTE).json()[KEY]] == spec
    assert [p.encode() for p in stored(env)] == spec
    # remove, then restore from the GET text: still byte for byte
    assert patch(env, tok, got[:1]).status_code == 200
    assert patch(env, tok, got).status_code == 200
    assert [p.encode() for p in stored(env)] == spec
