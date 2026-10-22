"""Alerts (TS §8.4 L1289-L1291; #50).

An alert is an audit entry whose detail holds "alert": true and "alert_kind",
written in the caller's transaction so it reaches the sink like any entry.
bitscan_alerts_total{kind} rises only after that transaction commits.
"""

from collections.abc import Callable, Mapping
from typing import Final

from bitscan_manager.services.audit.chain import AppendedEntry, AuditRepo, append_entry
from bitscan_manager.services.audit.metrics import ALERTS_TOTAL

# The M2 alert kinds (#50 (c)).
ALERT_KINDS: Final = frozenset(
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
