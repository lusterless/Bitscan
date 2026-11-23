"""cluster_audit jobs on the agent routes (TS §3.8, §5.2, §6.1, §6.2, §6.5;
owner decision 2026-11-23): the pull, the one kubeconfig fetch, the results
and cmax_run, the file uploads and the operator downloads.
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from . import scan_pg_fixtures as f
from .agent_sim import SCANS, ApiEnv, SimAgent, api_env, batch, item
from .conftest import PgServer, own_migrated_server
from .test_clustermax_scans_api_pg import admin_totp, cmax_policy, scanner
from .test_totp_enrol import Cipher

pytestmark = pytest.mark.pg

SECRET = "token: CANARY-kc-5e1f"  # noqa: S105 - a test canary, not a secret
KUBECONFIG = f"apiVersion: v1\nkind: Config\nusers:\n- name: a\n  user:\n    {SECRET}\n"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("cmax-jobs")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def cat(env: ApiEnv, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(env.db, env.clock, tmp_path)


def kubeconfig_row(env: ApiEnv) -> int:
    with env.conn() as c:
        row = c.execute(
            "INSERT INTO kubeconfig (name, cluster_name, server, content_enc,"
            " created_by) VALUES (%s, 'c', 'https://k:6443', %s, 1)"
            " RETURNING kubeconfig_id",
            (f"kc-{env.fresh_ip()}", Cipher().encrypt(KUBECONFIG.encode())),
        ).fetchone()
    assert row is not None
    return int(row[0])


def queued_job(
    env: ApiEnv, cat: f.Catalog, agent: SimAgent, cmax: Any = None
) -> dict[str, Any]:
    pol = cmax_policy(cat)
    body: dict[str, Any] = {
        "policy_id": pol.policy_id,
        "target": {"agents": [str(agent.agent_id)]},
    }
    if cmax is not None:
        body["cmax"] = cmax
    r = env.call("POST", SCANS, admin_totp(env), body=body)
    assert r.status_code == 202, r.text
    jobs = agent.pulled()
    assert len(jobs) == 1 and jobs[0]["kind"] == "cluster_audit"
    job: dict[str, Any] = jobs[0]
    job["scan_id"] = r.json()["scan_id"]
    return job


def fetch(agent: SimAgent, job_id: str) -> Any:
    path = f"/api/v1/agent/{agent.agent_id}/jobs/{job_id}/kubeconfig"
    return agent.client().post(path, headers=agent.row.headers())


def upload(
    agent: SimAgent, job_id: str, name: str, data: bytes, truncated: bool = False
) -> Any:
    path = f"/api/v1/agent/{agent.agent_id}/jobs/{job_id}/files/{name}"
    return agent.client().put(
        path,
        content=gzip.compress(data),
        headers=agent.row.headers()
        | {
            "Content-Type": "application/gzip",
            "X-Bitscan-Truncated": "true" if truncated else "false",
        },
    )


def test_pull_returns_the_job_and_results_grade_each_check(
    env: ApiEnv, cat: f.Catalog
) -> None:
    a = scanner(env)
    job = queued_job(env, cat, a, {"target": "standalone"})
    assert job["cmax"]["target"] == "standalone" and "plugins" not in job
    checks = job["cmax"]["checks"]
    results = [
        item(c["plugin_uuid"], stdout="PASS observed=true", exit_code=0) for c in checks
    ]
    run = {
        "exit_code": 0,
        "error_line": None,
        "started_at": results[0]["started_at"],
        "finished_at": results[0]["finished_at"],
    }
    r = a.post(job["job_id"], batch(*results) | {"cmax_run": run})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == len(checks)
    with env.conn() as c:
        state = c.execute(
            "SELECT state FROM scan_job WHERE job_id = %s", (job["job_id"],)
        ).fetchone()
        stored = c.execute(
            "SELECT exit_code FROM cluster_audit_run WHERE job_id = %s",
            (job["job_id"],),
        ).fetchone()
    assert state is not None and state[0] == "completed"
    assert stored is not None and stored[0] == 0


def test_cmax_run_is_refused_on_a_compliance_job(env: ApiEnv, cat: f.Catalog) -> None:
    pol = cat.policy(1)
    a = env.agent()
    env.call(
        "POST",
        SCANS,
        env.caller("operator")[1],
        body={"policy_id": pol.policy_id, "target": {"agents": [str(a.agent_id)]}},
    )
    job = a.pulled()[0]
    res = item(job["plugins"][0]["plugin_uuid"])
    run = {
        "exit_code": 0,
        "error_line": None,
        "started_at": res["started_at"],
        "finished_at": res["finished_at"],
    }
    assert a.post(job["job_id"], batch(res) | {"cmax_run": run}).status_code == 409


def test_kubeconfig_is_fetched_once_and_never_logged(
    env: ApiEnv, cat: f.Catalog
) -> None:
    a = scanner(env)
    job = queued_job(env, cat, a, {"kubeconfig_id": kubeconfig_row(env)})
    assert job["cmax"]["kubeconfig"] is True and SECRET not in str(job)
    r = fetch(a, job["job_id"])
    assert r.status_code == 200, r.text
    assert r.json() == {"kubeconfig": KUBECONFIG}
    assert r.headers["cache-control"] == "no-store"
    again = fetch(a, job["job_id"])
    assert again.status_code == 409
    with env.conn() as c:
        rows = c.execute("SELECT action, detail::text FROM audit_log").fetchall()
    text = repr(rows)
    assert "kubeconfig.fetch" in text and "kubeconfig.refetch" in text
    assert "CANARY-kc" not in text


def test_kubeconfig_is_refused_to_another_agent_and_without_one(
    env: ApiEnv, cat: f.Catalog
) -> None:
    a, other = scanner(env), scanner(env)
    job = queued_job(env, cat, a, {"kubeconfig_id": kubeconfig_row(env)})
    assert fetch(other, job["job_id"]).status_code == 409
    b = scanner(env)
    plain = queued_job(env, cat, b)  # no kubeconfig chosen
    assert fetch(b, plain["job_id"]).status_code == 409


def test_files_are_stored_once_and_downloaded_by_operators(
    env: ApiEnv, cat: f.Catalog
) -> None:
    a = scanner(env)
    job = queued_job(env, cat, a)
    data = b"PASS  Access / Sudo  [access.sudoAvailable]\n"
    r = upload(a, job["job_id"], "report.txt", data)
    assert r.status_code == 201, r.text
    assert r.json() == {
        "name": "report.txt",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    assert upload(a, job["job_id"], "report.txt", data).status_code == 409
    assert upload(a, job["job_id"], "secrets.txt", data).status_code == 404
    assert upload(scanner(env), job["job_id"], "run.log", data).status_code == 409
    files = env.call(
        "GET", f"{SCANS}/{job['scan_id']}/files", env.caller("operator")[1]
    )
    assert files.status_code == 200 and [i["name"] for i in files.json()["items"]] == [
        "report.txt"
    ]
    path = f"{SCANS}/{job['scan_id']}/jobs/{job['job_id']}/files/report.txt"
    got = env.call("GET", path, env.caller("operator")[1])
    assert got.status_code == 200 and gzip.decompress(got.content) == data
    assert env.call("GET", path, env.caller("viewer")[1]).status_code == 403


def test_a_gzip_bomb_is_refused(env: ApiEnv, cat: f.Catalog) -> None:
    a = scanner(env)
    job = queued_job(env, cat, a)
    bomb = b"\0" * (65 * 1024 * 1024)
    assert upload(a, job["job_id"], "audit.out", bomb).status_code == 413


@pytest.mark.parametrize(
    ("stdouts", "exit_code", "want"),
    [
        # Every result graded PASS (ExpectedResult "ok" in this fixture).
        (["ok", "ok", "ok", "ok"], 0, ("pass", 0, 0, 0, 0)),
        # Graded FAIL; the counts read the ClusterMAX verdict words.
        (
            ["ok", "ok", "PASS observed=true", "n/a observed=x"],
            0,
            ("fail", 1, 0, 0, 1),
        ),
        (["ok", "FAIL x", "WARNING x", "ok"], 2, ("error", 0, 1, 1, 0)),
    ],
)
def test_scan_detail_shows_the_clustermax_verdict(
    env: ApiEnv,
    cat: f.Catalog,
    stdouts: list[str],
    exit_code: int,
    want: tuple[str, int, int, int, int],
) -> None:
    """TS §3.8: `error` when the exit code is not 0, `pass` when every graded
    check passes, otherwise `fail`, with the PASS, FAIL, WARNING and n/a
    counts; no raw output, so a viewer sees it too."""
    a = scanner(env)
    job = queued_job(env, cat, a, {"target": "standalone"})
    detail_path = f"{SCANS}/{job['scan_id']}"
    viewer = env.caller("viewer", "session")[1]
    before = env.call("GET", detail_path, viewer).json()
    assert before["hosts"][0]["clustermax"] is None
    checks = job["cmax"]["checks"]
    results = [
        item(c["plugin_uuid"], stdout=s, exit_code=0)
        for c, s in zip(checks, stdouts, strict=True)
    ]
    run = {
        "exit_code": exit_code,
        "error_line": None if exit_code == 0 else "cmax: error: x",
        "started_at": results[0]["started_at"],
        "finished_at": results[0]["finished_at"],
    }
    assert a.post(job["job_id"], batch(*results) | {"cmax_run": run}).status_code == 200
    r = env.call("GET", detail_path, viewer)
    assert r.status_code == 200, r.text
    got = r.json()["hosts"][0]["clustermax"]
    assert got == {
        "verdict": want[0],
        "exit_code": exit_code,
        "passed": want[1],
        "failed": want[2],
        "warning": want[3],
        "not_applicable": want[4],
    }
    assert "cmax: error" not in r.text
