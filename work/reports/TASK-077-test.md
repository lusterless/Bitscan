# TASK-077 TEST report: tags and revoke

**Verdict: PASS** (2026-10-23, tester-e). REQ-082 (1)–(4), REQ-068 (4); #68, #71, #73 (c). Checks CHK-M3-280 to -283; mutation rows CHK-M3-328 (revoke), -330 and -372 (CHK-M3-280-mut). Code: `bm/services/agents/admin.py`, `bm/api/user/agents.py` (`work/reports/TASK-077-impl.md`). Tree copies: 10:04:13Z and 13:53:52Z. **Two approvals.**

## Commands
- W: `test_agents_admin_api_pg.py` is 39 of 39 in R1 and R2. The first run's one failure was my test assuming a revoke entry has a `detail` object (it is `{}` or NULL); fixed.
- W plants (P1): 8 of 8 red. The environment is the M2 users-API one, with the real shipper as the sink gate. L: clean.

## Acceptance criteria
- An operator replaces and clears the tag set; invalid tags are refused with no change; a viewer is refused: CHK-M3-280 PASS.
- After revoke, the current and the previous (overlap) token get 401 `token_revoked`; a re-enrolment is held: CHK-M3-281 PASS.
- Revoke refuses an admin `bsk_`, an unverified session, other roles and the sink outage: CHK-M3-282 PASS.
- One entry per change; concurrent revokes write one: CHK-M3-283 PASS.

## Test changes
- New: `manager/tests/test_agents_admin_api_pg.py`.

## Notes for the reviewer
1. Tags work during a sink outage (it is not a sensitive action, per TS §6.2); this is asserted.
2. The tag answer is sorted. #68 says only `{tags}`, and the test compares the result as a set.

Evidence runs (all W, CI=true):
- R1 = `tester2_m3run.sh t075079b tests/test_rotation_api_pg.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py -rf -v`. Tree copied 2026-10-23T10:04:13Z. Result: 135 passed, 1 failed; the failure is the TASK-078 float case that led to r1.
- R2 = `tester2_m3run.sh t078r1 tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_openapi.py tests/test_login.py tests/test_contract_agent.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py -rf`. Tree with TASK-078 r1 copied 2026-10-23T13:53:52Z. Result: 686 passed, 0 failed, 0 skipped.
- P1 = `tester2_mutw2.sh tester2_plants076.json` over the agents, agents-admin and metrics files: control 80 passed.
- P2 = `tester2_m3mutw2.sh tester2_plants078.json`: control 12 passed.
