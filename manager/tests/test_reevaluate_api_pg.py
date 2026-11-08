"""TP-M11-11: the re-evaluate route through the running app on PostgreSQL
(TASK-243 TEST, tester-m11c; REQ-270, REQ-271; CHK-M11-200 to -209, -413).

Expected values come from the spec and the approved answers, not the code:
TS §6.2 L1086 (re-evaluate is a sensitive action: TOTP-verified session, API
tokens refused), L1125 (``POST /scans/{id}/reevaluate``, admin), §5.3 L1053
(sensitive actions refused after 15 minutes of audit-sink outage until the
queue drains), §4.5 L603 (re-evaluation adds rows, originals never change,
audit-logged), §6 (bsa_ / bse_ never on user routes), §6.3 (problem details,
1 MiB JSON body cap); #118 (b), (c), (g) (dropped plugins get no row, a
deleted policy is refused, one ``scan.reevaluate`` entry), #147 (no body,
in the request, the six answer keys), #148 (no alert, decisions 2026-11-08
(3)).

The scan under test (one host, policy version 1, then an import to version
2): p0 the canary plugin (``equals`` EXP) stored PASS with stdout OUT and
stderr ERR, so version 2 gives FAIL; p1 (``equals nope``) stored FAIL with
stdout ``ok``, version 2 expects ``ok`` so it gives PASS; p2 dropped by
version 2 (no row, ``not_in_version`` 1); p3 an intake ERROR
``runner_unavailable`` that stays ERROR (#12). A second scan of the same
policy and host must never get a row.

Races use a held lock and a lock-wait probe on ``pg_locks`` (20 ms polls,
10 s bound), never a sleep for ordering (decisions 2026-10-26).
"""

from __future__ import annotations

import ast
import json
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.services.audit.metrics import REGISTRY

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .agent_sim import ApiEnv, api_env
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

UNKNOWN = "0b6e6a8c-3f0e-4c47-9d1a-5d2f8c0e4b11"
LEAK_WORDS = ("Traceback", "ScanNotFound", "PolicyDeleted", "psycopg", "SELECT")


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-reeval-api")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def who(env: ApiEnv) -> dict[str, m.Caller]:
    """m11 callers, plus an admin whose account has TOTP but whose session
    is not TOTP-verified, and an admin's expired session."""
    at = env.clock.now()
    with env.conn() as c:
        out = m.callers(c, at=at)
        uid = m.make_user(c, "admin", at=at)
        out["admin:unverified"] = m.Caller(
            uid, "admin", "unverified", m.make_token(c, uid, verified=False, at=at)
        )
        eid = m.make_user(c, "admin", at=at)
        out["admin:expired"] = m.Caller(
            eid,
            "admin",
            "expired",
            m.make_token(c, eid, at=at, expires_at=at - timedelta(seconds=1)),
        )
    return out


@dataclass
class World:
    pol: m.Pol
    scan_id: UUID
    other_scan: UUID
    job: m.JobRow
    p: list[m.PluginDef]

    @property
    def path(self) -> str:
        return f"/api/v1/scans/{self.scan_id}/reevaluate"


def build(env: ApiEnv, *, status: str = "enabled", delete: bool = False) -> World:
    at = env.clock.now()
    p = [m.canary_plugin(), f9.plugin(expected="nope"), f9.plugin(), f9.plugin()]
    with f9.owner(env.server) as c:
        pol = m.make_policy(c, p, status=status)
        a = m.host(c, at=at)
        sid = m.scan(c, pol, [a.agent_id], state="completed", created_at=at)
        jr = m.job(c, sid, a.agent_id, pol, state="completed", created_at=at)
        m.result(c, jr, pol, p[0], code=0, stdout=m.OUT, stderr=m.ERR)
        m.result(c, jr, pol, p[1], code=1, stdout="ok", stderr="")
        m.result(c, jr, pol, p[2], code=0, stdout="ok", stderr="")
        m.runner_unavailable(c, jr, pol, p[3])
        other = m.scan(c, pol, [a.agent_id], state="completed", created_at=at)
        jo = m.job(c, other, a.agent_id, pol, state="completed", created_at=at)
        for pd in p:
            m.result(c, jo, pol, pd, code=1, stdout="other", stderr="")
        m.new_version(
            c, pol, expected={p[1].plugin_uuid: "ok"}, drop=[p[2].plugin_uuid]
        )
        if delete:
            m.soft_delete(c, pol)
    return World(pol, sid, other, jr, p)


