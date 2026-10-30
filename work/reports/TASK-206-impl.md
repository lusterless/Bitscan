# TASK-206 IMPL: schedule routes CRUD `/scan-schedules`

Implementer: impl-manager-m9b, 2026-10-30. REQ-212, REQ-224. Open items #122 (h), (i), #128 (d), (i). Built on TASK-201 (`services/scheduler/schedules_admin.py`). Started after TASK-205's impl report; `openapi.json` regenerated on top of TASK-205's export.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/scan_schedules.py` | new, 212 lines: five routes, `CreateSchedule`, `PatchSchedule`, `ScheduleItem` |
| `manager/bitscan_manager/api/user/__init__.py` | `scan_schedules` imported and its router included after `scans` (+2 lines) |
| `manager/openapi.json` | re-exported with `python -m bitscan_manager.app manager/openapi.json`: +722 lines, insertions only against TASK-205's file; a second export is byte-identical |

## Routes (operator minimum on every one, GET included, `bsu_` or `bsk_`; not sensitive, so no TOTP or sink gate)

| Route | Answer |
| --- | --- |
| `POST /api/v1/scan-schedules` | 201 `ScheduleItem`; body `{name, policy_id, target, cron, timezone?: "UTC", enabled?: true}` |
| `GET /api/v1/scan-schedules` | 200 `{items, next_cursor}` ordered by `schedule_id`, `?limit` 1–500, `?cursor` |
| `GET /api/v1/scan-schedules/{id}` | 200 `ScheduleItem` |
| `PATCH /api/v1/scan-schedules/{id}` | 200 `ScheduleItem`; any non-empty subset of `name`, `target`, `cron`, `timezone`, `enabled` |
| `DELETE /api/v1/scan-schedules/{id}` | 204 |

`ScheduleItem` = `{schedule_id, name, policy_id, target, cron, timezone, enabled, last_run_at, next_run_at, created_by}` (#122 (h)); timestamps UTC with `Z` (`UtcDatetime`).

## Validation and refusals

- Bodies are `extra="forbid"`: `policy_id` in a PATCH, or `plugins`, `execute`, `command`, `payload`, `eval_spec` anywhere, is 400 through the app's validation handler (REQ-212 (1)). Strict types (`StrictStr`, `StrictInt` 1 to 2^53 − 1, `StrictBool`); a JSON `null` in a PATCH field reaches the service and is 400 for that field.
- An empty PATCH `{}` → 400 `Invalid request: body` (service `InvalidField("body")`).
- `{id}`: digits only (`^[0-9]{1,20}$`, else 400); beyond `bigint` → 404. Cursor: must decode for this list's scope to an int in `bigint` range, else 400 `Invalid request: query.cursor`.
- Service refusals mapped with fixed text: `InvalidField` / `InvalidTarget` / `InvalidSchedule` → 400 `invalid_request` with the field (`Invalid request: name`, `…: target.agents`, `…: cron`, `…: timezone`, `…: enabled`, `…: body`); `PolicyNotFound` → 404 "No such policy."; `ScheduleNotFound` → 404 "No such scan schedule."; `ScheduleConflict` → 409 `conflict` "The policy is deleted.".
- 413 over 1 MiB comes from the app's body-cap middleware (documented on POST and PATCH).
- Each change runs in one transaction with `tx.on_commit(runtime.sink_gate.wake)`; a refusal raises inside it (rolled back, so no audit entry) and the problem is raised after the block.

The handlers import no repository: `api` helpers, `auth`, `runtime`, `services.scheduler.schedules_admin`, `services.scheduler.cron.InvalidSchedule`, `services.jobs.targets.InvalidTarget`, `services.jobs.queue.PolicyNotFound`.

## OpenAPI (G6)

- Paths added: `/api/v1/scan-schedules` (GET, POST) and `/api/v1/scan-schedules/{id}` (GET, PATCH, DELETE); every path starts with `/api/v1/`.
- Components added: `CreateSchedule`, `PatchSchedule`, `ScheduleItem`, `Page_ScheduleItem_` (no clash). `policy_id` `maximum` is 9007199254740991 (checklist 3; written `.0` like the existing bounds).
- Responses: POST 201, 400, 401, 403, 404, 409, 413, 429, 503; PATCH 200 plus the same refusals; GET list 200, 400, 401, 403, 429, 503; GET/DELETE by id add 404. No agent-route component changed.

## Gates (Windows, worktree venv)

- `ruff check`, `ruff format --check`, `mypy --strict` (Windows and `--platform linux`) on `manager/bitscan_manager`: green (178 files).
- Whole `manager` tree: `ruff format --check` green (372 files); `ruff check` red only in tester files (`test_job_intake_repo_pg.py`, `test_job_sweep_repo_pg.py`, `test_schedules_repo_pg.py`).
- OpenAPI export twice: byte-identical.

## For the tester

- REQ-224 (5): viewer 403 on all five operations, `bsa_` 401 (the user router's token resolution); any operator may change another operator's schedule.
- The G34 route walk now sees five more operations under `/scan-schedules`.
- `web/src/api/schema.d.ts` (TASK-207, impl-web) must be regenerated from this `openapi.json`.

## Plants

- REQ-224 (5): `require_role("viewer")` on any route.
- REQ-212 (1): `extra="allow"` on `CreateSchedule` or `PatchSchedule`.
- REQ-224 (2): add `policy_id` to `PatchSchedule`.
- G6: add a route without re-exporting.
