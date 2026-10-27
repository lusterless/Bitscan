#!/bin/bash
# README walk for the first release (TP-M6-09 CHK-M6-151; TASK-137, REQ-145 (1)),
# against the walked manager host and the agent host of ops_upgrade.py.
# Runs in WSL as root: readme_walk.sh HOST AGENT TREE RELDIR
# RELDIR is the release folder of the local release run (the 12 files and
# SHA256SUMS). Each line PASS/FAIL names the README statement it checks.
set -u
CT=${1:?host}
AG=${2:?agent host}
TREE=${3:?tree}
REL=${4:?release dir}
pass=0 fail=0
res() { if [ "$2" = 0 ]; then pass=$((pass + 1)); s=PASS; else fail=$((fail + 1)); s=FAIL; fi; printf '%s %s %s :: %s\n' "$s" "$1" "$3" "$(printf '%s' "$4" | tr '\n' '|' | cut -c1-700)"; }
x() { docker exec -i "$CT" bash -c "$1" 2>&1; }
adm() { docker exec -i -u admin -w /home/admin "$CT" bash -c "$1" 2>&1; }
a() { docker exec -i "$AG" bash -c "$1" 2>&1; }
RM="$TREE/README.md"
cmd=$(awk '/^\*\*Verifying downloads\.\*\*/{f=1} f && /^```sh$/{b=1; next} b && /^```$/{exit} b' "$RM")

# "Release files" list vs the release folder
want=$(printf '%s\n' bitscan_manager-0.1.0-py3-none-any.whl bitscan-manager-0.1.0-requirements.txt bitscan-manager.service bitscan-manager-migrate.service \
	bitscan-manager-maintain.service bitscan-manager-maintain.timer bitscan-agent_0.1.0-1_amd64.deb | sort)
