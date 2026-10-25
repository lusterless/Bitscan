#!/bin/bash
# Package build tests (M4 TP-M4-17: CHK-M4-200 to CHK-M4-206; REQ-106,
# REQ-109; TS 3.1 L158-L166, L177; PD-26; decisions 2026-10-24: amd64 only).
#
# Usage: bash deploy/tests/test_build_deb.sh [--deb PATH] SUBCOMMAND...
#   repro     two builds with deploy/debian/build-deb.sh in fresh copies of the
#             repo at different absolute paths, each with its own GOCACHE,
#             GOPATH and GOMODCACHE: identical sha256 for the three binaries,
#             the .deb, its .sha256 file and the SBOMs (CHK-M4-200)
#   contents  dpkg-deb -c lists exactly the REQ-106 files, owners and modes;
#             units and policy in the .deb equal deploy/ (CHK-M4-201)
#   static    ELF x86-64 static binaries, no PT_INTERP, amd64 only (CHK-M4-202)
#   sbom      each CycloneDX SBOM lists exactly the modules `go version -m`
#             prints, with the same versions, plus the Go version (CHK-M4-203)
#   sha256    the .sha256 file passes sha256sum -c; a one-byte change fails
#             (CHK-M4-204)
#   flags     go version -m shows -trimpath, CGO_ENABLED=0, no VCS stamp, the
#             reproducible -ldflags and the changelog version; no build path in
#             the binaries; empty Go build id (CHK-M4-206)
#   lintian   lintian --fail-on error,warning; every override has a reason
#             comment and is used (CHK-M4-205)
#   all       every subcommand above
# --deb PATH checks a built .deb (and the .sha256 and SBOMs next to it, as
# build-deb.sh writes them). Without it, the first repro build is used, or
# the script builds once. Building needs the Go of agent/go.mod, dpkg-dev,
# debhelper and build-essential; contents, static, sbom, sha256 and flags with
# --deb need only Go, dpkg-deb, file, readelf (binutils) and python3. Root is
# not needed; the script writes only under its own mktemp folder.
#
# Exit: 0 all checks passed, 1 a check failed, 2 setup or usage error.
set -u
export LC_ALL=C

usage() { echo "usage: $0 [--deb PATH] {repro|contents|static|sbom|sha256|flags|lintian|all}..." >&2; exit 2; }
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
[ "${#SUBS[@]}" -gt 0 ] || usage
ALL=(repro contents static sbom sha256 flags lintian)
for s in "${SUBS[@]}"; do
    case " ${ALL[*]} all " in *" $s "*) ;; *) echo "unknown subcommand: $s" >&2; usage ;; esac
done
if [ -n "$DEB" ]; then
    [ -f "$DEB" ] || { echo "no such .deb: $DEB" >&2; exit 2; }
    DEB=$(cd "$(dirname "$DEB")" && pwd)/$(basename "$DEB")
fi
ROOT=$(cd "$(dirname "$0")/../.." && pwd -P)
need() { for t in "$@"; do command -v "$t" >/dev/null || { echo "missing tool: $t" >&2; exit 2; }; done; }
need dpkg-deb sha256sum file readelf python3 go
W=$(mktemp -d /tmp/m4b-builddeb.XXXXXX)
trap 'chmod -R u+w "$W" 2>/dev/null; rm -rf "$W"' EXIT

PASSN=0
FAILN=0
ok() { if [ "$1" = 0 ]; then PASSN=$((PASSN + 1)); echo "PASS $2"; else FAILN=$((FAILN + 1)); echo "FAIL $2"; fi; }
is() { [ "$1" = "$2" ]; ok $? "$3 (got '$1', want '$2')"; }

VERSION=$(dpkg-parsechangelog -l "$ROOT/deploy/debian/changelog" -S Version 2>/dev/null ||
    sed -n '1s/^bitscan-agent (\([^)]*\)).*/\1/p' "$ROOT/deploy/debian/changelog")
