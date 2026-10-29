# TASK-166 TEST: PASS

Tester: tester-m7, 2026-10-28. Full rigor (importer, CLI). REQ-175 (1)–(6); TS §8.7 L1347, §4.2 L540; #107 (a)–(f); the TASK-046 rule (no DSN content in any output); TASK-157 r2 (a task no longer running: nothing runs). Code under test: `bm/cli/bits.py` and `bm/cli/__init__.py`. New test file: `manager/tests/test_cli_bits_pg.py` (12 tests). `bits_main` runs in a subprocess with a temporary DSN file, `manager.env` and folders (`python -c` from the tree under test), and the installed console script runs for `--help`. Its own module database.

## Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t160r1`, `-n 0`, `CI=true`) | Count |
| --- | --- | --- |
| b0 | `pytest tests/test_cli_bits_pg.py` (with the TASK-160 set) | **12/12 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 7 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 7/7 red. c7 needed `PYTHONPATH` on the plant copy, because the console script imports the venv's editable install, not the copy |
| static (L) | whole-tree ruff, ruff format, `mypy --strict` (CI form) | clean (304 files) |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-290 (1) | APP | W | b0 | PASS | A server file and an `uploaded/` file: exit 0. One line each, `success <rel> policy <id> version 1`, then `rebuild succeeded: 2 files, 0 rejected, 0 policies deleted, 0 plugins retired (task <uuid>)`, three lines in all. The task is `succeeded` with `requested_by` NULL. One `bits.rebuild` (`policy_rebuilt`) by `cli:root`, two `policy.import`, every entry by `cli:root`. The DSN password is in no output. The `uploaded/` file is relocated | 2026-10-28 |
| CHK-M7-290 (2) | APP | W | b0 | PASS | One rejected file: exit 0, the line `rejected bad.bit (1 findings)`, summary `2 files, 1 rejected` (#107 (c)). A removed file prints one `deleted policy <id>` line and the summary counts it | 2026-10-28 |
| CHK-M7-290 (3) | APP | W | b0 | PASS | A non-TLS DSN (`sslmode=disable`), a DSN without `sslmode`, a missing DSN file, a missing folder and a missing `uploaded/` each exit 2. Each writes one `bits rebuild: …` stderr line and empty stdout, with the canary password nowhere, and no task row is written (no database work) | 2026-10-28 |
| CHK-M7-290 (4) | APP | W | b0 | PASS | Started while another session holds the catalog lock: still running after 3 s, and `pg_locks` shows it waiting. After the release it exits 0 with its summary | 2026-10-28 |
| CHK-M7-290 (5) | APP | W | b0 | PASS | With `BITSCAN_DB_DSN`, `BITSCAN_DB_DSN_FILE`, `DATABASE_URL` and `PGPASSWORD` set to working values and the fixed DSN file absent, it exits 2 naming that file. `--dsn`, a folder argument and `--bits-dir` are usage errors (2). #107 (a): without `BITSCAN_BITS_DIR` in the environment it uses the last `BITSCAN_BITS_DIR=` of `manager.env` (quotes removed). The environment wins over it. A `manager.env` that isn't UTF-8 exits 2 without showing its content (canary absent) | 2026-10-28 |
| CHK-M7-290 (6) | APP | W | b0 | PASS | `bitscan-manager --help` lists `bits rebuild` (exit 0); `bits rebuild --help` exits 0; `bits` and `bits nonsense` exit 2. Through the console script with no DSN file: exit 2 naming `/etc/bitscan/secrets/app.dsn`, with no prompt | 2026-10-28 |
| failed and not run | APP | W | b0 | PASS | A database error inside the rebuild (injected) → exit 1, empty stdout, stderr `bits rebuild: The rebuild failed; the catalog was left unchanged. (task <uuid>)`. The database down → exit 1, `bits rebuild: database error (<Type>)`, canary absent. TASK-157 r2: the task failed by a start-up while the CLI waited for the lock → exit 1, `bits rebuild: interrupted by manager start-up; run it again`, empty stdout, no audit entry | 2026-10-28 |
| plant c1 | APP | W | the DSN read from `BITSCAN_DB_DSN_FILE` | PASS (red) | 1 failed: (5) exit 0 instead of 2 | 2026-10-28 |
| plant c2 | APP | W | the `uploaded/` check dropped | PASS (red) | 1 failed: (3), a rebuild of a folder without `uploaded/` ran | 2026-10-28 |
| plant c3 | APP | W | `str(exc)` printed for a database error | PASS (red) | 1 failed: the error-type row (message text and pool detail in the output) | 2026-10-28 |
| plant c4 | APP | W | exit 0 when the task wasn't running | PASS (red) | 1 failed | 2026-10-28 |
| plant c5 | APP | W | exit 1 when files were rejected | PASS (red) | 1 failed: (2) | 2026-10-28 |
| plant c6 | APP | W | `requested_by` a user id | PASS (red) | 1 failed: (1) the task row | 2026-10-28 |
| plant c7 | APP | W | the `--help` line removed | PASS (red, with `PYTHONPATH`) | 1 failed: (6). Without `PYTHONPATH` the console script ran the venv's installed tree and the row stayed green (a harness effect) | 2026-10-28 |

## Acceptance (TASK-166 row)

REQ-175 (1)–(6) → CHK-M7-290 (1)–(6); #107 (a)–(d) → (1), (2), (5) and "failed and not run". #107 (e), (f) need no row, since the command has no finish, no check and no prompt (seen in (1)). Every security row has a plant that went red.

## Shared-venv check (lead, 2026-10-28)

`/root/venv-m7`'s editable install points at the last folder installed, so the `bitscan-manager` console script (`run_cli`) imports that tree, not the plant copy. In this file only `test_help_lists_bits_rebuild` and `test_the_cli_entry_point_reaches_bits_main` use the console script. The only plant aimed at them, c7, was re-run with `PYTHONPATH=<plant copy>/manager` and went red. Plants c1–c6 run `bits_main` through `python -c` from the plant copy's folder (checked: the copy's tree is imported), so their results stand.
