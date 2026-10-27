# TASK-148 IMPL: catalog repository for imports

Owner: impl-manager-m7b. REQ-158, REQ-159; #14, #21, #100 (a), #104. Spec: SR §3.1–§3.4, §3.6 steps 1–5; TS §4.1 L519, §4.3 L548–L550, §5.2 (catalog DDL L642–L692, grants L992–L1013). Risk: high (importer; two approvals). Interface: `work/plans/TASK-151.md` §4.

The lead split the task across two files (2026-10-27): policies and families in `catalog.py`, plugins in `catalog_plugins.py`. It is still one task id.

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/repositories/catalog.py` | new: `family` and `policy` rows, plus the BIT015 owner read | 155 |
| `manager/bitscan_manager/repositories/catalog_plugins.py` | new: `plugin` and `policy_plugin` rows | 118 |

No other file was changed. No migration was added. Neither module imports the other, so there is no cycle. Each defines its own one-line `Conn` alias.

## Functions (module functions; the caller's connection comes first; none commits)

`catalog.py`:
- `policy_by_name_for_update(conn, name)`, `policy_by_source_file_for_update(conn, path)`, `policy_by_id_for_update(conn, id)` → `PolicyRow | None`. Each runs `SELECT … FOR UPDATE` (D3) and also returns deleted rows. `PolicyRow` holds every `policy` column, with the enums as text.
- `upsert_family(conn, family_name, now) -> int`: `INSERT … ON CONFLICT (family_name) DO NOTHING RETURNING`, then `SELECT`. It never updates a family row (#104 (e)) and sets `created_at = now`.
- `next_policy_id(conn) -> int`: `nextval('policy_policy_id_seq')`, which only needs USAGE. With it an upload's `source_file` (`uploaded/policy-<id>.bit`) is known before the INSERT.
- `insert_policy(conn, policy_id, PolicyValues, now) -> PolicyRow`: `version` 1, `policy_status = file_status`, `status_overridden` left at its default `false`, `imported_at = updated_at = now`.
- `update_policy(conn, policy_id, PolicyValues, now) -> PolicyRow | None` is one UPDATE that serves update, rename in place, moves and revival:
  - `policy_status = CASE WHEN status_overridden THEN policy_status ELSE <file> END` inside the statement (D3, TS §4.3 L548). `status_overridden` is never written (#14).
  - `version + 1` when `source_sha256 <> <sha>` **or** the row was deleted (a revival, #14). This is the plan's "or the case is `revive`": a revival is exactly the case where the locked row has `deleted_at` set.
  - `deleted_at = NULL` and `imported_at = now` on every successful import (#104 (d)).
  - `updated_at = now` only if a stored column changes (#104 (d)): name, description, `file_status`, effective status, family, format, `source_file` or `source_sha256`, or a revival.
  - `RETURNING` gives the new row (`version`, `policy_status`). The caller compares it with the locked old row to see `reenabled`.
- `owners_of(conn, uuids) -> list[Owner]` reads the BIT015 inputs for every id in one query: `plugin_uuid`, `owner_id`, `owner_name`, `owner_deleted`, and `owner_lists` (whether a `policy_plugin (owner, plugin)` row exists). Ids with no plugin row are absent. The store applies the rule, including the displaced-policy and self exceptions in plan §3.2.

`catalog_plugins.py`:
- `current_plugins(conn, uuids) -> dict[UUID, str]`: the stored `execute_sha256` of each existing id (#100 (a)).
- `upsert_plugins(conn, plugins, *, family_id, owner_policy_id, now) -> list[tuple[UUID, bool]]` sends batches of `BATCH = 500` rows, one `INSERT … SELECT FROM unnest(…) ON CONFLICT (plugin_uuid) DO UPDATE … WHERE (stored columns) IS DISTINCT FROM (EXCLUDED …)` per batch. Each written row comes with `state = 'active'`, the owner and the family.
  - It returns `(uuid, inserted)` only for rows inserted or changed. Unchanged rows are not returned (#21). So `plugins_added` = count where `inserted`, and `plugins_updated` = the rest.
  - "Inserted" is read from a `MATERIALIZED` CTE over `plugin`. That CTE runs on the statement's snapshot, so it sees the rows as they were before the statement. This avoids the `xmax = 0` trick the plan mentions; the result is the same.
  - The compared columns: `family_id`, `owner_policy_id`, `plugin_name`, `control_ref`, `plugin_description`, `execute`, `execute_sha256`, `timeout_s`, `operator`, `expected_result`, `state`. A `retired → active` change therefore counts as updated (#21), and so do an owner or family change.
- `replace_membership(conn, policy_id, uuids)`: `DELETE FROM policy_plugin WHERE policy_id`, then one `INSERT … SELECT FROM unnest(…) WITH ORDINALITY`, which gives `sort_order` 1..n in the given order.
- `retire_unreferenced(conn, now) -> list[UUID]`: one UPDATE turns every `active` plugin that no non-deleted policy lists into `retired`, with `updated_at = now` (#104 (b)). It returns the changed ids in sorted order, and the store uses `len()`. Rows are never deleted.
- `PluginValues` is the store's input row: trimmed values, lowercase `operator`, `execute_sha256` of the trimmed `execute`.

## Differences from the TASK-151 plan §4 (sent to planner-m7)

- Module per function: `catalog_plugins.` for `current_plugins`, `upsert_plugins`, `replace_membership`, `retire_unreferenced`, `PluginValues`. Everything else is in `catalog.`.
- `retire_unreferenced` returns `list[UUID]`, not `int`, because the TASK-148 row says "retire returns the plugins it changed". The count is `len()`.
- `upsert_family` and `upsert_plugins` take `now` (Clock), as do `insert_policy` and `update_policy`. `insert_policy` takes the id from `next_policy_id`.
- `owners_of` returns `Owner` dataclasses with the plan's five fields, not tuples.
- The version rule lives inside `update_policy`, so the store passes no "bump" flag.

## Grants used (bitscan_app, TS §5.2)

SELECT, INSERT and UPDATE on `family`, `policy` and `plugin` (`FOR UPDATE` and `ON CONFLICT DO UPDATE` need UPDATE, which is granted); INSERT and DELETE on `policy_plugin`; USAGE on `policy_policy_id_seq`. There is no DELETE on `policy`, `family` or `plugin`, and no other table is touched.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager`: all checks passed. `ruff format --check manager`: 239 files already formatted. There is no `noqa` in either file. All SQL is a constant `str` or `psycopg.sql` composition of constant identifiers, so S608 stays clean.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI form, which loads the pydantic plugin): no issues in 241 source files.
- I could not run PostgreSQL here (no Docker). Every statement was rendered with `as_string(None)` and read through, but **no statement has been run against PostgreSQL yet**.

