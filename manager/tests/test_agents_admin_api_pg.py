"""TASK-077: PUT /api/v1/agents/{id}/tags and POST /api/v1/agents/{id}/revoke on
PostgreSQL (TP-M3-31).

Checks CHK-M3-280 to CHK-M3-283 of tests/m3/test-plan.md and the API halves of
the mutation rows CHK-M3-328 (revoke), -330 and -372. Expected values come from
the spec and the answers, not from the code: TS §6.2 L1084 (revoke is a
sensitive action: admin, TOTP-verified session, API tokens refused), L1112
(tags: operator), L1113 (revoke forces re-enrolment), TS §3.2 L191 (a revoked
token gets 401 token_revoked), TS §5.3 L1051 (sensitive actions refused after
15 minutes of sink outage), TS §5.2 L742-L746 (agent_tag VARCHAR(64)), #68
(PUT {tags} replaces the set, 0-32 distinct tags of 1-64 characters from
[A-Za-z0-9._:-]; 200 {tags}; revoke 204, again 204), #71 (agent.tags_set,
agent.revoke, actor user:<id>), #73 (c) (revoke does not change the status),
REQ-068 (4) (a re-enrolment of that machine-id is held), REQ-082 (1)-(4).
The M2 users-API environment provides the real sink gate and shipper.
"""

import threading
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from . import test_enrolment_requests_api_pg as rq
from . import test_users_api_pg as users_api
from .test_users_api_pg import Env, problem

pytestmark = pytest.mark.pg

env = users_api.env

OK_CHARS = "ABCxyz019._:-"


def agent_path(h: rq.Host, tail: str) -> str:
    return f"/api/v1/agents/{h.agent_id}/{tail}"


def host(e: Env) -> rq.Host:
    """An enrolled, heartbeating host made through the real enrol route."""
    h = rq.enrol(e, auto=True)
    assert h.status == "enrolled"
    assert rq.beat(e, h).status_code == 200
    return h


def tags_of(e: Env, h: rq.Host) -> list[str]:
    with e.conn() as c:
        rows = c.execute(
            "SELECT tag FROM agent_tag WHERE agent_id = %s ORDER BY tag", (h.agent_id,)
        ).fetchall()
    return [r[0] for r in rows]


def entries(e: Env, h: rq.Host, action: str) -> list[tuple[Any, ...]]:
    with e.conn() as c:
        return c.execute(
            "SELECT actor, action, target, detail FROM audit_log WHERE target = %s"
            " AND action = %s ORDER BY audit_id",
            (f"agent:{h.agent_id}", action),
        ).fetchall()


def agent_row(e: Env, h: rq.Host) -> dict[str, Any]:
    with e.conn() as c:
        cur = c.execute("SELECT * FROM agent WHERE agent_id = %s", (h.agent_id,))
        cols = [d.name for d in cur.description or []]
        values = cur.fetchone()
    assert values is not None
    return dict(zip(cols, values, strict=True))


def put_tags(e: Env, tok: str, h: rq.Host, body: Any) -> Any:
    return e.call("PUT", tok, agent_path(h, "tags"), json=body)


def operator(e: Env, kind: str = "session") -> tuple[int, str]:
    uid = e.user("operator")
    return uid, e.token(uid, kind)


# ------------------------------------------------------------ CHK-M3-280


def test_operator_sets_then_clears_tags(env: Env) -> None:
    """REQ-082 (1), #68: an operator replaces the set with ["prod-web", "db"]
    (200 {tags}), the host detail shows exactly that set, and [] clears it."""
    uid, tok = operator(env)
    h = host(env)
    r = put_tags(env, tok, h, {"tags": ["prod-web", "db"]})
    assert r.status_code == 200, r.text
    assert list(r.json()) == ["tags"] and sorted(r.json()["tags"]) == ["db", "prod-web"]
    assert tags_of(env, h) == ["db", "prod-web"]
    d = env.call("GET", tok, f"/api/v1/agents/{h.agent_id}").json()
    assert sorted(d["tags"]) == ["db", "prod-web"]
    r = put_tags(env, tok, h, {"tags": ["web"]})
    assert r.status_code == 200 and r.json()["tags"] == ["web"]
    assert tags_of(env, h) == ["web"]  # replaced, not merged
    r = put_tags(env, tok, h, {"tags": []})
    assert r.status_code == 200 and r.json() == {"tags": []}
    assert tags_of(env, h) == []


