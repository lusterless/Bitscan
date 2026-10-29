# TASK-152 IMPL: policy delete service

Implementer: impl-manager-m7c. REQ-167. Risk high (importer; two approvals). Spec: TS §4.3 L550 (soft delete, its effects, 409 for server-folder policies, revival later), TS §4.1 L524-L526 (one folder per policy; the catalog lock spans the file deletion), TS §8.4 L1290 (delete alerts), TS §5.2 grants (no DELETE on `policy`); open questions #14, #98 (e), #101, #103, #104. No plan file; built from the task row and the W1 and W2 interfaces.

## Files

| File | Non-blank lines | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/delete.py` (new) | 115 | Below. |

No other file changed. It uses `catalog.policy_by_id_for_update` (TASK-148), `catalog_admin.soft_delete_effects` (TASK-150), `catalog_lock` (TASK-147), `PgAuditRepo`, TASK-153's `deleted` and `emit`, and TASK-151's `PolicyManagedOnServer` and `in_server_folder`.

## Interface

- `PolicyNotFound` and `PolicyAlreadyDeleted` are exceptions; the TASK-163 route maps them to 404 `not_found` and 409 `conflict` (#98 (e)). A server-folder policy raises `store.PolicyManagedOnServer` (409 `policy_managed_on_server`), the exception the upload path also uses.
- `DeleteResult(policy_id, policy_name, source_file, effects: DeleteEffects, remove_after_commit)` is frozen. `source_file` is the file before the delete; `remove_after_commit` is `("uploaded/policy-<id>.bit",)` for an uploaded policy, else `()`.
- `delete_in_tx(tx, policy_id, *, actor, reason, now, refuse_server_folder=False) -> DeleteResult` is the no-lock core. It runs in the caller's transaction or savepoint:
  - It locks the row (`policy_by_id_for_update`) and decides on that locked state (builder checklist 9). Unknown raises `PolicyNotFound`; already deleted raises `PolicyAlreadyDeleted`; `refuse_server_folder` with a server-folder `source_file` raises `PolicyManagedOnServer`.
  - It then calls `soft_delete_effects`. A `None` there is unreachable under the lock and raises `LookupError`.
  - It writes one `policy.delete` entry that is the `policy_deleted` alert (TASK-153 `deleted`, target `policy:<id>`, detail `{policy_id, policy_name, source_file, reason}`) through `emit` with `PgAuditRepo(tx.conn)` and `tx.on_commit`. The alert counter rises only on commit.
  - It does not touch files; the caller removes `remove_after_commit` after its commit. The watcher (TASK-156/159) and the rebuild (TASK-157) call it with `reason="file removed"` and the server folder allowed. In a rebuild savepoint, a rollback drops the entry and its hook with the savepoint.
- `delete_policy(db, policy_id, *, actor, clock, bits_dir) -> DeleteResult` is the route path:
  - It opens a session, takes `catalog_lock`, and runs one transaction: `delete_in_tx` with `reason="deleted through the API"` and `refuse_server_folder=True`.
  - After the commit, and **before** the lock is released (TS §4.1 L526), it calls `remove_after_commit`.
  - Any exception before the commit rolls the transaction back, so the row and the file are unchanged.
  - The TOTP-session, admin and sink-gate checks belong to the route (TASK-163, #1).
- `remove_after_commit(bits_dir, paths)` unlinks only paths of the exact form `uploaded/policy-<ASCII digits>.bit`, built under `bits_dir / "uploaded"`.
  - Any other path (`..`, a server file, a non-numeric id) is refused with one fixed log line.
  - A missing file is fine (`missing_ok`). Any other `OSError` is logged by type name only and left to the #103 integrity check, because the catalog has already committed.
  - TASK-154 can use it for `StoreResult.remove_after_commit` (`move_upload`).

## Choices for the reviewer

- The audit detail does not list the cancelled job ids or disabled schedule ids. They are in `DeleteResult.effects` for the caller, but TASK-153's `deleted` shape has no field for them.
- #102 (c) (ignore the watcher event the manager's own file deletion causes) is not here. `remove_after_commit` is the single place where the file goes, so TASK-159 or 160 can wrap or record it there.
- `delete_policy` takes the `SessionDatabase` and opens its own session, because the pool refuses nested sessions (TASK-147). TASK-160's `CatalogService.delete` calls it directly.

## Static gates (Windows, `manager/.venv`)

- `ruff check` and `ruff format --check` on delete.py: pass. There is no SQL in this module.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 263 source files.
- Smoke check with a temporary folder: `remove_after_commit` removed `uploaded/policy-7.bit`. It refused `uploaded/../keep.bit`, `keep.bit` and `uploaded/policy-x.bit` (one log line each), and ignored a missing `policy-8.bit`. `keep.bit` survived.

## For the tester (tester-m7, TP-M7-13, `manager/tests/test_policy_delete_pg.py`, PostgreSQL, temporary bits folder)

- REQ-167 (1): owner-written scans with jobs `queued`, `dispatched` and `running`, and two schedules. Call `delete_policy(db, id, actor="user:1", clock=fake, bits_dir=tmp)` with `tmp/uploaded/policy-<id>.bit` present.
- REQ-167 (2): a server-folder policy raises `PolicyManagedOnServer` and changes nothing.
- (5): after the delete, a new policy can claim its plugins (TASK-151 `check_ownership` gives no BIT015).
- (6): no statement deletes from `policy`.
- "A fault before commit leaves the row and the file": make `emit` or `PgAuditRepo.insert` raise, or plant a failing `on_commit`.
- "The core called inside another transaction rolls back with it": call `delete_in_tx` inside a transaction that then raises.
- `PolicyNotFound` and `PolicyAlreadyDeleted` are plain exceptions with no message.

## Revision 1 (impl-manager-m7, taking over delete.py; decisions 2026-10-28, "#102 (c) wiring")

`remove_after_commit` now records each removal in `OWN_CHANGES` (`services/importer/own_changes.py`, TASK-159), so the watcher drops the manager's own deletions (#102 (c)). The record is written **just before** the filesystem call, under the caller's catalog lock. Only `delete.py` changed: 1 import and 1 line.
- Each path that passes the existing `uploaded/policy-<n>.bit` check gets `OWN_CHANGES.removed(rel)` immediately before `unlink(missing_ok=True)`. A refused path is still skipped with its log line, and gets no record.
- Every caller gets the record with no change on its side: the delete route, the reconcile's deletion pass (TASK-156), the rebuild (TASK-157) and `import_one`'s move removals (TASK-154).
- Behaviour is otherwise unchanged. TASK-152 had the user's second approval, so it goes back to the user after re-test and re-review.
- **Gates:** `ruff check manager` and `ruff format --check manager` pass (295 files), and the CI mypy command gives Success (295 files).
- **For the tester:**
  - after `delete_policy` of an uploaded policy, `OWN_CHANGES.drop_removal("uploaded/policy-<id>.bit")` is True once, then False;
  - a server-folder path passed to `remove_after_commit` is refused and gets no record.
  - Plant: drop the record line → that row goes red.
