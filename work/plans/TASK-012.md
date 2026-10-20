# TASK-012 plan: start-up configuration loader

REQ: REQ-019. Owner: impl-manager. Depends on: TASK-011 (psycopg at runtime, for DSN parsing). Files: `manager/bitscan_manager/config/__init__.py`, `manager/bitscan_manager/config/startup.py`. Tests: TP-M1-03 (tester). Open questions: #45 (TLS rule), #24 (marker).

## Spec quotes

- TS §8.6 L1302: "**Start-up configuration** (from `/etc/bitscan/manager.env` and the units' credentials, §8.7; changing them needs a restart)".
- TS §8.6 L1306–L1315: the variable table. Required: `BITSCAN_DB_DSN_FILE` ("File holding the `bitscan_app` PostgreSQL DSN (TLS required)"), `BITSCAN_RETENTION_DSN_FILE`, `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF`, `BITSCAN_VAULT_TOKEN_FILE`, `BITSCAN_TLS_CERT_FILE`, `BITSCAN_TLS_KEY_FILE`, `BITSCAN_AUDIT_SINK`. `BITSCAN_MIGRATE_DSN_FILE`: "set by the migrate and maintain units | those units only | … loaded only by those two units". Optional: `BITSCAN_LISTEN` (default `0.0.0.0:8443`), `BITSCAN_BITS_DIR` (default `/var/lib/bitscan/bits`; "uploads go to its `uploaded/` subfolder").
- TS §8.7 L1345: "Secrets live in `/etc/bitscan/secrets/` … handed to each unit with `LoadCredential=` … The `BITSCAN_*_FILE` variables point into the unit's credentials folder (`%d`)."
- TS §8.7 L1405–L1416 and L1439–L1449: the migrate and maintain units set only `EnvironmentFile=/etc/bitscan/manager.env` and `BITSCAN_MIGRATE_DSN_FILE=%d/migrate_dsn`. `BITSCAN_DB_DSN_FILE`, `BITSCAN_RETENTION_DSN_FILE`, `BITSCAN_VAULT_TOKEN_FILE` and the TLS variables are set only by `bitscan-manager.service` (L1367–L1371). **So the db profile must not require them.** This is read from the unit files, not invented.
- TS §8.1 L1259: "Manager secrets from a vault or root-only files (§8.6), never in the repo." `.claude/rules/manager/config-and-cli.md`: "Secrets are read from the `*_FILE` paths, never from plain environment values." "Fail start-up if any is missing."
- TS §8.4 L1287, TS §5.3 L1052: never write tokens to logs. A DSN password and the vault token are treated the same way.

## Interface (fixed contract for TASK-013, TASK-019 and M2)

```python
# bitscan_manager/config/startup.py
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from pydantic import SecretStr

class ConfigError(Exception):
    """Message names the variable and the problem only; never a value or file content."""

@dataclass(frozen=True)
class ServeConfig:
    db_dsn: SecretStr            # from BITSCAN_DB_DSN_FILE
    retention_dsn: SecretStr     # from BITSCAN_RETENTION_DSN_FILE
    vault_addr: str              # opaque (#24)
    totp_key_ref: str            # opaque (#24)
    vault_token: SecretStr       # from BITSCAN_VAULT_TOKEN_FILE
    tls_cert_file: Path          # checked readable, not loaded (serve loads it in M2)
    tls_key_file: Path           # checked readable, not loaded
    audit_sink: str              # opaque (#24)
    listen_host: str
    listen_port: int
    bits_dir: Path
    uploads_dir: Path            # bits_dir / "uploaded"

@dataclass(frozen=True)
class DbConfig:
    migrate_dsn: SecretStr       # from BITSCAN_MIGRATE_DSN_FILE

def load_serve_config(environ: Mapping[str, str]) -> ServeConfig: ...
def load_db_config(environ: Mapping[str, str]) -> DbConfig: ...
```

`config/__init__.py` re-exports these names. Callers pass `os.environ`; tests pass a dict. `SecretStr` (pydantic is already a dependency) gives `**********` in `repr` and `str`.

