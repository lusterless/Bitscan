#!/usr/bin/env bash
# Sets up a Bitscan manager and what it depends on, following
# deploy/runbooks/manager-install.md (TS §8.6, §8.7). Run the modes in order:
#
#   1. ca       (admin workstation)  lab CA and server certificates      runbook 1.1
#   2. openbao  (admin workstation)  Transit key, policy, role, token     runbook 1.2, 5
#   3. sink     (sink host, root)    rsyslog receiver over TLS            runbook 1.3
#   4. manager  (manager host, root) checks the sink, then OpenBao, then installs
#                                    PostgreSQL, secrets, software, units runbook 1.2-11
#   5. agent    (each agent host, root) checks the manager over TLS, then
#                                    installs and enrols the agent        agent-install.md
#
# OpenBao and the audit sink are reached over TLS only; a private CA that signed
# them is added to the manager host's system CA store, which is what the manager
# verifies against. The manager itself serves HTTPS only (TS §8.7).
#
# No password, token or DSN is ever put on a command line or in the
# environment: database passwords are generated here and written straight into
# the 0600 DSN files, PostgreSQL receives only their SCRAM verifiers, and the
# OpenBao token reaches curl on standard input.
#
# Usage: bitscan-setup.sh <mode> [options]; bitscan-setup.sh <mode> --help

set -euo pipefail
umask 077
# Git Bash on an admin workstation would rewrite -subj "/CN=..." as a path
export MSYS_NO_PATHCONV=1

PROG="${0##*/}"
step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "run this mode as root (sudo $0 $MODE ...)"; }
need_file() { [ -s "$1" ] || die "$2: $1 is missing or empty"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed"; }

# host and port of a URL; $2 is the default port
url_host_port() {
    local rest="${1#*://}"
    rest="${rest%%/*}"
    case "$rest" in
        *:*) printf '%s %s\n' "${rest%%:*}" "${rest##*:}" ;;
        *) printf '%s %s\n' "$rest" "$2" ;;
    esac
}

# TLS handshake that must verify the chain and the host name against the system store
check_tls() {
    local host="$1" port="$2" what="$3" out
    out="$(openssl s_client -connect "$host:$port" -servername "$host" -verify_hostname "$host" \
        -verify_return_error -brief </dev/null 2>&1 || true)"
    if ! grep -q 'Verification: OK' <<<"$out"; then
        printf '%s\n' "$out" | sed -n '1,5p' >&2
        die "$what at $host:$port: TLS verification failed (is its CA installed? is the name in its certificate?)"
    fi
    info "$what $host:$port: TLS OK, certificate verified for $host"
}

install_ca() {
    # $1 PEM file, $2 name in /usr/local/share/ca-certificates
    need_file "$1" "CA certificate"
    openssl x509 -in "$1" -noout >/dev/null 2>&1 || die "$1 is not a PEM certificate"
    install -o root -g root -m 0644 "$1" "/usr/local/share/ca-certificates/$2.crt"
    update-ca-certificates >/dev/null
    info "added $1 to the system CA store as $2"
}

# ---------------------------------------------------------------------------
# 1. ca: lab CA and server certificates (admin workstation, never a Bitscan host)
# ---------------------------------------------------------------------------
mode_ca() {
    local dir="." names=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --dir) dir="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: $PROG ca [--dir DIR] NAME...
Creates DIR/manager-ca.pem and manager-ca.key (once), then a key and a
certificate (NAME.key, NAME.crt) for each DNS name, for example:
    $PROG ca --dir lab mgr.example sink.example openbao.example
Keep manager-ca.key off every Bitscan host.
EOF
                return ;;
            -*) die "ca: unknown option $1" ;;
            *) names+=("$1"); shift ;;
        esac
    done
    [ "${#names[@]}" -gt 0 ] || die "ca: name at least one DNS name"
    need_cmd openssl
    mkdir -p "$dir"
    cd "$dir"
    if [ ! -s manager-ca.pem ]; then
        step "Creating the lab CA in $dir"
        openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
            -keyout manager-ca.key -out manager-ca.pem -days 1825 -subj "/CN=Bitscan lab CA" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
    fi
    local n
    for n in "${names[@]}"; do
        step "Issuing a server certificate for $n"
        openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
            -keyout "$n.key" -out "$n.csr" -subj "/CN=$n" 2>/dev/null
        printf 'subjectAltName=DNS:%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' \
            "$n" >"$n.ext"
        openssl x509 -req -in "$n.csr" -CA manager-ca.pem -CAkey manager-ca.key -CAcreateserial \
            -days 397 -extfile "$n.ext" -out "$n.crt" 2>/dev/null
        rm -f "$n.csr" "$n.ext"
        openssl verify -CAfile manager-ca.pem "$n.crt"
    done
    info "copy each NAME.crt, NAME.key and manager-ca.pem to its host, then delete the key copies here"
}

# ---------------------------------------------------------------------------
# 2. openbao: Transit key, policy, token role and the manager's token
# ---------------------------------------------------------------------------
mode_openbao() {
    local key="bitscan-totp" token_out=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --key) key="$2"; shift 2 ;;
            --token-out) token_out="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: $PROG openbao [--key bitscan-totp] [--token-out FILE]
