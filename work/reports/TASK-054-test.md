# TASK-054 TEST report: job repository (inventory jobs)

**Verdict: PASS** (2026-10-23, tester). REQ-072 (1) to (4), REQ-076 (job lookup and finish), REQ-077 (1), (2), (3) and (5) at the repository level, REQ-078 (3), and REQ-079 (#66 input). Plan checks: CHK-M3-080 to -086 in `tests/m3/test-plan.md`, written before the code was read. Code tested: `manager/bitscan_manager/repositories/jobs.py` (`work/reports/TASK-054-impl.md`).

## Tests added
- `manager/tests/test_jobs_repo_pg.py`: 32 tests (marker `pg`). Every call runs as `bitscan_app` on a freshly migrated database. Compliance rows are planted as owner. Fleet-wide statements run in rolled-back transactions.

## Commands
- W (WSL2 Ubuntu 24.04, Docker, `CI=true`, `/root/venv-m2` rebuilt from the hashed dev lock: install exit 0): `pytest tests/test_jobs_repo_pg.py tests/test_grants.py` → 57 passed, 0 skipped, no container left.
- L: ruff, ruff format, `mypy --strict` clean (the 32 tests are skipped on L: Docker unavailable).
- Mutation plants, each in a throwaway copy `/root/bitscan-mut` (imports checked to come from the copy). Control: 32 passed. All 16 plants red:
  - CHK-M3-347, -348, -349 (two variants), -350, -351;
  - payload id generated separately;
  - advisory lock removed;
  - `running` not open;
  - `offline` skipped (the G33 plant);
  - expire `<`;
  - inventory failure on any kind;
  - inventory failure `<=`;
  - oldest age over every agent;
  - complete from any state;
  - `get_for_agent` ignoring the agent.

## Acceptance criteria
- "the payload's `job_id` equals the row's id": CHK-M3-080 PASS.
- "two concurrent pulls never return one job": CHK-M3-082 PASS.
- "every update uses only the TS §5.2 progress columns (a probe changing `agent_id` or `payload` is refused by the grants)": CHK-M3-083 PASS.
- "the expire and stale-inventory updates touch exactly the rows past their bound for a given `now`": CHK-M3-084 PASS.
- Also: the pull limit, ordering and filters (CHK-M3-081); open states and the queue-age input (CHK-M3-085); lookup and finish (CHK-M3-086).

## Notes
- Agreed reading, recorded by impl-manager: the 30-minute inventory bound is strict (exactly 30 min stays `dispatched`), per REQ-078 "more than 30 minutes". The plan sketch said `<=`. The test pins the REQ wording; if you want `<=`, tell me and the boundary row changes.
- The 24 h `pickup_by` rule itself belongs to the service that computes it (TASK-061; CHK-M3-143).
