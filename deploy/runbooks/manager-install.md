# Install the Bitscan manager

This runbook installs one manager on a fresh host: what it depends on (its TLS certificate, OpenBao and the audit sink), PostgreSQL, the `bitscan-manager` user and folders, configuration and secrets, the Python package, the four systemd units, the database schema and the first admin. Run every command as an administrator with `sudo`. Upgrades, certificate replacement, backups and removal are in `manager-operations.md`; agents are installed with `agent-install.md`.

**Never put a password, token or DSN on a command line or in an environment variable** (including `PGPASSWORD`): they end up in shell history and process lists. Type passwords at prompts, and write secret files with `sudoedit` after creating them empty with mode 0600.

## 1. Before you start

- **Manager host:** Ubuntu 24.04 LTS on amd64, with systemd. It ships Python 3.12 and PostgreSQL 16. Ubuntu 22.04 has neither in its archive, so it can't be a manager host.
- **Time:** the host must be NTP-synced. Turn time synchronisation on, then check it:

  ```sh
  sudo timedatectl set-ntp true
  timedatectl
  ```

  `timedatectl` must show `System clock synchronized: yes`; this can take a minute. If `set-ntp` answers `NTP not supported`, install `systemd-timesyncd` first (`sudo apt install systemd-timesyncd`).
- **Name and certificate:** a DNS name for the manager (for example `mgr.example`), a server certificate for it and its private key (section 1.1). Agents connect to TCP 8443 by default; open that port to them.
- **OpenBao** (Vault Transit API), which encrypts the users' TOTP seeds (section 1.2).
- **Audit sink**, which receives every audit entry (section 1.3).

### 1.1 Manager TLS certificate

The manager serves HTTPS only, with one server certificate. Agents and browsers check it against the name they connect to.

**From your organisation's CA.** Create the key and a certificate request on the manager host, then send `manager.csr` to the CA:

```sh
(umask 077 && openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
    -keyout manager.key -out manager.csr -subj "/CN=mgr.example" -addext "subjectAltName=DNS:mgr.example")
```

Ask for a TLS server certificate whose subject alternative names hold every DNS name agents and browsers use for the manager. An RSA key of at least 2048 bits works too. The key must stay unencrypted PEM, because the service can't be given a passphrase. Put the certificate you get back, in PEM, into `manager.crt`: the manager's own certificate first, then each intermediate, without the root. For example `cat mgr.example.crt intermediate.crt > manager.crt`. Check it:

```sh
openssl x509 -in manager.crt -noout -subject -ext subjectAltName -enddate
cmp <(openssl x509 -in manager.crt -noout -pubkey) <(openssl pkey -in manager.key -pubout)
openssl verify -untrusted manager.crt manager.crt
```

The names must be the ones agents use, and `cmp` must print nothing (the certificate matches the key). `openssl verify` must print `manager.crt: OK`. If your CA isn't in the system store, add `-CAfile` with its root certificate. Save that root certificate as `manager-ca.pem`: agents need it (below), and section 9 uses it.

**From a private CA, for a lab.** On an admin workstation, not on the manager host, create a CA and issue certificates with it. The `issue` function makes a key and a certificate for one DNS name. Use it for the manager, and for the audit sink if you follow section 1.3:

```sh
(umask 077 && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
    -keyout manager-ca.key -out manager-ca.pem -days 1825 -subj "/CN=Bitscan lab CA" \
    -addext "keyUsage=critical,keyCertSign,cRLSign")
issue() {
    (umask 077 && openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
        -keyout "$1.key" -out "$1.csr" -subj "/CN=$1")
    printf 'subjectAltName=DNS:%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' "$1" > "$1.ext"
    openssl x509 -req -in "$1.csr" -CA manager-ca.pem -CAkey manager-ca.key -CAcreateserial \
        -days 397 -extfile "$1.ext" -out "$1.crt"
}
issue mgr.example
mv mgr.example.crt manager.crt
mv mgr.example.key manager.key
```

