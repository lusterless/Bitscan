# TASK-026 IMPL report: problem details and cursor pagination

REQ: REQ-038. Spec: TS §6.3 (problem details, pagination with limit at most 500), TS §7.1 L1212 (400 for bad query parameters), L1215 (`{items, next_cursor}`); #47 (d), #48, #52; lead ruling 2026-10-21 (413 type `too_large`); reviewer carry-over (`route_caps` default).

## Files (4)

- `manager/bitscan_manager/api/__init__.py`: new, an empty package marker.
- `manager/bitscan_manager/api/problems.py`: new, 91 non-blank lines.
- `manager/bitscan_manager/api/pagination.py`: new, 68 non-blank lines.
- `manager/bitscan_manager/app.py`: `create_app()` calls `problems.install(app)`. `BodyLimit` now builds its 413 body with `problem_body()`. `BitscanApp.route_caps` defaults to an empty read-only mapping (reviewer carry-over).

## Problem `type` values (#48, with the lead's 413 ruling)

| Status | `type` | Source |
| --- | --- | --- |
| 400 | `invalid_request` | #48: every validation error, a bad `limit`, a bad cursor |
| 401 | `unauthorized` | #48 |
| 403 | `forbidden` by default; routes raise `Problem(403, "session_required" \| "totp_session_required" \| "totp_enrolment_required", …)` | #48 |
| 404 | `not_found` | #48. Also used for unknown paths: one value for one condition, as in the 413 ruling |
| 409 | `conflict` | #48 |
| 413 | `too_large` | lead ruling 2026-10-21; same value as the TS §6.5 agent routes |
| 429 | `rate_limited` | #48 |
| 503 | `audit_sink_unavailable` (raised explicitly by TASK-037) | #48 |
| 405, 500, a 503 without a type (for example `get_runtime` with no runtime) | `about:blank` | **No #48 value exists.** RFC 9457 §4.2.1 says `about:blank` is the type when no specific type applies, so no new value is invented. Lead: say if you want named values instead |

`title` is the HTTP reason phrase of the status. On Python 3.12, 413 gives `Request Entity Too Large`, which replaces TASK-024's hand-written `Payload Too Large`. `instance` is `request.url.path`, which has no query string.

## `api/problems.py`

- `Problem(status, type_=None, detail=None, headers=None)` is an exception that routes and dependencies raise. `type_` defaults to the table above, else `about:blank`, and `detail` defaults to the reason phrase. `headers` carries, for example, `Retry-After` for 429.
- `problem_body(status, type_, detail, instance) -> bytes` and `problem_response(request, problem, headers)` build responses whose body has exactly `type, title, status, detail, instance`. The content type is `application/problem+json`.
- `install(app)` registers four handlers:
  - `Problem`;
  - Starlette `HTTPException`: 404, 405 with its `Allow` header kept, and any `HTTPException` our code raises. Its `detail` is used only when it is a string;
  - `RequestValidationError`: 400 `invalid_request`. The detail is `Invalid request: <field>, …`: the sorted, de-duplicated `loc` paths, each at most 64 characters, at most 10 of them. It never includes the value, the validator message or the input;
  - `Exception`: 500 `about:blank` with the fixed text `An unexpected error occurred.`. No exception text or stack trace is included. Because `BitscanApp` wraps `ServerErrorMiddleware`, the security headers are still added.

## `api/pagination.py`

