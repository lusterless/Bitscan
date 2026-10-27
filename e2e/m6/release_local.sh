#!/bin/bash
# G49 local run of .github/workflows/release.yml (TP-M6-06 CHK-M6-112, -116;
# REQ-141 (2), (4)). Runs inside an Ubuntu 24.04 build container (dpkg-dev,
# debhelper, build-essential, python3.12-venv, Go of agent/go.mod on PATH) as:
#
#   release_local.sh WF TREE WEBUI NPMDIR WORK [TAG]
#
# WF the workflow file to run (the tree's, or a planted copy); TREE a copy of
# the M6 tree; WEBUI the `npm run build` output (manager/bitscan_manager/webui,
# built with Node 24 / npm 11 outside the container, since Node 24 is not in the
# Ubuntu archive); NPMDIR the outputs of the two npm commands the workflow runs
# in web/ (`npm sbom --sbom-format cyclonedx --package-lock-only` -> web.cdx.json,
# `npm ls --omit=dev --all --json` -> npm-ls.json, from the same build tree),
# served by an `npm` shim that refuses any other arguments. Every other step's
# `run:` script is taken verbatim from WF (check_release_workflow.py --extract)
# and run with `bash --noprofile --norc -eo pipefail`, as GitHub runs it, with
# RUNNER_TEMP, GITHUB_OUTPUT and the step's env: set; artifacts are copied
# between job folders as upload/download-artifact would. `gh` is a shim that
# records its arguments (publish creates nothing). Prints one line per step and
# the harness's own checks; exit 1 if any step or check fails.
set -u
WF=${1:?workflow}
TREE=${2:?tree}
WEBUI=${3:?webui}
NPMDIR=${4:?npm outputs}
W=${5:?work}
TAG=${6:-v0.1.0}
EX="python3 -I $TREE/deploy/tests/check_release_workflow.py --file $WF --extract"
rm -rf "$W" && mkdir -p "$W/bin"
fails=0
note() { printf '%s\n' "$*"; }
ok() { if [ "$2" = 0 ]; then note "PASS $1"; else note "FAIL $1 :: ${3:-}"; fails=$((fails + 1)); fi; }

# shims
cat >"$W/bin/npm" <<EOF
#!/bin/bash
case "\$*" in
  "sbom --sbom-format cyclonedx --package-lock-only") cat "$NPMDIR/web.cdx.json" ;;
  "ls --omit=dev --all --json") cat "$NPMDIR/npm-ls.json" ;;
  *) echo "npm shim: unexpected arguments: \$*" >&2; exit 97 ;;
esac
EOF
cat >"$W/bin/gh" <<EOF
#!/bin/bash
printf '%s\n' "\$@" > "$W/gh-args.txt"
echo "gh shim: recorded \$# arguments"
EOF
ln -sf "$(command -v python3.12)" "$W/bin/python"
chmod +x "$W/bin/"*
export PATH="$W/bin:$PATH" LC_ALL=C

step() { # step JOB "STEP NAME" WORKDIR [VAR=VAL ...]
	local job=$1 name=$2 wd=$3
	shift 3
	$EX "$job" "$name" >"$W/step.sh" || { ok "$job/$name extracted" 1 "no such step"; return 1; }
	(cd "$wd" && env "$@" bash --noprofile --norc -eo pipefail "$W/step.sh") >"$W/step.log" 2>&1
	local rc=$?
	ok "$job / $name (rc $rc)" $rc "$(tail -5 "$W/step.log" | tr '\n' '|')"
	sed 's/^/    | /' "$W/step.log" | tail -8
	return $rc
}
checkout() { mkdir -p "$(dirname "$1")"; cp -a "$TREE" "$1"; rm -rf "$1/manager/bitscan_manager/webui"; }

# versions
mkdir -p "$W/versions/rt"
checkout "$W/versions/ws"
: >"$W/versions/out"
step versions "Tag, pyproject and changelog versions agree" "$W/versions/ws" RUNNER_TEMP="$W/versions/rt" GITHUB_OUTPUT="$W/versions/out" \
	EVENT=push REF_NAME="$TAG" INPUT_VERSION= || { note "versions refused; nothing is built"; echo "release_local: $fails failed"; exit 1; }
