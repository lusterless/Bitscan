#!/bin/bash
# Debconf tests for the agent package (M4 TP-M4-11: CHK-M4-120, CHK-M4-121;
# REQ-107, REQ-106; TS 3.1 L164).
#
# Usage (root): bash deploy/tests/test_debconf.sh [REPO_ROOT]
#
# Expected values come from TS 3.1 L164 and work/tasks.md TASK-096, not from
# the files under test:
# - the four questions bitscan/manager_url, bitscan/enrol_token,
#   bitscan/ca_file, bitscan/manager_spki_sha256; the token is a password
#   question, the others strings; the required inputs carry no default;
# - a preseeded (debconf-set-selections), non-interactive configure runs
#   config without prompting and leaves all four values set and seen;
# - the token is stored only in passwords.dat (root, 0600) of the default
#   debconf split (config.dat / passwords.dat / templates.dat);
# - config never takes a value from an environment variable (REQ-107 (4)) and
#   never sets a value itself.
#
# Isolation: debconf runs on a scratch database (DEBCONF_SYSTEMRC = a copy of
# the host's /etc/debconf.conf with only /var/cache/debconf/ replaced), and the
# whole test runs in a private mount namespace with an overlay on /etc, so the
# fixed paths /etc/bitscan/install.env and /etc/bitscan/agent.yaml can be
# planted without touching the host. Set BITSCAN_TEST_DISPOSABLE=1 to skip the
# namespace inside a throwaway container. The host's debconf database is
# hashed before and after and must be unchanged.
set -u

ROOT=${1:-$(cd "$(dirname "$0")/../.." && pwd)}
CONFIG="$ROOT/deploy/debian/config"
TEMPLATES="$ROOT/deploy/debian/templates"
PROTO="$ROOT/deploy/tests/debconf_protocol.py"

if [ "$(id -u)" != 0 ]; then
    echo "test_debconf.sh: must run as root" >&2
    exit 2
fi

