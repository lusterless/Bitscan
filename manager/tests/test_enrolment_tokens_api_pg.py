"""TASK-066: /api/v1/enrollment-tokens through the API on PostgreSQL (TP-M3-20).

Checks CHK-M3-190 to CHK-M3-195 of tests/m3/test-plan.md, plus the mutation
rows CHK-M3-325, -328, -329 and -336. Expected values come from the spec and
the answers, not from the code: TS §3.2 L181 (max_uses 1-10,000, a required
expiry, optional allowed_cidrs, auto_approve off by default; an auto-approve
or over-100-uses token alerts), TS §6.2 L1083 (bse_ + 256 random bits, only
the SHA-256 stored), L1084 and L1116 (CRUD, admin, TOTP session, API tokens
refused), TS §5.3 L1051 (refused after 15 minutes of sink outage), #48, #68
(bodies: POST {max_uses?, expires_in_hours? 1-720 (24), allowed_cidrs? 1-64
network addresses or null, auto_approve?} -> 201; list and read without the
token, plus revoked_at and created_by; DELETE -> 204, again 204; no PATCH),
#71 (enrollment_token.create / .revoke, one entry per event; the risky token
is one enrolment_token_risky alert flagging both causes), REQ-063 (2), (3),
(5), REQ-067 (1)-(6). Carry-overs: a CIDR with host bits gets 400 before the
database sees it; token shown once; admin TOTP session and sink gate on every
method; admin bsk_ refused.
"""

import json
import threading
from datetime import UTC, timedelta
from typing import Any

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from psycopg import sql

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.enrolment import EnrolmentRepo
from bitscan_manager.services.audit import REGISTRY
from bitscan_manager.services.enrolment import enrolment_tokens as service
from bitscan_manager.services.users import TxAudit

from . import test_users_api_pg as users_api
from .conftest import PgServer
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env  # the M2 users-API environment (clock, sink, shipper, admin)

ROUTE = "/api/v1/enrollment-tokens"
CREATE_KEYS = [
    "token_id",
    "token",
    "max_uses",
    "uses",
    "auto_approve",
    "allowed_cidrs",
    "expires_at",
    "created_at",
]
ITEM_KEYS = {
    "token_id",
    "max_uses",
    "uses",
    "auto_approve",
    "allowed_cidrs",
    "expires_at",
    "created_at",
    "revoked_at",
    "created_by",
}
BSE = re2.compile(r"^bse_[A-Za-z0-9_-]{43}$")
CANARY = "CANARY-066a1b2c3d4e5f60"


def iso(at: Any) -> str:
    """RFC 3339 UTC ending in Z, as the M2 timestamp type writes it."""
    return str(at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))


def snapshot(e: Env) -> tuple[Any, ...]:
    with e.conn() as c:
        tokens = c.execute(
            "SELECT * FROM enrollment_token ORDER BY token_id"
        ).fetchall()
        audit = c.execute("SELECT count(*), max(audit_id) FROM audit_log").fetchone()
    return tokens, audit


def last_audit_id(e: Env) -> int:
    with e.conn() as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


def entries_after(e: Env, audit_id: int) -> list[tuple[Any, ...]]:
    with e.conn() as c:
        return c.execute(
            "SELECT actor, action, target, detail FROM audit_log WHERE audit_id > %s"
            " AND action LIKE 'enrollment_token.%%' ORDER BY audit_id",
            (audit_id,),
        ).fetchall()


def token_row(e: Env, token_id: int) -> dict[str, Any]:
    with e.conn() as c:
        cur = c.execute(
            "SELECT * FROM enrollment_token WHERE token_id = %s", (token_id,)
        )
        cols = [d.name for d in cur.description or []]
        values = cur.fetchone()
    assert values is not None
    return dict(zip(cols, values, strict=True))


def risky_counted() -> float:
    return (
        REGISTRY.get_sample_value(
            "bitscan_alerts_total", {"kind": "enrolment_token_risky"}
        )
        or 0.0
    )


def create(e: Env, tok: str, body: Any = None) -> Any:
    return e.call("POST", tok, ROUTE, json={} if body is None else body)


# ------------------------------------------------------------ CHK-M3-190


