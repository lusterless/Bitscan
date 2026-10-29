# TASK-151 REVIEW: import store algorithm (SR §3.6)

Verdict: APPROVED (revision 3)

Reviewer: reviewer-m7, 2026-10-27. REQ-158, REQ-159, REQ-177. High risk (importer; TS §8.2 two approvals: this is the first). **r3 reopens an approved task: it needs the user's second approval again.**

Scope reviewed: the new `manager/bitscan_manager/services/importer/store.py` (types, `in_server_folder`, `apply`, `_reason`) and `store_decide.py` (`decide`, `check_ownership`, `is_unchanged`), per `work/reports/TASK-151-impl.md` (r0, r2, r3). The split into two files is plan §7's, agreed by main; it stays one task. There is no SQL in either file, and it uses only the W1 repository API, plus TASK-148 r1's `retired_among`.

TEST: PASS, r0 to r3 (`work/reports/TASK-151-test.md`; 42 store tests on PostgreSQL as `bitscan_app`; the r3 run was 103/103). These planted faults turned it red:
- CHK-M7-335, -338, the store half of -369;
- ten store-specific plants (151-a to -j);
- r2: revive not `reactivated`, a re-listed retired plugin not `reactivated`, and the prior state read after the displaced delete;
- r3: a server target accepting a `/` path, an upload target compared by `source_file`, and `is_unchanged` ignoring the hash.

Spec read: SR §3.1–§3.6, §4.1 BIT007 and BIT015; TS §4.1 L519–L528, §4.3 L548–L550; plan `work/plans/TASK-151.md` §3–§6 (§3.3 r3); #14, #15, #21, #100 (a) (widened 2026-10-27), #104, #106. Decisions 2026-10-27 L213–L214 (the crash-window ruling and its consequences).

## Checks
1. **`decide` (plan §3.1).** Every row matches the plan, for both target kinds:
   - Upload: a live server-folder policy raises `PolicyManagedOnServer`; a live upload gives `update`; a deleted one gives `revive`; otherwise `insert`.
   - Server file `S`:
     - the same file gives `update`;
     - another existing server file gives BIT007 with nothing written;
     - a file that is gone gives `move_server`;
     - an uploaded policy gives `move_upload`;
     - a deleted policy gives `revive`;
     - otherwise a rename in place or an insert.
   - The #106 displaced policy is soft-deleted first. Rows are locked `FOR UPDATE` under the caller's catalog lock.
2. **BIT015 (plan §3.2).**
   - One query covers all ids.
   - It conflicts only with a live owner that still lists the plugin and is neither the deciding nor the displaced policy.
   - Line, #105 path and document order are right.
3. **`apply` (plan §3.4).**
   - The SR §3.6 steps run in order; the override and #14 version rules hold; the #21 counts are right.
   - There is no DELETE on `policy`.
   - A fault after the third plugin leaves the catalog unchanged after the caller's rollback.
4. **r2, #100 (a).**
   - `_reason` gives `new`, `changed` or `reactivated` (a revival, or retired before the import); a plugin that was live and unchanged gets nothing.
   - The prior state is read before the displaced delete, so takeovers are not reported.
5. **r3, the crash-window ruling.**
   - `Target("server")` refuses any `source_file` containing `/`, so `uploaded/…`, `deleted/…` and subfolder paths can never reach `move_server` or BIT007. The server folder is flat (TS §4.1). This closes my r2 carry-over.
   - `is_unchanged` now also holds for an upload target: `update`, live, equal hash. The caller (TASK-156) has already matched the file to that policy's `source_file`, per the L214 classification.
   - A deleted policy's leftover upload never reaches `decide`: TASK-156 removes it. So the store cannot revive it. TASK-156 owns that check.
6. **Re-run by me:** ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` are clean (274 files). I relied on the tester's WSL runs for PostgreSQL.

## Findings
None blocking or should-fix.

1. nit, `store_decide.py:66`: a BIT007-rejected decision carries the name-matched policy's id, so BIT015 for plugins that policy owns is not reported (SR L250 asks for every failing rule). The file is rejected by BIT007 in any case.
2. Closed by r3: the r2 carry-over about server targets with `uploaded/` paths (decisions L214).
3. Carry to TASK-156 (L213–L214): classify `uploaded/` files under the lock. A deleted policy's file is a leftover: remove it, import nothing, and log and alert it as a #103 difference. Only a live policy's own file reaches the store, as an upload target.
