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
from bitscan_manager.services.jobs import build
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