Run on the admin workstation, signed in with 'bao login -no-print' and
BAO_ADDR set to the https:// OpenBao address (BAO_CACERT for a private CA).
Enables Transit, creates the key, the bitscan-manager policy and token role.
With --token-out, also creates the manager's periodic token into FILE (0600).
Copy FILE to the manager host for '$PROG manager --vault-token-file', then delete it.
EOF
                return ;;
            *) die "openbao: unknown option $1" ;;
        esac
    done
    need_cmd bao
    case "${BAO_ADDR:-}" in
        https://*) ;;
        *) die "openbao: set BAO_ADDR to the https:// address of OpenBao" ;;
    esac
    bao token lookup >/dev/null 2>&1 || die "openbao: not signed in; run 'bao login -no-print' first"

    step "Transit engine and key $key"
    if bao secrets list -format=json | grep -q '"transit/"'; then
        info "transit/ already enabled"
    else
        bao secrets enable transit
    fi
    if bao read "transit/keys/$key" >/dev/null 2>&1; then
        info "key $key already exists"
    else
        bao write -f "transit/keys/$key" >/dev/null
    fi

    step "Policy and token role bitscan-manager"
    bao policy write bitscan-manager - <<EOF
path "transit/encrypt/$key" { capabilities = ["update"] }
path "transit/decrypt/$key" { capabilities = ["update"] }
path "auth/token/renew-self" { capabilities = ["update"] }
EOF
    bao write auth/token/roles/bitscan-manager allowed_policies=bitscan-manager \
        orphan=true token_no_default_policy=true token_period=168h >/dev/null

    if [ -n "$token_out" ]; then
        if [ -s "$token_out" ]; then die "openbao: $token_out already holds something; not overwriting"; fi
        step "Manager token into $token_out"
        bao token create -role=bitscan-manager -policy=bitscan-manager -no-default-policy \
            -display-name=bitscan-manager -field=token >"$token_out"
        chmod 0600 "$token_out"
        info "copy $token_out to the manager host, then delete it here"
    fi
    info "back up OpenBao: without key $key no stored TOTP seed can be decrypted"
}

# ---------------------------------------------------------------------------
# 3. sink: rsyslog TLS receiver (runbook 1.3)
# ---------------------------------------------------------------------------
mode_sink() {
    local cert="" key="" ca="" allow="" port=6514
    while [ $# -gt 0 ]; do
        case "$1" in
            --cert) cert="$2"; shift 2 ;;
            --key) key="$2"; shift 2 ;;
            --ca) ca="$2"; shift 2 ;;
            --allow) allow="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: sudo $PROG sink --cert sink.crt --key sink.key --ca ca.pem [--allow MANAGER_ADDR]
Sets up rsyslog on this Ubuntu 24.04 host to accept the manager's audit entries
over TLS on TCP $port and write them to /var/log/bitscan-audit.log.
--allow adds a ufw rule for TCP $port from the manager's address only.
EOF
                return ;;
            *) die "sink: unknown option $1" ;;
        esac
    done
    need_root
    need_file "$cert" "--cert"
    need_file "$key" "--key"
    need_file "$ca" "--ca"
    cmp -s <(openssl x509 -in "$cert" -noout -pubkey) <(openssl pkey -in "$key" -pubout) ||
        die "sink: $cert does not match $key"

    step "Installing rsyslog with TLS"
    DEBIAN_FRONTEND=noninteractive apt-get update -q >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q rsyslog rsyslog-gnutls >/dev/null

    step "Certificate files in /etc/rsyslog.d/tls"
    install -d -o root -g syslog -m 0750 /etc/rsyslog.d/tls
    install -o root -g syslog -m 0644 "$ca" /etc/rsyslog.d/tls/ca.pem
    install -o root -g syslog -m 0644 "$cert" /etc/rsyslog.d/tls/sink.crt
    [ -e /etc/rsyslog.d/tls/sink.key ] || install -o root -g syslog -m 0640 /dev/null /etc/rsyslog.d/tls/sink.key
    cat "$key" >/etc/rsyslog.d/tls/sink.key

    step "Receiver configuration /etc/rsyslog.d/60-bitscan-audit.conf"
    install -o root -g root -m 0644 /dev/null /etc/rsyslog.d/60-bitscan-audit.conf
    cat >/etc/rsyslog.d/60-bitscan-audit.conf <<EOF
# Bitscan manager audit entries: TLS only on TCP $port, written to one file
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
input(type="imtcp" port="$port" ruleset="bitscan-audit")
EOF
    rsyslogd -N1 >/dev/null 2>&1 || { rsyslogd -N1 || true; die "sink: rsyslog rejects the configuration"; }
    systemctl restart rsyslog
    sleep 1
    ss -ltn "sport = :$port" | grep -q LISTEN || die "sink: rsyslog does not listen on $port (check: dmesg | grep -i apparmor)"
    info "rsyslog listens on TCP $port"

    if [ -n "$allow" ]; then
        if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
            ufw allow from "$allow" to any port "$port" proto tcp >/dev/null
            info "ufw: TCP $port allowed from $allow"
        else
            info "ufw is not active; allow TCP $port only from $allow in your firewall"
        fi
    fi
    info "delete your copy of $key; on the manager use --sink syslog+tls://$(hostname -f 2>/dev/null || hostname):$port"
}

