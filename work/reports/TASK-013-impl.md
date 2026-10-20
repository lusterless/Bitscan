# TASK-013 IMPL report: Alembic environment, migration runner, `db migrate`

REQs: REQ-020 (REQ-032 is delivered by the tester's harness in the TEST step). Spec: TS §5.3 (Alembic, forward-only, `bitscan_migrate` with `SET ROLE bitscan_owner`), TS §5.2 L1016 (the owner owns everything), TS §8.7 L1346 and L1405–L1435 (the migrate unit sets only `BITSCAN_MIGRATE_DSN_FILE`), TS §8.1 "Secrets in config". Plan: `work/plans/TASK-013.md`. Decision #41 is applied (decisions 2026-10-20).

## Files (5)

- `manager/bitscan_manager/db/__init__.py` (runner, about 80 lines): `run_migrations(dsn: SecretStr) -> str`, `MigrationError`, `MIGRATIONS_DIR`, `OWNER_ROLE`.
- `manager/bitscan_manager/db/migrations/__init__.py` (empty).
- `manager/bitscan_manager/db/migrations/env.py`: online mode only. Offline mode raises `RuntimeError`. It requires the connection handed in through `config.attributes["connection"]` and calls `context.configure(connection=..., target_metadata=None, transaction_per_migration=True, version_table_schema="public")`.
- `manager/bitscan_manager/db/migrations/versions/__init__.py` (empty). There are no migrations yet; TASK-014 adds `m0001`.
- `manager/bitscan_manager/cli/__init__.py`: adds `db migrate` and a help epilog listing it. The refusal text for other input is now "unknown or not yet implemented command".

## How it works

1. **No `alembic.ini`.** `Config()` is built in code with `script_location` = the package's `db/migrations`. Alembic's default `versions/` location applies. No DSN appears in any file or in Alembic's configuration.
2. **The DSN is never a URL.** `create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool)`, no `echo`, and `engine.dispose()` in `finally`.
3. **Role switch first.** `SET ROLE bitscan_owner`, then `SELECT current_user` must equal `bitscan_owner`, then a **commit** (SQLAlchemy 2 autobegins, and a rollback would undo the `SET`). A non-member role (for example `bitscan_app`) fails at `SET ROLE` before any DDL, so nothing is created.
4. `command.upgrade(config, "head")` runs on that connection, then `connection.commit()`. That commit is required: with no pending migration, Alembic creates `alembic_version` inside the autobegun transaction, and without the commit that transaction would be rolled back.
5. **#41:** `alembic_version` is created after `SET ROLE` in schema `public` (`version_table_schema="public"`, so `search_path` does not matter), so `bitscan_owner` owns it. No grants are added.
6. **Return value:** the head revision id, or `"base"` (Alembic's name for "no revision") while `versions/` is empty, as in M1 W3. The CLI prints it to stdout.
7. **Forward-only:**
   - `db migrate` only ever calls `upgrade head`, and there is no CLI argument for a target.
   - `db downgrade`, `db migrate <anything>` and other `db` input are refused with exit 2.
   - The migration file convention for TASK-014 to TASK-018 is in the `env.py` docstring: `versions/m000N_<name>.py`, `revision = "m000N"`, a typed `upgrade()`, and a `downgrade()` that raises `NotImplementedError`.
8. **Errors:** every failure inside `run_migrations` becomes `MigrationError("<ExceptionClass>: <message>")`. As a safety net, the message has the full DSN and the DSN's password replaced with `**********`. It is raised outside the `except` block, so the original exception, which may hold connection state, is not chained.

   CLI exit codes:
   - 0: success;
   - 1: database or migration failure (`db migrate: <message>` on stderr);
   - 2: configuration error (one `db migrate: <ConfigError line>` per problem) or any other command.
9. **Logging:** a plain `StreamHandler(stderr)` on the `alembic` logger at INFO, added once. Alembic's lines carry revision ids, never SQL. SQLAlchemy's engine logger is not enabled.
10. **Lazy imports:** `config` is imported inside the `db migrate` handler, and `bitscan_manager.db` (with psycopg, sqlalchemy and alembic) only after the configuration has loaded. `serve`, unknown commands, and `db migrate` with the variable unset or invalid load no database module.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (20 files) | pass |
| `pytest` (Windows) | 72 passed, 10 skipped (pg), **1 failed: `tests/test_cli.py::test_refused_commands_touch_no_env_socket_or_db[argv1]`** (see "For the tester") |
| `db migrate` with an unreachable host and a canary password (key/value and URI DSN) | exit 1, `db migrate: OperationalError: (psycopg.errors.ConnectionTimeout) connection timeout expired`, canary absent |
| `db migrate` with the variable unset / a DSN without TLS | exit 2, the message names `BITSCAN_MIGRATE_DSN_FILE`, canary absent |
| `db downgrade`, `db migrate extra`, `serve` | exit 2 |
| `cli.main` for `db migrate` (unset), `serve`, `bogus`: imported modules | none of psycopg, sqlalchemy, alembic, `bitscan_manager.db` |
| Alembic script directory | loads; head `None` (empty `versions`); `upgrade --sql` (offline) refused by `env.py` |
| Non-editable wheel (`hatchling build -t wheel`) | contains `db/__init__.py`, `db/migrations/__init__.py`, `db/migrations/env.py`, `db/migrations/versions/__init__.py` |
| **Real PostgreSQL** (migrate twice, owner of `alembic_version`, app-role refusal, wrong password) | **NOT RUN by me.** The auto-mode classifier blocked my attempt to run a smoke test as root in WSL twice, so I did not retry. The tester's `migrated_db` fixture already drives `bitscan-manager db migrate` |

## For the tester

- **Expected M0 test change:** `test_cli.py::test_refused_commands_touch_no_env_socket_or_db` with `["db", "migrate"]` now fails. `db migrate` reads `BITSCAN_MIGRATE_DSN_FILE`, as REQ-020 requires and REQ-008 is narrowed. It still imports no database module and opens no socket when the variable is unset. `serve` keeps the M0 behaviour. `test_everything_else_is_refused_on_stderr` and `test_console_script_refuses` still pass for `db migrate` without the variable (exit 2, stderr, empty stdout).
- **Real-DB checks, which I could not run:**
  - two runs exit 0 and print `base`;
  - the only table in `public` is `alembic_version`, owned by `bitscan_owner`, with 0 rows;
  - a `bitscan_app` DSN gives exit 1 and leaves `public` empty;
  - a wrong password and an unreachable host give exit 1 with the canary absent.
- Exit codes: 1 for database failures, 2 for configuration and usage. Assert `!= 0` if you only need REQ-020 (5) and (6).
