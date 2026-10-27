#!/bin/bash
# M6 Wave 0 network check (TP-M6-01, CHK-M6-001 to -012; work/plans/M6-e2e.md
# section 2 as adapted by the environment ruling, decisions 2026-10-26).
# Runs in Git Bash on Windows: PowerShell for Hyper-V, Windows ssh/scp for the
# VMs (WSL has no route to them), wsl.exe for the listeners (netcheck_wsl.sh).
#
# Usage: bash e2e/m6/netcheck.sh OUTDIR host            CHK-M6-001 (read only)
#        bash e2e/m6/netcheck.sh OUTDIR vm NAME MAC NONCE
#                                                       CHK-M6-002..011 for one VM
# One VM at a time (host memory). Prerequisite: netcheck_wsl.sh DIR ca.
# Rows go to OUTDIR/rows.tsv (check, vm, PASS|FAIL|INFO, evidence).
# Never changes firewall, portproxy, WSL or any admin setting; no tunnels.
set -u
export MSYS_NO_PATHCONV=1 LC_ALL=C
OUT=${1:?outdir}; MODE=${2:?mode}
mkdir -p "$OUT"
KEY=/c/Users/kaiquan.koh/BitscanVMs/ssh/bitscan_vm
KH="$OUT/known_hosts"
WDIR=/root/m6t/netcheck
WSLN=/mnt/c/Users/kaiquan.koh/Documents/Bitscan-m6/e2e/m6/netcheck_wsl.sh
ROWS="$OUT/rows.tsv"
LOG="$OUT/netcheck.log"
ps() { powershell.exe -NoProfile -NonInteractive -Command "$1" | tr -d '\r'; }
wsl() { wsl.exe -d Ubuntu-24.04 -u root -- bash "$WSLN" "$WDIR" "$@" 2>&1 | tr -d '\r'; }
row() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" | tee -a "$ROWS"; }
log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" >> "$LOG"; }

if [ "$MODE" = host ]; then
    sw=$(ps "(Get-NetIPAddress -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4).IPAddress + '/' + (Get-NetIPAddress -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4).PrefixLength")
    pp=$(netsh.exe interface portproxy show v4tov4 | tr -d '\r' | awk '$1=="172.31.0.1" && $2=="8443" {print $3":"$4}')
    log "switch=$sw portproxy=$pp"
    if [ "$sw" = "172.31.0.1/20" ] && [ "$pp" = "127.0.0.1:18443" ]; then
        row CHK-M6-001 host PASS "Default Switch $sw; portproxy 172.31.0.1:8443 -> $pp"
    else
        row CHK-M6-001 host FAIL "Default Switch '$sw'; portproxy '$pp' (expected 172.31.0.1/20 and 127.0.0.1:18443)"; exit 1
    fi
    exit 0
fi

[ "$MODE" = vm ] || { echo "unknown mode" >&2; exit 2; }
NAME=${3:?name}; MAC=${4:?mac}; NONCE=${5:?nonce}
SSHO=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KH" -o ConnectTimeout=8 -o BatchMode=yes -o LogLevel=ERROR)
vssh() { ssh "${SSHO[@]}" "bstester@$IP" "$@"; }

# CHK-M6-002: restore clean, start, IP from the static MAC
# NETCHECK_STARTED=1: the VM was restored to clean and started by hand just
# before (for example after a Start-VM memory failure); do not restore again.
if [ "${NETCHECK_STARTED:-0}" != 1 ]; then
    ps "Restore-VMSnapshot -VMName $NAME -Name clean -Confirm:\$false; Start-VM $NAME" >> "$LOG" 2>&1
fi
st=$(ps "(Get-VM $NAME).State")
if [ "$st" != Running ]; then
    row CHK-M6-002 "$NAME" FAIL "VM not running after Start-VM (state $st; see $LOG, e.g. host memory)"; exit 1
fi
t0=$(date +%s); IP=
while [ $(( $(date +%s) - t0 )) -lt 240 ] && [ -z "$IP" ]; do
    sleep 5
    cands=$(ps "Get-NetNeighbor -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4 | Where-Object LinkLayerAddress -eq '$MAC' | ForEach-Object IPAddress")
    for c in $cands; do
        if ssh "${SSHO[@]}" -o ConnectTimeout=4 "bstester@$c" true 2>/dev/null; then IP=$c; break; fi
    done
