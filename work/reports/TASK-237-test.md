# TASK-237 TEST: PASS

Tester: tester-m11b, 2026-11-08. High risk, full rigor: a plant for every security row, boundary and race. REQ-275, REQ-278 at repository level; TP-M11-06 and TP-M11-22. TS §5.3 L1049, L1051; TS §5.2 L996–L1006 (grants) and the ON DELETE CASCADE chain; #150 (a)–(g), (j), (k); both lead corrections of 2026-11-08 (the tokens probe on `user_token.created_at`; no row lock in `scan_chunk`). Code under test: `bm/repositories/retention.py` (sha256 `fab299016750c02c…`), impl-manager-b, `work/reports/TASK-237-impl.md`.

Test files (new):
- `manager/tests/test_retention_repo_pg.py`. TASK-237 part: CHK-M11-135 to -140, -142 to -144; the TASK-238 rows are in `TASK-238-test.md`. 22 functions, 29 items in all.
- `manager/tests/test_retention_grants_pg.py`. TP-M11-22, CHK-M11-150 to -154: 8 functions, 12 items.

Each repository test starts from emptied retention tables (`TRUNCATE … CASCADE` as owner, never a superuser), so row counts are exact. The inputs are `m.aged_world`: rows labelled inside, at the cutoff, 1 µs past it, and far past, relative to the real current instant. The expected survivors come from TS §5.3 and #150, not from the code.

