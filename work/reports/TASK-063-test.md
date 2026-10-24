# TASK-063 TEST report: agent router and bsa_ dependency

**Verdict: PASS** (2026-10-23, tester). Two approvals are needed. REQ-062 (1), (2), (4); REQ-064 (1), (2), (6) through the dependency; REQ-065 (1), (3), (4); REQ-066 (3); REQ-087 (1), (2). Plan checks: CHK-M3-160 to -169. Code tested: `bm/api/agent/{dependencies,bodies,__init__}.py`, `bm/app.py` (`work/reports/TASK-063-impl.md`).

## Tests added
- `manager/tests/test_agent_auth_pg.py`: 21 tests (marker `pg`). It uses the real dependency on a real `Runtime`, with test-only routes at agent paths, a probe route and an after-auth inventory route with a 1,024-byte cap, plus a raw ASGI driver that counts the bytes pulled.

## Commands
- W (`CI=true`): 21 passed. With G25 (`test_auth_dependencies.py`, `test_security_m2.py`): 62 passed, 0 skipped, no container left. L: ruff, format and mypy clean (164 files).
- Plants (WSL copies; control 21 passed), all 14 red:
  - CHK-M3-320, -321, -338, -362, -363, -364, -366;
  - the refusal raised inside the transaction (the carry-over);
  - pending counted;
  - the per-agent alert removed;
  - IP not recorded;
  - IPv4-mapped not normalised;
  - `agent_id` not set in the log context;
  - `read_capped` failing open.
- CHK-M3-323 against G25: red.

## Acceptance criteria
- "the full matrix … gives exactly the #59 outcomes": CHK-M3-160 to -163 PASS. It covers no header, wrong scheme, `bsu_`, `bsk_`, `bse_`, unknown, revoked, expired, mismatch, a missing machine-id header, pending, rejected, a foreign `{id}`, and the 31st request in a minute.
- "an IP over the failed limit presenting a valid token" passes: CHK-M3-164 PASS.
- "failures count toward the IP limit and valid tokens never do": CHK-M3-164 PASS.
- "records carry the `agent_id`": CHK-M3-167 PASS.

## Carry-overs
- All four from the reviews are tested: 0 bytes before a 401, `read_capped` failing closed, the refusal committing inside the transaction, and valid tokens never counted.
- For TASK-067 and 072 to 075: the route walk (CHK-M3-169) and the 401/403 matrix are re-run against the real routes, and the real after-auth routes must pull 0 bytes before a 401 (checked again in TASK-073 and TASK-074).
