# TASK-025 IMPL report: runtime contract and the app database pool

REQ: REQ-044, REQ-055, REQ-056 (contract parts). Spec: TS §2.1 L103 (one manager instance), TS §2.3 L118 (internal steps use DB credentials), TS §5.3 L1049 (`bitscan_app`), L1051 (audit lock needs a real transaction). Plan: `work/plans/TASK-025.md`.

## Files (2)

- `manager/bitscan_manager/runtime.py`: new, 50 non-blank lines.
- `manager/bitscan_manager/db/pool.py`: new, 114 non-blank lines.

## `runtime.py` (exactly the plan's interface)

- **Protocols:**
  - `Clock.now()`: timezone-aware UTC;
  - `Tx`: `conn` property and `on_commit(hook)`;
  - `Database`: `transaction()` returns a context manager of `Tx`, plus `ping()`;
  - `TotpCipher.encrypt/decrypt`;
  - `SinkGate.refusing/wake`;
  - `RateLimits.allow_login/allow_user/failed_check_blocked/record_failed_check`;
  - `Lifecycle.start/stop` (async).
- **`SystemClock`:** returns `datetime.now(UTC)`.
- **`Runtime`:** a frozen dataclass with fields `clock, db, totp_cipher, sink_gate, limits, lifecycle=None`.
- **`get_runtime(request)`:** returns `request.app.state.runtime`. If it is missing or not a `Runtime`, it raises `HTTPException(503, "The service is not ready.")`, which TASK-026 turns into a problem body.

## `db/pool.py`

- **`AppDatabase(dsn: SecretStr, *, min_size=1, max_size=10, connect_timeout_s=5.0)`** wraps `psycopg_pool.ConnectionPool` with these settings:
  - `open=False`, name `bitscan_app`;
  - `kwargs={"autocommit": False, "connect_timeout": max(1, int(connect_timeout_s))}`;
  - `configure` sets `IsolationLevel.READ_COMMITTED`;
  - `timeout=connect_timeout_s` for acquiring a connection.

  The DSN goes in only as `conninfo`. `AppDatabase` has no custom `repr`, and the pool's `repr` shows only its name.
- **`open()`** attaches a scrub filter to the `psycopg.pool` logger. It then calls `pool.open(wait=False)`, so start-up does not wait for the database or fail when it is down; the pool retries in the background, and later requests grow it again. **`close()`** closes the pool and removes the filter. The filter rewrites each record's message through `db.scrub()` with `db.dsn_secrets()` (M1), so neither the DSN nor its password can appear in a log record.
- **`transaction()`** is a context manager yielding a `Tx`: it takes a pooled connection and opens `conn.transaction()` (BEGIN … COMMIT).
  - **Commit:** after the commit, the hooks run in order. A hook that raises is logged at ERROR with its exception type only, and the remaining hooks still run. The commit stands.
  - **Rollback:** if the body raises, the transaction rolls back, no hook runs, and the body's exception propagates unchanged. This includes a `psycopg.OperationalError` raised by the caller's own statement.
  - **Database unreachable:** a failure to get a connection (`PoolTimeout`, `PoolClosed`, `OperationalError`) or to commit raises `DatabaseUnavailable("database unavailable: <type>: <scrubbed message>")`. It is raised outside the `except` block, so `__context__` and `__cause__` are both `None` and the driver error is not chained.
  - **Nesting:** a nested `transaction()` on the same thread raises `RuntimeError`. Nesting would silently open a second connection.
