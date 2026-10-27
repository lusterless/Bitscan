"""Policy delete (TS §4.3 L550, §4.1 L524-L526, §8.4 L1290; REQ-167; open
questions #14, #101, #104).

A delete is soft: `soft_delete_effects` sets `deleted_at` and
`source_file = deleted/<id>`, cancels queued compliance jobs, disables
schedules and retires the plugins; the uploaded file goes after the commit.
Each delete writes one `policy.delete` entry that is the `policy_deleted`
alert. `delete_in_tx` is the no-lock core (the watcher and rebuild call it
inside their own transaction or savepoint); `delete_policy` is the route's
path, which takes the catalog lock itself.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bitscan_manager.repositories import catalog, catalog_admin
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.catalog_admin import DeleteEffects
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.runtime import Clock, SessionDatabase, Tx
from bitscan_manager.services.importer.alerts import DeleteReason, deleted, emit
from bitscan_manager.services.importer.store import (
    PolicyManagedOnServer,
    in_server_folder,
)

log = logging.getLogger(__name__)
_UPLOADED = "uploaded/"


class PolicyNotFound(Exception):
    """No policy has this id (404 `not_found`, #98 (e))."""


class PolicyAlreadyDeleted(Exception):
    """The policy is already deleted (409 `conflict`, #98 (e))."""


@dataclass(frozen=True, slots=True)
class DeleteResult:
    policy_id: int
    policy_name: str
    source_file: str  # the file before the delete
    effects: DeleteEffects
    remove_after_commit: tuple[str, ...]  # the uploaded copy, relative path


def delete_in_tx(
    tx: Tx,
    policy_id: int,
    *,
    actor: str,
    reason: DeleteReason,
    now: datetime,
    refuse_server_folder: bool = False,
) -> DeleteResult:
    """The REQ-167 database effects and the alert, in the caller's
    transaction, decided on the row locked here. The caller holds the catalog
    lock and removes `remove_after_commit` after its commit. The route sets
    `refuse_server_folder` (409 `policy_managed_on_server`, TS §4.3 L550);
    a removed server file deletes its policy without it."""
    row = catalog.policy_by_id_for_update(tx.conn, policy_id)
    if row is None:
        raise PolicyNotFound()
    if row.deleted_at is not None:
        raise PolicyAlreadyDeleted()
    if refuse_server_folder and in_server_folder(row.source_file):
        raise PolicyManagedOnServer(policy_id)
    effects = catalog_admin.soft_delete_effects(tx.conn, policy_id, now)
    if effects is None:  # unreachable: the row is locked live above
        raise LookupError("policy changed under its row lock")
    event = deleted(
        policy_id=policy_id,
        policy_name=row.policy_name,
        source_file=row.source_file,
        reason=reason,
    )
    emit(PgAuditRepo(tx.conn), tx.on_commit, event, actor=actor)
    uploaded = row.source_file.startswith(_UPLOADED)
    return DeleteResult(
        policy_id=policy_id,
        policy_name=row.policy_name,
        source_file=row.source_file,
        effects=effects,
        remove_after_commit=(row.source_file,) if uploaded else (),
    )


def delete_policy(
    db: SessionDatabase, policy_id: int, *, actor: str, clock: Clock, bits_dir: Path
) -> DeleteResult:
    """`DELETE /policies/{id}`: under the catalog lock, one transaction, then
    the uploaded file is removed before the lock is released (TS §4.1 L526).
    A failure before the commit leaves the row and the file as they were."""
    with db.session() as session, catalog_lock(session):
        with session.transaction() as tx:
            result = delete_in_tx(
                tx,
                policy_id,
                actor=actor,
                reason="deleted through the API",
                now=clock.now(),
                refuse_server_folder=True,
            )
        remove_after_commit(bits_dir, result.remove_after_commit)
    return result


def remove_after_commit(bits_dir: Path, paths: Sequence[str]) -> None:
    """Remove committed-away upload copies (`uploaded/policy-<id>.bit` only;
    any other path is refused), through an `uploaded/` handle that follows no
    link ("Folder guard details" (2)). A failure, or an unreadable `uploaded/`,
    is logged and the copy left to the start-up integrity check (#103): the
    catalog has already committed."""
    # Imported here: uploads imports the pipeline, which imports this module.
    from bitscan_manager.services.importer.uploads import open_uploaded_dir

    names = []
    for rel in paths:
        name = rel.removeprefix(_UPLOADED)
        digits = name.removeprefix("policy-").removesuffix(".bit")
        if not (
            rel.startswith(_UPLOADED)
            and name == f"policy-{digits}.bit"
            and digits.isascii()
            and digits.isdigit()
        ):
            log.warning("upload removal skipped: not an upload path")
            continue
        names.append(name)
    if not names:
        return
    try:
        dir_fd = open_uploaded_dir(bits_dir / "uploaded")
    except OSError as exc:
        log.warning(
            "upload removal skipped: uploaded folder unreadable: %s", type(exc).__name__
        )
        return
    try:
        for name in names:
            try:
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("upload removal failed: %s", type(exc).__name__)
    finally:
        os.close(dir_fd)
