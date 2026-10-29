# TASK-154 TEST: PASS

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-150 (4), REQ-155, REQ-157 (3), REQ-160, REQ-162, REQ-176 (2); TS §4.1 L516–L532, §4.2, §4.3, §8.4 L1288–L1291; SR §3.5, §3.6, §4; #23, #98 (j), #99 (b), (e), #100 (a) widened, #101, #106, #110; BIT016 ruling (2026-10-27); the 2026-10-28 TASK-154 rulings. Code under test: `bm/services/importer/pipeline.py` and `pipeline_record.py` (the split). New test files: `manager/tests/test_import_pipeline_pg.py` (216 tests, its own module database, plus a fresh database for the two exact first-import tests) and `manager/tests/test_import_fuzz_pg.py` (1 test, 500 files, its own database). Rows go in through the real `AppDatabase.session()` and `catalog_lock`, with a temporary bits folder. BIT102 is checked only through cases TASK-146 r2 does not change (lead, 2026-10-28): `rm x` is rejected, and the SR and sample Executes pass.

## Runs

| Run | Command (W, `/root/bstest-m7-t154`, `CI=true`) | Count |
| --- | --- | --- |
| r0 (`-n 2`) | `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | 53/217 passed, 162 failed, 2 errors, 0 skipped. All were test bugs: `errors` key order compared as a list (jsonb doesn't keep key order), and the fresh-server creds folder not created |
| r1 (`-n 2`) | the same two files after the two fixes | **217/217 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (`-n 0`) | `tests/test_import_fuzz_pg.py` after widening its fault handler (any exception from an injected fault is checked for state) | 1/1 passed |
| r3 (`-n 0`) | `tests/test_module_imports.py` (covers the new modules) | 131/131 passed |
| plants | 14 plants in throwaway copies `/root/bstest-m7-mut-<id>` (removed after each), clean copy green first (r1) | 14/14 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on both new files | clean |

The first two plants ran at `-n 2` with 2,772 MB free, under the 3,000 MB floor. That was my error. Every run after that checked memory first and used `-n 0` below 3,000 MB. No container was left by label.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-190 | APP | W | r1 | PASS | Fresh database, the SR §1.1 bytes (manifest sha), server file `cis-ubuntu.bit`, actor `user:7`: exactly one `bit_import` row `{file_name cis-ubuntu.bit, sha, policy_version 1, manual, success, 1/0/0, errors [], imported_by 7, imported_at = clock}`; exactly one audit entry, `policy.import` by `user:7` on `policy:<id>`, `alert true`, `policy_imported`, `changed_executes` = the one plugin (`3f6c2a9e-…`, `1.3.1.1 - Ensure AppArmor is installed`, the trimmed Execute, its sha, `new`, no flags); `bitscan_alerts_total{policy_imported}` +1 and no other counter moves; membership `[(uuid, 1)]` | 2026-10-28 |
| CHK-M7-191 | APP | W | r1 | PASS | 145 rejecting fixtures of `bits/tests/manifest.json` (every Reject code: BIT001–005, 008, 010–014, 016, 017, 102 via `bit102-rm`), PluginIds isolated per test: each gives one `rejected` row (version null, counts 0, mode, file name) whose code set is exactly the manifest's, four keys per finding, ordered by line; exactly one `policy.import_rejected` entry (`policy_import_rejected`, `import_id`, mode, `codes` in row order, `finding_count`); catalog checksums unchanged; `policy_import_rejected` +1 and `bitscan_import_failures_total{mode}` +1 for `auto`, `manual` and `rebuild` each; oversize folder file (data None, #99 (b)) and 5 MiB + 1 bytes → BIT001 rejected; exactly 5,242,880 bytes → success; alert target `policy:<id>` for a matched update, the file name otherwise | 2026-10-28 |
| CHK-M7-192 | APP | W | r1 | PASS | `auto` with an unchanged file: one `skipped` row (current version, counts 0, `[]`), **no** audit entry, no counter, catalog unchanged; `manual` and `rebuild` on the same bytes: `success`, same version, 0/0/0, one `policy.import` with empty `changed_executes`; `auto` imports a changed file (version +1) and retries a rejected one each time (rejected again, never skipped), and skips again on the last successful bytes; `auto` revives a deleted policy instead of skipping it (version +1, #14) | 2026-10-28 |
| CHK-M7-193 | APP | W | r1 | PASS | 25 success fixtures (valid, at-limit, warnings) import with exactly the manifest's warning codes in `errors` and in the outcome (#110), one `policy_imported` each | 2026-10-28 |
| CHK-M7-194 | APP | W | r1 | PASS | `before_commit` raising `OSError`: it was called with the policy id, then nothing committed, no row, no entry, no counter (#98 (j)); a database error inside the store (`replace_membership`): the same; a record failure after a committed success: the catalog stands, `import_id` None, one `policy.import`, `policy_imported` +1, the log has `bit_import record failed: OperationalError` and no name or Execute; a record failure on a rejection propagates with no alert and no count; `after_commit` raising: the success row is still written, then the error propagates; `after_commit` runs after the commit (another connection sees the policy) and before the record | 2026-10-28 |
| CHK-M7-195 | APP | W | r1 | PASS | Read once: with a different file on disk, `import_one` stores the buffer (source sha and Execute from the buffer), and the audit hook sees no open of any path in the bits folder; `prepare` takes only `data`, has no side effects and is deterministic | 2026-10-28 |
| CHK-M7-196 | APP | W | r1 | PASS | Internal errors write no `bit_import` row (store database error, `before_commit` disk error) | 2026-10-28 |
| CHK-M7-197 | APP | W | r1, r2 | PASS | 500 seeded files (seed 20261028; pools of 4 names, 10 ids and 3 server files plus uploads; SR example and samples; half byte-mutated; 10 % with a fault injected late in the store). After each run: unchanged (full row sets of `family`, `policy`, `plugin`, `policy_plugin`) for rejected, skipped, refused and faulted runs. For success, complete against the file as the test reads it with defusedxml: name, family, sha, source file, version rule, membership in document order, owner, `active`, Execute and sha; nothing else changed except a displaced policy (#106) and retirements of plugins no live policy lists. Exactly one row per import, none for refused or faulted. Every branch was reached | 2026-10-28 |
| plan §10 row 4 | APP | W | r1 | PASS | `formatVersion` `2.0` and `1.1` with a bad status → BIT016 and BIT003 in one row (BIT016 ruling); BIT002 with BIT003 → only BIT002; BIT003, BIT007 and BIT015 together in one row; the `db/bit007-*` pair gives BIT007 at `Policy/PolicyName`, then once `a.bit` is gone the move keeps the id and writes `policy.move {from a.bit, to b.bit}` (no alert); the `db/bit015-*` trio gives BIT015 at `Plugin[2]/PluginId`, then after the owner drops the id, the claim moves `owner_policy_id` | 2026-10-28 |
| plan §10 row 5 | APP | W | r1 | PASS | An upload of a server-folder policy raises `PolicyManagedOnServer(policy_id)`, writes no row, and writes exactly one entry `{actor user:3, policy.import_refused, policy:<id>, {policy_id, mode, file_sha256}}` with no alert key; catalog and counters unchanged | 2026-10-28 |
| plan §10 row 7 | APP | W | r1 | PASS | Rebuild of three files in one transaction with `store_in_savepoint`, the second now `rm x`: the pending outcomes are success, rejected, success with no `import_id`; `record` in a second transaction writes three `rebuild` rows (the middle one `["BIT102"]`); the rejected policy's rows, membership and plugin are byte-equal to before; the other two are updated; `policy.import` only for those two (mode `rebuild`), exactly one `policy.import_rejected` and no other entry on the rejected policy; counters `policy_imported` +2, `policy_import_rejected` +1, `fail:rebuild` +1 | 2026-10-28 |
| plan §10 row 8 | APP | W | r1 | PASS | Server file wins over an upload: same id, `source_file` moves, the uploaded copy is deleted from disk, entries `policy.import` then `policy.move {uploaded/policy-<id>.bit → srv.bit}`. Displaced (#106): X deleted (`deleted/<id>`), entries `policy.import`, `policy.move` and `policy.delete` (`policy_deleted`, "file now holds another policy"), counters +1 each. Rename in place keeps the id with `renamed_from`. A file re-enable gives `policy.status_change` `policy_reenabled` by `file`; with the admin override it stays disabled and no re-enable alert is raised. `changed_executes` gives `new` (with the `shadow` flag), then only the `changed` one, then `reactivated` for a retired plugin listed again (#100 (a) widened) | 2026-10-28 |
| REQ-157 (3) entry points | APP | W | r1 | PASS | `rm x` added to a live policy is rejected (BIT102 at `Plugin[2]/Execute`) on server and upload targets in `auto`, `manual` and `rebuild` modes, and in the rebuild savepoint; the SR Execute in a generated file and both `bits/samples` files (fresh database) import with no Reject and no BIT102 | 2026-10-28 |
| actors, lock, logs | APP | W | r1 | PASS | `user:42` → `imported_by` 42; `cli:root` and `system` → NULL; the audit actor is the given string on success and rejection; the caller's catalog lock stays held during `before_commit`, during `after_commit` and after `import_one` returns, and is free after the caller releases it; no Execute, description, name or `rm x` text in any log record across success, BIT102 rejection and BIT003 rejection | 2026-10-28 |
| CHK-M7-333 | APP | W | plant a: `prepare` skips `check_execute` (`pipeline.py`) | PASS (red) | 8 failed: `bit102-rm` fixture, all six `test_rm_is_rejected_on_every_entry_point`, the rebuild row | 2026-10-28 |
| CHK-M7-333 | APP | W | plant b: `store_in_savepoint` drops the BIT102 findings (`pipeline_record.py`) | PASS (red) | 1 failed: `test_rebuild_with_one_file_rejected_keeps_its_rows` (`[] == ['BIT102']`) | 2026-10-28 |
| CHK-M7-339 | APP | W | plant: the rejected `record` written inside tx1 (`pipeline.py`) | PASS (red) | 166 failed: every rejection loses its row with the rollback | 2026-10-28 |
| CHK-M7-340 | APP | W | plant a: `before_commit` `OSError` swallowed, tx1 commits | PASS (red) | 1 failed: `test_before_commit_failure_rolls_back_with_no_row_and_no_alert` (did not raise) | 2026-10-28 |
| CHK-M7-340 | APP | W | plant b: a database error in tx1 suppressed and the transaction committed (`pipeline.py`) | PASS (red) | 2 failed: the fuzz at run 6 (injected fault left a partial import: the catalog differs) and `test_a_database_error_in_the_store_writes_nothing` | 2026-10-28 |
| CHK-M7-349 | APP | W | plant: the `policy_imported` `put` removed (`pipeline_record.py`) | PASS (red) | 36 failed, among them every success fixture, both no-skip modes, the rebuild, move, displaced, rename, re-enable, changed-executes and record-failure rows | 2026-10-28 |
| CHK-M7-350 | APP | W | plant a: the rejected `alerts.emit` removed from `record` | PASS (red) | 163 failed (every rejection row) | 2026-10-28 |
| CHK-M7-350 | APP | W | plant b: `count_failure` removed from `record` | PASS (red) | 163 failed (`fail:<mode>` +1 missing) | 2026-10-28 |
| CHK-M7-369 | APP | W | plant a: `mode == "auto" and` dropped (manual and rebuild skip) | PASS (red) | 2 failed: `test_manual_and_rebuild_never_skip[manual]`, `[rebuild]` | 2026-10-28 |
| CHK-M7-369 | APP | W | plant b: `mode != "auto"` (auto never skips) | PASS (red) | 4 failed: the skip row, both no-skip rows, and the auto retry row | 2026-10-28 |
| CHK-M7-154-ref | APP | W | plant: the refusal re-raised without its `policy.import_refused` entry | PASS (red) | 1 failed: `test_upload_of_a_server_folder_policy_is_refused_without_a_row` | 2026-10-28 |
| CHK-M7-154-read | APP | W | plant: `import_one` re-reads a server file from disk | PASS (red) | 2 failed: `test_the_buffer_is_used_and_the_file_is_never_opened` (open seen), and the oversize folder row | 2026-10-28 |
| CHK-M7-154-lock | APP | W | plant: `import_one` unlocks the catalog at its start | PASS (red) | 1 failed: `test_the_callers_lock_is_held_throughout_and_not_released` (`[True, True, True]`) | 2026-10-28 |
| BIT102 fixtures (r2) | APP | W | — | NOT RUN (by the lead's instruction) | `content/bit102-redirect`, `-systemctl-stop`, `-sed-i`, `-bash-c-subst` and `-unlexable` wait for TASK-146 r2 approval; they are in `R2_PENDING` in the test file and join `REJECTING` on the targeted re-run | 2026-10-28 |
| REQ-162 (5) sink | APP | — | — | NOT RUN (not this task) | Delivery to the fake sink belongs to G60 `test_catalog_alerts_pg.py` (CHK-M7-286); here every entry is checked in `audit_log` with `detail.alert` and its counter | 2026-10-28 |

## Acceptance (TASK-154 row)

- SR §1.1 example: one `success` row and one `policy_imported` alert → CHK-M7-190.
- Each BIT fixture: its `rejected` row and alert, and no catalog change → CHK-M7-191 (five BIT102 fixtures pending r2, as above).
- An unchanged file in `auto` mode writes only a `skipped` row → CHK-M7-192.
- 500 generated files leave the catalog complete or unchanged → CHK-M7-197.
- A rolled-back import writes no success alert → CHK-M7-194.

Plan flows: move with a displaced policy, server-folder refusal and `policy.import_refused`, failure in the record step and in `after_commit`, rebuild with one file rejected → plan §10 rows 5 to 8 above. Every named plant (333, 339, 340, 349, 350, 369) and three security plants went red.

## For the lead (no defect; please confirm)

1. **Rejected-alert target.** #101 reads "Target: `policy:<policy_id>`, or the file path for a rejected import". Plan §5 and the approved TASK-153 builder read this as "the matched policy if any, else the file name". My test asserts the plan's reading: a BIT003 update of a live policy targets `policy:<id>`, and an unknown name targets the file name. If #101 means every rejected import targets the file path, that test and TASK-153 need to change.
2. **Skipped row version.** A `skipped` row stores the current `policy_version` (plan §5). SR §3.5 describes the column as "`policy.version` after the import, if it succeeded". The test pins the plan's value.
3. **The `auto` skip comes before the findings** (the impl report's observation, the lead's 2026-10-28 ruling). The tests pin that a rejected file is retried every time and that the last successful bytes skip.

## Revision 1 (2026-10-28): `policy_version` NULL unless `success`

Ruling: work/decisions.md "TASK-154 test questions" (2), which reads SR §3.5 literally. Product change: `pipeline_record.py` only. A skip no longer carries the old version, and `record` writes `policy_version` only when `outcome = success` (impl report, "Revision 1"). The re-pin was made from the ruling before the r1 code arrived:

- `test_auto_unchanged_writes_only_a_skipped_row` now expects the `skipped` row's `policy_version` to be NULL. The outcome still carries the `policy_id`.
- Rejected rows were already pinned to NULL in `assert_rejected`.
- The fuzz now asserts that every non-success row has a NULL `policy_version`.

Rulings (1) (the rejected-alert target: `policy:<id>` when matched, else the file name) and (3) (the `auto` skip before the findings, TS §4.2) confirm the existing pins. No test changed for them.

| Run | Command (W, `/root/bstest-m7-t154`; only `pipeline_record.py` and the two test files synced, so the BIT102 code is the same as in r1 above) | Count |
| --- | --- | --- |
| r1-1 (`-n 2`, label `m7t-t154r1`) | `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | **217/217 passed**, 0 failed, 0 errors, 0 skipped |
| plants | the record-touching plants again, plus the r1 plant | 4/4 red |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-192 (r1) | APP | W | r1-1 | PASS | `auto` unchanged: one `skipped` row with `policy_version` NULL, mode `auto`, `errors` `[]`, counts 0; no audit entry, no counter, catalog unchanged; `manual` and `rebuild` → `success` with the version | 2026-10-28 |
| CHK-M7-191 (r1) | APP | W | r1-1 | PASS | every rejected row has a NULL `policy_version` (145 fixtures, the mode, oversize, target and DB-rule rows) | 2026-10-28 |
| CHK-M7-197 (r1) | APP | W | r1-1 | PASS | 500 files: every non-success row's `policy_version` is NULL, and the earlier complete-or-unchanged checks still hold | 2026-10-28 |
| CHK-M7-154-r1 | APP | W | plant: the skip carries `old.version` again and `record` writes `pending.policy_version` unconditionally | PASS (red) | 2 failed: `test_auto_unchanged_writes_only_a_skipped_row` (`('skipped', 'auto', 1, [])` vs `None`), and the fuzz at run 97 (an `auto` skip on `f2.bit`) | 2026-10-28 |
| CHK-M7-350 (r1) | APP | W | plants a and b again (`record` changed) | PASS (red) | 163 failed each | 2026-10-28 |
| CHK-M7-339 (r1) | APP | W | plant again (the record inside tx1) | PASS (red) | 167 failed | 2026-10-28 |

