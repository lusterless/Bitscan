# TASK-067 TEST report: `POST /api/v1/agent/enroll`

**Verdict: PASS** (round 2 on revision 1, 2026-10-23, tester-c). Round 1 FAIL: CHK-M3-204-scope. Two approvals are needed (TS §8.2). REQ-068 (1)–(7), REQ-065 (2), REQ-077 (#36), REQ-062 (1), (2). Plan checks: CHK-M3-200 to -208; mutation rows CHK-M3-322, -324, -337, -365 (and -332 to -335 through the route). Code tested: `bm/services/enrolment/enrol.py` (including the #71 actor revision), `bm/api/agent/enrol.py`, `bm/api/agent/__init__.py`, `bm/api/agent/dependencies.py`, `bm/app.py`, `bm/api/user/auth.py` (rename), `manager/openapi.json` (`work/reports/TASK-067-impl.md`); in r1 also `bm/api/peer.py` and `bm/auth/dependencies.py`.

## Round 1 failing check (fixed in r1)
- `tests/test_enrol_api_pg.py::test_scoped_ipv6_peer_is_never_a_500` and `tests/test_agent_auth_pg.py::test_scoped_ipv6_peer_is_never_a_500` (CHK-M3-204-scope).
  - **Input:** a TCP peer `fe80::1%eth0`, with a valid auto-approve `bse_` on enrol, or with a valid `bsa_` on a bsa_ route.
  - **Expected:** an answer from #59, never a 500. Either a 401 that changes nothing, or a success that stores the IP without its zone.
  - **Actual:** 500 `about:blank` on both routes.
  - **Diagnosis:** `source_ip()` in `bm/api/agent/dependencies.py` passes the zone through, because `ipaddress.ip_address` accepts it. `CAST(%s AS inet)` in `EnrolmentRepo.use_token` and in `AgentRepo.record_ip` then refuses it.
  - **Reach:** a link-local IPv6 client of a manager listening on `::` is reported with its zone by CPython. This is the same class as the TASK-066 r1 scope-id CIDR defect.

## Round 2 (revision 1)
- **Fix:** `bm/api/peer.py` (new). `peer_ip()` drops an IPv6 zone and turns IPv4-mapped peers into IPv4; `peer_key()` keys the limiters. The agent `source_ip()` uses `peer_ip()`. The agent, enrol, sign-in and user failed-check limiter keys all use `peer_key()`. The last two are M2 files: `api/user/auth.py` and `auth/dependencies.py`.
- **Scoped peer:** a scoped peer enrols and authenticates, and `fe80::1` is stored without its zone (CHK-M3-204-scope-r1 PASS).
- **One key per IP:** one IP gives one aggregate across user and agent routes, for mapped, zoned and non-IP peers alike, and the sign-in key is shared too (CHK-M3-164-r1 PASS).
- **Commands:** W gives 1178 passed, 0 failed. L static gates are clean. 7 of 7 r1 plants are red (CHK-M3-200-mut-r1).
- **G25 and the M2 suites** (login, rate-limit, request-log, API tokens, users API) were re-run because of the M2 files: PASS.
- **Tests added in round 2:** in `tests/test_agent_auth_pg.py`, `test_scoped_ipv6_peer_passes_and_is_stored_without_its_zone`, `test_user_and_agent_routes_key_one_peer_alike` and `test_a_non_ip_peer_is_keyed_alike_on_both_route_groups`. In `tests/test_enrol_api_pg.py`, the scoped test is tightened to the ruling and renamed `test_scoped_ipv6_peer_enrols_without_its_zone`.

## Tests added or changed
- New `manager/tests/test_enrol_api_pg.py`: 79 tests (marker `pg`). It runs the real `create_app()` with a fake clock, the real `RateLimiter`, and a probe route behind the real bsa_ dependency.
- `manager/tests/test_agent_auth_pg.py`:
  - added the commit-only re-check of the `agent_auth_failures` window and the scoped-IPv6 case;
  - the route walk now descends into included routers and is no longer vacuous.
- Placeholders updated per the ruling: `test_app.py`, `test_problems.py`, `test_login.py`, `test_auth_dependencies.py`, `test_contract_agent.py` (document `schema_gap`, enrol/`TotpEnrolRequest` document check), and `test_security_m2.py` (`user_routes()` excludes the agent group).
- TASK-048 r2: the fixtures moved to 2^53 − 1, three new 2^53 fixtures, a bound test, and the depth tests fixed for Linux.

## Commands
- W (`CI=true`), 15 files: 1152 passed, 1 failed (the failing check above), 0 skipped, no container left.
- L: the full suite gives 2175 passed and 951 skipped (pg, not run on L), plus 1 failure from TASK-072 (`test_body_caps`). ruff, ruff format and mypy --strict are clean (180 files).
- Plants (WSL copies, control 100 passed): 23 of 23 red (tests/m3/report.md CHK-M3-200-mut).

## Acceptance criteria
- Every refusal changes nothing, `uses` unchanged, counted, one 401 body: CHK-M3-200 PASS.
- 20 concurrent enrolments on a 5-use token give exactly 5: CHK-M3-201 PASS.
- The new auto-approved, new held and re-enrolment outcomes write exactly the REQ-068 rows and responses, and a re-enrolment with an auto-approve token stays held with the agent row untouched and no IP recorded: CHK-M3-202, -203 PASS.
- The IPv6 and mixed CIDR checks pass (CHK-M3-204 PASS); the scoped IPv6 peer FAILs (CHK-M3-204-scope).
- The 11th attempt from one IP gets 429: CHK-M3-207 PASS.
- The #61 alert fires on the enrolment after the threshold, actor `agent:<id>`: CHK-M3-205 PASS.
- One audit entry per enrolment, no token at rest or in logs: CHK-M3-206 PASS.
- The fixtures pass through the route and the document holds the enrol operation: CHK-M3-208, -304-067 PASS.

## Carry-overs
- Windows built once in `create_app()`, and the commit-only "fired" rule for the `agent_auth_failures` and enrolment windows: CHK-M3-160-067 and CHK-M3-205 PASS.
- The agent route walk (CHK-M3-169-067) and the 401/403 matrix (CHK-M3-160-067) were re-run: PASS, except the new scoped case.
- G25 re-run: CHK-M3-313-067 PASS.

## For TASK-072 TEST
- `test_body_caps.py::test_other_agent_routes_keep_one_mib` is shadowed by the real heartbeat route.
