# TASK-024 REVIEW: `create_app()` hardening (telemetry off, headers, body cap)

Reviewer: reviewer. Date: 2026-10-21. REQ-035, REQ-036, REQ-037. Spec: TS §6.3 L1138 (size limits), L1140 (headers, no CORS); TS §8.4 (logs and metrics only); TS §2.3; #34, #57; decisions 2026-10-20 (FastAPI telemetry row) and 2026-10-21 ("M2 test-plan answers"). Inputs: `work/reports/TASK-024-impl.md`; `work/reports/TASK-024-test.md` (PASS, CHK-M2-010 to -021 in `tests/m2/report.md`, `manager/tests/test_app_hardening.py` with 53 tests, 11 of 11 mutations red).

File reviewed: `manager/bitscan_manager/app.py`.

Verdict: APPROVED

TASK-024 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **Telemetry (REQ-035 (1), (2)).** `telemetry=TELEMETRY_OFF` sets all five keys to False. In the installed FastAPI 0.148, `telemetry/_api.py` documents that an explicit `auto_configure` overrides `FASTAPI_OTEL_AUTO_CONFIGURE`. The tester's subprocess probe has a control connection, so a silent listener cannot pass by accident. It also asserts that no SDK or exporter module is loaded and that FastAPI logs no auto-configure warning.
- **Headers (REQ-036).** `SecurityHeaders` wraps the whole Starlette stack, including `ServerErrorMiddleware`, so the 500 path and the 413 from `BodyLimit` carry the headers too. Handler copies of the four headers and every `access-control-allow-*` header are dropped case-insensitively, and the spec values are appended once. The CSP bytes match TS §6.3 L1140. HSTS is `max-age=31536000` (#57).
- **Body cap (REQ-037).** The default is 1 MiB (#57 (b)). A decimal `Content-Length` over the cap gets 413 before any `receive`, and every `Content-Length` header is checked. Otherwise reading stops at the first chunk that crosses the cap; this covers chunked bodies and a lying `Content-Length`. The 413 body has the five problem keys and `instance` is the path without the query. The registry validates class, range and duplicates when the app is created.
- **No docs routes, no CORS.** `openapi_url`, `docs_url` and `redoc_url` are None, and there is no CORS middleware.
- **My own probe** (a scratch script outside the repo). These each carried the four headers exactly once: 200, 404, 405, 500 (raised exception), 413 (`Content-Length` and chunked), the docs paths and a CORS preflight. A handler's own CSP, HSTS and `Access-Control-Allow-Origin` were replaced or removed.
- **Gates (my run).** ruff and format are clean, `mypy --strict` is clean, and `test_app_hardening.py`, `test_app.py` and `test_openapi.py` pass (88). The OpenAPI export has no diff.
- **Scope.** 1 file, about 150 lines.

## Findings

None block approval.

1. **nit, carry-over to M3 (accepted by the lead, decisions 2026-10-21).** `app.py:27`, `:102`: `ROUTE_BODY_CAPS` is keyed by exact `scope["path"]`. Two of the three larger-cap routes have path parameters: `PUT /api/v1/agent/{id}/inventory` and `POST /api/v1/agent/{id}/jobs/{job_id}/results` (TS §6.1). An exact-path registry cannot express them, so M3 must change the lookup. One way is to match registered templates segment by segment, with `{x}` matching one non-empty segment and no regex. The validation part stays as it is.
2. **resolved by lead ruling (decisions 2026-10-21).** `app.py:139`: the 413 `type` is `too_large` on user routes too, the same value as TS §6.5. TASK-026 records it with #48. No change here.
3. **nit.** `app.py:158`: `BitscanApp.route_caps` is set only by `create_app()`, so a `BitscanApp` built directly fails at its first request with `AttributeError`. Either pass the caps through the constructor or default them to `{}`.
4. **note for TASK-045 (accepted by the lead).** Responses that uvicorn writes itself never pass through the ASGI app, for example 400 for a malformed request line, or 503 when `limit_concurrency` is set. They carry none of the four headers. TASK-045 must leave `limit_concurrency` unset.
5. **note, no change.** `BodyLimit` buffers the whole body, up to the cap, before routing. That means at most 1 MiB per request in M2, and 10 MiB on the inventory route in M3.
