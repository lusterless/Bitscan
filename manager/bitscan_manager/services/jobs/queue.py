"""Queue a scan (TS §2.3 L133, §3.3 L213, §4.4 L555–L560, L566, §4.1 L530,
§4.3 L547, L550, §8.4 L1290; REQ-209, REQ-211, REQ-212, REQ-227; open
questions #3, #18, #122 (f), #125, #129 (a), (b); design note D1).

One scan, inside the caller's transaction: the per-policy queue lock, the
policy row FOR SHARE and one snapshot statement, the refusals, the job parts
built from the snapshot's active plugins only, the target resolved, the scan
row, every job in one INSERT, the older queued jobs of the policy for those
agents cancelled, and one `scan.create` entry. That entry is the
`all_hosts_scan_api_token` alert when `{"all": true}` is queued with an API
token. Every refusal raises before anything is written, so the caller's
rollback leaves nothing. No argument carries command text: `execute` comes
only from the snapshot (REQ-212).

A new scan's jobs are all `queued`, so its derived state is the inserted
`queued` (#127 (f)); nothing more is derived here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from bitscan_manager.repositories import scan_queue
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Tx
from bitscan_manager.services.agents.versions import compare
from bitscan_manager.services.jobs import build, cmax
from bitscan_manager.services.jobs.targets import Target, stored_target
from bitscan_manager.services.scheduler.inventory import PICKUP_WINDOW
from bitscan_manager.services.settings import read_settings
from bitscan_manager.services.users import TxAudit

ALERT_KIND = "all_hosts_scan_api_token"  # #129 (b)


class PolicyNotFound(Exception):
    """No policy has this id (404)."""


class PolicyDisabled(Exception):
    """The policy is disabled (409, TS §4.4 L559)."""


class PolicyDeleted(Exception):
    """The policy is deleted (409, #122 (f))."""


class PolicyHasNoPlugins(Exception):
    """The policy lists no active plugin (409, #125 (h))."""


class ClusterMaxProfile(Exception):
    """A ClusterMAX profile on the plugin path (409): it is run only by an
    admin's manual ClusterMAX scan (TS §4.4, owner decision 2026-11-23)."""


class NotScanners(Exception):
    """A ClusterMAX target holds an agent that does not report the scanner
    role or is older than 0.6.0 (409)."""


class KubeconfigUnusable(Exception):
    """The chosen kubeconfig does not exist or is deleted (409)."""


class TooManyScanners(Exception):
    """A kubeconfig scan has more than one scanner, or the target more than
    the cap (400)."""


class NoTargetAgents(Exception):
    """The target resolves to no eligible agent (422, #3)."""


@dataclass(frozen=True, slots=True)
class ScanQueued:
    scan_id: UUID
    state: Literal["queued"]
    policy_version: int
    jobs: int


def queue_scan(
    tx: Tx,
    *,
    policy_id: int,
    target: Target,
    trigger: Literal["manual", "scheduled"],
    schedule_id: int | None,
    requested_by: int | None,
    actor: str,
    via_api_token: bool,
    now: datetime,
) -> ScanQueued:
    """Queue one scan of `policy_id` for `target` (design note D1). Raises
    one of the refusals above, or `build.UnstorableText` (500, #125 (g)),
    before any write."""
    conn = tx.conn
    scan_queue.lock_policy_queue(conn, policy_id)
    snapshot = scan_queue.policy_snapshot(conn, policy_id)
    if snapshot is None:
        raise PolicyNotFound
    if snapshot.deleted:
        raise PolicyDeleted
    if snapshot.status != "enabled":
        raise PolicyDisabled
    if not snapshot.plugins:
        raise PolicyHasNoPlugins
    if scan_queue.policy_family(conn, policy_id) == cmax.FAMILY:
        raise ClusterMaxProfile
    patterns = read_settings(SettingsRepo(conn)).redaction_patterns
    built = build.plugins_and_spec(snapshot.plugins, patterns)
    resolved = scan_queue.resolve_agents(conn, target.kind, target.agents, target.tags)
    if not resolved:
        raise NoTargetAgents
    scan_id = scan_queue.insert_scan(
        conn,
        policy_id=policy_id,
        policy_version=snapshot.version,
        trigger=trigger,
        schedule_id=schedule_id,
        target_json=stored_target(target, resolved),
        requested_by=requested_by,
        created_at=now,
    )
    inserted = scan_queue.insert_jobs(
        conn,
        scan_id=scan_id,
        policy_id=policy_id,
        agent_ids=resolved,
        job_ids=[uuid4() for _ in resolved],
        created_at=now,
        pickup_by=now + PICKUP_WINDOW,
        pickup_text=build.pickup_text(now),
        plugins_json=built.plugins_json,
        patterns=built.patterns,
        eval_spec_json=built.eval_spec_json,
    )
    jobs = inserted.queued + inserted.already_running
    cancelled = scan_queue.cancel_older_queued(
        conn, policy_id=policy_id, agent_ids=resolved, new_scan_id=scan_id, now=now
    )
    detail = {
        "policy_id": policy_id,
        "policy_version": snapshot.version,
        "trigger": trigger,
        "schedule_id": schedule_id,
        "target_kind": target.kind,
        "jobs": jobs,
        "cancelled_older": len(cancelled),
        "already_running": inserted.already_running,
    }
    audit = TxAudit(PgAuditRepo(conn), tx.on_commit)
    entry_target = f"scan:{scan_id}"
    if target.kind == "all" and via_api_token:
        audit.alert(ALERT_KIND, actor, "scan.create", entry_target, detail)
    else:
        audit.audit(actor, "scan.create", entry_target, detail)
    return ScanQueued(scan_id, "queued", snapshot.version, jobs)


def is_clustermax(tx: Tx, policy_id: int) -> bool:
    return scan_queue.policy_family(tx.conn, policy_id) == cmax.FAMILY


def _is_scanner(candidate: scan_queue.ScannerCandidate) -> bool:
    version = candidate.agent_version
    return (
        cmax.SCANNER_HELPER in candidate.runner_helpers
        and version[:1].isdigit()
        and compare(version, cmax.SCANNER_SINCE) >= 0
    )


def queue_cluster_scan(
    tx: Tx,
    *,
    policy_id: int,
    target: Target,
    options: cmax.Options,
    requested_by: int,
    actor: str,
    now: datetime,
) -> ScanQueued:
    """One manual ClusterMAX scan (TS §3.8, §4.4): one fixed cluster_audit job
    per scanner. Every refusal raises before any write."""
    conn = tx.conn
    scan_queue.lock_policy_queue(conn, policy_id)
    snapshot = scan_queue.policy_snapshot(conn, policy_id)
    if snapshot is None:
        raise PolicyNotFound
    if snapshot.deleted:
        raise PolicyDeleted
    if snapshot.status != "enabled":
        raise PolicyDisabled
    if scan_queue.policy_family(conn, policy_id) != cmax.FAMILY:
        raise PolicyNotFound
    checks = cmax.checks([(p.plugin_uuid, p.execute) for p in snapshot.plugins])
    if not checks:
        raise PolicyHasNoPlugins
    resolved = scan_queue.resolve_agents(conn, target.kind, target.agents, target.tags)
    if not resolved:
        raise NoTargetAgents
    if len(resolved) > cmax.MAX_SCANNERS or (
        options.kubeconfig_id is not None and len(resolved) != 1
    ):
        raise TooManyScanners
    candidates = scan_queue.scanner_candidates(conn, resolved)
    if len(candidates) != len(resolved) or not all(map(_is_scanner, candidates)):
        raise NotScanners
    if options.kubeconfig_id is not None and not scan_queue.kubeconfig_is_usable(
        conn, options.kubeconfig_id
    ):
        raise KubeconfigUnusable
    graded = {c.plugin_uuid for c in checks}
    patterns = read_settings(SettingsRepo(conn)).redaction_patterns
    built = build.plugins_and_spec(
        [p for p in snapshot.plugins if p.plugin_uuid in graded], patterns
    )
    scan_id = scan_queue.insert_cluster_scan(
        conn,
        policy_id=policy_id,
        policy_version=snapshot.version,
        target_json=stored_target(target, resolved),
        clustermax=options.stored(),
        requested_by=requested_by,
        created_at=now,
    )
    job_payload = {
        "target": options.target,
        "kubeconfig": options.kubeconfig_id is not None,
        "vars": dict(options.vars),
        "checks": [
            {"plugin_uuid": str(c.plugin_uuid), "check_id": c.check_id} for c in checks
        ],
    }
    jobs = scan_queue.insert_cluster_jobs(
        conn,
        scan_id=scan_id,
        agent_ids=resolved,
        job_ids=[uuid4() for _ in resolved],
        created_at=now,
        pickup_by=now + PICKUP_WINDOW,
        pickup_text=build.pickup_text(now),
        cmax_json=job_payload,
        patterns=built.patterns,
        eval_spec_json=built.eval_spec_json,
    )
    TxAudit(PgAuditRepo(conn), tx.on_commit).audit(
        actor,
        "scan.create",
        f"scan:{scan_id}",
        {
            "policy_id": policy_id,
            "policy_version": snapshot.version,
            "trigger": "manual",
            "target_kind": target.kind,
            "jobs": jobs,
            "clustermax": {
                "target": options.target,
                "kubeconfig_id": options.kubeconfig_id,
                "vars": dict(options.vars),
            },
        },
    )
    return ScanQueued(scan_id, "queued", snapshot.version, jobs)
