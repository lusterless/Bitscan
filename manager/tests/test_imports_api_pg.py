"""TP-M7-22 (TASK-165): GET /api/v1/imports through the API on PostgreSQL.

CHK-M7-258, -281, -282 (tests/m7/test-plan.md). Expected values come from the
spec and the answers, not from the code: TS §6.2 L1107 (`/imports`, import
history and errors, admin; session or API token, no TOTP session), §6 L1056
(user routes take only bsu_ and bsk_), §6.3 L1133 to L1141 (problem+json,
`?limit=50&cursor=<opaque>`, max 500, catalog keys are integers, RFC 3339 UTC,
stored text is untrusted and returned as stored), §5.2 L694 to L707 (the
twelve `bit_import` columns), §6.3 rate limits (600 per minute per user);
REQ-173 (1) to (4), REQ-174 (2); #98 (h) (every column, newest first by
import_id, no filters, {items, next_cursor}), #98 (i) (import_id a JSON
integer), #110 (warnings stored in errors), #53 (i) (an admin's API token is
refused while the admin has no TOTP), #48 (a cursor from another list is 400).

The module has a database of its own and empties bit_import (as owner) before
each test, so page contents can be asserted exactly.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.api.pagination import encode_cursor
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.imports import ImportRecord, insert_import

from . import test_users_api_pg as users_api
from .catalog_rows import T0, app, owner, sha, tag
from .conftest import PgServer, own_migrated_server
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg
REVOKED = "revoked"

env = users_api.env
ROUTE = "/api/v1/imports"
COLUMNS = {
    "import_id", "file_name", "file_sha256", "policy_version", "mode", "outcome",
    "plugins_added", "plugins_updated", "plugins_retired", "errors", "imported_by",
    "imported_at",
}  # fmt: skip
# A rejected file's findings and a success's warnings (#110): the four keys,
# null line and element for file-level findings, text with escapes and bidi.
ERRORS: list[dict[str, Any]] = [
    {
        "line": 3,
        "element": "Policy/PolicyStatus",
        "code": "BIT003",
        "message": 'x "on"',
    },
    {
        "line": 14,
        "element": "Policy/PluginsGroups/Plugin[1]/PluginName",
        "code": "BIT101",
        "message": "warn <b>",
    },
    {
        "line": 20,
        "element": "Policy/PluginsGroups/Plugin[2]",
        "code": "BIT103",
        "message": "w",
    },
    {"line": None, "element": None, "code": "BIT001", "message": "é \\ ‮\t\n🛡"},
]
WARNINGS = [e for e in ERRORS if e["code"] in {"BIT101", "BIT103"}]
# No U+0000 (TEXT refuses it); everything else a browser, a shell or a
# spreadsheet would act on.
HOSTILE = (
    "<script>alert('x')</script><img src=x onerror=alert(1)>"
    "../../etc/passwd =cmd|' /C calc'!A0 +1 -1 @SUM(1) \t\r\n"
    ' ‮ é \\ " & \x01 \x1b[31m \x7f 🛡 %00 %2e%2e/'
)


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("impapi")) as s:
        yield s


@pytest.fixture(autouse=True)
def _empty_log(migrated_db: PgServer) -> None:
    with owner(migrated_db) as c:
        c.execute("TRUNCATE bit_import")


def seed(e: Env, n: int = 1, **kw: Any) -> list[int]:
    """n rows, oldest first; returns their import_ids."""
    ids: list[int] = []
    with app(e.server) as c, c.transaction():
        for i in range(n):
            base: dict[str, Any] = {
                "file_name": f"imp-{tag()}-{i}.bit",
                "file_sha256": sha(tag()),
                "mode": "manual",
                "outcome": "rejected",
            }
            base.update(kw)
            ids.append(insert_import(c, ImportRecord(**base), T0))
    return ids


def admin_api(e: Env) -> str:
    return e.token(e.user("admin", totp=True), "api")


def get(e: Env, tok: str, **params: Any) -> Any:
    return e.call("GET", tok, ROUTE, params=params)


def page(e: Env, tok: str, **params: Any) -> dict[str, Any]:
    r = get(e, tok, **params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body) == {"items", "next_cursor"}
    return body  # type: ignore[no-any-return]


def walk(e: Env, tok: str, limit: int) -> list[list[int]]:
    """Every page's import_ids, following next_cursor to the end."""
    pages: list[list[int]] = []
    cursor: str | None = None
    for _ in range(1000):
        q: dict[str, Any] = {"limit": limit, **({"cursor": cursor} if cursor else {})}
        body = page(e, tok, **q)
        pages.append([i["import_id"] for i in body["items"]])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
        assert isinstance(cursor, str) and cursor
    pytest.fail("paging never ended")


