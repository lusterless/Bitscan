# TASK-046 TEST report: server CLI `users …`

Verdict: **PASS** (revision 1; round 1 **FAIL**). Tester, 2026-10-22. REQ-058 (1)–(8), REQ-019 (5), REQ-039; #7, #47 (e), #50, #51; user ruling (a) 2026-10-22 (no DSN content on stderr or in logs). Impl report: `work/reports/TASK-046-impl.md` ("Revision 1").

## Round 1: FAIL
`test_cli_users_pg.py::test_database_errors_name_only_the_error_type`: with a refused, well-formed TLS DSN, the expected stderr was `database error (<type>)` only. The actual stderr also had psycopg_pool's `error connecting in 'bitscan_app': connection failed: … port N failed: FATAL: password authentication failed for user "<user canary>"` three times. Cause: the CLI configured no logging, so the `psycopg.pool` WARNING went to Python's last-resort handler, and the TASK-025 filter scrubbed only the password. Fixed in revision 1 (`DriverLogFilter` on every psycopg logger, arguments reduced to type names, exceptions dropped; the CLI calls `configure_logging`).

## Commands run
- W: `tester2_t046r1.sh`, alone: wave files 238 passed; full suite 1505 passed, 0 skipped, services 99.32 %; 14 CLI and pool mutants plus 2 controls. `tester2_t046c.sh`: CLI files 78 passed. `tester2_t046rp.sh`: the real `/etc/bitscan/secrets/app.dsn`.
- L: ruff, ruff format, mypy --strict (120 files); `test_cli.py` (part of 69 passed).

## Criteria
| REQ-058 | Result | Rows |
| --- | --- | --- |
| (1) create-admin | PASS | CHK-M2-265 |
| (2), #7 password source and rules | PASS | CHK-M2-266 |
| (3) create-api-token | PASS | CHK-M2-267, CHK-M2-267-realpath |
| (4) reset-totp | PASS | CHK-M2-268 |
| (5) DSN file errors; no DSN content (ruling (a)) | PASS | CHK-M2-269, CHK-M2-269a (FAIL), CHK-M2-269a-r1 |
| (6) only PostgreSQL contacted | PASS | CHK-M2-270 |
| (7) audit `cli:root`, alerts, reach the sink | PASS | CHK-M2-271 |
| (8) unknown commands touch no database | PASS | CHK-M2-272 |
| README | PASS | CHK-M2-273 |
| Revision 1 in pool and serve (ruling (a)) | PASS | CHK-M2-035a, CHK-M2-263c |

Mutations: 12 of 14 red. Equivalent, confirmed by the lead: `dsn-in-error` (after revision 1 the CLI's exception is `PoolTimeout`, whose text holds no DSN; the two-layer variant is red) and `cli-no-logging-config` (the driver filter is the control and logging configuration is a second layer). Test defects of mine fixed before the evidence run: `unreadable` used `chmod 0`, which root ignores (now a folder); the connect recorder expected a Python event for libpq (now a probe control); mypy in `test_timestamps.py:57` (`model_validate`). Tests added: `test_cli_users_pg.py`, `test_cli_users_tty_linux.py`, CHK-M2-035a in `test_db_pool_pg.py`, CHK-M2-263c in `test_serve_linux.py`; updated: `test_cli.py`. Plan rows added: CHK-M2-035a, -263c, -269a (tests/m2/test-plan.md; index note in tests/test-plan.md).
