#!/bin/bash
# Maintainer-script tests for the agent package (M4 TP-M4-15: CHK-M4-165 to
# CHK-M4-177; REQ-108, REQ-107; TS 3.1 L158-L175; #81, #82; decisions
# 2026-10-24: install.env rules (A)-(E), TASK-100 revision 1).
#
# Usage (root, on a disposable host with systemd as PID 1):
#   BITSCAN_TEST_DISPOSABLE=1 bash deploy/tests/test_maintainer_scripts.sh \
#       --deb PATH [SUBCOMMAND...]
# Subcommands, run in the order given (default: all):
#   install missing installenv envvars reinstall upgrade purge reenrol invalid
#   etcperm stringpreseed symlink static all
# Each subcommand starts from a purged state (package purged, bitscan users,
# /etc/bitscan and the package's debconf answers removed); the script purges
# again at the end. It installs packages and creates users, so it refuses to
# run unless BITSCAN_TEST_DISPOSABLE=1. The upgrade test repacks the given
# .deb with a higher version (dpkg-deb only; no build tools).
#
# Exit: 0 all checks passed, 1 a check failed, 2 setup or usage error.
#
# Expected values come from TS 3.1, REQ-107, REQ-108, #81, #82 and the lead's
# rulings, not from the scripts under test.
set -u
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
PATH=/usr/sbin:/usr/bin:/sbin:/bin

usage() { echo "usage: BITSCAN_TEST_DISPOSABLE=1 $0 --deb PATH [SUBCOMMAND...]" >&2; exit 2; }
DEB=
SUBS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --deb) [ $# -ge 2 ] || usage; DEB=$2; shift 2 ;;
        -h | --help) usage ;;
        -*) usage ;;
        *) SUBS+=("$1"); shift ;;
    esac
done
[ -n "$DEB" ] || usage
[ -f "$DEB" ] || { echo "test_maintainer_scripts.sh: no such .deb: $DEB" >&2; exit 2; }
DEB=$(cd "$(dirname "$DEB")" && pwd)/$(basename "$DEB")
[ "${#SUBS[@]}" -gt 0 ] || SUBS=(all)
ALL=(install missing installenv envvars reinstall upgrade purge reenrol invalid etcperm stringpreseed symlink static)
for s in "${SUBS[@]}"; do
    case " ${ALL[*]} all " in *" $s "*) ;; *) echo "unknown subcommand: $s" >&2; usage ;; esac
done
if [ "$(id -u)" != 0 ]; then echo "test_maintainer_scripts.sh: must run as root" >&2; exit 2; fi
if [ "${BITSCAN_TEST_DISPOSABLE:-}" != 1 ]; then
    echo "test_maintainer_scripts.sh: installs and purges bitscan-agent and creates users; set BITSCAN_TEST_DISPOSABLE=1 on a disposable host" >&2
    exit 2
fi
if [ ! -d /run/systemd/system ] || [ "$(cat /proc/1/comm 2>/dev/null)" != systemd ]; then
    echo "test_maintainer_scripts.sh: needs systemd as PID 1" >&2; exit 2
fi
if [ -x /usr/sbin/policy-rc.d ] && ! /usr/sbin/policy-rc.d bitscan-agent.service start >/dev/null 2>&1; then
    echo "test_maintainer_scripts.sh: /usr/sbin/policy-rc.d forbids starting services (a container image default); remove it on this disposable host" >&2
    exit 2
fi
if dpkg-query -W -f='${Status}' bitscan-agent 2>/dev/null | grep -qv 'not-installed'; then
    echo "test_maintainer_scripts.sh: bitscan-agent is already installed here; refusing" >&2; exit 2
fi
if ! command -v debconf-set-selections >/dev/null; then
    apt-get install -y -qq debconf-utils >/dev/null 2>&1 || { echo "debconf-utils missing" >&2; exit 2; }
fi
for t in dpkg dpkg-deb apt-get systemctl journalctl getent stat sha256sum debconf-communicate setsid; do
    command -v "$t" >/dev/null || { echo "missing tool: $t" >&2; exit 2; }
done

