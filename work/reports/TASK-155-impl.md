# TASK-155 IMPL: uploads

Implementer: impl-manager-155. REQ-163, REQ-165 (1). Risk high (importer; needs two approvals). Spec: TS §4.1 L522, L526, L528; §4.6 L611; §8.7 L1344, L1377. Open question #99 (d), (e). Decisions: "Crash window ruling", "Rebuild finishes interrupted uploads first", carried item (b) of "TASK-154 REVIEW APPROVED".

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/importer/uploads.py` (new, 217 physical lines, about 150 code lines without docstrings and comments) | `client_file_name`, `_Upload` (the hooks), `import_upload`, `FinishedUploads`, `finish_interrupted_uploads` |
| `manager/bitscan_manager/services/importer/pipeline_record.py` | `FileInput.__post_init__` (carry (b)), plus `import hashlib` (+9 lines) |

No other file was changed. `folders.py` (TASK-156) was not touched.

## Interface

```python
def client_file_name(raw: bytes | str | None) -> str                      # #99 (d)
def import_upload(session, clock, bits_dir, data, client_name, *, actor, prepared=None) -> ImportOutcome
def finish_interrupted_uploads(session, bits_dir) -> FinishedUploads(renamed, deleted)
```

- `import_upload` (`uploads.py:112`): the caller holds `catalog_lock(session)` and should pass `prepared=prepare(data)`, computed before it takes the lock. It hashes `data`, builds `FileInput(data, sha, client_file_name(name), Target("upload", None, sha))` and calls `import_one` in mode `manual`, with `before_commit=_Upload.write` and `after_commit=_Upload.rename`. `PolicyManagedOnServer` (409 `policy_managed_on_server`) comes from the pipeline's existing refusal: one `policy.import_refused` entry, no row and nothing on disk.
- `finish_interrupted_uploads` (`uploads.py:178`): a public, reusable step. **The caller holds the catalog lock and has no transaction open on the session.** It is called by start-up (TASK-158) and by the rebuild, before it reads the folders (TASK-157).

## How the items are met

| Item | Where / how |
| --- | --- |
| REQ-163 (1) hostile names | The client name is never part of a path: the temp path uses only `policy_id` and the hex SHA-256 the manager computed itself, and the final name only `policy_id`. `client_file_name` (`:45`) applies #99 (d): UTF-8 with replacement, then U+0000, the other C0 controls and DEL become U+FFFD, then the name is cut to 255 characters; `None` becomes `""`. A `str` input is first encoded with `surrogatepass`, so a lone surrogate becomes U+FFFD (three of them, one per byte) and never reaches PostgreSQL. |
| (2) symlink at the temp path | `write` (`:77`) opens with `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW \| O_CLOEXEC`, mode 0600. Any existing entry, a symlink included, gives `FileExistsError`. The `OSError` propagates out of transaction 1, so everything rolls back (#98 (j): no row). `discard` deletes only a file this upload created (`temp` is set only after a successful open), so the planted link and its target stay untouched. |
| (3) rejected re-upload | A reject or skip never calls `before_commit`, so no temp file is written and `policy-<id>.bit` is not touched. |
| (4) fault before commit | Any exception before COMMIT leaves `committed` False, so `discard` (in a `finally`) unlinks the temp. **Exception:** a `DatabaseUnavailable` after the temp was written (`:143`) is the COMMIT failing (the session converts only out-of-body errors), so the outcome is unknown. The temp is kept, and the next `finish_interrupted_uploads` renames it if the policy row matches its hash, otherwise deletes it. |
| (4) fault between commit and rename | `rename` sets `committed` first, so a failing `os.replace` leaves the temp in place. `import_one` still writes the `success` row (TASK-154 deviation (5)) and re-raises, and the route answers 500. The next start-up or rebuild finishes the rename. |
| (5) 409 | Comes from the pipeline (`store_decide.decide`) before any store and before `before_commit`. |
| (6) mode 0600 | The mode is 0600 at creation (with the unit's `UMask=0077` it stays 0600). `os.replace` keeps the inode, so `policy-<id>.bit` has mode 0600 and belongs to the service user. |
| Flushed before commit | `os.fsync` of the file, then of `uploaded/` (`_fsync_dir`), all inside `before_commit`, the last step of transaction 1. After the rename `uploaded/` is fsynced again. |
| Rename after commit | `rename` (`:88`) checks that `pending.store.source_file == "uploaded/policy-<id>.bit"` and that the temp name carries the same id, then runs `os.replace`. `rename(2)` replaces a symlink at the destination; it never follows it. |
| REQ-165 (1) | `finish_interrupted_uploads`: it lists the `.tmp-*` entries of `uploaded/`. A name is kept only if it parses strictly as `.tmp-<decimal id ≤ 2^63−1, no leading zero>-<64 lowercase hex>`, its content (opened `O_RDONLY \| O_NOFOLLOW \| O_NONBLOCK`, regular file only, at most 5 MiB) hashes to that hex, and the policy row (read `FOR UPDATE` in one transaction) is live, has `source_file = uploaded/policy-<id>.bit` and has `source_sha256` equal to the hex. Kept files are renamed into place. Every other `.tmp-*` entry is unlinked (a symlink is removed, not followed). A directory that cannot be unlinked is logged by error type and left, since it is not `*.bit`. A rename error propagates, so a rebuild never goes on with a stale copy. Only counts are logged. |
| Carry (b) | `FileInput.__post_init__` (`pipeline_record.py:43`) raises `ValueError` if `sha256 != target.file_sha256`, or if `data` is not None and its SHA-256 differs from `sha256`. |

**Choice for the reviewer (narrower than the spec's text, fail closed):** TS §4.1 L528 says "whose hash equals that policy's `source_sha256`". I also require that the policy is live and its `source_file` is `uploaded/policy-<id>.bit`. A deleted policy (crash-window ruling: it never comes back by itself) and a policy that moved to the server folder therefore never get an `uploaded/` copy back; their temp files are deleted. If main reads L528 more literally, this is two lines to drop.

## Crash points: what each leaves behind

| Point | Disk | DB |
| --- | --- | --- |
| Before the temp open, or a reject or skip | unchanged | the rejected or skipped row only |
| After the temp write, before COMMIT (process alive) | temp deleted | rolled back, no row |
| Process killed after the temp write, before COMMIT | `.tmp-<id>-<sha>` | rolled back; at start-up the hash does not match (or there is no row), so the temp is deleted |
| COMMIT fails with `DatabaseUnavailable` | temp kept | unknown; start-up renames or deletes it by the row |
| After COMMIT, rename fails or the process is killed | temp, plus the old `policy-<id>.bit` or none | committed; the `success` row is written if the process is alive. Start-up or rebuild renames the temp |
| After the rename | `policy-<id>.bit` new | committed and recorded |

Residual risk: after a kept temp (an unknown commit), a second upload of the same bytes for the same policy before the next start-up hits `O_EXCL` and gets a 500. That is fail-closed, and the next restart or rebuild clears it.

## Gates (repo root)

- `ruff check manager && ruff format --check manager`: pass (287 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: pass.
- `tests/test_import_pipeline_pg.py tests/test_import_fuzz_pg.py tests/test_samples_import_pg.py` (from `manager/`, CI=true plus the RYUK variable): **202 passed**, after the `__post_init__` change.
- A throwaway smoke run on PostgreSQL, in the scratchpad and not kept. All of these passed: an upload under a hostile byte name gives only `policy-<id>.bit`, mode 0600, with identical bytes. A rejected re-upload leaves the file identical. A symlink planted at the temp path gives an `OSError`, with the victim, the old file and the link unchanged. A failing `os.replace` after commit leaves the temp, and `finish_interrupted_uploads` then renames it and deletes `.tmp-x` and a symlinked `.tmp-5-ab` (result 1 renamed, 2 deleted, victim untouched). A fault in the directory fsync before commit leaves `uploaded/` empty. A 409 for a server-folder name leaves `uploaded/` empty.

## Cases for the tester (TP-M7-15)

- All REQ-163 (1) names, given as bytes (the multipart header) and as `str`: a snapshot of `uploaded/` before and after shows only `policy-<id>.bit`, and `bit_import.file_name` equals `client_file_name(raw)`. A missing name gives `""`, and 5,000 characters give 255.
- A symlink at `.tmp-<id>-<sha>`, pointing at a file outside: the import raises, there is no row, the catalog checksums are unchanged, the target's bytes and the link are unchanged. Also a regular file planted there: it is not deleted.
- Faults: `before_commit` failing mid-write (an `os.write` fault) or at fsync leaves no temp; a COMMIT failure surfacing as `DatabaseUnavailable` keeps the temp, and start-up then decides; an `os.replace` fault after commit leaves one `success` row and the temp, which start-up renames (REQ-165 (1)).
- `finish_interrupted_uploads`: committed (renamed), uncommitted (deleted), `.tmp-x`, a symlink temp (deleted, target untouched), a temp whose content does not match its name, a temp for a deleted policy (deleted), a `.tmp-0012-…` (leading zero) and a 30-digit id (deleted, no DB error), a FIFO named `.tmp-…` (no hang; deleted), and non-temp files left alone.
- `FileInput` with a mismatched `sha256` and `target.file_sha256`, or with `data` not matching, raises `ValueError`.
- Carry (a), the tester's: the caller holds the lock around `import_upload` and `finish_interrupted_uploads`, and a concurrent upload and rebuild serialise.