# ---------------------------------------------------------------------------
# 4. manager: everything on the manager host (runbook 1.2-11)
# ---------------------------------------------------------------------------
SECRETS=/etc/bitscan/secrets
ENV_FILE=/etc/bitscan/manager.env
HBA=/etc/postgresql/16/main/pg_hba.conf
HBA_MARK='# Bitscan roles: TLS only, from this host only, to the bitscan database only'

psql_su() { runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 "$@"; }

# Gives a role a new random password: PostgreSQL gets only the SCRAM verifier,
# the password goes only into the role's DSN file. Skipped if the file is set.
set_role_password() {
    local role="$1" file="$2"
    if [ -s "$file" ]; then
        info "$file already set; keeping $role's password"
        return
    fi
    python3.12 -I - "$role" "$file.new" <<'PY' | psql_su -d bitscan
import base64, hashlib, hmac, secrets, sys
role, path = sys.argv[1], sys.argv[2]
password = secrets.token_urlsafe(32)
salt = secrets.token_bytes(16)
salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
client_key = hmac.new(salted, b"Client Key", "sha256").digest()
server_key = hmac.new(salted, b"Server Key", "sha256").digest()
b64 = lambda raw: base64.b64encode(raw).decode()
verifier = f"SCRAM-SHA-256$4096:{b64(salt)}${b64(hashlib.sha256(client_key).digest())}:{b64(server_key)}"
with open(path, "w") as handle:
    handle.write(
        f"host=127.0.0.1 port=5432 dbname=bitscan user={role} password={password} sslmode=require\n"
    )
print(f"ALTER ROLE {role} PASSWORD '{verifier}';")
PY
    # Copy onto the existing 0600 file, so its owner and mode stay.
    cat "$file.new" >"$file"
    rm -f "$file.new"
    info "$role: new password set, written to $file"
}

# Vault token header for curl on standard input
vault_hdr() { sed -n '1s/^/X-Vault-Token: /p' "$SECRETS/vault.token"; }

check_vault_token() {
    local addr="${1%/}" key="$2" ct pt renew p code bad=0
    ct="$(vault_hdr | curl -sS --fail --proto =https -H @- --data '{"plaintext": "Yml0c2Nhbg=="}' \
        "$addr/v1/transit/encrypt/$key" |
        python3.12 -I -c 'import json, sys; print(json.load(sys.stdin)["data"]["ciphertext"])')" ||
        die "OpenBao: the manager's token cannot encrypt with $key"
    pt="$(vault_hdr | curl -sS --fail --proto =https -H @- --data "{\"ciphertext\": \"$ct\"}" \
        "$addr/v1/transit/decrypt/$key" |
        python3.12 -I -c 'import json, sys; print(json.load(sys.stdin)["data"]["plaintext"])')" ||
        die "OpenBao: the manager's token cannot decrypt with $key"
    [ "$pt" = "Yml0c2Nhbg==" ] || die "OpenBao: decrypt returned a different value"
    renew="$(vault_hdr | curl -sS --fail --proto =https -H @- --data '{}' "$addr/v1/auth/token/renew-self" |
        python3.12 -I -c 'import json, sys; a = json.load(sys.stdin)["auth"]; print(a["lease_duration"], a["renewable"], a["policies"])')" ||
        die "OpenBao: the manager's token cannot renew itself"
    [ "$renew" = "604800 True ['bitscan-manager']" ] ||
        die "OpenBao: renewal gave '$renew', expected 604800 True ['bitscan-manager'] (token from the bitscan-manager role?)"
    for p in transit/encrypt/another-key transit/keys/$key/rotate auth/token/create; do
        code="$(vault_hdr | curl -sS -o /dev/null -w '%{http_code}' --proto =https -H @- --data '{}' "$addr/v1/$p")"
        [ "$code" = 403 ] || { info "POST $p answered $code, expected 403"; bad=1; }
    done
    for p in sys/mounts auth/token/lookup-self; do
        code="$(vault_hdr | curl -sS -o /dev/null -w '%{http_code}' --proto =https -H @- "$addr/v1/$p")"
        [ "$code" = 403 ] || { info "GET $p answered $code, expected 403"; bad=1; }
    done
    [ "$bad" -eq 0 ] || die "OpenBao: the manager's token can do more than encrypt, decrypt and renew"
    info "OpenBao token: encrypt, decrypt and renew work (7 days, renewable); everything else 403"
}

mode_manager() {
    local name="" cert="" key="" ca="" vault_addr="" vault_ca="" vault_token="" key_ref="bitscan-totp"
    local sink="" sink_ca="" release="" listen="" admin=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --name) name="$2"; shift 2 ;;
            --cert) cert="$2"; shift 2 ;;
            --key) key="$2"; shift 2 ;;
            --ca) ca="$2"; shift 2 ;;
            --sink) sink="$2"; shift 2 ;;
            --sink-ca) sink_ca="$2"; shift 2 ;;
            --vault-addr) vault_addr="$2"; shift 2 ;;
            --vault-ca) vault_ca="$2"; shift 2 ;;
            --vault-token-file) vault_token="$2"; shift 2 ;;
            --totp-key) key_ref="$2"; shift 2 ;;
            --release-dir) release="$2"; shift 2 ;;
            --listen) listen="$2"; shift 2 ;;
            --admin) admin="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: sudo $PROG manager --name mgr.example --cert manager.crt --key manager.key [--ca manager-ca.pem]
           --sink syslog+tls://sink.example:6514 | https://audit.example/bitscan [--sink-ca CA.pem]
           --vault-addr https://openbao.example:8200 [--vault-ca CA.pem] --vault-token-file FILE
           --release-dir DIR [--totp-key bitscan-totp] [--listen 0.0.0.0:8443] [--admin NAME]