@pytest.fixture
def world(env: ApiEnv) -> World:
    return build(env)


def expected_body(w: World) -> dict[str, Any]:
    return {
        "scan_id": str(w.scan_id),
        "policy_id": w.pol.policy_id,
        "scan_policy_version": 1,
        "policy_version": 2,
        "rows_added": 3,
        "not_in_version": 1,
    }


# ----- helpers -------------------------------------------------------------------


def post(env: ApiEnv, path: str, caller: m.Caller, **kw: Any) -> Any:
    return env.client.post(path, headers=caller.headers() | kw.pop("headers", {}), **kw)


def problem(r: Any, status: int, type_: str) -> dict[str, Any]:
    """The problem answer; ``type_`` may list alternatives as ``a|b`` where
    the spec fixes only the status."""
    assert r.status_code == status, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["status"] == status and body["type"] in type_.split("|"), body
    assert not [w for w in LEAK_WORDS if w in r.text], r.text
    return body


@dataclass(frozen=True)
class State:
    reeval: str
    reeval_rows: int
    audit: str
    audit_max: int
    results: str


def state(env: ApiEnv) -> State:
    with env.conn() as c:
        return State(
            m.checksum(c, "scan_result_reeval"),
            int(f9.one(c, "SELECT count(*) FROM scan_result_reeval")),
            m.checksum(c, "audit_log"),
            int(f9.one(c, "SELECT coalesce(max(audit_id), 0) FROM audit_log")),
            m.checksum(c, "scan_result"),
        )


def new_entries(env: ApiEnv, after: int) -> list[dict[str, Any]]:
    with env.conn() as c:
        rows = c.execute(
            "SELECT audit_id, actor, action, target, detail FROM audit_log"
            " WHERE audit_id > %s ORDER BY audit_id",
            (after,),
        ).fetchall()
    return [
        {
            "audit_id": r[0],
            "actor": r[1],
            "action": r[2],
            "target": r[3],
            "detail": r[4],
        }
        for r in rows
    ]


def reeval_rows(env: ApiEnv, job_id: UUID) -> list[tuple[Any, ...]]:
    with env.conn() as c:
        return [
            tuple(r)
            for r in c.execute(
                "SELECT reeval_id, plugin_uuid, eval_code, eval_detail, policy_version,"
                " reevaluated_by FROM scan_result_reeval WHERE job_id = %s"
                " ORDER BY reeval_id",
                (job_id,),
            ).fetchall()
        ]


def scan_reeval_count(env: ApiEnv, scan_id: UUID) -> int:
    with env.conn() as c:
        return int(
            f9.one(
                c,
                "SELECT count(*) FROM scan_result_reeval r JOIN scan_job j"
                " ON j.job_id = r.job_id WHERE j.scan_id = %s",
                (scan_id,),
            )
        )


class Wakes:
    """Stands in for the shipper's wake: counts calls, records how many
    ``scan.reevaluate`` entries another session can see at that moment (so a
    wake before the commit shows 0), and optionally runs one shipper cycle,
    as the shipper's loop does at once when woken."""

    def __init__(self, env: ApiEnv, target: str, *, deliver: bool) -> None:
        self.env = env
        self.target = target
        self.deliver = deliver
        self.seen: list[int] = []

    def __call__(self) -> None:
        with self.env.conn() as c:
            self.seen.append(
                int(
                    f9.one(
                        c,
                        "SELECT count(*) FROM audit_log"
                        " WHERE action = 'scan.reevaluate' AND target = %s",
                        (self.target,),
                    )
                )
            )
        if self.deliver:
            self.env.shipper.run_once()


def wakes(
    env: ApiEnv, mp: pytest.MonkeyPatch, scan_id: UUID, *, deliver: bool = False
) -> Wakes:
    """``scan.reevaluate`` entries are counted for ``scan_id`` only (the
    module's database is shared by its tests)."""
    w = Wakes(env, f"scan:{scan_id}", deliver=deliver)
    mp.setattr(env.shipper, "wake", w)
    return w


def alert_samples() -> dict[str, float]:
    out: dict[str, float] = {}
    for metric in REGISTRY.collect():
        for s in metric.samples:
            if s.name == "bitscan_alerts_total":
                out[s.labels["kind"]] = s.value
    return out


# ----- CHK-M11-200: success, audit entry, immediate delivery ---------------------


