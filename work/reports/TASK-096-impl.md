# TASK-096 IMPL: debconf templates, config, install file, source format

REQ-107, REQ-106. TS §3.1 (L158, L161, L164), #79 (pin format), #81 (b) (re-enrolment with `dpkg-reconfigure`), PD-26 (a). Builds on TASK-092.

No tests were run (that is the tester's job). There is no `shellcheck`, `checkbashisms`, debconf or lintian on this Windows machine, so I checked `config` for POSIX `sh` by reading it. All files use LF and are new. Nothing outside the four task files was changed.

## Files

| File | What |
| --- | --- |
| `deploy/debian/templates` | The four TS §3.1 questions, with no `Default:`: `bitscan/manager_url` (`string`), `bitscan/enrol_token` (`password`, so debconf keeps it only in `passwords.dat`), `bitscan/ca_file` (`string`) and `bitscan/manager_spki_sha256` (`string`; the description gives the #79 format). The short descriptions are prompts ending in `:`, which lintian `malformed-prompt-in-templates` expects. |
| `deploy/debian/config` | POSIX `sh` with `set -e` (see "What `config` does"). |
| `deploy/debian/bitscan-agent.install` | `bin/bitscan-{agent,runner,capread}` go to `usr/sbin`, and `debian/dbus/bitscan-runner.conf` goes to `etc/dbus-1/system.d`. Paths are relative to the PD-26 staging tree. `dh_fixperms` gives 0755 to `usr/sbin` files and 0644 to the policy. Because the policy is under `/etc`, `dh_installdeb` makes it a conffile. |
| `deploy/debian/source/format` | `3.0 (quilt)` followed by a newline. The version has a Debian revision (`-1`), and a binary-only `dpkg-buildpackage -b` needs no orig tarball. |

## What `config` does

1. If `/etc/bitscan/install.env` exists, it asks nothing. TS §3.1 makes that file the alternative to debconf; `postinst` (TASK-100) reads it and deletes it.
2. If `/etc/bitscan/agent.yaml` exists (the package was configured before):
   - an upgrade or reinstall asks nothing (TS L175);
   - `dpkg-reconfigure bitscan-agent` (`$1 = reconfigure`) asks only `bitscan/enrol_token` (#81 (b)).
3. On a first install it asks the URL and the token at priority `high`, and `ca_file` and the pin at `low`. Preseeded answers are marked seen, so a non-interactive preseeded install prompts for nothing.
4. If the URL or the token is still empty, `config` clears its seen flag first. After a first install fails on a missing input, a `dpkg --configure` run interactively then asks again. Without this, the empty answer would count as answered and `postinst` would fail the same way every time.

`config` does no validation and never clears the token. `postinst` (TASK-100) validates the values (https URL, `bse_` form, `ca_file` exists, 64-hex pin) and runs `db_set bitscan/enrol_token ""`.

## For the tester

- Run CHK-M4-121 with a password-type question in a scratch database. With the default `/etc/debconf.conf`, a value set by `debconf-set-selections` is written to `passwords.dat` only. A `DEBCONF_DB_*` override that merges the databases would hide that split.
- `config` reads only `$1` and the existence of two fixed paths. It ignores every environment variable, which is REQ-107 (4).
- `dpkg-reconfigure` on a package that never finished configuring is refused by dpkg. The recovery path for a failed first install is to preseed or write `install.env`, then `dpkg --configure bitscan-agent`.

## Carry-overs (from TASK-092 REVIEW, for TASK-102 and TASK-105)

- Set the executable bit on `deploy/debian/rules` in git with `git update-index --chmod=+x deploy/debian/rules` when the change is staged for the commit. I did not run it, because I don't stage or commit. `config` needs no git bit: `dh_installdebconf` installs it as `DEBIAN/config` 0755.
- TASK-105 lists every lintian override with its reason. Possible new tags from these files: `untranslatable-debconf-templates` and `not-using-po-debconf`. The package has no `po/` folder, and translations are not in scope.

## How to check

```sh
grep -n '^Template:\|^Type:' deploy/debian/templates
cat deploy/debian/bitscan-agent.install deploy/debian/source/format
sh -n deploy/debian/config
```
