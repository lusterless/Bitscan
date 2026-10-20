# TASK-002 REVIEW: manager package skeleton (app factory, CLI stub, services package, OpenAPI export)

Reviewer: reviewer. Date: 2026-10-20. REQ-003 to REQ-008. Spec: TS §2.1 L102, §2.3 L118, §6 L1056, §6.3 L1140 (no CORS, CSP), §8.1, §8.2 L1264, §8.7 L1347/L1359. Inputs: `work/plans/TASK-002.md`, `work/reports/TASK-002-impl.md`, `work/reports/TASK-002-test.md`, `tests/m0/report.md` CHK-M0-020 to -045.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268): this is not importer, auth, agent or runner code.

## What was checked (my own runs, `manager/.venv`, CPython 3.12.10)

- **Scope:** exactly the five listed files.
  - `__init__.py` has `__version__ = "0.1.0"`.
  - `app.py` is 41 lines; `cli/__init__.py` is 16.
  - `services/__init__.py` is empty.
  - `openapi.json` is generated.
  - The plan's interfaces match.
- **REQ-006: no routes, docs or CORS.**
  - `create_app().routes == []`, there is no `APIRoute`, `user_middleware == []`, and two calls return distinct objects.
  - With TestClient, these all return 404: `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`, `/api/v1/openapi.json`, `/api/v1/agent/enroll`, `/` and `/healthz`.
  - An `OPTIONS /api/v1/x` preflight from `Origin: https://evil.example`, and a simple GET with that Origin, return no `Access-Control-*` header.
- **REQ-006 (5) and REQ-008 (2): no environment, network or database access.** I blocked `socket.connect`, `bind`, `connect_ex` and `getaddrinfo` and tracked every `os.environ` read. Then I ran the import, `create_app()`, `openapi_document()` and `cli.main(["serve"])`.
  - No socket call was made.
  - No `BITSCAN_*` variable was read.
  - No `psycopg`, `sqlalchemy` or `asyncpg` module was loaded.
- **REQ-007: deterministic export.**
  - `python -m bitscan_manager.app <tmp>` run twice, with `PYTHONHASHSEED` 1 and 2, gives byte-identical output, and that output equals the committed `manager/openapi.json` (SHA-256 `d1c1b35e…`).
  - The document has `openapi` `3.1.0` and `paths` `{}`. It is LF only, with a single trailing newline, and its keys are sorted.
  - With no argument the export exits 2 with usage on stderr.
  - The `git diff --exit-code` form runs in CI; the file is untracked locally.
- **REQ-008: CLI stub.** The console script `bitscan-manager` returns:
  - `--help`: exit 0, help on stdout, nothing on stderr;
  - no arguments, `serve`, `db migrate`: exit 2, nothing on stdout, usage plus "no command is implemented yet" on stderr;
  - in-process, `-h`, `--version`, `--help serve` and `serve --help`: 0, 2, 2 and 2.
- **REQ-003 to REQ-005 gates:**
  - `ruff check manager` and `ruff format --check manager` exit 0;
  - `mypy --strict --config-file manager/pyproject.toml manager` reports "no issues found in 12 source files";
  - `pytest --cov=bitscan_manager/services --cov-fail-under=85` from `manager/`: 55 passed, 3 skipped (pg, no Docker), and the coverage table lists only `bitscan_manager/services/__init__.py`;
  - in a temp copy, a planted untested 24-statement `services/planted.py` gives exit 1, "Required test coverage of 85% not reached. Total coverage: 0.00%".
- **TASK-001 follow-up (lock header plus banned-api), checked under my TASK-001 approval:**
  - `--exclude-newer 2026-10-19T16:56:37Z` is in both headers;
  - the pins are unchanged (16 runtime and 49 dev, same versions and hashes);
  - regenerating both locks with that command gives bodies byte-identical to the committed files;
  - `xmlrpc` and `plistlib` are now banned (my TASK-001 nit 2).

## Findings

1. **nit, a question for `main`. FastAPI 0.148 has built-in OpenTelemetry, enabled by default.**
   - Where: `manager/bitscan_manager/app.py:14-20`.
   - `create_app()` gets `tracing`, `metrics` and `logs` all True, and `auto_configure` is read from `FASTAPI_OTEL_AUTO_CONFIGURE` (`fastapi/applications.py:1011-1022`). FastAPI also reads `OTEL_*` variables.
   - With the locked packages this is inert: only `opentelemetry-api` is installed, with no SDK or exporter. Even `FASTAPI_OTEL_AUTO_CONFIGURE=true` with `OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example` starts cleanly and exports nothing.
   - The spec is silent on telemetry. The question is whether `create_app()` should pass `telemetry={"tracing": False, "metrics": False, "logs": False, "auto_configure": False}`. That would stop a future SDK install, or a stray variable in `manager.env`, from exporting request data, and would keep TS §8.4 logging and "no token in logs" under Bitscan's own control. This belongs with the M3 middleware work; it does not block M0.
2. **nit, for impl-manager and the tester (dev lock).** `fastapi.testclient` emits `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2`. This is harmless now. If the suite ever runs with `-W error`, either add `httpx2` to the dev extra or filter the warning in `[tool.pytest.ini_options]`.
