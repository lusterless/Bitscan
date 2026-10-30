"""TASK-205 TEST (and r1): POST /api/v1/scans and POST /api/v1/scans/{id}/
cancel through the API on PostgreSQL (TP-M9-17; CHK-M9-240 to -246;
mutation rows CHK-M9-364 to -366, -382).

Expected values: TS §6.2 L1119 (POST /scans: operator), L1122 (cancel:
operator), L1084 (not sensitive: session or API token), §6.3 L1133–L1138
(problem details; Idempotency-Key; body cap 1 MiB), §6.4 L1146–L1155 (the
202 body), §8.4 L1290 (an all-hosts scan started with an API token alerts),
§3.3 L213 (no ad-hoc command); #3, #48, #122 (a)–(g), #123, #129 (b);
REQ-212 (1), REQ-220 (2), REQ-221, REQ-222 (3), (4).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from bitscan_manager.repositories import scan_queue

from . import scan_pg_fixtures as f
from .agent_sim import SCANS, ApiEnv, alerts_total, api_env, batch, item
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

KIND = "all_hosts_scan_api_token"
MIB = 1_048_576


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("scans-api")) as s:
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
    assert r.headers["content-type"].startswith("application/problem+json"), r.headers
    body: dict[str, Any] = r.json()
    assert body["type"] == type_ and body["status"] == status, body
    return body


def counts(env: ApiEnv) -> tuple[int, int, int, int]:
    with env.conn() as c:
        return f.counts(c)


def entries(env: ApiEnv, mark: int) -> list[dict[str, Any]]:
    with env.conn() as c:
        return f.audit_after(c, mark)


def mark_of(env: ApiEnv) -> int:
    with env.conn() as c:
        return f.last_audit(c)


# ------------------------------------------------------------ CHK-M9-240


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("operator", "api"),
        ("admin", "session"),
        ("admin", "api"),
    ],
)
def test_operator_and_admin_queue_a_scan_with_a_session_or_an_api_token(
    env: ApiEnv, cat: f.Catalog, role: str, kind: str
) -> None:
    """REQ-221 (1), TS §6.4: 202 with exactly {scan_id, state: "queued",
    policy_version, jobs}; the scan row is requested_by the caller."""
    pol = cat.policy(1)
    a = env.agent()
    uid, tok = env.caller(role, kind)
    r = env.call(
        "POST",
        SCANS,
        tok,
        body={"policy_id": pol.policy_id, "target": {"agents": [str(a.agent_id)]}},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert set(body) == {"scan_id", "state", "policy_version", "jobs"}
    assert (body["state"], body["policy_version"], body["jobs"]) == (
        "queued",
        pol.version,
        1,
    )
    with env.conn() as c:
        row = f.scan_row(c, UUID(body["scan_id"]))
    assert row["requested_by"] == uid and row["trigger"] == "manual"


def test_viewer_is_403_and_agent_missing_or_revoked_tokens_are_401(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-221 (1), TS §6 route groups, CHK-M9-364, -365: a viewer gets 403; a
    bsa_ token, no token and a revoked token get 401; nothing is written."""
    pol = cat.policy(1)
    a = env.agent()
    body = {"policy_id": pol.policy_id, "target": {"all": True}}
    before = counts(env)
    _, viewer = env.caller("viewer")
    problem(env.call("POST", SCANS, viewer, body=body), 403, "forbidden")
    for tok in (a.row.token, None, env.token(env.user("operator"), revoked=True)):
        r = env.call("POST", SCANS, tok, body=body)
        assert r.status_code == 401, (tok, r.text)
    assert counts(env) == before


# ------------------------------------------------------------ CHK-M9-241