- `DEFAULT_LIMIT = 50`, `MAX_LIMIT = 500`.
- `page_params` is a FastAPI dependency with `limit: int` (Query, 1–500, default 50) and `cursor: str | None` (at most 512 characters). It returns `PageParams(limit, cursor)`. 0, 501, negative or non-integer limits are validation errors and get 400 `invalid_request`, detail `Invalid request: query.limit`.
- `encode_cursor(scope, key)`: the cursor is base64url, unpadded, of 16 bytes of HMAC-SHA256 followed by the JSON `[scope, key]`. The HMAC key is 32 random bytes per process. `key` is the sort key of the last item: an int (#52 BIGSERIAL ids), a str, or a list of them.
- `decode_cursor(scope, cursor)` returns the key, or raises `Problem(400, "invalid_request", "Invalid request: query.cursor")` in three cases:
  - the string is not exactly what `encode_cursor` would produce. This also catches stray characters and changed padding bits, which the base64 decoder would otherwise ignore;
  - the MAC is wrong (compared with `hmac.compare_digest`);
  - the scope is another list's.

  Cursors stop working when the manager restarts; a client then starts the list again.
- The key is `secrets.token_bytes(32)`, created once per process when `bitscan_manager.api.pagination` is first imported. `create_app()` triggers that import through the routes. The key is never logged or returned, and it appears in no `repr`. The MAC is compared with `hmac.compare_digest`. The lead's ruling (decisions.md 2026-10-21, "Lead rulings on TASK-026") confirms `about:blank`, HMAC cursors and the restart behaviour.
- Lists return `Page[T]`, a generic Pydantic model with exactly `items` and `next_cursor`.
- `page_of(rows, limit, scope, key)` takes `limit + 1` rows from the query. It returns `limit` items and a `next_cursor` only if the extra row exists, so the last page has `next_cursor: null`.
- This is not cryptographic signing of `.bit` files or jobs (the owner decision). The MAC only lets the manager recognise its own opaque cursors.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 62 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 552 passed, 228 skipped (pg), 97.63 %. `test_app_hardening.py` still passes (it checks the key set, not the title) |
| OpenAPI re-export, `git diff --exit-code -- manager/openapi.json` | no diff |
| Scratch script with test routes (deleted afterwards). The canary was planted in the query, in the body values and in the exception text | Each of these returned `application/problem+json` with exactly the five keys, in order, and no canary in the response: a validation error (`body.n`), malformed JSON (`body.1`), an unknown path (404 `not_found`), a wrong method (405 `about:blank`, `Allow: GET`), an unhandled `RuntimeError` (500), a raised `Problem` (403 `totp_session_required`) and a 1 MiB + 1 body (413 `too_large`). `limit` 0, 501, `x` and -1 each gave 400. Paging 11 rows with `limit=5` returned each row once, in order, and then `null`. `limit=11` returned one page with `null` |
| Scratch: cursor tamper sweep. Every position was replaced with 7 characters; also an appended `=`, an appended `!`, an empty cursor, a truncated cursor and another list's scope | all refused |

## For the tester (TP-M2-04)

- The test route pattern is `def r(p: PageParams = Depends(page_params)) -> Page[int]`. Get the key with `decode_cursor("<scope>", p.cursor)`, fetch `limit + 1` rows and return `page_of(rows, p.limit, "<scope>", key_fn)`.
- `Problem` is importable from `bitscan_manager.api.problems` for test routes that need a specific `type`.
- 422 is no longer produced anywhere: validation errors are 400 (#48 / TS §7.1).

## Revision 1 (tester TEST round 1; lead rulings 2026-10-21, "Lead rulings on TASK-026 TEST questions")

1. **The validation `detail` no longer echoes keys the client chose** (REQ-038 (2), (3)). The handler walks each error `loc` against the route's own body type (`APIRoute.body_field`), unwrapping `Annotated` and `Optional`.
   - Kept: declared model field names (by alias) and list or tuple indexes.
   - At the first part that is neither (a dict key, or a key the model does not declare), the path stops and gets a generic reason. A field the model does not declare (`extra_forbidden`) gives `: unknown field`; anything else gives `: invalid key`.
   - Non-body sources (`query`, `path`, `header`, `cookie`) keep only the parameter name, which the route declares.
   - With no route information the path is just `body`.
   - Examples:
     - `{"m": {"CANARYKEY": "x"}}` on `dict[str, int]` gives `body.m: invalid key`;
     - an extra key on an `extra="forbid"` model gives `body: unknown field`;
     - nested `{"xs": [{"n": "x", "K": 2}]}` gives `body.xs.1.n, body.xs.1: unknown field`;
     - a multi-body route gives `body.x: unknown field, body.y`.
2. **New `manager/bitscan_manager/api/timestamps.py`** (the 5th file of this task) defines `UtcDatetime`, the one timestamp type every later route uses:
   - it is `Annotated[datetime, AfterValidator, PlainSerializer, WithJsonSchema]`;
   - validation refuses a naive datetime (400 `body.<field>`) and converts aware values to UTC;
   - serialisation is always `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC, whatever offset the value or the psycopg session carries;
   - the OpenAPI schema is `{"type": "string", "format": "date-time"}`.

Re-checked:
- ruff and mypy `--strict` pass on `bitscan_manager`. Ruff and mypy findings remain in the tester's in-progress `tests/test_tokens.py` (E501, S324) and `tests/test_problems.py` (an unused `type: ignore`); I have reported them to the tester.
- `pytest tests/test_problems.py tests/test_pagination.py tests/test_app_hardening.py tests/test_app.py` gives 137 passed, including both `test_client_chosen_keys_are_not_echoed` cases.
- Scratch check: a `+08:00` value serialises as `…T19:04:05.000000Z` on the previous day, and a naive value in a body gets 400.

## Revision 2 (tester TEST round 2: query, header and cookie parameter models)

**Cause.** Revision 1 assumed the second part of a non-body `loc` is always a parameter the route declares. That is not true with parameter models (`Annotated[M, Query()]`, `Header()`, `Cookie()`, especially `extra="forbid"`). There the second part is the client's own key, and a header model named every header the client sent.

**Fix.** The rule is now the same for every source: a name is kept only if the route declares it. `_declared(route)` collects:
- `body`: the body type;
- `query`, `header`, `cookie`, `path`: the parameters of the route and of all its dependencies, found by walking `route.dependant.dependencies`. A parameter model contributes its fields by alias. Header names are compared in lower case.

`_field` walks every `loc` against those declarations. At the first part that is not declared it stops with `<source>[.<path>]: unknown field` (`extra_forbidden`) or `: invalid key`. Results:
- `GET /q?a=x&KEYX=1` (query model) gives `query.a, query: unknown field`;
- a header model with an extra header gives `header: unknown field`, once;
- declared names are still reported, for example `header.x-token, path.item_id, query.limit` (the latter from the `page_params` dependency).

Only public FastAPI attributes are used: `APIRoute.body_field` and `Dependant.{query,header,cookie,path}_params` and `.dependencies`.

Re-checked:
- ruff and mypy `--strict` pass (71 files);
- `pytest tests/test_problems.py tests/test_pagination.py tests/test_timestamps.py tests/test_app_hardening.py tests/test_app.py`: 154 passed, including `test_client_chosen_parameter_keys_are_not_echoed[query|cookie|header]`.
