# TASK-155 REVIEW: uploads and the start-up finish of interrupted uploads

Verdict: APPROVED (r0 and revision 1)

Reviewer: reviewer-m7, 2026-10-28. REQ-163, REQ-165 (1). High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: `manager/bitscan_manager/services/importer/uploads.py` (268 lines, 235 non-blank), per `work/reports/TASK-155-impl.md` including "Revision 1". One file.

TEST: PASS (`work/reports/TASK-155-test.md`, tester-m7).
- 38/38 on PostgreSQL in WSL (Linux only: symlinks, FIFOs, modes). Whole-tree gates are clean (289 files).
- 17 plants: 15 red, and 2 equivalent mutants that are each red in a combined plant.
- #102 (c) is NOT RUN; it belongs to TASK-159.

**The two equivalent mutants: the claim holds.**
- u2 (`O_NOFOLLOW` dropped from the temp open): POSIX says `O_CREAT | O_EXCL` fails when the last path component exists, and that includes a symlink, whatever it points at. So behaviour can't differ. The TS L522 flag pin catches the plant, and that pin is the right check.
- u13 (the finish lists with `follow_symlinks=True`): `_content_sha256` still opens with `O_NOFOLLOW`, so a symlink gives no hash and is unlinked, and unlinking never follows it. The result is the same either way. u13 combined with u4 is red, which proves the read flag carries the protection.

Spec read: TS §4.1 L522, L526, L528, §8.1, §8.7 L1344, L1377, L1395; #98 (j), #99 (b), (d), (e); the crash-window ruling (2026-10-27); decisions 2026-10-28 "TASK-156 case (c) success" (the r1 API).

## Checks
1. **Client name (TS L522, #99 (d)).**
   - It is stored only as `bit_import.file_name`, in the #99 (d) form. The lone-surrogate rule is extra, and needed for PostgreSQL text (checklist 1).
   - Paths are built from `policy_id` and the hash only, and the name never reaches a log (CHK-M7-200, plant u11).
2. **Temp file (TS L522).**
   - `uploaded/.tmp-<id>-<sha256>` is created with `O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW`, mode 0600, and fsynced along with its folder.
   - It is written in `before_commit`, the last step of transaction 1.
   - A planted symlink, file or FIFO makes the import fail with nothing written (CHK-M7-201).
3. **Commit and rename (TS L522, L526).**
   - The rename (`os.replace`) runs after the commit, inside the caller's catalog lock; `upload()` takes the lock itself.
   - A rollback discards only a temp file this stage created.
   - A failed rename leaves the temp file. The `success` row is still written, and the error propagates. This closes my TASK-154 carry.
4. **Start-up finish (TS L528).** A temp file is renamed only when all of these hold: the name is in the exact form, it's a regular file read with `O_NOFOLLOW | O_NONBLOCK` (5 MiB or less), the policy is live with `source_file` `uploaded/policy-<id>.bit`, and the content hash equals `source_sha256`. Every other `.tmp-` entry is unlinked without following it, and nothing else is touched.
   - The extra live and `source_file` conditions only ever lead to a delete. They keep the crash-window ruling (a deleted policy never comes back) and keep server-folder policies out of `uploaded/`, so I accept impl reading 1.
   - The window between the hash read and the rename needs write access to the manager-owned `uploaded/` folder (0750), which is the TS §8.1 accepted risk, as the tester notes.
5. **Rejection and refusal.** A rejected upload never reaches `before_commit`, so the stored file is byte-identical (REQ-163 (3)). `PolicyManagedOnServer` writes no row or file (#99 (e)).
6. **r1 API.** `UploadStage` and `staged_upload` behave exactly like the r0 code. `upload()` uses them, and the stage exits inside the lock.
7. **Security invariants.** No client text or file content reaches a log, and log lines carry only types and counts. There is no SQL text here.

## Findings
None blocking or should-fix.

1. nit, `uploads.py:164-168` with `pipeline.py:113`: if the COMMIT statement itself fails in a way that may still have committed (the connection dropped after COMMIT was sent), `discard()` removes the temp file. If the commit did land, `uploaded/policy-<id>.bit` keeps the old bytes and the start-up reconcile would re-import them. Keeping the temp file whenever the commit outcome is unknown would be safe, because the start-up finish renames it only on a hash match and deletes it otherwise. The window is very rare; a later revision could leave the temp file on a failure raised by the commit itself.
2. nit, `uploads.py:199`: `file_exists` uses `Path.exists()`, which follows symlinks, while `folders.is_bit_file` uses `lstat`. BIT007 doesn't apply to uploads, so it doesn't matter today.
3. nit, `uploads.py:238`: `finish_interrupted` raises `FileNotFoundError` if `uploaded/` is missing, while `folders.discover` treats a missing folder as empty. The package creates the folder (TS L1344), so this is a consistency point only.
4. Carried to TASK-159: #102 (c). `UploadStage.after_commit` and `finish_interrupted` are the two places that rename or delete in `uploaded/`.
5. Carried to TASK-162: the `O_EXCL` clash (`FileExistsError`) maps to 503 (#98 (j), impl reading 2).
