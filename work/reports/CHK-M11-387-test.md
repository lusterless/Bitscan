# CHK-M11-387: retention chunk cost at fleet size (#151)

tester-m11t, 2026-11-09. Tree: `m11-results` at `c090303`. HEAD is now `c62da73`, but the retention code, the repositories, the pool, `serve.py` and the spec are unchanged since then (`git diff --stat c090303 HEAD` is empty for them). Gate items: `work/decisions.md`, 2026-11-08, "Gate item: the retention chunk against `statement_timeout`", and the lead's requests of 2026-11-09 (options (1) to (4)).

## Verdict: FAIL as the v1 limit. This is a finding for the user, not a product bug

The product code works as specified, and no code or setting was changed. But at fleet size, two retention steps cannot finish one chunk inside the inherited `statement_timeout` of 300 s, so they delete nothing, every night:

- **Inventory jobs:** one 1,000-job chunk takes **407 s** uncapped (data set A) and about 497 s (data set B). Under the real pool it is cancelled at 300.0 s.
- **Scans:** any scan of more than about **600 hosts** cannot be deleted in 300 s, even as a chunk of one scan. That scan is the oldest eligible one, so it heads every later chunk and the step never moves on. Halving `SCAN_CHUNK` (the user's 2026-11-09 remedy) does not help: the cost is per deleted **job**, not per scan.

The cause is the three missing indexes of #151. For each deleted `scan_job` row, PostgreSQL makes one full sequential scan of `scan_job` (the `retry_of` self-reference check) and one of `scan_result_reeval` (the `job_id` cascade). On this host that costs 0.41 to 0.50 s per job. With the three indexes, created on the test database only, the same chunks take 0.25 to 18 s, and a full nightly pass takes 25 to 33 s.

The snapshots, requests, tokens, audit (with checkpoint) and packages steps fit easily, at 0.03 to 1.7 s per chunk.

## Method

- WSL Ubuntu-24.04 with `CI=true`, in its own folder `/root/m11timing` and its own hashed venv (`pip install --require-hashes -r manager/requirements-dev.txt`, then the tree installed editable).
- PostgreSQL 16.15 from the test image `bitscan-test-postgres:16-d38e4c141225`, TLS on.
- The TS §5.2 Bootstrap ran through the harness (`tests.conftest._run_bootstrap`), then the real `bitscan-manager db migrate` to head `m0005`. There were 0 audit rows after the migration.
- Data was written as owner (`bitscan_migrate` with `SET ROLE bitscan_owner`), never as a superuser after the bootstrap. `VACUUM (ANALYZE)` ran after each bulk load, as autovacuum would.
- Every timed delete ran as `bitscan_retention`, through the real repository functions, on a pool built as `serve` builds it: `AppDatabase(bounded_dsn(...), min_size=0, max_size=1)`. Checked on the pool: `current_user = bitscan_retention`, `statement_timeout = 5min`, not a superuser.
- **One chunk** is one `db.transaction()` holding exactly the body of `task.py`'s loop:
  - scans: `scan_chunk(cutoff, 100)`, then `try_reeval_lock` per scan, then `delete_scans`;
  - inventory jobs: `delete_inventory_jobs(cutoff, 1000)`;
  - snapshots, requests, tokens and packages: their `delete_*` with 10,000;
  - audit: `lock_chain`, `oldest(10000)`, `audit_prefix`, `append_entry(audit.checkpoint)`, `delete_through`.
  Each time is wall time, commit included.
- **Full pass:** the real `run_retention(db, now, shipped_through=<max audit id>)`. Per-step times come from its own "retention step done" log lines.
- **Uncapped:** `EXPLAIN (ANALYZE, BUFFERS)` of the real statement as `bitscan_retention`, with `SET LOCAL statement_timeout = 0`, then rolled back.
- **Indexes for option (b):** `CREATE INDEX` on `scan_job(retry_of)`, `scan_job(scan_id)` and `scan_result_reeval(job_id)` on the throwaway database only (lead, 2026-11-09). They were dropped again before stage B was grown, and created again for B-idx.
- **Host:** Intel Core Ultra 7 155U (14 vCPU), WSL2 capped at 4 GB and shared with tester-m11g's concurrent full suite. The container was capped at 1.4 GB, with `shared_buffers` at 128 MB (the image default).
- Script and logs, outside the tree: `C:\Users\kaiquan.koh\Documents\m11t-timing\m11t.py` and `...\m11t-timing\logs\` (`results.jsonl`, `explain-*.txt`). The container has been removed. No `bs[uaek]_` value appears in any log (checked).

## Data set

The planning model is scaled from TS §7 L1196 (10,000 hosts × 2,000 packages) and the seeded schedules (inventory every 21,600 s). TS gives no scan frequency or plugin count, so these are my assumptions:

- a 200-plugin policy, about the size of CIS Ubuntu 24.04 L1 Server (the samples have 16);
- one fleet-wide scheduled scan per **week** (data set A, the lighter case) or per **day** (data set B);
- 2 % of compliance jobs have one retry;
- one fleet scan re-evaluated once in 400 days;
- one snapshot per host per day (unattended upgrades).

| Table | A (rows, heap) | B (rows, heap) | Notes |
| --- | --- | --- | --- |
| `agent` | 10,000 | 10,000 | |
| `scan` | 2,057 | 2,400 | A: 57 weekly fleet scans plus 2,000 manual single-host scans over 400 days. B: 399 fleet scans (daily) |
| `scan_job` | **1,816,379, 463 MB** (255 B/row) | **5,305,457, 1,125 MB** | Inventory: 1,233,000 (30 days × 4 a day × 10,000, plus a day past the cutoff). Compliance: A 583,379 (11,379 retries); B 4,072,457 (79,457 retries) |
| `scan_result` | 700,000 background, plus each test scan's own | 900,088 | 18 partitions, `2025_10` to `2027_02` plus the default, as `db maintain` keeps them (#44). Each scan being deleted has its full 200 results per job |
| `scan_result_reeval` | 2,000,000 | 2,200,088 | One re-evaluated fleet scan (10,000 × 200) |
| `inventory_snapshot` | 1,830,000 (40,000 past the cutoff) | 1,790,000 | 180 days × 10,000 |
| `enrollment_request` | 22,100 (20,100 past) | 2,000 | |
| `user_token` | 50,200 (30,200 past) | 20,000 | |
| `audit_log` | 1,100,000 (41,000 older than 3 years) | 1,059,005 | A valid chain, COPY-loaded through `m11_pg_fixtures.audit_chain` |
| `package` / `agent_package` | 81,000 (31,000 unreferenced) / 2,000,000 | 50,000 / 2,000,000 | |
| Database | 2,373 MB | 4,727 MB | |

**Scaled down, and by how much:**

- **`scan_result` background:** 50,000 rows per partition, against hundreds of millions in production. This only changes the depth of the per-partition primary-key probes in the results cascade: 3.6 to 8.3 ms per job without indexes, negligible beside the sequential scans. The deleted scans' own results are at full size.
- **`agent_package`:** 2 M rows, 10 % of TS §7's 20 M. This affects the packages step only (0.4 s).
- **Background compliance payloads:** `payload` and `eval_spec` are 18-byte JSONB placeholders, the inline width of a TOAST pointer, so the heap width is realistic (255 B per row). The scans being deleted use the real TS §6.5 payload and eval_spec of the 200-plugin policy (TOASTed), so their TOAST deletion is included.

## Timings, one chunk, against `statement_timeout` 300 s

Values are median / max over the repetitions (n). "Cancelled" means `QueryCanceled` at 300.0 s under the real pool.

| Step and chunk | A, as built | B, as built | A, three test indexes | B, three test indexes |
| --- | --- | --- | --- | --- |
| scans: 100 single-host scans (100 to 105 jobs, 20,000 results) | 107.7 / 108.3 s (3) | 132.5 / 138.5 s (3) | 0.28 / 0.35 s (3) | 0.42 / 0.56 s (3) |
| scans: 1 scan × 1,000 hosts (about 1,020 jobs, 200,000 results, 200,000 re-evaluation rows) | **cancelled in 4 of 4 reps** (note 1); uncapped **481.3 s** | not run (A is already over) | 0.86 / 0.96 s (2) | (in the full pass) |
| scans: 1 scan × 10,000 hosts (about 10,210 jobs, 2.0 M results) | **cancelled** inside the full pass (below); uncapped about 80 min, estimated (note 2) | uncapped about 85 min, estimated | 16.05 / 17.87 s (2) | 11.80 / 12.84 s (2) |
| inventory jobs: 1,000 | **cancelled** (1); uncapped **407.2 s** | **cancelled** (1); uncapped about 497 s (a 100-job run took 49.7 s) | 0.49 / 1.19 s (3) | 0.28 / 1.03 s (3) |
| snapshots: 10,000 | 0.08 / 0.12 s (3) | | | |
| tokens: 10,000 | 0.04 / 0.06 s (3) | | | |
| requests: 10,000 | 0.05 / 0.06 s (2) | | | |
| audit: 10,000 plus checkpoint | 0.12 / 0.15 s (3) | | | |
| packages: 10,000 | 0.42 / 0.45 s (3) | | | |

**Index build time** (option (b)'s migration cost here): 1.6, 0.7 and 0.5 s at A (12.4, 12.2 and 14.4 MB); 1.9, 2.0 and 0.9 s at B (37.0, 35.7 and 14.4 MB). The extra write cost on `scan_job` inserts was not measured.

### Full `run_retention` passes (one day's backlog)

| Pass | Backlog | Result |
| --- | --- | --- |
| A, as built | 22 scans (one fleet scan, one 1,000-host scan, 20 manual; 11,227 jobs), 43,000 inventory jobs, 10,000 snapshots, 100 requests, 200 tokens, 11,000 audit entries, 1,000 unreferenced packages | **602.6 s.** **scans FAILED** after 300.1 s (`QueryCanceled`), 0 deleted. **inventory_jobs FAILED** after 300.3 s, 0 deleted. snapshots 10,000 in 1.65 s; requests 100 in 0.04 s; tokens 200 in 0.03 s; audit 11,000 (2 chunks) in 0.34 s; packages 1,000 in 0.10 s |
| A, three test indexes | the same 22 scans (11,227 jobs) and 40,000 inventory jobs (the small steps were already empty) | **33.0 s.** scans 22 in 1 chunk, 25.95 s; inventory 40,000 in 40 chunks, 5.72 s; the rest 1.3 s |
| B, three test indexes | 22 scans (one fleet scan; 11,246 jobs), 40,000 inventory jobs | **25.4 s.** scans 12.57 s; inventory (40 chunks) 11.65 s; the rest 1.1 s |

A full pass at B as built was not run. A already shows both steps failing, and B's per-job cost is higher.

## Where the time goes: `EXPLAIN (ANALYZE, BUFFERS)`, uncapped

A, 1,000-job inventory chunk (the real `delete_inventory_jobs` statement):

```text
Delete on scan_job  (actual time=1007.849..1007.868 rows=0 loops=1)
  Buffers: shared hit=12609 read=27070 dirtied=38
  ->  Nested Loop  (actual time=387.587..993.715 rows=1000 loops=1)
        ->  ... Seq Scan on scan_job scan_job_1  (rows=1000; Rows Removed by Filter: 1100187)
        ->  Index Scan using scan_job_pkey on scan_job  (loops=1000)
Trigger for constraint scan_job_retry_of_fkey: time=238362.510 calls=1000
Trigger for constraint scan_result_job_id_fkey: time=3641.600 calls=1000
Trigger for constraint scan_result_reeval_job_id_fkey: time=164158.095 calls=1000
Execution Time: 407176.133 ms
```

A, one 1,000-host scan (the real `delete_scans` statement); the delete itself takes 4 ms:

```text
Delete on scan  (actual time=4.416..4.427 rows=0 loops=1)
Trigger for constraint scan_job_scan_id_fkey on scan: time=373.118 calls=1
Trigger for constraint scan_job_retry_of_fkey on scan_job: time=278841.502 calls=1019
Trigger for constraint scan_result_job_id_fkey on scan_job: time=8497.756 calls=1019
Trigger for constraint scan_result_reeval_job_id_fkey on scan_job: time=193621.645 calls=1019
Execution Time: 481345.123 ms
```

The same statement with the three test indexes (1,022 jobs): `retry_of` 183.5 ms, `scan_result` 543.6 ms, `reeval` 115.9 ms, `scan_id` 93.5 ms; **Execution Time 940 ms**.

The query each trigger call runs, without indexes. It is a full sequential scan every time; inside the trigger it runs single-threaded, because `FOR KEY SHARE` prevents parallelism:

```text
-- SELECT 1 FROM ONLY scan_job x WHERE retry_of = $1   (A; run directly, so parallel)
Parallel Seq Scan on scan_job x (actual time=606.218..606.219 rows=0 loops=3)
  Filter: (retry_of = '...'::uuid)   Rows Removed by Filter: 605799
  Buffers: shared hit=7685 read=51565
-- SELECT 1 FROM ONLY scan_result_reeval x WHERE job_id = $1
Parallel Seq Scan on scan_result_reeval x (loops=3)  Rows Removed by Filter: 733359
-- SELECT 1 FROM scan_result x WHERE job_id = $1  -> Index Only Scan on each partition's PK, 5.7 ms
```

Per trigger call, from these plans:

| RI trigger, per deleted row | A inventory (1,000) | A scan (1,019) | B inventory (100) | A scan, indexed (1,022) |
| --- | --- | --- | --- | --- |
| `scan_job_retry_of_fkey` (seq scan of `scan_job`) | 238.4 ms | 273.6 ms | 385.0 ms | 0.18 ms |
| `scan_result_reeval_job_id_fkey` (seq scan of re-evaluations) | 164.2 ms | 190.0 ms | 106.0 ms | 0.11 ms |
| `scan_result_job_id_fkey` (PK probes, every partition) | 3.6 ms | 8.3 ms | 4.4 ms | 0.53 ms |
| `scan_job_scan_id_fkey`, per deleted scan | | 373 ms | | 93 ms |
| **per deleted job** | **0.407 s** | **0.472 s** | **0.497 s** | **0.9 ms** |

The cost is linear in the number of deleted jobs: every call is one full scan, and the three sizes measured (100, 1,000 and 1,019 jobs) agree. The largest chunk that fits in 300 s without indexes is about 740 jobs (A) and about 600 jobs (B). It falls as `scan_job` grows, and `scan_job` grows by 40,000 rows a day while the inventory step fails.

## Nightly retention time at steady state

One day's backlog is 40,000 inventory jobs (10,000 hosts, every 6 h), plus the day's compliance jobs: one fleet scan of about 10,200 jobs per week (A) or per day (B). The small steps take under 3 s together.

| | A (weekly fleet scan) | B (daily fleet scan) |
| --- | --- | --- |
| As built (300 s) | **never completes.** Both the scans and inventory steps fail on their first chunk, and `scan_job` grows 40,000 rows a day | the same |
| No indexes, timeout lifted (estimate: per-job cost × jobs) | inventory 40,000 × 0.407 s = 4.5 h; plus the fleet scan 10,200 × 0.472 s ≈ 80 min one night in 7. **About 4.5 h, or 5.9 h on the fleet-scan night** | inventory 40,000 × 0.497 s = 5.5 h; plus the fleet scan ≈ 85 min (note 2). **About 6.9 h a night** |
| Three indexes (measured full pass) | **33.0 s** | **25.4 s** |

## Options for the user

| Option | Change needed | One fleet-scan chunk (1 × 10,000 hosts) | One 1,000-job inventory chunk | Nightly time (steady state) | Fits 300 s? |
| --- | --- | --- | --- | --- | --- |
| (a) As built: no indexes, 300 s | none | cancelled at 300 s (true time about 80 to 85 min, estimated) | cancelled at 300 s (true time 407 s at A, about 497 s at B) | never completes; nothing is deleted from scans or inventory jobs | **No** |
| (a1) Halve `SCAN_CHUNK` (the 2026-11-09 remedy) | a constant | unchanged: one scan of more than about 600 hosts is over 300 s even at `SCAN_CHUNK` = 1 | unchanged | as (a) | **No** |
| (a2) Smaller `JOB_CHUNK` (about 300) | a constant | not addressed: a scan's jobs go in the scan's one statement (TS §5.3 "deleted together") | about 120 to 150 s per 300 jobs (estimated) | inventory 4.5 to 5.5 h; scans still blocked by any scan of more than about 600 hosts | inventory only |
| (b) The #151 indexes: `scan_job(retry_of)`, `scan_job(scan_id)`, `scan_result_reeval(job_id)` | TS §5.2 edit and one migration (builds in 0.5 to 2.0 s here, 12 to 37 MB) | **10.8 to 17.9 s** | **0.25 to 1.19 s** | **25 to 33 s** (measured) | **Yes** at steady state. A backlog chunk of 100 fleet scans would take about 20 to 27 min (estimated: 100 × 12 to 16 s) and would not. With (b), `SCAN_CHUNK` would have to be about 12 or less to bound that case |
| (c) No indexes; lift `statement_timeout` for the retention session only | a retention-pool setting | about 80 to 85 min (estimated) | 407 s (A, measured); about 497 s (B, estimated) | about 4.5 to 5.9 h (A), about 6.9 h (B), estimated; grows with fleet size and scan frequency | n/a: the bound would have to be at least about 1.5 h per fleet-scan chunk, and each chunk holds its transaction and locks that long |

## Notes and limits

1. **A labelling slip of mine.** In the A as-built run, the two reps labelled "1 scan × 10,000 hosts" ran on the 1,000-host scan. That scan was still eligible after its own two cancelled reps, so my builder did not add the fleet scan. They are counted above as reps 3 and 4 of the 1,000-host scan (both cancelled at 300.0 s). The fleet scan was then built for the A full pass, whose scans chunk (22 scans, 11,227 jobs) was cancelled at 300.1 s. The builder was fixed before the indexed and B runs, which did time the 10,000-host scan.
2. **Estimates.** The uncapped fleet-scan chunk (about 85 min) was not run, to save time. It is extrapolated from the per-job costs above, which are linear because every trigger call is one full scan. B's compliance per-job cost uses B's inventory per-job cost (the same two sequential scans). I can run the real uncapped fleet chunk (about 1.5 h) on request.
3. **Hardware and cache.** The sequential scans read mostly from the OS cache (`shared read`), with a 1.4 GB container cap and `shared_buffers` 128 MB. The same re-evaluation scan took 164 ms (A) and 106 ms (B), so treat per-call costs as ±40 %. A production server with more memory and a faster core might be up to about 2× faster per scan (my estimate, not measured). That would put the inventory chunk near 300 s, not well under it, and the per-job cost still grows with `scan_job`.
4. **Assumptions:** the scan frequency, the plugin count (200), the 2 % retry rate and one re-evaluated fleet scan are mine (TS is silent). The re-evaluation cascade cost scales with the size of `scan_result_reeval`.
5. Nothing in the tree was edited. The test indexes existed only on the throwaway database, which has been removed.
