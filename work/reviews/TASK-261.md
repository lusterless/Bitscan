# TASK-261 REVIEW: retention indexes (m0006) and scan chunk 12 (M11 gate fix round)

Reviewer: reviewer-m11, 2026-11-11. Round 1. High risk (migration); the user's second look is pre-authorised.

Verdict: APPROVED

**Scope reviewed**
- Product: `manager/bitscan_manager/db/migrations/versions/m0006_retention_indexes.py` (new) and `manager/bitscan_manager/services/retention/rules.py` (`SCAN_CHUNK` 100 → 12).
- Docs: `README.md` §Retention and `deploy/runbooks/manager-operations.md` §6 "Batches".
- Tester changes: `test_retention_rules.py`, `test_retention_pg.py`, `test_security_m11.py` and `e2e/m6/ops_walk.sh`.

**Checked against**
- The owner-approved TS §5.2 change `68d3881` (L893, L894, L943).
- `work/decisions.md`, 2026-11-11 (1) and (2), and the stale-comments row.
- CLAUDE.md ("the DDL in TS §5.2 is the schema; Alembic migrations must reproduce it exactly, including grants").
- `.claude/rules/manager/database.md` (forward-only migrations, one per PR).
- `work/reports/CHK-M11-387-test.md`.

**Reports**
- `work/reports/TASK-261-impl.md`.
- The "r1" section of `work/reports/M11-gate-test.md`: PASS. G19 2/2 with 6/6 plants red, retention suites green, G18 11,909/11,909, G5 98.5920 %, G83 46/46.

## Checks

- **The migration reproduces the spec exactly.**
  - `STATEMENTS` holds the three spec lines in spec order with only the `--` comments removed. The spec's alignment spaces (`ix_job_scan     ON`) are kept.
  - `revision = "m0006"` and `down_revision = "m0005"`; Alembic has a single head.
  - There are no grants and no other DDL. An index takes its table's owner (`bitscan_owner` under `SET ROLE` in the unchanged `env.py`), so no grant is needed, and m0005's grants are untouched.
  - `downgrade()` only raises, so the migration is forward-only.
  - G19's schema diff of the migrated database against the new DDL is green. It is red when `m0006` is removed (the true before-state), an index is dropped, a column is wrong, or a GRANT is added.
  - The new G83 row `test_the_m11_migration_is_exactly_the_spec_indexes` compares the migration's SQL strings with the spec lines parsed from the reference DDL. It does not compare against a copy, so it can fail.
- **Plain `CREATE INDEX`:** the spec writes it without `CONCURRENTLY`, and it can't be concurrent inside Alembic's transaction. Migrations run with the manager stopped (runbook §1). The measured build was 0.5 to 2.0 s at 10,000 hosts.
- **`SCAN_CHUNK = 12`:** this follows my gate review. With the indexes, a 100-fleet-scan backlog chunk was estimated at 20 to 27 min; 12 fleet scans at 10.8 to 17.9 s each come to about 130 to 215 s, inside the 300 s timeout. The value is to be confirmed by tester-m11t's re-measurement (gate condition below). No other rule changed, and the retention loop is unchanged.
- **Docs:**
  - The README and runbook now say "12 scans".
  - The runbook's "no index … known limit" sentence, now false, is replaced by one naming `m0006`'s indexes.
  - `check_runbook_text.py` reports 0 findings, and the README walks pass 4/4.
- **Tester changes (PD-51 r1 rows):**
  - The chunk-constant row now pins 12.
  - `test_chunks` expects (250, 21): 20 × 12 + 10.
  - The second-chunk fault row is written in terms of `rules.SCAN_CHUNK`, with a guard that a full second chunk exists. It still pins the deleted count, now via the constants row.
  - The frozen-folder row now allows exactly `m0006`, and m0001 to m0005 stay byte-pinned to `6efe0fb`.
  - `ops_walk.sh` derives the head from the walked tree's files, as `manager_walk.py` does.
  - Every other assertion is kept, and each change is listed old → new.
- **The downgrade plant green in `test_downgrade_functions_raise`:** I accept this. That test only checks that calling `downgrade()` outside Alembic raises, and a planted `op.execute(DROP INDEX …)` raises there too. The plant is red in `test_migration_files_are_forward_only` (the AST rule) and in the new m0006 row, which are the checks meant to catch it.
- **Stale "no index" comments in frozen files** (`results.py`, `scan_progress.py`, `scan_reads.py`, `job_intake.py`): the lead deferred these to after M11 so the frozen pins stay intact. They are comments only, so I agree.
- **Re-run (Windows):**
  - `ruff check`, `ruff format --check` and `mypy --strict` on the two product files and the three test files: clean.
  - `test_security_m11.py` and `test_retention_rules.py` CODE rows: 89 passed. That includes the S608 and `re`-ban rows, which pass on Windows now that `fe0bd24` added `encoding="utf-8"`.
  - I also confirmed the three spec lines in `docs/spec/Technical_Specification.md`.

## Findings

None.