def test_create_with_defaults(env: Env) -> None:
    uid, tok = env.admin()
    r = create(env, tok)
    assert r.status_code == 201, r.text
    body = r.json()
    assert list(body) == CREATE_KEYS
    now = env.clock.now()
    assert body["max_uses"] == 1 and body["uses"] == 0
    assert body["auto_approve"] is False and body["allowed_cidrs"] is None
    assert body["expires_at"] == iso(now + timedelta(hours=24))
    assert body["created_at"] == iso(now)
    assert isinstance(body["token_id"], int)
    token = body["token"]
    assert BSE.match(token), token
    row = token_row(env, body["token_id"])
    # REQ-063 (2): only the lowercase SHA-256 hex of the whole token is stored
    assert row["token_hash"] == token_hash(token)
    assert re2.fullmatch(r"[0-9a-f]{64}", row["token_hash"])
    assert (row["max_uses"], row["uses"], row["auto_approve"]) == (1, 0, False)
    assert row["allowed_cidrs"] is None and row["revoked_at"] is None
    assert row["expires_at"] == now + timedelta(hours=24)
    assert row["created_by"] == uid


def test_tokens_are_distinct_and_random(env: Env) -> None:
    _, tok = env.admin()
    made = [create(env, tok).json()["token"] for _ in range(20)]
    assert len(set(made)) == 20
    assert len({t[4:] for t in made}) == 20


@pytest.mark.parametrize(
    ("body", "want"),
    [
        ({"max_uses": 1}, {"max_uses": 1}),
        ({"max_uses": 10_000}, {"max_uses": 10_000}),
        ({"expires_in_hours": 1}, {"hours": 1}),
        ({"expires_in_hours": 720}, {"hours": 720}),
        ({"allowed_cidrs": None}, {"allowed_cidrs": None}),
        ({"auto_approve": False}, {"auto_approve": False}),
    ],
)
def test_create_boundaries_accepted(env: Env, body: dict[str, Any], want: Any) -> None:
    _, tok = env.admin()
    r = create(env, tok, body)
    assert r.status_code == 201, r.text
    got = r.json()
    if "hours" in want:
        assert got["expires_at"] == iso(
            env.clock.now() + timedelta(hours=want["hours"])
        )
    else:
        for k, v in want.items():
            assert got[k] == v


def test_cidrs_are_stored_as_networks(env: Env) -> None:
    _, tok = env.admin()
    sent = ["10.0.0.0/8", "2001:db8::/32", "192.168.1.0/24", "203.0.113.7"]
    r = create(env, tok, {"allowed_cidrs": sent})
    assert r.status_code == 201, r.text
    stored = ["10.0.0.0/8", "2001:db8::/32", "192.168.1.0/24", "203.0.113.7/32"]
    assert r.json()["allowed_cidrs"] == stored
    row = token_row(env, r.json()["token_id"])
    assert [str(c) for c in row["allowed_cidrs"]] == stored
    many = [f"10.{i}.0.0/16" for i in range(64)]
    r = create(env, tok, {"allowed_cidrs": many})
    assert r.status_code == 201, r.text
    assert r.json()["allowed_cidrs"] == many


# ------------------------------------------------------------ CHK-M3-191


def _bad_bodies() -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    table: dict[str, list[Any]] = {
        "max_uses": [0, 10_001, -1, True, 1.5, "5", None, 2**63],
        "expires_in_hours": [0, 721, -24, True, 24.0, "24", None],
        "auto_approve": ["true", 1, 0, None],
        "allowed_cidrs": [
            "10.0.0.0/8",
            [],
            [f"10.{i}.0.0/16" for i in range(65)],
            [5],
            [None],
            ["nope"],
            ["10.0.0.0/33"],
            ["10.0.0.0/8 "],
            ["010.0.0.0/8"],
            [{"cidr": "10.0.0.0/8"}],
            [CANARY],
            ["fe80::%eth0/64"],
        ],
    }
    for key, bad in table.items():
        out += [(f"{key}={v!r}"[:60], {key: v}) for v in bad]
    out += [
        ("host-bits-v4", {"allowed_cidrs": ["10.0.0.1/8"]}),
        ("host-bits-v6", {"allowed_cidrs": ["2001:db8::1/32"]}),
        ("host-bits-among-good", {"allowed_cidrs": ["10.0.0.0/8", "192.168.1.1/24"]}),
        ("unknown-key", {"max_uses": 2, CANARY: 1}),
        ("token-given", {"token": "bse_" + "A" * 43}),
        ("revoked-given", {"revoked_at": "2026-10-21T10:00:00Z"}),
        ("array", [{"max_uses": 2}]),
        ("string", "x"),
        ("number", 3),
    ]
    return out


