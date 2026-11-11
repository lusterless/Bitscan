"""TASK-232 TEST: the M11 contract through the running app (CHK-M11-233,
the APP half of CHK-M11-234).

PD-48: until TASK-243 and TASK-244 fill the handlers, each M11 operation
answers 501 ``about:blank`` **after** its auth dependency ran. This file
checks that order. The 501 rows are W1-only; TASK-243 TEST and TASK-244 TEST
replace them with the filled answers. The refusal rows stay.

TASK-243 TEST (tester-m11c, 2026-11-08) replaced the re-evaluate 501 rows: on
this file's unknown SID an admin TOTP session now reaches the filled handler
and gets 404 not_found. The filled answers are in test_reevaluate_api_pg.py
(CHK-M11-200 to -209).

TASK-244 TEST (tester-m11d, 2026-11-08) replaced the five read 501 rows: on
this file's unknown SID and AID the filled handlers answer after their auth
dependency, GET /scans 200 and the four id routes 404 not_found. The filled
answers are in test_scan_views_api_pg.py and test_results_api_pg.py
(CHK-M11-213 to -228).

Expected values: TS §6 (route groups: bsa_ / bse_ never on user routes),
§6.2 L1083-L1093 (roles, TOTP session, restricted admin), L1125, §5.3 L1053
(sink gate after 15 minutes), §6.3 L1133 (problem details); M2 problem types
(``unauthorized``, ``forbidden``, ``totp_session_required``,
``totp_enrolment_required``, ``audit_sink_unavailable``).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .agent_sim import ApiEnv, api_env
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

SID = "0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11"
AID = "7d0b3c55-1f6e-4f7b-8a5e-0c9e1d2a3b44"
READS = [
    "/api/v1/scans",
    f"/api/v1/scans/{SID}",
    f"/api/v1/scans/{SID}/results",
    f"/api/v1/scans/{SID}/results.csv",
    f"/api/v1/agents/{AID}/scans",
]
REEVAL = f"/api/v1/scans/{SID}/reevaluate"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-contract")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def who(env: ApiEnv) -> dict[str, m.Caller]:
    with env.conn() as c:
        return m.callers(c, at=env.clock.now())


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    """The problem answer; ``type_`` may list alternatives as ``a|b`` where
    the spec fixes only the status (a viewer's API token on a TOTP-session
    route is refused either as an API token or for its role)."""
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["status"] == status and body["type"] in type_.split("|"), body
    return body


def reeval_rows(env: ApiEnv) -> int:
    with env.conn() as c:
        return int(f9.one(c, "SELECT count(*) FROM scan_result_reeval"))


def reeval_entries(env: ApiEnv) -> int:
    with env.conn() as c:
        return int(
            f9.one(c, "SELECT count(*) FROM audit_log WHERE action = 'scan.reevaluate'")
        )


def call(env: ApiEnv, method: str, path: str, caller: m.Caller) -> Any:
    return env.client.request(method, path, headers=caller.headers())


# ------------------------------------------------------------ CHK-M11-233


def filled(r: Any, path: str) -> None:
    """TASK-244: GET /scans is 200 (an empty page here); the four id routes
    are 404 not_found for this file's unknown SID and AID."""
    if path == READS[0]:
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json() == {"items": [], "next_cursor": None}
    else:
        problem(r, 404, "not_found")


@pytest.mark.parametrize("path", READS)
@pytest.mark.parametrize("kind", ["viewer:session", "viewer:api", "admin:api"])
def test_reads_answer_after_auth_for_any_role(
    env: ApiEnv, who: dict[str, m.Caller], path: str, kind: str
) -> None:
    """A viewer (session or API token) and an admin API token pass the viewer
    dependency and reach the filled handler (was 501 in W1)."""
    filled(call(env, "GET", path, who[kind]), path)


@pytest.mark.parametrize("path", READS)
@pytest.mark.parametrize("kind", ["none", "agent", "enrol", "operator:revoked"])
def test_reads_refuse_missing_wrong_group_and_revoked_tokens(
    env: ApiEnv, who: dict[str, m.Caller], path: str, kind: str
) -> None:
    """TS §6: bsa_ and bse_ are never user tokens; no token and a revoked
    token are 401 before the handler."""
    problem(call(env, "GET", path, who[kind]), 401, "unauthorized")


@pytest.mark.parametrize(
    ("kind", "status", "type_"),
    [
        ("viewer:session", 403, "forbidden"),
        ("operator:session", 403, "forbidden"),
        ("viewer:api", 403, "totp_session_required|forbidden"),
        ("operator:api", 403, "totp_session_required|forbidden"),
        ("admin:api", 403, "totp_session_required"),
        ("admin:restricted", 403, "totp_enrolment_required"),
        ("none", 401, "unauthorized"),
        ("agent", 401, "unauthorized"),
        ("enrol", 401, "unauthorized"),
        ("operator:revoked", 401, "unauthorized"),
    ],
)
def test_reevaluate_refusals_come_before_the_handler(
    env: ApiEnv, who: dict[str, m.Caller], kind: str, status: int, type_: str
) -> None:
    """TS §6.2 L1086, L1125: admin, TOTP-verified session; API tokens refused
    whatever the role; nothing is written."""
    before = (reeval_rows(env), reeval_entries(env))
    problem(call(env, "POST", REEVAL, who[kind]), status, type_)
    assert (reeval_rows(env), reeval_entries(env)) == before