Order: the audit sink is checked first (TLS), then OpenBao (TLS and token),
then PostgreSQL, user and folders, configuration and secrets, the OpenBao
renewal timer, the software, the units, the schema, the manager and the first
admin. Safe to run again: secrets that are already set are kept.

--release-dir holds the wheel, the requirements file, the four unit files and
SHA256SUMS, copied by hand from the release page (never fetched from the
download host). --ca is the CA that signed the manager's certificate, for the
readyz check; leave it out for a public CA. --sink-ca and --vault-ca add a
private CA to the system CA store, which the manager verifies against.
--vault-token-file is needed on the first run only.
EOF
                return ;;
            *) die "manager: unknown option $1" ;;
        esac
    done
    need_root
    [ -n "$name" ] || die "manager: --name is required"
    [ -n "$sink" ] || die "manager: --sink is required"
    [ -n "$vault_addr" ] || die "manager: --vault-addr is required"
    [ -n "$release" ] || die "manager: --release-dir is required"
    case "$vault_addr" in https://*) ;; *) die "manager: --vault-addr must be https://" ;; esac
    case "$sink" in syslog+tls://*|https://*) ;; *) die "manager: --sink must be syslog+tls:// or https://" ;; esac
    local port="${listen##*:}"
    port="${port:-8443}"

    step "Host checks"
    # shellcheck source=/dev/null
    . /etc/os-release
    [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || die "the manager host must be Ubuntu 24.04"
    [ "$(dpkg --print-architecture)" = amd64 ] || die "the manager host must be amd64"
    timedatectl set-ntp true >/dev/null 2>&1 || info "timedatectl set-ntp failed; install systemd-timesyncd"
    timedatectl show -p NTPSynchronized --value | grep -qx yes ||
        die "clock not NTP-synced yet; wait a minute and run again"
    info "Ubuntu 24.04 amd64, clock synchronised"

    step "TLS tools"
    DEBIAN_FRONTEND=noninteractive apt-get update -q >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q curl ca-certificates openssl >/dev/null

    # --- Audit sink first: nothing else is installed until it answers over TLS ---
    step "Audit sink (checked first)"
    if [ -n "$sink_ca" ]; then install_ca "$sink_ca" bitscan-audit-sink-ca; fi
    local sh sp
    case "$sink" in
        syslog+tls://*) read -r sh sp < <(url_host_port "$sink" 6514) ;;
        *) read -r sh sp < <(url_host_port "$sink" 443) ;;
    esac
    check_tls "$sh" "$sp" "audit sink"

    step "OpenBao TLS"
    if [ -n "$vault_ca" ]; then install_ca "$vault_ca" bitscan-openbao-ca; fi
    local vh vp
    read -r vh vp < <(url_host_port "$vault_addr" 443)
    check_tls "$vh" "$vp" "OpenBao"

    step "Packages"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
        postgresql-16 postgresql-16-debversion python3.12 python3.12-venv >/dev/null
    info "PostgreSQL 16, debversion and Python 3.12 installed"

    step "Release files"
    local f wheel reqs version
    [ -d "$release" ] || die "--release-dir $release is not a folder; download the release files into it first"
    wheel="$(find "$release" -maxdepth 1 -name 'bitscan_manager-*-py3-none-any.whl' -printf '%f\n' | sort | tail -n 1)"
    [ -n "$wheel" ] || die "no bitscan_manager-*.whl in $release"
    version="${wheel#bitscan_manager-}"
    version="${version%%-py3*}"
    reqs="bitscan-manager-$version-requirements.txt"
    local units=(bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service bitscan-manager-maintain.timer)
    need_file "$release/SHA256SUMS" "SHA256SUMS copied from the release page"
    for f in "$wheel" "$reqs" "${units[@]}"; do
        need_file "$release/$f" "release file"
        (cd "$release" && grep -E "^[0-9a-f]{64}  \*?$f\$" SHA256SUMS | sha256sum -c --quiet -) ||
            die "$f: checksum missing from SHA256SUMS or FAILED"
    done
    info "release $version: all six files match SHA256SUMS"

    step "Manager certificate"
    need_file "$cert" "--cert"
    need_file "$key" "--key"
    cmp -s <(openssl x509 -in "$cert" -noout -pubkey) <(openssl pkey -in "$key" -pubout) ||
        die "$cert does not match $key"
    openssl x509 -in "$cert" -noout -checkhost "$name" | grep -q 'does match' ||
        die "$cert is not valid for $name"
    if [ -n "$ca" ]; then
        openssl verify -CAfile "$ca" -untrusted "$cert" "$cert" >/dev/null || die "$cert does not verify against $ca"
    else
        openssl verify -untrusted "$cert" "$cert" >/dev/null || die "$cert does not verify against the system CA store (pass --ca)"
    fi
    info "$cert: matches its key, valid for $name, chain verifies"

    step "PostgreSQL 16 cluster"
    local cluster pg_port pg_state i
    cluster="$(pg_lsclusters -h | awk '$1 == "16" && $2 == "main" {print $3, $4}')"
    [ -n "$cluster" ] ||
        die "no PostgreSQL 16 cluster 'main' (pg_lsclusters); create it with: pg_createcluster 16 main --start"
    read -r pg_port pg_state <<<"$cluster"
    [ "$pg_port" = 5432 ] ||
        die "cluster 16/main uses port $pg_port, not 5432; see what holds 5432: ss -ltnp 'sport = :5432'"
    if [ "$pg_state" != online ]; then
        systemctl enable --now postgresql@16-main >/dev/null 2>&1 ||
            die "cluster 16/main does not start; see journalctl -u postgresql@16-main"
    fi
    for i in $(seq 1 30); do
        pg_isready -q -p 5432 && break
        sleep 1
    done
    pg_isready -q -p 5432 || die "PostgreSQL 16 does not answer on 5432; see journalctl -u postgresql@16-main"
    info "cluster 16/main online on port 5432"

    step "PostgreSQL roles and database"
    [ "$(psql_su -Atc 'SHOW ssl')" = on ] || die "PostgreSQL has TLS off"
    if [ "$(psql_su -Atc "SELECT 1 FROM pg_database WHERE datname = 'bitscan'")" = 1 ]; then
        info "database bitscan exists; bootstrap skipped"
    else
        psql_su <<'SQL'
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
SQL
        info "roles, database and extensions created"
    fi

    step "pg_hba.conf: TLS only, from this host only"
    if grep -qxF "$HBA_MARK" "$HBA"; then
        info "Bitscan lines already present"
    else
        local tmp
        tmp="$(mktemp)"
        {
            printf '%s\n' "$HBA_MARK"
            printf '%s\n' 'local      all      bitscan_app,bitscan_retention,bitscan_migrate                 reject'
            printf '%s\n' 'hostnossl  all      bitscan_app,bitscan_retention,bitscan_migrate  all            reject'
            printf '%s\n' 'hostssl    bitscan  bitscan_app,bitscan_retention,bitscan_migrate  127.0.0.1/32   scram-sha-256'
            printf '%s\n' 'host       all      bitscan_app,bitscan_retention,bitscan_migrate  all            reject'
            cat "$HBA"
        } >"$tmp"
        cat "$tmp" >"$HBA"
        rm -f "$tmp"
    fi
    systemctl reload postgresql
    [ -z "$(psql_su -Atc 'SELECT line_number, error FROM pg_hba_file_rules WHERE error IS NOT NULL')" ] ||
        die "pg_hba.conf has errors"
    local role out
    for role in bitscan_app bitscan_retention bitscan_migrate; do
        out="$(psql -X -w "host=127.0.0.1 dbname=bitscan user=$role sslmode=disable" -c '' 2>&1 || true)"
        grep -q 'no encryption' <<<"$out" || die "$role: a connection without TLS was not refused"
    done
    info "connections without TLS are refused for all three roles"

    step "User and folders"
    id bitscan-manager >/dev/null 2>&1 ||
        adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin bitscan-manager >/dev/null
    install -d -o root -g root -m 0755 /var/lib/bitscan
    install -d -o root -g bitscan-manager -m 0750 /var/lib/bitscan/bits
    install -d -o bitscan-manager -g bitscan-manager -m 0750 /var/lib/bitscan/bits/uploaded
    install -d -o bitscan-manager -g bitscan-manager -m 0700 /var/lib/bitscan/audit-queue

    step "Configuration and secrets"
    install -d -o root -g root -m 0755 /etc/bitscan
    install -d -o root -g root -m 0700 "$SECRETS"
    [ -e "$ENV_FILE" ] || install -o root -g root -m 0600 /dev/null "$ENV_FILE"
    for f in app.dsn retention.dsn migrate.dsn tls.crt tls.key vault.token; do
        [ -e "$SECRETS/$f" ] || install -o root -g root -m 0600 /dev/null "$SECRETS/$f"
    done
    {
        printf 'BITSCAN_VAULT_ADDR=%s\n' "$vault_addr"
        printf 'BITSCAN_TOTP_KEY_REF=%s\n' "$key_ref"
        printf 'BITSCAN_AUDIT_SINK=%s\n' "$sink"
        if [ -n "$listen" ]; then printf 'BITSCAN_LISTEN=%s\n' "$listen"; fi
    } >"$ENV_FILE"
    info "$ENV_FILE written"
    set_role_password bitscan_app "$SECRETS/app.dsn"
    set_role_password bitscan_retention "$SECRETS/retention.dsn"
    set_role_password bitscan_migrate "$SECRETS/migrate.dsn"
    cat "$cert" >"$SECRETS/tls.crt"
    cat "$key" >"$SECRETS/tls.key"
    info "certificate and key copied; delete your working copy of $key"
    if [ -n "$vault_token" ]; then
        need_file "$vault_token" "--vault-token-file"
        sed -n '1p' "$vault_token" >"$SECRETS/vault.token"
        info "OpenBao token copied; delete $vault_token"
    fi
    need_file "$SECRETS/vault.token" "OpenBao token (pass --vault-token-file)"

    step "OpenBao token check"
    check_vault_token "$vault_addr" "$key_ref"

    step "OpenBao token renewal timer"
    cat >/usr/local/sbin/bitscan-openbao-renew <<'EOF'