@pytest.mark.parametrize(
    ("name", "body"), _bad_bodies(), ids=[n for n, _ in _bad_bodies()]
)
def test_create_refusals_write_nothing(env: Env, name: str, body: Any) -> None:
    _, tok = env.admin()
    before = snapshot(env)
    r = create(env, tok, body)
    problem(r, 400, "invalid_request")
    assert CANARY not in r.text  # the detail never echoes a client string
    assert snapshot(env) == before, name


def test_create_with_invalid_json_or_no_body(env: Env) -> None:
    _, tok = env.admin()
    before = snapshot(env)
    r = env.client.post(
        ROUTE,
        content=b"{not json",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    problem(r, 400, "invalid_request")
    assert snapshot(env) == before


# ------------------------------------------------------------ CHK-M3-192


def test_token_appears_only_in_the_create_response(env: Env) -> None:
    uid, tok = env.admin()
    made = [create(env, tok, {"max_uses": n}).json() for n in (2, 3, 4)]
    tokens = [m["token"] for m in made]
    ids = [m["token_id"] for m in made]
    hashes = [token_hash(t) for t in tokens]
    texts: list[str] = []
    for tid in ids:
        r = env.call("GET", tok, f"{ROUTE}/{tid}")
        assert r.status_code == 200, r.text
        item = r.json()
        assert set(item) == ITEM_KEYS
        assert item["created_by"] == uid and item["revoked_at"] is None
        texts.append(r.text)
    # paginate the whole list
    seen: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = env.call("GET", tok, ROUTE, params=params)
        assert r.status_code == 200, r.text
        page = r.json()
        assert set(page) == {"items", "next_cursor"}
        assert len(page["items"]) <= 2
        texts.append(r.text)
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    seen_ids = [i["token_id"] for i in seen]
    assert seen_ids == sorted(set(seen_ids))  # token_id order, no repeats
    assert set(ids) <= set(seen_ids)
    assert all(set(i) == ITEM_KEYS for i in seen)
    for text in texts:
        for t, h in zip(tokens, hashes, strict=True):
            assert t not in text and t[4:] not in text and h not in text
        assert "token_hash" not in text and '"token"' not in text


def test_list_refuses_a_tampered_cursor(env: Env) -> None:
    _, tok = env.admin()
    for _ in range(3):
        create(env, tok)
    r = env.call("GET", tok, ROUTE, params={"limit": 1})
    cursor = r.json()["next_cursor"]
    assert isinstance(cursor, str)
    bad = cursor[:-2] + ("AA" if not cursor.endswith("AA") else "BB")
    problem(env.call("GET", tok, ROUTE, params={"cursor": bad}), 400, "invalid_request")


@pytest.mark.parametrize("path", ["abc", "-1", "0", "1.5", "99999999999999999999"])
def test_read_unknown_or_malformed_id(env: Env, path: str) -> None:
    _, tok = env.admin()
    for method in ("GET", "DELETE"):
        r = env.call(method, tok, f"{ROUTE}/{path}")
        assert r.status_code in (400, 404), (method, path, r.status_code, r.text)
        problem(
            r, r.status_code, "invalid_request" if r.status_code == 400 else "not_found"
        )


def test_no_patch_route(env: Env) -> None:
    _, tok = env.admin()
    tid = create(env, tok).json()["token_id"]
    r = env.call("PATCH", tok, f"{ROUTE}/{tid}", json={"max_uses": 9})
    assert r.status_code == 405, r.text
    assert token_row(env, tid)["max_uses"] == 1


def test_no_issued_token_at_rest(env: Env, migrated_db: PgServer) -> None:
    """REQ-063 (3) for enrolment tokens: no text, char or JSON column of any
    table holds a token issued here (read as owner); the hash is found."""
    _, tok = env.admin()
    issued = [
        create(env, tok, body).json()["token"]
        for body in ({}, {"auto_approve": True}, {"max_uses": 500}, {"max_uses": 5})
    ]
    tid = create(env, tok).json()
    issued.append(tid["token"])
    env.call("DELETE", tok, f"{ROUTE}/{tid['token_id']}")
    needles = [*issued, *(t[4:] for t in issued)]
    hits: list[str] = []
    with migrated_db.connect("bitscan_migrate") as c:
        c.execute("SET ROLE bitscan_owner")
        cols = c.execute(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c"
            " JOIN information_schema.tables t USING (table_schema, table_name)"
            " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
            " AND c.data_type IN ('text', 'character varying', 'character',"
            " 'json', 'jsonb') ORDER BY 1, 2"
        ).fetchall()
        assert ("enrollment_token", "token_hash") in cols
        for table, column in cols:
            query = sql.SQL(
                "SELECT count(*) FROM {} WHERE strpos({}::text, %s) > 0"
            ).format(sql.Identifier(table), sql.Identifier(column))
            for needle in needles:
                row = c.execute(query, (needle,)).fetchone()
                if row is not None and row[0]:
                    hits.append(f"{table}.{column}")
            if (table, column) == ("enrollment_token", "token_hash"):
                for t in issued:
                    row = c.execute(query, (token_hash(t),)).fetchone()
                    assert row == (1,)
    assert hits == []


# ------------------------------------------------------------ CHK-M3-193


@pytest.mark.parametrize(
    ("body", "flags"),
    [
        ({"auto_approve": True}, {"auto_approve": True, "over_100_uses": False}),
        ({"max_uses": 101}, {"auto_approve": False, "over_100_uses": True}),
        (
            {"auto_approve": True, "max_uses": 10_000},
            {"auto_approve": True, "over_100_uses": True},
        ),
        ({"max_uses": 100}, None),
        ({"max_uses": 1, "auto_approve": False}, None),
    ],
)
def test_create_audit_and_risky_alert(
    env: Env, body: dict[str, Any], flags: dict[str, bool] | None
) -> None:
    uid, tok = env.admin()
    after = last_audit_id(env)
    counted = risky_counted()
    r = create(env, tok, {**body, "allowed_cidrs": ["10.0.0.0/8"]})
    assert r.status_code == 201, r.text
    made = r.json()
    entries = entries_after(env, after)
    assert len(entries) == 1  # one entry per event (#71)
    actor, action, target, detail = entries[0]
    assert (actor, action, target) == (
        f"user:{uid}",
        "enrollment_token.create",
        f"enrollment_token:{made['token_id']}",
    )
    text = json.dumps(detail)
    assert made["token"] not in text and token_hash(made["token"]) not in text
    assert made["token"][4:] not in text
    if flags is None:
        assert "alert" not in detail
        assert risky_counted() == counted
    else:
        assert detail["alert"] is True
        assert detail["alert_kind"] == "enrolment_token_risky"
        assert detail["risky"] == flags
        assert risky_counted() == counted + 1
    with env.conn() as c:
        alerts = c.execute(
            "SELECT count(*) FROM audit_log WHERE audit_id > %s"
            " AND detail->>'alert_kind' = 'enrolment_token_risky'",
            (after,),
        ).fetchone()
    assert alerts == ((0,) if flags is None else (1,))


# ------------------------------------------------------------ CHK-M3-194


def _every_method(tid: int) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("POST", ROUTE, {"json": {"auto_approve": True}}),
        ("GET", ROUTE, {}),
        ("GET", f"{ROUTE}/{tid}", {}),
        ("DELETE", f"{ROUTE}/{tid}", {}),
    ]