DEBNAME=bitscan-agent_${VERSION}_amd64.deb
BINS="bitscan-agent bitscan-runner bitscan-capread"
UNITS="bitscan-agent.service bitscan-runner.socket bitscan-runner.service bitscan-capread.socket bitscan-capread.service"

build_once() { # build_once N -> $W/b$N/out (fresh copy at a distinct path, own Go caches)
    local n=$1
    local d="$W/b$n/src-copy-$n-$RANDOM"
    mkdir -p "$d" "$W/b$n/out" "$W/b$n/gopath" "$W/b$n/gocache" "$W/b$n/gomod"
    cp -r "$ROOT/agent" "$ROOT/deploy" "$d/"
    (cd "$d" && GOPATH="$W/b$n/gopath" GOCACHE="$W/b$n/gocache" GOMODCACHE="$W/b$n/gomod" GOFLAGS= \
        timeout 1800 bash deploy/debian/build-deb.sh "$W/b$n/out") >"$W/b$n/build.log" 2>&1
    local rc=$?
    echo "$d" >"$W/b$n/srcpath"
    return $rc
}

sub_repro() {
    echo "== repro (CHK-M4-200)"
    need dpkg-buildpackage dh
    local n
    for n in 1 2; do
        build_once "$n"; local rc=$?
        is "$rc" 0 "build $n (copy at $(cat "$W/b$n/srcpath")) exits 0"
        [ "$rc" = 0 ] || tail -5 "$W/b$n/build.log" | sed 's/^/     | /'
    done
    [ -f "$W/b1/out/$DEBNAME" ] && [ -f "$W/b2/out/$DEBNAME" ] || { ok 1 "both builds produced $DEBNAME"; return; }
    [ "$(cat "$W/b1/srcpath")" != "$(cat "$W/b2/srcpath")" ]; ok $? "the two source copies are at different absolute paths"
    local f
    for f in "$DEBNAME" "$DEBNAME.sha256"; do
        is "$(sha256sum <"$W/b1/out/$f" | cut -d' ' -f1)" "$(sha256sum <"$W/b2/out/$f" | cut -d' ' -f1)" "identical sha256 of $f in both builds"
    done
    # SBOMs: identical content; the SBOM tool's own hashes (metadata.tools)
    # are reported, not required (REQ-109 names the binaries and the .deb)
    for b in $BINS; do
        f="${DEBNAME%.deb}.$b.cdx.json"
        local norm1 norm2
        norm1=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); [t.pop("hashes",None) for t in d.get("metadata",{}).get("tools",[]) if isinstance(t,dict)]; print(json.dumps(d,sort_keys=True))' "$W/b1/out/$f" | sha256sum | cut -d' ' -f1)
        norm2=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); [t.pop("hashes",None) for t in d.get("metadata",{}).get("tools",[]) if isinstance(t,dict)]; print(json.dumps(d,sort_keys=True))' "$W/b2/out/$f" | sha256sum | cut -d' ' -f1)
        is "$norm1" "$norm2" "identical SBOM content for $b in both builds (tool hashes aside)"
        # build-deb.sh installs the SBOM tool with -trimpath (TASK-102 r1), so
        # the SBOM bytes, the tool's own hash included, are identical too
        cmp -s "$W/b1/out/$f" "$W/b2/out/$f"; ok $? "identical SBOM bytes for $b in both builds"
        if ! cmp -s "$W/b1/out/$f" "$W/b2/out/$f"; then
            echo "NOTE $f differs byte-wise between the builds:"
            diff <(python3 -I -m json.tool "$W/b1/out/$f") <(python3 -I -m json.tool "$W/b2/out/$f") | grep -c '^<' | sed 's/^/     | lines differing: /'
            python3 -I -c 'import json,sys
