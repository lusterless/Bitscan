"""TASK-083 (TP-M3-37): token before body on the heartbeat; hyphenated UUIDs
only for agent path and query ids; case-insensitive content coding.

Expected values: TS §6.3 L1136 (failed token checks on any route are limited to
20 per minute per IP; valid tokens never throttled), #59 (a bad token is one
401 and counts), W1 ruling (3) as extended 2026-10-23 (agent path and query
ids accept only the 8-4-4-4-12 form, either case; other forms 400), RFC 9110
§8.4.1 (content codings are case-insensitive; ruling 2026-10-23), the lead's
confirmation that a malformed {id} is 400, not counted, before the 30/min
limit. Uses the heartbeat test environment (fake clock, real PostgreSQL).
"""

import gzip
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token

from . import test_heartbeat_api_pg as hb
from .test_heartbeat_api_pg import T0, Env, ok, problem

pytestmark = pytest.mark.pg

env = hb.env
restore_settings = hb.restore_settings

BAD_BODIES: list[tuple[bytes, str]] = [
    (b"not json", "text/plain"),
    (b'{"agent_version": ', "application/json"),
    (b"\xff\xfe\x00", "application/json"),
    (b"[1, 2]", "application/json"),
    (b"", "application/json"),
]
BAD_IDS = ["truncated", "text", "bad-utf8", "array", "empty"]


def failed_count(env: Env, ip: str) -> int:
    return sum(d.count for d in env.limits.drain(final=True) if d.ip == ip)


# ------------------------------------------------------------ token before body


@pytest.mark.parametrize(("content", "ctype"), BAD_BODIES, ids=BAD_IDS)
def test_bad_token_with_a_bad_body_is_401_and_counted(
    env: Env, content: bytes, ctype: str
) -> None:
    """A bad or missing token gets 401 unauthorized whatever the body, and
    each counts: 20 from one IP in a minute, then the 21st is 429; a valid
    token from that IP still passes (TS §6.3 L1136)."""
    a = env.agent()
    ip = env.fresh_ip()
    env.clock.at = T0.replace(microsecond=0) + timedelta(seconds=5)
    for i in range(20):
        tok = "" if i % 2 else new_agent_token(AgentTokenKind.AGENT)
        r = env.hb(
            a, token=tok, content=content, headers={"Content-Type": ctype}, ip=ip
        )
        problem(r, 401, "unauthorized")
    r = env.hb(
        a,
        token=new_agent_token(AgentTokenKind.AGENT),
        content=content,
        headers={"Content-Type": ctype},
        ip=ip,
    )
    problem(r, 429, "rate_limited")
    ok(env.hb(a, ip=ip))  # the valid token is never throttled
    assert failed_count(env, ip) == 21  # every one counted, 429 included


def test_bad_token_and_malformed_body_never_reaches_the_parser(env: Env) -> None:
    """The 401 body is the token refusal (one byte-identical answer), not a
    body 400, for every malformed body."""
    a = env.agent()
    bodies = set()
    for content, ctype in BAD_BODIES:
        env.clock.at += timedelta(seconds=1)
        r = env.hb(a, token="", content=content, headers={"Content-Type": ctype})
        problem(r, 401, "unauthorized")
        bodies.add(r.content)
    assert len(bodies) == 1


@pytest.mark.parametrize(("content", "ctype"), BAD_BODIES, ids=BAD_IDS)
def test_valid_token_with_a_bad_body_is_400_and_not_counted(
    env: Env, content: bytes, ctype: str
) -> None:
    a = env.agent()
    ip = env.fresh_ip()
    before = env.beat_cols(a.agent_id)
    for _ in range(3):
        r = env.hb(a, content=content, headers={"Content-Type": ctype}, ip=ip)
        problem(r, 400, "invalid_request")
    assert env.beat_cols(a.agent_id) == before
    assert failed_count(env, ip) == 0


def test_token_outcomes_with_a_bad_body_keep_their_types(env: Env) -> None:
    """Revoked, pending and mismatch tokens with a non-JSON body answer their
    #59 type (decided before the body), and a mismatch still revokes."""
    revoked = env.agent(token_revoked_at=T0 - timedelta(minutes=1))
    pending = env.agent(status="awaiting_approval")
    mismatch = env.agent()
    h = {"Content-Type": "text/plain"}
    problem(env.hb(revoked, content=b"x", headers=h), 401, "token_revoked")
    problem(env.hb(pending, content=b"x", headers=h), 403, "pending_approval")
    problem(
        env.hb(mismatch, content=b"x", headers=h, machine="f" * 32),
        401,
        "machine_id_mismatch",
    )
    assert env.row(mismatch.agent_id)["token_revoked_at"] == env.clock.now()


