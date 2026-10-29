"""Compliance profiles: list, detail and the admin status change (TS §4.3
L546-L548, §6.2 L1100-L1102, §8.4 L1290; REQ-168, REQ-169; open questions #9,
#98, #101, #104 (d)).

Reads and status only: no function here edits a plugin or a command, queues a
job or touches files. The list never holds deleted policies (#9); the detail
returns a deleted one with `deleted_at`. Every PATCH writes one
`policy.status_change` entry, the `policy_reenabled` alert when the effective
status goes from disabled to enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import psycopg

from bitscan_manager.repositories import catalog_admin
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog_admin import ProfileDetail, ProfileItem
from bitscan_manager.runtime import Tx
from bitscan_manager.services.importer.alerts import (
    PolicyStatus,
    emit,
    status_change,
)
from bitscan_manager.services.importer.delete import (
    PolicyAlreadyDeleted,
    PolicyNotFound,
)

type Conn = psycopg.Connection[Any]
# REQ-168: an admin override to one status, or back to the file's status.
type StatusChange = Literal["enabled", "disabled", "clear_override"]

__all__ = [
    "PolicyAlreadyDeleted",
    "PolicyNotFound",
    "StatusChange",
    "change_status",
    "get_profile",
    "list_profiles",
]


def list_profiles(
    conn: Conn,
    *,
    limit: int,
    status: PolicyStatus | None,
    after: tuple[str, int] | None,
) -> list[ProfileItem]:
    """Non-deleted policies in (policy_name, policy_id) order, by effective
    status if given, keyset after `after` (#98 (a))."""
    return catalog_admin.list_page(conn, limit, status, after)


def get_profile(conn: Conn, policy_id: int) -> ProfileDetail:
    """The policy with its plugins in sort_order (#98 (b)), deleted or not."""
    found = catalog_admin.detail(conn, policy_id)
    if found is None:
        raise PolicyNotFound()
    return found


def _status(value: str) -> PolicyStatus:
    if value == "enabled":
        return "enabled"
    if value == "disabled":
        return "disabled"
    raise ValueError("not a policy_status")  # unreachable: the enum has two


def change_status(
    tx: Tx, policy_id: int, change: StatusChange, *, actor: str, now: datetime
) -> ProfileItem:
    """REQ-168 on the row locked here (builder checklist 9), with its audit
    entry in the same transaction. A concurrent import waits on the row lock
    and keeps the override (its UPDATE reads status_overridden itself)."""
    state = catalog_admin.lock(tx.conn, policy_id)
    if state is None:
        raise PolicyNotFound()
    if state.deleted_at is not None:
        raise PolicyAlreadyDeleted()
    if change == "clear_override":
        changed = catalog_admin.clear_override(tx.conn, policy_id, now)
    else:
        changed = catalog_admin.set_status(tx.conn, policy_id, change, now)
    item = catalog_admin.item(tx.conn, policy_id)
    if not changed or item is None:  # unreachable under the row lock
        raise LookupError("policy changed under its row lock")
    event = status_change(
        policy_id=policy_id,
        policy_name=item.policy_name,
        before=_status(state.policy_status),
        after=_status(item.policy_status),
        status_overridden=item.status_overridden,
        by="patch",
    )
    emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor)
    return item
