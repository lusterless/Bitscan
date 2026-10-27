# TASK-156 IMPL: folders (discovery, `uploaded/` classification, auto reconcile)

Implementer: impl-manager-156. Spec: TS §4.1 (L515, L524, L528, L532), §4.2, §4.3 (L550), §4.6; SR §3.6; REQ-159 (2), (3), (6), REQ-164 (2), REQ-165 (3); #15, #102 (b), #103; decisions 2026-10-27 "Crash window" (both rows) and **"Stray `uploaded/` files are skipped and reported, never imported"** (the last row, which amends case (c) of the task row; see below).

## Files

- `manager/bitscan_manager/services/importer/folders.py` (new, 263 lines, 197 of them code, about 45 of those imports and formatter-split calls). This is the only product file changed. It writes no file outside the leftover removal, and it does not touch `pipeline*.py`, `store*.py`, `delete.py` or `uploads.py`.
- `pipeline_record.py`'s new `FileInput.__post_init__` hash check (TASK-155) is satisfied: `read_input` builds `FileInput(data, sha, rel, Target(..., sha))`, where `sha` is the SHA-256 of `data`, or of the whole file when it is oversize (`data` None).

## Public API (for TASK-157, -158, -159)

All of these run under the catalog lock the caller holds (`catalog_lock(session)`). None takes or releases it (module docstring).

