# TASK-156 REVIEW: folders (discovery, `auto` reconcile, `uploaded/` classification)

Verdict: APPROVED (r0 and revision 1)

Reviewer: reviewer-m7, 2026-10-28. REQ-159, REQ-164 (2), REQ-165 (3). High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: `manager/bitscan_manager/services/importer/folders.py` (251 non-blank lines), per `work/reports/TASK-156-impl.md`. One file. The size was accepted by the lead (decisions 2026-10-28, "TASK-156 staging extension and size").

TEST: PASS (`work/reports/TASK-156-test.md`, tester-m7).
- 30/30 on PostgreSQL in WSL. 15/15 plants red. Whole-tree gates are clean (289 files).
- The watcher rows REQ-164 (1), (3)–(5) are NOT RUN; they belong to TASK-159.
- The "Gap fix" section closes my nit 1: the BIT007 symlink row now goes red under plant f13.

Spec read: TS §4.1 L515, L522, L524, L526, L528, §4.3 L550, §4.6; SR §3.6 step 2, §4.1 BIT007; #15, #99 (b), #102 (b), #103; the crash-window ruling and its follow-up (2026-10-27); decisions 2026-10-28 "TASK-156 case (c) success", "TASK-156 staging extension and size" and "TASK-157 rulings" (3)–(4).

## Checks
1. **Discovery (TS L524, #102 (b)).**
   - A file counts only if it is a regular `*.bit` file directly in either folder (`scandir(follow_symlinks=False)`) and isn't hidden, so temp files never count.
   - An unstorable name gets one fixed log line and no row.
   - C1 controls are refused too, which is stricter and errs toward skipping.
2. **Read once (TS L516).** The file is opened with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and checked with `fstat` to be a regular file. It is hashed while it is read, and the buffer stops growing at 5 MiB plus one chunk. An oversize file is passed as `data=None` with the full hash, so it becomes a BIT001 row (#99 (b)).
3. **How files reach `decide()` (row (a)–(c), crash-window ruling).**
   - A server file becomes `Target("server", name)`.
   - An `uploaded/` file is classified under the lock and is always an upload target (r3 `Target` guard; row (iv), plant f3).
   - A leftover is removed with no row, and the policy stays deleted (row (ii)).
4. **Case (c) success and the staging extension (both 2026-10-28 rulings).**
   - The bytes are staged through the TASK-155 r1 API, so the temp, commit and rename rules are unchanged.
   - The foreign (c) file is unlinked only after the rename succeeds.
   - A file already at its policy's own name isn't staged (the `staged` guard, plant f9).
   - Rejected and refused files stay for #103.
5. **Reconcile order (TS L528, §4.3 L550).** Imports come first, in #15 order: recorded files, then the bytes of the UTF-8 path. Deletions follow (`delete_in_tx`, reason "file removed", which raises the `policy_deleted` alert, then `remove_after_commit`). So a replaced file is a move, not a revive (REQ-159 (2), plant f6). `refuse_server_folder` stays off here, which is correct for a removed server file.
6. **Lock and state.** Every step runs under the caller's catalog lock. Classification and import read state in their own transactions under that lock, and nothing else changes `source_file` or `deleted_at` without the lock (checklist 9).
7. **Security invariants.** Symlinks are never followed in discovery, read, BIT007 `file_exists` (now proved by the gap-fix row) or deletion (`lstat`). No file name or content is logged; the leftover line names the policy id only. There is no SQL text here.
8. **Revision 1 (rename only, "TASK-157 rulings" (3)–(4)).**
   - `_read` became `read_file` and `_Relocate` became `Relocate`; no reference to the old names remains.
   - The file is still 251 non-blank lines, and ruff and mypy are clean.
   - The re-test is 30/30, and plants f5, f8 and f9 are red on the new names ("Revision 1" in the test report).

## Findings
None blocking or should-fix.

1. Closed (test gap fixed by tester-m7, "Gap fix" section): the BIT007 symlink row now points at a valid `.bit` file holding the same policy, and goes red under plant f13.
2. nit, `folders.py:197`: `prepare(data)` runs under the caller's catalog lock (the TASK-154 nit 1). For the watcher (TASK-159), consider reading and preparing before the lock and re-checking the hash under it.
3. nit, `folders.py:241`: the leftover line "removed the leftover upload …" is logged even when the unlink just failed (that failure is logged on the line before). Log it only after a successful unlink.
4. Carried to TASK-158: an internal error (database or disk) on one file propagates out of `reconcile`, skipping the remaining files and the deletion pass. The start-up retry must re-run the whole reconcile, and deletions must never run after a partial import pass.
5. Carried to TASK-159: the #102 (c) self-event record must cover the `Relocate` unlink and `_remove_leftover`, as well as TASK-155's rename and finish.
