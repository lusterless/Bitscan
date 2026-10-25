# TASK-100 IMPL: maintainer scripts (postinst, postrm)

This task covers REQ-108 and REQ-107. Sources:
- TS §3.1 (L164 to L175) and §3.7 (the file ownership table).
- #79 (pin format), #81 (re-enrolment) and #82 (purge only the agent's files).
- The lead's install.env and re-enrolment rulings of 2026-10-24, quoted below.
- Supported hosts are now Ubuntu 22.04 and 24.04, amd64 only (decisions 2026-10-24: Debian 12 dropped).

Full rigor, two approvals recommended. No tests were run (that is the tester's job). There is no `shellcheck`, dash, debconf or systemd on this Windows machine. Run locally:
- `sh -n` on both scripts (passes);
- a smoke run of the four validators under Git Bash `sh`: the good URL, uppercase scheme, token and pin are accepted; `http://`, no host, a quote, a space, a 42-character token, a `bsa_` token, a `=` in the token, a 63-hex pin and a non-hex pin are refused.

## Files

Both files are new and LF only. No other file was touched.

| File | Code lines (without comments and blank lines) |
| --- | --- |
| `deploy/debian/postinst` | 160 |
| `deploy/debian/postrm` | 16 |

The total of 176 is close to the 170 estimate.

## Rulings applied (lead, 2026-10-24), for the reviewer and the user

### `/etc/bitscan/install.env` (proposal A to E, approved as written)

- **(A)** One `KEY=value` per line, taken literally: no quotes and no `$` expansion. Blank lines and `#` lines are skipped. The file is parsed with shell builtins and never sourced.
- **(B)** Keys: `MANAGER_URL`, `ENROL_TOKEN`, optional `CA_FILE` and `MANAGER_SPKI_SHA256`. An unknown key, a key given twice, or a line without `=` is refused with one fixed line that never echoes a value.
- **(C)** If the file exists, it replaces debconf completely. The debconf token is still cleared.
- **(D)** The file must be a regular file (not a symlink, so a dangling link is also refused), owned root:root, mode 0600. Otherwise it is refused and left in place, and the package stays unconfigured. It is deleted after a successful use.
- **(E)** When `/etc/bitscan/agent.yaml` already exists, the file may hold only `ENROL_TOKEN`. Any other key is refused, so a changed URL is never silently ignored.

### #81 (b) re-enrolment

If `agent.yaml` exists and the debconf token is non-empty (after `dpkg-reconfigure`, or a token preseeded at upgrade), `postinst`:
1. checks the token;
2. writes `enroll.token`;
3. clears the debconf value;
4. leaves the restart to the debhelper snippet. On `configure` with a previous version (upgrade or reconfigure) the snippet runs `restart`, and #81 (c) makes the agent enrol on start.

An empty token means a plain upgrade or reinstall, and nothing is written.

## `postinst configure`, step by step

1. **Users** (TS L170). `bitscan`, then `bitscan-runner`, each created only if `getent passwd` does not find it:
   - `adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin`;
   - `--ingroup` instead of `--group` if the group already exists.

   `adduser` output goes to stderr, because debconf owns stdout once the confmodule is loaded.
2. **Inputs.** `install.env` if it exists (or is a symlink, which is then refused), otherwise debconf (`db_get` on the four questions). Environment variables are never read: REQ-107 (4), CHK-M4-170.
3. **Configured before** (`agent.yaml` exists): see the rulings above. `agent.yaml`, `token` and `agent_id` are never rewritten (REQ-108 (3)).
4. **First install.**
   - The URL is checked first, then the token. Each missing one fails with one line, for example `bitscan-agent: the manager URL is missing; preseed bitscan/manager_url or write /etc/bitscan/install.env`. The exit status is 1, before `#DEBHELPER#`, so no unit is enabled or started and the package stays half-configured.
   - Then all four values are validated before anything is written:
     - **URL:** `https://`, any case, followed by a host character (not `/`, `?`, `#` or `@`). No quote, backslash, white space or control character. The agent's own check (`config.go`) does the full URL parse.
     - **Token:** `bse_` followed by exactly 43 characters from `[A-Za-z0-9_-]`, the `bse_` form of `BSA_PATTERN`.
     - **CA file:** empty, or an absolute path with no unsafe character that is a regular file the `bitscan` user can read (`setpriv --reuid=bitscan … test -r`). The agent reads it as `bitscan`, and a root-only file would leave it restarting every 10 s.
     - **Pin:** empty, or exactly 64 hex characters in either case (#79).
   - `enroll.token` is written first, then `agent.yaml`. An existing `agent.yaml` therefore always means the token was written. A failure between the two leaves no `agent.yaml`, so the retry runs the first-install path again.
5. **Clearing.** `db_set bitscan/enrol_token ""` (TS L172), then `rm -f /etc/bitscan/install.env` if the file was used.
6. **`db_stop`, then `#DEBHELPER#`.** The TASK-092 `rules` snippets enable and start `bitscan-agent.service` and `bitscan-runner.socket` (TS L173), or restart them on upgrade (TS L175).

`abort-*` arguments do nothing. Any other argument fails.

## Files written, and how

- **`/etc/bitscan/`** is created as root:root 0755 only if it is missing. An existing folder, possibly the manager's, keeps its owner and mode.
- **`agent.yaml`** (root:bitscan 0640) is written through `/etc/bitscan/agent.yaml.tmp`: umask 077, then `chown`, `chmod`, `mv -f`.
  - It holds the full TS §3.6 key set. The three inputs are single-quoted, and the validators have already refused `'`, so a value cannot break the YAML. The rest are the #4 values: `state_dir: /var/lib/bitscan-agent`, `heartbeat_seconds: 300`, `job_pull_seconds: 300`, `max_parallel_plugins: 2`, `spool_max_mb: 50`, `log_level: info`.
  - `ca_file` and the pin are written as `''` when unset. The loader reads that as empty.
  - The token is never in `agent.yaml`.
- **`/var/lib/bitscan-agent/`** is set to bitscan:bitscan 0700 with `install -d`.
- **`enroll.token`** (bitscan:bitscan 0600) is the token plus a newline. The agent trims it (`state.EnrolToken`).
  - **Security point for the reviewer:** the file is written as `bitscan`, not as root. The command is `printf | setpriv --reuid=bitscan --regid=bitscan --clear-groups --reset-env sh -c 'umask 077 && rm -f enroll.token.tmp && cat > enroll.token.tmp && mv -f …'`. The folder belongs to `bitscan`, so a root write there could follow a symlink that a compromised agent planted, for example `enroll.token.tmp` pointing to `/etc/shadow`. As `bitscan`, the write can reach only what `bitscan` could already write.
  - The token goes through a pipe from the `printf` builtin, never through a command's arguments, so it never shows in `/proc/*/cmdline`. Every token check uses builtins only (`${#…}`, `case`, `[`).
- **Messages** are fixed text. No input value is ever printed (builder checklist items 11 and 12).

## `postrm`

- **`purge`** (#82):
  - `rm -rf /var/lib/bitscan-agent`, then `rm -f` on `/etc/bitscan/agent.yaml`, `agent.yaml.tmp` and `install.env`. All are fixed literal paths, with no variable in any `rm` (CHK-M4-176).
  - Then `rmdir --ignore-fail-on-non-empty /etc/bitscan` if the folder exists, so a planted `manager.env` or `secrets/` survives together with the folder.
  - The debconf answers are purged by the `dh_installdebconf` snippet in `#DEBHELPER#`.
  - The users are kept.
- **`remove`, `upgrade`, `failed-upgrade`, `abort-*`, `disappear`:** nothing of ours. The `dh_installsystemd` snippets stop and disable the units.
- **Unknown argument:** fails.

Both scripts can run twice in a row. `adduser` is skipped for an existing user, `install -d` reapplies the same owner and mode, the temporary files have fixed names and are removed first, and every `rm` is `-f`.

## For the tester

- Dependencies: `setpriv` (util-linux), `stat` (coreutils) and `getent` (libc-bin) are Essential on Ubuntu, and `adduser` is in `Depends`. setpriv's `--reset-env` needs util-linux 2.35 or later; Ubuntu 22.04 has 2.37.
- **CHK-M4-168:** a missing input exits before `#DEBHELPER#`, so `dpkg -s` shows `half-configured` and no bitscan unit is enabled or active. The debconf token stays set after a failure, because it was never used, so a fixed preseed plus `dpkg --configure bitscan-agent` can recover.
- **CHK-M4-169:** a 0644 or user-owned `install.env` is refused and left in place (ruling D).
- **CHK-M4-174:** for re-enrolment, use `dpkg-reconfigure` with a preseeded new token. `config` (TASK-096) asks only the token question, and `postinst` writes `enroll.token` while `agent.yaml` stays byte-identical. The restart comes from the debhelper snippet.
- **Planted symlink:** as root, plant `/var/lib/bitscan-agent/enroll.token.tmp` pointing to a root-owned file, then re-enrol. The root-owned file must stay unchanged. The `bitscan` shell removes the link first, so re-enrolment still succeeds and `enroll.token` is a regular bitscan:bitscan 0600 file.
- **lintian (TASK-105):** I expect no new tags from these scripts. Commands are called without absolute paths, `set -e` is used, and `adduser` is in `Depends`. `debconf-is-not-a-registry` can only appear if lintian objects to `db_get` in `postinst`, which TS §3.1 requires.

## Revision 1 (before the first TEST; lead ruling 2026-10-24, from the reviewer's pre-read)

Only `deploy/debian/postinst` changed (now 179 code lines; `postrm` unchanged). Test r0 and r1 together. Local checks: `sh -n` passes; a Git Bash smoke run of the two new `case` patterns gives the results listed below.

1. **Rule (E) tracks keys, not values.** `read_env_file` now records every key it reads in `ENV_KEYS` (the former local `seen`; it also drives the duplicate check). With an existing `agent.yaml`, the file may hold no key or only `ENROL_TOKEN`; any other key fails with the same fixed line as before (`… may hold only ENROL_TOKEN once agent.yaml exists`), **even when its value is empty**, for example `MANAGER_URL=` or `CA_FILE=`. Before r1 an empty `MANAGER_URL=` passed, because the check looked at `$URL$CA$PIN`.
2. **`/etc/bitscan` owner and mode.** New `check_conf_dir`, the first step of `configure` (before users, inputs or any write). If `/etc/bitscan` exists (or is a dangling symlink) it must be a real directory (not a symlink), owned by uid 0, with no group-write and no other-write bit. Otherwise `postinst` exits 1 before `#DEBHELPER#` with one fixed line, `bitscan-agent: /etc/bitscan must be a directory owned by root and not writable by group or others`, writes nothing, leaves `install.env` in place, and the package stays unconfigured. The group owner is not checked (only the owner uid and the write bits). A missing `/etc/bitscan` is still created as root:root 0755. The check also runs on upgrade and reconfigure, so a tampered folder blocks every `configure`.
   - Smoke results (`stat -c '%u %a'` → result): `0 755`, `0 750`, `0 700`, `0 2755`, `0 1755` accepted; `0 775`, `0 757`, `0 777`, `0 765`, `0 735`, `0 1777`, `1000 755` refused.

For the tester (new cases): an existing `agent.yaml` plus `install.env` with `MANAGER_URL=` (empty) or `ENROL_TOKEN=<valid>` and `CA_FILE=` is refused, the file stays, `enroll.token` is not written; `ENROL_TOKEN=<valid>` alone is still accepted. `/etc/bitscan` as `chown 1000 /etc/bitscan`, `chmod 0775`, `chmod 0757`, `chmod 1777`, or replaced by a symlink to a root-owned 0755 directory, each fails `dpkg --configure bitscan-agent` with the line above and enables no unit; restoring root 0755 then configures normally.

## Revision 2 (reviewer round 1 nits, work/reviews/TASK-100.md; lead 2026-10-25: apply only the clearly safe ones)

Only `deploy/debian/postinst` changed (three lines changed, one comment line added; `postrm` unchanged). `sh -n` passes; the file is LF and ASCII. No test was run.

| Nit | Taken | Change |
| --- | --- | --- |
| (3) bitscan children inherit the debconf pipes | yes | `check_ca`: `setpriv … test -r "$CA" </dev/null 3>&-`. `write_token`: `3>&-` on the `setpriv … sh -c '…'` call (its stdin stays the token pipe). The children running as bitscan no longer hold debconf's fd 3 (command pipe) or, in `check_ca`, fd 0 (reply pipe). |
| (4) `mv -f` into a planted directory | yes | `mv -fT …/enroll.token.tmp …/enroll.token`: if `enroll.token` is a directory, `mv` now fails, the `sh -c` exits non-zero and postinst fails under `set -e` instead of succeeding without a token. |
| (5) CA under `/home`, `/root`, `/run/user` or `/tmp` passes postinst but is hidden by `ProtectHome` and `PrivateTmp` | runbook only (TASK-107 revision 2) | No postinst change: refusing path prefixes would be a new install rule the spec does not state. The runbook now says to keep the CA under `/etc` (example `/etc/bitscan/ca.pem`). |
| (6) an existing non-system `bitscan` or `bitscan-runner` account is reused silently | no | Refusing an account needs a uid-range and shell rule the spec does not give, and it would change the reinstall path. Left for the lead if wanted. |

For the tester (TASK-100 r2): re-run the existing suite (install, reinstall, upgrade, reenrol, the symlink case and the CA checks) to show no regression; new cases if wanted: (a) a directory planted at `/var/lib/bitscan-agent/enroll.token` makes re-enrolment fail (`dpkg --configure` non-zero) instead of passing; (b) during `write_token` and `check_ca`, the bitscan child has no fd 3 (for example with the `/usr/local/bin/cat` wrapper also logging `ls -l /proc/self/fd`).

**Final r2 file:** the `postinst` saved at 01:31 (nits 3 and 4) is the final TASK-100 r2 version; no further change is made before the re-test. Summary: nits 3 and 4 applied in postinst; nit 5 not in postinst, handled in the runbook (TASK-107 r2); nit 6 skipped (no spec rule for uid range or shell, and it would change the reinstall path).
