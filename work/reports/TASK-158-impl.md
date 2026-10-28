# TASK-158 IMPL: integrity check (#103) and the start-up sequence

REQ-165 (1)–(4) and (6) (the manager side); TS §4.1 L528, §4.2 L540 and L542, §8.4 L1291; #27, #102 (d), #103; the decisions rows from "Crash window ruling" to the end.

## Files

| File | Change | Physical lines |
|---|---|---|
| `manager/bitscan_manager/services/importer/integrity.py` | new | 127 |
| `manager/bitscan_manager/services/importer/startup.py` | new | 90 |

No other file was changed: no approved importer file, no `runtime.py`, no tests. Both files together are about 150 code lines, inside the ~170 budget.

## Start-up order (`startup.py`)

`run_once(db, clock, bits_dir)` (:53) opens one pinned session and holds `catalog_lock(session)` for all four steps. Each step writes one fixed INFO log line, `catalog start-up step: <name>`, which is the recorded step log:

1. `finish_uploads`: `uploads.finish_interrupted_uploads(session, bits_dir)`. If `uploaded/` is missing or unreadable, that approved function returns `(0, 0)` with one log line and start-up carries on.
2. `fail_running_tasks`: in one transaction, `repositories.imports.fail_running_tasks` with the fixed #98 (g) result `{"error": "The manager stopped before the task finished."}` (:38) and `clock.now()`.
3. `reconcile`: `folders.reconcile(session, clock, bits_dir)` in auto mode.
4. `integrity_check`: `integrity.check_and_alert(session, bits_dir, reconciled)`, run after the reconcile (#27).

Then `done`. The function returns a `StartupResult` with `uploads`, `failed_tasks` (count), `reconciled` and `differences`.

`run_until_done(db, clock, bits_dir, stop, *, retry_s=10.0)` (:69) is the #27/#102 (d) retry. If a pass raises `DatabaseUnavailable` or `psycopg.OperationalError` (inside a session body the pool re-raises the raw driver error), the function logs one fixed line naming only the exception type, then calls `stop.wait(retry_s)`. That is a blocking wait with no busy loop, and a stop request ends it at once (checklist item 10). The next try restarts from step 1, and every step is safe to repeat. The interval is a constant 10 s, as #102 (d) says ("retrying every 10 s"); the retry is bounded by the stop event. The function returns `None` if stop is set before a pass completes. Any other exception propagates. TASK-160 owns the thread, the 503 gate and what to do with such an error.

## Integrity check (`integrity.py`)

`differences(session, bits_dir, reconciled)` (:65) only reads; it never repairs anything. Differences come in a fixed order, each as `alerts.Difference(subject, check)` with a fixed check text (:38–46):

1. Unreadable folders: every label in `reconciled.unreadable_folders`, together with `folders.unreadable(bits_dir)` re-checked now, in the order `./` then `uploaded/`. Check text: **"folder could not be read safely"**. Per the TASK-156 tester's finding, it does not claim the folder is missing (Folder guard ruling).
2. `reconciled.leftovers`, exactly as TASK-156 built them: subject is the path, check is "leftover of an interrupted delete" (Crash window ruling).
3. `reconciled.strays`: subject is the path, check "uploaded file that is not a live policy's file" (stray ruling).
4. `reconciled.renamed`: subject is the path, check "uploaded file whose policy name was edited" (edited-name ruling, with its own text as TASK-156 r1 asked).
5. For each non-deleted policy, from `integrity_rows` (TASK-150), with subject `policy:<id>`:
   - `bad_plugins > 0` gives "listed plugin not active or owned by another policy". This runs even when the folder is unreadable.
   - If the policy's folder is unreadable, the file checks are skipped: the folder is already listed and nothing is read through it.
   - Otherwise the file is read once with `folders.read_input`, which uses a no-follow folder handle:
     - no file: "file missing at source_file";
     - SHA-256 differs from `source_sha256`: "file hash differs from source_sha256". The Plugin count is then not compared, because it is a different file;
     - same hash: the file is parsed with `parse_bit` and `structure.check`, and nothing is written. Unparseable gives "file at source_file could not be parsed"; a `<Plugin>` count different from the `policy_plugin` count gives "policy_plugin count differs from the Plugin elements in the file".
6. Folder side (#103): every `discover()`ed file that is not a live `source_file` and not already listed (strays and renamed files) is read for its hash. Those pairs go to `rejected_files` in one query. A file with no rejected row for its current hash gives "file is not a policy's source_file and has no rejected import".

`check_and_alert` (:110): with no differences, it logs `clean` and writes nothing, so a clean catalog raises no alert. Otherwise it writes one transaction with `emit(PgAuditRepo, on_commit, alerts.integrity_failed(found), actor="system")`. That builder (TASK-153) lists the first 100 differences plus `difference_count`, uses `target=None` (so the 255-character cap does not apply; paths are only in the detail and go through `_storable`) and the `catalog_integrity_failed` kind. The function then logs one line with the count only.

Logging: no paths, no file content and no tokens. The only log lines are the fixed step names, the count and the exception type. The approved folders and uploads code writes its own lines.

## How REQ-165 is met
- (1) Step 1 calls the approved function; a missing or unreadable `uploaded/` does not fail start-up.
- (2) Step 2 sets `failed` with `finished_at` = `clock.now()` and the fixed result.
- (3) Step 3 runs the auto reconcile.
- (4) Step 4 runs after the reconcile (#27) and writes one alert that lists every difference.
- (6) `run_until_done` retries every 10 s on a stop event. `/healthz` is TASK-160's wiring; nothing here touches it.

## Gates (from the repo root, venv)
- `ruff check manager` and `ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues, 293 files.
- No-regression suites (PG via Docker): `test_folders_pg`, `test_uploads`, `test_uploads_pg`, `test_import_pipeline_pg`, `test_catalog_admin_repo_pg`, `test_alerts`, `test_alerts_pg`, `test_import_alerts`, `test_import_alerts_pg` and `test_catalog_lock_pg`: 674 passed.
- I also ran a throwaway smoke test (in the scratchpad, not in the repo). Results:
  - A clean start-up gave no alert and the steps logged in order.
  - After deleting one `policy_plugin` row (owner) and planting an uploaded stray, one alert listed both. A rejected server file with a `rejected` row was not listed.
  - With the database unreachable, `run_until_done` returned `None` when stop was set.

## Cases for the tester (TP-M7-18, `manager/tests/test_catalog_startup_pg.py`)
- **Step order:** capture the `bitscan_manager.services.importer.startup` INFO lines. Expect `finish_uploads`, `fail_running_tasks`, `reconcile`, `integrity_check`, `done`.
- REQ-165 (1): the four temp-file cases through `run_once`. With `uploaded/` missing, start-up still reconciles the server folder.
- REQ-165 (2): a `running` task becomes `failed` with `finished_at` set and result `{"error": ...}`; other tasks are untouched.
- REQ-165 (3): a file added while the manager was down is imported, and one removed is deleted.
- REQ-165 (4): a deleted `policy_plugin` row gives `policy:<id>` with the count check, and a changed `source_sha256` gives `policy:<id>` with the hash check. Both appear in one `catalog_integrity_failed` alert, with `detail.alert = true` and `bitscan_alerts_total{kind="catalog_integrity_failed"}` +1. A clean catalog gives no `catalog.integrity_check` entry.
- Plugin ownership: a listed plugin set `retired`, or owned by another policy (owner UPDATE), gives the plugin check.
- **Extra test 1 (Crash window):** commit a delete of an uploaded policy (owner UPDATE as `delete_in_tx` would) and leave `uploaded/policy-<id>.bit` on disk. After `run_once`: the file is gone, the policy is still deleted, there is no new `bit_import` row, and one alert has `{subject: "uploaded/policy-<id>.bit", check: "leftover of an interrupted delete"}`.
- **Extra test 2:** a restart with only live uploaded policies (unchanged files) gives no alert.
- Stray, renamed and unreadable folders: an uploaded stray, an edited `<PolicyName>`, and `uploaded/` replaced by a symlink or a file. Each is listed with its own text, and the folder text never says "missing".
- Folder side: an unknown server file with a `rejected` row for its current hash is not listed; the same file edited (new hash) is listed with the untracked check.
- More than 100 differences: 100 listed, `difference_count` is the total.
- REQ-165 (6): an `AppDatabase` pointing at a closed port with `retry_s` small. `run_until_done` returns `None` soon after stop is set (G27-style bound) and does not spin. A fake that fails once and then succeeds returns a result after one wait.
- Canary: plant a token-like string in a folder file's content and check that it is absent from logs and from the alert detail.
- Lock: a concurrent `delete_policy` started during `run_once` waits until `run_once` returns (TASK-154 review carry (a)).

## Known limits (for reviewer and tester)
- A renamed live upload appears twice: once as the path with the renamed text, and once as `policy:<id>` with the hash check, because its hash differs from `source_sha256`. These are two true #103 differences with different subjects. A rejected changed server file also alerts at each start-up (hash check). This follows #103 and the TASK-156 review nit (TS §4.1).
- If the database fails after the reconcile removed a leftover but before the alert commits, the retry no longer sees that file, so the alert does not list it. `folders.remove_leftover` has already written its log line. Fixing this would need a change in approved `folders.py`. It is the same window as a crash at that moment.
