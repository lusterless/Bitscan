#!/bin/bash
# Gate mutation rows CHK-M6-320..322 (G47, TASK-129; work/tasks.md "M6 mutation table").
# Each plant changes manager/pyproject.toml in a throwaway copy of the tree, then
# runs deploy/tests/test_manager_wheel.sh on that copy in a fresh ubuntu:24.04
# container; the plant is "red" when the script exits non-zero AND the named
# check fails for the planted reason. A control (no change) must be green first.
#
# Runs in WSL as root (Docker); never touches the tree, binds no port, no VM:
#   bash e2e/m6/wheel_plants.sh TREE OUT [control|320|321|322 ...]
# TREE is a copy of the M6 tree with the UI built into manager/bitscan_manager/webui.
set -u
TREE=${1:?tree}; OUT=${2:?out}; shift 2
[ "$#" -gt 0 ] || set -- control 320 321 322
CA=/usr/local/share/ca-certificates/zscaler-root.crt
mkdir -p "$OUT"
[ -f "$TREE/manager/bitscan_manager/webui/index.html" ] || { echo "no UI build in $TREE" >&2; exit 2; }

plant() { # plant ID DIR: apply the planted change to DIR/manager/pyproject.toml (python3 -I, exact text)
    python3 -I - "$1" "$2/manager/pyproject.toml" "$2" <<'PY'
import sys
from pathlib import Path
pid, f, root = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
s = f.read_text(encoding="utf-8")
sec = '[tool.hatch.build.targets.wheel]\npackages = ["bitscan_manager"]\nartifacts = ["/bitscan_manager/webui/**"]\n'
assert s.count(sec) == 1, "the TASK-129 section is not where the plant expects it"
if pid == "320":    # the UI dropped from the wheel: the artifacts line removed
    s = s.replace(sec, '[tool.hatch.build.targets.wheel]\npackages = ["bitscan_manager"]\n')
elif pid == "320x":  # the UI really dropped: the artifacts line replaced by an exclude of webui/
    # (tester-m6d: hatchling 1.32.4 applies the repo-root .gitignore's patterns relative to manager/, so
    # `manager/bitscan_manager/webui/` never matches and the UI is packed with or without the artifacts
    # line; removing the line alone (320) leaves the wheel unchanged)
    s = s.replace(sec, '[tool.hatch.build.targets.wheel]\npackages = ["bitscan_manager"]\nexclude = ["/bitscan_manager/webui"]\n')
elif pid == "321":  # migration files dropped from the wheel
    s = s.replace(sec, sec + 'exclude = ["/bitscan_manager/db/migrations/versions"]\n')
elif pid == "322":  # tests/ packed into the wheel: manager/tests force-included as bitscan_manager/tests
    # (tester-m6d: the first form also copied tests/ into the package, which `packages` already packs, so
    # hatchling refused the duplicate path and no wheel was built at all; one change, not two)
    assert (root / "manager" / "tests").is_dir()
    s = s.replace(sec, sec + '\n[tool.hatch.build.targets.wheel.force-include]\n"tests" = "bitscan_manager/tests"\n')
elif pid != "control":
    raise SystemExit(f"unknown plant {pid}")
f.write_text(s, encoding="utf-8")
print(f"planted {pid}")
PY
}

for id in "$@"; do
    d=/root/m6t/wheel-mut-$id
    rm -rf "$d"; mkdir -p "$d"
    # the repo-root .gitignore comes too: it ignores manager/bitscan_manager/webui/, and hatchling honours the
    # first .gitignore in the project folder or a parent, as in the release checkout (release.yml builds
    # ./manager from the checkout root). Without it the UI is packed even with the artifacts line removed,
    # and plant 320 can't go red (tester-m6d's first run, 2026-10-26).
    [ -f "$TREE/.gitignore" ] && grep -qx 'manager/bitscan_manager/webui/' "$TREE/.gitignore" || { echo "$id: the tree's .gitignore does not ignore webui/" | tee -a "$OUT/summary.txt"; continue; }
    (cd "$TREE" && tar --exclude=.git --exclude=node_modules --exclude=.venv --exclude=__pycache__ -cf - .gitignore manager deploy docs web) | tar -C "$d" -xf -
    plant "$id" "$d" || { echo "$id: plant failed" | tee -a "$OUT/summary.txt"; continue; }
    docker rm -f "m6-wheel-mut-$id" >/dev/null 2>&1
    docker run --rm --name "m6-wheel-mut-$id" -v "$d:/w/repo" -v "$CA:$CA:ro" -e BITSCAN_TEST_DISPOSABLE=1 -e WHEEL_PREBUILT_UI=1 \
        ubuntu:24.04 bash -c 'apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq ca-certificates >/dev/null 2>&1; update-ca-certificates >/dev/null 2>&1
        timeout 2400 bash /w/repo/deploy/tests/test_manager_wheel.sh /w/repo' >"$OUT/$id.log" 2>&1
    rc=$?
    fails=$(grep -c '^FAIL ' "$OUT/$id.log")
    case "$id" in
        control) want='^OK ' ;;
        320|320x) want='^FAIL (wheel lists bitscan_manager/webui/index.html|GET / status|GET / body byte-identical)' ;;
        321) want='^FAIL (every migration file of the tree is in the wheel|db migrate exits 0|the database is at head)' ;;
        322) want='^FAIL no test path in the wheel' ;;
    esac
    hit=$(grep -cE "$want" "$OUT/$id.log")
    if [ "$id" = control ]; then verdict=$([ "$rc" = 0 ] && [ "$hit" -ge 1 ] && echo GREEN || echo NOT-GREEN)
    else verdict=$([ "$rc" != 0 ] && [ "$hit" -ge 1 ] && echo RED || echo NOT-RED); fi
    echo "$id $verdict rc=$rc fails=$fails :: $(grep -E '^(FAIL|OK) ' "$OUT/$id.log" | head -6 | tr '\n' ';')" | tee -a "$OUT/summary.txt"
    rm -rf "$d"
done
