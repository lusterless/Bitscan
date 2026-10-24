# TASK-071 TEST report: the scheduler inside `serve`

**Verdict: PASS** (round 2, revision 1, 2026-10-23, tester-d). Round 1 FAILED only CHK-M3-233-db: SIGTERM took 46 s with the database refusing. REQ-080 (1)–(5), #67. Plan checks: CHK-M3-230 to -234. Gates: G27 (also as `bstester`) and G29. Code tested: `bm/services/scheduler/runner.py` (r1: stop flag, `_StoppableDatabase`) and `bm/cli/serve.py` (`work/reports/TASK-071-impl.md`, "Revision 1"). Lead ruling 2026-10-23 (TASK-071 revision 1).

## Commands
- W (CI=true), the 11 files, as root and as `bstester`: 201 passed, 0 failed, 0 skipped in each.
- W timing run (`-rP`): SIGTERM with the database refusing in 4.0 s (wrong password) and 4.2 s (closed port).
- L: `tests/test_scheduler_runner.py` 15 passed. ruff, ruff format and mypy --strict are clean.
- Plants (WSL copies): 14 of 14 round-1 plants red, 2 of 2 in 071b, 3 of 3 new stop-flag plants red. All controls green.

## Acceptance criteria
- Both jobs run repeatedly, with the inventory run at start-up: CHK-M3-230 PASS (round 1, re-run green).
- A run that raises is logged by type, and the next run happens: CHK-M3-231 PASS.
- Overlapping runs never execute at once: CHK-M3-232 PASS.
- SIGTERM exits 0 with no run after the pool closed, database up: CHK-M3-233-r1 PASS.
- SIGTERM with the database down exits within the M2 bound (CHK-M2-257's 10 s): CHK-M3-233-db-r1 PASS.
- G29: PASS.
- An interval change takes effect within one sweep: CHK-M3-234 PASS.
- No production interval or skip knob: confirmed (CHK-M3-233-r1).

## Tests changed
- `manager/tests/test_scheduler_runner.py`: new `test_stop_with_the_database_refusing_gives_up_at_the_next_step` (L).
- `manager/tests/test_serve_scheduler_linux.py`:
  - the refusing-DB test is parametrized (wrong password, closed port), with its bound tightened from 15 s to 10 s and no `PoolClosed`/`Traceback` allowed;
  - the database-up SIGTERM test now allows only `SchedulerStopping` give-ups, logged by job and type, as the r1 ruling describes.

## Round 1 (FAIL, kept for the record)
- CHK-M3-233-db: with PostgreSQL refusing connections, SIGTERM took 46.0 s, because `shutdown(wait=True)` waited for start-up runs whose every transaction waited the 5 s pool timeout; the M2 G27 test (15 s) went red as root and as `bstester`. Everything else passed, with 14 of 14 plants red.

## Observation (not a defect)
With the database down, `start()` still waits one connect timeout per interval read during the lifespan start-up before it uses the seeded values. The impl report already notes this; SIGTERM timing is not affected.
