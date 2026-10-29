"""TP-M7-25 (TASK-164): POST /api/v1/policies/rebuild and GET /api/v1/tasks/{id}
on PostgreSQL.

CHK-M7-276, -282, -342, -344 (tests/m7/test-plan.md). Expected values come
from the spec and the approved answers, not from the code: TS §6.2 L1084
(rebuild is a sensitive action: TOTP-verified session, API tokens refused),
L1105 (`POST /policies/rebuild`, async, returns a task id; admin, TOTP
session), L1106 (`GET /tasks/{id}`, admin), §4.2 L538-L540 (every file of
both folders re-imported; gone files deleted; a task left running is failed
at start-up), §5.3 L1051 (sink gate), §6 L1056 (user routes take only bsu_
and bsk_), §6.3 (problem+json, UUID ids, RFC 3339 UTC); REQ-172 (1)-(4),
REQ-174 (2); #1, #20 (rejected files do not fail the rebuild), #98 (f), (g),
(i), (j), #101 (`bits.rebuild`, the `policy_rebuilt` alert), #102 (d); the
TASK-157 rulings and the crash-window ruling (decisions 2026-10-27/28:
`task.result` also carries `not_imported` and `removed_leftovers`; a deleted
policy's leftover upload is removed, never revived).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.app import create_app
from bitscan_manager.repositories import imports as imports_repo
from bitscan_manager.services.importer import rebuild as rb_mod

from .catalog_api import (
    POLICIES,
    REBUILD,
    STARTING,
    TASKS,
    CatEnv,
    alerts,
    conn_of,
    make_env,
    policy_doc,
    until,
    wrong_group_headers,
)
from .catalog_rows import app, tag
from .conftest import PgServer, own_migrated_server
from .test_contract_agent import RFC3339
from .test_users_api_pg import problem

pytestmark = pytest.mark.pg

TASK_KEYS = [
    "task_id",
    "kind",
    "state",
    "requested_by",
    "result",
    "started_at",
    "finished_at",
]  # fmt: skip  (#98 (g), in this order)
RESULT_KEYS = {
    "files",
    "deleted_policy_ids",
    "plugins_retired",
    "removed_leftovers",
    "not_imported",
}
FILE_KEYS = ["source_file", "import_id", "outcome", "policy_id", "policy_version"]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("rebuild-api")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[CatEnv]:
    yield from make_env(server, tmp_path)


def task(e: CatEnv, token: str, tid: str) -> dict[str, Any]:
    r = e.call("GET", token, f"{TASKS}/{tid}")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert list(body) == TASK_KEYS
    return body


def finished(e: CatEnv, token: str, tid: str) -> dict[str, Any]:
    return until(lambda: (t := task(e, token, tid))["state"] != "running" and t)  # type: ignore[no-any-return]


def start(e: CatEnv, token: str, **kw: Any) -> str:
    r = e.call("POST", token, REBUILD, **kw)
    assert r.status_code == 202, r.text
    body = r.json()
    assert list(body) == ["task_id"]
    tid = body["task_id"]
    assert str(UUID(tid)) == tid  # a hyphenated lowercase UUID string (#98 (i))
    return str(tid)


def utc(text: str) -> datetime:
    assert RFC3339.search(text) and text.endswith("Z"), text
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class CatalogLock:
    """pg_advisory_lock(hashtext('catalog')) held from another session."""

    def __init__(self, e: CatEnv) -> None:
        self.conn = conn_of(e.server)

    def __enter__(self) -> CatalogLock:
        self.conn.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        self.conn.close()


# CHK-M7-276: REQ-172 (1) 202, running, then succeeded with its result ---------


def test_a_rebuild_runs_in_the_background_and_reports_every_file(env: CatEnv) -> None:
    t = tag()
    good, bad, gone = (f"m7rb-{t}-{k}" for k in ("good", "bad", "gone"))
    env.put_server("good.bit", policy_doc(good))
    env.put_server("bad.bit", policy_doc(bad, status="on"))  # BIT003
    env.put_server("gone.bit", policy_doc(gone, plugins=2))
    env.restart()  # the start-up reconcile imports the folder
    (g_id,) = env.one("SELECT policy_id FROM policy WHERE policy_name = %s", (good,))
    (x_id,) = env.one("SELECT policy_id FROM policy WHERE policy_name = %s", (gone,))
    _, api = env.admin_api()
    u_id = env.uploaded(api, policy_doc(f"m7rb-{t}-upl"))
    d_data = policy_doc(f"m7rb-{t}-del")
    d_id = env.uploaded(api, d_data)
    uid, tok = env.admin_session()
    assert env.call("DELETE", tok, f"{POLICIES}/{d_id}").status_code == 204
    leftover = env.bits / "uploaded" / f"policy-{d_id}.bit"
    leftover.write_bytes(d_data)  # an interrupted delete's leftover
    (env.bits / "gone.bit").unlink()
    (env.bits / "uploaded" / "copy.bit").write_bytes(policy_doc(good, plugins=2))
    imports, mark = env.last_import(), env.last_audit()
    rebuilt = alerts("policy_rebuilt")

    with CatalogLock(env):  # the worker waits on the lock: the task is running
        tid = start(env, tok)
        running = task(env, api, tid)  # REQ-172 (3): an admin bsk_ may read it
        assert running == {
            "task_id": tid, "kind": "rebuild", "state": "running",
            "requested_by": uid, "result": None,
            "started_at": running["started_at"], "finished_at": None,
        }  # fmt: skip
        utc(running["started_at"])
    done = finished(env, tok, tid)
    assert done["state"] == "succeeded"  # #20: a rejected file does not fail it
    assert utc(done["finished_at"]) >= utc(done["started_at"])
    result = done["result"]
    assert set(result) == RESULT_KEYS
    files = {f["source_file"]: f for f in result["files"]}
    assert all(list(f) == FILE_KEYS for f in result["files"])
    assert set(files) == {"good.bit", "bad.bit", f"uploaded/policy-{u_id}.bit"}
    assert (files["good.bit"]["outcome"], files["good.bit"]["policy_id"]) == (
        "success",
        g_id,
    )
    assert files[f"uploaded/policy-{u_id}.bit"]["policy_id"] == u_id
    assert files["bad.bit"]["outcome"] == "rejected"
    assert (files["bad.bit"]["policy_id"], files["bad.bit"]["policy_version"]) == (
        None,
        None,
    )
    assert result["deleted_policy_ids"] == [x_id]
    assert result["removed_leftovers"] == [f"uploaded/policy-{d_id}.bit"]
    assert result["not_imported"] == ["uploaded/copy.bit"]
    assert type(result["plugins_retired"]) is int and result["plugins_retired"] >= 2
    # the leftover is removed and never revived, with no import row
    assert not leftover.exists()
    assert env.policy(d_id)["deleted_at"] is not None
    assert env.policy(x_id)["source_file"] == f"deleted/{x_id}"
    rows = env.q(
        "SELECT import_id, mode::text, imported_by FROM bit_import WHERE import_id > %s"
        " ORDER BY import_id",
        (imports,),
    )
    assert sorted(f["import_id"] for f in result["files"]) == [r[0] for r in rows]
    assert {(m, by) for _, m, by in rows} == {("rebuild", uid)}
    entries = [a for a in env.audit_after(mark) if a["action"] == "bits.rebuild"]
    assert len(entries) == 1 and entries[0]["actor"] == f"user:{uid}"
    assert entries[0]["detail"]["alert_kind"] == "policy_rebuilt"
    assert entries[0]["detail"]["removed_leftovers"] == [f"uploaded/policy-{d_id}.bit"]
    assert alerts("policy_rebuilt") == rebuilt + 1


@pytest.mark.parametrize("body", ["none", "empty_object"])
def test_the_post_takes_no_body_or_an_empty_object(env: CatEnv, body: str) -> None:
    uid, tok = env.admin_session()
    kw: dict[str, Any] = {"json": {}} if body == "empty_object" else {}
    tid = start(env, tok, **kw)
    done = finished(env, tok, tid)
    assert (done["state"], done["requested_by"]) == ("succeeded", uid)
    (by,) = env.one("SELECT requested_by FROM task WHERE task_id = %s", (UUID(tid),))
    assert by == uid


# CHK-M7-276: REQ-172 (4) a restart in the middle fails the task ---------------


def test_a_manager_stopped_mid_rebuild_leaves_the_task_failed(
    env: CatEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    def stuck(*a: Any, **k: Any) -> Any:  # the rebuild in progress when stopped
        started.set()
        release.wait(30)
        return None

    monkeypatch.setattr(rb_mod, "run", stuck)
    _, tok = env.admin_session()
    try:
        tid = start(env, tok)
        assert started.wait(10)
        assert task(env, tok, tid)["state"] == "running"
        env.restart()  # stop, then a new start-up sequence
        got = task(env, tok, tid)
    finally:
        release.set()
    assert got["state"] == "failed"
    assert list(got["result"]) == ["error"]  # #98 (g): {error: "<fixed text>"}
    assert isinstance(got["result"]["error"], str) and got["result"]["error"]
    assert tid not in got["result"]["error"]
    assert got["finished_at"] is not None


# CHK-M7-276: REQ-172 (2) callers refused (plants CHK-M7-342, -344) ------------


def test_an_admin_api_token_is_refused_totp_session_required(env: CatEnv) -> None:
    _, tok = env.admin_api()
    n = env.tasks()
    problem(env.call("POST", tok, REBUILD), 403, "totp_session_required")
    assert env.tasks() == n


def test_an_admin_without_a_totp_verified_session_is_refused(env: CatEnv) -> None:
    n = env.tasks()
    restricted = env.token(env.user("admin", totp=False), "session", verified=False)
    problem(env.call("POST", restricted, REBUILD), 403, "totp_enrolment_required")
    unverified = env.token(env.user("admin", totp=True), "session", verified=False)
    r = env.call("POST", unverified, REBUILD)
    assert r.status_code == 403, r.text
    assert env.tasks() == n


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("viewer", "session"),
        ("operator", "api"),
        ("viewer", "api"),
    ],
)
def test_operator_and_viewer_cannot_start_a_rebuild(
    env: CatEnv, role: str, kind: str
) -> None:
    tok = env.token(env.user(role, totp=True), kind)
    n = env.tasks()
    r = env.call("POST", tok, REBUILD)
    if kind == "session":
        problem(r, 403, "forbidden")
    else:
        assert r.status_code == 403, r.text
    assert env.tasks() == n


@pytest.mark.parametrize("route", ["post", "get"])
@pytest.mark.parametrize("token", list(wrong_group_headers()))
def test_agent_and_bad_tokens_get_401(env: CatEnv, token: str, route: str) -> None:
    n = env.tasks()
    method, url = (
        ("POST", REBUILD) if route == "post" else ("GET", f"{TASKS}/{uuid4()}")
    )
    r = env.client.request(method, url, headers=wrong_group_headers()[token])
    problem(r, 401, "unauthorized")
    assert env.tasks() == n


def test_the_sink_gate_refuses_after_15_minutes_until_the_queue_drains(
    env: CatEnv,
) -> None:
    _, tok = env.admin_session()
    env.sink_outage(seconds=14 * 60 + 59)
    assert not env.shipper.refusing()
    first = start(env, tok)  # 14:59: still allowed
    finished(env, tok, first)
    env.clock.at += timedelta(seconds=1)  # 15:00
    assert env.shipper.refusing()
    n = env.tasks()
    problem(env.call("POST", tok, REBUILD), 503, "audit_sink_unavailable")
    assert env.tasks() == n
    # the task route is not a sensitive action: it still answers
    assert task(env, tok, first)["state"] == "succeeded"
    env.sink_back()
    assert finished(env, tok, start(env, tok))["state"] == "succeeded"


def test_before_the_catalog_start_up_ends_the_post_is_503_retry_after_10(
    env: CatEnv,
) -> None:
    client = env.app_with(env.new_service(start=False))
    _, tok = env.admin_session()
    n = env.tasks()
    r = client.post(REBUILD, headers={"Authorization": f"Bearer {tok}"})
    problem(r, 503, "about:blank")
    assert r.headers["retry-after"] == "10"
    assert r.json()["detail"] == STARTING
    bare = env.app_with(None)
    problem(
        bare.post(REBUILD, headers={"Authorization": f"Bearer {tok}"}),
        503,
        "about:blank",
    )
    assert env.tasks() == n


# CHK-M7-276: REQ-172 (3) the task route ----------------------------------------


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("operator", "api"),
        ("viewer", "session"),
        ("viewer", "api"),
    ],
)
def test_only_an_admin_reads_a_task(env: CatEnv, role: str, kind: str) -> None:
    with app(env.server) as c, c.transaction():
        tid = imports_repo.insert_task(c, None, env.clock.now())
    tok = env.token(env.user(role, totp=True), kind)
    r = env.call("GET", tok, f"{TASKS}/{tid}")
    problem(r, 403, "forbidden")
    assert "running" not in r.text


def test_a_cli_task_reads_with_requested_by_null(env: CatEnv) -> None:
    with app(env.server) as c, c.transaction():
        tid = imports_repo.insert_task(c, None, env.clock.now())
    _, api = env.admin_api()
    got = task(env, api, str(tid))
    assert (got["task_id"], got["state"], got["requested_by"]) == (
        str(tid),
        "running",
        None,
    )
    assert (got["result"], got["finished_at"]) == (None, None)
    assert utc(got["started_at"]) == env.clock.now()


def test_an_unknown_task_is_404(env: CatEnv) -> None:
    _, api = env.admin_api()
    for tid in (uuid4(), UUID(int=0), UUID(int=2**128 - 1)):
        problem(env.call("GET", api, f"{TASKS}/{tid}"), 404, "not_found")


@pytest.mark.parametrize(
    "bad",
    [
        "abc",
        "0" * 32,
        "{00000000-0000-0000-0000-000000000000}",
        "urn:uuid:00000000-0000-0000-0000-000000000000",
        "00000000-0000-0000-0000-0000000000000",
        "00000000-0000-0000-0000-00000000000",
        "0000000-00000-0000-0000-000000000000",
        "g0000000-0000-0000-0000-000000000000",
        "00000000_0000_0000_0000_000000000000",
        "1",
        "-1",
    ],
)
def test_a_task_id_that_is_not_a_hyphenated_uuid_is_400(env: CatEnv, bad: str) -> None:
    _, api = env.admin_api()
    problem(env.call("GET", api, f"{TASKS}/{bad}"), 400, "invalid_request")


def test_an_upper_case_uuid_never_errors(env: CatEnv) -> None:
    with app(env.server) as c, c.transaction():
        tid = imports_repo.insert_task(c, None, env.clock.now())
    _, api = env.admin_api()
    r = env.call("GET", api, f"{TASKS}/{str(tid).upper()}")
    assert r.status_code in (200, 400), r.text
    if r.status_code == 200:
        assert r.json()["task_id"] == str(tid)


# OpenAPI (G6 itself runs in test_openapi.py) -----------------------------------


def test_both_operations_are_documented_with_the_98_g_shapes() -> None:
    doc = create_app().openapi()
    schemas = doc["components"]["schemas"]

    def schema(ref: dict[str, Any]) -> dict[str, Any]:
        return schemas[ref["$ref"].rsplit("/", 1)[-1]]  # type: ignore[no-any-return]

    post = doc["paths"][REBUILD]["post"]
    assert "requestBody" not in post and "parameters" not in post
    assert {"202", "401", "403", "503"} <= set(post["responses"])
    started = schema(post["responses"]["202"]["content"]["application/json"]["schema"])
    assert list(started["properties"]) == ["task_id"]
    assert started["properties"]["task_id"]["format"] == "uuid"
    get = doc["paths"][f"{TASKS}/{{id}}"]["get"]
    assert {"200", "400", "401", "403", "404"} <= set(get["responses"])
    for status in ("400", "401", "403", "404"):
        assert list(get["responses"][status]["content"]) == ["application/problem+json"]
    (param,) = get["parameters"]
    assert param["in"] == "path" and "pattern" in param["schema"]
    item = schema(get["responses"]["200"]["content"]["application/json"]["schema"])
    assert list(item["properties"]) == TASK_KEYS
    refs = [
        s["$ref"].rsplit("/", 1)[-1]
        for s in item["properties"]["result"]["anyOf"]
        if "$ref" in s
    ]
    result = next(schemas[r] for r in refs if "files" in schemas[r]["properties"])
    assert set(result["properties"]) == RESULT_KEYS
    file_item = schema(result["properties"]["files"]["items"])
    assert list(file_item["properties"]) == FILE_KEYS
