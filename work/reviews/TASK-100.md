# TASK-100 REVIEW: maintainer scripts (postinst, postrm), r0 + r1 + r2

Verdict: APPROVED (round 2). Round 1 was CHANGES_REQUESTED on the tests only (Findings 1 and 2). Round 2 closes both, and r2 takes nits 3 and 4.

Round 1 history: CHANGES_REQUESTED. No product change was required. Findings 1 and 2 were test-side (tester-m4b). Findings 3 to 6 were nits for impl-deploy.

Reviewer: reviewer, 2026-10-25. Full rigor (maintainer scripts run as root and handle the `bse_` token). **Two approvals (TS §8.2, decisions 2026-10-24): the user's second approval follows this review's APPROVED.**

Scope reviewed: `deploy/debian/postinst` (179 code lines) and `deploy/debian/postrm` (16), per `work/reports/TASK-100-impl.md` including "Revision 1". Sources:
- TS §3.1 L158–L175, §3.6, §3.7 L490–L496.
- REQ-107, REQ-108, #81 (b), #82.
- Decisions 2026-10-24 (install.env A–E; r1 key tracking and `/etc/bitscan` owner and mode) and 2026-10-25 (D2: runbook warning only, no postinst change).

TEST: PASS (`work/reports/TASK-100-test.md`, rows CHK-M4-165..177 and -175-r1). 529/529 passed on Ubuntu 24.04 and on 22.04. Debian 12 NOT RUN (dropped by the user). The G38 plants CHK-M4-357..361 are NOT RUN (drain).

## Checks
1. **Spec.**
   - Users are created as system users with `/usr/sbin/nologin` and `/nonexistent`.
   - `agent.yaml` is root:bitscan 0640 with exactly the TS §3.6 keys and never holds the token.
   - `enroll.token` is bitscan:bitscan 0600, and the state directory is bitscan:bitscan 0700.
   - The debconf token is cleared with `db_set bitscan/enrol_token ""` (TS L172).
   - A missing URL or token exits 1 before `#DEBHELPER#`, with one fixed line. The package stays half-configured and no unit is enabled.
   - On upgrade nothing is read or written, and the debhelper snippet restarts the units (TS L175).
   - Purge follows #82: fixed literal paths, and `rmdir --ignore-fail-on-non-empty`.
   - No environment variable is read (REQ-107 (4)).
2. **install.env against the decisions.**
   - (A) The file is read with `read -r` and `${line%%=*}`/`${line#*=}` and never sourced. A `=` inside a value is kept.
   - (B) The four keys only. An unknown key, a duplicate key or a line without `=` gets a fixed line that echoes no value. The duplicate test pattern is quoted, so a key holding `*` matches literally.
   - (C) When the file exists, debconf is not read at all, and the debconf token is still cleared on success.
   - (D) The file must not be a symlink, must be a regular file, and `stat` must give `0:0 600`. A refused file is left in place. The file is deleted only after success.
   - (E) + r1: `ENV_KEYS` records every key, empty values included. On a configured host only `" "` or `" ENROL_TOKEN "` passes.
   - r1 `/etc/bitscan`: it must be a real directory with uid 0. The mode patterns `*[2367]` and `*[2367][0-7]` refuse group-write and other-write on every `%a` length (I checked 3- and 4-digit modes and 000). The check runs before any user, read or write.
   - CRLF lines fail closed: `\r` is refused as a control character, or gives a wrong token length or an unknown line.
3. **setpriv write of `enroll.token`.** The `printf` builtin pipes the token into `setpriv --reuid=bitscan --regid=bitscan --clear-groups --reset-env sh -c '…'`.
   - The token is never in an argv or environ (CHK-M4-177 checked this with a sampler).
   - Root only runs `install -d` on `/var/lib/bitscan-agent`. `/var/lib` is root-only, so that path cannot be planted by the agent.
   - `rm`, `cat` and `mv` run as uid bitscan with no capabilities. A link planted between `rm` and `cat` therefore reaches only files bitscan can already write.
   - `mv` renames over a planted `enroll.token` link and does not follow it.
4. **CA-file readability refusal.**
   - The path must be absolute and free of unsafe characters.
   - `[ -f ]` as root follows links and refuses a FIFO or a directory (checklist 14).
   - `setpriv … test -r` then proves bitscan can read the file.
   - A root-only 0600 file is refused (CHK-M4-175).
5. **Writes as root.** These happen only in `/etc/bitscan`, which r1 guarantees is root-owned and not group- or other-writable. `agent.yaml.tmp` is removed first and created under umask 077. The values hold no `'`, backslash, white space or control character, so the single-quoted YAML cannot be broken.
6. **Idempotence.**
   - `getent` skips existing users, and `install -d` reapplies the same owner and mode.
   - The temporary files have fixed names and are removed first.
   - The token is written before `agent.yaml`, so a failure between the two re-runs the first-install path.
7. **Re-run by the reviewer (Windows).** `sh -n` passes on both files. Both are LF and ASCII. shellcheck is not available here. The tester's shellcheck 0.9.0 run found only SC1091 (CHK-M4-176), and I accept that.
8. **Scope.** 2 files, 195 code lines, no other file touched.
9. **r2 (`work/reports/TASK-100-impl.md` "Revision 2").** Only `postinst` changed, by three lines and a comment:
   - `check_ca` runs `setpriv … test -r "$CA" </dev/null 3>&-`;
   - `write_token` closes fd 3 on its `setpriv` call (stdin is still the token pipe) and uses `mv -fT`.
   - I read the diff, and `sh -n` passes.