@pytest.mark.parametrize("who", ["operator-bsk", "admin-session", "admin-bsk"])
def test_operator_and_admin_by_session_or_api_token(env: Env, who: str) -> None:
    """TS §6.2: operator and above, session or API token (not a sensitive
    action)."""
    role, kind = who.split("-")
    uid = env.user(role, totp=role == "admin")
    tok = env.token(uid, "api" if kind == "bsk" else "session")
    h = host(env)
    assert put_tags(env, tok, h, {"tags": ["x1"]}).status_code == 200
    assert tags_of(env, h) == ["x1"]


def test_largest_valid_set(env: Env) -> None:
    """#68 bounds: 32 distinct tags of 64 characters from the whole allowed
    alphabet are accepted."""
    _, tok = operator(env)
    h = host(env)
    tags = [f"{i:02d}" + (OK_CHARS * 6)[: 64 - 2] for i in range(32)]
    assert all(len(t) == 64 for t in tags)
    r = put_tags(env, tok, h, {"tags": tags})
    assert r.status_code == 200, r.text
    assert tags_of(env, h) == sorted(tags)


@pytest.mark.parametrize(
    "body",
    [
        {"tags": [f"t{i}" for i in range(33)]},
        {"tags": ["a" * 65]},
        {"tags": [""]},
        {"tags": ["has space"]},
        {"tags": ["café"]},
        {"tags": ["<script>"]},
        {"tags": ["a/b"]},
        {"tags": ["a,b"]},
        {"tags": ["dup", "dup"]},
        {"tags": [1]},
        {"tags": None},
        {"tags": "prod"},
        {},
        {"tags": ["ok"], "extra": 1},
        ["ok"],
    ],
    ids=[
        "33-tags",
        "65-chars",
        "empty-tag",
        "space",
        "non-ascii",
        "angle",
        "slash",
        "comma",
        "duplicate",
        "not-string",
        "null",
        "string",
        "missing",
        "extra-key",
        "array",
    ],
)
def test_invalid_tags_are_400_and_change_nothing(env: Env, body: Any) -> None:
    """REQ-082 (1), #68: refused with 400 invalid_request; the existing set and
    the audit log are unchanged."""
    _, tok = operator(env)
    h = host(env)
    assert put_tags(env, tok, h, {"tags": ["keep"]}).status_code == 200
    before = entries(env, h, "agent.tags_set")
    problem(put_tags(env, tok, h, body), 400, "invalid_request")
    assert tags_of(env, h) == ["keep"]
    assert entries(env, h, "agent.tags_set") == before


@pytest.mark.parametrize("who", ["viewer-session", "viewer-bsk", "none", "bsa"])
def test_viewer_and_others_cannot_set_tags(env: Env, who: str) -> None:
    """REQ-082 (1), CHK-M3-372: a viewer gets 403 forbidden; no token or an
    agent token gets 401; nothing changes."""
    h = host(env)
    if who.startswith("viewer"):
        uid = env.user("viewer")
        tok = env.token(uid, "api" if who.endswith("bsk") else "session")
        problem(put_tags(env, tok, h, {"tags": ["x"]}), 403, "forbidden")
    elif who == "bsa":
        problem(put_tags(env, h.token, h, {"tags": ["x"]}), 401, "unauthorized")
    else:
        r = env.client.put(agent_path(h, "tags"), json={"tags": ["x"]})
        problem(r, 401, "unauthorized")
    assert tags_of(env, h) == []
    assert entries(env, h, "agent.tags_set") == []


def test_tags_of_an_unknown_agent_is_404(env: Env) -> None:
    _, tok = operator(env)
    import uuid

    r = env.call("PUT", tok, f"/api/v1/agents/{uuid.uuid4()}/tags", json={"tags": []})
    problem(r, 404, "not_found")


# ------------------------------------------------------------ CHK-M3-281


