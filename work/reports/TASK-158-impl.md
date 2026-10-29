# TASK-158 IMPL: integrity check (#103) and the catalog start-up sequence

Implementer: impl-manager-m7. REQ-165. Risk high (importer; two approvals). No per-task plan; built from:
- the TASK-158 row (crash-window text included);
- REQ-165;
- TS §4.1 L528, §4.2 L540, L542, §8.4 L1291;
- #27, #98 (g), #102 (d), #103.

Carries applied:
- main's order: finish_interrupted, then reconcile, then the integrity check, all under one catalog lock, with each reconcile leftover one "leftover of an interrupted delete" difference;
- the TASK-156 review carry: retry the whole reconcile, and never run its deletion pass after a partial import pass.

## Files

| File | Lines (total / non-blank / code) | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/integrity.py` (new) | 82 / 71 / 54 | The #103 check texts, `check`, `alert` |
| `manager/bitscan_manager/services/importer/startup.py` (new) | 92 / 80 / 59 | `StartupReport`, `run_once`, `run`, `RETRY_S`, `TASK_INTERRUPTED` |

Size: 113 code lines against the estimate of 170. No other file changed. It calls only public interfaces:
- `uploads.finish_interrupted`;
- `folders`: `reconcile`, `discover`, `read_file`, `SYSTEM`;
- `parse.parse_bit`;
- `alerts`: `integrity_failed`, `emit`, `Difference`;
- repositories: `catalog_integrity.integrity_rows` and `rejected_files`, `imports.fail_running_tasks`, `catalog_lock`.

## Interface (TASK-160 runs it on a background thread)

```python
# startup.py
RETRY_S = 10.0
def run(db, clock, bits_dir, stop: threading.Event, retry_s: float = RETRY_S) -> StartupReport | None
def run_once(db, clock, bits_dir) -> StartupReport
@dataclass class StartupReport:
    finished: FinishResult
    failed_tasks: tuple[UUID, ...]
    reconciled: ReconcileResult
    differences: tuple[Difference, ...]

