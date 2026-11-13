#!/usr/bin/env bash
# One-time upgrade of an installed manager to a new web UI build, without a
# release. The UI ships inside the manager wheel (bitscan_manager/webui/), and
# the manager reads it into memory at start, so this rebuilds the wheel,
# reinstalls it and restarts the manager. Two modes, in order:
#
#   1. build    (dev machine, Git Bash)  npm ci, lint, typecheck, vite build,
#                                        pip wheel, check the wheel, SHA-256
#   2. install  (manager host, root)     check the wheel, back up the installed
#                                        package, reinstall, restart, check
#                                        /readyz and that / serves the new UI
#
# UI-only: install refuses a wheel whose migrations or dependencies differ
# from the installed ones; use manager-operations.md section 1 for those.
# On a failed check after the reinstall it restores the backup and restarts.
#
# Usage: upgrade-webui.sh <mode> [options]; upgrade-webui.sh <mode> --help

set -euo pipefail
umask 077

PROG="${0##*/}"
step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }
need_file() { [ -s "$1" ] || die "$2: $1 is missing or empty"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed"; }

VENV=/opt/bitscan-manager
ENV_FILE=/etc/bitscan/manager.env
BACKUPS=/var/backups

# ---------------------------------------------------------------------------
# 1. build: the UI and the wheel (dev machine)
# ---------------------------------------------------------------------------
mode_build() {
    local out=dist
    while [ $# -gt 0 ]; do
        case "$1" in
            --out) out="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: $PROG build [--out DIR]
Builds web/ into manager/bitscan_manager/webui/, then the manager wheel into
DIR (default dist, relative to the repository root), and writes
DIR/<wheel>.sha256. Copy both files to the manager host.
EOF
                return ;;
            *) die "build: unknown option $1" ;;
        esac
    done
    local root py wheel
    root="$(cd "$(dirname "$0")/../.." && pwd)"
    cd "$root"
    need_cmd npm
    need_cmd sha256sum
    case "$(node --version 2>/dev/null)" in v24.*) ;; *) die "Node 24 is required (web/package.json engines)" ;; esac
    if [ -x manager/.venv/Scripts/python.exe ]; then py=manager/.venv/Scripts/python.exe
    elif [ -x manager/.venv/bin/python ]; then py=manager/.venv/bin/python
    else die "no venv at manager/.venv"; fi

    step "Web UI"
    (cd web && npm ci --ignore-scripts && npm run lint && npm run typecheck && npm run build)
    need_file manager/bitscan_manager/webui/index.html "UI build"
    info "built into manager/bitscan_manager/webui/"

    step "Wheel"
    mkdir -p "$out"
    out="$(cd "$out" && pwd)"
    rm -f "$out"/bitscan_manager-*-py3-none-any.whl "$out"/bitscan_manager-*-py3-none-any.whl.sha256
    # hatchling is the build backend (manager/pyproject.toml), installed in the
    # venv from the hashed dev lock; the venv may have no pip (uv).
    (cd manager && "$root/$py" -m hatchling build -t wheel -d "$out" >/dev/null)
    wheel="$(cd "$out" && ls bitscan_manager-*-py3-none-any.whl)"
    "$py" -I - "$out/$wheel" <<'EOF'
import sys
import zipfile

names = zipfile.ZipFile(sys.argv[1]).namelist()
if "bitscan_manager/webui/index.html" not in names:
    sys.exit("wheel without the UI: no bitscan_manager/webui/index.html")
if not any(n.startswith("bitscan_manager/webui/assets/") and not n.endswith("/") for n in names):
    sys.exit("wheel without the UI: no file under bitscan_manager/webui/assets/")
EOF
    (cd "$out" && sha256sum "$wheel" >"$wheel.sha256")
    info "$out/$wheel"
    info "$out/$wheel.sha256"

    if [ -n "$(git status --porcelain -- web manager 2>/dev/null)" ]; then
        info "note: built from uncommitted changes in web/ or manager/"
    fi
    info "next: copy both files to the manager host, then"
    info "  sudo ./$PROG install --wheel $wheel --name <manager DNS name> [--ca manager-ca.pem]"
}

# ---------------------------------------------------------------------------
# 2. install: reinstall the wheel on the manager host (root)
# ---------------------------------------------------------------------------
PKG="" SITE="" BACKUP=""

rollback() {
    printf '%s: %s; restoring %s\n' "$PROG" "$1" "$BACKUP" >&2
    systemctl stop bitscan-manager || true
    rm -rf "$PKG" "$SITE"/bitscan_manager-*.dist-info
    tar -xzf "$BACKUP" -C "$SITE"
    systemctl start bitscan-manager || true
    die "rolled back to the previous package; see journalctl -u bitscan-manager"
}

mode_install() {
    local wheel="" name="" ca=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --wheel) wheel="$2"; shift 2 ;;
            --name) name="$2"; shift 2 ;;
            --ca) ca="$2"; shift 2 ;;
            -h|--help)
                cat <<EOF
