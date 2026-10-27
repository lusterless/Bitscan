# TASK-155 TEST: PASS (r0, r1 and r2)

Tester: tester-m7-155b, 2026-10-27. This continues the files that tester-m7-155 left when the container restarted (snapshot d6e60d6). Covers REQ-163 (1)–(6) and REQ-165 (1). Spec: TS §4.1 L516–L532 (L522, L526, L528), §4.6, §8.7 (L1344, L1377). Answers and rulings used: #99 (d) and (e), #101, #98 (j). Decisions (2026-10-27): "Crash window ruling", "Rebuild finishes interrupted uploads first", "TASK-154 REVIEW APPROVED … Carried" (a) and (b), and "TASK-155 built … lead rulings" (1)–(3). Checks: TP-M7-15, CHK-M7-200 to -204, the REQ-165 (1) half of CHK-M7-230, and mutation rows CHK-M7-357 to -359.

Files under test: `manager/bitscan_manager/services/importer/uploads.py` and `FileInput.__post_init__` in `pipeline_record.py`. No product file was changed.

Tester files:
- `manager/tests/test_uploads.py`: 74 tests, no database. They cover the #99 (d) name form (bytes and `str`), the 255-character cut, lone surrogates, the `FileInput` mismatches, the rename guard and the discard log.
- `manager/tests/test_uploads_pg.py`: 63 tests, on PostgreSQL with a temporary bits folder per test.

Changes this session to the snapshot:
- (1) The hostile-name test no longer assumes `/abs.bit` is absent. It compares the state (inode, mtime, hash) of `/abs.bit`, `/x.bit` and `/a/b.bit` before and after the upload. The predecessor's plant run of "client name as path" had left a root-owned `/abs.bit` (a generated "Hostile …" policy, 19:29:56). That file failed 21 rows of the control run and made its plant log worthless, so every plant was redone.
- (2) New: `test_two_concurrent_uploads_of_one_policy_serialise`.

## Runs (Linux container, Docker PostgreSQL 16, `CI=true`, Ryuk pinned, nothing skipped; from `manager/`)

