"""Import store: its types and the write half (SR §3.6; TS §4.1 L519-L524,
§4.3 L548-L550; open questions #14, #21, #100 (a), #104, #106), per
work/plans/TASK-151.md. The decision half (`decide`, `check_ownership`,
`is_unchanged`) is in store_decide, which imports from here, never the reverse.

`apply` runs in the caller's transaction or savepoint, under the catalog lock
the caller holds. Nothing here commits, rolls back, locks the catalog, writes
audit entries or touches files. A policy row is never deleted: a displaced
policy is soft-deleted (#106).
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg

from bitscan_manager.repositories import catalog, catalog_admin, catalog_plugins
from bitscan_manager.repositories.catalog import PolicyRow, PolicyValues
from bitscan_manager.repositories.catalog_plugins import PluginValues
from bitscan_manager.services.importer.alerts import ChangeReason
from bitscan_manager.services.importer.model import Finding

type Conn = psycopg.Connection[Any]
type Case = Literal[
    "update", "rename", "move_server", "move_upload", "revive", "insert", "rejected"
]
_UPLOADED = "uploaded/"
_DELETED = "deleted/"


@dataclass(frozen=True, slots=True)
class CandidatePlugin:
    plugin_uuid: UUID
    line: int  # line of <PluginId>
    plugin_name: str
    control_ref: str | None
    plugin_description: str
    execute: str  # trimmed
    execute_sha256: str  # SHA-256 of the trimmed execute, UTF-8
    operator: str  # lowercase, one of the 14
    expected_result: str  # trimmed
    timeout_s: int  # 1..600, default 60


@dataclass(frozen=True, slots=True)
class Candidate:
    """A file with no Reject finding left, values trimmed and normalised."""

    policy_name: str
    policy_name_line: int
    policy_description: str
    file_status: Literal["enabled", "disabled"]
    family_name: str
    format_version: str
    plugins: tuple[CandidatePlugin, ...]  # document order


@dataclass(frozen=True, slots=True)
class RuleId:
    plugin_uuid: UUID
    line: int  # line of <PluginId>
    index: int  # 1-based Plugin position, for the #105 (g) path


@dataclass(frozen=True, slots=True)
class RuleKeys:
    """The database-rule inputs, built whenever the structure passed."""

    policy_name: str | None  # None if PolicyName itself is invalid
    policy_name_line: int
    plugin_ids: tuple[RuleId, ...]  # the valid, distinct ids, document order


@dataclass(frozen=True, slots=True)
class Target:
    kind: Literal["server", "upload"]
    source_file: str | None  # server: relative to the bits folder; upload: None
    file_sha256: str

    def __post_init__(self) -> None:
        if (self.kind == "server") != (self.source_file is not None):
            raise ValueError("a server target needs source_file; an upload none")
        # A server-folder file sits in the folder itself (no subfolders), so
        # uploaded/ and deleted/ never reach the server rows of decide (r3).
        if self.source_file is not None and "/" in self.source_file:
            raise ValueError("a server target's source_file has no folder part")


class PolicyManagedOnServer(Exception):
    """An upload names a live policy whose file is in the server folder."""

    def __init__(self, policy_id: int) -> None:
        super().__init__("policy_managed_on_server")
        self.policy_id = policy_id


@dataclass(frozen=True, slots=True)
class Decision:
    case: Case
    policy_id: int | None  # the policy this file becomes; None for insert
    displaced_id: int | None  # policy X that loses the file, deleted on apply
    old: PolicyRow | None  # the locked row before the change
    findings: tuple[Finding, ...] = ()  # BIT007 only


@dataclass(frozen=True, slots=True)
class ChangedExecute:
    plugin_uuid: UUID
    plugin_name: str
    execute: str
    execute_sha256: str
    reason: ChangeReason


@dataclass(frozen=True, slots=True)
class StoreResult:
    policy_id: int
    policy_name: str
    version: int
    plugins_added: int
    plugins_updated: int
    plugins_retired: int
    changed_executes: tuple[ChangedExecute, ...]
    renamed_from: str | None
    moved_from: str | None  # previous source_file on a move
    revived: bool
    reenabled: bool  # effective policy_status went disabled -> enabled
    deleted_policy_ids: tuple[int, ...]  # displaced policies soft-deleted here
    remove_after_commit: tuple[str, ...]  # relative paths, after commit
    source_file: str


def in_server_folder(source_file: str) -> bool:
    """A server-folder source_file: neither uploaded/ nor deleted/."""
    return not source_file.startswith((_UPLOADED, _DELETED))


def apply(
    conn: Conn, decision: Decision, cand: Candidate, target: Target, now: datetime
) -> StoreResult:
    """SR §3.6 steps 1-5 for a decided, non-rejected file (plan §3.4).
    Raises only on a database error or a row that vanished under the lock."""
    if decision.case == "rejected":
        raise ValueError("a rejected decision cannot be applied")
    # Prior plugin state, read before step 1: the displaced delete retires X's
    # plugins, which Y may take over while they are still live (#100 (a)).
    uuids = [p.plugin_uuid for p in cand.plugins]
    before = catalog_plugins.current_plugins(conn, uuids)
    was_retired = catalog_plugins.retired_among(conn, uuids)
    deleted: tuple[int, ...] = ()
    if decision.displaced_id is not None:
        if catalog_admin.soft_delete_effects(conn, decision.displaced_id, now) is None:
            raise LookupError("displaced policy is gone under the lock")
        deleted = (decision.displaced_id,)
    family_id = catalog.upsert_family(conn, cand.family_name, now)
    if decision.policy_id is None:
        policy_id = catalog.next_policy_id(conn)
    else:
        policy_id = decision.policy_id
    source_file = target.source_file or f"{_UPLOADED}policy-{policy_id}.bit"
    values = PolicyValues(
        policy_name=cand.policy_name,
        policy_description=cand.policy_description,
        file_status=cand.file_status,
        family_id=family_id,
        format_version=cand.format_version,
        source_file=source_file,
        source_sha256=target.file_sha256,
    )
    if decision.case == "insert":
        row: PolicyRow | None = catalog.insert_policy(conn, policy_id, values, now)
    else:
        row = catalog.update_policy(conn, policy_id, values, now)
    if row is None:
        raise LookupError("policy row is gone under the lock")

    written = catalog_plugins.upsert_plugins(
        conn,
        [_plugin_values(p) for p in cand.plugins],
        family_id=family_id,
        owner_policy_id=policy_id,
        now=now,
    )
    added = sum(1 for _, inserted in written if inserted)
    catalog_plugins.replace_membership(conn, policy_id, uuids)
    retired = catalog_plugins.retire_unreferenced(conn, now)

    old = decision.old
    moved = decision.case in ("move_server", "move_upload")
    return StoreResult(
        policy_id=policy_id,
        policy_name=row.policy_name,
        version=row.version,
        plugins_added=added,
        plugins_updated=len(written) - added,
        plugins_retired=len(retired),
        changed_executes=tuple(
            ChangedExecute(p.plugin_uuid, p.plugin_name, p.execute, p.execute_sha256, r)
            for p in cand.plugins
            if (r := _reason(p, before, was_retired, decision.case == "revive"))
        ),
        renamed_from=old.policy_name if old and decision.case == "rename" else None,
        moved_from=old.source_file if old and moved else None,
        revived=decision.case == "revive",
        reenabled=old is not None
        and old.policy_status == "disabled"
        and row.policy_status == "enabled",
        deleted_policy_ids=deleted,
        remove_after_commit=(
            (old.source_file,) if old and decision.case == "move_upload" else ()
        ),
        source_file=row.source_file,
    )


def _reason(
    p: CandidatePlugin,
    before: Mapping[UUID, str],
    was_retired: AbstractSet[UUID],
    revive: bool,
) -> ChangeReason | None:
    """Why the plugin's command goes live with this import, the first that
    applies (#100 (a) widened, 2026-10-27); None when it was live unchanged."""
    stored = before.get(p.plugin_uuid)
    if stored is None:
        return "new"
    if stored != p.execute_sha256:
        return "changed"
    if revive or p.plugin_uuid in was_retired:
        return "reactivated"
    return None


def _plugin_values(p: CandidatePlugin) -> PluginValues:
    return PluginValues(
        plugin_uuid=p.plugin_uuid,
        plugin_name=p.plugin_name,
        control_ref=p.control_ref,
        plugin_description=p.plugin_description,
        execute=p.execute,
        execute_sha256=p.execute_sha256,
        timeout_s=p.timeout_s,
        operator=p.operator,
        expected_result=p.expected_result,
    )
