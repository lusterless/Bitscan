# TASK-147 TEST: PASS (revision 1 included)

Tester: tester-m7, 2026-10-27. REQ-161, REQ-178; TS §4.1 "Locking"; design note D4. Checks CHK-M7-140 to -145, plants CHK-M7-372 to -374 plus extra plants (tests/m7/test-plan.md). Test file: `manager/tests/test_catalog_lock_pg.py` (17 tests). Waiting is observed through `pg_locks` (a not-granted row for the waiter's backend), never by sleeping for order. Each nested-session row runs its body in a worker thread joined with a timeout, so a self-deadlock fails instead of hanging.

## Runs (W = WSL 24.04, `CI=true`, `-n 0`, one PostgreSQL 16 container, leftover-own 0)

| Run | Command | Count |
| --- | --- | --- |
| r0 (label m7t-t147) | `pytest tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py` | 43/43 passed (13 + 30), 0 failed, 0 skipped |
| r1 (label m7t-t147r1, after the nested-session guard) | same files plus `tests/test_imports_repo_pg.py` | 69/69 passed (17 lock + 30 pool/runtime + 22 imports), 0 failed, 0 skipped |
| static (L) | `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | clean, 248 files |

## Checks

| Check | What | Result |
| --- | --- | --- |
| CHK-M7-140 | of two sessions the second waits (seen in `pg_locks`) until the first releases; order a_in, a_out, b_in; a session also waits for a holder in another process (a raw connection, as a CLI would) | PASS |
| CHK-M7-141 | two transactions in one session keep the lock throughout (held between them, while idle), on the same backend pid | PASS |
| CHK-M7-142 | released when the block raises, when a transaction inside raises (the session stays usable), when the connection is closed inside the block, and when the backend is terminated (`pg_terminate_backend`) | PASS |
| CHK-M7-143 | session-level lock on the `hashtext('catalog')` key (bigint form, `objsubid` 1), taken while idle outside a transaction, and the only advisory lock the backend holds | PASS |
| CHK-M7-144 | the connection goes back clean: `max_size=1` pool, a stray `pg_advisory_lock(42)` released, `autocommit` False, 0 advisory locks; existing pool and runtime tests pass; nesting refused (savepoint outside a transaction, transaction in transaction, `db.transaction()` in a session transaction, `db.session()` in `db.transaction()`); a rolled-back savepoint drops its rows **and its on-commit hooks**, and the hooks run only after COMMIT (rows visible to another connection inside the hook); an unreachable database gives `DatabaseUnavailable` with no DSN text and no chained cause | PASS |
| CHK-M7-145 | `Runtime` and the new Protocols under `mypy --strict` (CI form) | PASS |
| r1 rows | a nested `db.session()` inside `session()` + `catalog_lock` raises RuntimeError (no deadlock); the outer session's transaction still works, the lock is free and its connection goes back clean (0 advisory locks); a nested session without the lock is refused too; another thread can open a session while one is open; a session opens again after a normal exit and after an error | PASS |

## Plants (throwaway copies, imported first through PYTHONPATH)

| Plant | Red |
| --- | --- |
| CHK-M7-372 unlock not in `finally` | 2 failed (block raises; transaction raises) |
| CHK-M7-373 `pg_advisory_xact_lock` instead of the session lock | 5 failed |
| CHK-M7-374 another key (`hashtext('catalog2')`) | 6 failed (incl. the other-process holder) |
| `catalog_lock` a no-op (the TASK-147 half of CHK-M7-356) | 6 failed |
| savepoint keeps a rolled-back savepoint's hooks | 1 failed |
| session release skips `pg_advisory_unlock_all()` | 1 failed (connection back clean) |
| r1: nested-session guard removed | 3 failed (2 caught as a deadlock by the bounded worker, 1 DID NOT RAISE), no hang |

Note (not a finding): `pg_advisory_lock` waits without a bound (no timeout in TS §4.1), as the impl report says. TASK-160's stop path has to account for a waiter.

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-140..145 | APP | W | `pytest -q -n 0 tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py` (m7t-t147) | PASS | 43/43 passed (13 + 30), 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-140..145-r1 | APP | W | same plus `tests/test_imports_repo_pg.py`, after r1 (m7t-t147r1) | PASS | 69/69 passed (17 lock incl. 4 nested-session rows + 30 + 22) | 2026-10-27 |
| CHK-M7-145 | CODE | L | `mypy --strict --config-file manager/pyproject.toml manager` | PASS | no issues, 248 files | 2026-10-27 |
| CHK-M7-372 | APP | W | plant: unlock not in finally | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-373 | APP | W | plant: pg_advisory_xact_lock | PASS (red) | 5 failed | 2026-10-27 |
| CHK-M7-374 | APP | W | plant: key hashtext('catalog2') | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-356 (147 half) | APP | W | plant: catalog_lock a no-op | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-147-sp | APP | W | plant: savepoint keeps rolled-back hooks | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-147-rel | APP | W | plant: session release skips pg_advisory_unlock_all | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-147-nest | APP | W | plant r1: nested-session guard removed; `-k 'nested or another_thread or opens_again'` | PASS (red) | 3 failed (2 as deadlock via the bounded worker, 1 DID NOT RAISE); no hang | 2026-10-27 |

## Revision 2 (session transactions run with autocommit off; found through TASK-152)

New rows in `test_catalog_lock_pg.py` (20 tests now):
- `test_audit_append_inside_a_session_transaction`: an audit append inside `session.transaction()` under `catalog_lock` succeeds; the entry is invisible before COMMIT and visible after; a rolled-back session transaction leaves no entry.
- `test_between_transactions_the_session_is_autocommit_and_idle` (reviewer rows 1 and 2): after a commit and after a rollback, `autocommit` is True and the status IDLE; `catalog_lock` then takes the lock while idle, session-level.
- `test_commit_failure_closes_the_connection_and_the_pool_replaces_it` (reviewer row 4): the backend is terminated inside the transaction, so COMMIT fails with `DatabaseUnavailable`; the session's connection is closed or broken; the next pooled connection (`max_size=1`) is a new backend with autocommit False and 0 advisory locks.
- Reviewer row 3 is the existing `test_connection_goes_back_clean`, which still passes.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-140..145-r2 | APP | W | `pytest -q -n 2 tests/test_catalog_lock_pg.py tests/test_db_pool_pg.py tests/test_runtime.py tests/test_policy_delete_pg.py tests/test_audit_append_pg.py` (m7t-t147r2) | PASS | 77/77 passed, 0 failed, 0 skipped (20 lock + 30 pool/runtime + 11 delete + the M2 audit append tests) | 2026-10-27 |
| CHK-M7-147-ac | APP | W | plant: `autocommit = False` removed in `transaction()` | PASS (red) | 8 failed (`AuditError` in the audit row and in the delete tests) | 2026-10-27 |
| CHK-M7-147-rs | APP | W | plant: `_restore_autocommit()` removed | PASS (red) | 2 failed (`test_between_transactions…`: autocommit False; `test_released_when_a_transaction_inside_raises`: ProgrammingError) | 2026-10-27 |

Verdict after revision 2: **PASS**.
