"""TASK-198 TEST: ``queue_scan()`` on PostgreSQL as bitscan_app (TP-M9-11;
CHK-M9-153 to -161; mutation rows CHK-M9-351, -352, -354 to -358, -366,
-381 service side).

Expected values: TS §2.3 L133 (one job per host from the policy's current
plugins), §3.3 L213 (only active plugins of enabled policies; no ad-hoc
command), §3.5 L248 (a compliance job carries {plugin_uuid, execute,
timeout_s} and the redaction patterns; Operator and ExpectedResult stay on
the manager), §4.4 L555 (targets resolved at queue time; offline agents get
jobs), L558 (a newer queued job cancels the older queued one), L559
(disabled → refused), L560 (each scan records policy.version), L566
(pickup_by = creation + 24 h), §4.1 L530, §4.3 L547, L550, §6.5
L1165–L1182, §8.4 L1290 (all-hosts scan with an API token alerts); #3, #18,
#122 (c)–(f), #125 (a)–(h), #129 (a), (b); SR §1.1; REQ-209, REQ-211,
REQ-212, REQ-227, REQ-229 (2).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.api.agent import schemas
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories import scan_progress, scan_queue
from bitscan_manager.repositories.results import host_counts
from bitscan_manager.services.audit.metrics import REGISTRY
from bitscan_manager.services.evaluator.eval_spec import parse_eval_spec
from bitscan_manager.services.jobs import build, queue
from bitscan_manager.services.jobs.scan_state import derive
from bitscan_manager.services.jobs.targets import parse_target

from . import scan_pg_fixtures as f
from .conftest import PgServer, own_migrated_server

pytestmark = pytest.mark.pg

NOW = f.T0 + timedelta(hours=1, microseconds=250_000)
KIND = "all_hosts_scan_api_token"
DETAIL_KEYS = {
    "policy_id",
    "policy_version",
    "trigger",
    "schedule_id",
    "target_kind",
    "jobs",
    "cancelled_older",
    "already_running",
}


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("queue")) as s:
        yield s


@pytest.fixture
def db(server: PgServer) -> Iterator[AppDatabase]:
    with f.app_database(server) as d:
        yield d


@pytest.fixture
def cat(db: AppDatabase, tmp_path: Path) -> f.Catalog:
    return f.make_catalog(db, f.Clock(), tmp_path)


def scan(db: AppDatabase, pol: f.Pol | int, target: Any, **kw: Any) -> queue.ScanQueued:
    args: dict[str, Any] = {
        "policy_id": pol if isinstance(pol, int) else pol.policy_id,
        "target": parse_target(target),
        "trigger": "manual",
        "schedule_id": None,
        "requested_by": 11,
        "actor": "user:11",
        "via_api_token": False,
        "now": NOW,
    } | kw
    with db.transaction() as tx:
        return queue.queue_scan(tx, **args)


def alerts(kind: str = KIND) -> float:
    return REGISTRY.get_sample_value("bitscan_alerts_total", {"kind": kind}) or 0.0


# ------------------------------------------------------------ CHK-M9-153


def test_tag_scan_of_version_3_queues_one_job_per_eligible_agent(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-211 (1), REQ-208 (3), (4), TS §4.4 L555, L560: version 3, a tag
    target over four tagged agents (decommissioned, awaiting approval,
    offline, online) → (scan_id, "queued", 3, 2); one scan row with the
    version, trigger, target (request + sorted resolved_agents), requested_by
    and state queued; two queued jobs (the offline one included) whose
    created_at is the scan's."""
    pol = cat.bump_to(cat.policy(2), 3)
    tag = f.new_tag()
    with f.app(server) as c:
        ag = {
            s: f.make_agent(c, s, tags=[tag]).agent_id
            for s in ("decommissioned", "awaiting_approval", "offline", "online")
        }
        before = f.counts(c)
    out = scan(db, pol, {"tags": [tag]})
    assert (out.state, out.policy_version, out.jobs) == ("queued", 3, 2)
    want = sorted([ag["offline"], ag["online"]])
    with f.app(server) as c:
        row = f.scan_row(c, out.scan_id)
        jobs = f.jobs_of_scan(c, out.scan_id)
        after = f.counts(c)
    assert (row["policy_id"], row["policy_version"], row["trigger"]) == (
        pol.policy_id,
        3,
        "manual",
    )
    assert (row["schedule_id"], row["requested_by"], row["state"]) == (
        None,
        11,
        "queued",
    )
    assert row["target"] == {"tags": [tag], "resolved_agents": [str(a) for a in want]}
    assert row["created_at"] == NOW and row["finished_at"] is None
    assert [j["agent_id"] for j in jobs] == want
    assert all(j["state"] == "queued" and j["created_at"] == NOW for j in jobs)
    assert after == (before[0] + 1, before[1] + 2, before[2], before[3] + 1)