W=$(mktemp -d /tmp/m4b-maint.XXXXXX)
SAMPLER=
cleanup() {
    [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null
    reset_host >/dev/null 2>&1
    rm -rf "$W"
}
trap cleanup EXIT

PASSN=0
FAILN=0
ok() {
    if [ "$1" = 0 ]; then PASSN=$((PASSN + 1)); echo "PASS $2"; else FAILN=$((FAILN + 1)); echo "FAIL $2"; fi
}
is() { # is ACTUAL EXPECTED MESSAGE
    [ "$1" = "$2" ]; ok $? "$3 (got '$1', want '$2')"
}

VERSION=$(dpkg-deb -f "$DEB" Version)
URL="https://mgr.example:8443"
PIN=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
# A public root certificate (ISRG Root X1) as the test's CA bundle: the agent
# refuses a ca_file holding no PEM certificate (TASK-089), so the test must
# use a real one.
TEST_CA_PEM='-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----'
write_ca() { mkdir -p /etc/ssl; printf '%s
' "$TEST_CA_PEM" >"$1"; chmod 0644 "$1"; }
newtok() { echo "bse_CANARY-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')AAAAAAAAAAAAAAAAAAAA"; }
canary_of() { echo "$1" | grep -o 'CANARY-[0-9a-f]\{16\}'; }
UNITS="bitscan-agent.service bitscan-runner.socket bitscan-runner.service bitscan-capread.socket bitscan-capread.service"

st() { stat -c '%U:%G %a' "$1" 2>/dev/null || echo absent; }
sha() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }
status() { dpkg-query -W -f='${Status}' bitscan-agent 2>/dev/null; }
enabled() { systemctl is-enabled "$1" 2>/dev/null; }
active() { systemctl is-active "$1" 2>/dev/null; }
inv() { systemctl show -p InvocationID --value bitscan-agent.service 2>/dev/null; }
dc_get() { printf 'GET %s\n' "$1" | debconf-communicate bitscan-agent 2>/dev/null | sed -n 's/^0 \{0,1\}//p'; }
dbfiles_with() { grep -l -r -F "$1" /var/cache/debconf 2>/dev/null | sort | tr '\n' ' '; }

reset_host() {
    systemctl stop $UNITS >/dev/null 2>&1
    dpkg --purge bitscan-agent >/dev/null 2>&1
    rm -rf /etc/bitscan /var/lib/bitscan-agent /run/bitscan
    for u in bitscan-runner bitscan; do
        userdel "$u" >/dev/null 2>&1
        groupdel "$u" >/dev/null 2>&1
    done
    echo PURGE | debconf-communicate bitscan-agent >/dev/null 2>&1
    for q in manager_url enrol_token ca_file manager_spki_sha256; do
        printf 'UNREGISTER bitscan/%s\n' "$q" | debconf-communicate bitscan-agent >/dev/null 2>&1
    done
    rm -f /etc/m4b-victim /etc/ssl/m4b-ca.pem /etc/ssl/m4b-rootonly.pem /tmp/m4b-pwn
    writer_trace_off
    systemctl daemon-reload >/dev/null 2>&1
    systemctl reset-failed >/dev/null 2>&1
}

preseed() { # preseed URL TOKEN [CA] [PIN] (empty values are not preseeded)
    {
        [ -n "$1" ] && echo "bitscan-agent bitscan/manager_url string $1"
        [ -n "$2" ] && echo "bitscan-agent bitscan/enrol_token password $2"
        [ -n "${3:-}" ] && echo "bitscan-agent bitscan/ca_file string $3"
        [ -n "${4:-}" ] && echo "bitscan-agent bitscan/manager_spki_sha256 string $4"
        true
    } | debconf-set-selections
}

sampler_start() { # samples /proc/*/cmdline and environ for $1 while installing
    : >"$W/sampler.hits"
    printf '%s\n' "$1" >"$W/sampler.pat" # the pattern is never on a command line
    (
        while :; do
            grep -a -l -F -f "$W/sampler.pat" /proc/[0-9]*/cmdline /proc/[0-9]*/environ 2>/dev/null |
                grep -v "^/proc/$BASHPID/" >>"$W/sampler.hits"
            sleep 0.02
        done
    ) &
    SAMPLER=$!
}
sampler_stop() { kill "$SAMPLER" 2>/dev/null; wait "$SAMPLER" 2>/dev/null; SAMPLER=; }

# Writer trace (TASK-100 review round 1): enroll.token must be written by a
# process running as bitscan (setpriv), not by root followed by chown. A
# disposable-host wrapper for cat, tee, dd, install, cp and mv is put in
# /usr/local/bin, which setpriv --reset-env puts first on PATH for a regular
# user; this script's own PATH (and so apt's, dpkg's and postinst's as root)
# does not include it. Each wrapped call whose stdout or an argument names
# /var/lib/bitscan-agent/enroll.token* logs "<tool> <uid>" (never the data)
# to /run/m4b-writer.log, then runs the real tool.
WRAP_TOOLS="cat tee dd install cp mv"
writer_trace_on() {
    mkdir -p /usr/local/bin /usr/local/lib
    cat >/usr/local/lib/m4b-wrap <<'EOF'
#!/bin/sh
n=${0##*/}
hit=
case "$(/usr/bin/readlink /proc/$$/fd/1 2>/dev/null)" in /var/lib/bitscan-agent/enroll.token*) hit=1 ;; esac
for a in "$@"; do case "$a" in *enroll.token*) hit=1 ;; esac; done
fd3=n
[ -e /proc/$$/fd/3 ] && fd3=y
[ -n "$hit" ] && echo "$n $(/usr/bin/id -u) fd3=$fd3" >>/run/m4b-writer.log
exec "/usr/bin/$n" "$@"
EOF
    chmod 0755 /usr/local/lib/m4b-wrap
    local t
    for t in $WRAP_TOOLS; do ln -sf /usr/local/lib/m4b-wrap "/usr/local/bin/$t"; done
    : >/run/m4b-writer.log
    chmod 0666 /run/m4b-writer.log
}
writer_trace_off() {
    local t
    for t in $WRAP_TOOLS; do
        [ "$(readlink "/usr/local/bin/$t" 2>/dev/null)" = /usr/local/lib/m4b-wrap ] && rm -f "/usr/local/bin/$t"
    done
    rm -f /usr/local/lib/m4b-wrap /run/m4b-writer.log
}
writer_trace_check() { # writer_trace_check LABEL
    local uid recs writes bad
    uid=$(id -u bitscan 2>/dev/null)
    recs=$(sort /run/m4b-writer.log 2>/dev/null | uniq -c | awk '{print $2 "@" $3 "/" $4 "x" $1}' | tr '\n' ' ')
    writes=$(grep -cE '^(cat|tee|dd|install|cp) ' /run/m4b-writer.log 2>/dev/null)
    [ "${writes:-0}" -ge 1 ]; ok $? "$1: the enroll.token write was observed through the wrapper (records: ${recs:-none})"
    bad=$(awk -v u="$uid" '$2 != u' /run/m4b-writer.log 2>/dev/null | sort -u | tr '\n' ' ')
    [ -n "$uid" ] && [ -z "$bad" ]; ok $? "$1: every process that wrote or renamed enroll.token ran as bitscan (uid $uid; others: ${bad:-none})"
    # TASK-100 r2 (review nit 3): the bitscan child gets no debconf pipe on fd 3
    ! grep -q ' fd3=y$' /run/m4b-writer.log 2>/dev/null; ok $? "$1: the bitscan writer holds no fd 3 (debconf pipe closed)"
    : >/run/m4b-writer.log
}

apt_install() { # apt_install LOG [extra apt args] -> rc in AI_RC
    timeout 300 apt-get install -y --no-install-recommends "$@" </dev/null >"$W/$1.log" 2>&1
    AI_RC=$?
}
install_deb() { # install_deb LOGNAME [DEB] -> AI_RC
    local log=$1 deb=${2:-$DEB}
    timeout 300 setsid apt-get install -y --no-install-recommends "$deb" </dev/null >"$W/$log.log" 2>&1
    AI_RC=$?
    sed -i 's/\r$//' "$W/$log.log" # apt runs dpkg on a pty: CRLF line ends
}
wait_active() { # wait until bitscan-agent.service is active (max 15 s)
    local i
    for i in $(seq 1 30); do [ "$(active bitscan-agent.service)" = active ] && return 0; sleep 0.5; done
    return 1
}
bitscan_lines() { grep -c '^bitscan-agent: ' "$1"; }
no_unit_active() {
    local u bad=
    for u in $UNITS; do [ "$(active "$u")" = active ] && bad="$bad $u"; done
    [ -z "$bad" ]; ok $? "$1: no bitscan unit active (active:${bad:- none})"
}

fresh_install() { # fresh_install TOKEN [CA] [PIN] -> installed with a preseed
    reset_host
    preseed "$URL" "$1" "${2:-}" "${3:-}"
    install_deb "fresh"
}

# plant the files the agent writes after enrolling (TS 3.7 file table), so
# upgrade and purge can be checked against them
plant_enrolled() {
    printf '%s\n' "0b0e5c3a-1a2b-4c3d-8e4f-5a6b7c8d9e0f" >/var/lib/bitscan-agent/agent_id
    chown bitscan:bitscan /var/lib/bitscan-agent/agent_id; chmod 0644 /var/lib/bitscan-agent/agent_id
    printf '%s\n' "bsa_M4BPLANTEDTOKENAAAAAAAAAAAAAAAAAAAAAAAAAAAA" >/var/lib/bitscan-agent/token
    chown bitscan:bitscan /var/lib/bitscan-agent/token; chmod 0600 /var/lib/bitscan-agent/token
    rm -f /var/lib/bitscan-agent/enroll.token
}
snap() { # snap -> one line of owner/mode/hash for agent.yaml, agent_id, token
    local f out=
    for f in /etc/bitscan/agent.yaml /var/lib/bitscan-agent/agent_id /var/lib/bitscan-agent/token; do
        out="$out $(st "$f") $(sha "$f");"
    done
    echo "$out"
}

repack() { # repack VERSION OUT -> a copy of $DEB with another Version
    local d="$W/repack.$$"
    rm -rf "$d"; mkdir -p "$d"
    dpkg-deb -R "$DEB" "$d/x" || return 1
    sed -i "s/^Version: .*/Version: $1/" "$d/x/DEBIAN/control"
    dpkg-deb --root-owner-group -b "$d/x" "$2" >/dev/null || return 1
    rm -rf "$d"
}