# integrity.py
def check(session: CatalogSession, bits_dir: Path) -> list[Difference]   # caller holds the lock
def alert(tx: Tx, differences: Sequence[Difference]) -> None
```

- `run` returns the report once the sequence has completed. It returns None if `stop` is set first; it waits on `stop`, so a stop returns at once (builder checklist 10).
- TASK-160 keeps the catalog routes on the #102 (d) answer until `run` returns, and starts the watcher after it.

## The sequence (`run_once`)

All of it runs in one pinned session, under one `catalog_lock(session)`, before any other catalog work (#102):
1. `finish_interrupted(session, bits_dir)` (TASK-155): a temp file of a committed upload is renamed, every other one is deleted (REQ-165 (1)).
2. `fail_running_tasks` marks every task still `running` as `failed`, with `finished_at` and result `{"error": "The manager stopped before the task ended."}` (#98 (g) fixed text; REQ-165 (2), TS §4.2 L540).
   - It runs under the lock, so a CLI rebuild still holding the lock (#102 (e)) finishes and marks its own task first.
3. `reconcile(session, clock, bits_dir)` (TASK-156) runs in `auto` mode: new and changed files are imported, gone policies are deleted (REQ-165 (3)), and a leftover of an interrupted delete is removed and returned as a difference.
4. **The integrity check, after the reconcile** (#27): the differences are the reconcile's leftovers first, then `integrity.check`. If there is any difference, `integrity.alert` writes one `catalog.integrity_check` entry, the `catalog_integrity_failed` alert. It lists the first 100 differences and the total (TASK-153's `integrity_failed`), with actor `system`. A clean catalog raises nothing (REQ-165 (4)).
5. One log line gives counts only.

**Retry (`run`, #102 (d), the TASK-156 carry):**
- Any exception from an attempt is logged by its type and the whole sequence is retried from step 1 after `retry_s` (10 s). This covers the database being down at start (`db.session()` raises), or one file's internal error inside the reconcile.
- Every step is idempotent:
  - the finish only acts on temp files;
  - failing running tasks changes only `running` rows;
  - the reconcile skips unchanged files in `auto` mode;
  - the check only reads.
- `folders.reconcile` runs its deletion pass only after its import loop has finished. An internal error in the loop raises out of `reconcile` before any deletion, so a policy whose file wasn't reached is never deleted: the retry starts over with a fresh import pass.
- The lock is released between attempts (the session closes). TASK-160's gate keeps the catalog routes closed meanwhile. A CLI rebuild could take the lock in that gap, which is safe: the next attempt starts again from step 1.

## The #103 check (`integrity.check`)

It reads only; it never repairs anything (that is the rebuild).
- **Catalog side.** For each non-deleted policy (`catalog_integrity.integrity_rows`, by id), with subject `policy:<id>`:
  - "its file is missing": `read_file(bits_dir / source_file)` is None (absent, a symlink, or not a regular file; O_NOFOLLOW);
  - "its file's hash differs from source_sha256";
  - "its plugin count differs from its file": the hash matches but the `policy_plugin` count differs from the number of `Plugin` elements under `PluginsGroups`. The file is parsed with `parse_bit`, nothing is written, and it is skipped for an oversize file (data None);
  - "a listed plugin is not active or not owned by it": `bad_plugins > 0`.
- **Folder side.** Each `*.bit` from `folders.discover` that isn't a live policy's `source_file` is hashed (`read_file`). If no `rejected` `bit_import` row exists for `(path, sha256)` (`catalog_integrity.rejected_files`), it is reported as "the file is neither a policy's file nor a rejected import", with the relative path as subject.
- The check texts are fixed constants, and no file content or name reaches a log.

## Readings for the reviewer

1. **Leftovers from a failed attempt.** If an attempt fails after the reconcile has removed a leftover, the retry no longer sees that file. Its difference isn't in the final alert. The removal is still logged (TASK-156's warning line), and the leftover rule only ever removes a deleted policy's file. Carrying the list across attempts would need `reconcile` to return partial results when it raises, which is TASK-156's interface.
2. **Programming errors are retried too.** `run` retries every `Exception`, not only database errors. A permanent bug therefore keeps the catalog closed and logs one line every 10 s, rather than silently ending the start-up thread. It fails closed.
3. **The integrity alert is written in its own transaction after the check,** still under the lock. If that write fails, the attempt fails and the whole sequence is retried.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` passes, and `ruff format --check manager` passes (295 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 295 source files.

No scratch run for these two files; they are thin compositions of tested functions. The tester's PostgreSQL rows cover them.

## For the tester (tester-m7, TP-M7-18, `manager/tests/test_catalog_startup_pg.py`; PostgreSQL with temporary folders in WSL)

- `run_once(db, clock, bits_dir)` for the step rows. `run(db, clock, bits_dir, stop, retry_s=<small>)` for the retry rows.
- **Step log:** spy on `startup.finish_interrupted`, `startup.fail_running_tasks`, `startup.reconcile`, `startup.check` and `startup.alert`. The order must be exactly finish, fail, reconcile, check, then alert (only with differences), all inside one held catalog lock (a second session's `pg_try_advisory_lock` is false throughout).
- **REQ-165:**
  - (1) the temp-file cases;
  - (2) a task left `running` ends `failed` with `finished_at` and `{error}`;
  - (3) a file added and one removed while down;
  - (4) the owner-role corruptions: a deleted `policy_plugin` row gives "its plugin count differs from its file"; a changed `source_sha256` gives "its file's hash differs"; a plugin set `retired` gives "a listed plugin is not active or not owned by it". There is one `catalog_integrity_failed` alert naming those policies, and a clean catalog gives none;
  - (6) with the database refusing, `run` keeps retrying and returns once it is up; with `stop` set, it returns None within one wait.
- **Crash window:** a committed delete whose `uploaded/policy-<id>.bit` was left on disk gives, at start-up:
  - the file gone, the policy still deleted, no `bit_import` row;
  - one alert listing `{"subject": "uploaded/policy-<id>.bit", "check": "leftover of an interrupted delete"}`.
  A start-up with only live uploaded policies gives no alert.
- **Carry row:** make one file's import raise once (for example by patching `folders.import_one` to fail on the second file the first time). No policy is deleted in that attempt, and the retry completes with the full import and deletion.
- **Suggested plants:**
  - run the check before the reconcile → a file changed while down alerts (red);
  - drop the leftovers from `differences` → the crash-window row goes red;
  - skip `fail_running_tasks` → (2) red;
  - retry only the failing step → the carry row goes red;
  - alert on an empty list → the clean-catalog row goes red (`integrity_failed` raises ValueError).
