#!/usr/bin/env bash
# Build bitscan-agent_<version>_amd64.deb, its SHA-256 file and one CycloneDX
# SBOM per binary (PD-26 (a); TS 3.1; REQ-106, REQ-109). amd64 only; the
# package targets Ubuntu 22.04 and 24.04 (decisions 2026-10-24).
#
# Usage: deploy/debian/build-deb.sh [OUT_DIR]     (default: dist/ in the repo)
# Needs: the Go version of agent/go.mod, build-essential (dpkg-checkbuilddeps
# requires it), dpkg-dev, debhelper (compat 13) and the Go module proxy. Unsigned (-us -uc): v1 has no signing or APT repository.
set -euo pipefail
umask 022
export LC_ALL=C TZ=UTC

ROOT=$(cd "$(dirname "$0")/../.." && pwd -P)
OUT=${1:-$ROOT/dist}
SBOM_MODULE=github.com/CycloneDX/cyclonedx-gomod
SBOM_VERSION=v1.12.0
SBOM_SUM=h1:OuFUYNhnjpju7RNArOVPPchFPWNobGfhrHODDPKcgZs=
UNITS=(bitscan-agent.service bitscan-runner.socket bitscan-runner.service bitscan-capread.socket bitscan-capread.service)
DEBIAN_FILES=(control rules changelog copyright templates config postinst postrm bitscan-agent.install bitscan-agent.lintian-overrides)
BINARIES=(bitscan-agent bitscan-runner bitscan-capread)

cd "$ROOT"
VERSION=$(dpkg-parsechangelog -l deploy/debian/changelog -S Version)
# Every file time in the .deb is clamped to the changelog date.
SOURCE_DATE_EPOCH=$(dpkg-parsechangelog -l deploy/debian/changelog -S Timestamp)
export SOURCE_DATE_EPOCH
DEB=bitscan-agent_${VERSION}_amd64.deb

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE=$WORK/bitscan-agent-$VERSION
mkdir -p "$STAGE/bin" "$STAGE/debian/source" "$STAGE/debian/systemd" "$STAGE/debian/dbus" "$OUT"

# 1. Static binaries with reproducible flags: no paths, no VCS stamp, no build id.
(
    cd agent
    go mod verify
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 GOFLAGS=-mod=readonly \
        go build -trimpath -buildvcs=false \
        -ldflags "-s -w -buildid= -X main.version=$VERSION" \
        -o "$STAGE/bin/" ./cmd/bitscan-agent ./cmd/bitscan-runner ./cmd/bitscan-capread
)

# 2. SBOM tool, pinned by version and by its module checksum.
sum=$(cd "$WORK" && GOFLAGS= go mod download -json "$SBOM_MODULE@$SBOM_VERSION" |
    grep -o '"Sum": "[^"]*"' | cut -d'"' -f4)
if [ "$sum" != "$SBOM_SUM" ]; then
    echo "build-deb: $SBOM_MODULE@$SBOM_VERSION checksum does not match the pinned value" >&2
    exit 1
fi
(cd "$WORK" && GOBIN="$WORK/tools" GOFLAGS= go install -trimpath "$SBOM_MODULE/cmd/cyclonedx-gomod@$SBOM_VERSION")

# 3. Staging tree (PD-26): an explicit file list, so nothing else is packaged.
for f in "${DEBIAN_FILES[@]}"; do
    cp "deploy/debian/$f" "$STAGE/debian/$f"
done
cp deploy/debian/source/format "$STAGE/debian/source/format"
for u in "${UNITS[@]}"; do
    cp "deploy/systemd/$u" "$STAGE/debian/systemd/$u"
done
cp deploy/dbus/bitscan-runner.conf "$STAGE/debian/dbus/bitscan-runner.conf"
# Fixed modes, whatever the source tree carries: Git on Windows keeps no
# executable bit (TASK-092 carry-over), and a tree where every file is
# executable makes dh_install run bitscan-agent.install as a program.
find "$STAGE/debian" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/debian/rules" "$STAGE/debian/config" "$STAGE/debian/postinst" "$STAGE/debian/postrm"

# 4. SBOMs: every module go version -m lists, plus the Go standard library;
# no serial number or timestamp, so they are as reproducible as the binaries.
for b in "${BINARIES[@]}"; do
    "$WORK/tools/cyclonedx-gomod" bin -json -std -noserial -notimestamp \
        -version "$VERSION" -output "$OUT/${DEB%.deb}.$b.cdx.json" "$STAGE/bin/$b"
done

# 5. The package (binary only, unsigned) and its SHA-256 file.
(cd "$STAGE" && dpkg-buildpackage -b -us -uc -aamd64)
cp "$WORK/$DEB" "$OUT/$DEB"
(cd "$OUT" && sha256sum "$DEB" >"$DEB.sha256")

(cd "$STAGE/bin" && sha256sum "${BINARIES[@]}")
cat "$OUT/$DEB.sha256"