def test_admin_totp_session_reevaluates(
    env: ApiEnv, who: dict[str, m.Caller], world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-270 (1), REQ-271: 200 with exactly the six keys and the true
    counts; rows added only for the listed plugins of this scan with the
    current version's definitions; originals unchanged; one
    ``scan.reevaluate`` entry; no UPDATE or DELETE on the result tables."""
    admin = who["admin:session"]
    w = wakes(env, monkeypatch, world.scan_id)
    before = state(env)
    spy = m.RoleSpy()
    with pytest.MonkeyPatch.context() as mp:
        spy.install(mp)
        r = post(env, world.path, admin)
    assert r.status_code == 200, r.text
    assert r.json() == expected_body(world)
    rows = reeval_rows(env, world.job.job_id)
    got = {pu: (code, det, ver, by) for _, pu, code, det, ver, by in rows}
    assert got == {
        world.p[0].plugin_uuid: (1, None, 2, admin.user_id),
        world.p[1].plugin_uuid: (0, None, 2, admin.user_id),
        world.p[3].plugin_uuid: (2, "runner_unavailable", 2, admin.user_id),
    }
    assert len(rows) == 3  # p2 is not in version 2: no row (#118 (b))
    assert scan_reeval_count(env, world.other_scan) == 0
    after = state(env)
    assert after.results == before.results  # originals never change
    assert after.reeval_rows == before.reeval_rows + 3
    entries = new_entries(env, before.audit_max)
    assert entries == [
        {
            "audit_id": entries[0]["audit_id"],
            "actor": f"user:{admin.user_id}",
            "action": "scan.reevaluate",
            "target": f"scan:{world.scan_id}",
            "detail": {
                "policy_id": world.pol.policy_id,
                "scan_policy_version": 1,
                "policy_version": 2,
                "rows_added": 3,
                "not_in_version": 1,
            },
        }
    ]
    assert w.seen == [1]  # woken once, after the entry was committed
    writes = [
        s
        for s in spy.statements
        if m.verb(s) in ("UPDATE", "DELETE")
        and ("scan_result" in s or "scan_result_reeval" in s)
    ]
    assert writes == []
    assert any(
        "scan_result_reeval" in s and "INSERT" in s.upper() for s in spy.statements
    )


def test_entry_reaches_the_sink_on_the_wake(
    env: ApiEnv, who: dict[str, m.Caller], world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-270 (1): the shipper is woken after the commit, so its next cycle
    (run at once when woken) ships the entry; without the wake nothing would
    reach the sink until a later poll."""
    w = wakes(env, monkeypatch, world.scan_id, deliver=True)
    r = post(env, world.path, who["admin:session"])
    assert r.status_code == 200, r.text
    assert w.seen == [1]
    shipped = [
        x
        for x in env.sink.records
        if x.action == "scan.reevaluate" and x.target == f"scan:{world.scan_id}"
    ]
    assert len(shipped) == 1
    assert shipped[0].target == f"scan:{world.scan_id}"
    detail = json.loads(shipped[0].detail_text or "{}")
    assert detail["rows_added"] == 3 and "alert" not in detail


def test_each_call_adds_rows_and_the_latest_wins(
    env: ApiEnv, who: dict[str, m.Caller], world: World
) -> None:
    """TS §4.5 L603: re-evaluation adds rows; a second call adds three more
    with higher ids, and one entry per call."""
    before = state(env)
    for _ in range(2):
        r = post(env, world.path, who["admin:session"])
        assert r.status_code == 200 and r.json() == expected_body(world), r.text
    rows = reeval_rows(env, world.job.job_id)
    assert len(rows) == 6
    assert max(r[0] for r in rows[:3]) < min(r[0] for r in rows[3:])
    actions = [e["action"] for e in new_entries(env, before.audit_max)]
    assert actions == ["scan.reevaluate", "scan.reevaluate"]


def test_disabled_policy_is_reevaluated(env: ApiEnv, who: dict[str, m.Caller]) -> None:
    """#118 (c): only a deleted policy is refused; a disabled one is not."""
    w = build(env, status="disabled")
    r = post(env, w.path, who["admin:session"])
    assert r.status_code == 200 and r.json() == expected_body(w), r.text


# ----- CHK-M11-201, -207: refusals write nothing and do no work ------------------

REFUSALS = [
    ("admin:api", 403, "totp_session_required"),
    ("operator:api", 403, "totp_session_required|forbidden"),
    ("viewer:api", 403, "totp_session_required|forbidden"),
    ("operator:session", 403, "forbidden"),
    ("viewer:session", 403, "forbidden"),
    ("admin:restricted", 403, "totp_enrolment_required"),
    # REQ-046 (d) (M2): an admin session not TOTP-verified is restricted.
    ("admin:unverified", 403, "totp_enrolment_required"),
    ("admin:expired", 401, "unauthorized"),
    ("operator:revoked", 401, "unauthorized"),
    ("none", 401, "unauthorized"),
    ("agent", 401, "unauthorized"),
    ("enrol", 401, "unauthorized"),
]


@pytest.mark.parametrize(("kind", "status", "type_"), REFUSALS)
def test_refusal_writes_nothing_and_reads_no_scan(
    env: ApiEnv,
    who: dict[str, m.Caller],
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    status: int,
    type_: str,
) -> None:
    """REQ-270 (2): each refusal leaves scan_result_reeval and audit_log
    byte-identical, wakes nobody, and (CHK-M11-207) runs no statement on the
    scan, its results, the re-evaluation lock or the audit log."""
    w = wakes(env, monkeypatch, world.scan_id)
    before = state(env)
    spy = m.RoleSpy()
    with pytest.MonkeyPatch.context() as mp:
        spy.install(mp)
        r = post(env, world.path, who[kind])
    problem(r, status, type_)
    assert state(env) == before
    assert w.seen == []
    touched = [
        s
        for s in spy.statements
        if any(t in s.lower() for t in ("scan", "audit_log", "advisory"))
    ]
    assert touched == []


def test_viewer_on_an_unknown_scan_is_403_not_404(
    env: ApiEnv, who: dict[str, m.Caller]
) -> None:
    """Auth comes before existence: no scan-id oracle for a non-admin."""
    r = post(env, f"/api/v1/scans/{UNKNOWN}/reevaluate", who["viewer:session"])
    problem(r, 403, "forbidden")


# ----- CHK-M11-202: the sink gate under clock control ----------------------------


def test_sink_outage_gate_at_15_minutes_and_after_the_drain(
    env: ApiEnv, who: dict[str, m.Caller], world: World
) -> None:
    """TS §5.3 L1053: 14 min 59 s of outage still accepted; at 15 min 503
    audit_sink_unavailable with nothing written; accepted again once the
    queue drained."""
    admin = who["admin:session"]
    m.sink_down(env, 14 * 60 + 59)
    r = post(env, world.path, admin)
    assert r.status_code == 200 and r.json() == expected_body(world), r.text
    env.clock.advance(seconds=1)
    before = state(env)
    problem(post(env, world.path, admin), 503, "audit_sink_unavailable")
    assert state(env) == before
    m.sink_up(env)
    r = post(env, world.path, admin)
    assert r.status_code == 200 and r.json() == expected_body(world), r.text
    assert len(reeval_rows(env, world.job.job_id)) == 6


# ----- CHK-M11-203: 404, 400, 409 -----------------------------------------------


def test_unknown_scan_is_404_with_fixed_words(
    env: ApiEnv, who: dict[str, m.Caller], world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = wakes(env, monkeypatch, UUID(UNKNOWN))
    before = state(env)
    path = f"/api/v1/scans/{UNKNOWN}/reevaluate"
    body = problem(post(env, path, who["admin:session"]), 404, "not_found")
    assert body == {
        "type": "not_found",
        "title": body["title"],
        "status": 404,
        "detail": "No such scan.",
        "instance": path,
    }
    assert UNKNOWN not in body["detail"]
    assert state(env) == before and w.seen == []


def test_deleted_policy_is_409_with_fixed_words(
    env: ApiEnv, who: dict[str, m.Caller], monkeypatch: pytest.MonkeyPatch
) -> None:
    wd = build(env, delete=True)
    w = wakes(env, monkeypatch, wd.scan_id)
    before = state(env)
    body = problem(post(env, wd.path, who["admin:session"]), 409, "conflict")
    assert body == {
        "type": "conflict",
        "title": body["title"],
        "status": 409,
        "detail": "The policy is deleted.",
        "instance": wd.path,
    }
    assert state(env) == before and w.seen == []


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-uuid",
        UNKNOWN.replace("-", ""),
        UNKNOWN + "0",
        UNKNOWN[:-1],
        "{" + UNKNOWN + "}",
        "urn:uuid:" + UNKNOWN,
    ],
)
def test_malformed_id_is_400_for_an_admin(
    env: ApiEnv, who: dict[str, m.Caller], world: World, bad: str
) -> None:
    before = state(env)
    r = post(env, f"/api/v1/scans/{bad}/reevaluate", who["admin:session"])
    problem(r, 400, "invalid_request")
    assert state(env) == before


