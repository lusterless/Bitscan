#!/bin/bash
# Operations walk (TP-M6-04, TASK-134, REQ-139) on the walked manager host.
# Runs in WSL as root: ops_walk.sh CONTAINER WORK STEP...
#   cert96   #96 fact check: new tls.crt/tls.key, `systemctl reload`; records PID,
#            the credential copy's hash and the leaf a new connection presents
#   cert     §2 as written (cp + restart): a new connection presents the new leaf
#   vault    §3 as written (sudoedit vault.token + restart) with the fake rotated
# Blocks are taken verbatim from deploy/runbooks/manager-operations.md where the
# step has one; WORK holds pki/ and secrets/ from manager_walk.py. Prints
# PASS/FAIL/FACT lines and a total; exit 1 on a FAIL.
set -u
CT=${1:?container}
W=${2:?work}
shift 2
pass=0 fail=0
res() { if [ "$2" = 0 ]; then pass=$((pass + 1)); s=PASS; else fail=$((fail + 1)); s=FAIL; fi; printf '%s %s %s :: %s\n' "$s" "$1" "$3" "$(printf '%s' "$4" | tr '\n' '|' | cut -c1-700)"; }
x() { docker exec -i "$CT" bash -c "$1" 2>&1; }
adm() { docker exec -i -u admin -w /home/admin/rel "$CT" bash -o pipefail -c "$1" 2>&1; }
leaf() { adm 'python3.12 -I /opt/m6b/mgr_api.py tls --host bitscan-mgr.test --ca /home/admin/rel/manager-ca.pem' | awk '/leaf sha256/ {print $3}'; }
fp() { openssl x509 -in "$1" -outform der | sha256sum | cut -c1-64; }
state() { x 'echo "pid=$(systemctl show -p MainPID --value bitscan-manager) cred=$(sha256sum /run/credentials/bitscan-manager.service/tls_cert | cut -c1-16) src=$(sha256sum /etc/bitscan/secrets/tls.crt | cut -c1-16)"'; }
ready() { for _ in $(seq 30); do o=$(adm 'curl -s --cacert manager-ca.pem https://bitscan-mgr.test:8443/readyz'); [ "$o" = '{"status":"ok"}' ] && { echo "$o"; return 0; }; sleep 1; done; echo "${o:-no answer}"; return 1; }

