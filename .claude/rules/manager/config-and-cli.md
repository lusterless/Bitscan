---
paths:
  - "manager/**/config/**"
  - "manager/**/services/settings/**"
  - "manager/**/cli/**"
---

# Start-up configuration, runtime settings and the server CLI

Spec: TS §8.6 (configuration), §8.7 (deployment and CLI), §8.2 (configuration rule). Start-up configuration comes from environment variables or root-only files; anything an admin changes at runtime lives in the `setting` table.

## Start-up configuration (`/etc/bitscan/manager.env` + unit credentials; restart to change)

- Required: `BITSCAN_DB_DSN_FILE` (`%d/app_dsn`, the `bitscan_app` DSN; refuse a DSN without TLS), `BITSCAN_RETENTION_DSN_FILE`, `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF` (vault key that encrypts TOTP seeds), `BITSCAN_VAULT_TOKEN_FILE` (`%d/vault_token`), `BITSCAN_TLS_CERT_FILE`, `BITSCAN_TLS_KEY_FILE`, `BITSCAN_AUDIT_SINK`. Fail start-up if any is missing.
- Optional: `BITSCAN_LISTEN` (default `0.0.0.0:8443`, HTTPS), `BITSCAN_BITS_DIR` (default `/var/lib/bitscan/bits`; uploads go to its `uploaded/` subfolder).
- `BITSCAN_MIGRATE_DSN_FILE` is read only by `db migrate` and `db maintain`, which only the migrate and maintain units load; `serve` never reads it.
- Secrets are read from the `*_FILE` paths, never from plain environment values. `serve` reloads the TLS certificate on `SIGHUP`.

## Runtime settings (`setting` table, `/settings`)

- `GET` admin; `PATCH` admin with a TOTP session. Every change is audit-logged and alerts. The first migration seeds the defaults.

| Key | Default | Range |
| --- | --- | --- |
| `agent_token_ttl_days` | 365 | 60–730 (applies to tokens issued or rotated afterwards) |
| `job_pull_seconds` | 300 | 60–3,600 |
| `decommission_after_days` | 7 | 0 (never) – 365 |
| `redaction_patterns` | the five TS §8.6 defaults, exactly as written | RE2 patterns, max 50; removing a default needs a TOTP session and alerts |
| `max_parallel_plugins` | 2 | 1–8; sent to agents in the heartbeat |
| `enrolment_alert_per_hour` | 50 | 1–10,000 |
| `inventory_interval_s` | 21,600 | 3,600–86,400; stored in `system_schedule`, not `setting` |

- Validate every redaction pattern with RE2 before saving. There is no setting that disables inventory.

## Server CLI (`bitscan-manager`, run as root via `sudo`)

`users …` and `bits rebuild` read their DSN from `/etc/bitscan/secrets/app.dsn` (TS §8.7).

- `users create-admin <name>`: first admin; must enrol TOTP at first sign-in.
- `users create-api-token <user>`: writes the token hash to the database and shows the token once; alerts like UI creation.
- `users reset-totp <user>`: alerts, audit-logged, ends the user's sessions.
- `bits rebuild`: same rebuild as `POST /policies/rebuild` (catalog lock, `task` row, alert).
- `db migrate` and `db maintain`: run by `bitscan-manager-migrate.service` and `bitscan-manager-maintain.timer`, reading `BITSCAN_MIGRATE_DSN_FILE`, as `bitscan_migrate` with `SET ROLE bitscan_owner` (TS §8.6, §8.7; see `.claude/rules/manager/database.md`).
- `serve`: the manager service.

Tests (TS §8.3): Integration (settings validation and ranges, `PATCH /settings` refused for API tokens, CLI commands against Testcontainers PostgreSQL, start-up failure on missing required config).
