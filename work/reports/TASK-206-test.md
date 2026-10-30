# TASK-206 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-212 (1), REQ-224; TS §6.2 L1124, L1084, §6.3 L1133–L1138, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), #129 (a). Code under test: `bm/api/user/scan_schedules.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (impl-manager-m9b, `work/reports/TASK-206-impl.md`), on TASK-201 r1. Test file: `manager/tests/test_scan_schedules_api_pg.py` (new). Plan rows: CHK-M9-255 to -257.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_schedules_api_pg.py` | 21/22 passed, 1 failed: **test bug** (after moving the clock a day, my session token had idled out → 401; the test now opens a new session for the later call) |
| re-run | the file | **22/22 passed**, 0 skipped; 0 containers left |
| plants | 2 | 2/2 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-255 | PASS | POST → 201 with exactly the 10 item keys, `UTC`, enabled, `created_by` = the caller (API token), `last_run_at` null, `next_run_at` RFC 3339 Z = the next 03:00 UTC; list `{items, next_cursor}` paged by `schedule_id` in order; get → the item; unknown → 404 `not_found`; ids `x`, `1.0`, `+1`, `-1` and a bad cursor → 400 |
| CHK-M9-256 | PASS | PATCH cron → 04:30 next day; timezone Asia/Kolkata → 23:00 UTC; `enabled: false` → off; a day later `enabled: true` → recomputed from then; `{"policy_id": …}`, `{}`, `{"name": null}`, `{"enabled": "yes"}` → 400; a disabled policy's schedule → 201; a deleted policy → create 409 "The policy is deleted.", enable 409; unknown policy → 404 |
| CHK-M9-257 | PASS | DELETE → 204, empty body; second DELETE → 404; the schedule's scan keeps its row with `schedule_id` NULL; create, update and delete → exactly three entries by the caller with target `scan_schedule:<id>` (update detail `{"name": "renamed"}`). A viewer → 403 on all five operations, a `bsa_` token and no token → 401, nothing written; another operator (API token) and an admin may change and delete the schedule. 17 bad bodies (cron `61 * * * *`, `@daily`, both day fields; zone `Mars/Base`, `localtime`; target `{all:false}`, bad uuid; name empty, 129 characters, U+0000; extra `execute`, `plugins`, `command`, `payload`, `eval_spec`; `policy_id` "1"; `enabled` 1) → 400 `invalid_request` on create (and on PATCH for the patchable fields), counts and the `scan_schedule` checksum unchanged, no input echoed. A body over 1 MiB → 413 |
| role plant | PASS (red) | operator → viewer → 1 failed |
| extra-keys plant | PASS (red) | `extra="ignore"` on both bodies → 5 failed (the command-text keys and `policy_id` in PATCH accepted) |

## Acceptance (TASK-206 row)

REQ-224 (1)–(7) and REQ-212 (1) for the schedule bodies → the rows above. `manager/openapi.json` byte-identical after the re-export (G6 green in the security run).
