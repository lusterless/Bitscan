"""TP-M7-24 (TASK-163): DELETE /api/v1/policies/{id} on PostgreSQL.

CHK-M7-271, -282, -341, -343, -346 (tests/m7/test-plan.md). Expected values
come from the spec and the approved answers, not from the code: TS §6.2 L1104
(admin, TOTP session), L1084 (API tokens refused for TOTP-session actions),
§4.3 L550 (soft delete: `deleted_at`, `source_file` `deleted/<id>`, queued
jobs cancelled, schedules disabled, plugins retired, the uploaded file
removed; audit-logged and alerting; a server-folder policy is 409
`policy_managed_on_server`), §5.3 L1051 (sensitive actions refused after 15
minutes of sink outage until the queue drains), §6 L1056 (user routes take
only bsu_ and bsk_), §6.3 (problem+json); REQ-171 (1)-(4), REQ-167 (1)-(3)
through the route, REQ-174 (2); #1 (agreed: delete is refused during the
outage too), #9 (deleted policies leave the list; the detail shows
`deleted_at`), #98 (e), (k), #101 (`policy.delete`, the `policy_deleted`
alert), #102 (d) (503 `about:blank`, `Retry-After: 10`).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.app import create_app

from .catalog_api import (
    MANAGED_DETAIL,
    POLICIES,
    STARTING,
    CatEnv,
    alerts,
    make_env,
    policy_doc,
    wrong_group_headers,
)
from .catalog_rows import agent, owner, scan_with_jobs, schedule, tag
from .conftest import PgServer, own_migrated_server
from .test_users_api_pg import problem

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("delete-api")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[CatEnv]:
    yield from make_env(server, tmp_path)


def path(pid: int | str) -> str:
    return f"{POLICIES}/{pid}"


def an_upload(e: CatEnv, plugins: int = 2) -> int:
    _, tok = e.admin_api()
    return e.uploaded(tok, policy_doc(f"m7del-{tag()}", plugins=plugins))


def plugin_states(e: CatEnv, pid: int) -> list[str]:
    return [
        s
        for (s,) in e.q(
            "SELECT p.state::text FROM plugin p JOIN policy_plugin pp"
            " USING (plugin_uuid) WHERE pp.policy_id = %s ORDER BY pp.sort_order",
            (pid,),
        )
    ]


def refused(e: CatEnv, r: Any, status: int, type_: str, before: Any) -> None:
    problem(r, status, type_)
    assert e.state() == before  # nothing changed


# CHK-M7-271: REQ-171 (1) 204, and REQ-167 (1) seen through the route -----------


def test_an_admin_totp_session_deletes_with_every_effect(env: CatEnv) -> None:
    pid = an_upload(env)
    with owner(env.server) as c:
        a = agent(c)
        _, jobs = scan_with_jobs(c, pid, a, ["queued", "dispatched", "running"])
        s1, s2 = schedule(c, pid), schedule(c, pid, enabled=False)
    other = an_upload(env)  # an unrelated policy keeps everything
    other_state = (env.policy(other), plugin_states(env, other))
    assert (env.bits / "uploaded" / f"policy-{pid}.bit").is_file()
    uid, tok = env.admin_session()
    mark, before = env.last_audit(), alerts("policy_deleted")
    r = env.call("DELETE", tok, path(pid))
    assert r.status_code == 204, r.text
    assert r.content == b""
    pol = env.policy(pid)
    assert pol["deleted_at"] is not None  # kept, soft-deleted
    assert pol["source_file"] == f"deleted/{pid}"
    assert set(plugin_states(env, pid)) == {"retired"}
    states = dict(
        env.q(
            "SELECT job_id, state::text FROM scan_job WHERE job_id = ANY(%s)",
            (list(jobs.values()),),
        )
    )
    assert states == {
        jobs["queued"]: "cancelled",
        jobs["dispatched"]: "dispatched",
        jobs["running"]: "running",
    }
    (fin,) = env.one(
        "SELECT finished_at FROM scan_job WHERE job_id = %s", (jobs["queued"],)
    )
    assert fin is not None
    assert env.q(
        "SELECT schedule_id, enabled FROM scan_schedule WHERE schedule_id IN (%s, %s)"
        " ORDER BY schedule_id",
        (s1, s2),
    ) == [(min(s1, s2), False), (max(s1, s2), False)]
    assert not (env.bits / "uploaded" / f"policy-{pid}.bit").exists()
    deleted = [a for a in env.audit_after(mark) if a["action"] == "policy.delete"]
    assert len(deleted) == 1
    assert (deleted[0]["actor"], deleted[0]["target"]) == (
        f"user:{uid}",
        f"policy:{pid}",
    )
    assert deleted[0]["detail"]["alert"] is True
    assert deleted[0]["detail"]["alert_kind"] == "policy_deleted"
    assert alerts("policy_deleted") == before + 1
    assert (env.policy(other), plugin_states(env, other)) == other_state


def test_a_deleted_policy_leaves_the_list_and_its_detail_shows_deleted_at(
    env: CatEnv,
) -> None:
    pid = an_upload(env)
    _, tok = env.admin_session()
    assert env.call("DELETE", tok, path(pid)).status_code == 204
    listed = env.call("GET", tok, POLICIES, params={"limit": 500}).json()["items"]
    assert pid not in [i["policy_id"] for i in listed]  # REQ-167 (3), #9
    detail = env.call("GET", tok, path(pid))
    assert detail.status_code == 200, detail.text
    assert detail.json()["deleted_at"] is not None
    assert detail.json()["source_file"] == f"deleted/{pid}"


def test_a_reupload_after_the_route_delete_revives_it(env: CatEnv) -> None:
    name = f"m7rev-{tag()}"
    _, api = env.admin_api()
    data = policy_doc(name)
    pid = env.uploaded(api, data)
    _, tok = env.admin_session()
    assert env.call("DELETE", tok, path(pid)).status_code == 204
    again = env.upload(api, policy_doc(name, plugins=2))
    assert again.status_code == 200, again.text
    assert again.json()["policy_id"] == pid  # the same id (TS §4.3, #14)
    assert env.policy(pid)["deleted_at"] is None


# CHK-M7-271: REQ-171 (1) callers refused (plants CHK-M7-341, -346) ------------


def test_an_admin_api_token_is_refused_totp_session_required(env: CatEnv) -> None:
    pid = an_upload(env)
    _, tok = env.admin_api()
    before = env.state()
    refused(
        env, env.call("DELETE", tok, path(pid)), 403, "totp_session_required", before
    )


def test_an_admin_session_without_totp_verification_is_refused(env: CatEnv) -> None:
    pid = an_upload(env)
    uid = env.user("admin", totp=True)
    before = env.state()
    r = env.call("DELETE", env.token(uid, "session", verified=False), path(pid))
    assert r.status_code == 403, r.text
    assert r.json()["type"] in ("totp_enrolment_required", "totp_session_required")
    assert env.state() == before


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("viewer", "session"),
        ("operator", "api"),
        ("viewer", "api"),
    ],
)
def test_operator_and_viewer_are_refused(env: CatEnv, role: str, kind: str) -> None:
    pid = an_upload(env)
    tok = env.token(env.user(role, totp=True), kind)
    before = env.state()
    r = env.call("DELETE", tok, path(pid))
    if kind == "session":
        refused(env, r, 403, "forbidden", before)  # REQ-171 (1)
    else:
        assert r.status_code == 403, r.text  # REQ-171 (1): viewer bsk_ 403
        assert env.state() == before


@pytest.mark.parametrize("token", list(wrong_group_headers()))
def test_agent_and_bad_tokens_get_401(env: CatEnv, token: str) -> None:
    pid = an_upload(env)
    before = env.state()
    r = env.client.request("DELETE", path(pid), headers=wrong_group_headers()[token])
    refused(env, r, 401, "unauthorized", before)


# CHK-M7-271: REQ-171 (2) the sink gate (#1; plant CHK-M7-343) -----------------


def test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains(
    env: CatEnv,
) -> None:
    early, late = an_upload(env), an_upload(env)
    _, tok = env.admin_session()
    env.sink_outage(seconds=14 * 60 + 59)  # 14:59 into the outage: still allowed
    assert not env.shipper.refusing()
    assert env.call("DELETE", tok, path(early)).status_code == 204
    env.clock.at += timedelta(seconds=1)  # 15:00
    assert env.shipper.refusing()
    before = env.state()
    refused(
        env, env.call("DELETE", tok, path(late)), 503, "audit_sink_unavailable", before
    )
    assert env.policy(late)["deleted_at"] is None
    env.sink_back()
    r = env.call("DELETE", tok, path(late))
    assert r.status_code == 204, r.text


# CHK-M7-271: REQ-171 (3), (4) the #98 (e) answers ------------------------------


def test_a_server_folder_policy_is_409_and_nothing_changes(env: CatEnv) -> None:
    name = f"m7srv-{tag()}"
    env.put_server("srv.bit", policy_doc(name))
    env.restart()  # the start-up reconcile imports it
    (pid,) = env.one("SELECT policy_id FROM policy WHERE policy_name = %s", (name,))
    _, tok = env.admin_session()
    before, deleted = env.state(), alerts("policy_deleted")
    r = env.call("DELETE", tok, path(pid))
    refused(env, r, 409, "policy_managed_on_server", before)
    assert r.json()["detail"] == MANAGED_DETAIL
    assert (env.bits / "srv.bit").is_file()
    assert alerts("policy_deleted") == deleted


def test_an_unknown_id_is_404_and_an_already_deleted_one_is_409(env: CatEnv) -> None:
    pid = an_upload(env)
    _, tok = env.admin_session()
    (top,) = env.one("SELECT max(policy_id) FROM policy")
    for unknown in (top + 1000, 0, 2**63 - 1, 2**63, 10**19):
        before = env.state()
        refused(env, env.call("DELETE", tok, path(unknown)), 404, "not_found", before)
    assert env.call("DELETE", tok, path(pid)).status_code == 204
    before, deleted = env.state(), alerts("policy_deleted")
    refused(env, env.call("DELETE", tok, path(pid)), 409, "conflict", before)
    assert alerts("policy_deleted") == deleted  # one alert per delete


@pytest.mark.parametrize(
    "bad", ["abc", "+1", "-1", "1.0", "1e3", " 1", "0x10", "1" * 21]
)
def test_a_malformed_id_is_400(env: CatEnv, bad: str) -> None:
    _, tok = env.admin_session()
    before = env.state()
    refused(env, env.call("DELETE", tok, path(bad)), 400, "invalid_request", before)


def test_before_the_catalog_start_up_ends_the_delete_is_503_retry_after_10(
    env: CatEnv,
) -> None:
    pid = an_upload(env)
    client = env.app_with(env.new_service(start=False))
    _, tok = env.admin_session()
    before = env.state()
    r = client.request("DELETE", path(pid), headers={"Authorization": f"Bearer {tok}"})
    refused(env, r, 503, "about:blank", before)
    assert r.headers["retry-after"] == "10"
    assert r.json()["detail"] == STARTING
    r = env.app_with(None).request(
        "DELETE", path(pid), headers={"Authorization": f"Bearer {tok}"}
    )
    refused(env, r, 503, "about:blank", before)


# OpenAPI (G6 itself runs in test_openapi.py) -----------------------------------


def test_the_operation_is_documented() -> None:
    op = create_app().openapi()["paths"][f"{POLICIES}/{{id}}"]["delete"]
    assert {"204", "400", "401", "403", "404", "409", "503"} <= set(op["responses"])
    assert "content" not in op["responses"]["204"]
    for status in ("400", "401", "403", "404", "409", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
    assert "requestBody" not in op
