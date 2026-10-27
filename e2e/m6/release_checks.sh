#!/bin/bash
# G49 functional checks and plants of the release workflow's own checks
# (TP-M6-06 CHK-M6-113, -114, -115, -117; plants CHK-M6-327..332 and the
# bare-`manager` pip plant). Runs in the Ubuntu 24.04 build container:
#
#   release_checks.sh WF TREE CLEAN_RUN_DIR
#
# WF is the workflow under test; every script is extracted from it verbatim
# (check_release_workflow.py --extract) and run with bash -eo pipefail and the
# step's env: values; inputs are crafted in a scratch folder. CLEAN_RUN_DIR is a
# release_local.sh work folder of a clean run (its manager outputs feed the SBOM
# checks). Plants are made in copies of WF under the scratch folder. Prints
# PASS/FAIL per case and a total; exit 1 on any FAIL.
set -u
WF=${1:?wf}
TREE=${2:?tree}
CLEAN=${3:?clean run dir}
CHK="python3 -I $TREE/deploy/tests/check_release_workflow.py"
S=$(mktemp -d /tmp/m6b-relchk.XXXX)
pass=0 fail=0
ok() { if [ "$2" = 0 ]; then pass=$((pass + 1)); echo "PASS $1"; else fail=$((fail + 1)); echo "FAIL $1 :: ${3:-}"; fi; }
run() { # run WF JOB STEP WD [VAR=VAL...] -> rc; output in $S/out
	local wf=$1 job=$2 name=$3 wd=$4
	shift 4
	$CHK --file "$wf" --extract "$job" "$name" >"$S/step.sh" || return 99
	(cd "$wd" && env "$@" bash --noprofile --norc -eo pipefail "$S/step.sh") >"$S/out" 2>&1
}
VSTEP="Tag, pyproject and changelog versions agree"
vws() { # vws PYVER DEBVER -> fresh workspace in $S/v
	rm -rf "$S/v" && mkdir -p "$S/v/manager" "$S/v/deploy/debian"
	sed "s/^version = \".*\"/version = \"$1\"/" "$TREE/manager/pyproject.toml" >"$S/v/manager/pyproject.toml"
	sed "1s/([^)]*)/($2)/" "$TREE/deploy/debian/changelog" >"$S/v/deploy/debian/changelog"
	: >"$S/v/out"
}
versions_cases() { # versions_cases WF LABEL -> runs every CHK-M6-113 case
	local wf=$1 l=$2
	vws 0.1.0 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.0 INPUT_VERSION=
	[ $? = 0 ] && grep -qx version=0.1.0 "$S/v/out" && grep -qx deb_version=0.1.0-1 "$S/v/out"
	ok "$l v0.1.0 + pyproject 0.1.0 + changelog 0.1.0-1 accepted, outputs 0.1.0 / 0.1.0-1" $? "$(cat "$S/out" "$S/v/out")"
	vws 0.1.0 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.1 INPUT_VERSION=
	[ $? != 0 ] && grep -q 'tag v0.1.1 and manager/pyproject.toml version 0.1.0 disagree' "$S/out"
	ok "$l v0.1.1 with pyproject 0.1.0 refused (tag/pyproject)" $? "$(cat "$S/out")"
	vws 0.1.1 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.1 INPUT_VERSION=
	[ $? != 0 ] && grep -q 'tag v0.1.1 and deploy/debian/changelog version 0.1.0-1 disagree' "$S/out"
	ok "$l v0.1.1 + pyproject 0.1.1 with changelog 0.1.0-1 refused (tag/changelog)" $? "$(cat "$S/out")"
	vws 0.1.0 0.1.1-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.0 INPUT_VERSION=
	[ $? != 0 ] && grep -q 'disagree' "$S/out"
	ok "$l v0.1.0 with changelog 0.1.1-1 refused" $? "$(cat "$S/out")"
	vws 0.1.0 '0.1.0~pre1-1'
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.0 INPUT_VERSION=
	[ $? != 0 ] && grep -q 'is a pre-release' "$S/out"
	ok "$l changelog 0.1.0~pre1-1 refused (pre-release)" $? "$(cat "$S/out")"
	vws 0.1.0 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=push REF_NAME=v0.1.0-rc1 INPUT_VERSION=
	[ $? != 0 ] && grep -q 'is not v<major>.<minor>.<patch>' "$S/out" && [ ! -s "$S/v/out" ]
	ok "$l tag v0.1.0-rc1 refused (pattern), no outputs" $? "$(cat "$S/out")"
	vws 0.1.0 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=workflow_dispatch REF_NAME=main INPUT_VERSION=0.1.0
	[ $? = 0 ] && grep -qx version=0.1.0 "$S/v/out"
	ok "$l manual run with input 0.1.0 accepted" $? "$(cat "$S/out")"
	vws 0.1.0 0.1.0-1
	run "$wf" versions "$VSTEP" "$S/v" GITHUB_OUTPUT="$S/v/out" EVENT=workflow_dispatch REF_NAME=main INPUT_VERSION='0.1.0$(touch /tmp/m6b-injected)'
	[ $? != 0 ] && [ ! -e /tmp/m6b-injected ] && grep -q 'is not v<major>' "$S/out"
	ok "$l manual input with a command substitution refused, nothing executed" $? "$(cat "$S/out")"
}

