# TASK-159 TEST: PASS (on revision 1); REQ-164 (4) PASS with the TASK-155 r2 and TASK-152 r1 hooks in

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-164 (1)–(5); TS §4.1 L526, L528; #102 (a)–(c); PD-33 (b); decisions "W6 pre-read rulings" (2) (r1: incoming paths first) and "#102 (c) wiring". Code under test: `bm/services/importer/inotify.py`, `watcher.py` (r1) and `own_changes.py`, with the writer hooks from TASK-155 r2, TASK-152 r1 and TASK-156 r2 in the same tree. New test file: `manager/tests/test_watcher_linux_pg.py` (17 tests). It runs only where inotify exists (Linux, W), against a real watcher thread (`poll=0.05`) with its own module database and a temporary folder per test. "Within 5 s" is a bound polled every 50 ms. Checks that nothing happened write a sentinel file afterwards and wait for its row, so no fixed sleeps decide them.

## Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t159` of the tree with r1 and the hooks, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| w0 | `pytest tests/test_watcher_linux_pg.py` (14 tests) | 14/14 passed |
| w1 | the same, after adding three rows that plants w3, w8 and h2 showed were needed | **17/17 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red (w3, w8 and h2 only after the new rows) |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`, `mypy --strict` (CI form) | clean |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-237 (1) | APP | W | w1 | PASS | REQ-164 (1): `cp` of `n.bit` into the server folder → a `success` row (`auto`, `imported_by` null) within 5 s; an edit → a second row with version +1; `rm` → the policy deleted within 5 s, one `policy.delete` by `system` with reason "file removed", `policy_deleted` +1. A file `mv`ed in (`IN_MOVED_TO`) imports; an `uploaded/foreign.bit` imports and is relocated to `uploaded/policy-<id>.bit` (case (c)) | 2026-10-28 |
| CHK-M7-237 (3) | APP | W | w1 | PASS | REQ-164 (3): ten chunks written over 2 s into one open file → exactly one row, `success`, the full file's sha, 10 plugins | 2026-10-28 |
| CHK-M7-237 (4) | APP | W | w1 | PASS | REQ-164 (4): two uploads (new, then a replacement) → only their two `manual` rows, no watcher row for the temp write or the rename (hook #1). An API delete adds nothing beyond its own `policy.delete` (hook #3). A start-up finish rename on its own, after a simulated restart cleared the stale record, adds no row (hook #2). An admin edit with another hash within 60 s of our rename is still imported (#102 (c) is by hash) | 2026-10-28 |
| CHK-M7-237 (2) | APP | W | w1 | PASS | REQ-164 (2), #102 (b): `n.txt`, `.n.bit`, `sub/n.bit`, `uploaded/.tmp-1-x`, a symlink `l.bit`, a FIFO `f.bit` and `\xff.bit` → no row; the unstorable name logs its one fixed line | 2026-10-28 |
| r1 mv | APP | W | w1 | PASS | `mv a.bit c.bit` (one batch, `IN_MOVED_FROM` + `IN_MOVED_TO`) → same policy id, `source_file` `c.bit`, exactly one `policy.move`, no `policy.delete` or `policy_deleted`; its queued job stays `queued` and its schedule stays enabled | 2026-10-28 |
| back again | APP | W | w1 | PASS | Delete-then-rewrite in one batch keeps the policy. With the lock held and the watcher seen waiting in `pg_locks` on the delete event, a rewrite before the lock is released → imported, not deleted (no `policy.delete`, no `policy_deleted`) | 2026-10-28 |
| #102 (a) rescan | APP | W | w1 | PASS | `uploaded/` removed and recreated → watched again (a file in it imports). `uploaded/` created after the watcher opened (none at open) → its `IN_CREATE` (`IN_ISDIR`) rewatches it, and a file in it imports | 2026-10-28 |
| failure | APP | W | w1 | PASS | One import raising `OSError` → one line `folder event failed: OSError` (no message text), then a reconcile after `RETRY` (patched to 0.2 s) imports the file | 2026-10-28 |
| lock | APP | W | w1 | PASS | With the catalog lock held elsewhere, a new file gets no row within 1 s; it imports once the lock is released | 2026-10-28 |
| CHK-M7-238 | APP | W | w1 | PASS | REQ-164 (5): with `inotify.available()` false, `open()` returns False after one line and `run()` returns at once (2 lines: one per open attempt). Windows itself is not run | 2026-10-28 |
| #102 (c) unit | CODE | W | w1 | PASS | `OwnChanges`: no hash computed without a record; a same-hash record drops one event, once; another hash isn't dropped; two removals drop two events, then none; a removal expires after 60 s (injected clock) | 2026-10-28 |
| plant w1 | APP | W | `IN_MODIFY` instead of `IN_CLOSE_WRITE` | PASS (red) | 1 failed: the chunked write (several rows) | 2026-10-28 |
| plant w2 | APP | W | the hidden-name test dropped | PASS (red) | 1 failed: `.n.bit` imported | 2026-10-28 |
| plant w3 | APP | W | the `IN_ISDIR` `uploaded` rescan dropped | PASS (red) after the new row | First run 14 passed: the removed folder's `IN_IGNORED` rescans anyway. With the "created after open" row: 1 failed, not within 5 s | 2026-10-28 |
| plant w6 | APP | W | the own-write check dropped | PASS (red) | 2 failed: the upload and API-delete rows (an extra `auto` row) | 2026-10-28 |
| plant w7 (r1) | APP | W | incoming-first order removed | PASS (red) | 1 failed: `mv` deletes the policy (`policy.delete`) and revives it | 2026-10-28 |
| plant w8 | APP | W | the "back again" import removed | PASS (red) after the new row | First run 14 passed: coalescing hides it. With the lock-held row: 2 failed (`policy.delete` written) | 2026-10-28 |
| plant w4 | CODE | W | `drop_write` ignores the hash | PASS (red) | 1 failed: the unit row | 2026-10-28 |
| plant w5 | CODE | W | a match never used up | PASS (red) | 1 failed: the unit row | 2026-10-28 |
| plant h1 (155 r2) | APP | W | `UploadStage.after_commit` records nothing | PASS (red) | 2 failed: the upload and API-delete rows | 2026-10-28 |
| plant h2 (155 r2) | APP | W | the finish rename records nothing | PASS (red) after the new row | First runs passed: the failed upload rename had already recorded the same path and hash just before its call. With the restart-simulating row: 1 failed (a `skipped` row) | 2026-10-28 |

## Acceptance (TASK-159 row)

REQ-164 (1), (3) and (4) within 5 s → CHK-M7-237 (1), (3), (4). `n.txt`, `.n.bit` and `sub/n.bit` do nothing → CHK-M7-237 (2). No inotify → one line and `run` returns → CHK-M7-238. The lead's r1 row (`mv a.bit c.bit`: same id, no delete alert, no cancelled job, no disabled schedule) → r1 mv. Every security row has a plant that went red.

## Notes (no defect)

- The removal hooks (TASK-152 r1 `remove_after_commit`, TASK-156 r2 `Relocate` and the leftover) can't be seen in behaviour. The path they remove belongs to no live policy (a deleted policy, a foreign file or a leftover), so the unhooked delete event does nothing either. They are kept as defence in depth.
- The impl's caveat holds: a record made just before a call that then fails can drop one real event at that path within 60 s. In practice that is the finish rename of the same bytes, which is harmless.

## The three race plants, made deterministic (lead, 2026-10-28)

New rows: `test_an_overflow_triggers_a_rewatch_and_a_full_reconcile`, and `test_our_own_rename_is_recognised_whatever_the_writer_order[record_then_rename, rename_then_record]`.
- The overflow row feeds `_handle` a synthetic `Event(-1, IN_Q_OVERFLOW, "")`; `folders.reconcile` is a spy.
- The writer-order row is a writer stub. It holds the catalog lock across its rename into place, renames the same bytes, and waits until `pg_locks` shows the watcher blocked on the lock. In `rename_then_record` it records only then. With a correct watcher, neither order may give a row.

| Run (W, `/root/bstest-m7-t159`, `-n 0`) | Result |
| --- | --- |
| `pytest tests/test_watcher_linux_pg.py` | **20/20 passed**, 0 failed, 0 errors, 0 skipped |

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| overflow | APP | W | the run above | PASS | A synthetic `IN_Q_OVERFLOW` → one full reconcile, both folders re-watched, `_handle` returns False | 2026-10-28 |
| plant o1 | APP | W | an overflow event skipped | PASS (red) | 1 failed: the reconcile spy saw no call | 2026-10-28 |
| own change, both orders | APP | W | the run above | PASS | Record-then-rename and rename-then-record, both under the writer's lock: no row. The watcher checks the record after taking the lock | 2026-10-28 |
| plant o2 | APP | W | the own-change check moved before the lock | PASS (red) | 2 failed. `rename_then_record`: an extra `skipped` row, the race reproduced. `record_then_rename`: the watcher drops the event without waiting on the lock, so the harness's wait ends after 5 s (a harness effect, not a row) | 2026-10-28 |
| plant o3 | APP | W | `UploadStage.after_commit` records after its rename | equivalent (20 passed) | The writer holds the catalog lock and the watcher checks only after taking it, so recording after the call is still recognised. The `rename_then_record` row proves this. It goes red only together with o2 (shown above) | 2026-10-28 |
| overflow, real | — | — | — | NOT RUN | A real `IN_Q_OVERFLOW` needs more than `max_queued_events` (16,384) queued events; the synthetic row covers the branch | 2026-10-28 |

Verdict unchanged: **PASS**.