a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2]))
ta=a.get("metadata",{}).get("tools",[]); tb=b.get("metadata",{}).get("tools",[])
print("     | metadata.tools hashes equal:", [t.get("hashes") for t in ta]==[t.get("hashes") for t in tb])' "$W/b1/out/$f" "$W/b2/out/$f"
        fi
    done
    for n in 1 2; do dpkg-deb -x "$W/b$n/out/$DEBNAME" "$W/b$n/x"; done
    local b
    for b in $BINS; do
        is "$(sha256sum <"$W/b1/x/usr/sbin/$b" | cut -d' ' -f1)" "$(sha256sum <"$W/b2/x/usr/sbin/$b" | cut -d' ' -f1)" "identical sha256 of $b in both builds"
    done
    [ -z "$DEB" ] && DEB=$W/b1/out/$DEBNAME
    if [ "$DEB" != "$W/b1/out/$DEBNAME" ]; then
        is "$(sha256sum <"$DEB" | cut -d' ' -f1)" "$(sha256sum <"$W/b1/out/$DEBNAME" | cut -d' ' -f1)" "the given --deb equals the local builds"
    fi
}

ensure_deb() {
    [ -n "$DEB" ] && return 0
    need dpkg-buildpackage dh
    build_once 0 || { echo "build failed" >&2; tail -5 "$W/b0/build.log" >&2; exit 2; }
    DEB=$W/b0/out/$DEBNAME
}
x_deb() { # extracted data and control of $DEB in $W/x, $W/ctl
    [ -d "$W/x" ] && return 0
    dpkg-deb -x "$DEB" "$W/x" && dpkg-deb -e "$DEB" "$W/ctl"
}

sub_contents() {
    echo "== contents (CHK-M4-201)"
    ensure_deb; x_deb
    dpkg-deb -c "$DEB" >"$W/list.txt"
    # non-directory entries: mode owner path
    local got want
    got=$(awk '$1 !~ /^d/ {print $1, $2, $6}' "$W/list.txt" | sort)
    want=$( {
        for b in $BINS; do echo "-rwxr-xr-x root/root ./usr/sbin/$b"; done
        for u in $UNITS; do echo "-rw-r--r-- root/root ./lib/systemd/system/$u"; done
        echo "-rw-r--r-- root/root ./etc/dbus-1/system.d/bitscan-runner.conf"
        echo "-rw-r--r-- root/root ./usr/share/doc/bitscan-agent/changelog.Debian.gz"
        echo "-rw-r--r-- root/root ./usr/share/doc/bitscan-agent/copyright"
        echo "-rw-r--r-- root/root ./usr/share/lintian/overrides/bitscan-agent"
    } | sort)
    [ "$got" = "$want" ]; ok $? "dpkg-deb -c lists exactly the REQ-106 files with these modes and owners"
    [ "$got" = "$want" ] || diff <(echo "$want") <(echo "$got") | sed 's/^/     | /'
    local dirs bad
    dirs=$(awk '$1 ~ /^d/ {print $1, $2, $6}' "$W/list.txt")
    bad=$(echo "$dirs" | grep -v '^drwxr-xr-x root/root ' | head -3)
    [ -z "$bad" ]; ok $? "every directory is drwxr-xr-x root/root ($bad)"
    local extra
    extra=$(echo "$dirs" | awk '{print $3}' | while read -r d; do
        [ "$d" = ./ ] && continue
        echo "$got" | awk '{print $3}' | grep -q "^${d}" || echo "$d"
    done)
    [ -z "$extra" ]; ok $? "no directory without a packaged file under it ($extra)"
    local u
    for u in $UNITS; do
        cmp -s "$W/x/lib/systemd/system/$u" "$ROOT/deploy/systemd/$u"; ok $? "$u in the .deb is byte-identical to deploy/systemd/$u"
    done
    cmp -s "$W/x/etc/dbus-1/system.d/bitscan-runner.conf" "$ROOT/deploy/dbus/bitscan-runner.conf"; ok $? "the D-Bus policy in the .deb is byte-identical to deploy/dbus/"
    if [ -f "$ROOT/deploy/tests/check_units_verbatim.py" ] && [ -f "$ROOT/docs/spec/Technical_Specification.md" ]; then
        (cd "$ROOT" && python3 -I deploy/tests/check_units_verbatim.py agent) >"$W/verbatim.txt" 2>&1; local vr=$?
        ok $vr "deploy/ units and policy are verbatim TS 3.7 (check_units_verbatim.py agent)"
        [ "$vr" = 0 ] || tail -8 "$W/verbatim.txt" | sed 's/^/     | /'
    else
        echo "NOT RUN verbatim check (docs/spec or check_units_verbatim.py not in this tree)"
    fi
    local members
    members=$(ls "$W/ctl" | sort | tr '\n' ' ')
    is "$members" "conffiles config control md5sums postinst postrm preinst prerm templates " "control archive members"
    is "$(cat "$W/ctl/conffiles")" "/etc/dbus-1/system.d/bitscan-runner.conf" "conffiles is exactly the D-Bus policy"
    for f in config postinst postrm preinst prerm; do
        is "$(stat -c '%a' "$W/ctl/$f")" 755 "control $f mode"
    done
    cmp -s "$W/ctl/templates" "$ROOT/deploy/debian/templates"; ok $? "templates equal deploy/debian/templates"
    cmp -s "$W/ctl/config" "$ROOT/deploy/debian/config"; ok $? "config equals deploy/debian/config"
    is "$(dpkg-deb -f "$DEB" Package)" bitscan-agent "Package"
    is "$(dpkg-deb -f "$DEB" Version)" "$VERSION" "Version (from debian/changelog)"
    is "$(dpkg-deb -f "$DEB" Architecture)" amd64 "Architecture"
    dpkg-deb -f "$DEB" Depends | grep -q '\badduser\b'; ok $? "Depends has adduser ($(dpkg-deb -f "$DEB" Depends))"
    is "$(basename "$DEB")" "$DEBNAME" "file name bitscan-agent_<version>_amd64.deb"
}

