# TASK-051 TEST report: agent repository

**Verdict: PASS** (2026-10-23, tester). REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082 at the repository level. Plan checks: CHK-M3-050 to -055 (plus -051-rot and -051-list). Code tested: `bm/repositories/agents.py` (`work/reports/TASK-051-impl.md`).

## Tests added
- `manager/tests/test_agent_repo_pg.py`: 53 tests (marker `pg`), all as `bitscan_app`. Fleet-wide statements run in rolled-back transactions.

## Commands
- W (`CI=true`): 109 passed together with the TASK-052 and TASK-053 files, 0 skipped, no container left.
- L: ruff, format, mypy clean. Full L suite: 1816 passed, 607 skipped (PostgreSQL and Linux-only).
- Plants: 16 in WSL copies, all red. Control 109 passed. G1: f-string SQL → S608.

## Acceptance criteria
- "every function works with only the TS §5.2 grants": CHK-M3-050 PASS.
- "an unknown hash returns none": CHK-M3-051 PASS.
- "the `agent_ip_seen` upsert keeps `first_seen_at`": CHK-M3-052 PASS.
- "a tag replace is all-or-nothing": CHK-M3-053 PASS.
- "the status update touches only agents in the statuses it names": CHK-M3-054 PASS.
- "ruff S608 passes": CHK-M3-055 PASS.

## Note
- The age base (`GREATEST(last_heartbeat_at, enrolled_at, latest approval)`) is under a ruling you were asked for. The tests pin the #25 (c) cases (never-heartbeat agents from `enrolled_at` or the approval) and the normal heartbeat case. They do not pin the re-enrolment case the impl report describes; if your ruling changes the base, I add that case.
