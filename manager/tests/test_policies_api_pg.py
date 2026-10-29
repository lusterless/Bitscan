"""TP-M7-21 (TASK-161): GET /policies, GET and PATCH /policies/{id} on PostgreSQL.

CHK-M7-250, -251, -282 (tests/m7/test-plan.md). Expected values: TS §6.2
L1100 to L1102 (viewer reads; admin PATCH with session or API token), §4.3
L546 to L548, §6.3 L1133 to L1141 (problem+json, cursor pagination, max 500,
catalog ids are integers, stored text returned as stored), §6 L1056 (user
routes take only bsu_ and bsk_); REQ-168 (1) to (5), REQ-169 (1) to (5),
REQ-174 (2); #9 (no deleted policy in the list; `?status=deleted` is 400; the
detail shows `deleted_at`), #98 (a) to (c), #101 (`policy.status_change`
every PATCH, `policy_reenabled` on a re-enable). Policies are built through
the TASK-151 store.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token
from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.services.audit.metrics import REGISTRY

from . import test_users_api_pg as users_api
from .catalog_rows import T1, app, tag
from .test_import_store_pg import cand, cp, ok, server_t, upload_t
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env
ROUTE = "/api/v1/policies"
ITEM_KEYS = [
    "policy_id", "policy_name", "policy_description", "policy_status", "file_status",
    "status_overridden", "family_id", "family_name", "format_version", "version",
    "source_file", "plugin_count", "imported_at", "updated_at",
]  # fmt: skip
PLUGIN_KEYS = [
    "plugin_uuid", "sort_order", "display_name", "plugin_name", "control_ref",
    "plugin_description", "execute", "execute_sha256", "operator", "expected_result",
    "timeout_s", "state", "updated_at",
]  # fmt: skip
HOSTILE = '<script>alert("x")</script> ‮ é \\ \' " & \x01 🛡'


def make(e: Env, **kw: Any) -> Any:
    deleted = kw.pop("deleted", False)
    plugins = kw.pop("plugins", None)
    with app(e.server) as s, s.transaction():
        r = ok(s, cand(plugins, **kw), upload_t())
        if deleted:
            assert adm.soft_delete_effects(s, r.policy_id, T1) is not None
    return r


def viewer(e: Env, kind: str = "api") -> str:
    return e.token(e.user("viewer"), kind)


def alerts(kind: str) -> float:
    v = REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind})
    return 0.0 if v is None else v


def audit(e: Env, pid: int) -> list[tuple[str, Any]]:
    with e.conn() as c:
        return [
            (a, d)
            for a, d in c.execute(
                "SELECT action, detail FROM audit_log WHERE target = %s"
                " ORDER BY audit_id",
                (f"policy:{pid}",),
            ).fetchall()
        ]


def walk(e: Env, tok: str, limit: int, **params: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10_000):
        q = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        r = e.call("GET", tok, ROUTE, params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"items", "next_cursor"}
        assert len(body["items"]) <= limit
        out += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return out
    pytest.fail("paging never ended")


# CHK-M7-251: REQ-169 ----------------------------------------------------------


def test_list_holds_live_policies_and_filters_by_status(env: Env) -> None:
    t = tag()
    for i in range(3):
        make(env, policy_name=f"m7api-{t}-e{i}")
    make(env, policy_name=f"m7api-{t}-d0", file_status="disabled")
    d1 = make(env, policy_name=f"m7api-{t}-d1")
    with app(env.server) as s, s.transaction():
        assert adm.set_status(s, d1.policy_id, "disabled", T1)  # effective status
    make(env, policy_name=f"m7api-{t}-x0", deleted=True)
    tok = viewer(env)

    def mine(items: list[dict[str, Any]]) -> list[str]:
        return sorted(
            i["policy_name"]
            for i in items
            if i["policy_name"].startswith(f"m7api-{t}-")
        )

    assert len(mine(walk(env, tok, 500))) == 5
    assert mine(walk(env, tok, 500, status="enabled")) == [
        f"m7api-{t}-e{i}" for i in range(3)
    ]
    assert mine(walk(env, tok, 500, status="disabled")) == [
        f"m7api-{t}-d0",
        f"m7api-{t}-d1",
    ]


@pytest.mark.parametrize("status", ["deleted", "ENABLED", "", "enabled,disabled"])
def test_unknown_status_filter_is_400(env: Env, status: str) -> None:
    problem(
        env.call("GET", viewer(env), ROUTE, params={"status": status}),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize("n", [1, 2, 5])
def test_paging_shows_each_policy_once_in_name_order(env: Env, n: int) -> None:
    t = tag()
    names = [f"m7pg-{t}-{i:02d}" for i in range(n + 1)]
    for name in reversed(names):
        make(env, policy_name=name)
    items = walk(env, viewer(env), n)
    ids = [i["policy_id"] for i in items]
    assert len(ids) == len(set(ids))
    assert [
        i["policy_name"] for i in items if i["policy_name"].startswith(f"m7pg-{t}-")
    ] == names


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"cursor": "x"}, {"cursor": "W10"}, {"limit": "a"}],
)
def test_bad_paging_is_400(env: Env, params: dict[str, Any]) -> None:
    problem(env.call("GET", viewer(env), ROUTE, params=params), 400, "invalid_request")


def test_a_cursor_from_another_route_is_refused(env: Env) -> None:
    uid, admin = env.admin()
    for _ in range(3):
        env.user("viewer")
    other = env.call("GET", admin, "/api/v1/users", params={"limit": 1}).json()
    assert other["next_cursor"]
    problem(
        env.call("GET", viewer(env), ROUTE, params={"cursor": other["next_cursor"]}),
        400,
        "invalid_request",
    )


def test_item_and_detail_shapes_order_and_display_names(env: Env) -> None:
    fam = f"CIS {tag()}"
    a, b, c = (
        cp(plugin_name="1.1 - First"),
        cp(plugin_name="2.1 - Second"),
        cp(plugin_name="3 - Third"),
    )
    r = make(env, family_name=fam, plugins=[c, a, b])
    tok = viewer(env)
    item = next(i for i in walk(env, tok, 500) if i["policy_id"] == r.policy_id)
    assert list(item) == ITEM_KEYS
    assert (
        type(item["policy_id"]) is int and type(item["family_id"]) is int
    )  # §6.3 L1139
    assert item["plugin_count"] == 3 and item["family_name"] == fam
    assert item["imported_at"].endswith("Z") and item["updated_at"].endswith("Z")
    d = env.call("GET", tok, f"{ROUTE}/{r.policy_id}")
    assert d.status_code == 200, d.text
    body = d.json()
    assert list(body) == [*ITEM_KEYS, "deleted_at", "plugins"]
    assert body["deleted_at"] is None
    assert {k: body[k] for k in ITEM_KEYS} == item
    assert [p["plugin_uuid"] for p in body["plugins"]] == [
        str(x.plugin_uuid) for x in (c, a, b)
    ]
    assert [p["sort_order"] for p in body["plugins"]] == [1, 2, 3]
    assert all(list(p) == PLUGIN_KEYS for p in body["plugins"])
    assert body["plugins"][1]["display_name"] == f"{fam} - 1.1 - First"
    assert (
        body["plugins"][0]["execute"] == c.execute
    )  # every role sees execute (#98 (b))


def test_deleted_policy_detail_shows_deleted_at(env: Env) -> None:
    r = make(env, deleted=True)
    body = env.call("GET", viewer(env), f"{ROUTE}/{r.policy_id}").json()
    assert (
        body["deleted_at"].endswith("Z")
        and body["source_file"] == f"deleted/{r.policy_id}"
    )
    assert len(body["plugins"]) == 1


@pytest.mark.parametrize(
    "bad", ["abc", "+1", "1.0", "1_0", "-1", "%201", "1e3", "1" * 21, "١"]
)
def test_non_integer_ids_are_400(env: Env, bad: str) -> None:
    problem(env.call("GET", viewer(env), f"{ROUTE}/{bad}"), 400, "invalid_request")


@pytest.mark.parametrize("unknown", ["0", str(2**62), str(2**63), "9" * 20])
def test_unknown_ids_are_404(env: Env, unknown: str) -> None:
    problem(env.call("GET", viewer(env), f"{ROUTE}/{unknown}"), 404, "not_found")


def test_hostile_text_comes_back_byte_identical(env: Env) -> None:
    r = make(
        env,
        policy_name=HOSTILE + tag(),
        policy_description=HOSTILE,
        family_name=HOSTILE + tag(),
        plugins=[
            cp(
                plugin_name=HOSTILE,
                plugin_description=HOSTILE,
                execute=HOSTILE,
                expected_result=HOSTILE,
            )
        ],
    )
    resp = env.call("GET", viewer(env), f"{ROUTE}/{r.policy_id}")
    body = resp.json()
    assert resp.headers["content-type"].startswith("application/json")
    assert (
        body["policy_name"].startswith(HOSTILE)
        and body["policy_description"] == HOSTILE
    )
    p = body["plugins"][0]
    assert (
        p["plugin_name"]
        == p["execute"]
        == p["expected_result"]
        == p["plugin_description"]
        == HOSTILE
    )


@pytest.mark.parametrize("kind", ["api", "session"])
def test_viewer_reads_with_either_token(env: Env, kind: str) -> None:
    r = make(env)
    tok = viewer(env, kind)
    assert env.call("GET", tok, ROUTE, params={"limit": 1}).status_code == 200
    assert env.call("GET", tok, f"{ROUTE}/{r.policy_id}").status_code == 200


# CHK-M7-282: route group (REQ-174 (2)) ----------------------------------------


@pytest.mark.parametrize("token", ["agent", "enrolment", "none", "garbage"])
def test_agent_tokens_and_no_token_get_401_on_every_operation(
    env: Env, token: str
) -> None:
    r = make(env)
    tok = {
        "agent": new_agent_token(AgentTokenKind.AGENT),
        "enrolment": new_agent_token(AgentTokenKind.ENROLMENT),
        "none": "",
        "garbage": "bsu_" + "x" * 43,
    }[token]
    before = audit(env, r.policy_id)
    for method, path, kw in [
        ("GET", ROUTE, {}),
        ("GET", f"{ROUTE}/{r.policy_id}", {}),
        ("PATCH", f"{ROUTE}/{r.policy_id}", {"json": {"policy_status": "disabled"}}),
    ]:
        resp = env.client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {tok}"} if tok else {},
            **kw,
        )
        problem(resp, 401, resp.json()["type"])
        assert resp.json()["type"] != "about:blank" or resp.status_code == 401
    assert audit(env, r.policy_id) == before


# CHK-M7-250: REQ-168 ----------------------------------------------------------


def state(env: Env, pid: int) -> tuple[str, str, bool]:
    with env.conn() as c:
        row = c.execute(
            "SELECT policy_status::text, file_status::text, status_overridden"
            " FROM policy"
            " WHERE policy_id = %s",
            (pid,),
        ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def patch(env: Env, tok: str, pid: int, body: Any, **kw: Any) -> Any:
    return env.call("PATCH", tok, f"{ROUTE}/{pid}", json=body, **kw)


@pytest.mark.parametrize("kind", ["session", "api"])
def test_each_body_sets_the_stated_columns(env: Env, kind: str) -> None:
    r = make(env)  # file enabled
    uid = env.user("admin", totp=True)
    tok = env.token(uid, kind)
    resp = patch(env, tok, r.policy_id, {"policy_status": "disabled"})
    assert resp.status_code == 200, resp.text
    assert list(resp.json()) == ITEM_KEYS
    assert (resp.json()["policy_status"], resp.json()["status_overridden"]) == (
        "disabled",
        True,
    )
    assert state(env, r.policy_id) == ("disabled", "enabled", True)
    assert patch(env, tok, r.policy_id, {"policy_status": "enabled"}).status_code == 200
    assert state(env, r.policy_id) == ("enabled", "enabled", True)
    assert patch(env, tok, r.policy_id, {"status_overridden": False}).status_code == 200
    assert state(env, r.policy_id) == ("enabled", "enabled", False)
    actions = [a for a, _ in audit(env, r.policy_id)]
    assert actions.count("policy.status_change") == 3  # every PATCH is audited
    entries = [d for a, d in audit(env, r.policy_id) if a == "policy.status_change"]
    assert all(e["by"] == "patch" for e in entries)
    with env.conn() as c:
        actor = c.execute(
            "SELECT DISTINCT actor FROM audit_log WHERE target = %s AND action = %s",
            (f"policy:{r.policy_id}", "policy.status_change"),
        ).fetchall()
    assert actor == [(f"user:{uid}",)]


@pytest.mark.parametrize(
    "body",
    [
        {"status_overridden": True},
        {"execute": "x"},
        {"policy_status": "disabled", "status_overridden": False},
        {},
        {"policy_status": "on"},
        {"policy_status": "Enabled"},
        {"policy_status": None},
        {"status_overridden": None},
        {"status_overridden": "false"},
        {"status_overridden": 0},
        {"policy_status": "disabled", "plugins": []},
        [],
        "disabled",
        None,
    ],
)
def test_other_bodies_are_400_and_change_nothing(env: Env, body: Any) -> None:
    r = make(env)
    _, tok = env.admin()
    before = (state(env, r.policy_id), audit(env, r.policy_id))
    problem(patch(env, tok, r.policy_id, body), 400, "invalid_request")
    assert (state(env, r.policy_id), audit(env, r.policy_id)) == before


def test_non_json_body_is_400(env: Env) -> None:
    r = make(env)
    _, tok = env.admin()
    resp = env.client.request(
        "PATCH",
        f"{ROUTE}/{r.policy_id}",
        content=b"policy_status=disabled",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "text/plain"},
    )
    problem(resp, 400, "invalid_request")
    assert state(env, r.policy_id) == ("enabled", "enabled", False)


def test_reenable_alerts_and_disable_does_not(env: Env) -> None:
    r = make(env, file_status="disabled")
    _, tok = env.admin()
    n0 = alerts("policy_reenabled")
    assert patch(env, tok, r.policy_id, {"policy_status": "enabled"}).status_code == 200
    assert alerts("policy_reenabled") == n0 + 1
    assert (
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}).status_code == 200
    )
    assert alerts("policy_reenabled") == n0 + 1
    assert (
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}).status_code == 200
    )  # no-op
    assert alerts("policy_reenabled") == n0 + 1
    kinds = [
        d.get("alert_kind")
        for a, d in audit(env, r.policy_id)
        if a == "policy.status_change"
    ]
    assert kinds == ["policy_reenabled", None, None]


def test_clearing_an_override_onto_an_enabled_file_alerts(env: Env) -> None:
    r = make(env)  # file enabled
    _, tok = env.admin()
    assert (
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}).status_code == 200
    )
    n0 = alerts("policy_reenabled")
    resp = patch(env, tok, r.policy_id, {"status_overridden": False})
    assert resp.status_code == 200 and resp.json()["policy_status"] == "enabled"
    assert alerts("policy_reenabled") == n0 + 1
    # clearing onto a disabled file is not a re-enable
    q = make(env, file_status="disabled")
    assert patch(env, tok, q.policy_id, {"policy_status": "enabled"}).status_code == 200
    n1 = alerts("policy_reenabled")
    assert patch(env, tok, q.policy_id, {"status_overridden": False}).status_code == 200
    assert state(env, q.policy_id) == ("disabled", "disabled", False)
    assert alerts("policy_reenabled") == n1


def test_deleted_is_409_and_unknown_404(env: Env) -> None:
    r = make(env, deleted=True)
    _, tok = env.admin()
    before = audit(env, r.policy_id)
    problem(patch(env, tok, r.policy_id, {"policy_status": "enabled"}), 409, "conflict")
    assert audit(env, r.policy_id) == before
    problem(patch(env, tok, 2**62, {"policy_status": "enabled"}), 404, "not_found")
    problem(patch(env, tok, 0, {"policy_status": "enabled"}), 404, "not_found")
    problem(
        env.call("PATCH", tok, f"{ROUTE}/x", json={"policy_status": "enabled"}),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("viewer", "api"),
        ("viewer", "session"),
        ("operator", "session"),
        ("operator", "api"),
    ],
)
def test_non_admins_get_403_and_change_nothing(env: Env, role: str, kind: str) -> None:
    r = make(env)
    tok = env.token(env.user(role), kind)
    problem(
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}), 403, "forbidden"
    )
    assert state(env, r.policy_id) == ("enabled", "enabled", False)


def test_restricted_admin_session_gets_totp_enrolment_required(env: Env) -> None:
    r = make(env)
    tok = env.token(env.user("admin", totp=False), "session", verified=False)
    problem(
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}),
        403,
        "totp_enrolment_required",
    )
    problem(env.call("GET", tok, ROUTE), 403, "totp_enrolment_required")


def test_file_import_after_a_patch_disable_stays_disabled(env: Env) -> None:
    c = cand()
    t = server_t(f"{tag()}.bit")
    with app(env.server) as s, s.transaction():
        r = ok(s, c, t)
    _, tok = env.admin()
    assert (
        patch(env, tok, r.policy_id, {"policy_status": "disabled"}).status_code == 200
    )
    with app(env.server) as s, s.transaction():
        ok(s, replace(c, policy_description="v2"), replace(t, file_sha256="e" * 64))
    assert state(env, r.policy_id) == ("disabled", "enabled", True)
    body = env.call("GET", tok, f"{ROUTE}/{r.policy_id}").json()
    assert (body["policy_status"], body["version"]) == ("disabled", 2)


def test_patch_never_touches_plugins(env: Env) -> None:
    p = cp()
    r = make(env, plugins=[p])
    _, tok = env.admin()
    with env.conn() as c:
        before = c.execute(
            "SELECT * FROM plugin WHERE plugin_uuid = %s", (p.plugin_uuid,)
        ).fetchone()
    patch(env, tok, r.policy_id, {"policy_status": "disabled"})
    patch(env, tok, r.policy_id, {"execute": "rm -rf /"})
    with env.conn() as c:
        after = c.execute(
            "SELECT * FROM plugin WHERE plugin_uuid = %s", (p.plugin_uuid,)
        ).fetchone()
    assert after == before