def test_upper_case_id_is_accepted(
    env: ApiEnv, who: dict[str, m.Caller], world: World
) -> None:
    path = f"/api/v1/scans/{str(world.scan_id).upper()}/reevaluate"
    r = post(env, path, who["admin:session"])
    assert r.status_code == 200 and r.json() == expected_body(world), r.text


# ----- CHK-M11-204: no body is read ----------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"garbage {",
        json.dumps({"execute": f"{m.EXEC}; rm -rf /", "scan_id": UNKNOWN}).encode(),
        json.dumps({"policy_version": 1, "rows": [1, 2]}).encode(),
    ],
    ids=["garbage", "execute", "fields"],  # stable ids: EXEC is random per run
)
def test_a_body_never_changes_the_answer(
    env: ApiEnv, who: dict[str, m.Caller], world: World, body: bytes
) -> None:
    before = state(env)
    r = post(
        env,
        world.path,
        who["admin:session"],
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200 and r.json() == expected_body(world), r.text
    assert scan_reeval_count(env, world.other_scan) == 0
    entries = new_entries(env, before.audit_max)
    assert [e["action"] for e in entries] == ["scan.reevaluate"]
    assert m.hits([json.dumps(entries[0]["detail"])]) == []


def test_a_2_mib_body_is_refused_before_any_work(
    env: ApiEnv, who: dict[str, m.Caller], world: World
) -> None:
    """TS §6.3: the 1 MiB JSON cap refuses it (413) before the app."""
    before = state(env)
    blob = json.dumps({"pad": "x" * (2 * 1_048_576)}).encode()
    r = post(
        env,
        world.path,
        who["admin:session"],
        content=blob,
        headers={"Content-Type": "application/json"},
    )
    problem(r, 413, "too_large")
    assert state(env) == before


# ----- CHK-M11-205: two concurrent calls ----------------------------------------


def wait_for_waiters(env: ApiEnv, n: int, bound_s: float = 10.0) -> None:
    deadline = time.monotonic() + bound_s
    with env.conn() as c:
        while True:
            k = int(
                f9.one(
                    c,
                    "SELECT count(*) FROM pg_locks"
                    " WHERE locktype = 'advisory' AND NOT granted",
                )
            )
            if k >= n:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"{k} advisory-lock waiters, wanted {n}")
            time.sleep(0.02)  # poll interval of the probe, not ordering