#!/bin/sh
# Renews the Bitscan manager's periodic OpenBao token. The token reaches curl
# on standard input, never on the command line.
set -eu
sed -n '1s/^/X-Vault-Token: /p' "$CREDENTIALS_DIRECTORY/vault_token" |
    curl -sS --fail --proto =https -o /dev/null -H @- --data '{}' \
        "${BITSCAN_VAULT_ADDR%/}/v1/auth/token/renew-self"
EOF
    chmod 0755 /usr/local/sbin/bitscan-openbao-renew
    cat >/etc/systemd/system/bitscan-openbao-renew.service <<'EOF'
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
    cat >/etc/systemd/system/bitscan-openbao-renew.timer <<'EOF'
[Unit]
Description=Renew the Bitscan manager's OpenBao token twice a day

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
    chmod 0644 /etc/systemd/system/bitscan-openbao-renew.service /etc/systemd/system/bitscan-openbao-renew.timer
    systemctl daemon-reload
    systemctl start bitscan-openbao-renew.service
    systemctl enable --now bitscan-openbao-renew.timer >/dev/null 2>&1
    info "renewal ran once and is scheduled twice a day"

    step "Software $version"
    [ -x /opt/bitscan-manager/bin/pip ] || (umask 022 && python3.12 -m venv /opt/bitscan-manager)
    (umask 022 && /opt/bitscan-manager/bin/pip install -q --require-hashes --only-binary :all: -r "$release/$reqs")
    (umask 022 && /opt/bitscan-manager/bin/pip install -q --no-deps --no-index "$release/$wheel")
    ln -sfn /opt/bitscan-manager/bin/bitscan-manager /usr/bin/bitscan-manager
    [ -z "$(find /opt/bitscan-manager ! -type l -perm /022)" ] || die "files in /opt/bitscan-manager are group- or world-writable"
    info "installed in /opt/bitscan-manager"

    step "Units (as released, never edited)"
    for f in "${units[@]}"; do
        install -o root -g root -m 0644 "$release/$f" /etc/systemd/system/
    done
    systemctl daemon-reload
    out="$(cd /etc/systemd/system && systemd-analyze verify "${units[@]}" 2>&1 || true)"
    [ -z "$out" ] || { printf '%s\n' "$out" >&2; die "systemd-analyze verify reported problems"; }

    step "Database schema and maintenance"
    systemctl start bitscan-manager-migrate
    systemctl start bitscan-manager-maintain.service
    systemctl enable --now bitscan-manager-maintain.timer >/dev/null 2>&1
    info "migrated; maintenance ran and runs daily"

    step "Start the manager"
    systemctl enable bitscan-manager >/dev/null 2>&1
    systemctl restart bitscan-manager
    local cacert=() ready="" i addr="${listen%:*}"
    if [ -n "$ca" ]; then cacert=(--cacert "$ca"); fi
    case "$addr" in ""|0.0.0.0|"$listen") addr=127.0.0.1 ;; esac
    for i in $(seq 1 15); do
        ready="$(curl -sS "${cacert[@]}" --resolve "$name:$port:$addr" "https://$name:$port/readyz" 2>/dev/null || true)"
        [ "$ready" = '{"status":"ok"}' ] && break
        sleep 1
    done
    [ "$ready" = '{"status":"ok"}' ] ||
        die "readyz answered '${ready:-nothing}' after $i tries; see journalctl -u bitscan-manager"
    info "https://$name:$port/readyz: ok"

    step "Install checks"
    local pid caps
    pid="$(systemctl show -p MainPID --value bitscan-manager)"
    [ "$(systemctl show -p User --value bitscan-manager)" = bitscan-manager ] || die "the service does not run as bitscan-manager"
    caps="$(grep -E '^(CapEff|CapPrm|CapBnd|CapAmb):' "/proc/$pid/status" | awk '{print $2}' | sort -u)"
    [ "$caps" = 0000000000000000 ] || die "the manager has capabilities"
    grep -qE '^NoNewPrivs:\s+1' "/proc/$pid/status" || die "NoNewPrivs is not set"
    if runuser -u bitscan-manager -- cat "$SECRETS/migrate.dsn" >/dev/null 2>&1; then
        die "bitscan-manager can read migrate.dsn"
    fi
    info "runs as bitscan-manager, no capabilities, NoNewPrivs, secrets unreadable to it"

    if [ -n "$admin" ]; then
        step "First admin $admin"
        bitscan-manager users create-admin "$admin"
    fi

    step "Done"
    info "sign in at https://$name:$port/ and enrol TOTP (admins must)"
    info "then check the sink: the sign-in writes auth.login, the enrolment auth.totp_enrol"
    case "$sink" in
        syslog+tls://*) info "on the sink host: sudo grep -c '\"action\":\"auth.login\"' /var/log/bitscan-audit.log" ;;
    esac
    info "agent pin (bitscan/manager_spki_sha256): $(openssl x509 -in "$SECRETS/tls.crt" -noout -pubkey |
        openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1)"
}

