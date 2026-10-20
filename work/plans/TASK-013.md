# TASK-013 plan: Alembic environment, migration runner, `db migrate`

REQ: REQ-020. Owner: impl-manager. Depends on: TASK-011, TASK-012. Files:
- `manager/bitscan_manager/db/__init__.py` (runner)
- `manager/bitscan_manager/db/migrations/__init__.py`
- `manager/bitscan_manager/db/migrations/env.py`
- `manager/bitscan_manager/db/migrations/versions/__init__.py`
- `manager/bitscan_manager/cli/__init__.py`

Tests: TP-M1-02 (harness), TP-M1-04. Open question: #41.

## Spec quotes

- TS §5.3 L1046: "Alembic, forward-only, one migration per PR, reviewed. No manual DDL in production. Migrations run with `bitscan-manager db migrate` as `bitscan_migrate` (`SET ROLE bitscan_owner`)."
- TS §5.2 L1016: Bootstrap "before the first migration; migrations then run as `bitscan_owner`, so it owns every table".
- TS §8.7 L1346: "`bitscan-manager-migrate.service` runs `bitscan-manager db migrate` before a new version starts". The unit (L1405–L1435) sets only `BITSCAN_MIGRATE_DSN_FILE`.
- PD-18 (user, 2026-10-20): hand-written SQL via Alembic `op.execute`, forward-only, no downgrade.

## Interface

```python
# bitscan_manager/db/__init__.py
from pydantic import SecretStr
def run_migrations(dsn: SecretStr) -> str:
    """Upgrade to head as bitscan_owner. Returns the head revision id. Raises MigrationError."""
class MigrationError(Exception): ...
```

CLI (`bitscan_manager/cli/__init__.py`): `bitscan-manager db migrate` calls `load_db_config(os.environ)` and then `run_migrations(cfg.migrate_dsn)`. Exit codes: 0 success, 1 database or migration failure, 2 usage or configuration error. Every other command keeps the M0 refusal. The `db` modules and `psycopg`, `sqlalchemy` and `alembic` are imported **inside** the `db` handler only, so `serve` and unknown commands still import no database module (`manager/tests/test_cli.py` checks this).

## Approach

1. **No `alembic.ini`.** Build `alembic.config.Config()` in code with `script_location` set to the package path of `db/migrations`, and `version_locations` set to its `versions/` folder. A DSN never appears in a file in the repository or in Alembic's configuration (TS §8.1 "Secrets in config").
2. **Engine without a URL that carries the secret:** `sqlalchemy.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn.get_secret_value()), poolclass=NullPool)`. The DSN never becomes a SQLAlchemy URL, so it cannot appear in a SQLAlchemy `repr` or log. No `echo`.
3. **Role switch:** on the connection, run `SET ROLE bitscan_owner`, check `SELECT current_user` = `bitscan_owner`, and **commit**. A `SET` inside a transaction that is later rolled back is undone, and SQLAlchemy 2 autobegins. A failure (the role is not a member) raises `MigrationError` before any DDL, so REQ-020 (5) creates nothing.
4. Pass the connection to Alembic through `config.attributes["connection"]`, and call `alembic.command.upgrade(config, "head")`.
5. **`env.py`:** online mode only (offline mode raises, because SQL-script generation is not needed and would put DDL outside the reviewed path). `context.configure(connection=conn, target_metadata=None, transaction_per_migration=True)`, then `with context.begin_transaction(): context.run_migrations()`. Each migration is atomic, and a failure leaves the earlier ones applied.
6. **Migration file convention (fixed here for TASK-014 to TASK-018):** file `versions/m000N_<name>.py`, `revision = "m000N"`, `down_revision` = the previous id (`None` for `m0001`), typed `def upgrade() -> None`, and `def downgrade() -> None: raise NotImplementedError("forward-only (TS §5.3)")`. The `m` prefix keeps module names valid for mypy and ruff; a name starting with a digit is not a valid module name. `versions/__init__.py` makes `versions` a package, so mypy checks the files as `bitscan_manager.db.migrations.versions.m0001_catalog`.
7. **Alembic version table (#41):** with the role switched first, Alembic creates `alembic_version` in `public`, owned by `bitscan_owner`. It exists before `m0005` runs `GRANT … ON ALL TABLES`, so `bitscan_app` gets SELECT and INSERT on it and `bitscan_retention` gets SELECT. M2's `/readyz` "migrations current" check needs that SELECT. The diff test excludes this table (#41 asks the owner to confirm all of this).
8. **Errors and output:** print `db migrate: <ExceptionClass>: <message>` to stderr. libpq connection messages name the host and user but never the password; the canary test (REQ-020 (6)) proves it. Configuration errors come from `ConfigError` and carry no values. On success, print the head revision to stdout. Alembic's INFO lines go to stderr through a minimal `logging` handler that never logs SQL.
9. **Packaging:** hatchling includes `db/migrations/**/*.py` by default. TP-M1-04 checks this with a non-editable `pip install .` (REQ-020 (8)).

## Edge cases

- **SQLAlchemy `text()` bind-parameter parsing:** `op.execute("…")` wraps the string in `text()`, which treats `:word` as a bind parameter, unless the colon follows another colon or a word character. `::debversion` is safe. The TS §5.2 comment `{"all":true}` (L850) and the TS §8.6 patterns `(?:password…` and `(?:AKIA…` are **not** safe. So migrations leave out SQL comments that contain `:word`, and the seeds are inserted with bound parameters (TASK-018). The reviewer checks every migration for `:\w` outside `::`.
- **`%` handling:** psycopg is not given parameters for DDL, but SQLAlchemy may pass an empty parameter set. Partition SQL that uses PL/pgSQL `format('%I', …)` (TASK-018) must be tested to reach the server unchanged. If it is mangled, use `op.get_bind().exec_driver_sql(sql)` for that statement.
- **Re-run:** `upgrade head` at head does nothing. REQ-020 (3) compares catalog snapshots.
- **Concurrent runs** (the unit plus a manual run): Alembic does not lock. The second run fails on the duplicate DDL or no-ops at head. Acceptable; the upgrade runbook runs the migrate unit once.
- `CREATE EXTENSION IF NOT EXISTS` in `m0001` runs as `bitscan_owner`. It is a no-op after the Bootstrap (TS §5.2 L1029), and if the Bootstrap was skipped it fails for `debversion`. That is the correct signal.

## Not in this task

Any table (TASK-014 onwards), `db maintain` (TASK-019), and a downgrade command (never).