# --- CHK-M4-165, -166, -167, -177: fresh install with a preseed ---------------
sub_install() {
    echo "== install (CHK-M4-165, -166, -167, -177)"
    reset_host
    local tok can; tok=$(newtok); can=$(canary_of "$tok")
    preseed "$URL" "$tok"
    writer_trace_on
    sampler_start "$can"
    install_deb install
    sampler_stop
    is "$AI_RC" 0 "apt-get install ./bitscan-agent_${VERSION}_amd64.deb with a preseed exits 0"
    is "$(status)" "install ok installed" "package configured"
    writer_trace_check "install"
    writer_trace_off
    local u
    for u in bitscan bitscan-runner; do
        local pw; pw=$(getent passwd "$u")
        [ -n "$pw" ]; ok $? "user $u exists"
        is "$(echo "$pw" | cut -d: -f7)" /usr/sbin/nologin "$u shell"
        local home; home=$(echo "$pw" | cut -d: -f6)
        [ ! -e "$home" ] && [ "$home" != /home/$u ]; ok $? "$u has no home directory (home field '$home' does not exist)"
        local uid; uid=$(echo "$pw" | cut -d: -f3)
        [ "$uid" -gt 0 ] && [ "$uid" -lt 1000 ]; ok $? "$u is a system user (uid $uid < 1000)"
        getent group "$u" >/dev/null; ok $? "group $u exists"
    done
    is "$(st /etc/bitscan/agent.yaml)" "root:bitscan 640" "agent.yaml owner and mode"
    grep -qx "manager_url: '$URL'" /etc/bitscan/agent.yaml; ok $? "agent.yaml holds the manager URL"
    ! grep -q -F "$can" /etc/bitscan/agent.yaml; ok $? "agent.yaml does not hold the token"
    local keys; keys=$(sed -n 's/^\([a-z_0-9]*\):.*/\1/p' /etc/bitscan/agent.yaml | sort | tr '\n' ' ')
    is "$keys" "ca_file heartbeat_seconds job_pull_seconds log_level manager_spki_sha256 manager_url max_parallel_plugins spool_max_mb state_dir " "agent.yaml has exactly the TS 3.6 keys"
    is "$(st /var/lib/bitscan-agent)" "bitscan:bitscan 700" "/var/lib/bitscan-agent owner and mode"
    is "$(st /var/lib/bitscan-agent/enroll.token)" "bitscan:bitscan 600" "enroll.token owner and mode"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$tok" "enroll.token holds the preseeded token"
    is "$(dc_get bitscan/enrol_token)" "" "db_get bitscan/enrol_token is empty after install (TS L172)"
    is "$(dbfiles_with "$can")" "" "the token is in no debconf file (including *-old backups)"
    is "$(dc_get bitscan/manager_url)" "$URL" "bitscan/manager_url kept in debconf"
    # units (TS 3.1 L159, postinst step 4)
    wait_active
    is "$(enabled bitscan-agent.service)" enabled "bitscan-agent.service enabled"
    is "$(active bitscan-agent.service)" active "bitscan-agent.service active"
    is "$(enabled bitscan-runner.socket)" enabled "bitscan-runner.socket enabled"
    is "$(active bitscan-runner.socket)" active "bitscan-runner.socket active"
    [ "$(enabled bitscan-runner.service)" != enabled ]; ok $? "bitscan-runner.service not enabled (got $(enabled bitscan-runner.service))"
    for u in bitscan-capread.socket bitscan-capread.service; do
        [ "$(enabled $u)" != enabled ]; ok $? "$u not enabled (got $(enabled $u))"
        [ "$(active $u)" != active ]; ok $? "$u not active (got $(active $u))"
        # never started, not even briefly (a static unit started by the
        # debhelper snippet may exit at once and look inactive)
        local inv_id act_ts exit_ts
        inv_id=$(systemctl show -p InvocationID --value "$u" 2>/dev/null)
        act_ts=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$u" 2>/dev/null)
        exit_ts=$(systemctl show -p InactiveExitTimestampMonotonic --value "$u" 2>/dev/null)
        [ -z "$inv_id" ] && [ "${act_ts:-0}" = 0 ] && [ "${exit_ts:-0}" = 0 ]
        ok $? "$u was never started (InvocationID '$inv_id', ActiveEnter $act_ts, InactiveExit $exit_ts)"
    done
    sleep 5
    is "$(systemctl show -p NRestarts --value bitscan-agent.service)" 0 "the agent accepts the agent.yaml postinst wrote (no restart within 5 s)"
    is "$(active bitscan-agent.service)" active "bitscan-agent.service still active after 5 s"
    # CHK-M4-177: the token never shows outside its file
    ! grep -q -F "$can" "$W/install.log"; ok $? "token not in the apt/dpkg/postinst output"
    ! grep -q -F "$can" /var/log/dpkg.log /var/log/apt/term.log /var/log/apt/history.log 2>/dev/null; ok $? "token not in dpkg.log or apt logs"
    ! journalctl --no-pager -o cat 2>/dev/null | grep -q -F "$can"; ok $? "token not in the journal"
    [ ! -s "$W/sampler.hits" ]; ok $? "token in no /proc/*/cmdline or environ during install (hits: $(sort -u "$W/sampler.hits" | head -3 | tr '\n' ' '))"
    local where; where=$(grep -r -l -F "$can" /etc /var/cache /var/log /var/lib /root /tmp /run 2>/dev/null | grep -v "^$W/" | sort | tr '\n' ' ')
    is "$where" "/var/lib/bitscan-agent/enroll.token " "the token is on disk only in enroll.token"
}

# --- CHK-M4-168: a missing URL or token -------------------------------------
missing_case() { # missing_case NAME URL TOKEN EXPECTED-WORD
    reset_host
    preseed "$2" "$3"
    install_deb "missing_$1"
    [ "$AI_RC" != 0 ]; ok $? "$1: apt-get install exits non-zero (rc $AI_RC)"
    is "$(bitscan_lines "$W/missing_$1.log")" 1 "$1: exactly one bitscan-agent: line"
    grep '^bitscan-agent: ' "$W/missing_$1.log" | grep -q -F "$4"; ok $? "$1: the line names $4 ($(grep '^bitscan-agent: ' "$W/missing_$1.log"))"
    is "$(status)" "install ok half-configured" "$1: package half-configured"
    no_unit_active "$1"
    [ ! -e /etc/bitscan/agent.yaml ]; ok $? "$1: no agent.yaml"
    [ ! -e /var/lib/bitscan-agent/enroll.token ]; ok $? "$1: no enroll.token"
}
sub_missing() {
    echo "== missing (CHK-M4-168)"
    local tok; tok=$(newtok)
    missing_case url "" "$tok" "manager URL"
    # recovery: the preseed fixed, then dpkg --configure
    preseed "$URL" ""
    timeout 120 dpkg --configure bitscan-agent </dev/null >"$W/recover.log" 2>&1
    is "$?" 0 "url: after preseeding the URL, dpkg --configure succeeds"
    is "$(status)" "install ok installed" "url: package configured after recovery"
    missing_case token "$URL" "" "enrolment token"
    missing_case both "" "" "manager URL"
}

