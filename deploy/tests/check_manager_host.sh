#!/bin/bash
# REQ-140 checks on an installed manager host (TP-M6-03 CHK-M6-049, -053, -054,
# -056, -057, -058; G48). Runs in WSL as root against a running host container:
#
#   check_manager_host.sh CONTAINER TREE [SECRETS_DIR]
#
# TREE is a copy of the M6 tree (spec and check_units_verbatim.py). SECRETS_DIR
# holds one file per secret value the walk used (database passwords, admin
# password, vault token); the journal canary greps for each value, which is
# copied in for the grep only and removed again. Prints one line per check,
# `PASS|FAIL <check> <what> :: <evidence>`, and a total; exit 1 on any FAIL.
set -u
CT=${1:?container}
TREE=${2:?tree}
SECRETS=${3:-}
pass=0 fail=0
res() { # res CHK OK WHAT EVIDENCE
	if [ "$2" = 0 ]; then pass=$((pass + 1)); s=PASS; else fail=$((fail + 1)); s=FAIL; fi
	printf '%s %s %s :: %s\n' "$s" "$1" "$3" "$(printf '%s' "$4" | tr '\n' '|' | cut -c1-600)"
}
x() { docker exec -i "$CT" bash -c "$1" 2>&1; }

units="bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service bitscan-manager-maintain.timer"

# CHK-M6-053 REQ-140 (1): the installed files against TS §8.7 (check_units_verbatim.py on a copy)
w=$(mktemp -d)
mkdir -p "$w/docs/spec" "$w/deploy/systemd"
cp "$TREE/docs/spec/Technical_Specification.md" "$w/docs/spec/"
for u in $units; do docker cp "$CT:/etc/systemd/system/$u" "$w/deploy/systemd/$u" >/dev/null; done
out=$(python3 -I "$TREE/deploy/tests/check_units_verbatim.py" manager --root "$w" 2>&1)
rc=$?
res CHK-M6-053 $rc "installed units byte-identical to TS §8.7" "$out"
own=$(x "stat -c '%U:%G %a %n' /etc/systemd/system/bitscan-manager*")
[ "$(grep -c '^root:root 644 ' <<<"$own")" = 4 ]
res CHK-M6-053 $? "installed units root:root 0644, exactly four" "$own"
drop=$(x "ls -d /etc/systemd/system/bitscan-manager*.d 2>/dev/null; systemctl show -p DropInPaths --value $units | tr -s ' \n' ' '")
[ -z "$(tr -d ' ' <<<"$drop")" ]
res CHK-M6-053 $? "no drop-in for any manager unit" "[$drop]"
rm -rf "$w"

# CHK-M6-049 REQ-140 (2): systemd-analyze verify with the real binary installed
out=$(x "readlink -f /usr/bin/bitscan-manager; cd /etc/systemd/system && systemd-analyze verify $units 2>&1; echo rc=\$?")
[ "$(tail -1 <<<"$out")" = rc=0 ] && [ "$(wc -l <<<"$out")" = 2 ]
res CHK-M6-049 $? "systemd-analyze verify prints nothing, exit 0 (binary $(head -1 <<<"$out"))" "$out"

# CHK-M6-054 REQ-140 (4)
out=$(x 'pid=$(systemctl show -p MainPID --value bitscan-manager); ps -o user= -p $pid; grep -E "^(Cap(Eff|Prm|Bnd|Amb|Inh)|NoNewPrivs|Seccomp):" /proc/$pid/status')
grep -q '^bitscan-manager$' <<<"$out" && [ "$(grep -cE '^Cap(Eff|Prm|Bnd|Amb):\s+0000000000000000$' <<<"$out")" = 4 ] &&
	grep -qE '^NoNewPrivs:\s+1$' <<<"$out" && grep -qE '^Seccomp:\s+2$' <<<"$out"
res CHK-M6-054 $? "main PID as bitscan-manager, four Cap sets 0, NoNewPrivs 1, seccomp filter on" "$out"
out=$(x 'curl -s -w " %{http_code}" --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/readyz')
[ "$out" = '{"status":"ok"} 200' ]
res CHK-M6-054 $? "/readyz 200 {\"status\":\"ok\"}" "$out"

