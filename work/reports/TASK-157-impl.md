# TASK-157 IMPL: rebuild service

Implementer: impl-manager-157. REQ-166. Risk high (importer, two approvals). Spec: TS §4.2 L540, §4.1 L524–L532, §4.3 L550, §5.2 `task`, §8.4 L1290; SR §3.6. Open questions #20, #23, #98 (g) (j), #103. Rulings (`work/decisions.md`): Crash window (and the lead's TASK-157 extension), Rebuild finishes interrupted uploads first, Stray files, Edited name, Folder guard (and details), the TASK-156 r3/r4 review carries.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/importer/rebuild.py` (new) | 258 physical lines, 227 non-blank, about 185 code lines |

No other file changed.

## Public API (for TASK-160 and TASK-166)

- `create_task(db: SessionDatabase, clock, actor: Actor) -> UUID` (rebuild.py:72): writes the `task` row (`rebuild`, `running`, `requested_by = actor.user_id`, NULL for the CLI) in its own transaction. The route returns this id with 202 before the worker runs.
- `run_rebuild(db, clock, bits_dir, task_id, actor) -> RebuildResult` (:78): the REQ-166 run. **It never raises for a rebuild error.** It logs the exception type only, ends the task `failed` with `{"error": "rebuild failed"}` (#98 (g)) and returns `RebuildResult(task_id, "failed", ...)`. `RebuildResult(task_id, state, result)` (:56): `result` is exactly what was stored in `task.result`.
- `actor` is the pipeline `Actor`: `Actor("user:<id>", id)` for the API, `Actor("cli:root", None)` for the CLI (#101). It is used for every audit entry, the deletes included.

## Flow (`_rebuild`, :112)

1. `db.session()` + `catalog_lock(session)`, held for the whole run (:89).
2. `uploads.finish_interrupted_uploads(session, bits_dir)` runs first, before any folder is read (:115; ruling "Rebuild finishes interrupted uploads first").
3. Folder guard: `folders.unreadable` → `_mark` writes one constant log line per folder (:101). Then `folders.discover`.
4. **One transaction** (:119–:128): the #15 order (server files first, a live `source_file` first, then UTF-8 bytes; then `uploaded/` files by bytes; same as the reconcile). Per file (`_one`, :161):
   - It is skipped if its folder is already in `blind` (the reviewer's TASK-156 nit, applied here), or if the path is an upload copy this rebuild will remove after commit (a policy moved to the server folder, or a displaced policy).
   - `uploaded/` files: `folders.classify_upload` in the rebuild transaction.
     - `leftover` → queued, removed only after the commit (see 6).
     - `stray` → one log line, `skipped` `{source_file, reason: "stray"}`, never imported.
   - `folders.read_input` once. A None caused by a folder swapped after discovery marks the folder.
   - `prepare` once. For `uploaded/`: `folders.renamed` → one log line, `skipped` `{reason: "renamed"}`, never imported.
   - `pipeline.store_in_savepoint` (mode `rebuild`, never skips). A rejection rolls back to its savepoint, so the policy keeps its rows.
   - Then the gone-file deletes (`_delete_gone`, :206), **in the same transaction**, after all imports. For each live policy: skip it if its folder is in `blind`. Otherwise `folders._state(bits_dir, source_file)` runs **right before each delete**: unreadable → mark the folder and skip; only `absent` deletes, via `delete.delete_in_tx` (reason "file removed"; emits `policy_deleted`).
5. COMMIT. Then `delete.remove_after_commit` for the upload copies of moved, displaced and deleted policies (:130).
6. For each leftover: `folders.remove_leftover`. If it returns None (not confirmed gone), `uploaded/` is marked unreadable and the file is not listed; otherwise it goes into `removed_leftovers` (:131–:137). No `bit_import` row, no import; the policy stays deleted.
7. Last transaction (:138–:158):
   - `pipeline.record` for each stored file: a `bit_import` row with mode `rebuild`, plus for a rejection its `policy_import_rejected` alert and the failure count.
   - `imports.finish_task(succeeded, result)`.
   - `alerts.rebuilt(...)` → the one `bits.rebuild` / `policy_rebuilt` alert, with `removed_leftovers`.

`task.result` on success (#98 (g), plus the ruling's `removed_leftovers`; `skipped` and `unreadable_folders` pending main's answer, Q4):

```json
{"files": [{"source_file", "import_id", "outcome", "policy_id", "policy_version"}],
 "deleted_policy_ids": [...], "plugins_retired": n,
 "removed_leftovers": ["uploaded/policy-<id>.bit"],
 "skipped": [{"source_file", "reason": "stray" | "renamed"}],
 "unreadable_folders": ["./" | "uploaded/"]}
```

- `deleted_policy_ids` covers both the displaced policies (`StoreResult.deleted_policy_ids`) and the gone-file deletes.
- `plugins_retired` is the files' `plugins_retired` plus the plugins retired by those deletes.

## REQ-166 acceptance

| Item | How |
| --- | --- |
| (1) Corrupted catalog restored, ids unchanged | Every file is re-stored through `store.apply` by natural key in `rebuild` mode (never skipped). No truncation; nothing outside the store's upserts, `delete_in_tx` and the task, bit_import and audit writes. |
| (2) One rejected file among three | Savepoint per file; the rejected file's rows stay. `task.state` is `succeeded` (#20). `files` lists all three with their outcomes and `import_id`s. |
| (3) Other tables untouched | Only the catalog (via store and delete), `bit_import`, `task` and `audit_log` (appends) are written. The `delete_in_tx` effects (cancelled queued jobs, disabled schedules) are the REQ-167 exception. |
| (4) Removed file → deleted, with alert | `_delete_gone` → `delete_in_tx` → `policy_deleted`. |
| (5) DB error mid-run | Imports and deletes share one transaction, so it rolls back as a whole. No files are removed (removal happens only after the commit) and no `bit_import` rows are written (#98 (j)). In a fresh session: `finish_task(failed, {"error": "rebuild failed"})` plus `policy_rebuilt` with state `failed` and zero counts. |
| (6) Alerts | Exactly one `policy_rebuilt`. One `policy_import_rejected` per rejected file (from `record`). `policy_imported`: see Q1 below. |

## Rulings

- (1) The finish step runs first under the lock: :115.
- (2) TASK-156 pieces are reused: `unreadable`, `discover`, `read_input`, `classify_upload`, `renamed`, `remove_leftover` (the None return is handled), `present` (as `file_exists`), and the server-first, imports-before-deletes and #15 order. Stray and renamed files are skipped and reported, never imported.
- (3) Folder guard: an unreadable folder imports nothing and deletes nothing, with one log line per folder. A symlinked or missing bits folder blocks both, through `folders.unreadable`. Each deletion uses the per-row three-way `_state` check right before it. Once a folder is marked, its later files and rows are skipped.
- (4) Leftovers are removed, listed in `task.result.removed_leftovers` and in the alert, never revived, with no `bit_import` row.

## Open points sent to main (2026-10-28, defaults applied)

- **Q1 (#23 / REQ-166 (6)).** `store_in_savepoint` → `audit_success` emits `policy_imported` for every successful file, so an unchanged file in a rebuild also alerts. The approved code has no "unchanged" signal. Default: accept it and read "changed" as "re-stored by the rebuild". The alternative needs a change in pipeline.py/store.py.
- **Q2.** `folders.delete_removed` uses its own transaction per delete, which breaks (5). The deletes therefore run inside the rebuild transaction and call the private `folders._state` (the same per-row check). Main may prefer a public alias in folders.py.
- **Q3.** On failure, no `bit_import` rows are written. This follows #98 (j)/(g), not plan TASK-154 §8's "successes recorded as rejected".
- **Q4.** The `skipped` and `unreadable_folders` fields in `task.result` are not in #98 (g).

## Known edge

If the **last** transaction (records, task, alert) fails after the catalog commit, the catalog changes stand. The task is still marked `failed` with zero counts in a fresh session, and leftovers already removed are not listed. The same applies to the `bit_import` rows of that run (cf. REQ-160 (4)).

## Gates (repo root)

- `ruff check` / `ruff format --check` on rebuild.py: pass. The full `ruff check manager` currently reports 6 errors, all in impl-manager-159's in-progress `watcher.py` (S101, E501), not mine.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues (296 files).
- PG regression from `manager/`: `test_folders_pg.py test_import_pipeline_pg.py test_import_store_pg.py test_policy_delete_pg.py test_catalog_lock_pg.py test_uploads.py test_uploads_pg.py`: **588 passed**.
- Throwaway smoke tests (scratchpad, not kept), 3/3 passed:
  - three files with a corrupted execute and a flipped status, then one file made BIT102-rejected: ids unchanged, the execute and status restored, `succeeded`, outcomes `success, success, rejected`, one `bits.rebuild`, one `policy.import_rejected`, rows all `rebuild`;
  - a leftover: removed, listed in `task.result` and in the alert, policy still deleted, no row for it; a gone file: deleted with `policy.delete`;
  - an OperationalError on the second file: no policy created, task `failed` `{"error": "rebuild failed"}`, no `bit_import` rows, only `bits.rebuild` written.

## Cases for the tester (TP-M7-17, `manager/tests/test_rebuild_pg.py`)

1. REQ-166 (1)–(6) as written. For (1), corrupt one `execute`, delete one `policy_plugin` row, set one plugin `retired` and flip `policy_status` with no override.
2. The row's extra test: a leftover `uploaded/policy-<id>.bit` of a deleted policy. The policy stays deleted, the file is removed, it is listed in `task.result.removed_leftovers` and in the `bits.rebuild` detail `removed_leftovers`, and there is no `bit_import` row for it.
3. The finish step runs first: a `.tmp-<id>-<sha>` matching the live policy's `source_sha256` is renamed before the rebuild reads `uploaded/`, so the older `policy-<id>.bit` is never re-imported.
4. Stray and renamed `uploaded/` files: no row, no catalog change, listed in `skipped`.
5. Folder guard: `uploaded/` missing, a symlink, or a file; the bits folder a symlink. No import and no delete for that folder, and it is listed in `unreadable_folders`. Also `uploaded/` swapped for a symlink mid-loop (patch `folders._state` or `delete_in_tx` timing): no further deletes for that folder.
6. A `remove_leftover` that is not confirmed (`remove_after_commit` patched to a no-op): the file is not listed and `uploaded/` is in `unreadable_folders`.
7. A server file taking an uploaded policy's name: `move_server`. The old upload copy is removed after commit and is neither reported as a stray nor treated as a leftover.
8. A concurrent upload and rebuild serialise (TS §8.3): an upload holding `catalog_lock` makes `run_rebuild` wait.
9. A DB error in the final transaction: the task is `failed` (see Known edge).
10. The canary: no file content or Execute in the logs. The log lines are constant words plus folder labels and the leftover path, as in folders.py.
