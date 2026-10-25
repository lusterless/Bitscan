# TASK-102 IMPL: `.deb` build script

This task covers REQ-106 and REQ-109, PD-26 (a) and TS §3.1 (L177). The build is amd64 only, and the package targets Ubuntu 22.04 and 24.04 (decisions 2026-10-24).

No tests were run (that is the tester's job). There is no `dpkg-dev`, debhelper or shellcheck on this Windows machine. Only `bash -n` was run locally (it passes).

## Files

`deploy/debian/build-deb.sh` is new: 53 code lines, LF only, bash with `set -euo pipefail`. No other file was touched.

## Usage

```sh
bash deploy/debian/build-deb.sh [OUT_DIR]    # default OUT_DIR: dist/ in the repo (git-ignored)
```

It needs:
- the Go version named in `agent/go.mod`;
- `dpkg-dev` and `debhelper` (compat 13);
- network access to the Go module proxy, to fetch the pinned SBOM tool.

Call it through `bash`. Git on Windows stores no executable bit, the same issue as `rules`.

## What it does

1. **Settings.** `umask 022`, `LC_ALL=C`, `TZ=UTC`. `VERSION` and `SOURCE_DATE_EPOCH` both come from `deploy/debian/changelog` (`dpkg-parsechangelog -S Version` and `-S Timestamp`, so 0.1.0~pre1-1 and 1792800000). The work happens in a fresh `mktemp -d`, removed on exit.
2. **Binaries.**
   - `go mod verify` runs first.
   - Then `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 GOFLAGS=-mod=readonly go build -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X main.version=$VERSION"` builds the three `cmd/` packages into `stage/bin/`.
   - The flags remove build paths, the VCS stamp and the build id.
   - **For impl-agent (TASK-106):** the version is injected as `main.version`, so `cmd/bitscan-agent` needs a package-level `var version string`. Until that variable exists, Go silently ignores `-X`.
3. **SBOM tool.**
   - `cyclonedx-gomod` v1.12.0 is pinned by version and by its module checksum, `h1:OuFUYNhnjpju7RNArOVPPchFPWNobGfhrHODDPKcgZs=`. I read that value from `go mod download -json` on 2026-10-24.
   - The script compares that checksum before it runs `go install`, and stops with one line if it differs.
   - `go install` also verifies every dependency against the Go checksum database and the tool's own `go.sum`.
4. **Staging tree** (PD-26 layout).
   - `stage/debian/` gets exactly the nine files `control`, `rules`, `changelog`, `copyright`, `templates`, `config`, `postinst`, `postrm` and `bitscan-agent.install`, plus `source/format`. Because the list is explicit, `build-deb.sh`, editor backups and stray files are never packaged.
   - `stage/debian/systemd/` gets the five agent units, copied unchanged (the manager units are never staged).
   - `stage/debian/dbus/` gets `bitscan-runner.conf`.
   - **TASK-092 carry-over:** `chmod 0755` is applied to `rules`, `config`, `postinst` and `postrm` in the staging tree. The lead's latest instruction places the bit in the staging tree. The reviewer's `git update-index --chmod=+x deploy/debian/rules` can still be applied when the change is staged for the commit.
5. **SBOMs.**
   - One per binary: `cyclonedx-gomod bin -json -std -noserial -notimestamp -version $VERSION`.
   - Output: `OUT/bitscan-agent_<version>_amd64.<binary>.cdx.json`.
   - `bin` mode reads the build info embedded in the binary, so the SBOM lists exactly the modules `go version -m` prints, plus the Go standard library with the Go version (`-std`).
   - With no serial number and no timestamp, the SBOMs are byte-stable across builds as well.
6. **Package.**
   - `dpkg-buildpackage -b -us -uc -aamd64` in the staging tree: binary only and unsigned (owner decision: no signing, no APT repository).
   - `Rules-Requires-Root: no`, so the package has root:root ownership without fakeroot.
   - dpkg-deb clamps every file time and the ar member times to `SOURCE_DATE_EPOCH`, and sorts the entries.
   - The script copies `bitscan-agent_<version>_amd64.deb` to `OUT` and writes `OUT/<deb>.sha256` in `sha256sum` format, so `sha256sum -c` runs from `OUT`.
   - It prints the SHA-256 values of the three binaries and of the `.deb`.

## For the tester (TP-M4-17)

- **Reproducibility (CHK-M4-200)** holds for builds with the same toolchain image: the same Go version (from `go.mod`) and the same dpkg and debhelper versions. dpkg's default compression differs between Ubuntu releases (xz or zstd), so compare two builds from the same image. CI builds on one pinned runner image (TASK-105).
- **Path independence:** each run uses a new random `mktemp` folder, and `-trimpath` keeps that path out of the binaries. Two runs from clones at different absolute paths should give identical hashes.
- **`dpkg-deb -c` (REQ-106 (1)) should list:**
  - `/usr/sbin/bitscan-{agent,runner,capread}` at 0755;
  - the five units in `/lib/systemd/system/` at 0644;
  - `/etc/dbus-1/system.d/bitscan-runner.conf` at 0644;
  - `/usr/share/doc/bitscan-agent/{copyright,changelog.Debian.gz}`.

  The control archive holds `config`, `templates`, `postinst`, `postrm`, `prerm` (debhelper's), `conffiles` and `md5sums`.
- **lintian** is not run by the script. lintian and each override with its reason belong to TASK-105 (lead).

## Not done (out of scope)

- No `lintian`, no install test and no `dpkg-deb -c` check in the script; those are TASK-105.
- Publishing the SHA-256 on the release page is the M6 release step.

## Changes before the first TEST verdict

Test these together with the original version. `bash -n` passes, and the file is still LF only.

1. **TASK-105 (approved by the lead):** `bitscan-agent.lintian-overrides` was added to `DEBIAN_FILES`. `dh_lintian` therefore ships `/usr/share/lintian/overrides/bitscan-agent` (0644), and the `contents` list above gains that file.
2. **tester-m4b's note (1):** a fresh environment needs `build-essential`, because `dpkg-checkbuilddeps` stops with "Unmet build dependencies: build-essential:native". The "Needs:" header line now lists it. The dependency check is not skipped with `-d`, so a real missing build dependency still stops the build. `package.yml` installs it explicitly.
3. **tester-m4b's note (2):** the staged files now get fixed modes, whatever the source tree carries. `find "$STAGE/debian" -type f -exec chmod 0644 {} +` runs first, then 0755 on `rules`, `config`, `postinst` and `postrm`. Before this, a source tree where every file is executable (a copy from `/mnt/c`, or a tarball made on Windows) made `dh_install` run `bitscan-agent.install` as an executable config, which failed with exit code 2. A Linux git checkout (100644) was not affected. The `.deb`'s own file modes are unchanged: `dh_fixperms` and the `rules` `install -m` calls set those.

## Revision 1 (after TEST PASS; tester-m4b's suggestion, lead 2026-10-25)

One word changed in `deploy/debian/build-deb.sh`: the SBOM tool is now installed with `go install -trimpath "$SBOM_MODULE/cmd/cyclonedx-gomod@$SBOM_VERSION"`. The tool binary then holds no build-folder paths, so its hash (the SBOM's `metadata.tools[].hashes`, the only part that differed between two builds) is the same in every build, and the three SBOM files become byte-identical across builds. Nothing else changed: the module checksum pin, the version and the SBOM flags are the same. `bash -n` passes, and the file is still LF only.

For the tester: run `test_build_deb.sh repro` once and confirm the three SBOM files are byte-identical between the two builds, along with the `.deb`.
