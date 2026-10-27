# Install the Bitscan manager

This runbook installs one manager on a fresh host: PostgreSQL, the `bitscan-manager` user and folders, configuration and secrets, the Python package, the four systemd units, the database schema and the first admin. Run every command as an administrator with `sudo`. Upgrades, certificate replacement, backups and removal are in `manager-operations.md`; agents are installed with `agent-install.md`.

**Never put a password, token or DSN on a command line or in an environment variable** (including `PGPASSWORD`): they end up in shell history and process lists. Type passwords at prompts, and write secret files with `sudoedit` after creating them empty with mode 0600.

## 1. Before you start

- **Manager host:** Ubuntu 24.04 LTS on amd64, with systemd. It ships Python 3.12 and PostgreSQL 16. Ubuntu 22.04 has neither in its archive, so it can't be a manager host.
- **Time:** the host must be NTP-synced (`timedatectl` shows `System clock synchronized: yes`).
- **Name and certificate:** a DNS name for the manager (for example `mgr.example`), a server certificate for it (PEM, the manager's own certificate first, then any intermediates) and its private key. Agents connect to TCP 8443 by default; open that port to them.
- **OpenBao** (Vault Transit API) reachable over `https://`, with its certificate trusted by the system CA store. You need a Transit key for TOTP seeds (for example `bitscan-totp`) and a periodic or non-expiring token whose policy allows only encrypt and decrypt with that key:

  ```hcl
  path "transit/encrypt/bitscan-totp" { capabilities = ["update"] }
  path "transit/decrypt/bitscan-totp" { capabilities = ["update"] }
  ```

  The manager doesn't renew the token.
- **Audit sink:** an `https://host[:port]/path` endpoint (preferred: one JSON `POST` per entry, a `2xx` acknowledges it) or a `syslog+tls://host[:port]` receiver, with its certificate trusted by the system CA store. Every audit entry is sent there.

## 2. Check the release files

Download these files of the release into one folder (for 0.1.0):

- `bitscan_manager-0.1.0-py3-none-any.whl`
- `bitscan-manager-0.1.0-requirements.txt`
- `bitscan-manager.service`, `bitscan-manager-migrate.service`, `bitscan-manager-maintain.service`, `bitscan-manager-maintain.timer`

The release page, which is served from a different origin than the download, shows the release's `SHA256SUMS` text in its notes. Copy that text from the release page into a file named `SHA256SUMS` in the same folder. Never use a checksum file fetched from the same host as the files, including the `SHA256SUMS` file attached to the release.

```sh
sha256sum -c --ignore-missing SHA256SUMS
```

It must print `OK` for each of the six files. Stop if any line says `FAILED`, or if a file is missing from the output.

## 3. PostgreSQL

Install PostgreSQL 16, the `debversion` extension and Python 3.12:

```sh
sudo apt update
sudo apt install postgresql-16 postgresql-16-debversion python3.12 python3.12-venv
```

`pg_trgm` and `pgcrypto` come with `postgresql-16`. Ubuntu turns TLS on with a self-signed certificate. Check it:

```sh
sudo -u postgres psql -X -Atc 'SHOW ssl'
```

It must print `on`. This runbook keeps the database on the manager host and listening only on `localhost` (the default `listen_addresses`). A database on another host is covered at the end of this section.

**Bootstrap.** Save this block, exactly as shown, as `bitscan-bootstrap.sql` (it holds no secret):

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
-- Extensions need a superuser; the CREATE EXTENSION lines in the DDL are then no-ops
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS debversion;
```

Run it once, as the database superuser:

```sh
sudo -u postgres psql -X -v ON_ERROR_STOP=1 < bitscan-bootstrap.sql
```

**Passwords.** Give each of the three login roles its own long random password, typed at the `psql` prompt (`\password` sends only a hash to the server, and no password reaches the history file). Keep them for section 5.

```sh
sudo -u postgres psql -X
```

```text
\password bitscan_app
\password bitscan_retention
\password bitscan_migrate
\q
```

**TLS only.** Edit `/etc/postgresql/16/main/pg_hba.conf` (`sudoedit /etc/postgresql/16/main/pg_hba.conf`) and add these lines **above every other line**. The first matching line wins, so the three roles can then connect only over TLS, only from the manager host and only to the `bitscan` database:

```text
# Bitscan roles: TLS only, from this host only, to the bitscan database only
local      all      bitscan_app,bitscan_retention,bitscan_migrate                 reject
hostnossl  all      bitscan_app,bitscan_retention,bitscan_migrate  all            reject
hostssl    bitscan  bitscan_app,bitscan_retention,bitscan_migrate  127.0.0.1/32   scram-sha-256
host       all      bitscan_app,bitscan_retention,bitscan_migrate  all            reject
```

```sh
sudo systemctl reload postgresql
sudo -u postgres psql -X -Atc 'SELECT line_number, error FROM pg_hba_file_rules WHERE error IS NOT NULL'
```

The query must print nothing. Then check that a connection without TLS is refused before any password is asked:

```sh
psql -X "host=127.0.0.1 dbname=bitscan user=bitscan_app sslmode=disable"
```

It must fail with `pg_hba.conf rejects connection … no encryption`. Repeat with `user=bitscan_retention` and `user=bitscan_migrate`.

**Database on another host.** Use the same Bootstrap, passwords and `pg_hba.conf` lines there, with the manager's address (`<manager address>/32`) instead of `127.0.0.1/32`. Also give PostgreSQL a certificate for its host name signed by a CA you control (`ssl_cert_file`, `ssl_key_file`), and set `listen_addresses` to the address the manager uses. The manager then verifies that certificate (section 5). Accept connections only from the manager host.

## 4. User and folders

```sh
sudo adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin bitscan-manager
sudo install -d -o root -g root -m 0755 /var/lib/bitscan
sudo install -d -o root -g bitscan-manager -m 0750 /var/lib/bitscan/bits
sudo install -d -o bitscan-manager -g bitscan-manager -m 0750 /var/lib/bitscan/bits/uploaded
sudo install -d -o bitscan-manager -g bitscan-manager -m 0700 /var/lib/bitscan/audit-queue
```

Create the folders before the first start: the service can write only `bits/uploaded/` and `audit-queue/`, and it fails to start if they are missing. Only server administrators write `/var/lib/bitscan/bits/`.

## 5. Configuration and secrets

Run this first block only on a fresh host. On an installed host it empties `manager.env` and every secret file.

```sh
sudo install -d -o root -g root -m 0755 /etc/bitscan
sudo install -d -o root -g root -m 0700 /etc/bitscan/secrets
sudo install -o root -g root -m 0600 /dev/null /etc/bitscan/manager.env
for f in app.dsn retention.dsn migrate.dsn tls.crt tls.key vault.token; do
    sudo install -o root -g root -m 0600 /dev/null "/etc/bitscan/secrets/$f"
done
```

**`/etc/bitscan/manager.env`** holds the settings that aren't secret (`sudoedit /etc/bitscan/manager.env`):

```text
BITSCAN_VAULT_ADDR=https://openbao.example:8200
BITSCAN_TOTP_KEY_REF=bitscan-totp
BITSCAN_AUDIT_SINK=https://audit.example/bitscan
# Optional: BITSCAN_LISTEN=0.0.0.0:8443 and BITSCAN_BITS_DIR=/var/lib/bitscan/bits
```

Never put a DSN, password or token in this file, and never set a `BITSCAN_*_FILE` variable here: the units set those to their own credential copies, and a value in this file would replace them.

**The three DSNs.** Write one line into each file with `sudoedit`, using the password you set for that role in section 3:

| File | Line (database on the manager host) |
| --- | --- |
| `/etc/bitscan/secrets/app.dsn` | `host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_app password=<password> sslmode=require` |
| `/etc/bitscan/secrets/retention.dsn` | `host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_retention password=<password> sslmode=require` |
| `/etc/bitscan/secrets/migrate.dsn` | `host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_migrate password=<password> sslmode=require` |

Each DSN uses a TCP address, because a Unix-socket connection doesn't use TLS. `sslmode=require` encrypts the loopback connection without checking the self-signed certificate.

For a database on another host, verify its certificate instead. Copy the CA that signed it (a public certificate, not a secret) to `/etc/bitscan/postgres-ca.pem`:

```sh
sudo install -o root -g root -m 0644 postgres-ca.pem /etc/bitscan/postgres-ca.pem
```

Then write each DSN as `host=<database host name> port=5432 dbname=bitscan user=<role> password=<password> sslmode=verify-full sslrootcert=/etc/bitscan/postgres-ca.pem`. The CA must be named in the DSN. The manager's user has no home folder, the units hide home folders, and the migrate and maintain units run as a temporary user, so libpq's default CA file `~/.postgresql/root.crt` never exists for them. The CA stays outside `secrets/`, which those users can't read.

**Certificate, key and OpenBao token.** Copy the certificate and key into the empty files (copying onto an existing file keeps its owner and mode), and write the OpenBao token into `vault.token` with `sudoedit`:

```sh
sudo cp manager.crt /etc/bitscan/secrets/tls.crt
sudo cp manager.key /etc/bitscan/secrets/tls.key
sudoedit /etc/bitscan/secrets/vault.token
```

Then delete your working copy of the key.

## 6. Install the software

```sh
sudo python3.12 -m venv /opt/bitscan-manager
sudo /opt/bitscan-manager/bin/pip install --require-hashes --only-binary :all: -r bitscan-manager-0.1.0-requirements.txt
sudo /opt/bitscan-manager/bin/pip install --no-deps --no-index ./bitscan_manager-0.1.0-py3-none-any.whl
sudo ln -sfn /opt/bitscan-manager/bin/bitscan-manager /usr/bin/bitscan-manager
bitscan-manager --help
sudo find /opt/bitscan-manager ! -type l -perm /022
```

`--help` must list `serve`, `users …`, `db migrate` and `db maintain`. The `find` must print nothing: nothing in the venv may be writable by group or others. Every dependency is checked against the hash in the requirements file, and only wheels are installed.

Without internet access on the manager host, download the wheels on another Ubuntu 24.04 amd64 host with Python 3.12: `python3.12 -m pip download --require-hashes --only-binary :all: -r bitscan-manager-0.1.0-requirements.txt -d wheelhouse`. Copy `wheelhouse/` across, and add `--no-index --find-links wheelhouse` to the first `pip install`. The hashes are still checked.

## 7. Units

Install the four unit files exactly as released:

```sh
sudo install -o root -g root -m 0644 bitscan-manager.service bitscan-manager-migrate.service \
    bitscan-manager-maintain.service bitscan-manager-maintain.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/bitscan-manager.service \
    /etc/systemd/system/bitscan-manager-migrate.service \
    /etc/systemd/system/bitscan-manager-maintain.service \
    /etc/systemd/system/bitscan-manager-maintain.timer
```

`systemd-analyze verify` must print nothing. Never edit these files or add drop-ins (`systemctl edit`). Their hardening is part of the security design, and an upgrade replaces them.

## 8. Database schema and maintenance

```sh
sudo systemctl start bitscan-manager-migrate
sudo journalctl -u bitscan-manager-migrate -n 20 --no-pager
sudo systemctl start bitscan-manager-maintain.service
sudo journalctl -u bitscan-manager-maintain -n 5 --no-pager
sudo systemctl enable --now bitscan-manager-maintain.timer
systemctl list-timers bitscan-manager-maintain.timer
```

`systemctl start bitscan-manager-migrate` must return without an error, and the log ends with the head revision id. A second start changes nothing. The maintenance run writes `created <name>` or `nothing to do` to its journal, which the `journalctl -u bitscan-manager-maintain` line shows. The timer then runs it daily.

## 9. Start the manager

```sh
sudo systemctl enable --now bitscan-manager
systemctl is-active bitscan-manager
ok=no
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sS --cacert manager-ca.pem https://mgr.example:8443/readyz; then ok=yes; break; fi
    sleep 1
done
[ "$ok" = yes ] || echo "readyz: no answer after $i tries; see sudo journalctl -u bitscan-manager" >&2
```

The manager starts listening a moment after `enable --now` returns, so the loop tries `curl` up to 10 times, a second apart. `curl` must print `{"status":"ok"}`. Leave out `--cacert` if the manager's certificate is signed by a CA in the system store. A 503 names the failed check: `db` (check the DSNs and `pg_hba.conf`), `migrations` (run section 8 again) or `system_schedule`. Start-up errors are in `sudo journalctl -u bitscan-manager`.

## 10. First admin

```sh
sudo bitscan-manager users create-admin alice
```

Use the admin's own user name instead of `alice` (1–64 characters of letters, digits, `.`, `_`, `@` and `-`). The command asks for the password twice (12 to 1,024 characters). Open `https://mgr.example:8443/` in a browser that trusts the manager's certificate and sign in. The new admin sees only the TOTP page: press **Start**, scan the QR code with an authenticator app, enter a code and press **Confirm**. This needs OpenBao, and the session is then TOTP-verified. Next, create an enrolment token on **Enrolment tokens** and install agents with `agent-install.md`.

## 11. Check the install

```sh
systemctl show -p User,ActiveState bitscan-manager
grep -E '^(CapEff|CapPrm|CapBnd|CapAmb|NoNewPrivs)' /proc/"$(systemctl show -p MainPID --value bitscan-manager)"/status
sudo find /etc/bitscan /var/lib/bitscan -maxdepth 2 -printf '%u:%g %m %p\n'
sudo -u bitscan-manager cat /etc/bitscan/secrets/migrate.dsn
for f in bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service bitscan-manager-maintain.timer; do
    cmp "$f" "/etc/systemd/system/$f"
done
```

- The service runs as `User=bitscan-manager` and is `active`.
- The four `Cap…` values are all `0000000000000000`, and `NoNewPrivs` is `1`.
- The `find` lines show the owners and modes of sections 4 and 5: `root:root 755` for `/etc/bitscan` and `/var/lib/bitscan`, `root:root 600` for `manager.env` and every secret, `root:root 700` for `secrets/`, `root:bitscan-manager 750` for `bits/`, `bitscan-manager:bitscan-manager 750` for `uploaded/` and `bitscan-manager:bitscan-manager 700` for `audit-queue/`.
- Reading `migrate.dsn` as `bitscan-manager` fails with `Permission denied`.
- `cmp` prints nothing for each unit file.
