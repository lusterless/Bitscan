# TASK-155 IMPL: uploads and the start-up finish of interrupted uploads

Implementer: impl-manager-m7. REQ-163, REQ-165 (1). Risk high (importer; two approvals). No per-task plan; built from the TASK-155 row, #99, REQ-163, REQ-165, TS §4.1 L522, L526, L528 and §8.7 L1344, L1377, L1395. Rulings applied:
- decisions 2026-10-28, "TASK-154 and TASK-165 rulings": the record is written in a `finally` when `after_commit` raises;
- the reviewer's carry from TASK-154: a failed rename after the commit leaves the temp file for the start-up finish;
- the crash-window ruling (2026-10-27): a deleted policy's file is never brought back.

## Files

| File | Lines (total / non-blank / code) | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/uploads.py` (new) | 237 / 209 / 176 | `client_file_name`, `upload`, `finish_interrupted`, `FinishResult`; private file helpers |

No other file is changed. The importer `__init__` export isn't needed: callers (TASK-158, TASK-160) import from `services.importer.uploads`. It calls the pipeline only through `pipeline.prepare` and `pipeline.import_one`. Size: 176 code lines against the estimate of about 170.

## Interface (for TASK-158 and TASK-160)

```python
def client_file_name(raw: bytes | str | None) -> str
def upload(db: SessionDatabase, clock: Clock, bits_dir: Path, data: bytes,
           client_name: bytes | str | None, actor: Actor) -> ImportOutcome
@dataclass(frozen=True) class FinishResult: renamed: int; deleted: int
def finish_interrupted(session: CatalogSession, bits_dir: Path) -> FinishResult
```

- `upload` takes the catalog lock itself, like `delete.delete_policy` (TASK-152). The lock has to cover the rename after the commit (TS L526). It runs `prepare` before taking the lock (the TASK-154 reviewer's nit 1).
- `finish_interrupted` follows the `import_one` convention instead: the caller holds `catalog_lock(session)`. That way TASK-158 can run the whole start-up sequence under one lock if it wants to. It calls this before any other catalog step (#102).

## How each point is met

- **Client name (#99 (d), REQ-163 (1)):**
  - The name is decoded as UTF-8 with replacement if it arrives as bytes.
  - U+0000 to U+001F, DEL and lone surrogates each become U+FFFD; surrogates are included because PostgreSQL text can't store them.
  - It is cut to 255 characters; a missing name becomes `""`.
  - It is idempotent, so TASK-162's `parse_upload` can call it on the raw `filename` bytes, or pass its own result through again.
  - The name goes only into `FileInput.file_name`, which becomes `bit_import.file_name`. It never reaches a path, a log line or a detail. Every path is built from `policy_id` and the hash alone.
- **The import:**
  - It runs as `Target("upload", None, sha256)` in mode `manual`, so it is never skipped.
  - `PolicyManagedOnServer` comes from the pipeline (409, #99 (e)) after its `policy.import_refused` entry, with no row and no file.
  - A rejection never reaches `before_commit`, so nothing is written to disk and the existing file stays byte-identical (REQ-163 (3)).
- **Before the commit (`before_commit`, the last step of the pipeline's transaction 1):**
  - It creates `uploaded/.tmp-<policy_id>-<sha256>` with `O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW` (plus `O_BINARY` where it exists), mode 0600.
  - It writes all the bytes, `fsync`s the file and then `fsync`s the `uploaded/` folder, so the temp file's name survives a crash after the commit.
  - A failed write removes the file it created.
  - An existing file or symlink at the temp path makes `os.open` fail (`O_EXCL`; `O_NOFOLLOW`). Nothing is created or removed, the import rolls back, and the symlink's target is untouched (REQ-163 (2)).
  - The file is 0600 from the open mode, and the unit's `UMask=0077` also applies (REQ-163 (6)). It belongs to the service user, which runs the process.
- **Rollback (REQ-163 (4) first half):** an exception before the commit removes the temp file, but only if this call created it. That covers a database error, an error from `before_commit`, or a failed commit.
- **After the commit (`after_commit`):**
  - `os.replace(temp, uploaded/policy-<policy_id>.bit)` replaces the policy's previous upload, and the folder is `fsync`ed.
  - If the rename fails, the temp file is left in place (the reviewer's carry). The pipeline still writes the `success` row and then the error propagates. The next start-up finishes the rename (REQ-163 (4) second half).
  - All of this happens inside the caller's catalog lock.
- **Start-up finish (`finish_interrupted`, TS L528, REQ-165 (1)):**
  - Every `uploaded/` entry whose name starts with `.tmp-` is examined, in name order.
  - It is **renamed** to `uploaded/policy-<id>.bit` only when all of these hold:
    - the name is exactly `.tmp-<id>-<64 lowercase hex>` (decimal id, no leading zero, ASCII digits only; no `re`, which is banned);
    - it is a regular file (`is_file(follow_symlinks=False)`);
    - policy `<id>` exists and isn't deleted;
    - the policy's `source_file` is `uploaded/policy-<id>.bit`;
    - the file's content hash equals the policy's `source_sha256`. The content is read with `O_NOFOLLOW | O_NONBLOCK`, and must be a regular file of at most 5 MiB per `fstat`.
  - **Every other** temp file is deleted (unlinked, never followed): a foreign name such as `.tmp-x`, a symlink, a FIFO, an uncommitted upload, a hash mismatch, or a temp for a deleted policy (crash-window ruling).
  - Files without the `.tmp-` prefix are never touched.
  - An `OSError` on one entry (for example a folder named `.tmp-x`) is logged by its type, and the loop goes on. The folder is `fsync`ed once at the end.
  - One log line gives the counts only, no names. The policy row is read in a short transaction per temp file, under the caller's lock.

## Readings for the reviewer

1. **The finish checks more than the hash.** It also requires the policy to be live with `source_file` `uploaded/policy-<id>.bit`. TS L528 says "whose hash equals that policy's `source_sha256`". The extra conditions only ever lead to a delete, and they stop a temp file being renamed into a name the catalog doesn't point at.
2. **A temp-path clash while the manager runs:** a rename failed after commit, then the same bytes are uploaded again for the same policy before a restart. The second upload's `O_EXCL` open fails, so it is an internal error (503, #98 (j)) until the start-up finish runs. Removing a pre-existing entry before the open would break REQ-163 (2), so it isn't done.
3. **#102 (c), the watcher ignoring the manager's own renames,** isn't wired here. TASK-159 owns that record, and its interface doesn't exist yet. When it does, `after_commit` and `finish_interrupted` are the two places that rename or delete in `uploaded/`.
4. **`O_NOFOLLOW` and `O_NONBLOCK`** are taken with `getattr(..., 0)`, as `api/webui.py` does. They are POSIX only, so on the Windows dev box only `O_EXCL` guards the temp path. The manager runs on Linux, where both flags apply.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager`: All checks passed. `ruff format --check manager`: 286 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 286 source files.

