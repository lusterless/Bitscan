# TASK-025 REVIEW: runtime contract and the app database pool

Reviewer: reviewer. Date: 2026-10-21. REQ-044, REQ-055 and REQ-056 (the contract parts). Spec: TS §2.1 L103 (one manager instance), TS §2.3 L118 (internal steps use database credentials), TS §5.3 L1049 (`bitscan_app`), L1051 (the audit lock needs a real transaction). Plan: `work/plans/TASK-025.md`. Inputs:
- `work/reports/TASK-025-impl.md`, including revision 1 (`ping()` hung on a paused server);
- `work/reports/TASK-025-test.md`: PASS (code round 2 on revision 1; Linux mutations in round 3), rows CHK-M2-030 to -037 in `tests/m2/report.md`. All 3 WSL mutants were red; the round-1 pool ping gave `ping() blocked for over 10 s`. A `docker pause` probe gave False in 2.0 s and True after unpause.

Files reviewed: `manager/bitscan_manager/runtime.py`, `manager/bitscan_manager/db/pool.py`.

Verdict: APPROVED

TASK-025 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **Contract (`runtime.py`).** The `Clock`, `Tx`, `Database`, `TotpCipher`, `SinkGate`, `RateLimits` and `Lifecycle` protocols match the plan exactly. `Runtime` is frozen, with `lifecycle` defaulting to None. `get_runtime` answers 503 when no runtime is set, and TASK-026 renders that as a problem body. Only `SystemClock` reads the real time.
- **Transactions (`pool.py:104`).**
  - Connections from the pool are never autocommit and are READ COMMITTED (set by `configure`), as `PgAuditRepo` requires. The tester checked this on PostgreSQL: `session_user` is `bitscan_app`, and an audit append through `tx.conn` commits.
  - Hooks run only after COMMIT, never after a rollback or a failed commit. A hook that raises is logged by its type only, and the hooks after it still run.
  - An error from the caller's own statement propagates unchanged.
  - Nested use on the same thread raises, so a second connection cannot open silently.
- **Secrets.** `DatabaseUnavailable` is built with `db.scrub()` and `dsn_secrets()`, and raised outside the `except` block, so neither the DSN nor its password is in the message or the chain. Messages of the `psycopg.pool` logger are scrubbed while the pool is open. An unparsable DSN shows no part of itself. The tester's canary sweeps covered a closed port, a wrong password and pool log records. The DSN is kept as a `SecretStr`.
- **`ping()`, revision 1 (`:134-:165`).** It probes on its own autocommit connection outside the pool (`connect_timeout` 2 s, `statement_timeout` 2 s) from a daemon thread. The caller waits at most `timeout_s`. If a previous probe is still stuck, `ping()` returns False at once. It never raises.
- **Nothing reads `BITSCAN_MIGRATE_DSN_FILE`.** `bitscan_retention` gets no pool in M2.
- **Gates (my run).** ruff, format and `mypy --strict` are clean. `test_runtime.py` and `test_db_pool_pg.py` give 22 passed and 7 skipped; the skipped ones are pg tests, run in WSL by the tester.
- **Scope.** 2 files, about 190 non-blank lines.

## Findings

None block approval.

1. **note, accepted (the tester's point).** A probe stuck on a silent server keeps one daemon thread and one socket open until the OS gives up on the connection. Later pings return False at once and start no new probe, so nothing builds up, and no pooled connection is held. A single stuck probe is a reasonable cost.
2. **placed in TASK-045 (user decision, decisions 2026-10-21).** A statement on an already-open pooled connection has no client-side bound, so a paused server can hang a request. TASK-045 sets keepalives with `tcp_user_timeout` 300 s and `statement_timeout` 5 min per connection when the pool opens it. Recorded limit: a frozen server whose network still answers is bounded by neither. The TASK-045 review will check this.
3. **nit.** `pool.py:158`: the probe uses `connect_timeout=max(1, int(PING_TIMEOUT_S))`, not the caller's `timeout_s`. If `ping(timeout_s=0.5)` is called, the probe can run up to 2 s after the caller has given up. This is harmless (one probe at a time), but taking the value from `timeout_s` would keep the two in step.
4. **note for TASK-044.** `/readyz` should run its migration and `system_schedule` checks only after `ping()` is True, or give them the same bound. They go through the pooled `transaction()`, which has no such bound, so on a paused server `/readyz` could still hang.
