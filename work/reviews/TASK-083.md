# TASK-083 REVIEW: token before body on the heartbeat; hyphenated agent ids; case-insensitive content coding

Reviewer: reviewer. Date: 2026-10-23. REQ-062, REQ-065, REQ-060. Spec: TS §6.3 L1136 (failed token checks on any route are counted per IP), §6.1 L1069 (`{id}` must match the token's agent, otherwise 403), §6.3 L1139 (UUID strings); W1 ruling (3) (hyphenated RFC 9562 UUIDs on input); RFC 9110 §8.4.1 (content codings are case-insensitive). Decisions (`work/decisions.md`, 2026-10-23):
- the user's follow-up order (from the TASK-072 second approval);
- "Agent path and query UUIDs: hyphenated form only; content coding case-insensitive";
- the lead's placement of the `{id}` form check;
- TASK-083 stays one task at 6 source files.

Inputs:
- `work/reports/TASK-083-impl.md`;
- `work/reports/TASK-083-test.md` (PASS: `manager/tests/test_agent_token_first_pg.py` plus 13 re-run suites; 1258 passed in WSL; 4 of 4 plants red).

Files reviewed:
- `manager/bitscan_manager/api/agent/dependencies.py` (`token_first`, `agent_uuid`, `content_coding`, the `{id}` form check, the per-request result);
- `manager/bitscan_manager/api/attempt_limits.py` (awaitable checks);
- `manager/bitscan_manager/api/agent/heartbeat.py` (route class);
- `manager/bitscan_manager/api/agent/jobs.py` and `inventory.py` (ids and encoding);
- `manager/bitscan_manager/api/agent/schemas.py` (the `Count64` comment);
- the tester-e tests.

Verdict: APPROVED

**Two approvals required** (TS §8.2; agent routes). This is the first one; the user's second approval is still needed.

## What was checked

- **Token before body (the TASK-072 nit 2 follow-up).**
  - The heartbeat router uses `limit_first(token_first)`. `token_first` runs the whole `authenticate_agent` (token, machine-id, `{id}`, the 30/min limit, IP record) in the threadpool, before FastAPI parses the body.
  - `limit_first` now awaits an awaitable check. The sync per-IP checks of TASK-082 are unchanged.
  - The result is stored in `request.scope["bitscan.agent"]`, and the route's own `current_agent` reuses it. So the token check, the per-agent count, the failed-check count and the IP record each happen **once** per request (tested).
  - A bad or missing token with any body, non-JSON included, is 401 and counted, and the 21st failure from one IP in a minute is 429. A valid token with a bad body still gets 400.
  - Results, inventory and rotate already read their body after the token check, so they are unchanged.
  - The route-walk marker `bsa_` stays on `current_agent`.
- **Hyphenated ids (ruling).**
  - `agent_uuid()` uses RE2 with the contract's `UUID_PATTERN` (8-4-4-4-12 hex, either case) for `{job_id}` on results and `?job_id` on inventory. The 32-hex, `{…}` and `urn:uuid:` forms and garbage get 400 `invalid_request`, naming only the parameter, never echoing the value.
  - For `{id}`, the token is checked first, so a bad token is always 401 and counted. After a valid token, a malformed `{id}` gets 400 and a well-formed foreign one gets 403 `forbidden`. Both are uncounted and come before the 30/min limit, as ruled.
- **Content coding.** `content_coding()` lowercases `Content-Encoding`, so inventory accepts `gzip` in any case, and results accept `gzip` or `identity` in any case, or no header.
- **Scope.** 6 source files, about 60 changed lines (lead ruling). The `Count64` change is the TASK-048 r2 naming nit, done as a comment.
- **OpenAPI (G6).** My re-export is byte-identical, and there is no document change.
- **Security invariants.** No path skips the token check. A route that declares a JSON body can no longer answer before authentication. No new header, setting or command path.
- **Tests (my run, Windows).** `test_agent_token_first_pg.py`, `test_heartbeat_api_pg.py`, `test_agent_auth_pg.py`, `test_jobs_api_pg.py`, `test_inventory_api_pg.py`, `test_attempt_limits_pg.py`, `test_rotation_api_pg.py`, `test_contract_agent.py` and `test_openapi.py`: 575 passed, 441 skipped (PostgreSQL; run in WSL by tester-e, 1258 passed). ruff and format are clean, and `mypy --strict` is clean on the whole tree (209 files).

## Findings

None.

## Note

The `bitscan.agent` scope key is set only by `authenticate_agent`, from the token it checked. No client input can pre-fill it, because ASGI scope keys are not request-controlled.
