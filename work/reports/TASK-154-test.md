# TASK-154 TEST: PASS

Tester: tester-m7-154, 2026-10-27. Covers REQ-150, REQ-155, REQ-157, REQ-160, REQ-162 and REQ-176 (2). Spec: TS §4.1 L516–L532, §5.2 (`bit_import`; the app only inserts it and never deletes `policy`), §8.4 L1290–L1291; SR §1.1, §3.6, L250. Open-question answers used: #23, #98 (j), #99 (b) and (e), #100 (a) as widened, #101, #110. Design: D4 and `work/plans/TASK-154.md` §10, plus deviations (1)–(5) (`work/decisions.md`, last TASK-154 row).

Files under test: `bm/services/importer/pipeline.py` and `bm/services/importer/pipeline_record.py`. Checks: CHK-M7-190 to -197 (TP-M7-14), mutation rows CHK-M7-333, -339, -340, -349, -350 and -369, plus extra plants CHK-M7-154-*. Also, because G59 was waiting on this task, CHK-M7-300 and -301 (G59, the TASK-174/175 samples).

New tester files (no product file changed):
- `manager/tests/pipeline_rows.py`: helpers. It generates files with fresh names and plugin ids, takes a snapshot of the catalog checksums, the `bit_import` and `audit_log` high-water marks and every M7 counter, and reads the results as owner.
- `manager/tests/test_import_pipeline_pg.py`: 199 tests, with its own migrated server per module.
- `manager/tests/test_import_fuzz_pg.py`: 1 test, 500 files.
- `manager/tests/test_samples_import_pg.py`: 2 tests, each in its own fresh catalog.

The tests were written from the spec, the acceptance row and plan §10 before reading `pipeline*.py`. The code was read afterwards, only to find the branches to plant and the hook names to patch for fault injection.

## Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 | `pytest -n 0 tests/test_import_pipeline_pg.py` | 199/199 passed, 0 failed, 0 errors, 0 skipped |
| r1 | `pytest -n 2 tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` | 3/3 passed, 0 failed, 0 errors, 0 skipped. Fuzz tally: success 140, rejected 234, skipped 15, refused 78, injected fault 33 (total 500) |
| r2 (affected set) | `pytest -n 4` the 3 new files plus `test_import_store_pg.py test_import_alerts.py test_import_alerts_pg.py test_imports_repo_pg.py test_catalog_lock_pg.py test_policy_delete_pg.py test_bit_validate.py test_bit102.py test_bit_fixtures.py` | **2829/2829 passed**, 0 failed, 0 errors, 0 skipped |
| r3 (coverage) | `pytest -n 2 --cov=bitscan_manager.services.importer` the 3 new files | 202/202 passed; `pipeline.py` 113/113 lines (100 %), `pipeline_record.py` 62/62 (100 %) |
| static | `ruff check manager`, `ruff format --check` (tests), `mypy --strict --config-file manager/pyproject.toml manager` | clean (286 files) |
| plants control | copy `scratchpad/t154/base` (manager, bits and docs, no venv), run from the copy's `manager/` with `PYTHONPATH` set to it. The import path printed was the copy's `pipeline.py`. Same 3 files, `-n 4` | 202/202 passed |

