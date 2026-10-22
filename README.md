# Bitscan

Bitscan is a manager + agent platform that inventories Ubuntu/Debian endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported hosts are Ubuntu 22.04, Ubuntu 24.04 and Debian 12 (amd64 and arm64, cgroup v2).

**Status:** M2 (auth core and API plumbing). The manager runs:

- `bitscan-manager serve`: the HTTPS API with the health routes, sign-in and sign-out, TOTP enrolment (`/api/v1/auth/totp/enrol`), password change (`/api/v1/auth/password`), API tokens (`/api/v1/api-tokens`) and user administration (`/api/v1/users`);
- the server commands `users create-admin`, `users create-api-token` and `users reset-totp`;
- `db migrate` and `db maintain`.

The agent and the web UI do not run yet.

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
| `BITSCAN_VAULT_ADDR` | server | yes | OpenBao address (Vault Transit API), `https://host[:port]`, no credentials, query or fragment |
| `BITSCAN_TOTP_KEY_REF` | server | yes | Name of the Transit key that encrypts TOTP seeds (letters, digits, `_`, `-`, `.`; at most 128) |
| `BITSCAN_VAULT_TOKEN_FILE` | server | yes | File holding the manager's OpenBao token |
| `BITSCAN_TLS_CERT_FILE`, `BITSCAN_TLS_KEY_FILE` | server | yes | Server certificate (chain) and private key, PEM |
| `BITSCAN_AUDIT_SINK` | server | yes | `https://host[:port]/path` or `syslog+tls://host[:port]` (default port 6514); no credentials |
| `BITSCAN_LISTEN` | server | no | `host:port` or `[v6-address]:port`, port 1–65535; default `0.0.0.0:8443` |
| `BITSCAN_BITS_DIR` | server | no | Policy folder, default `/var/lib/bitscan/bits`; uploads go to its `uploaded/` subfolder |

The "server" variables are read by `bitscan-manager serve`. It never reads `BITSCAN_MIGRATE_DSN_FILE`.

Rules the loader enforces:

- **Secret files** must be readable UTF-8, not empty, and at most 64 KiB. Surrounding whitespace, such as a final newline, is removed. The certificate and key must be readable, non-empty files; `serve` then loads them and exits 2 if they are not a matching certificate and key.
- **DSNs** may be key/value (`host=db.example dbname=bitscan user=bitscan_migrate password=... sslmode=verify-full`) or URI form (`postgresql://user:pass@host/bitscan?sslmode=require`).
  - All three DSNs must set `sslmode` to `require`, `verify-ca` or `verify-full` in the DSN itself. `PGSSLMODE` and `service=` entries do not count, and `disable`, `allow`, `prefer` or a missing `sslmode` are refused.
  - A DSN containing a NUL byte is refused.
- **Errors:** every problem is reported at once, one line per variable, naming the variable but never its value or file content. `serve` and the `db` commands exit 2 on a configuration error.

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

`bitscan-manager serve` runs the manager. In production it runs as the `bitscan-manager` user under `bitscan-manager.service`, which loads the secrets as unit credentials (TS §8.7); a production install method is not provided yet.

- **Before the first start:** run `db migrate`. The audit queue folder `/var/lib/bitscan/audit-queue/` must belong to the `bitscan-manager` user with mode `0700`; `serve` creates it that way if it is missing (its parent must be writable) and refuses one that group or others can access.
- **Listening:** HTTPS only, on `BITSCAN_LISTEN`, TLS 1.2 or later; there is no plain-HTTP listener and no redirect. One process, one worker. `X-Forwarded-For` and `Forwarded` are ignored: the client address is the TCP peer.
- **Certificate reload:** `systemctl reload bitscan-manager` (or `kill -HUP <pid>`) loads the certificate and key files again for new connections, on the same process and socket. If the new pair cannot be loaded, the old one stays in use and an error is logged.
- **Stopping:** `SIGTERM` stops the server, writes the pending failed token-check counts to the audit log, and leaves queued audit entries on disk. It exits 0.
- **Logs:** one JSON object per line on stderr, each with `request_id`, `agent_id` and `job_id`. Access records hold the method, the path without its query string, the status and the duration. Tokens, passwords, headers, bodies and any part of a DSN (host, port, user, database) are never logged; database driver warnings keep only their fixed text.
- **Start-up errors:** a missing or invalid variable, an unusable certificate or key, a plain `BITSCAN_AUDIT_SINK` (`http://`, `tcp://`, `udp://` or `syslog://`) and an unsafe queue folder each print one `serve: …` line naming the variable or folder, and exit 2. An unreachable database or OpenBao does not stop start-up: `/readyz` reports the database, and sign-in of users with TOTP answers 503 until OpenBao is back.

**Health routes** (no token, outside `/api/v1`):

- `GET /healthz` returns `{"status": "ok"}` whenever the process answers.
- `GET /readyz` returns `{"status": "ok"}` only when the database answers as `bitscan_app`, the schema is at the packaged migration head, and the three `system_schedule` rows exist. Otherwise it returns 503 with `detail` set to `db`, `migrations` or `system_schedule`, within about 4 seconds.

**Audit sink** (`BITSCAN_AUDIT_SINK`): every committed audit entry is sent in `audit_id` order, with every column, so the receiver can verify the hash chain.

