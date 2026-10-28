# TASK-133 (and TASK-134): manager install layout and runbook outline

REQs: REQ-138, REQ-139, REQ-140. Answers used: #6 (M6 re-check, install half), #46 (M6 re-check), #90, #93, #96. This plan is the contract for TASK-133 (`deploy/runbooks/manager-install.md`), TASK-134 (`deploy/runbooks/manager-operations.md`) and TASK-137 (README links). The units themselves are never edited: they are `deploy/systemd/bitscan-manager*.{service,timer}`, verbatim TS §8.7.

## 1. Spec quotes that fix the layout

- TS §8.7 L1343: "the manager runs as the system user `bitscan-manager` under `bitscan-manager.service` … one instance in v1, listening on `BITSCAN_LISTEN` over HTTPS only. A `SIGHUP` reloads the TLS certificate."
- L1344: "`/var/lib/bitscan/bits/` (`root:bitscan-manager`, 0750), `/var/lib/bitscan/bits/uploaded/` (`bitscan-manager`, 0750), `/var/lib/bitscan/audit-queue/` (`bitscan-manager`, 0700)."
- L1345: "non-secret settings live in `/etc/bitscan/manager.env` (`root:root`, 0600) … Secrets live in `/etc/bitscan/secrets/` (`root:root`, 0700) and are handed to each unit with `LoadCredential=` … The migrate and maintain units run as a separate dynamic user."
- L1346: "`bitscan-manager-migrate.service` runs `bitscan-manager db migrate` before a new version starts … the upgrade runbook starts it first."
- L1347: "commands such as `users create-admin` … are run as root (`sudo bitscan-manager …`) and read their DSN from `/etc/bitscan/secrets/app.dsn`."
- L1348: "manager first (migrate, then restart), then agents. The manager supports agents of its own version and the one before."
- L1359: `ExecStart=/usr/bin/bitscan-manager serve`.
- TS §5.2 L1016: the Bootstrap is "run once by a database superuser with `psql`, before the first migration". TS §5.3 L1049: "PostgreSQL accepts connections only from the manager host, over TLS." L1048: backups.
- TS §8.2 L1264: Python dependencies installed with `pip --require-hashes`.

## 2. Layout (#6 install half, recommended answer)

| Path | Owner | Mode | Source of the rule |
| --- | --- | --- | --- |
| `/opt/bitscan-manager/` (Python 3.12 venv: `bin/`, `lib/`) | `root:root` | 0755 dirs, files as pip writes them, nothing group- or other-writable | #6 (spec silent; read-only under `ProtectSystem=strict`, outside `/home` for `ProtectHome=yes`) |
| `/usr/bin/bitscan-manager` → `/opt/bitscan-manager/bin/bitscan-manager` | `root:root` | symlink | TS §8.7 L1359 |
| `/etc/systemd/system/bitscan-manager.service`, `-migrate.service`, `-maintain.service`, `-maintain.timer` | `root:root` | 0644 | verbatim TS §8.7; locally installed units go in `/etc/systemd/system/` |
| `/etc/bitscan/` | `root:root` | 0755 | shared with the agent package on a host that runs both; the agent's `postinst` refuses an `/etc/bitscan` that is not root-owned or is group- or other-writable (TASK-100 r1) |
| `/etc/bitscan/manager.env` | `root:root` | 0600 | L1345 |
| `/etc/bitscan/secrets/` | `root:root` | 0700 | L1345 |
| `/etc/bitscan/secrets/{app.dsn,retention.dsn,migrate.dsn,tls.crt,tls.key,vault.token}` | `root:root` | 0600 | L1345, L1362–L1366, L1415 |
| `/var/lib/bitscan/` | `root:root` | 0755 | parent only; the spec gives no mode, so the most restrictive common default that lets the service reach its sub-folders |
| `/var/lib/bitscan/bits/` | `root:bitscan-manager` | 0750 | L1344 |
| `/var/lib/bitscan/bits/uploaded/` | `bitscan-manager:bitscan-manager` | 0750 | L1344 |
| `/var/lib/bitscan/audit-queue/` | `bitscan-manager:bitscan-manager` | 0700 | L1344 |

The user: `adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin bitscan-manager`.

