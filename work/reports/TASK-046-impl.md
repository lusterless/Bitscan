# TASK-046 IMPL report: server CLI `users create-admin`, `create-api-token`, `reset-totp`

REQ: REQ-058, REQ-008 (narrowed again). Spec: TS §8.7 L1347, TS §6.2 L1081, L1089, L1090, TS §8.4 L1290, TS §5.3 L1049.

Decisions applied:
- #7: on a terminal the password is asked twice with no echo, otherwise one line is read from stdin; never argv or the environment.
- #47 (e): `--name` and `--days`.
- #50: actor `cli:root`.
- #51: the running `serve` shipper delivers the entries.
- Lead: the alert hooks run after the CLI's own commit, and there is one alert entry per event.

## Files (3)

- `manager/bitscan_manager/cli/users.py`: new, 146 non-blank lines.
- `manager/bitscan_manager/cli/__init__.py`: `users <sub…>` is routed to `users_main(args[1:])` through a lazy import, and the help epilog lists the three commands. `users` on its own, `bits rebuild` and unknown commands keep the M0 refusal (exit 2, nothing read).
- `README.md`: the command list is updated and there is a new "Users" section with the three commands, the password rule, the DSN path, the username rule and the exit codes. The examples contain no secrets.

## Behaviour

- **Argument parsing** (`argparse`, `prog bitscan-manager users`) runs first, before any configuration or database module is imported. An unknown subcommand, a missing username, `--password` (an unknown option) or `--days x` exits **2**.
- **DSN.** The DSN is read from `APP_DSN_FILE = /etc/bitscan/secrets/app.dsn` with the serve profile's own loader checks:
  - the file must be readable UTF-8, not empty, and at most 64 KiB;
  - the DSN must parse and set `sslmode` to `require`, `verify-ca` or `verify-full`.

  The loader names the file **path** in every message and never its content. A failure exits **2**, for example `users reset-totp: <path>: DSN must set sslmode to require, verify-ca or verify-full`.
- **The test override:** `users_main(argv, *, dsn_file=Path(...))`. Tests run it in-process, or as `python -c "…users_main(sys.argv[2:], dsn_file=Path(sys.argv[1]))"` in a subprocess. No variable or option was added for production.
- **Password (`create-admin`)** is read only after the DSN file checks out:
  - When `sys.stdin.isatty()`: `getpass` twice with no echo. A mismatch exits 1 with `password not read (the two passwords differ)`.
  - Otherwise one line is read from stdin, with only the trailing newline removed.
  - It is never read from argv or any environment variable.
  - The REQ-041 rules (12–1024 code points, valid UTF-8) are checked before the database is contacted. A failure exits 1 and names the rule.
- **Database.** `AppDatabase(dsn, min_size=1, max_size=1)` opens one transaction per command, with a `TxAudit(PgAuditRepo(tx.conn), tx.on_commit)`. The alert counter therefore rises only after **this command's commit**. The pool is closed at the end. No other network connection is made: no vault and no sink.
- **The commands:**

| Command | Service | Refusals (exit 1) |
| --- | --- | --- |
| `create-admin <name>` | `services.users.create_admin`: role `admin`, no TOTP, Argon2id hash. Alert `admin_created` (`user.create`) | an existing username (`the username is already taken`); a username that breaks the rule |
| `create-api-token <user> [--name N] [--days D]` | `auth.api_tokens.create_api_token`, the same service as `POST /api-tokens`, `actor="cli:root"`. Alert `api_token_created`. The token is printed **once on stdout**, nothing else is printed there, and only its SHA-256 is stored | an unknown or disabled user (`no such enabled user`); `--days` outside 1–365; `--name` over 64 characters |
| `reset-totp <user>` | `services.users.reset_totp(actor_id=None)`: clears `totp_secret_enc` and `totp_last_step` and revokes the user's sessions. Alert `totp_reset` | an unknown or disabled user |

