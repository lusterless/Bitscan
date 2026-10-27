"""Alerts (TS §8.4 L1289-L1291; #50, #71).

An alert is an audit entry whose detail holds "alert": true and "alert_kind",
written in the caller's transaction so it reaches the sink like any entry.
bitscan_alerts_total{kind} rises only after that transaction commits.
"""

from collections.abc import Callable, Mapping
from typing import Final

from bitscan_manager.services.audit.chain import AppendedEntry, AuditRepo, append_entry
from bitscan_manager.services.audit.metrics import ALERTS_TOTAL

# The M2 alert kinds (#50 (c)).
M2_ALERT_KINDS: Final = frozenset(
    {
        "api_token_created",
        "totp_enrolled",
        "totp_replaced",
        "totp_reset",
        "user_created",
        "role_granted",
        "admin_created",
        "audit_sink_unreachable",
        "login_failures",
        "token_check_failures",
    }
)
# The M3 alert kinds (#71): agent, enrolment, settings and fleet events.
M3_ALERT_KINDS: Final = frozenset(
    {
        "enrolment_token_risky",
        "enrolments_per_hour",
        "reenrolment_approved",
        "machine_id_mismatch",
        "token_reuse",
        "rotation_outside_window",
        "rotation_new_ip",
        "runner_helper_changed",
        "settings_changed",
        "redaction_default_removed",
        "clock_skew",
        "agents_offline",
        "job_queue_age",
        "inventory_stale",
        "new_packages_burst",
        "result_409_flood",
        "agent_auth_failures",
        "default_partition_rows",
    }
)
# The M7 alert kinds (#101): catalog events. A policy move is audited but is
# not an alert.
M7_ALERT_KINDS: Final = frozenset(
    {
        "policy_imported",
        "policy_import_rejected",
        "policy_deleted",
        "policy_rebuilt",
        "policy_reenabled",
        "catalog_integrity_failed",
    }
)
ALERT_KINDS: Final = M2_ALERT_KINDS | M3_ALERT_KINDS | M7_ALERT_KINDS

for _kind in sorted(ALERT_KINDS):
    ALERTS_TOTAL.labels(kind=_kind)  # every kind is exported, from zero


def raise_alert(
    repo: AuditRepo,
    on_commit: Callable[[Callable[[], None]], None],
    *,
    kind: str,
    actor: str,
    action: str,
    target: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> AppendedEntry:
    """Append the alert entry; on_commit is the transaction's hook registrar
    (Tx.on_commit), so a rollback leaves neither the entry nor the count."""
    if kind not in ALERT_KINDS:
        raise ValueError(f"unknown alert kind {kind!r}")
    extra = dict(detail or {})
    if "alert" in extra or "alert_kind" in extra:
        raise ValueError("detail must not set alert or alert_kind")
    entry = append_entry(
        repo,
        actor=actor,
        action=action,
        target=target,
        detail={"alert": True, "alert_kind": kind, **extra},
    )
    on_commit(ALERTS_TOTAL.labels(kind=kind).inc)
    return entry