## Approach

1. A helper `_required(environ, name) -> str` raises `ConfigError(f"{name} is not set")` when the variable is missing or empty after stripping. Only names listed in the profile are ever looked up. The serve profile has no code path that mentions `BITSCAN_MIGRATE_DSN_FILE`, and the db profile only that name.
2. `_read_secret_file(name, path) -> SecretStr`: open the path, read at most 64 KiB, decode as UTF-8 and strip surrounding whitespace (credential files usually end in a newline). Missing, unreadable, non-UTF-8, empty or oversize files raise `ConfigError(f"{name}: cannot read the file it points to")`, or "file is empty". Use `raise … from None`, so the `OSError` (which holds the path, harmless) and any decode error (which can hold bytes of the content) are not chained. The 64 KiB cap is a robustness limit, not spec behaviour; the reviewer can drop it.
3. DSN check `_check_dsn(name, dsn)`: parse with `psycopg.conninfo.conninfo_to_dict`. On `psycopg.ProgrammingError`, raise `ConfigError(f"{name}: not a valid PostgreSQL DSN") from None`. **psycopg's parse error text quotes part of the DSN, which can include the password, so it must never be shown or chained.** Then apply the TLS rule: `sslmode` must be in the DSN itself and in the accepted set. The `PGSSLMODE` environment variable does not count, because the rule is about the credential file. Until #45 is answered, implement the accepted set as a module constant `TLS_SSLMODES`, with the suggested value `{"require", "verify-ca", "verify-full"}`, and apply the check to the app DSN, which is the only DSN where the spec states it. Applying it to the retention and migrate DSNs is one line per DSN, added or left out per #45.
4. `BITSCAN_LISTEN`: split on the last `:`. Allow a `[v6]` host in brackets. The port is an integer from 1 to 65535. Otherwise raise `ConfigError("BITSCAN_LISTEN must be host:port")`. No DNS lookup.
5. TLS cert and key: check `os.access(path, os.R_OK)` and `is_file()`, without reading the content. A failure raises an error naming the variable.
6. `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF` and `BITSCAN_AUDIT_SINK`: required and non-empty. They are not parsed further, because the vault API and sink format are open (#24). Add a code comment that points at #24.
7. `BITSCAN_BITS_DIR`: default `/var/lib/bitscan/bits`; `uploads_dir` is that path plus `uploaded`. No file-system check here (the importer, M7, owns that).
8. Collect errors or stop at the first one? Report **all** missing or invalid variables in one `ConfigError`, one line per variable, so an operator fixes them in one pass. That is not spec behaviour; either choice meets REQ-019 (2), which needs only "names that variable".
9. No logging, no I/O other than reading the named files, no network. Unknown `BITSCAN_*` variables are ignored.

## Edge cases

- Plain-value look-alikes (`BITSCAN_DB_DSN`, etc.) are never looked up, so setting one is a silent no-op, and the `_FILE` variable still reports missing.
- A DSN in URI form (`postgresql://u:p@h/db?sslmode=require`) and in key/value form both parse with `conninfo_to_dict`.
- A `service=` DSN entry would pull settings from `pg_service.conf`, and `sslmode` could hide there. With the rule "`sslmode` must be in the DSN itself", such a DSN is refused unless it also sets `sslmode`. Raise this in review if `service=` should be refused outright; the spec says nothing about it.
- On Windows, `os.access` and permission bits behave differently. Tests use a missing file, not chmod, for "unreadable" on Windows; the chmod case runs only on Linux.
- `ConfigError` must not include the file path's content, but may include the path itself. The path is not a secret (`%d/app_dsn`).

## Not in this task

- Wiring `serve` (M2) and SIGHUP reload (M2).
- Runtime settings (`setting` table, `/settings`; M2/M3).
- Vault access and TOTP-key decryption (M2, #24).
- The CLI's own DSN for `users …` and `bits rebuild` (`/etc/bitscan/secrets/app.dsn`, TS §8.7 L1347; M2 and M7).