Copy `manager.crt`, `manager.key` and `manager-ca.pem` to the manager host, and delete the key's copy from the workstation once section 5 is done. Keep `manager-ca.key` off every Bitscan host.

**What agents need.** With a certificate from a CA in the agents' system store, nothing. With a private CA, give each agent `manager-ca.pem` as `bitscan/ca_file` (`agent-install.md` section 1). Optionally, pin the manager's key with `bitscan/manager_spki_sha256`: the SHA-256 of the DER `SubjectPublicKeyInfo` of the manager's own (leaf) certificate, which is what the agent compares. After section 5, compute it on the manager host:

```sh
sudo openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey |
    openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1
```

It prints 64 hexadecimal characters. A pin stays valid while the certificate keeps the same key (`manager-operations.md` section 2). With a private CA, the browsers that sign in to the manager need `manager-ca.pem` too.

### 1.2 OpenBao

The manager encrypts and decrypts TOTP seeds with an OpenBao Transit key. You need an OpenBao server that the manager host reaches over `https://`. To install one, follow the [OpenBao documentation](https://openbao.org/docs/). The manager checks the server's certificate against the manager host's system CA store. If a private CA signed it, add that CA (PEM) on the manager host:

```sh
sudo install -o root -g root -m 0644 openbao-ca.pem /usr/local/share/ca-certificates/openbao-ca.crt
sudo update-ca-certificates
```

Then, as an OpenBao admin, signed in with the `bao` CLI on your admin workstation (`BAO_ADDR` set to the server), enable the Transit engine, create the key, write the manager's policy and a token role:

```sh
bao secrets enable transit
bao write -f transit/keys/bitscan-totp
bao policy write bitscan-manager - <<'EOF'
path "transit/encrypt/bitscan-totp" { capabilities = ["update"] }
path "transit/decrypt/bitscan-totp" { capabilities = ["update"] }
path "auth/token/renew-self" { capabilities = ["update"] }
EOF
bao write auth/token/roles/bitscan-manager allowed_policies=bitscan-manager \
    orphan=true token_no_default_policy=true token_period=168h
```

If Transit is already enabled at `transit/`, skip the first line. The policy allows only encrypt and decrypt with the TOTP key, and renewing the token itself. The role's tokens are:

- **periodic:** each renewal extends the token by 7 days, and a token that isn't renewed for 7 days expires. OpenBao gives only root tokens an unlimited lifetime, so the manager's token must be renewed. The manager doesn't renew it itself; section 5 sets up a timer that does;
- **orphans:** revoking the admin token that created them, or its expiry, doesn't revoke them;
- **without the `default` policy.**

You create the manager's token in section 5, once its file exists. Back up OpenBao as well: without the `bitscan-totp` key, no stored TOTP seed can be decrypted, and every user's TOTP must be reset.

### 1.3 Audit sink

The manager sends every audit entry to `BITSCAN_AUDIT_SINK`, which takes one of two forms:

- `https://host[:port]/path` (preferred): one JSON `POST` per entry, and a `2xx` acknowledges exactly that entry. Use an HTTPS intake of your log platform that accepts this. The manager sends no credentials, so allow only the manager's address to post.
- `syslog+tls://host[:port]` (default port 6514): one RFC 5424 message per entry over TLS, with RFC 5425 framing. Syslog has no acknowledgement, so watch the receiver for gaps in `audit_id`.

In both forms the manager checks the receiver's certificate against the manager host's system CA store, and the host name in the URL must be in the certificate. Add a private CA as in section 1.2. The manager presents no client certificate.

**Example: an rsyslog receiver** on its own Ubuntu 24.04 host, `sink.example`, that writes every entry to `/var/log/bitscan-audit.log`. It needs a certificate for `sink.example` (for a lab, `issue sink.example` in section 1.1) and the CA that signed it, here the lab's `manager-ca.pem`. On the sink host:

```sh
sudo apt install rsyslog rsyslog-gnutls
sudo install -d -o root -g syslog -m 0750 /etc/rsyslog.d/tls
sudo install -o root -g syslog -m 0644 manager-ca.pem /etc/rsyslog.d/tls/ca.pem
sudo install -o root -g syslog -m 0644 sink.example.crt /etc/rsyslog.d/tls/sink.crt
sudo install -o root -g syslog -m 0640 /dev/null /etc/rsyslog.d/tls/sink.key
sudo cp sink.example.key /etc/rsyslog.d/tls/sink.key
sudo install -o root -g root -m 0644 /dev/null /etc/rsyslog.d/60-bitscan-audit.conf
sudoedit /etc/rsyslog.d/60-bitscan-audit.conf
```

Then delete your copy of `sink.example.key`. Write this into `60-bitscan-audit.conf`:

```text
# Bitscan manager audit entries: TLS only on TCP 6514, written to one file
global(
    DefaultNetstreamDriver="gtls"
    DefaultNetstreamDriverCAFile="/etc/rsyslog.d/tls/ca.pem"
    DefaultNetstreamDriverCertFile="/etc/rsyslog.d/tls/sink.crt"
    DefaultNetstreamDriverKeyFile="/etc/rsyslog.d/tls/sink.key"
    maxMessageSize="1m"
)
module(load="imtcp" StreamDriver.Name="gtls" StreamDriver.Mode="1" StreamDriver.AuthMode="anon" MaxFrameSize="1048576")
ruleset(name="bitscan-audit") {
    action(type="omfile" file="/var/log/bitscan-audit.log")
}
input(type="imtcp" port="6514" ruleset="bitscan-audit")
```

`StreamDriver.Mode="1"` accepts TLS only, and `AuthMode="anon"` asks the manager for no client certificate. The `bitscan-audit` ruleset keeps the entries out of the host's other logs. Check the file, restart rsyslog and check that it listens:

```sh
sudo rsyslogd -N1
sudo systemctl restart rsyslog
sudo ss -ltn 'sport = :6514'
```

`rsyslogd -N1` must report no error, and `ss` must show a listener on port 6514. Allow TCP 6514 only from the manager's address, for example `sudo ufw allow from <manager address> to any port 6514 proto tcp`. If rsyslog can't read its files, check `sudo dmesg | grep -i apparmor` for a denied read. From the manager host, check the TLS connection and the certificate:

```sh
openssl s_client -connect sink.example:6514 -verify_hostname sink.example -verify_return_error -brief </dev/null
```

It must print `Verification: OK`. In section 5, set `BITSCAN_AUDIT_SINK=syslog+tls://sink.example:6514`. Section 10 checks that an entry arrives.

**If the sink is down**, the manager keeps working. Entries queue on disk in `/var/lib/bitscan/audit-queue/` and an `audit_sink_unreachable` alert is written at once. After 15 minutes of outage, sensitive actions answer 503 until the queue has drained. These are approving or rejecting enrolments, revoking agents, rebuilding, re-evaluating, and managing users, enrolment tokens and settings. Keep the sink as available as the manager.

## 2. Check the release files

Download these files of the release into one folder (for 0.2.0):

- `bitscan_manager-0.2.0-py3-none-any.whl`
- `bitscan-manager-0.2.0-requirements.txt`
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
# Or, with the rsyslog receiver of section 1.3: BITSCAN_AUDIT_SINK=syslog+tls://sink.example:6514
# Optional: BITSCAN_LISTEN=0.0.0.0:8443 and BITSCAN_BITS_DIR=/var/lib/bitscan/bits
```

`BITSCAN_VAULT_ADDR` is your OpenBao server and `BITSCAN_TOTP_KEY_REF` the Transit key of section 1.2. `BITSCAN_AUDIT_SINK` is the receiver of section 1.3.

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

**Certificate and key** (section 1.1). Copy them into the empty files (copying onto an existing file keeps its owner and mode):

```sh
sudo cp manager.crt /etc/bitscan/secrets/tls.crt
sudo cp manager.key /etc/bitscan/secrets/tls.key
```

Then delete your working copy of the key.

**OpenBao token.** As the OpenBao admin of section 1.2, create the manager's token from the role. Prefer your admin workstation, so your own OpenBao admin token never reaches the manager host. Run the `bao token create` line below there, without the `| sudo tee …` part, paste the token it prints into `sudoedit /etc/bitscan/secrets/vault.token` on the manager host, then clear that terminal. The file must hold the token on its first line.

If you must run `bao` on the manager host, sign in with `bao login -no-print` and type your admin token at its prompt, never through `BAO_TOKEN`. Without `-no-print`, `bao login` shows the token on screen. It keeps your token in `~/.vault-token`, so remove it afterwards. The `revoke -self` line also revokes it in OpenBao; leave that line out if you still need that admin token:

```sh
bao login -no-print
bao token create -role=bitscan-manager -policy=bitscan-manager -no-default-policy \
    -display-name=bitscan-manager -field=token | sudo tee /etc/bitscan/secrets/vault.token >/dev/null
bao token revoke -self
rm -f ~/.vault-token
```

Check that the token can encrypt and decrypt with the TOTP key and renew itself, and is refused on other paths. The block reads the address and key from `manager.env`, and hands the token to `curl` on standard input, in an `X-Vault-Token` header:

```sh
bao_url="$(sudo sed -n 's/^BITSCAN_VAULT_ADDR=//p' /etc/bitscan/manager.env)"
bao_url="${bao_url%/}"
key="$(sudo sed -n 's/^BITSCAN_TOTP_KEY_REF=//p' /etc/bitscan/manager.env)"
tok() { sudo sed -n '1s/^/X-Vault-Token: /p' /etc/bitscan/secrets/vault.token; }
ct="$(tok | curl -sS --fail -H @- --data '{"plaintext": "Yml0c2Nhbg=="}' "$bao_url/v1/transit/encrypt/$key" |
    python3.12 -I -c 'import json, sys; print(json.load(sys.stdin)["data"]["ciphertext"])')"