def test_reevaluate_admin_session_reaches_the_handler(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """TASK-243 filled the handler: an admin TOTP session passes the auth
    dependency and the unknown SID is 404 not_found (was 501 in W1)."""
    before = (reeval_rows(env), reeval_entries(env))
    problem(call(env, "POST", REEVAL, who["admin:session"]), 404, "not_found")
    assert (reeval_rows(env), reeval_entries(env)) == before


def test_reevaluate_sink_gate_at_15_minutes(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """TS §5.3 L1053: a sensitive action is refused after 15 minutes of sink
    outage (14 min 59 s still passes the gate), and again accepted after the
    queue drains. The reads have no sink gate."""
    admin = who["admin:session"]
    m.sink_down(env, 14 * 60 + 59)
    problem(call(env, "POST", REEVAL, admin), 404, "not_found")
    env.clock.advance(seconds=1)
    problem(call(env, "POST", REEVAL, admin), 503, "audit_sink_unavailable")
    filled(call(env, "GET", READS[0], who["viewer:session"]), READS[0])
    m.sink_up(env)
    problem(call(env, "POST", REEVAL, admin), 404, "not_found")


# ------------------------------------------------------------ CHK-M11-234 (APP)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/scans/not-a-uuid",
        "/api/v1/scans/0b6e6a8c3f0e4c479d1a5d2f8c0e4b11",
        f"/api/v1/scans/{SID}x",
        "/api/v1/scans/not-a-uuid/results",
        "/api/v1/scans/not-a-uuid/results.csv",
    ],
)
def test_malformed_scan_ids_are_400(
    env: ApiEnv, who: dict[str, m.Caller], path: str
) -> None:
    """Plan §3: the hyphenated UUID pattern; anything else is 400
    invalid_request before the handler."""
    problem(call(env, "GET", path, who["viewer:session"]), 400, "invalid_request")


def test_malformed_reevaluate_id_is_400_for_an_admin(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    r = call(env, "POST", "/api/v1/scans/not-a-uuid/reevaluate", who["admin:session"])
    problem(r, 400, "invalid_request")


def test_upper_case_scan_id_passes_the_pattern(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    problem(
        call(env, "GET", f"/api/v1/scans/{SID.upper()}", who["viewer:session"]),
        404,
        "not_found",
    )


@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/api/v1/scans", {"limit": "0"}),
        ("/api/v1/scans", {"limit": "501"}),
        ("/api/v1/scans", {"state": "expired"}),
        ("/api/v1/scans", {"state": "dispatched"}),
        ("/api/v1/scans", {"policy_id": "0"}),
        ("/api/v1/scans", {"agent_id": "not-a-uuid"}),
        ("/api/v1/scans", {"created_after": "2026-11-08T12:00:00"}),
        (f"/api/v1/scans/{SID}/results", {"status": "pass"}),
        (f"/api/v1/scans/{SID}/results", {"status": "NOTRUN"}),
        (f"/api/v1/scans/{SID}/results", {"limit": "501"}),
        (f"/api/v1/scans/{SID}/results.csv", {"status": "OK"}),
        (f"/api/v1/agents/{AID}/scans", {"limit": "0"}),
    ],
)
def test_invalid_query_values_are_400(
    env: ApiEnv, who: dict[str, m.Caller], path: str, query: dict[str, str]
) -> None:
    """REQ-264 (3), REQ-267 (5) at contract level: values outside the
    declared parameters are 400 invalid_request (#47), not 422."""
    r = env.client.get(path, params=query, headers=who["viewer:session"].headers())
    problem(r, 400, "invalid_request")


def test_limit_500_and_an_offset_date_pass_validation(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    q = {
        "limit": "500",
        "created_after": "2026-11-08T12:00:00+08:00",
        "state": "partial",
    }
    r = env.client.get(
        "/api/v1/scans", params=q, headers=who["viewer:session"].headers()
    )
    filled(r, READS[0])


# ------------------------------------------------------------ TASK-232 r1

QUERY_PATHS = [
    "/api/v1/scans",
    f"/api/v1/scans/{SID}/results",
    f"/api/v1/scans/{SID}/results.csv",
]
HEX = AID.replace("-", "")


@pytest.mark.parametrize("path", QUERY_PATHS)
@pytest.mark.parametrize(
    "value",
    [
        HEX,
        HEX.upper(),
        "{" + AID + "}",
        "urn:uuid:" + AID,
        AID + "\n",
        " " + AID,
        AID[:-1],
    ],
)
def test_query_agent_id_is_hyphenated_only(
    env: ApiEnv, who: dict[str, m.Caller], path: str, value: str
) -> None:
    """Decisions 2026-11-08 (TASK-232 r1): the 32-hex, braced and urn:uuid:
    forms (and padded or short values) are 400 invalid_request."""
    r = env.client.get(
        path, params={"agent_id": value}, headers=who["viewer:session"].headers()
    )
    problem(r, 400, "invalid_request")


@pytest.mark.parametrize("path", QUERY_PATHS)
@pytest.mark.parametrize("value", [AID, AID.upper()])
def test_query_agent_id_hyphenated_any_case_is_accepted(
    env: ApiEnv, who: dict[str, m.Caller], path: str, value: str
) -> None:
    r = env.client.get(
        path, params={"agent_id": value}, headers=who["viewer:session"].headers()
    )
    filled(r, path)