| Run | Command | Count |
| --- | --- | --- |
| r0 (snapshot as found) | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | 115/136 passed, 21 failed: all `hostile…[i]`, `assert not Path("/abs.bit").exists()`. This was a test bug from the leaked file, not a product failure |
| r1 | same, after (1) and (2) | **137/137 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (TASK-154 suites) | `pytest -n 4 tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | **202/202 passed** |
| r3 (affected set) | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py tests/test_import_store_pg.py tests/test_catalog_lock_pg.py tests/test_policy_delete_pg.py tests/test_bit_fixtures.py tests/test_import_alerts_pg.py` | **439/439 passed** |
| r4 (coverage) | `pytest -n 2 --cov=bitscan_manager.services.importer` on the 2 files | 137/137 passed. `uploads.py` 122/122 lines (100 %), `pipeline_record.py` 68/68 (100 %) |
| static | `ruff check` and `ruff format --check` on the 2 files; `mypy --strict --config-file manager/pyproject.toml manager` | ruff clean. mypy: no error in the TASK-155 files; 17 errors, all in `test_folders_pg.py` (another tester's, in progress against TASK-156 r1) |
| plants control | copy `scratchpad/t155/r2/base`, `PYTHONPATH` = the copy (the printed `uploads.__file__` is the copy's) | 137/137 passed |

## Report rows (tests/m7/report.md format, to be folded by the lead)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-200 | APP | Linux/PG | r1 `test_a_hostile_client_name_lands_only_as_policy_id_bit[0..20]`, `test_a_client_name_naming_another_policy_never_touches_its_file`, `test_uploads.py` name rows | PASS | 21 names, as bytes and as `str`. They include every REQ-163 (1) name (`../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, 5,000 chars, NUL, CR, LF, `<script>`, RLO, invalid UTF-8), plus `uploaded/../../x.bit`, `policy-1.bit`, `.tmp-1-<hex>`, a lone surrogate and 5,000 × `é`. The tree diff of the whole tmp root is exactly `{bits/uploaded/policy-<id>.bit: (file, 0600, sha(data))}`. `/`-level targets and `/etc/passwd` are unchanged. `file_name` equals `client_file_name(raw)` and the literal #99 (d) values; it is ≤ 255 characters with no C0 or DEL. A name equal to another policy's stored file leaves that file byte-identical | 2026-10-27 |
| CHK-M7-201 | APP | Linux/PG | r1 `test_a_symlink_at_the_temp_path_…`, `test_a_dangling_symlink_…`, `test_a_regular_file_at_the_temp_path_…`, `test_a_directory_at_the_temp_path_…`, `test_a_symlink_at_the_final_path_…` | PASS | A planted symlink, dangling link, regular file or directory at `.tmp-<id>-<sha>` → `OSError` (EEXIST or ELOOP). There is no `bit_import` row and no audit entry, the catalog checksums and counters are unchanged, and the tree under the tmp root is identical: the link, its target's bytes and mode, the planted file and the old `policy-<id>.bit` are all kept. A dangling link's target is never created. A symlink at the final path is replaced by a regular file, and the victim is unchanged | 2026-10-27 |
| CHK-M7-202 (3) | APP | Linux/PG | r1 `test_a_rejected_reupload_…`, `test_a_rejected_new_upload_writes_nothing`, `test_a_reupload_replaces_only_that_policys_file` | PASS | A BIT003 re-upload → `rejected` with an identical file (inode, mtime_ns, mode) and an unchanged catalog, one `rejected` row with `bad.bit`. A rejected new upload or non-XML writes nothing. A re-upload replaces only that policy's file | 2026-10-27 |
| CHK-M7-202 (4) before commit | APP | Linux/PG | r1 `test_a_fault_after_the_temp_open_and_before_commit_leaves_no_temp[write, fsync, dirsync × new, update]` | PASS | A partial `os.write` (ENOSPC), an `fsync` EIO or a directory-fsync EIO → `OSError`. The tree is identical (no temp, old file kept), with no catalog change, no row, no entry and no counter | 2026-10-27 |
| CHK-M7-202 (4) at commit | APP | Linux/PG | r1 `test_a_failed_commit_keeps_the_temp_and_finish_deletes_it_when_not_committed`, `test_a_commit_that_happened_but_reported_unavailable_is_renamed_by_finish` | PASS | Lead ruling (2). Backend killed before COMMIT → `DatabaseUnavailable`, the temp is kept, the catalog is unchanged; `finish` → (0 renamed, 1 deleted), old file kept. COMMIT done but `DatabaseUnavailable` reported → the temp is kept and the row has the new hash; the same bytes uploaded again → `OSError` and the temp is untouched (the accepted 500); `finish` → (1, 0), the new file has mode 0600 | 2026-10-27 |
| CHK-M7-202 (4) after commit | APP | Linux/PG | r1 `test_a_fault_between_commit_and_rename_is_finished_at_the_next_start`, `test_a_new_policy_whose_rename_failed_gets_its_file_from_finish` | PASS | `os.replace` EIO → `OSError`. There is one `success` row (`v2.bit`, TASK-154 deviation (5)) and the row has the new hash; `uploaded/` holds the old file and the temp. `finish` → (1, 0), and the file is the new bytes. A new policy gets its first file from `finish` | 2026-10-27 |
| CHK-M7-203 | APP | Linux/PG | r1 `test_an_upload_of_a_server_folder_policy_is_409_with_nothing_written` | PASS | `PolicyManagedOnServer` with the server policy's id; the tree is identical and `uploaded/` is empty. No `bit_import` row; exactly 1 entry `policy.import_refused`, `policy:<id>`, `user:7`, with no `alert`. No counter and no catalog change | 2026-10-27 |
| CHK-M7-204 | APP | Linux/PG | r1 `test_the_stored_file_is_0600_and_the_service_users[umask 000, 022, 077]`, `test_temp_open_flags_…` | PASS | A regular file with mode 0600 and uid/gid = the process's, under every umask. A re-upload over a file chmodded 0644 gives 0600 again. The open mode argument is 0600 | 2026-10-27 |
| CHK-M7-155-flags | APP | Linux/PG | r1 `test_temp_open_flags_flush_then_commit_then_rename` | PASS | One open with `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW`, no `O_TRUNC` or `O_APPEND`. Order: fsync(temp) < COMMIT, fsync(dir) < COMMIT, COMMIT < `replace(.tmp-<id>-<sha>, policy-<id>.bit)` | 2026-10-27 |
| CHK-M7-230 (1) | APP | Linux/PG | r1 `test_finish_renames_only_full_matches_…` and 9 `test_finish_*` rows | PASS | Renamed only when the name, content hash, live row, `source_file = uploaded/policy-<id>.bit` and `source_sha256` all match (ruling (1)). Deleted: an uncommitted temp, content not matching the name, a symlink temp (the target is not followed, even when its bytes match; the target is kept), `.tmp-x`, `.tmp-`, uppercase hex, a leading zero, extra suffix, negative, id > 2^63−1, a 30-digit id (no DB error), a short hash, a deleted policy (by `source_file` and, as owner, `deleted_at` alone), a policy moved to the server folder, and a FIFO (no hang). Non-temp files are kept. A `.tmp-dir` directory is left and the rest still finish. Empty folder → (0, 0). Missing folder → nothing created, no change. No row, no entry and no catalog change. The log holds no name or content | 2026-10-27 |
| CHK-M7-155-lock | APP | Linux/PG | r1 `test_import_upload_and_finish_never_take_the_catalog_lock_themselves`, `test_the_callers_lock_is_held_at_the_temp_write_and_the_rename`, `test_a_concurrent_upload_and_delete_serialise_…`, `test_a_concurrent_upload_and_server_import_serialise`, `test_two_concurrent_uploads_of_one_policy_serialise` | PASS | Carry (a). Both functions finish while a probe holds the lock, so they take no lock themselves (the contract is documented). The probe cannot take the lock at the write or at the rename. A delete, a server-folder import and a second upload each wait (`pg_locks`, not granted) while the first upload holds the lock after the write or the commit, and run after its rename. The final disk state matches the catalog (deleted → no file; server wins → no copy; the last upload's bytes) | 2026-10-27 |
| CHK-M7-155-fileinput | CODE | Linux | r1 `test_fileinput_raises_on_each_mismatch[6]`, `test_fileinput_accepts_agreeing_hashes[2]` | PASS | Carry (b). `ValueError` when the target hash differs, when both hashes agree but not with the data, for uppercase hex, for empty data, for no data with differing hashes, and for one extra byte. Agreeing inputs and `data=None` with equal hashes are accepted | 2026-10-27 |
| CHK-M7-155 static | CODE | Linux | ruff, format, mypy | PASS | clean for the TASK-155 files | 2026-10-27 |

### Plants (copies `scratchpad/t155/r2/<id>`, control 137/137 green; each run is the 2 files, `-n 4`)

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-357 (a) | `O_NOFOLLOW` removed | PASS (red) | 1: the flags spy. The symlink rows stay green because `O_CREAT \| O_EXCL` alone already refuses an existing link (kernel behaviour) |
| CHK-M7-357 (b) | `O_EXCL` removed | PASS (red) | 3: the flags spy, the planted regular file (overwritten), and the kept-temp re-upload |
| CHK-M7-357 (c) | both removed | PASS (red) | 5: symlink at temp (victim written), dangling symlink (target created), regular file, flags, kept temp |
| CHK-M7-358 | client name used as the stored path | PASS (red) | 48 (`hostile[1]` `/abs.bit` deselected, so the plant cannot write at `/`): 18 hostile rows, the name-of-another-policy row, the 0600 rows and every flow that stores a file |
| CHK-M7-359 (a) | temp kept on rollback (`discard` does nothing) | PASS (red) | 7: 6 before-commit fault rows and the discard log row |
| CHK-M7-359 (b) | rename before commit (in `write`) | PASS (red) | 11: the order spy, both COMMIT-failure rows, both post-commit-fault rows, the rename-guard rows |
| CHK-M7-359 (c) | `discard` deletes a planted entry (`temp` set before the open) | PASS (red) | 4: symlink, dangling, regular file, kept temp |
| CHK-M7-155-P06 | finish: `deleted_at` check removed | PASS (red) | 1: the owner-built deleted row (the app's own delete is also refused by `source_file`) |
| CHK-M7-155-P06b | finish: `source_file` check removed | PASS (red) | 1: the policy moved to the server folder |
| CHK-M7-155-P07 | `FileInput` check removed | PASS (red) | 6: every mismatch row |
| CHK-M7-155-P08 | finish follows links (`O_NOFOLLOW` dropped on read) | PASS (red) | 2: a symlink temp renamed into place |
| CHK-M7-155-P09 | temp not kept on `DatabaseUnavailable` | PASS (red) | 2: both COMMIT-failure rows |
| CHK-M7-155-P10 | mode 0644 | PASS (red) | 25 |
| CHK-M7-155-P11 | controls not replaced | PASS (red) | 20 |
| CHK-M7-155-P12 | no 255 cut | PASS (red) | 7 |
| CHK-M7-155-P14 | finish: content hash not checked | PASS (red) | 3: content ≠ name, symlink, FIFO |
| CHK-M7-155-P15 | `import_upload` takes the catalog lock itself | PASS (red) | 1 |
| CHK-M7-155-P16 | temp not fsynced | PASS (red) | 1: the order spy |

Plants: **18/18 red.** The security plants the lead named (O_NOFOLLOW, O_EXCL, client name as path, temp kept on rollback, rename before commit, finish renaming a deleted policy's file, FileInput check removed) are all red.

## Acceptance coverage

- REQ-163 (1): CHK-M7-200 PASS. (2): CHK-M7-201 PASS. (3) and (4): CHK-M7-202 (all four rows) PASS. (5): CHK-M7-203 PASS. (6): CHK-M7-204 PASS.
- REQ-165 (1): CHK-M7-230 (1) PASS.
- The symlink at the temp path, a fault before commit, and a fault between commit and rename: CHK-M7-201 and CHK-M7-202 PASS. The COMMIT fault: ruling (2) PASS.
- Carry (a): CHK-M7-155-lock PASS. Carry (b): CHK-M7-155-fileinput PASS.

## Findings for the reviewer (none blocking)

1. **A missing `uploaded/` folder.** Resolved by the lead ruling "A missing `bits/uploaded/` folder" and implemented in r1; see "Revision 1" below.
2. **The flags are defence in depth.** With only one of `O_EXCL` / `O_NOFOLLOW` removed, a planted symlink is still refused. Only the flags spy guards each flag on its own, so keep that test.
3. **The deleted-policy guard is two checks.** For an app-deleted policy, `source_file = deleted/<id>` already refuses the rename. `deleted_at IS NULL` matters only for an owner-built inconsistent row, and is tested that way.
4. **Environment:** `/abs.bit` (root-owned, 675 bytes, a generated test policy) was left at the file-system root by the previous tester's plant run. The safety check blocked my removal and I did not work around it. **The user should delete `/abs.bit`.** The tests no longer depend on it.

## Revision 1 (lead ruling "A missing `bits/uploaded/` folder", `work/decisions.md`; commit c26e046)

The change: if `uploaded/` is missing, `finish_interrupted_uploads` logs one fixed warning, returns `(0, 0)` and creates nothing. `import_upload` is unchanged.

Test changes:
- The missing-folder test now asserts the ruling exactly: `(0, 0)`, the folder not created, no row, no entry, no catalog change, and exactly one warning from the `uploads` logger with no path in it.
- New `test_an_upload_with_no_uploaded_folder_fails_closed_with_no_row`: `FileNotFoundError`; nothing is created anywhere under the tmp root; no `bit_import` row, no entry, no counter and no catalog change (#98 (j)). A rejected upload still gets its normal `rejected` row.

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r1-1 | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | **138/138 passed**, 0 failed, 0 errors, 0 skipped |
| r1-2 | `pytest -n 4 tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | **202/202 passed** |
| r1-3 | `--cov=bitscan_manager.services.importer` on the 2 files | 138/138 passed; `uploads.py` 127/127 (100 %), `pipeline_record.py` 68/68 (100 %) |
| r1-static | ruff, ruff format (2 files); `mypy --strict --config-file manager/pyproject.toml manager` | clean; mypy "no issues found in 291 source files" |
| r1-plants | copies `scratchpad/t155/r3/<id>`. Control 138/138; the import path is the copy's | all 18 r0 plants re-applied: each red again, same counts. Plus 4 new plants below |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-230 (1) missing folder | APP | Linux/PG | r1-1 `test_finish_on_a_missing_folder_is_empty_logs_one_line_and_creates_nothing` | PASS | `(0, 0)`, `uploaded/` not created, one warning without a path, no row, entry or catalog change | 2026-10-27 |
| CHK-M7-155-nofolder | APP | Linux/PG | r1-1 `test_an_upload_with_no_uploaded_folder_fails_closed_with_no_row` | PASS | `FileNotFoundError`; the tmp root still holds only `bits/` (empty); no row, entry, counter or catalog change. A rejected upload gets 1 `rejected` row | 2026-10-27 |

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-155-R1a | the missing-folder branch removed (raises again) | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1b | finish creates `uploaded/` | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1c | the log line removed | PASS (red) | 1: the missing-folder test |
| CHK-M7-155-R1d | `import_upload` creates `uploaded/` | PASS (red) | 1: the no-folder upload test |

Plants on r1: **22/22 red** (the 18 r0 plants plus R1a to R1d). Verdict for r1: **PASS**.

## Revision 2 (lead ruling "Folder guard applied to the upload path", user ruling "Folder guard"; working tree after 09fcf66)

The change: `uploaded/` is opened with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` (`open_uploaded_dir`). The temp open, the fsync, the rename, the listing and the unlinks are all relative to that fd. The same applies to `delete.remove_after_commit`. If the folder is missing, a symlink or not a directory:
- the upload fails as an internal error (#98 (j)) and writes nothing through the link;
- the finish step returns `(0, 0)` with one fixed log line;
- the post-commit removal leaves the copy and logs one line.

The rows were drafted from the ruling before r2 landed. The previous run showed that r1 wrote through a symlinked `uploaded/`.

Test changes in `manager/tests/test_uploads_pg.py`:
- **Spies updated for the `dir_fd` call shapes** (the impl's 4 "spy" failures, all test-side):
  - The flags/order test now also asserts the ruling: the folder is opened with `O_DIRECTORY` and `O_NOFOLLOW`, the temp open is relative to that fd, and so are both sides of the rename.
  - The `broken` replace spies accept `**kw`.
  - `test_uploads.py`: the discard-log test patches `os.unlink` as well.
- **New tests:**
  - `test_finish_touches_nothing_when_uploaded_is_not_a_real_directory[file, dir-link, file-link, dangling-link]`;
  - `test_an_upload_writes_nothing_when_uploaded_is_not_a_real_directory[4 kinds × new, update]`;
  - `test_a_rejected_upload_still_gets_its_row_with_a_broken_folder[4]`;
  - `test_the_folder_is_checked_at_each_call_not_cached`;
  - `test_a_server_file_taking_an_uploaded_name_through_a_linked_folder_leaves_the_copy` (`move_upload`);
  - `test_a_delete_through_a_linked_folder_commits_and_leaves_the_copy`, `test_a_delete_with_a_real_folder_still_removes_the_copy`;
  - `test_a_failed_copy_removal_is_logged_by_type_and_never_raises`;
  - `test_a_folder_swapped_for_a_link_after_the_write_renames_in_the_original`.

In every broken-folder case the link target holds a committed temp (it would be renamed if the link were followed), a junk `.tmp-x` (it would be deleted) and the live `policy-<id>.bit`. The tree under the tmp root is compared before and after.

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r2-1 | `pytest -n 4 tests/test_uploads.py tests/test_uploads_pg.py` | **160/160 passed**, 0 failed, 0 errors, 0 skipped (74 + 86) |
| r2-2 (TASK-154 suites + affected) | `pytest -n 4` the 2 files + `test_import_pipeline_pg.py test_import_fuzz_pg.py test_samples_import_pg.py test_policy_delete_pg.py test_folders_pg.py test_import_store_pg.py test_catalog_lock_pg.py` | **522/522 passed** (run before the last new row; that row passed in r2-1) |
| r2-3 (coverage) | `--cov=bitscan_manager.services.importer`, the 2 files | `uploads.py` 136/136 (100 %), `pipeline_record.py` 68/68 (100 %). `delete.py`: with the delete, folder and pipeline suites, every r2 line is covered (152–153 by the new removal-error row) |
| r2-static | ruff, ruff format (2 files); `mypy --strict --config-file manager/pyproject.toml manager` | clean; "no issues found in 291 source files" |
| r2-plants | copies `scratchpad/t155/r4/<id>` (`plant_r2.py`); control 160/160, the import paths of `uploads.py` and `delete.py` are the copy's | **27/27 red** |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-155-guard-finish | APP | Linux/PG | r2-1 `test_finish_touches_nothing_…[file, dir-link, file-link, dangling-link]` | PASS | `(0, 0)`; the tree is identical (the committed temp in the link target is not renamed and `.tmp-x` is not deleted); the dangling target is not created; no row, entry or catalog change; exactly 1 warning, with no path, entry name or folder name | 2026-10-27 |
| CHK-M7-155-guard-upload | APP | Linux/PG | r2-1 `test_an_upload_writes_nothing_…[8]`, `…_rejected_upload_still_gets_its_row_…[4]`, `…_not_cached` | PASS | `OSError` for new and update; the tree is identical (nothing written, renamed or deleted in the target); no row, entry, counter or catalog change (#98 (j)); the client-name canary is not logged. A rejection still gets its `rejected` row. Swapped to a link after a good upload → refused; restored → success | 2026-10-27 |
| CHK-M7-155-guard-removal | APP | Linux/PG | r2-1 `test_a_server_file_taking_…`, `test_a_delete_through_a_linked_folder_…`, `test_a_delete_with_a_real_folder_…`, `test_a_failed_copy_removal_…` | PASS | Through a linked folder: the catalog move or delete commits, nothing raises, the copy behind the link is byte-identical, and "upload removal skipped" is logged with no path. With a real folder the copy is removed. An `EACCES` on the unlink → `upload removal failed: PermissionError`, the copy is left, the delete commits | 2026-10-27 |
| CHK-M7-155-guard-fd | APP | Linux/PG | r2-1 `test_temp_open_flags_…`, `test_a_folder_swapped_for_a_link_after_the_write_…` | PASS | The folder is opened `O_DIRECTORY \| O_NOFOLLOW`; the temp open and both rename sides use that fd. `uploaded/` swapped for a link to a decoy between commit and rename → the file lands in the original directory, and the decoy holds only `keep` | 2026-10-27 |
| CHK-M7-200 to -204, -230 (1) | APP | Linux/PG | r2-1 | PASS | every r0 and r1 row passes unchanged on r2 | 2026-10-27 |

| Check | Plant | Result | Red tests |
| --- | --- | --- | --- |
| CHK-M7-155-G1 | `dir_fd` removed: the folder opened by path, following links; the temp open and the rename by path | PASS (red) | 5: the flags/fd spy, the dir-link upload (new, update), not-cached, the swap |
| CHK-M7-155-G2 | `O_DIRECTORY` dropped from the folder open | PASS (red) | 2: the flags spy, finish with a regular file (raised `NotADirectoryError` instead of `(0, 0)`) |
| CHK-M7-155-G3 | `O_NOFOLLOW` dropped from the folder open | PASS (red) | 7: the flags spy, dir-link finish, the dir-link upload (2), not-cached, both linked-folder removals |
| CHK-M7-155-G4 | finish raises instead of returning `(0, 0)` | PASS (red) | 5: missing plus the 4 kinds |
| CHK-M7-155-G5 | `remove_after_commit` opens the folder following links | PASS (red) | 2: the `move_upload` and delete rows |
| CHK-M7-155-G6 | rename by path instead of by fd | PASS (red) | 2: the fd spy, the swap |
| CHK-M7-155-R1b, R1c, R1d (on r2) | finish creates the folder; no log line; the upload creates the folder | PASS (red) | 1, 5, 4 |
| r0 plants re-applied on r2 (P01–P17, adapted to the fd call shapes) | as in r0 | PASS (red) | same counts as r0, except P03 at 58 (more flows store a file) |

Plants on r2: **27/27 red.** Verdict for r2: **PASS**. One note: under P03 the rename is relative to the fd, but an absolute client name still escapes the fd. That is why the `/abs.bit` row stays deselected in plant runs (see the `/abs.bit` note above).