got=$(cd "$REL" && ls | grep -v -e '\.cdx\.json$' -e '^SHA256SUMS$' | sort)
sboms=$(cd "$REL" && ls ./*.cdx.json | wc -l)
[ "$want" = "$got" ] && [ "$sboms" = 5 ] && [ "$(awk '{print $2}' "$REL/SHA256SUMS" | sort)" = "$(cd "$REL" && ls | grep -vx SHA256SUMS | sort)" ]
res CHK-M6-151 $? "'Release files': the named manager and agent files, CycloneDX SBOMs, and SHA256SUMS listing every file above" "files [$(tr '\n' ' ' <<<"$got")]; SBOMs $sboms; SHA256SUMS lines $(wc -l <"$REL/SHA256SUMS")"

# "Verifying downloads" on the manager host: the downloaded manager files + the page's SHA256SUMS
x 'rm -rf /home/admin/dl && install -d -o admin -g admin /home/admin/dl /home/admin/dl-empty'
for f in bitscan_manager-0.1.0-py3-none-any.whl bitscan-manager-0.1.0-requirements.txt bitscan-manager.service bitscan-manager-migrate.service \
	bitscan-manager-maintain.service bitscan-manager-maintain.timer SHA256SUMS; do docker cp "$REL/$f" "$CT:/home/admin/dl/$f"; done
docker cp "$REL/SHA256SUMS" "$CT:/home/admin/dl-empty/SHA256SUMS"
x 'chown -R admin:admin /home/admin/dl /home/admin/dl-empty'
out=$(adm "cd dl && $cmd; echo rc=\$?")
[ "$(grep -c ': OK$' <<<"$out")" = 6 ] && grep -q 'rc=0' <<<"$out" && ! grep -q FAILED <<<"$out"
res CHK-M6-151 $? "'Verifying downloads' (the README's command, manager files): each downloaded file OK" "$out"
out=$(adm "cd dl && printf X | dd of=bitscan-manager.service bs=1 seek=0 conv=notrunc status=none && $cmd; echo rc=\$?")
grep -q 'bitscan-manager.service: FAILED' <<<"$out" && grep -q 'rc=1' <<<"$out"
res CHK-M6-151 $? "'Stop if any line says FAILED': a changed file gives FAILED, rc 1" "$out"
out=$(adm "cd dl-empty && $cmd; echo rc=\$?")
grep -q 'no file was verified' <<<"$out" && grep -q 'rc=1' <<<"$out"
res CHK-M6-151 $? "'… or if no file was verified': a folder without the files says so, rc 1" "$out"
x 'rm -rf /home/admin/dl /home/admin/dl-empty'

# Versions
v=$(x '/opt/bitscan-manager/bin/pip show bitscan-manager 2>/dev/null | grep -E "^(Name|Version):" | tr "\n" " "')
d=$(a "dpkg-query -W -f='\${Version}' bitscan-agent")
av=$(adm 'python3.12 -I /opt/m6b/mgr_api.py call --url https://bitscan-mgr.test:8443 --ca /home/admin/rel/manager-ca.pem --state /home/admin/stage/session.json GET /api/v1/agents' | grep -o '"agent_version": "[^"]*"' | sort -u | tr '\n' ' ')
grep -q 'Version: 0.1.0' <<<"$v" && [ "$d" = 0.1.0-1 ] && grep -q '0.1.0-1' <<<"$av"
res CHK-M6-151 $? "'Status' / 'Versions': manager 0.1.0, agent package 0.1.0-1 (semver + Debian revision)" "manager [$v]; agent package [$d]; reported [$av]"

# What the agent package installs and does
u=$(a 'for s in bitscan-agent.service bitscan-runner.socket bitscan-runner.service bitscan-capread.socket bitscan-capread.service; do printf "%s %s %s; " $s $(systemctl is-enabled $s 2>/dev/null || true) $(systemctl is-active $s 2>/dev/null || true); done')
grep -q 'bitscan-agent.service enabled active' <<<"$u" && grep -q 'bitscan-runner.socket enabled active' <<<"$u" && grep -qE 'bitscan-runner.service (static|indirect|disabled) inactive' <<<"$u" &&
	grep -qE 'bitscan-capread.socket disabled inactive' <<<"$u" && grep -qE 'bitscan-capread.service (static|disabled) inactive' <<<"$u"
res CHK-M6-151 $? "'installs the bitscan-agent and bitscan-runner services'; the runner and capread installed but idle" "$u"
aid=$(a 'cat /var/lib/bitscan-agent/agent_id')
det=$(adm "python3.12 -I /opt/m6b/mgr_api.py call --url https://bitscan-mgr.test:8443 --ca /home/admin/rel/manager-ca.pem --state /home/admin/stage/session.json GET /api/v1/agents/$aid")
n=$(a 'dpkg-query -W | wc -l')
grep -q '"status": "online"' <<<"$det" && grep -q '"os_id": "ubuntu"' <<<"$det" && grep -q "\"package_count\": $n" <<<"$det"
res CHK-M6-151 $? "'The agent enrols, sends a heartbeat …, pulls its jobs and uploads the inventory': online, os_info and a snapshot of every dpkg package" "dpkg-query lines $n; $(grep -oE '"(status|os_id|os_version_id|package_count|last_heartbeat_at|last_inventory_at)": [^,}]*' <<<"$det" | tr '\n' ' ')"
res CHK-M6-151 0 "'answers every check of a compliance job with runner_unavailable'" "NOT RUN: 0.1.0 has no policy or scan to make a compliance job (M7+); recorded, not counted as a pass"
pass=$((pass - 1))

# Configuration: units read manager.env and point *_FILE at their copies
e=$(x 'systemctl cat bitscan-manager | grep -E "^(EnvironmentFile|Environment=BITSCAN_.*_FILE)"; pid=$(systemctl show -p MainPID --value bitscan-manager); tr "\0" "\n" </proc/$pid/environ | grep "_FILE="')
grep -q 'EnvironmentFile=/etc/bitscan/manager.env' <<<"$e" && [ "$(grep -c '=/run/credentials/bitscan-manager.service/' <<<"$e")" = 5 ]
res CHK-M6-151 $? "'Configuration': units read /etc/bitscan/manager.env and point the *_FILE variables at their own copies" "$e"

# Starting the app: under the unit the audit-queue folder must exist before the first start
out=$(x 'systemctl stop bitscan-manager; mv /var/lib/bitscan/audit-queue /var/lib/bitscan/audit-queue.m6b; systemctl start bitscan-manager; sleep 2; systemctl show -p ActiveState,Result,ExecMainStatus bitscan-manager | tr "\n" " "; journalctl -u bitscan-manager -n 3 --no-pager -o cat | grep -iE "namespace|No such|226" | head -1; systemctl stop bitscan-manager; systemctl reset-failed bitscan-manager; mv /var/lib/bitscan/audit-queue.m6b /var/lib/bitscan/audit-queue; systemctl start bitscan-manager; for i in $(seq 20); do curl -sf --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/readyz >/dev/null && break; sleep 1; done; echo; systemctl is-active bitscan-manager')
grep -qE 'Result=(exit-code|resources)' <<<"$out" && grep -qiE 'namespace|No such file' <<<"$out" && [ "$(tail -1 <<<"$out")" = active ]
res CHK-M6-151 $? "'Starting the app': under bitscan-manager.service the audit-queue folder must exist before the first start" "$out"

# Certificate reload bullet: SIGHUP reloads the files the process was started with (#96 fact)
out=$(x 'pid=$(systemctl show -p MainPID --value bitscan-manager); h0=$(sha256sum < /run/credentials/bitscan-manager.service/tls_cert); kill -HUP $pid; sleep 2; echo "pid $pid -> $(systemctl show -p MainPID --value bitscan-manager); credential copy unchanged: $([ "$h0" = "$(sha256sum < /run/credentials/bitscan-manager.service/tls_cert)" ] && echo yes)"; journalctl -u bitscan-manager --since -1min -o cat --no-pager | grep -c "tls certificate reloaded"')
grep -q 'unchanged: yes' <<<"$out" && [ "$(tail -1 <<<"$out")" -ge 1 ] && [ "$(sed -n 's/pid \([0-9]*\) -> \([0-9]*\).*/\1 \2/p' <<<"$out" | awk '{print ($1==$2)}')" = 1 ]
res CHK-M6-151 $? "'Certificate reload': SIGHUP reloads the files it was started with, same process; replacing the certificate goes to operations §2" "$out"

# Web UI: the release wheel already contains the built UI, served at /
out=$(adm 'curl -s -o /tmp/idx.html -w "%{http_code} %{content_type}" --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/; echo; unzip -p /home/admin/rel/bitscan_manager-0.1.0-py3-none-any.whl bitscan_manager/webui/index.html 2>/dev/null | cmp - /tmp/idx.html && echo same' 2>&1)
if ! grep -q same <<<"$out"; then out="$out $(adm 'python3.12 -I -c "import zipfile,sys; z=zipfile.ZipFile(\"/home/admin/rel/bitscan_manager-0.1.0-py3-none-any.whl\"); print(\"same\" if z.read(\"bitscan_manager/webui/index.html\")==open(\"/tmp/idx.html\",\"rb\").read() else \"differ\")"')"; fi
grep -q '^200 text/html' <<<"$out" && grep -q same <<<"$out"
res CHK-M6-151 $? "'Web UI': the release wheel contains the built UI; GET / serves its index.html byte for byte" "$out"

echo "readme_walk: $pass/$((pass + fail)) passed, $fail failed (1 NOT RUN)"
[ "$fail" = 0 ]
