# TASK-156 TEST: PASS

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-159 (2), (3), (6), REQ-164 (2), REQ-165 (3); TS §4.1 L515, L522, L524, L526, L528, §4.3 L550; SR §4.1 BIT007; #15, #102 (b), #103; the crash-window ruling (2026-10-27); decisions 2026-10-28 "TASK-156 case (c) success" and "TASK-156 staging extension and size"; the lead's 2026-10-28 request (the own-name skip-path must-pass row and the dropped-guard plant). Code under test: `bm/services/importer/folders.py`. New test file: `manager/tests/test_folders_pg.py` (30 tests, Linux only). Its own module database, and each test owns its bits folder. Before each test, the earlier tests' live policies are soft-deleted, so a reconcile neither deletes them nor counts their paths as recorded (#15).

## Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t156`, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| f0 | `pytest tests/test_folders_pg.py` | 28/30 passed, 2 failed. Both were test bugs: a 256-byte name can't be created on Linux (NAME_MAX), and I had left out the expected `skipped` row of the server file in the refused-copy test |
| f0-r | the two node ids after the fixes | 2/2 passed |
| f1 | the whole file again | **30/30 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 15 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 15/15 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean (289 files) |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-208 | APP | W | f1 | PASS | REQ-164 (2), #102 (b), in both folders: `n.txt`, `.n.bit`, `A.BIT`, `n.bit.bak`, `.tmp-1-x`, `sub/s.bit`, a FIFO `f.bit` (never blocks), a symlink `l.bit`, and the names `\xff.bit`, `a\x01.bit` and `a\nb.bit` are never imported and get no row. A 255-byte name imports with `file_name` intact. Each unstorable name writes exactly one fixed log line (6 in total) naming nothing. The whole tree is unchanged except the case (c) relocation of `uploaded/u.bit`. `storable`: 254 bytes accepted; 256 bytes, DEL, C1 (U+009F) and a lone surrogate refused; U+00A0 accepted. Over 255 bytes can only be a unit row, since Linux can't create such a name. An oversize server file is rejected BIT001 with the full-file hash (#99 (b)) | 2026-10-28 |
| CHK-M7-209 | APP | W | f1 | PASS | #15: two new files with one name → the first in byte order (`B.bit` before `a.bit`; `z.bit` before `é.bit`, bytes not locale) imports and the other gets BIT007; a recorded `z.bit` goes before a new `a.bit`. REQ-159 (2): `a.bit` removed and `c.bit` added with its name → same id, `source_file` `c.bit`, no delete, one `policy.move {a.bit → c.bit}`. REQ-159 (3): a server file with an uploaded policy's name → the policy moves, the uploaded copy is deleted, one move entry; a later upload of that name → `PolicyManagedOnServer` (409). A symlink at the old path doesn't keep BIT007 alive | 2026-10-28 |
| CHK-M7-210 | APP | W | f1 | PASS | An unchanged folder (two server files and one upload) writes only `skipped` rows, one per file (`policy_version` NULL, TASK-154 r1), no audit entry, no counter, catalog unchanged, nothing deleted | 2026-10-28 |
| REQ-165 (3) | APP | W | f1 | PASS | A file added while down imports. A server file and an uploaded policy's file both removed → both policies deleted (`deleted/<id>`), `policy.delete` by `system` with reason "file removed" and `policy_deleted` (+2). A file replaced by a symlink counts as removed, and the symlink target is never followed or removed | 2026-10-28 |
| row (i) | APP | W | f1 | PASS | A live upload's unchanged file → one `skipped` row and no alert. Edited in place (own name `policy-<id>.bit`) → `success`, the file still present with its bytes, no error, no `.tmp-`, `source_sha256` updated: the skip-path must-pass row | 2026-10-28 |
| row (ii) | APP | W | f1 | PASS | A deleted policy's leftover `uploaded/policy-<id>.bit` → removed, no `bit_import` row, catalog unchanged, `deleted_at` kept, returned as `Difference("uploaded/policy-<id>.bit", "leftover of an interrupted delete")` | 2026-10-28 |
| row (iii) | APP | W | f1 | PASS | A live policy's upload file with another hash is never treated as a leftover. Its content names a new policy, so it is staged for that one, and the file itself stays as its own `source_file`. A `policy-<n>.bit` whose `n` is a live server-folder policy is "other": refused and kept for #103 | 2026-10-28 |
| row (iv) | APP | W | f1 | PASS | A spy on `import_one` sees every `uploaded/` file as `Target("upload", None)` and every server file as `Target("server", rel)`; `Target("server", "uploaded/…")` raises | 2026-10-28 |
| case (c) | APP | W | f1 | PASS | `uploaded/foreign.bit` with a new name → `success`, stored as `uploaded/policy-<id>.bit` (0600, its bytes), the foreign file removed, the only entry, `source_file` `uploaded/policy-<id>.bit`, row `file_name` `uploaded/foreign.bit`; the next reconcile skips the stored copy. Rejected (`rm x`) and refused (server-folder name) (c) files stay; refused gets `policy.import_refused` and no row; no temp left. A (c) `policy-<n>.bit` inserted as id `n` keeps its file, which is not staged or removed (the own-name path). An `uploaded/` symlink is never imported, and its target is untouched | 2026-10-28 |
| staging extension | APP | W | f1 | PASS | A live (a) file whose content names another policy → that policy is staged to its own `policy-<id>.bit`; the (a) file is kept and its policy stays live | 2026-10-28 |
| read and logs | APP | W | f1 | PASS | A file swapped for a symlink before its read → the open carries `O_NOFOLLOW`, the file isn't imported, there is no row, and it is listed in `not_imported`. No file name, policy name or Execute marker in the logs across server, (c), rejected and leftover files | 2026-10-28 |
| plant f1 | APP | W | a deleted policy classified "live" | PASS (red) | 1 failed: row (ii) | 2026-10-28 |
| plant f2 | APP | W | every name classified "other" | PASS (red) | 3 failed: rows (ii), (iii), the staging extension | 2026-10-28 |
| CHK-M7-363 / (iv) | APP | W | plant f3: `uploaded/` files as server targets | PASS (red) | 6 failed: row (iv), (i), server wins, removed files, case (c), refused copy | 2026-10-28 |
| CHK-M7-363 | APP | W | plant f4: discovery follows symlinks | PASS (red) | 1 failed: the discovery row | 2026-10-28 |
| CHK-M7-363 | APP | W | plant f5: `O_NOFOLLOW` dropped from the read | PASS (red) | 1 failed: the swap race (flags `[2048]`) | 2026-10-28 |
| CHK-M7-363 | APP | W | plants f4 + f5 together | PASS (red) | 3 failed, including an `uploaded/` symlink imported through its target | 2026-10-28 |
| plant f6 | APP | W | deletions before imports | PASS (red) | 1 failed: REQ-159 (2) (deleted `[7]`, not a move) | 2026-10-28 |
| plant f7 | APP | W | #15 sort reversed | PASS (red) | 2 failed: both byte-order rows | 2026-10-28 |
| plant f8 | APP | W | the case (c) unlink skipped | PASS (red) | 2 failed: the discovery tree and case (c) | 2026-10-28 |
| plant f9 | APP | W | the `if not self.staged: return` guard dropped | PASS (red) | 2 failed: row (i) own name and case (c) own name, both `LookupError: committed upload has no temp file` | 2026-10-28 |
| plant f10 | APP | W | delete reason changed | PASS (red) | 1 failed: "file removed" | 2026-10-28 |
| plant f11 | APP | W | `storable` always true | PASS (red) | 6 failed: the discovery row and five `storable` rows | 2026-10-28 |
| plant f12 | APP | W | the leftover not removed | PASS (red) | 1 failed: row (ii) | 2026-10-28 |
| plant f13 | APP | W | `is_bit_file` follows symlinks (`stat`) | PASS (red) | 1 failed: the symlink-counts-as-removed row | 2026-10-28 |
| plant f14 | APP | W | a refused (c) file removed | PASS (red) | 2 failed: row (iii) and the refused-copy row | 2026-10-28 |
| REQ-164 (1), (3)–(5) | — | — | — | NOT RUN (TASK-159) | inotify watcher and its events | 2026-10-28 |