def test_refusals_answer_their_problem_and_write_nothing(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-221 (2), #122 (f), #3, #48, REQ-212 (1), CHK-M9-382: unknown policy
    404; disabled 409; deleted 409; no eligible agent 422 about:blank "The
    target resolves to no host."; a malformed target, an extra key (plugins,
    execute, command, payload, eval_spec) and a non-integer policy_id 400; a
    body over 1 MiB 413. Each writes no scan, job or audit entry."""
    off = cat.policy(1, status="disabled")
    gone = cat.policy(1)
    cat.delete(gone)
    live = cat.policy(1)
    dec = env.agent("decommissioned")
    _, tok = env.caller("operator")
    t_all = {"all": True}
    cases: list[tuple[Any, int, str]] = [
        ({"policy_id": 2**40, "target": t_all}, 404, "not_found"),
        ({"policy_id": off.policy_id, "target": t_all}, 409, "conflict"),
        ({"policy_id": gone.policy_id, "target": t_all}, 409, "conflict"),
        (
            {"policy_id": live.policy_id, "target": {"agents": [str(dec.agent_id)]}},
            422,
            "about:blank",
        ),
        (
            {"policy_id": live.policy_id, "target": {"all": False}},
            400,
            "invalid_request",
        ),
        (
            {"policy_id": live.policy_id, "target": {"agents": [], "tags": ["x"]}},
            400,
            "invalid_request",
        ),
        ({"policy_id": "1", "target": t_all}, 400, "invalid_request"),
        ({"target": t_all}, 400, "invalid_request"),
        *(
            (
                {"policy_id": live.policy_id, "target": t_all, extra: "echo pwned"},
                400,
                "invalid_request",
            )
            for extra in ("plugins", "execute", "command", "payload", "eval_spec")
        ),
        (
            {"policy_id": live.policy_id, "target": {"all": True, "execute": "id"}},
            400,
            "invalid_request",
        ),
    ]
    before = counts(env)
    for body, status, type_ in cases:
        p = problem(env.call("POST", SCANS, tok, body=body), status, type_)
        if status == 422:
            assert p["detail"] == "The target resolves to no host."
        if status == 409:
            assert p["detail"] in ("The policy is disabled.", "The policy is deleted.")
        assert "pwned" not in json.dumps(p)
    raw = json.dumps({"policy_id": live.policy_id, "target": t_all}).encode()
    problem(
        env.call("POST", SCANS, tok, content=raw + b" " * (MIB + 1 - len(raw))),
        413,
        "too_large",
    )
    assert counts(env) == before


def test_a_body_of_exactly_1_mib_is_read(env: ApiEnv, cat: f.Catalog) -> None:
    """TS §6.3 L1138: 1,048,576 bytes are within the cap (202)."""
    pol = cat.policy(1)
    a = env.agent()
    _, tok = env.caller("operator")
    raw = json.dumps(
        {"policy_id": pol.policy_id, "target": {"agents": [str(a.agent_id)]}}
    ).encode()
    r = env.call("POST", SCANS, tok, content=raw + b" " * (MIB - len(raw)))
    assert r.status_code == 202, r.text


# ------------------------------------------------------------ CHK-M9-242


def test_an_all_hosts_scan_with_an_api_token_alerts(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-221 (3), REQ-227 (2), TS §8.4 L1290, #129 (b), CHK-M9-366: {"all":
    true} with a bsk_ token writes the scan.create entry as the alert
    (detail.alert true, alert_kind), the fake sink receives it and
    bitscan_alerts_total{kind} grows by 1; the same with a session, and tags
    with a bsk_ token, raise nothing (and 202, not 500)."""
    pol = cat.policy(1)
    tag = f.new_tag()
    env.agent(tags=[tag])
    _, api = env.caller("operator", "api")
    _, ses = env.caller("operator", "session")
    base = alerts_total(KIND)
    m = mark_of(env)
    r = env.call(
        "POST", SCANS, api, body={"policy_id": pol.policy_id, "target": {"all": True}}
    )
    assert r.status_code == 202, r.text
    assert alerts_total(KIND) == base + 1
    (e,) = entries(env, m)
    assert (e["action"], e["detail"]["alert"], e["detail"]["alert_kind"]) == (
        "scan.create",
        True,
        KIND,
    )
    env.shipper.run_once()
    assert any(
        rec.action == "scan.create" and KIND in (rec.detail_text or "")
        for rec in env.sink.records
    )
    for tok, target in ((ses, {"all": True}), (api, {"tags": [tag]})):
        m = mark_of(env)
        r = env.call(
            "POST", SCANS, tok, body={"policy_id": pol.policy_id, "target": target}
        )
        assert r.status_code == 202, r.text
        (e,) = entries(env, m)
        assert e["action"] == "scan.create" and e["detail"].get("alert") is None
    assert alerts_total(KIND) == base + 1


# ------------------------------------------------------------ CHK-M9-243


def test_cancel_route_roles_ids_and_effects(env: ApiEnv, cat: f.Catalog) -> None:
    """REQ-221 (4), REQ-220 (2), (4), #122 (g): an operator gets 200 {scan_id,
    state, cancelled_jobs}; a repeat answers cancelled_jobs 0; a viewer 403;
    an unknown id 404; a malformed id 400; a bsa_ token 401. The cancelled
    queued job is never pulled; posts for the cancelled dispatched and
    running jobs are 409 and store nothing."""
    pol = cat.policy(1)
    q, d, run = env.agent(), env.agent(), env.agent()
    _, op = env.caller("operator")
    _, viewer = env.caller("viewer")
    r = env.call(
        "POST",
        SCANS,
        op,
        body={
            "policy_id": pol.policy_id,
            "target": {"agents": [str(x.agent_id) for x in (q, d, run)]},
        },
    )
    sid = r.json()["scan_id"]
    (jd,) = d.pulled()
    (jr,) = run.pulled()
    env.clock.advance(seconds=5)
    assert run.start(jr["job_id"]).status_code == 200
    path = f"{SCANS}/{sid}/cancel"
    problem(env.call("POST", path, viewer), 403, "forbidden")
    assert env.call("POST", path, q.row.token).status_code == 401
    r = env.call("POST", path, op)
    assert r.status_code == 200, r.text
    assert r.json() == {"scan_id": sid, "state": "cancelled", "cancelled_jobs": 3}
    assert env.call("POST", path, op).json()["cancelled_jobs"] == 0
    problem(env.call("POST", f"{SCANS}/{uuid4()}/cancel", op), 404, "not_found")
    for bad in ("x", "123", str(uuid4())[:-1], str(uuid4()) + "0"):
        problem(env.call("POST", f"{SCANS}/{bad}/cancel", op), 400, "invalid_request")
    env.clock.advance(seconds=5)
    assert q.pulled() == []
    for a, job in ((d, jd), (run, jr)):
        env.clock.advance(seconds=5)
        problem(
            a.post(job["job_id"], batch(item(pol.uuids[0]))), 409, "job_not_acceptable"
        )
    with env.conn() as c:
        assert f.results_of(c, [UUID(jd["job_id"]), UUID(jr["job_id"])]) == []