Two first-draft test bugs, both mine and both fixed before r1: (a) `test_samples_import_pg.py` did not create its credentials folder; (b) the first fuzz mix gave too few successes and faults (the 27 >= 50 assertion caught it), so the generator was re-weighted. Neither was a product failure.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-190 | APP | Linux/PG | r0 `test_sr_example_imports_with_one_success_row_and_one_alert_then_auto_skips` | PASS | The byte-identical SR §1.1 example (manifest sha matches), `manual`. Exactly 1 `bit_import` row, every column: `sr.bit`, sha, v1, `manual`, `success`, 1/0/0, `[]`, `imported_by` 7, `imported_at` = clock. Exactly 1 audit entry: `policy.import`, actor `user:7`, target `policy:<id>`, `alert` true, kind `policy_imported`, `changed_executes` = [the SR plugin, full Execute, its sha, reason `new`, flags `[]`]. Counter delta exactly `{policy_imported: +1}`. The alert's `xmin` equals the policy row's `xmin` (same transaction) and the record's `xmin` differs (its own transaction) | 2026-10-27 |
| CHK-M7-191 | APP | Linux/PG | r0 `test_each_rejecting_fixture_…` (150 fixtures, all `rejected` non-`db/` manifest entries; modes cycle auto, manual, rebuild) | PASS | Each fixture gives 1 `rejected` row: codes = the manifest codes, `errors` = the outcome's findings, keys exactly `{line, element, code, message}`, sorted by line, manifest line and element checked. 1 `policy.import_rejected` alert in the record transaction (same `xmin`): `import_id`, mode, file name, distinct codes; target is the file name, or `policy:<id>` when a policy matched. Counter delta exactly `{policy_import_rejected: +1, import_failures{mode}: +1}`. Catalog checksums unchanged. The XXE canary file was never created | 2026-10-27 |
| CHK-M7-191 db rules | APP | Linux/PG | r0 `test_bit007_…`, `test_bit015_…`, `test_bit016_…[2.0, 1.1]`, `test_bit002_stops_the_content_rules`, `test_rejecting_an_update_…` | PASS | BIT007 at line 4 `Policy/PolicyName`, target `policy:<a>`; BIT007 + BIT003 → `[(BIT007,4),(BIT003,6)]`. BIT015 at `Plugin[2]/PluginId`; BIT003 + BIT015 sorted by line; after the owner drops the id the claimer succeeds and owns its plugins. formatVersion 2.0 or 1.1 with a bad status → {BIT003, BIT016} (SR L250). BIT002 + bad status → only BIT002. Rejecting an update to a live policy leaves it unchanged, target `policy:<id>` | 2026-10-27 |
| CHK-M7-191 bounds | APP | Linux/PG | r0 `test_oversize_…`, `test_5_mib_…`, `test_5000_plugins_…`, `test_long_client_name_…` | PASS | `data=None` → exactly `[{null, null, BIT001, "The file is larger than 5 MiB."}]`, the streamed hash stored, metric `auto` +1. 5,242,880 bytes → `success`; 5,242,881 → BIT001. 5,000 plugins → `success` with 5,000 added, order kept and 5,000 changed Executes; 5,001 → BIT017. A 304-character client name is kept whole in `file_name`, and the target is its first 255 characters | 2026-10-27 |
| CHK-M7-192 | APP | Linux/PG | r0 (SR test second half), `test_auto_skip_only_for_an_unchanged_last_success`, `test_auto_skips_an_unchanged_live_upload_…` | PASS | `auto` on an unchanged file → exactly 1 `skipped` row (v1, 0/0/0, `[]`), no audit entry, no counter, catalog unchanged. The plain string `"auto"` works the same. `manual` and `rebuild` → `success`, v1 kept for the identical hash, 0/0/0, one `policy.import` with `changed_executes` `[]`. Changed bytes in `auto` → v2. A retire reaches the row (0/0/1, v3). A file rejected earlier is retried (2 `rejected` rows, `fail:auto` +2). An unchanged live upload in `auto` → skipped | 2026-10-27 |
| CHK-M7-193 | APP | Linux/PG | r0 `test_warnings_only_…`, `test_a_rejected_file_lists_its_warnings_too` | PASS | `valid/warnings-only.bit` → `success` with BIT101 and BIT103 stored in `errors` (#110). BIT102 + BIT101 → `rejected` with both listed | 2026-10-27 |
| CHK-M7-194 | APP | Linux/PG | r0 `test_before_commit_…`, `test_record_failure_after_a_committed_success_…`, `test_after_commit_…` (2) | PASS | `before_commit` gets an int id (the existing id on an update). If it raises: catalog unchanged, no row, no audit entry, no counter (REQ-162 (4)). If transaction 2 fails after a success: the catalog is committed, `import_id` None, the alert stands, and one log line `bit_import record failed: DivisionByZero` (REQ-160 (4)). `after_commit` sees the policy committed (visible from another connection) and no row yet; if it raises, the `success` row is still written and the error propagates (deviation (5)). It is not called for a rejection or a skip | 2026-10-27 |
| CHK-M7-195 | APP | Linux/PG | r0 `test_the_buffer_is_hashed_and_parsed_once_and_never_reread`, `test_prepare_is_pure_…` | PASS | The file on disk is rewritten after the one read. An audit hook sees no `open` of it during `import_one`. The stored `source_sha256`, the row's `file_sha256` and the plugin Execute all come from the buffer. `prepare` takes only `data`, with no file, socket or process events. A given `prepared` is not redone (spy: 0 calls; without it, 1) | 2026-10-27 |
| CHK-M7-196 | APP | Linux/PG | r0 `test_database_error_in_the_catalog_transaction_is_not_a_rejection` (3 places × 3 modes), `test_record_failure_with_nothing_committed_propagates[rejected, skipped]` | PASS | A real PostgreSQL error (`SELECT 1/0`) before the membership write, after the store, or after the audit entries → `DivisionByZero` propagates. Catalog unchanged, no `bit_import` row, no entry, no counter (#98 (j)). If transaction 2 fails for a rejected or skipped file: the error propagates, with no row, no alert and no count | 2026-10-27 |
| CHK-M7-197 | APP | Linux/PG | r1 `test_500_generated_files_leave_the_catalog_complete_or_unchanged` | PASS | 500 seeded files (structured mutations; 20 % also byte-mutated). About 10 % had a database fault mid-store and about 10 % a `before_commit` `OSError`. After every rejection, skip, refusal or fault, all 4 catalog checksums equal the ones before, with no row on a fault. After every success the policy is exactly the file (name, status, hash, not deleted, plugins in order with Execute and timeout, active, owned by it). Tally asserted (≥ 50 success, ≥ 100 rejected, ≥ 25 faults, ≥ 1 skip) | 2026-10-27 |
| CHK-M7-154-refused | APP | Linux/PG | r0 `test_upload_of_a_server_folder_policy_is_refused_…` | PASS | `PolicyManagedOnServer` is re-raised with the server policy's id. No row, 1 `policy.import_refused` entry (target `policy:<id>`, actor kept, no `alert`, the client-name canary absent), no counter, catalog unchanged (#99 (e)) | 2026-10-27 |
| CHK-M7-154-entries | APP | Linux/PG | r0 `test_reenable_…`, `test_move_from_upload_…`, `test_a_file_renamed_onto_an_uploaded_name_…` | PASS | Re-enable by file → `policy.import` then `policy.status_change` (`policy_reenabled`, `by: file`, `status_overridden: false`). With the admin override → only `policy.import`, and the status stays disabled. Upload to server folder → `policy.move` `{from: uploaded/policy-<id>.bit, to: mv.bit}`, no alert, the copy removed after commit. A file renamed onto an uploaded name → import, move, then `policy.delete` of X (`policy_deleted`, "file now holds another policy"), X `deleted_at` set | 2026-10-27 |
| CHK-M7-154-rebuild | APP | Linux/PG | r0 `test_rebuild_savepoints_…` | PASS | 4 files in one transaction: ok, BIT102, ok, BIT015-against-the-first. Results: success, rejected, success, rejected. No counter moves before the commit; `policy_imported` +2 after it. `record` writes 4 `rebuild` rows (ids returned in order) and 2 rejected alerts; `fail:rebuild` +2; the rejected files leave no entries | 2026-10-27 |
| CHK-M7-154-bit102 | APP | Linux/PG | r0 `test_bit102_rejects_in_every_mode_and_target` (3 modes × 2 target kinds × 6 fixtures × with or without `prepared`) | PASS | Every combination is `rejected` with BIT102 and leaves the catalog unchanged (REQ-157 (3), pipeline half) | 2026-10-27 |
| CHK-M7-154-metric | APP | Linux/PG | r0 `test_failure_metric_counts_once_per_rejection_with_its_mode[auto, manual, rebuild]` | PASS | After 1 and 2 rejections the delta is exactly that number for that mode only, with the rejected alert equal to it | 2026-10-27 |
| CHK-M7-154-logs | APP | Linux/PG | r0 `test_execute_text_names_and_tokens_never_reach_application_logs` | PASS | DEBUG capture across a success, a skip, a BIT102 rejection, a BIT003 rejection and a transaction-2 failure. The Execute canary, a `bsa_` token, the policy-name canary and the client-file-name canary appear in no record (message, args or `__dict__`). The pipeline's own `bit import success` / `rejected` / `skipped` lines are present | 2026-10-27 |
| CHK-M7-154-lock | APP | Linux/PG | r0 `test_import_one_never_takes_the_catalog_lock_itself`, `test_the_callers_lock_spans_the_rename_and_the_record` | PASS | While a probe holds `hashtext('catalog')`, `import_one` on another session still finishes, so it never takes the lock (the contract is in its docstring). With the caller's lock: during `after_commit` the probe's `pg_try_advisory_lock` fails; after `import_one` returns it still fails; after the caller's `catalog_lock` exits it succeeds | 2026-10-27 |
| CHK-M7-300 | APP | Linux/PG | r1 `test_all_samples_import_together_with_no_reject_and_no_bit102` | PASS | Both `bits/samples/*.bit` in one fresh catalog (own container), `auto`, every file present: each `success`, no Reject finding, no BIT102, distinct names, plugin count = sum of added (distinct ids) | 2026-10-27 |
| CHK-M7-301 | APP | Linux/PG | r1 `test_the_sr_example_alone_imports_in_a_fresh_catalog` | PASS | Another fresh catalog: `success`, v1, 1 added; `CIS Ubuntu 24.04 Level 1 - Server` with 1 plugin | 2026-10-27 |
| CHK-M7-154 static | CODE | Linux | ruff, format, mypy (CI form) | PASS | clean, 286 files | 2026-10-27 |

### Plants (copy `scratchpad/t154/<id>`; control `base` 202/202 green; each run is the 3 new files, `-n 4`)

| Check | Plant | Result | Red tests (reason) |
| --- | --- | --- | --- |
| CHK-M7-154-P01 | Success alert committed before the commit point (`COMMIT; BEGIN` after `audit_success`) | PASS (red) | 3 failed: the before-commit rollback test (catalog checksum changed), the rebuild test, fuzz |
| CHK-M7-154-P02 | Alert counters run at once, not on commit | PASS (red) | 5 failed (`{policy_imported: 1}` != `{}`): rollback, 3 × DB error after audit, rebuild |
| CHK-M7-154-P03 | Rejected path changes the catalog (a DB-rule rejection still applied and committed) | PASS (red) | 2 failed: BIT015 (checksum changed), fuzz |
| CHK-M7-369 (a) | `manual` skips too | PASS (red) | 2 failed (`skipped` != `success`) |
| CHK-M7-369 (b) | `auto` never skips | PASS (red) | 6 failed, incl. the SR test and fuzz |
| CHK-M7-154-P06 | A `rejected` record written for an internal error | PASS (red) | 11 failed: 9 DB-error cases, rollback, fuzz (row exists) |
| CHK-M7-350 (count) | `count_failure` removed | PASS (red) | 156 failed |
| CHK-M7-154-P07b | Failure counted under `auto` whatever the mode | PASS (red) | 103 failed (the manual and rebuild rows) |
| CHK-M7-154-P08 | BIT102 step skipped in `prepare` | PASS (red) | 15 failed |
| CHK-M7-333 | BIT102 skipped in `rebuild` mode (import_one and `store_in_savepoint`) | PASS (red) | 8 failed: rebuild sweep rows, the BIT102 matrix, the rebuild savepoint test, fuzz |
| CHK-M7-339 | `bit_import` written in transaction 1 (lost on reject) | PASS (red) | 177 failed |
| CHK-M7-340 | Late exception swallowed (`before_commit` error ignored, transaction 1 committed) | PASS (red) | 2 failed: rollback (DID NOT RAISE), fuzz |
| CHK-M7-349 | No `policy_imported` entry | PASS (red) | 8 failed |
| CHK-M7-350 (alert) | No `policy_import_rejected` entry | PASS (red) | 158 failed |
| CHK-M7-154-P14 | `import_one` takes the catalog lock itself | PASS (red) | 1 failed ("import_one waited on the catalog lock") |
| CHK-M7-154-P15 | Lock released before the rename | PASS (red) | 1 failed (probe got the lock) |
| CHK-M7-154-P16 | File read again from disk | PASS (red) | 1 failed (`open` of `once.bit` recorded) |
| CHK-M7-154-P17 | `Pending` logged | PASS (red) | 1 failed (Execute canary in the log) |
| CHK-M7-154-P18 | Transaction-2 failure after a success propagates | PASS (red) | 2 failed (`DivisionByZero` raised) |

Plants: **19/19 red.**

## Acceptance coverage

- SR §1.1 example: one `success` row and one `policy_imported` alert. CHK-M7-190 PASS.
- Each BIT fixture rejected, with its row and alert and no catalog change. CHK-M7-191 (150 fixtures plus the db, bounds and BIT016 rows) PASS.
- Unchanged file in `auto` → only `skipped`. CHK-M7-192 PASS.
- 500 generated files: complete or unchanged. CHK-M7-197 PASS.
- A rolled-back import writes no success alert. CHK-M7-194 and CHK-M7-196, P01, P02, CHK-M7-340: PASS.
- Also checked: the lock contract, read once, the log canary, audit entries in the same transaction (`xmin`), and the metric once per rejection with its mode. All PASS.

## Findings for the reviewer (none blocking)

1. **The lock contract is documented, not enforced.** `import_one` runs to completion on a session that does not hold `catalog_lock` (shown by `test_import_one_never_takes_the_catalog_lock_itself`). Every current caller is a future task (155 to 158), so a missed lock there would go unnoticed. One option is a cheap guard: a flag set by `catalog_lock` on the session, checked at entry. Reviewer or lead to decide.
2. **`FileInput.sha256` is trusted, not checked against `data`.** `import_one` stores whatever hash the caller passes. The read-once and hash-of-the-same-bytes property therefore belongs to the callers (TASK-155 uploads, TASK-156 folders), and their tests must check it there. A one-line check (`sha256(data) == sha256` when `data` is not None) would make the pipeline self-checking.
3. Deviation (5) behaves as accepted: after a failed `after_commit` there is still one `success` row, and the error is re-raised.
4. `policy.import_refused` detail `{policy_id, mode, file_sha256}`: no client text reaches the entry (canary checked).
