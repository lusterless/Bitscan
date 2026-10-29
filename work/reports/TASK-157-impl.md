# TASK-157 IMPL: catalog rebuild

Implementer: impl-manager-m7. REQ-166. Risk high (importer; two approvals). No per-task plan; built from:
- the TASK-157 row (crash-window text included);
- REQ-166;
- TS §4.2 L540, §4.3 L550, §8.4 L1290;
- #20, #23, #98 (g) and (j), #101, #103.

Rulings and carries applied:
- decisions 2026-10-28, "TASK-157 rulings" (1)–(5);
- TASK-154 r2, alerts only for changed policies;
- TASK-156 r1, the public `read_file` and `Relocate`;
- "#102 (c) wiring";
- the crash-window ruling, 2026-10-27;
- the TASK-154 review carries: `prepare` per file, `PolicyManagedOnServer` handled outside `store_in_savepoint`, `classify_upload` reused.

## Files

| File | Lines (total / non-blank / code) | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/rebuild.py` (new) | 249 / 227 / 202 (37 imports) | `RebuildResult`, `start_task`, `run`; private `_Work`, `_rebuild`, `_unlink`, `_end`, `_finish` |

No other file changed for this task. It calls only public interfaces:
- `folders`: `discover`, `classify_upload`, `read_file`, `Relocate`, `UploadClass`, `is_bit_file`;
- `pipeline`: `prepare`, `store_in_savepoint`, `record`, `Actor`, `FileInput`, `ImportOutcome`;
- `uploads.staged_upload`;
- `delete`: `delete_in_tx`, `remove_after_commit`;
- `alerts`: `rebuilt`, `emit`;
- repositories: `imports.insert_task` and `finish_task`, `catalog_integrity.integrity_rows`, `catalog_lock`;
- `own_changes.OWN_CHANGES`.

**Size:** 202 code lines against the estimate of 180. 37 are imports, and about 30 are ruff-format expansion (the #98 (g) result dict, the `rebuilt(...)` call, the `store_in_savepoint` call). The cause is the two rulings that came after the estimate: staging case (c) upload files like uploads (`staged_upload` + `Relocate`), and the crash-window leftover list.

## Interface (TASK-160 worker, TASK-164 route, TASK-166 CLI)

```python
def start_task(db: SessionDatabase, clock: Clock, requested_by: int | None) -> UUID
def run(db: SessionDatabase, clock: Clock, bits_dir: Path, task_id: UUID, actor: Actor) -> RebuildResult

@dataclass class RebuildResult:
    task_id: UUID
    state: Literal["succeeded", "failed"]
    files: list[tuple[str, ImportOutcome]]   # source_file, outcome with import_id
    not_imported: list[str]                  # no row: unreadable, or a refused case (c) copy
    deleted_policy_ids: list[int]
    plugins_retired: int
    removed_leftovers: list[str]