def snapshot(e: Env) -> tuple[Any, ...]:
    with e.conn() as c:
        imports = c.execute("SELECT * FROM bit_import ORDER BY import_id").fetchall()
        audit = c.execute("SELECT count(*) FROM audit_log").fetchone()
    return imports, audit


# CHK-M7-258: REQ-173 (1) ------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_n_plus_one_rows_with_limit_n_appear_once_each_newest_first(
    env: Env, n: int
) -> None:
    ids = seed(env, n + 1)
    pages = walk(env, admin_api(env), n)
    assert pages == [sorted(ids, reverse=True)[:n], [min(ids)]]


def test_exactly_limit_rows_is_one_page_with_a_null_cursor(env: Env) -> None:
    ids = seed(env, 3)
    body = page(env, admin_api(env), limit=3)
    assert [i["import_id"] for i in body["items"]] == sorted(ids, reverse=True)
    assert body["next_cursor"] is None


def test_empty_log_is_an_empty_page(env: Env) -> None:
    assert page(env, admin_api(env)) == {"items": [], "next_cursor": None}


def test_default_limit_is_50(env: Env) -> None:
    ids = seed(env, 51)
    body = page(env, admin_api(env))
    assert [i["import_id"] for i in body["items"]] == sorted(ids, reverse=True)[:50]
    assert body["next_cursor"] is not None


def test_limit_500_is_the_maximum_page(env: Env) -> None:
    ids = seed(env, 501)
    pages = walk(env, admin_api(env), 500)
    assert pages == [sorted(ids, reverse=True)[:500], [min(ids)]]


def test_order_is_by_import_id_not_imported_at(env: Env) -> None:
    """The newest import is the highest import_id even when its imported_at is
    older (clock steps back): #98 (h) orders by import_id."""
    ids: list[int] = []
    with app(env.server) as c, c.transaction():
        for i, at in enumerate([T0, T0 - timedelta(days=1), T0 + timedelta(days=1)]):
            rec = ImportRecord(f"o-{i}.bit", sha(str(i)), "auto", "success")
            ids.append(insert_import(c, rec, at))
    pages = walk(env, admin_api(env), 1)
    assert pages == [[ids[2]], [ids[1]], [ids[0]]]


def test_rows_added_between_pages_never_repeat_or_reorder_a_page(env: Env) -> None:
    old = seed(env, 4)
    tok = admin_api(env)
    first = page(env, tok, limit=2)
    new = seed(env, 2)
    second = page(env, tok, limit=2, cursor=first["next_cursor"])
    got = [i["import_id"] for i in first["items"] + second["items"]]
    assert got == sorted(old, reverse=True)
    assert second["next_cursor"] is None
    assert [i["import_id"] for i in page(env, tok, limit=2)["items"]] == sorted(
        new, reverse=True
    )


def test_unknown_query_parameters_are_ignored_and_never_filter(env: Env) -> None:
    """#98 (h): no filters. Unknown parameters are ignored, as on the other
    user lists (test_package_query.py::test_unknown_parameters_are_ignored)."""
    seed(env, 1, outcome="success", mode="auto", policy_version=1)
    seed(env, 2)
    tok = admin_api(env)
    plain = page(env, tok)
    assert len(plain["items"]) == 3
    for extra in [
        {"outcome": "success"},
        {"mode": "manual"},
        {"file_name": "nothing"},
        {"status": "rejected"},
        {"order": "asc"},
        {"sort": "import_id"},
        {"before": "1"},
    ]:
        assert page(env, tok, **extra) == plain, extra


@pytest.mark.parametrize("limit", ["0", "501", "-1", "a", "1.5", "", "1e2"])
def test_bad_limit_is_400(env: Env, limit: str) -> None:
    problem(get(env, admin_api(env), limit=limit), 400, "invalid_request")


# CHK-M7-258: cursor safety (#48; 400, never 500) --------------------------------


def a_cursor(env: Env, tok: str) -> str:
    seed(env, 3)
    c = page(env, tok, limit=1)["next_cursor"]
    assert isinstance(c, str)
    return c


