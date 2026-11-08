"""TASK-244 TEST: the scan read routes through the API on PostgreSQL
(TP-M11-12; CHK-M11-213 to -219, -227, -228, and -455 to -458).

Expected values, from the spec and the criteria first: TS §6.2 L1113, L1120,
L1122 (viewer reads, `bsu_` or `bsk_`), §6.3 L1135-L1136 (`{items,
next_cursor}`, limit 1-500, default 50), L1141 (UUID strings, RFC 3339 with
an offset), L1142 (security headers); REQ-264 (1)-(5), REQ-265 (3), (6),
REQ-266 (1)-(4); #89 (cursors hold ids only), #145 (a)-(d); decisions
2026-11-08 (query `agent_id` hyphenated only, either case). The lead's TASK-244
rows: upper- and lower-case `agent_id` share one cursor scope; one instant
written with two offsets shares a time-filter scope; a cursor is accepted only
in its exact form ("Invalid request: query.cursor" otherwise). Then bound to
the route module's names (the cursor scope strings, to build forged cursors).

Each test starts from emptied scan tables (TRUNCATE as owner).
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.api.pagination import encode_cursor

from . import m11_pg_fixtures as m
from .agent_sim import ApiEnv, api_env
from .conftest import PgServer, own_migrated_server
from .evaluator_pg_fixtures import add_reeval, reserve_reeval_ids

pytestmark = pytest.mark.pg

BASE_AT = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
BAD_CURSOR = "Invalid request: query.cursor"
SCAN_ITEM_KEYS = {
    "scan_id",
    "policy_id",
    "policy_name",
    "policy_version",
    "trigger",
    "schedule_id",
    "requested_by",
    "state",
    "target_kind",
    "resolved_count",
    "created_at",
    "finished_at",
}
HOST_KEYS = {
    "agent_id",
    "hostname",
    "jobs",
    "passed",
    "failed",
    "errors",
    "not_run",
    "score",
}
JOB_KEYS = {"job_id", "state", "retry_of", "dispatched_at", "started_at", "finished_at"}
FORBIDDEN_KEYS = {"resolved_agents", "stdout", "stderr", "execute", "expected"}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-scan-api")) as s:
        yield s


@pytest.fixture
def clean(server: PgServer) -> PgServer:
    with m.owner(server) as c:
        c.execute("TRUNCATE scan, scan_job, scan_result, scan_result_reeval CASCADE")
    return server


@pytest.fixture
def env(clean: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(clean, tmp_path) as e:
        yield e


@pytest.fixture
def who(env: ApiEnv) -> dict[str, m.Caller]:
    with env.conn() as c:
        return m.callers(c, at=env.clock.now())


def get(env: ApiEnv, caller: m.Caller, path: str, **params: Any) -> Any:
    return env.client.get(path, params=params or None, headers=caller.headers())


def ok(r: Any) -> Any:
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def problem(r: Any, status: int, type_: str, detail: str | None = None) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == status and body["type"] == type_, body
    if detail is not None:
        assert body["detail"] == detail, body


def ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["scan_id"] for i in items]


def walk(env: ApiEnv, caller: m.Caller, path: str, **params: Any) -> list[str]:
    """Every page of a scan list; each page's cursor used once."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(200):
        q = dict(params)
        if cursor is not None:
            q["cursor"] = cursor
        body = ok(get(env, caller, path, **q))
        assert set(body) == {"items", "next_cursor"}
        seen += ids(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("paging did not end")


def results(c: Any) -> m.ResultsWorld:
    """REQ-267 (1)'s world, requested and re-evaluated by a real admin."""
    admin = m.make_user(c, "admin", at=BASE_AT)
    return m.results_world(c, at=BASE_AT, admin_id=admin)


def newest_first(scans: dict[str, tuple[datetime, UUID]], keep: set[str]) -> list[str]:
    rows = sorted(
        (scans[k] for k in keep), key=lambda r: (r[0], str(r[1])), reverse=True
    )
    return [str(sid) for _, sid in rows]


class World:
    """REQ-264 (1)'s fleet: two policies, three hosts, scans in four states
    over two days with overlapping targets, and two scans at one instant (the
    scan_id tie-break)."""

    def __init__(self, server: PgServer) -> None:
        with m.owner(server) as c:
            self.p1, self.p2 = m.make_policy(c, 2), m.make_policy(c, 2)
            self.a, self.b, self.c = (m.host(c, at=BASE_AT) for _ in range(3))
            a, b, cc = self.a.agent_id, self.b.agent_id, self.c.agent_id
            day = timedelta(days=1)
            hour = timedelta(hours=1)
            plan = {
                "s1": (self.p1, [a, b], "completed", BASE_AT),
                "s2": (self.p1, [b, cc], "running", BASE_AT + hour),
                "s3": (self.p2, [a], "failed", BASE_AT + 2 * hour),
                "s4": (self.p2, [a, cc], "completed", BASE_AT + day),
                "s5": (self.p1, [cc], "running", BASE_AT + day + hour),
                "s6": (self.p2, [b], "completed", BASE_AT + day + 2 * hour),
                "t1": (self.p1, [a], "queued", BASE_AT + 3 * hour),
                "t2": (self.p1, [a], "queued", BASE_AT + 3 * hour),
            }
            self.scans: dict[str, tuple[datetime, UUID]] = {}
            self.meta: dict[str, tuple[m.Pol, list[UUID], str]] = {}
            for key, (pol, agents, state, at) in plan.items():
                sid = m.scan(c, pol, agents, state=state, created_at=at)
                self.scans[key] = (at, sid)
                self.meta[key] = (pol, agents, state)

    def sid(self, key: str) -> str:
        return str(self.scans[key][1])

    def expect(self, **f: Any) -> list[str]:
        keep = set()
        for key, (pol, agents, state) in self.meta.items():
            at = self.scans[key][0]
            if "policy_id" in f and pol.policy_id != f["policy_id"]:
                continue
            if "agent_id" in f and f["agent_id"] not in agents:
                continue
            if "state" in f and state != f["state"]:
                continue
            if "after" in f and at < f["after"]:
                continue
            if "before" in f and at >= f["before"]:
                continue
            keep.add(key)
        return newest_first(self.scans, keep)


# ------------------------------------------------------------ CHK-M11-213


def test_each_filter_alone_and_together_in_order(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-264 (1): newest first (created_at, then scan_id, descending); each
    filter alone and all together give exactly the expected scans;
    created_after inclusive and created_before exclusive at the same instant."""
    w = World(env.server)
    v = who["viewer:session"]
    day1 = BASE_AT + timedelta(days=1)
    assert ids(ok(get(env, v, "/api/v1/scans"))["items"]) == w.expect()
    cases: list[tuple[dict[str, str], dict[str, Any]]] = [
        ({"policy_id": str(w.p1.policy_id)}, {"policy_id": w.p1.policy_id}),
        ({"agent_id": str(w.a.agent_id)}, {"agent_id": w.a.agent_id}),
        ({"state": "completed"}, {"state": "completed"}),
        ({"state": "failed"}, {"state": "failed"}),
        ({"created_after": day1.isoformat()}, {"after": day1}),
        ({"created_before": day1.isoformat()}, {"before": day1}),
        (
            {
                "policy_id": str(w.p2.policy_id),
                "agent_id": str(w.a.agent_id),
                "state": "completed",
                "created_after": BASE_AT.isoformat(),
                "created_before": (day1 + timedelta(days=1)).isoformat(),
            },
            {
                "policy_id": w.p2.policy_id,
                "agent_id": w.a.agent_id,
                "state": "completed",
                "after": BASE_AT,
                "before": day1 + timedelta(days=1),
            },
        ),
    ]
    for query, expect in cases:
        got = ids(ok(get(env, v, "/api/v1/scans", **query))["items"])
        assert got == w.expect(**expect), query
    assert w.sid("s4") in ids(
        ok(get(env, v, "/api/v1/scans", created_after="2026-11-02T18:00:00+08:00"))[
            "items"
        ]
    )  # the same instant as day1, written with +08:00: inclusive
    assert w.sid("s4") not in ids(
        ok(get(env, v, "/api/v1/scans", created_before="2026-11-02T05:00:00-05:00"))[
            "items"
        ]
    )  # exclusive
    together = ids(
        ok(
            get(
                env,
                v,
                "/api/v1/scans",
                policy_id=str(w.p2.policy_id),
                agent_id=str(w.a.agent_id),
                state="completed",
            )
        )["items"]
    )
    assert together == [w.sid("s4")]


def test_the_scan_item_body(env: ApiEnv, who: dict[str, m.Caller]) -> None:
    """#145 (a): the item keys exactly; values from the stored scan (the
    state as stored, the target kind, the resolved count)."""
    w = World(env.server)
    items = ok(get(env, who["viewer:session"], "/api/v1/scans"))["items"]
    by_id = {i["scan_id"]: i for i in items}
    s1 = by_id[w.sid("s1")]
    assert set(s1) == SCAN_ITEM_KEYS
    assert s1["policy_id"] == w.p1.policy_id
    assert s1["policy_name"] == w.p1.name
    assert (s1["state"], s1["target_kind"], s1["resolved_count"]) == (
        "completed",
        "agents",
        2,
    )
    assert s1["trigger"] == "manual" and s1["finished_at"] is None
    assert datetime.fromisoformat(s1["created_at"]) == BASE_AT


def test_limit_2_paging_visits_every_scan_once(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-264 (1): limit=2 pages visit every scan exactly once, in order,
    and the last page has no cursor; also under a filter."""
    w = World(env.server)
    v = who["operator:api"]
    assert walk(env, v, "/api/v1/scans", limit="2") == w.expect()
    assert walk(
        env, v, "/api/v1/scans", limit="2", agent_id=str(w.a.agent_id)
    ) == w.expect(agent_id=w.a.agent_id)


def test_default_limit_is_50(env: ApiEnv, who: dict[str, m.Caller]) -> None:
    """TS §6.3 L1136: 51 scans → 50 items and a cursor, then 1 and none;
    limit=500 is accepted."""
    with m.owner(env.server) as c:
        pol = m.make_policy(c, 1)
        a = m.host(c, at=BASE_AT)
        for i in range(51):
            m.scan(c, pol, [a.agent_id], created_at=BASE_AT + timedelta(minutes=i))
    v = who["viewer:session"]
    first = ok(get(env, v, "/api/v1/scans"))
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = ok(get(env, v, "/api/v1/scans", cursor=first["next_cursor"]))
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert len(ok(get(env, v, "/api/v1/scans", limit="500"))["items"]) == 51


# ------------------------------------------------------------ CHK-M11-455


def test_upper_and_lower_case_agent_id_share_one_cursor_scope(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """The reviewer's TASK-232 note and the lead's row: a cursor made with the
    lower-case agent_id continues with the upper-case spelling (and back),
    giving the same next page."""
    w = World(env.server)
    v = who["viewer:session"]
    low, up = str(w.a.agent_id), str(w.a.agent_id).upper()
    first = ok(get(env, v, "/api/v1/scans", limit="1", agent_id=low))
    c = first["next_cursor"]
    assert c
    same = ok(get(env, v, "/api/v1/scans", limit="1", agent_id=low, cursor=c))
    other = ok(get(env, v, "/api/v1/scans", limit="1", agent_id=up, cursor=c))
    assert other == same
    c_up = ok(get(env, v, "/api/v1/scans", limit="1", agent_id=up))["next_cursor"]
    assert ok(get(env, v, "/api/v1/scans", limit="1", agent_id=low, cursor=c_up)) == (
        same
    )


def test_one_instant_with_two_offsets_shares_a_time_scope(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """The lead's row: created_after written as Z and as +08:00 (the same
    instant) share the cursor scope; 1 µs later is another scope (400)."""
    w = World(env.server)
    v = who["viewer:session"]
    z, plus8 = "2026-11-01T10:00:00Z", "2026-11-01T18:00:00+08:00"
    first = ok(get(env, v, "/api/v1/scans", limit="2", created_after=z))
    c = first["next_cursor"]
    assert c
    a = ok(get(env, v, "/api/v1/scans", limit="2", created_after=z, cursor=c))
    b = ok(get(env, v, "/api/v1/scans", limit="2", created_after=plus8, cursor=c))
    assert a == b and a["items"]
    for name in ("created_after", "created_before"):
        cc = ok(get(env, v, "/api/v1/scans", limit="1", **{name: plus8}))
        if cc["next_cursor"] is None:
            continue
        r = get(
            env,
            v,
            "/api/v1/scans",
            limit="1",
            cursor=cc["next_cursor"],
            **{name: "2026-11-01T10:00:00.000001Z"},
        )
        problem(r, 400, "invalid_request", BAD_CURSOR)
    assert w.expect()


# ------------------------------------------------------------ CHK-M11-215


def test_bad_cursors_are_400(env: ApiEnv, who: dict[str, m.Caller]) -> None:
    """REQ-264 (3): a tampered cursor, a cursor made under other filters, a
    cursor whose scan was deleted, and cursors from the host history and the
    results routes are 400 invalid_request "Invalid request: query.cursor"."""
    w = World(env.server)
    v = who["viewer:session"]
    page = ok(get(env, v, "/api/v1/scans", limit="2"))
    c = page["next_cursor"]
    assert c
    raw = bytearray(base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)))
    raw[-1] ^= 0x01
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    problem(get(env, v, "/api/v1/scans", cursor=tampered), 400, "invalid_request")
    problem(get(env, v, "/api/v1/scans", cursor=c + "x"), 400, "invalid_request")
    pc = ok(get(env, v, "/api/v1/scans", limit="1", policy_id=str(w.p1.policy_id)))
    for other in (
        {"policy_id": str(w.p2.policy_id)},
        {},
        {"state": "running"},
        {"agent_id": str(w.a.agent_id)},
    ):
        r = get(env, v, "/api/v1/scans", limit="1", cursor=pc["next_cursor"], **other)
        problem(r, 400, "invalid_request", BAD_CURSOR)
    hist = ok(get(env, v, f"/api/v1/agents/{w.a.agent_id}/scans", limit="1"))
    assert hist["next_cursor"]
    r = get(env, v, "/api/v1/scans", limit="1", cursor=hist["next_cursor"])
    problem(r, 400, "invalid_request", BAD_CURSOR)
    r = get(env, v, f"/api/v1/agents/{w.a.agent_id}/scans", limit="1", cursor=c)
    problem(r, 400, "invalid_request", BAD_CURSOR)
    # the anchor scan deleted: the cursor no longer names a scan
    anchor = page["items"][-1]["scan_id"]
    with m.owner(env.server) as conn:
        conn.execute("DELETE FROM scan WHERE scan_id = %s", (anchor,))
    problem(
        get(env, v, "/api/v1/scans", limit="2", cursor=c),
        400,
        "invalid_request",
        BAD_CURSOR,
    )


@pytest.mark.parametrize(
    "key",
    [
        ["UPPER"],
        ["HEX"],
        ["{BRACED}"],
        [123],
        [None],
        [],
        ["OK", "extra"],
        [["OK"]],
    ],
)
def test_a_scan_cursor_is_accepted_only_in_its_exact_form(
    env: ApiEnv, who: dict[str, m.Caller], key: list[Any]
) -> None:
    """The lead's row: a cursor signed for the right scope but holding
    anything other than [canonical lower-case scan_id] is 400 (white box: the
    scope string, to sign it)."""
    w = World(env.server)
    sid = w.sid("s2")
    sub = {
        "UPPER": sid.upper(),
        "HEX": sid.replace("-", ""),
        "{BRACED}": "{" + sid + "}",
        "OK": sid,
    }

    def fill(v: Any) -> Any:
        if isinstance(v, list):
            return [fill(x) for x in v]
        return sub.get(v, v) if isinstance(v, str) else v

    forged = encode_cursor("scans:::::", fill(key))
    r = get(env, who["viewer:session"], "/api/v1/scans", cursor=forged)
    problem(r, 400, "invalid_request", BAD_CURSOR)
    good = encode_cursor("scans:::::", [sid])
    assert ok(get(env, who["viewer:session"], "/api/v1/scans", cursor=good))["items"]


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ({"state": "expired"}, 400),
        ({"agent_id": "nope"}, 400),
        ({"created_after": "2026-11-01T10:00:00"}, 400),
        ({"created_before": "2026-11-01"}, 400),
        ({"limit": "0"}, 400),
        ({"limit": "501"}, 400),
        ({"limit": "500"}, 200),
        ({"limit": "1"}, 200),
    ],
)
def test_query_boundaries(
    env: ApiEnv, who: dict[str, m.Caller], query: dict[str, str], status: int
) -> None:
    """REQ-264 (3) at the route with data present: 400 invalid_request for an
    unknown state, a malformed agent_id, a date without an offset, limit 0
    and 501; 1 and 500 accepted."""
    World(env.server)
    r = get(env, who["viewer:session"], "/api/v1/scans", **query)
    if status == 200:
        ok(r)
    else:
        problem(r, 400, "invalid_request")