echo "== CHK-M6-113 versions ($WF)"
versions_cases "$WF" CHK-M6-113

echo "== CHK-M6-114 wheel UI check"
mkwheel() { # mkwheel DIR NAME [FILES...]
	mkdir -p "$1"
	python3 -I - "$1/$2" "${@:3}" <<'EOF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("bitscan_manager/__init__.py", "")
    for n in sys.argv[2:]:
        z.writestr(n, "x")
EOF
}
UI="The wheel carries the built UI"
W0=bitscan_manager-0.1.0-py3-none-any.whl
for c in "full:0:bitscan_manager/webui/index.html bitscan_manager/webui/assets/index-x.js" \
	"noindex:1:bitscan_manager/webui/assets/index-x.js" "noassets:1:bitscan_manager/webui/index.html" "none:1:"; do
	n=${c%%:*} r=${c#*:}
	want=${r%%:*} files=${r#*:}
	rm -rf "$S/rt" && mkwheel "$S/rt/dist" "$W0" $files
	run "$WF" manager "$UI" "$S" RUNNER_TEMP="$S/rt" VERSION=0.1.0
	rc=$?
	if [ "$want" = 0 ]; then [ $rc = 0 ]; else [ $rc != 0 ] && grep -q 'wheel without the UI' "$S/out"; fi
	ok "CHK-M6-114 wheel '$n' -> want rc $want" $? "rc $rc $(cat "$S/out")"
done
rm -rf "$S/rt" && mkwheel "$S/rt/dist" "$W0" bitscan_manager/webui/index.html bitscan_manager/webui/assets/a.js && mkwheel "$S/rt/dist" Manager-2.0.5-py3-none-any.whl
run "$WF" manager "$UI" "$S" RUNNER_TEMP="$S/rt" VERSION=0.1.0
[ $? != 0 ] && grep -q 'want exactly' "$S/out"
ok "CHK-M6-114 dist with a second (foreign) wheel refused" $? "$(cat "$S/out")"

echo "== CHK-M6-115 SHA256SUMS"
SUMS="Write and check SHA256SUMS"
PUB="Create the draft release"
fake_release() { # -> $S/sr/release with the 12 files
	rm -rf "$S/sr" && mkdir -p "$S/sr/release"
	for f in bitscan-agent_0.1.0-1_amd64.deb bitscan-agent_0.1.0-1_amd64.bitscan-agent.cdx.json bitscan-agent_0.1.0-1_amd64.bitscan-runner.cdx.json \
		bitscan-agent_0.1.0-1_amd64.bitscan-capread.cdx.json bitscan_manager-0.1.0-py3-none-any.whl bitscan-manager-0.1.0-requirements.txt \
		bitscan-manager-0.1.0.python.cdx.json bitscan-manager-0.1.0.web.cdx.json bitscan-manager.service bitscan-manager-migrate.service \
		bitscan-manager-maintain.service bitscan-manager-maintain.timer; do
		head -c 64 /dev/urandom >"$S/sr/release/$f"
	done
}
mkdir -p "$S/bin"
printf '#!/bin/bash\nprintf "%%s\\n" "$@" > %s/gh-args\n' "$S" >"$S/bin/gh"
chmod +x "$S/bin/gh"
pub() { # pub -> run publish on $S/sr/release (copied to $S/pr)
	rm -rf "$S/pr" "$S/gh-args" && mkdir -p "$S/pr/notes" && cp -a "$S/sr/release" "$S/pr/release" && cp "$S/sr/notes.md" "$S/pr/notes/" 2>/dev/null
	run "$WF" publish "$PUB" "$S/pr" PATH="$S/bin:$PATH" RUNNER_TEMP="$S/pr" TAG=v0.1.0 VERSION=0.1.0 GH_TOKEN=x GH_REPO=l/b
}
fake_release
run "$WF" sums "$SUMS" "$S/sr" RUNNER_TEMP="$S/sr" VERSION=0.1.0 DEB_VERSION=0.1.0-1
rc=$?
[ $rc = 0 ] && [ "$(wc -l <"$S/sr/release/SHA256SUMS")" = 12 ] && grep -q '```text' "$S/sr/notes.md"
ok "CHK-M6-115 clean folder: SHA256SUMS of 12 files, notes written" $? "rc $rc $(tail -3 "$S/out")"
pub
[ $? = 0 ] && grep -qx -- --draft "$S/gh-args" && [ "$(grep -c '^bitscan\|SHA256SUMS' "$S/gh-args")" = 13 ]
ok "CHK-M6-115 clean publish: gh release create --draft with 13 files" $? "$(tr '\n' ' ' <"$S/gh-args" 2>/dev/null) $(cat "$S/out")"
cp -a "$S/sr/release" "$S/good"
printf 'X' | dd of="$S/sr/release/bitscan-manager.service" bs=1 seek=3 conv=notrunc status=none
pub
[ $? != 0 ] && grep -q 'FAILED' "$S/out" && [ ! -e "$S/gh-args" ]
ok "CHK-M6-115 a file changed after SHA256SUMS: publish refuses before gh" $? "$(cat "$S/out")"
rm -rf "$S/sr/release" && cp -a "$S/good" "$S/sr/release" && echo extra >"$S/sr/release/extra.bin"
pub
[ $? != 0 ] && [ ! -e "$S/gh-args" ]
ok "CHK-M6-115 a file not in SHA256SUMS: publish refuses" $? "$(cat "$S/out")"
rm -rf "$S/sr/release" && cp -a "$S/good" "$S/sr/release" && rm "$S/sr/release/bitscan-manager.service"
pub
[ $? != 0 ] && [ ! -e "$S/gh-args" ]
ok "CHK-M6-115 a listed file missing: publish refuses" $? "$(cat "$S/out")"
fake_release && echo extra >"$S/sr/release/extra.bin"
run "$WF" sums "$SUMS" "$S/sr" RUNNER_TEMP="$S/sr" VERSION=0.1.0 DEB_VERSION=0.1.0-1
[ $? != 0 ] && grep -q 'want exactly' "$S/out"
ok "CHK-M6-115 sums: an extra file in the release folder refused" $? "$(tail -2 "$S/out")"
fake_release && rm "$S/sr/release/bitscan-manager-0.1.0.web.cdx.json"
run "$WF" sums "$SUMS" "$S/sr" RUNNER_TEMP="$S/sr" VERSION=0.1.0 DEB_VERSION=0.1.0-1
[ $? != 0 ]
ok "CHK-M6-115 sums: a released file missing from the folder refused" $? "$(tail -2 "$S/out")"

echo "== CHK-M6-117 SBOM completeness"
R="$CLEAN/mgr/rt/release"
COMPLETE="Both SBOMs are complete"
sbom_case() { # sbom_case LABEL EXPECT(0|1) PYTHON-EDIT WEB-EDIT
	rm -rf "$S/sb" && mkdir -p "$S/sb/rt/release" "$S/sb/ws/web" && cp -a "$R/." "$S/sb/rt/release/"
	python3 -I - "$S/sb/rt/release/bitscan-manager-0.1.0.python.cdx.json" "$S/sb/rt/release/bitscan-manager-0.1.0.web.cdx.json" "$3" "$4" <<'EOF'
import json, sys
py, web, pe, we = sys.argv[1:5]
p = json.load(open(py)); w = json.load(open(web))
if pe == "drop-alembic": p["components"] = [c for c in p["components"] if c["name"] != "alembic"]
if pe == "drop-hash": [c["hashes"].pop() for c in p["components"] if c["name"] == "fastapi"]
if we == "drop-react": w["components"] = [c for c in w["components"] if c.get("name") != "react"]
if we == "optional-qr":
    for c in w["components"]:
        if c.get("name") == "qrcode-generator": c["scope"] = "optional"
json.dump(p, open(py, "w")); json.dump(w, open(web, "w"))
EOF
	run "$WF" manager "$COMPLETE" "$S/sb/ws" PATH="$NPMSHIM:$PATH" RUNNER_TEMP="$S/sb/rt" VERSION=0.1.0
	rc=$?
	if [ "$2" = 0 ]; then [ $rc = 0 ]; else [ $rc != 0 ] && grep -q "$5" "$S/out"; fi
	ok "CHK-M6-117 $1 -> want rc $2" $? "rc $rc $(cat "$S/out")"
}
NPMSHIM=$(dirname "$(command -v npm)")
sbom_case "clean SBOMs" 0 none none
sbom_case "alembic dropped from the Python SBOM" 1 drop-alembic none "python sbom lacks alembic=="
sbom_case "one fastapi hash dropped" 1 drop-hash none "python sbom hashes differ for fastapi=="
sbom_case "react dropped from the web SBOM" 1 none drop-react "web sbom lacks react@"
sbom_case "qrcode-generator re-scoped optional" 1 none optional-qr "web sbom lacks qrcode-generator@"

echo "== plants on copies of the workflow"
P="$S/plant.yml"
# CHK-M6-327: the version agreement checks removed
python3 -I - "$WF" "$P" <<'EOF'
import sys
t = open(sys.argv[1]).read()
a = t.index('          if [ "$py" != "$want" ]; then')
b = t.index('          echo "release $want')
open(sys.argv[2], "w").write(t[:a] + t[b:])
EOF
out=$(versions_cases "$P" plant-327)
grep -q '^FAIL plant-327 v0.1.1 with pyproject 0.1.0 refused' <<<"$out" && grep -q '^FAIL plant-327 changelog 0.1.0~pre1-1 refused' <<<"$out"
r=$?
ok "CHK-M6-327 plant (tag/pyproject/changelog checks removed) turns the version cases red" $r "$(grep plant-327 <<<"$out" | tr '\n' '|')"
# CHK-M6-328: one action pinned by tag
sed '0,/uses: actions\/checkout@[0-9a-f]\{40\} # v7.0.1/s//uses: actions\/checkout@v7.0.1/' "$WF" >"$P"
$CHK --file "$P" >"$S/out" 2>&1
[ $? != 0 ] && grep -q '^FAIL every uses: pinned' "$S/out"
ok "CHK-M6-328 plant (actions/checkout@v7.0.1) red" $? "$(grep FAIL "$S/out")"
# CHK-M6-329: no --draft; contents: write at workflow level
sed 's/gh release create "$TAG" --draft /gh release create "$TAG" /' "$WF" >"$P"
$CHK --file "$P" >"$S/out" 2>&1
[ $? != 0 ] && grep -q '^FAIL one gh release create, with --draft' "$S/out"
ok "CHK-M6-329 plant (no --draft) red" $? "$(grep FAIL "$S/out")"
python3 -I - "$WF" "$P" <<'EOF'
import sys
t = open(sys.argv[1]).read()
open(sys.argv[2], "w").write(t.replace("permissions:\n  contents: read\n", "permissions:\n  contents: write\n", 1))
EOF
$CHK --file "$P" >"$S/out" 2>&1
[ $? != 0 ] && grep -q '^FAIL top-level permissions are exactly contents: read' "$S/out"
ok "CHK-M6-329 plant (contents: write at workflow level) red" $? "$(grep FAIL "$S/out")"
# CHK-M6-330: SHA256SUMS written without the last file, and the job's own listed/present check removed
python3 -I - "$WF" "$P" <<'EOF'
import sys
t = open(sys.argv[1]).read()
t = t.replace('sha256sum -- "${files[@]}" >SHA256SUMS', 'sha256sum -- "${files[@]:0:11}" >SHA256SUMS', 1)
a = t.index("          # Every file but SHA256SUMS listed exactly once")
b = t.index("          sha256sum -c SHA256SUMS\n", a)
open(sys.argv[2], "w").write(t[:a] + t[b:])
EOF
fake_release
WFSAVE=$WF WF=$P
run "$WF" sums "$SUMS" "$S/sr" RUNNER_TEMP="$S/sr" VERSION=0.1.0 DEB_VERSION=0.1.0-1
src=$?
WF=$WFSAVE
listed=$(awk '{print $2}' "$S/sr/release/SHA256SUMS" | sort)
present=$(cd "$S/sr/release" && find . -mindepth 1 ! -name SHA256SUMS -printf '%P\n' | sort)
[ "$listed" != "$present" ]
ok "CHK-M6-330 plant (a released file left out of SHA256SUMS, own check removed): the planted sums job passes (rc $src) but the G49 listed-vs-present check is red" $? "listed $(wc -l <<<"$listed") of $(wc -l <<<"$present")"
pub
[ $? != 0 ] && [ ! -e "$S/gh-args" ]
ok "CHK-M6-330 ... and the unplanted publish step refuses that folder" $? "$(cat "$S/out")"
# CHK-M6-331: the wheel UI check accepts a wheel without index.html
python3 -I - "$WF" "$P" <<'EOF'
import sys
t = open(sys.argv[1]).read()
open(sys.argv[2], "w").write(t.replace("sys.exit(1 if problems else 0)", "sys.exit(0)", 1))
EOF
rm -rf "$S/rt" && mkwheel "$S/rt/dist" "$W0" bitscan_manager/webui/assets/index-x.js
run "$P" manager "$UI" "$S" RUNNER_TEMP="$S/rt" VERSION=0.1.0
[ $? = 0 ]
ok "CHK-M6-331 plant (UI check always passes): a wheel without webui/index.html is accepted, so the CHK-M6-114 'noindex' case is red" $? "$(cat "$S/out")"
# CHK-M6-332: a requirements.txt package missing from the Python SBOM (generator planted)
python3 -I - "$WF" "$P" <<'EOF'
import sys
t = open(sys.argv[1]).read()
old = '          components.sort(key=lambda c: (c["name"].lower(), c["version"]))\n'
open(sys.argv[2], "w").write(t.replace(old, old + "          components = components[1:]\n", 1))
EOF
rm -rf "$S/g" && mkdir -p "$S/g/rt/release" "$S/g/ws/web" && cp "$R/bitscan-manager-0.1.0-requirements.txt" "$R/bitscan-manager-0.1.0.web.cdx.json" "$S/g/rt/release/"
run "$P" manager "Python SBOM from the hashed runtime lock" "$S/g/ws" RUNNER_TEMP="$S/g/rt" VERSION=0.1.0
g=$?
run "$P" manager "$COMPLETE" "$S/g/ws" PATH="$NPMSHIM:$PATH" RUNNER_TEMP="$S/g/rt" VERSION=0.1.0
c=$?
[ $g = 0 ] && [ $c != 0 ] && grep -q 'python sbom lacks' "$S/out"
ok "CHK-M6-332 plant (generator drops the first lock package): the completeness step is red" $? "$(cat "$S/out")"
# bare `manager` in pip wheel (the TASK-135 r0 form)
sed 's|--no-index -w "$RUNNER_TEMP/dist" ./manager$|-w "$RUNNER_TEMP/dist" manager|' "$WF" >"$P"
$CHK --file "$P" >"$S/out" 2>&1
[ $? != 0 ] && grep -q "pip wheel target 'manager' is not a path" "$S/out"
ok "CHK-M6-112p plant (bare 'manager' pip wheel target, no --no-index) red in the static check" $? "$(grep FAIL "$S/out")"

echo "release_checks: $pass/$((pass + fail)) passed, $fail failed"
rm -rf "$S" /tmp/m6b-injected
[ "$fail" = 0 ]