tok | curl -sS --fail -H @- --data "{\"ciphertext\": \"$ct\"}" "$bao_url/v1/transit/decrypt/$key" |
    python3.12 -I -c 'import json, sys; print(json.load(sys.stdin)["data"]["plaintext"])'
tok | curl -sS --fail -H @- --data '{}' "$bao_url/v1/auth/token/renew-self" |
    python3.12 -I -c 'import json, sys; a = json.load(sys.stdin)["auth"]; print(a["lease_duration"], a["renewable"], a["policies"])'
for p in transit/encrypt/another-key transit/keys/bitscan-totp/rotate auth/token/create; do
    tok | curl -sS -o /dev/null -w "%{http_code} $p\n" -H @- --data '{}' "$bao_url/v1/$p"
done
for p in sys/mounts auth/token/lookup-self; do
    tok | curl -sS -o /dev/null -w "%{http_code} $p\n" -H @- "$bao_url/v1/$p"
done
```

- The decrypt line prints `Yml0c2Nhbg==`, the test value sent to encrypt.
- The renewal line prints `604800 True ['bitscan-manager']`: 7 days, renewable, and only the manager's policy.
- Each of the last five lines starts with `403`.

**Renew the OpenBao token.** A timer on the manager host renews the token twice a day, so a failed renewal has days to be noticed and fixed before the token expires. It runs as a temporary user and receives only the token, as a unit credential (`LoadCredential=`, as in the manager's own units). Create the script, the service and the timer:

```sh
sudo tee /usr/local/sbin/bitscan-openbao-renew >/dev/null <<'EOF'
#!/bin/sh
# Renews the Bitscan manager's periodic OpenBao token. The token reaches curl
# on standard input, never on the command line.
set -eu
sed -n '1s/^/X-Vault-Token: /p' "$CREDENTIALS_DIRECTORY/vault_token" |
    curl -sS --fail --proto =https -o /dev/null -H @- --data '{}' \
        "${BITSCAN_VAULT_ADDR%/}/v1/auth/token/renew-self"