for step in "$@"; do
	case $step in
	cert96)
		old=$(fp "$W/pki/manager.crt") new=$(fp "$W/pki/manager-new.crt")
		before=$(state) l0=$(leaf)
		docker cp "$W/pki/manager-new.crt" "$CT:/home/admin/rel/new-manager.crt"
		docker cp "$W/pki/manager-new.key" "$CT:/home/admin/rel/new-manager.key"
		x 'chown admin:admin /home/admin/rel/new-manager.*; chmod 600 /home/admin/rel/new-manager.key'
		adm 'sudo cp new-manager.crt /etc/bitscan/secrets/tls.crt && sudo cp new-manager.key /etc/bitscan/secrets/tls.key'
		x 'systemctl reload bitscan-manager'
		sleep 3
		after=$(state) l1=$(leaf)
		log=$(x 'journalctl -u bitscan-manager --since "-1min" --no-pager -o cat | grep -iE "tls|certificate|reload" | tail -3')
		echo "FACT CHK-M6-081 #96 systemctl reload on systemd $(x 'systemctl --version | head -1 | cut -d" " -f2'): before [$before leaf ${l0:0:16}] after [$after leaf ${l1:0:16}]; old leaf ${old:0:16}, new leaf ${new:0:16}; journal: $(tr '\n' '|' <<<"$log")"
		if [ "$l1" = "$new" ]; then echo "FACT CHK-M6-081 reload: a new connection presents the NEW certificate"; else echo "FACT CHK-M6-081 reload: a new connection still presents the OLD certificate (credential copy not refreshed)"; fi
		[ "$l0" = "$old" ]
		res CHK-M6-081 $? "before the reload a new connection presents the original leaf" "leaf ${l0:0:16} want ${old:0:16}"
		;;
	cert)
		new=$(fp "$W/pki/manager-new.crt")
		p0=$(x 'systemctl show -p MainPID --value bitscan-manager')
		block=$(awk '/^## 2\./{f=1} f && /^```sh$/{b=1; next} b && /^```$/{exit} b' "$W/tree/deploy/runbooks/manager-operations.md")
		out=$(adm "$block"; echo "rc=$?")
		r=$(ready)
		p1=$(x 'systemctl show -p MainPID --value bitscan-manager') l1=$(leaf)
		modes=$(x 'stat -c "%U:%G %a %n" /etc/bitscan/secrets/tls.crt /etc/bitscan/secrets/tls.key')
		[ "$l1" = "$new" ] && [ "$p0" != "$p1" ] && grep -q 'rc=0' <<<"$out" && [ "$r" = '{"status":"ok"}' ] && [ "$(grep -c '^root:root 600 ' <<<"$modes")" = 2 ]
		res CHK-M6-082 $? "§2 as written (cp onto the 0600 files, restart): a new connection presents the new certificate" "block [$(tr '\n' ';' <<<"$block")] $out; PID $p0 -> $p1; leaf ${l1:0:16} want ${new:0:16}; readyz $r; $modes"
		adm 'rm -f new-manager.key'
		;;
	vault)
		newtok="m6b-vault2-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
		printf '%s\n' "$newtok" >"$W/secrets/vault_token2"
		chmod 600 "$W/secrets/vault_token2"
		# the fake: the new token replaces the old one (create new + revoke old, as OpenBao would
		# end up; the fake reads its token file on every request, the Transit key is unchanged)
		docker cp "$W/secrets/vault_token2" "$CT:/opt/m6b/vault.token"
		x 'chmod 600 /opt/m6b/vault.token'
		pre=$(adm "python3.12 -I - <<'EOF'
import json, sys
sys.path.insert(0, '/opt/m6b')
import mgr_api
st = json.load(open('/home/admin/stage/session.json'))
c = mgr_api.Client('https://bitscan-mgr.test:8443', '/home/admin/rel/manager-ca.pem')
pw = open('/home/admin/stage/admin_pw').read().rstrip('\n')
s, out = c.call('POST', '/api/v1/auth/login', {'username': 'alice', 'password': pw, 'totp_code': mgr_api.next_code(st)}, token='')
json.dump(st, open('/home/admin/stage/session.json', 'w'))
print('login with TOTP, fake rotated, manager still on the old token:', s)
EOF")
		echo "INFO CHK-M6-083 $pre"
		docker cp "$W/secrets/vault_token2" "$CT:/home/admin/stage/vault.token"
		x 'chown admin:admin /home/admin/stage/vault.token; chmod 600 /home/admin/stage/vault.token'
		block=$(awk '/^## 3\./{f=1} f && /^```sh$/{b=1; next} b && /^```$/{exit} b' "$W/tree/deploy/runbooks/manager-operations.md")
		p0=$(x 'systemctl show -p MainPID --value bitscan-manager')
		out=$(docker exec -i -u admin -w /home/admin/rel -e SUDO_EDITOR=/home/admin/bin/m6b-editor -e M6B_STAGE=vault.token "$CT" bash -o pipefail -c "$block" 2>&1; echo "rc=$?")
		r=$(ready)
		p1=$(x 'systemctl show -p MainPID --value bitscan-manager')
		x 'rm -f /home/admin/stage/vault.token'
		pw=$(cat "$W/secrets/admin_pw")
		# a TOTP sign-in needs OpenBao decrypt with the new token
		login=$(adm "python3.12 -I - <<'EOF'
import json, sys, time
sys.path.insert(0, '/opt/m6b')
import mgr_api
st = json.load(open('/home/admin/stage/session.json'))
c = mgr_api.Client('https://bitscan-mgr.test:8443', '/home/admin/rel/manager-ca.pem')
pw = open('/home/admin/stage/admin_pw').read().rstrip('\n')
s, out = c.call('POST', '/api/v1/auth/login', {'username': 'alice', 'password': pw, 'totp_code': mgr_api.next_code(st)}, token='')
json.dump(st, open('/home/admin/stage/session.json', 'w'))
print('login with TOTP after the token change:', s, (out or {}).get('totp_verified') if isinstance(out, dict) else out)
EOF")
		mode=$(x 'stat -c "%U:%G %a" /etc/bitscan/secrets/vault.token; cmp -s /etc/bitscan/secrets/vault.token /opt/m6b/vault.token && echo same-as-fake')
		grep -q 'rc=0' <<<"$out" && [ "$r" = '{"status":"ok"}' ] && [ "$p0" != "$p1" ] && grep -q 'after the token change: 200 True' <<<"$login" && grep -q 'root:root 600' <<<"$mode" && grep -q same-as-fake <<<"$mode"
		res CHK-M6-083 $? "§3 as written (sudoedit vault.token, restart): restarted, /readyz 200, TOTP sign-in decrypts with the new token" "block [$(tr '\n' ';' <<<"$block")] $out; PID $p0 -> $p1; readyz $r; $login; $mode"
		;;
	upgrade)
		# §1 steps 2-4 as written, degenerate upgrade (0.1.1 -> 0.1.0); the agent part is ops_upgrade.py
		mdf="$W/tree/deploy/runbooks/manager-operations.md"
		blk() { python3 -I -c "import re,sys,textwrap; t=open(sys.argv[1]).read(); s=t[t.index('## 1.'):t.index('## 2.')]; b=re.findall(r'^ *\`\`\`sh\n(.*?)^ *\`\`\`\$', s, re.S|re.M); print(textwrap.dedent(b[int(sys.argv[2])]), end='')" "$mdf" "$1"; }
		p0=$(x 'systemctl show -p MainPID --value bitscan-manager')
		out2=$(adm "$(blk 0 | sed 's/0\.1\.1/0.1.0/g')"; echo "rc=$?")
		out3=$(adm "$(blk 1)"; echo "rc=$?")
		out4=$(adm "$(blk 2 | sed 's/mgr\.example/bitscan-mgr.test/g')"; echo "rc=$?")
		p1=$(x 'systemctl show -p MainPID --value bitscan-manager')
		head=$(x 'sudo -u postgres psql -X -At -d bitscan -c "select version_num from alembic_version"')
		# The head of the walked tree's migrations, as manager_walk.py derives it (m0005 to M10, m0006 from TASK-261).
		want_head=$(sed -n 's/^revision: str = "\(m[0-9]*\)"$/\1/p' "$W"/tree/manager/bitscan_manager/db/migrations/versions/m*.py | sort | tail -1)
		grep -q 'rc=0' <<<"$out2" && grep -q 'Successfully installed bitscan-manager-0.1.0' <<<"$out2" && grep -q 'rc=0' <<<"$out3" &&
			grep -q '{"status":"ok"}rc=0$' <<<"$out4" && [ "$p0" != "$p1" ] && [ -n "$want_head" ] && [ "$head" = "$want_head" ]
		res CHK-M6-080 $? "§1 steps 2-4 as written (stop, pip, units, migrate, start, readyz loop)" "step2 $(tail -1 <<<"$out2"); step3 $(tail -1 <<<"$out3"); step4 [$(tail -6 <<<"$out4" | tr '\n' ' ')]; PID $p0 -> $p1; head $head"
		;;
	n4)
		# r5 §4: base backups named and labelled base-<UTC timestamp>; two on the same day; grep and prune (CHK-M6-084-r5)
		mdf="$W/tree/deploy/runbooks/manager-operations.md"
		nth4() { awk -v n="$1" '/^## 4\./{f=1} /^## 5\./{f=0} f && /^ *```sh$/{k++; b=(k==n); next} f && /^ *```$/{b=0} b' "$mdf" | sed 's/^   //'; }
		base=$(nth4 2) prune=$(nth4 3)
		x 'mkdir -p /var/backups/bitscan/old && mv /var/backups/bitscan/base-*.tar.gpg /var/backups/bitscan/r3-old-* /var/backups/bitscan/o2-old-* /var/backups/bitscan/old/ 2>/dev/null; true'
		o1=$(adm "$base"; echo "rc=$?")
		sleep 2
		o2=$(adm "$base"; echo "rc=$?")
		files=$(x 'ls /var/backups/bitscan/ | grep "^base-" | sort')
		f1=$(head -1 <<<"$files") f2=$(tail -1 <<<"$files")
		l1=${f1%.tar.gpg} l2=${f2%.tar.gpg}
		[ "$(grep -c . <<<"$files")" = 2 ] && [ "$f1" != "$f2" ] && grep -q 'rc=0' <<<"$o1" && grep -q 'rc=0' <<<"$o2" && [[ $l1 =~ ^base-[0-9]{8}T[0-9]{6}Z$ ]]
		res CHK-M6-084 $? "r5 two base backups on the same day as written: two files, distinct base-<UTC timestamp> names, no overwrite prompt" "$(tr '\n' ' ' <<<"$files")"
		g=$(adm "$(head -1 <<<"$prune" | sed "s/base-YYYYMMDDTHHMMSSZ/$l2/")")
		n=$(grep -c . <<<"$g")
		keep=$(basename "$(head -1 <<<"$g")")
		lbl=$(x "grep -h '^LABEL:' /var/lib/postgresql/wal-archive/$keep")
		[ "$n" = 1 ] && [ "$lbl" = "LABEL: $l2" ]
		res CHK-M6-084 $? "r5 the grep as written finds exactly one .backup file for the newer label" "grep printed [$g]; its label [$lbl]"
		x "rm /var/backups/bitscan/$f1"
		before=$(x 'ls /var/lib/postgresql/wal-archive | sort')
		dry=$(adm "$(sed -n 2p <<<"$prune" | sed "s/000000010000000000000042.00000028.backup/$keep/")")
		mid=$(x 'ls /var/lib/postgresql/wal-archive | sort')
		po=$(adm "$(sed -n 3p <<<"$prune" | sed "s/000000010000000000000042.00000028.backup/$keep/")"; echo "rc=$?")
		after=$(x 'ls /var/lib/postgresql/wal-archive | sort')
		removed=$(comm -23 <(echo "$before") <(echo "$after") | tr '\n' ' ')
		ks=${keep:0:24}
		bad=$(comm -23 <(echo "$before") <(echo "$after") | awk -v k="$ks" 'substr($0,1,24) >= k')
		[ "$before" = "$mid" ] && [ -n "$removed" ] && [ -z "$bad" ] && grep -q "rc=0" <<<"$po" && grep -qx "$keep" <<<"$after"
		res CHK-M6-084 $? "r5 pruning with that file: dry run changes nothing; the prune removes only segments before $ks" "removed [$removed]; kept $keep; dry run printed $(grep -c . <<<"$dry") lines"
		;;
	removal5)
		# r5 §5: the drain check first (stop, segments, newest audit_id = cursor), then removal (CHK-M6-085-r5)
		mdf="$W/tree/deploy/runbooks/manager-operations.md"
		nth() { awk -v n="$1" '/^## 5\./{f=1} f && /^```sh$/{k++; b=(k==n); next} f && /^```$/{b=0} b' "$mdf"; }
		drain=$(nth 1) b1=$(nth 2) b2=$(nth 3)
		api() { adm "python3.12 -I /opt/m6b/mgr_api.py call --url https://bitscan-mgr.test:8443 --ca /home/admin/rel/manager-ca.pem --state /home/admin/stage/session.json $*"; }
		# a. sink outage: entries queue on disk, then the check as written
		x 'systemctl stop m6b-doubles'
		for v in 311 312 313; do api "PATCH /api/v1/settings --body '{\"job_pull_seconds\": $v}'" >/dev/null; done
		sleep 4
		qa=$(x 'ls /var/lib/bitscan/audit-queue | tr "\n" " "')
		out=$(adm "$drain"; echo "rc=$?")
		grep -q '^not drained' <<<"$out" && ! grep -q '^OK' <<<"$out"
		res CHK-M6-085 $? "r5 drain check as written during a sink outage (entries queued)" "queue [$qa]; $(tr '\n' ' ' <<<"$out")"
		# b. sink back: start the manager, wait a minute, run the block again (the runbook's loop)
		x 'systemd-run --unit m6b-doubles -p WorkingDirectory=/opt/m6b /usr/bin/python3.12 -I /opt/m6b/doubles.py --dir /opt/m6b --cert /opt/m6b/doubles.crt --key /opt/m6b/doubles.key >/dev/null 2>&1; systemctl start bitscan-manager'
		sleep 60
		out=$(adm "$drain"; echo "rc=$?")
		grep -q '^OK' <<<"$out"
		res CHK-M6-085 $? "r5: after 'start the manager, wait a minute, run the block again' the check prints OK" "$(tr '\n' ' ' <<<"$out")"
		# c. cursor behind the newest audit_id with no segment file (a committed row not yet read)
		x 'cp -a /var/lib/bitscan/audit-queue/state.json /root/state.m6b; n=$(sudo -u postgres psql -X -d bitscan -Atc "select max(audit_id) from audit_log"); python3.12 -I -c "import json,sys; p=\"/var/lib/bitscan/audit-queue/state.json\"; d=json.load(open(p)); d[\"cursor\"]=int(sys.argv[1])-1; json.dump(d,open(p,\"w\"))" $n'
		out=$(adm "$drain"; echo "rc=$?")
		x 'cp -a /root/state.m6b /var/lib/bitscan/audit-queue/state.json; rm -f /root/state.m6b'
		grep -q '^not drained' <<<"$out" && grep -q 'segment files: 0' <<<"$out"
		res CHK-M6-085 $? "r5 drain check: cursor one behind the newest audit_id, no segment file -> not drained" "$(tr '\n' ' ' <<<"$out")"
		out=$(adm "$drain"; echo "rc=$?")
		grep -q '^OK' <<<"$out"
		res CHK-M6-085 $? "r5 drain check after restoring state.json -> OK" "$(tr '\n' ' ' <<<"$out")"
		x 'install -o bitscan-manager -g bitscan-manager -m 0600 /dev/null /var/lib/bitscan/audit-queue/segment-000099.jsonl'
		out=$(adm "$drain"; echo "rc=$?")
		x 'rm -f /var/lib/bitscan/audit-queue/segment-000099.jsonl'
		grep -q '^not drained' <<<"$out" && grep -q 'segment files: 1' <<<"$out"
		res CHK-M6-085 $? "r5 drain check with a segment file left (cursor = newest) -> not drained" "$(tr '\n' ' ' <<<"$out")"
		out=$(adm "$b1"; echo "rc=$?")
		left=$(x 'systemctl list-unit-files "bitscan-manager*" --no-legend | wc -l; ps -C python3.12 -o args= | grep -c "/usr/bin/bitscan-manager serve" || true; ls -d /usr/bin/bitscan-manager /opt/bitscan-manager 2>&1 | grep -c "No such"; ls -d /etc/bitscan/manager.env /etc/bitscan/secrets /var/lib/bitscan 2>/dev/null | wc -l')
		read -r nunits nproc nlink nkept <<<"$(tr '\n' ' ' <<<"$left")"
		grep -q 'rc=0' <<<"$out" && [ "$nunits" = 0 ] && [ "$nproc" = 0 ] && [ "$nlink" = 2 ] && [ "$nkept" = 3 ]
		res CHK-M6-085 $? "r5 disable/remove block as written; data kept" "rc $(grep -o 'rc=[0-9]*' <<<"$out"); units $nunits, processes $nproc, link+venv missing $nlink/2, kept $nkept/3"
		out=$(adm "$b2"; echo "rc=$?")
		gone=$(x 'sudo -u postgres psql -X -Atc "select count(*) from pg_database where datname=$(printf "\x27")bitscan$(printf "\x27")"; sudo -u postgres psql -X -Atc "select count(*) from pg_roles where rolname like $(printf "\x27")bitscan%$(printf "\x27")"; ls -d /etc/bitscan/secrets /etc/bitscan/manager.env /var/lib/bitscan 2>/dev/null | wc -l; getent passwd bitscan-manager | wc -l')
		read -r gdb groles gfiles guser <<<"$(tr '\n' ' ' <<<"$gone")"
		grep -q 'rc=0' <<<"$out" && [ "$gdb" = 0 ] && [ "$groles" = 0 ] && [ "$gfiles" = 0 ] && [ "$guser" = 0 ]
		res CHK-M6-085 $? "r5 destroy block as written" "rc $(grep -o 'rc=[0-9]*' <<<"$out"); db $gdb roles $groles files $gfiles user $guser"
		;;
	removal)
		# §5 as written, on a throwaway copy of the host (CHK-M6-085)
		mdf="$W/tree/deploy/runbooks/manager-operations.md"
		b1=$(awk '/^## 5\./{f=1} f && /^```sh$/{n++; b=(n==1); next} f && /^```$/{b=0} b' "$mdf")
		b2=$(awk '/^## 5\./{f=1} f && /^```sh$/{n++; b=(n==2); next} f && /^```$/{b=0} b' "$mdf")
		out=$(adm "$b1"; echo "rc=$?")
		left=$(x 'systemctl list-unit-files "bitscan-manager*" --no-legend | wc -l; ps -C python3.12 -o args= | grep -c "/usr/bin/bitscan-manager serve" || true; ls -d /usr/bin/bitscan-manager /opt/bitscan-manager 2>&1 | grep -c "No such"; ls -d /etc/bitscan/manager.env /etc/bitscan/secrets /var/lib/bitscan 2>/dev/null | wc -l; sudo -u postgres psql -X -Atc "select count(*) from pg_database where datname=$(printf "\x27")bitscan$(printf "\x27")"')
		read -r nunits nproc nlink nkept ndb <<<"$(tr '\n' ' ' <<<"$left")"
		grep -q 'rc=0' <<<"$out" && [ "$nunits" = 0 ] && [ "$nproc" = 0 ] && [ "$nlink" = 2 ] && [ "$nkept" = 3 ] && [ "$ndb" = 1 ]
		res CHK-M6-085 $? "§5 first block as written: units, link and venv gone, no process; database, manager.env, secrets/ and /var/lib/bitscan kept" "block rc: $(grep -o 'rc=[0-9]*' <<<"$out"); unit files $nunits, processes $nproc, link+venv missing $nlink/2, kept $nkept/3, db $ndb"
		qcmd=$(grep -o '`sudo find /var/lib/bitscan/audit-queue[^`]*`' "$mdf" | head -1 | tr -d '`')
		q=$(adm "$qcmd")
		segs=$(x 'find /var/lib/bitscan/audit-queue -name "segment-*.jsonl" | wc -l')
		[ -n "$qcmd" ] && [ -z "$q" ] && [ "$segs" = 0 ]
		res CHK-M6-085 $? "§5 the audit-queue drain check as written prints nothing on a drained queue" "command [$qcmd]; printed [$(tr '\n' ' ' <<<"$q")]; queued segment files: $segs; files present: $(x 'ls /var/lib/bitscan/audit-queue | tr "\n" " "')"
		# control: one queued segment must make the same check print it
		x 'install -o bitscan-manager -g bitscan-manager -m 0600 /dev/null /var/lib/bitscan/audit-queue/segment-000099.jsonl'
		q2=$(adm "$qcmd")
		x 'rm -f /var/lib/bitscan/audit-queue/segment-000099.jsonl'
		grep -q 'segment-000099.jsonl' <<<"$q2"
		res CHK-M6-085 $? "control: with a queued segment file the same check prints it" "$q2"
		out=$(adm "$b2"; echo "rc=$?")
		gone=$(x 'sudo -u postgres psql -X -Atc "select count(*) from pg_database where datname=$(printf "\x27")bitscan$(printf "\x27")"; sudo -u postgres psql -X -Atc "select count(*) from pg_roles where rolname like $(printf "\x27")bitscan%$(printf "\x27")"; ls -d /etc/bitscan/secrets /etc/bitscan/manager.env /var/lib/bitscan 2>/dev/null | wc -l; getent passwd bitscan-manager | wc -l; ls -d /etc/bitscan 2>/dev/null | wc -l')
		read -r gdb groles gfiles guser getc <<<"$(tr '\n' ' ' <<<"$gone")"
		grep -q 'rc=0' <<<"$out" && [ "$gdb" = 0 ] && [ "$groles" = 0 ] && [ "$gfiles" = 0 ] && [ "$guser" = 0 ]
		res CHK-M6-085 $? "§5 destroy block as written: database, four roles, secrets, manager.env, /var/lib/bitscan and the user gone" "rc: $(grep -o 'rc=[0-9]*' <<<"$out"); db $gdb, roles $groles, files $gfiles, user $guser; /etc/bitscan itself still present: $getc (kept for a host with the agent)"
		;;
	*) echo "unknown step $step"; exit 2 ;;
	esac
done
echo "ops_walk: $pass/$((pass + fail)) passed, $fail failed"
[ "$fail" = 0 ]
