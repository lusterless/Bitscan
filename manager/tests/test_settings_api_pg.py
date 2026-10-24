"""TASK-062: GET and PATCH /api/v1/settings through the API on PostgreSQL.

Checks CHK-M3-150 to CHK-M3-156 of tests/m3/test-plan.md (TP-M3-16). Expected
values: TS §6.2 L1126 (GET admin; PATCH admin with a TOTP session), L1084
(settings are a sensitive action: API tokens refused), L1129 (no inventory
switch), TS §8.6 L1317-L1327 (keys, defaults, ranges), TS §5.3 L1051 (refused
after 15 minutes of sink outage), #42, #48, #68 (one object of seven keys; a
non-empty partial patch), #71 (settings.change with the settings_changed alert,
one entry per event), REQ-083 (1)-(6). Every test restores the seeded rows as
owner, so later tests see the defaults.
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token
from bitscan_manager.services.audit import REGISTRY

from . import test_users_api_pg as users_api
from .conftest import PgServer
from .test_settings_service import DEFAULT_PATTERNS, SPEC_DEFAULTS, SPEC_RANGES
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env  # the M2 users-API environment fixture (admin, sink, clock)

ROUTE = "/api/v1/settings"
KEYS = [
    "agent_token_ttl_days",
    "job_pull_seconds",
    "decommission_after_days",
    "redaction_patterns",
    "max_parallel_plugins",
    "enrolment_alert_per_hour",
    "inventory_interval_s",
]
DEFAULTS = {**SPEC_DEFAULTS, "redaction_patterns": DEFAULT_PATTERNS}
CANARY = "CANARY-62a1b2c3d4e5f607"


@pytest.fixture(autouse=True)
def restore(migrated_db: PgServer) -> Iterator[None]:
    with migrated_db.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        rows = oc.execute(
            "SELECT key, value, updated_by, updated_at FROM setting"
        ).fetchall()
        sched = oc.execute(
            "SELECT job_kind, interval_s FROM system_schedule"
        ).fetchall()
    yield
    with migrated_db.connect("bitscan_migrate") as oc:
        oc.execute("SET ROLE bitscan_owner")
        for key, value, by, at in rows:
            oc.execute(
                "UPDATE setting SET value = %s, updated_by = %s, updated_at = %s"
                " WHERE key = %s",
                (Jsonb(value), by, at, key),
            )
        for kind, interval in sched:
            oc.execute(
                "UPDATE system_schedule SET interval_s = %s WHERE job_kind = %s",
                (interval, kind),
            )


def state(e: Env) -> tuple[Any, ...]:
    with e.conn() as c:
        s = c.execute(
            "SELECT key, value, updated_by, updated_at FROM setting ORDER BY key"
        )
        sched = c.execute("SELECT job_kind, interval_s FROM system_schedule ORDER BY 1")
        audit = c.execute("SELECT count(*), max(audit_id) FROM audit_log")
        return s.fetchall(), sched.fetchall(), audit.fetchone()


def settings_entries(e: Env, after_id: int) -> list[tuple[Any, ...]]:
    with e.conn() as c:
        return c.execute(
            "SELECT action, actor, target, detail FROM audit_log"
            " WHERE audit_id > %s ORDER BY audit_id",
            (after_id,),
        ).fetchall()


def last_id(e: Env) -> int:
    with e.conn() as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


def alerts(kind: str) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


# ------------------------------------------------------------ CHK-M3-150


def test_get_returns_the_seeded_defaults(env: Env) -> None:
    uid, session = env.admin()
    api = env.token(uid, "api")
    for tok in (session, api):  # admin session or admin API token
        r = env.call("GET", api if tok == api else session, ROUTE)
        assert r.status_code == 200, r.text
        body = r.json()
        assert list(body) == KEYS  # the TS §8.6 order, one object (#68)
        assert body == DEFAULTS
        assert [p.encode() for p in body["redaction_patterns"]] == [
            p.encode() for p in DEFAULT_PATTERNS
        ]


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_get_is_admin_only(env: Env, role: str) -> None:
    uid = env.user(role, totp=True)
    problem(env.call("GET", env.token(uid), ROUTE), 403, "forbidden")
    problem(env.call("GET", env.token(uid, "api"), ROUTE), 403, "forbidden")


def test_get_refuses_no_token_and_agent_tokens(env: Env) -> None:
    problem(env.client.get(ROUTE), 401, "unauthorized")
    for kind in (AgentTokenKind.AGENT, AgentTokenKind.ENROLMENT):
        problem(env.call("GET", new_agent_token(kind), ROUTE), 401, "unauthorized")


# ------------------------------------------------------------ CHK-M3-151


@pytest.mark.parametrize("key", sorted(SPEC_RANGES))
@pytest.mark.parametrize("end", [0, 1], ids=["min", "max"])
def test_patch_each_key_at_its_bounds(env: Env, key: str, end: int) -> None:
    _, tok = env.admin()
    value = SPEC_RANGES[key][end]
    r = env.call("PATCH", tok, ROUTE, json={key: value})
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == KEYS
    assert body == {**DEFAULTS, key: value}
    assert env.call("GET", tok, ROUTE).json() == body
    with env.conn() as c:
        if key == "inventory_interval_s":
            row = c.execute(
                "SELECT interval_s FROM system_schedule WHERE job_kind = 'inventory'"
            ).fetchone()
            assert row == (value,)
            keys = {r[0] for r in c.execute("SELECT key FROM setting").fetchall()}
            assert "inventory_interval_s" not in keys  # never a setting row
        else:
            row = c.execute(
                "SELECT value FROM setting WHERE key = %s", (key,)
            ).fetchone()
            assert row == (value,)


def test_patch_every_key_at_once(env: Env) -> None:
    uid, tok = env.admin()
    patch: dict[str, Any] = {k: v[1] for k, v in SPEC_RANGES.items()}
    patch["redaction_patterns"] = DEFAULT_PATTERNS[:2]
    r = env.call("PATCH", tok, ROUTE, json=patch)
    assert r.status_code == 200, r.text
    assert r.json() == {k: patch[k] for k in KEYS}
    with env.conn() as c:
        rows = c.execute("SELECT updated_by, updated_at FROM setting").fetchall()
    assert {row for row in rows} == {(uid, env.clock.now())}


# ------------------------------------------------------------ CHK-M3-152


def _bad_bodies() -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for key, (low, high) in SPEC_RANGES.items():
        out += [(f"{key}-below", {key: low - 1}), (f"{key}-above", {key: high + 1})]
        out += [(f"{key}-true", {key: True}), (f"{key}-float", {key: 1.5})]
        out += [(f"{key}-string", {key: str(low)}), (f"{key}-null", {key: None})]
    out += [
        ("inventory_enabled", {"inventory_enabled": False}),
        (
            "inventory_enabled-with-valid",
            {"job_pull_seconds": 120, "inventory_enabled": True},
        ),
        ("unknown-canary", {CANARY: 1}),
        ("mixed-range", {"job_pull_seconds": 120, "max_parallel_plugins": 9}),
        ("mixed-pattern", {"job_pull_seconds": 120, "redaction_patterns": [r"(a)\1"]}),
        ("mixed-null", {"job_pull_seconds": 120, "max_parallel_plugins": None}),
        ("empty", {}),
        ("array", [{"job_pull_seconds": 120}]),
        ("patterns-51", {"redaction_patterns": [f"p{i}" for i in range(51)]}),
        ("patterns-not-list", {"redaction_patterns": "x"}),
        ("patterns-int-item", {"redaction_patterns": ["ok", 3]}),
        ("patterns-re2-invalid", {"redaction_patterns": ["(?=x)"]}),
    ]
    return out


BAD = _bad_bodies()


@pytest.mark.parametrize("body", [b for _, b in BAD], ids=[n for n, _ in BAD])
def test_invalid_patches_change_nothing(env: Env, body: Any) -> None:
    """REQ-083 (2), (3): 400 invalid_request, no row, no audit entry, no alert."""
    _, tok = env.admin()
    before = state(env)
    count = alerts("settings_changed")
    r = env.call("PATCH", tok, ROUTE, json=body)
    problem(r, 400, "invalid_request")
    assert CANARY not in r.text  # an unknown key is never echoed
    assert state(env) == before
    assert alerts("settings_changed") == count


def test_inventory_interval_3599_is_400_not_500(env: Env) -> None:
    """CHK-M3-354: the service refuses before the database CHECK can raise."""
    _, tok = env.admin()
    for value in (3599, 86_401):
        problem(
            env.call("PATCH", tok, ROUTE, json={"inventory_interval_s": value}),
            400,
            "invalid_request",
        )
    r = env.call("PATCH", tok, ROUTE, json={"inventory_interval_s": 3600})
    assert r.status_code == 200 and r.json()["inventory_interval_s"] == 3600


def test_malformed_json_is_400(env: Env) -> None:
    _, tok = env.admin()
    before = state(env)
    r = env.client.patch(
        ROUTE,
        content=b'{"job_pull_seconds": ',
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    problem(r, 400, "invalid_request")
    assert state(env) == before


# ------------------------------------------------------------ CHK-M3-153


def test_one_audit_and_alert_entry_with_old_and_new(env: Env) -> None:
    """REQ-083 (4), #71: one settings.change entry, which is the alert entry."""
    uid, tok = env.admin()
    start = last_id(env)
    count = alerts("settings_changed")
    r = env.call(
        "PATCH",
        tok,
        ROUTE,
        json={"job_pull_seconds": 120, "inventory_interval_s": 7200},
    )
    assert r.status_code == 200, r.text
    rows = settings_entries(env, start)
    assert len(rows) == 1, rows
    action, actor, target, detail = rows[0]
    assert (action, actor, target) == ("settings.change", f"user:{uid}", "settings")
    assert detail["alert"] is True and detail["alert_kind"] == "settings_changed"
    assert detail["old"] == {"job_pull_seconds": 300, "inventory_interval_s": 21_600}
    assert detail["new"] == {"job_pull_seconds": 120, "inventory_interval_s": 7200}
    assert alerts("settings_changed") == count + 1  # counted after commit
    # a second patch writes a second entry with the new old values
    env.call("PATCH", tok, ROUTE, json={"job_pull_seconds": 60})
    rows = settings_entries(env, start)
    assert len(rows) == 2 and rows[1][3]["old"] == {"job_pull_seconds": 120}


