#!/bin/bash
# Binary-level tests of bitscan-agent (tests/m4/test-plan.md TP-M4-21,
# CHK-M4-260 to -263, -265; lead rulings 2026-10-24 for TASK-106).
#
# Runs as root on Linux (WSL Ubuntu 24.04). The binary reads only its
# production paths (/etc/bitscan/agent.yaml, /etc/machine-id, /etc/os-release,
# /var/lib/bitscan-agent), so each scenario runs inside a private mount
# namespace with overlayfs on /etc and /var/lib and a tmpfs on /tmp: nothing
# on the host changes. The manager is e2e/fake_manager.py on 127.0.0.1 with a
# test CA in ca_file. Usage: agent_binary.sh <repo> <workdir>
set -uo pipefail
REPO=${1:?repo}
B=${2:?workdir}
GO=/opt/go1.27.2/bin/go
VERSION="0.1.0~pre1-1"
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
cp "$REPO/e2e/fake_manager.py" "$B/fake_manager.py"
export PATH=/opt/go1.27.2/bin:/usr/sbin:/usr/bin:/sbin:/bin GOTOOLCHAIN=local GOFLAGS=-mod=readonly \
	GOPATH=/root/bitscan-m4a/gopath GOMODCACHE=/root/bitscan-m4/gopath/pkg/mod GOCACHE=/root/bitscan-m4a/gocache CGO_ENABLED=0 HOME=/root
(cd "$B/agent" && GOOS=linux GOARCH=amd64 $GO build -trimpath -buildvcs=false \
	-ldflags "-s -w -buildid= -X main.version=$VERSION" -o "$B/bitscan-agent" ./cmd/bitscan-agent) || {
	echo "BUILD FAILED"
	exit 2
}
(cd "$B/agent" && GOOS=linux GOARCH=amd64 $GO build -trimpath -buildvcs=false -o "$B/bitscan-agent-nover" ./cmd/bitscan-agent) || exit 2

# test PKI: CA and a leaf for 127.0.0.1
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout "$B/ca.key" -out "$B/ca.pem" \
	-days 2 -subj /CN=bitscan-test-ca -addext basicConstraints=critical,CA:true -addext keyUsage=keyCertSign 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout "$B/leaf.key" -out "$B/leaf.csr" -subj /CN=localhost 2>/dev/null
printf 'subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\n' >"$B/leaf.ext"
openssl x509 -req -in "$B/leaf.csr" -CA "$B/ca.pem" -CAkey "$B/ca.key" -CAcreateserial -out "$B/leaf.pem" -days 1 -extfile "$B/leaf.ext" 2>/dev/null
chmod 0644 "$B/ca.pem"

BSE="bse_CANARY$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 37)"
echo "$BSE" >"$B/bse"

# scenario NAME MODE FAKEARGS... ; MODE: run | hold:OP | refuse:KIND | idle
scenario() {
	local name=$1 mode=$2
	shift 2
	local d="$B/$name"
	mkdir -p "$d/u/etc" "$d/w/etc" "$d/u/varlib" "$d/w/varlib"
	python3 -I "$B/fake_manager.py" --cert "$B/leaf.pem" --key "$B/leaf.key" --port-file "$d/port" --log "$d/requests.jsonl" "$@" &
	local fpid=$!
	for _ in $(seq 100); do [ -s "$d/port" ] && break; sleep 0.1; done
	local port
	port=$(cat "$d/port")
	: >"$d/requests.jsonl"
	cat >"$d/inner.sh" <<EOF
set -u
mount -t overlay overlay -o lowerdir=/etc,upperdir=$d/u/etc,workdir=$d/w/etc /etc
mount -t overlay overlay -o lowerdir=/var/lib,upperdir=$d/u/varlib,workdir=$d/w/varlib /var/lib
mount -t tmpfs tmpfs /tmp
mkdir -p /etc/bitscan
cat >/etc/bitscan/agent.yaml <<YAML
manager_url: "https://127.0.0.1:$port"
ca_file: "$B/ca.pem"
manager_spki_sha256: ""
state_dir: /var/lib/bitscan-agent
heartbeat_seconds: 300
job_pull_seconds: 300
max_parallel_plugins: 2
spool_max_mb: 50
log_level: debug
YAML
chmod 0640 /etc/bitscan/agent.yaml
mkdir -m 0700 /var/lib/bitscan-agent
install -m 0600 $B/bse /var/lib/bitscan-agent/enroll.token
BIN=$B/bitscan-agent
case "$mode" in
refuse:http) sed -i 's#https://#http://#' /etc/bitscan/agent.yaml ;;
refuse:unknown-key) echo 'inventory: false' >>/etc/bitscan/agent.yaml ;;
refuse:machine-id) tr a-f A-F </etc/machine-id >/tmp/m && cat /tmp/m >/etc/machine-id ;;
refuse:no-credentials) rm /var/lib/bitscan-agent/enroll.token ;;
refuse:no-version) BIN=$B/bitscan-agent-nover ;;
refuse:ca-file) sed -i 's#ca.pem#absent.pem#' /etc/bitscan/agent.yaml ;;
refuse:corrupt-seen) echo '{bad' >/var/lib/bitscan-agent/seen_jobs.json ;;
esac
\$BIN >$d/stdout 2>$d/stderr &
apid=\$!
echo \$apid >$d/pid
case "$mode" in
run)
  for i in \$(seq 300); do grep -q '"method": "PUT"' $d/requests.jsonl && break; sleep 0.1; done
  sleep 1
  ss -ltnupH >$d/ss.txt 2>&1
  ;;