sub_static() {
    echo "== static (CHK-M4-202)"
    ensure_deb; x_deb
    local b
    for b in $BINS; do
        local f; f=$(file -b "$W/x/usr/sbin/$b")
        case "$f" in *"ELF 64-bit LSB executable, x86-64"*) ok 0 "$b is ELF 64-bit LSB x86-64" ;; *) ok 1 "$b is ELF 64-bit LSB x86-64 ($f)" ;; esac
        case "$f" in *"statically linked"*) ok 0 "$b is statically linked" ;; *) ok 1 "$b is statically linked ($f)" ;; esac
        ! readelf -lW "$W/x/usr/sbin/$b" 2>/dev/null | grep -q 'INTERP'; ok $? "$b has no PT_INTERP"
        ! readelf -dW "$W/x/usr/sbin/$b" 2>/dev/null | grep -q 'NEEDED'; ok $? "$b needs no shared library"
    done
    local dir; dir=$(dirname "$DEB")
    ! ls "$dir" | grep -qiE 'arm64|aarch64|armhf|i386'; ok $? "no other-architecture artifact next to the .deb ($(ls "$dir" | tr '\n' ' '))"
    ! grep -rqiE 'arm64|aarch64' "$W/ctl/control"; ok $? "control names no other architecture"
}