# --- CHK-M4-169 + rules (A)-(E): /etc/bitscan/install.env ----------------------
envfile() { # envfile MODE OWNER LINES...
    local mode=$1 owner=$2; shift 2
    mkdir -p /etc/bitscan
    printf '%s\n' "$@" >/etc/bitscan/install.env
    chown "$owner" /etc/bitscan/install.env; chmod "$mode" /etc/bitscan/install.env
}
refused_env() { # refused_env NAME EXPECTED-LINE-PART [CANARY-NOT-ECHOED]
    local name=$1 part=$2 hide=${3:-}
    local before; before=$(sha /etc/bitscan/install.env)
    install_deb "env_$name"
    [ "$AI_RC" != 0 ]; ok $? "$name: refused (rc $AI_RC)"
    is "$(bitscan_lines "$W/env_$name.log")" 1 "$name: exactly one bitscan-agent: line"
    grep '^bitscan-agent: ' "$W/env_$name.log" | grep -q -F "$part"; ok $? "$name: line says '$part' ($(grep '^bitscan-agent: ' "$W/env_$name.log"))"
    if [ -n "$hide" ]; then ! grep -q -F "$hide" "$W/env_$name.log"; ok $? "$name: the value is not echoed"; fi
    [ -e /etc/bitscan/install.env ] || [ -L /etc/bitscan/install.env ]; ok $? "$name: install.env left in place"
    is "$(sha /etc/bitscan/install.env)" "$before" "$name: install.env unchanged"
    is "$(status)" "install ok half-configured" "$name: package half-configured"
    no_unit_active "$name"
    [ ! -e /etc/bitscan/agent.yaml ]; ok $? "$name: no agent.yaml"
}
sub_installenv() {
    echo "== installenv (CHK-M4-169; rules A-E; r1)"
    local tok can; tok=$(newtok); can=$(canary_of "$tok")
    reset_host
    write_ca /etc/ssl/m4b-ca.pem
    envfile 600 root:root "# Bitscan install inputs" "" "MANAGER_URL=$URL" "ENROL_TOKEN=$tok" "CA_FILE=/etc/ssl/m4b-ca.pem" "MANAGER_SPKI_SHA256=$PIN"
    install_deb env_good
    is "$AI_RC" 0 "good install.env (root:root 0600, comment and blank line): install exits 0"
    [ ! -e /etc/bitscan/install.env ]; ok $? "install.env deleted after use"
    grep -qx "manager_url: '$URL'" /etc/bitscan/agent.yaml && grep -qx "ca_file: '/etc/ssl/m4b-ca.pem'" /etc/bitscan/agent.yaml &&
        grep -qx "manager_spki_sha256: '$PIN'" /etc/bitscan/agent.yaml
    ok $? "agent.yaml holds the URL, CA file and pin from install.env"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$tok" "enroll.token holds the install.env token"
    is "$(dbfiles_with "$can")" "" "install.env token in no debconf file"
    wait_active; is "$(active bitscan-agent.service)" active "agent active after an install.env install"
    sleep 5
    is "$(systemctl show -p NRestarts --value bitscan-agent.service)" 0 "the agent accepts agent.yaml with the CA file and pin (no restart within 5 s)"

    # (C) the file replaces debconf completely; the debconf token is still cleared
    local tok2 can2; tok2=$(newtok); can2=$(canary_of "$tok2")
    reset_host
    preseed "https://other.example:8443" "$tok2"
    envfile 600 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok"
    install_deb env_over
    is "$AI_RC" 0 "install.env and a preseed: install exits 0"
    grep -qx "manager_url: '$URL'" /etc/bitscan/agent.yaml; ok $? "install.env wins over the preseed (rule C)"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$tok" "enroll.token from install.env, not the preseed"
    is "$(dc_get bitscan/enrol_token)" "" "the preseeded debconf token is cleared too"
    is "$(dbfiles_with "$can2")" "" "the preseeded token is in no debconf file"

    # (A) literal values, never sourced
    reset_host
    envfile 600 root:root 'MANAGER_URL=https://mgr.example:8443/$(id>/tmp/m4b-pwn)`id`' "ENROL_TOKEN=$tok"
    install_deb env_literal
    is "$AI_RC" 0 "a value with \$( ) and backticks is taken literally (install exits 0)"
    [ ! -e /tmp/m4b-pwn ]; ok $? "install.env is never sourced or expanded (no /tmp/m4b-pwn)"
    grep -qF 'manager_url: '"'"'https://mgr.example:8443/$(id>/tmp/m4b-pwn)`id`'"'" /etc/bitscan/agent.yaml; ok $? "agent.yaml holds the value literally"

    # (D) mode, owner, type
    reset_host; envfile 644 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok"
    refused_env mode0644 "must be a regular file owned by root:root with mode 0600"
    reset_host; envfile 640 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok"
    refused_env mode0640 "must be a regular file owned by root:root with mode 0600"
    reset_host; envfile 600 nobody:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok"
    refused_env owner_nobody "must be a regular file owned by root:root with mode 0600"
    reset_host; envfile 600 root:nogroup "MANAGER_URL=$URL" "ENROL_TOKEN=$tok"
    refused_env group_nogroup "must be a regular file owned by root:root with mode 0600"
    reset_host; mkdir -p /etc/bitscan; printf 'MANAGER_URL=%s\nENROL_TOKEN=%s\n' "$URL" "$tok" >/etc/m4b-victim; chmod 600 /etc/m4b-victim
    ln -s /etc/m4b-victim /etc/bitscan/install.env
    refused_env symlink "must be a regular file owned by root:root with mode 0600"
    reset_host; mkdir -p /etc/bitscan; ln -s /nonexistent/m4b /etc/bitscan/install.env
    install_deb env_dangling
    [ "$AI_RC" != 0 ] && grep -q '^bitscan-agent: .*must be a regular file' "$W/env_dangling.log"; ok $? "dangling symlink install.env refused"
    # (B) unknown, duplicate and malformed lines; values never echoed
    reset_host; envfile 600 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok" "EXTRA=$can"
    refused_env unknown_key "unknown key" "$can"
    reset_host; envfile 600 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok" "ENROL_TOKEN=$tok"
    refused_env duplicate_key "a key is given twice" "$can"
    reset_host; envfile 600 root:root "MANAGER_URL=$URL" "ENROL_TOKEN=$tok" "export X"
    refused_env no_equals "every line must be KEY=value" "$can"
    reset_host; envfile 600 root:root "manager_url=$URL" "ENROL_TOKEN=$tok"
    refused_env lowercase_key "unknown key" "$can"
    reset_host; envfile 600 root:root "MANAGER_URL=\"$URL\"" "ENROL_TOKEN=$tok"
    refused_env quoted_value "https:// URL" "$can"
    reset_host; envfile 600 root:root "ENROL_TOKEN=$tok"
    refused_env no_url "manager URL is missing" "$can"

    # (E) + r1: an existing agent.yaml allows only ENROL_TOKEN, keys tracked
    fresh_install "$tok"
    local yaml; yaml=$(sha /etc/bitscan/agent.yaml)
    local etok; etok=$(sha /var/lib/bitscan-agent/enroll.token)
    local new can3; new=$(newtok); can3=$(canary_of "$new")
    e_refused() { # e_refused NAME LINES...
        local n=$1; shift
        envfile 600 root:root "$@"
        local before; before=$(sha /etc/bitscan/install.env)
        timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/e_$n.log" 2>&1
        local rc=$?
        [ "$rc" != 0 ]; ok $? "E/$n: dpkg-reconfigure refused (rc $rc)"
        grep -q '^bitscan-agent: .*may hold only ENROL_TOKEN once agent.yaml exists' "$W/e_$n.log"; ok $? "E/$n: fixed line ($(grep '^bitscan-agent: ' "$W/e_$n.log" | head -1))"
        ! grep -q -F "$can3" "$W/e_$n.log"; ok $? "E/$n: value not echoed"
        is "$(sha /etc/bitscan/install.env)" "$before" "E/$n: install.env left unchanged"
        is "$(sha /etc/bitscan/agent.yaml)" "$yaml" "E/$n: agent.yaml unchanged"
        is "$(sha /var/lib/bitscan-agent/enroll.token)" "$etok" "E/$n: enroll.token not rewritten"
        rm -f /etc/bitscan/install.env
        timeout 120 dpkg --configure -a </dev/null >/dev/null 2>&1
    }
    e_refused url_changed "MANAGER_URL=https://other.example:8443"
    e_refused url_empty "MANAGER_URL="
    e_refused token_and_empty_ca "ENROL_TOKEN=$new" "CA_FILE="
    e_refused empty_pin "MANAGER_SPKI_SHA256="
    envfile 600 root:root "# only a new token" "ENROL_TOKEN=$new"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/e_ok.log" 2>&1
    is "$?" 0 "E: install.env with only ENROL_TOKEN accepted on a configured host"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token)" "$new" "E: enroll.token holds the new token"
    [ ! -e /etc/bitscan/install.env ]; ok $? "E: install.env deleted after use"
    is "$(sha /etc/bitscan/agent.yaml)" "$yaml" "E: agent.yaml unchanged"
    envfile 600 root:root "# nothing"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/e_empty.log" 2>&1
    is "$?" 0 "E: an install.env with no key is accepted and changes nothing"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token)" "$new" "E: enroll.token unchanged by an empty install.env"
    [ ! -e /etc/bitscan/install.env ]; ok $? "E: the empty install.env is deleted"
}

