"""TP-M7-22 (TASK-165): GET /api/v1/imports on PostgreSQL.

CHK-M7-258, -282 (tests/m7/test-plan.md). Expected values come from the spec
and the approved answers, not from the code: TS §6.2 L1107 (`/imports`,
"Import history and errors", admin) with L1081 to L1088 (admin routes take a
session or an API token), §6.3 L1133 to L1139 (problem+json, cursor
pagination with an opaque cursor and at most 500, catalog keys are integers,
RFC 3339 UTC), §6 L1056 (user routes take only bsu_ and bsk_), §5.2 L694 to
L707 and SR §3.5 (the twelve `bit_import` columns); REQ-173 (1) to (4),
REQ-174 (2); #98 (h) (every column, newest first by `import_id`, no filters),
#98 (i) (`import_id` a JSON integer), #48 (400 `invalid_request` for a bad
query, never 500). Rows are written through the TASK-149 repository as
`bitscan_app`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from bitscan_manager.api.pagination import encode_cursor
from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories import imports as rep
from bitscan_manager.repositories.imports import ImportRecord

from . import test_users_api_pg as users_api
from .catalog_rows import T0, T1, T2, app, checksum, sha, tag
from .test_contract_agent import RFC3339
from .test_policies_api_pg import make
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env
ROUTE = "/api/v1/imports"
# TS §5.2 L694-L707, in table order (#98 (h): every column)
COLUMNS = [
    "import_id", "file_name", "file_sha256", "policy_version", "mode", "outcome",
    "plugins_added", "plugins_updated", "plugins_retired", "errors", "imported_by",
    "imported_at",
]  # fmt: skip
FINDINGS: list[dict[str, Any]] = [
    {"line": None, "element": None, "code": "BIT001", "message": "file-level"},
    {
        "line": 3,
        "element": "Policy/PolicyStatus",
        "code": "BIT003",
        "message": 'PolicyStatus "on" \\x01 \\\\ ‮ <b>x</b>',
    },
    {
        "line": 14,
        "element": "Policy/PluginsGroups/Plugin[1]/PluginName",
        "code": "BIT101",
        "message": "warning: no leading control reference",
    },
    {
        "line": 2**31 - 1,
        "element": "Policy/PluginsGroups/Plugin[5000]/Execute/@timeout",
        "code": "BIT017",
        "message": "é 🛡 " + "m" * 200,
    },
]
HOSTILE_NAMES = [
    '<script>alert("x")</script>.bit',
    "‮gnp.bit",  # U+202E right-to-left override
    "a�b�.bit",  # the #99 (d) form of C0 and invalid UTF-8
    "../../etc/x.bit",
    "a\\b 'c' \"d\" & %00 %2e%2e.bit",
    "\x01\x1f\x7f.bit",  # raw controls: stored as given, returned as given
    "🛡" * 255,  # 255 characters, 1,020 UTF-8 bytes
    "",  # a missing client name (#99 (d))
    " lead and trail ",
]


def insert(e: Env, *recs: ImportRecord, at: datetime = T0) -> list[int]:
    with app(e.server) as c, c.transaction():
        return [rep.insert_import(c, r, at) for r in recs]


def rec(**kw: Any) -> ImportRecord:
    base: dict[str, Any] = {
        "file_name": f"m7imp-{tag()}.bit",
        "file_sha256": sha(tag()),
        "mode": "manual",
        "outcome": "rejected",
    }
    base.update(kw)
    return ImportRecord(**base)


def stored(e: Env, iid: int) -> dict[str, Any]:
    with e.conn() as c:
        cur = c.execute("SELECT * FROM bit_import WHERE import_id = %s", (iid,))
        cols = [d.name for d in cur.description or []]
        row = cur.fetchone()
    assert row is not None
    return dict(zip(cols, row, strict=True))


def admin_api(e: Env) -> str:
    return e.token(e.user("admin", totp=True), "api")


def walk(e: Env, tok: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100_000):
        q: dict[str, Any] = {"limit": limit, **({"cursor": cursor} if cursor else {})}
        r = e.call("GET", tok, ROUTE, params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        assert list(body) == ["items", "next_cursor"]
        assert len(body["items"]) <= limit
        out += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return out
        assert body["items"], "a next_cursor on an empty page"
    pytest.fail("paging never ended")


def find(e: Env, tok: str, iid: int) -> dict[str, Any]:
    """The item for one id: the cursor of id + 1 starts the page there."""
    page = page_at(e, tok, iid + 1, 1)
    assert [i["import_id"] for i in page] == [iid]
    return page[0]


def page_at(e: Env, tok: str, before: int, limit: int) -> list[dict[str, Any]]:
    r = e.call(
        "GET",
        tok,
        ROUTE,
        params={"limit": limit, "cursor": encode_cursor("imports", before)},
    )
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


# CHK-M7-258: REQ-173 (1) newest first, each row once ---------------------------


@pytest.mark.parametrize("n", [1, 2, 5])
def test_n_plus_one_rows_page_once_each_newest_first(env: Env, n: int) -> None:
    mine = insert(env, *(rec() for _ in range(n + 1)))
    items = walk(env, admin_api(env), n)
    ids = [i["import_id"] for i in items]
    assert len(ids) == len(set(ids))  # each row once
    assert ids == sorted(ids, reverse=True)  # newest first across pages
    assert [i for i in ids if i in mine] == sorted(mine, reverse=True)
    with env.conn() as c:
        total = c.execute("SELECT count(*) FROM bit_import").fetchone()
    assert total is not None and len(ids) == total[0]  # the whole table


def test_newest_first_is_by_import_id_not_imported_at(env: Env) -> None:
    # #98 (h): the order key is import_id. A later id with an earlier time
    # still comes first.
    (late,) = insert(env, rec(), at=T2)
    (early,) = insert(env, rec(), at=T0)
    assert early > late
    page = page_at(env, admin_api(env), early + 1, 2)
    assert [i["import_id"] for i in page] == [early, late]


def test_first_page_is_the_newest_rows_with_the_default_limit(env: Env) -> None:
    mine = insert(env, *(rec() for _ in range(51)))
    r = env.call("GET", admin_api(env), ROUTE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 50  # TS §6.3 L1134: ?limit=50
    assert [i["import_id"] for i in body["items"]] == sorted(mine, reverse=True)[:50]
    assert isinstance(body["next_cursor"], str)


def test_limit_500_is_accepted_and_the_cursor_ends_the_walk(env: Env) -> None:
    insert(env, rec())
    items = walk(env, admin_api(env), 500)
    assert items


@pytest.mark.parametrize("limit", ["0", "501", "-1", "a", "1.5", "", "1e2"])
def test_bad_limits_are_400(env: Env, limit: str) -> None:
    problem(
        env.call("GET", admin_api(env), ROUTE, params={"limit": limit}),
        400,
        "invalid_request",
    )


def test_no_filters_are_offered(env: Env) -> None:
    # #98 (h): no filters. An unknown query parameter changes nothing.
    tok = admin_api(env)
    insert(env, rec(outcome="success", policy_version=1), rec(outcome="rejected"))
    plain = env.call("GET", tok, ROUTE, params={"limit": 5}).json()["items"]
    filtered = env.call(
        "GET", tok, ROUTE, params={"limit": 5, "outcome": "success", "mode": "auto"}
    ).json()["items"]
    assert [i["import_id"] for i in filtered] == [i["import_id"] for i in plain]
    doc = create_app().openapi()
    params = doc["paths"][ROUTE]["get"].get("parameters", [])
    assert sorted((p["name"], p["in"]) for p in params) == [
        ("cursor", "query"),
        ("limit", "query"),
    ]


# CHK-M7-258: every column as stored, REQ-173 (2) errors -----------------------


def test_items_carry_every_column_exactly_as_stored(env: Env) -> None:
    uid = env.user("admin", totp=True)
    ids = insert(
        env,
        rec(
            mode="auto",
            outcome="success",
            policy_version=7,
            plugins_added=3,
            plugins_updated=2,
            plugins_retired=1,
            errors=FINDINGS[2:3],
            imported_by=uid,
        ),
        rec(mode="rebuild", outcome="rejected", errors=FINDINGS),
        rec(mode="auto", outcome="skipped"),
        at=T1,
    )
    tok = env.token(uid, "api")
    for iid in ids:
        item = find(env, tok, iid)
        row = stored(env, iid)
        assert list(row) == COLUMNS  # the DDL, so the expected key list is real
        assert list(item) == COLUMNS  # every column, in table order
        assert type(item["import_id"]) is int  # #98 (i)
        assert RFC3339.search(item["imported_at"]) and item["imported_at"].endswith("Z")
        got = datetime.fromisoformat(item["imported_at"].replace("Z", "+00:00"))
        assert got == row["imported_at"] == T1
        assert {k: v for k, v in item.items() if k != "imported_at"} == {
            k: v for k, v in row.items() if k != "imported_at"
        }
    first, second, third = (find(env, tok, i) for i in ids)
    assert (first["policy_version"], first["imported_by"]) == (7, uid)
    assert (second["policy_version"], second["imported_by"]) == (None, None)
    assert (second["plugins_added"], second["plugins_updated"]) == (0, 0)
    assert third["errors"] == [] and third["outcome"] == "skipped"


def test_errors_come_back_exactly_as_stored(env: Env) -> None:
    many = [
        {
            "line": i,
            "element": f"Policy/PluginsGroups/Plugin[{i}]/Execute",
            "code": "BIT102",
            "message": f"m{i}",
        }
        for i in range(1, 2001)
    ]
    tok = admin_api(env)
    for errors in (FINDINGS, many, []):
        (iid,) = insert(env, rec(errors=errors))
        got = find(env, tok, iid)["errors"]
        assert got == stored(env, iid)["errors"] == errors  # order and values kept
        assert all(list(f) == ["line", "element", "code", "message"] for f in got)


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_hostile_file_name_comes_back_byte_identical(env: Env, name: str) -> None:
    (iid,) = insert(env, rec(file_name=name))
    assert stored(env, iid)["file_name"] == name
    r = env.call("GET", admin_api(env), ROUTE, params={
        "limit": 1, "cursor": encode_cursor("imports", iid + 1)
    })  # fmt: skip
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    (item,) = r.json()["items"]
    assert item["file_name"] == name
    assert item["file_name"].encode("utf-8") == name.encode("utf-8")


def test_reading_writes_nothing_to_bit_import(env: Env) -> None:
    insert(env, rec())
    tok = admin_api(env)
    with env.conn() as c:
        before = checksum(c, "bit_import", "import_id")
    walk(env, tok, 500)
    with env.conn() as c:
        assert checksum(c, "bit_import", "import_id") == before


# CHK-M7-258: REQ-173 (3) admin only, session or API token ---------------------


@pytest.mark.parametrize("kind", ["session", "api"])
def test_admin_reads_with_a_session_or_an_api_token(env: Env, kind: str) -> None:
    (iid,) = insert(env, rec())
    tok = env.token(env.user("admin", totp=True), kind)
    assert find(env, tok, iid)["import_id"] == iid


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("operator", "api"),
        ("viewer", "session"),
        ("viewer", "api"),
    ],
)
def test_operator_and_viewer_get_403(env: Env, role: str, kind: str) -> None:
    insert(env, rec())
    tok = env.token(env.user(role, totp=True), kind)
    problem(env.call("GET", tok, ROUTE), 403, "forbidden")
    problem(
        env.call("GET", tok, ROUTE, params={"cursor": encode_cursor("imports", 5)}),
        403,
        "forbidden",
    )


def test_admin_without_totp_is_refused(env: Env) -> None:
    uid = env.user("admin", totp=False)
    restricted = env.token(uid, "session", verified=False)
    problem(env.call("GET", restricted, ROUTE), 403, "totp_enrolment_required")
    problem(
        env.call("GET", env.token(uid, "api"), ROUTE), 403, "totp_enrolment_required"
    )


# CHK-M7-282: REQ-174 (2) route group ------------------------------------------


@pytest.mark.parametrize(
    "token", ["agent", "enrolment", "none", "garbage_bsu", "garbage_bsk", "basic"]
)
def test_agent_tokens_and_bad_tokens_get_401(env: Env, token: str) -> None:
    insert(env, rec())
    headers = {
        "agent": {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        "enrolment": {
            "Authorization": f"Bearer {new_agent_token(AgentTokenKind.ENROLMENT)}"
        },
        "none": {},
        "garbage_bsu": {"Authorization": "Bearer bsu_" + "x" * 43},
        "garbage_bsk": {"Authorization": "Bearer bsk_" + "x" * 43},
        "basic": {"Authorization": "Basic YWRtaW46YWRtaW4="},
    }[token]
    resp = env.client.request("GET", ROUTE, headers=headers)
    problem(resp, 401, "unauthorized")
    assert "items" not in resp.json()


def test_a_real_agent_token_of_an_enrolled_agent_gets_401(env: Env) -> None:
    # A bsa_ token whose hash is stored on an agent row is still not a user
    # token: the route group refuses it (TS §6, security invariants).
    tok = new_agent_token(AgentTokenKind.AGENT)
    with app(env.server) as c, c.transaction():
        c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status) VALUES (%s, 'h', 'v', %s,"
            " now(), now() + interval '30 days', 'online')",
            (tag() * 4, token_hash(tok)),
        )
    problem(
        env.client.request("GET", ROUTE, headers={"Authorization": f"Bearer {tok}"}),
        401,
        "unauthorized",
    )


def test_the_user_rate_limit_applies(env: Env) -> None:
    uid = env.user("admin", totp=True)
    tok = env.token(uid, "api")
    limits = env.client.app.state.runtime.limits  # type: ignore[attr-defined]
    for _ in range(599):
        assert limits.allow_user(uid)
    assert env.call("GET", tok, ROUTE, params={"limit": 1}).status_code == 200  # 600th
    problem(env.call("GET", tok, ROUTE, params={"limit": 1}), 429, "rate_limited")


# CHK-M7-258: the cursor (tampered, wrong shape, wrong scope → 400, never 500) -


def real_cursor(e: Env, tok: str) -> str:
    insert(e, rec(), rec())
    body = e.call("GET", tok, ROUTE, params={"limit": 1}).json()
    cur = body["next_cursor"]
    assert isinstance(cur, str) and cur
    return cur


def flip(s: str, i: int) -> str:
    c = s[i]
    return s[:i] + ("A" if c != "A" else "B") + s[i + 1 :]


@pytest.mark.parametrize(
    "how",
    [
        "flip_first",
        "flip_middle",
        "flip_last",
        "truncate",
        "append",
        "pad",
        "swapcase",
        "space",
        "plus_slash",
        "empty",
        "x",
        "non_ascii",
        "too_long",
    ],
)
def test_a_tampered_cursor_is_400(env: Env, how: str) -> None:
    tok = admin_api(env)
    cur = real_cursor(env, tok)
    assert len(cur) < 513
    tampered: dict[str, str] = {
        "flip_first": flip(cur, 0),
        "flip_middle": flip(cur, len(cur) // 2),
        "flip_last": flip(cur, len(cur) - 1),
        "truncate": cur[:-2],
        "append": cur + "A",
        "pad": cur + "==",
        "swapcase": cur.swapcase(),
        "space": cur[:5] + " " + cur[5:],
        "plus_slash": cur.replace("-", "+").replace("_", "/") + "+/",
        "empty": "",
        "x": "x",
        "non_ascii": cur[:-1] + "é",
        "too_long": cur + "A" * (513 - len(cur)),
    }
    bad = tampered[how]
    assert bad != cur
    problem(env.call("GET", tok, ROUTE, params={"cursor": bad}), 400, "invalid_request")


@pytest.mark.parametrize(
    "key",
    [
        "5",
        True,
        False,
        0,
        -1,
        2**63,
        2**64,
        10**30,
        [5],
        [5, 6],
        [],
        None,
        {"import_id": 5},
        1.5,
        5.0,
    ],
)
def test_a_signed_cursor_of_the_wrong_shape_is_400(env: Env, key: Any) -> None:
    # Signed with the manager's own key (same process), so only the shape is
    # wrong: the route must refuse it before PostgreSQL sees it.
    cur = encode_cursor("imports", key)
    problem(
        env.call("GET", admin_api(env), ROUTE, params={"cursor": cur}),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize("key", [1, 2, 2**63 - 1])
def test_the_bounds_of_a_good_key_are_accepted(env: Env, key: int) -> None:
    insert(env, rec())
    r = env.call(
        "GET", admin_api(env), ROUTE, params={"cursor": encode_cursor("imports", key)}
    )
    assert r.status_code == 200, r.text
    assert all(i["import_id"] < key for i in r.json()["items"])
    if key == 1:
        assert r.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "route", ["/api/v1/audit-log", "/api/v1/users", "/api/v1/policies"]
)
def test_a_cursor_from_another_list_is_400(env: Env, route: str) -> None:
    _, session = env.admin()
    for _ in range(3):
        env.user("viewer")  # at least two users
    for _ in range(2):  # at least two policies, and audit entries by PATCH
        pid = make(env).policy_id
        r = env.call(
            "PATCH",
            session,
            f"/api/v1/policies/{pid}",
            json={"policy_status": "disabled"},
        )
        assert r.status_code == 200, r.text
    insert(env, rec())
    other = env.call("GET", session, route, params={"limit": 1}).json()
    assert other["next_cursor"], other
    problem(
        env.call("GET", session, ROUTE, params={"cursor": other["next_cursor"]}),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize("scope", ["audit_log", "users", "policies", "agents", ""])
def test_a_signed_int_cursor_of_another_scope_is_400(env: Env, scope: str) -> None:
    problem(
        env.call(
            "GET",
            admin_api(env),
            ROUTE,
            params={"cursor": encode_cursor(scope, 5)},
        ),
        400,
        "invalid_request",
    )


# OpenAPI (#48 refusals documented; G6 runs in test_openapi.py) ----------------


def test_the_operation_is_documented_with_the_item_columns() -> None:
    doc = create_app().openapi()
    op = doc["paths"][ROUTE]["get"]
    assert {"200", "401", "403", "429"} <= set(op["responses"])
    for status in ("401", "403", "429"):
        content = op["responses"][status]["content"]
        assert list(content) == ["application/problem+json"]
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    page = doc["components"]["schemas"][ok["$ref"].rsplit("/", 1)[-1]]
    assert set(page["properties"]) == {"items", "next_cursor"}
    item_ref = page["properties"]["items"]["items"]["$ref"]
    item = doc["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    assert list(item["properties"]) == COLUMNS
    assert item["properties"]["import_id"]["type"] == "integer"
    assert set(item["required"]) == set(COLUMNS)
