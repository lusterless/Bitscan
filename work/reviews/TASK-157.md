# TASK-157 REVIEW: catalog rebuild

Verdict: APPROVED (revision 2)

Reviewer: reviewer-m7, 2026-10-28. REQ-166. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: `manager/bitscan_manager/services/importer/rebuild.py` (about 236 non-blank lines), per `work/reports/TASK-157-impl.md` including "Revision 1" and "Revision 2". One file.

**Round 0, blocking (my pre-read, confirmed by main), fixed in r1.** A case (c) `uploaded/` file creating a new policy was soft-deleted inside its own rebuild transaction:
- Its `source_file` `uploaded/policy-<id>.bit` exists only after the post-commit rename, so the gone-file loop saw it as missing.
- After the commit, `remove_after_commit` then removed the renamed file, so the policy was deleted and its bytes lost.
- The r1 fix: `_Work.staged` collects every staged `uploaded/policy-<id>.bit` (`move.staged` is True), and the loop treats those as present.

**Revision 2 ("TASK-158 test questions" (2)).** This is the start-up versus CLI race, from my TASK-158 pre-read and tester-m7's probe.
- The problem: `start_task` writes the `running` row before `run` takes the lock. If the start-up fails that task in the meantime, the rebuild used to run and commit anyway, and its `bits.rebuild` said `succeeded` while the task row stayed `failed`.
- The fix: right after taking the lock, `run` re-reads its task (`rebuild.py:103-106`). If the task is missing or not `running`, it returns `failed` with the fixed `reason` `NOT_RUNNING` and changes nothing.
- Writing no entry for that no-op is acceptable. Nothing in the catalog changes, the task row already says `failed` with the start-up's text, and the CLI prints the reason and exits 1 (#107 (c)).

TEST: PASS on r1 and r2 (`work/reports/TASK-157-test.md`, tester-m7).
- r1: 17/17 on PostgreSQL in WSL, 10/10 plants red, whole-tree gates clean. Plant b0 (the staged check dropped) is red on the case (c) row and on both r1 must-pass rows.
- r2: 17/17, and 32/32 with the start-up file. The race is now two must-pass rows in `test_catalog_startup_pg.py`. Plant rr (the re-check dropped) is red.

Spec read: TS §4.1 L524, L526, §4.2 L540, L542, §4.3 L550, §8.4 L1290; #20, #23, #98 (g), (j), #101, #103, #107 (c); decisions 2026-10-28 "TASK-157 rulings" (1)–(5), "TASK-156 case (c) success", "#102 (c) wiring", "TASK-158 test questions" (2); the crash-window ruling (2026-10-27).

## Checks
1. **One lock, one transaction (TS L526, L540).**
   - The catalog lock is held from the task re-check through the post-commit renames and removals (plant b6).
   - There is one rebuild transaction, with one savepoint per file (`store_in_savepoint`, mode `rebuild`, never skipped).
   - A rejected file keeps its rows (CHK-M7-217 (2)).
2. **Internal error (ruling (1), #98 (j)).** Any exception rolls the whole rebuild back, and the `ExitStack` discards every staged temp file (plant b9). No `bit_import` row is written. The task ends `failed` with the fixed `{error}`, and one `bits.rebuild` entry with state `failed` is written in a final transaction (plants b2 and b3).
3. **Classification (crash window).**
   - `uploaded/` files go through `classify_upload`, and a leftover is never imported. It is removed after the commit, with `OWN_CHANGES.removed` recorded first, and listed in `task.result` and the alert (plants b1 and b7).
   - A refused case (c) copy is caught outside the savepoint and listed in `not_imported` (ruling (5)).
4. **Gone files (TS L550).** Every live policy whose file is gone is soft-deleted with `delete_in_tx(reason="file removed")`, which raises its alert. After r1, a staged upload counts as present. No table is truncated, and `agent`, inventory, `scan_*` and earlier audit rows are untouched (CHK-M7-217 (3), (4)).
5. **Alerts (ruling (2), #23, REQ-166 (6)).** The rebuild raises:
   - one `policy_rebuilt`;
   - one `policy_imported` per changed policy (TASK-154 r2), and none for an unchanged file;
   - one `policy_import_rejected` plus a failure count per rejected file.
6. **`task.result` (the lead's question).** It holds the #98 (g) keys plus `removed_leftovers` and `not_imported`. That's acceptable:
   - `removed_leftovers` is required by the TASK-157 row itself;
   - `not_imported` comes from ruling (5);
   - both are additive, and the failed shape stays `{error}`.
7. **Security invariants.** Logs carry only exception types. No file content or names reach them, and there is no SQL text.

## Findings
None blocking or should-fix (the round 0 blocking finding is fixed in r1 and proved by plant b0; the race is fixed in r2 and proved by plant rr).

1. nit, `rebuild.py` leftover handling: a leftover is added to `removed_leftovers` before its unlink, so a failed unlink still lists it as removed. The next start-up's reconcile removes it the same way. Listing it only after a successful unlink, or adding a failed list, would make the report exact.
2. nit: if the final record transaction fails after the catalog commit, the task stays `running` until the next start-up marks it `failed`, although the catalog changes stand. That's accepted in the impl report; the `failed` state then understates what happened.
3. Carried to TASK-164: `GET /tasks/{id}` must document `removed_leftovers` and `not_imported` in its response schema.
4. Carried to TASK-166: print `RebuildResult.reason` when it is set, and exit 1.