def test_one_valid_heartbeat_counts_once_toward_the_agent_limit(env: Env) -> None:
    """The check runs once per request (token_first's result reused by the
    route): 30 heartbeats pass and the 31st is 429, not the 16th."""
    a = env.agent()
    env.clock.at = T0.replace(microsecond=0) + timedelta(seconds=5)
    ip = env.fresh_ip()
    for _ in range(30):
        ok(env.hb(a, ip=ip))
    problem(env.hb(a, ip=ip), 429, "rate_limited")
    assert len(env.ips(a.agent_id)) == 1


# ------------------------------------------------------------ UUID form


def other_forms(u: str) -> list[str]:
    return [u.replace("-", ""), "{" + u + "}", "urn:uuid:" + u, u[:-1], u + "0"]


def test_malformed_path_id_is_400_not_counted(env: Env) -> None:
    """{id} in another uuid.UUID form: 400 invalid_request after a valid
    token, not counted toward the failed-check limit, no heartbeat recorded;
    the upper-case form of the own id is accepted."""
    a = env.agent()
    ip = env.fresh_ip()
    before = env.beat_cols(a.agent_id)
    for form in other_forms(str(a.agent_id)):
        r = env.hb(a, path_id=form, ip=ip)
        assert r.status_code in (400, 404), (form, r.text)  # a newline may not route
        if r.status_code == 400:
            problem(r, 400, "invalid_request")
    assert env.beat_cols(a.agent_id) == before
    assert failed_count(env, ip) == 0
    ok(env.hb(a, path_id=str(a.agent_id).upper(), ip=ip))


def test_malformed_results_job_id_is_400(env: Env) -> None:
    a = env.agent()
    u = str(uuid4())
    body = json.dumps({"results": [], "final": False}).encode()
    for form in [*other_forms(u)[:3], u.upper()]:
        r = env.client().post(
            f"/api/v1/agent/{a.agent_id}/jobs/{form}/results",
            content=body,
            headers={
                "Authorization": f"Bearer {a.token}",
                "X-Bitscan-Machine-Id": a.machine_id,
                "Content-Type": "application/json",
            },
        )
        if form == u.upper():
            problem(r, 409, "job_not_acceptable")  # well formed: refused in M3
        else:
            problem(r, 400, "invalid_request")


def test_malformed_inventory_job_id_is_400(env: Env) -> None:
    a = env.agent()
    u = str(uuid4())
    for form in other_forms(u)[:3]:
        r = env.client().put(
            f"/api/v1/agent/{a.agent_id}/inventory",
            params={"job_id": form},
            content=gzip.compress(b"{}"),
            headers={
                "Authorization": f"Bearer {a.token}",
                "X-Bitscan-Machine-Id": a.machine_id,
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
            },
        )
        problem(r, 400, "invalid_request")


# ------------------------------------------------------------ content coding


@pytest.mark.parametrize("coding", ["GZIP", "Gzip", "gzip"])
def test_content_coding_is_case_insensitive(env: Env, coding: str) -> None:
    """Results: a GZIP-labelled well-formed batch is inflated and refused 409
    (not 400); inventory: a GZIP upload reaches the decoder (422 for an
    empty object), not the 400 for a missing gzip coding."""
    a = env.agent()
    h: dict[str, Any] = {
        "Authorization": f"Bearer {a.token}",
        "X-Bitscan-Machine-Id": a.machine_id,
        "Content-Type": "application/json",
        "Content-Encoding": coding,
    }
    r = env.client().post(
        f"/api/v1/agent/{a.agent_id}/jobs/{uuid4()}/results",
        content=gzip.compress(b'{"results": [], "final": false}'),
        headers=h,
    )
    problem(r, 409, "job_not_acceptable")
    r = env.client().put(
        f"/api/v1/agent/{a.agent_id}/inventory", content=gzip.compress(b"{}"), headers=h
    )
    problem(r, 422, "about:blank")
    r = env.client().post(
        f"/api/v1/agent/{a.agent_id}/jobs/{uuid4()}/results",
        content=b'{"results": [], "final": false}',
        headers=h | {"Content-Encoding": "IDENTITY"},
    )
    problem(r, 409, "job_not_acceptable")