def test_patterns_change_detail_holds_lists(env: Env) -> None:
    _, tok = env.admin()
    start = last_id(env)
    new = [*DEFAULT_PATTERNS, r"\bmysecret=\S+"]
    assert (
        env.call("PATCH", tok, ROUTE, json={"redaction_patterns": new}).status_code
        == 200
    )
    (row,) = settings_entries(env, start)
    assert row[3]["old"] == {"redaction_patterns": DEFAULT_PATTERNS}
    assert row[3]["new"] == {"redaction_patterns": new}


# ------------------------------------------------------------ CHK-M3-154


def test_patch_refused_for_api_tokens_unverified_and_lower_roles(env: Env) -> None:
    """REQ-083 (5); CHK-M3-331 (admin bsk_ patches settings)."""
    uid, _ = env.admin()
    api = env.token(uid, "api")
    unverified = env.token(uid, verified=False)
    op = env.token(env.user("operator", totp=True))
    viewer = env.token(env.user("viewer", totp=True))
    before = state(env)
    body = {"job_pull_seconds": 120}
    problem(env.call("PATCH", api, ROUTE, json=body), 403, "totp_session_required")
    problem(
        # an admin session that is not TOTP-verified is the M2 restricted
        # session (REQ-046 (d)), answered 403 totp_enrolment_required (#48)
        env.call("PATCH", unverified, ROUTE, json=body),
        403,
        "totp_enrolment_required",
    )
    problem(env.call("PATCH", op, ROUTE, json=body), 403, "forbidden")
    problem(env.call("PATCH", viewer, ROUTE, json=body), 403, "forbidden")
    problem(env.client.patch(ROUTE, json=body), 401, "unauthorized")
    assert state(env) == before
    # GET still works with the admin API token (REQ-083 (5))
    assert env.call("GET", api, ROUTE).status_code == 200