- **`ping()`** runs `SET LOCAL statement_timeout = '2s'; SELECT 1` in its own transaction. It returns `False` on any error and never raises.
- Not done here: `create_app(runtime)` and its lifespan (TASK-044), routing the pool logger through the JSON log handler (TASK-027), and reading `BITSCAN_MIGRATE_DSN_FILE` (never read here).

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 57 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 535 passed, 222 skipped (pg), 97.63 % |
| Scratch script (deleted): DSN to `127.0.0.1:1` with a canary password, `connect_timeout_s=1` | `transaction()` raised `DatabaseUnavailable` after 1.0 s, with no canary and no `__context__`/`__cause__`; `ping()` returned `False`; the canary was not in any captured log record (pool warnings included) |
| Scratch: fake pool | hooks ran in order after commit; a raising hook was logged with its type only and the hooks after it still ran; no hook ran after a body exception; a nested call raised `RuntimeError`, and the next transaction worked |
| PostgreSQL (`session_user = bitscan_app`, READ COMMITTED, audit append through `PgAuditRepo(tx.conn)` commits) | NOT RUN (no Docker here); TP-M2-03 in WSL |

## For the tester (TP-M2-03)

- `AppDatabase(SecretStr(dsn))`, then `.open()`, then `with db.transaction() as tx:` with `PgAuditRepo(tx.conn)` and `append_entry(...)`; call `.close()` at the end. `SHOW transaction_isolation` inside gives `read committed`, and `tx.conn.autocommit` is `False`.
- For the unreachable-database canary, set a small `connect_timeout_s` so the test is fast. The default is 5 s.
- For a `Runtime` built from fakes under `mypy --strict`, any objects with the Protocol methods will do. Use `lifecycle=None`.

## Revision 1 (tester round 1, CHK-M2-036: `ping()` hung on a paused server)

**Cause.** `SET LOCAL statement_timeout` is enforced by the server. A paused or silent server never answers on an already-open pooled connection, so `ping()` blocked indefinitely. libpq has no client-side read timeout. Keepalives and `tcp_user_timeout` would not help either: a paused container's kernel still ACKs.

**Fix.** `ping(timeout_s=PING_TIMEOUT_S)` (2 s) now never blocks longer than `timeout_s` and never raises. It works like this:
- It probes from a **daemon thread on its own connection, outside the pool**: `psycopg.connect(dsn, autocommit=True, connect_timeout=2, options="-c statement_timeout=2000")`, then `SELECT 1`.
- The caller waits at most `timeout_s` with `join(timeout_s)`. It gets `True` only if the probe finished with success in time.
- **At most one probe is in flight.** While an earlier probe is still stuck, `ping()` returns `False` at once rather than starting another thread. A stuck server therefore costs one thread and one socket, never a pooled connection.
- The DSN is kept as the `SecretStr` and unwrapped only for the probe's connect call. No exception from the probe leaves the thread.

Why not through the pool: a probe that is stuck holding a pooled connection would take capacity from real requests, and it would still need the thread to bound the wait.

**What bounds a normal `transaction()` when the server stops answering.**
- Getting a connection is bounded by `connect_timeout_s` (the pool timeout and libpq `connect_timeout`); the result is `DatabaseUnavailable`.
- A statement on an already-open connection has no client-side bound. It waits for the server-side `statement_timeout` (none is set for the app role) or for TCP to fail. A paused server can therefore block a request indefinitely, and a dead host until kernel TCP retransmission gives up (about 15 min on Linux defaults).
- If the lead wants a bound, two options:
  - libpq `keepalives` plus `tcp_user_timeout` in the pool kwargs, which covers a dead host but not a paused one;
  - a per-statement `statement_timeout` for the app role, which covers a slow server but not a silent one.

  Either is a TASK-045 or settings decision, not done here.

Scratch check (deleted afterwards). Against a TCP listener that accepts and never speaks:
- `ping()` returned `False` in 2.0 s;
- a second call, with the first probe still connecting, returned `False` in 0.0 s;
- after the first probe ended, a new probe started and returned `False` in 2.0 s.

ruff and mypy `--strict` are clean.

**For the tester.** `test_runtime.py::test_ping_runs_a_bounded_select_and_never_raises` encodes the old design: ping through the pool with `SET LOCAL`. It now fails, because `ping()` no longer uses the pool. Please re-target it at `psycopg.connect` (monkeypatch `bitscan_manager.db.pool.psycopg.connect`) or at the real driver. The nested-transaction case now returns the probe's result, because the probe uses its own connection rather than a nested `transaction()`. The other 17 unit tests pass.
