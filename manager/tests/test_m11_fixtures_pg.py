"""TP-M11-01 self-test: the M11 fixture builder writes what it says
(tester-m11; CHK-M11-100 to -104).

Each check reads the rows back as the database stores them and compares
them with the TS §5.2 shapes the builder promises, so a suite built on a
wrong fixture fails here first.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from bitscan_manager.auth.tokens import token_hash
from bitscan_manager.services.audit.verify import verify_chain

from . import m11_pg_fixtures as m
from . import scan_pg_fixtures as f9
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m11-fixtures")) as s:
        yield s


def partitions_of(conn: m.Conn, job_ids: list[Any]) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT tableoid::regclass::text FROM scan_result"
        " WHERE job_id = ANY(%s)",
        (job_ids,),
    ).fetchall()
    return {str(r[0]) for r in rows}


# ------------------------------------------------------------ CHK-M11-100


def test_results_world_shapes(server: PgServer) -> None:
    with m.owner(server) as c:
        w = m.results_world(c)
        target = f9.scan_row(c, w.scan_id)["target"]
        assert target["resolved_agents"] == sorted(
            str(h.agent_id) for h in w.hosts.values()
        )
        assert set(target) == {"agents", "resolved_agents"}
        parts = partitions_of(c, [j.job_id for j in w.jobs.values()])
        assert len(parts) == 2 and "scan_result_default" not in parts, parts
        assert m.default_partition_rows(c) == 0
        stored = {
            (r["job_id"], r["plugin_uuid"]): r["result"]
            for r in f9.results_of(c, [j.job_id for j in w.jobs.values()])
        }
        p = w.p
        assert stored[(w.jobs["a"].job_id, p[2].plugin_uuid)] == "ERROR"
        assert stored[(w.jobs["a_retry"].job_id, p[3].plugin_uuid)] == "FAIL"
        assert (w.jobs["a"].job_id, p[3].plugin_uuid) not in stored
        assert not any(k[0] == w.jobs["b"].job_id for k in stored)
        assert w.jobs["a_retry"].retry_of == w.jobs["a"].job_id
        lo, hi = f9.one(
            c,
            "SELECT (SELECT reevaluated_at FROM scan_result_reeval"
            " WHERE reeval_id = %s), (SELECT reevaluated_at"
            " FROM scan_result_reeval WHERE reeval_id = %s)",
            (w.reevals["low"], w.reevals["high"]),
        )
        assert w.reevals["high"] > w.reevals["low"] and hi < lo
        hostname = f9.one(
            c,
            "SELECT hostname FROM agent WHERE agent_id = %s",
            (w.hosts["b"].agent_id,),
        )
        assert m.SCRIPT in hostname
        spec = w.jobs["a"].eval_spec["plugins"][0]
        assert spec["expected"] == m.EXP
        assert m.EXEC in w.jobs["a"].payload["plugins"][0]["execute"]


def test_every_job_state_and_random_scans(server: PgServer) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 3)
        _, jobs = m.jobs_in_every_state(c, pol)
        states = {s: f9.job_state(c, j.job_id)["state"] for s, j in jobs.items()}
        assert states == {s: s for s in m.JOB_STATES}
        agents = [m.host(c).agent_id for _ in range(4)]
        rng = random.Random(1108)  # noqa: S311 - seeded test data
        for _ in range(10):
            rs = m.random_scan(c, rng, pol, agents)
            rows = f9.results_of(c, [j.job_id for j in rs.jobs])
            # one result per host and plugin in the unit (first result wins)
            unit = {j.job_id: (j.retry_of or j.job_id) for j in rs.jobs}
            keys = [(unit[r["job_id"]], r["plugin_uuid"]) for r in rows]
            assert len(keys) == len(set(keys))
            for j in rs.jobs:
                if j.retry_of is not None:
                    orig = next(o for o in rs.jobs if o.job_id == j.retry_of)
                    answered = {
                        r["plugin_uuid"] for r in rows if r["job_id"] == orig.job_id
                    }
                    assert not answered & set(j.uuids)
        assert m.default_partition_rows(c) == 0


def test_new_version_and_soft_delete(server: PgServer) -> None:
    with m.owner(server) as c:
        pol = m.make_policy(c, 2)
        first = pol.plugins[0].plugin_uuid
        m.new_version(
            c, pol, rename={first: "renamed"}, drop=[pol.plugins[1].plugin_uuid]
        )
        assert pol.version == 2
        assert (
            f9.one(c, "SELECT plugin_name FROM plugin WHERE plugin_uuid = %s", (first,))
            == "renamed"
        )
        m.soft_delete(c, pol)
        deleted, source = f9.one(
            c,
            "SELECT deleted_at IS NOT NULL, source_file FROM policy"
            " WHERE policy_id = %s",
            (pol.policy_id,),
        )
        assert deleted and source == f"deleted/{pol.policy_id}"


# ------------------------------------------------------------ CHK-M11-101


def test_callers_cover_every_role_and_kind(server: PgServer) -> None:
    with m.app(server) as c:
        who = m.callers(c)
        assert set(who) == {
            "viewer:session", "viewer:api", "operator:session", "operator:api",
            "admin:session", "admin:api", "admin:restricted", "operator:revoked",
            "agent", "enrol", "none",
        }  # fmt: skip
        prefixes = {k: (v.token or "")[:4] for k, v in who.items()}
        assert {prefixes[k] for k in who if k.endswith(":session")} == {"bsu_"}
        assert {prefixes[k] for k in who if k.endswith(":api")} == {"bsk_"}
        assert (prefixes["agent"], prefixes["enrol"], who["none"].token) == (
            "bsa_",
            "bse_",
            None,
        )
        rows = {
            k: c.execute(
                "SELECT u.role::text, u.totp_secret_enc IS NOT NULL, t.kind,"
                " t.totp_verified, t.revoked_at IS NOT NULL FROM user_token t"
                " JOIN app_user u USING (user_id) WHERE t.token_hash = %s",
                (token_hash(v.token),),
            ).fetchone()
            for k, v in who.items()
            if v.user_id is not None and v.token is not None
        }
        assert rows["admin:session"] == ("admin", True, "session", True, False)
        assert rows["admin:api"] == ("admin", True, "api", False, False)
        assert rows["admin:restricted"] == ("admin", False, "session", False, False)
        assert rows["operator:revoked"] == ("operator", True, "session", True, True)
        assert rows["viewer:session"] == ("viewer", True, "session", True, False)


# ------------------------------------------------------------ CHK-M11-102


def test_canaries_spy_and_lock(
    server: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(set(m.CANARIES)) == 4
    assert m.hits(["x " + m.OUT, "y"]) == [m.OUT]
    spy = m.RoleSpy()
    spy.install(monkeypatch)
    with m.retention_database(server) as db, db.transaction() as tx:
        tx.conn.execute("SELECT 1")
    with m.app(server) as c:
        c.execute("SELECT 2")
    assert "bitscan_retention" in spy.roles and "bitscan_app" in spy.roles
    assert any(s == "SELECT 1" for s in spy.by_role("bitscan_retention"))
    monkeypatch.undo()
    with m.owner(server) as c:
        pol = m.make_policy(c, 1)
        sid = m.scan(c, pol, [m.host(c).agent_id])
    probe = (
        "SELECT pg_try_advisory_xact_lock(hashtext('scan_reeval'),"
        " hashtext(CAST(CAST(%s AS uuid) AS text)))"
    )
    with m.holding_reeval_lock(server, sid):
        with m.tx_conn(server, "bitscan_app") as other:
            assert f9.one(other, probe, (sid,)) is False
    with m.tx_conn(server, "bitscan_app") as other:
        assert f9.one(other, probe, (sid,)) is True


# ------------------------------------------------------------ CHK-M11-103


def test_aged_world_offsets_are_exact(server: PgServer) -> None:
    now = m.now_utc()
    with m.owner(server) as c:
        w = m.aged_world(c, now)
        scan_at = {
            label: f9.one(
                c,
                "SELECT created_at FROM scan WHERE scan_id = %s",
                (w.key("scan", label),),
            )
            for label in ("inside", "at", "past", "old")
        }
        assert scan_at["at"] == now - timedelta(days=400)
        assert scan_at["past"] == now - timedelta(days=400, microseconds=1)
        tok = {
            label: f9.one(
                c,
                "SELECT expires_at FROM user_token WHERE token_id = %s",
                (w.key("token", label),),
            )
            for label in ("at", "past", "inside_89")
        }
        assert tok["at"] == now - timedelta(days=90)
        assert tok["past"] == now - timedelta(days=90, microseconds=1)
        assert tok["inside_89"] == now - timedelta(days=89)
        snap = f9.one(
            c,
            "SELECT collected_at FROM inventory_snapshot WHERE snapshot_id = %s",
            (w.key("snapshot", "past"),),
        )
        assert snap == now - timedelta(days=180, microseconds=1)
        dec = f9.one(
            c,
            "SELECT decided_at, decision FROM enrollment_request WHERE request_id = %s",
            (w.key("request", "at"),),
        )
        assert dec == (now - timedelta(days=90), "approved")
        pend = f9.one(
            c,
            "SELECT decision FROM enrollment_request WHERE request_id = %s",
            (w.key("request", "pending"),),
        )
        assert pend is None
        fin = f9.one(
            c,
            "SELECT finished_at, kind FROM scan_job WHERE job_id = %s",
            (w.key("inventory_job", "past"),),
        )
        assert fin == (now - timedelta(days=30, microseconds=1), "inventory")
        left = m.scan_remains(c, w.key("scan", "past"), w.scan_jobs["past"])
        assert left == {
            "scan": 1,
            "scan_job": 4,
            "scan_result": 4,
            "scan_result_reeval": 2,
        }
        assert len(partitions_of(c, w.scan_jobs["past"])) == 2
        assert m.default_partition_rows(c) == 0
        assert all(m.present(c, w).values())


# ------------------------------------------------------------ CHK-M11-104


def test_audit_chain_with_chosen_times_verifies(server: PgServer) -> None:
    now = m.now_utc()
    old = now - timedelta(days=4 * 366)
    ids = m.audit_chain(
        server, [old, old + timedelta(seconds=1), now, old], detail={"k": m.EXP}
    )
    assert ids == sorted(ids) and len(ids) == 4
    with psycopg.connect(server.dsn("bitscan_app"), autocommit=True) as c:
        assert verify_chain(c).ok
        ats = [
            f9.one(c, "SELECT at FROM audit_log WHERE audit_id = %s", (i,)) for i in ids
        ]
    assert ats == [old, old + timedelta(seconds=1), now, old]


def test_checksum_and_grant_probe(server: PgServer) -> None:
    with m.owner(server) as c:
        uid = m.make_user(c, "viewer")
        before = m.checksum(c, "app_user")
        with c.transaction(force_rollback=True):
            c.execute(
                "UPDATE app_user SET username = username || 'x' WHERE user_id = %s",
                (uid,),
            )
            assert m.checksum(c, "app_user") != before
        assert m.checksum(c, "app_user") == before
    with m.app(server) as c:
        assert m.refused(c, "DELETE FROM scan") == "42501"
        assert m.refused(c, "SELECT 1 FROM scan LIMIT 1") is None