# CHK-M6-046/-047 REQ-138 (4): owners and modes of TS §8.7 L1344-L1345 (plan TASK-133 §2)
want='root:root 755 /etc/bitscan
root:root 600 /etc/bitscan/manager.env
root:root 700 /etc/bitscan/secrets
root:root 600 /etc/bitscan/secrets/app.dsn
root:root 600 /etc/bitscan/secrets/migrate.dsn
root:root 600 /etc/bitscan/secrets/retention.dsn
root:root 600 /etc/bitscan/secrets/tls.crt
root:root 600 /etc/bitscan/secrets/tls.key
root:root 600 /etc/bitscan/secrets/vault.token
root:root 755 /var/lib/bitscan
root:bitscan-manager 750 /var/lib/bitscan/bits
bitscan-manager:bitscan-manager 750 /var/lib/bitscan/bits/uploaded
bitscan-manager:bitscan-manager 700 /var/lib/bitscan/audit-queue
root:root 755 /opt/bitscan-manager
root:root 777 /usr/bin/bitscan-manager'
got=$(x 'stat -c "%U:%G %a %n" /etc/bitscan /etc/bitscan/manager.env /etc/bitscan/secrets /etc/bitscan/secrets/* /var/lib/bitscan /var/lib/bitscan/bits /var/lib/bitscan/bits/uploaded /var/lib/bitscan/audit-queue /opt/bitscan-manager /usr/bin/bitscan-manager')
[ "$got" = "$want" ]
res CHK-M6-047 $? "owners and modes of /etc/bitscan, secrets, /var/lib/bitscan, the venv and the link" "$(diff <(echo "$want") <(echo "$got") | grep '^[<>]' || echo same)"
# manager-install.md §5: the three required settings, plus only the optional BITSCAN_LISTEN and
# BITSCAN_BITS_DIR the runbook names (M11: test managers set BITSCAN_BITS_DIR, REQ-291); any other
# key, a key given twice or a missing required one is a FAIL
out=$(x 'grep -vE "^\s*(#|$)" /etc/bitscan/manager.env | sed "s/=.*//" | sort | tr "\n" " "; echo; grep -ciE "password|token|dsn|_FILE|secret" /etc/bitscan/manager.env')
keys=$(head -1 <<<"$out" | tr ' ' '\n' | grep -v '^$')
req=$(grep -cxE 'BITSCAN_(AUDIT_SINK|TOTP_KEY_REF|VAULT_ADDR)' <<<"$keys")
extra=$(grep -vxE 'BITSCAN_(AUDIT_SINK|TOTP_KEY_REF|VAULT_ADDR|LISTEN|BITS_DIR)' <<<"$keys" | tr '\n' ' ')
dups=$(uniq -d <<<"$keys" | tr '\n' ' ')
[ "$req" = 3 ] && [ -z "$extra" ] && [ -z "$dups" ] && [ "$(tail -1 <<<"$out")" = 0 ]
res CHK-M6-047 $? "manager.env holds the three required settings and only the optional BITSCAN_LISTEN, BITSCAN_BITS_DIR; no secret or *_FILE" \
	"keys: $(tr '\n' ' ' <<<"$keys"); other keys: [${extra}]; twice: [${dups}]; secret-like lines: $(tail -1 <<<"$out")"

