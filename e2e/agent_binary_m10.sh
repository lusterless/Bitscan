#!/bin/bash
# Binary-level M10 walk of bitscan-agent (tests/m10/test-plan.md TP-M10-19,
# CHK-M10-182 to -185; TASK-227 TEST, TASK-212/220/223 r1 rows; tester-m10c).
#
# Like e2e/agent_binary.sh (M4): runs as root in WSL, each scenario in a
# private mount namespace with overlayfs on /etc and /var/lib and tmpfs on
# /tmp and /run, so nothing on the host changes. The manager is
# e2e/fake_manager_m10.py on 127.0.0.1 (test CA in ca_file); the runner is
# e2e/fake_runner_m10.py on /run/bitscan/runner.sock inside the namespace.
# Usage: agent_binary_m10.sh <repo> <workdir> [scenario...]
set -uo pipefail
REPO=${1:?repo}
B=${2:?workdir}
shift 2
ONLY=" ${*:-e2e sigterm nospool invheld absent overflow dropped} "
GO=/opt/go1.27.2/bin/go
VERSION="0.2.0~pre1-1"
AID=6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b
rm -rf "$B"
mkdir -p "$B"
PASS=0
FAIL=0
RESULTS="$B/results.txt"
: >"$RESULTS"
check() { # name, then a command that must succeed
	local name=$1
	shift
	if "$@" >/dev/null 2>&1; then
		echo "PASS $name" >>"$RESULTS"
		PASS=$((PASS + 1))
	else
		echo "FAIL $name" >>"$RESULTS"
		FAIL=$((FAIL + 1))
	fi
}
cp -r "$REPO/agent" "$B/agent"
cp "$REPO/e2e/fake_manager_m10.py" "$REPO/e2e/fake_runner_m10.py" "$B/"
export PATH=/opt/go1.27.2/bin:/usr/sbin:/usr/bin:/sbin:/bin GOTOOLCHAIN=local GOFLAGS=-mod=readonly CGO_ENABLED=0 HOME=/root
export GOMODCACHE=${GOMODCACHE:-/root/m10c/gomod} GOCACHE=${GOCACHE:-/root/m10c/gocache}
(cd "$B/agent" && GOOS=linux GOARCH=amd64 $GO build -trimpath -buildvcs=false \
	-ldflags "-s -w -buildid= -X main.version=$VERSION" -o "$B/bitscan-agent" ./cmd/bitscan-agent) || {
	echo "BUILD FAILED"
	exit 2
}
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout "$B/ca.key" -out "$B/ca.pem" \
	-days 2 -subj /CN=bitscan-test-ca -addext basicConstraints=critical,CA:true -addext keyUsage=keyCertSign 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout "$B/leaf.key" -out "$B/leaf.csr" -subj /CN=localhost 2>/dev/null
printf 'subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\n' >"$B/leaf.ext"
openssl x509 -req -in "$B/leaf.csr" -CA "$B/ca.pem" -CAkey "$B/ca.key" -CAcreateserial -out "$B/leaf.pem" -days 1 -extfile "$B/leaf.ext" 2>/dev/null
chmod 0644 "$B/ca.pem"
echo "bse_CANARY$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 37)" >"$B/bse"

# jobs.json: one compliance job of N plugins (command and pattern canaries),
# optionally followed by an inventory job.
mkjobs() { # file nplugins with_inventory
	python3 -I - "$1" "$2" "$3" "$AID" <<'PY'
import json, sys
f, n, inv, aid = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4]
jobs = [{"job_id": "d1000000-0000-4000-8000-000000000227", "agent_id": aid, "kind": "compliance", "pickup_by": "x",
         "plugins": [{"plugin_uuid": "e1000000-0000-4000-8000-%012d" % (i + 1),
                      "execute": "touch /tmp/EXECCANARY-%d; cat /etc/shadow" % (i + 1), "timeout_s": 30} for i in range(n)],
         "redaction_patterns": ["PATTERNCANARY[0-9]+"]}]
if inv:
    jobs.append({"job_id": "d2000000-0000-4000-8000-000000000227", "agent_id": aid, "kind": "inventory", "pickup_by": "x"})
json.dump(jobs, open(f, "w"))
PY
}

