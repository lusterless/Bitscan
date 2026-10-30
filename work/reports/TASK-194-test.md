# TASK-194 TEST: PASS

Tester: tester-m9b, 2026-10-30. Full rigor (high risk). REQ-219, REQ-220, REQ-230; TS §4.4 L573, L579–L581, §5.2 L1012; #127 (d)–(f). Code under test: `bm/repositories/scan_progress.py` (impl-manager-m9b, `work/reports/TASK-194-impl.md`). Test files: `manager/tests/test_scan_progress_repo_pg.py` (new), on the TP-M9-01 builder `manager/tests/scan_pg_fixtures.py` (self-test `test_m9_fixtures_pg.py`, 5/5). Plan rows: CHK-M9-114 to -116.

## Runs

| Run | Command (W: `/root/bstest-m9b-base`, venv `/root/venv-m9b`, `PYTHONPATH` pinned, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0`, a database of the module's own) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_progress_repo_pg.py` (in the W1 batch) | **6/6 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 4 (3 pytest, 1 ruff), each in a throwaway copy `/root/bstest-m9b-mut-<id>` | 4/4 red |
| static (L) | `ruff check manager`, `ruff format --check manager`, `mypy --strict` on the test files | clean |

## Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-114 | PASS | `unit_facts` over 3 scans is **one** statement (spy); the 6 units of scan A match the hand-written `Unit`s: a completed original; a partial original whose retry stored the 2 missing plugins (one complete, closed unit); a failed original with a queued retry (open, not all-queued); cancelled; expired; a partial + failed retry with p3 missing (has results, not complete). Scan B (two queued jobs) is all-queued; scan C (running, 1 result) is open with results. Unknown id absent, `[]` → `{}`. A result only in the retry makes the unit `has_results` |
| CHK-M9-115 | PASS | Candidates include a 30-day-old scan with `finished_at` NULL, finished `partial`/`failed`/`cancelled` scans created within 8 days, and a queued scan; they exclude a `completed` scan and a finished `partial` scan created 9 days ago |
| CHK-M9-116 | PASS | `cancel_open_jobs` of a scan with one job per state plus a queued retry cancels exactly queued, dispatched, running and the retry (sorted ids, `finished_at` = now); the 5 other jobs, another scan's queued job, the inventory job and every `scan` row are byte-identical; a repeat returns `[]`. `set_scan_state`: unchanged state → False (no write); `finished_at` is set once and kept through later state changes (`None` never clears it); `dispatched`, `expired`, `bogus` → `ValueError`; the other `scan` columns never change. `scan_row(lock=True)` makes a second session's `set_scan_state` wait (lock probe) until commit |
| CHK-M9-359 | PASS (red) | plant `state IN ('queued')` → 1 failed (cancel row) |
| CHK-M9-363 | PASS (red) | plant: candidates `finished_at IS NULL` only → 1 failed (refresh row) |
| CHK-M9-361 (repo) | PASS (red) | plant: group by `job_id` instead of the root → 2 failed (unit rows) |
| CHK-M9-376 | PASS (red) | f-string query added → ruff `S608`, exit 1 |

## Acceptance (TASK-194 row)

Unit facts match owner-written fixtures (originals with retries, results, every state) → CHK-M9-114. Candidates exclude `completed` scans and finished scans older than 8 days → CHK-M9-115. Cancel moves only queued, dispatched and running jobs of that scan; only `state` and `finished_at` of `scan` are updated → CHK-M9-116 (and CHK-M9-272: the app cannot update `scan.policy_id`, `policy_version` or `target`; `test_scan_queue_repo_pg.py::test_repository_runs_with_app_grants_only`).

## Notes (no defect)

- The 8-day boundary itself (`created_at > now − 8 days`, strict) is recorded, not asserted: #127 (f) says "created in the last 8 days" without naming the boundary instant.
- Probe fix in my builder: `pg_stat_activity` hides other roles' wait events from a non-superuser, so the lock probe reads `pg_locks` (`granted = false`), which every role can read.