done
if [ -z "$IP" ]; then row CHK-M6-002 "$NAME" FAIL "no SSH-reachable IP for MAC $MAC within 240 s (candidates: ${cands:-none})"; exit 1; fi
row CHK-M6-002 "$NAME" PASS "restored clean, started; IP $IP (MAC $MAC, by Get-NetNeighbor + SSH probe) after $(( $(date +%s) - t0 )) s"

# CHK-M6-003: tester -> VM, cloud-init, cgroup v2, clock, release, no Bitscan package
info=$(vssh 'cloud-init status --wait >/dev/null 2>&1; cloud-init status | tr "\n" " "; echo "|$(stat -fc %T /sys/fs/cgroup)"; for i in $(seq 1 24); do s=$(timedatectl show -p NTPSynchronized --value); [ "$s" = yes ] && break; sleep 5; done; echo "|ntp=$s"; . /etc/os-release; echo "|$PRETTY_NAME"; echo "|pkgs=$(dpkg-query -W -f "\${Package} " "bitscan*" 2>/dev/null)"; echo "|$(uname -r)"' 2>&1 | tr -d '\n')
log "003 $info"
case "$info" in
    *"status: done"*"|cgroup2fs|ntp=yes|Ubuntu "*"|pkgs=|"*) row CHK-M6-003 "$NAME" PASS "ssh (Git Bash) OK: $info" ;;
    *) row CHK-M6-003 "$NAME" FAIL "$info" ;;
esac
# diagnostic: Windows ssh.exe through WSL interop (used by the W4 harness)
iop=$(wsl.exe -d Ubuntu-24.04 -u root -- /mnt/c/Windows/System32/OpenSSH/ssh.exe -i C:/Users/kaiquan.koh/BitscanVMs/ssh/bitscan_vm \
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=C:/Users/kaiquan.koh/Documents/m6-tester-scratch/known_hosts_interop \
    -o BatchMode=yes -o ConnectTimeout=8 "bstester@$IP" hostname 2>&1 | tr -d '\r')
row CHK-M6-003 "$NAME" INFO "ssh.exe via WSL interop: '$iop'"

# CHK-M6-004: scp 10 MB, SHA-256 on both ends
f="$OUT/blob-$NAME.bin"; head -c 10485760 /dev/urandom > "$f"; h1=$(sha256sum "$f" | cut -c1-64)
if scp "${SSHO[@]}" -q "$f" "bstester@$IP:/tmp/m6-blob.bin"; then
    h2=$(vssh 'sha256sum /tmp/m6-blob.bin; rm -f /tmp/m6-blob.bin' | cut -c1-64)
    [ "$h1" = "$h2" ] && row CHK-M6-004 "$NAME" PASS "10485760 bytes, sha256 $h1 on both ends" || row CHK-M6-004 "$NAME" FAIL "local $h1 remote $h2"
else row CHK-M6-004 "$NAME" FAIL "scp failed"; fi
rm -f "$f"

# CHK-M6-005: /etc/hosts and the test CA (outside /etc/bitscan)
wsl.exe -d Ubuntu-24.04 -u root -- cat "$WDIR/ca.pem" | tr -d '\r' > "$OUT/ca.pem"
scp "${SSHO[@]}" -q "$OUT/ca.pem" "bstester@$IP:/tmp/m6-ca.pem"
h=$(vssh 'echo "172.31.0.1 bitscan-mgr.test" | sudo tee -a /etc/hosts >/dev/null; sudo install -d -m 0755 /etc/bitscan-netcheck; sudo install -m 0644 /tmp/m6-ca.pem /etc/bitscan-netcheck/ca.pem; rm -f /tmp/m6-ca.pem; getent hosts bitscan-mgr.test; sha256sum /etc/bitscan-netcheck/ca.pem | cut -c1-16' | tr '\n' ' ')
case "$h" in "172.31.0.1 "*bitscan-mgr.test*) row CHK-M6-005 "$NAME" PASS "getent: $h" ;; *) row CHK-M6-005 "$NAME" FAIL "$h" ;; esac

