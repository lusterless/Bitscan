# TASK-166 IMPL: CLI `bitscan-manager bits rebuild`

Owner: impl-manager-m7b. REQ-175. Risk: high. Depends on TASK-157 (`rebuild.start_task`, `rebuild.run`, `RebuildResult`, `NOT_RUNNING`, `FAILED`).

Spec and rulings: TS §8.7 L1347, §4.2 L540, §4.6 L613; `.claude/rules/manager/config-and-cli.md` "Server CLI"; #107 (a)–(f); the TASK-046 rule "no DSN content in output".

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/cli/bits.py` | new | 145 |
| `manager/bitscan_manager/cli/__init__.py` | `bits …` dispatch, and `bits rebuild` in the `--help` epilog | +5 |

**Size: 150 lines against an estimate of 120.** The extra is the #107 (a) folder resolution: reading `BITSCAN_BITS_DIR` from `/etc/bitscan/manager.env` (a systemd EnvironmentFile; there is no parser for it in the tree yet), about 25 lines, plus the module docstring.

## Behaviour

- **Structure (mirrors `cli/users.py`).**
  - `bits_main(argv, *, environ=None, dsn_file=None, env_file=None)` parses the arguments first, so a usage error exits 2 and `--help` exits 0 before any configuration or database module loads.
  - It then calls `configure_logging(level=WARNING)` (JSON on stderr) and loads the configuration, then runs.
  - `ACTOR` (`cli:root`) and `APP_DSN_FILE` (`/etc/bitscan/secrets/app.dsn`) are imported from `cli/users.py`, so the two commands share one definition.
- **DSN.** It is read only from `APP_DSN_FILE`, with the serve profile's checks through `config.startup._Loader`, exactly as `users` does: readable, UTF-8, at most 64 KiB, and `sslmode` must be require, verify-ca or verify-full. Messages name the file path, never its content. Nothing is read from argv or the environment except the non-secret `BITSCAN_BITS_DIR`. A database error prints `bits rebuild: database error (<ExceptionType>)` only.
- **Folder (#107 (a)).** `BITSCAN_BITS_DIR` from the environment if set; else the last `BITSCAN_BITS_DIR=` line of `/etc/bitscan/manager.env` (surrounding quotes removed); else `/var/lib/bitscan/bits`.
  - Missing folder or `uploaded/`: exit 2 with `BITSCAN_BITS_DIR: the folder or its uploaded/ is missing`. This stops a rebuild of a wrong, empty folder from deleting every policy.
  - `manager.env` missing: falls through to the default.
  - `manager.env` present but unreadable or not UTF-8: exit 2. Its content is never shown.
- **Run.**
  - `rebuild.start_task(db, clock, None)` writes the task row with `requested_by` NULL (#107 (d)).
  - `rebuild.run(db, clock, folder, task_id, Actor("cli:root", None))` then runs in the foreground. It waits on the catalog lock while an import holds it (REQ-175 (4)), and writes the alerts like the API rebuild.
  - A one-connection `AppDatabase(min_size=1, max_size=1)` is closed in `finally`.
  - No upload finish, integrity check or confirmation prompt (#107 (e), (f)).
- **Output (#107 (b)), on stdout:** one line per file, then the policy and summary lines:
  - `success <source_file> policy <id> version <n>`;
  - `rejected <source_file> (<n> findings)`, where n is the number of findings stored for that import (warnings included); the findings themselves are read with `GET /imports`;
  - `not imported <rel>` for a file with no row, such as a server-folder policy's uploaded copy;
  - `removed leftover <rel>` for a leftover of an interrupted delete;
  - `deleted policy <id>`;
  - then `rebuild succeeded: N files, R rejected, D policies deleted, P plugins retired (task <uuid>)`.
- **Exit codes (#107 (c)):**

  | Exit | Case | Output |
  | --- | --- | --- |
  | 0 | the rebuild committed (`succeeded`), even with rejected files | the lines above |
  | 1 | the rebuild failed | `bits rebuild: The rebuild failed; the catalog was left unchanged. (task <uuid>)` on stderr |
  | 1 | it did not run (`RebuildResult.reason`, i.e. `NOT_RUNNING`) | `bits rebuild: interrupted by manager start-up; run it again` on stderr |
  | 1 | a database error | `bits rebuild: database error (<ExceptionType>)` on stderr |
  | 2 | a usage or configuration error | the error on stderr |

## Checks run here (scratch, outside the tree; the tests are the tester's)

- **Gates:** `ruff check manager/bitscan_manager` and `ruff format --check manager` (300 files) are clean, and so is `mypy --strict --config-file manager/pyproject.toml manager` (300 files).
- **Smoke** (`C:\Users\kaiquan.koh\scratch\task166\smoke.py`, with a fake `AppDatabase` and fake `rebuild.start_task`/`run`; no PostgreSQL):
  - `bitscan-manager --help` lists `bits rebuild` and exits 0; `bits rebuild --help` exits 0.
  - A usage error, and `bitscan-manager bits` alone, both exit 2.
  - Folder resolution: the value from `manager.env` is used, and the environment wins over it.
  - Exit 2, with the canary password absent from stdout and stderr, for each of: a missing folder, a missing `uploaded/`, a missing DSN file, and a DSN without `sslmode`.
  - `start_task` gets `requested_by=None`; `run` gets the resolved folder and `Actor("cli:root", None)`.
  - A succeeded result prints the six expected lines and exits 0. A failed result prints the FAILED line with the task id and exits 1. A `NOT_RUNNING` result prints its reason and exits 1.

## For the tester (REQ-175 (1)–(6), Testcontainers PostgreSQL)

- Pass `dsn_file=`, `env_file=` and `environ=` to `bits_main` to point it at a temporary DSN file and folders.
- Run the command with a canary in the DSN password, and check stdout and stderr for it on every path.
- **Plants:**
  - Read `BITSCAN_BITS_DIR` from argv or the DSN from the environment: REQ-175 (5).
  - Drop the `uploaded/` check: REQ-175 (3) (a missing `uploaded/` would no longer exit 2).
  - Print `str(exc)` of a database error: the canary leaks.
  - Return 0 when `result.reason` is set: the `NOT_RUNNING` row.
  - Return 1 when files were rejected: REQ-175 (2).
  - Pass `requested_by` as a user id: the task-row check.
  - Remove the `--help` epilog line: REQ-175 (6).
