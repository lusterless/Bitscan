# TASK-046 REVIEW: server CLI `users create-admin`, `create-api-token`, `reset-totp`

Reviewer: reviewer. Date: 2026-10-22. REQ-058, REQ-008 (narrowed again). Spec: TS §8.7 L1347, TS §6.2 L1081, L1089, L1090, TS §8.4 L1290, TS §5.3 L1049.

Decisions:
- #7: TTY prompt twice, otherwise one stdin line; never argv or the environment;
- #47 (e): `--name` and `--days`;
- #50: actor `cli:root`;
- #51: the running `serve` ships the entries;
- 2026-10-22 "Lead ruling on TASK-046": the `dsn_file` test seam only;
- 2026-10-22 "User decision: no part of a DSN reaches stderr or the logs";
- 2026-10-22 "Lead ruling on TASK-046 equivalent mutants".

Inputs:
- `work/reports/TASK-046-impl.md`, including revision 1;
- `work/reports/TASK-046-test.md`: PASS on revision 1, after a round 1 FAIL on the DSN leak in the pool log. Rows CHK-M2-265 to -273, -035a and -263c; CHK-M2-305-w9 on Linux, alone: 1505 passed, 0 skipped.

Files reviewed:
- `manager/bitscan_manager/cli/users.py`;
- `manager/bitscan_manager/cli/__init__.py`;
- `README.md`, the "Users" section;
- the revision 1 change to `manager/bitscan_manager/db/pool.py` (`DriverLogFilter`, `DatabaseUnavailable` text). That change also affects TASK-025 code and `serve` (TASK-045), so it was reviewed for both.

Verdict: APPROVED

**This task needs a second approval from the user (TS §8.2, auth).**

## What was checked

- **DSN (REQ-058 (5), TS §8.7).** It is read from `/etc/bitscan/secrets/app.dsn` with the serve profile's loader checks: readable, UTF-8, at most 64 KiB, and `sslmode` set to `require`, `verify-ca` or `verify-full`. Every message names the **path**, never the content, and a failure exits 2. The only test seam is the `dsn_file` function parameter, per the lead's ruling; no production variable or option was added.
- **Password (#7, REQ-058 (2)).** It is read after the DSN checks out: on a TTY, `getpass` twice with no echo; otherwise one stdin line. It is never read from argv or the environment, and `--password` is a usage error (exit 2). The REQ-041 rules are checked before the database is contacted. Parsing happens before any configuration or database import, so usage errors touch nothing (REQ-058 (8)).
- **Commands (REQ-058 (1), (3), (4)).**
  - `create-admin` uses `services.users.create_admin`: role `admin`, no TOTP, so the first sign-in is restricted, and an `admin_created` alert.
  - `create-api-token` uses the TASK-041 `create_api_token` service with actor `cli:root`, the same lifetime and name rules, and an `api_token_created` alert. The token is printed once on stdout and nothing else goes there; only its SHA-256 is stored.
  - `reset-totp` uses `reset_totp(actor_id=None)`: it clears both TOTP columns, revokes sessions and writes a `totp_reset` alert.
  - An unknown or disabled user, a duplicate username or a bad rule exits 1 and rolls back, so nothing changes.
- **Audit and alerts (REQ-058 (7); my TASK-035 note).** Each command runs one `AppDatabase` transaction with `TxAudit(PgAuditRepo(tx.conn), tx.on_commit)`, so the alert counter rises only after this command's own commit. As noted in TASK-035, that counter lives in the CLI process. The audit entries reach the sink through `serve`'s shipper, which polls committed rows (#51); the tester confirmed it.
- **No other connection (REQ-058 (6)).** The only connection is libpq's to the DSN; there is no vault and no sink.
- **Revision 1: no part of a DSN in stderr or logs (the user's decision).**
  - `DriverLogFilter` is installed at import on every psycopg and psycopg_pool logger, each listed by name, because filters do not apply to child loggers.
  - It replaces every format argument with its type name and drops `exc_info`/`exc_text`. libpq texts naming host, port, user and database therefore never reach a handler.
  - `DatabaseUnavailable` now says only `database unavailable: <type>`.
  - The CLI calls `configure_logging(WARNING)`, so no record falls through to Python's last-resort handler.
  - The tester's canary checks (host, user, dbname and password) are green for the pool (CHK-M2-035a), `serve` (CHK-M2-263c) and the CLI (CHK-M2-269a). The three plants are red: the old scrub-only filter, a missing `psycopg.pool` entry, and libpq text kept.
  - I probed the filter myself: a pool warning carrying `connection to server at "10.9.9.9" user "bob"` as an argument is logged as `str` only.
- **Effect on TASK-025 and TASK-045.** The error text gets shorter, and pool warnings carry type names. TASK-025's canary tests and the `serve` checks were re-run green (1505 passed on Linux). Diagnostics are still possible from the exception type and `/readyz`. This is the trade-off the user chose.
- **Equivalent mutants (lead ruling).** `dsn-in-error` and `cli-no-logging-config` are accepted as equivalent: the CLI's exception is `PoolTimeout`, which carries no DSN text, and the driver filter is the control. The two-layer variant is red.
- **README.** I checked it against the code: the three commands, `--name` and `--days` (1–365, default 90), the password rule, the DSN path, the username rule and the exit codes (0 success, 1 refused, 2 usage or DSN error). The examples contain no secrets.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 120 files. The suite has 1033 passed and 436 skipped (pg, run in WSL), with G5 at 97.13 %.
- **Scope.** 3 files plus the revision change in `db/pool.py`, about 170 lines. Accepted.

## Findings

None block approval.

1. **note, a residual of the user's DSN decision.** `DriverLogFilter` can only rewrite *arguments*. Text baked into a driver message string is passed through. I searched the pinned psycopg 3.3.6 and psycopg_pool 3.3.3: every WARNING, ERROR and INFO call uses a constant format string. The one exception is a DEBUG line in `psycopg/transaction.py:144`, an f-string with the connection `repr`, which includes host, user and database. That line fires only on an explicit `Rollback` exception, and only at DEBUG, while `serve` logs at INFO and the CLI at WARNING. So it cannot appear in production logs today. A psycopg upgrade should re-check this, or the filter could also drop DEBUG records from these loggers.
2. **nit.** `cli/users.py:52` imports the private `_Loader` from `config/startup.py`. A small public helper there, such as `read_dsn_file(path)`, would make the reuse explicit.
3. **nit.** `create-api-token` for an admin who has no TOTP succeeds, but the token is refused with 403 `totp_enrolment_required` until TOTP is enrolled (#53 (i), kept by the user). The README could say so in one line.
4. **note.** Reading the password from stdin when it is not a TTY means a password piped by a script lives in that script's process. #7 allows this, and it is never argv or the environment.

## For the user (second approval)

- The CLI never takes a password from the command line or the environment.
- It refuses a DSN file without TLS.
- It prints a new API token once, on stdout only.
- After your DSN decision, no host, port, user, database or password appears in any error or log line from the CLI, `serve` or the pool.

Nothing needs a new decision. Finding 1 is a residual to recheck on a psycopg upgrade.
