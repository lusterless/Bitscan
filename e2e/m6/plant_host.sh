#!/bin/bash
# G48 plants CHK-M6-323..326 (TASK-133 security rows) on the walked manager host.
# Runs in WSL as root: plant_host.sh CONTAINER TREE SECRETS_DIR
# Each plant is made in a throwaway copy (runbook) or in the host's state and
# reverted from a backup taken first; "red" = the named check prints FAIL for
# the planted reason. The clean host is checked green before and after.
set -u
CT=${1:?container}
TREE=${2:?tree}
SECRETS=${3:?secrets dir}
CHECK="bash $TREE/deploy/tests/check_manager_host.sh $CT $TREE $SECRETS"
W=$(mktemp -d /root/m6tb/plant.XXXX)
pass=0 fail=0
verdict() { # verdict CHK WHAT OK EVIDENCE
	if [ "$3" = 0 ]; then pass=$((pass + 1)); s=RED-AS-EXPECTED; else fail=$((fail + 1)); s=NOT-RED; fi
	printf '%s %s %s :: %s\n' "$s" "$1" "$2" "$(printf '%s' "$4" | tr '\n' '|' | cut -c1-500)"
}
x() { docker exec -i "$CT" bash -c "$1" 2>&1; }
restart() { x 'systemctl daemon-reload; systemctl restart bitscan-manager; for i in $(seq 30); do curl -sf --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/readyz >/dev/null && break; sleep 1; done'; }

$CHECK >"$W/clean0.txt" 2>&1
c0=$?
echo "clean host before plants: rc $c0, $(tail -1 "$W/clean0.txt")"
x 'cp -a /etc/bitscan /root/etc-bitscan.bak && cp -a /etc/systemd/system/bitscan-manager.service /root/unit.bak'

# CHK-M6-323: one character of the runbook's Bootstrap block changed
cp "$TREE/deploy/runbooks/manager-install.md" "$W/rb.md"
sed -i 's/^CREATE ROLE bitscan_app LOGIN;$/CREATE ROLE bitscan_app LOGIN:/' "$W/rb.md"
out=$(python3 -I "$TREE/deploy/tests/check_runbook_bootstrap.py" --root "$TREE" --runbook "$W/rb.md" 2>&1)
rc=$?
[ $rc = 1 ] && grep -q 'block line 3' <<<"$out"
verdict CHK-M6-323 "Bootstrap ';' -> ':' on line 3 (check_runbook_bootstrap.py)" $? "rc $rc; $out"

# CHK-M6-324a: the runbook makes /etc/bitscan/secrets 0755 (the planted line run as written)
cp "$TREE/deploy/runbooks/manager-install.md" "$W/rb.md"
sed -i 's|-m 0700 /etc/bitscan/secrets$|-m 0755 /etc/bitscan/secrets|' "$W/rb.md"
line=$(grep -m1 -- '-m 0755 /etc/bitscan/secrets$' "$W/rb.md")
x "cd /home/admin && sudo -u admin bash -c '$line'"
out=$($CHECK 2>&1)
grep -q '^FAIL CHK-M6-047 owners and modes' <<<"$out" && grep -q 'root:root 755 /etc/bitscan/secrets' <<<"$out"
verdict CHK-M6-324 "runbook: secrets/ 0755 -> mode row" $? "$(grep -E '^FAIL' <<<"$out")"
x 'chmod 0700 /etc/bitscan/secrets'

# CHK-M6-324b: the runbook makes manager.env 0644
cp "$TREE/deploy/runbooks/manager-install.md" "$W/rb.md"
sed -i 's|-m 0600 /dev/null /etc/bitscan/manager.env$|-m 0644 /dev/null /etc/bitscan/manager.env|' "$W/rb.md"
line=$(grep -m1 -- '-m 0644 /dev/null /etc/bitscan/manager.env$' "$W/rb.md")
x "cd /home/admin && sudo -u admin bash -c '$line' && cp -a /root/etc-bitscan.bak/manager.env /tmp/env.content && cat /tmp/env.content > /etc/bitscan/manager.env && rm -f /tmp/env.content"
out=$($CHECK 2>&1)
grep -q '^FAIL CHK-M6-047 owners and modes' <<<"$out" && grep -q 'root:root 644 /etc/bitscan/manager.env' <<<"$out"
verdict CHK-M6-324 "runbook: manager.env 0644 -> mode row" $? "$(grep -E '^FAIL' <<<"$out")"
x 'rm -rf /etc/bitscan && cp -a /root/etc-bitscan.bak /etc/bitscan'

# CHK-M6-325: LoadCredential=migrate_dsn added to the installed bitscan-manager.service
x 'sed -i "/^LoadCredential=vault_token:/a LoadCredential=migrate_dsn:/etc/bitscan/secrets/migrate.dsn" /etc/systemd/system/bitscan-manager.service'
restart >/dev/null
out=$($CHECK 2>&1)
grep -q '^FAIL CHK-M6-053 installed units byte-identical' <<<"$out" && grep -q '^FAIL CHK-M6-056 the service.s credentials folder holds exactly' <<<"$out" &&
	grep -q '^FAIL CHK-M6-056 only the migrate and maintain units load migrate_dsn' <<<"$out"
verdict CHK-M6-325 "unit loads migrate_dsn -> verbatim and credential rows" $? "$(grep -E '^FAIL' <<<"$out")"
x 'cp -a /root/unit.bak /etc/systemd/system/bitscan-manager.service'
restart >/dev/null

# CHK-M6-326: ReadWritePaths widened to /var/lib/bitscan
x 'sed -i "s|^ReadWritePaths=.*|ReadWritePaths=/var/lib/bitscan /var/lib/bitscan/bits/uploaded /var/lib/bitscan/audit-queue|" /etc/systemd/system/bitscan-manager.service'
restart >/dev/null
out=$($CHECK 2>&1)
grep -q '^FAIL CHK-M6-053 installed units byte-identical' <<<"$out" && grep -q '^FAIL CHK-M6-055 writable persistent mounts' <<<"$out" && grep -q '/var/lib/bitscan ' <<<"$out"
verdict CHK-M6-326 "ReadWritePaths widened -> verbatim and writable-mount rows" $? "$(grep -E '^FAIL' <<<"$out")"
x 'cp -a /root/unit.bak /etc/systemd/system/bitscan-manager.service'
restart >/dev/null

$CHECK >"$W/clean1.txt" 2>&1
c1=$?
echo "clean host after plants: rc $c1, $(tail -1 "$W/clean1.txt")"
x 'rm -rf /root/etc-bitscan.bak /root/unit.bak'
echo "plants: $pass/$((pass + fail)) red as expected, $fail not red; clean before rc $c0, after rc $c1"
rm -rf "$W"
[ "$fail" = 0 ] && [ "$c0" = 0 ] && [ "$c1" = 0 ]