EOF
sudo chmod 0755 /usr/local/sbin/bitscan-openbao-renew
sudo tee /etc/systemd/system/bitscan-openbao-renew.service >/dev/null <<'EOF'
[Unit]
Description=Renew the Bitscan manager's OpenBao token
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
DynamicUser=yes
EnvironmentFile=/etc/bitscan/manager.env
LoadCredential=vault_token:/etc/bitscan/secrets/vault.token
ExecStart=/usr/local/sbin/bitscan-openbao-renew
EOF
sudo tee /etc/systemd/system/bitscan-openbao-renew.timer >/dev/null <<'EOF'
[Unit]
Description=Renew the Bitscan manager's OpenBao token twice a day

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/bitscan-openbao-renew.service /etc/systemd/system/bitscan-openbao-renew.timer
sudo systemctl start bitscan-openbao-renew.service
sudo systemctl enable --now bitscan-openbao-renew.timer
systemctl list-timers bitscan-openbao-renew.timer
```

`systemd-analyze verify` must print nothing, and `systemctl start` must return without an error. `list-timers` shows the next run. A failed renewal leaves `bitscan-openbao-renew.service` failed (`systemctl --failed`), and `sudo journalctl -u bitscan-openbao-renew` gives curl's reason. Watch for it in your monitoring: once the token has expired, sign-in for users with TOTP answers 503 until you replace it (`manager-operations.md` section 3).

## 6. Install the software

```sh
sudo python3.12 -m venv /opt/bitscan-manager
sudo /opt/bitscan-manager/bin/pip install --require-hashes --only-binary :all: -r bitscan-manager-0.2.0-requirements.txt
sudo /opt/bitscan-manager/bin/pip install --no-deps --no-index ./bitscan_manager-0.2.0-py3-none-any.whl
sudo ln -sfn /opt/bitscan-manager/bin/bitscan-manager /usr/bin/bitscan-manager
bitscan-manager --help
sudo find /opt/bitscan-manager ! -type l -perm /022
```

`--help` must list `serve`, `users …`, `db migrate` and `db maintain`. The `find` must print nothing: nothing in the venv may be writable by group or others. Every dependency is checked against the hash in the requirements file, and only wheels are installed.

Without internet access on the manager host, download the wheels on another Ubuntu 24.04 amd64 host with Python 3.12: `python3.12 -m pip download --require-hashes --only-binary :all: -r bitscan-manager-0.2.0-requirements.txt -d wheelhouse`. Copy `wheelhouse/` across, and add `--no-index --find-links wheelhouse` to the first `pip install`. The hashes are still checked.

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

Use the admin's own user name instead of `alice` (1–64 characters of letters, digits, `.`, `_`, `@` and `-`). The command asks for the password twice (12 to 1,024 characters). Open `https://mgr.example:8443/` in a browser that trusts the manager's certificate and sign in. The new admin sees only the TOTP page: press **Start**, scan the QR code with an authenticator app, enter a code and press **Confirm**. This needs OpenBao, and the session is then TOTP-verified.

Check that audit entries reach the sink. The sign-in wrote an `auth.login` entry and the TOTP enrolment an `auth.totp_enrol` entry. With the rsyslog receiver of section 1.3, run this on the sink host:

```sh
sudo grep -c -e '"action":"auth.login"' -e '"action":"auth.totp_enrol"' /var/log/bitscan-audit.log
```

It must print 2 or more within a minute of the enrolment. With an HTTPS sink, look for the two entries in your log platform. If they don't arrive, `sudo journalctl -u bitscan-manager` on the manager host names the delivery error.

Next, create an enrolment token on **Enrolment tokens** and install agents with `agent-install.md`.

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
