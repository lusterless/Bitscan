"""Import store, the decision half (SR §3.6 step 2, §4.1 BIT007 and BIT015;
TS §4.1 L522-L524, §4.3 L549-L550; open questions #99 (e), #106), per
work/plans/TASK-151.md §3.1-§3.3. `store.apply` writes what `decide` chose.

Runs in the caller's transaction, under the catalog lock the caller holds.
It only reads and locks rows; nothing here writes, commits or audits.
"""

from __future__ import annotations

from collections.abc import Callable

from bitscan_manager.repositories import catalog
from bitscan_manager.services.importer.model import Code, Finding, plugin_path, quote
from bitscan_manager.services.importer.store import (
    Conn,
    Decision,
    PolicyManagedOnServer,
    RuleKeys,
    Target,
    in_server_folder,
)


def decide(
    conn: Conn, rules: RuleKeys, target: Target, file_exists: Callable[[str], bool]
) -> Decision:
    """Lock the candidate rows (by name, then by file) and choose the case
    (plan §3.1). Raises PolicyManagedOnServer for the #99 (e) upload."""
    name = rules.policy_name
    if name is None:
        return Decision("rejected", None, None, None)
    byname = catalog.policy_by_name_for_update(conn, name)
    if target.source_file is None:  # an upload
        if byname is None:
            return Decision("insert", None, None, None)
        if byname.deleted_at is not None:
            return Decision("revive", byname.policy_id, None, byname)
        if in_server_folder(byname.source_file):
            raise PolicyManagedOnServer(byname.policy_id)
        return Decision("update", byname.policy_id, None, byname)
    here = target.source_file
    byfile = catalog.policy_by_source_file_for_update(conn, here)
    if byfile is not None and byfile.deleted_at is not None:
        byfile = None
    if byname is None:
        if byfile is not None:
            return Decision("rename", byfile.policy_id, None, byfile)
        return Decision("insert", None, None, None)
    if byname.deleted_at is None and byname.source_file == here:
        return Decision("update", byname.policy_id, None, byname)
    # The natural key wins: X (the file's other policy) loses the file (#106).
    displaced = None if byfile is None else byfile.policy_id
    if byname.deleted_at is not None:
        return Decision("revive", byname.policy_id, displaced, byname)
    if not in_server_folder(byname.source_file):
        return Decision("move_upload", byname.policy_id, displaced, byname)
    if file_exists(byname.source_file):
        bit007 = Finding(
            rules.policy_name_line,
            "Policy/PolicyName",
            Code.BIT007,
            f"PolicyName {quote(name)} is already imported from"
            f" {quote(byname.source_file)}.",
        )
        return Decision("rejected", byname.policy_id, None, byname, (bit007,))
    return Decision("move_server", byname.policy_id, displaced, byname)


def check_ownership(
    conn: Conn, decision: Decision, rules: RuleKeys
) -> tuple[Finding, ...]:
    """BIT015 for every id whose owner is another live policy that still
    lists it (plan §3.2). The deciding and the displaced policy never count.
    With no valid PolicyName the store adds no finding (plan §3.1)."""
    if rules.policy_name is None or not rules.plugin_ids:
        return ()
    owners = {
        o.plugin_uuid: o
        for o in catalog.owners_of(conn, [r.plugin_uuid for r in rules.plugin_ids])
    }
    ours = {decision.policy_id, decision.displaced_id}
    findings: list[Finding] = []
    for rule in rules.plugin_ids:
        owner = owners.get(rule.plugin_uuid)
        if owner is None or owner.owner_id in ours:
            continue
        if owner.owner_deleted or not owner.owner_lists:
            continue  # claimed by the importing policy
        findings.append(
            Finding(
                rule.line,
                plugin_path(rule.index, "PluginId"),
                Code.BIT015,
                f"PluginId {rule.plugin_uuid} belongs to policy"
                f" {quote(owner.owner_name)}.",
            )
        )
    return tuple(findings)


def is_unchanged(decision: Decision, target: Target) -> bool:
    """The `auto` skip: same live policy, same hash, and for a server target
    the same file (plan §3.3). For an upload target the caller (TASK-156) has
    already matched the file to this live policy's source_file (r3)."""
    old = decision.old
    return (
        decision.case == "update"
        and old is not None
        and old.deleted_at is None
        and (target.source_file is None or old.source_file == target.source_file)
        and old.source_sha256 == target.file_sha256
    )
