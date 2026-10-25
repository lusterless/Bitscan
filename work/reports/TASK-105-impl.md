# TASK-105 IMPL: package CI (`.github/workflows/package.yml`)

This task covers REQ-111, REQ-109 and REQ-106, and TS §3.1 (packaging, reproducible builds, SBOM, SHA-256), §3.7 (units and the D-Bus policy) and §8.3 (`systemd-analyze verify`, package tests). Platforms: Ubuntu 22.04 and 24.04, amd64 only (decisions 2026-10-24: arm64 and Debian 12 dropped; PD-27 (a) Debian container part therefore not built). Lead ruling (A), 2026-10-24: the workflow calls the tester's `deploy/tests/` scripts, so the assertions live in one place; install-test jobs stay red until those scripts land, and tester-m4b's verdict covers the joined state.

One review round (CI). No tests were run (that is the tester's job). Local checks only:
- the YAML parses (Go, `go.yaml.in/yaml/v3` v3.0.5, from a scratch folder outside the repo), and every `run:` block passes `bash -n` (with `${{ }}` masked);
- `bash -n deploy/debian/build-deb.sh` passes;
- `grep -n arm64 .github/workflows/*.yml` prints nothing; all three files are LF only;
- a Git Bash smoke run of the mtime filter (`TZ=UTC tar -tv --full-time | awk`): a tar made with `--mtime=@1792800000 --clamp-mtime` gives no line, a tar with fresh times lists every member.
- `actionlint` was not run (not installed here; CHK-M4-250 runs it).

## Files

| File | Status | Code lines | Note |
| --- | --- | --- | --- |
| `.github/workflows/package.yml` | new | 240 | Over the 150 estimate: seven jobs, each with its own pinned checkout, setup and download steps. One file; splitting it would leave untestable halves. |
| `deploy/debian/bitscan-agent.lintian-overrides` | new, **outside the task's file list** (approved by the lead) | 7 overrides | Each with its reason in the comment above it. |
| `deploy/debian/build-deb.sh` | one line changed, **outside the task's file list** (approved by the lead; a TASK-102 file) | 0 net | `bitscan-agent.lintian-overrides` added to `DEBIAN_FILES`, so the overrides are staged and `dh_lintian` ships them. |

**Effect on TASK-102 (tester):** the `.deb` now also contains `/usr/share/lintian/overrides/bitscan-agent` (0644, root:root, installed by `dh_lintian`). The `contents` check (CHK-M4-201) must expect it; CHK-M4-205 asks for the overrides to be in the package.

## Actions (pinned by commit, like `agent.yml`)

| Action | Commit | Tag |
| --- | --- | --- |
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | v7.0.1 (same as `agent.yml`) |
| `actions/setup-go` | `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e` | v7.0.0 (same as `agent.yml`) |
| `actions/setup-python` | `5fda3b95a4ea91299a34e894583c3862153e4b97` | v7.0.0 (same as `units.yml`) |
| `actions/upload-artifact` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | v7.0.2 (new) |
| `actions/download-artifact` | `9000827ccba6bdab643e8b6fd33ac0654aef8333` | v8.0.2 (new) |

The two new commits were read with `git ls-remote` on 2026-10-24; both tags are lightweight (no peeled `^{}` entry), so the value is the commit. Inputs used (`name`, `path`, `if-no-files-found`) were checked against each `action.yml` at that commit.

Tools: Go is the `agent/go.mod` version (setup-go, no cache); `cyclonedx-gomod` is pinned by version and module checksum inside `build-deb.sh` (TASK-102); `dpkg-dev`, `debhelper`, `lintian`, `file` and `debconf-utils` come from the signed Ubuntu archive of the runner image. The build job prints the image (`$ImageOS $ImageVersion`) and the dpkg, dpkg-dev and debhelper versions.

## Jobs

Triggers, permissions and shell are the same as the other workflows (`pull_request`, `push` to main; `contents: read`; bash, which GitHub runs with `-eo pipefail`). `LC_ALL=C` for the whole workflow. Every job has a `timeout-minutes`.

1. **`sources`** (ubuntu-24.04): `python deploy/tests/check_units_verbatim.py agent` (the five agent units and the D-Bus policy, byte-identical to TS §3.7) and `python deploy/tests/check_debian_meta.py` (control, rules flags, changelog, copyright, install file). Plant "an altered unit" turns this red.
2. **`build`** (matrix of two, both **ubuntu-24.04**, `fail-fast: false`): checkout to `src/` and to `rebuild/copy/src/` (different absolute paths, separate VMs, fresh Go caches), install `build-essential`, `dpkg-dev` and `debhelper` (build-essential added after tester-m4b's TASK-102 note; the runner image already has it, so this makes the requirement explicit), run `bash <src>/deploy/debian/build-deb.sh "$RUNNER_TEMP/out"`, upload the out folder as `bitscan-agent-amd64` (the release artifact: `.deb`, `.deb.sha256`, three CycloneDX SBOMs) and `bitscan-agent-amd64-rebuild`. Both builds use the same image because dpkg compression defaults differ between Ubuntu releases.
3. **`reproducible`** (needs build): both artifacts must hold exactly the five expected files (no other architecture or stray file), every file's SHA-256 must be equal between the two builds (`diff -u` of the two lists), `sha256sum -c` must pass on the `.sha256` file, and every member of the control and data tarballs must carry the changelog date (`SOURCE_DATE_EPOCH` from `dpkg-parsechangelog -S Timestamp`). Plant "a timestamp in the build" turns this red: a time-dependent byte breaks the double build, and an unclamped file time breaks the date check.
4. **`lintian`** (needs build, ubuntu-24.04): `lintian --display-info --pedantic --show-overrides --fail-on error,warning` on the `.deb`, with the output printed. Red on any error or warning, and also on any `unused-override` or `mismatched-override`, so the overrides file holds only tags lintian really emits. lintian is not run on 22.04 (one lintian version keeps the override list exact).
5. **`package-checks`** (needs build, ubuntu-24.04; Go, Python 3.12, `dpkg-dev`, `file`): `bash deploy/tests/test_build_deb.sh --deb <ci .deb> contents static sbom sha256 flags`. Plant "a module missing from the SBOM" turns this red (tester's `sbom` check, CHK-M4-203).
6. **`packaged-units`** (needs build; ubuntu-22.04 and ubuntu-24.04): `dpkg-deb -x` the `.deb`, install the three packaged binaries to `/usr/sbin`, require exactly five units under `*/systemd/system/`, then `systemd-analyze verify` on them must succeed and print nothing (as `units.yml`). Running it on 22.04 too checks the units against systemd 249, the oldest supported.
7. **`install-test`** (needs build; ubuntu-22.04 and ubuntu-24.04): install `debconf-utils`, then `sudo env BITSCAN_TEST_DISPOSABLE=1 bash deploy/tests/test_maintainer_scripts.sh --deb <ci .deb> all`. Plant "a failing install test" turns this red.

Exit code 1 or 2 from either tester script fails the step (any non-zero does).

## Agreed interface of the tester scripts (tester-m4b, 2026-10-24)

- `deploy/tests/test_maintainer_scripts.sh --deb PATH [SUBCOMMAND...]`: subcommands `install`, `missing`, `installenv`, `envvars`, `reinstall`, `upgrade`, `purge`, `reenrol`, `invalid`, `etcperm`, `all` (default); each starts from a purged state and the script purges at the end; `upgrade` repacks the given `.deb` with a bumped version (dpkg only). Needs root, systemd as PID 1, apt/dpkg, `debconf-utils`; refuses to run (exit 2) unless `BITSCAN_TEST_DISPOSABLE=1`, or if `bitscan-agent` is already installed by someone else. Output: one `PASS`/`FAIL` line per check and a final total.
- `deploy/tests/test_build_deb.sh [--deb PATH] SUBCOMMAND...`: `repro`, `contents`, `static`, `sbom`, `sha256`, `flags`, `lintian`, `all`. With `--deb`, the checks read the `.deb` and the `.sha256` and SBOM files next to it (the artifact folder keeps `build-deb.sh`'s layout). Needs Go, `dpkg-dev`, `file`; no root, no `BITSCAN_TEST_DISPOSABLE`.
- Exit codes for both: 0 pass, 1 a check failed, 2 setup or usage error.
- CI does not call `repro` (the two-VM double build replaces it) or `lintian` (job 4 runs lintian with the override policy).

## Lintian overrides (best knowledge; to be confirmed by tester-m4b's raw tag list)

Not run here (no lintian). Each override has its reason in the file:
- `dbus-policy-in-etc [etc/dbus-1/system.d/bitscan-runner.conf]`: TS §3.1 and §3.7 put the policy there (decisions 2026-10-24).
- `statically-linked-binary` for the three binaries: TS §3 and the stack rules require static Go binaries with `CGO_ENABLED=0`. lintian exempts Go builds only when it sees a `golang-go` Build-Depends in a source package, which a binary-only lint does not have.
- `no-manual-page` for the three binaries: services started only by their units, never run by hand; the install runbook documents them.

Not overridden, because they are source-package tags and lintian here checks only the binary `.deb`: `untranslatable-debconf-templates` and `not-using-po-debconf`. If the tester's run shows other tags (for example `hardening-no-pie` or `hardening-no-relro` on the static binaries), or one of the above does not fire, the override file is adjusted in a fix round. CI fails on an unused override, so a wrong guess shows up as red, not as a silent override.

### Fix round 1 (from tester-m4b's raw lintian lists, 2026-10-25)

On Ubuntu 24.04 (lintian 2.117.0ubuntu1.5), all 7 overrides above are used, with no unused or mismatched override. Two more warnings fired there, and both now have an override with its reason. This is the only file changed in this round:

- `uses-dpkg-database-directly [usr/sbin/bitscan-agent]`: TS §3.4 requires the agent to watch `/var/lib/dpkg/` with inotify (`IN_MOVED_TO`, `IN_CLOSE_WRITE` on `status`). The code confirms that the path is only the watched folder (`internal/inventory/watch.go`, `DpkgDir`). The package list comes only from `/usr/bin/dpkg-query` (`internal/inventory/command.go`).
- `initial-upload-closes-no-bugs [usr/share/doc/bitscan-agent/changelog.Debian.gz:1]`: the package is shipped directly as a `.deb` (TS §3.1), never uploaded to the Debian archive, so there is no Debian bug to close.

**Still red, and waiting on the lead (not overridden on my own):** two `E: dbus-policy-excessively-broad` (Properties `Get`, `GetAll`) and four `W: dbus-policy-without-send-destination` (rules 1, 3, 4, 5). They come from the D-Bus policy, which is byte-identical to TS §3.7 and cannot change without a spec change. tester-m4b has raised this with the lead as a conflict with TS §3.1's "must pass `lintian`". If the ruling is "override with a reason", the six lines go in this file.

**Ubuntu 22.04's lintian (2.114) is not used by CI, and that stays so.** It does not know `dbus-policy-in-etc` (a `malformed-override` error). It reads overrides only in the older form, without `[…]` brackets, so every override is "mismatched". And it reports `statically-linked-binary` as an error. One overrides file cannot suit both versions. The `lintian` job runs only on ubuntu-24.04, the build image; the 22.04 runners run the install, unit and package checks, not lintian.

The info-level tags (`systemd-service-file-missing-documentation-key` ×3, `systemd-service-file-missing-install-key` on `bitscan-capread.service`, which TS §3.7 gives no `[Install]` section) do not fail `--fail-on error,warning` and are not overridden.

### Fix round 2 (lead ruling 2026-10-25: D-Bus findings overridden with a reason)

Only `deploy/debian/bitscan-agent.lintian-overrides` changed; the D-Bus policy (`deploy/dbus/bitscan-runner.conf`) is untouched and still byte-identical to TS §3.7 L412–L431. Six override lines were added in two commented groups, one line per finding:

- 2 × `dbus-policy-excessively-broad` (rule 3 Properties `Get`, rule 4 Properties `GetAll`);
- 4 × `dbus-policy-without-send-destination` (rule 1 `deny send_type="method_call"`, rules 3, 4 and 5 Properties `Get`, `GetAll`, `Introspectable`).

The comments give the reason: the policy text is fixed verbatim by TS §3.7, it applies only to the `bitscan-runner` user, rule 1 denies every method call on purpose, and rules 3–5 allow only the read-only calls that `systemctl is-active`, `is-enabled` and `list-units` need.

The tag and context of each line were copied from tester-m4b's raw lintian 2.117.0ubuntu1.5 output (`%TEMP%\m4b_bt_u24c.log`). A `diff` of the six `E:`/`W:` lines from that log (with the `E: ` / `W: ` prefix removed) against the six new lines prints nothing. The file is ASCII with LF line endings. lintian was not run here. Expected result on 24.04: no error or warning, and no unused or mismatched override (13 overrides, all used).

## For the tester (TP-M4-20)

- CHK-M4-250: the debian:12 part is NOT RUN (dropped by the user, 2026-10-24); there is no Debian job.
- CHK-M4-251 plants and the job each turns red: lintian error → `lintian`; build timestamp → `reproducible`; altered unit → `sources` (and `package-checks` `contents`, and `packaged-units` if the change breaks verify); failing install test → `install-test`; module missing from the SBOM → `package-checks`.
- The CI run itself is NOT RUN until pushed (the lead commits and pushes).
