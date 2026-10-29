# TASK-150 IMPL: catalog admin repository

Owner: impl-manager-m7b. REQ-165, REQ-167, REQ-168, REQ-169; #9, #14, #98 (a) and (b), #103, #104. Spec: TS §4.2 L542, §4.3 L546–L551, §5.2 (catalog DDL, `scan_job` L872–L889, `scan_schedule` L846–L857, `v_plugin` L1035–L1041, grants L1005–L1013), §6.3 (cursors, plain text). Risk: high (importer; two approvals).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/repositories/catalog_admin.py` | new: list, item, detail, lock, status, soft delete | 206 |
| `manager/bitscan_manager/repositories/catalog_integrity.py` | new: the #103 reads | 46 |

No other file was changed. The lead split the task across two files (2026-10-27): the #103 reads moved to `catalog_integrity.py`, and every TASK-151 plan name stays in `catalog_admin.py`. It is still one task id. About 60 of `catalog_admin.py`'s lines are the #98 row dataclasses. Neither module imports the other.

## Functions (module functions; the caller's connection comes first; none commits)

Reads:
- `list_page(conn, limit, status, after) -> list[ProfileItem]`, for `GET /policies`: non-deleted policies only (#9), filtered by effective `policy_status` when `status` is `enabled` or `disabled`.
  - Order is `(policy_name, policy_id)`, keyset `> after`, the same pattern as `agents.list_page`. The caller asks for `limit + 1`.
  - `ProfileItem` holds the #98 (a) fields in order. `plugin_count` is the policy's `policy_plugin` row count.
- `item(conn, policy_id) -> ProfileItem | None`: the same shape for one policy, deleted or not. This is the PATCH answer.
- `detail(conn, policy_id) -> ProfileDetail(item, deleted_at, plugins) | None`, for `GET /policies/{id}` (#98 (b)): a deleted policy is returned with `deleted_at` (#9).
  - Plugins come from `v_plugin` (`display_name` is never stored) joined to `policy_plugin`, ordered by `sort_order`. Each holds the #98 (b) fields in order.
  - The policy and its plugins are read in **one statement**, so they share one snapshot even under READ COMMITTED. The plugins come back as `json_agg(json_build_array(…))`, and only `plugin_uuid` and `updated_at` are converted back from JSON strings. Text values round-trip unchanged.
  - A deleted policy's plugins are shown, because its `policy_plugin` rows are kept (#104 (a)).

Status (REQ-168):
- `lock(conn, policy_id) -> PolicyState | None`: `SELECT … FOR UPDATE` of `policy_status`, `file_status`, `status_overridden`, `source_file` and `deleted_at`. The services decide on this re-read row (checklist 9): 404, 409 for deleted, 409 `policy_managed_on_server` for a server-folder delete, and whether the status was `disabled` before (`policy_reenabled`).
- `set_status(conn, policy_id, status, now) -> bool`: sets `policy_status` and `status_overridden = true`.
- `clear_override(conn, policy_id, now) -> bool`: sets `policy_status = file_status` and `status_overridden = false` (TS §4.3 L548).
- Both of those update only a non-deleted row, and move `updated_at` only when a column changes (#104 (d)).

Delete (REQ-167; TS §4.3 L550):
- `soft_delete_effects(conn, policy_id, now) -> DeleteEffects | None`, in this order:
  1. `UPDATE policy SET deleted_at = now, source_file = 'deleted/' || policy_id, updated_at = now WHERE policy_id = … AND deleted_at IS NULL`. If no row changes (unknown or already deleted), it returns None and runs nothing else (checklist 8).
  2. Cancel the policy's **queued** compliance jobs: `state = 'cancelled'`, `finished_at = now`. Dispatched and running jobs are untouched. A pull holding a job row makes this statement wait, and READ COMMITTED then re-checks `state = 'queued'`.
  3. Disable its `scan_schedule` rows that are still enabled.
  4. Retire the active plugins it owns or lists that no non-deleted policy lists (#104 (b)).
- It returns the ids changed in each of the three tables, for the alert detail. It never DELETEs, and its `policy_plugin` rows are kept (#104 (a)).
- The uploaded file, the audit entry and the alert are the caller's (TASK-152).

Integrity (#103, start-up TASK-158), in `catalog_integrity.py`:
- `integrity_rows(conn) -> list[IntegrityRow]`: for each non-deleted policy, its `source_file`, `source_sha256`, `policy_plugin` count, and `bad_plugins` (listed plugins that are not `active` or are owned by another policy). The service compares the first three with the files on disk.
- `rejected_files(conn, [(file_name, sha256)]) -> set[…]`: the pairs that have a `rejected` `bit_import` row. Both `file_name` and `sha256` are passed as arrays in one query. `bit_import` has no index on `file_name` and none may be added, so this is one sequential scan at start-up.

## Grants used (bitscan_app, TS §5.2)

UPDATE on `policy` and `plugin`; UPDATE of `state` and `finished_at` only on `scan_job`; UPDATE on `scan_schedule`; SELECT on `scan`, `family`, `policy_plugin`, `v_plugin` and `bit_import`. There is no DELETE anywhere. `policy` cannot be deleted by the grant, and this code never tries.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` and `ruff format --check manager`: clean, with no `noqa`. All SQL is constant text or `psycopg.sql` composition of constant fragments, so S608 is clean.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI form): no issues in 241 source files.
- Nothing has been run against PostgreSQL (no Docker here).

## For the tester (TP-M7-10, `test_catalog_repo_pg.py`)

- Use owner-written fixtures: a scan of the policy with jobs `queued`, `dispatched` and `running`, two enabled schedules, and a second policy's queued job.
  - After `soft_delete_effects`, only the first policy's queued job is `cancelled` with `finished_at`, and both schedules have `enabled = false`.
  - The row is kept, with `deleted_at` set and `source_file` `deleted/<id>`. Its plugins are `retired`, and its `policy_plugin` rows still exist.
  - A second call returns None and changes nothing.
  - The statement log shows no `DELETE FROM policy`.
- List: 3 enabled, 2 disabled and 1 deleted gives 5, 3 and 2. N + 1 rows page once each in name order.
- Detail: plugins in `sort_order` with `display_name` = `<family> - <plugin>`. Hostile text comes back byte-identical, and a deleted policy shows `deleted_at`.
- Status: `set_status` and `clear_override` give the REQ-168 (1) columns and return False for a deleted policy. `updated_at` stays put on a no-op.
- The CHK-M7-337 plant (an f-string in `catalog_admin.py`) should turn G1 red. Plant the same in `catalog_integrity.py`, since the split added that file.
- Integrity: `integrity_rows` lists only non-deleted policies, and `bad_plugins` counts a listed plugin that is `retired` or owned by another policy. `rejected_files` returns only pairs with a `rejected` row: a `success` row for the same pair does not count, and neither does another hash for the same name.
