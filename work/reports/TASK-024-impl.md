# TASK-024 IMPL report: `create_app()` hardening

REQ: REQ-035, REQ-036, REQ-037. Spec: TS §6.3 (size limits L1138, headers L1140, no CORS), TS §8.4 (logs and metrics only), TS §8.1; #34 (no docs), #57 (HSTS value, MB = MiB); decisions 2026-10-20 (FastAPI telemetry row); lead ruling 2026-10-21 on the REQ-037 (5) cap registry shape.

## Files (1)

- `manager/bitscan_manager/app.py` (about 150 hand-written lines added).

## What changed

- **Telemetry off.** `create_app()` passes `telemetry=TELEMETRY_OFF` = `{tracing, metrics, logs, operation_spans, auto_configure}` all `False`. FastAPI's explicit `auto_configure=False` overrides `FASTAPI_OTEL_AUTO_CONFIGURE`, and with every signal off `NativeTelemetry.enabled()` is false, so the request path skips FastAPI's telemetry wrapper. Nothing imports `opentelemetry.sdk`.
- **`BitscanApp(FastAPI)`** overrides `build_middleware_stack()` to wrap the whole Starlette stack (including `ServerErrorMiddleware`) as `SecurityHeaders(BodyLimit(stack))`. This is why unhandled-exception 500s also get the headers. `app.user_middleware` stays empty; `isinstance(create_app(), FastAPI)` still holds; still no routes, no docs routes, no CORS middleware.
- **`SecurityHeaders`** (pure ASGI): on `http.response.start` it drops any header named like one of the four (case-insensitive) and any `access-control-allow-*` header, then appends the four TS §6.3 headers once each:
  - `strict-transport-security: max-age=31536000` (#57)
  - `content-security-policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`
  - `x-content-type-options: nosniff`
  - `referrer-policy: no-referrer`
- **`BodyLimit`** (pure ASGI), cap = `ROUTE_BODY_CAPS` entry for the exact path, else 1 MiB (1,048,576 bytes, #57):
  - a decimal `Content-Length` above the cap gets 413 at once; `receive` is never called, so no body byte is read;
  - otherwise the body is read up front, chunk by chunk; as soon as the running total exceeds the cap it answers 413 and stops calling `receive` (chunked bodies with no `Content-Length`, and a lying `Content-Length`). Reading stops at the first chunk that crosses the cap; the ASGI server decides the chunk size, so "cap + 1 bytes" is the logical limit, not a byte-exact read count;
  - a body within the cap is replayed to the app as one `http.request` message; later `receive` calls go to the server (disconnect detection);
  - a client disconnect before the body completes ends the request with no response.
- **413 body**: `application/problem+json`, `{"type": "too_large", "title": "Payload Too Large", "status": 413, "detail": "The request body exceeds the size limit.", "instance": <path without query>}`, plus `connection: close`. `too_large` is the TS §6.5 agent-route value; #48 lists no user-route value for 413. TASK-026 owns problem details and may move this body onto its helper.
- **Cap registry (REQ-037 (5))**, shape agreed with the lead:
  - `BODY_CAP_CLASSES` (fixed): `json` 1 MiB, `result_batch` 1.5 MiB (comment: after decompression, so the M3 route must also apply it to the decoded size), `bit` 5 MiB, `inventory` 10 MiB (the gzip body as sent; the 64 MiB decompressed limit is the M3 decoder's job and is not in the table).
  - `ROUTE_BODY_CAPS: list[tuple[path, class, bytes]] = []` (module level, empty in M2). `create_app()` validates it and raises `ValueError` at app creation for an unknown class, a value `<= 0` or above the class maximum, or the same path registered twice.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 46 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 366 passed, 181 skipped (pg), 98.15 % (M0 `test_app.py` unchanged and green) |
| OpenAPI re-export, `git diff --exit-code -- manager/openapi.json` | no diff |
| Scratch smoke script in a temp folder (deleted, not a test file) with test routes added to a `create_app()` instance | 200, 404, 405, 422, 500 (raised `RuntimeError`) and 413 each carry the four headers exactly once with the exact CSP; a handler's own CSP and `Access-Control-Allow-Origin` are replaced/removed; 1 MiB passes, 1 MiB + 1 gets 413 problem+json; a 17 × 64 KiB generator body (chunked) gets 413 and 16 × 64 KiB passes; `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json` 404; with the four `OTEL_*`/`FASTAPI_OTEL_AUTO_CONFIGURE` variables set and a local listener as the OTLP endpoint, 20 requests made no connection; no `opentelemetry.sdk` module imported; each bad `ROUTE_BODY_CAPS` value raises at `create_app()` |

## For the tester

- REQ-037 (5): monkeypatch `bitscan_manager.app.ROUTE_BODY_CAPS` (a list of `(path, class, bytes)`), then call `create_app()`; expect `ValueError` for class maximum + 1, 0, an unknown class and a duplicate path. A valid entry (for example `("/echo", "bit", 2 * MIB)`) raises the cap for that exact path only.
- To provoke 500 with `TestClient`, use `raise_server_exceptions=False` (Starlette re-raises after sending the 500).
- 413 is sent before the app runs, so a 413 response never reaches a route handler or FastAPI exception handlers.
- The Starlette `httpx` TestClient deprecation warning is the accepted one from decisions 2026-10-20.
