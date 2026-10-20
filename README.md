# Bitscan

Bitscan is a manager + agent platform that inventories Ubuntu/Debian endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported hosts are Ubuntu 22.04, Ubuntu 24.04 and Debian 12 (amd64 and arm64, cgroup v2).

**Status:** M1 (database and audit core) in progress. The manager has its configuration loader, database schema and the `db migrate` and `db maintain` commands. The API server, the agent and the web UI do not run yet.

The specifications are in `docs/spec/`: `Technical_Specification.md` and `bit_Schema_Reference.md`.

## Prerequisites

- Python 3.12, and `uv` to regenerate the lock files.
- PostgreSQL 16 with the `pg_trgm`, `pgcrypto` and `debversion` extensions (Debian/Ubuntu package `postgresql-16-debversion`). The server must accept TLS connections.
- To run the PostgreSQL tests: Docker. On Windows, use Docker Engine inside WSL2 (Ubuntu 24.04).

## Setup (development)

From the repository root:

```sh
python -m venv manager/.venv          # Linux/macOS: manager/.venv/bin/..., Windows: manager/.venv/Scripts/...
manager/.venv/Scripts/python.exe -m pip install --require-hashes -r manager/requirements-dev.txt
manager/.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e manager
```

- `manager/requirements.txt` holds the runtime dependencies only. `manager/requirements-dev.txt` adds the test, lint and build tools, including the build backend, so the last command downloads nothing unhashed.
- Both lock files install from wheels only (`--only-binary :all:`) and with hash checks.
- To change a dependency, edit `manager/pyproject.toml`, then rerun the `uv pip compile` command written at the top of each lock file. The `--exclude-newer` date there fixes the result; move it forward only to take newer releases.
- A production install method is not provided yet.

## Configuration

Start-up configuration comes from environment variables. Secrets are read only from the files that the `*_FILE` variables point to, never from plain variables. `BITSCAN_DB_DSN`, for example, is ignored.

| Variable | Used by | Required | Meaning |
| --- | --- | --- | --- |
| `BITSCAN_MIGRATE_DSN_FILE` | `db migrate`, `db maintain` | yes | File holding the `bitscan_migrate` DSN |
| `BITSCAN_DB_DSN_FILE` | server | yes | File holding the `bitscan_app` DSN |
| `BITSCAN_RETENTION_DSN_FILE` | server | yes | File holding the `bitscan_retention` DSN |
| `BITSCAN_VAULT_ADDR` | server | yes | Vault address (any non-empty text) |
| `BITSCAN_TOTP_KEY_REF` | server | yes | Vault reference of the TOTP key (any non-empty text) |
| `BITSCAN_VAULT_TOKEN_FILE` | server | yes | File holding the vault token |
| `BITSCAN_TLS_CERT_FILE`, `BITSCAN_TLS_KEY_FILE` | server | yes | Server certificate and key |
| `BITSCAN_AUDIT_SINK` | server | yes | Audit sink endpoint (any non-empty text) |
| `BITSCAN_LISTEN` | server | no | `host:port` or `[v6-address]:port`, port 1–65535; default `0.0.0.0:8443` |
| `BITSCAN_BITS_DIR` | server | no | Policy folder, default `/var/lib/bitscan/bits`; uploads go to its `uploaded/` subfolder |

The "server" variables are checked by the server's configuration loader, which no command uses yet.

Rules the loader enforces:

- **Secret files** must be readable UTF-8, not empty, and at most 64 KiB. Surrounding whitespace, such as a final newline, is removed. The certificate and key must be readable, non-empty files; their content is not read at start-up.
- **DSNs** may be key/value (`host=db.example dbname=bitscan user=bitscan_migrate password=... sslmode=verify-full`) or URI form (`postgresql://user:pass@host/bitscan?sslmode=require`).
  - All three DSNs must set `sslmode` to `require`, `verify-ca` or `verify-full` in the DSN itself. `PGSSLMODE` and `service=` entries do not count, and `disable`, `allow`, `prefer` or a missing `sslmode` are refused.
  - A DSN containing a NUL byte is refused.
- **Errors:** every problem is reported at once, one line per variable, naming the variable but never its value or file content. `db` commands exit 2 on a configuration error.

## Database

**Bootstrap**, once, as a PostgreSQL superuser (TS §5.2), then give the three login roles passwords:

