# TASK-152 TEST: PASS (round 2, on TASK-147 revision 2)

Tester: tester-m7, 2026-10-27. REQ-167 (1), (2), (5), (6), REQ-161 (2); TS §4.3 L550, §4.1 L526, §8.4 L1290; #98 (e), #101. File under test: `bm/services/importer/delete.py` (unchanged since round 1). Test file: `manager/tests/test_policy_delete_pg.py` (11 tests), PostgreSQL as `bitscan_app` with a temporary bits folder.

## Round 1: FAIL

4/11 passed, 7 failed with `AuditError: audit append needs a transaction, not autocommit`. The pinned session's transaction left `conn.autocommit` True, so `PgAuditRepo` refused the delete alert. This is a TASK-147 defect, fixed in TASK-147 revision 2 (session transactions run with autocommit off). `delete.py` did not change.

## Round 2

| Run | Command | Count |
| --- | --- | --- |
| W (label m7t-t147r2, `CI=true`, `-n 2`) | `pytest tests/test_policy_delete_pg.py` (with the TASK-147 r2 files) | 11/11 passed (the run: 77/77), 0 failed, 0 skipped |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-224 | APP | W | round 1 (m7t-t152b) | FAIL | 4/11; `AuditError` (TASK-147 defect) | 2026-10-27 |
| CHK-M7-224-r2 | APP | W | round 2 (m7t-t147r2) | PASS | REQ-167 (1) through `delete_policy`: owner-written jobs (`queued`, `dispatched`, `running`) and two schedules; only the queued job is cancelled; both schedules disabled; `deleted_at` = the clock, `source_file` `deleted/<id>`; plugins retired; `uploaded/policy-<id>.bit` removed and another upload kept; exactly one `policy.delete` entry (actor `user:1`, `alert = true`, kind `policy_deleted`, `reason` "deleted through the API", the old `source_file`); `bitscan_alerts_total{policy_deleted}` +1; the catalog lock free afterwards. (2) A server-folder policy raises `PolicyManagedOnServer` (its id), with nothing changed (6 table checksums), no alert, its file untouched. Unknown → `PolicyNotFound`; already deleted → `PolicyAlreadyDeleted`, nothing changed. (5) A new policy claims the deleted policy's plugin with no BIT015. (6) The `policy` row count is unchanged | 2026-10-27 |
| CHK-M7-225-r2 | APP | W | round 2 | PASS | a fault before commit (`emit` raising) leaves the row, the checksums, the counter and the upload file as they were, and frees the lock; the core inside a caller's transaction that later raises rolls back with it (checksums, counter); the core without the refusal deletes a server policy with reason "file removed", actor `system`, and never removes its file; a delete waits while another holder has the catalog lock (REQ-161 (2)); two racing deletes give one success, one `PolicyAlreadyDeleted` and exactly one alert; `remove_after_commit` removes only `uploaded/policy-<ASCII digits>.bit` (refuses `x.bit`, `uploaded/../x.bit`, a traversal through a policy name, Arabic-Indic digits, `policy-.bit`, `.tmp-`, `deleted/7`; a symlink is removed without touching its target; a missing file is no error) and logs no path | 2026-10-27 |
| CHK-M7-351 | APP | W | plant: no `emit` (no `policy_deleted`) | PASS (red) | 4 failed | 2026-10-27 |
| CHK-M7-152-s | APP | W | plant: server-folder refusal ignored | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-152-f | APP | W | plant: upload file removed before commit | PASS (red) | 1 failed (fault row: file gone) | 2026-10-27 |
| CHK-M7-356 (152 half) | APP | W | plant: delete without the catalog lock | PASS (red) | 1 failed (did not wait) | 2026-10-27 |
| CHK-M7-152-p | APP | W | plant: path check removed (relative path joined) | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-365 (152 half) | APP | W | hard DELETE / skipped job cancel | covered | planted at the repository (TASK-150: red); the route-path rows above see the cancel and the kept row | 2026-10-27 |