## For the tester (TP-M7-10, `test_catalog_repo_pg.py`)

- Run as `bitscan_app` on a freshly migrated database. Each function should work with only the grants above.
- #21 counts: on a mixed file (2 new, 1 changed, 1 unchanged, 1 retired then re-listed) the upsert returns 2 rows with `inserted` true and 2 with false, and the unchanged id is absent.
- Batching: 501 or more plugins take two statements and return the same result as one batch.
- `retire_unreferenced` skips plugins any non-deleted policy lists, retires plugins listed only by a deleted policy, and returns exactly the ids it changed.
- `update_policy`: with an override in place, `policy_status` is kept and `file_status` changes. An identical hash keeps `version`, and a revival adds 1 even with an identical hash. `updated_at` stays put on an identical re-import, while `imported_at` moves.
- `next_policy_id` followed by `insert_policy` with that id works for `bitscan_app`.
- The CHK-M7-336 plant (an f-string query in `catalog.py`) should turn G1 red. Plant the same in `catalog_plugins.py` too, since the split added that file.
- Text from files must hold no U+0000 or lone surrogate. Strict UTF-8 decoding and expat (TASK-141) guarantee this; the repository does not re-check it.

## Revision 1 (2026-10-27): `retired_among` for #100 (a)

The user widened #100 (a) (decisions 2026-10-27), so the store has to know which of a file's plugins were retired before the import changed anything. The lead asked for one additive function. It is specified in `work/plans/TASK-151.md` §3.4 step 0 and §4.

| File | Change | Non-blank lines now |
| --- | --- | --- |
| `manager/bitscan_manager/repositories/catalog_plugins.py` | added `retired_among` | 132 (was 118) |

- `retired_among(conn, plugin_uuids) -> frozenset[UUID]` returns those of the given ids whose `plugin.state` is `retired`. Ids with no plugin row and active ids are not in the result.
- It is one parameterised SELECT: `SELECT plugin_uuid FROM plugin WHERE state = 'retired' AND plugin_uuid = ANY(CAST(%s AS uuid[]))`. That needs only SELECT on `plugin`.
- Empty input sends no query and returns `frozenset()`.
- The store calls it before step 1, because the displaced-policy delete retires plugins in the same transaction (plan §3.4 step 0).
- No other function changed; `current_plugins` is as before.
- Gates (CI form): `ruff check manager`, `ruff format --check manager` (270 files) and `mypy --strict --config-file manager/pyproject.toml manager` (270 files) are clean, with no `noqa`.

For the tester:
- Given a mix of retired, active and unknown uuids, only the retired ones come back.
- Empty input returns an empty set, and the statement log shows no query.
- It works as `bitscan_app`.
- Plants: drop the `state` filter (active ids come back), invert it, or remove the empty-input guard (still correct, but the "no query" row goes red). The S608 f-string plant applies to this function too.
