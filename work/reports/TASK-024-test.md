# TASK-024 TEST report: `create_app()` hardening

Verdict: **PASS**. Tester, 2026-10-21. REQ-035, REQ-036, REQ-037. Impl report: `work/reports/TASK-024-impl.md`.

## Commands run (all L)
- `cd manager && .venv/Scripts/python.exe -m pytest tests/test_app_hardening.py tests/test_app.py tests/test_openapi.py`
- Planted violations: a throwaway harness copies `manager/` to `%TEMP%\m2-mut-<name>`, applies one edit to `bitscan_manager/app.py`, runs the tests against the copy (`PYTHONPATH` checked), then deletes it. 11 mutations plus a control.
- `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager`, the full suite, OpenAPI export plus `cmp`.

## Counts
- New `manager/tests/test_app_hardening.py`: 53 tests, all pass. Full L suite: 423 passed, 181 skipped (pg).
- Mutations: 11/11 red, control green (telemetry removed, auto_configure on, headers inside the error middleware, handler headers kept, cap on Content-Length only, decimal MB, off by one, CORS added, docs served, registry unchecked).

## Criteria
| Criterion | Result | Rows |
| --- | --- | --- |
| REQ-035 (1), (2) telemetry off with and without OTel env | PASS | CHK-M2-010, -011 |
| REQ-035 (3) docs routes 404 | PASS | CHK-M2-012 |
| REQ-035 (4), REQ-036 (4) no CORS | PASS | CHK-M2-013 |
| REQ-035 (5) `/api/v1` paths | not applicable until TASK-038 (no routes yet) | CHK-M2-182 |
| REQ-036 (1)–(3) four headers once on every status, handler values replaced | PASS | CHK-M2-014, -015 |
| REQ-037 (1)–(4) cap, Content-Length, chunked, 413 problem body | PASS | CHK-M2-016 to -019 |
| REQ-037 (5) cap registry | PASS | CHK-M2-020 |

Rows are in [tests/m2/report.md](../../tests/m2/report.md).

## Notes
- REQ-037 (2), (3) "at most cap + 1 bytes are read": in ASGI the server chooses the chunk size. The tests assert that no `receive()` happens after the chunk that crosses the cap, and that with one-byte chunks exactly cap + 1 bytes are pulled. This proves the limit at the granularity the app controls.
- With no OpenTelemetry SDK installed, egress cannot be shown directly. FastAPI swallows a failed auto-configure with a warning, so the test captures that warning, and it also asserts FastAPI's five settings. Removing `telemetry=` turns both red.
- The 413 `type` is `too_large`; #48 names no user-route value for 413. TASK-026 owns problem details.