- **Errors.** Any database error exits 1 with `database error (<exception type>)`, never a DSN or SQL text. psycopg pool warnings are scrubbed by `AppDatabase`. Every refusal rolls the transaction back, so nothing changes.
- **Exit codes:** 0 success, 1 refused, 2 usage or DSN-file error.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager/bitscan_manager`, `ruff format --check manager` | pass. The only ruff findings in the tree are E501 lines in the tester's in-progress `tests/test_users_api_pg.py` |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 118 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1029 passed, 403 skipped (pg), 97.13 %. One failure during the run, `test_auth_dependencies.py::test_route_walk_sees_the_admin_totp_check_on_api_token_creation` (TASK-043's carry-over test). It passes when re-run on its own, so it was probably caught mid-edit by the tester |
| Smoke, with DSN files in a temp folder containing a canary password (deleted) | (1) |
| PostgreSQL: rows, hashes, a sign-in after create-admin, the alerts, a pty prompt | NOT RUN here; TP-M2-23 in WSL |

(1) Smoke results:
- A missing DSN file exited 2 with `<path>: cannot read the file it points to`.
- `sslmode=disable` exited 2 with a message naming the path.
- An unknown subcommand, `--password x` and `--days x` each exited 2 with a usage line.
- An 11-character stdin password exited 1 with `password must be at least 12 characters`, and no database was contacted.
- A valid password against a closed port exited 1 with `database error (DatabaseUnavailable)`.
- `users` alone kept the M0 refusal, and `--help` listed the commands.
- No canary appeared in any output.

## For the tester (TP-M2-23)

- `tests/test_cli.py` still lists `["users", "create-admin", "x"]` in `STILL_STUBS`. It is a real command now: with no DSN file it exits 2 naming the file, but it reads no `BITSCAN_*` variable. Please update that test.
- CHK-M2-266: with a pty, both prompts are written by `getpass` to the terminal. Without a TTY, empty stdin fails the length rule.
- CHK-M2-270: the only connection the CLI makes is libpq's to the DSN host and port.

## Lead ruling (decisions.md 2026-10-22, "Lead ruling on TASK-046")

- **Test seam:** the `dsn_file` function parameter of `users_main` is accepted as the only test seam. No production variable or option is added.
- **README:** the lead confirmed the "Users" section as user-guide content that matches #7, #56 (d) and TASK-041.

## Revision 1 (tester finding; user decision 2026-10-22, "no part of a DSN reaches stderr or the logs")

**Cause.** When PostgreSQL refused a well-formed TLS DSN, `psycopg_pool` logged its own WARNING with the libpq text, for example `connection to server at "127.0.0.1", port N failed: FATAL: password authentication failed for user "<user>"`. It was logged three times per pool retry. The CLI configured no logging, so Python's last-resort handler wrote those records to stderr. The password never appeared, but the user, host and port did. The old `_ScrubFilter` in `db/pool.py` removed only the whole DSN string and the password.

**Fix.**
1. **`manager/bitscan_manager/db/pool.py` (TASK-025 code; this also changes `serve`, TASK-045).**
   - `_ScrubFilter` is replaced by `DriverLogFilter`, installed once at import on every logger that psycopg and psycopg_pool use: `psycopg`, `.pool`, `.pq`, `.debug`, `.transaction`, `.waiting`, `psycopg_pool`, `.sched` and `.sched_async`. Each has to be listed, because a logger's filters do not apply to records from its child loggers.
   - For each such record the filter keeps the fixed format text, replaces every argument with its **type name**, and drops any exception (`exc_info` and `exc_text`). For example, `error connecting in 'str': ConnectionTimeout`. No libpq message, connection `repr`, host, port, user or database name can reach any handler.
   - `DatabaseUnavailable` messages are now `database unavailable: <exception type>` only. The libpq text is no longer included, even scrubbed.
   - `AppDatabase.open()` and `close()` no longer add or remove a filter, and the `dsn_secrets`/`scrub` imports in this module are gone. M1's `db migrate` and `db maintain` still use them.
2. **`manager/bitscan_manager/cli/users.py`.** After argument parsing, `users_main` calls `configure_logging(level=logging.WARNING)`, as `serve` does. Every record then goes to the JSON handler on stderr, and none reaches the last-resort handler. WARNING is used rather than INFO so the commands stay quiet: importing the database package otherwise logs alembic's INFO lines. The CLI's own message is unchanged, for example `users create-api-token: database error (DatabaseUnavailable)`.

Re-checked:
- ruff and mypy `--strict` are clean (120 files).
- `pytest --cov=bitscan_manager/services --cov-fail-under=85`: 1033 passed, 435 skipped (pg), 97.13 %, no failures.
- Smoke (deleted): with `user`, `password` and `dbname` set to canaries and a closed port, stderr held only `{"…", "logger": "psycopg.pool", "message": "error connecting in 'str': ConnectionTimeout", …}` and the CLI line; no canary was in stdout or stderr.
- A unit probe of the filter: a pool warning carrying `connection to server at "10.1.2.3" … user "bob"`, a connection-object argument and an `exception()` with a host in its text were all logged without the host, the user or the exception text.

**For the tester:** TASK-025's canary tests and the `serve` checks are affected by item 1. `DatabaseUnavailable` text no longer includes any driver message, and pool warnings now carry argument type names in place of values.