def test_every_method_refuses_api_tokens_unverified_and_lower_roles(env: Env) -> None:
    admin, admin_tok = env.admin()
    tid = create(env, admin_tok).json()["token_id"]
    api = env.token(admin, "api")
    unverified = env.token(admin, "session", verified=False)
    op = env.user("operator", totp=True)
    viewer = env.user("viewer", totp=True)
    cases = [
        (api, 403, "totp_session_required"),
        (unverified, 403, "totp_enrolment_required"),
        (env.token(op), 403, "forbidden"),
        # #48: an API token on a TOTP-session route, whatever its role
        (env.token(op, "api"), 403, "totp_session_required"),
        (env.token(viewer), 403, "forbidden"),
        (new_agent_token(AgentTokenKind.ENROLMENT), 401, "unauthorized"),
        (new_agent_token(AgentTokenKind.AGENT), 401, "unauthorized"),
    ]
    for method, path, kw in _every_method(tid):
        for credential, status, type_ in cases:
            before = snapshot(env)
            problem(env.call(method, credential, path, **kw), status, type_)
            assert snapshot(env) == before, (method, path, type_)
        before = snapshot(env)
        problem(env.client.request(method, path, **kw), 401, "unauthorized")
        assert snapshot(env) == before
    assert token_row(env, tid)["revoked_at"] is None