## Acceptance

TASK-156 row: REQ-164 (2) → CHK-M7-208; REQ-159 (2), (3), (6) and #15 → CHK-M7-209; REQ-165 (3) and the "file removed" reason → REQ-165 (3) row; an unstorable name skipped with one log line and no row → CHK-M7-208; an unchanged folder writes only `skipped` rows → CHK-M7-210; extra tests (i)–(iv) → rows (i)–(iv); the 2026-10-28 rulings → the case (c) and staging-extension rows. The lead's own-name must-pass row → row (i) and case (c) own name, and plant f9 drops the guard → red. Every security row has a plant that went red.

## Notes (no defect)

- `storable` also refuses C1 controls (U+0080–U+009F). That is stricter than #102 (b) "a control character", and errs toward skipping.
- Plant f13 turned only the symlink-removed row red. The BIT007-with-symlink row stayed green, because the old policy's own file check doesn't decide that case.

## Gap fix (2026-10-28, after review)

The reviewer found that `test_a_symlink_at_the_old_path_does_not_keep_bit007_alive` stayed green under plant f13. Its symlink pointed at a missing file, so even `stat` saw no regular file. The symlink at the old path `a.bit` now points at a valid `*.bit` regular file holding the same policy. The row asserts: `b.bit` imports with `success` and no BIT007, the policy moves to `b.bit`, and the symlink and its target are left as they were. Only the lstat rule (a symlink never counts as the old file still existing) can make it pass.

