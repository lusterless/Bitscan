# TASK-147 IMPL: catalog lock on a pinned session

Implementer: impl-manager-m7. REQ-161, REQ-178. Risk high (two approvals). Spec: TS §4.1 "Locking" (L526); `.claude/rules/manager/database.md` "Locks"; design note D4; interface per `work/plans/TASK-154.md` §2.

## Revision 2 (cross-task defect found by tester-m7 in TASK-152's tests)

- **Defect:** `_Session.transaction()` opened its transaction while the pinned connection was still in autocommit. psycopg then sends an explicit BEGIN, but `conn.autocommit` stays True. M2's `PgAuditRepo._check_transaction` (`repositories/audit_log.py`) therefore refused every audit append in a catalog session with `AuditError: audit append needs a transaction, not autocommit`. That blocked delete (TASK-152) and would block the pipeline, rebuild and start-up. My revision-1 checks never appended an audit entry inside a session, so they missed it.
- **Fix (in `pool.py`; the audit guard stays strict):** `transaction()` sets `conn.autocommit = False` before `conn.transaction()`. Inside, it is therefore a real READ COMMITTED transaction, the same as `AppDatabase.transaction()` (the module docstring: "never autocommit, as the audit chain needs"). In `finally`, once COMMIT or ROLLBACK has left the connection idle, a new `_restore_autocommit()` sets autocommit back to True for `catalog_lock()`. If that fails (a broken connection, or one not idle), it logs the type name and closes the connection, as `release()` does, which also ends its session locks. If setting `autocommit = False` raises `OperationalError`, that maps to `DatabaseUnavailable` like a failed BEGIN. `savepoint()`, `catalog_lock()` and the nested-session guard are unchanged. +16 lines.
- **Re-checked** (WSL, my copy `/root/impl-m7`, `CI=true`):
  - A new scratch row inside `session()` + `catalog_lock()` showed:
    - `s.conn.autocommit` is True outside, False inside `transaction()`;
    - `PgAuditRepo(tx.conn).lock_chain()` (which runs `_check_transaction`) passes in the transaction and in a savepoint;
    - `SHOW transaction_isolation` gives `read committed`;
    - autocommit is True again after a commit and after a rollback;
    - the lock is held throughout and free after the session.
  - A connection closed inside a session transaction raises `OperationalError` to the caller, and the next session works.
  - `tests/test_runtime.py`, `tests/test_db_pool_pg.py` and all scratch rows: 33 passed.
  - The tester's `tests/test_catalog_lock_pg.py` together with `tests/test_policy_delete_pg.py` (TASK-152): 28 passed.
- Gates: ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` (270 files) are clean.
- **For the tester:** add an audit-inside-session row: an `append_entry` or `raise_alert` through `PgAuditRepo(tx.conn)` in `session.transaction()` succeeds and commits. Suggested plant: delete the `self._conn.autocommit = False` line, which turns that row red with `AuditError`.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/db/pool.py` | New `_Session` and `AppDatabase.session()`. `_unavailable` and the on-commit hook loop moved to module helpers (`_unavailable`, `_run_hooks`), which both `transaction()` and the session use. `AppDatabase.transaction()` behaves exactly as before. +114 / -10. |
| `manager/bitscan_manager/runtime.py` | New `CatalogSession` and `SessionDatabase` Protocols. `Database` and `Runtime` unchanged (TASK-160 adds `Runtime.catalog`). +19. |
| `manager/bitscan_manager/repositories/catalog_lock.py` | New: `catalog_lock(session)`. 31 lines. |

## Interface (as the TASK-154 plan §2, plus one member)

```python
class CatalogSession(Protocol):
    @property
    def conn(self) -> psycopg.Connection[Any]: ...      # ADDED: autocommit outside transaction(); catalog_lock only
    def transaction(self) -> AbstractContextManager[Tx]: ...
    def savepoint(self) -> AbstractContextManager[None]: ...

class SessionDatabase(Protocol):
    def session(self) -> AbstractContextManager[CatalogSession]: ...

@contextmanager
def catalog_lock(session: CatalogSession) -> Iterator[None]: ...
```

`conn` is the one addition to the plan's shape. `catalog_lock` must run `pg_advisory_lock` in autocommit outside a transaction, and the SQL belongs in `repositories/`, so the lock function needs the pinned connection. planner-m7 has been told.

## Behaviour

- **`AppDatabase.session()`**:
  - takes one pooled connection and switches it to autocommit for the session;
  - raises `RuntimeError` if called inside an open `transaction()` on the same thread;
  - a pool timeout, a closed pool or an `OperationalError` before the body gives `DatabaseUnavailable` (type name only, not chained), as `transaction()` does; errors from the body propagate unchanged.
  - On exit, always (`finally`): `SELECT pg_advisory_unlock_all()` and `autocommit = False`, so a pooled connection never carries a session lock or autocommit back to the pool. If that fails, the connection is closed: the backend ends with its locks, and psycopg_pool discards a closed connection (its `transaction_status` is UNKNOWN).
  - **Revision 1 (before review, reviewer-m7 pre-read via `main`):** a nested `session()` in the same context now raises `RuntimeError("nested AppDatabase.session() is not supported")`.
    - Reason: `catalog_lock` waits without a bound. A nested session taking the lock while the outer session holds it would wait on its own lock for ever and freeze the catalog.
    - The guard is a per-instance `ContextVar[bool]` (`_session_open`). It is set on entry, after the existing in-transaction check, and reset with its token in `finally`, so it clears after a normal exit, a body error and a `DatabaseUnavailable`.
    - It is per context: another thread or asyncio task may open its own session, which then waits on the lock normally.
