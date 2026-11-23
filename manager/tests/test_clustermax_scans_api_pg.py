"""ClusterMAX scans through POST /api/v1/scans (TS §3.8, §4.4, §6.2, §6.5;
owner decision 2026-11-23).

Expected values come from the spec: a Clustermax profile is scanned only by
an admin with a TOTP session and only by hand; one cluster_audit job per
scanner (agent 0.6.0 or later reporting "scanner"); a kubeconfig scan has
exactly one scanner and target k8s; only allow-listed variables; the job
payload carries the checks, never a command or a kubeconfig; schedules of a
ClusterMAX profile are refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from . import scan_pg_fixtures as f
from .agent_sim import SCANS, ApiEnv, api_env
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

CHECKS = ["header", "status", "access.sudoAvailable", "software.perf.installed"]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("cmax-scans")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[ApiEnv]:
    with api_env(server, tmp_path) as e:
        yield e


@pytest.fixture
def cat(env: ApiEnv, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(env.db, env.clock, tmp_path)


def cmax_policy(cat: f.Catalog) -> f.Pol:
    defs = [
        f.plugin(execute=f"cmax-check {c}", name=f"0.{i} - {c} - x")
        for i, c in enumerate(CHECKS, 1)
    ]
    return cat.policy(defs, family="Clustermax")


def scanner(
    env: ApiEnv,
    version: str = "0.6.0",
    helpers: tuple[str, ...] = ("capread", "scanner"),
) -> Any:
    return env.agent(version=version, runner_helpers=Jsonb(list(helpers)))


def admin_totp(env: ApiEnv) -> str:
    return env.caller("admin", "session")[1]


def scan(env: ApiEnv, tok: str, pol: f.Pol, agents: list[Any], cmax: Any = None) -> Any:
    body: dict[str, Any] = {
        "policy_id": pol.policy_id,
        "target": {"agents": [str(a.agent_id) for a in agents]},
    }
    if cmax is not None:
        body["cmax"] = cmax
    return env.call("POST", SCANS, tok, body=body)


def jobs_of(env: ApiEnv, scan_id: str) -> list[tuple[Any, ...]]:
    with env.conn() as c:
        return c.execute(
            "SELECT kind, state, payload, eval_spec, agent_id FROM scan_job"
            " WHERE scan_id = %s",
            (scan_id,),
        ).fetchall()


def kubeconfig(env: ApiEnv, deleted: bool = False) -> int:
    with env.conn() as c:
        row = c.execute(
            "INSERT INTO kubeconfig (name, cluster_name, server, content_enc,"
            " created_by,"
            " deleted_at) VALUES (%s, 'c', 'https://k:6443', 'enc:00', 1, %s)"
            " RETURNING kubeconfig_id",
            (f"k-{env.fresh_ip()}", env.clock.now() if deleted else None),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_admin_queues_one_cluster_audit_job_per_scanner(
    env: ApiEnv, cat: f.Catalog
) -> None:
    pol = cmax_policy(cat)
    a, b = scanner(env), scanner(env)
    r = scan(
        env,
        admin_totp(env),
        pol,
        [a, b],
        {"target": "slurm", "vars": {"CLUSTERMAX_K8S_GPU_DRA": "1"}},
    )
    assert r.status_code == 202, r.text
    assert r.json()["jobs"] == 2
    jobs = jobs_of(env, r.json()["scan_id"])
    assert {j[0] for j in jobs} == {"cluster_audit"} and {j[1] for j in jobs} == {
        "queued"
    }
    payload = jobs[0][2]
    assert set(payload) == {
        "job_id",
        "agent_id",
        "kind",
        "pickup_by",
        "cmax",
        "redaction_patterns",
    }
    assert (
        payload["cmax"]["target"] == "slurm" and payload["cmax"]["kubeconfig"] is False
    )
    # TS §6.5: every allow-listed name is present, null when unset.
    assert payload["cmax"]["vars"] == {
        "CLUSTERMAX_K8S_GPU_DRA": "1",
        "CLUSTERMAX_K8S_GPU_DRA_DEVICE_CLASS": None,
        "CLUSTERMAX_K8S_GPU_DRA_DRIVER": None,
        "CLUSTERMAX_AUDIT_K8S_NAMESPACE": None,
        "CLUSTERMAX_AUDIT_TENANT_NAMESPACE": None,
    }
    assert [c["check_id"] for c in payload["cmax"]["checks"]] == CHECKS
    assert "execute" not in str(payload) and "plugins" not in payload
    assert len(jobs[0][3]["plugins"]) == len(CHECKS)  # graded on the manager only
    with env.conn() as c:
        row = c.execute(
            "SELECT clustermax FROM scan WHERE scan_id = %s", (r.json()["scan_id"],)
        ).fetchone()
    assert row is not None and row[0] == {
        "target": "slurm",
        "kubeconfig_id": None,
        "vars": {"CLUSTERMAX_K8S_GPU_DRA": "1"},
    }


def test_default_options_are_auto(env: ApiEnv, cat: f.Catalog) -> None:
    r = scan(env, admin_totp(env), cmax_policy(cat), [scanner(env)])
    assert r.status_code == 202, r.text
    assert jobs_of(env, r.json()["scan_id"])[0][2]["cmax"]["target"] == "auto"


def test_only_an_admin_totp_session(env: ApiEnv, cat: f.Catalog) -> None:
    pol, a = cmax_policy(cat), scanner(env)
    for role, kind in (("operator", "session"), ("admin", "api")):
        r = scan(env, env.caller(role, kind)[1], pol, [a])
        assert r.status_code == 403, (role, kind, r.text)


def test_hosts_must_be_scanners_on_0_6_0(env: ApiEnv, cat: f.Catalog) -> None:
    pol, tok = cmax_policy(cat), admin_totp(env)
    for agent in (
        scanner(env, version="0.5.7"),
        scanner(env, helpers=("capread",)),
        env.agent(),
    ):
        r = scan(env, tok, pol, [scanner(env), agent])
        assert r.status_code == 409, r.text


def test_kubeconfig_rules(env: ApiEnv, cat: f.Catalog) -> None:
    pol, tok = cmax_policy(cat), admin_totp(env)
    kid = kubeconfig(env)
    r = scan(env, tok, pol, [scanner(env)], {"kubeconfig_id": kid})
    assert r.status_code == 202, r.text
    cm = jobs_of(env, r.json()["scan_id"])[0][2]["cmax"]
    assert (cm["target"], cm["kubeconfig"]) == ("k8s", True)
    assert (
        scan(
            env, tok, pol, [scanner(env), scanner(env)], {"kubeconfig_id": kid}
        ).status_code
        == 400
    )
    assert (
        scan(
            env, tok, pol, [scanner(env)], {"kubeconfig_id": kid, "target": "slurm"}
        ).status_code
        == 400
    )
    assert (
        scan(
            env,
            tok,
            pol,
            [scanner(env)],
            {"kubeconfig_id": kubeconfig(env, deleted=True)},
        ).status_code
        == 409
    )
    assert (
        scan(env, tok, pol, [scanner(env)], {"kubeconfig_id": 999_999}).status_code
        == 409
    )


@pytest.mark.parametrize(
    "variables",
    [
        {"CLUSTERMAX_AUDIT_K8S_HOST_CHECK_IMAGE": "evil/image"},
        {"CLUSTERMAX_K8S_GPU_DRA": "2"},
        {"CLUSTERMAX_AUDIT_K8S_NAMESPACE": "Bad_Namespace"},
        {"PATH": "/usr/local/evil"},
    ],
)
def test_variables_outside_the_list_are_refused(
    env: ApiEnv, cat: f.Catalog, variables: dict[str, str]
) -> None:
    r = scan(
        env, admin_totp(env), cmax_policy(cat), [scanner(env)], {"vars": variables}
    )
    assert r.status_code == 400, r.text


def test_plugin_path_refuses_a_clustermax_profile_and_cmax_needs_one(
    env: ApiEnv, cat: f.Catalog
) -> None:
    tok = admin_totp(env)
    plain = cat.policy(1)
    assert scan(env, tok, plain, [env.agent()], {"target": "auto"}).status_code == 400


def test_a_clustermax_profile_cannot_be_scheduled(env: ApiEnv, cat: f.Catalog) -> None:
    pol = cmax_policy(cat)
    body = {
        "name": "nightly",
        "policy_id": pol.policy_id,
        "target": {"all": True},
        "cron": "0 1 * * *",
    }
    r = env.call("POST", "/api/v1/scan-schedules", admin_totp(env), body=body)
    assert r.status_code == 409, r.text
