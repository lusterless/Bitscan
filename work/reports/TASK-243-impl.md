# TASK-243 IMPL: re-evaluate route

Implementer: impl-manager-b, 2026-11-08. REQ-270, REQ-271. Spec: TS §6.2 L1086 (sensitive action), L1125 (`POST /scans/{id}/reevaluate`, admin, TOTP session); TS §4.5 L603 (re-evaluation adds rows, audit-logged); TS §5.3 L1053 (sensitive actions refused after 15 minutes of sink outage); TS §8.1 L1245. Open items: #118, #147, #148 (no alert). Plan: `work/plans/TASK-232.md` §6. High risk (full rigor, plus the user's second look, PD-47).

## Files (+30 / −8)

- `manager/bitscan_manager/api/user/reevaluate.py`. Only the handler body and its imports changed, plus the module docstring, where the PD-48 "answers 501 until filled" paragraph was replaced.
  - The route decorator, the parameters (`id: SCAN_ID`, `principal: TOTP_ADMIN`, `runtime: RUNTIME`), `ReevalItem`, the return annotation and the handler docstring are byte-unchanged from TASK-232 (`69baeaa`).
  - The body calls M8's `services.evaluator.reevaluate.reevaluate_scan(runtime.db, UUID(id), user_id=principal.user_id, wake=runtime.sink_gate.wake)`, unchanged and in the request (#147 (a)).
  - It maps `ScanNotFound` to 404 `not_found` "No such scan." and `PolicyDeleted` to 409 `conflict` "The policy is deleted.". Both problems are raised outside the `except` blocks, as in `scans.py` `cancel`, so they carry no chained cause.
  - It returns `ReevalItem` field by field from M8's `ReevalResult`.

No other file changed. Nothing under `bm/auth/`, `services/evaluator/` or `repositories/` was touched, and `openapi.json` was not re-exported (the contract is unchanged).

## How each REQ-270 / REQ-271 row is met

- **Auth (REQ-270 (2)): `require_totp_session()` from TASK-232, unchanged.** Its defaults are minimum role `admin` and `sink_gate=True`.
  - That dependency gives the outcomes REQ-270 (2) lists: 403 `totp_session_required` for an API token, 403 for an operator or viewer, 403 `totp_enrolment_required` for a restricted admin, 401 for no token or a `bsa_` token, and 503 `audit_sink_unavailable` after 15 minutes of sink outage.
  - FastAPI resolves the dependency before the handler runs, so a refused call never reaches `reevaluate_scan`. It opens no transaction and writes no `scan_result_reeval` row and no audit entry.
- **Body (#147 (b)).** No body parameter is declared, so none is read or parsed. Builder checklist 4 has nothing to order.
- **Id.** `SCAN_ID` (the hyphenated pattern) answers 400 for a malformed id before the handler runs. Upper case is accepted and parsed with `UUID(id)` (REQ-270 (3)).
- **Writes (REQ-271).** The one `scan.reevaluate` audit entry and the `scan_result_reeval` rows are M8's, in M8's single transaction. There is no alert (#148): the route adds no audit entry, alert or log line of its own.
- **Sink wake.** `wake=runtime.sink_gate.wake` is registered by M8 with `tx.on_commit`, so the entry is shipped straight after the commit (REQ-270 (1); CHK-M11-338 plants its removal).
- **Concurrency (REQ-270 (4)).** Unchanged M8 behaviour: the per-scan advisory lock serialises two calls, and both answer 200.
- **Layering (REQ-270 (5)).** The route imports `api`, `auth`, `runtime` and `services.evaluator.reevaluate` only, with no repository.
- **No output in logs.** Nothing is logged. The problem details are fixed words and never echo the id.

## Deviations

None from plan TASK-232 §6. Matching the codebase, I used the `failure` variable pattern rather than `raise … from None` inside the `except`. The plan asks only that problems carry no chained driver text, and both forms satisfy that.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check manager && ruff format --check manager`: all checks passed, 403 files formatted.
- `mypy --strict manager`: 12 errors, the same 12 as on main and in my TASK-236 report (`packages.py`, `agents.py`, `enrolment.py`, `policy_import.py`, the `python_multipart` stub in a stale local venv). None is in `reevaluate.py`.
- **G6 (OpenAPI export) NOT RUN locally.** `python -m bitscan_manager.app` fails to import here (`ModuleNotFoundError: python_multipart`, the same stale venv; `api/user/__init__` imports `policy_import`). The document can't change, because the decorator, parameters, response model, return annotation and handler docstring are byte-identical to `69baeaa`; only the function body changed. **Please run G6 in WSL.**
- The API tests on PostgreSQL are the tester's: `manager/tests/test_reevaluate_api_pg.py`, TP-M11-11.

## Builder checklist

- 4: there is no body.
- 5: the hyphenated id pattern is used.
- 7 and 8: wake runs on commit only (M8), and the audit entry is M8's single in-transaction write.
- 11 and 12: nothing is logged, and the details are fixed words.
- 13: the contract is unchanged; G6 is for the tester in WSL (see above).
- 1–3, 6, 14–22 don't apply.
