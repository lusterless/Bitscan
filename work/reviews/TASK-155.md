# TASK-155 REVIEW: uploads on disk and interrupted uploads (r0 + r1 + r2)

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-163, REQ-165 (1); #99 (d), (e). High risk (importer; two approvals).

Scope: frozen worktree `8780eba`. Per `work/reports/TASK-155-impl.md` (Revisions 1 and 2):
- `services/importer/uploads.py` (new, 247 lines, about 150 code lines; size accepted by the lead);
- `delete.py` `remove_after_commit` (edited in r2 with the lead's permission);
- `pipeline_record.py` (`FileInput.__post_init__`, my TASK-154 carry).

TEST: PASS (`TASK-155-test.md`, r0–r2: 160/160, affected set 522/522, 27/27 plants red).

Re-run by me: `test_uploads*.py`, `test_folders_pg.py`, `test_import_pipeline_pg.py`, `test_policy_delete_pg.py` and `test_catalog_lock_pg.py` gave 501 passed. `ruff`, `ruff format` (291 files) and `mypy --strict manager` are clean.

Rulings applied: "TASK-155 built … lead rulings" (1)–(3), "A missing `bits/uploaded/` folder", "Folder guard", "Folder guard applied to the upload path", and "Folder guard details" (2).

## Checks
1. **Temp file (TS §4.1 L522, §8.7).**
   - `uploaded/` is opened once with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
   - The temp file is created relative to that fd with `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`, mode 0600. It is written fully, then the file and the directory are fsynced, as `before_commit`, so it is the last step in transaction 1.
   - The rename after commit goes through the same fd. The source name is checked against the stored `source_file` and this upload's sha.
   - `discard` deletes the temp unless the commit happened or its outcome is unknown (`DatabaseUnavailable`, lead ruling (2)).
   - No path is built from client text. The name holds only `policy_id` and the hex sha, so it is never absolute and cannot escape `dir_fd`. The tester's absolute-path plant escapes only because the plant makes the name absolute.
2. **Folder guard on the upload path.**
   - If `uploaded/` is missing, a regular file, a symlink to a directory or file, or a dangling link, the `open` fails. That `OSError` comes from `before_commit`, so transaction 1 rolls back with no row (#98 (j); TASK-162 answers 503). Nothing is written through the link, and the manager never creates the folder.
   - The tester also swapped `uploaded/` for a link between commit and rename: the file still lands in the original directory through the fd.
3. **`finish_interrupted_uploads` (REQ-165 (1), crash-window ruling).**
   - An unreadable folder gives one fixed log line and `(0, 0)`, and nothing is touched.
   - Listing, hashing (`O_NOFOLLOW|O_NONBLOCK`, `S_ISREG`, capped at 5 MiB + 1), rename and unlink all go through `dir_fd`.
   - It renames only when the hash equals the name and the live policy has that `source_sha256` and the `uploaded/policy-<id>.bit` source file. Every other `.tmp-*` entry is removed (a link is removed, never followed). `_parse_temp` bounds the id to BIGINT.
4. **`remove_after_commit` (`delete.py`, approved TASK-152 code).**
   - Only `uploaded/policy-<n>.bit` paths are accepted, as before. The unlink now goes through the `uploaded/` directory fd.
   - If the folder is unreadable, the copy is left and one line is logged, per "details" (2). A missing file is ignored, and other errors are logged by type only.
   - The function-local import is there to break the `uploads → pipeline → delete` cycle, and is acceptable.
5. **Client name (#99 (d)).** It is decoded as UTF-8 with replacement; NUL, C0 controls and DEL become U+FFFD; it is cut to 255 characters. It is only ever `bit_import.file_name`.
6. **TASK-154 carries.**
   - (a) Lock: the caller holds it. `test_two_concurrent_uploads_of_one_policy_serialise`, the upload-versus-delete and upload-versus-server-file serialisation tests, and the lock-held-at-write-and-rename tests pass, and plant P15 is red.
   - (b) `FileInput.__post_init__` now refuses a hash that differs from `target.file_sha256` or from `sha256(data)`, failing closed.
7. **Logs.** There are no file names, content or tokens; exception type names only.

## Tester's points
- **O_EXCL and O_NOFOLLOW are each redundant against a planted link:** keep the flags-spy test. It is the only test that pins each flag, and both are required by the task row.
- **`deleted_at IS NULL` matters only for an owner-built row:** agreed. It is defence in depth, cheap, and tested that way.
- **`/abs.bit` left at the file-system root by an earlier plant run:** this is an environment issue for the user, not product. I have not touched it.

## Findings
None blocking or should-fix.

1. nit, `uploads.py:150`: `file_exists=lambda rel: (bits_dir / rel).is_file()` follows symlinks. `folders.present` is the guarded form with the same meaning, so use it for consistency. It is harmless for an upload target today.

## Revision 3 re-review (2026-10-28)

Verdict: APPROVED

Frozen worktree `ed228ea`: the product code of `1be4769` plus both final test reports. r3 changes:
- `uploads.open_uploaded_dir(bits_dir)` now opens the bits folder with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`, then `uploaded` relative to that fd with the same flags;
- the three callers pass `bits_dir`: `_Upload.write`, `finish_interrupted_uploads` and `delete.remove_after_commit`.

This closes the r4 TEST FAIL, where a swapped bits folder was followed by the leftover removal, `delete_removed` and the server-wins move. All three now go through `remove_after_commit`. A grep shows no path-based open of `uploaded/` is left: `folders.discover` lists names only, and every read goes through `folders._open_folder`.

TEST: PASS (`TASK-155-test.md` "Revision 3": 172/172, affected set 419/419, 30/30 plants red). The new rows cover a symlinked, regular-file and dangling bits folder, for the finish step, a new upload, an update, the delete and `move_upload` removals, and a swap between commit and rename.

Re-run by me: the uploads, folders, pipeline, delete, catalog-lock and store files gave 588 passed. `ruff` and `mypy --strict manager` (291 files) are clean.

Tester's note: a plant that opens `uploaded` by path after the no-follow check on the bits folder is caught only by the flags spy. The real code opens `uploaded` relative to the bits-folder fd, so there is no window between two path lookups to race. Keep the flags-spy test, since it is the pin.

## Findings
None blocking or should-fix. The r0–r2 nit (`uploads.py:150`, `file_exists` follows links) is carried to TASK-160/162 (decisions.md).
