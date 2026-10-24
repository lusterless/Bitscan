# TASK-063 IMPL report: agent router and `bsa_` dependency

REQ: REQ-062, REQ-064, REQ-065, REQ-066, REQ-087. Spec: TS §6 L1056, §6.1 L1069–L1070, §6.3 L1136 and L1138, §8.4 L1287; #25 (b), #55 (d), #59, #63, #65 (d). Plan: `work/plans/TASK-059.md` (dependency paragraph) and `TASK-049.md` (after-auth reader). It depends on TASK-048, 049, 057 and 059, all approved. **Two approvals** (TS §8.2). All reviewer carry-overs are applied.

## Files (4)

- `manager/bitscan_manager/api/agent/dependencies.py`: new, 168 lines.
- `manager/bitscan_manager/api/agent/bodies.py`: new, 40 lines.
- `manager/bitscan_manager/api/agent/__init__.py`: adds `build_agent_router()`.
- `manager/bitscan_manager/app.py`: one import and one `include_router` line. The rest of its diff is TASK-049.
- `manager/openapi.json`: **unchanged**. The router has no operations yet; TASK-067 and 072 to 075 add them, and a re-export is byte-identical.

## The dependency (`current_agent`, used as `Depends(current_agent)` on every `bsa_` route)

`authenticate_agent(request, id: str, runtime)` is **sync**: FastAPI runs it in the threadpool, alongside its database calls. In order:

1. **Inputs.** `Authorization` must be exactly one header of the form `Bearer <token>`; anything else counts as no token. `X-Bitscan-Machine-Id` must be exactly one header; a missing or repeated one counts as missing (#63). The source IP is the TCP peer (#55 (d)), with IPv4-mapped IPv6 normalised to IPv4. A peer that is not an IP address (TestClient's `testclient`) gets `source_ip = None` and is not recorded.
2. **Token check: one transaction.** TASK-059 `check_agent_token(AgentRepo, EnrolmentRepo, TxAudit, …)` runs inside it. **`AgentTokenRefused` is caught inside the `with`**, so any revoke and alert it wrote commit (reviewer carry-over).
   - **Every 401:** the M2 pattern applies: `failed_check_blocked(ip)`, then `record_failed_check(ip)`, then 429 `rate_limited` with `Retry-After` if the IP was already over 20 per minute, else 401 with the #59 type. Failed agent checks therefore feed the same per-IP limit and aggregated entry as user routes.
   - **Per-agent 401 window, #65 (d):** when the token resolved to an agent, `SlidingCount(1 min, 1 h, > 20)` is fed. When it fires, one `agent_auth_failures` alert entry is written in the same transaction (action `alert.agent_auth_failures`, actor and target `agent:<id>`). The window is built once per app, on first use, in `app.state`.
   - **403 `pending_approval`** is answered without counting.
3. Accepted token, in this order:
   - **`{id}`:** `id.lower() == str(agent_id)`, else 403 `forbidden`, not counted. `{id}` is taken as a plain `str` and checked only after the token, so a malformed id cannot get a 400 before authentication. A non-UUID id is simply never equal.
   - **Rate limit:** then `limits.allow_agent(agent_id)`, 30 per minute, else 429 `rate_limited` with `Retry-After`.
   - **IP recording (#25 (b)):** then `ip_last_seen` is read first and `record_ip` called, all before commit.
4. It returns `AuthenticatedAgent(caller, source_ip, ip_last_seen)`; `ip_last_seen` is for the rotation's 7-day rule (TASK-075).

`current_agent` is the **async** wrapper. It sets `agent_id_var` in the request task's context, so records written by the route (which FastAPI copies into its thread) and the access record both carry the `agent_id` (REQ-087 (1)). It carries the marker `current_agent.bitscan_agent_auth = "bsa_"`, so a route walk can see it (CHK-M3-169). The agent router never uses a user dependency.

A database outage raises `DatabaseUnavailable` from the transaction. That is the existing 503 `about:blank` handler, and it is not counted. Nothing logs a header or a token.

## The capped reader (`bodies.read_capped`, for the inventory and results routes)

- If the scope has no `BodyCap`, it reads nothing and raises `TooLarge` (fail closed). One case is a path that Starlette matches but RE2 does not, such as a trailing newline (`%0A`). Probe: 413.
- A `Content-Length` over the limit raises `TooLarge` unread.
- A stream is read through `request.stream()`, and `BodyTooLarge` from `CappedReceive` becomes `TooLarge`.
- `TooLarge` is a `Problem` subclass: 413 `too_large`, with `Connection: close`. Routes may catch it to audit and fail the job before answering (TASK-074).
- After-auth routes must declare **no** body parameter (reviewer carry-over), because FastAPI reads declared bodies before solving dependencies.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (156 files).
- `pytest -q`: 2003 passed, 704 skipped, 0 failed.
- OpenAPI export: byte-identical.
- **Scratch probe**: `create_app()` with a fake database, fake repositories and a fake token check, but the real `RateLimiter`, `BodyLimit` and JSON logging. Test routes `POST /api/v1/agent/{id}/probe`, and an after-auth `PUT …/inventory` with a 100-byte cap. Results:

  | Case | Result |
  | --- | --- |
  | valid token | 200; IP `::ffff:10.0.0.7` recorded as `10.0.0.7` |
  | upper-case `{id}` | 200 |
  | foreign `{id}` | 403 `forbidden` |
  | non-UUID `{id}` | 403 `forbidden` |
  | no header | 401 `unauthorized` |
  | `Basic` scheme | 401 `unauthorized` |
  | pending | 403 `pending_approval` |
  | revoked | 401 `token_revoked` |
  | 30th request in a minute | 200 |
  | 31st request in a minute | 429 `rate_limited`, `Retry-After: 55` |
  | next minute | 200 |
  | 20 bad tokens from one IP | 20 × 401 |
  | 21st bad token | 429 |
  | a valid token from that IP | still 200 |
  | 21 × 401 resolving to one agent in a minute | exactly one `agent_auth_failures` alert |
  | 21 more within the hour | no second alert |
  | inventory at the cap | 200 |
  | inventory over the cap, valid token | 413 `too_large`, `Connection: close` |
  | inventory over the cap, bad token | 401 |
  | trailing-newline path | 413, nothing read |

  Logs: the route's own record and its access record carry the `agent_id`. Refused requests carry `agent_id = null`. No token text appeared in any log line.

## For the tester

- To get real IP recording, give `TestClient` a `client=("10.0.0.1", 1234)`. With the default `testclient` peer nothing is recorded, and the failed-check key is `"unknown"`.
- Refused requests have `agent_id = null` in their log records. The context is set only after a successful check.

## Deviations

- The plan sketched `current_agent(...) -> AgentCaller`. It returns `AuthenticatedAgent(caller, source_ip, ip_last_seen)` instead, because rotation needs the IP's previous `last_seen_at` (plan: "returns the IP's previous `last_seen_at` so rotation can check the 7-day rule"). The `caller` field is the planned `AgentCaller`.
- `bodies.py` imports `BodyCap`, `BodyTooLarge` and `BODY_CAP_SCOPE_KEY` from `bitscan_manager.app`. Under `python -m bitscan_manager.app` (the export only) that module is a second copy, but no request is served there.
