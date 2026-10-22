# TASK-027 IMPL report: JSON logging and access records

REQ: REQ-039. Spec: TS §8.4 L1287 (structured JSON logs with `request_id`, `agent_id`, `job_id`; never stdout, stderr or tokens), TS §5.3 L1052, TS §8.1 L1249/L1255; security invariants "Secrets and output".

## Files (2)

- `manager/bitscan_manager/api/request_log.py`: new, 110 non-blank lines.
- `manager/bitscan_manager/app.py`: `BitscanApp.build_middleware_stack()` now returns `RequestLog(SecurityHeaders(BodyLimit(stack)))`, so the access record sees every final status, including 413 and the error middleware's 500.

## Behaviour

- **IDs on every record.** `request_id_var`, `agent_id_var` and `job_id_var` are `ContextVar[str | None]`, default `None`. `agent_id` and `job_id` stay null in M2; the M3 agent routes set them. `RequestLog` sets a new `uuid4` string per HTTP request and resets it when the request ends. ContextVars follow the request into sync handlers (Starlette's threadpool copies the context), so records logged inside a handler carry the same `request_id`.
- **`JsonFormatter`** writes one JSON object per record:
  - always `time` (RFC 3339 UTC, ms), `level`, `logger`, `message` (`record.getMessage()`), `request_id`, `agent_id` and `job_id`. A record logged outside a request has null ids;
  - any fields the caller passes in `extra={"data": {...}}`, which never override the base keys;
  - for third-party records with `exc_info`, only `exc_type` and `stack` (a list of `file:line function`). The formatter never calls `formatException`, so no exception message, local or traceback text is written.
- **`configure_logging(stream=None, level=INFO)`** installs one JSON handler on the root logger (stderr by default). Calling it again replaces that handler, so tests can point it at a `StringIO`. It also sets the `httpx` and `httpcore` loggers to at least WARNING, because httpx logs every request URL at INFO: the vault and sink calls in the manager, and query strings in test clients. `serve` (TASK-045) will call it. `create_app()` does not touch global logging.
- **Access record.** Logger `bitscan_manager.access`, message `request`. Data: `method`, `path` (`scope["path"]`, never the query string), `status` and `duration_ms`. It is written in `finally`, so every request gets one. No header, query string or body is ever read for logging.
- **Unhandled exception.** Starlette's error middleware has already answered 500 with the TASK-026 problem body and re-raised. `RequestLog` then logs `bitscan_manager.error` / `unhandled exception` with `exc_type` and `stack` only, passed as data rather than `exc_info`, so no handler (`caplog` included) can render the message. It **does not re-raise**, so uvicorn never logs the message or traceback. If no response had started, it re-raises.

  Consequence for tests: a default `TestClient` (`raise_server_exceptions=True`) now gets the 500 response instead of the exception. No existing test relied on the old behaviour; the full suite is green.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 75 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 767 passed, 229 skipped (pg), 97.73 % |
| OpenAPI re-export, `git diff --exit-code -- manager/openapi.json` | no diff |
| Scratch script (deleted), with `configure_logging(StringIO, DEBUG)` called twice | one handler only. Requests were sent with a canary in `Authorization: Bearer`, `Cookie`, a custom header, the query string and JSON and raw bodies: no canary in any line. A handler raised `RuntimeError("bad <canary>")` with a canary in a local variable: one error record with `exc_type: RuntimeError`, the stack frames and the request's `request_id`, and no canary. 200, 404, 413 and 500 each gave one access record with method, path (no query), status and duration. Over 24 requests (20 of them concurrent) there were 24 distinct `request_id`s. Each handler log line shared its `request_id` with its own access record. The start-up record parsed with null ids |

## For the tester (TP-M2-05)

- Capture logs with `configure_logging(stream)` (the handler the app installs). Records logged through `caplog` also hold no exception text, because the error record carries no `exc_info`.
- `RequestLog` is part of every `create_app()` app; no extra set-up is needed.
- For CHK-M2-052, add a route that raises. Use either `TestClient` mode: the exception no longer propagates once the 500 is sent.