# --- private namespace with an overlay on /etc --------------------------------
if [ -z "${M4B_DEBCONF_INNS:-}" ] && [ "${BITSCAN_TEST_DISPOSABLE:-}" != 1 ]; then
    NS=$(mktemp -d /tmp/m4b-debconf-ns.XXXXXX)
    mkdir "$NS/u" "$NS/w"
    before=$(sha256sum /var/cache/debconf/*.dat 2>/dev/null)
    M4B_DEBCONF_INNS=1 M4B_NS="$NS" unshare --mount --propagation private bash -c '
        mount -t overlay overlay -o "lowerdir=/etc,upperdir=$M4B_NS/u,workdir=$M4B_NS/w" /etc || exit 3
        exec bash "$0" "$1"' "$0" "$ROOT"
    rc=$?
    after=$(sha256sum /var/cache/debconf/*.dat 2>/dev/null)
    rm -rf "$NS"
    if [ "$before" != "$after" ]; then
        echo "FAIL host: /var/cache/debconf changed during the test"
        exit 1
    fi
    echo "PASS host: /var/cache/debconf unchanged (outside the namespace)"
    exit $rc
fi

PASSN=0
FAILN=0
ok() { # ok COND-EXIT-STATUS MESSAGE
    if [ "$1" = 0 ]; then
        PASSN=$((PASSN + 1)); echo "PASS $2"
    else
        FAILN=$((FAILN + 1)); echo "FAIL $2"
    fi
}
check() { # check MESSAGE -- command...
    local msg=$1; shift
    "$@" >/dev/null 2>&1
    ok $? "$msg"
}

W=$(mktemp -d /tmp/m4b-debconf.XXXXXX)
trap 'rm -rf "$W"' EXIT
CAN=CANARY-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
TOKEN="bse_${CAN}AAAAAAAAAAAAAAAAAAAA"      # bse_ + 43 base64url characters
URL="https://mgr.example:8443"
CAFILE="/etc/ssl/certs/bitscan-ca.pem"
PIN="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
QS="bitscan/manager_url bitscan/enrol_token bitscan/ca_file bitscan/manager_spki_sha256"
[ ${#TOKEN} = 47 ] || { echo "test bug: token length ${#TOKEN}"; exit 2; }

rm -rf /etc/bitscan    # inside the overlay (or the disposable container) only

# A scratch debconf database with the host's default split.
newdb() { # newdb NAME -> sets DEBCONF_SYSTEMRC and DB
    DB="$W/$1"
    mkdir -p "$DB"
    sed "s#/var/cache/debconf/#$DB/#g" /etc/debconf.conf >"$W/$1.conf"
    export DEBCONF_SYSTEMRC="$W/$1.conf"
}
loadtemplates() {
    perl -MDebconf::Db -MDebconf::Template -e \
        'Debconf::Db->load; Debconf::Template->load($ARGV[0], $ARGV[1]); Debconf::Db->save' \
        "$TEMPLATES" bitscan-agent
}
preseed() {
    debconf-set-selections <<EOF
bitscan-agent bitscan/manager_url string $URL
bitscan-agent bitscan/enrol_token password $TOKEN
bitscan-agent bitscan/ca_file string $CAFILE
bitscan-agent bitscan/manager_spki_sha256 string $PIN
EOF
}
dc_get() { # dc_get QUESTION -> value (debconf-communicate "0 value")
    printf 'GET %s\n' "$1" | debconf-communicate bitscan-agent 2>/dev/null | sed -n 's/^0 \{0,1\}//p'
}
dc_seen() {
    printf 'FGET %s seen\n' "$1" | debconf-communicate bitscan-agent 2>/dev/null | sed -n 's/^0 \{0,1\}//p'
}
run_config_noninteractive() { # -> rc in CFG_RC, seconds in CFG_S
    local t0=$SECONDS
    DEBCONF_PACKAGE=bitscan-agent DEBIAN_FRONTEND=noninteractive \
        timeout 60 setsid sh "$CONFIG" configure </dev/null >"$W/cfg.out" 2>&1
    CFG_RC=$?
    CFG_S=$((SECONDS - t0))
}
token_files() { # files under the db holding the canary, basenames, sorted
    grep -l -r -F "$CAN" "$DB" 2>/dev/null | xargs -r -n1 basename | sort | tr '\n' ' '
}

echo "== host default debconf split"
check "host /etc/debconf.conf has the passwords database (Accept-Type: password, Mode: 600)" \
    grep -Pzq 'Name: passwords\n(.*\n)*?Mode: 600\n(.*\n)*?Accept-Type: password\n' /etc/debconf.conf
check "host /etc/debconf.conf config database rejects passwords (Reject-Type: password)" \
    grep -q '^Reject-Type: password' /etc/debconf.conf

echo "== CHK-M4-120 templates loaded into debconf"
newdb tpl
loadtemplates
ok $? "templates load into debconf"
# names of every template in the scratch template database (only ours loaded)
names=$(sed -n 's/^Name: //p' "$DB/templates.dat" | sort | tr '\n' ' ')
perl -MDebconf::Db -MDebconf::Template -e '
    Debconf::Db->load;
    for my $n (@ARGV) {
        my $t = Debconf::Template->get($n);
        unless ($t) { print "$n|<missing>|<none>|0|0\n"; next; }
        my $d = $t->default; $d = "<none>" unless defined $d && length $d;
        printf "%s|%s|%s|%s|%s\n", $n, $t->type, $d,
            length($t->description // ""), length($t->extended_description // "");
    }' $QS 2>/dev/null | sort >"$W/tpl.txt"
want=$(printf '%s\n' $QS | sort | tr '\n' ' ')
[ "$names" = "$want" ]; ok $? "exactly the four bitscan/ templates (got: $names)"
ttype() { awk -F'|' -v q="$1" '$1==q{print $2}' "$W/tpl.txt"; }
tdef() { awk -F'|' -v q="$1" '$1==q{print $3}' "$W/tpl.txt"; }
[ "$(ttype bitscan/enrol_token)" = password ]; ok $? "bitscan/enrol_token Type password (got $(ttype bitscan/enrol_token))"
for q in bitscan/manager_url bitscan/ca_file bitscan/manager_spki_sha256; do
    [ "$(ttype $q)" = string ]; ok $? "$q Type string (got $(ttype $q))"
done
while IFS='|' read -r q _ _ dl el; do
    [ "$dl" -gt 0 ] && [ "$el" -gt 0 ]; ok $? "$q has a short and an extended description ($dl, $el chars)"
done <"$W/tpl.txt"
for q in bitscan/manager_url bitscan/enrol_token; do
    [ "$(tdef $q)" = "<none>" ]; ok $? "$q (required input) has no Default (got $(tdef $q))"
done

echo "== CHK-M4-121 preseed first, then templates (TS 3.1 install order), noninteractive configure"
newdb seq_a
preseed; ok $? "debconf-set-selections accepts the preseed"
loadtemplates; ok $? "templates load after the preseed"
run_config_noninteractive
[ "$CFG_RC" = 0 ]; ok $? "config configure exits 0 (rc $CFG_RC, ${CFG_S}s, stdin /dev/null, no tty)"
[ "$CFG_S" -lt 30 ]; ok $? "config does not wait for input (${CFG_S}s < 30s)"
[ "$(dc_get bitscan/manager_url)" = "$URL" ]; ok $? "bitscan/manager_url = $URL"
[ "$(dc_get bitscan/enrol_token)" = "$TOKEN" ]; ok $? "bitscan/enrol_token = the preseeded token"
[ "$(dc_get bitscan/ca_file)" = "$CAFILE" ]; ok $? "bitscan/ca_file = $CAFILE"
[ "$(dc_get bitscan/manager_spki_sha256)" = "$PIN" ]; ok $? "bitscan/manager_spki_sha256 = the pin"
for q in $QS; do
    [ "$(dc_seen $q)" = true ]; ok $? "$q marked seen (got $(dc_seen $q))"
done
tf=$(token_files)
[ "$tf" = "passwords.dat " ]; ok $? "token only in passwords.dat (files with the canary: ${tf:-none})"
st=$(stat -c '%U:%G %a' "$DB/passwords.dat" 2>/dev/null)
[ "$st" = "root:root 600" ]; ok $? "passwords.dat root:root 0600 (got $st)"
st=$(stat -c '%a' "$DB/config.dat" 2>/dev/null)
[ "$st" = 644 ]; ok $? "config.dat 0644 and without the token (got $st)"
! grep -q -F "$CAN" "$W/cfg.out"; ok $? "config output does not contain the token"

echo "== CHK-M4-121 no prompt on an interactive frontend when preseeded (pty probe)"
# teletype frontend on a pseudo-terminal with no input: a shown question
# prints its prompt. Negative control first: unseen questions are shown.
newdb probe_neg
loadtemplates
DEBCONF_PACKAGE=bitscan-agent DEBIAN_FRONTEND=teletype \
    timeout 30 script -qec "sh $CONFIG configure" /dev/null </dev/null >"$W/neg.out" 2>&1
grep -q 'Bitscan manager URL:' "$W/neg.out" && grep -q 'Bitscan enrolment token:' "$W/neg.out"
ok $? "negative control: without a preseed the URL and token prompts are shown"
newdb probe_pos
preseed
loadtemplates
DEBCONF_PACKAGE=bitscan-agent DEBIAN_FRONTEND=teletype \
    timeout 30 script -qec "sh $CONFIG configure" /dev/null </dev/null >"$W/pos.out" 2>&1
pos_rc=$?
[ "$pos_rc" = 0 ]; ok $? "preseeded teletype configure exits 0 (rc $pos_rc)"
! grep -q -E 'Bitscan manager URL:|Bitscan enrolment token:|CA bundle for|Pin of the manager' "$W/pos.out"
ok $? "preseeded: no question is shown (output: $(tr -d '\r' <"$W/pos.out" | head -c 120))"

echo "== CHK-M4-121 templates first, then preseed (re-preseed), token still only in passwords.dat"
newdb seq_b
loadtemplates
preseed
run_config_noninteractive
[ "$CFG_RC" = 0 ]; ok $? "config configure exits 0 (rc $CFG_RC)"
[ "$(dc_get bitscan/enrol_token)" = "$TOKEN" ]; ok $? "bitscan/enrol_token set"
tf=$(token_files)
[ "$tf" = "passwords.dat " ]; ok $? "token only in passwords.dat (files: ${tf:-none})"

echo "== REQ-107 (4): environment variables are not install inputs"
newdb envdb
loadtemplates
BITSCAN_MANAGER_URL=$URL BITSCAN_ENROL_TOKEN=$TOKEN BITSCAN_CA_FILE=$CAFILE \
BITSCAN_MANAGER_SPKI_SHA256=$PIN MANAGER_URL=$URL ENROL_TOKEN=$TOKEN \
bitscan_manager_url=$URL bitscan_enrol_token=$TOKEN \
    run_config_noninteractive
[ "$CFG_RC" = 0 ]; ok $? "config with only environment variables exits 0 (rc $CFG_RC; postinst refuses later)"
for q in $QS; do
    v=$(dc_get $q)
    [ -z "$v" ]; ok $? "$q stays empty with the inputs only in the environment (got '${v}')"
done
tf=$(token_files)
[ -z "$tf" ]; ok $? "token from the environment reaches no debconf file (files: ${tf:-none})"

echo "== config branches through the debconf protocol (no SET, questions shown)"
proto() { # proto ANSWERS-JSON ARG... -> JSON on stdout
    local answers=$1; shift
    python3 -I "$PROTO" "$CONFIG" "$@" --answers "$answers"
}
cmds() { python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(d["rc"]); [print(l) for l in d["log"]]'; }
ALLSEEN='{"values":{"bitscan/manager_url":"'$URL'","bitscan/enrol_token":"'$TOKEN'","bitscan/ca_file":"","bitscan/manager_spki_sha256":""},"seen":{"bitscan/manager_url":true,"bitscan/enrol_token":true,"bitscan/ca_file":true,"bitscan/manager_spki_sha256":true}}'
NONE='{"values":{},"seen":{}}'

proto "$NONE" configure | cmds >"$W/p_first_empty"
[ "$(head -1 "$W/p_first_empty")" = 0 ]; ok $? "first install, no answers: rc 0"
grep -qx 'FSET bitscan/manager_url seen false' "$W/p_first_empty" &&
    grep -qx 'FSET bitscan/enrol_token seen false' "$W/p_first_empty"
ok $? "first install, empty URL and token: their seen flags are reset (asked again)"
for q in "high bitscan/manager_url" "high bitscan/enrol_token" "low bitscan/ca_file" "low bitscan/manager_spki_sha256"; do
    grep -qx "INPUT $q" "$W/p_first_empty"; ok $? "first install: INPUT $q"
done
grep -qE '^GO ?$' "$W/p_first_empty"; ok $? "first install: GO"
! grep -q '^SET ' "$W/p_first_empty"; ok $? "first install: config sets no value"

proto "$ALLSEEN" configure | cmds >"$W/p_first_seed"
[ "$(head -1 "$W/p_first_seed")" = 0 ]; ok $? "first install, preseeded: rc 0"
! grep -q 'seen false' "$W/p_first_seed"; ok $? "first install, preseeded: no seen flag reset"
! grep -q '^SET ' "$W/p_first_seed"; ok $? "first install, preseeded: config sets no value"

mkdir -p /etc/bitscan
printf 'BITSCAN_MANAGER_URL=%s\n' "$URL" >/etc/bitscan/install.env
chmod 600 /etc/bitscan/install.env
proto "$NONE" configure | cmds >"$W/p_env"
[ "$(head -1 "$W/p_env")" = 0 ]; ok $? "install.env present: rc 0"
! grep -q '^INPUT ' "$W/p_env"; ok $? "install.env present: no question asked"
! grep -q '^SET ' "$W/p_env"; ok $? "install.env present: config sets no value"
[ -f /etc/bitscan/install.env ]; ok $? "install.env left for postinst (config does not delete it)"
rm -f /etc/bitscan/install.env

printf 'manager_url: "%s"\n' "$URL" >/etc/bitscan/agent.yaml
proto "$NONE" configure 0.1.0~pre1-1 | cmds >"$W/p_upgrade"
[ "$(head -1 "$W/p_upgrade")" = 0 ]; ok $? "upgrade (agent.yaml present, configure OLDVER): rc 0"
! grep -q '^INPUT ' "$W/p_upgrade"; ok $? "upgrade: no question asked (TS 3.1 L175)"
! grep -q '^SET \|^FSET ' "$W/p_upgrade"; ok $? "upgrade: no value or flag changed"

proto "$NONE" reconfigure 0.1.0~pre1-1 | cmds >"$W/p_reconf"
[ "$(head -1 "$W/p_reconf")" = 0 ]; ok $? "dpkg-reconfigure (agent.yaml present): rc 0"
inputs=$(grep '^INPUT ' "$W/p_reconf" | tr '\n' ';')
[ "$inputs" = "INPUT high bitscan/enrol_token;" ]; ok $? "reconfigure asks only bitscan/enrol_token (#81 (b)) (got: $inputs)"
grep -qE '^GO ?$' "$W/p_reconf"; ok $? "reconfigure: GO"
! grep -q '^SET ' "$W/p_reconf"; ok $? "reconfigure: config sets no value"
rm -rf /etc/bitscan

echo "== static: config is POSIX sh with set -e and no environment input"
check "sh -n config" sh -n "$CONFIG"
if command -v checkbashisms >/dev/null 2>&1; then
    check "checkbashisms config" checkbashisms "$CONFIG"
fi
check "config has set -e" grep -qx 'set -e' "$CONFIG"
! grep -nE '\$\{?(BITSCAN_|MANAGER_|ENROL)' "$CONFIG" >/dev/null; ok $? "config reads no BITSCAN_/MANAGER_/ENROL variable"
! grep -nE '(^|[^_])db_set ' "$CONFIG" >/dev/null; ok $? "config has no db_set"

TOTAL=$((PASSN + FAILN))
if [ "$FAILN" = 0 ]; then
    echo "OK $PASSN/$TOTAL checks passed"
    exit 0
fi
echo "FAIL $PASSN/$TOTAL checks passed, $FAILN failed"
exit 1