sub_sbom() {
    echo "== sbom (CHK-M4-203)"
    ensure_deb; x_deb
    local dir b; dir=$(dirname "$DEB")
    for b in $BINS; do
        local sb="$dir/${DEBNAME%.deb}.$b.cdx.json"
        [ -f "$sb" ]; ok $? "SBOM for $b next to the .deb ($(basename "$sb"))"
        [ -f "$sb" ] || continue
        go version -m "$W/x/usr/sbin/$b" >"$W/gvm_$b.txt" 2>&1
        python3 -I - "$W/gvm_$b.txt" "$sb" "$b" >"$W/sbom_$b.txt" 2>&1 <<'EOF'
import json, sys
gvm, sbom, name = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(gvm).read().splitlines()
gover = lines[0].split(": ", 1)[1].strip() if lines and ": " in lines[0] else ""
mods, mainmod = {}, None
for l in lines[1:]:
    p = l.strip().split("\t")
    if p[0] == "mod":
        mainmod = (p[1], p[2])
    elif p[0] == "dep":
        mods[p[1]] = p[2]
    elif p[0] == "=>":
        last = list(mods)[-1]
        mods[last] = p[2]  # replaced module: the version actually linked
d = json.load(open(sbom))
ok = True
def report(cond, msg):
    global ok
    print(("PASS " if cond else "FAIL ") + msg)
    ok = ok and cond
report(d.get("bomFormat") == "CycloneDX", f"{name}: SBOM is CycloneDX (specVersion {d.get('specVersion')})")
comps = {}
def walk(cs):
    for c in cs or []:
        comps.setdefault(c.get("name"), set()).add(c.get("version"))
        walk(c.get("components"))
walk(d.get("components"))
for m, v in sorted(mods.items()):
    report(v in comps.get(m, set()), f"{name}: module {m} {v} (go version -m) is in the SBOM (SBOM has {sorted(x for x in comps.get(m, set()) if x)})")
extra = sorted(n for n in comps if n not in mods and n != "std" and not (mainmod and n == mainmod[0]))
report(not extra, f"{name}: no SBOM component outside go version -m ({extra})")
stdv = comps.get("std", set())
report(any(gover in (v or "") or (v or "").lstrip("v") == gover.lstrip("go") for v in stdv), f"{name}: the Go standard library component carries the Go version {gover} (std {sorted(x for x in stdv if x)})")
meta = (d.get("metadata") or {}).get("component") or {}
report(bool(mainmod) and meta.get("name") == mainmod[0], f"{name}: SBOM metadata component is the main module ({meta.get('name')})")
report("serialNumber" not in d and "timestamp" not in (d.get("metadata") or {}), f"{name}: no serial number or timestamp (reproducible)")
sys.exit(0 if ok else 1)
EOF
        local rc=$?
        cat "$W/sbom_$b.txt"
        PASSN=$((PASSN + $(grep -c '^PASS ' "$W/sbom_$b.txt")))
        FAILN=$((FAILN + $(grep -c '^FAIL ' "$W/sbom_$b.txt")))
        if [ "$rc" != 0 ] && ! grep -q '^FAIL ' "$W/sbom_$b.txt"; then ok 1 "$b: SBOM check script error"; fi
    done
}

sub_sha256() {
    echo "== sha256 (CHK-M4-204)"
    ensure_deb
    local dir; dir=$(dirname "$DEB")
    [ -f "$DEB.sha256" ]; ok $? "$(basename "$DEB").sha256 exists"
    (cd "$dir" && sha256sum -c "$(basename "$DEB").sha256" >/dev/null 2>&1); ok $? "sha256sum -c accepts it"
    is "$(awk '{print $2}' "$DEB.sha256")" "$DEBNAME" "the .sha256 names the .deb file"
    mkdir -p "$W/tamper"; cp "$DEB" "$DEB.sha256" "$W/tamper/"
    python3 -I -c 'import sys; p=sys.argv[1]; b=bytearray(open(p,"rb").read()); b[len(b)//2]^=1; open(p,"wb").write(b)' "$W/tamper/$(basename "$DEB")"
    ! (cd "$W/tamper" && sha256sum -c "$(basename "$DEB").sha256" >/dev/null 2>&1); ok $? "a one-byte change to the .deb fails sha256sum -c"
}

