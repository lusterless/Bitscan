#!/bin/bash
# TASK-228 WSL rows (tests/m10/test-plan.md CHK-M10-188 to -191; tester-m10c):
# the built bitscan-runner under a transient systemd-run unit carrying the
# verbatim [Service] directives of deploy/systemd/bitscan-runner.service and
# the [Socket] directives of bitscan-runner.socket. The shipped units are
# never installed or enabled. Root in WSL Ubuntu 24.04 (cgroup2, systemd 255).
# Usage: runner_unit_m10.sh <repo> <workdir> [base|nolock]
set -uo pipefail
REPO=${1:?repo}
B=${2:?workdir}
VARIANT=${3:-base}
U=m10c-runner
BIN=/usr/local/lib/m10c/bitscan-runner # under /usr: the unit's ExecPaths
AID=6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b
export PATH=/opt/go1.27.2/bin:/usr/sbin:/usr/bin:/sbin:/bin GOTOOLCHAIN=local CGO_ENABLED=0 HOME=/root
export GOMODCACHE=${GOMODCACHE:-/root/m10c/gomod} GOCACHE=${GOCACHE:-/root/m10c/gocache}
rm -rf "$B"
mkdir -p "$B"
PASS=0
FAIL=0
R="$B/results.txt"
: >"$R"
ok() { if [ "$2" = 1 ]; then echo "PASS $1" >>"$R"; PASS=$((PASS + 1)); else echo "FAIL $1" >>"$R"; FAIL=$((FAIL + 1)); fi; }
t() { if eval "$2" >/dev/null 2>&1; then ok "$1" 1; else ok "$1" 0; fi; }
cleanup() {
	systemctl stop $U.socket $U.service >/dev/null 2>&1
	systemctl reset-failed $U.socket $U.service >/dev/null 2>&1
	rm -f /tmp/m10c-host-marker /var/tmp/m10c-host-marker
	if [ -n "${MADE_STATE:-}" ]; then rm -rf /var/lib/bitscan-agent; fi
	if [ -n "${SAVED_ID:-}" ]; then cp -a "$B/agent_id.saved" /var/lib/bitscan-agent/agent_id; fi
}
trap cleanup EXIT

rsync -a --exclude '*.exe' "$REPO/agent/" "$B/agent/"
if [ "$VARIANT" = nolock ]; then # plant: the TASK-221 r2 m0 lock removed from main
	sed -i 's/^func init() { runtime.LockOSThread() }$/func init() { _ = runtime.LockOSThread }/' "$B/agent/cmd/bitscan-runner/main.go"
	grep -q '_ = runtime.LockOSThread' "$B/agent/cmd/bitscan-runner/main.go" || { echo "PLANT ANCHOR NOT FOUND"; exit 9; }
fi
if [ "$VARIANT" = notmp ]; then # plant: the private /tmp and /var/tmp not emptied
	sed -i 's#TmpDirs: \[\]string{"/tmp", "/var/tmp"},#TmpDirs: nil,#' "$B/agent/cmd/bitscan-runner/main.go"
	grep -q 'TmpDirs: nil,' "$B/agent/cmd/bitscan-runner/main.go" || { echo "PLANT ANCHOR NOT FOUND"; exit 9; }
fi
if [ "$VARIANT" = noharden ]; then # plant: PR_SET_DUMPABLE never set
	python3 - "$B/agent/cmd/bitscan-runner/main.go" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
