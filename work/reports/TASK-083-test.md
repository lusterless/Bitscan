# TASK-083 TEST report: token before body on the heartbeat; UUID form; content coding

**Verdict: PASS** (2026-10-23, tester-e). TP-M3-37; REQ-065, REQ-062; TS §6.3 L1136; the lead rulings of 2026-10-23 (hyphenated agent path and query ids, case-insensitive content coding, malformed `{id}` → 400). Code: `bm/api/agent/{heartbeat,dependencies,jobs,inventory,schemas}.py`, `bm/api/attempt_limits.py` (`work/reports/TASK-083-impl.md`). Tree copies: 14:03:35Z (suite) and about 14:10Z (plants). **Two approvals.** This is the first PostgreSQL run of this change.

## Commands
- W: 13 files, 1256 passed, 2 failed, 0 skipped. Both failures were in my new file:
  - one test ran 31 heartbeats from several IPs;
  - httpx cannot send a `\n` in a URL (that path is covered by `test_body_caps.py`).
  Both are fixed and green in the 108-test plant control.
- W plants: 4 of 4 red.
- L: ruff, format and mypy clean.

## Acceptance criteria
- A bad or missing token with any body → 401 and counted; the 21st → 429; a valid token with a bad body → 400; valid behaviour unchanged: CHK-M3-385 PASS.
- Path and query ids accept only the hyphenated form; a malformed `{id}` → 400, not counted: CHK-M3-386 PASS.
- Content coding case-insensitive: CHK-M3-387 PASS.
- Heartbeat, M2 sign-in, enrol, jobs/results, inventory, rotation and OpenAPI suites re-run green: CHK-M3-388 PASS.

## Test changes
- New: `manager/tests/test_agent_token_first_pg.py`.
- Updated:
  - `test_attempt_limits_pg.py`: the route-class list includes the heartbeat;
  - `test_agent_auth_pg.py`: a malformed `{id}` → 400.