sub_flags() {
    echo "== flags (CHK-M4-206)"
    ensure_deb; x_deb
    local b
    for b in $BINS; do
        local m; m=$(go version -m "$W/x/usr/sbin/$b")
        echo "$m" | grep -qP '^\tbuild\t-trimpath=true$'; ok $? "$b: -trimpath=true"
        echo "$m" | grep -qP '^\tbuild\tCGO_ENABLED=0$'; ok $? "$b: CGO_ENABLED=0"
        echo "$m" | grep -qP '^\tbuild\tGOOS=linux$' && echo "$m" | grep -qP '^\tbuild\tGOARCH=amd64$'; ok $? "$b: GOOS=linux GOARCH=amd64"
        ! echo "$m" | grep -qP '^\tbuild\tvcs'; ok $? "$b: no VCS stamp (-buildvcs=false)"
        # go does not record -ldflags in the build info under -trimpath
        # (go.dev/issue/52372), so the -ldflags effects are checked directly:
        # -s (no symbol table), -w (no DWARF), -buildid= (empty Go build id).
        local sec; sec=$(readelf -SW "$W/x/usr/sbin/$b" 2>/dev/null)
        ! echo "$sec" | grep -qE '\.symtab|\.strtab'; ok $? "$b: no symbol table (-s)"
        ! echo "$sec" | grep -qE '\.(z)?debug_'; ok $? "$b: no DWARF (-w)"
        is "$(go tool buildid "$W/x/usr/sbin/$b" 2>/dev/null)" "" "$b: empty Go build id (-buildid=)"
        echo "$m" | grep -qP '^\tbuild\tGOAMD64=v1$'; ok $? "$b: GOAMD64=v1"
        local leak; leak=$(strings -n 6 "$W/x/usr/sbin/$b" | grep -E '/(home|root|tmp|var/tmp|opt/go|usr/local/go|mnt)/|m4b-|src-copy|/runner/work|GOROOT=' | head -3)
        [ -z "$leak" ]; ok $? "$b: no build path in the binary ($leak)"
    done
    strings -n 6 "$W/x/usr/sbin/bitscan-agent" | grep -qxF "$VERSION"; ok $? "bitscan-agent holds the changelog version $VERSION (-X main.version took effect)"
}

sub_lintian() {
    echo "== lintian (CHK-M4-205)"
    need lintian
    ensure_deb
    lintian --version | sed 's/^/     /'
    lintian --info --display-level '>=pedantic' --show-overrides "$DEB" >"$W/lintian.txt" 2>&1
    sed 's/^/     | /' "$W/lintian.txt"
    lintian --fail-on error,warning "$DEB" >/dev/null 2>&1; ok $? "lintian --fail-on error,warning passes"
    ! grep -qE '^[EW]: ' "$W/lintian.txt"; ok $? "no E: or W: tag"
    ! grep -qE 'unused-override|mismatched-override' "$W/lintian.txt"; ok $? "no unused or mismatched override"
    local ov="$ROOT/deploy/debian/bitscan-agent.lintian-overrides"
    if [ -f "$ov" ]; then
        python3 -I - "$ov" <<'EOF'
import sys
lines = open(sys.argv[1]).read().splitlines()
ok, prev_comment = True, False
for l in lines:
    s = l.strip()
    if not s:
        prev_comment = prev_comment  # a blank line inside a group keeps the reason
        continue
    if s.startswith("#"):
        prev_comment = True
        continue
    if not prev_comment:
        print(f"FAIL override without a reason comment above it: {s}"); ok = False
sys.exit(0 if ok else 1)
EOF
        ok $? "every override has a reason comment"
    fi
}

for s in "${SUBS[@]}"; do
    if [ "$s" = all ]; then
        for a in "${ALL[@]}"; do "sub_$a"; done
    else
        "sub_$s"
    fi
done

TOTAL=$((PASSN + FAILN))
if [ "$FAILN" = 0 ]; then echo "OK $PASSN/$TOTAL checks passed"; exit 0; fi
echo "FAIL $PASSN/$TOTAL checks passed, $FAILN failed"
exit 1