```sql
CREATE ROLE bitscan_owner NOLOGIN;
CREATE ROLE bitscan_app LOGIN;
CREATE ROLE bitscan_retention LOGIN;
CREATE ROLE bitscan_migrate LOGIN IN ROLE bitscan_owner;
CREATE DATABASE bitscan OWNER bitscan_owner;
REVOKE ALL ON DATABASE bitscan FROM PUBLIC;
GRANT CONNECT ON DATABASE bitscan TO bitscan_app, bitscan_retention, bitscan_migrate;
\c bitscan
ALTER SCHEMA public OWNER TO bitscan_owner;
GRANT USAGE ON SCHEMA public TO bitscan_app, bitscan_retention;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS debversion;
```

**`bitscan-manager db migrate`** upgrades the schema with `BITSCAN_MIGRATE_DSN_FILE`:

- It connects as `bitscan_migrate` and runs `SET ROLE bitscan_owner`, so `bitscan_owner` owns every object.
- It applies, in order, every forward-only migration in `manager/bitscan_manager/db/migrations/versions/` that has not run yet. Together they create the tables, grants and seed rows, and the `scan_result` partitions for the current UTC month and the next three.
- It prints the head revision id. A second run changes nothing.
- There is no downgrade.

**`bitscan-manager db maintain`** is meant to run daily, with the same DSN and role switch:

- It creates the missing monthly partitions `scan_result_YYYY_MM` for the current UTC month and the next three.
- It drops partitions whose upper bound is at least 400 days in the past. It deletes no rows.
- It prints `created <name>`, `dropped <name>` or `nothing to do`.
- It refuses and changes nothing (exit 1) if `scan_result_default` holds rows in a month it must create, or if a partition does not cover exactly one UTC month.
- **Clock guard:** all drops are refused if any of these holds:
  - no partition contains the current time;
  - `scan_result` holds rows dated after the current time;
  - the existing partitions (as found before this run creates any) have a gap: a UTC month missing between the oldest and the newest.

  The missing partitions are still created. The command exits 1 with a message naming the clock time and any missing months (`YYYY-MM`). Check the system clock, and remove stray partitions, for example ones created while the clock was wrong.
- If `db maintain` has not run for about three months, a gap appears, and drops stay refused until an operator has checked.
- Two overlapping runs do not conflict: the second waits for the first.

Exit codes for both commands: 0 success, 1 database failure or refusal, 2 configuration or usage error. Messages never contain the DSN or its password.

## Running the checks

From the repository root, with the venv activated:

```sh
source manager/.venv/Scripts/activate   # Linux/macOS: source manager/.venv/bin/activate
ruff check manager && ruff format --check manager
mypy --strict --config-file manager/pyproject.toml manager
cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85
```

- Tests marked `pg` start PostgreSQL 16 in Docker (Testcontainers, image built from `manager/tests/postgres/Dockerfile`).
- Without Docker they are skipped as `not run: Docker unavailable`. With `CI=true` a missing Docker fails the run instead.
- The PostgreSQL tests read the TS §5.2 bootstrap and schema from `docs/spec/Technical_Specification.md`, so they need the repository layout: at least `manager/` and `docs/`.
- On Windows, run the PostgreSQL tests inside WSL2: copy the working tree to a Linux path, without `manager/.venv`, `node_modules` and `__pycache__`. Then, from `manager/` there:

```sh
python3.12 -m venv <venv>
<venv>/bin/python -m pip install --require-hashes -r requirements-dev.txt
<venv>/bin/python -m pip install --no-deps --no-build-isolation -e .
CI=true SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
RYUK_CONTAINER_IMAGE=testcontainers/ryuk:0.8.1@sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e \
<venv>/bin/python -m pytest --cov=bitscan_manager/services --cov-fail-under=85 -rs
```

`-rs` lists the reason for every skipped test.

The tests run the installed `bitscan-manager` command, so the editable install is required. `SSL_CERT_FILE` is needed only behind a TLS-intercepting proxy whose root certificate is in the system store.

## Starting the app

The API server is not implemented yet; it is planned for M2 and M3. `bitscan-manager --help` lists the commands that work: `db migrate` and `db maintain`. Every other command, including `serve`, `users …` and `bits rebuild`, prints a usage line and `unknown or not yet implemented command`, and exits 2, without reading configuration or touching the database.