# ---------------------------------------------------------------------------
# 5. agent: install and enrol bitscan-agent on this host (agent-install.md)
# ---------------------------------------------------------------------------
AGENT_CA=/etc/bitscan/ca.pem
INSTALL_ENV=/etc/bitscan/install.env

mode_agent() {
    local url="" manager_ip="" ca="" pin="" release="" token_file=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --manager-url) url="$2"; shift 2 ;;
            --manager-ip) manager_ip="$2"; shift 2 ;;
            --ca) ca="$2"; shift 2 ;;
            --pin) pin="$2"; shift 2 ;;
            --release-dir) release="$2"; shift 2 ;;
            --token-file) token_file="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: sudo $PROG agent --manager-url https://mgr.example --release-dir DIR
           [--ca manager-ca.pem] [--pin 64-HEX] [--manager-ip ADDR] [--token-file FILE]

Checks the host, makes sure the manager's name resolves (--manager-ip adds an
/etc/hosts line when it does not), installs the CA as $AGENT_CA, checks the
manager over TLS (and the pin, if given), verifies the .deb against SHA256SUMS,
then installs it through a root-only $INSTALL_ENV, which the package deletes.

The bse_ enrolment token is asked at a hidden prompt, or read from the first
line of --token-file (delete that file afterwards). Create the token in the
manager under Enrolment tokens. On a host where the agent is already installed,
the same command re-enrols it with the new token.

