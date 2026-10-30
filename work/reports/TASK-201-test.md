# TASK-201 TEST: PASS (incl. r1)

Tester: tester-m9b, 2026-10-30. Full rigor. REQ-224, REQ-227; TS §6.2 L1124, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), (i), #129 (a); decisions "M9 builder rulings" (FOR SHARE on schedule create and enable). Code under test: `bm/services/scheduler/schedules_admin.py` (impl-manager-m9b, `work/reports/TASK-201-impl.md` incl. r1). Test file: `manager/tests/test_schedules_admin_pg.py` (new). Plan rows: CHK-M9-188, -189.

## Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_schedules_admin_pg.py` | 8/26 passed, 18 failed: **test bug** (my checksum helper lacked `scan_schedule`) |
| re-run | the file after the helper fix | **26/26 passed**, 0 skipped; 0 containers left |
| plants | 5 | 5/5 red |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-188 | PASS | create: defaults UTC and enabled; `next_run_at` = 16th 03:00 UTC from the 15th 12:00 (worked out by hand); agent ids stored lowercase; one `scan_schedule.create` by `user:7`, target `scan_schedule:<id>`. `0 9 * * *` Asia/Kolkata → 03:30 UTC; `0 3 * * 0` and `* * 7` → the next Sunday 03:00. PATCH cron → 04:30 UTC; timezone → 23:00 UTC (04:30 IST); `enabled: false` keeps `next_run_at`; `enabled: true` two days later recomputes from then; `policy_id` and `{}` → `InvalidField`; four `scan_schedule.update` entries by `user:8` naming the changed fields. Deleted policy: create and enable → `ScheduleConflict`, nothing written; a disabled policy is accepted; an unknown policy → `PolicyNotFound`; renaming a deleted policy's (disabled) schedule is allowed |
| CHK-M9-189 | PASS | delete: one `scan_schedule.delete` entry; its scan keeps its row with `schedule_id` NULL; delete/get/update afterwards → `ScheduleNotFound`. 18 bad fields (name `""`, 129 chars, U+0000, lone surrogate, non-string; cron `61 * * * *`, `@daily`, `0 0 1 * 1`, `0 0 30 2 *`, six fields, non-string; zone `Mars/Base`, `localtime`, `../etc/passwd`; target `{all:false}`, `{tags:[]}`, bad uuid; enabled `"yes"`) are refused on create **and** PATCH, with counts and the `scan_schedule` checksum unchanged and no input in the message. A 128-character name with outer spaces is kept as given. Another operator may change the schedule (`created_by` kept) |
| r1 race | PASS | for create and for enable: the schedule transaction is held open after its write; M7's policy delete started then **waits** (pg_locks probe) and, after the commit, disables the schedule. The schedule ends `enabled = false`, the policy deleted |
| plants | PASS (red) | FOR SHARE dropped (`lock=False`) → the race row; `next_run_at` not recomputed on enable → the PATCH row; NUL allowed in name → its row; the deleted check dropped → the conflict row; (CHK-M9-370 zone ignored, TASK-203 list) → the Kolkata rows |

## Acceptance (TASK-201 row)

REQ-224 (1)–(4), (6), (7) at service level → CHK-M9-188, -189. Through the API (incl. (5), RBAC) → TASK-206.