10. **Round 2 TEST (tester-m4b, rows CHK-M4-357..361, -174-writer, -174-r2 and -167-r2): PASS.**
    - The final full run is 542/544 on u24 and u22. The 2 failures were tester bugs, and the targeted re-runs (symlink 19/19, install 43/43) pass on both.
    - Every G38 plant is red: 357 (token in `agent.yaml`), 358 (debconf token not cleared), 359 (an environment input read), 360 (`rm -rf /etc/bitscan`) and 361a/b, plus both `set -e` plants.
    - 361c (only `--no-start` dropped) does not change runtime behaviour, because `deb-systemd-invoke` starts neither capread unit. The install test now also asserts both units were never started, and CHK-M4-072 catches that plant statically. I accept this.

## Findings
1. **Closed in round 2.** should-fix (tester-m4b), G38 not proven. CHK-M4-357..361 have not been run yet. Under full rigor, each row must turn red on its plant before approval. Fix: run the five plants and add a row for each to `tests/m4/report.md`.
2. **should-fix (tester-m4b), the setpriv property is untested.** Location: `deploy/tests/test_maintainer_scripts.sh` `sub_symlink` (L743–L768), checking `postinst:162-167`.
   - The planted `enroll.token.tmp` link is removed by `rm -f` before the write. A root write would therefore pass that test too. A root write followed by `chown bitscan:bitscan` (for example `install -o bitscan -g bitscan -m 0600 /dev/stdin …`) passes every current row.
   - So nothing shows that the write runs as bitscan, which is the point of the design (impl report, "Security point for the reviewer").
   - Fix: add a deterministic check. `--reset-env` sets PATH to `/usr/local/bin:/bin:/usr/bin`, so a test-only wrapper `/usr/local/bin/cat` in the disposable container can log `id -u` and exec `/bin/cat`. Assert that the writer's uid is bitscan's.
   - Then plant "write_token as root, then chown" and show that row goes red. A sampler on `/proc` is not enough: the `sh -c` lives for a few milliseconds.
   - **Closed in round 2** (CHK-M4-174-writer):
     - Wrappers for `cat`, `tee`, `dd`, `install`, `cp` and `mv` sit in `/usr/local/bin`. That directory is on the reset PATH that `setpriv` gives the bitscan child, and not on root's PATH. They log the tool, the uid and whether fd 3 is open for any call touching `enroll.token*`.
     - On the final `.deb`, every record is uid 101 (bitscan) with fd3=n.
     - Plant `rootw` (root write, then `chown`) is red: "write not observed".
     - Plant `rootw2` (the same, with the wrappers on root's PATH) is red: "cat 0, mv 0".
     - The check is deterministic and covers both ways a root writer could escape it.
3. **nit, `postinst:164-166`, `127`. The bitscan children inherit debconf's file descriptors.** The confmodule leaves fd 3 as the command pipe to the debconf frontend. In `check_ca`, the child also gets fd 0 as the reply pipe.
   - The pipes are root-owned 0600, so a compromised agent cannot reopen them through `/proc/<pid>/fd`.
   - `pidfd_getfd` and ptrace need attach rights, which Yama `ptrace_scope=1` (the Ubuntu default) withholds.
   - On a host with `ptrace_scope=0`, a compromised agent racing a re-enrolment could write debconf commands (`SET` on any package's question).
   - Defence in depth, optional: add `3>&-` to both `setpriv` calls and `</dev/null` to the `test -r` one.
   - **Taken in r2.** The pre-r2 `.deb` is red on the new fd-3 checks (CHK-M4-174-r2).
4. **nit, `postinst:166`. `mv -f tmp enroll.token` moves the file into `enroll.token` if that is a directory.** postinst then succeeds without writing the token. This is reachable only by a compromised or broken agent. Optional: `mv -fT`. **Taken in r2.** A planted directory now makes `dpkg-reconfigure` fail, and the directory is left empty (CHK-M4-174-r2).
5. **nit, `postinst:121-130`. `test -r` runs outside the agent's sandbox.** `ProtectHome=yes` and `PrivateTmp=yes` hide `/home`, `/root`, `/run/user` and `/tmp` from the agent. A CA there passes postinst, and then the agent restarts every 10 s, which is the failure this check exists to prevent. Optional: refuse those prefixes, or say in the TASK-107 runbook to keep the CA under `/etc` or `/usr/local/share/ca-certificates`. **Handled in the TASK-107 runbook (r2).** The script is unchanged, because the spec states no prefix rule. I accept that.
6. **nit, `postinst:28-31`. An existing non-system `bitscan` or `bitscan-runner` account is reused silently.** An admin may have created a login user with that name. `adduser --system` would refuse such an account, but the `getent` skip bypasses that check, and the account could then read the agent token. Optional: refuse an existing account whose uid is outside the system range or whose shell is not `nologin`/`false`. **Not taken** (no spec rule; it would change the reinstall path). I accept that, as a residual noted for the runbook.