def test_patch_refused_during_the_sink_outage(env: Env) -> None:
    """TS §5.3 L1051; CHK-M3-328 (sink_gate=False on PATCH /settings)."""
    _, tok = env.admin()
    env.sink.up = False
    env.shipper.run_once()
    start = env.clock.now()
    env.clock.at = start + timedelta(minutes=15)
    before = state(env)
    problem(
        env.call("PATCH", tok, ROUTE, json={"job_pull_seconds": 120}),
        503,
        "audit_sink_unavailable",
    )
    assert state(env) == before
    env.sink.up = True
    for _ in range(5):
        env.clock.at += timedelta(seconds=31)
        env.shipper.run_once()
    assert (
        env.call("PATCH", tok, ROUTE, json={"job_pull_seconds": 120}).status_code == 200
    )


# ------------------------------------------------------------ CHK-M3-155


def test_ttl_change_leaves_existing_tokens(env: Env) -> None:
    """REQ-083 (6): only tokens issued or rotated afterwards use the new TTL."""
    _, tok = env.admin()
    with env.conn() as c:
        row = c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status) VALUES (md5(random()::text),"
            " 'h', '1', md5(random()::text) || md5(random()::text), now(),"
            " now() + interval '365 days', 'online')"
            " RETURNING agent_id, token_expires_at"
        ).fetchone()
    assert row is not None
    assert (
        env.call("PATCH", tok, ROUTE, json={"agent_token_ttl_days": 60}).status_code
        == 200
    )
    with env.conn() as c:
        after = c.execute(
            "SELECT token_expires_at FROM agent WHERE agent_id = %s", (row[0],)
        ).fetchone()
    assert after == (row[1],)