# CHK-M6-055 REQ-140 (5): writable persistent mounts in the service's namespace
# (the last mount of each target wins; API, runtime and private tmp mounts left out)
out=$(x 'pid=$(systemctl show -p MainPID --value bitscan-manager); nsenter -t $pid -m findmnt -rn -o TARGET,OPTIONS |
	awk "{opt[\$1]=\$2} END {for (t in opt) if (opt[t] ~ /^rw/) print t}" |
	grep -Ev "^/(proc|sys|dev|run|tmp|var/tmp)(/|$)" | sort | tr "\n" " "')
[ "$out" = "/var/lib/bitscan/audit-queue /var/lib/bitscan/bits/uploaded " ]
res CHK-M6-055 $? "writable persistent mounts in the service namespace are exactly the two ReadWritePaths" "$out"

# CHK-M6-056 REQ-140 (6): credential isolation
out=$(x 'sudo -u bitscan-manager cat /etc/bitscan/secrets/migrate.dsn 2>&1; echo rc=$?')
grep -q 'Permission denied' <<<"$out" && grep -q 'rc=1' <<<"$out"
res CHK-M6-056 $? "bitscan-manager reading /etc/bitscan/secrets/migrate.dsn is denied" "$out"
out=$(x 'sudo -u bitscan-manager ls /etc/bitscan/secrets 2>&1; echo rc=$?')
grep -q 'Permission denied' <<<"$out"
res CHK-M6-056 $? "bitscan-manager cannot list /etc/bitscan/secrets" "$out"
out=$(x 'ls -1 /run/credentials/bitscan-manager.service | tr "\n" " "')
[ "$out" = "app_dsn retention_dsn tls_cert tls_key vault_token " ]
res CHK-M6-056 $? "the service's credentials folder holds exactly app_dsn retention_dsn tls_cert tls_key vault_token" "$out"
out=$(x 'pid=$(systemctl show -p MainPID --value bitscan-manager); tr "\0" "\n" </proc/$pid/environ | grep "^BITSCAN_" | sed "s/=.*//" | sort | tr "\n" " "; echo; tr "\0" "\n" </proc/$pid/environ | grep "_FILE=" | sort')
! grep -q MIGRATE <<<"$out" && grep -q 'BITSCAN_DB_DSN_FILE=/run/credentials/bitscan-manager.service/app_dsn' <<<"$out"
res CHK-M6-056 $? "the service environment points into its credentials folder and has no migrate DSN" "$out"
out=$(x 'for u in bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service; do printf "%s:" $u; systemctl cat $u | grep -c "^LoadCredential=migrate_dsn:"; done | tr "\n" " "')
[ "$out" = "bitscan-manager.service:0 bitscan-manager-migrate.service:1 bitscan-manager-maintain.service:1 " ]
res CHK-M6-056 $? "only the migrate and maintain units load migrate_dsn (as systemd loaded them)" "$out"
out=$(x 'journalctl -u bitscan-manager-migrate -u bitscan-manager-maintain -o json --no-pager | python3.12 -I -c "import json,sys; e=[json.loads(l) for l in sys.stdin]; print(sorted({x.get(\"_UID\") for x in e if x.get(\"SYSLOG_IDENTIFIER\") == \"bitscan-manager\"}))"; id -u bitscan-manager')
uids=$(head -1 <<<"$out")
mu=$(tail -1 <<<"$out")
! grep -qw "$mu" <<<"$uids" && ! grep -qw "'0'" <<<"$uids" && [ "$uids" != "[]" ]
res CHK-M6-056 $? "migrate and maintain ran as dynamic users (neither root nor bitscan-manager uid $mu)" "$uids"

# CHK-M6-057 REQ-140: server CLI as root reads app.dsn; the service user cannot
out=$(x 'sudo -u bitscan-manager /usr/bin/bitscan-manager users create-admin m6bprobe </dev/null 2>&1 | tail -2; echo rc=${PIPESTATUS[0]}')
! grep -q 'rc=0' <<<"$out"
res CHK-M6-057 $? "the CLI as bitscan-manager cannot read app.dsn (refused, no user made)" "$out"
out=$(x 'sudo -u postgres psql -X -At -d bitscan -c "select username, role from app_user order by username"')
grep -q '^alice|admin$' <<<"$out" && ! grep -q m6bprobe <<<"$out"
res CHK-M6-057 $? "the root CLI created alice (admin); the refused run created nothing" "$out"

# CHK-M6-058 REQ-140 (7): journal canary
out=$(x 'journalctl --no-pager -o cat | grep -Eo "\bbs[uaek]_[A-Za-z0-9_-]{20,}" | head -3; journalctl --no-pager -o cat | grep -c "" ')
toks=$(sed '$d' <<<"$out")
[ -z "$toks" ]
res CHK-M6-058 $? "no bsu_/bsk_/bsa_/bse_ token in the whole journal ($(tail -1 <<<"$out") lines)" "${toks:-none}"
if [ -n "$SECRETS" ]; then
	cat "$SECRETS"/* | docker exec -i "$CT" bash -c 'umask 077; cat > /root/canary.pat'
	docker exec "$CT" bash -c "awk 'NR==2' /etc/bitscan/secrets/tls.key >> /root/canary.pat"
	n=$(x 'wc -l < /root/canary.pat')
	hit=$(x 'journalctl --no-pager -o cat | grep -cFf /root/canary.pat; rm -f /root/canary.pat')
	[ "$hit" = 0 ]
	res CHK-M6-058 $? "no DSN password, admin password, vault token or key text in the journal ($n patterns)" "matching lines: $hit"
else
	res CHK-M6-058 1 "secret canary" "no SECRETS_DIR given"
fi

echo "check_manager_host: $pass/$((pass + fail)) passed, $fail failed"
[ "$fail" = 0 ]
