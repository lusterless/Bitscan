# TASK-261 IMPL: retention indexes and scan chunk (M11 gate fix round)

Implementer: impl-manager-b, 2026-11-11. Decision: `work/decisions.md`, 2026-11-11 "User decisions: retention indexes and G39" (1). Spec: the owner-approved TS §5.2 change `68d3881`, at L893–L894 (`ix_job_scan` and `ix_job_retry_of` after `ix_job_pending`) and L943 (`ix_reeval_job` after `scan_result_reeval`). The finding it fixes: CHK-M11-387 (`work/reports/CHK-M11-387-test.md`), plus the reviewer's gate review for `SCAN_CHUNK`. REQ-275, REQ-278 (3) (grants unchanged), #151. High risk: it touches the migrations. Full rigor, plus the user's second look (pre-authorised on clean results).

## Files (+43 / −2)

1. `manager/bitscan_manager/db/migrations/versions/m0006_retention_indexes.py` (new, 36 lines). Revision `m0006`, `down_revision = "m0005"`, in the m0003/m0004 style:
   - a `STATEMENTS` tuple holding the spec lines in order with the SQL comments removed (and the whitespace before them; the spec's alignment spaces inside `ix_job_scan     ON` are kept verbatim);
   - `upgrade()` runs each through `op.execute`;
   - `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

   ```sql
   CREATE INDEX ix_job_scan     ON scan_job(scan_id);
   CREATE INDEX ix_job_retry_of ON scan_job(retry_of);
   CREATE INDEX ix_reeval_job ON scan_result_reeval(job_id);
   ```

   - **Grants:** none. An index takes its table's owner (`bitscan_owner`, as `db migrate` runs `SET ROLE bitscan_owner` through the unchanged `env.py`) and needs no privilege of its own. The table grants of m0005 are untouched.
   - **Locking:** plain `CREATE INDEX`, not `CONCURRENTLY`, exactly as the spec writes it; it also can't run concurrently inside Alembic's transaction. That briefly blocks writes on `scan_job` and `scan_result_reeval` during `db migrate`; the measured build time was 0.5–2.0 s at 10,000 hosts (CHK-M11-387 report). Migrations run with the manager stopped (runbook §1 upgrade order).
2. `manager/bitscan_manager/services/retention/rules.py` (+3 / −1): `SCAN_CHUNK` goes from 100 to **12**, with a comment naming TASK-261 and CHK-M11-387. Nothing else in the rules changes.
   - The reason: with the indexes, a backlog chunk of 100 fleet-wide scans was estimated at about 20–27 min against the 300 s `statement_timeout` (each fleet scan measured 10.8–17.9 s). 12 fleet scans then take about 130–215 s.
   - tester-m11t re-measures to confirm the value.
3. `README.md` (+1 / −1), §Retention, "Batches": "100 scans" becomes "12 scans". README is manager-area (TASK-252); no other README line names the chunk size or the migration head.

## Not changed, routed

- **`deploy/runbooks/manager-operations.md` §6 L280 (impl-deploy's area, not mine)** says "100 scans", and that deleting scans and inventory jobs on a large database "is slow, because the schema has no index on the columns those deletes check; this is a known limit of this version". Both become wrong with this task. I've sent the lead the replacement text to route to impl-deploy:
  - "12 scans";
  - drop the "no index … known limit" sentence. It could read "On a large database the scans and inventory-job deletes use the indexes added by migration `m0006`."
- **Comments now stale in frozen files** (not edited; "no other change", and these files are frozen for M11). Each says these columns have no index, which is now false: `repositories/results.py` L7, `repositories/scan_progress.py` L7, `repositories/scan_reads.py` L10, `repositories/job_intake.py` L115. They don't affect behaviour. The query plans may now use the indexes, which is the intent. Listed for the lead to decide.

## For the testers: test files that pin what this task changes (tester-owned; not edited)

- `manager/tests/test_retention_rules.py` L41 pins `(SCAN_CHUNK, JOB_CHUNK, ROW_CHUNK, AUDIT_CHUNK) == (100, …)`. The new value is 12.
- `manager/tests/test_security_m11.py`:
  - `FROZEN_DIRS` includes `db/migrations/versions`, "no file added", so the new `m0006` turns it red by design. The decision lifts the M11 "no migration" rule for this one file.
  - The m0001–m0005 hashes stay valid: those files are byte-unchanged.
- `e2e/m6/ops_walk.sh` L110 pins `[ "$head" = m0005 ]`. The head is now `m0006`. `deploy/tests/test_manager_wheel.sh` L175 and `e2e/m6/manager_walk.py` L593 derive the head from the files, so they need no change.
- `manager/tests/test_retention_pg.py` L583 and L613 use `rules.SCAN_CHUNK` symbolically, so they follow the new value. With 12, the stranding row is 13 locked scans plus those behind them.
- G19 (the schema diff) now expects the three indexes from the TS §5.2 DDL.
- `test_db_migrate.py`'s bind-trap scan: the new statements contain no `:`.
- CI: `manager.yml`'s "Migrations are forward-only, at most one added" sees exactly one added file.

## Plants suggested (full rigor; one per part)

| Part | Plant | Must turn red |
| --- | --- | --- |
| Migration | drop one of the three statements (for example `ix_reeval_job`) | G19 schema diff; CHK-M11-387 (the cascade seq-scans again) |
| Migration | a wrong column (`ix_job_scan ON scan_job(agent_id)`) | G19 |
| Migration | an extra `GRANT DELETE ON scan_job TO bitscan_app` in `STATEMENTS` | the grant probes (TP-M11-22, G19) |
| Migration | a `downgrade()` that drops the indexes | the forward-only checks |
| Chunk | `SCAN_CHUNK` back to 100 | `test_retention_rules.py` (as updated); CHK-M11-387's backlog-chunk row over 300 s |

## Checks run (Windows, venv of the main checkout, run against this worktree)

- `ruff check` and `ruff format --check` on both Python files: clean. `mypy --strict` on both: no issues.
- Alembic `ScriptDirectory` over `manager/bitscan_manager/db/migrations`: heads `['m0006']`, chain `m0006 → m0005 → m0004 → m0003 → m0002 → m0001`.
- No migration, `db migrate` or PostgreSQL run here. Those are the testers': tester-m11g (the retention suites, G5, G18, G19) and tester-m11t (CHK-M11-387 on the real migration).

## Builder checklist

| Item | How it is met |
| --- | --- |
| 1 and 2 | don't apply: no client input or version compare |
| 10, 20 | unchanged: the retention loop is the same, only the chunk constant moves |
| 11 and 12 | nothing new is logged |
| 13 | doesn't apply: no OpenAPI change |
| 15 | doesn't apply: no pip step; the new module is inside the `migrations/versions` package, so the wheel ships it like m0001–m0005 |

## Runbook part (impl-deploy, 2026-11-11)

File: `deploy/runbooks/manager-operations.md`, one line changed (§6 "Batches", L280). No other file.

- "100 scans" becomes "12 scans" (`rules.SCAN_CHUNK = 12`).
- The known-limit sentence ("deleting scans and inventory jobs is slow, because the schema has no index …; this is a known limit of this version") is replaced with: "On a large database, the scan and inventory-job deletes use the indexes that migration `m0006` adds (on the scan and retry columns of `scan_job`, and on the job column of `scan_result_reeval`)". Those are `ix_job_scan`, `ix_job_retry_of` and `ix_reeval_job` in `m0006_retention_indexes.py`.
- §1 checked: it names no revision id. It says only that the migrate log "ends with the new head revision id", which holds for `m0006`. §4's restore test compares against "the live database's last migration", which also holds. Neither names `m0005`, so they are unchanged.
- §8 (results CSV memory) is unchanged.
- §1 to §7 keep their block order. §1's four blocks are as before, and the edit touches no sh block.

Check: `python -I deploy/tests/check_runbook_text.py deploy/runbooks/manager-operations.md` gives `OK 1 files, 24 sh blocks, 0 findings`. `grep` finds no "100 scans", no "no index" and no `m0005` left in the file.
