"""Catalog audit entries and alerts (TS §4.1 L530, §8.4 L1289-L1291; open
questions #23, #100, #101, #103).

Each builder returns the entry one catalog event writes: its #101 action,
target and detail, and its alert kind (None for a plain audit entry such as a
move). `emit` appends it in the caller's transaction, through `raise_alert`
when it is an alert, so a rollback leaves neither the entry nor its count.
Nothing here logs: details hold `Execute` text, which never goes to a log.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from uuid import UUID

from bitscan_manager.repositories.imports import Mode
from bitscan_manager.services.audit.alerts import raise_alert
from bitscan_manager.services.audit.chain import AppendedEntry, AuditRepo, append_entry
from bitscan_manager.services.audit.metrics import IMPORT_FAILURES, IMPORT_MODES
from bitscan_manager.services.importer.model import Finding

# TS §8.4 L1290, matched as case-insensitive substrings of the whole Execute
# (#100 (c)): a hint for the reader of the alert, not a control.
FLAG_WORDS: Final = ("shadow", ".ssh", ".pem", ".key", "token", "credentials")
INTEGRITY_LIST_MAX: Final = 100  # differences listed in one alert (#103)
TARGET_MAX: Final = 255  # audit_log.target VARCHAR(255) (TS §5.2)

type OnCommit = Callable[[Callable[[], None]], None]
type PolicyStatus = Literal["enabled", "disabled"]
type DeleteReason = Literal[
    "deleted through the API", "file removed", "file now holds another policy"
]
# #100 (a) as widened by the user (2026-10-27): new, a changed execute_sha256,
# or retired before this import and active after it (a revival included).
type ChangeReason = Literal["new", "changed", "reactivated"]


class ChangedExecute(Protocol):
    """A plugin whose command goes live on hosts with this import (#100 (a))."""

    @property
    def plugin_uuid(self) -> UUID: ...
    @property
    def plugin_name(self) -> str: ...
    @property
    def execute(self) -> str: ...
    @property
    def execute_sha256(self) -> str: ...
    @property
    def reason(self) -> ChangeReason: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: str
    target: str | None
    detail: Mapping[str, object]
    kind: str | None = None  # an M7 alert kind, or None for a plain entry


@dataclass(frozen=True, slots=True)
class Difference:
    """One failed #103 integrity check."""

    subject: str  # "policy:<id>", or a file path relative to the bits folder
    check: str


def flags(execute: str) -> list[str]:
    """The FLAG_WORDS found in `execute`, in FLAG_WORDS order."""
    text = execute.casefold()
    return [word for word in FLAG_WORDS if word in text]


def _target(policy_id: int) -> str:
    return f"policy:{policy_id}"


def _storable(text: str) -> str:
    """A path for jsonb: U+0000 and lone surrogates (an undecodable file
    name) become U+FFFD, so the entry cannot fail the transaction."""
    return "".join(
        "�" if ch == "\x00" or "\ud800" <= ch <= "\udfff" else ch for ch in text
    )


def imported(
    *,
    policy_id: int,
    policy_name: str,
    version: int,
    mode: Mode,
    file_sha256: str,
    source_file: str,
    plugins_added: int,
    plugins_updated: int,
    plugins_retired: int,
    renamed_from: str | None,
    revived: bool,
    changed_executes: Sequence[ChangedExecute],
) -> AuditEvent:
    """`policy.import`, the `policy_imported` alert: every changed Execute in
    full, each with its flags (#100 (b)); one entry per import (#100 (d))."""
    return AuditEvent(
        action="policy.import",
        target=_target(policy_id),
        kind="policy_imported",
        detail={
            "policy_id": policy_id,
            "policy_name": policy_name,
            "version": version,
            "mode": mode,
            "file_sha256": file_sha256,
            "source_file": _storable(source_file),
            "plugins_added": plugins_added,
            "plugins_updated": plugins_updated,
            "plugins_retired": plugins_retired,
            "renamed_from": renamed_from,
            "revived": revived,
            "changed_executes": [
                {
                    "plugin_uuid": str(change.plugin_uuid),
                    "plugin_name": change.plugin_name,
                    "execute": change.execute,
                    "execute_sha256": change.execute_sha256,
                    "reason": change.reason,
                    "flags": flags(change.execute),
                }
                for change in changed_executes
            ],
        },
    )


def rejected(
    *,
    import_id: int,
    mode: Mode,
    file_name: str,
    file_sha256: str,
    policy_id: int | None,
    findings: Sequence[Finding],
) -> AuditEvent:
    """`policy.import_rejected`, the `policy_import_rejected` alert, written
    with the `bit_import` row; the findings themselves stay in that row.
    Target: the matched policy, else the file name (#101)."""
    name = _storable(file_name)
    codes = list(dict.fromkeys(finding.code.value for finding in findings))
    return AuditEvent(
        action="policy.import_rejected",
        # The target column holds 255 characters; detail keeps the full name.
        target=_target(policy_id)
        if policy_id is not None
        else (name[:TARGET_MAX] or None),
        kind="policy_import_rejected",
        detail={
            "import_id": import_id,
            "mode": mode,
            "file_name": name,
            "file_sha256": file_sha256,
            "policy_id": policy_id,
            "finding_count": len(findings),
            "codes": codes,
        },
    )


def count_failure(on_commit: OnCommit, mode: Mode) -> None:
    """Add 1 to bitscan_import_failures_total{mode} when the rejected import's
    record transaction commits (#101)."""
    if mode not in IMPORT_MODES:
        raise ValueError("unknown import mode")
    on_commit(IMPORT_FAILURES.labels(mode=mode).inc)


def deleted(
    *, policy_id: int, policy_name: str, source_file: str, reason: DeleteReason
) -> AuditEvent:
    """`policy.delete`, the `policy_deleted` alert; `source_file` is the
    file the policy had before the delete (REQ-167)."""
    return AuditEvent(
        action="policy.delete",
        target=_target(policy_id),
        kind="policy_deleted",
        detail={
            "policy_id": policy_id,
            "policy_name": policy_name,
            "source_file": _storable(source_file),
            "reason": reason,
        },
    )


def moved(*, policy_id: int, from_file: str, to_file: str) -> AuditEvent:
    """`policy.move` (the server folder wins, or BIT007's move); not an alert."""
    return AuditEvent(
        action="policy.move",
        target=_target(policy_id),
        detail={"from": _storable(from_file), "to": _storable(to_file)},
    )


def status_change(
    *,
    policy_id: int,
    policy_name: str,
    before: PolicyStatus,
    after: PolicyStatus,
    status_overridden: bool,
    by: Literal["patch", "file"],
) -> AuditEvent:
    """`policy.status_change`; the `policy_reenabled` alert when the effective
    status goes from disabled to enabled, by PATCH or by an import (#101)."""
    reenabled = before == "disabled" and after == "enabled"
    return AuditEvent(
        action="policy.status_change",
        target=_target(policy_id),
        kind="policy_reenabled" if reenabled else None,
        detail={
            "policy_id": policy_id,
            "policy_name": policy_name,
            "from": before,
            "to": after,
            "status_overridden": status_overridden,
            "by": by,
        },
    )


def rebuilt(
    *,
    task_id: UUID,
    state: Literal["succeeded", "failed"],
    files_imported: int,
    files_rejected: int,
    deleted_policy_ids: Sequence[int],
    plugins_retired: int,
    removed_leftovers: Sequence[str],
) -> AuditEvent:
    """`bits.rebuild`, the `policy_rebuilt` alert, once when the task ends;
    the per-file outcomes are in `task.result` (#20, #23). `removed_leftovers`
    are the `uploaded/` files of deleted policies the rebuild removed (crash
    window ruling, 2026-10-27), relative paths in order."""
    return AuditEvent(
        action="bits.rebuild",
        target=f"task:{task_id}",
        kind="policy_rebuilt",
        detail={
            "task_id": str(task_id),
            "state": state,
            "files_imported": files_imported,
            "files_rejected": files_rejected,
            "deleted_policy_ids": list(deleted_policy_ids),
            "plugins_retired": plugins_retired,
            "removed_leftovers": [_storable(p) for p in removed_leftovers],
        },
    )


def integrity_failed(differences: Sequence[Difference]) -> AuditEvent:
    """`catalog.integrity_check`, the `catalog_integrity_failed` alert, with
    the first 100 differences and their total (#103). A clean catalog raises
    nothing, so an empty list is a caller error."""
    if not differences:
        raise ValueError("no differences: a clean catalog raises no alert")
    listed = differences[:INTEGRITY_LIST_MAX]
    return AuditEvent(
        action="catalog.integrity_check",
        target=None,
        kind="catalog_integrity_failed",
        detail={
            "difference_count": len(differences),
            "differences": [
                {"subject": _storable(d.subject), "check": d.check} for d in listed
            ],
        },
    )


def emit(
    repo: AuditRepo, on_commit: OnCommit, event: AuditEvent, *, actor: str
) -> AppendedEntry:
    """Append `event` in the caller's transaction. `actor` is `user:<id>`,
    `cli:root` or `system` (#101)."""
    if event.kind is None:
        return append_entry(
            repo,
            actor=actor,
            action=event.action,
            target=event.target,
            detail=event.detail,
        )
    return raise_alert(
        repo,
        on_commit,
        kind=event.kind,
        actor=actor,
        action=event.action,
        target=event.target,
        detail=event.detail,
    )
