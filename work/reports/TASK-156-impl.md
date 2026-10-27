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
