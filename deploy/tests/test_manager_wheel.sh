#!/bin/bash
# Manager wheel test (M6 TP-M6-02, G47: CHK-M6-020 to CHK-M6-027; REQ-137;
# TS 8.7 L1343, L1359; #6 install half; PD-28 (b)).
#
# Usage (root, in a fresh disposable Ubuntu 24.04 host or container; network
# access to the Ubuntu archive and PyPI; the repo checked out or copied at REPO):
#   BITSCAN_TEST_DISPOSABLE=1 bash deploy/tests/test_manager_wheel.sh REPO [WHEEL_UI WHEEL_NOUI]
# Without the two wheel paths the script builds them itself:
#   - web/: npm ci --ignore-scripts && npm run build (needs Node 24 on PATH;
#     WHEEL_PREBUILT_UI=1 uses the build already in REPO/manager/bitscan_manager/webui)
#   - a build venv from manager/requirements-dev.txt (--require-hashes), then
#     pip wheel --no-deps --no-build-isolation of manager/ (REQ-137)
#   - a second wheel from a copy without the UI build (the development case)
# Then, in this host: PostgreSQL 16 + postgresql-16-debversion from the Ubuntu
# archive, the TS 5.2 Bootstrap read from the spec, a fresh Python 3.12 venv
# with manager/requirements.txt (--require-hashes --only-binary :all:) and the
# wheel (--no-deps), `db migrate` twice, and `serve` over TLS.
# It installs packages and starts PostgreSQL, so it refuses to run unless
# BITSCAN_TEST_DISPOSABLE=1.
#
# Expected values come from REQ-137 and TS 8.7, not from pyproject.toml.
# Exit: 0 all checks passed, 1 a check failed, 2 setup or usage error.
set -u
export LC_ALL=C DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
REPO=${1:-}; WHEEL=${2:-}; WHEEL_NOUI=${3:-}
[ -n "$REPO" ] && [ -d "$REPO/manager" ] || { echo "usage: $0 REPO [WHEEL_UI WHEEL_NOUI]" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "must run as root" >&2; exit 2; }
[ "${BITSCAN_TEST_DISPOSABLE:-}" = 1 ] || { echo "installs PostgreSQL and packages; set BITSCAN_TEST_DISPOSABLE=1 on a disposable host" >&2; exit 2; }
REPO=$(cd "$REPO" && pwd)
. /etc/os-release
[ "$VERSION_ID" = 24.04 ] || { echo "needs Ubuntu 24.04 (got $VERSION_ID)" >&2; exit 2; }
VERSION=0.3.0
NAME=bitscan_manager-$VERSION-py3-none-any.whl
W=$(mktemp -d "${WHEEL_WORK:-/tmp}/m6-wheel.XXXXXX")
SERVE_PID=
cleanup() { [ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null; }
trap cleanup EXIT
PASSN=0; FAILN=0
ok() { if [ "$1" = 0 ]; then PASSN=$((PASSN + 1)); echo "PASS $2"; else FAILN=$((FAILN + 1)); echo "FAIL $2"; fi; }
is() { [ "$1" = "$2" ]; ok $? "$3 (got '$1', want '$2')"; }

apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq --no-install-recommends python3.12 python3.12-venv unzip openssl curl ca-certificates \
    postgresql-16 postgresql-16-debversion >"$W/apt.log" 2>&1 || { tail -5 "$W/apt.log"; echo "apt install failed" >&2; exit 2; }

# ---------------------------------------------------------------- CHK-M6-020: build
if [ -z "$WHEEL" ]; then
    cp -r "$REPO" "$W/src"
    rm -rf "$W/src/web/node_modules"
    if [ "${WHEEL_PREBUILT_UI:-0}" = 1 ]; then
        # Node 24 is not in the Ubuntu archive: the caller ran `npm ci
        # --ignore-scripts && npm run build` on the same tree elsewhere and
        # copied its output into REPO/manager/bitscan_manager/webui.
        [ -f "$W/src/manager/bitscan_manager/webui/index.html" ]; ok $? "prebuilt UI present (npm run build output copied in)"
    else
        command -v npm >/dev/null || { echo "no npm (Node 24) on PATH for the UI build (or set WHEEL_PREBUILT_UI=1)" >&2; exit 2; }
        rm -rf "$W/src/manager/bitscan_manager/webui"
        (cd "$W/src/web" && npm ci --ignore-scripts && npm run build) >"$W/npm.log" 2>&1; ok $? "npm ci --ignore-scripts && npm run build exits 0"
    fi
    python3.12 -m venv "$W/buildenv"
    "$W/buildenv/bin/pip" install -q --require-hashes -r "$W/src/manager/requirements-dev.txt" >"$W/devlock.log" 2>&1; ok $? "build venv from the hashed dev lock"
    mkdir -p "$W/dist"
    "$W/buildenv/bin/pip" wheel -q --no-deps --no-build-isolation -w "$W/dist" "$W/src/manager" >"$W/wheel.log" 2>&1; ok $? "pip wheel --no-deps --no-build-isolation exits 0"
    is "$(ls "$W/dist")" "$NAME" "exactly one file, $NAME"
    WHEEL=$W/dist/$NAME
    BUILD_UI=$W/src/manager/bitscan_manager/webui
    cp -r "$REPO" "$W/srcnoui"; rm -rf "$W/srcnoui/manager/bitscan_manager/webui"
    mkdir -p "$W/distnoui"
    "$W/buildenv/bin/pip" wheel -q --no-deps --no-build-isolation -w "$W/distnoui" "$W/srcnoui/manager" >"$W/wheelnoui.log" 2>&1; ok $? "a wheel builds without a UI build"
    WHEEL_NOUI=$W/distnoui/$NAME
else
    BUILD_UI=$REPO/manager/bitscan_manager/webui
fi
[ -f "$WHEEL" ] && [ -d "$BUILD_UI" ] || { echo "no wheel or no UI build to compare with" >&2; exit 2; }
sha256sum "$WHEEL" | sed 's/^/wheel sha256 /'

# ---------------------------------------------------------------- CHK-M6-021, -022, -026: contents
python3.12 -I - "$WHEEL" "$BUILD_UI" "$REPO/manager/bitscan_manager/db/migrations" "$VERSION" <<'PY' >"$W/contents.txt"
import hashlib, re, sys, zipfile
from pathlib import Path
whl, ui, mig, version = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
z = zipfile.ZipFile(whl)
names = z.namelist()
def row(ok, msg): print(("PASS " if ok else "FAIL ") + msg)
ui_files = {p.relative_to(ui).as_posix() for p in ui.rglob("*") if p.is_file()}
in_wheel = {n[len("bitscan_manager/webui/"):] for n in names if n.startswith("bitscan_manager/webui/") and not n.endswith("/")}
row("index.html" in in_wheel, "wheel lists bitscan_manager/webui/index.html")
assets = {f for f in ui_files if f.startswith("assets/")}
row(bool(assets), f"the build has assets ({len(assets)})")
row(in_wheel == ui_files, f"webui/ in the wheel equals the build: {len(in_wheel)} files (missing {sorted(ui_files - in_wheel)}, extra {sorted(in_wheel - ui_files)})")
same = all(z.read("bitscan_manager/webui/" + f) == (ui / f).read_bytes() for f in ui_files & in_wheel)
row(same, "every UI file byte-identical to the build")
mig_files = {p.relative_to(mig.parent.parent.parent).as_posix() for p in mig.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
mig_wheel = {n for n in names if n.startswith("bitscan_manager/db/migrations/")}
row(mig_files and mig_files <= mig_wheel, f"every migration file of the tree is in the wheel ({len(mig_files)}; missing {sorted(mig_files - mig_wheel)})")
row(mig_wheel == mig_files, f"no extra file under db/migrations (extra {sorted(mig_wheel - mig_files)})")
bad = [n for n in names if re.search(r"(^|/)tests?/", n) or "/tests/" in n or n.startswith("tests") or "conftest" in n]
row(not bad, f"no test path in the wheel ({bad[:5]})")
row(not [n for n in names if "__pycache__" in n or n.endswith(".pyc")], "no __pycache__ or .pyc")
tops = sorted({n.split("/")[0] for n in names})
row(tops == ["bitscan_manager", f"bitscan_manager-{version}.dist-info"], f"top-level entries {tops}")
meta = z.read(f"bitscan_manager-{version}.dist-info/METADATA").decode()
row(re.search(r"^Name: bitscan-manager$", meta, re.M) is not None, "METADATA Name: bitscan-manager")
row(re.search(rf"^Version: {re.escape(version)}$", meta, re.M) is not None, f"METADATA Version: {version}")
rp = re.search(r"^Requires-Python: (.+)$", meta, re.M)
row(rp is not None and "3.12" in rp.group(1), f"Requires-Python names 3.12 ({rp.group(1) if rp else None})")
wh = z.read(f"bitscan_manager-{version}.dist-info/WHEEL").decode()
row("Tag: py3-none-any" in wh and "Root-Is-Purelib: true" in wh, "WHEEL: Tag py3-none-any, purelib")
ep = z.read(f"bitscan_manager-{version}.dist-info/entry_points.txt").decode()
row(re.search(r"^bitscan-manager = bitscan_manager\.cli:main$", ep, re.M) is not None, "entry point bitscan-manager = bitscan_manager.cli:main")
# G42 on the wheel's index.html (TS 6.3 L1140; lead ruling 2026-10-25 r1b)
html = z.read("bitscan_manager/webui/index.html").decode()
inline = [m.group(0) for m in re.finditer(r"<script\b(?![^>]*\bsrc=)[^>]*>", html, re.I)]
urls = re.findall(r"""(?:src|href)\s*=\s*["']?([^"' >]+)""", html, re.I)
ext = [u for u in urls if re.match(r"^[a-z][a-z0-9+.-]*:|^//", u, re.I)]
ev = re.findall(r"\son[a-z]+\s*=", html, re.I) + re.findall(r"\son[a-z]+(?=[\s>/])", html, re.I)
row(not inline, f"G42: no <script> without src ({inline})")
row(not re.search(r"<style\b", html, re.I), "G42: no <style>")
row(not re.search(r"\sstyle\s*=", html, re.I), "G42: no style= attribute")
row(not ext, f"G42: no URL with a scheme or // ({ext})")
row(not ev, f"G42: no on<event> attribute ({ev})")
row(not re.search(r"\ssrcdoc\b", html, re.I), "G42: no srcdoc")
row(any(u.startswith("/assets/") or u.startswith("./assets/") or u.startswith("assets/") for u in urls), f"index.html loads its bundle from assets ({urls})")
PY
while read -r verdict msg; do ok "$([ "$verdict" = PASS ] && echo 0 || echo 1)" "$msg"; done <"$W/contents.txt"
[ -s "$W/contents.txt" ] || ok 1 "content checks ran"

# ---------------------------------------------------------------- CHK-M6-023: fresh venv install
python3.12 -m venv "$W/venv"
V=$W/venv/bin
"$V/pip" install --require-hashes --only-binary :all: -r "$REPO/manager/requirements.txt" >"$W/runtime.log" 2>&1; ok $? "pip install --require-hashes --only-binary :all: -r manager/requirements.txt"
! grep -qiE "Building wheel|setup.py|\.tar\.gz" "$W/runtime.log"; ok $? "no source distribution was downloaded or built"
"$V/pip" install --no-deps "$WHEEL" >"$W/wheelinst.log" 2>&1; ok $? "pip install --no-deps <wheel>"
"$V/pip" check >"$W/pipcheck.log" 2>&1; ok $? "pip check: $(tr '\n' ' ' <"$W/pipcheck.log")"
is "$("$V/python" -c 'import importlib.metadata as m; print(m.version("bitscan-manager"))')" "$VERSION" "installed version"
loc=$("$V/python" -I -c 'import bitscan_manager, pathlib; print(pathlib.Path(bitscan_manager.__file__).parent)')
case "$loc" in "$W/venv/lib/python3.12/site-packages/bitscan_manager") ok 0 "imported from the venv ($loc)";; *) ok 1 "imported from the venv ($loc)";; esac
help=$("$V/bitscan-manager" --help 2>&1); rc=$?
is "$rc" 0 "bitscan-manager --help exits 0"
for c in serve "users" "db migrate" "db maintain"; do
    grep -qE "(^|[^a-z])$c([^a-z]|$)" <<<"$help"; ok $? "--help lists '$c'"
