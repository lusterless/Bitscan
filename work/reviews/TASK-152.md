# TASK-152 REVIEW: policy delete service

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-167 (and REQ-161 (2)). High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/services/importer/delete.py` (115 non-blank lines), per `work/reports/TASK-152-impl.md`. One file, with no SQL; it is unchanged since round 1.

TEST: round 1 FAIL, then round 2 PASS (`work/reports/TASK-152-test.md`).
- The round-1 failure was a TASK-147 defect: session transactions ran in autocommit, so the audit guard refused the entry. It is fixed by TASK-147 r2. Round 2: 11/11.
- These plants turned it red:
  - CHK-M7-351, no `policy_deleted`;
  - the server-folder refusal ignored;
  - the file removed before commit;
  - no catalog lock (the 152 half of CHK-M7-356);
  - the path check removed.
- CHK-M7-365 (hard DELETE, skipped cancel) is planted at the repository (TASK-150).

Spec read: TS §4.3 L550, §4.1 L524–L526, §8.4 L1290, §5.2 grants; #14, #98 (e), #101, #104.

## Checks
1. **Soft delete (REQ-167 (1), TS §4.3 L550).** `delete_in_tx` locks the row `FOR UPDATE` and decides on that state (checklist 9): unknown, already deleted, and (on the route path) server folder → `PolicyManagedOnServer`. It then applies TASK-150's `soft_delete_effects`. There is no DELETE on `policy`, and two racing deletes give one success and one alert.
2. **Alert and audit (TS §8.4 L1290, #101).**
   - One `policy.delete` entry is the `policy_deleted` alert, written in the same transaction through `emit` and `PgAuditRepo`, and counted on commit.
   - The target is `policy:<id>` (checklist 16); there is no other target built here.
3. **Lock and file (TS §4.1 L526).**
   - `delete_policy` takes the session and `catalog_lock`, runs one transaction, and removes the upload copy after the commit and before the lock is released.
   - A fault before commit leaves the row, the counter and the file as they were.
   - The no-lock core rolls back with a caller's transaction or savepoint, for the watcher and the rebuild (`reason="file removed"`, server folder allowed, file untouched).
4. **File removal.**
   - `remove_after_commit` unlinks only `uploaded/policy-<ASCII digits>.bit` under `bits_dir/uploaded`. Traversal, other names, non-ASCII digits and `.tmp-` files are refused.
   - A symlink is removed, not followed; a missing file is fine.
   - Failures are logged by type name only, with no path.
5. **Layering.** Service only; the route (TASK-163) owns the TOTP session, the admin role and the sink gate (#1).
6. **Re-run by me:** ruff, ruff format and mypy (CI form) are clean on product code.

## Findings
None blocking or should-fix.

1. nit: the delete alert's detail omits the cancelled job and disabled schedule ids. They are in `DeleteResult.effects`, and TASK-153's `deleted` shape has no field for them. Optional, if the owner wants them in the alert.
2. Carry to TASK-156/158: if the process stops after the delete's commit and before the file removal, `uploaded/policy-<id>.bit` stays on disk. The start-up reconcile must not import it as a new or revived policy. It should delete it, or treat it as the #103 difference it is. The same note is in the TASK-151 review.