# ------------------------------------------------------------ CHK-M11-214


@pytest.mark.parametrize(
    "kind",
    [
        "viewer:session",
        "viewer:api",
        "operator:session",
        "operator:api",
        "admin:session",
        "admin:api",
    ],
)
def test_every_role_and_token_kind_reads_all_five(
    env: ApiEnv, who: dict[str, m.Caller], kind: str
) -> None:
    """REQ-264 (2), REQ-266 (4): viewer, operator and admin, with a session
    and with an API token, get 200 on the five reads of a real scan (the 401
    rows for no token, revoked, bsa_ and bse_ are in
    test_m11_contract_api_pg.py)."""
    w = World(env.server)
    caller = who[kind]
    sid, aid = w.sid("s1"), w.a.agent_id
    for path in (
        "/api/v1/scans",
        f"/api/v1/scans/{sid}",
        f"/api/v1/scans/{sid}/results",
        f"/api/v1/agents/{aid}/scans",
    ):
        ok(get(env, caller, path))
    r = get(env, caller, f"/api/v1/scans/{sid}/results.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")


# ------------------------------------------------------------ CHK-M11-216


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        out = set(value)
        for v in value.values():
            out |= _keys(v)
        return out
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


@pytest.mark.parametrize("kind", ["viewer:session", "operator:session", "admin:api"])
def test_no_scan_item_holds_output_execute_or_expected(
    env: ApiEnv, who: dict[str, m.Caller], kind: str
) -> None:
    """REQ-264 (4), REQ-265 (6), REQ-268 (3): with the four canaries stored
    (stdout, stderr, execute, expected), no list, detail or host-history
    response holds them or a resolved_agents, stdout, stderr, execute or
    expected key, for any role."""
    with m.owner(env.server) as c:
        rw = results(c)
    caller = who[kind]
    a = rw.hosts["a"].agent_id
    for path in (
        "/api/v1/scans",
        f"/api/v1/scans/{rw.scan_id}",
        f"/api/v1/agents/{a}/scans",
    ):
        r = get(env, caller, path)
        body = ok(r)
        assert not (_keys(body) & FORBIDDEN_KEYS), (path, _keys(body) & FORBIDDEN_KEYS)
        assert m.hits([r.text]) == [], path


