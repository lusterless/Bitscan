# TASK-012 IMPL report: start-up configuration loader

REQ: REQ-019. Spec: TS §8.6 (start-up variables), TS §8.7 (credentials via `LoadCredential=`; the migrate and maintain units set only `BITSCAN_MIGRATE_DSN_FILE`), TS §5.3 (TLS only), TS §8.1 "Secrets in config", TS §8.4 (no secrets in logs). Plan: `work/plans/TASK-012.md`. Question #45 is answered (decisions 2026-10-20). #24 is still open: vault, key reference and sink are treated as opaque.

## Files (2, 193 lines)

- `manager/bitscan_manager/config/startup.py`: `ConfigError`, `ServeConfig`, `DbConfig`, `load_serve_config(environ)`, `load_db_config(environ)`, plus the constants `TLS_SSLMODES`, `DEFAULT_LISTEN`, `DEFAULT_BITS_DIR` and `MAX_SECRET_FILE_BYTES`. The interface is exactly the plan's.
- `manager/bitscan_manager/config/__init__.py`: re-exports the five public names.

## Behaviour

- **Errors are collected, not stopped at the first.** One `ConfigError` lists every problem, one line per variable (plan step 8). Messages are fixed text plus the variable name only, never a value, path or file content:
  - `X is not set` (missing, or empty after stripping)
  - `X: cannot read the file it points to`
  - `X: file is empty`
  - `X: file is larger than 64 KiB`
  - `X: file is not valid UTF-8`
  - `X: not a valid PostgreSQL DSN`
  - `X: DSN must set sslmode to require, verify-ca or verify-full`
  - `X: file is missing or unreadable` (TLS cert and key)
  - `BITSCAN_LISTEN must be host:port with a port from 1 to 65535`
- **No exception chain.** `ConfigError` is raised once, at the end, outside any `except` block. So `__cause__` and `__context__` are `None`, and no `OSError`, `UnicodeDecodeError` or psycopg error is attached. This matters because psycopg's parse error quotes the DSN: for `postgresql://u:PW@[::1/db` the message contains `"postgresql://u:CAN…`. The frames that held DSN text have returned before the raise, so the traceback's locals hold only `SecretStr` values.
- **Secret files** are read as bytes (at most 64 KiB + 1), decoded as UTF-8 and stripped. DSNs and the vault token are `pydantic.SecretStr`, so `repr` and `str` print `**********`.
- **DSN check (#45), applied to all three DSNs** (app, retention, migrate):
  - The DSN is parsed with `psycopg.conninfo.conninfo_to_dict`. That function returns only what the string itself sets: `PGSSLMODE` is not applied and `service=` is not expanded.
  - `sslmode` must be one of `require`, `verify-ca` or `verify-full`. The match is case-sensitive, as in libpq.
  - A DSN with no sslmode, or with `disable`, `allow` or `prefer`, is refused. So is `service=…` alone.
  - A DSN containing a NUL byte is refused as invalid. libpq silently truncates at the NUL, so an `sslmode` after it would be dropped.
- **psycopg is imported lazily** inside the DSN check. Importing `bitscan_manager.config` or `bitscan_manager.cli` loads no `psycopg`, `sqlalchemy` or `alembic` (REQ-020 (7) safety for TASK-013).
- **Environment lookups.** Only `environ.get(name)` is called, and only for the profile's own names. The mapping is never iterated or copied. The serve profile never mentions `BITSCAN_MIGRATE_DSN_FILE`; the db profile mentions only that name. Plain look-alikes are never read.
- **TLS cert and key:** `is_file()` and `os.access(R_OK)` only; the content is not read.
- **`BITSCAN_LISTEN`:** default `0.0.0.0:8443`, split on the last `:`. A `[v6]` host must be in brackets and non-empty. An unbracketed host with `:` is refused. The port must be ASCII digits from 1 to 65535, so `+80` and non-ASCII digits are refused.
- **`BITSCAN_BITS_DIR`:** default `/var/lib/bitscan/bits`; `uploads_dir` is that path plus `uploaded`. No file-system check.
- No logging, no network, no I/O beyond the named files.

## Checks run (Windows, `manager/.venv`)

- `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (15 files): pass. `pytest --cov=bitscan_manager/services --cov-fail-under=85`: 66 passed, 3 skipped (pg).
- A throwaway smoke script (deleted afterwards; the tester owns the real tests) ran with `PGSSLMODE=require` set, socket creation patched to raise, logging captured, and a canary password in every DSN and the vault token. Results:
  - valid serve config: OK, `BITSCAN_MIGRATE_DSN_FILE` never looked up;
  - all eight required variables missing: eight lines;
  - an empty variable, a look-alike only, and a missing, empty, non-UTF-8 or oversize file: each refused with the expected message;
  - app DSN with no sslmode, or with `disable`, `allow`, `prefer` or `REQUIRE`: refused; `verify-ca`: OK;
  - retention DSN with no TLS: refused;
  - `service=` only, a bad IPv6 URI, an unterminated quote, a NUL byte: refused;
  - listen `[::1]:8443` and `127.0.0.1:443`: OK; `h:0`, `h:65536`, `::1:8443`, `h`, `:8443`, `h:+80`, Arabic-Indic digits, `[]:80`: refused;
  - missing cert: refused;
  - db profile: OK when valid; missing and no-TLS cases refused.

  On every path, the canary appeared nowhere: not in `repr`/`str` of the configs or errors, not in the formatted exception chain, not in captured stdout, stderr or logs. No socket was opened.

## Revision 1 (reviewer pre-review should-fix, REQ-019 (11))

`BITSCAN_LISTEN="h:" + "9" * 5000` raised an uncaught `ValueError`: Python refuses to convert integers of more than 4300 digits. `startup.py` lines 132–137 now check `len(port) <= 5`, then ASCII digits only, before `int(port)`. That case now gets the fixed `BITSCAN_LISTEN must be host:port with a port from 1 to 65535` message. Nothing else changed. Checked: a 5000-digit port and `h:000080` are refused; `h:00080`, `h:65535` and `h:8443` are accepted. ruff, format, mypy (16 files) and pytest (73 passed, 10 skipped) are green. The reviewer's note for #24, with no change now: if the sink URL or vault address ever carries credentials, wrap them in `SecretStr`.

## Revision 2 (TEST FAIL on REQ-019 (3), lead ruling 2026-10-20)

REQ-019 (3) applies to every `*_FILE` variable, including the TLS certificate and key. `readable_file` (`startup.py` lines 117–134) still never reads the content. It now takes the size from `stat()` (inside a `try`, so an `OSError` race gives the "missing or unreadable" message) and refuses a 0-byte file with `X: file is empty`. That is fixed text with the variable name and no path. Whitespace-only TLS files stay out of scope, because catching them would need a read. Nothing else changed. Gates: ruff, format and mypy (21 files) pass; `tests/test_config.py` 152 passed, 2 skipped; full suite 249 passed, 12 skipped.

## For the tester (TP-M1-03)

- `ConfigError` messages are newline-joined, one per problem. Assert with `in`, not equality, if several variables are wrong.
- On Windows, `Path` renders the default bits dir as `\var\lib\bitscan\bits`. Compare with `Path("/var/lib/bitscan/bits")`, not a string.
- Permission-based "unreadable" works only on Linux (as the plan says). On Windows use a missing file or a directory path.
- The 64 KiB cap and the NUL-byte refusal are robustness limits, not spec behaviour. Both give the named-variable messages above.