```

- `start_task` writes the `task` row (`rebuild`, `running`, `requested_by`) in its own transaction, without the catalog lock. The route can then answer 202 `{task_id}` before the worker starts; the ruling (5) split.
- The CLI calls both in the foreground, with `requested_by` None and `Actor("cli:root", None)` (#107 (d)).
- `run` returns a result rather than raising when the rebuild fails, so the CLI can map `state` to its exit code (#107 (c)). It raises only if no session or lock can be had (the database is down before it starts). The task then stays `running` until the next start-up marks it `failed` (TS §4.2 L540).

## How it works (`run`)

1. **Session and lock.** One pinned session, `catalog_lock(session)` for the whole rebuild, including the renames and removals after the commit (TS L526).
2. **One rebuild transaction** (`_rebuild`), inside an `ExitStack` that owns every staged upload:
   1. The files of both folders come from `folders.discover`, in the #15 order the reconcile uses: a live policy's `source_file` first, then the UTF-8 bytes of the path.
   2. Each `uploaded/` file goes through `classify_upload` first. A **leftover of an interrupted delete** is not imported. It is listed in `removed_leftovers` and removed after the commit, so the deleted policy is never revived.
   3. Each file is read once with `read_file` (O_NOFOLLOW, 5 MiB, hash over the whole file). A file that is gone, or isn't a regular file, is listed in `not_imported`.
   4. Each file is prepared on its own (`prepare(data)`; None over 5 MiB gives BIT001). The target is `Target("server", rel, sha)` in the server folder, `Target("upload", None, sha)` under `uploaded/`.
   5. `store_in_savepoint(..., mode "rebuild")` stores it: never skipped, its own savepoint, so a rejection keeps that policy's rows (TS L540). Its audit entries follow TASK-154 r2: `policy_imported` only for a policy whose rows changed.
   6. `PolicyManagedOnServer` (a case (c) copy of a server-folder policy) is caught per file, outside `store_in_savepoint`. Its savepoint has already rolled back. It gets no row and is listed in `not_imported`, and the integrity check reports the file (ruling (5)).
   7. **After a success:**
      - `plugins_retired` adds up;
      - `StoreResult.remove_after_commit` (the old uploaded copy on a `move_upload`) is kept for after the commit (ruling (3)–(4));
      - an `uploaded/` file is staged as an upload: `staged_upload` + `Relocate(stage, path, kind)`, then `before_commit(policy_id)`, inside the transaction. `Relocate` stages only when the file isn't already at `policy-<id>.bit` (TASK-156 case (c) ruling).
   8. **Gone files:** every live policy whose `source_file` is no longer a regular file is deleted with `delete_in_tx(..., reason="file removed")` (REQ-167, with its `policy_deleted` alert). Its retired plugins count, and its uploaded copy is kept for removal after the commit.
3. **If anything raises** (database or disk, #98 (j); a commit failure included):
   - the transaction rolls back and the `ExitStack` discards every staged temp file;
   - no `bit_import` row is written;
   - a final transaction sets the task `failed` with `{"error": "The rebuild failed; the catalog was left unchanged."}` and writes one `bits.rebuild` entry, the `policy_rebuilt` alert, with state `failed` (ruling (1));
   - if even that fails, it is logged by type, and the next start-up marks the task failed.
   - Only the exception type is logged.
4. **After the commit**, still under the lock:
   - each leftover is unlinked (`OWN_CHANGES.removed(rel)` first, #102 (c));
   - each staged upload's `Relocate.after_commit` renames it and removes a case (c) foreign file. A rename failure is logged and leaves the temp file for the start-up finish;
   - `remove_after_commit` removes the old copies. `delete.py` records those removals for #102 (c).
5. **Final transaction:**
   - `record(...)` writes one `bit_import` row per imported file, with mode `rebuild`. A rejected file gets its `policy_import_rejected` alert and the failure count (#23).
   - `finish_task(succeeded, ...)` stores the #98 (g) result: `{files: [{source_file, import_id, outcome, policy_id, policy_version}], deleted_policy_ids, plugins_retired, removed_leftovers, not_imported}`. `removed_leftovers` comes from the crash-window ruling, `not_imported` from ruling (5).
   - It writes the one `bits.rebuild` entry, the `policy_rebuilt` alert, with `files_imported`, `files_rejected`, `deleted_policy_ids`, `plugins_retired` and `removed_leftovers`.
   - If this transaction fails, the catalog stands. The failure is logged, `import_id`s stay None, and the task is marked failed at start-up.

**What it never touches:**
- No catalog table is truncated, and no `policy` row is deleted: deletes are soft, as in REQ-167.
- `agent`, inventory, `scan_*` and audit tables are never written, apart from the REQ-167 delete effects and its own audit entries.

## Readings for the reviewer

1. `task.result` gains `not_imported` (ruling (5): "listed as not imported") and `removed_leftovers` (the crash-window ruling) beyond the #98 (g) keys.
2. A failed rebuild's result holds only `{error}` (#98 (g)). Its `bits.rebuild` entry has state `failed` and zero counts, because nothing was committed.
3. Leftovers are removed only after a successful commit. If the rebuild fails, a leftover stays until the next start-up's reconcile or rebuild, which removes it the same way.
4. `run` catches every `Exception` from the rebuild transaction and turns it into `failed`. A programming error therefore also ends `failed`; it is logged by type only, and the task row and the alert show it.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` passes, and `ruff format --check manager` passes (295 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 295 source files.

## Scratch checks (outside the tree, `%TEMP%\m7-154-scratch\check_rebuild.py`; every collaborator stubbed; not tests)

- **Five files:**
  - `a.bit` succeeds;
  - `b.bit` is rejected;
  - `uploaded/foreign.bit` succeeds, case (c), staged as policy 1;
  - `uploaded/policy-3.bit` is a leftover;
  - `uploaded/policy-9.bit` succeeds, live, at its own name.
  - One more live policy's file is gone.
- **Success:**
  - The savepoints run in order, the staging happens inside the transaction, and `DELETE 4 file removed` runs, all before COMMIT1.
  - After COMMIT1, the renames, then the removals.
  - Transaction 2 writes four `rebuild` rows, then `FINISH succeeded` with the six result keys, then one `bits.rebuild` entry (`imported=3 rejected=1 leftovers=[uploaded/policy-3.bit]`). The leftover file is gone afterwards.
- **A refused case (c) copy:** no row, nothing staged, and the rest unchanged.
- **A database error at the second file:** ROLLBACK1. Transaction 2 holds only `FINISH failed ['error']` and a `bits.rebuild` entry with state failed. There are no rows and nothing is staged; the leftover is not removed.

## For the tester (tester-m7, REQ-166 (1)–(6); PostgreSQL with temporary folders in WSL)

- Call `task_id = start_task(db, clock, user_id)` then `run(db, clock, bits_dir, task_id, Actor("user:<id>", <id>))`, or with `None` and `Actor("cli:root", None)`.
- **REQ-166 (1):** corrupt the catalog as the owner role (an `execute`, a deleted `policy_plugin` row, a plugin set `retired`, a `policy_status` flipped). After the rebuild, every id is unchanged and it matches a fresh import. Each corrupted policy gets exactly one `policy_imported`; an untouched one gets none (TASK-154 r2).
- **REQ-166 (5):** inject a database error in the middle, for example by patching `rebuild.store_in_savepoint` to raise on the second file. The catalog checksums are unchanged, no `bit_import` row is written, the task ends `failed` with `{error}`, and there is one `policy_rebuilt` entry with state failed.
- **Crash window:** a deleted policy's `uploaded/policy-<id>.bit` is removed, listed in `task.result.removed_leftovers` and in the alert's `removed_leftovers`, and gets no row. The policy stays deleted.
- **Suggested plants:**
  - skip `classify_upload`, so a leftover is imported → the crash-window row goes red;
  - commit on error (catch inside the transaction) → REQ-166 (5) goes red;
  - write the records inside the rebuild transaction → (5) red, since rows appear on failure;
  - drop the gone-file loop → (4) red;
  - pass `mode="auto"`-like skipping (call `import_one`) → the never-skipped row goes red.

## Revision 1 (blocking defect found by reviewer-m7's pre-read, confirmed by main)

**The defect:** an `uploaded/` file that `Relocate` stages under a new name was soft-deleted again in the same transaction. That happens for a case (c) file creating or updating a policy, or a case (a) `policy-<n>.bit` whose content names another policy. The staged file is only `uploaded/.tmp-<id>-<sha>` until the commit, so the gone-file loop found no `uploaded/policy-<id>.bit` on disk and called `delete_in_tx` on the policy just imported. After the commit, the rename landed and the delete's `remove_after_commit` removed the file again.

**The fix** is in `rebuild.py` only, 4 lines plus 2 comments:
- `_Work.staged` collects `uploaded/policy-<id>.bit` for every move where `Relocate` actually staged (`move.staged` is True, after `before_commit`).
- The gone-file loop treats a policy whose `source_file` is in `work.staged` as present. It is never deleted, so the delete adds none of those paths to `work.removals`.

**Case (a) checked:**
- A live `uploaded/policy-<n>.bit` whose content is policy `<n>` is at its own name, so `Relocate` doesn't stage and the file is on disk. The loop finds it, as before.
- When its content names another policy `<m>`, `<m>`'s staged `uploaded/policy-<m>.bit` is now in `work.staged` and is kept. Policy `<n>`'s file is still on disk, so `<n>` isn't deleted either.

**The one remaining way a staged path reaches `work.removals` is correct, and is kept on purpose.** A later server-folder file takes over the same policy as `move_upload` (TS §4.1 L524, "server folder wins"). Its `StoreResult.remove_after_commit` names the old uploaded copy. After the commit the rename lands first and that removal then deletes it, leaving the policy in its server file with no stray upload copy. Filtering it out of the removals would leave `uploaded/policy-<id>.bit` behind as an integrity difference.

**Gates:** `ruff check manager` and `ruff format --check manager` pass (296 files), and the CI mypy command gives Success (296 files).

**Scratch** (`check_rebuild_r1.py`):
- `uploaded/foreign.bit` is staged as new policy 13 (`staged=True`), and policy 13's `source_file` `uploaded/policy-13.bit` isn't on disk yet. Only the truly gone policy 4 is deleted. Policy 13 is kept and its rename runs after the commit.
- A case (a) file at its own name (`policy-9.bit`, `staged=False`) is unaffected.

**For the tester:** new rows:
- a rebuild with a case (c) `uploaded/foo.bit` holding a new policy ends with that policy live, `uploaded/policy-<id>.bit` holding the bytes, and `foo.bit` gone;
- the same with a case (a) `uploaded/policy-<n>.bit` whose content names a new policy;
- a rebuild with an uploaded file and a server file of the same name ends with the policy in the server file and no `uploaded/policy-<id>.bit`.
- Plant: drop the `work.staged` check → the first two rows go red (the policy deleted, the file gone).

The reviewer accepted the extra `task.result` keys (`not_imported`, `removed_leftovers`); the carry to TASK-164 is to document them in the `GET /tasks/{id}` schema.

## Revision 2 (decisions 2026-10-28, "TASK-158 test questions" (2))

**The race (tester-m7's probe):**
1. A CLI rebuild's task is written by `start_task`.
2. The rebuild waits for the catalog lock while the manager's start-up holds it.
3. Start-up marks every `running` task `failed`, the rebuild's included.
4. The rebuild then ran anyway: its catalog changes committed and its `bits.rebuild` entry said `succeeded`, while its task row stayed `failed` (`finish_task` changes only `running` rows).

**The fix** is in `rebuild.py` only, 6 lines plus 2 comments:
- Right after taking the catalog lock, `run` re-reads the task row (`imports.get_task`) in a short transaction.
- If the row is missing or its state isn't `running`, `run` changes nothing and returns at once with `RebuildResult(task_id, state="failed", reason=NOT_RUNNING)`. That means:
  - no catalog change and no file change;
  - no `bit_import` rows;
  - no audit entry and no alert, so no `bits.rebuild` either;
  - no `finish_task`.
- `NOT_RUNNING` = "interrupted by manager start-up; run it again", a fixed text. TASK-166's CLI prints it and exits non-zero (#107 (c): `failed` → 1).
- `RebuildResult` gains `reason: str | None = None`. It is None on every other path, a normal `failed` result included: there the detail is in `task.result.error`.
- The task row and the audit log now always agree: a rebuild either runs and finishes its own `running` task, or does nothing.

**Gates:** `ruff check manager` and `ruff format --check manager` pass (298 files), and the CI mypy command gives Success (298 files).

**Scratch** (`check_rebuild_r2.py`, `get_task` stubbed):
- a task already `failed` → one read transaction only (no savepoint, row, finish or entry), state `failed`, reason `NOT_RUNNING`;
- a `running` task → the full rebuild as before, reason None.

**For the tester:**
- Re-run the probe: `start_task`, then `fail_running_tasks` (or start-up's `run_once`), then `run`. Expect:
  - `state == "failed"` and `reason == "interrupted by manager start-up; run it again"`;
  - catalog checksums unchanged;
  - no new `bit_import` row and no new `audit_log` entry;
  - the task row still `failed` with the start-up's `{error}`.
- An unknown `task_id` gives the same.
- **Plant:** drop the re-check → the probe row goes red: the rebuild commits and a `bits.rebuild` entry says `succeeded` while the task stays `failed`.