# --- CHK-M4-170: environment variables are not inputs ------------------------
sub_envvars() {
    echo "== envvars (CHK-M4-170)"
    reset_host
    local tok can; tok=$(newtok); can=$(canary_of "$tok")
    timeout 300 env BITSCAN_ENROL_TOKEN="$tok" BITSCAN_MANAGER_URL="$URL" MANAGER_URL="$URL" ENROL_TOKEN="$tok" \
        BITSCAN_CA_FILE=/etc/ssl/certs/ca-certificates.crt MANAGER_SPKI_SHA256="$PIN" \
        bitscan_manager_url="$URL" bitscan_enrol_token="$tok" DEBCONF_ENROL_TOKEN="$tok" \
        setsid apt-get install -y --no-install-recommends "$DEB" </dev/null >"$W/envvars.log" 2>&1
    local rc=$?
    [ "$rc" != 0 ]; ok $? "install with the inputs only in environment variables fails (rc $rc)"
    grep '^bitscan-agent: ' "$W/envvars.log" | grep -q 'manager URL is missing'; ok $? "it fails as 'missing' ($(grep '^bitscan-agent: ' "$W/envvars.log"))"
    is "$(status)" "install ok half-configured" "package half-configured"
    [ ! -e /var/lib/bitscan-agent/enroll.token ] && [ ! -e /etc/bitscan/agent.yaml ]; ok $? "no enroll.token and no agent.yaml"
    is "$(dbfiles_with "$can")" "" "the environment token reached no debconf file"
    ! grep -q -F "$can" "$W/envvars.log"; ok $? "the environment token is not echoed"
}

# --- CHK-M4-171: reinstall twice ---------------------------------------------
sub_reinstall() {
    echo "== reinstall (CHK-M4-171)"
    local tok; tok=$(newtok)
    fresh_install "$tok"
    is "$AI_RC" 0 "fresh install"
    wait_active
    plant_enrolled
    local before; before=$(snap)
    local i
    for i in 1 2; do
        timeout 300 setsid apt-get install -y --reinstall --no-install-recommends "$DEB" </dev/null >"$W/reinstall$i.log" 2>&1
        is "$?" 0 "reinstall $i exits 0"
        is "$(snap)" "$before" "reinstall $i: agent.yaml, agent_id, token byte-identical with the same owner and mode"
        [ ! -e /var/lib/bitscan-agent/enroll.token ]; ok $? "reinstall $i: no enroll.token written"
        is "$(status)" "install ok installed" "reinstall $i: configured"
    done
    wait_active; is "$(active bitscan-agent.service)" active "agent active after the reinstalls"
    for i in 1 2; do
        timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/reconf$i.log" 2>&1
        is "$?" 0 "dpkg-reconfigure $i without a new token exits 0"
        is "$(snap)" "$before" "dpkg-reconfigure $i: nothing changed"
    done
}

# --- CHK-M4-172: upgrade to a newer 0.x twice --------------------------------
sub_upgrade() {
    echo "== upgrade (CHK-M4-172)"
    local v1="${VERSION}+m4b1" v2="${VERSION}+m4b2"
    repack "$v1" "$W/up1.deb" && repack "$v2" "$W/up2.deb"; ok $? "repacked $v1 and $v2"
    dpkg --compare-versions "$v1" gt "$VERSION" && dpkg --compare-versions "$v2" gt "$v1"; ok $? "repacked versions sort higher"
    local tok; tok=$(newtok)
    fresh_install "$tok"
    wait_active
    plant_enrolled
    timeout 30 systemctl restart bitscan-agent.service; wait_active
    local before; before=$(snap)
    local deb ver i=0
    for ver in "$v1" "$v2"; do
        i=$((i + 1)); deb="$W/up$i.deb"
        local inv0; inv0=$(inv)
        timeout 300 setsid apt-get install -y --no-install-recommends "$deb" </dev/null >"$W/upgrade$i.log" 2>&1
        is "$?" 0 "upgrade $i to $ver exits 0 with no input"
        is "$(dpkg-query -W -f='${Version}' bitscan-agent)" "$ver" "upgrade $i: version $ver installed"
        is "$(snap)" "$before" "upgrade $i: agent.yaml, agent_id, token byte-identical (owner, mode, sha256)"
        [ ! -e /var/lib/bitscan-agent/enroll.token ]; ok $? "upgrade $i: no enroll.token written"
        wait_active
        local inv1; inv1=$(inv)
        [ -n "$inv1" ] && [ "$inv1" != "$inv0" ]; ok $? "upgrade $i: bitscan-agent.service restarted (new InvocationID)"
        is "$(active bitscan-runner.socket)" active "upgrade $i: runner socket active"
        ! grep -q '^bitscan-agent: ' "$W/upgrade$i.log"; ok $? "upgrade $i: no bitscan-agent error line"
    done
}