def test_tampered_cursors_are_400(env: Env) -> None:
    tok = admin_api(env)
    good = a_cursor(env, tok)
    flip = "A" if good[5] != "A" else "B"
    bad = [
        good[:5] + flip + good[6:],  # MAC byte changed
        good[:-1] + ("A" if good[-1] != "A" else "B"),  # payload changed
        good[:-2],
        good + "A",
        good + "==",
        good + " ",
        "x",
        "W10",
        "!!!!",
        "%00",
        "A" * 512,
    ]
    for c in bad:
        problem(get(env, tok, cursor=c), 400, "invalid_request")
    problem(get(env, tok, cursor="A" * 513), 400, "invalid_request")
    assert page(env, tok, limit=1, cursor=good)["items"]  # the original still works


def test_a_real_cursor_from_another_list_is_400(env: Env) -> None:
    uid, admin = env.admin()
    for _ in range(3):
        env.user("viewer")
        env.token(uid, "api")
    for other in ("/api/v1/users", "/api/v1/api-tokens"):
        r = env.call("GET", admin, other, params={"limit": 1})
        assert r.status_code == 200, r.text
        cursor = r.json()["next_cursor"]
        assert cursor, other
        problem(get(env, admin, cursor=cursor), 400, "invalid_request")


@pytest.mark.parametrize(
    "scope", ["audit_log", "policies", "users", "agents", "api_tokens", "Imports", ""]
)
def test_a_signed_integer_cursor_of_another_scope_is_400(env: Env, scope: str) -> None:
    """A cursor whose MAC is good and whose key is a valid import_id, but which
    was issued for another list (#48)."""
    ids = seed(env, 3)
    problem(
        get(env, admin_api(env), cursor=encode_cursor(scope, max(ids))),
        400,
        "invalid_request",
    )


@pytest.mark.parametrize(
    "key",
    [True, False, 0, -1, -(2**63), 2**63, 2**64, 10**30, "5", "", [5], [], None, 1.5],
    ids=repr,
)
def test_a_signed_cursor_with_a_bad_key_is_400_never_500(env: Env, key: Any) -> None:
    seed(env, 2)
    problem(
        get(env, admin_api(env), cursor=encode_cursor("imports", key)),
        400,
        "invalid_request",
    )


def test_a_dict_key_cursor_is_400(env: Env) -> None:
    problem(
        get(env, admin_api(env), cursor=encode_cursor("imports", {"a": 1})),  # type: ignore[arg-type]
        400,
        "invalid_request",
    )


def test_key_bounds_1_and_2_pow_63_minus_1_are_accepted(env: Env) -> None:
    ids = seed(env, 3)
    tok = admin_api(env)
    assert page(env, tok, cursor=encode_cursor("imports", 1)) == {
        "items": [],
        "next_cursor": None,
    }
    top = page(env, tok, cursor=encode_cursor("imports", 2**63 - 1))
    assert [i["import_id"] for i in top["items"]] == sorted(ids, reverse=True)
    mid = page(env, tok, cursor=encode_cursor("imports", sorted(ids)[1]))
    assert [i["import_id"] for i in mid["items"]] == [min(ids)]


# CHK-M7-258: REQ-173 (2), (4); #98 (h), (i); #110 --------------------------------


def test_every_column_with_its_json_type(env: Env) -> None:
    uid, _ = env.admin()
    at = T0 + timedelta(seconds=1)
    with app(env.server) as c, c.transaction():
        rid = insert_import(
            c,
            ImportRecord(
                file_name="uploaded-name.bit",
                file_sha256=sha("body"),
                mode="manual",
                outcome="success",
                policy_version=7,
                plugins_added=3,
                plugins_updated=2,
                plugins_retired=1,
                errors=WARNINGS,
                imported_by=uid,
            ),
            at,
        )
        sid = insert_import(c, ImportRecord("cis.bit", sha("s"), "auto", "skipped"), at)
    resp = get(env, admin_api(env))
    raw = json.loads(resp.content)
    by_id = {i["import_id"]: i for i in raw["items"]}
    item = by_id[rid]
    assert set(item) == COLUMNS
    assert type(item["import_id"]) is int and item["import_id"] == rid  # #98 (i)
    assert item["file_name"] == "uploaded-name.bit"
    assert item["file_sha256"] == sha("body") and len(item["file_sha256"]) == 64
    assert type(item["policy_version"]) is int and item["policy_version"] == 7
    assert (item["mode"], item["outcome"]) == ("manual", "success")
    assert [
        (type(item[k]), item[k])
        for k in ("plugins_added", "plugins_updated", "plugins_retired")
    ] == [(int, 3), (int, 2), (int, 1)]
    assert item["errors"] == WARNINGS  # warnings on a success (#110)
    assert type(item["imported_by"]) is int and item["imported_by"] == uid
    assert item["imported_at"].endswith("Z")
    assert datetime.fromisoformat(item["imported_at"]) == at
    system = by_id[sid]
    assert set(system) == COLUMNS
    assert system["policy_version"] is None and system["imported_by"] is None
    assert system["errors"] == []
    assert (system["mode"], system["outcome"]) == ("auto", "skipped")
    assert (
        system["plugins_added"],
        system["plugins_updated"],
        system["plugins_retired"],
    ) == (0, 0, 0)