done

# ---------------------------------------------------------------- CHK-M6-024: migrate on a fresh database
PGV=16; PGB=/usr/lib/postgresql/$PGV/bin
pg_dropcluster --stop $PGV main >/dev/null 2>&1
# UTF8 as on a stock 24.04 host (LANG=C.UTF-8); LC_ALL=C above would give SQL_ASCII
pg_createcluster --locale C.UTF-8 $PGV main >/dev/null 2>&1 || { echo "pg_createcluster failed" >&2; exit 2; }
CONF=/etc/postgresql/$PGV/main
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=localhost" -keyout $CONF/server.key -out $CONF/server.crt >/dev/null 2>&1
chown postgres:postgres $CONF/server.key $CONF/server.crt; chmod 600 $CONF/server.key
printf '%s\n' "ssl = on" "ssl_cert_file = '$CONF/server.crt'" "ssl_key_file = '$CONF/server.key'" "listen_addresses = '127.0.0.1'" >>$CONF/postgresql.conf
printf '%s\n' "local all postgres peer" "hostssl all all 127.0.0.1/32 scram-sha-256" >$CONF/pg_hba.conf
pg_ctlcluster $PGV main start || { echo "postgres did not start" >&2; exit 2; }
"$V/python" -I - "$REPO/docs/spec/Technical_Specification.md" >"$W/bootstrap.sql" <<'PY'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
i = next(n for n, l in enumerate(lines) if l.startswith("**Bootstrap**"))
a = next(n for n in range(i + 1, len(lines)) if lines[n].strip() == "```sql")
b = next(n for n in range(a + 1, len(lines)) if lines[n].strip() == "```")
print("\n".join(lines[a + 1 : b]))
PY
grep -q '^CREATE ROLE bitscan_migrate LOGIN IN ROLE bitscan_owner;$' "$W/bootstrap.sql"; ok $? "Bootstrap read from TS 5.2 ($(wc -l <"$W/bootstrap.sql") lines)"
su postgres -c "psql -X -q -v ON_ERROR_STOP=1" <"$W/bootstrap.sql" >"$W/bootstrap.log" 2>&1; ok $? "Bootstrap runs as the superuser: $(head -c 300 "$W/bootstrap.log" | tr '
' ' ')"
PW=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
for r in bitscan_app bitscan_retention bitscan_migrate; do
    printf "ALTER ROLE %s PASSWORD '%s';\n" "$r" "$PW" | su postgres -c "psql -X -q -v ON_ERROR_STOP=1" >/dev/null || ok 1 "password for $r"
