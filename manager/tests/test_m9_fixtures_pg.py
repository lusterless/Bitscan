"""TP-M9-01 self-test (CHK-M9-100 to -104): the M9 fixture builder and the
simulated agent produce what the spec says they model, before any M9
suite relies on them. Expected values: SR §1.1 (display name), SR §2.3
(document order = sort_order), TS §5.2 (agent_status, scan_job checks, the
job_created_at trigger), TS §6.5 (ComplianceJob), #117 (eval_spec).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.services.evaluator.eval_spec import parse_eval_spec

from . import scan_pg_fixtures as f
from .agent_sim import ApiEnv, api_env, fixture_body, map_uuids
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m9fx")) as s:
        yield s


@pytest.fixture
def cat(server: PgServer, tmp_path: Path) -> Iterator[f.Catalog]:
    clock = f.Clock()
    with f.app_database(server) as db:
        yield f.make_catalog(db, clock, tmp_path)


def test_catalog_upload_stores_order_names_and_versions(
    server: PgServer, cat: f.Catalog
) -> None:
    """CHK-M9-100: three plugins in document order become sort_order 0..2 (SR
    §2.3), v_plugin shows `<family> - <plugin>` (SR §1.1), a changed Execute
    re-import bumps the version, a disabled upload is disabled, a delete
    soft-deletes (TS §4.3 L550)."""
    defs = [f.sr_plugin(), f.plugin(), f.plugin()]
    pol = cat.policy(defs, family=f.SR_FAMILY)
    with f.app(server) as c:
        rows = c.execute(
            "SELECT pp.plugin_uuid, v.display_name, pl.execute, pl.operator::text,"
            " pl.expected_result, pl.timeout_s FROM policy_plugin pp"
            " JOIN v_plugin v ON v.plugin_uuid = pp.plugin_uuid"
            " JOIN plugin pl ON pl.plugin_uuid = pp.plugin_uuid"
            " WHERE pp.policy_id = %s ORDER BY pp.sort_order",
            (pol.policy_id,),
        ).fetchall()
    assert [r[0] for r in rows] == pol.uuids
    assert rows[0][1] == "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed"
    assert rows[0][2:] == (f.SR_EXECUTE, "equals", "install ok installed", 30)
    v1 = pol.version
    cat.bump_to(pol, v1 + 2)
    assert cat.version_of(pol.policy_id) == v1 + 2
    off = cat.policy(1, status="disabled")
    with f.app(server) as c:
        assert (
            f.one(
                c,
                "SELECT policy_status FROM policy WHERE policy_id = %s",
                (off.policy_id,),
            )
            == "disabled"
        )
    cat.delete(off)
    with f.app(server) as c:
        assert f.one(
            c,
            "SELECT deleted_at IS NOT NULL FROM policy WHERE policy_id = %s",
            (off.policy_id,),
        )


def test_fleet_has_all_six_statuses_with_tags_and_real_tokens(server: PgServer) -> None:
    """CHK-M9-101: TS §5.2 agent_status has exactly six values; each agent
    holds its tags; only the token's hash is stored (TS §6.2)."""
    tag = f.new_tag()
    with f.app(server) as c:
        fl = f.fleet(c, [tag, "m9.common"])
        enum = c.execute(
            "SELECT unnest(enum_range(NULL::agent_status))::text"
        ).fetchall()
        for status, a in fl.items():
            assert a.token.startswith("bsa_")
            got = c.execute(
                "SELECT status::text, token_hash FROM agent WHERE agent_id = %s",
                (a.agent_id,),
            ).fetchone()
            assert got is not None and got[0] == status and a.token not in got[1]
            tags = c.execute(
                "SELECT tag FROM agent_tag WHERE agent_id = %s ORDER BY tag",
                (a.agent_id,),
            ).fetchall()
            assert [t[0] for t in tags] == sorted([tag, "m9.common"])
    assert tuple(r[0] for r in enum) == f.STATUSES