| Run (W, fresh copy `/root/bstest-m7-t156g`, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_folders_pg.py::test_a_symlink_at_the_old_path_does_not_keep_bit007_alive` | 1/1 passed |
| plant f13 (`is_bit_file` uses `stat`): that row and `test_a_file_replaced_by_a_symlink_counts_as_removed` | PASS (red): 2 failed. `{'b.bit': ['rejected']}` instead of `success` (BIT007 kept alive through the symlink), and `[] == [2]` (not deleted) |

Static: `ruff check`, `ruff format --check` and `mypy --strict` are clean on the changed file. Verdict unchanged: **PASS**.

## Revision 1 (2026-10-28): rename only (`_read` → `read_file`, `_Relocate` → `Relocate`)

No test or monkeypatch names either private name, and every plant text still matches the revised `folders.py` exactly once.

| Run (W, fresh copy of the tree with r1, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_folders_pg.py` | **30/30 passed**, 0 failed, 0 errors, 0 skipped |
| plant f5 (`O_NOFOLLOW` dropped, read by `read_file`) | PASS (red): 1 failed, the swap race |
| plant f8 (the `Relocate` unlink skipped) | PASS (red): 2 failed, the discovery tree and case (c) |
| plant f9 (the `Relocate` guard dropped) | PASS (red): 2 failed, the own-name rows (`LookupError`) |

Verdict unchanged: **PASS**.

## Revision 2 (2026-10-28): `OWN_CHANGES.removed(...)` before both unlinks

`Relocate.after_commit` and the leftover removal record the path just before the unlink; nothing else changed. On a fresh copy of the tree with r2 (`-n 0`, with the 155 r2, 152 r1 and 159 files): `tests/test_folders_pg.py` **30/30 passed**. The watcher rows in `work/reports/TASK-159-test.md` pass with these hooks. They can't be seen in behaviour, because the removed path belongs to no live policy, so an unhooked event does nothing either. Verdict unchanged: **PASS**.
