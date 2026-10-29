# TASK-156 IMPL: folders (discovery, `auto` reconcile, `uploaded/` classification)

Owner: impl-manager-m7b. REQ-159, REQ-164 (and REQ-165 (3)). Risk: high (importer; two approvals). Depends on TASK-152, TASK-154 (APPROVED), TASK-151 r3, and TASK-155 r1 (the upload staging API).

Spec and rulings: TS §4.1 (L515, L522, L524, L526, L528), §4.2, §4.3 (L550), §4.6 (L612, L615); SR §3.6 step 2, §4.1 BIT007; #15, #102 (b), #103. Decisions: the user's "Crash window" ruling and the lead's follow-up (2026-10-27), the M7 pre-authorisation, and "TASK-156 case (c) success" (2026-10-28).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/folders.py` | new | 251 |

No other file was changed. It uses these through their public interfaces only:
- `pipeline.import_one` and `prepare`;
- `delete.delete_in_tx` and `remove_after_commit`;
- `store.Target` and `PolicyManagedOnServer`;
- `uploads.staged_upload` and `UploadStage` (TASK-155 r1);
- `repositories.catalog.policy_by_id_for_update`;
- `repositories.catalog_integrity.integrity_rows`;
- `alerts.Difference`.

`store_decide` is reached only through the pipeline.

**Size: 251 lines against an estimate of 180.** The extra comes from three places:
- the #102 (b) rules: the name test, a regular-file read with `O_NOFOLLOW | O_NONBLOCK`, and a full-file hash for an oversize file (#99 (b)), about 45 lines;
- the case (c) relocation that the 2026-10-28 ruling added (`Relocate`), about 30 lines;
- the docstrings that cite the rulings.

## Interface (all called under the caller's catalog lock)

