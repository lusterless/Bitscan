#!/bin/bash
# Hyper-V VM helper for the M6 end-to-end run (TP-M6-10..13; work/plans/M6-e2e.md
# section 4, environment ruling decisions 2026-10-26). Runs in Git Bash on
# Windows: PowerShell for Hyper-V, Windows ssh/scp for the VMs (WSL has no
# route to them). Never changes firewall, portproxy, WSL or any admin setting.
#
#   vm.sh mem                      Windows free physical memory in MB
#   vm.sh switch                   the Default Switch address (e2e_vms.py checks it against its MGR_IP setting)
#   vm.sh restore NAME             restore the clean checkpoint (VM off)
#   vm.sh start NAME MAC           start, then print the SSH-reachable IP (by MAC)
#   vm.sh stop NAME                clean shutdown; prints the state
#   vm.sh ssh IP CMD...            run CMD as bstester (sudo NOPASSWD)
#   vm.sh put IP SRC DST           scp SRC to DST on the VM
#   vm.sh hosts IP MGRIP           map bitscan-mgr.test -> MGRIP in /etc/hosts (MGRIP: the caller's
#                                  setting, the Default Switch address; it moved at a host reboot)
# Known hosts go to $VM_KH (default: the tester scratch folder), never ~/.ssh.
set -u
export MSYS_NO_PATHCONV=1 LC_ALL=C
KEY=/c/Users/kaiquan.koh/BitscanVMs/ssh/bitscan_vm
KH=${VM_KH:-/c/Users/kaiquan.koh/Documents/m6-tester-scratch/known_hosts_e2e}
SSHO=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KH" -o ConnectTimeout=8 -o BatchMode=yes -o LogLevel=ERROR -o ServerAliveInterval=15)
ps() { powershell.exe -NoProfile -NonInteractive -Command "$1" | tr -d '\r'; }
cmd=${1:?command}; shift
case "$cmd" in
mem) ps '[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)' ;;
switch) ps "\$a=Get-NetIPAddress -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4; \$a.IPAddress + '/' + \$a.PrefixLength" ;;
restore)
    ps "Stop-VM ${1:?name} -TurnOff -Force -ErrorAction SilentlyContinue; Restore-VMSnapshot -VMName $1 -Name clean -Confirm:\$false; (Get-VM $1).State" ;;
start)
    name=${1:?name}; mac=${2:?mac}
    ps "Start-VM $name -ErrorAction Stop" >/dev/null 2>&1 || { echo "start failed: $(ps "Start-VM $name" 2>&1 | head -2 | tr '\n' ' ')" >&2; exit 1; }
    t0=$(date +%s)
    while [ $(( $(date +%s) - t0 )) -lt 300 ]; do
        sleep 5
        for c in $(ps "Get-NetNeighbor -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4 | Where-Object LinkLayerAddress -eq '$mac' | ForEach-Object IPAddress"); do
            if ssh "${SSHO[@]}" -o ConnectTimeout=4 "bstester@$c" 'cloud-init status --wait >/dev/null 2>&1; true' 2>/dev/null; then echo "$c"; exit 0; fi
        done
    done
    echo "no SSH-reachable IP for $mac within 300 s" >&2; exit 1 ;;
stop) ps "Stop-VM ${1:?name}; (Get-VM $1).State" ;;
ssh) ip=${1:?ip}; shift; ssh "${SSHO[@]}" "bstester@$ip" "$@" ;;
put) scp "${SSHO[@]}" -q "${2:?src}" "bstester@${1:?ip}:${3:?dst}" ;;
hosts) mip=${2:?manager ip}; [[ $mip =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "bad manager ip $mip" >&2; exit 2; }
    ssh "${SSHO[@]}" "bstester@${1:?ip}" "sudo sed -i '/ bitscan-mgr.test\$/d' /etc/hosts; echo '$mip bitscan-mgr.test' | sudo tee -a /etc/hosts >/dev/null; getent hosts bitscan-mgr.test" ;;
*) echo "unknown command $cmd" >&2; exit 2 ;;
esac