# scenario NAME JOBS(n:inv) RUNNERMODE(normal|hold:N|eof:N|absent) WAIT SPOOLMB [MGRARGS...]
# WAIT: final | item | inventory | phase2
scenario() {
	local name=$1 jobs=$2 rmode=$3 wait=$4 smb=$5
	shift 5
	local d="$B/$name"
	mkdir -p "$d/u/etc" "$d/w/etc" "$d/u/varlib" "$d/w/varlib"
	mkjobs "$d/jobs.json" "${jobs%%:*}" "${jobs##*:}"
	python3 -I "$B/fake_manager_m10.py" --cert "$B/leaf.pem" --key "$B/leaf.key" --port-file "$d/port" --log "$d/requests.jsonl" --jobs "$d/jobs.json" "$@" &
	local fpid=$!
	for _ in $(seq 100); do [ -s "$d/port" ] && break; sleep 0.1; done
	local port
	port=$(cat "$d/port")
	: >"$d/requests.jsonl"
	: >"$d/runner.jsonl"
	cat >"$d/inner.sh" <<EOF
set -u
mount -t overlay overlay -o lowerdir=/etc,upperdir=$d/u/etc,workdir=$d/w/etc /etc
mount -t overlay overlay -o lowerdir=/var/lib,upperdir=$d/u/varlib,workdir=$d/w/varlib /var/lib
mount -t tmpfs tmpfs /tmp
mount -t tmpfs tmpfs /run
mkdir -m 0755 /run/bitscan
mkdir -p /etc/bitscan
cat >/etc/bitscan/agent.yaml <<YAML
manager_url: "https://127.0.0.1:$port"
ca_file: "$B/ca.pem"
manager_spki_sha256: ""
state_dir: /var/lib/bitscan-agent
heartbeat_seconds: 300
job_pull_seconds: 300
max_parallel_plugins: 2
spool_max_mb: $smb
log_level: debug
YAML
chmod 0640 /etc/bitscan/agent.yaml
mkdir -m 0700 /var/lib/bitscan-agent
install -m 0600 $B/bse /var/lib/bitscan-agent/enroll.token
case "$name" in
nospool*) printf 'not a directory\n' >/var/lib/bitscan-agent/spool ;;
dropped*) J=/var/lib/bitscan-agent/spool/d9000000-0000-4000-8000-000000000999
  mkdir -m 0700 -p \$J && printf '{bad' >\$J/job.json && chmod 0600 \$J/job.json ;;
esac
startrunner() {
  if [ "\$1" != absent ]; then
    python3 -I $B/fake_runner_m10.py --sock /run/bitscan/runner.sock --log $d/runner.jsonl --mode "\$1" ${STDOUT_BYTES:+--stdout-bytes $STDOUT_BYTES} &
    rpid=\$!
    for i in \$(seq 50); do [ -S /run/bitscan/runner.sock ] && break; sleep 0.1; done
  fi
}
spoolsize() { find /var/lib/bitscan-agent/spool -type f -printf '%s\n' 2>/dev/null | awk '{s+=\$1} END {print s+0}'; }
term() { # SIGTERM the agent, record exit code and elapsed seconds into \$1.*
  t0=\$(date +%s.%N); kill -TERM \$apid; wait \$apid; echo \$? >$d/\$1.exit; t1=\$(date +%s.%N); echo "\$t1 - \$t0" | bc >$d/\$1.elapsed
}
startrunner "$rmode"
$B/bitscan-agent >$d/stdout 2>$d/stderr &
apid=\$!
: >$d/spoolsize.txt
waitfor() { # python condition over the logs, max seconds
  for i in \$(seq \$((\$2 * 5))); do
    spoolsize >>$d/spoolsize.txt
    python3 -I -c "\$1" $d && return 0
    sleep 0.2
  done
  return 1
}
FINAL='import json,sys; r=[json.loads(l) for l in open(sys.argv[1]+"/requests.jsonl") if l.strip()]; sys.exit(0 if any(x["op"]=="results" and x["status"]==200 and json.loads(x["body"]).get("final") for x in r) else 1)'
INV='import json,sys; r=[json.loads(l) for l in open(sys.argv[1]+"/requests.jsonl") if l.strip()]; sys.exit(0 if any(x["op"]=="inventory" for x in r) else 1)'
SENT='import json,sys; r=[json.loads(l) for l in open(sys.argv[1]+"/runner.jsonl") if l.strip()]; sys.exit(0 if any(x["event"]=="sent" for x in r) else 1)'
case "$wait" in
final) waitfor "\$FINAL" 180 || echo timeout >$d/wait-timeout ;;
inventory) waitfor "\$INV" 120 || echo timeout >$d/wait-timeout; sleep 2 ;;
overflow)
  DONE='import json,sys; r=[json.loads(l) for l in open(sys.argv[1]+"/runner.jsonl") if l.strip()]; sys.exit(0 if any(x["event"]=="done" for x in r) else 1)'
  waitfor "\$DONE" 120 || echo timeout >$d/wait-timeout
  sleep 3; spoolsize >$d/spool-at-full.txt; rm -f $d/503
  waitfor "\$FINAL" 400 || echo timeout >$d/wait-timeout ;;