# --- CHK-M4-173: remove and purge twice (#82) ----------------------------------
sub_purge() {
    echo "== purge (CHK-M4-173, #82)"
    local tok; tok=$(newtok)
    fresh_install "$tok"
    wait_active
    plant_enrolled
    mkdir -p /etc/bitscan/secrets
    printf 'MANAGER=1\n' >/etc/bitscan/manager.env; printf 'secret\n' >/etc/bitscan/secrets/x
    local menv; menv=$(sha /etc/bitscan/manager.env)
    local i
    for i in 1 2; do
        timeout 300 apt-get remove -y bitscan-agent </dev/null >"$W/remove$i.log" 2>&1
        is "$?" 0 "apt-get remove $i exits 0"
    done
    for u in bitscan-agent.service bitscan-runner.socket; do
        [ "$(active $u)" != active ]; ok $? "after remove: $u stopped (got $(active $u))"
        [ "$(enabled $u)" != enabled ]; ok $? "after remove: $u not enabled (got $(enabled $u))"
    done
    [ -f /etc/bitscan/agent.yaml ] && [ -f /var/lib/bitscan-agent/agent_id ] && [ -f /var/lib/bitscan-agent/token ]
    ok $? "after remove: agent.yaml and the state are kept"
    is "$(status)" "deinstall ok config-files" "after remove: config-files state"
    timeout 300 apt-get purge -y bitscan-agent </dev/null >"$W/purge1.log" 2>&1
    is "$?" 0 "apt-get purge exits 0"
    timeout 60 dpkg --purge bitscan-agent >"$W/purge2.log" 2>&1
    is "$?" 0 "a second purge (dpkg --purge; apt no longer knows the package) exits 0"
    [ ! -e /var/lib/bitscan-agent ]; ok $? "purge: /var/lib/bitscan-agent removed"
    [ ! -e /etc/bitscan/agent.yaml ]; ok $? "purge: agent.yaml removed"
    is "$(sha /etc/bitscan/manager.env)" "$menv" "purge: a planted /etc/bitscan/manager.env survives unchanged"
    is "$(cat /etc/bitscan/secrets/x 2>/dev/null)" secret "purge: /etc/bitscan/secrets/x survives"
    [ -d /etc/bitscan ]; ok $? "purge: /etc/bitscan kept while not empty"
    is "$(debconf-show bitscan-agent 2>/dev/null | wc -l)" 0 "purge: the package's debconf answers are purged"
    getent passwd bitscan >/dev/null && getent passwd bitscan-runner >/dev/null; ok $? "purge: the users are kept"
    [ ! -e /etc/systemd/system/multi-user.target.wants/bitscan-agent.service ] && [ ! -e /etc/systemd/system/sockets.target.wants/bitscan-runner.socket ]
    ok $? "purge: no enablement symlinks left"
    # postrm purge itself, run twice in a row on a host where it already ran
    rm -rf "$W/ctlp"; dpkg-deb -e "$DEB" "$W/ctlp"
    for i in 1 2; do
        DPKG_MAINTSCRIPT_PACKAGE=bitscan-agent DPKG_MAINTSCRIPT_NAME=postrm DEBCONF_PACKAGE=bitscan-agent sh "$W/ctlp/postrm" purge >"$W/postrm$i.log" 2>&1
        is "$?" 0 "postrm purge run directly, time $i, exits 0"
    done
    is "$(sha /etc/bitscan/manager.env)" "$menv" "postrm purge twice: manager.env still unchanged"
    # without foreign files /etc/bitscan goes; a leftover install.env is removed
    fresh_install "$tok"
    mkdir -p /etc/bitscan; printf 'X=1\n' >/etc/bitscan/install.env; chmod 644 /etc/bitscan/install.env
    timeout 300 apt-get purge -y bitscan-agent </dev/null >"$W/purge4.log" 2>&1
    is "$?" 0 "purge with a leftover install.env exits 0"
    [ ! -e /etc/bitscan ]; ok $? "purge: an empty /etc/bitscan is removed (install.env removed too)"
}

# --- CHK-M4-174: #81 re-enrolment ----------------------------------------------
sub_reenrol() {
    echo "== reenrol (CHK-M4-174, #81 (b))"
    local tok; tok=$(newtok)
    fresh_install "$tok"
    wait_active
    plant_enrolled
    timeout 30 systemctl restart bitscan-agent.service; wait_active
    local yaml; yaml=$(sha /etc/bitscan/agent.yaml)
    local new can; new=$(newtok); can=$(canary_of "$new")
    local inv0; inv0=$(inv)
    preseed "" "$new"
    writer_trace_on
    sampler_start "$can"
    timeout 120 setsid dpkg-reconfigure bitscan-agent </dev/null >"$W/reenrol.log" 2>&1
    local rc=$?
    sampler_stop
    is "$rc" 0 "dpkg-reconfigure with a new preseeded token exits 0"
    writer_trace_check "re-enrolment"
    writer_trace_off
    is "$(st /var/lib/bitscan-agent/enroll.token)" "bitscan:bitscan 600" "enroll.token written bitscan:bitscan 0600"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$new" "enroll.token holds the new token"
    is "$(sha /etc/bitscan/agent.yaml)" "$yaml" "agent.yaml unchanged"
    wait_active
    local inv1; inv1=$(inv)
    [ -n "$inv1" ] && [ "$inv1" != "$inv0" ]; ok $? "the agent was restarted (new InvocationID)"
    is "$(dc_get bitscan/enrol_token)" "" "the debconf token is cleared"
    is "$(dbfiles_with "$can")" "" "the new token is in no debconf file"
    ! grep -q -F "$can" "$W/reenrol.log"; ok $? "the new token is not in the output"
    [ ! -s "$W/sampler.hits" ]; ok $? "the new token in no /proc/*/cmdline or environ"
    # through install.env
    local new2; new2=$(newtok)
    envfile 600 root:root "ENROL_TOKEN=$new2"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/reenrol2.log" 2>&1
    is "$?" 0 "re-enrolment through install.env exits 0"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$new2" "enroll.token holds the install.env token"
    [ ! -e /etc/bitscan/install.env ]; ok $? "install.env deleted"
    # an invalid new token is refused and the old enroll.token stays
    local before; before=$(sha /var/lib/bitscan-agent/enroll.token)
    preseed "" "bse_short"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/reenrol3.log" 2>&1
    local rc3=$?
    [ "$rc3" != 0 ]; ok $? "an invalid re-enrolment token is refused (rc $rc3)"
    grep -q '^bitscan-agent: .*bse_ enrolment token' "$W/reenrol3.log"; ok $? "with the token line ($(grep '^bitscan-agent: ' "$W/reenrol3.log"))"
    is "$(sha /var/lib/bitscan-agent/enroll.token)" "$before" "enroll.token unchanged after the refusal"
    preseed "" "$(newtok)"
    timeout 120 dpkg --configure -a </dev/null >/dev/null 2>&1
}

