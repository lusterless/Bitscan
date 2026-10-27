# TASK-175 IMPL: sample policy CIS Ubuntu 22.04 Level 1 - Server

Owner: impl-bits. REQ-179; #111 (approved recommendation, decisions 2026-10-27). Spec: SR §1, §2, §2.4 script rules, §4.1, §4.2; TS §3.5, §3.7, §6.5 default redaction patterns, §8.5.

## What changed

| File | Change |
| --- | --- |
| `bits/samples/cis-ubuntu-22.04-l1-server.bit` | new, 207 lines (data), UTF-8, LF |

No other file was changed.

- `PolicyName` `CIS Ubuntu 22.04 Level 1 - Server` (differs from TASK-174's), `FamilyName` `CIS Ubuntu 22.04`, `PolicyStatus` `enabled`, `formatVersion="1.0"`.
- `PolicyDescription` ends with the #111 note: "Control numbers are not yet confirmed against the CIS benchmark copy (TS §8.5)."
- 16 plugins, all with new random v4 ids, lowercase. None is shared with TASK-174 or SR §1.1.
- Control numbers follow my reading of CIS Ubuntu 22.04 LTS Benchmark v1.0.0, whose layout differs from 24.04's (for example AppArmor is 1.6.1.1, SSH is 5.2.x, accounts are 5.5.x, file permissions are 6.1.x). They are **unconfirmed** (#111).
- Where a control is the same as in 24.04, the script is the same text as TASK-174's, so both samples behave alike. Rows 5, 8, 11, 13 and 15 are new here.

## Per-plugin rows (script rules, SR §2.4)

"Read-only" means the same as in TASK-174: no write or redirect other than `2>/dev/null`, no SR §4.2 word, option or verb, no code-running form, and only system binaries run, reading files as data. Tested output = an `ubuntu:22.04` container (22.04.5; mawk, coreutils 8.32, util-linux 2.37.2, dpkg 1.21.1) run as uid 65534 with `--network none --read-only --memory 128m`, a tmpfs `/tmp` and `--rm`, under the runner environment (`env -i`, the TS §3.5 PATH, stdin `/dev/null`). The base image is minimal, so "not installed" results are expected there. SSH, shadow and modprobe logic shared with TASK-174 was also run against `/tmp` fixtures in WSL with mawk (see TASK-174).

| # | PluginName | Command (summary) | Operator / ExpectedResult | Why read-only, notes | Tested output (22.04 container) → result |
| --- | --- | --- | --- | --- | --- |
| 1 | 1.1.1.1 - Ensure mounting of cramfs filesystems is disabled | as TASK-174 row 2 | `regex` / `^(absent\|loaded=no install=yes blacklist=yes)$` | reads `/proc/modules`, `/lib/modules`, modprobe.d files; no `modprobe` | `absent` (the container has no `/lib/modules`) → PASS. WSL fixture: the pass state and the FAIL state |
| 2 | 1.1.2.2 - Ensure nodev option set on /tmp partition | `findmnt --task 1 -n -f -o OPTIONS --mountpoint /tmp` | `regex` / `(^\|,)nodev(,\|$)` | host view (SR §2.4) | `rw,nosuid,nodev,noexec,relatime,size=8192k` (the container's own tmpfs as seen by its PID 1) → PASS |
| 3 | 1.5.1 - Ensure address space layout randomization (ASLR) is enabled | `cat /proc/sys/kernel/randomize_va_space` | `eq` / `2` | reads /proc | `2` → PASS |
| 4 | 1.5.2 - Ensure prelink is not installed | `dpkg-query … prelink \| awk` (name unless `not-installed`/`config-files`) | `empty` | dpkg db read | empty → PASS; the same pipeline for `dpkg prelink` printed `dpkg` (the status field works on dpkg 1.21) |
| 5 | 1.6.1.1 - Ensure AppArmor is installed | `for p in apparmor apparmor-utils`: `dpkg-query -W -f='${db:Status-Status}' "$p"`, prints the name unless `installed` | `empty` | dpkg db read; a package unknown to dpkg is listed, so a missing package can never pass | `apparmor`, `apparmor-utils` → FAIL (minimal image). WSL 24.04: `apparmor-utils` |
| 6 | 2.3.4 - Ensure telnet client is not installed | as row 4 for `telnet` | `empty` | dpkg db read | empty → PASS |
| 7 | 3.2.2 - Ensure IP forwarding is disabled | as TASK-174 row 10 | `regex` / `^ipv4=0 ipv6=(0\|absent)$` | reads /proc | `ipv4=1 ipv6=0` → FAIL (Docker host) |
| 8 | 3.3.8 - Ensure TCP SYN Cookies is enabled | `cat /proc/sys/net/ipv4/tcp_syncookies` | `eq` / `1` | reads /proc | `1` → PASS |
| 9 | 3.5.1.1 - Ensure ufw is installed | `dpkg-query -W -f='${Status}' ufw` | `equals` / `install ok installed` | dpkg db read | empty → FAIL (minimal image) |
| 10 | 5.1.1 - Ensure cron daemon is enabled and running | as TASK-174 row 9 | `equals` / `enabled active` | read-only `systemctl is-enabled` / `is-active` | ` ` (no systemctl in the image; trims to empty) → FAIL. WSL 24.04: `enabled active` |
| 11 | 5.2.1 - Ensure permissions on /etc/ssh/sshd_config are configured | if `/etc/ssh/sshd_config` exists: `stat -Lc '%04a %U %G'`, prints `<file> <mode> <owner> <group>` unless `0[0246]00 root root` | `empty` | stat only (22.04 v1.0.0 covers this one file) | empty (no openssh-server) → PASS (not applicable). WSL fixture 0644: printed |
| 12 | 5.2.7 - Ensure SSH root login is disabled | as TASK-174 row 13 | `regex` / `^(no\|not-installed)$` | config read as data; no `sshd -T` (needs root) | `not-installed` → PASS. Fixtures as TASK-174 |
| 13 | 5.2.18 - Ensure SSH MaxAuthTries is set to 4 or less | as row 12 for `maxauthtries`, default `6` | `regex` / `^([1-4]\|not-installed)$` | as row 12; a regex rather than `le`, so `not-installed` is not an ERROR | `not-installed` → PASS. WSL fixtures: `3` in `sshd_config` → `3`; `8` in a `.d` file wins → `8` |
| 14 | 5.5.1.2 - Ensure password expiration is 365 days or less | `awk '$1 == "PASS_MAX_DAYS" …' /etc/login.defs` | `le` / `365` | reads a file | `99999` → FAIL (stock default) |
| 15 | 6.1.1 - Ensure permissions on /etc/passwd are configured | `stat -Lc '%04a %U %G' /etc/passwd` | `regex` / `^0[0246][04][04] root root$` | stat only; `%04a` keeps setuid/setgid/sticky bits visible (`4644` fails) | `0644 root root` → PASS |
| 16 | 6.2.2 - Ensure /etc/shadow password fields are not empty | as TASK-174 row 16 | `empty` | reads a file, prints names only | `unreadable` → FAIL (uid 65534 has no `CAP_DAC_READ_SEARCH`, as expected) |

Operators used: `equals`, `regex`, `eq`, `le`, `empty`. Every regex plugin prints one line. No compared value can hold text a TS §6.5 default redaction pattern would hide.

## How it was checked

1. The same validator as TASK-174, run over both files at once: every SR §4.1 rule, the #111 note, distinct `PolicyName`s, no plugin id shared between the samples, CDATA, and the rough BIT102 scan. Result: **no findings**. The planted copy showed a duplicated id across files is caught.
2. `dash -n` on every `Execute`: all 16 OK (in the 22.04 container and in WSL).
3. Ran read-only in the container as above. The container was removed (`docker ps -a` showed none left). Nothing ran as root, and nothing was written outside the container's tmpfs `/tmp`.
4. RE2 check of the regex `ExpectedResult`s (TASK-174 item 4, which covers rows 1, 2, 7, 12, 13 and 15).

## For the tester

- G59 and CHK-M7-366: import this file with TASK-174's into one fresh catalog; both should end `success`, with no Reject and no BIT102. The BIT102 constructs listed in TASK-174 also appear here, plus a `for … do … done` holding `$( )` and an `if`.
- The M10 sandbox notes in TASK-174 apply here too (rows 2, 10, 16).