probe() { # $1 = listener letter; GET by name and by IP; prints evidence
    local by_name by_ip rc1 rc2
    by_name=$(vssh 'curl -sS --max-time 10 --cacert /etc/bitscan-netcheck/ca.pem https://bitscan-mgr.test:8443/ 2>&1; echo "rc=$?"' | tr '\n' ' ')
    by_ip=$(vssh 'curl -sS --max-time 10 --cacert /etc/bitscan-netcheck/ca.pem https://172.31.0.1:8443/ 2>&1; echo "rc=$?"' | tr '\n' ' ')
    echo "name: $by_name| ip: $by_ip"
    case "$by_name" in "bitscan-netcheck $NONCE $1 rc=0"*) ;; *) return 1 ;; esac
    case "$by_ip" in "bitscan-netcheck $NONCE $1 rc=0"*) ;; *) return 1 ;; esac
}

# CHK-M6-007: listener A in WSL on 127.0.0.1:18443
log "start-a: $(wsl start-a "$NONCE")"
if ev=$(probe A); then row CHK-M6-007 "$NAME" PASS "listener A (WSL 127.0.0.1:18443 via portproxy): $ev"
else row CHK-M6-007 "$NAME" FAIL "listener A: $ev"; fi
# CHK-M6-010: without the test CA the handshake must fail verification
neg=$(vssh 'curl -sS --max-time 10 https://bitscan-mgr.test:8443/ 2>&1 | head -1; echo "rc=${PIPESTATUS[0]}"' | tr '\n' ' ')
case "$neg" in *"rc=60"*) row CHK-M6-010 "$NAME" PASS "system CA store only: $neg" ;; *) row CHK-M6-010 "$NAME" FAIL "$neg" ;; esac
log "stop-a: $(wsl stop-a)"

# CHK-M6-008: listener B in a container, -p 127.0.0.1:18443:8443
log "start-b: $(wsl start-b "$NONCE")"
if ev=$(probe B); then row CHK-M6-008 "$NAME" PASS "listener B (container, -p 127.0.0.1:18443:8443): $ev"
else row CHK-M6-008 "$NAME" FAIL "listener B: $ev"; fi
log "stop-b: $(wsl stop-b)"
log "listener access lines: $(wsl logs | tr '\n' ';')"

# CHK-M6-009: control port 8444 (diagnostic)
ctl=$(vssh 's=$(date +%s.%N); timeout 8 bash -c "exec 3<>/dev/tcp/bitscan-mgr.test/8444" 2>&1; rc=$?; e=$(date +%s.%N); echo "rc=$rc after $(echo "$e - $s" | bc 2>/dev/null || echo ?) s"' | tr '\n' ' ')
case "$ctl" in *"rc=124"*) k=timeout ;; *refused*) k=refused ;; *) k=other ;; esac
row CHK-M6-009 "$NAME" INFO "8444 control: $k ($ctl)"

# CHK-M6-011: the Ubuntu archive
apt=$(vssh 'sudo apt-get update -q >/tmp/apt.log 2>&1; rc=$?; grep -E "^(Hit|Get):" /tmp/apt.log | head -2 | tr "\n" " "; tail -1 /tmp/apt.log; echo "rc=$rc"' | tr '\n' ' ')
case "$apt" in *"rc=0"*) row CHK-M6-011 "$NAME" PASS "apt-get update: $apt" ;; *) row CHK-M6-011 "$NAME" FAIL "$apt" ;; esac

# CHK-M6-012: clean up and shut down (the next session restores clean again)
vssh 'sudo rm -rf /etc/bitscan-netcheck; sudo sed -i "/ bitscan-mgr.test$/d" /etc/hosts' >/dev/null 2>&1
ps "Stop-VM $NAME" >> "$LOG" 2>&1
st=$(ps "(Get-VM $NAME).State")
row CHK-M6-012 "$NAME" "$([ "$st" = Off ] && echo PASS || echo FAIL)" "VM state after Stop-VM: $st; /etc/bitscan-netcheck removed"