# --- CHK-M4-175: input validation ----------------------------------------------
invalid_case() { # invalid_case NAME URL TOKEN CA PIN EXPECTED-PART
    reset_host
    preseed "$2" "$3" "$4" "$5"
    install_deb "inv_$1"
    [ "$AI_RC" != 0 ]; ok $? "$1: refused (rc $AI_RC)"
    is "$(bitscan_lines "$W/inv_$1.log")" 1 "$1: one bitscan-agent: line"
    grep '^bitscan-agent: ' "$W/inv_$1.log" | grep -q -F "$6"; ok $? "$1: line says '$6' ($(grep '^bitscan-agent: ' "$W/inv_$1.log"))"
    local c; c=$(canary_of "$3")
    if [ -n "$c" ]; then ! grep -q -F "$c" "$W/inv_$1.log"; ok $? "$1: the token is not echoed"; fi
    is "$(status)" "install ok half-configured" "$1: half-configured"
    [ ! -e /etc/bitscan/agent.yaml ] && [ ! -e /var/lib/bitscan-agent/enroll.token ]; ok $? "$1: nothing written"
    no_unit_active "$1"
}
sub_invalid() {
    echo "== invalid (CHK-M4-175)"
    local tok; tok=$(newtok)
    local U="https:// URL" T="bse_ enrolment token" C="CA file" P="key pin"
    invalid_case url_http "http://mgr.example:8443" "$tok" "" "" "$U"
    invalid_case url_nohost "https://" "$tok" "" "" "$U"
    invalid_case url_slash "https:///x" "$tok" "" "" "$U"
    invalid_case url_userinfo "https://@mgr.example" "$tok" "" "" "$U"
    invalid_case url_space "https://mgr.example/a b" "$tok" "" "" "$U"
    invalid_case url_quote "https://mgr.example/a'b" "$tok" "" "" "$U"
    invalid_case url_ftp "ftp://mgr.example" "$tok" "" "" "$U"
    invalid_case token_bsa "$URL" "bsa_${tok#bse_}" "" "" "$T"
    invalid_case token_42 "$URL" "${tok%A}" "" "" "$T"
    invalid_case token_44 "$URL" "${tok}A" "" "" "$T"
    invalid_case token_eq "$URL" "${tok%A}=" "" "" "$T"
    invalid_case token_dot "$URL" "${tok%A}." "" "" "$T"
    invalid_case token_upper_prefix "$URL" "BSE_${tok#bse_}" "" "" "$T"
    invalid_case ca_missing "$URL" "$tok" "/etc/ssl/m4b-missing.pem" "" "$C"
    invalid_case ca_relative "$URL" "$tok" "etc/ssl/m4b-ca.pem" "" "$C"
    invalid_case ca_dir "$URL" "$tok" "/etc/ssl/certs" "" "$C"
    reset_host; mkdir -p /etc/ssl; printf 'x\n' >/etc/ssl/m4b-rootonly.pem; chmod 0600 /etc/ssl/m4b-rootonly.pem
    preseed "$URL" "$tok" "/etc/ssl/m4b-rootonly.pem" ""
    install_deb inv_ca_rootonly
    [ "$AI_RC" != 0 ] && grep -q '^bitscan-agent: .*CA file' "$W/inv_ca_rootonly.log"; ok $? "ca_rootonly: a CA file bitscan cannot read is refused"
    invalid_case pin_63 "$URL" "$tok" "" "${PIN%f}" "$P"
    invalid_case pin_65 "$URL" "$tok" "" "${PIN}0" "$P"
    invalid_case pin_nonhex "$URL" "$tok" "" "${PIN%f}g" "$P"
    invalid_case pin_colons "$URL" "$tok" "" "01:23:45:67:89:ab:cd:ef:01:23:45:67:89:ab:cd:ef:01:23:45:67:89:ab" "$P"
    # accepted boundaries
    reset_host
    write_ca /etc/ssl/m4b-ca.pem
    preseed "HTTPS://MGR.example:8443" "$tok" "/etc/ssl/m4b-ca.pem" "$(echo "$PIN" | tr a-f A-F)"
    install_deb inv_ok
    is "$AI_RC" 0 "accepted: uppercase scheme, a readable CA bundle, an uppercase 64-hex pin"
    [ "$AI_RC" = 0 ] || grep '^bitscan-agent: ' "$W/inv_ok.log" | sed 's/^/     | /'
    wait_active; sleep 5
    is "$(systemctl show -p NRestarts --value bitscan-agent.service)" 0 "the agent accepts that agent.yaml (no restart within 5 s)"
}

# --- TASK-100 r1: /etc/bitscan owner and mode ----------------------------------
etc_refused() { # etc_refused NAME
    install_deb "etc_$1"
    [ "$AI_RC" != 0 ]; ok $? "$1: install refused (rc $AI_RC)"
    grep -qx 'bitscan-agent: /etc/bitscan must be a directory owned by root and not writable by group or others' "$W/etc_$1.log"
    ok $? "$1: the fixed /etc/bitscan line (got: $(grep '^bitscan-agent: ' "$W/etc_$1.log" | head -1 | cat -A | head -c 200))"
    is "$(bitscan_lines "$W/etc_$1.log")" 1 "$1: one bitscan-agent: line"
    is "$(status)" "install ok half-configured" "$1: half-configured"
    no_unit_active "$1"
    [ ! -e /var/lib/bitscan-agent/enroll.token ]; ok $? "$1: no enroll.token"
}
sub_etcperm() {
    echo "== etcperm (TASK-100 r1)"
    local tok; tok=$(newtok)
    local m
    for m in 775 757 777 1777 765 735 0757; do
        reset_host; preseed "$URL" "$tok"; install -d -m "$m" /etc/bitscan; chmod "$m" /etc/bitscan
        etc_refused "mode_$m"
    done
    reset_host; preseed "$URL" "$tok"; install -d -m 755 /etc/bitscan; chown 1000 /etc/bitscan
    etc_refused owner_uid1000
    reset_host; preseed "$URL" "$tok"; mkdir -p /etc/m4b-realdir; chmod 755 /etc/m4b-realdir; ln -s /etc/m4b-realdir /etc/bitscan
    etc_refused symlink_to_root_dir
    [ ! -e /etc/m4b-realdir/agent.yaml ]; ok $? "symlink_to_root_dir: nothing written through the link"
    rm -f /etc/bitscan; rm -rf /etc/m4b-realdir
    reset_host; preseed "$URL" "$tok"; printf 'x\n' >/etc/bitscan
    etc_refused regular_file
    reset_host; preseed "$URL" "$tok"; ln -s /nonexistent/m4b /etc/bitscan
    etc_refused dangling_symlink
    rm -f /etc/bitscan
    # recovery: root 0755 then dpkg --configure
    reset_host; preseed "$URL" "$tok"; install -d -m 775 /etc/bitscan
    install_deb etc_recover0
    chmod 755 /etc/bitscan
    timeout 120 dpkg --configure bitscan-agent </dev/null >"$W/etc_recover.log" 2>&1
    is "$?" 0 "after chmod 0755, dpkg --configure succeeds"
    is "$(status)" "install ok installed" "configured after recovery"
    # tampered after install: every configure is blocked
    chmod 775 /etc/bitscan
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/etc_tamper.log" 2>&1
    local rc=$?
    [ "$rc" != 0 ] && grep -q '^bitscan-agent: /etc/bitscan must be' "$W/etc_tamper.log"; ok $? "a group-writable /etc/bitscan blocks dpkg-reconfigure (rc $rc)"
    chmod 755 /etc/bitscan
    timeout 120 dpkg --configure -a </dev/null >/dev/null 2>&1
    # accepted modes and a non-root group
    for m in 750 700 2755 1755 755; do
        reset_host; preseed "$URL" "$tok"; install -d -m "$m" /etc/bitscan; chmod "$m" /etc/bitscan
        install_deb "etc_ok_$m"
        is "$AI_RC" 0 "existing /etc/bitscan root $m accepted"
        is "$(stat -c '%u %a' /etc/bitscan)" "0 $(echo $m | sed 's/^0*//')" "existing /etc/bitscan $m kept as it was"
    done
    reset_host; preseed "$URL" "$tok"; install -d -m 750 -g nogroup /etc/bitscan
    install_deb etc_ok_group
    is "$AI_RC" 0 "existing /etc/bitscan root:nogroup 0750 accepted (group not checked)"
}

