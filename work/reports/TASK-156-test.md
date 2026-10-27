# TASK-156 TEST: PASS (revisions 1 and 2 included)

Tester: tester-m7-156, 2026-10-27. Covers REQ-159 (1), (2), (3), (6), REQ-164 (2), REQ-165 (3), and #15, #102 (b) and #103 (the folder side). Spec: TS §4.1 L515, L524, L526, L528, L532; §4.2; §4.3 L550; §4.6; SR §3.6. Rulings applied (`work/decisions.md`, 2026-10-27):
- "Crash window": a deleted policy's leftover upload is removed and reported.
- "Stray `uploaded/` files are skipped and reported": this amends case (c) and sets the lead's accepted order (server files first, then `uploaded/`, then the removed-file deletes).
- "A live upload file with a hand-edited `<PolicyName>` is skipped and reported like a stray": this ruling came from this test round. Revision 1 implements it.

File under test: `manager/bitscan_manager/services/importer/folders.py` (r1). Checks: CHK-M7-208, -209, -210 (TP-M7-16) and mutation row CHK-M7-363, plus extra plants CHK-M7-156-P*.

Tester file (no product file changed): `manager/tests/test_folders_pg.py`. It has 37 test functions (88 cases) and its own migrated server per module. An autouse fixture soft-deletes, as owner, every policy still live, because the reconcile works on the whole catalog. I wrote the tests from the spec, the TASK-156 row and the rulings first. I read the code afterwards, to find branches and plant targets.

## Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| r0 (pre-r1 code, 85db3c9) | `pytest -n 0 tests/test_folders_pg.py` | 82/82 passed. A probe then found the edited-name churn (Findings 1), which I sent to main |
| r1 (r1 code) | `pytest -n 4 tests/test_folders_pg.py` | **88/88 passed**, 0 failed, 0 errors, 0 skipped |
| r2 (affected set) | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py` | **360/360 passed**, 0 failed, 0 errors, 0 skipped |
| r3 (coverage) | `pytest -n 2 tests/test_folders_pg.py --cov=bitscan_manager.services.importer.folders` | 88/88 passed. `folders.py` 165/166 lines (99.4 %). Only line 233 is not covered: a file that vanishes between `discover` and `read_input` |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |
| plants control | copy at `scratchpad/t156/base` (manager, bits, docs, deploy; no venv), run from the copy's `manager/` with `PYTHONPATH` set to it. The import path printed was the copy's `folders.py` | 88/88 passed |

There were two test bugs, both mine and both fixed. (a) A first draft compared a symlink target with a newly generated file whose UUIDs differed. (b) The parse-count spy patched only `folders.prepare`, so plant P24 (a re-parse inside `import_one`) survived. The spy now patches `pipeline.prepare` too, and P24 goes red. Neither was a product failure.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-208 | APP | Linux/PG | r1 `test_discover_…`, `test_present_matches_discover`, `test_a_symlinked_uploaded_folder_…`, `test_a_missing_uploaded_folder_…`, `test_read_input_never_follows_…`, `test_hostile_entries_are_never_imported` | PASS | The folder holds `n.txt`, `.n.bit`, `A.BIT`, `a.Bit`, `a.bit.txt`, `a.bit~`, `sub/n.bit`, a directory `d.bit/`, FIFO `f.bit`, char device `c.bit`, symlinks `l.bit` (to a.bit), `passwd.bit` (to /etc/passwd), `etc.bit` (to /etc), a dangling link, `o.bit` (to a file outside), `uploaded/.tmp-…`, `uploaded/.policy-2.bit`, `uploaded/sub/…`, an `uploaded/` FIFO and an `uploaded/` symlink. `discover` returns exactly `["a.bit", "uploaded/policy-1.bit"]`. `present` agrees, including `../` and `deleted/1`. A symlinked `uploaded/` folder is not followed. `read_input` returns None for a symlink, FIFO (no block), device, directory or missing file. On PG only `a.bit` is imported, none of the 9 hostile policy names exists, and the file tree (lstat) is identical before and after | 2026-10-27 |
| CHK-M7-208 (#102 b) | APP | Linux/PG | r1 `test_unstorable_names_…`, `test_wanted_name_rules` (17), `test_upload_policy_id` (20) | PASS | The test creates files whose names are `bad\xff.bit`, `a\x01.bit`, `del\x7f.bit` and `uploaded/policy-1\xfe.bit`. Each gives exactly one warning per reconcile and no row. No log record holds the name. The next reconcile does the same. A 255-byte name imports, and a 256-byte one is refused. That limit is in bytes: 125×`é`+`a.bit` passes and 126×`é`+`.bit` fails. Cc controls (TAB, LF, DEL, C1 U+0085) are refused, and U+202E (Cf) is allowed. Ids: no leading zeros, ASCII digits only, ≤ 2^63−1 | 2026-10-27 |
| CHK-M7-208 (oversize) | APP | Linux/PG | r1 `test_read_input_oversize_…`, `test_oversize_server_file_…` | PASS | Exactly 5 MiB is read as data. MAX+1 bytes and MAX+3 MiB give `data=None`, with the hash taken over the whole file. On PG this is one `rejected` `auto` row: BIT001 only, `file_sha256` = the whole-file hash, `imported_by` NULL, catalog unchanged | 2026-10-27 |
| CHK-M7-209 (REQ-159 1) | APP | Linux/PG | r1 `test_req159_1_…` | PASS | `b.bit` edited to `a.bit`'s name gives rows `[a.bit skipped, b.bit rejected]`, with BIT007 naming `a.bit`. Both policies and the catalog checksums are unchanged | 2026-10-27 |
| CHK-M7-209 (REQ-159 2) | APP | Linux/PG | r1 `test_req159_2_…` | PASS | `a.bit` renamed to `c.bit` gives one `success` row for `c.bit` with the same id. `source_file` is `c.bit`, the version is the same, and the members are the same. The audit entries are `policy.import` then `policy.move {from a.bit, to c.bit}`. There is no delete (`deleted == ()`), and the only alert is `policy_imported` +1 | 2026-10-27 |
| CHK-M7-209 (REQ-159 3) | APP | Linux/PG | r1 `test_req159_3_…`, `test_server_files_are_reconciled_before_uploaded_files` | PASS | A server file named like an uploaded policy gives one row (`x.bit success`) and the copy never reaches the pipeline. The policy moves to `x.bit` and `uploaded/policy-<id>.bit` is removed. The audit entries are `policy.import` and `policy.move`. `strays`, `renamed` and `deleted` are all empty. A later upload of that name raises `PolicyManagedOnServer`, and the next reconcile is one `skipped`. Server files always come before `uploaded/` | 2026-10-27 |
| CHK-M7-209 (REQ-159 6, #15) | APP | Linux/PG | r1 `test_req159_6_…` (4 pairs), `test_15_a_live_policys_file_goes_before_a_new_file` | PASS | Of two new files with one name, the byte-order winner imports and the other gets BIT007 naming the winner. Pairs: `a`/`b`, `B`/`a` (raw bytes, not casefold), `a`/`a0`, `z`/`é`. When live `z.bit` renames X to Y in place and new `a.bit` takes X, `z.bit` goes first: rows `[z.bit success, a.bit success]`, Y keeps the old id, and X is new at `a.bit` | 2026-10-27 |
| CHK-M7-210 | APP | Linux/PG | r1 `test_an_unchanged_folder_…`, `test_three_reconciles_and_a_restart_cause_no_churn` | PASS | For 3 server files and 1 live upload, the rows are exactly 4 `skipped` `auto` rows (0/0/0). There is no audit entry and no counter change, the catalog checksums and the file tree are the same, and every result list is empty. Mixed folder (adds a BIT007 loser, a stray and a leftover): after run 1, three runs and a restart (new pool) are identical. The catalog is the same, the rows are `skipped` plus the loser's `rejected` (retried per TS §4.1 L532), and the only entry is `policy.import_rejected` | 2026-10-27 |
| REQ-165 (3) | APP | Linux/PG | r1 `test_new_server_files_…`, `test_a_removed_server_file_…`, `test_a_removed_upload_…`, `test_a_server_file_replaced_by_a_symlink_…`, `test_a_changed_server_file_…` | PASS | New files give `success` `auto` rows with `imported_by` NULL, actor `system` and v1. A removed `a.bit` gives `deleted_at` = clock and `source_file` `deleted/<id>`, keeps the row and the name, and retires both plugins. The audit entry is `policy.delete` (actor `system`, reason `file removed`, `source_file a.bit`), with `policy_deleted` +1. An added `c.bit` imports in the same run. A removed upload is deleted the same way. A server file replaced by a symlink counts as removed, and its target is untouched. A changed file gives v2 with 1 updated | 2026-10-27 |
| (i) | APP | Linux/PG | r1 `test_i_…` | PASS | An unchanged live upload gives one `skipped` row with no audit entry and no alert. Changed, it gives `success` v2, with `source_sha256` = the new hash, the file kept and one `policy.import` | 2026-10-27 |
| (ii) leftover | APP | Linux/PG | r1 `test_ii_…[same, other, names-live, garbage]` | PASS | The test deletes through `delete_policy` and then restores the file (the crash window). Then the file is removed and never read (read spy). There is no row, no entry and no counter change, the catalog is unchanged and the policy row is identical (still deleted). `leftovers == (Difference(path, "leftover of an interrupted delete"),)` with one log line. The next run reports nothing | 2026-10-27 |
| (iii) | APP | Linux/PG | r1 `test_iii_…`, `test_classify_upload_cases` | PASS | A live policy's file with another hash gives `success`, the file stays and `deleted_at` stays NULL. `classify_upload` returns `live`, `leftover`, `stray` (a server policy's copy), `stray` (leading zero, no policy, 2^63−1, 2^63, `x.bit`) | 2026-10-27 |
| (iv) | APP | Linux/PG | r1 `test_iv_…`, `test_spy_contract` | PASS | Spies on `folders.import_one` and `store_decide.decide` over a mixed folder show that no target is `Target("server", "uploaded/…")`. Exactly the 2 live uploads (as `Target("upload", None, sha)`) and the 2 server files reach the pipeline. The 4 strays are reported and the leftover is reported | 2026-10-27 |
| (c) strays | APP | Linux/PG | r1 `test_c_…[new-name, no-policy, leading-zero, over-bigserial, server-copy, live-name]` | PASS | Over 2 runs: `strays == (path,)`, the file is never read, there is no row for it, no audit entry and no counter change. The catalog checksums are the same, the tree is byte-identical and there is one log line without the name. The server policy and the live policy keep their `source_file` | 2026-10-27 |
| r1 edited name | APP | Linux/PG | r1 `test_a_live_upload_with_an_edited_name_…[new-name, other-upload, server-name, new-name-with-bit102]` | PASS | Over 3 runs: `renamed == (path,)`, there is no row, entry or alert for it, and the file is byte-identical. There is one fixed-words log line (no name, no path), and each file is parsed once (3 parses). The policy row is identical (not deleted). The new name never exists, the server policy is unchanged and there is no `policy.import_refused`. The changed later upload still imports (`success`, then `skipped`) | 2026-10-27 |
| r1 no valid name | APP | Linux/PG | r1 `test_a_live_upload_with_no_valid_name_…[unparsable, oversize, bad-name]` | PASS | Over 3 runs: one `rejected` row with the file's hash and one `policy.import_rejected`. `renamed`, `strays` and `deleted` are empty, the catalog and the policy row are unchanged, and the file is kept | 2026-10-27 |
| carry (a) lock | APP | Linux/PG | r1 `test_the_lock_spans_every_import_…` | PASS | The lock is held at each of the 3 imports and still held when `reconcile` returns. A concurrent `delete_policy` waits (still alive after 1 s) and completes after the reconcile's block ends. Then the lock is free | 2026-10-27 |
| carry (c) temp | APP | Linux/PG | r1 `test_reconcile_leaves_temp_files_and_writes_no_file` | PASS | Does not apply (no temp file is written, as the impl report says). A `.tmp-<id>-<sha>` is left byte-identical, and an unchanged reconcile leaves the tree identical | 2026-10-27 |
| logs | APP | Linux/PG | r1 `test_reconcile_never_logs_file_content_or_names` | PASS | A canary in file names, a policy name, an Execute, a malformed file and a symlink appears in no log record (message, args or `__dict__`) over 2 runs | 2026-10-27 |

### Plants (copy `scratchpad/t156/<id>` of the r1 base; control 88/88 green; each run is `test_folders_pg.py`, `-n 4`): 32/32 red

| Check | Plant | Red |
| --- | --- | --- |
| CHK-M7-363 / P01 | `entry.is_file(follow_symlinks=True)` | 1 (discover) |
| P01b | `present` uses `os.stat` | 2 (present, symlink-replaced file) |
| P01c | O_NOFOLLOW dropped | 1 (read_input) |
| P01d | `_real_dir` follows a symlinked `uploaded/` | 1 |
| P02 | stray falls through to import | 9 |
| P03 | leftover imported (revived) | 6 |
| P03b | leftover removed but not reported | 6 |
| P03c | leftover not removed | 5 |
| P04 | deletes before imports | 2 (REQ-159 (2) and the removed file) |
| P05 | `Mode.MANUAL` (skips become `success`) | 24 |
| P06a | #15 byte order reversed | 10 |
| P06b | existing-file-first dropped | 1 (`test_15_…`) |
| P06c | casefold order | 1 (`B.bit`/`a.bit`) |
| P07 | uploads before server files | 7 |
| P08 | Cc check dropped | 6 |
| P08b | length in characters, not bytes | 1 |
| P09 | leading zeros accepted | 2 |
| P10 | BIGSERIAL cap dropped | 2 (unit only; see Findings 3) |
| P11 | hidden files kept | 5 |
| P12 | case-insensitive `.bit` | 4 |
| P14 | a server policy's copy treated as a leftover (removed) | 5 |
| P14b | live treated as leftover | 27 |
| P15 | uploads read as server targets | 23 |
| P16 | reconcile releases the catalog lock | 1 |
| P17 | unstorable name written to the log | 1 |
| P18 | stray removed | 8 |
| P19 | O_NONBLOCK dropped | red by hang: the FIFO test is killed at 30 s (exit 124) |
| P20 | fstat regular-file check dropped | 1 (char device read) |
| P21 | stray not reported | 9 |
| P22 (r1) | edited-name check disabled | 4 |
| P23 (r1) | edited name not listed in `renamed` | 4 |
| P24 (r1) | `prepared` not passed (parsed twice) | 4 |

The pre-r1 plant P13 (refused aborts the reconcile) is retired, because `refused` no longer exists. The 13 plants P01 to P06c were also red on the pre-r1 code.

## Findings for the reviewer (none blocking)

1. Fixed in r1. The pre-r1 code sent a live upload with an edited `<PolicyName>` through the pipeline. With a new name, each reconcile inserted or revived that policy and then deleted it: versions 1, 2, 3, with an import and a delete alert every time. With another uploaded policy's name, each reconcile flip-flopped that policy (versions 3, 5, 7). Main got the user's ruling. Those cases are now PASS criteria over 3 runs.
2. A missing or symlinked `uploaded/` folder makes `discover` find no uploads, so `delete_removed` soft-deletes every live uploaded policy. This follows from the spec ("policies whose files disappeared are deleted"; symlinks are never followed), but a mis-mounted folder would delete them all, with an alert for each. It is not asserted here. The reviewer or TASK-158 may want a guard or an explicit ruling.
3. P10: without the BIGSERIAL cap, PostgreSQL compares the out-of-range id as numeric and finds no row, so the PG path still gives `stray`. Only the unit test catches it. That is harmless.
4. A BIT007 loser, or any rejected folder file, writes a `rejected` row and a `policy.import_rejected` alert at every reconcile. TS §4.1 L532 says to retry, and #103 counts the rejected row. Expected, but noisy at every start-up.
5. `folders.import_one`, `folders.prepare` and `pipeline.store_decide` are re-exports that the spies patch. The tests use `pipeline.import_one` and `pipeline.prepare` for the real calls, so mypy is clean.

## Revision 2 (tester-m7-156r2, 2026-10-27): folder guard: PASS

Ruling: `work/decisions.md`, 2026-10-27, user "Folder guard" and lead "Folder guard details" (1). The code under test is `folders.py` at HEAD 09fcf66 (r2: `unreadable`, `BITS_ROOT`, `ReconcileResult.unreadable_folders`, the guard in `reconcile` and `delete_removed`, and `discover` returning `[]` for a bits folder that is not a real directory). This revision closes r1 Finding 2. I wrote the expected values from the two rulings first. I read the code afterwards, only to choose plant targets. No product file changed.

File changed: `manager/tests/test_folders_pg.py`. It gains 7 test functions (23 cases), so it now has 44 functions (111 cases).

### Runs (Linux container, Docker PostgreSQL 16, `CI=true`, RYUK pinned, nothing skipped)

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| baseline (HEAD, before the new tests) | `pytest -n 4 tests/test_folders_pg.py` | 88/88 passed |
| r2 file | `pytest -n 4 tests/test_folders_pg.py` | **111/111 passed**, 0 failed, 0 errors, 0 skipped (r1's 88 are among them) |
| r2 affected set | `pytest -n 4 tests/test_folders_pg.py tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py tests/test_catalog_lock_pg.py` | **383/383 passed**, 0 failed, 0 errors, 0 skipped |
| coverage | `pytest -n 2 tests/test_folders_pg.py --cov=bitscan_manager.services.importer.folders` | 111/111 passed. `folders.py` 179/180 lines (99.4 %). Only line 256 is missed: a file that vanishes between `discover` and `read_input`, the same branch as in r1 |
| static | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (291 files) |
| plants control | copy at `scratchpad/t156r2/base` (rebuilt from the current tree). The import path printed was the copy's `folders.py` | 111/111 passed |

`test_uploads*.py` were not run. They belong to TASK-155 r2, which is in progress, and `folders.py` does not import `uploads.py`. The `upload()` helper here goes through `uploads.import_upload` and works at HEAD.

### Report rows

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| r2 labels (no DB) | CODE | Linux | `test_unreadable_labels` (10) | PASS | `unreadable()` returns `()` for real folders and for real empty ones. It returns `("uploaded/",)` when `uploaded/` is missing, a symlink to a real folder, a dangling symlink or a regular file. It returns `("./", "uploaded/")` when the bits folder is missing, a symlink to a real folder, a file, or a symlink to a folder with no `uploaded/`. In every case `discover` returns only the files of readable folders (`[]` through a symlinked bits folder), and the whole tmp tree (lstat) is unchanged | 2026-10-27 |
| r2 `uploaded/` unreadable | APP | Linux/PG | `test_an_unreadable_uploaded_folder_is_left_alone_and_the_server_folder_reconciled[missing, symlink, file]` | PASS | Setup: server S and R, live upload U, deleted upload D. Then `uploaded/` is broken. Its real folder (the symlink target) holds U's file changed, D's leftover and a stray. `r.bit` is removed and `n.bit` added. Over 3 reconciles: `unreadable_folders == ("uploaded/",)`; there is no `bit_import` row for any `uploaded/` path, and `read_input` is never called for one (spy). Leftovers, strays and renamed are empty. U's and D's rows (incl. xmin) and member states are identical, and the real folder's tree is byte-identical. There is exactly one guard log line per run, ending in the label, identical across runs, with no tmp path, `/bits` or `policy-` in any record. Run 1 reconciles the server folder normally: `n.bit success`, `s.bit skipped`, R deleted (`deleted_at` = clock), `policy.import` and `policy.delete`, +1/+1 alerts. Runs 2 and 3 give only skips, no audit entries, no counter change and the same catalog. Recovery: `()`, U `success` with the new hash, D reported as a leftover, the stray reported, no delete | 2026-10-27 |
| r2 bits folder unreadable | APP | Linux/PG | `test_an_unreadable_bits_folder_makes_both_folders_unreadable[missing, symlink, file]` | PASS | The real folder (the symlink target) holds `s.bit` changed, `r.bit` removed, a new `n.bit`, U's file changed, D's leftover and a stray. Over 3 reconciles: `("./", "uploaded/")`, two guard lines per run, no rows, no audit entries, no counter change, same catalog, and empty outcomes, deleted, leftovers, strays and renamed. S, R, U and D are identical, the target tree is byte-identical, `read_input` is never called, and `discover(bits) == []`. Recovery: `()`, R deleted, `n.bit` and `s.bit` `success`, U's new hash, D reported as a leftover | 2026-10-27 |
| r2 both together | APP | Linux/PG | `test_both_folders_unreadable_together[missing, symlink, file]` | PASS | A symlinked bits folder whose own `uploaded/` is missing, a symlink or a file, with `s.bit` also removed in the target. Over 2 runs: `("./", "uploaded/")`, two lines, no rows or entries, no deletes, same catalog, the policies identical and the whole tmp tree unchanged | 2026-10-27 |
| r2 real empty folder | APP | Linux/PG | `test_a_real_empty_folder_still_deletes_its_policies[uploaded, server, both]` | PASS | Empty real `uploaded/` (`listdir == []`), a bits folder holding only `uploaded/`, or both. Run 1: `()`, no guard line, exactly the folder's policies soft-deleted (`deleted_at` = clock, `deleted/<id>`, members retired, `policy.delete` with reason `file removed`, `policy_deleted` +n), the other folder's policies kept. Runs 2 and 3: nothing deleted, no entries, no counter change, same catalog | 2026-10-27 |
| r2 `delete_removed` direct | APP | Linux/PG | `test_delete_removed_skips_an_unreadable_folder_but_not_an_empty_one` | PASS | With `uploaded/` missing it returns only R (the server folder still works) and U stays live. With `uploaded/` real and empty it returns U. With the bits folder a symlink and `s.bit` gone in the target it returns `()` and S stays live | 2026-10-27 |

### Plants (copy `scratchpad/t156r2/<id>` of the r2 base; control 111/111 green; each run is `test_folders_pg.py`, `-n 4`): 10/10 red

| Plant | Change | Red |
| --- | --- | --- |
| R1 | guard skipped in `reconcile` (`blind = ()`) | 9 |
| R2 | guard skipped in `delete_removed` (`blind = ()`) | 10 |
| R3 | a symlinked bits folder lists only `"./"` | 6 |
| R3b | any unreadable bits folder lists only `"./"` | 10 |
| R4 | label missing from the result (last field `()`) | 9 |
| R5 | `_real_dir` uses `stat` (follows links) | 10 |
| R6 | a real empty folder treated as unreadable | 5 (labels `both-empty`, empty `[uploaded]` and `[both]`, the `delete_removed` test, r1's removed-upload test) |
| R7 | `discover`'s bits-folder check dropped (reads `uploaded/` through a symlinked bits folder) | 2 |
| R8 | guard log line also carries `bits_dir` | 9 |
| R9 | guard log line dropped | 9 |

### Findings for the reviewer (none blocking)

1. r1 Finding 2 (a mis-mounted `uploaded/` deletes every uploaded policy) is fixed and is now a PASS criterion.
2. Plant R6 does not turn `test_a_real_empty_folder_still_deletes_its_policies[server]` red. A bits folder always holds `uploaded/`, so it is never literally empty. The case still covers "a bits folder with no `.bit` file is readable".
3. On recovery, a folder that comes back with changed content is imported normally (a `success` row and an alert), and a leftover inside it is removed then. That is the expected behaviour, not churn: the guard only defers the reconcile.
4. Through a symlinked bits folder, `present(bits, "s.bit")` still resolves the link, because `lstat` does not follow only the last path component. This is harmless, because `delete_removed` checks `unreadable` first (plant R2 shows the guard is what protects), but TASK-157 should keep that order.
5. The guard log words are not pinned. The tests check one line per folder, ending in its label, identical across runs, with no path.
