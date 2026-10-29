# TASK-147 REVIEW: catalog lock on a pinned session

Verdict: APPROVED (revision 2)

Reviewer: reviewer-m7, 2026-10-27. REQ-161, REQ-178. High risk (importer; TS §8.2 two approvals: this is the first). It changes M2 code in `db/pool.py` and `runtime.py`. **r2 needs a fresh user second approval in the W2 batch** (r1 had one).

Scope reviewed: `git diff` of `manager/bitscan_manager/db/pool.py` (+131/−10 after r2), `manager/bitscan_manager/runtime.py` (+19), and the new `manager/bitscan_manager/repositories/catalog_lock.py` (31 lines), per `work/reports/TASK-147-impl.md` (r1 and r2 sections). That is 3 files, within the row. The M2 change is limited to moving `_unavailable` and the hook loop to module helpers; `AppDatabase.transaction()` behaves as before.

TEST: PASS, r0, r1 and r2 (`work/reports/TASK-147-test.md`).
- r2 run: 77/77 (20 lock, 30 pool and runtime, 11 TASK-152 delete, and the M2 audit-append tests).
- Planted faults all turned it red:
  - CHK-M7-372 to -374, a no-op lock, kept savepoint hooks, a skipped `pg_advisory_unlock_all`;
  - r1: the guard removed (the bounded worker caught the deadlock, and nothing hung);
  - r2: `autocommit = False` removed (8 failed, `AuditError`) and `_restore_autocommit()` removed (2 failed).
- The phase rows are in the test report, not in `tests/m7/report.md`, which the harness blocks for the tester (main, 2026-10-27).

Spec read: TS §4.1 "Locking" (L526); `database.md` "Locks"; design note D4; `work/plans/TASK-154.md` §2; `repositories/audit_log.py` `_check_transaction` (M2).

## Checks
1. **Lock (TS §4.1).**
   - `catalog_lock` takes the session-level `pg_advisory_lock(hashtext('catalog'))` in autocommit, with the connection idle, and unlocks in `finally`.
   - If the unlock fails, the connection is closed, which ends the lock.
   - The SQL is constant and lives in `repositories/`.
   - The tests see the lock, and the waiter, through `pg_locks`, including a holder in another process (the CLI case).
2. **Pinned session.**
   - One pooled connection serves several transactions in a row; nesting is refused.
   - BEGIN or COMMIT failures give `DatabaseUnavailable` with no driver text chained. Errors from the caller's own statements keep their type.
   - Hooks run only after COMMIT. A rolled-back savepoint drops the hooks registered inside it.
3. **r2: real transactions inside the session.**
   - `transaction()` turns autocommit off before `BEGIN`, so the body runs in a READ COMMITTED transaction (the pool's `configure`). The strict M2 audit guard therefore accepts appends there; the guard is not loosened.
   - `_restore_autocommit()` runs in `finally`, after COMMIT or ROLLBACK, so `catalog_lock` between transactions runs on an idle, autocommit connection. The tests check this after a commit and after a rollback.
   - psycopg sets autocommit only on an IDLE connection and raises `ProgrammingError` otherwise. The restore catches that and closes the connection, so a broken or non-idle connection never stays in the session or reaches the pool in the wrong mode. A COMMIT failure (backend terminated) closes it, and the pool hands out a new backend with autocommit off and 0 advisory locks.
   - `savepoint()`, the nested-session guard and `release()` are unchanged.
4. **Pool returned clean.**
   - `release()` runs `pg_advisory_unlock_all()` and sets `autocommit = False`; on any failure it closes the connection.
   - psycopg_pool does not reset autocommit and discards a closed connection (I checked the pinned 3.x source).
   - The test with `max_size=1` sees the same connection come back non-autocommit with 0 advisory locks.
5. **r1: no nested sessions.** A per-instance `ContextVar` guard (`pool.py:209`) refuses a nested `session()` in the same context, which would otherwise wait on its own lock for ever. Other threads are not affected.
6. **Security.**
   - Log lines carry only exception type names.
   - The unreachable-database test finds no DSN canary in the error.
   - There is no new route, flag or setting.
7. **Re-run by me (Windows):** ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` are clean on product code. The one mypy error is in tester-m7b's in-progress `manager/tests/test_bit102_lexer.py:517` (TASK-145), not this task. I relied on the tester's WSL runs for PostgreSQL.

## Findings
1. should-fix, `pool.py:198` (r0): a nested `AppDatabase.session()` was not refused, so a self-deadlock with no bound was possible. **Closed by r1** (guard and four test rows, red when planted out).
2. Defect found through TASK-152 (r1): session transactions ran with `conn.autocommit` True, so `PgAuditRepo` refused every audit append in a catalog session. **Closed by r2** (autocommit off in the transaction, restored when idle, closed on failure; rows and plants above).
3. nit, `catalog_lock.py:22`: it does not itself check that the session is outside a transaction. With r2 the connection is idle in autocommit at every point where the callers take it.
4. nit, `pool.py:176`: each `AppDatabase` creates a `ContextVar` that is never freed. It is harmless at the few instances `serve` and the tests create.
5. Carried to TASK-160 (decisions 2026-10-27): a waiter on the lock holds a pooled connection and cannot be interrupted, and `ServeLifecycle.stop` must account for that (builder checklist 10).
