# TASK-164 IMPL: `POST /api/v1/policies/rebuild` and `GET /api/v1/tasks/{id}`

Owner: impl-manager-m7b. REQ-172, REQ-174, REQ-177. Risk: high (a sensitive route). Depends on TASK-160 (`CatalogService.start_rebuild`, `Runtime.catalog`) and TASK-157 (the `task.result` shape).

Spec and rulings: TS §6.2 L1084 (rebuild is a sensitive action), L1105 (admin, TOTP session), L1106 (admin), §4.2 L540; #1, #20, #98 (f), (g), (i), (j), #102 (d), #107 (d); decisions rows "TASK-157 rulings", "Speed-up" (2026-10-28), and the TASK-165 ruling (a read route may read the repository directly).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/api/user/rebuild.py` | new | 90 |

- **Registration and `openapi.json` are not done here**, per the Speed-up row and impl-manager-m7's ownership. It registers `rebuild.router` in `api/user/__init__.py` (module `bitscan_manager.api.user.rebuild`, attribute `router`, no prefix of its own; paths `/policies/rebuild` and `/tasks/{id}` under `/api/v1`). It then regenerates `manager/openapi.json` once.
- No other file was changed.

## Routes

- **`POST /policies/rebuild`, 202 `{"task_id": "<uuid>"}`.**
  - **Auth:** `require_totp_session()` (admin, TOTP-verified session, sink gate). An admin `bsk_` gets 403 `totp_session_required`, an operator 403 `forbidden`, and an audit-sink outage 503 `audit_sink_unavailable`. This is the dependency the approved sensitive routes use.
  - **No body is declared**, so none is read: no body and `{}` both work (#98 (f)).
  - **Action:** it calls `runtime.catalog.start_rebuild(principal.user_id, Actor("user:<id>", <id>))`. That writes the `task` row (`requested_by` = the admin) and queues the rebuild on the catalog worker.
  - **503 answers:** `CatalogStarting` gives 503 `about:blank` "The catalog is starting; retry shortly." with `Retry-After: 10` (#102 (d)). With no catalog, 503 `about:blank` "The service is not ready.". A database error goes to the app's 503 handling (#98 (j)).
- **`GET /tasks/{id}`, 200 `TaskItem`.**
  - **Auth:** `require_role("admin")`, session or API token (L1106). A viewer or operator gets 403.
  - **Id:** must be the hyphenated 8-4-4-4-12 form (`Path(pattern=UUID_PATTERN)`, builder checklist 5). A non-UUID, a 32-hex string, `{…}` or `urn:` gets 400. An unknown id gets 404 `not_found` "No such task.".
  - **Read:** `imports.get_task` in a read-only transaction.
- **Schemas (#98 (g), (i); review carry):**
  - `TaskItem`: `{task_id, kind: "rebuild", state: running|succeeded|failed, requested_by: int|null, result, started_at, finished_at|null}`.
  - `result` is `null` while running. A failed task has `TaskFailure {error}`: a rebuild that errored, or one start-up found running. A succeeded task has `TaskResult {files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported}`.
  - `files` items: `TaskFile {source_file, import_id|null, outcome: success|rejected, policy_id|null, policy_version|null}`.
  - **`removed_leftovers`** (uploads of deleted policies the rebuild removed, crash-window ruling) and **`not_imported`** (files with no import row, for example a server-folder policy's refused copy) are documented fields with descriptions in the code.
  - `RebuildStarted {task_id}`.

## Checks run here (scratch, outside the tree; the tests are the tester's)

- **Gates:** `ruff check manager/bitscan_manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager` are clean.
- **Schema** (`C:\Users\kaiquan.koh\scratch\task164\smoke.py`: the router mounted under `/api/v1` in a scratch FastAPI app, in memory; `openapi.json` not written):
  - The POST has responses 202, 401, 403, 429 and 503, and no `requestBody`.
  - `TaskResult` lists `files`, `deleted_policy_ids`, `plugins_retired`, `removed_leftovers` and `not_imported`.
  - `TaskItem` follows the #98 (g) field order, and the task id parameter carries the UUID pattern.
  - There are no component-name clashes with `create_app().openapi()` (`RebuildStarted`, `TaskFile`, `TaskResult`, `TaskFailure` and `TaskItem` are all new).
- **Handler smoke** (fake runtime):
  - the POST returns the task id, and the catalog gets `(7, "user:7", 7)`;
  - `CatalogStarting` gives 503 `about:blank` with `Retry-After: 10`, and no catalog gives 503;
  - the GET serialises a running task (result null), a succeeded one (the full result, including both new lists) and a failed one (`{error}`);
  - an unknown id gives 404.

## For the tester (REQ-172 (1)–(4), REQ-174 (2))

- **Plants:**
  - Use `require_role("admin")` on the POST: REQ-172 (2) `bsk_` and the sink gate.
  - Drop the UUID pattern: REQ-172 (3) non-UUID gives 404 or 500 instead of 400.
  - Allow `viewer` on the GET: REQ-172 (3).
  - Drop `removed_leftovers` or `not_imported` from `TaskResult`: the schema check, and those fields go missing from the response.
  - Swallow `CatalogStarting`: 500 instead of 503 with Retry-After.
- **Once impl-manager-m7 has registered the router and exported `openapi.json`:** the route walk (G34) and G6.