# ------------------------------------------------------------ CHK-M3-156


def test_openapi_documents_both_operations_without_422() -> None:
    doc = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text("utf-8")
    )
    ops = doc["paths"][ROUTE]
    assert set(ops) == {"get", "patch"}
    for method, op in ops.items():
        assert "422" not in op["responses"], method
        for status in ("401", "403"):
            assert "application/problem+json" in op["responses"][status]["content"]
    assert "400" in ops["patch"]["responses"]
    assert "application/problem+json" in ops["patch"]["responses"]["400"]["content"]
    text = json.dumps(doc)
    assert "inventory_enabled" not in text
    assert "HTTPValidationError" not in text


def test_live_app_matches_the_committed_document() -> None:
    assert create_app().openapi() == json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text("utf-8")
    )


def test_concurrent_patches_both_apply_in_turn(env: Env) -> None:
    import threading

    _, tok = env.admin()
    start = last_id(env)
    results: list[int] = []

    def go(v: int) -> None:
        results.append(
            env.call("PATCH", tok, ROUTE, json={"job_pull_seconds": v}).status_code
        )

    ts = [threading.Thread(target=go, args=(v,)) for v in (61, 62)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert results == [200, 200]
    rows = settings_entries(env, start)
    assert len(rows) == 2
    # serialised: the second entry's old value is the first entry's new value
    assert (
        rows[1][3]["old"]["job_pull_seconds"] == rows[0][3]["new"]["job_pull_seconds"]
    )
