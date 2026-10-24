# TASK-061 TEST report: inventory queueing

**Verdict: PASS** (2026-10-23, tester). REQ-077 (1), (2), (3), (5), (6) and REQ-088 (2), (3). Plan checks: CHK-M3-140 to -146. Code tested: `bm/services/scheduler/{__init__,inventory}.py` (`work/reports/TASK-061-impl.md`), over the TASK-054 statement.

## Tests added
- `manager/tests/test_inventory_queue_pg.py`: 19 tests (marker `pg`, G33). They run through the service with the real `JobRepo`. Single runs are rolled back; the race tests commit jobs for their own agents.
- `manager/tests/test_inventory_queue.py`: 5 unit tests (L, a fake queue). These keep G5 measuring the service locally, and hold the static no-switch and no-client checks.

## Commands
- W (`CI=true`): 55 passed with `test_jobs_repo_pg.py`, 0 skipped, no container left. L: 5 passed; ruff, format and mypy clean.
- Plants (WSL copies; control 23 passed): all 6 red:
  - window 23 h;
  - first job not limited to the agent;
  - a skip switch on the run;
  - `httpx` imported;
  - offline skipped (the G33 plant);
  - advisory lock removed.

## Acceptance criteria
- "one run queues exactly one job per `enrolled`, `online`, `stale` and `offline` agent and none for the others": CHK-M3-140 PASS.
- "a second run adds nothing while jobs are open": CHK-M3-141 PASS.
- "two simultaneous runs still give one job per agent": CHK-M3-142 PASS.
- "`queue_first_inventory` queues one job unless one is open": CHK-M3-144 PASS.
- REQ-077 (4), an interval change taking effect per #67, is the scheduler wiring: TASK-071 (CHK-M3-234).