## Runs (W, `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest -n 0 tests/test_retention_repo_pg.py tests/test_retention_grants_pg.py` | 39/40 passed, 1 failed, 0 errors, 0 skipped. The failure was a test bug: `test_sequence_usage_only_on_the_audit_sequence` listed sequences through `information_schema`, which hides the ones the caller has no right on. |
| 2 | `pytest -n 0 tests/test_retention_grants_pg.py::test_sequence_usage_only_on_the_audit_sequence`, after the fix (`pg_class`) | 1/1 passed |
| 3 | `pytest -n 0 …::test_undecided_request_stays_even_with_a_decided_at …::test_specific_keeps` (new row for plant -401) | 2/2 passed |
| 4 | both files again, `-n 2`, on the final tree | 41/41 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` on both files | clean |

No product bug found.

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-135 | `test_retention_repo_pg.py::test_each_delete_removes_exactly_the_rows_past_its_cutoff[4 deletes]`, `::test_specific_keeps`, `::test_undecided_request_stays_even_with_a_decided_at`, `::test_at_most_one_chunk_per_call[5]`, `::test_packages_only_unreferenced`, `::test_refuses_a_naive_cutoff_and_a_chunk_below_one` | PASS | As `bitscan_retention`, each delete with `now − age` removes exactly "past" and "old"; "at the cutoff" and "inside" stay. Inventory jobs: compliance jobs and unfinished jobs stay. Requests: pending ones stay, and so does one with an old `decided_at` but no decision. Tokens: past, old and revoked-past go; 89 days, revoked-not-expired and the live API token stay. Packages: only the two unreferenced go. The other rules' rows and the `NEVER_DELETED` checksums are unchanged (`os_info`, `agent_package` included). `n = 1` removes one row per call, then 0. A naive cutoff or `n < 1` raises `ValueError`. |
| CHK-M11-136 | `::test_scan_chunk_oldest_first_at_most_n_no_row_lock` | PASS | ids of scans with `created_at <` cutoff, oldest first; ties are ordered by `scan_id`; at most `n`. While the retention transaction is still open, another session locks the same rows with `FOR UPDATE NOWAIT`, so no row lock is held, and no transaction id is taken. |
| CHK-M11-137 | `::test_delete_scans_removes_whole_scans_only`, `::test_delete_scan_whose_partitions_were_dropped` | PASS | One statement (spy) removes the 2 expired scans, their 4 originals and retries, the results in two partitions, and the re-evaluation rows. The 399-day scan and the scan at 400 days are whole. A scan whose two result partitions were dropped (#44) still goes with its jobs. An empty list or an unknown id gives 0. |
| CHK-M11-192 (repository part) | `::test_scans_step_runs_as_bitscan_retention` | PASS | Lead correction (b): chunk, then `try_reeval_lock` per scan, then `delete_scans`, all in one transaction as `bitscan_retention`, with no error; 2 deleted, "inside" and "at" kept |
| CHK-M11-138 | `::test_try_reeval_lock`, `::test_try_reeval_lock_refuses_autocommit` | PASS | **Race.** False while another session holds M8's lock, taken by M8's own `reeval.lock_scan`; true for a different scan; true again after release. While the retention transaction holds the lock, M8's `lock_scan` in another session waits and times out (`lock_timeout` 300 ms); after rollback it gets the lock. An autocommit connection raises `RuntimeError`. |
| CHK-M11-139 | `::test_newest_per_probe_column`, `::test_newest_unknown_table_raises_before_sql` | PASS | None on empty tables. `scan.created_at` max; inventory-only `scan_job.finished_at` (a compliance job finished 2 days ahead is not probed); `collected_at`; `decided_at`. **`user_token.created_at`** gives now − 65 d, the live tokens' creation, not their `expires_at` of now + 300 d. `audit_log`, `agent`, an injection string, `SCAN` and `""` raise `ValueError` with no statement run. |
| CHK-M11-140 | `::test_db_now_is_the_transaction_clock` | PASS | equals `SELECT now()` in the same transaction; aware; stable within the transaction; within 1 min of the real clock |
| CHK-M11-142 (TASK-237 part) | `::test_bitscan_app_is_refused_every_delete` | PASS | As `bitscan_app`, all six deletes (scans, inventory jobs, snapshots, requests, tokens, packages) raise `InsufficientPrivilege`. Checksums of the nine retention tables are unchanged. The reads (`db_now`, `newest`, `scan_chunk`, `try_reeval_lock`) work with SELECT. |
| CHK-M11-143 | `::test_tokens_91_days_deleted_89_kept_with_a_live_api_token`, `::test_token_probe_decides_the_tokens_step` | PASS | **Lead's row:** with a live API token expiring in 300 days present, the probe does not skip (`future_rows` false). The token expired 91 days ago is deleted; the one expired 89 days ago and the live one stay. **Lead's row:** a token whose `created_at` is 2 days ahead makes `future_rows(newest("user_token"))` true, so the tokens step is skipped; once it is removed, false again. The service-level skip is TASK-242's CHK-M11-189. |
| CHK-M11-144 | `::test_statements_parameterised_select_or_delete_only` | PASS | All 18 statements are from `bitscan_retention` and are SELECT or DELETE only. They contain no INSERT, UPDATE or DDL word and no `FOR UPDATE`/`FOR SHARE`. No scan id or cutoff date appears in the SQL text. |
| CHK-M11-150 | `test_retention_grants_pg.py::test_delete_exactly_on_the_nine_tables`, `::test_select_on_every_table` | PASS | Over every public table (partitions excluded), DELETE is allowed on exactly the nine. DELETE is refused (`42501`) on `agent`, `policy`, `agent_package`, `os_info`, `enrollment_token`, `setting`, `family`, `plugin`, `policy_plugin`, `scan_schedule`, `system_schedule`, `app_user`, `task`, `bit_import`, `agent_tag` and `agent_ip_seen`. SELECT works on every table. |
| CHK-M11-151 | `::test_insert_only_on_audit_log_and_no_update_anywhere`, `::test_sequence_usage_only_on_the_audit_sequence` | PASS | INSERT is refused on every table but `audit_log`; a checkpoint-shaped insert is allowed. UPDATE is refused on every table. `nextval` works only on `audit_log_audit_id_seq`; every other sequence gives `42501`. |
| CHK-M11-152 | `::test_no_row_lock_on_scan[FOR UPDATE, FOR UPDATE SKIP LOCKED, FOR NO KEY UPDATE, FOR SHARE, FOR KEY SHARE]` | PASS | **Lead's row:** the plan's chunk form with each locking clause is `42501` as `bitscan_retention`; the same SELECT without the clause works |
| CHK-M11-153 | `::test_a_new_partition` | PASS | A partition created after the migration (2099-01) holds a result. `bitscan_retention` deletes it through the parent (1 row, rolled back) and can read the partition. `bitscan_app` gets `42501` for DELETE and UPDATE through the parent, the default partition and the new partition. The row remains. |
| CHK-M11-154 | `::test_no_ddl`, `::test_probe_connection_is_not_a_superuser` | PASS | `42501` for DROP and DETACH of a partition, TRUNCATE of `scan`, `audit_log` and a partition, `ALTER TABLE … ADD COLUMN`, `CREATE TABLE` and `CREATE INDEX`; the partition still exists. The role is not a superuser and has no CREATEROLE, CREATEDB or BYPASSRLS. |

## Plants (throwaway copies; log `/root/m11t/logs/plants-237.jsonl`; plants `/root/m11t/plants-237.json`, `plants-237b.json`)

TASK-237 and TP-M11-22: 29 plants (24 + 5), 29 red, 0 survived (no copy left behind). The TASK-238 plants are in its report.

| Plant | Fault | Red tests (count failed) |
| --- | --- | --- |
| CHK-M11-394 | tokens probe back on `expires_at` | `newest` row, the token-probe row, the 91/89-day row (3) |
| CHK-M11-395 | `FOR UPDATE SKIP LOCKED` back in `scan_chunk` | scan chunk, scans step, statements (3): permission denied |
| CHK-M11-396 (×5) | `<=` instead of `<`, for scans, inventory jobs, snapshots, requests and tokens in turn | each rule's boundary row (3, 2, 2, 2, 2) |
| CHK-M11-350 | pending requests deleted by `requested_at` | requests row, specific keeps (3) |
| CHK-M11-401 | `delete_requests` without `decision IS NOT NULL` | the undecided-with-`decided_at` row (1); without that row the plant is equivalent, see Notes |
| CHK-M11-402 | `delete_inventory_jobs` without `kind = 'inventory'` | inventory row, specific keeps (3) |
| CHK-M11-341 | retention deletes `agent_package` rows | packages rows (4): refused by the grants |
| CHK-M11-354 | a scan's jobs deleted, the scan row kept | whole-scan rows (3) |
| CHK-M11-355 | the re-evaluation lock not tried (always true) | lock row (1) |
| P237-lock-wrong-key | another advisory key than M8's | lock row (1) |
| P237-lock-session-level | `pg_try_advisory_lock` (session) instead of xact | lock row (1) |
| P237-lock-autocommit-allowed | autocommit guard removed | (1) |
| CHK-M11-369 | DDL in a delete (`DROP TABLE … scan_result_default`) | whole-scan row (4): refused, not owner |
| P237-chunk-ignored-tokens / -packages | `LIMIT n + 5` | one-chunk rows (1 each) |
| P237-chunk-order | chunk ordered by `scan_id` only | chunk row (1) |
| P237-unknown-table | unknown probe table composed instead of refused | (1) |
| P237-naive-cutoff / P237-chunk-zero | input guards removed | (1 each) |
| CHK-M11-345 | f-string SQL in `retention.py` | `ruff check`: S608 (G1) |
| P22-update-column-on-scan | a throwaway migration grants `UPDATE (state) ON scan` | all 5 lock clauses, because locks become possible (5) |
| P22-delete-agent-package | DELETE on `agent_package` granted | nine-tables row (1) |
| P22-update-audit-log | UPDATE on `audit_log` granted | no-update row (1) |
| P22-insert-scan | INSERT on `scan` granted | insert-only row (1) |
| P22-other-sequence | USAGE on the re-evaluation sequence granted | sequence row (1) |

## Acceptance (TASK-237: "PostgreSQL as bitscan_retention: each delete removes exactly the rows past the cutoff it is given, at most one chunk per call, a scan whose lock another session holds is skipped, and as bitscan_app every delete is refused by the grants")

- Exact rows: CHK-M11-135 and -137.
- One chunk per call: CHK-M11-135.
- Lock held by another session gives false, so the scan is left out: CHK-M11-138. The skip itself is the service's (TASK-242, CHK-M11-193).
- `bitscan_app` refused: CHK-M11-142.
- The lead's three rows: CHK-M11-143 (both) and CHK-M11-152.

## Notes

- `delete_requests` relies on `decision IS NOT NULL`. The DDL does not tie `decided_at` to `decision` (TS §5.2 L775–L777), so I added a row with an old `decided_at` and no decision. Without it, dropping the clause would be an equivalent mutant on every row the app writes.
- The package-prune race (#150 (f)) and the stop flag are service-level (TASK-242: CHK-M11-195, -197). The repository holds no state between calls.
- #151 measurement (CHK-M11-387) is for the gate.