Verdict after revision 1: **PASS**. The five BIT102 fixtures are still NOT RUN and wait for TASK-146 r2, as above.

## Revision 2 (2026-10-28): a rebuild alerts only for a policy whose rows it changed

Ruling: work/decisions.md "TASK-157 rulings" (2) (#23 agreed, REQ-166 (6)). Product change: `pipeline_record.py` only (`_fingerprint`, `_changed`; rebuild mode only). Test changes, made from the ruling:
- **Re-pin:** `test_manual_and_rebuild_never_skip[rebuild]` expected a `policy.import` entry for an unchanged rebuild file. Under the ruling an unchanged rebuild file writes no entry and no count, so it now asserts that, while `[manual]` still expects its entry and count (TS L530).
- **New rows:**
  - `test_a_rebuild_that_changes_nothing_alerts_for_nothing`: three unchanged files through `store_in_savepoint` and `record` → three `success` rows, no entry, no counter, catalog unchanged.
  - `test_each_corruption_gives_exactly_one_policy_imported[execute, membership, retired, status, sha, owner]`, one per owner-made corruption: the REQ-166 (1) four, plus `source_sha256` and `owner_policy_id`. Each gives exactly one `policy.import` for that policy, one `policy_imported` count, and the restored rows (execute, membership, `active`, `policy_status`, owner, sha).

| Run (W, fresh copy `/root/bstest-m7-t154r2`, `-n 2`) | Count |
| --- | --- |
| `pytest tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py` | **224/224 passed**, 0 failed, 0 errors, 0 skipped |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-154-r2 rows | APP | W | run above | PASS | An unchanged rebuild file is `success` with no entry and no count; each of the six corruptions gives exactly one `policy_imported` and is restored; manual stays audited; the rebuild with one file rejected still alerts for its two changed files | 2026-10-28 |
| plant r2a | APP | W | the fingerprint comparison dropped | PASS (red) | 4 failed: the `membership`, `status` and `sha` corruption rows, and the rebuild row (its description-only change is seen only by the fingerprint) | 2026-10-28 |
| plant r2b | APP | W | `_changed` always true | PASS (red) | 2 failed: the unchanged-rebuild row and `never_skip[rebuild]` | 2026-10-28 |
| plant r2c | APP | W | the change gate applied in every mode | equivalent alone (223 passed) | Outside rebuild mode the before fingerprint is None, so the change test is always true. Together with r2d (the fingerprint read in every mode) → red, 1 failed: `never_skip[manual]` (an unchanged manual import lost its entry) | 2026-10-28 |

Verdict after revision 2: **PASS**.