## Scratch checks (outside the tree, `%TEMP%\m7-154-scratch\check_uploads.py`; Windows, fake session, `import_one` stubbed; not tests)

- `client_file_name`:
  - `b"../../etc/\x00pa\r\nss\xff\x7fwd"` gives `../../etc/�pa��ss��wd`;
  - `None` gives `""`;
  - 5,000 characters give 255;
  - a lone surrogate gives U+FFFD.
- `_temp_policy_id` accepts `.tmp-12-<64 hex>` and refuses each of these:
  - a leading zero;
  - uppercase hex;
  - 63 hex digits;
  - a second `-`;
  - an Arabic-Indic digit;
  - `.tmp-x`.
- `upload`, one case at a time:
  - success: the temp exists before the commit, and afterwards only `policy-7.bit` remains;
  - rejected: no file is written;
  - a commit failure: the temp is removed and the previous `policy-7.bit` is unchanged;
  - a planted file at the temp path: `FileExistsError`, and the planted file is kept unchanged;
  - a rename failure: `OSError` propagates and the temp file is left.
- `finish_interrupted` was given four temp files: one committed, one uncommitted, one for an unknown policy, and `.tmp-x`. It renamed 1 and deleted 3. The renamed file holds the committed bytes.
- Symlink, FIFO and file-mode cases need Linux. They are for the tester in WSL.

## For the tester (tester-m7; TASK-155 row tests and REQ-163, REQ-165 (1); temporary folder plus PostgreSQL in WSL)

- `upload(db, clock, bits_dir, data, client_name, Actor("user:<id>", <id>))` with a real `SessionDatabase`. Inside `bits_dir`, `uploaded/` must exist (mode 0750, TS L1344).
- **REQ-163 (2):** plant a symlink at `uploaded/.tmp-<id>-<sha>` before the upload. For a new policy, `<id>` is the next `policy_id`; or re-upload an existing policy with changed bytes. Expect: an `OSError` propagates, there is no `bit_import` row, the catalog is unchanged, and the target is untouched.
- **REQ-163 (4):**
  - Inject the fault before the commit by making the `bit_import`/catalog transaction fail after `before_commit`. One way is to patch `pipeline.alerts.emit`; another is a `before_commit` wrapper via `uploads._write_new`.
  - Inject the fault between the commit and the rename by patching `uploads.os.replace`. Then call `finish_interrupted(session, bits_dir)` under `catalog_lock(session)` and expect `policy-<id>.bit` to hold the committed bytes.
- **REQ-165 (1):** temp files for a committed upload (renamed), an uncommitted one (deleted), `.tmp-x` (deleted) and a symlink temp (deleted, target untouched).
- **Suggested plants:**
  - drop `os.O_EXCL` or `_NOFOLLOW` from `_write_new` → the symlink row goes red;
  - make the `except` in `upload` also remove the temp after the commit → the rename-fault row goes red;
  - make `finish_interrupted` skip the hash comparison → the uncommitted-temp row goes red;
  - write the temp in `after_commit` instead of `before_commit` → a fault before the rename leaves no recoverable file.

## Revision 1 (decisions 2026-10-28, "TASK-156 case (c) success")

