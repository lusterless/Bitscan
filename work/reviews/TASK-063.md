# TASK-063 REVIEW: agent router and `bsa_` dependency

Reviewer: reviewer. Date: 2026-10-23. REQ-062, REQ-064, REQ-065, REQ-066, REQ-087. Spec: TS §6 L1056 (separate router per route group, own token check), §6.1 L1069–L1070 (`{id}` match, else 403; `pending_approval` on every route), §6.3 L1136 (30 per minute per agent; 20 failed checks per minute per IP; valid tokens never throttled), L1138 (size limits), §8.4 L1287 (logs carry `agent_id`, never tokens); #25 (b) (every authenticated call records the IP), #55 (d) (TCP peer), #59, #63, #65 (d) (more than 20 401s a minute for one agent, one alert an hour); decisions 2026-10-21 (correction to the M2 answers (3): every token is checked first; an invalid token from a limited IP gets 429 and still counts). Plans: `work/plans/TASK-059.md` (dependency paragraph), `TASK-049.md` (after-auth reader). Inputs:
- `work/reports/TASK-063-impl.md`;
- `work/reports/TASK-063-test.md` (PASS: CHK-M3-160 to -169, `manager/tests/test_agent_auth_pg.py`, 21 PostgreSQL tests in WSL, 62 with G25; 14 of 14 plants red, CHK-M3-323 red against G25).

Files reviewed:
- `manager/bitscan_manager/api/agent/dependencies.py` (new, 168 lines);
- `manager/bitscan_manager/api/agent/bodies.py` (new, 40 lines);
- `manager/bitscan_manager/api/agent/__init__.py` (`build_agent_router`);
- `manager/bitscan_manager/app.py` (one import and one `include_router` line);
- the tester's test file.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent routes). This is the first one; the user's second approval is still needed.

## What was checked

- **Route groups (REQ-062, security invariants "Authorisation").**
  - The agent router is its own `APIRouter` under `/api/v1/agent` and never uses a user dependency.
  - `current_agent` accepts only a well-formed `bsa_`, through TASK-059's `is_agent_token(raw, AGENT)`. So `bsu_`, `bsk_`, `bse_`, other schemes, a repeated `Authorization` header and malformed values all get one 401 `unauthorized` body (#59).
  - The dependency carries a route-walk marker (CHK-M3-169).
  - User routes still refuse real `bsa_` and `bse_` rows (G25 re-run, CHK-M3-323 red).
- **Order and outcomes.**
  - Header and token parsing, then the TASK-059 token check in **one transaction**. `AgentTokenRefused` is caught inside the `with`, so a mismatch revoke and its alert commit before the 401 (the TASK-059 carry-over, tested).
  - Then the `{id}` match: 403 `forbidden`, not counted. `{id}` is compared only after the token, so a malformed id cannot reveal anything before authentication.
  - Then `allow_agent`: 30 per minute, 429 `rate_limited` with `Retry-After`.
  - Then `ip_last_seen` is read before `record_ip`, for TASK-075's 7-day rule.
  - A database outage gives 503 `about:blank` and is not counted.
- **Failed checks (REQ-065 (3), (4)).**
  - Every 401 runs `failed_check_blocked`, then `record_failed_check`, then answers 429 once the IP is over 20, exactly as M2 `current_principal` does, so agent failures feed the same aggregated entry. A valid token from a limited IP still passes (CHK-M3-363 red).
  - A 403 `pending_approval` is never counted.
  - 401s resolving to one agent feed a 1-minute window above 20, which writes one `agent_auth_failures` alert per agent per hour in the same transaction (#65 (d)).
- **Source IP.** The TCP peer only, with no forwarded headers (#55 (d)). An IPv4-mapped peer is normalised to IPv4.
- **Capped reader (REQ-066, TASK-049 carry-overs).** `read_capped` refuses with 413 `too_large` and `Connection: close`:
  - when the scope has no `BodyCap`, reading nothing (fail closed);
  - when `Content-Length` is over the cap, reading nothing;
  - when the stream crosses the cap (`BodyTooLarge`).

  The tester proves 0 bytes are pulled before a 401 on an after-auth route.
- **Logs (REQ-087).** The async wrapper sets `agent_id_var` in the request task, so the route's records and its access record carry the `agent_id`. Refused requests carry none. No token or header reaches any record (canary test).
- **Scope.** Four files, as the task row lists. `manager/openapi.json` is unchanged, because the router has no operations yet. I confirmed the re-export is byte-identical. The return type is `AuthenticatedAgent(caller, source_ip, ip_last_seen)` rather than the plan's `AgentCaller`, because rotation needs the IP's previous `last_seen_at`. Accepted.
- **Tests (my run, Windows).** `test_agent_auth_pg.py`, `test_body_caps.py`, `test_auth_dependencies.py`, `test_security_m2.py` and `test_openapi.py`: 49 passed, 57 skipped (PostgreSQL; run in WSL by the tester). ruff and format are clean, and `mypy --strict` is clean on the whole tree (164 files). Plants red include CHK-M3-320, -321, -338, -362, -363, -364 and -366, plus the refusal raised outside the transaction.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/api/agent/dependencies.py:83-94`. The per-agent failure window is created lazily on `app.state`, and two threadpool requests arriving together can each build one, so one set of counts is lost once. Optional fix: build it in `create_app()` (or `Runtime`) so there is exactly one per process.

## Carry-overs

- **TASK-067, 072 to 075.** Each real route re-runs the CHK-M3-169 route walk and the 401/403 matrix. The after-auth routes (TASK-073 results, TASK-074 inventory) declare no body parameter, register their `RouteCap(..., after_auth=True)`, and re-prove 0 bytes pulled before a 401 on the real route.
- **TASK-074.** Catch `TooLarge` to fail a dispatched job and write the audit entry before re-raising it, in its own transaction (#72).
- **TASK-075.** Use `AuthenticatedAgent.ip_last_seen` (read before this call's `record_ip`) for the 7-day new-IP alert.
