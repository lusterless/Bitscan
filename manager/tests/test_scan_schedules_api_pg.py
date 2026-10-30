"""TASK-206 TEST: CRUD /api/v1/scan-schedules through the API on PostgreSQL
(TP-M9-17; CHK-M9-255 to -257).

Expected values: TS §6.2 L1124 (CRUD /scan-schedules: operator), L1084 (not
sensitive), §6.3 L1133–L1138 (problem details, cursor pages {items,
next_cursor}, 1 MiB cap), §4.4 L557, §4.3 L550, §5.2 L846–L857, L864;
#122 (h), (i) (item shape; POST 201, PATCH 200 with a non-empty subset and
no policy_id, DELETE 204; unknown 404; deleted policy 409; any operator may
change any schedule), #128 (d) (next_run_at = next fire after now), #129 (a);
REQ-212 (1) (no command text in a schedule body), REQ-224.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from . import scan_pg_fixtures as f
from .agent_sim import SCHEDULES, ApiEnv, api_env
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

ITEM_KEYS = {
    "schedule_id",
    "name",
    "policy_id",
    "target",
    "cron",
    "timezone",
    "enabled",
    "last_run_at",
    "next_run_at",
    "created_by",
}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("sched-api")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def cat(env: ApiEnv, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(env.db, env.clock, tmp_path)


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["type"] == type_, body
    return body


def ts(text: str) -> datetime:
    return f.parse_ts(text)


def body_for(pol: f.Pol, **kw: Any) -> dict[str, Any]:
    return {
        "name": "nightly",
        "policy_id": pol.policy_id,
        "target": {"all": True},
        "cron": "0 3 * * *",
    } | kw


def state(env: ApiEnv) -> tuple[Any, ...]:
    with env.conn() as c:
        return f.counts(c), f.checksum(c, "scan_schedule")


# ------------------------------------------------------------ CHK-M9-255


def test_create_list_and_get(env: ApiEnv, cat: f.Catalog) -> None:
    """REQ-224 (1), #122 (h), #128 (d): POST → 201 with exactly the item keys,
    timezone UTC and enabled true by default, created_by the caller and
    next_run_at = the next 03:00 UTC (RFC 3339 Z); list pages by schedule_id
    with {items, next_cursor}; get returns the item."""
    pol = cat.policy(1)
    uid, tok = env.caller("operator", "api")
    now = env.clock.now()
    ids = []
    for i in range(3):
        r = env.call("POST", SCHEDULES, tok, body=body_for(pol, name=f"s{i}"))
        assert r.status_code == 201, r.text
        item = r.json()
        assert set(item) == ITEM_KEYS
        assert (item["timezone"], item["enabled"], item["created_by"]) == (
            "UTC",
            True,
            uid,
        )
        assert item["next_run_at"].endswith("Z") and item["last_run_at"] is None
        assert ts(item["next_run_at"]) == (now + timedelta(days=1)).replace(hour=3)
        ids.append(item["schedule_id"])
    page1 = env.call("GET", f"{SCHEDULES}?limit=2", tok).json()
    assert set(page1) == {"items", "next_cursor"} and len(page1["items"]) == 2
    page2 = env.call(
        "GET", f"{SCHEDULES}?limit=2&cursor={page1['next_cursor']}", tok
    ).json()
    got = [i["schedule_id"] for i in page1["items"] + page2["items"]]
    assert got == sorted(got) and set(ids) <= set(got)
    r = env.call("GET", f"{SCHEDULES}/{ids[1]}", tok)
    assert r.status_code == 200 and r.json()["name"] == "s1"
    problem(env.call("GET", f"{SCHEDULES}/{2**40}", tok), 404, "not_found")
    for bad in ("x", "1.0", "+1", "-1"):
        problem(env.call("GET", f"{SCHEDULES}/{bad}", tok), 400, "invalid_request")
    problem(env.call("GET", f"{SCHEDULES}?cursor=bogus", tok), 400, "invalid_request")


# ------------------------------------------------------------ CHK-M9-256


def test_patch_recomputes_enables_disables_and_refuses_policy_id(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-224 (2), (3), #122 (h): PATCH cron → next_run_at recomputed; PATCH
    timezone → recomputed; enabled false → kept off; enabled true →
    recomputed from now; {"policy_id": …} and {} are 400; a deleted policy's
    schedule cannot be enabled (409) or created (409); a disabled policy's
    schedule is accepted."""
    pol = cat.policy(1)
    uid, tok = env.caller("operator")
    sid = env.call("POST", SCHEDULES, tok, body=body_for(pol)).json()["schedule_id"]
    now = env.clock.now()
    path = f"{SCHEDULES}/{sid}"
    r = env.call("PATCH", path, tok, body={"cron": "30 4 * * *"})
    assert r.status_code == 200 and ts(r.json()["next_run_at"]) == (
        now + timedelta(days=1)
    ).replace(hour=4, minute=30)
    r = env.call("PATCH", path, tok, body={"timezone": "Asia/Kolkata"})
    assert ts(r.json()["next_run_at"]) == now.replace(hour=23, minute=0)  # 04:30 IST
    r = env.call("PATCH", path, tok, body={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    env.clock.advance(days=1)
    tok = env.token(uid)  # a day later: a new session (the old one idled out)
    r = env.call("PATCH", path, tok, body={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert ts(r.json()["next_run_at"]) == env.clock.now().replace(hour=23, minute=0)
    for bad in ({"policy_id": pol.policy_id}, {}, {"name": None}, {"enabled": "yes"}):
        problem(env.call("PATCH", path, tok, body=bad), 400, "invalid_request")
    off = cat.policy(1, status="disabled")
    assert env.call("POST", SCHEDULES, tok, body=body_for(off)).status_code == 201
    gone = cat.policy(1)
    gsid = env.call("POST", SCHEDULES, tok, body=body_for(gone)).json()["schedule_id"]
    cat.delete(gone)
    p = problem(env.call("POST", SCHEDULES, tok, body=body_for(gone)), 409, "conflict")
    assert p["detail"] == "The policy is deleted."
    problem(
        env.call("PATCH", f"{SCHEDULES}/{gsid}", tok, body={"enabled": True}),
        409,
        "conflict",
    )
    problem(
        env.call("POST", SCHEDULES, tok, body=body_for(f.Pol(2**40, "", "", [], 1))),
        404,
        "not_found",
    )


# ------------------------------------------------------------ CHK-M9-257


def test_delete_keeps_scans_and_every_change_writes_one_entry(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-224 (4), (6), TS §5.2 L864, #129 (a): DELETE → 204 (no body); its
    scans keep their rows with schedule_id NULL; a second DELETE is 404;
    create, update and delete each write one scan_schedule.* entry by the
    caller with target scan_schedule:<id>."""
    pol = cat.policy(1)
    uid, tok = env.caller("operator")
    with env.conn() as c:
        mark = f.last_audit(c)
    sid = env.call("POST", SCHEDULES, tok, body=body_for(pol)).json()["schedule_id"]
    env.call("PATCH", f"{SCHEDULES}/{sid}", tok, body={"name": "renamed"})
    with f.owner(env.server) as o:
        scan = f.owner_scan(o, pol, schedule_id=sid, trigger="scheduled")
    r = env.call("DELETE", f"{SCHEDULES}/{sid}", tok)
    assert r.status_code == 204 and r.content == b""
    problem(env.call("DELETE", f"{SCHEDULES}/{sid}", tok), 404, "not_found")
    with env.conn() as c:
        es = f.audit_after(c, mark)
        assert f.scan_row(c, scan)["schedule_id"] is None
    assert [(e["actor"], e["action"], e["target"]) for e in es] == [
        (f"user:{uid}", a, f"scan_schedule:{sid}")
        for a in (
            "scan_schedule.create",
            "scan_schedule.update",
            "scan_schedule.delete",
        )
    ]
    assert es[1]["detail"] == {"name": "renamed"}


def test_roles_and_token_groups(env: ApiEnv, cat: f.Catalog) -> None:
    """REQ-224 (5), #122 (i): a viewer gets 403 on every operation, a bsa_
    token and no token 401; an operator may change and delete another
    operator's schedule; an admin may too."""
    pol = cat.policy(1)
    _, op1 = env.caller("operator")
    _, op2 = env.caller("operator", "api")
    _, adm = env.caller("admin")
    _, viewer = env.caller("viewer")
    agent = env.agent()
    sid = env.call("POST", SCHEDULES, op1, body=body_for(pol)).json()["schedule_id"]
    calls = [
        ("POST", SCHEDULES, body_for(pol)),
        ("GET", SCHEDULES, None),
        ("GET", f"{SCHEDULES}/{sid}", None),
        ("PATCH", f"{SCHEDULES}/{sid}", {"name": "x"}),
        ("DELETE", f"{SCHEDULES}/{sid}", None),
    ]
    before = state(env)
    for method, path, body in calls:
        problem(env.call(method, path, viewer, body=body), 403, "forbidden")
        for tok in (agent.row.token, None):
            assert env.call(method, path, tok, body=body).status_code == 401
    assert state(env) == before
    assert (
        env.call(
            "PATCH", f"{SCHEDULES}/{sid}", op2, body={"name": "theirs"}
        ).status_code
        == 200
    )
    assert (
        env.call("PATCH", f"{SCHEDULES}/{sid}", adm, body={"name": "admin"}).status_code
        == 200
    )
    assert env.call("DELETE", f"{SCHEDULES}/{sid}", op2).status_code == 204


@pytest.mark.parametrize(
    "bad",
    [
        {"cron": "61 * * * *"},
        {"cron": "@daily"},
        {"cron": "0 0 1 * 1"},
        {"timezone": "Mars/Base"},
        {"timezone": "localtime"},
        {"target": {"all": False}},
        {"target": {"agents": ["not-a-uuid"]}},
        {"name": ""},
        {"name": "n" * 129},
        {"name": "a\x00b"},
        {"execute": "id"},
        {"plugins": [{"execute": "id"}]},
        {"command": "id"},
        {"payload": {}},
        {"eval_spec": {}},
        {"policy_id": "1"},
        {"enabled": 1},
    ],
    ids=lambda b: next(iter(b)),
)
def test_bad_bodies_are_400_and_write_nothing(
    env: ApiEnv, cat: f.Catalog, bad: dict[str, Any]
) -> None:
    """REQ-224 (7), REQ-212 (1): a bad cron, time zone, target or name, an
    extra key carrying command text, and wrong types are 400 invalid_request
    on create (and, for the patchable fields, on PATCH); nothing written; the
    answer does not echo the input."""
    pol = cat.policy(1)
    _, tok = env.caller("operator")
    sid = env.call("POST", SCHEDULES, tok, body=body_for(pol)).json()["schedule_id"]
    before = state(env)
    p = problem(
        env.call("POST", SCHEDULES, tok, body=body_for(pol, **bad)),
        400,
        "invalid_request",
    )
    for v in bad.values():
        if isinstance(v, str) and len(v) > 3:
            assert v not in json.dumps(p)
    if next(iter(bad)) in (
        "cron",
        "timezone",
        "target",
        "name",
        "execute",
        "policy_id",
        "enabled",
    ):
        problem(
            env.call("PATCH", f"{SCHEDULES}/{sid}", tok, body=bad),
            400,
            "invalid_request",
        )
    assert state(env) == before


def test_a_body_over_1_mib_is_413(env: ApiEnv, cat: f.Catalog) -> None:
    """TS §6.3 L1138."""
    pol = cat.policy(1)
    _, tok = env.caller("operator")
    raw = json.dumps(body_for(pol)).encode()
    before = state(env)
    problem(
        env.call("POST", SCHEDULES, tok, content=raw + b" " * (1_048_577 - len(raw))),
        413,
        "too_large",
    )
    assert state(env) == before