hold:*)
  for i in \$(seq 300); do grep -q "${mode#hold:}" $d/requests.jsonl && break; sleep 0.1; done
  sleep 0.5
  ;;
refuse:*)
  for i in \$(seq 100); do kill -0 \$apid 2>/dev/null || break; sleep 0.1; done
  ;;
idle)
  sleep 6
  kill -0 \$apid 2>/dev/null && echo alive >$d/alive
  ;;
esac
if kill -0 \$apid 2>/dev/null; then
  t0=\$(date +%s.%N)
  kill -TERM \$apid
  wait \$apid
  echo \$? >$d/exit
  t1=\$(date +%s.%N)
  echo "\$t1 - \$t0" | bc >$d/elapsed
else
  wait \$apid
  echo \$? >$d/exit
  echo 0 >$d/elapsed
fi
ls -la /var/lib/bitscan-agent >$d/state-ls.txt 2>&1
mkdir -p $d/state
cp -a /var/lib/bitscan-agent/. $d/state/ 2>/dev/null
stat -c '%n %a %U' /var/lib/bitscan-agent/* >$d/state-modes.txt 2>/dev/null
ls -A /tmp | grep -v '^m\$' >$d/tmp-left.txt
EOF
	unshare -m --propagation private bash "$d/inner.sh"
	kill "$fpid" 2>/dev/null
	wait "$fpid" 2>/dev/null
	# what changed under /etc and /var/lib (overlay upper dirs)
	(cd "$d/u/etc" && find . -mindepth 1 | sort) >"$d/etc-changed.txt"
	(cd "$d/u/varlib" && find . -mindepth 1 | sort) >"$d/varlib-changed.txt"
}

ncalls() { grep -c . "$1/requests.jsonl"; }
has() { grep -q -- "$2" "$1"; }
lt() { [ "$(echo "$1 < $2" | bc)" = 1 ]; }

# ---- S1: full run: enrol, heartbeat, rotate, pull, inventory upload ----
scenario s1 run --inventory-job --rotate-open
S="$B/s1"
python3 -I - "$S" "$BSE" "$(cat /etc/machine-id)" >"$S/analysis.txt" 2>&1 <<'PY'
import gzip, hashlib, json, sys, pathlib
d, bse, mid = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
reqs = [json.loads(l) for l in (d / "requests.jsonl").read_text().splitlines() if l.strip()]
toks = (d / "requests.jsonl.tokens").read_text().split()
def first(path_end, method=None):
    return next((r for r in reqs if r["path"].endswith(path_end) and (method is None or r["method"] == method)), None)
out = {}
e = first("/api/v1/agent/enroll")
out["enrol_once"] = sum(r["path"].endswith("/enroll") for r in reqs) == 1
out["enrol_bse_header"] = e is not None and e["authorization"] == "Bearer " + bse and e["machine_id"] == []
eb = json.loads(e["body"]) if e else {}
out["enrol_body_keys"] = sorted(eb) == ["agent_version", "hostname", "machine_id", "os_id", "os_pretty_name", "os_version_id"]
out["enrol_machine_id"] = eb.get("machine_id") == mid
out["enrol_version"] = eb.get("agent_version") == "0.1.0~pre1-1"
hb = first("/heartbeat")
out["heartbeat_first_token"] = hb is not None and hb["authorization"] == "Bearer " + toks[0] and hb["machine_id"] == [mid]
hbb = json.loads(hb["body"]) if hb else {}
out["heartbeat_body"] = hbb.get("agent_version") == "0.1.0~pre1-1" and hbb.get("spool_bytes") == 0 and hbb.get("runner_helpers") == [] and hbb.get("last_pull_at") is None
rot = first("/token/rotate")
out["rotate_called_old_token"] = rot is not None and rot["authorization"] == "Bearer " + toks[0] and rot["body"] in ("{}", "")
jobs = first("/jobs", "GET")
out["jobs_new_token"] = jobs is not None and len(toks) >= 2 and jobs["authorization"] == "Bearer " + toks[1]
inv = first("/inventory", "PUT")
out["inventory_job_upload"] = inv is not None and inv["query"] == "job_id=c1a4e5f6-0718-4293-a4b5-c6d7e8f9a0b1" and inv["content_encoding"].lower() == "gzip" and inv["authorization"] == "Bearer " + toks[1]
body = json.loads(inv["body"]) if inv else {}
pk = body.get("packages", [])
lines = sorted(("%s\t%s\t%s\t%s\n" % (p["name"], p["version"], p["architecture"], p["status"])).encode() for p in pk)
out["inventory_hash"] = bool(pk) and hashlib.sha256(b"".join(lines)).hexdigest() == body.get("list_sha256")
import subprocess
n = len(subprocess.run(["dpkg-query", "-W"], capture_output=True, text=True).stdout.splitlines())
out["inventory_count_matches_dpkg"] = len(pk) == n
oi = body.get("os_info", {})
out["inventory_os_info"] = oi.get("architecture") == "x86_64" and oi.get("os_id") == "ubuntu" and isinstance(oi.get("ip_addresses"), list)
# state after the run: agent_id, the rotated token, times, seen job
st = d / "state"
out["state_agent_id"] = (st / "agent_id").read_text() == "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b\n"
out["state_token_rotated"] = len(toks) >= 2 and (st / "token").read_text() == toks[1] + "\n"
out["state_enroll_token_gone"] = not (st / "enroll.token").exists()
out["state_seen_job"] = "c1a4e5f6-0718-4293-a4b5-c6d7e8f9a0b1" in (st / "seen_jobs.json").read_text()
out["state_no_tmp"] = not any(p.name.endswith(".tmp") for p in st.iterdir())
json.loads((st / "token.json").read_text())
modes = dict(l.split()[0].rsplit("/", 1)[1:] + [l.split()[1]] for l in (d / "state-modes.txt").read_text().splitlines()) if False else {l.split()[0].rsplit("/", 1)[1]: l.split()[1] for l in (d / "state-modes.txt").read_text().splitlines()}
out["state_modes"] = modes.get("agent_id") == "644" and modes.get("token") == "600" and modes.get("token.json") == "600" and modes.get("seen_jobs.json") == "600"
# canaries: no token in stdout or stderr
logs = (d / "stdout").read_text() + (d / "stderr").read_text()
out["no_canary_in_output"] = "CANARY" not in logs and "bsa_" not in logs and "bse_" not in logs
out["stdout_empty"] = (d / "stdout").read_text() == ""
out["start_line_version"] = "bitscan-agent started" in logs and "version=0.1.0~pre1-1" in logs
for k, v in out.items():
    print(("PASS " if v else "FAIL ") + k)
PY
while read -r verdict name; do
	if [ "$verdict" = PASS ]; then check "s1 $name" true; else check "s1 $name" false; fi
done < <(grep -E '^(PASS|FAIL) ' "$S/analysis.txt")
check "s1 analysis ran" grep -q '^PASS no_canary_in_output\|^FAIL no_canary_in_output' "$S/analysis.txt"
check "s1 exit 0 after SIGTERM" grep -qx 0 "$S/exit"
check "s1 exit within 5 s" lt "$(cat "$S/elapsed")" 5
check "s1 no listening socket" bash -c "! grep -q bitscan-agent '$S/ss.txt'"
check "s1 nothing in /tmp" bash -c "[ ! -s '$S/tmp-left.txt' ]"
check "s1 /etc changed only by the test (agent.yaml)" bash -c "[ \"\$(cat '$S/etc-changed.txt' | tr '\n' ' ')\" = './bitscan ./bitscan/agent.yaml ' ]"
check "s1 /var/lib changed only in bitscan-agent" bash -c "! grep -v '^./bitscan-agent' '$S/varlib-changed.txt'"

# ---- S2-S4: SIGTERM while a call is held open ----
for op in heartbeat jobs inventory; do
	scenario "hold-$op" "hold:$op" --hold "$op" --inventory-job
	S="$B/hold-$op"
	check "hold-$op request reached" grep -q "$op" "$S/requests.jsonl"
	check "hold-$op exit 0" grep -qx 0 "$S/exit"
	check "hold-$op exit within 5 s" lt "$(cat "$S/elapsed")" 5
	check "hold-$op no .tmp left" bash -c "! ls -A '$S/state' | grep -q '\.tmp$'"
	check "hold-$op state complete" bash -c "[ -s '$S/state/agent_id' ] && [ -s '$S/state/token' ] && [ -s '$S/state/token.json' ] && [ ! -e '$S/state/enroll.token' ]"
	check "hold-$op no canary in output" bash -c "! grep -q 'CANARY' '$S/stdout' '$S/stderr'"
done

# ---- S5: start-up refusals: exit 1, one line naming the cause, no call ----
for kind in http unknown-key machine-id no-credentials no-version ca-file corrupt-seen; do
	scenario "refuse-$kind" "refuse:$kind"
	S="$B/refuse-$kind"
	check "refuse-$kind exit 1" grep -qx 1 "$S/exit"
	check "refuse-$kind no manager call" bash -c "[ \$(grep -c . '$S/requests.jsonl') = 0 ]"
	check "refuse-$kind one stderr line" bash -c "[ \$(grep -c . '$S/stderr') = 1 ]"
	check "refuse-$kind no canary" bash -c "! grep -q CANARY '$S/stderr' '$S/stdout'"
done
check "refuse-http names manager_url" grep -q manager_url "$B/refuse-http/stderr"
check "refuse-unknown-key names inventory" grep -q inventory "$B/refuse-unknown-key/stderr"
check "refuse-machine-id names /etc/machine-id" grep -q /etc/machine-id "$B/refuse-machine-id/stderr"
check "refuse-no-credentials names both files" bash -c "grep -q 'enroll.token' '$B/refuse-no-credentials/stderr' && grep -q 'neither token' '$B/refuse-no-credentials/stderr'"
check "refuse-no-version names the version" grep -q version "$B/refuse-no-version/stderr"
check "refuse-ca-file names ca_file" grep -q ca_file "$B/refuse-ca-file/stderr"
check "refuse-corrupt-seen names seen_jobs.json" grep -q seen_jobs.json "$B/refuse-corrupt-seen/stderr"
check "refuse-* enroll.token kept" bash -c "[ -e '$B/refuse-http/state/enroll.token' ] && [ -e '$B/refuse-machine-id/state/enroll.token' ]"

# ---- S6: refused enrolment (401, 403): one line, idle until SIGTERM ----
for code in 401 403; do
	scenario "enrol-$code" idle --enrol "$code"
	S="$B/enrol-$code"
	check "enrol-$code still running after 6 s" test -e "$S/alive"
	check "enrol-$code exactly one call" bash -c "[ \$(grep -c . '$S/requests.jsonl') = 1 ]"
	check "enrol-$code one log line" bash -c "[ \$(grep -c . '$S/stderr') = 1 ]"
	check "enrol-$code exit 0 on SIGTERM" grep -qx 0 "$S/exit"
	check "enrol-$code exit within 5 s" lt "$(cat "$S/elapsed")" 5
	check "enrol-$code enroll.token kept, nothing written" bash -c "[ \"\$(ls -A '$S/state' | tr '\n' ' ')\" = 'enroll.token ' ]"
	check "enrol-$code no canary" bash -c "! grep -q CANARY '$S/stderr' '$S/stdout'"
done
check "enrol-401 line says a new enrolment token is needed" grep -q "new enrolment token" "$B/enrol-401/stderr"

# ---- S7: a 401 on the pull stops every loop; the process stays up idle ----
scenario jobs-401 idle --jobs-401
S="$B/jobs-401"
check "jobs-401 still running" test -e "$S/alive"
check "jobs-401 no call after the 401" python3 -I -c "
import json,sys
r=[json.loads(l) for l in open('$S/requests.jsonl') if l.strip()]
i=max(k for k,x in enumerate(r) if x['path'].endswith('/jobs'))
sys.exit(0 if i==len(r)-1 else 1)"
check "jobs-401 re-enrol line once" bash -c "[ \$(grep -c 're-enrolled' '$S/stderr') = 1 ]"
check "jobs-401 exit 0 on SIGTERM" grep -qx 0 "$S/exit"

echo "$PASS/$((PASS + FAIL)) passed, $FAIL failed, 0 errors, 0 skipped"
grep '^FAIL' "$RESULTS"
[ "$FAIL" = 0 ]