**Manager host OS (#6 re-check):** Ubuntu 24.04 amd64, which ships Python 3.12 (`python3.12`, `python3.12-venv`) and PostgreSQL 16 (`postgresql-16`, `postgresql-16-debversion`) in its archive. Ubuntu 22.04 has neither Python 3.12 nor PostgreSQL 16 in its archive, so it is not a manager host in v1 (the spec names no manager OS; agent hosts are unchanged).

`manager.env` holds only `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF`, `BITSCAN_AUDIT_SINK` and, if needed, `BITSCAN_LISTEN` and `BITSCAN_BITS_DIR` (TS §8.6). The `*_FILE` variables come from the units (`%d/…`) and never appear in it.

## 3. TASK-133 runbook outline (`deploy/runbooks/manager-install.md`)

1. **Before you start:** the prerequisites above; an OpenBao server with a Transit key and a token limited to `encrypt`/`decrypt` on it (README "OpenBao"); an audit sink (`https://` or `syslog+tls://`); a server certificate and key for the manager's name; NTP.
2. **Check the release files:** download the `.whl`, `bitscan-manager-<v>-requirements.txt` and the four unit files; copy `SHA256SUMS` from the release page (another origin, #91); `sha256sum -c --ignore-missing SHA256SUMS` must print `OK` for each.
3. **PostgreSQL:** install; TLS on (`ssl = on` with a certificate); `listen_addresses` limited to what the manager needs (`localhost` when on the same host); `pg_hba.conf`: a `hostnossl bitscan all all reject` line before any `host` line, and `hostssl bitscan bitscan_app,bitscan_retention,bitscan_migrate <manager address>/32 scram-sha-256`. Run the **Bootstrap block, a byte-identical copy of TS §5.2 L1018–L1032** (comment line included), with `sudo -u postgres psql -v ON_ERROR_STOP=1 -f <file>`. Set the three passwords with `\password <role>` at the `psql` prompt (#46): never in a command line or a file under version control.
4. **User and folders:** the `adduser` line; `install -d -o … -g … -m …` for every folder in §2.
5. **Configuration and secrets:** create each file empty with its mode first (`install -m 0600 /dev/null <file>`), then write its content with an editor (`sudoedit`) or from stdin; DSN form `host=<db host> port=5432 dbname=bitscan user=<role> password=<password> sslmode=verify-full` (`require` only when the database certificate cannot be verified); each DSN uses a TCP host, because a Unix-socket connection does not use TLS.
6. **Install the software:** `python3.12 -m venv /opt/bitscan-manager`; `/opt/bitscan-manager/bin/pip install --require-hashes --only-binary :all: -r bitscan-manager-<v>-requirements.txt`; `/opt/bitscan-manager/bin/pip install --no-deps --no-index ./bitscan_manager-<v>-py3-none-any.whl`; `ln -sfn /opt/bitscan-manager/bin/bitscan-manager /usr/bin/bitscan-manager`. Offline variant: `pip download --require-hashes --only-binary :all: -r … -d wheelhouse` on a build host, then `--no-index --find-links wheelhouse`.
7. **Units:** `install -m 0644 -o root -g root` the four unit files into `/etc/systemd/system/`; `systemctl daemon-reload`. They must not be edited (a local change breaks the verbatim rule and the upgrade path).
8. **Database schema:** `systemctl start bitscan-manager-migrate`; `journalctl -u bitscan-manager-migrate` shows the head revision. `systemctl enable --now bitscan-manager-maintain.timer`.
9. **Start:** `systemctl enable --now bitscan-manager`; `curl --cacert <CA> https://<name>:8443/readyz` returns `{"status": "ok"}`.
10. **First admin:** `sudo bitscan-manager users create-admin <name>` (password typed twice at the prompt); sign in to the UI; enrol TOTP; then create enrolment tokens for agents (agent runbook).
11. **Check the install:** the REQ-140 list in operator words (unit status, `/readyz`, folder modes, no secret in `manager.env`).

## 4. TASK-134 runbook outline (`deploy/runbooks/manager-operations.md`)

1. **Upgrade** (L1346, L1348): check the new files (`SHA256SUMS`); install the new requirements and wheel into the venv (`--require-hashes`, then `--no-deps --force-reinstall`); if a release changes a unit file, install it and `daemon-reload`; `systemctl start bitscan-manager-migrate`; `systemctl restart bitscan-manager`; `/readyz`; then upgrade the agents (agent runbook, "Upgrade"). Never upgrade agents before the manager.
2. **Compatibility** (L1267, L1348; #90): a manager supports agents of its own version and the one before; pre-release agent builds (`0.1.0~preN`) are not supported; 0.1.0 is the first supported release.
3. **Certificate replacement** (L1343; #96): write the new `tls.crt` and `tls.key` into `/etc/bitscan/secrets/` (mode 0600 first), then the step #96's fact check gives: `systemctl reload bitscan-manager` if systemd refreshes the unit's credentials on reload, otherwise `systemctl restart bitscan-manager` (agents ride out the short gap with their back-off).
4. **OpenBao token replacement:** replace `vault.token`, then restart (README: the manager does not renew tokens).
5. **Backups** (TS §5.3 L1048): nightly `pg_dump -Fc` plus WAL archiving, encrypted at rest (they hold scan output and token hashes); keep `/etc/bitscan/secrets/` backed up separately and encrypted; a monthly restore test into a scratch database, which `bitscan-manager db migrate` (with a migrate DSN for the scratch database) reports at head; catalog corruption is fixed by rebuild (TS §4.2), not by restore.
6. **Removal:** stop and disable the units, remove them and `daemon-reload`; remove the venv and the link; the database and `/etc/bitscan/secrets/` are kept or destroyed by an explicit decision; on a host that also runs the agent, `/etc/bitscan/` itself stays (#82).

## 5. What the tester checks (TP-M6-03, TP-M6-04)

REQ-138 (1)–(6), REQ-139 (1)–(4) and REQ-140 (1)–(7). The Bootstrap check extracts the fenced block from the runbook and from TS §5.2 and compares bytes. The write sweep and the credential-isolation check are scripted in `deploy/tests/check_manager_host.sh`.

## 6. Edge cases for the implementer

- `ReadWritePaths=` folders must exist before the first start, or the unit fails to set up its namespace: create them in step 4, before step 8.
- `serve` creates the audit queue folder only if missing and refuses one that group or others can access (README "Before the first start"): the runbook's mode 0700 matches.
- The CLI as root reads `/etc/bitscan/secrets/app.dsn` directly; that DSN's host must be reachable from the host shell too.
- Do not tell the operator to put `PGPASSWORD`, a DSN or a token on a command line, in `manager.env` or in shell history.