phase2)
  waitfor "\$SENT" 60 || echo timeout >$d/wait-timeout
  for i in \$(seq 50); do ls /var/lib/bitscan-agent/spool/*/0*.json >/dev/null 2>&1 && break; sleep 0.1; done
  sleep 0.5
  ls -la /var/lib/bitscan-agent/spool/* >$d/spool-before-term.txt 2>&1
  term phase1
  cp /var/lib/bitscan-agent/spool/*/job.json $d/manifest-after-term.json 2>/dev/null
  ls /var/lib/bitscan-agent/spool/* >$d/spool-after-term.txt 2>&1
  kill \$rpid 2>/dev/null; wait \$rpid 2>/dev/null
  rm -f /run/bitscan/runner.sock
  echo "== phase 2" >>$d/runner.jsonl.marker
  python3 -I -c 'import time; print(time.time())' >$d/phase2.t
  startrunner normal
  $B/bitscan-agent >>$d/stdout 2>>$d/stderr &
  apid=\$!
  ITEM='import json,sys,time; t=float(open(sys.argv[1]+"/phase2.t").read()); r=[json.loads(l) for l in open(sys.argv[1]+"/requests.jsonl") if l.strip()]; sys.exit(0 if any(x["op"]=="results" and x["t"]>t and json.loads(x["body"])["results"] for x in r) else 1)'
  waitfor "\$ITEM" 120 || echo timeout >$d/wait-timeout
  sleep 40 ;;
esac
ss -xlpH >$d/ss.txt 2>&1
term final
[ -n "\${rpid:-}" ] && kill \$rpid 2>/dev/null
mkdir -p $d/state
cp -a /var/lib/bitscan-agent/. $d/state/ 2>/dev/null
ls -A /tmp >$d/tmp-left.txt
EOF
	if [ "$wait" = overflow ]; then touch "$d/503"; fi
	STDOUT_BYTES=${STDOUT_BYTES:-} unshare -m --propagation private bash "$d/inner.sh"
	kill "$fpid" 2>/dev/null
	wait "$fpid" 2>/dev/null
	(cd "$d/u/etc" && find . -mindepth 1 | sort) >"$d/etc-changed.txt"
	(cd "$d/u/varlib" && find . -mindepth 1 | sort) >"$d/varlib-changed.txt"
}

analyse() { # scenario name; prints PASS/FAIL lines from python
	python3 -I "$B/analyse.py" "$B/$1" "$1" >"$B/$1/analysis.txt" 2>&1
	while read -r verdict nm; do
		if [ "$verdict" = PASS ]; then check "$1 $nm" true; else check "$1 $nm" false; fi
	done < <(grep -E '^(PASS|FAIL) ' "$B/$1/analysis.txt")
	check "$1 analysis ran" grep -q '^PASS no_canary' "$B/$1/analysis.txt"
	check "$1 no wait timeout" test ! -e "$B/$1/wait-timeout"
	check "$1 exit 0 on SIGTERM" grep -qx 0 "$B/$1/final.exit"
	check "$1 exit within 5 s" bash -c "[ \"\$(echo \"\$(cat '$B/$1/final.elapsed') < 5\" | bc)\" = 1 ]"
	check "$1 /etc changed only by the test" bash -c "[ \"\$(tr '\n' ' ' <'$B/$1/etc-changed.txt')\" = './bitscan ./bitscan/agent.yaml ' ]"
	check "$1 /var/lib changed only in bitscan-agent" bash -c "! grep -v '^./bitscan-agent' '$B/$1/varlib-changed.txt'"
	check "$1 the agent executed nothing (no EXECCANARY file)" bash -c "! grep -q EXECCANARY '$B/$1/tmp-left.txt'"
	check "$1 no listening socket of the agent" bash -c "! grep -q bitscan-agent '$B/$1/ss.txt'"
}
cp "$REPO/e2e/agent_binary_m10_analyse.py" "$B/analyse.py"

case "$ONLY" in *" e2e "*)
	scenario e2e 3:0 normal final 50
	analyse e2e ;; esac
case "$ONLY" in *" sigterm "*)
	scenario sigterm 3:0 hold:1 phase2 50
	analyse sigterm
	check "sigterm phase 1 exit 0" grep -qx 0 "$B/sigterm/phase1.exit"
	check "sigterm phase 1 exit within 5 s" bash -c "[ \"\$(echo \"\$(cat '$B/sigterm/phase1.elapsed') < 5\" | bc)\" = 1 ]" ;; esac
case "$ONLY" in *" nospool "*)
	scenario nospool 3:1 normal inventory 50
	analyse nospool ;; esac
case "$ONLY" in *" invheld "*)
	scenario invheld 3:1 hold:1 inventory 50
	analyse invheld ;; esac
case "$ONLY" in *" absent "*)
	scenario absent 3:1 absent final 50
	analyse absent ;; esac
case "$ONLY" in *" dropped "*)
	scenario dropped 1:0 normal final 50
	analyse dropped ;; esac
case "$ONLY" in *" overflow "*)
	STDOUT_BYTES=65536 scenario overflow 30:0 slow:5:32 overflow 1 --results "503-while:$B/overflow/503"
	analyse overflow ;; esac

echo "$PASS/$((PASS + FAIL)) passed, $FAIL failed, 0 errors, 0 skipped"
grep '^FAIL' "$RESULTS"
[ "$FAIL" = 0 ]
