#!/bin/bash
# WSL half of the M6 Wave 0 network check (TP-M6-01). Called by
# e2e/m6/netcheck.sh through wsl.exe; runs as root in the Ubuntu-24.04 distro.
#
# Usage: bash netcheck_wsl.sh DIR {ca|start-a|stop-a|start-b|stop-b|local|logs|clean} [NONCE]
#   DIR      working folder (created; never inside the repo), e.g. /root/m6t/netcheck
#   ca       a test CA and a leaf with SAN DNS:bitscan-mgr.test, IP:172.31.0.1
#   start-a  listener A: TLS on 127.0.0.1:18443 in this distro (transient unit)
#   start-b  listener B: the same listener in a container, -p 127.0.0.1:18443:8443
#   local    GET through 127.0.0.1:18443 from this distro (name check via --resolve)
#   logs     the listeners' access lines
#   clean    stop both listeners and remove DIR
# Environment ruling 2026-10-26: nothing here binds 8443 (the Windows
# portproxy 172.31.0.1:8443 -> 127.0.0.1:18443 holds it).
set -u
export LC_ALL=C
DIR=${1:?dir}; CMD=${2:?cmd}; NONCE=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
IMG=m4b-sysd-u24
case "$DIR" in /root/m6t/*) ;; *) echo "DIR must be under /root/m6t" >&2; exit 2 ;; esac

wait_port() { # $1 = want (up|down)
    for _ in $(seq 1 50); do
        if ss -ltnH 'sport = :18443' | grep -q .; then [ "$1" = up ] && return 0
        else [ "$1" = down ] && return 0; fi
        sleep 0.2
    done
    return 1
}

case "$CMD" in
ca)
    mkdir -p "$DIR" && cd "$DIR" || exit 2
    umask 077
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
        -keyout ca.key -out ca.pem -days 7 -subj "/CN=Bitscan M6 netcheck test CA" \
        -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign 2>/dev/null || exit 1
    openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
        -keyout leaf.key -out leaf.csr -subj "/CN=bitscan-mgr.test" 2>/dev/null || exit 1
    printf '%s\n' "subjectAltName=DNS:bitscan-mgr.test,IP:172.31.0.1" "basicConstraints=critical,CA:FALSE" \
        "keyUsage=critical,digitalSignature" "extendedKeyUsage=serverAuth" > leaf.ext
    openssl x509 -req -in leaf.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out leaf.pem \
        -days 7 -extfile leaf.ext 2>/dev/null || exit 1
    chmod 644 ca.pem leaf.pem; chmod 640 leaf.key; chgrp 0 leaf.key
    cp "$HERE/tls_listener.py" "$DIR/tls_listener.py"
    openssl x509 -in leaf.pem -noout -ext subjectAltName | tr -d '\n' ; echo
    openssl verify -CAfile ca.pem leaf.pem
    sha256sum ca.pem leaf.pem
    ;;
start-a)
    [ -n "$NONCE" ] || exit 2
    ss -ltnH 'sport = :8443' | grep -q . && { echo "something listens on 8443 in WSL" >&2; exit 1; }
    systemd-run --quiet --unit=m6-netcheck-a --collect python3 -I "$DIR/tls_listener.py" --bind 127.0.0.1 --port 18443 \
        --cert "$DIR/leaf.pem" --key "$DIR/leaf.key" --body "bitscan-netcheck $NONCE A" || exit 1
    wait_port up || { journalctl -u m6-netcheck-a --no-pager | tail -5; exit 1; }
    ss -ltnpH 'sport = :18443'
    ;;
stop-a)
    systemctl stop m6-netcheck-a 2>/dev/null; wait_port down; echo "a stopped" ;;
start-b)
    [ -n "$NONCE" ] || exit 2
    docker run -d --rm --name m6-netcheck-b -p 127.0.0.1:18443:8443 -v "$DIR:/nc:ro" --entrypoint python3 "$IMG" \
        -I /nc/tls_listener.py --bind 0.0.0.0 --port 8443 --cert /nc/leaf.pem --key /nc/leaf.key \
        --body "bitscan-netcheck $NONCE B" >/dev/null || exit 1
    for _ in $(seq 1 50); do docker logs m6-netcheck-b 2>&1 | grep -q listening && break; sleep 0.2; done
    wait_port up || exit 1
    docker port m6-netcheck-b; ss -ltnpH 'sport = :18443'
    ;;
stop-b)
    docker logs m6-netcheck-b > "$DIR/listener-b.log" 2>&1
    docker rm -f m6-netcheck-b >/dev/null 2>&1; wait_port down; echo "b stopped" ;;
local)
    curl -sS --max-time 10 --cacert "$DIR/ca.pem" --resolve bitscan-mgr.test:18443:127.0.0.1 https://bitscan-mgr.test:18443/ ;;
logs)
    journalctl -u m6-netcheck-a --no-pager -o cat 2>/dev/null | grep netcheck; cat "$DIR/listener-b.log" 2>/dev/null ;;
clean)
    systemctl stop m6-netcheck-a 2>/dev/null; docker rm -f m6-netcheck-b >/dev/null 2>&1
    wait_port down; rm -rf "$DIR"; echo cleaned ;;
*) echo "unknown command" >&2; exit 2 ;;
esac