@pytest.mark.parametrize("mode", ["auto", "manual", "rebuild"])
@pytest.mark.parametrize("outcome", ["success", "skipped", "rejected"])
def test_each_mode_and_outcome_round_trips(env: Env, mode: str, outcome: str) -> None:
    (rid,) = seed(env, 1, mode=mode, outcome=outcome)
    (item,) = page(env, admin_api(env))["items"]
    assert (item["import_id"], item["mode"], item["outcome"]) == (rid, mode, outcome)


def test_errors_come_back_exactly_as_stored_warnings_included(env: Env) -> None:
    (rid,) = seed(env, 1, outcome="rejected", errors=ERRORS)
    with env.conn() as c:
        row = c.execute(
            "SELECT errors FROM bit_import WHERE import_id = %s", (rid,)
        ).fetchone()
    assert row is not None
    (item,) = page(env, admin_api(env))["items"]
    assert item["errors"] == row[0] == ERRORS
    assert [e["code"] for e in item["errors"]] == [
        "BIT003",
        "BIT101",
        "BIT103",
        "BIT001",
    ]
    assert all(set(e) == {"line", "element", "code", "message"} for e in item["errors"])


def test_a_large_errors_list_is_returned_whole(env: Env) -> None:
    many = [
        {"line": i, "element": f"Policy/PluginsGroups/Plugin[{i}]", "code": "BIT010",
         "message": "m" * 64}
        for i in range(1, 2001)
    ]  # fmt: skip
    seed(env, 1, errors=many)
    (item,) = page(env, admin_api(env))["items"]
    assert item["errors"] == many


def test_hostile_file_name_comes_back_byte_identical(env: Env) -> None:
    (rid,) = seed(env, 1, file_name=HOSTILE)
    seed(env, 1, file_name=HOSTILE + "-" + tag(), errors=[
        {"line": 1, "element": HOSTILE, "code": "BIT002", "message": HOSTILE}
    ])  # fmt: skip
    resp = get(env, admin_api(env))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["x-content-type-options"] == "nosniff"
    items = json.loads(resp.content)["items"]
    assert items[1]["import_id"] == rid
    assert items[1]["file_name"] == HOSTILE
    assert items[1]["file_name"].encode("utf-8") == HOSTILE.encode("utf-8")
    assert (
        items[0]["errors"][0]["element"] == items[0]["errors"][0]["message"] == HOSTILE
    )


def test_the_read_writes_nothing(env: Env) -> None:
    seed(env, 3)
    tok = admin_api(env)
    before = snapshot(env)
    for _ in range(3):
        page(env, tok, limit=1)
    assert snapshot(env) == before


# CHK-M7-258: REQ-173 (3); TS §6.2 L1107; #53 (i) ---------------------------------


@pytest.mark.parametrize("kind", ["session", "api"])
def test_admin_with_session_or_api_token_gets_200(env: Env, kind: str) -> None:
    ids = seed(env, 2)
    tok = env.token(env.user("admin", totp=True), kind)
    body = page(env, tok)
    assert [i["import_id"] for i in body["items"]] == sorted(ids, reverse=True)


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("viewer", "session"),
        ("viewer", "api"),
        ("operator", "session"),
        ("operator", "api"),
    ],
)
def test_operator_and_viewer_get_403_and_no_rows(
    env: Env, role: str, kind: str
) -> None:
    seed(env, 2, file_name="secret-name.bit")
    resp = get(env, env.token(env.user(role, totp=True), kind))
    problem(resp, 403, "forbidden")
    assert "items" not in resp.json() and b"secret-name" not in resp.content


@pytest.mark.parametrize("kind", ["session", "api"])
def test_admin_without_totp_gets_totp_enrolment_required(env: Env, kind: str) -> None:
    seed(env, 1)
    tok = env.token(env.user("admin", totp=False), kind, verified=False)
    resp = get(env, tok)
    problem(resp, 403, "totp_enrolment_required")
    assert "items" not in resp.json()


