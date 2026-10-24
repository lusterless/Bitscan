# TASK-078 TEST report: audit-log route

**Verdict: PASS on revision 1** (2026-10-23, tester-e). REQ-085 (1)–(3); #38, #68; lead ruling 2026-10-23 (b) (`detail_text`). Checks CHK-M3-285 to -287 (CHK-M3-285-mut). Code: `bm/repositories/audit_log.py`, `bm/api/user/audit_log.py`, `bm/api/user/__init__.py`, and in r1 also `README.md` (`work/reports/TASK-078-impl.md`).

## Round 1 (tree 10:04:13Z)
11 of 12 passed. `test_numbers_written_by_the_app_reverify` was red: an app-written float (`1e-07`, stored by jsonb as `0.0000001`) could not be re-verified from `detail`, because re-serialising it in Python does not give the hashed text. I asked `main` before calling a verdict. Ruling (b): add `detail_text`. This was a spec gap, so I did not count it as a FAIL round.

## Revision 1 (tree 13:53:52Z)
- R2: 12 of 12 passed (686 in the whole run).
- P2: 4 of 4 red, including "`detail_text` re-serialised from `detail`".
- The test kept its round-1 expectation; only its key list gained `detail_text`.

## Acceptance criteria
- An admin `bsk_` pages through every entry once, newest first; an operator is refused: CHK-M3-285 PASS.
- Items are the columns plus `detail_text`, and the chain re-verifies from the items with `compute_row_hash`, floats included: CHK-M3-286 PASS.
- The route writes nothing: CHK-M3-287 PASS.

## Test changes
- New: `manager/tests/test_audit_log_api_pg.py`.

Evidence runs (all W, CI=true):
- R1 = `tester2_m3run.sh t075079b tests/test_rotation_api_pg.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py -rf -v`. Tree copied 2026-10-23T10:04:13Z. Result: 135 passed, 1 failed; the failure is the TASK-078 float case that led to r1.
- R2 = `tester2_m3run.sh t078r1 tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_openapi.py tests/test_login.py tests/test_contract_agent.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py -rf`. Tree with TASK-078 r1 copied 2026-10-23T13:53:52Z. Result: 686 passed, 0 failed, 0 skipped.
- P1 = `tester2_mutw2.sh tester2_plants076.json` over the agents, agents-admin and metrics files: control 80 passed.
- P2 = `tester2_m3mutw2.sh tester2_plants078.json`: control 12 passed.
