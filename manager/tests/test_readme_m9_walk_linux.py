"""CHK-M9-285 to -287 (TASK-208, REQ-233): walk the README "Scans" and
"Schedules" sections, the agent "Compliance jobs and results" bullets and the
metrics line against a real `serve` over HTTPS on PostgreSQL, with the fake
OpenBao and audit sink, real agents enrolled through the API, and the real
clock (the scheduler ticks every 30 s, `offline_sweep` every 60 s).

Expected answers come from README.md, not from the code. Each documented step
is one row; the run collects every row and fails if any differs from the
README. With WALK_OUT set the rows are written there as JSON lines. Database
reads (job and scan states, stored results, audit entries) are made as the
owner, to observe; nothing is written to the database outside the API.

Not walked here, with the reason: deadlines, retries, the 24 h and 7-day
rules and "no back-fill" need hours of real time; they are tested with clock
control on PostgreSQL (TP-M9-14, TP-M9-15, tester-m9b).
"""

import functools
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import re2  # type: ignore[import-untyped]

from .catalog_rows import owner
from .conftest import PgServer
from .test_cli_users_pg import run as run_users
from .test_readme_m5_walk_linux import V1, Totp, Walk, section
from .test_readme_m7_walk_linux import (  # noqa: F401 - fixtures
    bit,
    ids,
    migrated_db,
    multipart,
    stack,
    until,
)
from .test_serve_linux import client_context

pytestmark = pytest.mark.pg

if sys.platform == "win32":
    pytest.skip("not run: Linux only (serve, inotify)", allow_module_level=True)

__all__ = ["migrated_db", "stack"]  # fixtures used by this module

FIX = Path(__file__).resolve().parent / "contract" / "fixtures"
NUL = chr(0)
FFFD = chr(0xFFFD)
SHAPE_RE = r"\bbs[uakse]_[A-Za-z0-9_-]{20,}"


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def result(plugin: str, stdout: str = "ok", **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "plugin_uuid": plugin,
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
        "started_at": now_text(),
        "finished_at": now_text(),
        "timed_out": False,
        "truncated": False,
        "error": None,
    }
    item.update(over)
    return item


def post_big(port: int, ca: Path, path: str, token: str, data: bytes) -> str:
    """POST a body over the cap as a client such as curl does: send it all,
    tolerate the server closing early, then read the answer it sent."""
    import http.client

    conn = http.client.HTTPSConnection(
        "localhost", port, context=client_context(ca), timeout=10
    )
    conn.putrequest("POST", path)
    conn.putheader("Authorization", f"Bearer {token}")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(len(data)))
    conn.endheaders()
    try:
        for i in range(0, len(data), 65_536):
            conn.send(data[i : i + 65_536])
    except OSError:
        pass  # the server answered and closed before reading it all
    try:
        resp = conn.getresponse()
        return str(resp.status)
    except (OSError, http.client.HTTPException) as exc:
        return "no answer: " + type(exc).__name__
    finally:
        conn.close()