a="	if err := runner.Harden(); err != nil {"
assert a in s
open(p,"w").write(s.replace(a, "	if err := error(nil); err != nil {",1))
PY
fi
(cd "$B/agent" && go build -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X main.version=0.2.0~pre1-1" -o "$B/bitscan-runner" ./cmd/bitscan-runner) || { echo BUILD FAILED; exit 2; }
install -D -m 0755 "$B/bitscan-runner" $BIN
id -u bitscan >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin bitscan
if [ ! -d /var/lib/bitscan-agent ]; then
	MADE_STATE=1
	install -d -m 0700 -o bitscan -g bitscan /var/lib/bitscan-agent
elif [ -e /var/lib/bitscan-agent/agent_id ]; then
	SAVED_ID=1
	cp -a /var/lib/bitscan-agent/agent_id "$B/agent_id.saved"
fi
printf '%s\n' "$AID" >/var/lib/bitscan-agent/agent_id
chown bitscan:bitscan /var/lib/bitscan-agent/agent_id
chmod 0644 /var/lib/bitscan-agent/agent_id
echo "== state dir: $(stat -c '%U:%G %a' /var/lib/bitscan-agent), agent_id $(stat -c '%U:%G %a' /var/lib/bitscan-agent/agent_id)" >>"$B/notes.txt"
echo m >/tmp/m10c-host-marker
echo m >/var/tmp/m10c-host-marker
S=/mnt/c/Users/kaiquan.koh/AppData/Local/Temp/m10c
mapfile -t SVC < <(python3 -I $S/unitprops.py "$REPO/deploy/systemd/bitscan-runner.service" Service -p)
mapfile -t SOCK < <(python3 -I $S/unitprops.py "$REPO/deploy/systemd/bitscan-runner.socket" Socket --socket-property)
echo "== service properties: $((${#SVC[@]} / 2)); socket properties: $((${#SOCK[@]} / 2))" >>"$B/notes.txt"
grep -n -- '' <<<"$(printf '%s\n' "${SVC[@]}" | grep -v '^-p$')" >"$B/service-props.txt"

start() { # extra properties...
	systemctl stop $U.socket $U.service >/dev/null 2>&1
	systemctl reset-failed $U.socket $U.service >/dev/null 2>&1
	systemd-run --unit=$U "${SOCK[@]}" "${SVC[@]}" "$@" $BIN 2>"$B/systemd-run.err"
}
if ! start; then
	echo "== systemd-run refused the verbatim set: $(cat "$B/systemd-run.err")" >>"$B/notes.txt"
	# find the refused properties one by one (each is NOT RUN)
	keep=()
	for ((i = 0; i < ${#SVC[@]}; i += 2)); do
		if systemd-run --unit=m10c-probe --dry-run -p "${SVC[i + 1]}" /bin/true >/dev/null 2>&1 ||
			systemd-run --unit=m10c-probe -p "${SVC[i + 1]}" --wait -q /bin/true >/dev/null 2>&1; then keep+=(-p "${SVC[i + 1]}")
		else echo "REFUSED ${SVC[i + 1]}" >>"$B/notes.txt"; fi
	done
	SVC=("${keep[@]}")
	start || { echo "== still refused: $(cat "$B/systemd-run.err")" >>"$B/notes.txt"; exit 3; }
fi
ok "systemd-run accepted the unit properties" 1
for _ in $(seq 50); do [ -S /run/bitscan/runner.sock ] && break; sleep 0.1; done
echo "== socket: $(stat -c '%U:%G %a' /run/bitscan/runner.sock), dir $(stat -c '%U:%G %a' /run/bitscan)" >>"$B/notes.txt"
t "socket root:bitscan 0660 in a root 0755 dir" '[ "$(stat -c "%U:%G %a" /run/bitscan/runner.sock)" = "root:bitscan 660" ] && [ "$(stat -c "%U:%G %a" /run/bitscan)" = "root:root 755" ]'
python3 -I - "$S" >"$B/patterns.txt" <<'PY'
import re, sys
t = open("/mnt/c/Users/kaiquan.koh/Documents/Bitscan-m10/docs/spec/Technical_Specification.md", encoding="utf-8").read()
r = t[t.index("**Default redaction patterns**"):]
b = r[r.index("```text\n") + 8:]
print(b[: b.index("\n```")])
PY
chmod 0644 "$B/patterns.txt"
chmod 0755 "$B"
install -d -o bitscan -g bitscan -m 0755 "$B/logs"

# ---- job 1: 8 plugins at max_parallel_plugins 8 ----
python3 -I - "$B/plugins8.json" <<'PY'
import json, sys
p = []
for i in range(8):
    p.append({"plugin_uuid": "e8000000-0000-4000-8000-%012d" % (i + 1), "timeout_s": 30,
              "execute": "S=$(date +%s.%N); echo CG=$(cut -d: -f3 /proc/self/cgroup); echo NICE=$(awk '{print $19}' /proc/$$/stat); "
                         "echo UID=$(id -u); echo M10EXECCANARY >/dev/null; echo x >/tmp/p" + str(i) + "; echo y >/var/tmp/q" + str(i) + "; "
                         "sleep 300.228 & sleep 1; echo OUT=M10OUTCANARY; echo SHADOW=$(head -c 5 /etc/shadow); echo START=$S END=$(date +%s.%N)"})
json.dump(p, open(sys.argv[1], "w"))
PY
cp "$REPO/e2e/runner_client_m10.py" "$B/client.py"
chmod 0644 "$B"/*.json "$B/client.py"
runuser -u bitscan -- python3 -I "$B/client.py" --sock /run/bitscan/runner.sock --log "$B/logs/job1.jsonl" --job-id d8000000-0000-4000-8000-$(printf '%012d' $((RANDOM * 32768 + RANDOM))) \
	--agent-id $AID --mpp 8 --plugins "$B/plugins8.json" --patterns "$B/patterns.txt" &
cpid=$!
sleep 0.5
PID=$(systemctl show -p MainPID --value $U.service)
grep -E '^(Uid|Gid|CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs|Seccomp):' /proc/$PID/status | tr '\t' ' ' >"$B/runner-status.txt"
stat -c '%U' /proc/$PID/environ >"$B/runner-environ-owner.txt"
ls /sys/fs/cgroup/system.slice/$U.service/ >"$B/cgroup-during.txt"
wait $cpid
# 10 more jobs of 8 short plugins: 88 spawns in all before the niceness read
python3 -I -c '
import json,sys
json.dump([{"plugin_uuid":"eb000000-0000-4000-8000-%012d"%(i+1),"timeout_s":30,"execute":"true"} for i in range(8)],open(sys.argv[1],"w"))' "$B/plugins8t.json"
chmod 0644 "$B/plugins8t.json"
for k in $(seq 10); do
	runuser -u bitscan -- python3 -I "$B/client.py" --sock /run/bitscan/runner.sock --log "$B/logs/job1-$k.jsonl" --job-id db000000-0000-4000-8000-$(printf '%012d' $((RANDOM * 32768 + RANDOM))) 		--agent-id $AID --mpp 8 --plugins "$B/plugins8t.json"
done
t "10 more jobs of 8 plugins each ended done" '[ "$(cat "$B"/logs/job1-*.jsonl | grep -c "\"done\"")" = 10 ]'
sleep 1
cat /proc/$PID/cgroup >"$B/runner-cgroup.txt"
for f in /proc/$PID/task/*/stat; do awk '{print FILENAME, $19}' FILENAME="${f%/stat}" "$f"; done >"$B/runner-threads-nice.txt" 2>/dev/null
pgrep -u bitscan-runner -f 'sleep 300.228' >"$B/survivors.txt"
find /sys/fs/cgroup/system.slice/$U.service -mindepth 1 -type d | sed "s#/sys/fs/cgroup/system.slice/$U.service/##" >"$B/cgroup-after.txt"
nsenter -t $PID -m ls -A /tmp /var/tmp >"$B/private-tmp-after.txt" 2>&1
journalctl -u $U.service --no-pager -o cat >"$B/journal1.txt"
python3 -I - "$B" >>"$R" <<'PY'
import json, sys, pathlib
b = pathlib.Path(sys.argv[1])
rep = [json.loads(l) for l in (b / "logs" / "job1.jsonl").read_text().splitlines() if l.strip()]
kinds = [r["type"] for r in rep]
def ok(name, v): print(("PASS " if v else "FAIL ") + name)
ok("job1 accepted, 8 results, done, EOF", kinds == ["accepted"] + ["result"] * 8 + ["done", "EOF"])
res = [r["result"] for r in rep if r["type"] == "result"]
def field(it, k):
    for l in it["stdout"].splitlines():
        if l.startswith(k + "="):
            return l[len(k) + 1:]
    return ""
ok("job1 every plugin exit 0, not timed out", len(res) == 8 and all(r["exit_code"] == 0 and not r["timed_out"] for r in res))
cgs = [field(r, "CG") for r in res]
ok("job1 each plugin in its own p-<n>", len(set(cgs)) == 8 and all("/p-" in c and "supervisor" not in c for c in cgs))
ok("job1 plugins at niceness 10", all(field(r, "NICE") == "10" for r in res))
ok("job1 plugins run as bitscan-runner, not 0", all(field(r, "UID") not in ("", "0") for r in res))
ev = []
for r in res:
    parts = dict(p.split("=") for p in field(r, "START").replace(" END", " END").split(" ") if "=" in p) if False else None
    line = next(l for l in r["stdout"].splitlines() if l.startswith("START="))
    s, e = line.split(" ")
    ev += [(float(s[6:]), 1), (float(e[4:]), -1)]
ev.sort(key=lambda x: (x[0], x[1]))
cur = top = 0
for _, dlt in ev:
    cur += dlt
    top = max(top, cur)
print("NOTE max plugins at once %d" % top)
ok("job1 8 plugins ran in parallel", top == 8)
ok("job1 CAP_DAC_READ_SEARCH reads /etc/shadow", all(len(field(r, "SHADOW")) >= 1 for r in res))
st = (b / "runner-status.txt").read_text()
caps = {l.split(":")[0]: l.split(":")[1].strip() for l in st.splitlines()}
print("NOTE runner " + "; ".join("%s %s" % kv for kv in caps.items()))
ok("runner CapEff, CapPrm, CapBnd, CapAmb each 0x4", all(caps.get(k) == "0000000000000004" for k in ("CapEff", "CapPrm", "CapBnd", "CapAmb")))
ok("runner NoNewPrivs 1 and seccomp on", caps.get("NoNewPrivs") == "1" and caps.get("Seccomp") == "2")
ok("runner uid is bitscan-runner", caps.get("Uid", "").split()[0] not in ("", "0"))
ok("runner in supervisor", (b / "runner-cgroup.txt").read_text().strip().endswith("/supervisor"))
ok("runner not dumpable (/proc/<pid>/environ owned by root)", (b / "runner-environ-owner.txt").read_text().strip() == "root")
nice = [l.split() for l in (b / "runner-threads-nice.txt").read_text().splitlines()]
bad = [n for n in nice if n[1] != "0"]
print("NOTE runner threads %d, not at niceness 0: %s" % (len(nice), bad))
ok("runner threads all at niceness 0 after the job (TASK-221 r2, binary level)", nice and not bad)
ok("no plugin process survives the job", (b / "survivors.txt").read_text().strip() == "")
ok("service subtree holds only supervisor after the job", (b / "cgroup-after.txt").read_text().split() == ["supervisor"])
pt = (b / "private-tmp-after.txt").read_text()
print("NOTE private tmp after: " + pt.replace("\n", " | "))
ok("the runner's private /tmp and /var/tmp are empty after the job", pt.split() == ["/tmp:", "/var/tmp:"])
j = (b / "journal1.txt").read_text()
ok("journal: started line, no canary or output", "bitscan-runner started" in j and "CANARY" not in j and "SHADOW" not in j)
ok("journal: job lines carry job_id", "job_id=d8000000" in j)
PY
# REQ-235 (3) in WSL: a user outside group bitscan gets EACCES from the 0660
# socket; root connects and is closed without a reply (peer uid check).
runuser -u nobody -- python3 -I -c 'import socket,sys
s=socket.socket(socket.AF_UNIX)
try: s.connect("/run/bitscan/runner.sock")
except PermissionError: sys.exit(0)
sys.exit(1)' && ok "nobody (outside group bitscan) gets EACCES from runner.sock" 1 || ok "nobody (outside group bitscan) gets EACCES from runner.sock" 0
python3 -I "$B/client.py" --sock /run/bitscan/runner.sock --log "$B/logs/root.jsonl" --job-id dc000000-0000-4000-8000-000000000001 	--agent-id $AID --mpp 1 --plugins "$B/plugins8t.json" 2>/dev/null
t "root connects and is closed without a reply (no frame; reset or EOF)" '! grep -qE "accepted|refused|result" "$B/logs/root.jsonl" 2>/dev/null'
journalctl -u $U.service --no-pager -o cat | grep -c 'peer refused.*uid=0' | sed 's/^/NOTE journal peer-refused lines for uid 0: /' >>"$R"
t "host /tmp and /var/tmp markers untouched" '[ -e /tmp/m10c-host-marker ] && [ -e /var/tmp/m10c-host-marker ]'
t "the runner did not touch the agent state dir" '[ "$(cat /var/lib/bitscan-agent/agent_id)" = "'$AID'" ]'

# ---- job 2: SIGTERM to the runner mid-job (CHK-M10-191) ----
python3 -I -c '
import json,sys
json.dump([{"plugin_uuid":"e9000000-0000-4000-8000-00000000000%d"%i,"timeout_s":600,"execute":"sleep 300.191"} for i in (1,2)],open(sys.argv[1],"w"))' "$B/plugins2.json"
chmod 0644 "$B/plugins2.json"
runuser -u bitscan -- python3 -I "$B/client.py" --sock /run/bitscan/runner.sock --log "$B/logs/job2.jsonl" --job-id d9100000-0000-4000-8000-$(printf '%012d' $((RANDOM * 32768 + RANDOM))) \
	--agent-id $AID --mpp 2 --plugins "$B/plugins2.json" &
cpid=$!
for _ in $(seq 50); do [ "$(pgrep -c -u bitscan-runner -x sleep)" -ge 2 ] && break; sleep 0.1; done
PID=$(systemctl show -p MainPID --value $U.service)
echo "NOTE job2 processes matching the plugins before SIGTERM: $(pgrep -a -u bitscan-runner -f 'sleep 300.191' | tr '
' ';')" >>"$R"
t "job2 two plugins running" '[ "$(pgrep -c -u bitscan-runner -x sleep)" -ge 2 ]'
systemctl kill -s TERM --kill-whom=main $U.service
for _ in $(seq 100); do kill -0 $PID 2>/dev/null || break; sleep 0.05; done
sleep 1
t "job2 runner exited after SIGTERM" '! kill -0 '$PID
t "job2 no plugin 1 s after the runner exited" '[ -z "$(pgrep -u bitscan-runner -f "sleep 300.191")" ]'
t "job2 runner exit status 0" '[ "$(systemctl show -p ExecMainStatus --value '$U'.service)" = 0 ]'
wait $cpid
t "job2 client saw no done" '! grep -q "\"done\"" '"$B/logs/job2.jsonl"
journalctl -u $U.service --no-pager -o cat >"$B/journal2.txt"
t "job2 journal: stopped line" 'grep -q "bitscan-runner stopped" '"$B/journal2.txt"

# ---- job 3: a cleanup error on a plugin-named path (TASK-224 r2, end to end) ----
mkdir -p /opt/m10c/ro-canary && echo x >/opt/m10c/ro-canary/f
start -p BindReadOnlyPaths=/opt/m10c/ro-canary:/var/tmp/M10PATHCANARY-ro
for _ in $(seq 50); do [ -S /run/bitscan/runner.sock ] && break; sleep 0.1; done
python3 -I -c 'import json,sys; json.dump([{"plugin_uuid":"ea000000-0000-4000-8000-000000000001","timeout_s":30,"execute":"true"}],open(sys.argv[1],"w"))' "$B/plugins1.json"
chmod 0644 "$B/plugins1.json"
runuser -u bitscan -- timeout 60 python3 -I "$B/client.py" --sock /run/bitscan/runner.sock --log "$B/logs/job3.jsonl" --job-id da000000-0000-4000-8000-$(printf '%012d' $((RANDOM * 32768 + RANDOM))) \
	--agent-id $AID --mpp 1 --plugins "$B/plugins1.json"
sleep 1
journalctl -u $U.service --no-pager -o cat >"$B/journal3.txt"
t "job3 no done after a failed cleanup" '! grep -q "\"done\"" '"$B/logs/job3.jsonl"
t "job3 runner exited 1 (cleanup cannot be guaranteed)" 'grep -q "cleanup cannot be guaranteed" '"$B/journal3.txt"
t "job3 journal names no part of the plugin path" '! grep -q "M10PATHCANARY" '"$B/journal3.txt"
grep -E "cleanup|reason" "$B/journal3.txt" | tail -3 | sed 's/^/NOTE job3 journal: /' >>"$R"

PASS=$(grep -c '^PASS' "$R"); FAIL=$(grep -c '^FAIL' "$R")
echo "$PASS/$((PASS + FAIL)) passed, $FAIL failed, 0 errors, 0 skipped"
grep -E '^(FAIL|NOTE)' "$R"
cat "$B/notes.txt"
[ "$FAIL" = 0 ]