# ------------------------------------------------------------ CHK-M9-154


def test_refusals_write_nothing(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-211 (2), #3, #122 (f), #125 (h), CHK-M9-352, -357: disabled →
    PolicyDisabled; deleted → PolicyDeleted; unknown → PolicyNotFound; no
    eligible agent → NoTargetAgents; no active plugin → PolicyHasNoPlugins;
    each leaves the scan, scan_job and audit_log counts unchanged."""
    with f.app(server) as c:
        a = f.make_agent(c).agent_id
        dec = f.make_agent(c, "decommissioned").agent_id
    off = cat.policy(1, status="disabled")
    gone = cat.policy(1)
    cat.delete(gone)
    live = cat.policy(1)
    empty = cat.policy(1)
    with f.owner(server) as o:
        o.execute(
            "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s",
            (empty.uuids[0],),
        )
    cases: list[tuple[Any, Any, type[Exception]]] = [
        (off, {"all": True}, queue.PolicyDisabled),
        (gone, {"all": True}, queue.PolicyDeleted),
        (2**62, {"all": True}, queue.PolicyNotFound),
        (live, {"agents": [str(dec)]}, queue.NoTargetAgents),
        (live, {"tags": ["m9.nobody-has-this"]}, queue.NoTargetAgents),
        (empty, {"agents": [str(a)]}, queue.PolicyHasNoPlugins),
    ]
    for pol, target, err in cases:
        with f.app(server) as c:
            before = f.counts(c)
        with pytest.raises(err):
            scan(db, pol, target)
        with f.app(server) as c:
            assert f.counts(c) == before, err


# ------------------------------------------------------------ CHK-M9-155


def test_a_newer_scan_cancels_only_the_older_queued_jobs_it_replaces(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-211 (3), TS §4.4 L558, #125 (e), REQ-229 (2), CHK-M9-358, -381:
    scan 2 for agents {a, b} cancels scan 1's queued job for a (finished_at =
    scan 2's time) and its queued retry for b; it leaves scan 1's dispatched
    job for c... and its job for d (not targeted), another policy's queued
    job for a, and every inventory job, byte-identical; cancelled_older
    counts 2."""
    pol, other = cat.policy(2), cat.policy(1)
    with f.app(server) as c:
        a, b, cc, d = (f.make_agent(c).agent_id for _ in range(4))
    with f.owner(server) as o:
        inv = [f.owner_inventory_job(o, x) for x in (a, b)]
        so = f.owner_scan(o, other)
        qo = f.owner_job(o, so, a, other, created_at=NOW - timedelta(hours=1))
    first = scan(
        db, pol, {"agents": [str(x) for x in (a, cc, d)]}, now=NOW - timedelta(hours=1)
    )
    with f.owner(server) as o:
        jobs1 = {j["agent_id"]: j for j in f.jobs_of_scan(o, first.scan_id)}
        o.execute(
            "UPDATE scan_job SET state = 'dispatched', dispatched_at = %s"
            " WHERE job_id = %s",
            (NOW, jobs1[cc]["job_id"]),
        )
        s0 = f.owner_scan(o, pol, state="running", created_at=NOW - timedelta(hours=3))
        ob = f.owner_job(
            o, s0, b, pol, state="failed", created_at=NOW - timedelta(hours=3)
        )
        rb = f.owner_job(
            o,
            s0,
            b,
            pol,
            state="queued",
            retry_of=ob.job_id,
            created_at=NOW - timedelta(hours=2),
        )
        keep = [jobs1[cc]["job_id"], jobs1[d]["job_id"], qo.job_id, ob.job_id, *inv]
        before = {j: f.job_state(o, j) for j in keep}
        mark = f.last_audit(o)
    second = scan(db, pol, {"agents": [str(a), str(b)]})
    with f.owner(server) as o:
        for j in (jobs1[a]["job_id"], rb.job_id):
            st = f.job_state(o, j)
            assert (st["state"], st["finished_at"]) == ("cancelled", NOW)
        for j, row in before.items():
            assert f.job_state(o, j) == row, j
        new = f.jobs_of_scan(o, second.scan_id)
        (entry,) = f.audit_after(o, mark)
    assert [j["state"] for j in new] == ["queued", "queued"]
    assert entry["detail"]["cancelled_older"] == 2


def _reasons(o: Any, scan_id: Any) -> dict[Any, tuple[str, Any, Any]]:
    rows = o.execute(
        "SELECT agent_id, state::text, cancel_reason, finished_at FROM scan_job"
        " WHERE scan_id = %s",
        (scan_id,),
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_a_host_already_running_the_policy_gets_its_job_not_run(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """TS §4.4, §5.2, §8.3 Integration (owner decision 2026-11-14): a host with
    a dispatched or running job of the same policy gets this scan's job
    inserted cancelled with cancel_reason 'already_running' and finished_at =
    the scan's time; a host running only another policy, one with a queued or
    a finished job of the policy, and a fresh host get queued jobs with no
    reason. The audit detail counts the jobs not run."""
    pol, other = cat.policy(2), cat.policy(1)
    with f.app(server) as c:
        disp, run, oth, que, done, fresh = (f.make_agent(c).agent_id for _ in range(6))
    earlier = NOW - timedelta(hours=1)
    with f.owner(server) as o:
        s0 = f.owner_scan(o, pol, state="running", created_at=earlier)
        f.owner_job(
            o,
            s0,
            disp,
            pol,
            state="dispatched",
            created_at=earlier,
            dispatched_at=earlier,
        )
        f.owner_job(
            o,
            s0,
            run,
            pol,
            state="running",
            created_at=earlier,
            dispatched_at=earlier,
            started_at=earlier,
        )
        f.owner_job(o, s0, que, pol, state="queued", created_at=earlier)
        f.owner_job(
            o, s0, done, pol, state="completed", created_at=earlier, finished_at=earlier
        )
        so = f.owner_scan(o, other, state="running", created_at=earlier)
        f.owner_job(
            o,
            so,
            oth,
            other,
            state="running",
            created_at=earlier,
            dispatched_at=earlier,
            started_at=earlier,
        )
        mark = f.last_audit(o)
    agents = [disp, run, oth, que, done, fresh]
    queued = scan(db, pol, {"agents": [str(x) for x in agents]})
    assert queued.jobs == 6 and queued.state == "queued"
    with f.owner(server) as o:
        got = _reasons(o, queued.scan_id)
        (entry,) = f.audit_after(o, mark)
    assert got[disp] == got[run] == ("cancelled", "already_running", NOW)
    for x in (oth, que, done, fresh):
        assert got[x] == ("queued", None, None), x
    assert entry["detail"]["already_running"] == 2
    assert entry["detail"]["jobs"] == 6
    assert entry["detail"]["cancelled_older"] == 1  # que's older queued job


def test_a_scan_whose_every_host_runs_the_policy_derives_cancelled(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """Every job not run: no job is open or has results, so the scan derives
    cancelled (TS §4.4 scan state), and the pull never sends the job."""
    pol = cat.policy(2)
    with f.app(server) as c:
        a = f.make_agent(c).agent_id
    earlier = NOW - timedelta(hours=1)
    with f.owner(server) as o:
        s0 = f.owner_scan(o, pol, state="running", created_at=earlier)
        f.owner_job(
            o,
            s0,
            a,
            pol,
            state="running",
            created_at=earlier,
            dispatched_at=earlier,
            started_at=earlier,
        )
    queued = scan(db, pol, {"agents": [str(a)]})
    with f.owner(server) as o:
        units = scan_progress.unit_facts(o, [queued.scan_id])[queued.scan_id]
        pending = o.execute(
            "SELECT count(*) FROM scan_job WHERE scan_id = %s AND state = 'queued'",
            (queued.scan_id,),
        ).fetchone()
    assert derive(units) == ("cancelled", True)
    assert pending == (0,)


# ------------------------------------------------------------ CHK-M9-156


def test_jobs_keep_the_commands_they_were_built_with(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-211 (5), (6), TS §4.1 L530, §4.3 L547, #18: a job queued before an
    import keeps the old Execute; one queued after carries the new one and
    the new version; disabling the policy afterwards leaves both queued."""
    pol = cat.policy(1)
    old = pol.plugins[0]
    with f.app(server) as c:
        a, b = f.make_agent(c).agent_id, f.make_agent(c).agent_id
    s1 = scan(db, pol, {"agents": [str(a)]})
    new = replace(old, execute="echo the-new-command")
    cat.reimport(pol, [new])
    s2 = scan(db, pol, {"agents": [str(b)]}, now=NOW + timedelta(minutes=1))
    cat.reimport(pol, status="disabled")
    with f.app(server) as c:
        (j1,) = f.jobs_of_scan(c, s1.scan_id)
        (j2,) = f.jobs_of_scan(c, s2.scan_id)
    assert j1["payload"]["plugins"][0]["execute"] == old.execute
    assert j2["payload"]["plugins"][0]["execute"] == "echo the-new-command"
    assert s2.policy_version == s1.policy_version + 1
    assert (j1["state"], j2["state"]) == ("queued", "queued")


# ------------------------------------------------------------ CHK-M9-157


def test_stored_payload_and_eval_spec_are_the_spec_shapes(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-209 (1)–(3), (6), TS §6.5, #125 (a)–(c), CHK-M9-351: exactly the six
    keys, validates ComplianceJob, job_id = the row id, ids lowercase,
    pickup_by = created + 24 h as YYYY-MM-DDTHH:MM:SSZ, plugins in sort_order,
    redaction_patterns = the setting at queue time; no operator, expected,
    eval_spec or name at any depth; the eval_spec parses and matches the
    payload one to one, with the SR §1.1 name, operator and expected."""
    defs = [
        f.sr_plugin(),
        f.plugin(timeout_s=600),
        f.plugin(operator="regex", expected="^ok$"),
    ]
    pol = cat.policy(defs, family=f.SR_FAMILY)
    pats = [r"(?i)password\s*=\s*\S+", r"bsa_[A-Za-z0-9_-]{43}"]
    with f.app(server) as c:
        a = f.make_agent(c).agent_id
    with f.setting(server, "redaction_patterns", pats):
        out = scan(db, pol, {"agents": [str(a).upper()]})
    with f.app(server) as c:
        (j,) = f.jobs_of_scan(c, out.scan_id)
    p = j["payload"]
    assert list(sorted(p)) == sorted(
        ["job_id", "agent_id", "kind", "pickup_by", "plugins", "redaction_patterns"]
    )
    schemas.ComplianceJob.model_validate(p)
    assert p == f.payload_of(j["job_id"], a, NOW, defs, pats)
    assert p["pickup_by"].endswith("Z") and "." not in p["pickup_by"]
    assert j["pickup_by"] == NOW + timedelta(hours=24)

    def keys(x: Any) -> set[str]:
        if isinstance(x, dict):
            return set(x) | {k for v in x.values() for k in keys(v)}
        if isinstance(x, list):
            return {k for v in x for k in keys(v)}
        return set()

    assert not keys(p) & {
        "operator",
        "expected",
        "expected_result",
        "eval_spec",
        "name",
    }
    spec = parse_eval_spec(j["eval_spec"])
    assert [e.plugin_uuid for e in spec.plugins] == [d.plugin_uuid for d in defs]
    first = spec.plugins[0]
    assert (first.name, first.operator, first.expected) == (
        "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed",
        "equals",
        "install ok installed",
    )


# ------------------------------------------------------------ CHK-M9-158


def test_unstorable_text_refuses_the_whole_scan(
    server: PgServer, db: AppDatabase, cat: f.Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-209 (4), #125 (g): a snapshot holding U+0000 (or a lone surrogate)
    in execute, name, expected or a pattern → build.UnstorableText with a
    fixed message, and nothing is written. The catalog cannot hold such text,
    so the snapshot is replaced here."""
    pol = cat.policy(1)
    with f.app(server) as c:
        a = f.make_agent(c).agent_id
    real = scan_queue.policy_snapshot
    for field, bad in (
        ("execute", "echo a\x00b"),
        ("display_name", "n\ud800"),
        ("expected", "e\x00"),
    ):

        def poisoned(conn: Any, pid: int, field: str = field, bad: str = bad) -> Any:
            snap = real(conn, pid)
            assert snap is not None
            changed: dict[str, Any] = {field: bad}
            return replace(snap, plugins=[replace(snap.plugins[0], **changed)])

        monkeypatch.setattr(scan_queue, "policy_snapshot", poisoned)
        with f.app(server) as c:
            before = f.counts(c)
        with pytest.raises(build.UnstorableText) as exc:
            scan(db, pol, {"agents": [str(a)]})
        assert bad not in str(exc.value)
        with f.app(server) as c:
            assert f.counts(c) == before
    monkeypatch.setattr(scan_queue, "policy_snapshot", real)


# ------------------------------------------------------------ CHK-M9-159, -160


def test_m8_host_counts_and_commands_on_an_m9_scan(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-209 (5), REQ-212 (2): M8's host_counts runs on a scan queued by M9
    (its SQL reads the payload M9 composes) and counts every plugin as not
    run; every execute of every job equals the execute of an active plugin
    of the scanned policy at queue time."""
    pol = cat.policy(4)
    with f.app(server) as c:
        ag = sorted(f.make_agent(c).agent_id for _ in range(3))
    out = scan(db, pol, {"agents": [str(x) for x in ag]})
    with f.app(server) as c:
        counts = host_counts(c, out.scan_id)
        jobs = f.jobs_of_scan(c, out.scan_id)
        active = dict(
            c.execute(
                "SELECT pl.plugin_uuid::text, pl.execute FROM policy_plugin pp"
                " JOIN plugin pl ON pl.plugin_uuid = pp.plugin_uuid"
                " WHERE pp.policy_id = %s"
                " AND pl.state = 'active'",
                (pol.policy_id,),
            ).fetchall()
        )
    assert [(h.agent_id, h.passed, h.failed, h.errors, h.not_run) for h in counts] == [
        (x, 0, 0, 0, 4) for x in ag
    ]
    for j in jobs:
        for item in j["payload"]["plugins"]:
            assert active[item["plugin_uuid"]] == item["execute"]


# ------------------------------------------------------------ CHK-M9-161


def test_scan_create_entry_and_the_all_hosts_api_token_alert(
    server: PgServer, db: AppDatabase, cat: f.Catalog
) -> None:
    """REQ-227 (1), (2), TS §8.4 L1290, #129 (a), (b), CHK-M9-366: one
    scan.create entry with exactly the #129 (a) detail keys; {"all": true}
    queued with an API token is the alert itself (detail.alert true, the
    kind) and bitscan_alerts_total{kind} grows after commit; a session, a tag
    target with a token, and a scheduled all-hosts scan raise none; a rolled
    back queue leaves no entry and no count."""
    pol = cat.policy(1)
    tag = f.new_tag()
    with f.app(server) as c:
        f.make_agent(c, tags=[tag])
        mark = f.last_audit(c)
    base = alerts()
    s1 = scan(
        db, pol, {"all": True}, via_api_token=True, actor="user:12", requested_by=12
    )
    assert alerts() == base + 1
    s2 = scan(db, pol, {"all": True}, via_api_token=False)
    s3 = scan(db, pol, {"tags": [tag]}, via_api_token=True)
    s4 = scan(
        db,
        pol,
        {"all": True},
        trigger="scheduled",
        schedule_id=None,
        requested_by=None,
        actor="system",
        via_api_token=False,
    )
    assert alerts() == base + 1
    with f.app(server) as c:
        es = f.audit_after(c, mark)
    assert [(e["action"], e["target"]) for e in es] == [
        ("scan.create", f"scan:{s.scan_id}") for s in (s1, s2, s3, s4)
    ]
    first = es[0]["detail"]
    assert first["alert"] is True and KIND in (
        first.get("alert_kind"),
        first.get("kind"),
    )
    assert DETAIL_KEYS <= set(first)
    assert {first[k] for k in ("trigger", "target_kind")} == {"manual", "all"}
    for e in es[1:]:
        assert set(e["detail"]) == DETAIL_KEYS and e["detail"].get("alert") is None
    assert es[0]["actor"] == "user:12" and es[3]["actor"] == "system"
    assert es[3]["detail"]["trigger"] == "scheduled"
    assert es[1]["detail"]["policy_version"] == pol.version
    with f.app(server) as c:
        mark = f.last_audit(c)
    with pytest.raises(RuntimeError), db.transaction() as tx:
        queue.queue_scan(
            tx,
            policy_id=pol.policy_id,
            target=parse_target({"all": True}),
            trigger="manual",
            schedule_id=None,
            requested_by=1,
            actor="user:1",
            via_api_token=True,
            now=NOW,
        )
        raise RuntimeError("rolled back by the caller")
    assert alerts() == base + 1
    with f.app(server) as c:
        assert f.audit_after(c, mark) == []
