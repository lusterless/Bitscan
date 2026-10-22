# TASK-025 plan: runtime contract and the app database pool

REQs: REQ-044, REQ-055, REQ-056. Owner: impl-manager. Depends on: TASK-023 (`psycopg-pool`). Files: `bm/runtime.py`, `bm/db/pool.py` (`bm/` = `manager/bitscan_manager/`). Tests: TP-M2-03.

Why a plan: this is the contract that TASK-030, TASK-034, TASK-036, TASK-037, TASK-038 and TASK-044 are written against, in parallel waves. Changing it later forces changes in all of them.

## Spec quotes

- TS §2.1 L103: the scheduler runs "inside the manager process (one manager instance in v1)". In-memory state (rate limits, pending TOTP enrolment, #49) is therefore acceptable.
- TS §2.3 L118: "Steps inside the manager use database credentials, never a user or agent token."
- TS §5.3 L1049: "`bitscan_app` (API and scheduler) gets read and insert on every table by default … and update or delete only where §5.2 grants it explicitly."
- TS §5.3 L1051: "every insert takes `pg_advisory_xact_lock(hashtext('audit_log'))`" (the M1 `PgAuditRepo` refuses autocommit and any level but READ COMMITTED).

## Interface (`bm/runtime.py`)

```python
class Clock(Protocol):
    def now(self) -> datetime: ...          # timezone-aware, UTC

class SystemClock:                           # the only real Clock
    def now(self) -> datetime: ...

class Tx(Protocol):
    @property
    def conn(self) -> psycopg.Connection[Any]: ...
    def on_commit(self, hook: Callable[[], None]) -> None: ...   # run after COMMIT, never after rollback

class Database(Protocol):
    def transaction(self) -> AbstractContextManager[Tx]: ...     # READ COMMITTED, not autocommit
    def ping(self) -> bool: ...                                   # for /readyz; never raises

class TotpCipher(Protocol):                  # implemented by TASK-030 (vault, #24)
    def encrypt(self, seed: bytes) -> str: ...
    def decrypt(self, ciphertext: str) -> bytes: ...

class SinkGate(Protocol):                    # implemented by TASK-034
    def refusing(self) -> bool: ...          # True after 15 min of outage until drained (REQ-054)
    def wake(self) -> None: ...              # an audit entry was committed; ship soon

class RateLimits(Protocol):                  # implemented by TASK-036
    def allow_login(self, ip: str) -> bool: ...
    def allow_user(self, user_id: int) -> bool: ...
    def failed_check_blocked(self, ip: str) -> bool: ...
    def record_failed_check(self, ip: str) -> None: ...

class Lifecycle(Protocol):                   # implemented by serve (TASK-045): pool, shipper, flusher, SIGHUP
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

@dataclass(frozen=True)
class Runtime:
    clock: Clock
    db: Database
    totp_cipher: TotpCipher
    sink_gate: SinkGate
    limits: RateLimits
    lifecycle: Lifecycle | None = None       # None in tests and the OpenAPI export

def get_runtime(request: Request) -> Runtime: ...   # reads request.app.state.runtime; 503 problem if absent
```

`create_app()` gains `runtime: Runtime | None = None` in TASK-044 (the first route that needs the database), stored on `app.state.runtime`, with a lifespan that awaits `runtime.lifecycle.start()` and `.stop()` when a lifecycle is set. The OpenAPI export keeps calling `create_app()` with no runtime; routes resolve the runtime only when a request arrives.

## `bm/db/pool.py`

```python
class AppDatabase:                           # implements Database
    def __init__(self, dsn: SecretStr, *, min_size: int = 1, max_size: int = 10,
                 connect_timeout_s: float = 5.0) -> None: ...
    def open(self) -> None: ...               # called by serve (TASK-045); does not fail if the DB is down
    def close(self) -> None: ...
    def transaction(self) -> AbstractContextManager[Tx]: ...
    def ping(self) -> bool: ...
```

- `psycopg_pool.ConnectionPool(open=False, kwargs={"autocommit": False})`, with a `configure` callback that sets `conn.isolation_level = IsolationLevel.READ_COMMITTED`. The DSN goes in as `conninfo`, never into a log record or exception.
- `transaction()`: take a connection, `with conn.transaction():` yield a `Tx`; collect hooks; after the `with` exits without error, run the hooks in order; a hook that raises is logged (type only) and does not undo the commit. On error: no hooks, re-raise.
- Errors from the pool or driver are re-raised as one `DatabaseUnavailable` error whose message passes through `bm/db.scrub()` with `dsn_secrets()` (M1), so neither the DSN nor its password can appear (REQ-039 canary).
- The `psycopg.pool` logger is routed through the JSON log handler (TASK-027) at WARNING; its messages are scrubbed the same way (a logging filter in this module).
- `ping()`: `SELECT 1` with `statement_timeout` 2 s, inside its own short transaction; returns False on any error.

## Edge cases

- The on-commit hook list is per transaction; nested use of `transaction()` is not supported (raise if called while one is open on the same thread, to avoid a silent second connection that would see uncommitted state differently).
- Pool size: 10 is a starting value for M2 (no agents yet); the M6 load test (10,000 heartbeating agents) will tune it.
- `bitscan_retention` gets no pool in M2: the retention task is M11. `ServeConfig.retention_dsn` stays loaded but unused.
- Nothing here reads `BITSCAN_MIGRATE_DSN_FILE`.
