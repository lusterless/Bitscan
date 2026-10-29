# TASK-157 TEST: PASS (on revision 1)

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-166 (1)–(6); TS §4.2 L540, L542, §4.1 L524, L526, §4.3 L550; #20, #23, #98 (g), (j); decisions "TASK-157 rulings" (1)–(5), TASK-154 r2, the crash-window ruling, "TASK-156 case (c) success"; the lead's r1 must-pass rows and the accepted-exception row (2026-10-28). Code under test: `bm/services/importer/rebuild.py` **revision 1** (staged `uploaded/policy-<id>.bit` targets count as present in the gone-file loop; the blocking defect found by reviewer-m7). New test file: `manager/tests/test_rebuild_pg.py` (17 tests, Linux only). Its own module database; each test owns its folders, and the earlier tests' live policies are soft-deleted first.

## Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t157` of the tree with r1, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| g0 | `pytest tests/test_rebuild_pg.py` (15 tests then) | 15/15 passed. The copy already had r1 (checked: `work.staged` in the copied `rebuild.py`) |
| g1 | the same, with the r1 must-pass rows and the accepted-exception row in both #15 orders | **17/17 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean |

(The g1 count of 17 counts the accepted-exception row once per parameter: 16 functions, one with 2 cases.)

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-216 | APP | W | g1 | PASS | REQ-166 (1): five policies; four corrupted by the owner (an `execute`, a `policy_plugin` row deleted, a plugin `retired`, `policy_status` flipped without an override), one untouched. The rebuild keeps every `policy_id` (and plugin uuid), restores the membership in order, `enabled`, each plugin's `execute`, `active` and owner. Exactly four `policy.import` entries, on the four corrupted policies, none on the untouched one; one `policy_rebuilt`; `policy_imported` +4 (TASK-154 r2) | 2026-10-28 |
| CHK-M7-217 (2) | APP | W | g1 | PASS | One rejected (`rm x`) of three: its policy row, membership and plugin byte-equal to before; the other two updated. The task is `rebuild`, `succeeded` (#20), `requested_by` 21, `finished_at` set. `result` keys are exactly `files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported`, and each file item is exactly `source_file, import_id, outcome, policy_id, policy_version` (null when rejected). Three `rebuild` rows match the item ids | 2026-10-28 |
| CHK-M7-217 (3) | APP | W | g1 | PASS | Checksums of `agent`, `agent_package`, `os_info`, `scan`, `scan_job`, `scan_result` and `scan_schedule` are unchanged (owner-made agent, scan with queued and running jobs, schedule), and so is `audit_log` up to the entry before the rebuild. `agent_package`, `os_info` and `scan_result` are empty in this database, so they show only that nothing was written | 2026-10-28 |
| CHK-M7-217 (4) | APP | W | g1 | PASS | A removed server file and a removed upload file: both policies deleted (`deleted/<id>`), listed in `deleted_policy_ids` (result and `task.result`), two `policy.delete` with reason "file removed", `policy_deleted` +2. Row counts of `policy`, `plugin` and `family` never go down (no truncation, soft delete only) | 2026-10-28 |
| CHK-M7-217 (5) | APP | W | g1 | PASS | A database error at the third file (after a case (c) file was staged): the result is `failed` with no files, and the task is `failed` with `{"error": "The rebuild failed; the catalog was left unchanged."}` and `finished_at`. Catalog checksums are unchanged, no `bit_import` row (#98 (j)), and exactly one entry, `bits.rebuild` with state `failed`. No other counter moves; `policy_rebuilt` +1. The staged temp is discarded and `foreign.bit` stays. The log has only `rebuild failed: QueryCanceled` | 2026-10-28 |
| CHK-M7-217 (6) | APP | W | g1 | PASS | Exactly one `policy_rebuilt` per rebuild, one `policy_imported` per changed policy (2 of 3; 4 of 5), one `policy_import_rejected` per rejected file, `fail:rebuild` +1. An unchanged rebuild: three `success` rows (never skipped), and the only entry is `bits.rebuild` (no `policy.import`), catalog unchanged. The `bits.rebuild` actor is `user:21`, or `cli:root` with `requested_by` null for the CLI form | 2026-10-28 |
| crash window | APP | W | g1 | PASS | A deleted policy's `uploaded/policy-<id>.bit` is removed, listed in `result.removed_leftovers`, `task.result` and the alert's `removed_leftovers`, gets no row, and the policy stays deleted | 2026-10-28 |
| case (c) and r1 | APP | W | g1 | PASS | `uploaded/foreign.bit` with a new name → live at `uploaded/policy-<id>.bit` with its bytes and sha; `foreign.bit` removed, the only entry; no `policy.delete`, no `policy_deleted`; `deleted_policy_ids` empty in the result and `task.result`. A live case (a) `policy-<n>.bit` whose content names a new policy → the new policy is live at its own `policy-<id>.bit`, the holder stays live with its own file, nothing deleted | 2026-10-28 |
| accepted exception | APP | W | g1 | PASS | `uploaded/foreign.bit` and a server file, both naming the same new policy, in one rebuild. The policy lives in the server file (TS L524), not deleted, with no upload copy and no `.tmp-`. #15 order: `zz.bit` (the upload first) → the upload's copy is staged, then moved; `foreign.bit` removed, `uploaded/` empty. `aa.bit` (the server first) → `uploaded/foreign.bit` is refused as a server-folder copy, listed in `not_imported` and kept for #103 (lead confirmed) | 2026-10-28 |
| refused copy | APP | W | g1 | PASS | Ruling (5): a case (c) copy of a server-folder policy → `not_imported` in the result and `task.result`; no row; the file kept | 2026-10-28 |
| lock | APP | W | g1 | PASS | Another session's `pg_try_advisory_lock(hashtext('catalog'))` is false during the post-commit rename (TS L526). A rebuild started while another session holds the lock waits (task still `running` after 2 s), then ends `succeeded` once it is released | 2026-10-28 |
| logs | APP | W | g1 | PASS | No file name, policy name or Execute marker in the logs across a success and a failure | 2026-10-28 |
| plant b0 (r1) | APP | W | the `work.staged` check dropped | PASS (red) | 3 failed: case (c) relocated, and both r1 must-pass rows (`deleted/<id>` instead of `uploaded/policy-<id>.bit`) | 2026-10-28 |
| plant b1 | APP | W | `classify_upload` skipped (every file "other") | PASS (red) | 2 failed: the leftover row (imported, so revived), and case (a) | 2026-10-28 |
| plant b2 | APP | W | an error swallowed inside the rebuild transaction (commits) | PASS (red) | 2 failed: (5) `succeeded` instead of `failed`, and the log row | 2026-10-28 |
| plant b3 | APP | W | records also written inside the rebuild transaction | PASS (red) | 3 failed: duplicate rows in (2), unchanged and refused rows | 2026-10-28 |
| plant b4 | APP | W | the gone-file loop dropped | PASS (red) | 1 failed: (4) | 2026-10-28 |
| plant b5 | APP | W | recorded files skipped | PASS (red) | 6 failed, among them (1), (2), never-skipped | 2026-10-28 |
| plant b6 | APP | W | the lock released before the renames | PASS (red) | 1 failed: the lock row (`[True]`) | 2026-10-28 |
| plant b7 | APP | W | the leftover not unlinked | PASS (red) | 1 failed: crash window | 2026-10-28 |
| plant b8 | APP | W | no `bits.rebuild` / `policy_rebuilt` | PASS (red) | 6 failed: (1), (2), (5), (6), crash window, CLI actor | 2026-10-28 |
| plant b9 | APP | W | a staged upload not owned by the rollback | PASS (red) | 1 failed: (5) (a `.tmp-` left after the failure) | 2026-10-28 |

## Acceptance

REQ-166 (1) → CHK-M7-216; (2)–(6) → CHK-M7-217 (2)–(6). Lead's list: one `policy_rebuilt`, a `policy_imported` per changed policy and a `policy_import_rejected` per rejected file → (6); an unchanged file gets no `policy.import` → (6); a database error midway → (5); a leftover → crash window; case (c) → case (c) and r1; `PolicyManagedOnServer` → refused copy; the r1 must-pass rows and the dropped-fix plant b0; the accepted exception in both orders. Every security row has a plant that went red.

## Notes (no defect)

- In the accepted exception with the upload first, the staged copy is written and then removed within the same rebuild (moved to the server file). The end state is as required.

## Revision 2 (2026-10-28): the task re-read after taking the lock

Ruling "TASK-158 test questions" (2). Right after taking the catalog lock, `rebuild.run` re-reads its task. If the task is missing or not `running`, it does nothing and returns `failed` with a `reason`. On a fresh copy of the tree with r2 (`-n 0`): `tests/test_rebuild_pg.py` **17/17 passed**, and with the start-up file 32/32. The must-pass race rows are in `test_catalog_startup_pg.py` (see `work/reports/TASK-158-test.md`):
- a task the start-up failed → `failed` with a reason, task still `failed`, no catalog change, no rows, no `bits.rebuild` and no `policy_rebuilt`;
- an unknown task id → the same.

Plant rr (the re-check dropped) → red, 2 failed. Verdict after revision 2: **PASS**.
