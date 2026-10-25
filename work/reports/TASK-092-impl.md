# TASK-092 IMPL: D-Bus policy and package metadata

REQ-106. TS §3.1 (L159, L161), §3.7 (L410–L433). PD-26 option (a): debhelper compat 13, version `0.1.0~preN-1`, amd64 only (decisions 2026-10-24). The licence and maintainer follow the user's answers relayed by `main` (decisions 2026-10-24, "Package licence and maintainer"). That entry is not yet in this worktree's `work/decisions.md`.

No tests were run (that is the tester's job). There is no Debian tooling on this Windows machine, so `lintian`, `dpkg-buildpackage`, `make` and `systemd-analyze verify` were not run either.

## Files (all new, all LF, no other file touched)

| File | What |
| --- | --- |
| `deploy/dbus/bitscan-runner.conf` | TS L413–L430 byte for byte (the lines between the ```` ```xml ```` fence at L412 and the closing fence at L431), LF, one final newline, 1,648 bytes. No XML declaration or DOCTYPE, because the spec block has none (dbus-daemon accepts a file without one). |
| `deploy/debian/control` | Source and binary stanza: `Maintainer: Bitdeer-Security <kaiquan.koh@bitdeer.com>`, `debhelper-compat (= 13)`, `Rules-Requires-Root: no`, `Standards-Version: 4.6.2`, `Architecture: amd64`, `Depends: adduser, ${misc:Depends}`. |
| `deploy/debian/rules` | `dh $@`; empty `override_dh_auto_build`, `override_dh_strip` and `override_dh_dwz`; `execute_after_dh_install` copies the five units from `debian/systemd/` to `lib/systemd/system/` with `install -m 0644`; `override_dh_installsystemd` with the TS §3.1 flags. |
| `deploy/debian/changelog` | One entry, `bitscan-agent (0.1.0~pre1-1) unstable; urgency=medium`. The trailer is `Bitdeer-Security <kaiquan.koh@bitdeer.com>  Sat, 24 Oct 2026 00:00:00 +0000`, which gives `SOURCE_DATE_EPOCH` 1792800000. |
| `deploy/debian/copyright` | DEP-5 format 1.0, with three stanzas. (1) `Files: *`, `Copyright: 2026 Bitdeer`, `License: proprietary` "All rights reserved." (2) `go.yaml.in/yaml/v3/*`: Apache-2.0, Canonical Ltd 2011-2019, pointing to `/usr/share/common-licenses/Apache-2.0`. (3) The eight libyaml-ported files: Expat (the DEP-5 name for the text the module's LICENSE calls MIT), Kirill Simonov 2006-2011, with the full text. Both are taken from the module's own LICENSE and NOTICE (checked against v3.0.5 in the module cache). The yaml module is not in `agent/go.mod` yet (TASK-087), so the stanza names no version. |

## The `dh_installsystemd` calls (acceptance criterion 2)

```make
override_dh_installsystemd:
	dh_installsystemd bitscan-agent.service bitscan-runner.socket
	dh_installsystemd --no-enable bitscan-runner.service
	dh_installsystemd --no-enable --no-start bitscan-capread.socket bitscan-capread.service
```

- Each call names its units, so each unit gets exactly one set of flags.
- The first call has the defaults: enable, start, and restart on upgrade. That gives TS §3.1 postinst step 4 (enable and start `bitscan-runner.socket` and `bitscan-agent.service`) and the upgrade restart (L175).
- `bitscan-runner.service` gets `--no-enable` only, exactly as TS L159 says. Note that without `--no-start` debhelper's snippet still starts (and on upgrade restarts) `bitscan-runner.service`. That is what the spec flags give, so I did not add `--no-start`. REQ-106 (3) only requires it to be not enabled.

## Choices the tester and the later deploy tasks must know

- **Staging layout (TASK-102):** `rules` expects the PD-26 staging tree: `bin/` holds the binaries, `debian/systemd/` the five agent units (copied unchanged from `deploy/systemd/`) and `debian/dbus/` the policy. `rules` installs the units itself, because TASK-096's `bitscan-agent.install` maps only the binaries and the policy.
- **Unit directory:** the units go to `/lib/systemd/system`, where debhelper compat 13 puts units on all three supported releases (`/usr/lib/systemd/system` comes only with compat 14).
- **`rules` mode:** Git on this Windows checkout has `core.fileMode=false`, so `rules` is stored without the executable bit. `build-deb.sh` (TASK-102) should `chmod 0755 debian/rules` in the staging tree. `dpkg-buildpackage` also fixes it, with a warning.
- **Source format (TASK-096):** the version has a Debian revision (`-1`), so `source/format` must be `3.0 (quilt)`, not `3.0 (native)`. A binary-only build (`-b`) needs no orig tarball.
- **`Depends: adduser`:** the TASK-100 plan creates the users with `adduser --system`, and lintian warns `maintainer-script-needs-depends-on-adduser` without it. `${misc:Depends}` adds `debconf` once TASK-096 adds `templates`. `${shlibs:Depends}` is left out: the binaries are static.
- **Expected lintian tags for TASK-105 (not fixable in TASK-092):**
  - `dbus-policy-in-etc`: TS §3.1 L161 fixes the path `/etc/dbus-1/system.d/`, while lintian prefers `/usr/share/dbus-1/system.d/`. This needs an override with that reason; keep the spec path.
  - Possibly `statically-linked-binary` and `no-manual-page` for the three `/usr/sbin` binaries.
  - Possibly `systemd-service-file-missing-install-key` for `bitscan-capread.service`, which has no `[Install]` section on purpose (TS §3.7).
  - Possibly `new-package-should-close-itp-bug` for the single `unstable` changelog entry. There is no Debian ITP, because this is not a Debian archive package.

  REQ-106 (4) wants each override listed with its reason.

## How to check

```sh
# policy byte-identical to TS L413-L430
python -I -c "from pathlib import Path; L=Path('docs/spec/Technical_Specification.md').read_bytes().splitlines(keepends=True); print(Path('deploy/dbus/bitscan-runner.conf').read_bytes()==b''.join(l.rstrip(b'\r\n')+b'\n' for l in L[412:430]))"
# flags
grep -n dh_installsystemd deploy/debian/rules
# metadata parses (on Linux with dpkg-dev / devscripts)
dpkg-parsechangelog -l deploy/debian/changelog -S Version   # 0.1.0~pre1-1
dpkg-parsechangelog -l deploy/debian/changelog -S Timestamp # 1792800000
```

The full checks happen in later tasks. `lintian`, the build and `dpkg-deb -c` need the staging tree from TASK-102 and the files from TASK-096, so they are run in TASK-102 and TASK-105.
