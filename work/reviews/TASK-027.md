# TASK-027 REVIEW: JSON logging and access records

Reviewer: reviewer. Date: 2026-10-21. REQ-039. Spec: TS §8.4 L1287 (structured JSON logs with `request_id`, `agent_id`, `job_id`; never stdout, stderr or tokens), TS §5.3 L1052, TS §8.1 L1249, L1255; security invariants "Secrets and output". Inputs: `work/reports/TASK-027-impl.md`; `work/reports/TASK-027-test.md`: PASS, rows CHK-M2-050 to -055 in `tests/m2/report.md`, 11 of 11 mutations red (the request-id reset mutant is caught by a raw-ASGI test), with `manager/tests/test_request_log.py` and the shared `manager/tests/canary.py`.

Files reviewed: `manager/bitscan_manager/api/request_log.py`, and in `manager/bitscan_manager/app.py` the stack order `RequestLog(SecurityHeaders(BodyLimit(stack)))`.

Verdict: APPROVED

TASK-027 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **IDs (REQ-039 (1)).** Every record carries `request_id`, `agent_id` and `job_id` from ContextVars. `request_id` is a fresh uuid4 per HTTP request and is reset in `finally`. Starlette's threadpool copies the context, so records logged in sync handlers carry the request's id. The tester checked distinct ids under concurrency.
- **Access record (REQ-039 (3)).** One record per request, written in `finally`, so 413 and 500 are counted. It holds `method`, `scope["path"]` (never the query string), `status` and `duration_ms`. No header, query or body is read. `RequestLog` is the outermost layer, so it sees the final status.
- **Exceptions (REQ-039 (4)).** The error record holds `exc_type` and the stack frames, passed as `data` rather than `exc_info`, so no handler can render the message or locals. `JsonFormatter` never calls `formatException`; for third-party records with `exc_info` it writes only the type and frames.
- **Secrets (REQ-039 (2)).** `create_app()` does not touch global logging. `configure_logging` called again replaces its own handler. The canary sweep covered `Authorization`, `Cookie`, a custom header, the query string, both kinds of body, the exception text and locals. The tester shows the canary helper can fail.
- **Gates (my run).** ruff, format and `mypy --strict` are clean, `test_request_log.py` passes (15), and the OpenAPI export has no diff.
- **Scope.** 2 files, about 115 lines.

## The two impl choices main asked me to judge

1. **No re-raise once the 500 is sent: accepted.** Re-raising would hand the exception to uvicorn, which logs it with `exc_info` (`uvicorn/protocols/http/h11_impl.py:416`), message included. An exception message can hold a token, a DSN fragment or plugin output, which the security invariants and TS §5.3 L1052 forbid in logs. The cost is that an operator sees only `exc_type`, the frames (file, line, function) and the `request_id`. That is enough to find the failing line, and the request can be correlated through `request_id`. If no response has started, the exception is still re-raised, so the server closes the connection. Spec-wise, there is no lower-risk option.
2. **httpx and httpcore capped at WARNING: accepted.** At INFO, httpx logs the method and full URL of every request (`HTTP Request: POST https://…`), so vault and sink URLs, and any query string, would reach the log. Their WARNING and ERROR records stay on. Those are connection-level failures and carry no request body. A raised `httpx` exception reaches our code as an exception, not a log line; TASK-030 and TASK-032 turn those into errors that name only the type. This is the right default. It is set in `configure_logging`, which `serve` calls, so tests that skip it are unaffected.

## Findings

None block approval.

1. **carry-over to TASK-045 (should be checked there).** uvicorn has its own loggers, and they bypass `RequestLog`. Its access log (`uvicorn.access`) writes `get_path_with_query_string(scope)` (`h11_impl.py:481`), the client address and the status, as text, not JSON. Its default `log_config` installs plain-text handlers that render `exc_info` in full. For REQ-039 (2) and (3) to hold in production, `serve` must run uvicorn with `access_log=False`, and with `log_config=None` (or an equivalent config) so `uvicorn.error` records reach the root JSON handler. TASK-045's tests should show that a query-string canary does not appear on stderr under `serve`. This is also the CHK-M2-056 full-run sweep.
2. **nit.** `request_log.py:54-61`: `stack` holds absolute file paths, which reveal the install path in logs. That is harmless and useful for diagnosis.
3. **note.** The access record logs `scope["path"]` as received. In M3, agent paths carry the agent id and job id. Those are UUIDs, not secrets, so this is fine.
