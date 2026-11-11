# TASK-237 IMPL: retention repository

Implementer: impl-manager-b, 2026-11-08. REQ-275, REQ-278. Spec: TS §5.3 L1049 (what is deleted and when), L1051 (`bitscan_retention` deletes only from the retention tables); TS §5.2 L861–L940 (cascades: `scan_job.scan_id`, `scan_result.job_id` and `scan_result_reeval.job_id` are `ON DELETE CASCADE`), L1002–L1006 (grants). Open items: #150 (a)–(c), (e)–(g), (j), (k). Plan: `work/plans/TASK-242.md` §3. High risk (the user's second look, PD-47).

## Files (1 new file, about 185 lines)

- `manager/bitscan_manager/repositories/retention.py` (new). Every function runs in the caller's transaction, never commits, and uses parameterised statements only. Each delete removes at most one chunk (`LIMIT %s` in a subquery, or the ids given) and returns its row count. `n < 1` raises `ValueError`, and so does a naive cutoff.

| Function | Statement |
| --- | --- |
| `db_now(conn) -> datetime` | `SELECT now()` |
| `newest(conn, table: ProbeTable) -> datetime \| None` | `SELECT max(<col>) FROM <table>`, from a fixed `MappingProxyType` of five statements composed with `sql.Identifier`: `scan.created_at`, `scan_job.finished_at WHERE kind = 'inventory'`, `inventory_snapshot.collected_at`, `enrollment_request.decided_at`, `user_token.created_at` (see deviation 1). Any other key raises `ValueError`. |
| `scan_chunk(conn, cutoff, n) -> list[UUID]` | `SELECT scan_id FROM scan WHERE created_at < %s ORDER BY created_at, scan_id LIMIT %s`, with no row lock (see deviation 2) |
| `try_reeval_lock(conn, scan_id) -> bool` | `SELECT pg_try_advisory_xact_lock(hashtext('scan_reeval'), hashtext(CAST(CAST(%s AS uuid) AS text)))`. This is M8's `reeval.lock_scan` key exactly. It raises `RuntimeError` on autocommit. |
| `delete_scans(conn, ids) -> int` | `DELETE FROM scan WHERE scan_id = ANY(CAST(%s AS uuid[]))`. The cascades delete the jobs (original and retry: the `retry_of` NO ACTION check runs at the end of the statement), the results in every partition and the re-evaluation rows in the same statement. An empty list returns 0 with no query. |
| `delete_inventory_jobs(conn, cutoff, n)` | `DELETE FROM scan_job WHERE job_id IN (SELECT job_id FROM scan_job WHERE kind = 'inventory' AND finished_at < %s LIMIT %s)` |
| `delete_snapshots(conn, cutoff, n)` | the same pattern on `inventory_snapshot.collected_at` |
| `delete_requests(conn, cutoff, n)` | the same, `WHERE decision IS NOT NULL AND decided_at < %s`. Pending requests are never deleted. |
| `delete_tokens(conn, cutoff, n)` | the same, `WHERE expires_at < %s`, revoked or not (#150 (b)) |
| `delete_packages(conn, n)` | `DELETE FROM package WHERE package_id IN (SELECT p.package_id FROM package p WHERE NOT EXISTS (SELECT 1 FROM agent_package ap WHERE ap.package_id = p.package_id) LIMIT %s)` |

## Deviations from plan TASK-242 §3 (both approved by the lead, 2026-11-08, recorded in `work/decisions.md`)

1. **The future-row probe on `user_token` reads `created_at`, not `expires_at`.**
   - A live token's `expires_at` is always ahead (API tokens up to 365 days), so `future_rows` would skip the tokens step on every run, and REQ-275 (1) and (4) would fail.
   - `created_at` is manager-written (`DEFAULT now()`), like the other four probe columns.
   - The delete cutoff stays `expires_at < now − 90 days`.
2. **`scan_chunk` takes no row lock** (plan: `FOR UPDATE SKIP LOCKED`).
   - PostgreSQL needs UPDATE privilege on at least one column for any row-locking clause, and `bitscan_retention` has none (TS §5.2 L1002–L1006). The plan's form would fail with "permission denied for table scan" on every run.
   - The #150 (k) guard is the per-scan `pg_try_advisory_xact_lock` on the M8 key. The `DELETE` takes its own row locks, so an app transaction holding a lock on a scan or job row more than 400 days old makes the delete wait rather than skip.
   - Retention runs once at a time (`max_instances=1`, TASK-245), so SKIP LOCKED was never needed between retention runs. No `lock_timeout` was added (the lead's answer).

## Behaviour the tester should know

- **Grants.**
  - As `bitscan_retention`: every function works.
  - As `bitscan_app`: every delete is refused (`InsufficientPrivilege`), since the app has no DELETE on `scan`, `scan_job`, `inventory_snapshot`, `enrollment_request`, `user_token` or `package`. The reads (`db_now`, `newest`, `scan_chunk`, `try_reeval_lock`) succeed for the app too; they need only SELECT or no privilege.
- **Boundary.** Every cutoff is compared with `<`, so a row exactly at the cutoff is kept and one 1 µs older is deleted (REQ-274 (1), with TASK-236's `cutoffs`).
- **Re-evaluation lock.**
  - A session holding `reeval.lock_scan(scan_id)` makes `try_reeval_lock` return False in another session; the service (TASK-242) then leaves that scan out of `delete_scans`.
  - A re-evaluation that starts after the delete commits gets the lock, finds no scan row and answers 404 (M8 `lock_scan` returns None).
- **Package race (#150 (f)).** If an inventory upload's `agent_package` insert (an uncommitted FK `KEY SHARE` lock on the package row) overlaps the prune, one side fails:
  - The upload loses: its FK insert fails, it answers 5xx, and the agent retries.
  - The prune loses: its `DELETE` waits, then fails the FK check against the committed `agent_package` row. That chunk rolls back, and TASK-242 logs the step failure. The next run prunes again.

  Nothing is lost either way.
- **What is never touched.** No statement touches `agent`, `os_info`, `agent_package`, `enrollment_token`, the catalog, schedule or setting tables, or any partition (no DDL; partitions stay with `db maintain`).
- **No logging.** Nothing is logged here, and error texts are fixed words.

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check manager && ruff format --check manager`: all checks passed. That includes S608: the only composed SQL is `_newest`, built from `sql.SQL` literals and `sql.Identifier` constants. B008 was fixed with the module constant `_NO_FILTER`.
- `mypy --strict` on the new modules: no issues. The whole-tree run gives the 12 errors already on main, in untouched files (see `TASK-236-impl.md`).
- PostgreSQL tests are the tester's: `manager/tests/test_retention_repo_pg.py` (TP-M11-06) and `test_retention_grants_pg.py` (TP-M11-22), in WSL.

## Builder checklist

- Items 1–3, 5, 6, 13 and 16 don't apply (no client input, version, route, OpenAPI or audit target).
- 9: the lock is tried in the deleting transaction, and the delete is by id. A scan deleted meanwhile is simply not counted.
- 10 and 20: the loops and per-chunk isolation are TASK-242's.
- 11 and 12: nothing is logged, and the error texts are fixed.