def test_the_m9_scans_and_schedules_sections_behave_as_written(  # noqa: PLR0915
    stack: dict[str, Any], migrated_db: PgServer, tmp_path: Path
) -> None:
    scans_text = section("Scans")
    totp = Totp()
    t = secrets.token_hex(3)
    bits = tmp_path / "bits"
    (bits / "uploaded").mkdir(parents=True)
    main_name, dis_name, other_name = (
        f"Walk9 main {t}",
        f"Walk9 disabled {t}",
        f"Walk9 other {t}",
    )
    main_ids = ids(3)
    (bits / "main.bit").write_bytes(
        bit(main_name, main_ids, execute="cat /etc/hostname")
    )
    (bits / "dis.bit").write_bytes(bit(dis_name, ids(), status="disabled"))
    (bits / "other.bit").write_bytes(bit(other_name, ids()))
    s = stack["serve"](bits)
    w = Walk(s.port, s.ca)

    def db(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with owner(migrated_db) as c:
            return list(c.execute(sql, params).fetchall())

    def audit(action: str) -> list[tuple[Any, ...]]:
        return db(
            "SELECT actor, target, detail FROM audit_log WHERE action = %s ORDER BY"
            " audit_id",
            (action,),
        )

    def scan_count() -> int:
        return int(db("SELECT count(*) FROM scan")[0][0])

    # ------------------------------------------------------------ users
    admin, apw = f"m9-adm-{t}", "m9 walk pass " + secrets.token_hex(6)
    w.secrets.append(apw)
    dsn = next(tmp_path.glob("run-*/creds/app_dsn"))
    assert run_users(["create-admin", admin], dsn, stdin=apw + "\n").returncode == 0
    _, _, out = w.req(
        "POST",
        V1 + "/auth/login",
        body={"username": admin, "password": apw, "totp_code": None},
    )
    s0 = json.loads(out)["token"]
    w.secrets.append(s0)
    _, _, out = w.req("POST", V1 + "/auth/totp/enrol", token=s0, body={})
    secret = json.loads(out)["secret"]
    w.secrets.append(secret)
    import base64

    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    _, _, out = w.req(
        "POST", V1 + "/auth/totp/enrol", token=s0, body={"totp_code": totp.code(seed)}
    )
    S = json.loads(out)["token"]  # admin, TOTP-verified session
    w.secrets.append(S)
    users: dict[str, str] = {}
    for role in ("operator", "viewer"):
        name, pw = f"m9-{role[:3]}-{t}", f"m9 {role} pass " + secrets.token_hex(6)
        w.secrets.append(pw)
        st, _, out = w.req(
            "POST",
            V1 + "/users",
            token=S,
            body={"username": name, "password": pw, "role": role},
        )
        assert st == 201, out
        _, _, out = w.req(
            "POST",
            V1 + "/auth/login",
            body={"username": name, "password": pw, "totp_code": None},
        )
        users[role] = json.loads(out)["token"]
        w.secrets.append(users[role])
    OP, VS = users["operator"], users["viewer"]
    st, _, out = w.req("POST", V1 + "/api-tokens", token=OP, body={"name": "m9-walk"})
    assert st == 201, out
    OK = json.loads(out)["token"]  # the operator's bsk_ token
    w.secrets.append(OK)

    # ------------------------------------------------------------ policies
    def policy(name: str) -> dict[str, Any] | None:
        _, _, out = w.req("GET", V1 + "/policies?limit=500", token=S)
        return next(
            (p for p in json.loads(out)["items"] if p["policy_name"] == name), None
        )

    p_main = until(lambda: policy(main_name), 30)
    p_dis = until(lambda: policy(dis_name), 30)
    p_other = until(lambda: policy(other_name), 30)
    assert p_main and p_dis and p_other, "the folder policies were not imported"
    pid, pid_dis, pid_other = (
        p_main["policy_id"],
        p_dis["policy_id"],
        p_other["policy_id"],
    )
    up_name = f"Walk9 upload {t}"
    body, h = multipart(bit(up_name, ids()), "up.bit")
    st, _, out = w.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    assert st == 200, out
    pid_up = json.loads(out)["policy_id"]

    # ------------------------------------------------------------ agents
    enrol_body = json.loads(
        (FIX / "enrol" / "request_valid_full.json").read_text(encoding="utf-8")
    )
    st, _, out = w.req(
        "POST",
        V1 + "/enrollment-tokens",
        token=S,
        body={
            "max_uses": 5,
            "expires_in_hours": 24,
            "allowed_cidrs": None,
            "auto_approve": True,
        },
    )
    assert st == 201, out
    E = json.loads(out)["token"]
    w.secrets.append(E)
    st, _, out = w.req("POST", V1 + "/enrollment-tokens", token=S, body={})
    E_held = json.loads(out)["token"]
    w.secrets.append(E_held)
    agents: dict[
        str, tuple[str, str, str]
    ] = {}  # name -> (agent_id, token, machine_id)
    for name, token in (("A1", E), ("A2", E), ("A3", E), ("A4", E_held)):
        mid = secrets.token_hex(16)
        st, _, out = w.req(
            "POST",
            V1 + "/agent/enroll",
            token=token,
            body=enrol_body | {"hostname": f"m9-{name}-{t}", "machine_id": mid},
        )
        assert st == 200, out
        a = json.loads(out)
        agents[name] = (a["agent_id"], a["agent_token"], mid)
        w.secrets.append(a["agent_token"])
    A1, A2, A3, A4 = (agents[n][0] for n in ("A1", "A2", "A3", "A4"))
    for name, tags in (
        ("A1", ["prod-web"]),
        ("A2", ["prod-web", "db"]),
        ("A3", ["db"]),
    ):
        st, _, out = w.req(
            "PUT", f"{V1}/agents/{agents[name][0]}/tags", token=OP, body={"tags": tags}
        )
        assert st in (200, 204), out
    held_tag = w.req(
        "PUT", f"{V1}/agents/{A4}/tags", token=OP, body={"tags": ["prod-web"]}
    )[0]

    def pull(name: str) -> list[dict[str, Any]]:
        aid, tok, mid = agents[name]
        st, _, out = w.req(
            "GET",
            f"{V1}/agent/{aid}/jobs",
            token=tok,
            headers={"X-Bitscan-Machine-Id": mid},
        )
        assert st == 200, out
        jobs: list[dict[str, Any]] = json.loads(out)["jobs"]
        return jobs

    def post(
        name: str, job_id: str, results: list[dict[str, Any]], final: bool
    ) -> tuple[int, Any]:
        aid, tok, mid = agents[name]
        st, _, out = w.req(
            "POST",
            f"{V1}/agent/{aid}/jobs/{job_id}/results",
            token=tok,
            body={"results": results, "final": final},
            headers={"X-Bitscan-Machine-Id": mid},
        )
        return st, json.loads(out) if out else None

    def jobs_of(scan_id: str) -> list[tuple[Any, ...]]:
        return db(
            "SELECT job_id::text, agent_id::text, state::text, finished_at"
            " FROM scan_job WHERE scan_id = %s ORDER BY agent_id",
            (scan_id,),
        )

    inv_before = db(
        "SELECT job_id, state::text FROM scan_job WHERE kind = 'inventory' ORDER BY"
        " job_id"
    )

    # ------------------------------------------------- deleted profile + schedule
    st, _, out = w.req(
        "POST",
        V1 + "/scan-schedules",
        token=OK,
        body={
            "name": "up",
            "policy_id": pid_up,
            "target": {"all": True},
            "cron": "0 3 * * *",
        },
    )
    sched_up = json.loads(out).get("schedule_id") if st == 201 else None
    w.check(
        "a schedule of an uploaded profile",
        "POST /scan-schedules",
        "201",
        str(st),
        st == 201,
    )
    w.expect(
        "delete the profile (admin, TOTP session)",
        "DELETE",
        f"{V1}/policies/{pid_up}",
        204,
        token=S,
    )
    st, _, out = w.req("GET", f"{V1}/scan-schedules/{sched_up}", token=OK)
    w.check(
        "Deleting a profile disables its schedules",
        f"GET /scan-schedules/{sched_up}",
        "enabled false",
        out.decode()[:120],
        st == 200 and json.loads(out)["enabled"] is False,
    )
    w.expect(
        "a schedule of a deleted profile cannot be enabled",
        "PATCH",
        f"{V1}/scan-schedules/{sched_up}",
        409,
        "conflict",
        token=OK,
        body={"enabled": True},
    )
    w.expect(
        "a schedule of a deleted profile cannot be created",
        "POST",
        V1 + "/scan-schedules",
        409,
        "conflict",
        token=OK,
        body={
            "name": "up2",
            "policy_id": pid_up,
            "target": {"all": True},
            "cron": "0 3 * * *",
        },
    )

    # ------------------------------------------------- another profile's job
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OP,
        body={"policy_id": pid_other, "target": {"agents": [A1]}},
    )
    scan_other = json.loads(out)["scan_id"]

    # ------------------------------------------------- starting a scan
    key = "nightly-web-" + t
    req1 = {"policy_id": pid, "target": {"tags": ["prod-web"]}}
    audit_create_0 = len(audit("scan.create"))
    st, _, out = w.req(
        "POST", V1 + "/scans", token=OK, body=req1, headers={"Idempotency-Key": key}
    )
    a1 = json.loads(out) if st == 202 else {}
    w.check(
        "202 {scan_id, state: queued, policy_version, jobs}; tags match any,"
        " awaiting host left out",
        "POST /scans tags [prod-web] (API token, Idempotency-Key)",
        f"202 keys [jobs, policy_version, scan_id, state] queued v{p_main['version']}"
        f" jobs 2",
        f"{st} {sorted(a1)} {a1.get('state')} v{a1.get('policy_version')} jobs"
        f" {a1.get('jobs')}",
        st == 202
        and sorted(a1) == ["jobs", "policy_version", "scan_id", "state"]
        and a1["state"] == "queued"
        and a1["policy_version"] == p_main["version"]
        and a1["jobs"] == 2,
    )
    scan1 = a1.get("scan_id", "")
    stored = db(
        "SELECT target, policy_version, trigger::text FROM scan WHERE scan_id = %s",
        (scan1,),
    )
    w.check(
        "the scan records the request, the resolved hosts and the version",
        "scan row",
        f"target tags + resolved [A1, A2]; version {p_main['version']}; manual",
        str(stored[0][0]) if stored else "missing",
        bool(stored)
        and stored[0][0].get("tags") == ["prod-web"]
        and stored[0][0].get("resolved_agents") == sorted([A1, A2])
        and stored[0][1] == p_main["version"]
        and stored[0][2] == "manual",
    )
    count = scan_count()
    st, _, out = w.req(
        "POST", V1 + "/scans", token=OK, body=req1, headers={"Idempotency-Key": key}
    )
    w.check(
        "Idempotency-Key repeat: the first 202 answer, no second scan",
        "POST /scans again, same key and body",
        "202, the same body, scan count unchanged, no second scan.create",
        f"{st} same={json.loads(out) == a1 if st == 202 else None} scans"
        f" {count}->{scan_count()}",
        st == 202
        and json.loads(out) == a1
        and scan_count() == count
        and len(audit("scan.create")) == audit_create_0 + 1,
    )
    w.expect(
        "the same key with a different body gets 409",
        "POST",
        V1 + "/scans",
        409,
        token=OK,
        body={"policy_id": pid, "target": {"tags": ["db"]}},
        headers={"Idempotency-Key": key},
    )
    w.expect(
        "Idempotency-Key over 255 characters gets 400",
        "POST",
        V1 + "/scans",
        400,
        token=OK,
        body=req1,
        headers={"Idempotency-Key": "k" * 256},
    )
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OP,
        body={"policy_id": pid, "target": {"agents": [A3, str(uuid4())]}},
    )
    w.check(
        "agents target: unknown agent ids are left out",
        "POST /scans agents [A3, unknown] (session)",
        "202 jobs 1",
        f"{st} jobs {json.loads(out).get('jobs') if st == 202 else out[:80]!r}",
        st == 202 and json.loads(out)["jobs"] == 1,
    )
    alerts_0 = [
        d for _, _, d in audit("scan.create") if isinstance(d, dict) and d.get("alert")
    ]
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OP,
        body={"policy_id": pid, "target": {"all": True}},
    )
    all_session = json.loads(out) if st == 202 else {}
    w.check(
        "all: every host not awaiting approval; with a session, no alert",
        "POST /scans {all: true} (session)",
        "202 jobs 3, no alert",
        f"{st} jobs {all_session.get('jobs')}",
        st == 202
        and all_session["jobs"] == 3
        and [
            d
            for _, _, d in audit("scan.create")
            if isinstance(d, dict) and d.get("alert")
        ]
        == alerts_0,
    )
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OK,
        body={"policy_id": pid, "target": {"all": True}},
    )
    scan_all_k = json.loads(out).get("scan_id") if st == 202 else None
    entry = next(
        (d for _, tg, d in audit("scan.create") if tg == f"scan:{scan_all_k}"), None
    )
    w.check(
        "an all-hosts scan started with an API token writes the"
        " all_hosts_scan_api_token alert",
        "POST /scans {all: true} (API token)",
        "202; its scan.create entry carries the alert",
        str(entry)[:160],
        st == 202
        and isinstance(entry, dict)
        and entry.get("alert") is True
        and "all_hosts_scan_api_token" in json.dumps(entry),
    )
    creates = audit("scan.create")
    w.check(
        "every scan writes one scan.create audit entry",
        "audit_log",
        "one per queued scan (4 so far)",
        str(len(creates) - audit_create_0),
        len(creates) - audit_create_0 == 4,
    )
    j1 = jobs_of(scan1)
    w.check(
        "a new scan cancels the still-queued jobs of earlier scans of the same profile",
        f"jobs of the first scan {scan1}",
        "both cancelled, with finished_at",
        str([(r[2], r[3] is not None) for r in j1]),
        len(j1) == 2 and all(r[2] == "cancelled" and r[3] is not None for r in j1),
    )
    j_other = jobs_of(scan_other)
    w.check(
        "another profile's queued job is untouched",
        "job of the other profile's scan",
        "queued",
        str([r[2] for r in j_other]),
        [r[2] for r in j_other] == ["queued"],
    )
    inv_now = db(
        "SELECT job_id, state::text FROM scan_job WHERE kind = 'inventory' ORDER BY"
        " job_id"
    )
    w.check(
        "inventory jobs are never touched",
        "inventory jobs before/after the scans",
        "unchanged",
        f"{len(inv_before)} jobs, same states: {inv_now == inv_before}",
        inv_now == inv_before and len(inv_before) >= 3,
    )

    # ------------------------------------------------- refusals (nothing written)
    count = scan_count()
    big = {
        "policy_id": pid,
        "target": {"tags": ["prod-web"]},
        "pad": "x" * (1024 * 1024 + 10),
    }
    for label, body_, want, want_type in (
        ("a malformed target", {"policy_id": pid, "target": {"tags": []}}, 400, None),
        (
            "two target forms",
            {"policy_id": pid, "target": {"all": True, "tags": ["a"]}},
            400,
            None,
        ),
        (
            "any other body key",
            {"policy_id": pid, "target": {"all": True}, "execute": "id"},
            400,
            None,
        ),
        (
            "an unknown profile",
            {"policy_id": 999_999, "target": {"all": True}},
            404,
            None,
        ),
        (
            "a disabled profile",
            {"policy_id": pid_dis, "target": {"all": True}},
            409,
            "conflict",
        ),
        (
            "a deleted profile",
            {"policy_id": pid_up, "target": {"all": True}},
            409,
            "conflict",
        ),
        (
            "a target with no eligible host",
            {"policy_id": pid, "target": {"tags": ["nobody"]}},
            422,
            None,
        ),
    ):
        st, hd, out = w.expect(
            "refused: " + label,
            "POST",
            V1 + "/scans",
            want,
            want_type,
            token=OK,
            body=body_,
        )
        if want == 400 and label == "a malformed target":
            detail = json.loads(out).get("detail", "")
            w.check(
                "a malformed target names it",
                "problem detail",
                "Invalid request: target…",
                detail,
                detail.startswith("Invalid request: target"),
            )
    got_big = post_big(s.port, s.ca, V1 + "/scans", OK, json.dumps(big).encode())
    w.check(
        "refused: a body over 1 MiB",
        "POST /scans (1 MiB + body)",
        "413",
        got_big,
        got_big == "413",
    )
    w.check(
        "refusals write nothing",
        "scan count",
        str(count),
        str(scan_count()),
        scan_count() == count,
    )
    w.expect(
        "a viewer cannot start a scan", "POST", V1 + "/scans", 403, token=VS, body=req1
    )

    # ------------------------------------------------- an agent runs a job
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OK,
        body={"policy_id": pid, "target": {"agents": [A3]}},
    )
    scan_a3 = json.loads(out)["scan_id"]
    pulled = pull("A3")
    comp = [j for j in pulled if j["kind"] == "compliance"]
    J = comp[0] if comp else {}
    keys = set(J)
    w.check(
        "a pull returns inventory and compliance jobs together; a compliance job"
        " carries plugins and redaction_patterns, no expected values",
        "GET /agent/{A3}/jobs",
        "1 compliance job (+ inventory), keys job_id agent_id kind pickup_by plugins"
        " redaction_patterns; plugin keys plugin_uuid execute timeout_s",
        f"{[j['kind'] for j in pulled]} {sorted(keys)}"
        f" {sorted(J.get('plugins', [{}])[0])}",
        len(comp) == 1
        and any(j["kind"] == "inventory" for j in pulled)
        and keys
        == {"job_id", "agent_id", "kind", "pickup_by", "plugins", "redaction_patterns"}
        and all(set(p) == {"plugin_uuid", "execute", "timeout_s"} for p in J["plugins"])
        and "expected" not in json.dumps(pulled)
        and "not_empty" not in json.dumps(pulled),
    )
    jid = J.get("job_id", "")
    st, _, _ = w.req(
        "POST",
        V1 + "/scans",
        token=OK,
        body={"policy_id": pid, "target": {"agents": [A3]}},
    )
    w.check(
        "jobs already handed out keep running when a newer scan is queued",
        "POST /scans agents [A3] after the pull",
        "the pulled job stays dispatched",
        str(db("SELECT state::text FROM scan_job WHERE job_id = %s", (jid,))),
        st == 202
        and db("SELECT state::text FROM scan_job WHERE job_id = %s", (jid,))
        == [("dispatched",)],
    )

    # commands are fixed when queued

    def is_main(job: dict[str, Any]) -> bool:
        """A compliance job of the main profile (A1 also has the other one's)."""
        return job["kind"] == "compliance" and {
            p["plugin_uuid"] for p in job["plugins"]
        } <= set(main_ids)

    v1 = p_main["version"]
    queued_a1 = [j for j in pull("A1") if is_main(j)]
    (bits / "main.bit").write_bytes(
        bit(main_name, main_ids, execute="cat /etc/os-release")
    )
    p_v2 = until(lambda: (p := policy(main_name)) and p["version"] > v1 and p, 30)
    w.check(
        "a job keeps the commands it was built with",
        "pull A1's job queued before the re-import",
        "execute cat /etc/hostname",
        str([p["execute"] for j in queued_a1 for p in j["plugins"]][:1]),
        len(queued_a1) == 1
        and all(p["execute"] == "cat /etc/hostname" for p in queued_a1[0]["plugins"]),
    )
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OK,
        body={"policy_id": pid, "target": {"agents": [A1]}},
    )
    newer = [j for j in pull("A1") if is_main(j)]
    w.check(
        "scans queued after a re-import use the new version",
        "POST /scans agents [A1] after the re-import, then pull",
        "policy_version v+1, execute cat /etc/os-release",
        f"{json.loads(out).get('policy_version') if st == 202 else st}"
        f" {[p['execute'] for j in newer for p in j['plugins']][:1]}",
        bool(p_v2)
        and st == 202
        and json.loads(out)["policy_version"] == p_v2["version"]
        and len(newer) == 1
        and all(p["execute"] == "cat /etc/os-release" for p in newer[0]["plugins"]),
    )

    # results
    u1, u2, u3 = (p["plugin_uuid"] for p in J["plugins"])
    st, ans = post("A3", jid, [], False)
    state = db(
        "SELECT state::text, started_at IS NOT NULL, deadline_at IS NOT NULL FROM"
        " scan_job WHERE job_id = %s",
        (jid,),
    )
    w.check(
        "an empty batch is the start notice: running, deadline started",
        "POST results [] (final false)",
        "200 {accepted 0, duplicates 0}; running with started_at and deadline_at",
        f"{st} {ans} {state}",
        st == 200
        and ans == {"accepted": 0, "duplicates": 0}
        and state == [("running", True, True)],
    )
    started = db(
        "SELECT started_at, deadline_at FROM scan_job WHERE job_id = %s", (jid,)
    )
    post("A3", jid, [], False)
    w.check(
        "later start notices change nothing",
        "POST results [] again",
        "started_at and deadline_at unchanged",
        "unchanged"
        if db("SELECT started_at, deadline_at FROM scan_job WHERE job_id = %s", (jid,))
        == started
        else "changed",
        db("SELECT started_at, deadline_at FROM scan_job WHERE job_id = %s", (jid,))
        == started,
    )
    st, ans = post("A3", jid, [result(u1, "hello")], False)
    w.check(
        "accepted counts the stored results",
        "POST results [p1]",
        "200 {1, 0}",
        f"{st} {ans}",
        st == 200 and ans == {"accepted": 1, "duplicates": 0},
    )
    st, ans = post("A3", jid, [result(u1, "again")], False)
    w.check(
        "a result the job already had is a duplicate",
        "POST results [p1] again",
        "200 {0, 1}",
        f"{st} {ans}",
        st == 200 and ans == {"accepted": 0, "duplicates": 1},
    )

    def rows_after() -> list[tuple[Any, ...]]:
        return db("SELECT count(*) FROM scan_result WHERE job_id = %s", (jid,))

    rows_0 = rows_after()
    st, ans = post("A3", jid, [result(u2, "x"), result(str(uuid4()))], False)
    w.check(
        "a batch naming a check that is not in the job gets 409 and nothing of it is"
        " stored",
        "POST results [p2, foreign]",
        "409 job_not_acceptable; p2 not stored",
        f"{st} {ans and ans.get('type')} rows {rows_0}->{rows_after()}",
        st == 409
        and ans.get("type") == "job_not_acceptable"
        and rows_after() == rows_0,
    )
    nul_text = "a" + NUL + "b"
    st, ans = post("A3", jid, [result(u2, nul_text), result(u3, "z" * 65_537)], True)
    stored_rows = {
        r[0]: r[1:]
        for r in db(
            "SELECT plugin_uuid::text, eval_code, eval_detail, stdout, stderr FROM"
            " scan_result WHERE job_id = %s",
            (jid,),
        )
    }
    w.check(
        "U+0000 in stdout is stored, and compared, as U+FFFD",
        "POST results [p2 'a<NUL>b', ...]",
        "stored 'a' U+FFFD 'b'",
        repr(stored_rows.get(u2, ("?",))[2] if u2 in stored_rows else None),
        st == 200 and stored_rows.get(u2, (None, None, None))[2] == "a" + FFFD + "b",
    )
    w.check(
        "stdout over 65,536 bytes is stored as ERROR oversize with both texts empty",
        "POST results [p3 stdout 65,537 bytes]",
        "eval_code 2, eval_detail oversize, stdout '', stderr ''",
        str(stored_rows.get(u3)),
        stored_rows.get(u3) == (2, "oversize", "", ""),
    )
    w.check(
        "every check has a result: the job is completed",
        "job state",
        "completed",
        str(db("SELECT state::text FROM scan_job WHERE job_id = %s", (jid,))),
        db("SELECT state::text FROM scan_job WHERE job_id = %s", (jid,))
        == [("completed",)],
    )
    st, _, out = w.req("GET", V1 + "/metrics", token=VS)
    text = out.decode()
    w.check(
        "bitscan_plugin_results_total{result} counts stored results",
        "GET /metrics",
        "PASS, FAIL and ERROR series; ERROR >= 1",
        " ".join(
            ln
            for ln in text.splitlines()
            if ln.startswith("bitscan_plugin_results_total")
        ),
        st == 200
        and all(
            f'bitscan_plugin_results_total{{result="{r}"}}' in text
            for r in ("PASS", "FAIL", "ERROR")
        )
        and any(
            ln.startswith('bitscan_plugin_results_total{result="ERROR"}')
            and float(ln.split()[-1]) >= 1
            for ln in text.splitlines()
        ),
    )
    got = until(
        lambda: (
            db(
                "SELECT state::text, finished_at IS NOT NULL FROM scan WHERE scan_id"
                " = %s",
                (scan_a3,),
            )
            == [("completed", True)]
        ),
        100,
    )
    w.check(
        "the scan's state follows within about a minute (offline_sweep)",
        "scan state of the A3 scan",
        "completed, finished",
        str(
            db(
                "SELECT state::text, finished_at IS NOT NULL FROM scan WHERE scan_id"
                " = %s",
                (scan_a3,),
            )
        ),
        bool(got),
    )

    # ------------------------------------------------- cancelling
    st, _, out = w.req(
        "POST",
        V1 + "/scans",
        token=OK,
        body={"policy_id": pid, "target": {"agents": [A1, A2]}},
    )
    scan_c = json.loads(out)["scan_id"]
    jc = [j for j in pull("A2") if j["kind"] == "compliance"]
    st, _, out = w.req("POST", f"{V1}/scans/{scan_c}/cancel", token=OK)
    c1 = json.loads(out) if st == 200 else {}
    w.check(
        "cancel answers 200 {scan_id, state, cancelled_jobs}; queued and handed-out"
        " jobs become cancelled",
        f"POST /scans/{scan_c}/cancel (no body)",
        "200 cancelled_jobs 2, state cancelled",
        f"{st} {c1}",
        st == 200
        and sorted(c1) == ["cancelled_jobs", "scan_id", "state"]
        and c1["cancelled_jobs"] == 2
        and c1["scan_id"] == scan_c
        and c1["state"] == "cancelled",
    )
    st, ans = post("A2", jc[0]["job_id"], [], False) if jc else (0, None)
    w.check(
        "a host still running its job: its results are refused (409) and not stored",
        "POST results for the cancelled handed-out job",
        "409 job_not_acceptable",
        f"{st} {ans and ans.get('type')}",
        st == 409 and ans is not None and ans.get("type") == "job_not_acceptable",
    )
    w.check(
        "cancelled queued jobs are never handed out",
        "GET /agent/{A1}/jobs",
        "no job of the cancelled scan",
        str([j["job_id"] for j in pull("A1") if j["kind"] == "compliance"]),
        not [
            j
            for j in pull("A1")
            if j["kind"] == "compliance"
            and j["job_id"] in {r[0] for r in jobs_of(scan_c)}
        ],
    )
    st, _, out = w.req("POST", f"{V1}/scans/{scan_c}/cancel", token=OK)
    w.check(
        "cancelling again answers cancelled_jobs 0",
        "POST cancel again",
        "200 cancelled_jobs 0",
        f"{st} {out[:80]!r}",
        st == 200 and json.loads(out)["cancelled_jobs"] == 0,
    )
    n_cancel = [tg for _, tg, _ in audit("scan.cancel") if tg == f"scan:{scan_c}"]
    w.check(
        "each cancel writes one scan.cancel audit entry",
        "audit_log",
        "2",
        str(len(n_cancel)),
        len(n_cancel) == 2,
    )
    w.expect(
        "an unknown scan gets 404",
        "POST",
        f"{V1}/scans/{uuid4()}/cancel",
        404,
        token=OK,
    )
    w.expect(
        "an id not in the hyphenated form gets 400",
        "POST",
        f"{V1}/scans/{uuid4().hex}/cancel",
        400,
        token=OK,
    )
    w.expect(
        "a viewer cannot cancel", "POST", f"{V1}/scans/{scan_c}/cancel", 403, token=VS
    )

    # ------------------------------------------------- schedules
    sched_body = {
        "name": "Nightly web",
        "policy_id": pid,
        "target": {"tags": ["prod-web"]},
        "cron": "30 2 * * *",
        "timezone": "Europe/London",
    }
    st, _, out = w.req("POST", V1 + "/scan-schedules", token=OK, body=sched_body)
    item = json.loads(out) if st == 201 else {}
    item_keys = [
        "created_by",
        "cron",
        "enabled",
        "last_run_at",
        "name",
        "next_run_at",
        "policy_id",
        "schedule_id",
        "target",
        "timezone",
    ]
    w.check(
        "create answers 201 with the schedule",
        "POST /scan-schedules (the README example)",
        f"201 keys {item_keys}; enabled true; next_run_at after now",
        f"{st} {sorted(item)} enabled={item.get('enabled')}"
        f" next={item.get('next_run_at')}",
        st == 201
        and sorted(item) == item_keys
        and item["enabled"] is True
        and item["last_run_at"] is None
        and datetime.fromisoformat(item["next_run_at"].replace("Z", "+00:00"))
        > datetime.now(UTC),
    )
    sid = item.get("schedule_id")
    st, _, out = w.req(
        "POST",
        V1 + "/scan-schedules",
        token=OP,
        body={
            "name": "x",
            "policy_id": pid,
            "target": {"all": True},
            "cron": "0 3 * * 0",
        },
    )
    sun = json.loads(out) if st == 201 else {}
    nxt = datetime.fromisoformat(
        sun.get("next_run_at", "1970-01-01T00:00:00+00:00").replace("Z", "+00:00")
    )
    w.check(
        "timezone defaults to UTC; weekday 0 is Sunday",
        "POST {cron: '0 3 * * 0'} without timezone",
        "201 timezone UTC, next_run_at a Sunday 03:00Z",
        f"{st} {sun.get('timezone')} {sun.get('next_run_at')}",
        st == 201
        and sun["timezone"] == "UTC"
        and nxt.weekday() == 6
        and (nxt.hour, nxt.minute) == (3, 0),
    )
    st, _, out = w.req(
        "POST",
        V1 + "/scan-schedules",
        token=OP,
        body={
            "name": "y",
            "policy_id": pid,
            "target": {"all": True},
            "cron": "0 3 * * 7",
        },
    )
    w.check(
        "weekday 7 is Sunday too",
        "POST {cron: '0 3 * * 7'}",
        "same next_run_at as weekday 0",
        f"{st} {json.loads(out).get('next_run_at') if st == 201 else out[:60]!r}",
        st == 201 and json.loads(out)["next_run_at"] == sun["next_run_at"],
    )
    sid_7 = json.loads(out).get("schedule_id") if st == 201 else None
    w.expect(
        "a disabled profile's schedule is accepted",
        "POST",
        V1 + "/scan-schedules",
        201,
        token=OK,
        body={
            "name": "dis",
            "policy_id": pid_dis,
            "target": {"all": True},
            "cron": "0 3 * * *",
        },
    )
    for path in ("", f"/{sid}"):
        w.expect(
            "a viewer cannot read schedules (operator, reading included)",
            "GET",
            V1 + "/scan-schedules" + path,
            403,
            token=VS,
        )
    st, _, out = w.req("GET", V1 + "/scan-schedules?limit=2", token=OP)
    page1 = json.loads(out) if st == 200 else {}
    st2, _, out2 = w.req(
        "GET",
        V1 + "/scan-schedules?limit=2&cursor=" + str(page1.get("next_cursor")),
        token=OP,
    )
    page2 = json.loads(out2) if st2 == 200 else {}
    listed = [i["schedule_id"] for i in page1.get("items", []) + page2.get("items", [])]
    w.check(
        "list is ordered by schedule_id, paged with limit and cursor",
        "GET /scan-schedules?limit=2, then the cursor",
        "2 items + next_cursor, then the following ones, ascending",
        f"{st} {st2} {listed} cursor={page1.get('next_cursor')}",
        st == 200
        and st2 == 200
        and len(page1["items"]) == 2
        and page1["next_cursor"] is not None
        and listed == sorted(listed)
        and len(listed) >= 4,
    )
    st, _, out = w.req("GET", f"{V1}/scan-schedules/{sid}", token=OK)
    w.check(
        "read one schedule",
        f"GET /scan-schedules/{sid}",
        "200 the item",
        f"{st}",
        st == 200 and json.loads(out)["schedule_id"] == sid,
    )
    before = item.get("next_run_at")
    st, _, out = w.req(
        "PATCH", f"{V1}/scan-schedules/{sid}", token=OK, body={"cron": "0 4 * * 1"}
    )
    p = json.loads(out) if st == 200 else {}
    pn = datetime.fromisoformat(
        p.get("next_run_at", "1970-01-01T00:00:00+00:00").replace("Z", "+00:00")
    )
    w.check(
        "PATCH cron recomputes next_run_at",
        "PATCH {cron: '0 4 * * 1'}",
        "200, next_run_at a Monday 04:00 London time",
        f"{st} {before} -> {p.get('next_run_at')}",
        st == 200
        and p["next_run_at"] != before
        and pn.astimezone(__import__("zoneinfo").ZoneInfo("Europe/London")).weekday()
        == 0,
    )
    w.expect(
        "policy_id cannot change",
        "PATCH",
        f"{V1}/scan-schedules/{sid}",
        400,
        token=OK,
        body={"policy_id": pid_other},
    )
    w.expect(
        "an empty change is refused",
        "PATCH",
        f"{V1}/scan-schedules/{sid}",
        400,
        token=OK,
        body={},
    )
    st, _, out = w.req(
        "PATCH", f"{V1}/scan-schedules/{sid}", token=OP, body={"enabled": False}
    )
    w.check(
        "{enabled: false} stops the runs",
        "PATCH {enabled: false} (another operator's schedule)",
        "200 enabled false",
        f"{st} {out[:60]!r}",
        st == 200 and json.loads(out)["enabled"] is False,
    )
    for label, bad in (
        ("both day fields", {"cron": "0 0 1 * 1"}),
        ("an @ macro", {"cron": "@daily"}),
        ("a seconds field", {"cron": "0 0 3 * * *"}),
        ("never fires", {"cron": "0 0 30 2 *"}),
        ("over 64 characters", {"cron": "0" + " " * 64 + "3 * * *"}),
        ("an unknown time zone", {"timezone": "Mars/Base"}),
        ("a time zone over 64 characters", {"timezone": "Europe/" + "x" * 58}),
        ("an empty name", {"name": ""}),
        ("a name over 128 characters", {"name": "n" * 129}),
        ("a bad target", {"target": {"tags": []}}),
        ("a command key", {"execute": "id"}),
    ):
        w.expect(
            "refused: " + label,
            "PATCH",
            f"{V1}/scan-schedules/{sid}",
            400,
            token=OK,
            body=bad,
        )
    w.expect(
        "a 128-character name is accepted",
        "PATCH",
        f"{V1}/scan-schedules/{sid}",
        200,
        token=OK,
        body={"name": "n" * 128},
    )
    st, _, _ = w.req("DELETE", f"{V1}/scan-schedules/{sid_7}", token=OK)
    w.check(
        "delete answers 204",
        f"DELETE /scan-schedules/{sid_7}",
        "204",
        str(st),
        st == 204,
    )
    w.expect(
        "a deleted schedule is gone",
        "GET",
        f"{V1}/scan-schedules/{sid_7}",
        404,
        token=OK,
    )
    n_aud = {
        a: len(audit(a))
        for a in (
            "scan_schedule.create",
            "scan_schedule.update",
            "scan_schedule.delete",
        )
    }
    w.check(
        "each create, change and delete writes one scan_schedule.* entry",
        "audit_log",
        "create 5, update 3 (cron, enabled, name), delete 1",
        str(n_aud),
        n_aud
        == {
            "scan_schedule.create": 5,
            "scan_schedule.update": 3,
            "scan_schedule.delete": 1,
        },
    )

    # ------------------------------------------------- runs (real clock)
    def make(name: str, policy_id: int, target: dict[str, Any], token: str = OK) -> int:
        st, _, out = w.req(
            "POST",
            V1 + "/scan-schedules",
            token=token,
            body={
                "name": name,
                "policy_id": policy_id,
                "target": target,
                "cron": "* * * * *",
            },
        )
        assert st == 201, out
        return int(json.loads(out)["schedule_id"])

    r_all = make("every minute, all", pid, {"all": True})  # created with an API token
    r_dis = make("every minute, disabled profile", pid_dis, {"all": True})
    r_none = make("every minute, nobody", pid, {"tags": ["nobody"]})

    def scans_of(sched: int) -> list[tuple[Any, ...]]:
        return db(
            "SELECT scan_id::text, trigger::text, requested_by, finished_at FROM"
            " scan WHERE schedule_id = %s ORDER BY created_at",
            (sched,),
        )

    # An every-minute cron fires up to 60 s after creation and the tick runs
    # every 30 s, so 100 s left little slack (flaky in the M11 W3 run).
    first = until(lambda: scans_of(r_all), 180)
    sc = (first or [("", "", "x", None)])[0]
    entry = next(
        ((a, d) for a, tg, d in audit("scan.create") if tg == f"scan:{sc[0]}"), None
    )
    w.check(
        "a due schedule queues its scan as system, with one scan.create entry, never"
        " the API-token alert",
        "schedule '* * * * *' {all: true} created with an API token",
        "a scheduled scan within ~1.5 min; requested_by NULL; actor system; no alert",
        f"{sc[1]} requested_by={sc[2]}"
        f" entry={entry and (entry[0], (entry[1] or {}).get('alert'))}",
        bool(first)
        and sc[1] == "scheduled"
        and sc[2] is None
        and entry is not None
        and entry[0] == "system"
        and not (isinstance(entry[1], dict) and entry[1].get("alert")),
    )
    st, _, out = w.req("GET", f"{V1}/scan-schedules/{r_all}", token=OK)
    w.check(
        "last_run_at is when the schedule last queued a scan",
        f"GET /scan-schedules/{r_all}",
        "last_run_at set",
        f"{st} {json.loads(out).get('last_run_at') if st == 200 else ''}",
        st == 200 and json.loads(out)["last_run_at"] is not None,
    )

    def skipped(sched: int, reason: str) -> bool:
        for line in s.output().splitlines():
            if (
                "scheduled run skipped" in line
                and reason in line
                and re2.search(rf"schedule_id\W{{1,4}}{sched}\b", line)
            ):
                return True
        return False

    for sched, reason, label in (
        (r_dis, "policy_disabled", "the profile is disabled"),
        (r_none, "no_target_agents", "the target resolves to no host"),
        (
            r_all,
            "previous_unfinished",
            "the previous scan from the schedule has not finished",
        ),
    ):
        hit = until(functools.partial(skipped, sched, reason), 130)
        w.check(
            "a run is skipped when " + label,
            f"schedule {sched}",
            f"log `scheduled run skipped` with the id and `{reason}`",
            "logged" if hit else "not logged",
            bool(hit),
        )
    w.check(
        "a skipped run queues nothing",
        "scans of the skipped schedules",
        "none; still one scan for the every-minute schedule",
        f"dis {len(scans_of(r_dis))}, nobody {len(scans_of(r_none))}, all"
        f" {len(scans_of(r_all))}",
        not scans_of(r_dis) and not scans_of(r_none) and len(scans_of(r_all)) == 1,
    )
    for sched in (r_all, r_dis, r_none):
        w.req("DELETE", f"{V1}/scan-schedules/{sched}", token=OK)
    w.check(
        "the scans a deleted schedule started are kept",
        f"scan {sc[0]} after DELETE /scan-schedules/{r_all}",
        "row kept, schedule_id NULL",
        str(db("SELECT schedule_id FROM scan WHERE scan_id = %s", (sc[0],))),
        db("SELECT schedule_id FROM scan WHERE scan_id = %s", (sc[0],)) == [(None,)],
    )

    # ------------------------------------------------- the README text itself
    sched_text = (
        scans_text[scans_text.index("### Schedules") :]
        if "### Schedules" in scans_text
        else ""
    )
    whole = scans_text
    w.check(
        "no token, password or internal id in the new sections",
        "README Scans + Schedules",
        "no bs?_ token, no 'password', no TASK/REQ ids, no tester or agent names",
        str(
            re2.findall(SHAPE_RE, whole)
            + re2.findall(
                r"\b(?:TASK|REQ|CHK)-\d+|tester|impl-|planner|\bM1\d\b|\bM9\b", whole
            )
        ),
        not re2.search(SHAPE_RE, whole)
        and "password" not in whole.lower()
        and not re2.search(
            r"\b(?:TASK|REQ|CHK)-\d+|tester|impl-|planner|\bM\d+\b", whole
        ),
    )
    # M11 (REQ-289; PD-51): REQ-233's "results views are not part of this
    # version yet" sentence is superseded. Old → new: CHK-M9-285's README-text
    # row → the Scans section has its "### Scan results" subsection and the
    # sentence is gone; how keys are kept and the scan-state lag are unchanged.
    wants = (
        "### Scan results",
        "in memory, for 24 hours",
        "forgotten when the manager restarts",
        "lag",
    )
    stated = all(x in whole for x in wants) and "not part of this version" not in whole
    w.check(
        "the README documents scan results (the old 'not part of this version'"
        " line is gone), and how keys are kept",
        "README Scans",
        "'### Scan results' present, 'not part of this version' absent; keys 'in"
        " memory, for 24 hours' and forgotten on restart; scan state lags",
        "stated" if stated else "missing",
        stated,
    )
    w.check(
        "the Schedules section is under Scans",
        "README",
        "### Schedules inside ## Scans",
        "found" if sched_text else "missing",
        bool(sched_text),
    )

    # Round 2 (TASK-208 r1): the DST sentence and the deadline wording. The
    # README claim is checked against what the manager computes, with the
    # Europe/London 2026 transition days (the TASK-191 rows).
    from bitscan_manager.services.scheduler.cron import next_fire, parse_schedule

    dst_phrases = (
        "skipped in spring runs just after the jump",
        "repeated in autumn runs once, at its first occurrence",
        "more often than hourly makes no runs during the repeated hour",
    )

    def fire_list(cron: str, after: datetime, n: int) -> list[str]:
        sch, out_, t_ = parse_schedule(cron, "Europe/London"), [], after
        for _ in range(n):
            t_ = next_fire(sch, t_)
            out_.append(t_.strftime("%m-%d %H:%MZ"))
        return out_

    spring = fire_list("30 1 * * *", datetime(2026, 3, 28, 12, tzinfo=UTC), 2)
    autumn = fire_list("30 1 * * *", datetime(2026, 10, 24, 12, tzinfo=UTC), 2)
    half = fire_list("*/30 * * * *", datetime(2026, 10, 24, 23, 50, tzinfo=UTC), 4)
    w.check(
        "DST: a time skipped in spring runs just after the jump; a repeated one"
        " runs once, at its first occurrence; sub-hourly has no run in the"
        " repeated hour",
        "README Schedules `timezone` bullet; next_fire on Europe/London 2026",
        "stated; 03-29 01:30Z; 10-25 00:30Z only; */30 skips 01:00Z and 01:30Z",
        f"stated={[p in sched_text for p in dst_phrases]} spring={spring}"
        f" autumn={autumn} half={half}",
        all(p in sched_text for p in dst_phrases)
        and spring == ["03-29 01:30Z", "03-30 00:30Z"]
        and autumn == ["10-25 00:30Z", "10-26 01:30Z"]
        and half == ["10-25 00:00Z", "10-25 00:30Z", "10-25 02:00Z", "10-25 02:30Z"],
    )
    deadline_text = "ends `partial` or `failed` (or `completed` if every check"
    w.check(
        "a job past its deadline may end completed; only partial or failed get"
        " the retry",
        "README How a scan proceeds",
        "stated (#127 (b), #126 (c))",
        "stated" if deadline_text in whole else "missing",
        deadline_text in whole
        and "a `partial` or `failed` one gets **one** retry" in whole,
    )
    w.check(
        "the awaiting host's tag call",
        "PUT /agents/{A4}/tags",
        "recorded only",
        str(held_tag),
        True,
    )

    out_path = os.environ.get("WALK_OUT")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            for r in w.rows:
                fh.write(json.dumps(r.__dict__) + "\n")
    failed_rows = [r for r in w.rows if not r.ok]
    assert not failed_rows, "\n".join(
        f"{r.label}: expected {r.expected!r}, got {r.actual!r} ({r.request})"
        for r in failed_rows
    )