The upload staging is now a public API in `uploads.py`, so TASK-156's `folders.py` can store a successful case (c) `uploaded/` import exactly as an upload, without copying code. There is no behaviour change: `upload()` now uses the same API. Only `uploads.py` changed; it is now 268 / 235 / 191 lines (total / non-blank / code). The extra lines are the class, its docstrings and the context manager.

```python
class UploadStage:
    def __init__(self, bits_dir: Path, sha256: str, data: bytes) -> None
    def before_commit(self, policy_id: int) -> None      # pass to import_one(before_commit=)
    def after_commit(self, outcome: ImportOutcome) -> None  # pass to import_one(after_commit=)
    def discard(self) -> None                            # rollback cleanup; no-op after commit
    committed: bool

@contextmanager
def staged_upload(bits_dir: Path, sha256: str, data: bytes) -> Iterator[UploadStage]
```

- **What each method does:**
  - `before_commit(policy_id)`: the last step of the pipeline's transaction 1. It creates `uploaded/.tmp-<policy_id>-<sha256>` (`O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW`, 0600), writes and `fsync`s it, then `fsync`s the folder. It records `policy_id` and the path.
  - `after_commit(outcome)`: marks the stage committed, renames the temp file to `uploaded/policy-<policy_id>.bit` with `os.replace`, using the id recorded in `before_commit`, and `fsync`s the folder. If the rename fails, the temp file is left for `finish_interrupted` and the error propagates.
  - `discard()`: removes the temp file only if this stage created it and the commit hasn't happened. An `OSError` is logged by type.
  - `staged_upload(...)` calls `discard()` when its block raises, then re-raises.
- **`policy_id` is not a constructor argument.** The pipeline learns it only from the store, and hands it to `before_commit(policy_id)`. That is the only point where the temp name can be built. For the same reason the stage needs no session or transaction: the caller's catalog lock covers the block, and the pipeline calls the hooks inside and after its transaction 1.
- **How folders.py uses it (TASK-156 case (c)):**

```python
with staged_upload(bits_dir, sha256, data) as stage:     # inside catalog_lock(session)
    outcome = import_one(session, clock, bits_dir, file, mode=..., actor=..., file_exists=...,
                         prepared=prepared, before_commit=stage.before_commit,
                         after_commit=stage.after_commit)
if outcome.outcome == "success":
    ...  # then remove the foreign file, unlinked without following (folders.py's own step)
```

  A rejected or refused file never reaches `before_commit`, so the stage writes nothing. The foreign file stays in place, and the integrity check reports it (the ruling).
- **`upload()`** is now `with db.session() as session, catalog_lock(session), staged_upload(...) as stage: return import_one(..., before_commit=stage.before_commit, after_commit=stage.after_commit)`. The stage exits first, so a discard still runs under the lock.
- **Gates:** `ruff check manager` passes, `ruff format --check manager` passes (287 files), and the CI mypy command gives Success with no issues in 287 source files.
- **Scratch re-run** (`check_uploads.py`): the same results as before the revision. That is success, rejected, commit failure (temp removed), planted temp (`FileExistsError`, planted file kept), rename failure (temp left), and the finish renaming 1 and deleting 3.
- **For the tester:**
  - The REQ-163 rows apply unchanged through `upload()`.
  - The r1 rows:
    - `staged_upload` around a stub `import_one` that raises after `before_commit` leaves no temp file;
    - after `after_commit`, `discard()` removes nothing;
    - a stage whose `before_commit` was never called discards nothing.
  - Plant: make `discard` ignore `committed` → the rename-fault row goes red, because the temp file is gone after a failed rename.

## Revision 2 (decisions 2026-10-28, "#102 (c) wiring")

The watcher drops the manager's own changes. `uploads.py` now records each rename into place in `OWN_CHANGES` (`services/importer/own_changes.py`, TASK-159) **just before** the filesystem call, under the catalog lock. Only `uploads.py` changed: 1 import and 4 lines.
- **`UploadStage.after_commit`:** `OWN_CHANGES.wrote(f"uploaded/policy-<id>.bit", sha256)` immediately before `os.replace(temp, final)`.
- **`finish_interrupted`:** for each temp file it renames, `OWN_CHANGES.wrote(f"uploaded/{target.name}", row.source_sha256)` immediately before `os.replace(path, target)`. That hash equals the file's content hash, since the rename requires it.
- No record is needed for the deleted and discarded `.tmp-` files: they start with `.` and aren't `*.bit`, so the watcher ignores them (#102 (b)).
- Behaviour is otherwise unchanged. The `upload()` scratch re-run gives the same results.
- **Gates:** `ruff check manager` and `ruff format --check manager` pass (295 files), and the CI mypy command gives Success (295 files).
- **For the tester:**
  - after a successful upload, `OWN_CHANGES.drop_write("uploaded/policy-<id>.bit", lambda: <sha of the file>)` is True once;
  - after a start-up finish rename, the same holds for that path.
  - Plant: record after the `os.replace` instead of before → a watcher event read at once isn't dropped (TASK-159's timing row).