def test_an_issued_bse_token_is_not_a_user_credential(env: Env) -> None:
    _, tok = env.admin()
    issued = create(env, tok).json()["token"]
    problem(env.call("GET", issued, ROUTE), 401, "unauthorized")


def test_every_method_refused_during_the_sink_outage(env: Env) -> None:
    _, tok = env.admin()
    tid = create(env, tok).json()["token_id"]
    env.sink.up = False
    env.shipper.run_once()  # first failed delivery: the outage starts now
    start = env.clock.now()
    env.clock.at = start + timedelta(minutes=14, seconds=59)
    assert env.call("GET", tok, f"{ROUTE}/{tid}").status_code == 200
    env.clock.at = start + timedelta(minutes=15)
    for method, path, kw in _every_method(tid):
        before = snapshot(env)
        problem(env.call(method, tok, path, **kw), 503, "audit_sink_unavailable")
        assert snapshot(env) == before, (method, path)
    env.sink.up = True
    for _ in range(5):
        env.clock.at += timedelta(seconds=31)
        env.shipper.run_once()
    assert env.shipper.refusing() is False
    assert create(env, tok).status_code == 201


# ------------------------------------------------------------ CHK-M3-195


def test_delete_revokes_keeps_the_row_and_audits_once(env: Env) -> None:
    uid, tok = env.admin()
    made = create(env, tok, {"max_uses": 5}).json()
    tid = made["token_id"]
    after = last_audit_id(env)
    revoked = env.clock.now()
    r = env.call("DELETE", tok, f"{ROUTE}/{tid}")
    assert r.status_code == 204 and r.content == b""
    env.clock.at += timedelta(minutes=5)
    r = env.call("DELETE", tok, f"{ROUTE}/{tid}")
    assert r.status_code == 204 and r.content == b""
    row = token_row(env, tid)
    assert row["revoked_at"] == revoked  # the first revoke time is kept
    assert row["token_hash"] == token_hash(made["token"])
    assert [e[:3] for e in entries_after(env, after)] == [
        (f"user:{uid}", "enrollment_token.revoke", f"enrollment_token:{tid}")
    ]
    item = env.call("GET", tok, f"{ROUTE}/{tid}").json()
    assert item["revoked_at"] == iso(revoked)
    # a revoked token can no longer be used (TASK-067 re-checks through enrol)
    with env.conn() as c, c.transaction():
        used = EnrolmentRepo(c).use_token(
            token_hash(made["token"]), "10.0.0.1", env.clock.now()
        )
    assert used is None
    assert token_row(env, tid)["uses"] == 0
    problem(env.call("DELETE", tok, f"{ROUTE}/999999999"), 404, "not_found")


def test_concurrent_deletes_write_one_revoke_entry(
    env: Env, migrated_db: PgServer
) -> None:
    """Two admins revoking the same token at the same moment: one revoke, one
    entry (#71: one entry per event)."""
    uid, tok = env.admin()
    tid = create(env, tok).json()["token_id"]
    after = last_audit_id(env)
    barrier = threading.Barrier(2, timeout=30)
    errors: list[BaseException] = []

    class Synced(EnrolmentRepo):
        def get_token(self, token_id: int) -> Any:
            row = super().get_token(token_id)
            barrier.wait()  # both have read the token before either revokes
            return row

    def run() -> None:
        try:
            with psycopg.connect(migrated_db.dsn("bitscan_app")) as c:
                with c.transaction():
                    service.revoke_token(
                        Synced(c),
                        TxAudit(PgAuditRepo(c), lambda hook: None),
                        admin_id=uid,
                        token_id=tid,
                        now=env.clock.now(),
                    )
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert [e[1] for e in entries_after(env, after)] == ["enrollment_token.revoke"]