- `classify_upload(tx, name) -> UploadClass(kind, policy_id)`: the shared classifier for TASK-157. `name` is the file name inside `uploaded/`. `kind` is `"live"`, `"leftover"` or `"other"`, following the row's cases (a), (b) and (c). It reads the policy with `policy_by_id_for_update`. The id must be `policy-<n>.bit` in decimal, with no leading zero, and at most 2^63 − 1; anything else is "other".
- `discover(bits_dir) -> list[str]`: the relative paths of the candidate files in both folders.
- `storable(name) -> bool` and `is_bit_file(bits_dir, rel) -> bool`: the #102 (b) name test, and "a regular file now, not a symlink".
- `import_path(session, clock, bits_dir, rel) -> ImportOutcome | Difference | None`: one file in `auto` mode, for the TASK-159 watcher too.
- `reconcile(session, clock, bits_dir) -> ReconcileResult(outcomes, not_imported, deleted, leftovers)`: start-up step 3. `leftovers` holds the #103 `Difference`s for TASK-158.
- `SYSTEM = Actor("system", None)` (#101), `UPLOADED`, and `LEFTOVER = "leftover of an interrupted delete"`.

## Rules

- **Discovery (#102 (b), REQ-164 (2)).** A file counts only if all of these hold:
  - it sits directly in `bits_dir` or `bits_dir/uploaded/` and is a regular file per `scandir(follow_symlinks=False)`;
  - its name ends in `.bit` (case-sensitive) and doesn't start with `.`.

  So `n.txt`, `.n.bit`, `A.BIT`, `sub/n.bit`, FIFOs and symlinks never count, and temp files never do either (`.tmp-…` is hidden). A name that is not valid UTF-8 (a POSIX name decodes to lone surrogates), holds a control character (U+0000–U+001F or U+007F–U+009F), or is over 255 UTF-8 bytes is skipped with one fixed log line and no row. A missing `uploaded/` counts as empty.
- **Read once (TS §4.1 step 2).** The file is opened with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and checked with `fstat` to be a regular file. It is read in 1 MiB chunks into one buffer, and the hash is computed while reading. A file over 5 MiB gets `data=None`, with the hash still covering the whole file, so the pipeline rejects it as BIT001 with a row (#99 (b)). A file that is no longer a regular file when opened is skipped without a row.
- **How files reach `decide()`:**
  - A server-folder file becomes `Target("server", "<name>.bit", sha)`.
  - An `uploaded/` file is classified first and never becomes a server target:
    - (a) "live": the normal pipeline with `Target("upload", None, sha)`. In `auto` mode it is `skipped` when its hash equals `source_sha256` (TASK-151 r3).
    - (b) "leftover": the file is unlinked without being followed. Nothing is imported, no `bit_import` row is written, and the policy stays deleted. One log line names the policy id, and a `Difference("uploaded/policy-<n>.bit", "leftover of an interrupted delete")` is returned.
    - (c) "other": the normal pipeline as an upload target. A server-folder policy's copy is refused: the pipeline writes `policy.import_refused`, and the file is left for #103.
- **Case (c) success (ruling "TASK-156 case (c) success").** The bytes are staged through `uploads.staged_upload` as `uploaded/.tmp-<id>-<sha>` before the commit, and renamed to `uploaded/policy-<id>.bit` after it. The foreign file is then unlinked without being followed. If the rename fails, the foreign file stays and the error propagates. A rejected or refused (c) file writes nothing and stays for the #103 check.
  - **One extension, flagged for the lead.** Staging happens whenever a successful upload-target import lands on a policy whose upload name differs from the file's own name. That includes a case (a) file whose content now names another policy. Without it, that policy would have no file and would be deleted at the next start-up. The case (a) file itself is never unlinked, because it is its own policy's `source_file`; #103 reports its hash.
  - A file that already sits at its policy's name is not staged. That happens when a (c) `policy-<n>.bit` whose policy didn't exist is inserted as id `n`.
- **Reconcile order.**
  1. Imports come first, in #15 order: files that are a live policy's `source_file` first, then by the bytes of the UTF-8 relative path.
  2. Then every live policy whose `source_file` is no longer a regular file is deleted with `delete_in_tx(reason="file removed", actor="system")`, in its own transaction, followed by `remove_after_commit`.

  Because the imports come first, a new server file that replaces a removed one moves its policy (decide's `move_server`, one move audit entry, REQ-159 (2)) instead of reviving it. The same applies to a server file and an uploaded policy (`move_upload`, REQ-159 (3)). For two new server files with one name, the first in byte order imports and the second gets BIT007 (REQ-159 (6)).
- **BIT007 `file_exists`** is `is_bit_file`: an `lstat` regular file, so a symlink doesn't count as the old file "still existing".

## Checks run here (scratch, outside the tree; the tests are the tester's)

- Gates: `ruff check manager` and `ruff format --check manager` are clean (287 files), and so is `mypy --strict --config-file manager/pyproject.toml manager` (287 files).
- Smoke (`C:\Users\kaiquan.koh\scratch\task156\smoke.py`, with a fake session, repository and pipeline; no PostgreSQL):
  - `discover` returns `a.bit`, `b.bit`, `big.bit` and the five `uploaded/` names. It skips `.h.bit`, `n.txt`, `A.BIT`, `sub/x.bit` and `uploaded/.tmp-1-x`.
  - `storable` rejects a control character, a lone surrogate, and a name of 258 UTF-8 bytes; 256 is rejected as well.
  - The oversize file gives `data=None` with the full-file hash.
  - Targets: `a.bit` becomes `server`/`a.bit`, and every `uploaded/` file becomes `upload`/`None`. No `Target("server", "uploaded/…")` appears (row test (iv)).
  - The leftover `policy-2.bit` (deleted policy) is removed and returned as a `Difference`, and the pipeline never sees it.
  - `foo.bit` imported as policy 7 is written as `policy-7.bit` and removed itself, with no temp file left over.
  - The refused `policy-9.bit` (policy in the server folder) is kept, and `import_path` returns None.
  - `policy-01.bit` is "other".

## For the tester (TP-M7-16, `test_folders_pg.py`)

- These need PostgreSQL plus temporary folders: REQ-164 (2), REQ-159 (2), (3) and (6), REQ-165 (3), the row's tests (i)–(iv), and "an unchanged folder writes only `skipped` rows".
- An unstorable name can be planted on Linux only (bytes `b"\xff.bit"`, a control character, or a 256-byte name).
- **Plants:**
  - `classify_upload` returns "live" for a deleted policy, or "other" for every name. Caught by (ii) and (iii).
  - Build `Target("server", rel)` for `uploaded/` files. Caught by (iv); `Target` also raises.
  - Drop `follow_symlinks=False` or `O_NOFOLLOW`. Caught by REQ-164 (2) and CHK-M7-363.
  - Run the deletions before the imports. Caught by REQ-159 (2): a revive instead of a move.
  - Reverse the #15 sort. Caught by REQ-159 (6).
  - Skip the `Relocate` unlink. A (c) file then stays after its successful import.
  - Drop the `if not self.staged: return` guard in `Relocate.after_commit`. Either of two checks catches it:
    - A case (a) success whose file keeps its own upload name (`uploaded/policy-<n>.bit` updated as policy n) raises `LookupError("committed upload has no temp file")` after the commit.
    - A case (c) `policy-<n>.bit` with no policy n, inserted as id n, has its own file deleted.

    Expected without the plant: both succeed, the file is still present, and no `.tmp-` file is left.
- **Messages and logs** are fixed text. A leftover logs only its policy id, and no file name or content is ever logged.

## Own-name staging guard (2026-10-28)

impl-manager-m7 flagged a possible defect: when nothing is staged, the `after_commit` path must call neither `stage.after_commit` nor the foreign-file unlink. The code already meets this, because `Relocate.after_commit` returns at once unless `staged` is set. The lead confirmed that no code change is needed; the extension and the 251-line size are approved (decisions row "TASK-156 staging extension and size").

Smoke cases added (`C:\Users\kaiquan.koh\scratch\task156\smoke.py`):
- **Case (a), own name.** `uploaded/policy-1.bit` updated as policy 1 succeeds with no exception. The file is unchanged and no temp file is left. With the guard dropped, the same call raises `LookupError` after the commit.
- **Case (c), own name.** `uploaded/policy-3.bit` with no policy 3, inserted as id 3, succeeds and keeps its file. With the unlink not gated on `staged`, the file is deleted.

Gates on `folders.py` are clean (ruff, format, `mypy --strict`). Two full-tree gates currently fail, both because of `manager/tests/test_uploads_pg.py`, the tester's in-progress TASK-155 test, which is not part of this task:
- `ruff check manager`: S103, on `os.chmod(..., 0o750)` at line 72;
- `mypy --strict --config-file manager/pyproject.toml manager`: 12 errors.

## Revision 1 (2026-10-28): public names for the rebuild

Decisions row "TASK-157 rulings" (3)–(4). This is a rename only; behaviour is unchanged. The rebuild (TASK-157) calls both names.

- `folders._read` is now `read_file(path: Path) -> tuple[bytes | None, str] | None`. It returns `(data, sha256)`: `data` is None over 5 MiB, and the result is None if the path is not a regular file when opened.
- `folders._Relocate` is now `Relocate(stage: UploadStage, path: Path, kind: UploadClass)`. Its `before_commit(policy_id)` and `after_commit(outcome)` are passed to `import_one`, inside `staged_upload(...)`.
- The internal callers (`import_path`) are updated. No other file was changed.
- The gates on `folders.py` are clean (ruff, format, mypy --strict). The scratch smoke run gives the same results as before, and both own-name plants still go red.
- The plant list above now reads `Relocate` where it said `Relocate`.

## Revision 2 (2026-10-28): #102 (c) records

Decisions row "#102 (c) wiring" (b). The folder watcher (TASK-159) drops the events caused by the manager's own removals. `folders.py` now records both of its removals in `own_changes.OWN_CHANGES` just BEFORE the unlink, so a fast inotify event is never missed:

- `Relocate.after_commit`: `OWN_CHANGES.removed(f"uploaded/{self.path.name}")` before `self.path.unlink()`. It still runs only when something was staged and the file is case (c).
- `_remove_leftover`: `OWN_CHANGES.removed(rel)` before `(bits_dir / rel).unlink()`.

There is one new import (`own_changes`, a neutral module), and the file is now 254 non-blank lines. Nothing else changed.

**Checks:**
- Gates are clean (ruff on the product code, ruff format and mypy --strict, 295 files).
- The scratch smoke run is unchanged, and the own-name plants are still red.
- A new smoke case shows both records made while the file still existed, so before the unlink: `uploaded/policy-2.bit` (leftover) and `uploaded/foo.bit` (relocated).

**Plants:**
- Remove either record: the TASK-159 watcher then handles the event, which for these two paths deletes nothing but still makes a delete attempt.
- Move the record after the unlink: a fast event can arrive before it.