- Prefer `https://`: each entry is one JSON `POST`, and a `2xx` acknowledges exactly that entry.
- With `syslog+tls://` (RFC 5424 messages, RFC 5425 framing), a frame is counted as delivered when it is written, because syslog has no acknowledgement. Watch the receiver for gaps in `audit_id`.
- The sink certificate is checked against the system CA store. While the sink is unreachable, entries queue in `/var/lib/bitscan/audit-queue/` and an `audit_sink_unreachable` alert is written. After 15 minutes of outage, sensitive actions are refused until the queue has drained.

**OpenBao** (Vault Transit API): the manager calls `POST /v1/transit/encrypt/<key>` and `/decrypt/<key>` with the token from `BITSCAN_VAULT_TOKEN_FILE`, checking the server certificate against the system CA store; proxy settings in the environment are ignored. Use a periodic or non-expiring token whose policy allows only those two paths for the TOTP key. The manager does not renew tokens, so replacing the token is an operational step (update the credential, then restart the service).

`bitscan-manager --help` lists the commands that work: `serve`, `users …`, `db migrate` and `db maintain`. Every other command, including `bits rebuild`, prints a usage line and `unknown or not yet implemented command`, and exits 2, without reading configuration or touching the database.

## API

Every route below is under `/api/v1` and needs `Authorization: Bearer <token>`, except sign-in. Session tokens start `bsu_`, API tokens `bsk_`; agent tokens are refused here. Errors are `application/problem+json` with `type`, `title`, `status`, `detail` and `instance`; invalid input gets 400. Timestamps are UTC and end in `Z`. Lists return `{"items": [...], "next_cursor": ...}` and take `?limit=` (1–500, default 50) and `?cursor=`; a cursor stops working when the manager restarts.

- **Sign-in:** `POST /auth/login` with `{"username", "password", "totp_code"}` returns `{token, expires_at, role, totp_enrolled, totp_verified}`. The session lasts at most 24 hours and ends after 8 hours without use. Every failure gives the same 401. Users with TOTP must give a code, and each code works once. Failed sign-ins slow the account down (1 second, doubling to 15 minutes; never a hard lock), and each source address may try 10 times a minute. An admin without TOTP gets a session that can only enrol TOTP or sign out.
- **Sign-out:** `POST /auth/logout` ends the presenting session.
- **TOTP enrolment:** `POST /auth/totp/enrol`, session only, in two calls. The first, `{}` (or `{"current_password", "current_code"}` to replace an existing TOTP), returns `{secret, otpauth_uri}` for the authenticator app; the new secret waits in memory for 10 minutes. The second, `{"totp_code"}` with a code from the app, stores it and returns a new TOTP-verified session in the same shape as sign-in; every other session of the user ends. Wrong passwords or codes during a replacement count as failed sign-ins.
- **Password change:** `POST /auth/password`, session only, with `{"current_password", "new_password"}` (12–1,024 characters). It answers 204 and ends every session of the user, including this one, so sign in again; API tokens keep working.
- **API tokens:** `POST /api-tokens` (session only; admins need a TOTP-verified session) with `{"name", "expires_in_days"}` (1–365, default 90) returns `{token_id, token, name, expires_at}`; the token is shown only this once. `GET /api-tokens` lists your own tokens, without the token. `DELETE /api-tokens/{token_id}` revokes one of your own; an API token may revoke itself.
- **Users:** `/users` needs an admin with a TOTP-verified session, and is refused for API tokens and while the audit sink has been down for 15 minutes. `GET /users` lists, `POST /users` with `{"username", "password", "role"}` creates a viewer (default) or operator, and `GET /users/{user_id}` reads; items are `{user_id, username, role, disabled, totp_enrolled, created_at}`. `PATCH /users/{user_id}` takes exactly one change: `{"role"}`, `{"disabled": false}` (re-enable), `{"totp": null}` (reset another user's TOTP) or `{"revoke_tokens": true}`. `DELETE /users/{user_id}` disables the user; users are never deleted. Promotion to admin needs TOTP already enrolled, the last active admin cannot be demoted or disabled, a role change ends the user's sessions, and lowering a role or disabling also revokes their API tokens.
- **Limits:** 600 requests a minute per user; after 20 failed token checks in a minute from one address, further bad tokens get 429 (valid tokens still work).

## Users

The `users` commands run on the server as root (`sudo bitscan-manager users …`). They read the `bitscan_app` DSN from `/etc/bitscan/secrets/app.dsn`, with the same checks as the server's DSN (readable, at most 64 KiB, and `sslmode` set to `require`, `verify-ca` or `verify-full`). They contact only PostgreSQL. Each writes an audit entry with actor `cli:root`; a running `serve` sends it to the audit sink.

- **`users create-admin <name>`** creates an admin with no TOTP. On a terminal it asks for the password twice without echo; otherwise it reads one line from standard input. The password is never taken from the command line or the environment. It must be 12 to 1,024 characters. Usernames are 1–64 characters of `A–Z`, `a–z`, `0–9`, `.`, `_`, `@` and `-`, and are case-sensitive. The admin's first sign-in gives a session that can only enrol TOTP or sign out. Alert: `admin_created`.
- **`users create-api-token <user> [--name NAME] [--days DAYS]`** prints a new `bsk_` API token on standard output, once; only its SHA-256 is stored. `--days` is 1–365 (default 90) and `--name` at most 64 characters. The user must exist and be enabled. Alert: `api_token_created`.
- **`users reset-totp <user>`** clears the user's TOTP and ends their sessions; their next sign-in works with the password only (an admin then gets the enrolment-only session). Alert: `totp_reset`.

Exit codes: 0 success; 1 refused (an existing or unknown user, a password or option that breaks a rule, a database error); 2 usage or DSN-file error. Messages name the rule or the DSN file path, never a password, token or DSN.