def test_owner_jobs_and_results_have_the_spec_shapes(
    server: PgServer, cat: f.Catalog
) -> None:
    """CHK-M9-102: payload validates as ComplianceJob (TS §6.5); eval_spec
    parses (#117) and matches the payload in order; a result with the job's
    created_at passes the TS §5.2 trigger and any other value is refused;
    jobs in two months land in two partitions; the scan_job CHECKs hold."""
    pol = cat.policy(3)
    with f.app(server) as ac:
        a = f.make_agent(ac)
    with f.owner(server) as c:
        sid = f.owner_scan(c, pol, state="running")
        job = f.owner_job(c, sid, a.agent_id, pol, state="running", patterns=["x=\\S+"])
        retry = f.owner_job(
            c,
            sid,
            a.agent_id,
            pol,
            pol.plugins[1:],
            state="queued",
            retry_of=job.job_id,
        )
        schemas.ComplianceJob.model_validate(job.payload)
        assert list(job.payload) == [
            "job_id",
            "agent_id",
            "kind",
            "pickup_by",
            "plugins",
            "redaction_patterns",
        ]
        spec = parse_eval_spec(job.eval_spec)
        assert [p.plugin_uuid for p in spec.plugins] == pol.uuids
        f.owner_result(c, job, pol, pol.plugins[0])
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute(
                "INSERT INTO scan_result (job_id, job_created_at, plugin_uuid,"
                " eval_code, plugin_name_snap, execute_snap, operator_snap,"
                " expected_snap, started_at, finished_at) VALUES (%s, %s, %s, 0,"
                " 'n', 'e', 'equals', 'x', now(), now())",
                (job.job_id, job.created_at + timedelta(seconds=1), pol.uuids[1]),
            )
        later = f.owner_job(
            c, sid, a.agent_id, pol, state="running", created_at=f.next_month(f.T0)
        )
        f.owner_result(c, later, pol, pol.plugins[0])
        parts = c.execute(
            "SELECT tableoid::regclass::text FROM scan_result WHERE job_id = ANY(%s)",
            ([job.job_id, later.job_id],),
        ).fetchall()
        assert len({p[0] for p in parts}) == 2
        assert "default" not in " ".join(p[0] for p in parts)
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO scan_job (kind, agent_id, payload, pickup_by)"
                " VALUES ('compliance', %s, '{}', now())",
                (a.agent_id,),
            )
    assert retry.retry_of == job.job_id


def test_clock_canary_and_checksum_helpers(server: PgServer, cat: f.Catalog) -> None:
    """CHK-M9-103: the clock moves only when told; the canary is unique per
    run; a checksum changes on a one-byte change."""
    clock = f.Clock()
    t = clock.now()
    assert clock.now() == t
    assert clock.advance(seconds=1) == t + timedelta(seconds=1)
    assert f.CANARY.startswith("M9CANARY-") and len(f.CANARY) == 45
    pol = cat.policy(1)
    with f.owner(server) as c:
        before = f.checksum(c, "plugin")
        c.execute(
            "UPDATE plugin SET execute = execute || 'x' WHERE plugin_uuid = %s",
            (pol.uuids[0],),
        )
        assert f.checksum(c, "plugin") != before


def test_simulated_agent_uses_fixtures_real_tokens_and_routes(
    server: PgServer, tmp_path: Path
) -> None:
    """CHK-M9-104: the simulated agent authenticates with its bsa_ token
    through the real pull route (an inventory job comes back, TS §6.5), and a
    fixture body mapped onto job uuids keeps every other field."""
    with api_env(server, tmp_path) as env:
        sim = env.agent()
        with f.owner(server) as c:
            inv = f.owner_inventory_job(
                c, sim.agent_id, created_at=env.clock.now() - timedelta(minutes=5)
            )
        jobs = sim.pulled()
        assert [j["job_id"] for j in jobs] == [str(inv)]
        assert sim.pull(path_id=str(env.agent().agent_id)).status_code == 403
    body = fixture_body("request_valid_error_cases")
    uuids = [uuid4() for _ in body["results"]]
    mapped = map_uuids(body, uuids)
    assert [i["plugin_uuid"] for i in mapped["results"]] == [str(u) for u in uuids]
    assert [i["error"] for i in mapped["results"]] == [
        i["error"] for i in body["results"]
    ]
    assert isinstance(env, ApiEnv)