done
umask 077; mkdir -p "$W/creds"
for r in app retention migrate; do
    printf 'host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_%s password=%s sslmode=require\n' "$r" "$PW" >"$W/creds/${r}_dsn"
done
umask 022
HEAD=$(sed -n 's/^revision[^=]*= *"\([^"]*\)".*/\1/p' "$REPO"/manager/bitscan_manager/db/migrations/versions/*.py | sort | tail -1)
BITSCAN_MIGRATE_DSN_FILE=$W/creds/migrate_dsn "$V/bitscan-manager" db migrate >"$W/migrate1.log" 2>&1; ok $? "db migrate exits 0"
cur() { su postgres -c "psql -X -At -d bitscan -c 'SELECT version_num FROM alembic_version'" 2>/dev/null; }
is "$(cur)" "$HEAD" "the database is at head after migrate"
ntab=$(su postgres -c "psql -X -At -d bitscan -c \"SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner='bitscan_owner'\"")
[ "$ntab" -ge 20 ]; ok $? "tables created and owned by bitscan_owner ($ntab)"
BITSCAN_MIGRATE_DSN_FILE=$W/creds/migrate_dsn "$V/bitscan-manager" db migrate >"$W/migrate2.log" 2>&1; ok $? "a second db migrate exits 0"
is "$(cur)" "$HEAD" "head unchanged after the second migrate"
grep -q "$PW" "$W/migrate1.log" "$W/migrate2.log"; [ $? -ne 0 ]; ok $? "no password in the migrate output"

# ---------------------------------------------------------------- CHK-M6-025, -027: serve
mkdir -p "$W/pki" && cd "$W/pki" || exit 2
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 2 -subj "/CN=wheel test CA" \
    -addext basicConstraints=critical,CA:TRUE -keyout ca.key -out ca.pem >/dev/null 2>&1
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=localhost" -keyout leaf.key -out leaf.csr >/dev/null 2>&1
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' >leaf.ext
openssl x509 -req -in leaf.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 2 -extfile leaf.ext -out leaf.pem >/dev/null 2>&1
cd / || exit 2
printf 'vault-token-not-used\n' >"$W/creds/vault_token"; chmod 600 "$W/creds/vault_token"
install -d -m 0700 /var/lib/bitscan/audit-queue; mkdir -p "$W/bits/uploaded"
start_serve() { # start_serve VENV LOG -> SERVE_PID; ready on /healthz
    BITSCAN_DB_DSN_FILE=$W/creds/app_dsn BITSCAN_RETENTION_DSN_FILE=$W/creds/retention_dsn \
    BITSCAN_VAULT_ADDR=https://127.0.0.1:1 BITSCAN_TOTP_KEY_REF=bitscan-totp \
    BITSCAN_VAULT_TOKEN_FILE=$W/creds/vault_token BITSCAN_TLS_CERT_FILE=$W/pki/leaf.pem \
    BITSCAN_TLS_KEY_FILE=$W/pki/leaf.key BITSCAN_AUDIT_SINK=https://127.0.0.1:2/audit \
    BITSCAN_LISTEN=127.0.0.1:18444 BITSCAN_BITS_DIR=$W/bits \
        "$1/bitscan-manager" serve >"$2" 2>&1 &
    SERVE_PID=$!
    local i
    for i in $(seq 1 60); do
        curl -s -o /dev/null --cacert "$W/pki/ca.pem" https://localhost:18444/healthz && return 0
        kill -0 "$SERVE_PID" 2>/dev/null || return 1
        sleep 0.5
    done
    return 1
}
stop_serve() { kill "$SERVE_PID" 2>/dev/null; wait "$SERVE_PID" 2>/dev/null; SERVE_PID=; }
start_serve "$V" "$W/serve.log"; ok $? "serve from the wheel starts and answers /healthz over TLS"
curl -s -D "$W/h.txt" -o "$W/index.got" --cacert "$W/pki/ca.pem" https://localhost:18444/
is "$(sed -n '1s/\r$//p' "$W/h.txt" | cut -d' ' -f2)" 200 "GET / status"
grep -qi '^content-type: text/html' "$W/h.txt"; ok $? "GET / is text/html"
cmp -s "$W/index.got" "$BUILD_UI/index.html"; ok $? "GET / body byte-identical to the build's index.html"
for f in $(cd "$BUILD_UI" && find assets -type f | sort); do
    code=$(curl -s -o "$W/asset.got" -w '%{http_code}' --cacert "$W/pki/ca.pem" "https://localhost:18444/$f")
    [ "$code" = 200 ] && cmp -s "$W/asset.got" "$BUILD_UI/$f"; ok $? "GET /$f 200 and byte-identical (got $code)"
done
code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$W/pki/ca.pem" https://localhost:18444/assets/does-not-exist.js)
is "$code" 404 "an unknown asset is 404"
! grep -q "web ui not built" "$W/serve.log"; ok $? "serve with the UI wheel does not log 'web ui not built'"
stop_serve

if [ -n "$WHEEL_NOUI" ] && [ -f "$WHEEL_NOUI" ]; then
    python3.12 -m venv "$W/venv2"
    "$W/venv2/bin/pip" install -q --require-hashes --only-binary :all: -r "$REPO/manager/requirements.txt" >/dev/null 2>&1
    "$W/venv2/bin/pip" install -q --no-deps "$WHEEL_NOUI" >/dev/null 2>&1; ok $? "the no-UI wheel installs"
    ! unzip -l "$WHEEL_NOUI" | grep -q 'bitscan_manager/webui/'; ok $? "the no-UI wheel has no webui/ entry"
    start_serve "$W/venv2/bin" "$W/serve2.log"; ok $? "serve from the no-UI wheel starts"
    grep -q "web ui not built; serving the API only" "$W/serve2.log"; ok $? "serve logs 'web ui not built; serving the API only'"
    curl -s -D "$W/h2.txt" -o "$W/b2.txt" --cacert "$W/pki/ca.pem" https://localhost:18444/
    is "$(sed -n '1s/\r$//p' "$W/h2.txt" | cut -d' ' -f2)" 404 "GET / without a UI is 404"
    grep -qi '^content-type: application/problem+json' "$W/h2.txt"; ok $? "the 404 is problem+json"
    stop_serve
else
    echo "NOT RUN no-UI wheel checks (no WHEEL_NOUI given)"
fi
grep -q "$PW" "$W/serve.log" "$W/serve2.log" 2>/dev/null; [ $? -ne 0 ]; ok $? "no password in the serve logs"
pg_ctlcluster $PGV main stop >/dev/null 2>&1

TOTAL=$((PASSN + FAILN))
if [ "$FAILN" = 0 ]; then echo "OK $PASSN/$TOTAL checks passed"; exit 0; fi
echo "FAIL $PASSN/$TOTAL checks passed, $FAILN failed"; exit 1
