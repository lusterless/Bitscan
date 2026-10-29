# TASK-158 TEST: PASS

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-165 (1)–(4), (6); TS §4.1 L528, §4.2 L540, L542, §8.4 L1291; #27, #98 (g), #102 (d), #103; the crash-window ruling; decisions "TASK-158 test questions" (2026-10-28): (1) a changed `source_sha256` is repaired by the reconcile, with its `policy_imported` alert, and the check then finds nothing; (2) the start-up versus CLI-rebuild race is fixed as TASK-157 r2. Code under test: `bm/services/importer/startup.py` and `integrity.py`, with TASK-157 r2 in the same tree. New test file: `manager/tests/test_catalog_startup_pg.py` (15 tests, Linux only). Its own module database; each test owns its folders, and earlier live policies and running tasks are cleared first.

## Runs

| Run | Command (W, `-n 0`, `CI=true`) | Count |
| --- | --- | --- |
| s0 (copy `/root/bstest-m7-t158`, before the rulings) | `pytest tests/test_catalog_startup_pg.py -s` | 15/15 passed, plus the race probe printed (below) |
| s1 (fresh copy `/root/bstest-m7-t158b`, with TASK-157 r2) | `pytest tests/test_catalog_startup_pg.py tests/test_rebuild_pg.py`, with the sha row re-pinned to ruling (1) and the race probe turned into two must-pass rows (ruling (2)) | **32/32 passed** (15 start-up and 17 rebuild), 0 failed, 0 errors, 0 skipped |
| plants | 11 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 11/11 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean (298 files) |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-230 order | APP | W | s1 | PASS | The steps run in order: `finish_interrupted`, `fail_running_tasks`, `reconcile`, `check`, then `alert` (only with a difference). Another session's `pg_try_advisory_lock(hashtext('catalog'))` is false at each step, and the lock is free afterwards | 2026-10-28 |
| REQ-165 (1) | APP | W | s1 | PASS | A committed temp is renamed (with the right bytes). An uncommitted temp, `.tmp-x` and a symlink temp are deleted, and the symlink target is untouched. `finished` = (1, 3); afterwards the only entry is `policy-<id>.bit`; no difference | 2026-10-28 |
| REQ-165 (2) | APP | W | s1 | PASS | A `running` task → `failed` with `{"error": "The manager stopped before the task ended."}` and `finished_at` = clock; a `succeeded` task is untouched | 2026-10-28 |
| REQ-165 (3) | APP | W | s1 | PASS | A file removed while down → its policy deleted; a file added → imported; no integrity alert afterwards | 2026-10-28 |
| REQ-165 (4) | APP | W | s1 | PASS | Owner corruptions: a deleted `policy_plugin` row → "its plugin count differs from its file"; a retired plugin → "a listed plugin is not active or not owned by it". One `catalog.integrity_check` entry by `system`: `catalog_integrity_failed`, `difference_count` 2, listing exactly those. A clean catalog (server and upload files) raises none. A refused upload copy → "the file is neither a policy's file nor a rejected import"; a rejected file (it has its `rejected` row) is not reported | 2026-10-28 |
| sha (ruling 1) | APP | W | s1 | PASS | A changed `source_sha256` → the reconcile re-imports the file: one `success` row, version +1, `source_sha256` restored, one `policy.import` (`policy_imported`) on that policy; no difference, no integrity alert | 2026-10-28 |
| crash window | APP | W | s1 | PASS | A deleted policy's leftover upload → removed, still deleted, no row; exactly one difference `{"subject": "uploaded/policy-<id>.bit", "check": "leftover of an interrupted delete"}` in the one alert; a live upload policy untouched. Only live uploads → no alert | 2026-10-28 |
| REQ-165 (6) | APP | W | s1 | PASS | With `session()` refusing twice, `run` retries (`retry_s` 0.05) and returns a report. It logs two lines `catalog start-up failed, retrying: OperationalError`, without the message text. With `stop` set while it waits (`retry_s` 30), it returns None within 2 s | 2026-10-28 |
| carry | APP | W | s1 | PASS | One file's import fails in the first attempt: at that moment the policy whose file is gone is still live (no deletion after a partial import pass). The retry completes: both new files imported and the gone one deleted | 2026-10-28 |
| race (ruling 2, TASK-157 r2) | APP | W | s1 | PASS | `start_task` (CLI), then the start-up marks it `failed`; then `rebuild.run` returns `failed` with a reason. The task stays `failed` with the start-up's error, and the catalog is unchanged although a file changed. There are no `bit_import` rows, no audit entries (no `bits.rebuild`), and no `policy_rebuilt`. An unknown task id gives the same | 2026-10-28 |
| race probe (r0 evidence) | APP | W | s0 | recorded | Before r2: the rebuild ran and committed, and its `bits.rebuild` said `succeeded`. `task.state` stayed `failed` ("The manager stopped before the task ended."), because `finish_task` is once-only. The catalog was consistent (a check afterwards found nothing); only the task row and the audit entry disagreed. This was the defect, fixed in r2 | 2026-10-28 |
| plant s1 | APP | W | the check before the reconcile | PASS (red) | 5 failed: the order, files changed while down alert ("its file is missing", unknown file), the sha row, the unknown and leftover rows | 2026-10-28 |
| plant s2 | APP | W | leftovers dropped from the differences | PASS (red) | 1 failed: crash window | 2026-10-28 |
| plant s3 | APP | W | `fail_running_tasks` skipped | PASS (red) | 3 failed: order, (2), race | 2026-10-28 |
| plant s4 | APP | W | an import error swallowed in the reconcile (a partial pass, then deletions) | PASS (red) | 1 failed: carry | 2026-10-28 |
| plant s5 | APP | W | the alert written for an empty list | PASS (red) | `test_a_clean_catalog_raises_no_alert`: `ValueError`. In the full file the retry rows loop forever (the retry is total) until the run's timeout | 2026-10-28 |
| plant s6 | APP | W | the lock released before the reconcile | PASS (red) | 1 failed: order (lock free at reconcile) | 2026-10-28 |
| plant s7 | APP | W | the plugin-count check off | PASS (red) | 1 failed: (4) | 2026-10-28 |
| plant s8 | APP | W | the plugin-state check off | PASS (red) | 2 failed: order (no alert step), (4) | 2026-10-28 |
| plant s9 | APP | W | rejected files reported as unknown | PASS (red) | 1 failed: the unknown-file row | 2026-10-28 |
| plant rr (157 r2) | APP | W | the task re-check after the lock dropped | PASS (red) | 2 failed: both race rows (`succeeded` instead of `failed`) | 2026-10-28 |

## Acceptance

REQ-165 (1)–(4), (6) → the rows above; the order (#27, after the reconcile) and one lock → CHK-M7-230 order; #103 → (4) and crash window. REQ-165 (5) (the #102 (d) route answer during start-up) belongs to TASK-160. Rulings (1) and (2) → the sha and race rows, and plant rr drops the r2 re-check. Every security row has a plant that went red.

## Notes (no defect)

- Impl reading 1 holds: a leftover removed in a failed attempt is missing from the final alert, but it was logged when it was removed.
- Impl reading 2 holds: a permanent error keeps retrying (plant s5 shows the loop); it fails closed.