# ------------------------------------------------------------ CHK-M11-218


def test_detail_body_keys_target_and_hosts(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-265 (6), #145 (b): the detail is the scan item plus `target` as
    requested (no resolved_agents) and `hosts` by hostname then agent_id;
    each host's jobs original first, then its retry; counts and score as the
    effective verdicts give them (host a: PASS, then FAIL re-evaluated to
    PASS, ERROR, a retry FAIL and one not run → 2/(2+1); queued host b →
    null)."""
    with m.owner(env.server) as c:
        rw = results(c)
    body = ok(get(env, who["viewer:api"], f"/api/v1/scans/{rw.scan_id}"))
    assert set(body) == SCAN_ITEM_KEYS | {"target", "hosts"}
    hosts = rw.hosts
    assert body["target"] == {
        "agents": [str(h.agent_id) for h in (hosts["a"], hosts["b"], hosts["c"])]
    }
    with m.owner(env.server) as c:
        # "by hostname, then agent_id" as the database orders text (the spec
        # names no collation; the <script> hostname sorts by its letters).
        rows = c.execute(
            "SELECT agent_id::text, hostname FROM agent WHERE agent_id = ANY(%s)"
            " ORDER BY hostname, agent_id",
            ([h.agent_id for h in hosts.values()],),
        ).fetchall()
    names = {str(r[0]): str(r[1]) for r in rows}
    order = [str(r[0]) for r in rows]
    assert [h["agent_id"] for h in body["hosts"]] == order
    assert [h["hostname"] for h in body["hosts"]] == [names[a] for a in order]
    by = {h["agent_id"]: h for h in body["hosts"]}
    for h in body["hosts"]:
        assert set(h) == HOST_KEYS
        for j in h["jobs"]:
            assert set(j) == JOB_KEYS
    ha = by[str(hosts["a"].agent_id)]
    assert [j["job_id"] for j in ha["jobs"]] == [
        str(rw.jobs["a"].job_id),
        str(rw.jobs["a_retry"].job_id),
    ]
    assert ha["jobs"][1]["retry_of"] == str(rw.jobs["a"].job_id)
    assert (ha["passed"], ha["failed"], ha["errors"], ha["not_run"]) == (2, 1, 1, 1)
    assert ha["score"] == pytest.approx(2 / 3)
    hb = by[str(hosts["b"].agent_id)]
    assert (hb["passed"], hb["failed"], hb["errors"], hb["score"]) == (0, 0, 0, None)
    assert hb["not_run"] == 5
    hc = by[str(hosts["c"].agent_id)]
    assert (hc["passed"], hc["failed"], hc["errors"], hc["not_run"]) == (3, 1, 1, 0)
    assert hc["score"] == pytest.approx(0.75)


def test_detail_of_a_deleted_policy_and_a_late_change(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-265 (4), (5) through the route: a scan of a deleted policy is
    still returned; a re-evaluation changes the next answer."""
    with m.owner(env.server) as c:
        rw = results(c)
    v = who["viewer:session"]
    before = ok(get(env, v, f"/api/v1/scans/{rw.scan_id}"))
    with m.owner(env.server) as c:
        base = reserve_reeval_ids(c, 3)
        add_reeval(
            c,
            rw.jobs["c"].job_id,
            rw.p[2].plugin_uuid,
            code=0,
            detail="late",
            policy_version=1,
            by=rw.admin_id,
            reeval_id=base + 1,
            at=BASE_AT + timedelta(hours=5),
        )
        m.soft_delete(c, rw.pol)
    after = ok(get(env, v, f"/api/v1/scans/{rw.scan_id}"))
    hc = str(rw.hosts["c"].agent_id)
    old = {h["agent_id"]: h for h in before["hosts"]}[hc]
    new = {h["agent_id"]: h for h in after["hosts"]}[hc]
    assert (old["passed"], old["failed"]) == (3, 1)
    assert (new["passed"], new["failed"], new["score"]) == (4, 0, 1.0)


@pytest.mark.parametrize(
    ("path", "status", "type_"),
    [
        ("/api/v1/scans/0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11", 404, "not_found"),
        ("/api/v1/scans/0b6e6a8c3f0e4c479d1a5d2f8c0e4b11", 400, "invalid_request"),
        (
            "/api/v1/scans/{0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11}",
            400,
            "invalid_request",
        ),
        ("/api/v1/scans/nope", 400, "invalid_request"),
    ],
)
def test_detail_unknown_404_and_malformed_400(
    env: ApiEnv, who: dict[str, m.Caller], path: str, status: int, type_: str
) -> None:
    """REQ-265 (3)."""
    problem(get(env, who["viewer:session"], path), status, type_)


def test_detail_upper_case_id_is_the_same_scan(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    w = World(env.server)
    v = who["viewer:session"]
    low = ok(get(env, v, f"/api/v1/scans/{w.sid('s1')}"))
    assert ok(get(env, v, f"/api/v1/scans/{w.sid('s1').upper()}")) == low


# ------------------------------------------------------------ CHK-M11-219


def test_host_history(env: ApiEnv, who: dict[str, m.Caller]) -> None:
    """REQ-266 (1)-(3): an agent in 3 of 5 scans gets exactly those 3, newest
    first; limit=1 visits each once; a decommissioned agent's history is
    returned; unknown and malformed ids are 404 not_found."""
    with m.owner(env.server) as c:
        pol = m.make_policy(c, 1)
        x, y = m.host(c, at=BASE_AT), m.host(c, at=BASE_AT)
        mine: list[tuple[datetime, UUID]] = []
        for i, agents in enumerate([[x, y], [y], [x], [y], [x]]):  # x in scans 0, 2, 4
            at = BASE_AT + timedelta(hours=i)
            sid = m.scan(c, pol, [h.agent_id for h in agents], created_at=at)
            if x in agents:
                mine.append((at, sid))
    want = [str(s) for _, s in sorted(mine, reverse=True)]
    v = who["viewer:session"]
    path = f"/api/v1/agents/{x.agent_id}/scans"
    body = ok(get(env, v, path))
    assert ids(body["items"]) == want and body["next_cursor"] is None
    assert walk(env, v, path, limit="1") == want
    with m.owner(env.server) as c:
        c.execute(
            "UPDATE agent SET status = 'decommissioned' WHERE agent_id = %s",
            (x.agent_id,),
        )
    assert ids(ok(get(env, v, path))["items"]) == want
    for bad in ("0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11", "nope", "1"):
        problem(get(env, v, f"/api/v1/agents/{bad}/scans"), 404, "not_found")


def test_host_history_id_forms_as_the_other_agent_routes(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-266 (2): "as the other /agents/{id} routes answer": each spelling
    of a real agent id gets the same status on /agents/{id}/scans as on
    /agents/{id}."""
    with m.owner(env.server) as c:
        a = m.host(c, at=BASE_AT)
    s = str(a.agent_id)
    v = who["viewer:session"]
    for form in (s, s.upper(), s.replace("-", ""), "{" + s + "}", "urn:uuid:" + s):
        one = get(env, v, f"/api/v1/agents/{form}").status_code
        hist = get(env, v, f"/api/v1/agents/{form}/scans").status_code
        assert hist == one, (form, one, hist)


# ------------------------------------------------------------ CHK-M11-217


def test_the_reads_run_select_only(
    env: ApiEnv, who: dict[str, m.Caller], monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-264 (5), REQ-271 (2), REQ-272: over the five reads, every statement
    is a read, except M2's token last_used_at bookkeeping; nothing writes a
    scan table."""
    with m.owner(env.server) as c:
        rw = results(c)
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    v = who["operator:session"]
    a = rw.hosts["a"].agent_id
    for path in (
        "/api/v1/scans",
        f"/api/v1/scans/{rw.scan_id}",
        f"/api/v1/scans/{rw.scan_id}/results",
        f"/api/v1/scans/{rw.scan_id}/results.csv",
        f"/api/v1/agents/{a}/scans",
    ):
        assert get(env, v, path).status_code == 200, path
    monkeypatch.undo()
    reads = [s for s in spy.statements if "user_token" not in s]
    assert len(reads) >= 5
    for s in spy.statements:
        text = " ".join(s.split()).upper()
        if text.startswith("UPDATE USER_TOKEN SET LAST_USED_AT"):
            continue
        assert m.verb(s) in {"SELECT", "WITH", "SET", "SHOW"}, s
        for w_ in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE "):
            assert w_ not in text, s
    assert set(spy.roles) == {"bitscan_app"}


# ------------------------------------------------------------ CHK-M11-227, -228


def test_csv_path_is_separate_and_headers_are_set(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """CHK-M11-227: /scans/{id}.csv is never a CSV (the id pattern refuses
    it), /results.csv is not /results. CHK-M11-228: every M11 response,
    success or problem, carries the TS §6.3 security headers."""
    w = World(env.server)
    v = who["viewer:session"]
    sid = w.sid("s1")
    r = get(env, v, f"/api/v1/scans/{sid}.csv")
    assert r.status_code in (400, 404) and not r.headers["content-type"].startswith(
        "text/csv"
    )
    js = get(env, v, f"/api/v1/scans/{sid}/results")
    assert js.headers["content-type"].startswith("application/json")
    responses = [
        get(env, v, "/api/v1/scans"),
        get(env, v, f"/api/v1/scans/{sid}"),
        js,
        get(env, v, f"/api/v1/scans/{sid}/results.csv"),
        get(env, v, f"/api/v1/agents/{w.a.agent_id}/scans"),
        get(env, v, "/api/v1/scans/nope"),
        get(env, who["none"], "/api/v1/scans"),
        r,
    ]
    for resp in responses:
        h = resp.headers
        assert "max-age=" in h["strict-transport-security"], resp.url
        assert h["content-security-policy"], resp.url
        assert h["x-content-type-options"] == "nosniff", resp.url
        assert h["referrer-policy"] == "no-referrer", resp.url
    body = get(env, v, "/api/v1/scans/nope").json()
    assert {"type", "title", "status", "detail"} <= set(body)


def test_no_scan_table_is_written_and_tables_unchanged(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """REQ-271 (2) as data: checksums of the four scan tables are the same
    after every read route ran for every role."""
    with m.owner(env.server) as c:
        rw = results(c)
        tables = ("scan", "scan_job", "scan_result", "scan_result_reeval")
        before = m.checksums(c, tables)
    for kind in ("viewer:session", "operator:api", "admin:session"):
        for path in (
            "/api/v1/scans",
            f"/api/v1/scans/{rw.scan_id}",
            f"/api/v1/scans/{rw.scan_id}/results",
            f"/api/v1/scans/{rw.scan_id}/results.csv",
        ):
            assert get(env, who[kind], path).status_code == 200
    with m.owner(env.server) as c:
        assert m.checksums(c, tables) == before
