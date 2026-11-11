# Bitscan

Bitscan is a manager + agent platform that inventories Ubuntu endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported agent hosts are Ubuntu 22.04 and Ubuntu 24.04 (amd64, cgroup v2). The manager host is Ubuntu 24.04 on amd64.

**Status:** the current release is 0.2.0: manager `0.2.0` and agent package `0.2.0-1` (git tag `v0.2.0`). It adds compliance scans to release 0.1.0: the policy catalog, scans and schedules, results, scores, CSV export, re-evaluation and retention. Release 0.1.0 (manager `0.1.0`, agent package `0.1.0-1`) covers enrolment and approval, heartbeat, the mandatory inventory (`os_info` and the full `dpkg` package list), the host pages and fleet-wide package search; its agent runs no check and answers every check of a compliance job with `runner_unavailable`. The pre-release agent builds (`0.1.0~preN-1`, `0.2.0~preN-1`) are not supported. Upgrade them to `0.2.0-1` as described in [Installing a release](#installing-a-release).

The manager runs:

- `bitscan-manager serve`: the HTTPS API with the health routes, sign-in and sign-out, TOTP enrolment (`/api/v1/auth/totp/enrol`), password change (`/api/v1/auth/password`), API tokens (`/api/v1/api-tokens`), user administration (`/api/v1/users`), enrolment tokens and requests, the host routes (`/api/v1/agents`), fleet package search and its CSV export (`/api/v1/packages/search`), the policy catalog (`/api/v1/policies`, `/api/v1/imports`, `/api/v1/tasks`), compliance scans, their results, scores, CSV export and re-evaluation, and scan schedules (`/api/v1/scans`, `/api/v1/scan-schedules`), runtime settings, the audit log and metrics; the six agent routes under `/api/v1/agent/`; the scheduler (inventory runs, `offline_sweep`, scheduled scans and [retention](#retention)); and the [web UI](#web-ui);
- the folder watcher, which imports `.bit` policy files as they change (see [Policies](#policies));
- the server commands `users create-admin`, `users create-api-token`, `users reset-totp` and `bits rebuild`;
- `db migrate` and `db maintain`.

The agent package (`bitscan-agent`) installs the `bitscan-agent` and `bitscan-runner` services. The agent enrols, sends a heartbeat every 5 minutes, pulls its jobs and uploads the inventory.

**Compliance scans and results (from release 0.2.0).** Hosts on agent `0.2.0-1` run compliance jobs:

- The agent hands each job to `bitscan-runner`. The runner runs every check in its sandbox as the `bitscan-runner` user: it can read every file, but it cannot write outside its private `/tmp` or open IP connections.
- The runner redacts the output on the host and returns it.
- The agent keeps the results in an on-disk spool until the manager has answered them.
- The optional `bitscan-capread` helper stays off until an administrator enables it on the host.

The manager lists scans, shows each host's results and score, exports them as CSV and re-evaluates them (see [Scan results](#scan-results)). It also deletes old data on a schedule (see [Retention](#retention)). [`agent-install.md`](deploy/runbooks/agent-install.md) sections 9 to 11 cover the cgroup v2 requirement, `runner_unavailable`, the helper and the spool.

The specifications are in `docs/spec/`: `Technical_Specification.md` and `bit_Schema_Reference.md`.

## Installing a release

Production installs follow the runbooks in `deploy/runbooks/`:

| Runbook | Covers |
| --- | --- |
| [`manager-install.md`](deploy/runbooks/manager-install.md) | A new manager host: PostgreSQL with TLS-only roles, the `bitscan-manager` user and folders, configuration and secrets, the Python package, the four systemd units, the schema and the first admin |
| [`manager-operations.md`](deploy/runbooks/manager-operations.md) | Upgrades, replacing the TLS certificate and the OpenBao token, backups and the monthly restore test, and removal |
| [`agent-install.md`](deploy/runbooks/agent-install.md) | Installing, checking, upgrading, re-enrolling and removing the agent on each host |

**Release files.** Each release is published on the project's GitHub release page. For 0.2.0 it holds:

- Manager: `bitscan_manager-0.2.0-py3-none-any.whl` (the built web UI is inside), `bitscan-manager-0.2.0-requirements.txt` (the hashed runtime dependencies), and the unit files `bitscan-manager.service`, `bitscan-manager-migrate.service`, `bitscan-manager-maintain.service` and `bitscan-manager-maintain.timer`.
- Agent: `bitscan-agent_0.2.0-1_amd64.deb`.
- CycloneDX SBOMs.
- `SHA256SUMS`, which lists every file above.

**Verifying downloads.** The release page shows the `SHA256SUMS` text in its notes. That page is served from a different origin than the file downloads. Copy the text from the release page into a file named `SHA256SUMS`, next to the files you downloaded. Never use a checksum file fetched from the download host, and that includes the `SHA256SUMS` file attached to the release. Then run:

```sh
sha256sum -c --ignore-missing SHA256SUMS
```

Each file you downloaded must show `OK`. Stop if any line says `FAILED`, if a downloaded file is missing from the output, or if no file was verified. There is no signed APT repository in this version, so this checksum check is the only way to verify the files.

**Versions and compatibility.**

- The manager and the agent use semantic versioning. The agent package version adds a Debian revision, for example `0.1.0-1`.
- A manager supports agents of its own version and the one before. An agent supports a manager of its own version and the one before. So manager 0.2.0 supports agents 0.2.0-1 and 0.1.0-1, and agent 0.2.0-1 supports managers 0.2.0 and 0.1.0.
- Upgrade order: the manager first (migrate, then restart), then the agents. See [`manager-operations.md`](deploy/runbooks/manager-operations.md) section 1 and [`agent-install.md`](deploy/runbooks/agent-install.md) section 6.

## Prerequisites

- Python 3.12, and `uv` to regenerate the lock files.
- PostgreSQL 16 with the `pg_trgm`, `pgcrypto` and `debversion` extensions (Debian/Ubuntu package `postgresql-16-debversion`). The server must accept TLS connections.
- To run the PostgreSQL tests: Docker. On Windows, use Docker Engine inside WSL2 (Ubuntu 24.04).
- To build the web UI: Node.js 24 and npm.

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
- This setup is for development. For a production install, see [Installing a release](#installing-a-release).

## Configuration

Start-up configuration comes from environment variables. Secrets are read only from the files that the `*_FILE` variables point to, never from plain variables. `BITSCAN_DB_DSN`, for example, is ignored. On an installed manager, the units read the settings that aren't secret from `/etc/bitscan/manager.env`. They point the `*_FILE` variables at their own copies of the files in `/etc/bitscan/secrets/` ([`manager-install.md`](deploy/runbooks/manager-install.md) section 5).

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

On a production host, set up the database with [`manager-install.md`](deploy/runbooks/manager-install.md) section 3, which also limits the three roles to TLS connections.

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

`bitscan-manager serve` runs the manager. In production it runs as the `bitscan-manager` user under `bitscan-manager.service`, which loads the secrets as unit credentials (TS §8.7). [`manager-install.md`](deploy/runbooks/manager-install.md) sets this up.

- **Before the first start:** run `db migrate`. The audit queue folder `/var/lib/bitscan/audit-queue/` must belong to the `bitscan-manager` user with mode `0700`; `serve` creates it that way if it is missing (its parent must be writable) and refuses one that group or others can access. Under `bitscan-manager.service` the folder must exist before the first start ([`manager-install.md`](deploy/runbooks/manager-install.md) section 4).
- **Listening:** HTTPS only, on `BITSCAN_LISTEN`, TLS 1.2 or later; there is no plain-HTTP listener and no redirect. One process, one worker. `X-Forwarded-For` and `Forwarded` are ignored: the client address is the TCP peer.
- **Certificate reload:** `SIGHUP` (`kill -HUP <pid>`, which is what `systemctl reload bitscan-manager` sends) makes the running process load the certificate and key files it was started with again, for new connections, on the same process and socket. If the new pair cannot be loaded, the old one stays in use and an error is logged. To replace the certificate of an installed manager, follow [`manager-operations.md`](deploy/runbooks/manager-operations.md) section 2.
- **Stopping:** `SIGTERM` stops the scheduler and then the server, writes the pending failed token-check counts to the audit log, and leaves queued audit entries on disk. It exits 0.
- **Logs:** one JSON object per line on stderr, each with `request_id`, `agent_id` and `job_id`. Access records hold the method, the path without its query string, the status and the duration. Tokens, passwords, headers, bodies and any part of a DSN (host, port, user, database) are never logged; database driver warnings keep only their fixed text.
- **Start-up errors:** a missing or invalid variable, an unusable certificate or key, a plain `BITSCAN_AUDIT_SINK` (`http://`, `tcp://`, `udp://` or `syslog://`) and an unsafe queue folder each print one `serve: …` line naming the variable or folder, and exit 2. An unreachable database or OpenBao does not stop start-up: `/readyz` reports the database, and sign-in of users with TOTP answers 503 until OpenBao is back.

**Health routes** (no token, outside `/api/v1`):

- `GET /healthz` returns `{"status": "ok"}` whenever the process answers.
- `GET /readyz` returns `{"status": "ok"}` only when the database answers as `bitscan_app`, the schema is at the packaged migration head, and the three `system_schedule` rows exist. Otherwise it returns 503 with `detail` set to `db`, `migrations` or `system_schedule`, within about 4 seconds.

**Audit sink** (`BITSCAN_AUDIT_SINK`): every committed audit entry is sent in `audit_id` order, with every column, so the receiver can verify the hash chain.

- Prefer `https://`: each entry is one JSON `POST`, and a `2xx` acknowledges exactly that entry.
- With `syslog+tls://` (RFC 5424 messages, RFC 5425 framing), a frame is counted as delivered when it is written, because syslog has no acknowledgement. Watch the receiver for gaps in `audit_id`.
- The sink certificate is checked against the system CA store. While the sink is unreachable, entries queue in `/var/lib/bitscan/audit-queue/` and an `audit_sink_unreachable` alert is written. After 15 minutes of outage, sensitive actions are refused until the queue has drained.

**OpenBao** (Vault Transit API): the manager calls `POST /v1/transit/encrypt/<key>` and `/decrypt/<key>` with the token from `BITSCAN_VAULT_TOKEN_FILE`, checking the server certificate against the system CA store; proxy settings in the environment are ignored. It reads the token once at start-up and never renews it, so use the periodic token of [`manager-install.md`](deploy/runbooks/manager-install.md) section 1.2, whose policy allows only those two paths for the TOTP key and renewing itself, and set up the renewal timer of section 5 there. To replace the token, follow [`manager-operations.md`](deploy/runbooks/manager-operations.md) section 3.

`bitscan-manager --help` lists the commands that work: `serve`, `users …`, `bits rebuild`, `db migrate` and `db maintain`. Every other command prints a usage line and `unknown or not yet implemented command`, and exits 2, without reading configuration or touching the database.

## Web UI

The manager serves the web UI from its own address, for example `https://manager.example:8443/`. The browser must trust the manager's certificate; with a private CA, add the CA to the browser.

**Building.** The release wheel already contains the built UI. To build it from a checkout, start from the repository root:

```sh
cd web
npm ci --ignore-scripts
npm run build
```

The build replaces the contents of `manager/bitscan_manager/webui/` with `index.html` and `assets/index-<hash>.js`. `serve` reads that folder once, at start-up, so restart it after a new build. Without a build, `serve` logs `web ui not built; serving the API only` and every UI address answers 404. A build larger than 32 MiB in total is not served, and one error line is logged.

**How it is served.**

- `GET /` returns the build's `index.html`, and `GET /assets/<file>` returns a file that was in the build's `assets/` folder when `serve` started. Both need no token, like the health routes; they hold no data. Every API call the UI makes carries the session token.
- Only `.js`, `.css`, `.svg`, `.png`, `.ico` and `.woff2` files are served, each with its fixed content type. Any other path, including `/index.html`, a sub-folder and `/favicon.ico`, gets the normal problem+json 404. There is no directory listing.
- UI pages use addresses after `#`, such as `/#/hosts/<agent_id>`, so they never reach the manager as paths.
- The UI keeps the session token in memory only. Reloading the page, signing out or any 401 answer signs you out.

**Signing in.** Enter the username, password and, for admins and users with TOTP, the current TOTP code. A failed sign-in always shows the same message. The password and code fields are emptied after every attempt.

- **An admin without TOTP** sees only the TOTP page until enrolment is done. Press **Start**, scan the QR code with an authenticator app (or type the secret shown under it), enter a code and press **Confirm**. A wrong code, or more than 10 minutes since Start, means you press Start again for a new secret.
- **A viewer or operator without TOTP** is offered the same page after each sign-in and may choose **Not now**.
- **TOTP** in the menu replaces an existing TOTP: give the current password and code, then confirm a code from the new secret. **Password** changes the password (at least 12 characters, typed twice); every session of the user ends, so sign in again.

**Pages by role:**

| Page | viewer | operator | admin |
| --- | --- | --- | --- |
| Hosts, host detail, Package search, Profiles, profile detail, Scans, scan detail, scan results, TOTP, Password | yes | yes | yes |
| Run scan, Schedules | no | yes | yes |
| Upload policy, Import history, Rebuild catalog | no | no | yes |
| Enrolment requests, Enrolment tokens | no | no | yes |

Admin actions on the enrolment pages, deleting a profile, rebuilding the catalog and re-evaluating a scan need a TOTP-verified session. If the session is not TOTP-verified, the page offers **Sign in again**.

- **Profiles:** every profile that isn't deleted, filtered by **All**, **Enabled** or **Disabled**. A name opens the profile page: its details and every check with its command. Admins also get **Enable** or **Disable**, **Clear override** and **Delete** (which asks for confirmation). A deleted profile shows **Deleted** and offers no actions.
- **Upload policy** (admin): choose a `.bit` file and press **Upload**. The page shows **Imported** or **Rejected** and the findings.
- **Import history** (admin): every import, newest first, with its findings.
- **Rebuild catalog** (admin): see [Rebuild](#rebuild).

- **Enrolment tokens:** the form's defaults create a single-use token valid for 24 hours, for any source address, without auto-approve. The new `bse_` token is shown once, with a **Copy** button; it cannot be shown again after **Done**. A token can be revoked from the list.
- **Enrolment requests:** **Show** switches between pending and decided requests. Each request shows the host, its source address, OS, agent version and machine-id. Any existing agent with the same hostname or machine-id is listed under a warning, because a cloned image shares the machine-id. **Approve** and **Reject** each ask for confirmation. A request already decided elsewhere shows "This request was already decided."
- **Hosts:** every host with its status, OS, agent version, last heartbeat and inventory, tags and runner helpers. A hostname opens the host page: identity and token times (never the token), the operating system and its raw `os_info`, the packages added and removed by the last inventory that changed the list, and the full package list.
- **Scans:** every scan, newest first, filtered by profile, host id, state and creation date (UTC). Operators and admins get **Run scan**, which is also on the page of an enabled profile: choose the profile and the target (hosts, tags or every host) and press **Run scan**; the new scan's page opens.
- **Scan detail:** the scan's profile, version, trigger, target and state, and one row per host with its jobs, the passed, failed and not-run counts and the [score](#scan-results), shown as a percentage rounded down to one decimal ("75.0 %"), or "n/a", with the error count beside it. Operators and admins get **Cancel scan** while the scan is not finished; admins get **Re-evaluate**. Both ask for confirmation.
- **Scan results:** one row per check of each host, filtered by status (PASS, FAIL, ERROR, Not run) and host. A re-evaluated result shows its current verdict with the original beside it. Operators and admins also see each check's output; viewers never do. **Export CSV** downloads the rows for the current filters.
- **Schedules** (operator and admin): list, create, edit and delete [schedules](#schedules).
- **Host detail** also lists the scans that included the host, newest first.
- **Package search:** the fields are the [package search parameters](#package-search). From 3 characters, **Name contains** suggests up to 10 package names; choosing one fills **Exact name**. **View** groups the results by package and version (the default) or by host. A version opens the hosts that have it, keeping the search's other filters. **Export CSV** downloads the result set on screen as `packages.csv`.

## API

Every route below is under `/api/v1` and needs `Authorization: Bearer <token>`, except sign-in. Session tokens start `bsu_`, API tokens `bsk_`; agent tokens are refused here. Errors are `application/problem+json` with `type`, `title`, `status`, `detail` and `instance`; invalid input gets 400. Timestamps are UTC and end in `Z`. Lists return `{"items": [...], "next_cursor": ...}` and take `?limit=` (1–500, default 50) and `?cursor=`; a cursor stops working when the manager restarts. Paths are matched exactly: a trailing slash (`/api/v1/agents/`) is not redirected and gets 404.

- **Sign-in:** `POST /auth/login` with `{"username", "password", "totp_code"}` returns `{token, expires_at, role, totp_enrolled, totp_verified}`. The session lasts at most 24 hours and ends after 8 hours without use. Every failure gives the same 401. Users with TOTP must give a code, and each code works once. Failed sign-ins slow the account down (1 second, doubling to 15 minutes; never a hard lock), and each source address may try 10 times a minute. An admin without TOTP gets a session that can only enrol TOTP or sign out.
- **Sign-out:** `POST /auth/logout` ends the presenting session.
- **TOTP enrolment:** `POST /auth/totp/enrol`, session only, in two calls. The first, `{}` (or `{"current_password", "current_code"}` to replace an existing TOTP), returns `{secret, otpauth_uri}` for the authenticator app; the new secret waits in memory for 10 minutes. The second, `{"totp_code"}` with a code from the app, stores it and returns a new TOTP-verified session in the same shape as sign-in; every other session of the user ends. Wrong passwords or codes during a replacement count as failed sign-ins.
- **Password change:** `POST /auth/password`, session only, with `{"current_password", "new_password"}` (12–1,024 characters). It answers 204 and ends every session of the user, including this one, so sign in again; API tokens keep working.
- **API tokens:** `POST /api-tokens` (session only; admins need a TOTP-verified session) with `{"name", "expires_in_days"}` (1–365, default 90) returns `{token_id, token, name, expires_at}`; the token is shown only this once. `GET /api-tokens` lists your own tokens, without the token. `DELETE /api-tokens/{token_id}` revokes one of your own; an API token may revoke itself.
- **Users:** `/users` needs an admin with a TOTP-verified session, and is refused for API tokens and while the audit sink has been down for 15 minutes. `GET /users` lists, `POST /users` with `{"username", "password", "role"}` creates a viewer (default) or operator, and `GET /users/{user_id}` reads; items are `{user_id, username, role, disabled, totp_enrolled, created_at}`. `PATCH /users/{user_id}` takes exactly one change: `{"role"}`, `{"disabled": false}` (re-enable), `{"totp": null}` (reset another user's TOTP) or `{"revoke_tokens": true}`. `DELETE /users/{user_id}` disables the user; users are never deleted. Promotion to admin needs TOTP already enrolled, the last active admin cannot be demoted or disabled, a role change ends the user's sessions, and lowering a role or disabling also revokes their API tokens.
- **Enrolment tokens:** `/enrollment-tokens` needs an admin with a TOTP-verified session. It is refused for API tokens, and once the audit sink has been down for 15 minutes. See [Enrolling agents](#enrolling-agents).
- **Enrolment requests:**
  - `GET /enrollment-requests?state=pending|decided|all` (admin, session or API token; default `pending`) lists held enrolments as `{request_id, kind, agent_id, hostname, machine_id, os_pretty_name, agent_version, source_ip, requested_at, token_expires_at, decision, decided_by, decided_at, matches}`.
  - `matches` lists every other agent with the same hostname or machine-id; this is how a cloned image shows up.
  - `POST /enrollment-requests/{request_id}/approve` and `/reject` need an admin TOTP-verified session.
- **Hosts:**
  - `GET /agents` (viewer) lists hosts by hostname, as `{agent_id, hostname, status, agent_version, os_id, os_version_id, os_pretty_name, last_heartbeat_at, last_inventory_at, tags, runner_helpers}`.
  - `GET /agents/{agent_id}` adds `machine_id`, `enrolled_at`, `last_seen_ip`, the token times, `os_info` and `last_snapshot`. The snapshot is `{snapshot_id, collected_at, package_count, added, removed}`: the package lines added and removed by the last inventory that changed the list.
  - `GET /agents/{agent_id}/packages` lists the host's packages by name, architecture and version (Debian version order).
  - No response holds a token or a token hash.
- **Package search:** `GET /packages/search` and `GET /packages/search.csv` (viewer). See [Package search](#package-search).
- **Scans:** `POST /scans` and `POST /scans/{scan_id}/cancel` (operator, session or API token); `GET /scans`, `GET /scans/{scan_id}`, `GET /scans/{scan_id}/results`, `GET /scans/{scan_id}/results.csv` and `GET /agents/{agent_id}/scans` (viewer, session or API token); `POST /scans/{scan_id}/reevaluate` (admin, TOTP-verified session). See [Scans](#scans) and [Scan results](#scan-results).
- **Scan schedules:** `/scan-schedules` (operator, session or API token, also for reading). See [Schedules](#schedules).
- **Tags:** `PUT /agents/{agent_id}/tags` (operator) with `{"tags": [...]}` replaces the whole set: up to 32 distinct tags, each 1–64 characters from `A–Z a–z 0–9 . _ : -`. `[]` clears them.
- **Revoke:**
  - `POST /agents/{agent_id}/revoke` (admin, TOTP-verified session) ends the agent's token at once, including a token still inside its rotation overlap. It answers 204.
  - Every agent call then gets 401 `token_revoked`, and the host must enrol again; that enrolment is held for approval.
- **Settings:** `GET /settings` (admin, session or API token) returns all seven runtime settings. `PATCH /settings` (admin, TOTP-verified session) changes any non-empty subset, all or nothing:

  | Key | Default | Range |
  | --- | --- | --- |
  | `agent_token_ttl_days` | 365 | 60–730; applies to tokens issued or rotated afterwards |
  | `job_pull_seconds` | 300 | 60–3,600; sent to agents in the heartbeat |
  | `decommission_after_days` | 7 | 0 (never) – 365 |
  | `redaction_patterns` | five built-in patterns | at most 50 RE2 patterns |
  | `max_parallel_plugins` | 2 | 1–8; sent to agents in the heartbeat |
  | `enrolment_alert_per_hour` | 50 | 1–10,000 |
  | `inventory_interval_s` | 21,600 | 3,600–86,400 (1–24 h) |

  - An unknown key, a wrong type or a value out of range gets 400 and changes nothing. No key can switch inventory off.
  - Every change writes one `settings_changed` alert entry holding the old and new values. Removing one of the default redaction patterns also writes `redaction_default_removed`.
- **Audit log:**
  - `GET /audit-log` (admin, session or API token) pages through the hash-chained log, newest first. Items are `{audit_id, actor, action, target, detail, detail_text, at, prev_hash, row_hash}`. `detail_text` is the stored detail exactly as it was hashed (`null` when `detail` is null); `detail` is the same value parsed.
  - Each item can be re-checked: `row_hash` is the lowercase hex SHA-256 of the UTF-8 JSON array `[prev_hash, audit_id, actor, action, target, detail_text, at]`, with `detail_text` and `at` used as the strings returned, written compactly (`,` and `:` with no spaces) and with non-ASCII characters left unescaped. Use `detail_text`, not `detail` written back as JSON: number forms such as `1e-07` would not match. Each item's `prev_hash` is the `row_hash` of the entry before it.
- **Metrics:**
  - `GET /api/v1/metrics` (viewer) returns the Prometheus text format (version 0.0.4). Give Prometheus a viewer API token as its bearer token.
  - The metrics are `bitscan_alerts_total{kind}`, `bitscan_agents{status}`, `bitscan_heartbeat_latency_seconds`, `bitscan_jobs_queued`, `bitscan_jobs_expired_total` and `bitscan_plugin_results_total{result}`.
  - `bitscan_plugin_results_total` counts stored check results by `result` (`PASS`, `FAIL` or `ERROR`). The plugin ERROR rate is `rate(bitscan_plugin_results_total{result="ERROR"}[5m]) / sum(rate(bitscan_plugin_results_total[5m]))`.
  - The agent and job counts are read from the database at each scrape. Labels never hold a hostname, token or agent id.
- **Limits:**
  - 600 requests a minute per user.
  - After 20 failed token checks in a minute from one address, counted across user and agent routes together, further bad tokens get 429. Valid tokens still work.
  - Request bodies are limited to 1 MiB.

## Package search

`GET /api/v1/packages/search` (viewer, session or API token) searches the packages of every host that is not decommissioned. It writes nothing.

| Parameter | Meaning |
| --- | --- |
| `q` | Package name contains this text (any letter case), or is similar to it (`pg_trgm`); 3–255 characters |
| `name` | Exact package name; not together with `q` |
| `version` | A Debian version; alone it matches that exact text |
| `version_op` | `lt`, `le`, `eq`, `ge` or `gt`: compare with `version` in Debian order (`1.10` is after `1.9`); needs `version` |
| `arch` | Exact architecture, for example `amd64` |
| `status` | `installed` (default): `install ok installed`, `hold ok installed` or `deinstall ok installed`. `any`: also removed packages whose configuration files remain |
| `os` | `ubuntu` (every version) or `ubuntu:24.04`, from the host's `os_info` |
| `tag` | Exact host tag |
| `host` | Hostname contains this text (any letter case) |
| `agent_id` | One host, in the hyphenated form |
| `group_by` | `package` (hosts per name, version and architecture) or `host` (matching packages per host) |

- Filters combine with AND. An empty or too long value, an unknown `version_op`, `status` or `group_by`, an invalid version or `agent_id`, `q` with `name`, or `version_op` without `version` gets 400 `invalid_request`. Its `detail` names the parameters, for example `Invalid request: query.q`, never the value. The characters `%`, `_` and `\` in `q` and `host` match literally.
- Items are `{name, version, architecture, status, agent_id, hostname}`; with `group_by=package` `{name, version, architecture, host_count}`; with `group_by=host` `{agent_id, hostname, package_count}`.
- Order: by name, then Debian version, architecture and hostname; host groups by hostname.
- `limit` (1–500, default 50) and `cursor` page as on every list. A cursor works only with the same filters and `group_by`; with others, or once the package or host it points at is gone, it gets 400 `Invalid request: query.cursor`.

```sh
curl -s -G https://manager.example:8443/api/v1/packages/search \
  -H 'Authorization: Bearer <token>' \
  --data-urlencode name=openssl --data-urlencode version=3.0.13 \
  --data-urlencode version_op=lt --data-urlencode group_by=package
```

**CSV export.** `GET /api/v1/packages/search.csv` takes the same parameters, except `limit` and `cursor`, and returns the whole result set as one file.

- The answer is `text/csv; charset=utf-8` (UTF-8 without BOM, CRLF line ends), with `Content-Disposition: attachment; filename="packages.csv"`. The first line holds the item keys, in the order above.
- At most 100,000 rows or groups. A larger result gets 400 `Invalid request: more than 100000 rows; narrow the filters`, before any CSV is sent.
- **Formula escaping:** a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return, or with whitespace followed by one of these, gets a leading `'`, so a spreadsheet shows it as text. Cells holding a comma, a double quote or a line break are then quoted, so `=HYPERLINK("http://x")` is written as `"'=HYPERLINK(""http://x"")"`.

## Policies

A compliance profile is one `<Policy>` in a `.bit` file. The file is UTF-8 XML holding exactly one `Policy`, its `Family` (the standard, for example `CIS Ubuntu 24.04`) and up to 5,000 `Plugin` checks. Each check has the shell command to run (`Execute`), and its output is compared with `ExpectedResult` using `Operator`. Checks are shown as `<family name> - <plugin name>`. [`docs/spec/bit_Schema_Reference.md`](docs/spec/bit_Schema_Reference.md) describes the format, every element and its limits, and the validation codes; its section 1.1 is a complete example. `<PolicyName>` is the profile's name and its unique key; the file name is never used as a name.

### Loading policies

A policy comes from one of two places, and lives in only one of them.

**The server folder.** `BITSCAN_BITS_DIR` (default `/var/lib/bitscan/bits`, owner `root:bitscan-manager`, mode 0750) is where a server administrator copies or moves `.bit` files.

- On Linux the manager watches the folder. It imports a file a few seconds after it is completely written or moved in, and removing a file deletes its policy.
- At start-up the manager imports what changed while it was down, and deletes the policies whose files are gone.
- Only regular files directly in the folder whose names end in `.bit` count. These are ignored:
  - hidden files (`.x.bit`) and other names;
  - sub-folders, symlinks, FIFOs and devices;
  - a name that is not valid UTF-8, holds a control character or is longer than 255 bytes. Such a name gets one log line and no import record.
- **Copy or move files into the folder; don't hard-link files into the bits folder.** The watcher sees only changes made through the folder. An edit made through another link to the same file is not imported until the next start-up or rebuild.
- Changing `<PolicyName>` inside the same file renames the policy and keeps its id, checks and history.
- Two server-folder files can't hold the same `<PolicyName>`. While the first still exists, the second is rejected with `BIT007`. If two new files share a name, the one whose file name sorts first byte by byte wins.

**Upload (admin).** Send `POST /api/v1/policies/import` with one multipart field, `file`. Use a session or an admin's `bsk_` API token, or the web UI's **Upload policy** page. The manager checks the file in memory. It keeps the file only if the import succeeds, as `uploaded/policy-<policy_id>.bit`; the name you uploaded it under is kept only in the import history.

```sh
curl -s https://manager.example:8443/api/v1/policies/import \
  -H 'Authorization: Bearer <token>' -F file=@cis-ubuntu-24.04.bit
```

- **The answer** is 200 for both outcomes: `{import_id, outcome, policy_id, policy_name, policy_version, plugins_added, plugins_updated, plugins_retired, errors}`.
  - `outcome` is `success` or `rejected`.
  - `errors` lists every finding, warnings included, as `{line, element, code, message}`.
  - A file larger than 5 MiB gets 413.
  - A 503 after an upload means the policy may already be live. Check the policy list or the import history before you upload it again. After "The import was stored but its record could not be written.", check the policy list (its version and imported time); this case has no import-history row.
- **The server folder wins.**
  - A policy whose file is in the server folder can't be uploaded: it gets 409 `policy_managed_on_server`. Change its file in the folder instead.
  - A server-folder file with the name of an uploaded policy takes that policy over: the policy moves to the server file, the uploaded copy is deleted, and the move is recorded in the audit log.

### What an import does

- **Validation.** The file is read once, with DTDs and external entities refused, and checked against every rule. One failing rule rejects the whole file, and nothing changes.
  - The codes `BIT001`–`BIT017` and `BIT102` reject the file; `BIT101` and `BIT103` are warnings.
  - `BIT102` refuses commands that write to or change the host: for example `rm`, `cp`, `tee`, `sed -i`, `apt install`, `systemctl stop`, `eval`, `source`, `xargs`, `find -exec`, and output redirection anywhere other than `/dev/null`, `/dev/stdout`, `/dev/stderr` or `/tmp/`. Rewrite such checks as the schema reference describes, for example with `find … -print` and a `while read` loop.
  - `BIT102` is only a safety net: what stops a command from changing the host is the agent's sandbox.
- **Live at once.** A successful import is stored in one transaction, and every scan job queued after it uses it; jobs already queued keep their commands. If the file's content changed, the policy's `version` goes up by 1. Checks that no profile lists any more are retired, not deleted, so old results stay readable.
- **Automatic imports** (by the watcher and at start-up) skip a file whose content hasn't changed since its last successful import, and record it as `skipped`. Uploads and rebuilds never skip a file.
- **Alerts.** Every import writes an audit entry.
  - A successful import raises `policy_imported`. It carries, in full, every `Execute` that goes live with the import: new, changed, or active again.
  - A rejected import raises `policy_import_rejected`.
- **Audit-sink entry size.** One `policy_imported` entry can be as large as the file's commands: up to about 10 MiB of JSON for a 5 MiB file. The HTTPS sink accepts this. A `syslog+tls://` receiver must accept messages that large; many cut messages at 8 KiB by default, so raise its limit before you load large policies.

### Status, delete and history

- **List and read (viewer).**
  - `GET /api/v1/policies` (optionally `?status=enabled` or `disabled`) lists the profiles that aren't deleted, ordered by name. Each item is `{policy_id, policy_name, policy_description, policy_status, file_status, status_overridden, family_id, family_name, format_version, version, source_file, plugin_count, imported_at, updated_at}`.
  - `GET /api/v1/policies/{policy_id}` adds `deleted_at` and `plugins`: every check, in file order, with its command.
- **Status (admin, session or API token).** `PATCH /api/v1/policies/{policy_id}`:
  - `{"policy_status": "disabled"}` (or `"enabled"`) sets the status and an override (`status_overridden: true`). Later file updates then change only `file_status`.
  - `{"status_overridden": false}` clears the override and takes the file's own status again.
  - A disabled profile can't be chosen for new scans; scans already running finish.
  - Re-enabling a profile raises `policy_reenabled`. A deleted policy gets 409.
- **Delete (admin, TOTP-verified session).** `DELETE /api/v1/policies/{policy_id}` answers 204. It is refused for API tokens, and once the audit sink has been down for 15 minutes.
  - The policy is marked deleted, not removed, so old results stay readable. It leaves selection, its queued jobs are cancelled, its schedules are disabled, its checks are retired and its uploaded file is deleted. The delete raises `policy_deleted`.
  - A server-folder policy gets 409 `policy_managed_on_server`; remove its file from the folder instead.
  - An unknown id gets 404, and an already deleted policy 409 `conflict`.
  - Uploading a file with the same `<PolicyName>` later brings the policy back, with the same id and a new version.
- **Import history (admin, session or API token).** `GET /api/v1/imports` lists every import, newest first. Each item is `{import_id, file_name, file_sha256, policy_version, mode, outcome, plugins_added, plugins_updated, plugins_retired, errors, imported_by, imported_at}`.
  - `mode` is `auto`, `manual` or `rebuild`.
  - `outcome` is `success`, `skipped` or `rejected`.
  - `errors` holds the findings.

### Rebuild

A rebuild re-imports every file in both folders, without skipping any, and deletes the policies whose files are gone.

- Each file is checked on its own. A rejected file keeps its existing catalog rows and is reported, and the rebuild commits as a whole.
- Ids and history are kept. A rebuild is the way to recover a damaged catalog, and it never touches hosts, inventory, scans or the audit log.
- It raises one `policy_rebuilt` alert, plus `policy_import_rejected` for each rejected file and `policy_imported` for each policy whose catalog rows it changed.

**In the web UI (admin, TOTP-verified session).** On **Rebuild catalog**, press **Rebuild** and confirm. The page follows the task until it succeeds or fails, then lists the files, the files not imported, the deleted policies and the removed leftovers.

**Through the API (admin, TOTP-verified session).** `POST /api/v1/policies/rebuild` answers 202 with `{"task_id"}`, and the rebuild runs in the background. Follow it with `GET /api/v1/tasks/{task_id}` (admin, session or API token), which returns `{task_id, kind, state, requested_by, result, started_at, finished_at}`.

- `state` is `running`, `succeeded` (even with rejected files) or `failed`.
- A succeeded `result` is `{files, deleted_policy_ids, plugins_retired, removed_leftovers, not_imported}`, and each file is `{source_file, import_id, outcome, policy_id, policy_version}`.
- A failed `result` is `{error}`. A failed rebuild leaves the catalog unchanged.
- A rebuild still running when the manager stops ends `failed` at the next start-up; start it again.

**On the server.** `sudo bitscan-manager bits rebuild` runs the same rebuild in the foreground, as `cli:root`.

- It reads the DSN from `/etc/bitscan/secrets/app.dsn`, checked like the `users` commands.
- It takes the folder from `BITSCAN_BITS_DIR` in its environment, else from `/etc/bitscan/manager.env`, else the default. The folder and its `uploaded/` must exist.
- If another import holds the catalog, it waits for it to finish.
- It prints one line per file (`success <file> policy <id> version <n>`, or `rejected <file> (<n> findings)`), then `not imported`, `removed leftover` and `deleted policy <id>` lines, and a summary. Read the findings with `GET /api/v1/imports`.
- Exit codes: 0 when the rebuild committed, rejected files included; 1 when it failed or didn't run; 2 for a usage, folder or DSN-file error.

**At start-up.** Before anything else, the manager finishes interrupted uploads and imports what changed, then compares the catalog with the files.

- Any difference raises one `catalog_integrity_failed` alert that lists them; a rebuild repairs the catalog.
- If a policy was deleted just before a crash, its uploaded file is removed and listed in that alert, and the policy stays deleted. To bring it back, upload it again.
- Until start-up has finished, upload, delete and rebuild answer 503 with `Retry-After: 10`.

## Scans

A scan runs one compliance profile on a set of hosts. The manager builds one job per host from the profile's active checks, and each agent picks its job up at its next job pull (within `job_pull_seconds` plus 30 seconds). Nothing is pushed to an agent, and there is no route that runs any other command.

**Starting a scan (operator, session or API token).** `POST /api/v1/scans` with `{"policy_id", "target"}`:

```sh
curl -s https://manager.example:8443/api/v1/scans \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: nightly-web-2026-10-30' \
  -d '{"policy_id": 3, "target": {"tags": ["prod-web"]}}'
```

- **`target`** is exactly one of:
  - `{"agents": [...]}`: 1–10,000 distinct agent ids, in the hyphenated form;
  - `{"tags": [...]}`: 1–32 distinct tags (each 1–64 characters from `A–Z a–z 0–9 . _ : -`); a host with **any** of them is included;
  - `{"all": true}`: every host.
- The target is resolved when the scan is queued, to hosts that are not decommissioned or awaiting approval. Offline hosts still get a job; it runs if the host comes back within 24 hours. Unknown agent ids are left out. The scan records the request, the resolved host list and the profile `version` its jobs were built from.
- **The answer** is 202 `{scan_id, state: "queued", policy_version, jobs}`; `jobs` is the number of hosts.
- **Refusals** (nothing is written): a malformed target or any other body key gets 400 (`Invalid request: target…`); an unknown profile 404; a disabled or deleted profile, or one with no active check, 409 `conflict`; a target with no eligible host 422; a body over 1 MiB 413.
- **One job per host and profile.** A new scan cancels the still-queued jobs of earlier scans of the same profile on the same hosts. Jobs already handed out keep running, and inventory jobs are never touched.
- **Commands are fixed when queued.** A job keeps the commands it was built with, even if the profile is imported again; scans queued afterwards use the new version. Disabling a profile blocks new scans; its queued and running jobs still run.
- **`Idempotency-Key`** (optional, 1–255 printable ASCII characters, else 400): repeating the request with the same key and the same body returns the first 202 answer and starts no second scan. The same key with a different body gets 409. Keys are kept per user, in memory, for 24 hours, and are forgotten when the manager restarts. Only a 202 is remembered, so a refused request can be retried with the same key. A repeat sent while the first is still running waits for its answer.
- **Alert:** an all-hosts scan (`{"all": true}`) started with an API token writes an `all_hosts_scan_api_token` alert. Every scan writes one `scan.create` audit entry.

**Cancelling (operator).** `POST /api/v1/scans/{scan_id}/cancel`, no body, answers 200 `{scan_id, state, cancelled_jobs}`. The scan's queued, handed-out and running jobs become `cancelled`; hosts are not contacted. A host still running its job may finish it, but its results are refused (409) and not stored. Cancelling again answers `cancelled_jobs: 0`. An unknown scan gets 404, and an id not in the hyphenated form 400. Each cancel writes one `scan.cancel` audit entry.

**How a scan proceeds.**

- A job is `queued`, then `dispatched` when its host pulls it, then `running` when the host starts it. It ends `completed` (a result for every check), `partial` (some missing) or `failed` (none). A job not picked up within 24 hours `expires`. A handed-out job that never starts fails 24 hours after it was handed out.
- A started job has a deadline: start + the sum of its checks' timeouts divided by `max_parallel_plugins` (rounded up) + 10 minutes. A job past its deadline ends `partial` or `failed` (or `completed` if every check already has a result); a `partial` or `failed` one gets **one** retry holding only the checks with no result, with the same commands. A retry is never retried, and none is made for a deleted profile or a decommissioned host.
- Results are accepted for 7 days after a job was handed out, so a host that was offline can still deliver them; they can still turn a `failed` or `partial` job into `partial` or `completed`. For each host and check, the first result to arrive is kept, from the job or from its retry.
- The scan's own state is `queued`, `running`, `completed`, `partial` (some results, not all), `failed` (no results) or `cancelled` (cancelled before any result). It is finished once no job is queued, handed out or running. It is updated by `offline_sweep`, so it can lag up to a minute behind its jobs.

### Scan results

Every read below needs a viewer, with a session or an API token, and writes nothing. Results and scores are worked out when they are read, so a late result or a re-evaluation shows at the next read.

**Listing scans.** `GET /api/v1/scans` lists scans newest first.

- Filters combine with AND: `policy_id`; `agent_id` (in the hyphenated form; a scan whose target included that host); `state` (`queued`, `running`, `completed`, `partial`, `failed` or `cancelled`); `created_after` (inclusive) and `created_before` (exclusive), each an RFC 3339 time with an offset, for example `2026-11-01T00:00:00Z`.
- Items are `{scan_id, policy_id, policy_name, policy_version, trigger, schedule_id, requested_by, state, target_kind, resolved_count, created_at, finished_at}`. `target_kind` is `agents`, `tags` or `all`, and `resolved_count` is the number of hosts the target resolved to.
- A cursor works only with the same filters. Once the scan it points at has been deleted by [retention](#retention), it gets 400 `Invalid request: query.cursor`.
- `GET /api/v1/agents/{agent_id}/scans` lists, in the same form, the scans whose target included the host, decommissioned hosts too. An unknown host gets 404.

**One scan.** `GET /api/v1/scans/{scan_id}` returns the item above, plus `target` as it was requested and `hosts`. `hosts` has one entry per host with a job in the scan, ordered by hostname: `{agent_id, hostname, jobs, passed, failed, errors, not_run, score}`.

- `jobs` lists the host's job and then its retry, each with `{job_id, state, retry_of, dispatched_at, started_at, finished_at}`. A retry's results count together with its job's.
- The counts use each check's current verdict (see re-evaluation below). `not_run` counts the checks with no result.
- **Score:** `score` is passed ÷ (passed + failed), from 0 to 1. ERROR and not-run checks are left out, and the error count is given beside it. With no PASS or FAIL result, `score` is `null`, which the web UI shows as "n/a".
- A scan of a profile that was deleted later is still returned. An unknown scan gets 404, and an id not in the hyphenated form 400.

**Results.** `GET /api/v1/scans/{scan_id}/results` returns one item per check of each host's job, ordered by host (`agent_id`) and then by the check's place in the profile.

- Items are `{agent_id, hostname, job_id, retry, plugin_uuid, plugin_name, result, eval_detail, original_result, original_eval_detail, reeval_policy_version, reevaluated_by, reevaluated_at, operator, expected, execute, exit_code, timed_out, truncated, started_at, finished_at, received_at}`.
  - `retry` is `true` when the result came to the retry.
  - `operator`, `expected`, `execute` and `plugin_name` are those the job was built with.
  - `result` is the current verdict: that of the latest re-evaluation, if any, else the stored one. `original_result` is the verdict stored when the result arrived. Each comes with its detail.
- **Not run:** a check with no result has `result: null` and null result fields.
- **Filters:** `status` (`PASS`, `FAIL` or `ERROR` on the current verdict, or `NOT_RUN`) and `agent_id` (hyphenated). Anything else gets 400.
- **Output:** `stdout` and `stderr` are in the items only for operators and admins, with a session or an API token alike. The caller's role is read at each request. A viewer's items have no `stdout` or `stderr` key at all.
- `limit` and `cursor` page as on every list. A cursor works only with the same `status` and `agent_id`.

**CSV export.** `GET /api/v1/scans/{scan_id}/results.csv` takes the same `status` and `agent_id`, and returns the whole set as one file.

- The answer is `text/csv; charset=utf-8` (UTF-8 without BOM, CRLF line ends), with `Content-Disposition: attachment; filename="scan-<scan_id>-results.csv"`.
- **Columns:** `hostname, agent_id, plugin_uuid, plugin_name, result, eval_detail, original_result, original_eval_detail, reevaluated_at, reeval_policy_version, exit_code, timed_out, truncated, started_at, finished_at, job_id, retry`. Operators and admins also get `stdout` and `stderr`; for a viewer those columns are not in the file.
- **Cells:** an empty cell for null, `true` or `false`, and UTC times ending in `Z`. A not-run check has an empty `result`.
- At most 100,000 rows. A larger set gets 400 `Invalid request: more than 100000 rows; narrow the filters`, before any CSV is sent.
- **Memory (a known limit of this version):** the manager builds the whole file in memory before sending it. An operator or admin export includes `stdout` (up to 64 KiB per check) and `stderr` (up to 16 KiB). At the 100,000-row cap, with maximal output, it can need several GB of manager memory, about 8 GB in the worst case. For big scans, narrow the filters, or export one host or one status at a time. A viewer's export carries no output and stays small.
- Formula escaping and quoting are those of the [package CSV](#package-search): a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return, or with whitespace followed by one of these, gets a leading `'`. This applies in every column, check output included.

**Re-evaluation (admin, TOTP-verified session).** `POST /api/v1/scans/{scan_id}/reevaluate`, with no body, re-checks the scan's stored results against the `Operator` and `ExpectedResult` of the profile's current version.

- It is refused for API tokens, and once the audit sink has been down for 15 minutes.
- It adds a new verdict for each result and never changes the stored ones.
- Some results are not re-checked:
  - A check that the current version no longer lists keeps its verdict.
  - A result the manager stored as ERROR on arrival (`oversize`, `spool_overflow` or `runner_unavailable`) stays ERROR.
- It runs during the request, so re-evaluating a very large scan holds the request until it ends.
- The answer is 200 `{scan_id, policy_id, scan_policy_version, policy_version, rows_added, not_in_version}`. `scan_policy_version` is the version the scan was built from, `policy_version` the version used now, and `not_in_version` the number of results whose check that version no longer lists.
- An unknown scan gets 404, and a scan of a deleted profile 409 `conflict`.
- Each re-evaluation writes one `scan.reevaluate` audit entry and raises no alert. Calling it again adds another set of verdicts; the latest one counts.

```sh
curl -s -X POST 'https://manager.example:8443/api/v1/scans/<scan_id>/reevaluate' \
  -H 'Authorization: Bearer <TOTP-verified session token>'
```

### Schedules

A schedule queues a scan of one profile on a cron timetable. Every `/api/v1/scan-schedules` route needs an operator (session or API token), reading included, and any operator may change any schedule.

```sh
curl -s https://manager.example:8443/api/v1/scan-schedules \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
  -d '{"name": "Nightly web", "policy_id": 3, "target": {"tags": ["prod-web"]}, "cron": "30 2 * * *", "timezone": "Europe/London"}'
```

- **Create:** `POST /scan-schedules` with `{name, policy_id, target, cron, timezone?, enabled?}` answers 201 with the schedule. `timezone` defaults to `UTC` and `enabled` to `true`. `name` is 1–128 characters; `target` takes the same forms as a scan and is resolved again at each run.
- **Read and list:** `GET /scan-schedules` (ordered by `schedule_id`, with `limit` and `cursor`) and `GET /scan-schedules/{schedule_id}`. Items are `{schedule_id, name, policy_id, target, cron, timezone, enabled, last_run_at, next_run_at, created_by}`.
- **Change:** `PATCH /scan-schedules/{schedule_id}` with any non-empty subset of `name`, `target`, `cron`, `timezone` and `enabled`. `policy_id` cannot change; create a new schedule instead. `{"enabled": false}` stops the runs.
- **Delete:** `DELETE /scan-schedules/{schedule_id}` answers 204. The scans it started are kept.
- **Profiles:** a schedule of a deleted profile can be neither created nor enabled (409). A schedule of a disabled profile is accepted, but its runs are skipped. Deleting a profile disables its schedules.
- **`cron`** is the five-field crontab format (minute, hour, day of month, month, day of week), at most 64 characters, with `*`, lists, ranges, steps, and month and weekday names. Weekday `0` and `7` are Sunday. A cron that restricts both the day of month and the day of week, uses `@` macros or a seconds field, or never fires (`0 0 30 2 *`) gets 400.
- **`timezone`** is an IANA zone name such as `Europe/London` or `Asia/Kolkata`, at most 64 characters; the cron is read in that zone. Across a daylight-saving change, a run whose local time is skipped in spring runs just after the jump, and a run in the hour repeated in autumn runs once, at its first occurrence; so a schedule that fires more often than hourly makes no runs during the repeated hour.
- `next_run_at` is the next fire time after now. It is set on create, when `cron` or `timezone` changes and when the schedule is enabled. `last_run_at` is when the schedule last queued a scan.
- Each create, change and delete writes one `scan_schedule.*` audit entry. A run queues its scan as `system`, with one `scan.create` entry; it never raises the API-token alert.

**When runs happen.** The scheduler checks for due schedules every 30 seconds.

- **No back-fill:** a run more than 2 minutes late (for example while the manager was down) is not made up; the schedule waits for its next time.
- **Skips:** a run is skipped when the previous scan from the schedule has not finished, when the profile is disabled, or when the target resolves to no host. A skipped run queues nothing and writes no audit entry; the manager logs `scheduled run skipped` with the schedule id and the reason (`missed`, `previous_unfinished`, `policy_disabled`, `no_target_agents`, `policy_has_no_plugins`, or `invalid` for a stored schedule that no longer validates, which is tried again a day later).
- Because a scan's finished state can lag a minute behind its jobs, a schedule that fires every minute may skip runs.

## Users

The `users` commands run on the server as root (`sudo bitscan-manager users …`). They read the `bitscan_app` DSN from `/etc/bitscan/secrets/app.dsn`, with the same checks as the server's DSN (readable, at most 64 KiB, and `sslmode` set to `require`, `verify-ca` or `verify-full`). They contact only PostgreSQL. Each writes an audit entry with actor `cli:root`; a running `serve` sends it to the audit sink.

- **`users create-admin <name>`** creates an admin with no TOTP. On a terminal it asks for the password twice without echo; otherwise it reads one line from standard input. The password is never taken from the command line or the environment. It must be 12 to 1,024 characters. Usernames are 1–64 characters of `A–Z`, `a–z`, `0–9`, `.`, `_`, `@` and `-`, and are case-sensitive. The admin's first sign-in gives a session that can only enrol TOTP or sign out. Alert: `admin_created`.
- **`users create-api-token <user> [--name NAME] [--days DAYS]`** prints a new `bsk_` API token on standard output, once; only its SHA-256 is stored. `--days` is 1–365 (default 90) and `--name` at most 64 characters. The user must exist and be enabled. Alert: `api_token_created`.
- **`users reset-totp <user>`** clears the user's TOTP and ends their sessions; their next sign-in works with the password only (an admin then gets the enrolment-only session). Alert: `totp_reset`.

Exit codes: 0 success; 1 refused (an existing or unknown user, a password or option that breaks a rule, a database error); 2 usage or DSN-file error. Messages name the rule or the DSN file path, never a password, token or DSN.

## Enrolling agents

Agents enrol with a `bse_` enrolment token that an admin creates on the **Enrolment tokens** page of the [web UI](#web-ui), or through the API. There is no command for it. To script it, sign in as an admin with TOTP, then call `/enrollment-tokens` with that TOTP-verified session (API tokens are refused). If the manager's certificate comes from a private CA, add `--cacert <ca.pem>` to each `curl` command.

```sh
# 1. Sign in (admin with TOTP); keep the session token from the answer.
curl -s https://manager.example:8443/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "alice", "password": "<password>", "totp_code": "<code>"}'

# 2. Create an enrolment token (every field is optional).
curl -s https://manager.example:8443/api/v1/enrollment-tokens \
  -H 'Authorization: Bearer <session token>' -H 'Content-Type: application/json' \
  -d '{"max_uses": 25, "expires_in_hours": 48, "allowed_cidrs": ["10.20.0.0/16"], "auto_approve": false}'
```

- **Fields:**
  - `max_uses`: 1–10,000; the default is 1, one host.
  - `expires_in_hours`: 1–720; the default is 24.
  - `allowed_cidrs`: a list of 1–64 network addresses (`10.20.0.0/16`, `2001:db8::/32`), or `null`, the default, for any source address.
  - `auto_approve`: the default is `false`.
- **The answer (201)** holds `token` this once, with `token_id`, `max_uses`, `uses`, `auto_approve`, `allowed_cidrs`, `expires_at` and `created_at`. Only its SHA-256 is stored.
- **Shared tokens:** a token used by many hosts, for example in an install script, should have `max_uses` set to the expected host count and `allowed_cidrs` set.
- **Alerts:** creating a token with `auto_approve` or more than 100 uses writes an `enrolment_token_risky` alert. More than `enrolment_alert_per_hour` enrolments on one token within an hour writes an `enrolments_per_hour` alert.
- **Managing tokens:** `GET /enrollment-tokens` and `GET /enrollment-tokens/{token_id}` list and read tokens, never the token itself. `DELETE /enrollment-tokens/{token_id}` revokes one (204; the record is kept).

**Approving enrolments.** Without `auto_approve`, a new host waits as `awaiting_approval`, and every agent call it makes gets 403 `pending_approval`. A host whose machine-id is already known, such as a reinstall or a cloned image, is always held, even with an `auto_approve` token. Decide them on the **Enrolment requests** page, or list them with `GET /enrollment-requests` and decide each one with an admin TOTP-verified session:

- **`POST /enrollment-requests/{request_id}/approve`:**
  - A new host becomes `enrolled`.
  - A re-enrolment moves the existing host record, with its history, tags and packages, to the new token. That ends the old token and writes a `reenrolment_approved` alert. A call with the old token then gets 401 `unauthorized`.
  - A request whose token has expired cannot be approved (409); the host must enrol again.
- **`POST /enrollment-requests/{request_id}/reject`:**
  - A new host is set to `decommissioned` (never deleted), and its agent gets 401 `enrollment_rejected`.
  - A rejected re-enrolment leaves the existing host and its old token as they were. That machine has already replaced its token, so it must enrol again with a new enrolment token.
- Deciding a request twice gets 409. Each decision is audit-logged. An approved host gets its first inventory job straight away.
- An operator who calls approve or reject gets 403 `totp_session_required` with an API token or a session not verified with TOTP, and 403 `forbidden` with a TOTP-verified session.

## Agent API

The agent routes are under `/api/v1/agent/` and accept only agent tokens: `bse_` on enrolment, and `bsa_` on the other five. User tokens are refused there, and agent tokens are refused on every user route. Agents always open the connection; the manager never connects to an agent and has no route that runs a command.

| Route | Purpose |
| --- | --- |
| `POST /agent/enroll` | Exchange a `bse_` token for `agent_id` and an agent token (`bsa_`), with `issued_at`, `expires_at` and `status` (`enrolled` or `awaiting_approval`) |
| `POST /agent/{id}/heartbeat` | Report status; the answer is only `job_pull_seconds`, `max_parallel_plugins` and `server_time` |
| `GET /agent/{id}/jobs` | Pull up to 10 queued jobs, each handed out once |
| `POST /agent/{id}/jobs/{job_id}/results` | Return results of a compliance job, at most 50 per batch; answers `{accepted, duplicates}` |
| `PUT /agent/{id}/inventory[?job_id=...]` | Upload `os_info` and the package list, gzip-compressed; answers 204 |
| `POST /agent/{id}/token/rotate` | Get a new agent token inside the rotation window |

- **Authentication on every `bsa_` call:**
  - The call carries the agent's machine-id in `X-Bitscan-Machine-Id`. A missing or different machine-id revokes the token (401 `machine_id_mismatch`) and alerts. For the new token of a re-enrolment that is still awaiting approval, a wrong machine-id gets the same 401 and alert, but nothing is revoked and the request stays pending.
  - `{id}` must be the token's own agent; any other gets 403. Path and query ids (`{id}`, `{job_id}`, `?job_id`) accept only the hyphenated form (`8-4-4-4-12` hex digits, either case); other forms get 400 `invalid_request`.
  - Unknown or malformed tokens get 401 `unauthorized`. Revoked, expired or rejected ones get `token_revoked`, `token_expired` or `enrollment_rejected`.
- **Limits:**
  - 30 requests a minute per agent.
  - 10 enrolment attempts a minute per source address. Every attempt counts, malformed ones included.
  - Failed token checks count toward the per-address limit that the user routes also use.
  - Over a limit, the answer is 429 `rate_limited` with `Retry-After`.
- **Bodies:**
  - The default limit is 1 MiB.
  - An inventory upload is at most 10 MiB as sent and 64 MiB decompressed, with at most 50,000 packages, `os_info.raw` at most 256 KiB, and every field within its column's length.
  - Keep `os_info.raw` a flat set of keys and values: the decoder refuses data nested more than 32 levels deep.
  - A result batch is at most 1.5 MiB after decompression.
  - Over a byte limit the answer is 413. A package or field limit, a duplicate package, or a `list_sha256` that does not match the list gives 422.
  - These limits are checked after the token, so a refused upload is audit-logged, and an upload that names a dispatched inventory job fails that job (413 or 422).
  - An inventory upload without `Content-Encoding: gzip` (any letter case), or one that is not valid gzip, UTF-8 or JSON, gets 400 `invalid_request`. So does a string holding U+0000 or a lone surrogate, or data nested more than 32 levels deep. A 400 is audit-logged too, but leaves a named job to the 30-minute sweep.
- **Inventory jobs:**
  - An upload with the `job_id` of this agent's dispatched inventory job completes it.
  - An upload with the `job_id` of an inventory job that already failed or completed is stored as an unscheduled upload, and the job is unchanged.
  - Any other `job_id` gets 409 `job_not_acceptable` and nothing is stored: unknown, another agent's, a compliance job, or one that is queued, running, expired or cancelled.
  - Unscheduled uploads (no `job_id`, or a failed or completed one) are accepted at most once per agent every 10 minutes (429 otherwise).
- **Compliance jobs and results:**
  - A pull returns inventory and compliance jobs together, oldest first. A compliance job carries `plugins` (`plugin_uuid`, `execute`, `timeout_s`) and `redaction_patterns`; the expected values never leave the manager.
  - An empty batch is the start notice: it moves the job to `running` and starts its deadline. Later start notices change nothing.
  - A batch is accepted for this agent's own compliance job that was handed out, running, `failed`, `partial` or `completed`, until 7 days after it was handed out. `accepted` counts the stored results; `duplicates` counts results the job or its retry already had, or that came earlier in the same batch.
  - Every other batch gets 409 `job_not_acceptable` and nothing of it is stored: an unknown job, another agent's, an inventory job, one that is queued, expired or cancelled, one past the 7 days, and a batch naming any check that is not in the job. Each 409 is audit-logged. More than 20 within 10 minutes write a `result_409_flood` alert; 409s for the agent's own cancelled job do not count toward it.
  - A result whose `stdout` is over 65,536 UTF-8 bytes, or whose `stderr` is over 16,384, is stored as `ERROR` (`oversize`) with both texts empty. U+0000 and lone surrogates in `stdout` and `stderr` are stored, and compared, as U+FFFD.
- **Heartbeat:**
  - A clock more than 5 minutes away from the manager's writes a `clock_skew` alert, at most once an hour per host.
  - A change in `runner_helpers` writes a `runner_helper_changed` alert.
  - A heartbeat makes an `enrolled`, `stale` or `offline` host `online` at once.
- **Token rotation:**
  - An agent token lives `agent_token_ttl_days` (default 365). It can be rotated from `issued_at + max(lifetime − 30 days, lifetime ÷ 2)` until it expires.
  - Rotating earlier gets 403 and a `rotation_outside_window` alert. A second rotation within 24 hours of a used one gets 429.
  - The old token keeps working until 10 minutes after the new token is first used. Using it after that revokes both tokens and alerts (`token_reuse`). A rotation with the old token after the new one has been used, even within those 10 minutes, counts as reuse: both tokens are revoked and an alert is raised.
  - If the answer to a rotation is lost, rotating again with the old token returns a fresh new token. While the new token has not been used, the old one is accepted for at most 30 days after the rotation.
  - A rotation from an address the agent has not used in the last 7 days writes a `rotation_new_ip` alert.
  - After `expires_at` every call, rotation included, gets 401 `token_expired`, and the host must enrol again.

## Scheduler

`serve` runs four scheduled jobs in its own process. None ever runs twice at once.

- **Inventory** (mandatory):
  - At start-up, and then every `inventory_interval_s` (default 6 hours, range 1–24 hours), it queues one inventory job for each host that is not decommissioned or awaiting approval and has no open inventory job.
  - A job must be picked up within 24 hours.
  - Inventory cannot be turned off: there is no setting, role or route for it.
  - An interval change takes effect within a minute.
- **`offline_sweep`** (every 60 seconds):
  - It sets each host `online` (a heartbeat in the last 10 minutes), `stale` (10–30 minutes) or `offline` (over 30 minutes). A host that has never sent a heartbeat ages from its enrolment or approval.
  - An offline host with no heartbeat for more than `decommission_after_days` is `decommissioned` and its token revoked; 0 means never.
  - Queued jobs past their pick-up time expire. An inventory job not uploaded within 30 minutes of being handed out fails. Inventory jobs are never retried.
  - Compliance jobs past their deadline end `partial`, `failed` or `completed`, and those handed out more than 24 hours ago that never started fail; each such job gets its single retry (see [Scans](#scans)).
  - It updates the state of every scan that can still change.
  - It raises the fleet alerts: more than 5 % of hosts offline; a job of an online host queued for over an hour; a heartbeating host whose inventory is older than twice the interval; and rows in the default `scan_result` partition.
- **Scan schedules** (every 30 seconds): runs each due [schedule](#schedules) once.
- **Retention** (10 minutes after start-up, then daily): deletes data past its retention period; see [Retention](#retention).

A failed run is logged by its kind of error, and the next run happens as usual. On `SIGTERM` the scheduler stops first; a run waiting on an unavailable database gives up within seconds, and a retention run stops at its next batch.

### Retention

The retention job deletes old data so the database does not grow without limit. It connects only as `bitscan_retention`, with the DSN in `BITSCAN_RETENTION_DSN_FILE`; that role can delete from the retention tables only. Its interval is the `retention` row of `system_schedule` (daily, as the first migration seeds it), read at start-up.

| Data | Deleted when |
| --- | --- |
| A scan, with its jobs, results and re-evaluations, all together | the scan was created more than 400 days ago |
| An inventory job | it finished more than 30 days ago |
| An inventory snapshot (the record of packages added and removed) | it was collected more than 180 days ago |
| An enrolment request | it was decided (approved or rejected) more than 90 days ago; pending requests stay |
| A user token (session or API token) | it expired more than 90 days ago, whether or not it was revoked |
| An audit log entry | it is more than 3 calendar years old (see below) |
| A package version | no host lists it any more |

- **Never deleted:** hosts, their `os_info` and current package lists, enrolment tokens, profiles and checks, schedules and settings.
- **Partitions:** `db maintain` still drops whole `scan_result` partitions past 400 days. Retention runs no DDL.
- **Audit log:** only the oldest entries go, in id order, and only those already queued for the audit sink. Each batch of at most 10,000 entries is deleted in one transaction. That transaction first appends an `audit.checkpoint` entry, with actor `system` and detail `{last_deleted_id, last_deleted_row_hash, deleted}`, so the hash chain still verifies from there. The checkpoint is sent to the sink like every entry.
- **Batches:** each batch is its own transaction: 2 scans, 1,000 inventory jobs or 10,000 rows. A batch that fails is rolled back alone, and the next run finishes the work.
- **Safety checks:**
  - If the manager's clock and the database's differ by more than 5 minutes, the run deletes nothing and logs `retention refused: clock_doubt`.
  - If a table holds rows dated more than a day in the future, that step is skipped and the other steps run.
  - A scan that is being re-evaluated is left for the next run.
- **Logs:**
  - Each step logs one `retention step done` line with the step name (`scans`, `inventory_jobs`, `snapshots`, `requests`, `tokens`, `audit` or `packages`), the rows deleted, the batches and any reason it was skipped.
  - A step that fails logs `retention step failed` with its name and error type, and the later steps still run.
  - No deleted row's content is ever logged.
- A list cursor that points at a deleted scan gets 400; start the list again.

## Nightly end-to-end run

The workflow `.github/workflows/e2e.yml` runs every night at 01:40 UTC and can also be started by hand. A push runs it only when its head commit message contains `[e2e]`. It builds the agent `.deb` and the manager wheel from the commit, then runs the whole chain on three machines:

- the manager host, installed by [`manager-install.md`](deploy/runbooks/manager-install.md), with test stand-ins for OpenBao and the audit sink;
- two QEMU/KVM guests from the official Ubuntu 22.04 and 24.04 cloud images, each installing the agent by [`agent-install.md`](deploy/runbooks/agent-install.md).

**The chain:** enrol, then approve the enrolment (admin TOTP session), heartbeat and inventory. Then it imports the example policy of [`bit_Schema_Reference.md`](docs/spec/bit_Schema_Reference.md) section 1.1, scans both hosts and reads the results.

**Pass condition:** both hosts PASS with exit code 0, score 1.0 and no errors, and a viewer's results hold no output.

**Compatibility:** two more runs, in parallel, each on its own runner with its own guest and manager host:

- `compat-a`: this manager with the 0.1.0 agent, whose checks all come back as ERROR `runner_unavailable`;
- `compat-b`: this agent with the 0.1.0 manager.

**Report and result:**
- Each step is one row per host, PASS, FAIL or NOT RUN with its reason.
- Each run uploads its report as an artifact, `e2e-report-nightly`, `e2e-report-compat-a` or `e2e-report-compat-b`, holding `report.json` and `report.md`. The tables are also shown on the run's summary page.
- The workflow fails when any row is FAIL or an expected row is missing.
- Tokens and passwords are kept out of the report and logs.
- To run the chain on your own Linux machine (root, Docker, QEMU and `/dev/kvm`), follow [`e2e/m11/README.md`](e2e/m11/README.md).
