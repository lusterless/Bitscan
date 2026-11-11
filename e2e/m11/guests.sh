#!/bin/bash
# QEMU/KVM guests for the M11 nightly end to end (TP-M11-18, REQ-285; #152 (a)).
# The stand-in VM form the user accepted for G76 (decisions 2026-11-03 (4)):
# the official Ubuntu cloud images, one fresh overlay per run on a read-only
# base, destroyed afterwards. Runs as root on Linux (WSL2 or a hosted runner)
# with /dev/kvm. Never touches Hyper-V or any other VM.
#
#   guests.sh fetch IMGDIR                 download noble and jammy, checked against
#                                          the release's SHA256SUMS (prints OK lines)
#   guests.sh up NAME BASE.img PORT MEM    overlay + cloud-init seed, boot, wait for
#                                          ssh and cloud-init; NAME is the hostname
#   guests.sh ssh NAME CMD...              run CMD as `bstester` (sudo without a password)
#   guests.sh put NAME SRC DST             scp SRC to DST in the guest (keeps the mode)
#   guests.sh down NAME                    power off, delete the overlay, seed and key
#
# State lives in $GUESTS_DIR (default /root/m11e/guests, mode 0700): per guest the
# overlay, the seed ISO, the console log, the pid and the ssh port. The ssh key
# is made per guest at `up` and never leaves that folder. Network: QEMU user
# mode; the guest reaches the WSL/runner host as 10.0.2.2, and /etc/hosts in the
# guest maps $MGR_NAME (default bitscan-mgr.test) to it. Only ssh is forwarded,
# to 127.0.0.1:PORT on the host; nothing listens in the guest for anything else.
set -euo pipefail
D=${GUESTS_DIR:-/root/m11e/guests}
MGR_NAME=${MGR_NAME:-bitscan-mgr.test}
mkdir -p "$D" && chmod 0700 "$D"
cmd=${1:?command}
shift

sshopts() { # sshopts NAME
	echo -i "$D/$1/key" -p "$(cat "$D/$1/port")" -o StrictHostKeyChecking=no -o UserKnownHostsFile="$D/$1/known_hosts" \
		-o ConnectTimeout=5 -o BatchMode=yes -o LogLevel=ERROR -o ServerAliveInterval=15
}

case "$cmd" in
fetch)
	dir=${1:?image dir}
	mkdir -p "$dir"
	cd "$dir"
	for r in noble jammy; do
		f=$r-server-cloudimg-amd64.img
		curl -fsSL "https://cloud-images.ubuntu.com/$r/current/SHA256SUMS" -o "$r.SHA256SUMS"
		[ -f "$f" ] || curl -fsSLO "https://cloud-images.ubuntu.com/$r/current/$f"
		grep " \*\?$f\$" "$r.SHA256SUMS" | sed 's/ \*/  /' | sha256sum -c -
	done
	;;
up)
	name=${1:?name}
	base=${2:?base image}
	port=${3:?ssh port}
	mem=${4:-1024}
	[[ $name =~ ^[a-z0-9-]{1,40}$ ]] || { echo "bad guest name $name" >&2; exit 2; }
	[ -r /dev/kvm ] && [ -w /dev/kvm ] || { echo "no usable /dev/kvm" >&2; exit 3; }
	g="$D/$name"
	rm -rf "$g" && mkdir -m 0700 "$g"
	echo "$port" >"$g/port"
	ssh-keygen -q -t ed25519 -N '' -C "m11e-$name" -f "$g/key"
	qemu-img create -q -f qcow2 -F qcow2 -b "$(realpath "$base")" "$g/disk.qcow2" 8G
	cat >"$g/user-data" <<EOF
#cloud-config
hostname: $name
manage_etc_hosts: false
users:
  - name: bstester
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - $(cat "$g/key.pub")
ssh_pwauth: false
package_update: false
package_upgrade: false
bootcmd:
  - [sh, -c, "grep -q ' $MGR_NAME\$' /etc/hosts || echo '10.0.2.2 $MGR_NAME' >> /etc/hosts"]
EOF
	printf 'instance-id: %s-%s\nlocal-hostname: %s\n' "$name" "$(date +%s)" "$name" >"$g/meta-data"
	cloud-localds "$g/seed.iso" "$g/user-data" "$g/meta-data"
	qemu-system-x86_64 -name "$name" -machine q35,accel=kvm -cpu host -smp 2 -m "$mem" \
		-drive file="$g/disk.qcow2",if=virtio,format=qcow2 \
		-drive file="$g/seed.iso",if=virtio,format=raw,readonly=on \
		-netdev user,id=n0,hostfwd=tcp:127.0.0.1:"$port"-:22 -device virtio-net-pci,netdev=n0 \
		-display none -serial file:"$g/console.log" -daemonize -pidfile "$g/pid"
	t0=$(date +%s)
	# shellcheck disable=SC2046
	until ssh $(sshopts "$name") bstester@127.0.0.1 'cloud-init status --wait >/dev/null 2>&1; cloud-init status' 2>/dev/null | grep -q 'status: done'; do
		if [ $(($(date +%s) - t0)) -gt 600 ]; then
			echo "$name: no ssh or cloud-init not done within 600 s; console tail:" >&2
			tail -n 20 "$g/console.log" >&2
			exit 4
		fi
		sleep 5
	done
	echo "$name up in $(($(date +%s) - t0)) s"
	;;
ssh)
	name=${1:?name}
	shift
	# shellcheck disable=SC2046
	exec ssh $(sshopts "$name") bstester@127.0.0.1 "$@"
	;;
put)
	name=${1:?name}
	# shellcheck disable=SC2046
	exec scp -q -p $(sshopts "$name" | sed 's/-p /-P /') "${2:?src}" bstester@127.0.0.1:"${3:?dst}"
	;;
down)
	name=${1:?name}
	g="$D/$name"
	if [ -f "$g/pid" ]; then
		pid=$(cat "$g/pid") # QEMU removes its pidfile when it exits
		kill "$pid" 2>/dev/null || true
		for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
		kill -9 "$pid" 2>/dev/null || true
	fi
	rm -rf "$g"
	echo "$name down"
	;;
*)
	echo "unknown command $cmd" >&2
	exit 2
	;;
esac
