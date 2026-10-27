# TASK-149 IMPL: import record and task repository

Owner: impl-manager-m7b. REQ-160, REQ-166, REQ-173; #20, #98 (g) and (h), #107 (d), #110. Spec: SR §3.5, §3.6 (the record in its own transaction); TS §4.1 L520, §4.2 L540, §5.2 (`bit_import` L694–L707, `task` L941–L949, grants L1005–L1009), §6.3 (cursor pagination). Risk: high (importer; two approvals).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/repositories/imports.py` | new | 132 |

No other file was changed. The row estimated 110 lines; the extra is mostly the row dataclasses and docstrings.

## Functions (module functions; the caller's connection comes first; none commits)

- `insert_import(conn, ImportRecord, now) -> int` (the `import_id`) writes every `bit_import` column, with `imported_at = now` (Clock).
  - `ImportRecord` has `file_name`, `file_sha256`, `mode` (`auto`/`manual`/`rebuild`), `outcome` (`success`/`skipped`/`rejected`), `policy_version` (None unless success), the three counts (default 0), `errors` (the findings, warnings included, #110) and `imported_by` (None = system or CLI).
  - The caller runs it in **its own** transaction after the catalog transaction (SR §3.6, D4 transaction 2). The repository cannot enforce that; TASK-154 does.
- `imports_newest_first(conn, limit, before_id) -> list[ImportRow]`, for `GET /imports` (#98 (h)): every column, `ORDER BY import_id DESC`, keyset `import_id < before_id` (None = first page). This is the same pattern as `audit_log.page_newest_first`. The caller asks for `limit + 1` and uses `api/pagination.page_of`. `errors` comes back as the decoded jsonb list.
- `insert_task(conn, requested_by, now) -> UUID`: a `rebuild` task, `running`, `started_at = now`. `requested_by` is None for the CLI (#107 (d)).
- `finish_task(conn, task_id, state, result, now) -> bool` (`succeeded` or `failed`): sets `state`, `result` and `finished_at`, but only while the row is `running`. It returns False otherwise, for example when start-up already marked the task failed. This is a conditional UPDATE (checklist 8).
- `get_task(conn, task_id) -> TaskRow | None`, for `GET /tasks/{id}` (#98 (g)).
- `fail_running_tasks(conn, result, now) -> list[UUID]`, for start-up (TS §4.2 L540, REQ-165 (2)): every `running` row becomes `failed` with `finished_at = now` and the given `result`. Other rows are untouched. The fixed `{error: "<text>"}` (#98 (g)) is the service's choice, so it is passed in.

## Grants used (bitscan_app, TS §5.2)

INSERT and SELECT on `bit_import`, and never UPDATE or DELETE on it. INSERT, SELECT and UPDATE on `task`. USAGE on `bit_import_import_id_seq`. `task_id` comes from the column default `gen_random_uuid()`.

## Not included (outside the row)

- The #103 check "has a `rejected` row for the file's current hash" is part of TASK-150's integrity reads: `catalog_admin.rejected_files`.
- The `auto` skip (#23) compares against the policy's `source_sha256` in the store (`TASK-151` plan §3.3), not against `bit_import`.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` and `ruff format --check manager`: clean, with no `noqa`. The SQL is constant strings or `psycopg.sql.SQL` constants.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI form): no issues in 241 source files.
- Nothing has been run against PostgreSQL (no Docker here).

## For the tester (TP-M7-10, `test_imports_repo_pg.py`)

- Run as `bitscan_app`. An `insert_import` committed in its own transaction survives the rollback of a sibling transaction on another connection.
- With N + 1 rows and `limit = N`, the pages hold each row once, newest first.
- `fail_running_tasks` changes only `running` rows and sets `finished_at`. After it, `finish_task` on such a task returns False and changes nothing.
- `errors` holding warnings and Reject findings round-trips exactly. The caller must not pass U+0000 or lone surrogates; #105 (g) and #99 (d) already guarantee that, and jsonb or text would refuse them.
- The M1 grant probe still shows that `bitscan_app` cannot UPDATE or DELETE `bit_import` (REQ-160 (5)).
