# TASK-261 REVIEW: retention indexes (m0006) and the scan chunk (M11 gate fix round)

Reviewer: reviewer-m11, 2026-11-11. Round 2 (r1: `SCAN_CHUNK` 12 → 2). High risk (migration); the user's second look is pre-authorised.

Verdict: APPROVED

## Round 2 (r1)

**What changed:**
- `manager/bitscan_manager/services/retention/rules.py`: `SCAN_CHUNK: Final = 2`, with a comment giving the measured reason.
- `README.md` §Retention and `deploy/runbooks/manager-operations.md` §6: "2 scans".
- Tester changes, all listed in the gate report's r1b PD-51 table:
  - `test_retention_rules.py` (pin 2);
  - `test_retention_pg.py::test_chunks` (250 scans in 125 chunks);
  - `test_retention_wiring.py::test_stop_during_a_real_retention_run_gives_up_at_the_next_transaction` (CHK-M11-197).

**Basis:** the lead's decision of 2026-11-11 under the user's standing remedy (decisions 2026-11-09 (3): lower the chunk and re-measure). tester-m11t's interim numbers on the real `m0006` (`work/status.md`, 2026-11-11) are:
- 12 fleet scans per chunk: cancelled at 300 s, in the indexed but I/O-bound `scan_result` cascade.
- 6 fleet scans: 208 to 268 s.
- 3 fleet scans: about 128 s.
- 1 fleet scan: 24 to 25 s.

Choosing 2 rather than 3 gives margin against slower disks. It costs only more chunks, and single-host scans take about 0.1 s a chunk. That is consistent with the numbers.

**Checks:**
- **The constant change:** it adds and removes no statement, so G5 (98.5920 %) stands. The retention loop and the skipped-ids logic are unchanged and still terminate with a chunk of 2: the limit is `2 + len(skipped)`.
- **CHK-M11-197:** the test still pins the stop rule. With the aged world's two expired scans filling a chunk of 2, the scans step commits its first chunk (2 deleted). It then asks for a second transaction, which the stop flag refuses, logging `{step: scans, exc_type: SchedulerStopping}` with `skipped` "failed". Each later step gives up once. No retention statement runs after the stop, and `stop()` returns in under 10 s.
  - The expectation follows `rules.SCAN_CHUNK` through a `full` flag, so both branches stay checked.
  - Every other assertion is unchanged.
- **The plant** (the chunk back to 12) is red.
- **Re-run by the tester:** 210/210 across the retention suites, G83 and the README walks, and 25/25 for the scheduler suites. `check_runbook_text.py` is clean.

**What this approval does not cover:** the fleet-size proof that a chunk of 2 fits, and that a full pass and the 7-night run finish with no step failed. Those are the last condition of `work/reviews/M11-gate.md`, waiting for tester-m11t's CHK-M11-387 r1 report.

**Findings:** none.

## Round 1 (`m0006`, `SCAN_CHUNK` 12)

**Scope reviewed:**
- `manager/bitscan_manager/db/migrations/versions/m0006_retention_indexes.py` (new) and `manager/bitscan_manager/services/retention/rules.py`.
- The README §Retention and runbook §6 lines.
- The tester's changes to `test_retention_rules.py`, `test_retention_pg.py`, `test_security_m11.py` and `e2e/m6/ops_walk.sh`.

**Checked against:**
- the owner-approved TS §5.2 change `68d3881` (L893, L894, L943);
- decisions 2026-11-11;
- CLAUDE.md ("Alembic migrations must reproduce it exactly, including grants");
- `.claude/rules/manager/database.md`.

**Checks:**
- **The migration reproduces the spec exactly:**
  - `m0006` holds the three spec lines in order, with only the comments removed.
  - It follows `m0005`, adds no grant (an index takes its table's owner) and no other DDL, and its `downgrade()` only raises.
  - G19 matches the new DDL. Its plants are red: `m0006` removed (the before-state), one index dropped, a wrong column, an extra GRANT, a downgrade.
  - The new G83 row compares the migration's SQL against the spec lines parsed from the reference DDL.
- **No `CONCURRENTLY`,** as the spec writes the lines. It also cannot be used inside Alembic's transaction. Migrations run with the manager stopped.
- **The downgrade plant** stays green in `test_downgrade_functions_raise`, which accepts any exception. I accept that, because the plant is red in the forward-only AST rule and in the m0006 row.
- **Stale "no index" comments in frozen files** are a post-M11 follow-up, as decisions 2026-11-11 records.
- **Re-run (Windows):**
  - `ruff check`, `ruff format --check` and `mypy --strict` are clean.
  - 89 CODE rows pass.

**Findings:** none.