# --- main's request: a token preseeded with the wrong type -------------------
sub_stringpreseed() {
    echo "== stringpreseed (REQ-107 (3) with a 'string' preseed of the token)"
    local tok can; tok=$(newtok); can=$(canary_of "$tok")
    reset_host
    printf 'bitscan-agent bitscan/manager_url string %s\nbitscan-agent bitscan/enrol_token string %s\n' "$URL" "$tok" | debconf-set-selections
    local pre; pre=$(dbfiles_with "$can")
    echo "     (before install, the canary is in: ${pre:-none})"
    install_deb stringpreseed
    is "$AI_RC" 0 "install with the token preseeded as 'string' exits 0"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token 2>/dev/null)" "$tok" "enroll.token holds the token"
    is "$(dc_get bitscan/enrol_token)" "" "db_get bitscan/enrol_token is empty after install"
    # main's check: config.dat (0644) must not hold the token after install
    ! grep -q -F "$can" /var/cache/debconf/config.dat; ok $? "after install the token is not in config.dat"
    ! grep -q -F "$can" /var/cache/debconf/passwords.dat; ok $? "after install the token is not in passwords.dat (cleared)"
    # The *-old backups are debconf's previous copies; a token preseeded with
    # the wrong type was already written to the 0644 config.dat by
    # debconf-set-selections before the package existed. Reported, not asserted
    # (the specified install uses a password preseed: see sub_install).
    local left; left=$(dbfiles_with "$can")
    if [ -n "$left" ]; then
        echo "NOTE string-typed preseed: the token is still in: $left($(for f in $left; do stat -c '%n %U:%G %a' "$f"; done | tr '
' ' '))"
    fi
}

# --- planted symlinks in the state directory (security point of TASK-100) ---
sub_symlink() {
    echo "== symlink (enroll.token written as bitscan, never through a planted link)"
    local tok; tok=$(newtok)
    fresh_install "$tok"
    wait_active
    printf 'victim\n' >/etc/m4b-victim; chmod 0644 /etc/m4b-victim
    local v; v=$(sha /etc/m4b-victim)
    ln -sf /etc/m4b-victim /var/lib/bitscan-agent/enroll.token.tmp
    local new; new=$(newtok)
    preseed "" "$new"
    writer_trace_on
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/sym1.log" 2>&1
    is "$?" 0 "re-enrolment with a planted enroll.token.tmp link succeeds"
    writer_trace_check "planted enroll.token.tmp link"
    is "$(sha /etc/m4b-victim)" "$v" "the link target is unchanged"
    [ -f /var/lib/bitscan-agent/enroll.token ] && [ ! -L /var/lib/bitscan-agent/enroll.token ]; ok $? "enroll.token is a regular file"
    is "$(st /var/lib/bitscan-agent/enroll.token)" "bitscan:bitscan 600" "enroll.token bitscan:bitscan 0600"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token)" "$new" "enroll.token holds the new token"
    rm -f /var/lib/bitscan-agent/enroll.token
    ln -s /etc/m4b-victim /var/lib/bitscan-agent/enroll.token
    local new2; new2=$(newtok)
    preseed "" "$new2"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/sym2.log" 2>&1
    is "$?" 0 "re-enrolment with enroll.token planted as a link succeeds"
    writer_trace_check "planted enroll.token link"
    writer_trace_off
    is "$(sha /etc/m4b-victim)" "$v" "the link target is unchanged"
    [ -f /var/lib/bitscan-agent/enroll.token ] && [ ! -L /var/lib/bitscan-agent/enroll.token ]; ok $? "enroll.token replaced by a regular file"
    is "$(head -1 /var/lib/bitscan-agent/enroll.token)" "$new2" "enroll.token holds the newer token"
    # TASK-100 r2 (review nit 4, mv -fT): a directory planted at enroll.token
    # makes re-enrolment fail; the token is never moved into it
    rm -f /var/lib/bitscan-agent/enroll.token
    install -d -o bitscan -g bitscan -m 0700 /var/lib/bitscan-agent/enroll.token
    local new3 can3; new3=$(newtok); can3=$(canary_of "$new3")
    preseed "" "$new3"
    timeout 120 dpkg-reconfigure bitscan-agent </dev/null >"$W/sym3.log" 2>&1
    local rc3=$?
    [ "$rc3" != 0 ]; ok $? "re-enrolment with a directory planted at enroll.token fails (rc $rc3)"
    [ -d /var/lib/bitscan-agent/enroll.token ] && [ -z "$(ls -A /var/lib/bitscan-agent/enroll.token)" ]
    ok $? "the planted directory is left empty (holds: $(ls -A /var/lib/bitscan-agent/enroll.token 2>/dev/null | tr '\n' ' '))"
    ! grep -q -F "$can3" "$W/sym3.log"; ok $? "the token is not echoed by the failed re-enrolment"
    rm -rf /var/lib/bitscan-agent/enroll.token /var/lib/bitscan-agent/enroll.token.tmp
    preseed "" "$(newtok)"
    timeout 120 dpkg --configure -a </dev/null >/dev/null 2>&1
    is "$(sha /etc/m4b-victim)" "$v" "the link target is still unchanged after the directory case"
}

# --- CHK-M4-176: static checks on the scripts in the .deb ----------------------
sub_static() {
    echo "== static (CHK-M4-176)"
    rm -rf "$W/ctl"; dpkg-deb -e "$DEB" "$W/ctl"
    local f
    for f in postinst postrm config; do
        [ -f "$W/ctl/$f" ]; ok $? "$f in the control archive"
        sh -n "$W/ctl/$f"; ok $? "sh -n $f"
        grep -qx 'set -e' "$W/ctl/$f"; ok $? "$f has set -e"
        ! grep -nE '\brm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*[[:space:]].*\$' "$W/ctl/$f" >/dev/null; ok $? "$f: no rm -r with a variable path"
        ! grep -nE '\$\{?(BITSCAN_|MANAGER_URL|ENROL_TOKEN|CA_FILE|MANAGER_SPKI)' "$W/ctl/$f" | grep -v 'ENV_FILE\|ENV_KEYS' | grep -vE '^\s*[0-9]+:\s*#' >/dev/null
        ok $? "$f reads no BITSCAN_ or install-input environment variable"
        if command -v shellcheck >/dev/null; then
            # -e SC1091 only: shellcheck cannot follow the sourced
            # /usr/share/debconf/confmodule (not given as input), which is an
            # info note, not a finding in the script; same as CHK-M4-176 and
            # CHK-M4-176-r2. Every other code at every severity still fails.
            local sc_rc
            shellcheck -s sh -e SC1091 "$W/ctl/$f" >"$W/sc_$f.txt" 2>&1; sc_rc=$?
            ok "$sc_rc" "shellcheck -s sh -e SC1091 $f (rc $sc_rc, $(wc -l <"$W/sc_$f.txt") lines)"
            if [ "$sc_rc" != 0 ] || [ -s "$W/sc_$f.txt" ]; then
                sed "s|^|    shellcheck $f: |" "$W/sc_$f.txt"
            fi
        else
            echo "NOT RUN shellcheck $f (shellcheck not installed)"
        fi
    done
}

for s in "${SUBS[@]}"; do
    if [ "$s" = all ]; then
        for a in "${ALL[@]}"; do "sub_$a"; done
    else
        "sub_$s"
    fi
done
reset_host

TOTAL=$((PASSN + FAILN))
if [ "$FAILN" = 0 ]; then
    echo "OK $PASSN/$TOTAL checks passed"
    exit 0
fi
echo "FAIL $PASSN/$TOTAL checks passed, $FAILN failed"
exit 1