VERSION=$(sed -n 's/^version=//p' "$W/versions/out")
DEB_VERSION=$(sed -n 's/^deb_version=//p' "$W/versions/out")
note "outputs: version=$VERSION deb_version=$DEB_VERSION"

# agent a and b: clones at two paths, separate Go caches (fresh runners)
for x in a:src b:rebuild/copy/src; do
	n=${x%%:*} src=${x#*:}
	mkdir -p "$W/agent-$n/rt" "$W/agent-$n/home"
	checkout "$W/agent-$n/ws/$src"
	step agent "Build the .deb and its SBOMs" "$W/agent-$n/ws" RUNNER_TEMP="$W/agent-$n/rt" SRC="$src" HOME="$W/agent-$n/home" \
		GOPATH="$W/agent-$n/home/go" GOCACHE="$W/agent-$n/home/cache" GOMODCACHE="$W/agent-$n/home/go/pkg/mod"
done

# agent-compare
mkdir -p "$W/cmp/rt"
cp -a "$W/agent-a/rt/out" "$W/cmp/rt/a"
cp -a "$W/agent-b/rt/out" "$W/cmp/rt/b"
step agent-compare "Same files and bytes, the .deb and its three binaries included" "$W/cmp" RUNNER_TEMP="$W/cmp/rt" DEB_VERSION="$DEB_VERSION"

# manager
mkdir -p "$W/mgr/rt"
checkout "$W/mgr/ws"
cp -a "$WEBUI" "$W/mgr/ws/manager/bitscan_manager/webui"
note "manager / npm ci + npm run build: done outside the container (Node 24, npm 11); webui copied in"
for s in "Build the wheel from the hashed dev lock" "The wheel carries the built UI" "Manager units match TS 8.7 verbatim" \
	"Collect the manager release files" "Python SBOM from the hashed runtime lock"; do
	step manager "$s" "$W/mgr/ws" RUNNER_TEMP="$W/mgr/rt" VERSION="$VERSION" || break
done
step manager "Web SBOM of the UI packages" "$W/mgr/ws/web" RUNNER_TEMP="$W/mgr/rt" VERSION="$VERSION"
step manager "Both SBOMs are complete" "$W/mgr/ws" RUNNER_TEMP="$W/mgr/rt" VERSION="$VERSION"

# sums
mkdir -p "$W/sums/rt/release"
cp -a "$W/cmp/rt/release/." "$W/sums/rt/release/" 2>/dev/null
cp -a "$W/mgr/rt/release/." "$W/sums/rt/release/" 2>/dev/null
step sums "Write and check SHA256SUMS" "$W/sums" RUNNER_TEMP="$W/sums/rt" VERSION="$VERSION" DEB_VERSION="$DEB_VERSION"

# publish (gh shim)
mkdir -p "$W/pub/rt/release" "$W/pub/rt/notes"
cp -a "$W/sums/rt/release/." "$W/pub/rt/release/"
cp -a "$W/sums/rt/notes.md" "$W/pub/rt/notes/" 2>/dev/null
step publish "Create the draft release" "$W/pub" RUNNER_TEMP="$W/pub/rt" TAG="$TAG" VERSION="$VERSION" GH_TOKEN=shim GH_REPO=local/bitscan

# harness checks (independent of the workflow's own)
R="$W/sums/rt/release"
base="bitscan-agent_${DEB_VERSION}_amd64"
want=$(printf '%s\n' SHA256SUMS "$base.deb" "$base.bitscan-agent.cdx.json" "$base.bitscan-runner.cdx.json" "$base.bitscan-capread.cdx.json" \
	"bitscan_manager-$VERSION-py3-none-any.whl" "bitscan-manager-$VERSION-requirements.txt" "bitscan-manager-$VERSION.python.cdx.json" \
	"bitscan-manager-$VERSION.web.cdx.json" bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service \
	bitscan-manager-maintain.timer | sort)
got=$(cd "$R" 2>/dev/null && find . -mindepth 1 -printf '%P\n' | sort)
[ "$got" = "$want" ]
ok "CHK-M6-112 release folder = plan TASK-135 §3 (13 files incl. SHA256SUMS)" $? "$(diff <(echo "$want") <(echo "$got") | grep '^[<>]' | tr '\n' ' ')"
(cd "$R" && sha256sum -c --quiet SHA256SUMS) >/dev/null 2>&1
ok "CHK-M6-112 sha256sum -c SHA256SUMS" $?
listed=$(awk '{print $2}' "$R/SHA256SUMS" 2>/dev/null | sort)
[ "$listed" = "$(grep -v '^SHA256SUMS$' <<<"$want")" ] && [ -z "$(uniq -d <<<"$listed")" ]
ok "CHK-M6-112 SHA256SUMS lists every released file once and nothing else" $? "$listed"
for f in "$base.deb" "$base.bitscan-agent.cdx.json" "$base.bitscan-runner.cdx.json" "$base.bitscan-capread.cdx.json" "$base.deb.sha256"; do
	cmp -s "$W/agent-a/rt/out/$f" "$W/agent-b/rt/out/$f" || { ok "CHK-M6-112 two builds identical: $f" 1; continue; }
done
cmp -s "$W/agent-a/rt/out/$base.deb" "$W/agent-b/rt/out/$base.deb"
ok "CHK-M6-112 the two .deb builds (paths src and rebuild/copy/src) are byte-identical: $(sha256sum "$W/agent-a/rt/out/$base.deb" 2>/dev/null | cut -c1-16)" $?
cmp -s "$R/$base.deb" "$W/agent-a/rt/out/$base.deb"
ok "CHK-M6-112 the released .deb is the build's" $?
python3 -I - "$R/bitscan_manager-$VERSION-py3-none-any.whl" "$WEBUI" <<'EOF'
import sys, zipfile, pathlib
z = zipfile.ZipFile(sys.argv[1]); web = pathlib.Path(sys.argv[2])
names = set(z.namelist())
want = {"bitscan_manager/webui/" + p.relative_to(web).as_posix(): p.read_bytes() for p in web.rglob("*") if p.is_file()}
bad = [n for n, b in want.items() if n not in names or z.read(n) != b]
bad += [n for n in names if n.startswith(("tests/", "manager/tests/")) or "/tests/" in n]
print("wheel UI files:", len(want), "bad:", bad)
sys.exit(1 if bad or "bitscan_manager/webui/index.html" not in want else 0)
EOF
ok "CHK-M6-112 the released wheel holds the build's index.html and every asset, byte for byte, and no tests/" $?
for u in bitscan-manager.service bitscan-manager-migrate.service bitscan-manager-maintain.service bitscan-manager-maintain.timer; do
	cmp -s "$R/$u" "$TREE/deploy/systemd/$u" || ok "CHK-M6-112 released $u = deploy/systemd" 1
done
cmp -s "$R/bitscan-manager-$VERSION-requirements.txt" "$TREE/manager/requirements.txt"
ok "CHK-M6-112 the released requirements file is manager/requirements.txt, and the four units equal deploy/systemd" $?
if [ -s "$W/gh-args.txt" ]; then
	files=$(grep -vE '^(release|create|--draft|--verify-tag|--title|--notes-file|Bitscan .*|.*/notes/notes.md|v[0-9.]+)$' "$W/gh-args.txt" | sort)
	head -8 "$W/gh-args.txt" | tr '\n' ' ' | sed 's/^/    gh: /'
	echo
	grep -qx -- --draft "$W/gh-args.txt" && [ "$files" = "$want" ]
	ok "CHK-M6-112 publish: gh release create --draft with the 13 files" $? "$files"
	notes="$W/pub/rt/notes/notes.md"
	python3 -I - "$notes" "$R/SHA256SUMS" <<'EOF'
import sys
n = open(sys.argv[1]).read(); s = open(sys.argv[2]).read()
sys.exit(0 if "```text\n" + s + "```" in n else 1)
EOF
	ok "CHK-M6-112 the notes carry SHA256SUMS verbatim in a code block" $?
else
	ok "CHK-M6-112 publish called gh" 1 "no gh call"
fi
echo "release_local: $fails failed"
[ "$fails" = 0 ]
