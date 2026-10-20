# TASK-013 REVIEW: Alembic environment, migration runner, `db migrate`

Reviewer: reviewer. Date: 2026-10-20. REQ-020 (REQ-032 harness parts are with tester-b, PD-17). Spec: TS §5.3 L1046/L1049 (Alembic, forward-only, `bitscan_migrate` with `SET ROLE bitscan_owner`), TS §5.2 L1016, TS §8.6 L1308, TS §8.7 L1346/L1405-1435, TS §8.1 "Secrets in config"; decision #41 (`alembic_version` in `public`, owned by `bitscan_owner`, no extra grants). Inputs: `work/plans/TASK-013.md`, `work/reports/TASK-013-impl.md`, `work/reports/TASK-013-test.md` (PASS; the first real-PostgreSQL run: WSL, `CI=true`, 274 passed), `tests/m1/report.md` CHK-M1-030, -050 to -058, -060 and -050-mut.

Verdict: APPROVED

One approval is enough here. The TS §8.2 L1268 "runner" is the agent's `bitscan-runner`, not this migration runner. The real-database results (CHK-M1-050 to -055) come from the tester's WSL run; there is no Docker here.

## What was checked

- **Scope:** the five listed files. `versions/m0001_catalog.py` is already on disk, but it belongs to TASK-014 and is not reviewed here.
- **Forward-only:**
  - The CLI matches only `["db", "migrate"]` exactly. These all exit 2 with nothing on stdout: `db downgrade base`, `db stamp head`, `db migrate head`, `db migrate --sql`, `db upgrade head`, `db maintain` and `serve`.
  - The runner only calls `command.upgrade(config, "head")`.
  - `env.py` refuses offline mode, and refuses any run without the connection handed in by `bitscan_manager.db`. The stock `alembic` CLI with an ini pointing at our `script_location` exits 1 for `downgrade base` and for `upgrade head --sql`.
  - The naming rule for TASK-014 and later is stated in the `env.py` docstring: `versions/m000N_<name>.py`, revision `"m000N"`, a typed `upgrade()`, and a `downgrade()` that raises `NotImplementedError`.
  - The "downgrade raises" check becomes testable with `m0001` (TASK-014 review).
- **Role switch and #41 (`db/__init__.py:50-61`):**
  - the order is `SET ROLE bitscan_owner`, then `SELECT current_user` must equal `bitscan_owner`, then `commit()`, all before `command.upgrade`;
  - the final `commit()` makes `alembic_version` durable when nothing is pending, and the tester's mutation run shows the test catches its removal;
  - `version_table_schema="public"` and `transaction_per_migration=True`;
  - a non-member role (`bitscan_app`) fails at `SET ROLE` before any DDL and creates nothing (CHK-M1-054);
  - `alembic_version` is owned by `bitscan_owner`, with no extra grants (CHK-M1-051).
- **The DSN is never a URL:**
  - `create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool)`, with no `echo`, and `dispose()` in `finally`;
  - no `alembic.ini`: `Config()` is built in code, with `%` escaped in the path;
  - the DSN has already passed REQ-019's sslmode rule in `load_db_config`.
- **Error scrubbing:**
  - with a canary password and an unreachable host, both a keyword and a URI DSN give exit 1, `db migrate: OperationalError: … connection timeout expired`, and no canary in stdout or stderr;
  - `MigrationError` is raised outside the `except` block, so there is no chain;
  - as a safety net, the full DSN and its password are replaced;
  - the Alembic logger at INFO prints revision ids only, and the SQLAlchemy engine logger is not enabled;
  - the wrong-password case is covered on real PostgreSQL (CHK-M1-055).
- **Exit codes:** 0 on success (prints the head, `base` while `versions/` is empty), 1 on a database or migration failure, 2 on a configuration or usage error. With the variable unset: exit 2, `db migrate: BITSCAN_MIGRATE_DSN_FILE is not set`.
- **Lazy imports:** after `cli.main` for `serve`, `bogus` and `db migrate` with the variable unset, none of `psycopg`, `sqlalchemy`, `alembic` or `bitscan_manager.db` is in `sys.modules`.
- **Wheel:** `hatchling build -t wheel` into a temp directory contains `db/__init__.py`, `db/migrations/{__init__,env}.py` and `db/migrations/versions/__init__.py`. The tester ran `db migrate` from a non-editable install (CHK-M1-057).
- **Gates:**
  - ruff and format are clean, with S608 active;
  - `mypy --strict` reports no issues in 23 files;
  - locally, `test_db_migrate.py`, `test_cli.py` and `test_conftest_hook.py` give 58 passed and 6 skipped (pg).

## Findings

1. **nit. `_scrub` parses the DSN while handling the original exception.**
   - Where: `manager/bitscan_manager/db/__init__.py:32-39` and `:77-78`.
   - `_scrub` calls `conninfo_to_dict(dsn)` inside the `except` block. The CLI always passes a DSN that `load_db_config` has already validated, so this cannot fail today.
   - But `run_migrations` is a public function. Given an unvalidated DSN, a parse error from psycopg quotes the DSN and would be chained to the original exception.
   - Fix: compute the password once, guarded, before the `try` (for example, a `_password(dsn)` helper that returns `None` on any parse error).
2. **note, for the TASK-014 to TASK-018 reviews.** Migration files must not run `RESET ROLE` or `SET ROLE`, must not change `search_path`, and must use `op.execute` with static SQL or bound parameters. ruff S608 recognises only some SQL shapes (tester note), so review is the control.