def test_revoke_ends_the_current_and_previous_token(env: Env) -> None:
    """REQ-082 (2), TS §3.2 L191, #73 (c): after revoke the agent's current
    token and its rotation-overlap token get 401 token_revoked on every agent
    call; the status is unchanged."""
    _, admin = env.admin()
    h = host(env)
    old = h.token
    with rq.client(env) as c:  # rotate inside the window: make one first
        with env.conn() as conn:
            conn.execute(
                "UPDATE agent SET"
                " token_issued_at = token_issued_at - interval '340 days',"
                " token_expires_at = token_expires_at - interval '340 days'"
                " WHERE agent_id = %s",
                (h.agent_id,),
            )
        r = c.post(
            f"/api/v1/agent/{h.agent_id}/token/rotate",
            headers={
                "Authorization": f"Bearer {old}",
                "X-Bitscan-Machine-Id": h.machine_id,
            },
        )
    assert r.status_code == 200, r.text
    new = r.json()["agent_token"]
    assert rq.beat(env, h, new).status_code == 200  # first use: overlap starts
    assert rq.beat(env, h, old).status_code == 200  # inside the 10 minutes
    status = agent_row(env, h)["status"]
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204
    row = agent_row(env, h)
    assert row["token_revoked_at"] == env.clock.now()
    assert row["status"] == status
    for tok in (new, old):
        problem(rq.beat(env, h, tok), 401, "token_revoked")
        with rq.client(env) as c:
            problem(
                c.get(
                    f"/api/v1/agent/{h.agent_id}/jobs",
                    headers={
                        "Authorization": f"Bearer {tok}",
                        "X-Bitscan-Machine-Id": h.machine_id,
                    },
                ),
                401,
                "token_revoked",
            )


def test_after_revoke_a_reenrolment_is_held(env: Env) -> None:
    """REQ-082 (2), REQ-068 (4): the host must re-enrol; a re-enrolment of
    that machine-id, even with an auto-approve token, is held, and the
    existing row stays revoked."""
    _, admin = env.admin()
    h = host(env)
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204
    before = agent_row(env, h)
    again = rq.enrol(env, machine=h.machine_id, auto=True)
    assert again.agent_id == h.agent_id
    assert again.status == "awaiting_approval"
    assert agent_row(env, h) == before
    problem(rq.beat(env, again), 403, "pending_approval")


# ------------------------------------------------------------ CHK-M3-282


@pytest.mark.parametrize(
    "who",
    [
        "admin-bsk",
        "admin-unverified",
        "operator-session",
        "viewer-session",
        "bsa",
        "none",
    ],
)
def test_revoke_refuses_everything_but_an_admin_totp_session(
    env: Env, who: str
) -> None:
    """REQ-082 (3), TS §6.2 L1084, CHK-M3-330: an admin bsk_ and an
    unverified admin session get 403; operator and viewer sessions 403
    forbidden; an agent token or no token 401; the token stays valid."""
    h = host(env)
    if who == "admin-bsk":
        uid = env.user("admin", totp=True)
        problem(
            env.call("POST", env.token(uid, "api"), agent_path(h, "revoke")),
            403,
            "totp_session_required",
        )
    elif who == "admin-unverified":
        uid = env.user("admin", totp=True)
        r = env.call("POST", env.token(uid, verified=False), agent_path(h, "revoke"))
        assert r.status_code == 403, r.text
        assert r.json()["type"] in ("totp_session_required", "totp_enrolment_required")
    elif who.endswith("session"):
        uid = env.user(who.split("-")[0])
        problem(
            env.call("POST", env.token(uid), agent_path(h, "revoke")), 403, "forbidden"
        )
    elif who == "bsa":
        problem(env.call("POST", h.token, agent_path(h, "revoke")), 401, "unauthorized")
    else:
        problem(env.client.post(agent_path(h, "revoke")), 401, "unauthorized")
    assert agent_row(env, h)["token_revoked_at"] is None
    assert rq.beat(env, h).status_code == 200
    assert entries(env, h, "agent.revoke") == []


