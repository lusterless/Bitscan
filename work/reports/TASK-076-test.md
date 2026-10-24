# TASK-076 TEST report: fleet read routes

**Verdict: PASS** (2026-10-23, tester-e). REQ-081 (1)–(5), REQ-063 (5); #68, #69. Checks CHK-M3-275 to -278 and their plants (CHK-M3-275-mut). Code: `bm/services/agents/fleet.py`, `bm/api/user/agents.py`, `bm/api/user/__init__.py`, the component-clash guard in `bm/app.py` (`work/reports/TASK-076-impl.md`). Tree copies: 10:04:13Z and 13:53:52Z.

## Commands
- W: `test_agents_api_pg.py` is 29 of 29 in R1 and R2. The first run (09:55Z tree) failed only on my fixture inserting `os_id` into `agent`, a column that does not exist; this is fixed.
- W plants (P1): 7 of 7 red. L: ruff, format and mypy are clean.

## Acceptance criteria
- A viewer `bsk_` reads the three routes with exactly the #68 fields (and the #69 snapshot); no token gets 401; an unknown id gets 404: CHK-M3-275 PASS.
- Paging N + 1 returns each item once: CHK-M3-276 PASS.
- `<script>` values are returned verbatim: CHK-M3-277 PASS.
- No token or hash appears in any response or in the document: CHK-M3-278 PASS.

## Test changes
- New: `manager/tests/test_agents_api_pg.py`.

## Notes for the reviewer
1. A package `version` that `debversion` cannot parse (`1 0`, `x:1.0`, …) is accepted by the contract and must not break the page. `test_a_package_version_that_is_not_debian_syntax_never_breaks_the_page` passes for 5 forms.
2. A malformed `{id}` on these user routes answers 404, not 400. #68 does not say which; the test accepts either, as problem+json.

Evidence runs (all W, CI=true):
- R1 = `tester2_m3run.sh t075079b tests/test_rotation_api_pg.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py -rf -v`. Tree copied 2026-10-23T10:04:13Z. Result: 135 passed, 1 failed; the failure is the TASK-078 float case that led to r1.
- R2 = `tester2_m3run.sh t078r1 tests/test_audit_log_api_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_openapi.py tests/test_login.py tests/test_contract_agent.py tests/test_agents_api_pg.py tests/test_agents_admin_api_pg.py -rf`. Tree with TASK-078 r1 copied 2026-10-23T13:53:52Z. Result: 686 passed, 0 failed, 0 skipped.
- P1 = `tester2_mutw2.sh tester2_plants076.json` over the agents, agents-admin and metrics files: control 80 passed.
- P2 = `tester2_m3mutw2.sh tester2_plants078.json`: control 12 passed.
