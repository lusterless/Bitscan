#!/bin/bash
# Bitscan sandbox suite host wrapper (G76 on bitscan-u2204/u2404, G77 on the
# GitHub hosted runners; tests/m10/test-plan.md TP-M10-20, TP-M10-21).
#
# Run as root on a THROWAWAY sandbox host only: a VM restored to `clean`, a
# hosted CI runner, or a systemd test container. It installs the .deb under
# test, stops bitscan-agent (the suite plays the agent's part), writes a test
# agent_id, and runs sandbox.py. No manager is contacted: the install uses an
# .invalid manager URL and a random enrolment token that no manager issued
# (never printed). Restore the VM to `clean` afterwards.
#
# Usage: run_vm.sh DEB OUT_DIR [--samples DIR] [--rows ID,ID] [--expect-red ID]
#                  [--label TEXT] [--with-nft] [--with-auditd]
set -euo pipefail
DEB=${1:?deb}
OUT=${2:?out dir}
shift 2
HERE=$(cd "$(dirname "$0")" && pwd -P)
ARGS=()
NFT=0
AUDITD=0
SAMPLES=0
while [ $# -gt 0 ]; do
	case "$1" in
	--with-nft) NFT=1 ;;
	--with-auditd) AUDITD=1 ;;
	--samples | --rows | --expect-red | --label)
		[ "$1" = --samples ] && SAMPLES=1
		ARGS+=("$1" "$2")
		shift
		;;
	*)
		echo "run_vm.sh: unknown argument $1" >&2
		exit 2
		;;
	esac
	shift
done
[ "$(id -u)" = 0 ] || {
	echo "run_vm.sh: run as root on a throwaway sandbox host" >&2
	exit 2
}
mkdir -p "$OUT"
export DEBIAN_FRONTEND=noninteractive
if [ "$NFT" = 1 ] || [ "$AUDITD" = 1 ] || { [ "$SAMPLES" = 1 ] && ! python3 -I -c 'import defusedxml' 2>/dev/null; }; then
	pk=()
	# CHK-M10-222 parses the .bit samples, with defusedxml only (security invariants)
	[ "$SAMPLES" = 1 ] && pk+=(python3-defusedxml)
	[ "$NFT" = 1 ] && pk+=(nftables)
	[ "$AUDITD" = 1 ] && pk+=(auditd)
	apt-get install -y --no-install-recommends "${pk[@]}" >"$OUT/apt.log" 2>&1 || {
		apt-get update >>"$OUT/apt.log" 2>&1
		apt-get install -y --no-install-recommends "${pk[@]}" >>"$OUT/apt.log" 2>&1
	}
fi

if dpkg-query -W -f '${Status}' bitscan-agent 2>/dev/null | grep -q 'install ok installed'; then
	echo "run_vm.sh: bitscan-agent is already installed; use a freshly restored host" >&2
	exit 3
fi
# Install inputs through the root-only install.env (TS 3.1); the token is
# random, never issued, and handled only through this file.
install -d -m 0755 /etc/bitscan
umask 077
{
	echo "MANAGER_URL=https://bitscan-sandbox.invalid:8443"
	printf 'ENROL_TOKEN=bse_%s\n' "$(head -c 32 /dev/urandom | base64 -w0 | tr '+/' '-_' | tr -d '=')"
} >/etc/bitscan/install.env
umask 022
apt-get install -y "$DEB" >"$OUT/install.log" 2>&1 || dpkg -i "$DEB" >>"$OUT/install.log" 2>&1
dpkg-query -W -f '${Version} ${Status}\n' bitscan-agent >"$OUT/package.txt"
grep -q 'install ok installed' "$OUT/package.txt"
# The suite sends the jobs itself: stop the agent so it never touches the
# runner or the agent_id file during the run.
systemctl stop bitscan-agent.service
install -d -m 0700 -o bitscan -g bitscan /var/lib/bitscan-agent
cat /proc/sys/kernel/random/uuid >/var/lib/bitscan-agent/agent_id
chown bitscan:bitscan /var/lib/bitscan-agent/agent_id
chmod 0644 /var/lib/bitscan-agent/agent_id

python3 -I "$HERE/sandbox.py" --out "$OUT" "${ARGS[@]}"
