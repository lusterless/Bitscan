# TASK-155 IMPL: uploads

Implementer: impl-manager-155. REQ-163, REQ-165 (1). Risk high (importer; needs two approvals). Spec: TS §4.1 L522, L526, L528; §4.6 L611; §8.7 L1344, L1377. Open question #99 (d), (e). Decisions: "Crash window ruling", "Rebuild finishes interrupted uploads first", carried item (b) of "TASK-154 REVIEW APPROVED".

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/importer/uploads.py` (new, 217 physical lines, about 150 code lines without docstrings and comments) | `client_file_name`, `_Upload` (the hooks), `import_upload`, `FinishedUploads`, `finish_interrupted_uploads` |
| `manager/bitscan_manager/services/importer/pipeline_record.py` | `FileInput.__post_init__` (carry (b)), plus `import hashlib` (+9 lines) |

No other file was changed. `folders.py` (TASK-156) was not touched.

## Interface

```python
def client_file_name(raw: bytes | str | None) -> str                      # #99 (d)
def import_upload(session, clock, bits_dir, data, client_name, *, actor, prepared=None) -> ImportOutcome
def finish_interrupted_uploads(session, bits_dir) -> FinishedUploads(renamed, deleted)
```

- `import_upload` (`uploads.py:112`): the caller holds `catalog_lock(session)` and should pass `prepared=prepare(data)`, computed before it takes the lock. It hashes `data`, builds `FileInput(data, sha, client_file_name(name), Target("upload", None, sha))` and calls `import_one` in mode `manual`, with `before_commit=_Upload.write` and `after_commit=_Upload.rename`. `PolicyManagedOnServer` (409 `policy_managed_on_server`) comes from the pipeline's existing refusal: one `policy.import_refused` entry, no row and nothing on disk.
- `finish_interrupted_uploads` (`uploads.py:178`): a public, reusable step. **The caller holds the catalog lock and has no transaction open on the session.** It is called by start-up (TASK-158) and by the rebuild, before it reads the folders (TASK-157).

## How the items are met

| Item | Where / how |
| --- | --- |
| REQ-163 (1) hostile names | The client name is never part of a path: the temp path uses only `policy_id` and the hex SHA-256 the manager computed itself, and the final name only `policy_id`. `client_file_name` (`:45`) applies #99 (d): UTF-8 with replacement, then U+0000, the other C0 controls and DEL become U+FFFD, then the name is cut to 255 characters; `None` becomes `""`. A `str` input is first encoded with `surrogatepass`, so a lone surrogate becomes U+FFFD (three of them, one per byte) and never reaches PostgreSQL. |
| (2) symlink at the temp path | `write` (`:77`) opens with `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW \| O_CLOEXEC`, mode 0600. Any existing entry, a symlink included, gives `FileExistsError`. The `OSError` propagates out of transaction 1, so everything rolls back (#98 (j): no row). `discard` deletes only a file this upload created (`temp` is set only after a successful open), so the planted link and its target stay untouched. |
| (3) rejected re-upload | A reject or skip never calls `before_commit`, so no temp file is written and `policy-<id>.bit` is not touched. |
| (4) fault before commit | Any exception before COMMIT leaves `committed` False, so `discard` (in a `finally`) unlinks the temp. **Exception:** a `DatabaseUnavailable` after the temp was written (`:143`) is the COMMIT failing (the session converts only out-of-body errors), so the outcome is unknown. The temp is kept, and the next `finish_interrupted_uploads` renames it if the policy row matches its hash, otherwise deletes it. |
| (4) fault between commit and rename | `rename` sets `committed` first, so a failing `os.replace` leaves the temp in place. `import_one` still writes the `success` row (TASK-154 deviation (5)) and re-raises, and the route answers 500. The next start-up or rebuild finishes the rename. |
| (5) 409 | Comes from the pipeline (`store_decide.decide`) before any store and before `before_commit`. |
| (6) mode 0600 | The mode is 0600 at creation (with the unit's `UMask=0077` it stays 0600). `os.replace` keeps the inode, so `policy-<id>.bit` has mode 0600 and belongs to the service user. |
| Flushed before commit | `os.fsync` of the file, then of `uploaded/` (`_fsync_dir`), all inside `before_commit`, the last step of transaction 1. After the rename `uploaded/` is fsynced again. |
| Rename after commit | `rename` (`:88`) checks that `pending.store.source_file == "uploaded/policy-<id>.bit"` and that the temp name carries the same id, then runs `os.replace`. `rename(2)` replaces a symlink at the destination; it never follows it. |
| REQ-165 (1) | `finish_interrupted_uploads`: it lists the `.tmp-*` entries of `uploaded/`. A name is kept only if it parses strictly as `.tmp-<decimal id ≤ 2^63−1, no leading zero>-<64 lowercase hex>`, its content (opened `O_RDONLY \| O_NOFOLLOW \| O_NONBLOCK`, regular file only, at most 5 MiB) hashes to that hex, and the policy row (read `FOR UPDATE` in one transaction) is live, has `source_file = uploaded/policy-<id>.bit` and has `source_sha256` equal to the hex. Kept files are renamed into place. Every other `.tmp-*` entry is unlinked (a symlink is removed, not followed). A directory that cannot be unlinked is logged by error type and left, since it is not `*.bit`. A rename error propagates, so a rebuild never goes on with a stale copy. Only counts are logged. |
| Carry (b) | `FileInput.__post_init__` (`pipeline_record.py:43`) raises `ValueError` if `sha256 != target.file_sha256`, or if `data` is not None and its SHA-256 differs from `sha256`. |

**Choice for the reviewer (narrower than the spec's text, fail closed):** TS §4.1 L528 says "whose hash equals that policy's `source_sha256`". I also require that the policy is live and its `source_file` is `uploaded/policy-<id>.bit`. A deleted policy (crash-window ruling: it never comes back by itself) and a policy that moved to the server folder therefore never get an `uploaded/` copy back; their temp files are deleted. If main reads L528 more literally, this is two lines to drop.

## Crash points: what each leaves behind

| Point | Disk | DB |
| --- | --- | --- |
| Before the temp open, or a reject or skip | unchanged | the rejected or skipped row only |
| After the temp write, before COMMIT (process alive) | temp deleted | rolled back, no row |
| Process killed after the temp write, before COMMIT | `.tmp-<id>-<sha>` | rolled back; at start-up the hash does not match (or there is no row), so the temp is deleted |
| COMMIT fails with `DatabaseUnavailable` | temp kept | unknown; start-up renames or deletes it by the row |
| After COMMIT, rename fails or the process is killed | temp, plus the old `policy-<id>.bit` or none | committed; the `success` row is written if the process is alive. Start-up or rebuild renames the temp |
| After the rename | `policy-<id>.bit` new | committed and recorded |

Residual risk: after a kept temp (an unknown commit), a second upload of the same bytes for the same policy before the next start-up hits `O_EXCL` and gets a 500. That is fail-closed, and the next restart or rebuild clears it.

## Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (287 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: pass.
- `tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` (from `manager/`, CI=true plus the RYUK variable): **202 passed**, after the `__post_init__` change.
- A throwaway smoke run on PostgreSQL, in the scratchpad and not kept. All of these passed: an upload under a hostile byte name gives only `policy-<id>.bit`, mode 0600, with identical bytes. A rejected re-upload leaves the file identical. A symlink planted at the temp path gives an `OSError`, with the victim, the old file and the link unchanged. A failing `os.replace` after commit leaves the temp, and `finish_interrupted_uploads` then renames it and deletes `.tmp-x` and a symlinked `.tmp-5-ab` (result 1 renamed, 2 deleted, victim untouched). A fault in the directory fsync before commit leaves `uploaded/` empty. A 409 for a server-folder name leaves `uploaded/` empty.

## Cases for the tester (TP-M7-15)

- All REQ-163 (1) names, given as bytes (the multipart header) and as `str`: a snapshot of `uploaded/` before and after shows only `policy-<id>.bit`, and `bit_import.file_name` equals `client_file_name(raw)`. A missing name gives `""`, and 5,000 characters give 255.
- A symlink at `.tmp-<id>-<sha>`, pointing at a file outside: the import raises, there is no row, the catalog checksums are unchanged, the target's bytes and the link are unchanged. Also a regular file planted there: it is not deleted.
- Faults: `before_commit` failing mid-write (an `os.write` fault) or at fsync leaves no temp; a COMMIT failure surfacing as `DatabaseUnavailable` keeps the temp, and start-up then decides; an `os.replace` fault after commit leaves one `success` row and the temp, which start-up renames (REQ-165 (1)).
- `finish_interrupted_uploads`: committed (renamed), uncommitted (deleted), `.tmp-x`, a symlink temp (deleted, target untouched), a temp whose content does not match its name, a temp for a deleted policy (deleted), a `.tmp-0012-…` (leading zero) and a 30-digit id (deleted, no DB error), a FIFO named `.tmp-…` (no hang; deleted), and non-temp files left alone.
- `FileInput` with a mismatched `sha256` and `target.file_sha256`, or with `data` not matching, raises `ValueError`.
- Carry (a), the tester's: the caller holds the lock around `import_upload` and `finish_interrupted_uploads`, and a concurrent upload and rebuild serialise.

## Revision 1 (lead ruling "A missing `bits/uploaded/` folder", `work/decisions.md`)

- `finish_interrupted_uploads` (`uploads.py:189`): if `os.scandir(uploaded/)` raises `FileNotFoundError`, the function logs one warning with fixed words ("interrupted uploads: uploaded folder missing, nothing to finish"), returns `FinishedUploads(0, 0)` and creates nothing. Start-up therefore goes on to reconcile the server folder. The docstring says so. Other errors, such as `NotADirectoryError` or `PermissionError`, still propagate.
- `import_upload` with a missing `uploaded/`: **unchanged, confirmed.**
  - What happens: `_Upload.write` opens `uploaded/.tmp-<id>-<sha>` with `O_CREAT` and gets `FileNotFoundError` (ENOENT). This happens inside transaction 1, which therefore rolls back. `import_one` propagates the error and writes no `bit_import` row (#98 (j)), and TASK-162 maps the error to 503. `discard` has nothing to remove, and nothing is created.
  - Exception: a rejected or skipped upload never reaches `before_commit`, so it still gets its normal row.
  - Evidence: a throwaway PostgreSQL smoke check in the scratchpad (not kept) with no `uploaded/` folder. `import_upload` raises `FileNotFoundError`, with 0 `bit_import` rows, 0 `policy` rows and the folder still empty. Then `finish_interrupted_uploads` returns `(0, 0)`.
- The manager creates the folder nowhere.
- Choices (1)–(3) are unchanged; the lead has accepted them.
- Gates:
  - ruff check, ruff format check and `mypy --strict` pass (291 files);
  - `tests/test_uploads.py tests/test_uploads_pg.py tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` give 339 passed.

## Revision 2 (user ruling "Folder guard"; lead row "Folder guard details" (2))

**Probe before the change: yes, a symlink was followed.** `O_NOFOLLOW` guarded only the temp file's own name. With `bits/uploaded -> <scratch dir>`, the temp file would be created in the scratch dir and renamed there, `finish_interrupted_uploads` would list it and unlink there, and `delete.remove_after_commit` would unlink `policy-<id>.bit` there.

**Change:**
- `uploads.py:58` `open_uploaded_dir(folder) -> int`: public. It is `os.open(bits_dir/"uploaded", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)`. A missing, symlinked or non-directory `uploaded/` raises `OSError`; on Linux a symlink gives `NotADirectoryError`.
- `_Upload` (`uploads.py:81`–`121`) opens that handle in `write`, as the first step of `before_commit`. The temp-file open (`dir_fd=`), the directory fsync, the rename (`os.replace(..., src_dir_fd=, dst_dir_fd=)`, `:107`) and the cleanup unlink (`os.unlink(..., dir_fd=)`, `:116`) all run relative to it. `discard` closes it.
  - So an upload with a bad `uploaded/` raises inside transaction 1. That is an internal error: rollback, no row, and TASK-162 maps it to 503.
  - A rejected or skipped upload never opens the folder, so it still gets its row (as in r1).
  - `_Upload`'s first field is still the `uploaded/` path, and `_fsync_dir` now takes the directory fd.
- `finish_interrupted_uploads` (`uploads.py:191`): it opens the handle first. On any `OSError` (missing, symlink, not a directory, no permission) it logs one fixed line, "interrupted uploads: uploaded folder unreadable: <ErrorType>", returns `(0, 0)` and touches nothing. Otherwise `_finish` (`:217`) does the listing (`os.listdir(dir_fd)`), the hashing reads (`_temp_hash(name, dir_fd)`, `O_NOFOLLOW`), the renames and the unlinks relative to the fd.
- `delete.py:115` `remove_after_commit` (lead-approved edit of that one function). This is the one removal path used by `delete_policy`, `import_one` (`move_upload`) and `folders.py`.
  - It filters names as before. It then opens `uploaded/` through `open_uploaded_dir` and unlinks with `dir_fd=`.
  - If the folder is unreadable it logs "upload removal skipped: uploaded folder unreadable: <ErrorType>", leaves the copy and does not raise; the integrity check reports the copy.
  - A missing file is ignored, as `missing_ok` was. Any other `OSError` is logged by type.
  - The import of `open_uploaded_dir` is inside the function, because `uploads` imports `pipeline`, which imports `delete` (a cycle at module level).
- The folder is never created anywhere. The bits folder itself is not guarded here (out of scope; TASK-156 r2).
- Files in r2: `uploads.py` and `delete.py`. Task total: `uploads.py`, `pipeline_record.py`, `delete.py`, and this report. I ran `ruff format` over `services/importer/`. The check before that already passed on every file there, so only my own `delete.py` lines were reformatted. `folders.py` shows as modified in git, but that is impl-manager-156's in-progress work, not mine.

**Probe after the change** (throwaway scripts in the scratchpad, PostgreSQL):
- `uploaded/` is a symlink to a scratch dir holding a planted `.tmp-1-<hex>`, or `uploaded/` is a regular file. In both cases `import_upload` raises `OSError`, with 0 `bit_import` rows and 0 `policy` rows. `finish_interrupted_uploads` returns `(0, 0)`. The scratch dir still holds only the planted file.
- `remove_after_commit(bits, ["uploaded/policy-3.bit"])` with `uploaded -> ../v` logs the "unreadable: NotADirectoryError" line and leaves `v/policy-3.bit`. With a real `uploaded/` it removes `policy-3.bit`, and a missing `policy-4.bit` raises nothing.

**Gates:**
- ruff check, ruff format check and `mypy --strict` pass (291 files).
- `tests/test_uploads.py`, `test_uploads_pg.py`, the TASK-154 suites, `test_policy_delete_pg.py` and `test_folders_pg.py`: 455 passed and **4 failed**. The 4 are tester spies tied to the old call shapes, not product faults:
  - `test_uploads_pg.py::test_temp_open_flags_flush_then_commit_then_rename` (`spy_replace`): the spy must accept `**kw` (`src_dir_fd`, `dst_dir_fd`);
  - `test_uploads_pg.py::test_a_fault_between_commit_and_rename_is_finished_at_the_next_start` (`broken`): the same;
  - `test_uploads_pg.py::test_a_new_policy_whose_rename_failed_gets_its_file_from_finish` (`broken`): the same;
  - `test_uploads.py::test_discard_logs_only_the_error_type_when_removal_fails`: it patches `Path.unlink`, but the removal is now `os.unlink(name, dir_fd=...)`, so it should patch `os.unlink`.

**Cases for the tester (r2):**
- `uploaded/` as a symlink to a real directory (with and without planted `.tmp-*` and `policy-*.bit` there), as a regular file, as a dangling symlink, and missing. For each:
  - `import_upload` raises with no row and no catalog change, and nothing in the link target changes;
  - a rejected upload still gets its row;
  - `finish_interrupted_uploads` returns `(0, 0)` with one log line and nothing in the target touched.
- The `move_upload` path: a server-folder file takes an uploaded policy's name while `uploaded/` is a symlink. The catalog move commits, the copy in the link target is left, the "upload removal skipped" line is logged, and nothing raises. With a real `uploaded/` the copy is removed.
- The `delete_policy` and `folders.py` removals go through the same function: the symlinked `uploaded/` leaves the copy and does not raise.
- Swapping `uploaded/` for a symlink after `write` opened the handle (between commit and rename): the rename still lands in the original directory, through the fd.
