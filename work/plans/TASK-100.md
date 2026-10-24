# TASK-100 plan: the 0.x `.deb` (metadata, debconf, maintainer scripts, build, CI)

Covers TASK-092, TASK-096, TASK-100, TASK-102 and TASK-105. REQ-106 to REQ-109, REQ-111. Owner: impl-deploy. **Two approvals recommended for TASK-100** (maintainer scripts run as root on every host). Tests: TP-M4-07, 11, 15, 17, 20 (G17, G37 to G40); mutation rows CHK-M4-357 to 364. Blocked on **PD-26**, **PD-27**, **#81**, **#82**.

## Spec quotes

- TS §3.1 L159: "Installed with `dh_installsystemd`; `--no-enable` for `bitscan-runner.service` (started by its socket), and `--no-enable --no-start` for the capread units".
- L164: debconf questions, preseedable: `bitscan/manager_url`, `bitscan/enrol_token`, optional `bitscan/ca_file`, `bitscan/manager_spki_sha256`; "`bitscan/enrol_token` is a `password`-type question, so debconf keeps it only in its root-only `passwords.dat`, and `postinst` clears it after use. Alternatively a root-only file `/etc/bitscan/install.env` (0600) that `postinst` reads and then deletes. Never command-line environment variables".
- L166: "`apt purge` (`postrm purge`) also removes `/etc/bitscan` and `/var/lib/bitscan-agent`" (see #82).
- L168–L175: `postinst` steps 1–4; "If the manager URL or enrolment token is missing, `postinst` fails with a clear message and the package stays unconfigured. On upgrade none are needed … Maintainer scripts must be idempotent and pass `lintian`."
- L177: reproducible Go builds, an SBOM per release, SHA-256 on a separate origin.

## Layout (PD-26 recommendation)

`deploy/debian/` holds the Debian packaging; `deploy/debian/build-deb.sh` assembles a staging tree:
```
stage/bitscan-agent-<version>/
  debian/            <- copy of deploy/debian/ (minus build-deb.sh)
  debian/systemd/    <- copies of the five agent units from deploy/systemd/
  debian/dbus/       <- deploy/dbus/bitscan-runner.conf
  bin/               <- prebuilt static linux/amd64 binaries
```
and runs `dpkg-buildpackage -b -us -uc -aamd64` (amd64 only: arm64 dropped from v1, decisions 2026-10-24; `control` says `Architecture: amd64`) (debhelper compat 13, `Rules-Requires-Root: no`, `dh $@` with `override_dh_auto_build` empty, `override_dh_installsystemd` with the TS flags per unit, `override_dh_strip` / `dh_dwz` off for static Go binaries). Go build: `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X main.version=<version>"`. `SOURCE_DATE_EPOCH` from `debian/changelog`. Version: `0.1.0~pre1-1` style (sorts below `0.1.0`), one changelog entry per pre-release. Unsigned (`-us -uc`): no APT repository, no signing (owner decision). SBOM: `cyclonedx-gomod bin` (pinned version and checksum) per binary, CycloneDX JSON; `sha256sum` file per `.deb`.

## postinst (TASK-100)

```
configure (first install, no /etc/bitscan/agent.yaml yet):
  1. adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin bitscan; same for bitscan-runner (skip if they exist)
  2. inputs: /etc/bitscan/install.env if present (must be root:root 0600, else fail), else debconf; validate https:// URL, bse_ token form, optional ca_file path exists, optional 64-hex pin
  3. write /etc/bitscan/agent.yaml (root:bitscan 0640) via a temp file; never the token
  4. install -d -o bitscan -g bitscan -m 0700 /var/lib/bitscan-agent; write enroll.token (bitscan:bitscan 0600)
  5. db_set bitscan/enrol_token ""; delete install.env
  6. (dh_installsystemd snippets) enable and start bitscan-runner.socket and bitscan-agent.service
configure (upgrade): keep everything; dh snippets restart the services
configure with a new enrolment token (#81 re-enrolment via dpkg-reconfigure): write enroll.token, restart the agent
```
Missing URL or token on first install: `echo "bitscan-agent: <input> is missing; preseed bitscan/<question> or write /etc/bitscan/install.env" >&2; exit 1`.

## postrm (TASK-100)

`remove`: dh snippets stop and disable. `purge` (#82 recommendation): remove `/var/lib/bitscan-agent`, `/etc/bitscan/agent.yaml` and `/etc/bitscan/install.env`, then `rmdir --ignore-fail-on-non-empty /etc/bitscan`, and purge the debconf answers. Users are kept (Debian practice). Both are idempotent (`rm -f`, `rm -rf` on fixed paths only, never a variable path).

## CI (TASK-105, `.github/workflows/package.yml`, PD-27)

Jobs (amd64 only; nothing builds, packages, tests or emulates arm64): `build` (twice in fresh workspaces, compare `sha256sum`), `lintian` (the `.deb`), `install-test` (Ubuntu 22.04 and 24.04 runners; Debian 12 in a systemd-enabled `debian:12` container, PD-27): install with preseed, check modes, owners and unit states, reinstall, upgrade from the previous 0.x build, purge, each twice; `sbom` (CycloneDX present, modules equal `go version -m`); artifacts: `.deb`, `.sha256`, SBOM. Every action pinned by commit, every tool by version and checksum.
