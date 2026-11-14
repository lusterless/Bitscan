#!/bin/sh
# Build clustermax-collector_<version>-<rev>_all.deb (TS §3.1, §3.8).
#
#   collector/packaging/build-deb.sh [output-dir]
#
# Fetches lusterless/clustermax at the pinned commit, checks the commit and
# version, installs the hash-pinned dependencies, and builds the package with
# fixed timestamps so two builds give the same file. Needs git, python3 with
# pip, and dpkg-deb. Runs as any user; it writes only under a temp directory
# and the output directory.
set -eu

CLUSTERMAX_REPO="https://github.com/lusterless/clustermax"
CLUSTERMAX_COMMIT="f849f4620ca9a703fab4a6544e55031929f9844e"
CLUSTERMAX_VERSION="0.3.0"
PACKAGE_REVISION="1"
# Commit time of f849f46, so repeated builds are byte-identical.
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1794127773}"
export SOURCE_DATE_EPOCH

here=$(cd "$(dirname "$0")" && pwd)
collector=$(dirname "$here")
out=$(mkdir -p "${1:-$collector/dist}" && cd "${1:-$collector/dist}" && pwd)
version="${CLUSTERMAX_VERSION}-${PACKAGE_REVISION}"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "==> ClusterMAX ${CLUSTERMAX_COMMIT}"
git init -q "$work/src"
git -C "$work/src" fetch -q --depth 1 "$CLUSTERMAX_REPO" "$CLUSTERMAX_COMMIT"
git -C "$work/src" checkout -q FETCH_HEAD
test "$(git -C "$work/src" rev-parse HEAD)" = "$CLUSTERMAX_COMMIT"
grep -qx "__version__ = \"${CLUSTERMAX_VERSION}\"" "$work/src/cmax/_version.py"

stage="$work/stage"
lib="$stage/usr/lib/clustermax"
mkdir -p "$lib/bin" "$lib/site" "$stage/usr/sbin" "$stage/usr/bin" \
    "$stage/usr/lib/systemd/system" "$stage/usr/share/doc/clustermax-collector" "$stage/DEBIAN"

echo "==> dependencies (hash-pinned)"
python3 -m pip install -q --no-deps --no-compile --require-hashes --only-binary :all: \
    --python-version 3.12 --implementation cp --abi cp312 \
    --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
    --target "$lib/site" -r "$here/requirements.txt"
# Pure Python only: drop PyYAML's compiled extension and pip's caches.
find "$lib/site" \( -name '*.so' -o -name '__pycache__' -o -name 'RECORD' -o -name 'INSTALLER' \) -prune -exec rm -rf {} +

echo "==> cmax package (files of the upstream wheel's package-data)"
( cd "$work/src" && find cmax -maxdepth 1 -name '*.py' -print \
    && printf '%s\n' cmax/cmax.yaml \
    && find cmax/scripts/1-audit -maxdepth 1 \( -name '*.json' -o -name '*.py' -o -name '*.sh' \) -print \
    && find cmax/scripts/1-audit/checks -maxdepth 2 -name '*.py' -print ) | sort | while read -r f; do
    mkdir -p "$lib/site/$(dirname "$f")"
    cp -p "$work/src/$f" "$lib/site/$f"
done

install -m 0755 "$here/cmax-wrapper.py" "$lib/bin/cmax"
install -m 0755 "$collector/src/cmax_helper.py" "$stage/usr/sbin/cmax-helper"
install -m 0755 "$collector/src/cmax_trigger.py" "$stage/usr/bin/cmax-trigger"
install -m 0644 "$collector/systemd/cmax-helper.socket" "$collector/systemd/cmax-helper.service" "$stage/usr/lib/systemd/system/"
install -m 0644 "$work/src/LICENSE" "$stage/usr/share/doc/clustermax-collector/LICENSE.clustermax"
printf 'ClusterMAX %s (%s @ %s)\n' "$CLUSTERMAX_VERSION" "$CLUSTERMAX_REPO" "$CLUSTERMAX_COMMIT" \
    > "$stage/usr/share/doc/clustermax-collector/SOURCE"

sed -e "s|@VERSION@|${version}|" -e "s|@COMMIT@|${CLUSTERMAX_COMMIT}|" "$here/debian/control" > "$stage/DEBIAN/control"
for script in postinst prerm postrm; do
    install -m 0755 "$here/debian/$script" "$stage/DEBIAN/$script"
done

# Fixed modes and timestamps for a reproducible package.
find "$stage" -type d -exec chmod 0755 {} +
find "$lib/site" -type f -exec chmod 0644 {} +
# ClusterMAX runs its check scripts only when they are executable
# (run_checks.py: os.access(path, os.X_OK)), so keep upstream's execute bits.
( cd "$work/src" && git ls-files -s cmax ) | awk '$1 == "100755" {print $4}' | while read -r f; do
    if [ -f "$lib/site/$f" ]; then chmod 0755 "$lib/site/$f"; fi
done
find "$stage" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +

deb="$out/clustermax-collector_${version}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$deb" >/dev/null
( cd "$out" && sha256sum "$(basename "$deb")" > "$(basename "$deb").sha256" )
echo "==> $deb"
cat "$deb.sha256"
