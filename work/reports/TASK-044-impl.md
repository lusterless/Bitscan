# TASK-044 IMPL report: health routes and `create_app(runtime)`

REQ: REQ-056, REQ-036. Spec: TS §8.4 L1292, TS §3.4 L230, TS §8.3 Integration (`/readyz` with the `inventory` row missing). Decisions and plans:
- #5: outside `/api/v1`, no token, no rate limit; 200 `{"status": "ok"}`; a 503 problem names only the failed check.
- #41: `alembic_version` holds the revision.
- #58 (c): the vault is not checked.
- The TASK-025 plan: `create_app(runtime)` with a lifespan.
- Lead carry-over 2026-10-21: `/readyz` is bounded, with every check limited on the client side.

## Files (4)

- `manager/bitscan_manager/api/health.py`: new, 77 non-blank lines.
- `manager/bitscan_manager/repositories/health.py`: new, 14 non-blank lines. All read-only: `bound_statements(conn, ms)` (a transaction-local `statement_timeout` via `set_config(…, true)`), `alembic_revisions(conn)` and `schedule_kinds(conn)`. Parameterised SELECTs only.
- `manager/bitscan_manager/app.py`:
  - `create_app(runtime: Runtime | None = None)` stores the runtime in `app.state.runtime`.
  - When `runtime.lifecycle` is set, a lifespan awaits `lifecycle.start()` on start-up and `lifecycle.stop()` on shutdown.
  - `create_app()` with no runtime still builds the OpenAPI export, and routes that need the runtime answer 503 (`get_runtime`).
  - The health router is included without a prefix.
- `manager/openapi.json`: regenerated. It now has `/healthz` and `/readyz` and the `Health` schema. No route has parameters or a body, so there is no 422 and no `HTTPValidationError` (CHK-M2-185 holds).

## Behaviour

- **`GET /healthz`** returns 200 `{"status": "ok"}`. It needs no runtime and makes no database call.
- **`GET /readyz`**:
  1. If `runtime.db.ping()` (TASK-025: its own connection, bounded at 2 s) fails, it answers 503 with detail `db`.
  2. Otherwise one worker thread runs a single short READ COMMITTED transaction, waited for at most `CHECK_TIMEOUT_S` = 2 s. The transaction does the following:
     - It sets `statement_timeout` to 2 s for this transaction only, as a server-side backstop.
     - The stored revisions must equal `[packaged head]`, or the answer is `migrations`. The packaged head is `ScriptDirectory(MIGRATIONS_DIR).get_current_head()`, cached and read from the package files with no database.
     - The `system_schedule` job kinds must include `inventory`, `offline_sweep` and `retention`, or the answer is `system_schedule`.
     - Any exception gives `db`.
  3. If the worker does not finish within 2 s, or an earlier stuck check is still running, the answer is `db` at once. At most one check is in flight, and a stuck one holds one pooled connection and one thread.

  Total worst case is about 4 s, so `/readyz` never hangs (CHK-M2-249). The route writes nothing: it sends SELECTs only, plus the transaction-local `set_config`, which changes no row.
- **The 503 body** is `{"type": "about:blank", "title": "Service Unavailable", "status": 503, "detail": "db" | "migrations" | "system_schedule", "instance": "/readyz"}`. There is no DSN, host or driver message. `about:blank` follows the TASK-026 ruling, because #48 gives no value for 503.
- **Headers and access.** Both routes pass through `RequestLog`, `SecurityHeaders` and `BodyLimit`, so they carry the four headers. They read no token, so a bad `Authorization` header is ignored and never counted as a failed check. They apply no rate limit. `/api/v1/healthz` is 404.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 95 files |
| OpenAPI re-export | `manager/openapi.json` regenerated (+65 lines: `/healthz`, `/readyz`, `Health`). Re-running the export gives no further diff |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 972 passed, 237 skipped (pg), 97.10 % (gate met); **3 expected failures in M0 tests** (below) |
| Scratch (deleted): `create_app(runtime)` with a fake db, fake lifecycle and patched repository functions | (1) |

(1) Scratch results:
- `/readyz` returned 200 with all four headers when everything was in place.
- A wrong revision gave `migrations`; a missing `inventory` row gave `system_schedule`; a failing ping gave `db` while `/healthz` stayed 200.
- A transaction that stalls for 3 s gave 503 `db` in 2.0 s. A second call while it was still stuck gave `db` in 0.0 s. After it ended, the next call gave 200.
- A bad bearer token on `/readyz` still gave 200, and `/api/v1/healthz` gave 404.
- The lifecycle ran `start` once and `stop` once.
- With no runtime, `/readyz` gave a 503 problem.

**Expected failures, for the tester to update.** REQ-006 (1) and REQ-007 (3) are superseded from this task on ("Changes to earlier requirements (M2)"):
- `tests/test_app.py::test_no_routes_registered` asserts `create_app().routes == []`;
- `tests/test_app.py::test_import_and_create_need_no_env_or_network` asserts `doc["paths"] == {}`;
- `tests/test_openapi.py::test_document_is_openapi_31_with_no_paths` asserts that there are no paths.

The "no docs routes" parts (`/docs`, `/redoc`, `/openapi.json` → 404) still hold. The import-and-create test should still pass once its `paths` assertion is changed: no environment variable or network use was added; the packaged head is read lazily from files.

## For the tester (TP-M2-21)

- Use `create_app(Runtime(clock, AppDatabase(...), cipher, gate, RateLimiter(clock), lifecycle=None))`.
- To test the stall case (CHK-M2-249), pause the proxy after `ping()` succeeds: the worker thread's 2 s wait answers `db`.
- The readiness worker is stored per app (`app.state.readyz_checker`), so separate test apps do not share a stuck check.
