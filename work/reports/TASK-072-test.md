# TASK-072 TEST report: heartbeat

**Verdict: PASS** (2026-10-23, tester-d). REQ-070 (1)–(6), REQ-086 (2), REQ-088 (4); #25, #65 (a), #71, #73 (a). Plan checks: CHK-M3-235 to -242, the re-run of CHK-M3-169 and the agent matrix, and mutation rows CHK-M3-345, -367 and -368. Code: `bm/services/agents/heartbeat.py`, `bm/api/agent/heartbeat.py`, `bm/api/agent/__init__.py` (`work/reports/TASK-072-impl.md`). TASK-048 r2 (2^53 − 1) was re-run here: the contract suite is green.

## Commands
- W (CI=true), the 23 files listed in CHK-M3-235: 1434 passed, 12 failed, 0 skipped. **None of the 12 is a heartbeat check.** 11 come from TASK-073/074 code that is already in the shared tree:
  - 7 `test_body_caps.py` inventory cases and 2 `test_agent_auth_pg.py` after-auth probes mount test routes on the inventory template, which the real `PUT /inventory` now shadows;
  - 2 `test_login.py::test_openapi_error_contract` cases see the inventory 422 ruled on 2026-10-23.
  These test updates belong to TASK-074 TEST. The 12th was a defect in my new TASK-070 test (snapshot taken before a heartbeat); it is fixed, and its file is 23 of 23 green in the plant control.
- L: test_openapi, the contract suites, test_body_caps, test_login (except the 9 above), test_app and test_problems are green. ruff, format and mypy are clean.
- Plants: 18 of 18 red (CHK-M3-235-mut).

## Acceptance criteria
- Exactly three keys from the current settings; PATCH reflected; `server_time` RFC 3339 UTC: CHK-M3-235 PASS.
- Time, IP, version and helpers stored; status online at once (#73 (a)): CHK-M3-236 PASS.
- Helper change gives one entry and alert; the same list gives none: CHK-M3-237 PASS.
- Skew over 5 min alerts once per agent per hour, exactly 5 min does not, 150 days for three agents, marked only after commit: CHK-M3-238 PASS.
- No job row touched: CHK-M3-239 PASS.
- `last_error` logged with the `agent_id` and never audited: CHK-M3-240 PASS.
- Latency histogram: CHK-M3-241 PASS.
- Fixtures through the route, own 400s, 1 MiB cap, OpenAPI, G6 and the contract re-run: CHK-M3-242 PASS.
- Route walk and the 401/403/429 matrix on the real route: CHK-M3-169-072 PASS.

## Test changes
- New: `manager/tests/test_heartbeat_api_pg.py`.
- Fixed: `test_body_caps.py::test_other_agent_routes_keep_one_mib` now uses a test-only path with no registered cap, so the real heartbeat route no longer shadows it. The real route's own 1 MiB check is in the heartbeat file.
- Plan: CHK-M3-240 and -302 corrected to #25 (a) (lead-confirmed).

## Notes for the reviewer
- A reordered helper list is not treated as a change (sets compared), and no test asserts either way, because the spec says only "any change". Only `capread` exists in v1.
- The latency is observed only for successful heartbeats.
