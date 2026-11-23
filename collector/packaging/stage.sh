#!/bin/sh
# Stage the ClusterMAX collector for the bitscan-agent package (TS §3.1, §3.8;
# owner decision 2026-11-15: the collector is part of bitscan-agent).
#
#   collector/packaging/stage.sh DEST
#
# Fetches lusterless/clustermax at the pinned commit, checks the commit and
# the version, installs the hash-pinned dependencies (pure Python only), and
# writes under DEST:
#   usr/lib/clustermax/        ClusterMAX and its dependencies, bin/cmax
#   usr/sbin/cmax-helper       the root helper
#   systemd/                   cmax-helper.socket and cmax-helper.service
#   doc/                       LICENSE.clustermax and clustermax-SOURCE
# Needs git and python3 with pip. Writes only under a temp directory and DEST.
# File times are left to the package build (SOURCE_DATE_EPOCH clamping).
set -eu

CLUSTERMAX_REPO="https://github.com/lusterless/clustermax"
CLUSTERMAX_COMMIT="f849f4620ca9a703fab4a6544e55031929f9844e"
CLUSTERMAX_VERSION="0.3.0"

here=$(cd "$(dirname "$0")" && pwd)
collector=$(dirname "$here")
dest=${1:?usage: stage.sh DEST}
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git init -q "$work/src"
git -C "$work/src" fetch -q --depth 1 "$CLUSTERMAX_REPO" "$CLUSTERMAX_COMMIT"
git -C "$work/src" checkout -q FETCH_HEAD
test "$(git -C "$work/src" rev-parse HEAD)" = "$CLUSTERMAX_COMMIT"
grep -qx "__version__ = \"${CLUSTERMAX_VERSION}\"" "$work/src/cmax/_version.py"

lib="$dest/usr/lib/clustermax"
mkdir -p "$lib/bin" "$lib/site" "$dest/usr/sbin" "$dest/usr/bin" "$dest/systemd" "$dest/doc"

python3 -m pip install -q --no-deps --no-compile --require-hashes --only-binary :all: \
    --python-version 3.12 --implementation cp --abi cp312 \
    --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
    --target "$lib/site" -r "$here/requirements.txt"
# Pure Python only: drop PyYAML's compiled extension and pip's records, so
# the files run on Python 3.10 and later.
find "$lib/site" \( -name '*.so' -o -name '__pycache__' -o -name 'RECORD' -o -name 'INSTALLER' \) -prune -exec rm -rf {} +

# The files of the upstream wheel's package-data.
( cd "$work/src" && find cmax -maxdepth 1 -name '*.py' -print \
    && printf '%s\n' cmax/cmax.yaml \
    && find cmax/scripts/1-audit -maxdepth 1 \( -name '*.json' -o -name '*.py' -o -name '*.sh' \) -print \
    && find cmax/scripts/1-audit/checks -maxdepth 2 -name '*.py' -print ) | sort | while read -r f; do
    mkdir -p "$lib/site/$(dirname "$f")"
    cp "$work/src/$f" "$lib/site/$f"
done

install -m 0755 "$here/cmax-wrapper.py" "$lib/bin/cmax"
install -m 0755 "$collector/src/cmax_helper.py" "$dest/usr/sbin/cmax-helper"
install -m 0644 "$collector/systemd/cmax-helper.socket" "$collector/systemd/cmax-helper.service" "$dest/systemd/"
install -m 0644 "$work/src/LICENSE" "$dest/doc/LICENSE.clustermax"
{
    printf 'ClusterMAX %s (%s @ %s), Apache-2.0\n' "$CLUSTERMAX_VERSION" "$CLUSTERMAX_REPO" "$CLUSTERMAX_COMMIT"
    printf 'Python dependencies (hash-pinned, pure Python):\n'
    grep -E '^[A-Za-z0-9_.-]+==' "$here/requirements.txt" | sed 's/ .*//; s/^/  /'
} > "$dest/doc/clustermax-SOURCE"
chmod 0644 "$dest/doc/clustermax-SOURCE"

# Fixed modes. ClusterMAX runs its check scripts only when they are executable
# (run_checks.py: os.access(path, os.X_OK)), so keep upstream's execute bits.
find "$dest" -type d -exec chmod 0755 {} +
find "$lib/site" -type f -exec chmod 0644 {} +
( cd "$work/src" && git ls-files -s cmax ) | awk '$1 == "100755" {print $4}' | while read -r f; do
    if [ -f "$lib/site/$f" ]; then chmod 0755 "$lib/site/$f"; fi
done
