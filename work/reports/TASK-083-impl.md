# TASK-083 IMPL: token before body on the heartbeat; agent path/query UUID form; case-insensitive content coding

The scope is the TASK-083 row plus three later decisions, all from 2026-10-23 in `work/decisions.md`: the user follow-up order, the lead ruling "Agent path and query UUIDs: hyphenated form only; content coding case-insensitive", and the lead's confirmation of how the `{id}` form is placed. It implements TS §6.3 L1136 (failed token checks on any route), TS §6.1 and W1 ruling (3) (hyphenated UUIDs on input), and RFC 9110 §8.4.1.

## What changed

1. **Token before body on `POST /api/v1/agent/{id}/heartbeat`.** This is the only `bsa_` route that declares a FastAPI JSON body.
   - **Route class:** the heartbeat router now uses `limit_first(token_first)`, the TASK-082 route class.
   - **Async checks:** `limit_first` now accepts a check that returns an awaitable, and awaits it. The sync per-IP checks are unchanged.
   - **`token_first(request)`** is new, in `api/agent/dependencies.py`. It runs the whole `authenticate_agent` in the threadpool before FastAPI reads the body: token, machine-id, `{id}`, the 30/min limit and the IP record.
   - **Single run:** `authenticate_agent` stores its result in `request.scope["bitscan.agent"]`. The route's own `current_agent` dependency then reuses it, so the check, the per-agent count and the IP record each happen once.
   - **Result:** a bad or missing token gets 401 and is counted whatever the body (the 21st from one IP in a minute gets 429). A valid token with a non-JSON or invalid body still gets 400.
   - **Other routes:** results, inventory and rotate already read their body after the token check, so they are unchanged.
2. **One shared validator for path and query ids:** `agent_uuid(value, where)` in `dependencies.py`.
   - It uses RE2 with the contract's `UUID_PATTERN`, the 8-4-4-4-12 hex form in either case. Anything else gets 400 `invalid_request` with `Invalid request: <where>`.
   - `{job_id}` on results (`path.job_id`) and `?job_id` on inventory (`query.job_id`) now use it instead of `uuid.UUID(...)`. The 32-hex, `{…}` and `urn:uuid:` forms are now 400, where they used to be accepted.
   - `{id}`: inside `authenticate_agent`, after a valid token, a non-8-4-4-4-12 `{id}` gets 400 `invalid_request` (`Invalid request: path.id`). A well-formed id of another agent still gets 403 `forbidden`. Both are uncounted and come before the 30/min limit, where the 403 already was.
3. **Content coding is case-insensitive:** `content_coding(request)` returns the lowercased `Content-Encoding`.
   - Inventory requires `gzip` in any case.
   - Results accept `gzip` or `identity` in any case, or no header.
4. **`Count64` comment** in `api/agent/schemas.py` now states its bound (2^53 − 1, not 2^63 − 1). This is a comment only.

## Files

- `manager/bitscan_manager/api/agent/heartbeat.py` (route class)
- `manager/bitscan_manager/api/attempt_limits.py` (awaitable checks)
- `manager/bitscan_manager/api/agent/schemas.py` (the `Count64` comment only)
- Shared files: `manager/bitscan_manager/api/agent/dependencies.py` (`token_first`, `agent_uuid`, `content_coding`, the `{id}` form check, the per-request result)
- Shared files: `manager/bitscan_manager/api/agent/jobs.py` (results `{job_id}` and the encoding)
- Shared files: `manager/bitscan_manager/api/agent/inventory.py` (`?job_id` and the encoding)
- `manager/openapi.json` was re-exported and is byte-identical: no OpenAPI change, and no 422.

That is 6 source files, about 60 changed lines. The row planned 4 files; the lead's ruling added `dependencies.py`, `jobs.py` and `inventory.py`.

## How to run

```sh
manager/.venv/Scripts/ruff check manager && manager/.venv/Scripts/ruff format --check manager
manager/.venv/Scripts/mypy --strict --config-file manager/pyproject.toml manager
cd manager && .venv/Scripts/python -m bitscan_manager.app openapi.json   # git diff shows no change
cd manager && .venv/Scripts/python -m pytest -q
```

Local results:
- ruff, format and mypy are green;
- the OpenAPI export is byte-stable and unchanged;
- full pytest: 2192 passed, 0 failed, 1178 skipped (no Docker on Windows, so every `pg` test skipped).

**Not run:** the PostgreSQL suites. My attempt to sync the tree into WSL to run them was refused by the permission system, so the tester's WSL run is the first PG run of this change.

A local probe with no database checked the ordering. With no runtime on the app, a non-JSON, truncated or invalid heartbeat body with `Bearer x` gets the token step's 503 problem+json, not FastAPI's body 400, so the token step runs before parsing. The same probe checked `agent_uuid` (both cases accepted; 32-hex, braces, `urn:uuid:`, garbage and a trailing newline refused) and `content_coding` (`GZIP` becomes `gzip`).

## Tests the tester must update (expected red until updated)

- `tests/test_attempt_limits_pg.py::test_only_the_two_routes_use_the_limit_first_route_class` (CHK-M3-383) expects exactly enrol and login. The heartbeat is now a third `limit_first` route, which is what TASK-083 asks for.
- `tests/test_agent_auth_pg.py` around L390 (CHK-M3-162): `path_id="not-a-uuid"` moves from 403 `forbidden` to 400 `invalid_request` (lead confirmation). It is still not counted, and still comes before the 30/min limit.
- Anything that expects the 32-hex, `{…}` or `urn:uuid:` forms of `{id}`, `{job_id}` or `?job_id` to be accepted (or, for `{id}`, to be 403) now gets 400. tester-e's TASK-073 note found them giving 409.

## Re-run

TP-M3-37, plus the heartbeat, agent-auth, jobs/results (TASK-073, 074), inventory (TASK-060, 076) and attempt-limit (TASK-082) suites, because `dependencies.py`, `jobs.py` and `inventory.py` are shared.