| Function | Line | Purpose |
| --- | --- | --- |
| `discover(bits_dir) -> list[str]` | folders.py:106 | Relative paths of the `*.bit` regular files in the bits folder and in `uploaded/`. |
| `present(bits_dir, rel) -> bool` | :112 | Whether `discover` would find `rel`. It is the `file_exists` for `decide` (BIT007) and the test for a disappeared file. |
| `read_input(bits_dir, rel) -> FileInput \| None` | :126 | Reads the file once with `O_NOFOLLOW \| O_NONBLOCK \| O_CLOEXEC`, then `fstat` must show a regular file. Over 5 MiB, `data` is None and the hash covers the whole file (#99 (b)). A server file gets `Target("server", rel, sha)`; `uploaded/…` gets `Target("upload", None, sha)`. Returns None if the file is gone or not regular. |
| `upload_policy_id(rel) -> int \| None` | :150 | `n` of `uploaded/policy-<n>.bit`: ASCII decimal, no leading zeros, ≤ 2^63−1 (BIGSERIAL, so PostgreSQL never sees an out-of-range id). |
| **`classify_upload(conn, rel) -> "live" \| "leftover" \| "stray"`** | :160 | **The one shared classification** of an `uploaded/` file, in the caller's transaction (it locks the policy row `FOR UPDATE`). The reconcile uses it, and TASK-157 must use it. |
| `remove_leftover(bits_dir, rel) -> Difference` | :179 | Removes the file through `delete.remove_after_commit` (upload paths only), writes one log line and returns `Difference(rel, "leftover of an interrupted delete")`. |
| `reconcile(session, clock, bits_dir) -> ReconcileResult` | :187 | TS §4.1 L528 in `auto` mode. |
| `delete_removed(session, clock, bits_dir) -> tuple[DeleteResult, ...]` | :241 | Soft-deletes each live policy whose `source_file` is not `present`, through `delete.delete_in_tx` (reason "file removed", actor `system`), one transaction each, then `remove_after_commit`. |

`ReconcileResult` (:64) holds `outcomes` (one `ImportOutcome` per file that reached the pipeline), `refused`, `deleted`, `leftovers` (#103 `Difference`s for TASK-158's alert) and `strays` (paths for the #103 check).

## Classification table (`classify_upload`)

| Case | Condition | Action |
| --- | --- | --- |
| (a) live | `uploaded/policy-<n>.bit`, policy `n` exists, `deleted_at` NULL, `source_file` = that path | Normal pipeline, `Target("upload", None, sha)`, mode `auto`. It is `skipped` when the hash equals `source_sha256` (TASK-151 r3 `is_unchanged`) and `success` when changed. |
| (b) leftover | `uploaded/policy-<n>.bit`, policy `n` has `deleted_at` set | `remove_leftover`: the file is removed, nothing is imported, no `bit_import` row is written, `deleted_at` is kept, one log line, and it is returned in `leftovers` as `Difference(path, "leftover of an interrupted delete")`. |
| (c) stray (**amended**, decisions 2026-10-27 last row) | anything else: another name, no policy `n`, or a live policy whose `source_file` is elsewhere (for example a server-folder policy's old uploaded copy) | **Never imported.** One log line, skipped, no `bit_import` row, no alert, no catalog change. Returned in `strays` so the #103 integrity check (TASK-158) reports it. The task row's original (c), "the normal pipeline as an upload target", churned: a stray new name made a policy with no file that the same reconcile deleted and the next one revived, and a stray copy of a live policy flip-flopped its bytes. I raised it, and the user ruled option B. |

`refused`: a case (a) file whose content was edited by hand to name a server-folder policy still raises `PolicyManagedOnServer` from `decide`. `import_one` writes its `policy.import_refused` entry; the reconcile logs one line, lists the path in `refused` and goes on.

## Reconcile order (accepted by the lead, decisions 2026-10-27 last row)

1. `discover`, then read the live `source_file` set (`catalog_integrity.integrity_rows`, read-only).
2. Server files in **#15 order**: a file that is already a live policy's `source_file` first, then by UTF-8 path bytes. The later file of a shared new name gets BIT007 from `decide` (REQ-159 (6)).
3. Then the `uploaded/` files (path-byte order), each classified first in its own short transaction, then read and imported. **Server files go first**, so a server file that takes an uploaded policy's name moves it (`move_upload`, `policy.move` entry, and the pipeline removes the uploaded copy). That copy is then gone: classify sees a stray (the policy's `source_file` is now the server file), `present` is false, so it is neither logged nor listed. See tester case 4.
4. **All imports before the deletes** (`delete_removed`), re-read after the imports (builder-checklist 9). With `a.bit` removed and `c.bit` added under the same name, the result is `move_server` (same id, one `policy.move`) and not delete-then-revive (REQ-159 (2)).

## Acceptance items

- REQ-164 (2): `_names` (:90) keeps only `entry.is_file(follow_symlinks=False)` entries, so symlinks, FIFOs, devices and subfolders are dropped. `_wanted` (:72) requires the `.bit` suffix (case-sensitive) and no leading `.`. A swapped-in FIFO or symlink between scandir and open is caught by `O_NOFOLLOW` (ELOOP) and `O_NONBLOCK` plus the `fstat` regular-file check. A symlinked `uploaded/` folder is never followed (`_real_dir` uses `lstat`).
- #102 (b), unstorable names: a name that is not valid UTF-8 (surrogate escapes), holds a Unicode `Cc` control character, or is over 255 bytes is logged once with fixed words (never the name) and skipped. No row is written.
- REQ-159 (2), (3), (6): the order above, plus `decide` and `present` as `file_exists`.
- REQ-165 (3): new and changed files are imported (`auto`), and policies whose files disappeared are deleted (`delete_removed`).
- An unchanged folder writes only `skipped` rows. Files rejected earlier (for example a BIT007 loser) are tried again and rejected again, per TS §4.1 L532.
- Read once: each file is opened and read one time; a leftover or a stray is never read.
- Reviewer carry (c), the temp file after a failed COMMIT: **does not apply**. The reconcile passes no `before_commit` and writes no file. Its only removals are the leftover's and the pipeline's own `remove_after_commit`.
- Logging: no file content, no `Execute`, no file names except a leftover's `uploaded/policy-<n>.bit` (a validated, manager-made name).

## Gates (repo root, Linux container)

- `ruff check manager && ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues (288 files).
- Regression: `pytest tests/test_import_pipeline_pg.py tests/test_import_store_pg.py tests/test_policy_delete_pg.py` (Docker PG) gives 252 passed.
- Scratch smoke runs on PG (my own throwaway files, deleted, not project tests). Hidden, `.txt`, symlink, FIFO, subfolder and control-character names are skipped. Two server files with one name: the first imports, the second gets BIT007. A second reconcile gives `skipped` plus a repeat `rejected` and nothing else. A stray `uploaded/x.bit` is skipped with no row. `a.bit` renamed to `c.bit` gives `success` with `policy.import` and `policy.move` and no delete. A deleted policy's re-created upload file is removed, with no row, `deleted_at` kept and one `Difference`. A live unchanged upload is `skipped`; after an edit it is `success`.

## Cases for the tester (TP-M7-16, `manager/tests/test_folders_pg.py`)

1. REQ-164 (2): `n.txt`, `.n.bit`, `sub/n.bit`, FIFO `f.bit`, symlink `l.bit` (to a valid file), and a symlinked `uploaded/` folder: no row, no policy.
2. #102 (b): names with invalid UTF-8 (`b"bad\xff.bit"`), a control character (`"a\x01.bit"`), and 256 bytes is impossible on most file systems, so cover that one with a unit test on `_wanted`. Each gives one log line, no row, and the log does not contain the name.
3. Oversize (> 5 MiB) server file: one `rejected` BIT001 row whose `file_sha256` is the whole file's hash.
4. REQ-159 (2), (3), (6), REQ-165 (3) as listed. For (3), also check the order: a server file and `uploaded/policy-<id>.bit` with the same name in one reconcile give one `policy.move`, the upload file is removed, `strays` is empty, and the reconcile does not fail.
5. Extra (i): a live policy's unchanged upload file gives one `skipped` row and no alert; a changed one gives `success`.
6. Extra (ii): a leftover is removed, no row is written, `deleted_at` is kept, and it is returned in `leftovers` with the check text `leftover of an interrupted delete`.
7. Extra (iii): the leftover rule never fires for a live policy, including a live policy whose upload file has another hash (that one is `success`).
8. Extra (iv): spy on `folders.import_one` (or `store_decide.decide`). No target is ever `Target("server", "uploaded/…")`, and no stray reaches it.
9. **Amended (c) (decisions 2026-10-27 last row):** `uploaded/x.bit` (new name), `uploaded/policy-99.bit` (no policy 99), `uploaded/policy-01.bit` (leading zero), `uploaded/policy-99999999999999999999.bit` (over BIGSERIAL), and a server-folder policy's old copy `uploaded/policy-<id>.bit` whose `source_file` is `a.bit`. Each gives no `bit_import` row, no alert or audit entry, no catalog change (checksums), the file left in place, and the path in `ReconcileResult.strays`. A second reconcile gives the same result (no churn).
10. `refused`: edit a live upload file to carry a server policy's name. You get one `policy.import_refused` entry, no row, and the path in `refused`, and the reconcile goes on to the next file.
11. Removed upload: delete `uploaded/policy-<id>.bit` of a live policy. The reconcile soft-deletes it (`policy.delete`, reason "file removed", actor `system`).
12. Carry (a) (TASK-154 review): the caller holds the lock. TASK-158 owns the call site; for this module, a test can show that a concurrent `delete_policy` waits until the reconcile's `catalog_lock` block ends.

## For TASK-157 and TASK-158

- TASK-157: call `classify_upload` in the rebuild's transaction. Handle `leftover` with `remove_leftover` (after the commit, or before it, since the file is never imported), then list it in `removed_leftovers`. Skip `stray`. `read_input` and `present` can be reused.
- TASK-158: `ReconcileResult.leftovers` are ready-made `Difference`s. `strays` are paths that the #103 folder-side check already flags (no live `source_file` and no rejected row).

## Revision 1 (impl-manager-156b): a live upload with an edited `<PolicyName>` is skipped

Ruling: `work/decisions.md`, last row, "A live upload file with a hand-edited `<PolicyName>` is skipped and reported like a stray" (user, 2026-10-27). Only `manager/bitscan_manager/services/importer/folders.py` changed. It is now 281 physical lines and 207 code lines (blank lines, comments and docstrings excluded; it was 197).

### What changed

- **`renamed(conn, rel, prepared) -> bool`** (folders.py:178), new and public so that TASK-157's rebuild can use the same rule. A "live" upload is `renamed` when `prepared.rules.policy_name` is not None and differs (exact string comparison, as `decide` matches names) from the current `policy_name` of policy `<id>`, which it reads with `policy_by_id_for_update`. A file with no valid name (`rules` is None, or `policy_name` is None: unparsable, oversize, BIT002, invalid `PolicyName`) is not `renamed`, so it goes through the pipeline and is recorded as `rejected`, as before. A file whose name was edited **and** that has other Reject findings is still `renamed`, so it is skipped and writes no rejected row, because its `<PolicyName>` differs.
- **`reconcile`** (folders.py:200). Each file read is parsed once (`prepare`, :234). For an `uploaded/` file classified "live", `renamed` runs in its own short transaction (:236–:241). If it is true, the reconcile writes one fixed-words warning, `uploaded file skipped: its policy name was edited` (no name, no path, no content), adds the path to `ReconcileResult.renamed`, and continues. There is no pipeline call, no `bit_import` row, no audit entry, no alert and no catalog change, so the policy keeps its last good rows. Otherwise the parse result goes to `import_one(prepared=prepared)` (:250). Server files also pass their `prepared`.
- **`ReconcileResult`** (:62). There is a new field, **`renamed: tuple[str, ...]`** (:67): live uploads skipped for an edited name, for the #103 check (TASK-158). I did not reuse `strays`. A renamed file *is* its policy's `source_file`, so TASK-158 should report it with its own check text (its hash also differs from `source_sha256`). **`refused` is removed.** The `except PolicyManagedOnServer` branch is gone too. Under the catalog lock, a live upload can only reach `decide` with its own policy's name, which is never in the server folder, so `refused` would always have been empty. The old refusal (a `policy.import_refused` entry and the path in `refused`) is now this skip. Field order: `outcomes, deleted, leftovers, strays, renamed`.
- `classify_upload` is unchanged in behaviour. Its docstring now says "live … unless `renamed`".

### Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (291 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: product code is clean. There are 17 errors, all in the tester's `manager/tests/test_folders_pg.py`. 13 of them are from the removed `refused` field (`attr-defined`, plus `comparison-overlap` on the chained `res.refused == res.deleted == …` at lines 517 and 560). 4 were already there (lines 1049, 1050, 1061, 1225: `folders.import_one` and `pipeline.store_decide` are not explicitly exported).
- PG run from `manager/`: `test_folders_pg.py test_import_pipeline_pg.py test_import_store_pg.py test_policy_delete_pg.py` gives **317 passed, 17 failed**. All 17 failures are in `test_folders_pg.py`, and each is `AttributeError: ... no attribute 'refused'`:
  - 15 only read `res.refused == ()` as part of an assertion: `test_hostile_entries_are_never_imported`, `test_unstorable_names_are_logged_once_and_skipped`, `test_new_server_files_are_imported_in_auto_mode_by_the_system`, `test_an_unchanged_folder_writes_only_skipped_rows`, `test_three_reconciles_and_a_restart_cause_no_churn` (in the `states` tuple, line 605), `test_req159_3_server_file_takes_an_uploaded_policy`, `test_ii_a_leftover_is_removed_never_imported_and_reported[same|other|names-live|garbage]`, `test_c_strays_are_never_imported_and_are_reported[new-name|no-policy|leading-zero|over-bigserial|server-copy|live-name]`. With `refused` dropped from those assertions (throwaway copy, now deleted), all of them pass.
  - 1 tests the old behaviour: `test_a_live_upload_edited_to_a_server_policys_name_is_refused` (line 1163). Now it should expect: `res.renamed == (first,)`, no `policy.import_refused` entry, rows `[("srv.bit","skipped"), (later,"success")]`, actions `["policy.import"]`, the server policy unchanged, and `first` left in place.
- Throwaway smoke (a copy of the test file in `manager/tests/`, deleted afterwards). One live upload, `uploaded/policy-<u1>.bit`, rewritten as each case below and then reconciled 3 times in a row. Every case passed all 3 runs.

### Cases for the tester

| Case | Each of 3 reconciles in a row |
| --- | --- |
| New name (`<PolicyName>` used by no policy) | `renamed == (rel,)`; no `bit_import` row for it; no audit entry or alert; catalog checksums unchanged; the file left byte-identical; `strays == ()` and `deleted == ()`; one log line containing neither the name nor the path |
| Another uploaded policy's name | the same as above; that other policy's `source_sha256` and rows unchanged (no flip-flop) |
| A server-folder policy's name | the same as above; **no** `policy.import_refused` entry; the server policy unchanged |
| Same name, changed content | 1st: `success` (`policy.import`); 2nd and 3rd: `skipped`, no audit entry; `renamed == ()` |
| Same name, unchanged | `skipped` every time, no audit entry, `renamed == ()` |
| Unparsable (`<not xml`) and oversize (> 5 MiB) | `rejected` every time with one `policy.import_rejected` alert (TS §4.1 L532 retry), `renamed == ()` |
| Also worth covering | Edited name plus another Reject finding (for example a BIT102 `Execute`): skipped as `renamed`, with no rejected row. A spy on `folders.prepare` or `parse_bit` shows each file is parsed once per reconcile. A renamed file's policy is still listed by `integrity_rows` and is not deleted by `delete_removed` (its file is present). |

### For TASK-157 and TASK-158

- TASK-157 (rebuild): after `classify_upload(...) == "live"` and `prepare`, call `renamed(conn, rel, prepared)` in the rebuild transaction. If it is true, skip the file the way a stray is skipped, with no `store_in_savepoint`. The policy keeps its rows only if the rebuild does not otherwise drop them; that is TASK-157's design.
- TASK-158: report `ReconcileResult.renamed` alongside `strays`. `refused` no longer exists.

## Revision 2 (impl-manager-156b): folder guard

Ruling: `work/decisions.md`, last row, "Folder guard" (user, 2026-10-27). Also the row "Folder guard details" (1) (lead). The r1 choices are accepted (lead). Only `manager/bitscan_manager/services/importer/folders.py` changed: 311 physical lines, 226 code lines (r1 had 207). `uploads.py` is untouched.

### What changed

- `BITS_ROOT = "./"` (folders.py:49), next to the existing `UPLOADED = "uploaded/"`. These two constants are the labels for the folders.
- **`unreadable(bits_dir) -> tuple[str, ...]`** (:106) is new and public, so TASK-157 and TASK-158 can use it. `_real_dir` uses `lstat` and never follows a link, so a folder that is missing, a symlink, or a non-directory (a file) is unreadable. If the bits folder is unreadable, it returns **both** `("./", "uploaded/")`, because `uploaded/` sits inside it ("Folder guard details" (1)). Otherwise it returns `("uploaded/",)` when `uploaded/` is unreadable, else `()`. A real empty folder is readable. `discover` (:121) returns `[]` when the bits folder is not a real directory, so nothing is read through a symlinked bits folder. `_folder(rel)` (:115) maps a `source_file` to its folder label.
- **`ReconcileResult.unreadable_folders`** (:69) is a new last field, in the fixed order `("./", "uploaded/")`, for TASK-158's `catalog_integrity_failed` alert.
- **`reconcile`** (:215):
  - It computes `unreadable` once at the start. For each unreadable folder it logs one fixed-words line, `folder unreadable, not reconciled: <label>`, where the label is one of the two constants and never a path from disk.
  - `discover` already finds nothing in an unreadable folder, because `_names` checks `_real_dir`, so nothing is imported from it.
  - The other folder is reconciled as before: imports, leftovers, strays and renamed files.
- **`delete_removed`** (:282) checks `unreadable(bits_dir)` again when it runs. It skips every live policy whose `source_file` folder is unreadable (:294), so no policy in that folder is deleted. In a readable folder, a file removed by hand still deletes its policy, and a real empty folder deletes all of its policies.

### Behaviour notes for the tester and reviewer

- **The bits folder is missing, a regular file, or a symlink:** both folders are listed, `("./", "uploaded/")`, and nothing is read or deleted in either.
- **Residual, not changed (owned by `delete.py` and `pipeline`):** a server file that takes an uploaded policy's name still moves it (`move_upload`, server folder wins). The pipeline's `remove_after_commit` then unlinks `bits/uploaded/policy-<id>.bit`. If `uploaded/` is a symlink, that unlink resolves through the link and removes the copy in the link's target. Before this revision the same was already true. It is being handled in TASK-155 r2 by impl-manager-155 ("Folder guard details" (2)); not changed here.

### Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (291 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues (291 files).
- PG run, from `manager/`: `test_folders_pg.py test_import_pipeline_pg.py test_import_store_pg.py test_policy_delete_pg.py` gives **340 passed** (re-run after the "details" change: 340 passed). No existing test asserted the old mass delete, so none fails.
- `test_uploads.py test_uploads_pg.py`: 10 failures (for example `broken() got an unexpected keyword argument 'src_dir_fd'`). These come from TASK-155's in-progress uploads tests and code, not from this change: `uploads.py` does not import `folders`.
- Throwaway smoke test (a copy of the test file, now deleted). Setup: one server policy, one uploaded policy, one reconcile. I then broke a folder and ran 2 more reconciles. Results:

| Broken | missing | symlink to a real copy | regular file |
| --- | --- | --- | --- |
| `uploaded/` | `("uploaded/",)` | `("uploaded/",)` | `("uploaded/",)` |
| bits folder | `("./","uploaded/")` | `("./","uploaded/")` (after the "details" change, checked on scratch folders: `discover` gives `[]`) | `("./","uploaded/")` |

  In every cell, nothing was deleted on either run, there were no audit entries, and `deleted == ()`. An empty real `uploaded/` gave `()`, and the uploaded policy was deleted once (`policy.delete`) while the server policy was kept. An empty real bits folder (server file removed, `uploaded/` real) gave `()`, and the server policy was deleted once while the uploaded policy was kept.

### Cases for the tester

1. For each folder (`uploaded/`, then the bits folder): missing, a symlink to a real folder holding the policies' files, and a regular file in its place. Check each of these over 2 reconciles in a row:
   - `unreadable_folders` is as in the table above.
   - No policy whose `source_file` is in the unreadable folder gets `deleted_at` set, and there is no `policy.delete` entry.
   - No `bit_import` row is written for any path in that folder, and nothing is followed through a symlink.
   - Exactly one log line per unreadable folder, and it contains no path from disk.
2. The other folder is still reconciled. With `uploaded/` unreadable, a new or changed server file is imported, and a removed server file deletes its policy. With the bits folder a symlink, **both** folders are unreadable: no upload is read through the link (spy on `read_input`), and no policy in either folder is deleted.
3. A real empty folder: `unreadable_folders == ()`, and each policy in it is soft-deleted once (`reason "file removed"`). The next reconcile writes nothing.
4. Both folders unreadable (the bits folder missing, a symlink, or a file): `("./", "uploaded/")`, no deletes, no rows, no audit entries.
5. Recovery: put the folder back as a real directory with the same files. The next reconcile gives `unreadable_folders == ()` and only `skipped` rows (no churn).
6. Call `delete_removed` directly with `uploaded/` missing: it returns `()` for the uploaded policies.

### For TASK-157 and TASK-158

- TASK-157 (rebuild): call `unreadable(bits_dir)` before reading the folders. Read no files from an unreadable folder, and do not retire or delete its policies.
- TASK-158: raise `catalog_integrity_failed` listing each label in `ReconcileResult.unreadable_folders`, together with `strays`, `renamed` and `leftovers`.

## Revision 3 (impl-manager-156b): three-way absence test and no-follow reads

Source: review `work/reviews/TASK-156.md`, finding 1 (should-fix) and nit 2, as routed by the last row of `work/decisions.md`. Only `manager/bitscan_manager/services/importer/folders.py` changed. It is now 375 lines in total, of which 270 are code (226 in r2); the r3 helpers and their split calls account for about 44.

### What changed

- `_DIR = O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` (folders.py:60). This is the same flag set as `uploads._DIR_FLAGS`. I did not reuse `uploads.open_uploaded_dir`, because it applies no-follow to `uploaded` only, while the bits folder needs it too.
- `_open_folder(bits_dir, label)` (:136) opens the bits folder with `_DIR`. For `UPLOADED` it then opens `uploaded` relative to that fd, also with `_DIR`. Neither component is ever followed through a link. If either is missing, a symlink or not a directory, it raises `OSError`.
- `unreadable()` (:108) is now built on `_open_folder`. The results are unchanged: a bad bits folder gives both labels.
- `_state(bits_dir, rel) -> "present" | "absent" | "unreadable"` (:149) is the three-way check:
  - "unreadable" if the folder cannot be opened, or if the `stat` has any error other than `FileNotFoundError`.
  - "absent" only if the folder is a real directory, opened without following a link, and the name is missing or is not a regular file. An unwanted or unstorable path is "absent", as before.
  - `present()` (:179) is now `_state(...) == "present"`. It no longer resolves a symlinked bits folder for server rows (tester finding 4).
- `delete_removed` (:340) keeps its signature and return type. It calls `_delete_removed(..., blind)` (:350), which runs `_state` again for each row just before that row's `delete_in_tx` (:360):
  - "unreadable": the row is skipped and its folder is marked.
  - "present": the row is skipped.
  - "absent": the row is deleted.
  - The start-of-call `blind` snapshot from r2 is gone, so a folder that disappears or is swapped for a link during the loop deletes none of its remaining policies.
- `_mark(blind, bits_dir, label)` (:123) adds a folder to `blind` and logs the constant line `folder unreadable, not reconciled: <label>` once per folder. If the bits folder itself has gone, it adds both labels.
- `reconcile` (:271) collects `blind` from three places: its start (as in r2), `read_input` failures, and the delete loop. `ReconcileResult.unreadable_folders` keeps the fixed order `("./", "uploaded/")`.
- `read_input` (:185) opens the file by name relative to `_open_folder`'s fd, with `_OPEN`, and closes the folder fd in `finally`. If the folder cannot be opened, it returns None with the fixed log line `folder file not read: its folder is unreadable`. `reconcile` then checks `unreadable()` and marks that folder (:307), so a folder swapped between `discover` and the read is reported. Nothing in it is read through the link, and no policy in it is deleted.
- Not changed: `_names` (scandir by path after `_real_dir`), `discover`, the classification, `renamed`, the order, and everything else.

### Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (291 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues (291 files).
- PostgreSQL suites, run from `manager/`: `test_folders_pg.py test_import_pipeline_pg.py test_import_store_pg.py test_policy_delete_pg.py test_catalog_lock_pg.py test_uploads.py test_uploads_pg.py` gives **543 passed**, with no failures.
- Throwaway smoke test, a copy of the test file that has since been deleted. All 6 passed:
  - **Folder broken after the first deletion.** Setup: 3 server and 3 uploaded policies, one file removed in the folder under test. The first `delete_in_tx` is wrapped so that after it commits, the folder is removed or swapped for a symlink to a copy. Cases: `uploaded/` missing, `uploaded/` symlink, bits folder missing, bits folder symlink. In every case exactly 1 policy was deleted, the other 2 in that folder stayed live, and `unreadable_folders` was `("uploaded/",)` or `("./","uploaded/")`.
  - **Folder swapped for a symlink after `discover`** (wrapped `discover`). With `uploaded/` swapped, the server files were imported (`a` skipped, `b` success), there was no row for the changed upload, `unreadable_folders == ("uploaded/",)` and nothing was deleted. With the bits folder swapped, there were no rows, `("./","uploaded/")`, and nothing was deleted.

### Cases for the tester

1. Mid-loop, `uploaded/`: there are two or more live uploaded policies and one of their files is removed. After the first deletion commits (for example by wrapping `folders.delete_in_tx`), `uploaded/` is removed, or swapped for a symlink to a copy holding the same files. Expect:
   - one deletion only;
   - the remaining uploaded policies have `deleted_at` NULL and no `policy.delete` entry;
   - `unreadable_folders == ("uploaded/",)`;
   - one log line for the folder;
   - server policies are unaffected.
2. The same as case 1 for the bits folder (missing, or a symlink to a copy). The remaining server and uploaded policies all stay live, and `unreadable_folders == ("./", "uploaded/")`.
3. A folder swapped for a symlink, or removed, between `discover` and `read_input`, for each folder. Expect:
   - no `bit_import` row for any of its files;
   - nothing is read through the link (spy on `os.open`, or check that the link target was never opened);
   - the folder is listed in `unreadable_folders`;
   - no deletion in it;
   - the other folder is still reconciled when only `uploaded/` was swapped.
4. Tester finding 4: when the bits folder is a symlink to a real folder, `present(bits, "a.bit")` is False and `read_input(bits, "a.bit")` is None. `delete_removed` deletes nothing.
5. `delete_removed` called directly: same signature and return type. With `uploaded/` missing it returns `()` for the uploaded policies. With a real folder where a file was removed, it deletes that policy once.
6. Regression: the r2 table (missing, symlink or file, for each folder; a real empty folder; both folders unreadable) stays the same.

### For TASK-157

- Use `present` / `_state` semantics for every deletion, and run the check for each row just before its delete: never decide "absent" from a snapshot.
- Read files through `read_input`, which opens them relative to the folder fd.

## Revision 4 (impl-manager-156b): r3 test findings 1 and 2

This revision is the last row of `work/decisions.md` (lead, yes to both). It fixes the two non-blocking findings from the r3 TEST in `work/reports/TASK-156-test.md`, "Revision 3". Only `manager/bitscan_manager/services/importer/folders.py` changed. It is now 383 lines, 275 of them code (270 in r3).

### What changed

- **(1) No log line per file.** When `read_input` cannot open the folder handle, it now returns None without logging (folders.py:195). The caller's folder guard (`_mark`, reached from `reconcile` at the `read_input` None check) still writes its one constant line per folder. Read errors on a single file inside a readable folder still log `folder file not read: <type>`, as before.
- **(2) A leftover is reported only once it is gone.**
  - `remove_leftover` (:262) now returns `Difference | None`. After `remove_after_commit`, it checks the file again with `_state` (:269), through the no-follow folder handle.
  - Only `"absent"` counts as removed. Then, as before, it writes the log line `removed a leftover …` and returns the `Difference`.
  - Otherwise it returns None and logs nothing. The cases are: the file is still there (the removal was refused or failed), or the folder became unreadable (a missing folder, or a swap for a symlink).
  - On None, `reconcile` (:302–304) does not list the file in `leftovers`. It calls `_mark(blind, bits_dir, UPLOADED)` instead: one guard line, and `"uploaded/"` in `unreadable_folders`.
  - The mark only reports the problem. Deletions are still decided row by row by `_state` (r3), so a real `uploaded/` whose leftover could not be removed still has its absent files deleted. On the next reconcile the leftover is tried again.
  - TASK-157 must handle the None return from `remove_leftover` in the same way.

### Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (291 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues (291 files).
- PG suites from `manager/` (`test_folders_pg.py test_import_pipeline_pg.py test_import_store_pg.py test_policy_delete_pg.py test_catalog_lock_pg.py test_uploads.py test_uploads_pg.py`): **562 passed**.
- Throwaway smoke checks, in a copy of the test file that has since been deleted. All 3 passed:
  - A leftover whose `remove_after_commit` is a no-op (refused): `leftovers == ()`, `unreadable_folders == ("uploaded/",)`, no `removed a leftover` line, and exactly one `folder unreadable` line.
  - A leftover with `uploaded/` swapped for a symlink to a copy after `discover`: the same result, and the file in the link target is still there.
  - Three changed live uploads with `uploaded/` removed after `discover`: the only WARNING line from the module is `folder unreadable, not reconciled: uploaded/`, `unreadable_folders == ("uploaded/",)`, and `deleted == ()`.

### Cases for the tester

1. A folder swapped or removed after `discover`, with N ≥ 2 files in it: exactly one `folder unreadable` line for that folder, and no `folder file not read` line. A per-file read error in a readable folder (for example a FIFO swapped in, or EACCES) still logs `folder file not read: <type>`.
2. A leftover with `uploaded/` swapped for a symlink, or removed, between `discover` and the removal:
   - `leftovers == ()` and `unreadable_folders == ("uploaded/",)`.
   - No `removed a leftover` line.
   - The policy stays deleted and untouched.
   - The file in the link target is untouched.
3. A leftover whose removal fails while `uploaded/` stays real (patch `folders.remove_after_commit` to a no-op, or make the unlink raise): the same as case 2. The next reconcile tries again. Once the file can be removed, it is listed once in `leftovers`.
4. Regression: a normal leftover is still removed, listed once with the existing log line, and never read. This is the r0 case ii, unchanged.
5. `remove_leftover` called directly returns a `Difference` when the file is gone and None otherwise.
