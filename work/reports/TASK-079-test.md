# TASK-079 TEST report: metrics route

**Verdict: PASS** (2026-10-23, tester-e). REQ-086 (1)–(3); #70. Checks CHK-M3-290 to -292 (CHK-M3-290-mut). Code: `bm/services/audit/metrics.py`, `bm/api/user/metrics.py`, `bm/api/user/__init__.py` (`work/reports/TASK-079-impl.md`). Tree copies: 10:04:13Z and 13:53:52Z; the second holds the TASK-078 r1 export, against which the document check was re-run.

## Commands
- W: `test_metrics_api_pg.py` is 12 of 12 in R1 and R2.
- L: `test_metrics_scrape.py` is 1 of 1.
- Plants: 3 of 3 red. One of them ("a status with no agents missing") survived P1 and is red only with the new unit test, run in a local throwaway copy.

## Acceptance criteria
- `GET /api/v1/metrics` with a viewer token returns Prometheus text holding every REQ-086 metric; #70 authentication: CHK-M3-290 PASS.
- The gauges equal database counts; 3 heartbeats add 3; a sweep expiring 2 jobs adds 2: CHK-M3-291 PASS.
- Only bounded labels are used; no hostname, agent id or token appears: CHK-M3-292 PASS.

## Test changes
- New: `manager/tests/test_metrics_api_pg.py` and `manager/tests/test_metrics_scrape.py`.

## Notes for the reviewer
- The gauges are module-global, so two app instances in one process share them. This is fine with one manager (TS §2.1).

Evidence runs (all W, CI=true):
- R1 = `tester2_m3run.sh t075079b tests/test_rotation_api_pg.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py -rf -v`. Tree copied 2026-10-23T10:04:13Z. Result: 135 passed, 1 failed; the failure is the TASK-078 float case that led to r1.
- R2 = `tester2_m3run.sh t078r1 tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_openapi.py tests/test_login.py tests/test_contract_agent.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py -rf`. Tree with TASK-078 r1 copied 2026-10-23T13:53:52Z. Result: 686 passed, 0 failed, 0 skipped.
- P1 = `tester2_mutw2.sh tester2_plants076.json` over the agents, agents-admin and metrics files: control 80 passed.
- P2 = `tester2_m3mutw2.sh tester2_plants078.json`: control 12 passed.
