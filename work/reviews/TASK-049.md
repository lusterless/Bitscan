# TASK-049 REVIEW: body caps by path template, and the after-auth mode

Reviewer: reviewer. Date: 2026-10-23. REQ-066 (REQ-037 still holds). Spec: TS §6.3 L1138 (size limits, 413), §6.1 L1072 (the manager re-checks every cap), §3.4 L240 and L244 (a refused upload is audit-logged and fails its job), §8.1 L1250 (hard caps); #57 (b) (MiB). Plan: `work/plans/TASK-049.md`. Inputs:
- `work/reports/TASK-049-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-030 to -035, rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/app.py` (the only impl file; about 90 added, 18 removed);
- the tester's `manager/tests/test_body_caps.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list; the M3 owner notes recommend a second look (the caps guard every agent route).

## What was checked

- **Spec conformance.** Class maxima are unchanged (json 1 MiB, result_batch 1.5 MiB, bit 5 MiB, inventory 10 MiB). A concrete path is matched against Starlette's own `compile_path` pattern, so the cap applies to exactly the paths the router sends to that template. Normal mode keeps the M2 behaviour (Content-Length pre-check, buffered read to cap + 1, 413 `too_large` with `Connection: close`). After-auth mode never answers 413 from the middleware and never buffers. It hands the route `BodyCap(limit, largest Content-Length)` and a `CappedReceive` that raises `BodyTooLarge` after the chunk that crosses the cap, and on every later call without pulling more. So REQ-066 (2) holds whichever reader the route uses. Unregistered paths, user routes included, keep 1 MiB (REQ-066 (6)). A duplicate template, an unknown class, or a limit of 0 or above the class maximum raise at app creation (REQ-066 (5)).
- **Security invariants.** The untrusted request path is matched with RE2 (`re2.compile` on the Starlette pattern); there is no stdlib `re`. In RE2, `$` does not match before a trailing newline the way Python's `$` does. So a path decoded from `%0A` reaches the router's template but not the cap, and falls back to the 1 MiB buffered cap. That is the safe direction, and the tester covers it (`trailing-newline` in CHK-M3-035). Nothing is logged, and no route or setting was added.
- **Scope.** One file, matches the task row. `manager/openapi.json` is unchanged (no route), and I confirmed the export is byte-identical. The plan sketched a frozen dataclass; the code uses a `NamedTuple` with the same fields so the M2 3-tuple test fixtures keep working. Accepted.
- **Tests (my run, Windows).** `tests/test_body_caps.py tests/test_tokens.py tests/test_app_hardening.py tests/test_app.py tests/test_auth_dependencies.py`: 206 passed, 27 skipped (PostgreSQL). `ruff check`, `ruff format --check` and `mypy --strict` are clean on the changed files. The tests count pulled bytes with a raw ASGI `receive` and pin `feed.pulled == cap + 1`. They also prove that a failing dependency runs before any byte is pulled (`feed.pulled == 0`), cover look-alike paths, and check the registry refusals. These assertions would fail under the plants CHK-M3-360 (exact-path lookup gives 413 on a 2 MiB inventory) and CHK-M3-361 (the middleware answering 413 in after-auth mode).

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/app.py:122`. The duplicate check compares template strings. `/api/v1/agent/{id}/inventory` and `/api/v1/agent/{agent_id}/inventory` would both register, and the second would be silently unreachable because the first match wins. Fix (optional): de-duplicate on the template with its parameter names normalised, for example `compile_path(t)[1]` with each `{name}` replaced by `{}`.
2. **nit**, `manager/bitscan_manager/app.py:51,121`. `ROUTE_BODY_CAPS` is typed `list[RouteCap]`, but `RouteCap(*entry)` also takes legacy 3-tuples. That works only because `RouteCap` is a `NamedTuple`. It is a test-compatibility shim. Remove it if the M2 tests are ever moved to `RouteCap`.

## Carry-overs (for the consuming tasks, not findings here)

- **TASK-063 (`bodies.read_capped`):**
  - Fail closed when `scope[BODY_CAP_SCOPE_KEY]` is missing on an after-auth route (the newline case above).
  - Catch `BodyTooLarge` and answer 413 `too_large` with `Connection: close`. Uncaught, it becomes a 500 through the error middleware.
- **TASK-063, TASK-073, TASK-074.** The after-auth routes must not declare a FastAPI body parameter. FastAPI reads declared bodies before it solves dependencies, which would read the body before the token check (REQ-066 (3)). The route TEST should repeat the CHK-M3-032 "0 bytes pulled before a 401" check on the real routes.