def test_revoke_refused_during_the_sink_outage(env: Env) -> None:
    """TS §5.3 L1051, CHK-M3-328: 15 minutes into a sink outage revoke is 503
    audit_sink_unavailable with nothing changed; after the queue drains it
    works. Tags (not a sensitive action) still work during the outage."""
    _, admin = env.admin()
    _, op = operator(env)
    h = host(env)
    env.sink.up = False
    env.shipper.run_once()
    env.clock.at = env.clock.now() + timedelta(minutes=15)
    problem(
        env.call("POST", admin, agent_path(h, "revoke")), 503, "audit_sink_unavailable"
    )
    assert agent_row(env, h)["token_revoked_at"] is None
    assert put_tags(env, op, h, {"tags": ["during"]}).status_code == 200
    env.sink.up = True
    for _ in range(5):
        env.clock.at += timedelta(seconds=31)
        env.shipper.run_once()
    assert env.shipper.refusing() is False
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204


def test_revoke_again_is_204_and_keeps_the_first_time(env: Env) -> None:
    """#68: revoke again → 204; revoked_at is the first one; one entry."""
    _, admin = env.admin()
    h = host(env)
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204
    first = agent_row(env, h)["token_revoked_at"]
    env.clock.at = env.clock.now() + timedelta(minutes=5)
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204
    assert agent_row(env, h)["token_revoked_at"] == first
    assert len(entries(env, h, "agent.revoke")) == 1


def test_revoke_of_an_unknown_agent_is_404(env: Env) -> None:
    import uuid

    _, admin = env.admin()
    problem(
        env.call("POST", admin, f"/api/v1/agents/{uuid.uuid4()}/revoke"),
        404,
        "not_found",
    )


# ------------------------------------------------------------ CHK-M3-283


def test_each_change_writes_one_entry(env: Env) -> None:
    """REQ-082 (4), #71: each tag set writes one agent.tags_set entry (actor
    user:<id>, target agent:<id>, the old and the new set); a revoke writes
    one agent.revoke entry; neither holds a token."""
    op_uid, op = operator(env)
    admin_uid, admin = env.admin()
    h = host(env)
    put_tags(env, op, h, {"tags": ["b", "a"]})
    put_tags(env, op, h, {"tags": []})
    tags = entries(env, h, "agent.tags_set")
    assert len(tags) == 2
    assert all(e[0] == f"user:{op_uid}" and e[2] == f"agent:{h.agent_id}" for e in tags)
    assert sorted(tags[0][3]["new"]) == ["a", "b"] and tags[0][3]["old"] == []
    assert tags[1][3]["new"] == [] and sorted(tags[1][3]["old"]) == ["a", "b"]
    assert env.call("POST", admin, agent_path(h, "revoke")).status_code == 204
    (rev,) = entries(env, h, "agent.revoke")
    assert rev[0] == f"user:{admin_uid}"
    assert (rev[3] or {}).get("alert") is not True
    text = str(tags) + str(rev)
    assert h.token not in text and h.token[4:] not in text


def test_concurrent_revokes_write_one_entry(env: Env) -> None:
    """Row lock: four simultaneous revokes give 204 each and one entry."""
    _, admin = env.admin()
    h = host(env)
    barrier = threading.Barrier(4)
    codes: list[int] = []
    lock = threading.Lock()

    def one() -> None:
        with rq.client(env) as c:
            barrier.wait(timeout=30)
            r = c.post(
                agent_path(h, "revoke"), headers={"Authorization": f"Bearer {admin}"}
            )
            with lock:
                codes.append(r.status_code)

    threads = [threading.Thread(target=one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert codes == [204] * 4
    assert len(entries(env, h, "agent.revoke")) == 1


def test_tag_replace_is_all_or_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the delete leaves the old set (one transaction) and
    writes no entry."""
    from bitscan_manager.repositories.audit_log import PgAuditRepo

    _, op = operator(env)
    h = host(env)
    assert put_tags(env, op, h, {"tags": ["old1", "old2"]}).status_code == 200
    before = entries(env, h, "agent.tags_set")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise psycopg.errors.QueryCanceled("injected")

    monkeypatch.setattr(PgAuditRepo, "allocate", boom)  # the entry after the replace
    r = put_tags(env, op, h, {"tags": ["new"]})
    assert r.status_code >= 500
    assert tags_of(env, h) == ["old1", "old2"]
    assert entries(env, h, "agent.tags_set") == before