- **`session.transaction()`**:
  - `BEGIN` ... `COMMIT` on the pinned connection; can be entered any number of times in a row;
  - refuses nesting (`RuntimeError`), including an `AppDatabase.transaction()` opened inside it, which would otherwise take a second connection and fall outside the catalog transaction;
  - BEGIN or COMMIT failures give `DatabaseUnavailable`; body errors roll back and propagate;
  - on-commit hooks run only after COMMIT, through the same `_run_hooks` as `transaction()`.
- **`session.savepoint()`**:
  - only inside an open session transaction (`RuntimeError` otherwise); psycopg's nested `conn.transaction()` gives SAVEPOINT / RELEASE / ROLLBACK TO;
  - **on rollback, the hooks registered inside the savepoint are dropped**, so a rejected rebuild file's on-commit hooks (for example alert counters) never run. That matches plan §7, where the savepoint's entries vanish with it.
- **`catalog_lock(session)`**:
  - `SELECT pg_advisory_lock(hashtext('catalog'))` (constant SQL, no parameters) before the block;
  - `SELECT pg_advisory_unlock(hashtext('catalog'))` in `finally`;
  - if the unlock fails, it logs the type and closes the connection, which ends the lock.
  - Callers must enter it outside any session transaction.

## Acceptance points (scratch checks on PostgreSQL 16, WSL)

I ran a throwaway pytest file in my own WSL copy (`/root/impl-m7`, venv `/root/venv-impl-m7`, `CI=true`, the `migrated_db` fixture, DSN `bitscan_app`). It was deleted afterwards and is not in the tree. All of these held:

1. Of two sessions on two threads, the second waits in `catalog_lock` until the first leaves (order A in, A out, B in; B still waiting 0.5 s after A got the lock).
2. Two transactions in a row inside one session keep the lock throughout (another connection's `pg_try_advisory_lock` is false during and between them). After commit, hooks ran `t1`, `t2`, `kept`; the hook registered in a rolled-back savepoint did not run.
3. The lock is released when the block raises: the next try-lock succeeds.
4. The lock is released when the connection closes inside the block. The session then exits cleanly and the pool replaces the connection.
5. A stray session lock taken directly on `s.conn` is released at session exit. The next 6 pooled `transaction()`s see `autocommit is False` and hold no advisory lock.
6. Nesting is refused: `transaction()` in `transaction()`, `db.transaction()` in a session transaction, `savepoint()` outside a transaction, and `db.session()` inside `db.transaction()`.
7. A rolled-back session transaction leaves the session usable for the next one.
8. (Revision 1) Inside `session()` + `catalog_lock`, a second `db.session()` on the same thread raises `RuntimeError` at once. A session on another thread opens and runs normally while the lock stays held. After a normal exit and after a body error, a new session opens again.

Existing tests (WSL, `CI=true pytest tests/test_runtime.py tests/test_db_pool_pg.py`): **30 passed**. After revision 1, the scratch file and those 30 tests were run again: 32 passed.

`Runtime` from fakes: `Runtime` and `Database` are unchanged. A scratch mypy file (outside the tree) assigned `AppDatabase` to both `Database` and `SessionDatabase` and used `session` / `catalog_lock` / `transaction` / `savepoint`: mypy --strict clean.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager`: All checks passed. `ruff format --check manager`: all formatted.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI command): Success, no issues in 240 source files (248 after revision 1, which includes the other builders' new files).

## Builder checklist

- 10 (stop): `pg_advisory_lock` waits without a bound, as TS §4.1 gives none. A caller waiting on the lock holds one pooled connection and cannot be interrupted until the holder finishes. TASK-160 (`ServeLifecycle.stop`) should stop the workers that may wait on it. No timeout is added here (none is in the spec).
- 11 and 12: log lines carry exception type names only; no DSN, SQL text or values.
- No string-built SQL: three constant statements.

## For the tester (TP-M7-09, `manager/tests/test_catalog_lock_pg.py`)

- Use `AppDatabase.session()` on `migrated_db.dsn("bitscan_app")`. `pg_try_advisory_lock(hashtext('catalog'))` from a separate connection is a simple held / free probe; release it if it returns true.
- The hook-dropping rule of `savepoint()` is new behaviour worth a row.
- Revision 1: add a nested-session refusal row: `db.session()` inside `db.session()` + `catalog_lock` on the same thread raises `RuntimeError`, and a session on another thread still works. Plant: remove the guard (the `_session_open` check and set in `session()`). The nested session then waits on its own lock, so run the row under a timeout (for example the body in a worker thread joined with a timeout); it must fail, not hang the suite.
- "Released when the connection closes": close `session.conn` inside `catalog_lock`. The session exits without raising and the pool discards the closed connection.
- CHK-M7-356 (lock removed) needs TASK-154; on this task alone, the plant to try is making `catalog_lock` a no-op, which turns row 1 red.