--manager-url without a port uses 443. --release-dir holds
bitscan-agent_<version>_amd64.deb and SHA256SUMS copied from the release page.
EOF
                return ;;
            *) die "agent: unknown option $1" ;;
        esac
    done
    need_root
    [ -n "$url" ] || die "agent: --manager-url is required"
    [ -n "$release" ] || die "agent: --release-dir is required"
    case "$url" in
        https://*) ;;
        *) die "agent: --manager-url must be https:// (the agent refuses plain HTTP)" ;;
    esac
    url="${url%/}"
    if [ -n "$pin" ] && ! [[ "$pin" =~ ^[0-9a-f]{64}$ ]]; then
        die "agent: --pin must be 64 lowercase hexadecimal characters"
    fi
    local host port
    read -r host port < <(url_host_port "$url" 443)

    step "Host checks"
    # shellcheck source=/dev/null
    . /etc/os-release
    case "${ID:-}:${VERSION_ID:-}" in
        ubuntu:22.04|ubuntu:24.04) ;;
        *) die "agent hosts must be Ubuntu 22.04 or 24.04" ;;
    esac
    [ "$(dpkg --print-architecture)" = amd64 ] || die "agent hosts must be amd64"
    [ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || die "the host must use the unified cgroup v2 hierarchy"
    timedatectl set-ntp true >/dev/null 2>&1 || info "timedatectl set-ntp failed; install systemd-timesyncd"
    timedatectl show -p NTPSynchronized --value | grep -qx yes ||
        die "clock not NTP-synced yet; wait a minute and run again"
    info "Ubuntu $VERSION_ID amd64, cgroup v2, clock synchronised"
    info "machine id $(cut -c1-8 /etc/machine-id)…: if this host is a clone, regenerate it first (agent-install.md section 1)"

    step "Tools"
    DEBIAN_FRONTEND=noninteractive apt-get update -q >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q curl ca-certificates openssl >/dev/null

    step "Manager name $host"
    local resolved
    resolved="$(getent ahostsv4 "$host" | awk 'NR == 1 {print $1}')"
    if [ -z "$resolved" ]; then
        [ -n "$manager_ip" ] || die "$host does not resolve; pass --manager-ip or add it to DNS"
        printf '%s %s\n' "$manager_ip" "$host" >>/etc/hosts
        resolved="$manager_ip"
        info "added '$manager_ip $host' to /etc/hosts"
    elif [ -n "$manager_ip" ] && [ "$resolved" != "$manager_ip" ]; then
        die "$host resolves to $resolved, not $manager_ip; fix this line: $(grep -n -w "$host" /etc/hosts || echo 'none in /etc/hosts, check DNS')"
    fi
    info "$host resolves to $resolved"

    step "Manager TLS"
    local cafile=()
    if [ -n "$ca" ]; then
        need_file "$ca" "--ca"
        openssl x509 -in "$ca" -noout >/dev/null 2>&1 || die "$ca is not a PEM certificate"
        # Under /etc, readable by all: the agent unit hides /home, /root and /tmp
        install -d -o root -g root -m 0755 /etc/bitscan
        install -o root -g root -m 0644 "$ca" "$AGENT_CA"
        cafile=(-CAfile "$AGENT_CA")
        info "CA installed as $AGENT_CA"
    fi
    local out
    out="$(openssl s_client -connect "$host:$port" -servername "$host" -verify_hostname "$host" \
        -verify_return_error -brief "${cafile[@]}" </dev/null 2>&1 || true)"
    if ! grep -q 'Verification: OK' <<<"$out"; then
        printf '%s\n' "$out" | sed -n '1,5p' >&2
        die "manager at $host:$port: TLS verification failed (wrong --ca? port $port blocked?)"
    fi
    info "manager $host:$port: TLS OK, certificate verified"
    if [ -n "$pin" ]; then
        local served
        served="$(openssl s_client -connect "$host:$port" -servername "$host" </dev/null 2>/dev/null |
            openssl x509 -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1)"
        [ "$served" = "$pin" ] || die "the manager's key does not match --pin; recompute the pin on the manager host"
        info "manager key matches the pin"
    fi
    local ready curl_ca=()
    if [ -n "$ca" ]; then curl_ca=(--cacert "$AGENT_CA"); fi
    ready="$(curl -sS "${curl_ca[@]}" "$url/readyz" 2>&1 || true)"
    [ "$ready" = '{"status":"ok"}' ] || die "manager readyz answered '$ready'"
    info "$url/readyz: ok"

    step "Package"
    [ -d "$release" ] || die "--release-dir $release is not a folder"
    local deb
    deb="$(find "$release" -maxdepth 1 -name 'bitscan-agent_*_amd64.deb' -printf '%f\n' | sort -V | tail -n 1)"
    [ -n "$deb" ] || die "no bitscan-agent_*_amd64.deb in $release"
    need_file "$release/SHA256SUMS" "SHA256SUMS copied from the release page"
    (cd "$release" && grep -E "^[0-9a-f]{64}  \*?$deb\$" SHA256SUMS | sha256sum -c --quiet -) ||
        die "$deb: checksum missing from SHA256SUMS or FAILED"
    info "$deb matches SHA256SUMS"

    step "Enrolment token"
    local token=""
    if [ -n "$token_file" ]; then
        need_file "$token_file" "--token-file"
        token="$(sed -n '1p' "$token_file")"
    else
        [ -t 0 ] || die "no terminal for the token prompt; use --token-file"
        read -rs -p "    bse_ enrolment token (hidden): " token
        echo
    fi
    token="${token//[[:space:]]/}"
    case "$token" in
        bse_?*) ;;
        *) die "the enrolment token must start with bse_" ;;
    esac

    # /etc/bitscan must be root-owned and not group/other-writable, and
    # install.env a 0600 root:root file, or the package refuses it.
    install -d -o root -g root -m 0755 /etc/bitscan
    chmod go-w /etc/bitscan
    rm -f "$INSTALL_ENV"
    install -o root -g root -m 0600 /dev/null "$INSTALL_ENV"
    local reenrol=no
    if [ -e /etc/bitscan/agent.yaml ] && dpkg-query -W -f='${Status}' bitscan-agent 2>/dev/null | grep -q 'ok installed'; then
        reenrol=yes
        # On an installed host the file may hold only the new token
        printf 'ENROL_TOKEN=%s\n' "$token" >"$INSTALL_ENV"
    else
        {
            printf 'MANAGER_URL=%s\n' "$url"
            printf 'ENROL_TOKEN=%s\n' "$token"
            if [ -n "$ca" ]; then printf 'CA_FILE=%s\n' "$AGENT_CA"; fi
            if [ -n "$pin" ]; then printf 'MANAGER_SPKI_SHA256=%s\n' "$pin"; fi
        } >"$INSTALL_ENV"
    fi
    token=""
    if [ -n "$token_file" ]; then info "token read; delete $token_file"; fi

    if [ "$reenrol" = yes ]; then
        step "Re-enrolling the installed agent"
        DEBIAN_FRONTEND=noninteractive dpkg-reconfigure bitscan-agent ||
            die "re-enrolment failed; the line starting 'bitscan-agent:' above names the cause"
    else
        step "Installing $deb"
        local deb_path
        deb_path="$(cd "$release" && pwd)/$deb"
        DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$deb_path" ||
            die "install stopped; fix the cause named in the 'bitscan-agent:' line, then: dpkg --configure bitscan-agent"
    fi
    [ ! -e "$INSTALL_ENV" ] || die "$INSTALL_ENV is still there; the package did not take it"

    step "Services"
    systemctl is-enabled -q bitscan-agent.service bitscan-runner.socket || die "the agent units are not enabled"
    systemctl is-active -q bitscan-agent.service bitscan-runner.socket || die "the agent units are not active; see journalctl -u bitscan-agent"
    local i
    for i in $(seq 1 20); do
        [ -s /var/lib/bitscan-agent/agent_id ] && break
        sleep 1
    done
    if [ -s /var/lib/bitscan-agent/agent_id ]; then
        info "enrolment request sent; agent id $(cat /var/lib/bitscan-agent/agent_id)"
    else
        info "no enrolment answer yet; see journalctl -u bitscan-agent -n 20"
    fi
    journalctl -u bitscan-agent -n 5 --no-pager -o cat | sed 's/^/    | /'

    step "Done"
    info "approve this host in the manager under Enrolment requests (unless the token has auto_approve)"
    info "after approval the first inventory arrives with the first inventory job"
}

MODE="${1:-}"
[ $# -gt 0 ] && shift
case "$MODE" in
    ca) mode_ca "$@" ;;
    openbao) mode_openbao "$@" ;;
    sink) mode_sink "$@" ;;
    manager) mode_manager "$@" ;;
    agent) mode_agent "$@" ;;
    *)
        sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
        exit 2 ;;
esac