# CHK-M7-282: route group (REQ-174 (2)) ------------------------------------------


@pytest.mark.parametrize(
    "token", ["agent", "enrolment", "none", "garbage_bsu", "garbage_bsk", "revoked"]
)
def test_agent_tokens_bad_and_no_token_get_401(env: Env, token: str) -> None:
    seed(env, 1, file_name="secret-name.bit")
    if token == REVOKED:
        tok = admin_api(env)
        with env.conn() as c:
            c.execute(
                "UPDATE user_token SET revoked_at = %s WHERE token_hash = %s",
                (T0, token_hash(tok)),
            )
    else:
        tok = {
            "agent": new_agent_token(AgentTokenKind.AGENT),
            "enrolment": new_agent_token(AgentTokenKind.ENROLMENT),
            "none": "",
            "garbage_bsu": "bsu_" + "x" * 43,
            "garbage_bsk": "bsk_" + "x" * 43,
        }[token]
    resp = env.client.request(
        "GET",
        ROUTE,
        headers={"Authorization": f"Bearer {tok}"} if tok else {},
    )
    assert resp.status_code == 401, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert b"secret-name" not in resp.content


@pytest.mark.parametrize("kind", [AgentTokenKind.AGENT, AgentTokenKind.ENROLMENT])
def test_an_agent_prefix_is_refused_even_if_its_hash_is_an_admin_token(
    env: Env, kind: AgentTokenKind
) -> None:
    """The prefix decides the route group (TS §6 L1056), not the hash lookup:
    a bsa_ or bse_ string whose hash sits in user_token as an admin API token
    is still 401."""
    tok = new_agent_token(kind)
    with env.conn() as c:
        c.execute(
            "INSERT INTO user_token (user_id, kind, token_hash, totp_verified,"
            " expires_at, created_at) VALUES (%s, 'api', %s, false, %s, %s)",
            (
                env.user("admin", totp=True),
                token_hash(tok),
                T0 + timedelta(days=30),
                T0,
            ),
        )
    seed(env, 1, file_name="secret-name.bit")
    resp = env.call("GET", tok, ROUTE)
    assert resp.status_code == 401, resp.text
    assert b"secret-name" not in resp.content


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_there_is_no_write_operation(env: Env, method: str) -> None:
    ids = seed(env, 2)
    tok = admin_api(env)
    before = snapshot(env)
    for path in (ROUTE, f"{ROUTE}/{ids[0]}"):
        r = env.call(method, tok, path, json={})
        assert r.status_code in (404, 405), (method, path, r.status_code)
    assert snapshot(env) == before


def test_the_600_per_minute_user_limit_applies(env: Env) -> None:
    tok = admin_api(env)
    for i in range(600):
        r = get(env, tok, limit=1)
        assert r.status_code == 200, (i, r.text)
    problem(get(env, tok, limit=1), 429, "rate_limited")
    env.clock.at = env.clock.at + timedelta(seconds=61)
    assert get(env, tok, limit=1).status_code == 200


# CHK-M7-281 / G6: the OpenAPI document -------------------------------------------


def test_openapi_documents_the_route_as_an_admin_get_with_limit_and_cursor() -> None:
    doc = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text("utf-8")
    )
    op = doc["paths"][ROUTE]
    assert set(op) == {"get"}
    get_op = op["get"]
    assert {p["name"] for p in get_op["parameters"]} == {"limit", "cursor"}
    limit = next(p for p in get_op["parameters"] if p["name"] == "limit")["schema"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 500, 50)
    assert {"200", "400", "401", "403", "429"} <= set(get_op["responses"])
    for code in ("400", "401", "403", "429"):
        assert set(get_op["responses"][code]["content"]) == {"application/problem+json"}
    ref = get_op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    page_schema = doc["components"]["schemas"][ref.rsplit("/", 1)[1]]
    assert set(page_schema["properties"]) == {"items", "next_cursor"}
    item_ref = page_schema["properties"]["items"]["items"]["$ref"]
    item = doc["components"]["schemas"][item_ref.rsplit("/", 1)[1]]
    assert set(item["properties"]) == COLUMNS == set(item["required"])
    assert item["properties"]["import_id"]["type"] == "integer"
    assert item["properties"]["errors"]["type"] == "array"
    assert set(item["properties"]["mode"]["enum"]) == {"auto", "manual", "rebuild"}
    assert set(item["properties"]["outcome"]["enum"]) == {
        "success",
        "skipped",
        "rejected",
    }