def test_two_concurrent_calls_are_serialised(env: ApiEnv, world: World) -> None:
    """REQ-270 (4): with the scan's re-evaluation lock held elsewhere, call
    A then call B queue on it; on release both answer 200, B's rows all
    have higher ids than A's, and the latest row of each plugin is B's."""
    at = env.clock.now()
    with env.conn() as c:
        ids = [m.make_user(c, "admin", at=at) for _ in range(2)]
        callers = [
            m.Caller(u, "admin", "session", m.make_token(c, u, at=at)) for u in ids
        ]
    clients = [env.client_for(env.fresh_ip()) for _ in range(2)]
    answers: dict[int, Any] = {}

    def run(i: int) -> None:
        try:
            answers[i] = clients[i].post(world.path, headers=callers[i].headers())
        except Exception as exc:  # reported by the asserts below
            answers[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    with m.holding_reeval_lock(env.server, world.scan_id):
        threads[0].start()
        wait_for_waiters(env, 1)
        threads[1].start()
        wait_for_waiters(env, 2)
    for t in threads:
        t.join(30)
        assert not t.is_alive()
    for i in range(2):
        r = answers[i]
        assert r.status_code == 200 and r.json() == expected_body(world), r
    rows = reeval_rows(env, world.job.job_id)
    a = [r[0] for r in rows if r[5] == ids[0]]
    b = [r[0] for r in rows if r[5] == ids[1]]
    assert len(a) == 3 and len(b) == 3
    assert max(a) < min(b)
    latest: dict[UUID, tuple[int, int]] = {}
    for rid, pu, *_, by in rows:
        if pu not in latest or rid > latest[pu][0]:
            latest[pu] = (rid, by)
    assert {by for _, by in latest.values()} == {ids[1]}
    with env.conn() as c:
        actors = [
            r[0]
            for r in c.execute(
                "SELECT actor FROM audit_log WHERE action = 'scan.reevaluate'"
                " AND target = %s ORDER BY audit_id",
                (f"scan:{world.scan_id}",),
            ).fetchall()
        ]
    assert actors == [f"user:{ids[0]}", f"user:{ids[1]}"]


# ----- CHK-M11-206: no alert ------------------------------------------------------


def test_reevaluation_raises_no_alert(
    env: ApiEnv, who: dict[str, m.Caller], world: World
) -> None:
    """REQ-271 (3), #148: audit-logged, but no entry has detail.alert and no
    bitscan_alerts_total{kind} moves."""
    metrics = alert_samples()
    assert metrics  # every kind is exported from zero
    before = state(env)
    r = post(env, world.path, who["admin:session"])
    assert r.status_code == 200, r.text
    entries = new_entries(env, before.audit_max)
    assert [e["action"] for e in entries] == ["scan.reevaluate"]
    assert [e for e in entries if (e["detail"] or {}).get("alert") is True] == []
    with env.conn() as c:
        alerted = int(
            f9.one(
                c,
                "SELECT count(*) FROM audit_log WHERE audit_id > %s"
                " AND detail ->> 'alert' = 'true'",
                (before.audit_max,),
            )
        )
    assert alerted == 0
    assert alert_samples() == metrics


# ----- CHK-M11-208: canaries and tokens ------------------------------------------


def test_no_canary_or_token_in_answers_logs_or_audit(
    env: ApiEnv,
    who: dict[str, m.Caller],
    world: World,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    deleted = build(env, delete=True)
    before = state(env)
    calls = [
        (world.path, who["admin:session"], 200),
        (f"/api/v1/scans/{UNKNOWN}/reevaluate", who["admin:session"], 404),
        (deleted.path, who["admin:session"], 409),
        (world.path, who["admin:api"], 403),
        (world.path, who["viewer:session"], 403),
        (world.path, who["agent"], 401),
    ]
    texts: list[str] = []
    for path, caller, status in calls:
        r = post(env, path, caller)
        assert r.status_code == status, (path, r.status_code, r.text)
        texts.append(r.text)
    assert m.hits(texts) == []
    records = [
        " ".join([rec.getMessage(), repr(rec.args), repr(vars(rec))])
        for rec in caplog.records
    ]
    assert any("token accepted" in t for t in records)  # the capture works
    assert m.hits(records) == []
    tokens = [c.token for c in who.values() if c.token is not None]
    assert [t for t in tokens if any(t in x for x in records + texts)] == []
    entries = new_entries(env, before.audit_max)
    assert m.hits([json.dumps(e["detail"]) for e in entries]) == []
    assert m.hits([x.detail_text or "" for x in env.sink.records]) == []


# ----- CHK-M11-209, -413: source checks -------------------------------------------

PKG = Path(__file__).resolve().parents[1] / "bitscan_manager"


def module_file(name: str) -> Path | None:
    p = PKG.joinpath(*name.split(".")[1:])
    if p.is_dir():
        return p / "__init__.py"
    f = p.with_suffix(".py")
    return f if f.exists() else None


def top_level_imports(path: Path) -> set[str]:
    """Module-level imports (also inside top-level if/try), not those in
    function bodies (``api/user/__init__`` imports its routers lazily)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.If | ast.Try):
            stack.extend(node.body)
            stack.extend(node.orelse)
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    stack.extend(h.body)
                stack.extend(node.finalbody)
    return out


def test_route_imports_no_repository() -> None:
    """REQ-270 (5), REQ-272 (2): reevaluate.py and every bm.api module it
    reaches import no bm.repositories module."""
    seen: set[str] = set()
    todo = ["bitscan_manager.api.user.reevaluate"]
    found: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = module_file(name)
        if path is None:
            continue
        imports = top_level_imports(path)
        found |= imports
        todo.extend(i for i in imports if i.startswith("bitscan_manager.api"))
    assert "bitscan_manager.services.evaluator.reevaluate" in found
    assert (
        sorted(i for i in found if i.startswith("bitscan_manager.repositories")) == []
    )


def test_reevaluate_scan_has_one_caller() -> None:
    """REQ-271 (1): M8's reevaluate_scan is used only by the route (and
    defined in its own module)."""
    users: set[str] = set()
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = (
                node.name
                if isinstance(node, ast.FunctionDef)
                else node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else None
            )
            aliases = (
                [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else []
            )
            if name == "reevaluate_scan" or "reevaluate_scan" in aliases:
                users.add(path.relative_to(PKG).as_posix())
    assert users == {"api/user/reevaluate.py", "services/evaluator/reevaluate.py"}