# ------------------------------------------------------------ CHK-M9-244


def test_the_scan_routes_import_no_repository() -> None:
    """REQ-221 (5), api → services → repositories: api/user/scans.py imports
    no repository and no psycopg."""
    src = Path(__file__).resolve().parents[1] / "bitscan_manager/api/user/scans.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert not {n for n in names if "repositories" in n or n.startswith("psycopg")}


# ------------------------------------------------------------ CHK-M9-245


def test_idempotency_key_repeats_conflicts_and_bad_keys(
    env: ApiEnv, cat: f.Catalog
) -> None:
    """REQ-222 (3), (4), #123: a repeat with the same key and body answers
    the first 202 and writes no second scan row or scan.create entry; the
    same key with another body is 409 conflict with the fixed detail;
    another user's same key makes its own scan; a key of 256 characters or
    with a control character is 400; a NaN in the target with a key is 400
    (r1), not 500."""
    pol = cat.policy(1)
    a, b = env.agent(), env.agent()
    _, tok = env.caller("operator")
    _, other = env.caller("operator")
    body = {"policy_id": pol.policy_id, "target": {"agents": [str(a.agent_id)]}}
    key = {"Idempotency-Key": "scan-" + "k" * 200}
    m = mark_of(env)
    before = counts(env)
    first = env.call("POST", SCANS, tok, body=body, headers=key)
    assert first.status_code == 202
    again = env.call("POST", SCANS, tok, body=body, headers=key)
    assert (again.status_code, again.json()) == (202, first.json())
    assert counts(env)[0] == before[0] + 1
    assert [e["action"] for e in entries(env, m)] == ["scan.create"]
    p = problem(
        env.call(
            "POST",
            SCANS,
            tok,
            headers=key,
            body={"policy_id": pol.policy_id, "target": {"agents": [str(b.agent_id)]}},
        ),
        409,
        "conflict",
    )
    assert p["detail"] == "Idempotency-Key was used with a different request."
    theirs = env.call("POST", SCANS, other, body=body, headers=key)
    assert (
        theirs.status_code == 202
        and theirs.json()["scan_id"] != first.json()["scan_id"]
    )
    for bad in ("k" * 256, "bad\x01key", "tab\tkey", ""):
        problem(
            env.call("POST", SCANS, tok, body=body, headers={"Idempotency-Key": bad}),
            400,
            "invalid_request",
        )
    nan = b'{"policy_id": %d, "target": {"agents": [NaN]}}' % pol.policy_id
    problem(
        env.call("POST", SCANS, tok, content=nan, headers={"Idempotency-Key": "nan-1"}),
        400,
        "invalid_request",
    )
    ok_255 = env.call(
        "POST", SCANS, tok, body=body, headers={"Idempotency-Key": "k" * 255}
    )
    assert ok_255.status_code == 202


# ------------------------------------------------------------ CHK-M9-246


def test_unstorable_text_is_500_about_blank_and_writes_nothing(
    env: ApiEnv, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#125 (g): the builder refuses U+0000 (a snapshot replaced here; the
    catalog cannot hold it) → 500 about:blank with a fixed detail, no row."""
    pol = cat.policy(1)
    a = env.agent()
    _, tok = env.caller("operator")
    real = scan_queue.policy_snapshot

    def poisoned(conn: Any, pid: int) -> Any:
        snap = real(conn, pid)
        assert snap is not None
        return replace(
            snap, plugins=[replace(snap.plugins[0], execute="echo \x00SECRET")]
        )

    monkeypatch.setattr(scan_queue, "policy_snapshot", poisoned)
    before = counts(env)
    p = problem(
        env.call(
            "POST",
            SCANS,
            tok,
            body={"policy_id": pol.policy_id, "target": {"agents": [str(a.agent_id)]}},
        ),
        500,
        "about:blank",
    )
    assert "SECRET" not in json.dumps(p)
    assert counts(env) == before
