# TASK-044 REVIEW: health routes and `create_app(runtime)`

Reviewer: reviewer. Date: 2026-10-22. REQ-056, REQ-036. Spec: TS §8.4 L1292, TS §3.4 L230, TS §8.3 Integration (`/readyz` with the `inventory` row missing). Decisions: #5 (outside `/api/v1`, no token), #41 (`alembic_version`), #58 (c) (no vault check); 2026-10-21 carry-over (`/readyz` bounded, the checks only after `ping()`). Inputs: `work/reports/TASK-044-impl.md`, `work/reports/TASK-044-test.md` (PASS; TP-M2-21).

Files reviewed:
- `manager/bitscan_manager/api/health.py`;
- `manager/bitscan_manager/repositories/health.py`;
- in `manager/bitscan_manager/app.py`: `create_app(runtime)`, the lifespan and the health router;
- `manager/openapi.json`.

Verdict: APPROVED

TASK-044 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **`/healthz` (REQ-056 (1)).** It returns 200 `{"status": "ok"}` with no runtime and no database access.
- **`/readyz` (REQ-056 (2) to (5)).** It first calls `runtime.db.ping()`, bounded at 2 s by TASK-025. Only if that is True does one worker thread run a single READ COMMITTED transaction, waited for at most 2 s, with a transaction-local `statement_timeout` of 2 s as a server-side backstop. That transaction checks:
  - the stored revisions equal `[packaged head]`; the head is read from the package's Alembic scripts, with no database (#41);
  - `system_schedule` contains `inventory`, `offline_sweep` and `retention`.

  If a stuck check is still running, the answer is `db` straight away. The worst case is about 4 s, so `/readyz` never hangs (the carry-over is met). The SQL is SELECT only, plus a transaction-local `set_config`, so nothing is written. A 503 body is problem details whose `detail` is exactly `db`, `migrations` or `system_schedule`, with no DSN, host or driver text.
- **Headers and auth.** Both routes pass through `RequestLog`, `SecurityHeaders` and `BodyLimit` (REQ-056 (6)). They read no token, so a bad `Authorization` header is never counted as a failed check, and they have no rate limit (#5). `/api/v1/healthz` gets 404.
- **`create_app(runtime)`.** The runtime is stored on `app.state`. The lifespan calls `lifecycle.start()` and `stop()` only when a lifecycle is set. With no runtime, the OpenAPI export still works and runtime-backed routes answer 503.
- **OpenAPI.** The regenerated `manager/openapi.json` has `/healthz` and `/readyz` with responses 200, 200 and 503 and no 422. The re-export has no diff. The M0 "no paths" assertions are updated by the tester, as REQ-006 and REQ-007 were superseded.
- **Gates (my run).** ruff, format and `mypy --strict` are clean, and `test_health.py`, `test_app.py` and `test_openapi.py` pass. The pg cases (the `inventory` row deleted as `bitscan_owner`, a revision mismatch) ran in WSL.
- **Scope.** 4 files, about 110 hand-written lines.

## Findings

None block approval.

1. **note, the tester's point, accepted.** A readiness check stuck on a silent server holds one daemon thread and one pooled connection until the server answers or TCP gives up. Later calls answer `db` straight away, so nothing builds up. Once TASK-045 sets `tcp_user_timeout` and `statement_timeout` on pooled connections, that one connection is released within 5 minutes. With a pool of 10 this is acceptable.
2. **nit.** `health.py:76-81`: `_checker` is created lazily on `app.state`. Two concurrent first requests can each create one, which briefly allows two checks in flight. Creating it in `create_app()` would remove the race. This is harmless.
3. **note, no change.** `/readyz` is unauthenticated, so it reveals to any client whether migrations are current, without saying which revision. This is accepted under #5. The 503 detail is one of three fixed words.
