# TASK-150 REVIEW: catalog admin repository

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-165, REQ-167, REQ-168, REQ-169. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/repositories/catalog_admin.py` (206 non-blank lines, of which about 60 are #98 row types) and `manager/bitscan_manager/repositories/catalog_integrity.py` (46), per `work/reports/TASK-150-impl.md`. The split into two files is the lead's (decisions 2026-10-27) and stays one task.

TEST: PASS (`work/reports/TASK-150-test.md`, 24 tests as `bitscan_app`; scans, jobs and schedules written as owner). These planted faults turned it red:
- CHK-M7-337 in both files, CHK-M7-365 and CHK-M7-381 to -384;
- `set_status` without the override (it also turns the D3 race red);
- the integrity owner check and the rejected-outcome check.

Spec read: TS §4.3 L546–L551, §4.2 L542; §5.2 DDL (`m0001`, `m0003_scanning.py`: `scan`, `scan_job`, `scan_schedule`), `v_plugin` and grants (`m0005` L51–L70); #9, #14, #98 (a) and (b), #103, #104.

## Checks
1. **Never DELETE on `policy`.** The soft delete is a conditional UPDATE (`deleted_at IS NULL`; builder checklist 8). It sets `deleted_at`, sets `source_file` to `deleted/<id>`, moves `updated_at`, and keeps the statuses, the version and `status_overridden` (#14).
2. **Delete effects (REQ-167 (1), TS §4.3 L550).**
   - Only the policy's `queued` compliance jobs, retries included, become `cancelled` with `finished_at`. That is within the column grant (`state`, `finished_at`).
   - Enabled schedules are disabled.
   - Active plugins it owns or lists, and that no live policy lists, are retired (#104 (b)).
   - The `policy_plugin` rows are kept (#104 (a)).
   - Nothing else is touched: no agent, inventory or result table. Scan-state derivation stays M9 (coverage matrix).
3. **D3 override.**
   - `set_status` sets `policy_status` and `status_overridden = true`; `clear_override` restores `file_status` and clears the override (TS §4.3 L548).
   - Both refuse a deleted row, and move `updated_at` only on a real change (#104 (d)).
   - `lock()` gives the row re-read under `FOR UPDATE` for the services (checklist 9).
   - The race test shows a file UPDATE that waits on an uncommitted PATCH keeps the override.
4. **List and detail (#9, #98).**
   - The list holds non-deleted rows only, filtered by effective status, with keyset paging on (`policy_name`, `policy_id`).
   - The item and plugin fields are in the #98 (a) and (b) order.
   - The detail reads the policy and its plugins in one statement (one snapshot), with `display_name` from `v_plugin`, never stored.
   - Hostile text round-trips byte-identical through the JSON aggregation, and timestamps stay exact under any session time zone.
5. **Integrity reads (#103).** They are read-only and cover the non-deleted policies; `bad_plugins` counts a listed plugin that is not active or is owned by another policy. `rejected_files` is one query over arrays.
6. **SQL.** Constant strings or `psycopg.sql` composition of constant fragments; S608 is clean. Re-run by me: ruff, ruff format and mypy (CI form) are clean.

## Findings
None blocking or should-fix.

1. Carry to TASK-161 (not this diff): `list_page`'s keyset `after` (a name and an id) comes from a client cursor and is cast to `varchar` and `bigint`. TASK-161 must decode and validate it before the cast: no U+0000 or lone surrogates, and the id inside the bigint range (builder checklist 1). Otherwise a crafted cursor gives a 500.
2. nit, `catalog_admin.py:150`: `detail()` reaches plugin fields by position (`p[1:12]`, `p[12]`) from `json_build_array`. That is correct and tested, but it is fragile if a column is added. `json_build_object` with named keys would be self-describing. Optional.
