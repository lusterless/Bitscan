# TASK-197 TEST: PASS (incl. r1)

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-224, REQ-225, REQ-230; TS §5.2 L846–L857, L864, L1013, §4.4 L557; #122 (h), #128 (d), (e); decisions "M9 builder rulings" (FOR SHARE on schedule create/enable; the tick never waits for a policy). Code under test: `bm/repositories/schedules.py` (impl-manager-m9b, `work/reports/TASK-197-impl.md` and its r1 note). Test file: `manager/tests/test_schedules_repo_pg.py` (new). Plan row: CHK-M9-122.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_schedules_repo_pg.py` (W1 batch, r1 tree) | **9/9 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 4 (3 pytest, 1 ruff) | 4/4 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-122 | PASS | CRUD round trip: insert returns the full row (name stored as given, incl. spaces and `é`); `update` changes name, target, cron, timezone, enabled, `next_run_at` and never `policy_id`/`created_by`. `policy_id`, `created_by`, `last_run_at`, `{}` and a mixed change → `ValueError`, with the row unchanged. Unknown id → None; delete True once, then False. Page by `schedule_id` after a cursor, in order. DELETE leaves the schedule's scans with `schedule_id` NULL (TS §5.2 L864). `due`: enabled and `next_run_at ≤ now` (exactly now is due, +1 µs not, NULL never, disabled never), oldest first, `limit` honoured; a second session gets `[]` for the rows the first holds, then both after release. `previous_unfinished`: the latest scan by `created_at` decides (no scan → False). `mark_run` keeps `last_run_at` on a skip. `get(lock=True)` holds the row (`LockNotAvailable` for a second session with a 300 ms lock timeout) |
| r1 FOR SHARE | PASS | `policy_state(lock=True)` makes a policy `UPDATE` (what M7's delete does first) in a second session wait (pg_locks probe) until the schedule transaction commits |
| r1 SKIP LOCKED | PASS | `try_share_policy` returns False **at once** while another session holds the policy row (an `UPDATE`), and True once released; another session's plain `FOR SHARE` does not block it |
| CHK-M9-373 | PASS (red) | plant: `due` without `SKIP LOCKED` → 1 failed (the second session waits and hits its 2 s lock timeout) |
| 197r1-share | PASS (red) | plant: `policy_state(lock=True)` without `FOR SHARE` → 1 failed |
| 197r1-skip | PASS (red) | plant: `try_share_policy` without `SKIP LOCKED` → 1 failed |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

## Acceptance (TASK-197 row)

CRUD round trip; due selection skips rows another session holds; DELETE leaves that schedule's scans with `schedule_id` NULL → CHK-M9-122. The r1 rows back TASK-201 r1 and TASK-203 r1 (their races are in those reports).

## Notes (no defect)

- `try_share_policy` on an unknown policy returns False. That can't happen: the FK holds, and policies are only soft-deleted.
