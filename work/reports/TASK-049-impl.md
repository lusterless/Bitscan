# TASK-049 IMPL report: body caps by path template, and the after-auth mode

REQ: REQ-066 (REQ-037 still holds). Spec: TS §6.3 L1138, §6.1 L1072, §3.4 L240 and L244, §8.1 L1250. Plan: `work/plans/TASK-049.md`. A second look is recommended (owner notes).

## Files (1)

- `manager/bitscan_manager/app.py`: 90 lines added, 18 removed. No other file changed. `manager/openapi.json` is unchanged, because no route was added.

## What changed

- **`RouteCap(template, cap_class, limit, after_auth=False)`** is a `NamedTuple`. It has the plan's fields, and it is a NamedTuple rather than a frozen dataclass so that the M2 tests, which set `ROUTE_BODY_CAPS` to plain `(path, class, bytes)` 3-tuples, stay valid. `_route_caps()` normalises every entry with `RouteCap(*entry)`.
- **`ROUTE_BODY_CAPS: list[RouteCap]`** is still empty in W1. The inventory and results routes register their caps in TASK-073 and TASK-074.
- **`_route_caps()`** runs once in `create_app()`. It raises `ValueError` at app creation, as in M2, for:
  - a template registered twice;
  - an unknown class;
  - a limit of 0 or less, or above the class maximum.

  Each template is compiled from Starlette's own `compile_path(template)[0].pattern`, so a cap matches exactly the paths the router matches for that template (`{id}` is `[^/]+`). The pattern is compiled with **RE2**, because the request path is untrusted. No stdlib `re` is used. Caps are tried in registration order, and the first match wins.
- **`BodyLimit`** looks up the cap per request:
  - **No cap or a normal cap:** the M2 behaviour is unchanged. Any digit-valued `Content-Length` above the cap gets 413 at once. Otherwise the body is buffered up to cap + 1 bytes, and the middleware answers 413 `too_large` with `Connection: close`. Paths with no registered cap keep the 1 MiB json cap, so user routes are unchanged (REQ-066 (6)).
  - **After-auth cap:** no 413 from the middleware and no buffering. The middleware sets `scope["bitscan.body_cap"] = BodyCap(limit, content_length)`, where `content_length` is the largest digit-valued `Content-Length` header or `None`. It then calls the app with `receive` wrapped in **`CappedReceive(receive, limit)`**.
- **`CappedReceive`** counts real body bytes, not the header. It raises **`BodyTooLarge`** as soon as the total passes `limit`, and raises again on every later call without pulling more. So the app pulls nothing after the chunk that crosses the cap: with one-byte chunks, exactly limit + 1 bytes are pulled. `http.disconnect` messages pass through unchanged.
- **Public names for TASK-063, 073 and 074:** `RouteCap`, `ROUTE_BODY_CAPS`, `BODY_CAP_SCOPE_KEY`, `BodyCap`, `BodyTooLarge`, `CappedReceive`.

## Local gates (Windows)

- `ruff check manager`: pass.
- `ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: pass (123 files).
- `cd manager && .venv/Scripts/python -m pytest -q`: 1033 passed, 451 skipped (the PostgreSQL tests; Docker unavailable on Windows). This includes every M2 `test_app_hardening.py` body-cap test, unchanged.
- OpenAPI re-export: byte-identical to `manager/openapi.json`.
- Scratch probe outside the tree, with test routes at the two templates (inventory 10 MiB after-auth, results 1.5 MiB normal) and random UUIDs:

  | Request | Result |
  | --- | --- |
  | inventory, exactly 10 MiB | reached the handler whole |
  | inventory, 10 MiB + 1 with `Content-Length` | the handler saw `content_length` > `limit` |
  | inventory, chunked over the cap | `BodyTooLarge` |
  | inventory, over the cap with a failed "auth" | answered without reading the body |
  | results, 1.5 MiB | 200 |
  | results, 1.5 MiB + 1 | 413 `too_large` |
  | heartbeat path, 1 MiB + 1 | 413 |
  | results path with a trailing `/` | the 1 MiB default (exact-template match only) |

  Registry: an inventory cap of 10 MiB + 1 raised, a duplicate template raised, and a legacy 3-tuple was accepted.

## For the tester

- Register test caps with, for example, `monkeypatch.setattr(app_module, "ROUTE_BODY_CAPS", [RouteCap("/api/v1/agent/{id}/inventory", "inventory", 10 * MIB, True)])`. A 3-tuple still works for normal mode.
- In after-auth mode the middleware never answers 413 itself. A test route has to read `request.scope[BODY_CAP_SCOPE_KEY]` and `request.stream()` (catching `BodyTooLarge`) to show the cap. The real reader is `bodies.read_capped` in TASK-063.
- "At most cap + 1 bytes" is measured like M2 CHK-M2-017: no receive call after the chunk that crosses the cap. A single large chunk that the server already holds cannot be split.

## For TASK-063 (`bodies.read_capped`)

- Fail closed if `scope[BODY_CAP_SCOPE_KEY]` is missing on an after-auth route. This can happen when the router matches a path that the RE2 pattern does not: Python `re` lets `$` match before a trailing newline, and a path decoded from `%0A` ends in one, while RE2 `$` does not match there. Such a request falls back to the normal 1 MiB buffered cap, so nothing over 1 MiB is read, but it carries no `BodyCap`.
- Give the after-auth 413 `Connection: close`, as the middleware's own 413 does.

## Deviations

None. The plan's `@dataclass(frozen=True)` sketch is a `NamedTuple` with the same fields, for compatibility with the existing tests.