Usage: sudo $PROG install --wheel bitscan_manager-X-py3-none-any.whl --name mgr.example [--ca manager-ca.pem]
<wheel>.sha256 from the build mode must sit next to the wheel. --name is the
DNS name in the manager's certificate; --ca is the CA that signed it, for the
checks (leave it out for a public CA).
EOF
                return ;;
            *) die "install: unknown option $1" ;;
        esac
    done
    [ "$(id -u)" -eq 0 ] || die "run this mode as root (sudo $0 install ...)"
    [ -n "$wheel" ] || die "install: --wheel is required"
    [ -n "$name" ] || die "install: --name is required"
    need_file "$wheel" "wheel"
    need_file "$wheel.sha256" "checksum from the build mode"
    [ -x "$VENV/bin/pip" ] || die "no manager venv at $VENV"
    need_cmd curl

    step "Wheel checks"
    (cd "$(dirname "$wheel")" && sha256sum -c --quiet "$(basename "$wheel").sha256") || die "$wheel: checksum FAILED"
    info "checksum OK"
    PKG="$("$VENV/bin/python" -I -c 'import importlib.util as u; print(u.find_spec("bitscan_manager").submodule_search_locations[0])')"
    SITE="$(dirname "$PKG")"
    local expected
    # UI-only: the migrations and dependencies must match what is installed,
    # so no migration runs and the backup can be restored safely.
    expected="$("$VENV/bin/python" -I - "$wheel" "$PKG" <<'EOF'
import hashlib
import os
import sys
import zipfile
from importlib.metadata import distribution

wheel, pkg = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(wheel)
names = z.namelist()
if "bitscan_manager/webui/index.html" not in names:
    sys.exit("wheel without the UI: no bitscan_manager/webui/index.html")
if not any(n.startswith("bitscan_manager/webui/assets/") and not n.endswith("/") for n in names):
    sys.exit("wheel without the UI: no file under bitscan_manager/webui/assets/")

prefix = "bitscan_manager/"
new = {
    n[len(prefix):]: hashlib.sha256(z.read(n)).hexdigest()
    for n in names
    if n.startswith(prefix + "db/migrations/") and n.endswith(".py")
}
old = {}
for d, _, files in os.walk(os.path.join(pkg, "db", "migrations")):
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                old[os.path.relpath(p, pkg).replace(os.sep, "/")] = hashlib.sha256(fh.read()).hexdigest()
if new != old:
    changed = sorted(set(new) ^ set(old) | {k for k in new.keys() & old.keys() if new[k] != old[k]})
    sys.exit("migrations differ from the installed ones (" + ", ".join(changed)
             + "); use the full upgrade in manager-operations.md section 1")


def requires(text):
    return sorted(
        line for line in text.splitlines()
        if line.startswith("Requires-Dist:") and "extra ==" not in line
    )


meta = next(n for n in names if n.endswith(".dist-info/METADATA"))
if requires(z.read(meta).decode()) != requires(distribution("bitscan-manager").read_text("METADATA") or ""):
    sys.exit("dependencies differ from the installed ones; use the full upgrade in manager-operations.md section 1")

print(hashlib.sha256(z.read("bitscan_manager/webui/index.html")).hexdigest())
EOF
)" || die "wheel checks failed"
    info "migrations and dependencies unchanged; UI present"

    local listen addr port
    listen="$(sed -n 's/^BITSCAN_LISTEN=//p' "$ENV_FILE" 2>/dev/null | tail -n 1)"
    addr="${listen%:*}"
    port="${listen##*:}"
    port="${port:-8443}"
    case "$addr" in ""|0.0.0.0|"$listen") addr=127.0.0.1 ;; esac
    local curl_opts=(-sS --resolve "$name:$port:$addr")
    if [ -n "$ca" ]; then need_file "$ca" "CA certificate"; curl_opts+=(--cacert "$ca"); fi

    step "Backup"
    BACKUP="$BACKUPS/bitscan-manager-$(date -u +%Y%m%dT%H%M%SZ).tgz"
    (cd "$SITE" && tar -czf "$BACKUP" bitscan_manager bitscan_manager-*.dist-info)
    info "$BACKUP"

    step "Reinstall"
    systemctl stop bitscan-manager
    (umask 022 && "$VENV/bin/pip" install -q --no-deps --no-index --force-reinstall "$wheel") || rollback "pip install failed"
    "$VENV/bin/pip" check >/dev/null || rollback "pip check failed"
    [ -z "$(find "$VENV" ! -type l -perm /022)" ] || rollback "files in $VENV are writable by group or others"
    info "installed $(basename "$wheel")"

    step "Start and check"
    systemctl start bitscan-manager || rollback "bitscan-manager did not start"
    local ready="" i served
    for i in $(seq 1 15); do
        ready="$(curl "${curl_opts[@]}" "https://$name:$port/readyz" 2>/dev/null || true)"
        [ "$ready" = '{"status":"ok"}' ] && break
        sleep 1
    done
    [ "$ready" = '{"status":"ok"}' ] || rollback "readyz answered '${ready:-nothing}' after $i tries"
    info "https://$name:$port/readyz: ok"
    served="$(curl "${curl_opts[@]}" "https://$name:$port/" 2>/dev/null | sha256sum | cut -d' ' -f1)"
    [ "$served" = "$expected" ] || rollback "/ does not serve the new index.html"
    info "https://$name:$port/ serves the new UI; hard-refresh open browsers (Ctrl+F5)"
    info "backup kept at $BACKUP; delete it once the new UI is confirmed"
}

MODE="${1:-}"
[ $# -gt 0 ] && shift
case "$MODE" in
    build) mode_build "$@" ;;
    install) mode_install "$@" ;;
    *) die "usage: $PROG build|install [options]; $PROG <mode> --help" ;;
esac

