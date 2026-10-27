# TASK-156 REVIEW: folders, discovery and the automatic reconcile (r0 + r1 + r2)

Verdict: CHANGES_REQUESTED

Reviewer: reviewer-m7, 2026-10-27. REQ-159, REQ-164, REQ-165 (3); #15, #102, #103. High risk (importer; two approvals).

Scope: frozen worktree `8780eba`, `services/importer/folders.py` (new, 311 lines, 207 code lines; size accepted by the lead), per `work/reports/TASK-156-impl.md` (Revisions 1 and 2).

TEST: PASS (`TASK-156-test.md`: r1 and r2, 111/111, affected set 383/383, 10/10 r2 plants red). My re-run is in TASK-155.md (501 passed, gates clean).

Rulings applied: "TASK-156 built" (stray), the edited-name skip (user), "TASK-156 r1 built", "Folder guard" (user) and "Folder guard details" (1).

## Checks
1. **Discovery (#102).**
   - Only regular `*.bit` files directly in the folder count: case-sensitive, not hidden, storable as UTF-8 within 255 bytes, no control characters. Symlinks, FIFOs, devices and subfolders are skipped. An unstorable name is logged without the name.
   - `read_input` opens with `O_NOFOLLOW|O_NONBLOCK`, checks `S_ISREG`, reads once, and hashes the whole file when it is over 5 MiB (#99 (b)).
2. **Classification (crash-window ruling; shared with TASK-157).**
   - `live` is the live policy's own `source_file`. It is imported as an upload target and skipped in `auto` when unchanged, unless its `<PolicyName>` was edited; then it is skipped and listed in `renamed`.
   - `leftover` is a deleted policy's file. It is removed, with no row, and listed as a #103 difference.
   - `stray` is everything else: skipped, with no row, and listed.
   - `uploaded/` files are never server targets.
3. **Order (#15, TS §4.1 L524).** Server files come first (existing `source_file`s first, then by UTF-8 bytes), then uploads. Deletions run after the imports, so a rename in the server folder moves its policy (REQ-159 (2)).
4. **Folder guard.**
   - `unreadable()` uses `lstat`, never following a link. An unreadable bits folder makes both folders unreadable.
   - Nothing is imported from an unreadable folder, and no policy whose `source_file` is in it is deleted. One constant log line is written, and the folder is listed in `unreadable_folders` for TASK-158.
   - A real empty folder still deletes its policies.
5. **Lock (TASK-154 carry (a)).** The caller holds it. `test_the_lock_spans_every_import_…` shows a concurrent `delete_policy` waits for the whole reconcile, and plant P16 is red.

## Findings
1. **should-fix**, `folders.py:294-310` (`delete_removed`). The guard is decided once, but each deletion is decided later from `present()`. This breaks the "Folder guard" ruling and checklist 9 ("decide from state re-read …, not from what an earlier check returned").
   - **The window.** `blind = unreadable(bits_dir)` is computed once, before the loop. `present()` then answers False for "folder gone" as well as for "file gone". If `uploaded/` or the bits folder disappears, or is swapped for a link, while the loop runs, every remaining policy in it is soft-deleted. That is the very loss the user's ruling prevents. Start-up and watcher events are when a mount may still be settling.
   - **A second path to the same result** (tester finding 4). For a server row, `present()` checks the file with `lstat(bits_dir / rel)`, which follows a symlinked bits folder. The answer is then wrong in either direction.
   - **Fix.** Before each `delete_in_tx`, re-run the guard for that row's folder (`_folder(row.source_file) in unreadable(bits_dir)` → skip and log). Better still, make the absence test tri-state (present / absent / folder unreadable), so absent is only ever decided inside a readable real directory.
   - **Test.** A plant or hook that breaks the folder after the first deletion: the remaining policies stay live.
2. nit, `folders.py:151`: `read_input` opens `bits_dir / rel` by path, so a swap of `uploaded/` (or the bits folder) for a link between `discover` and the open follows the directory link. `O_NOFOLLOW` covers the last component only. It only reads, and only server administrators can write the folders. Opening through an `O_DIRECTORY|O_NOFOLLOW` fd, as `uploads.py` does, would close it.
3. nit: `prepare()` runs under the caller's lock here, unlike D4's "before the lock". That is acceptable for start-up and the watcher, since the module needs the lock across classification and import, but it holds off uploads while large files parse.

## Tester's findings
- **(2) R6 can't empty the bits folder:** agreed; the server case still covers "a folder with no `.bit` file is readable".
- **(3) A recovered folder imports normally:** agreed; that is expected.
- **(4) `present` through a symlinked bits folder:** folded into finding 1. TASK-157 must keep "unreadable before present" for every deletion and recheck it per deletion.
- **(5) The log words are not pinned:** acceptable, since one constant line per folder with no path is pinned.
- **r1 (3) BIGSERIAL cap caught only by the unit test:** acceptable, as PostgreSQL's numeric comparison makes the database path harmless.
- **r1 (4) A rejected folder file alerts again at every start-up:** this is spec behaviour. TS §4.1 skips only a file equal to the last *successful* import. It goes in the M7 PR notes; no change.
