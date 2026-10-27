# TASK-174 IMPL: sample policy CIS Ubuntu 24.04 Level 1 - Server

Owner: impl-bits. REQ-179; #111 (approved recommendation, decisions 2026-10-27). Spec: SR §1.1, §2, §2.4 script rules, §4.1, §4.2; TS §3.5, §3.7, §6.5 default redaction patterns, §8.5.

## What changed

| File | Change |
| --- | --- |
| `bits/samples/cis-ubuntu-24.04-l1-server.bit` | new, 198 lines (data), UTF-8, LF |

No other file was changed. Nothing outside `bits/samples/` and this report.

- `PolicyName` `CIS Ubuntu 24.04 Level 1 - Server`, `FamilyName` `CIS Ubuntu 24.04` (both as in SR §1.1), `PolicyStatus` `enabled`, `formatVersion="1.0"`.
- `PolicyDescription` ends with the #111 note: "Control numbers are not yet confirmed against the CIS benchmark copy (TS §8.5)."
- 16 plugins. Plugin 1 is the SR §1.1 plugin, byte-identical (the `<Plugin>` … `</Plugin>` block, indentation and CDATA whitespace included, id `3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48`). Plugins 2 to 16 have new random v4 ids, lowercase, none shared with TASK-175.
- Control numbers follow my reading of CIS Ubuntu 24.04 LTS Benchmark v1.0.0 and are **unconfirmed** (#111). The owner confirms them before M11 uses the samples.

## Per-plugin rows (script rules, SR §2.4)

"Read-only" for every row: no write or redirect other than `2>/dev/null`, no BIT102 command word, no `sed -i`, `apt`, `dpkg` action or `systemctl` verb from SR §4.2, no `xargs`, `find -exec`, `eval`, `.`, `sh -c`, no backticks or `<( )`. Nothing is executed, sourced or `cd`'d into from a writable path: only system binaries run, and every file is read as data. Tested output = WSL Ubuntu 24.04.5, user `bstester` (uid 1000, no capabilities), runner environment (`env -i`, `PATH=/usr/sbin:/usr/bin:/sbin:/bin`, stdin `/dev/null`, `/bin/sh` = dash), with stock `mawk` 1.3.4 as `awk` (this WSL box uses gawk by default; a stock server uses mawk).

| # | PluginName | Command (summary) | Operator / ExpectedResult | Why read-only, notes | Tested output (WSL) → result |
| --- | --- | --- | --- | --- | --- |
| 1 | 1.3.1.1 - Ensure AppArmor is installed | `dpkg-query -W -f='${Status}' apparmor` (SR §1.1) | `equals` / `install ok installed` | dpkg-query reads the dpkg database | `install ok installed` → PASS |
| 2 | 1.1.1.1 - Ensure cramfs kernel module is not available | `grep` `/proc/modules`; `find /lib/modules/$(uname -r) -name 'cramfs.ko*' -print`; `grep -Eq` the `install … /bin/(false\|true)` and `blacklist` lines in `/etc`, `/run`, `/usr/local/lib`, `/lib` `modprobe.d/*.conf`; prints `absent` or `loaded=… install=… blacklist=…` | `regex` / `^(absent\|loaded=no install=yes blacklist=yes)$` | reads files only; no `modprobe` call. The variables are `ld`, `ins`, `bl` so no assignment looks like the word `install` | `loaded=no install=no blacklist=no` → FAIL (stock: module shipped, not disabled). Fixture with `install cramfs /bin/false` + `blacklist cramfs`: `loaded=no install=yes blacklist=yes`; a missing module: `absent` |
| 3 | 1.1.2.1.2 - Ensure nodev option set on /tmp partition | `findmnt --task 1 -n -f -o OPTIONS --mountpoint /tmp` | `regex` / `(^\|,)nodev(,\|$)` | host view via PID 1 (SR §2.4); `--task` cannot be combined with `--kernel` (findmnt refuses) | empty, rc 1 (/tmp is not a separate mount) → FAIL |
| 4 | 1.1.2.2.3 - Ensure nosuid option set on /dev/shm partition | `findmnt --task 1 -n -f -o OPTIONS --mountpoint /dev/shm` | `regex` / `(^\|,)nosuid(,\|$)` | as row 3 | `rw,nosuid,nodev,noatime` → PASS |
| 5 | 1.5.1 - Ensure address space layout randomization is enabled | `cat /proc/sys/kernel/randomize_va_space` | `eq` / `2` | reads /proc | `2` → PASS |
| 6 | 1.5.2 - Ensure ptrace_scope is restricted | `cat /proc/sys/kernel/yama/ptrace_scope` | `ge` / `1` | reads /proc | `1` → PASS |
| 7 | 1.5.4 - Ensure prelink is not installed | `dpkg-query -W -f='${Package} ${db:Status-Status}\n' prelink \| awk` (prints the name unless `not-installed` or `config-files`) | `empty` | dpkg db read | empty → PASS; same script with `apparmor`: `apparmor` (installed packages are listed) |
| 8 | 2.2.4 - Ensure telnet client is not installed | as row 7 for `telnet inetutils-telnet` | `empty` | dpkg db read | empty → PASS |
| 9 | 2.4.1.1 - Ensure cron daemon is enabled and active | `printf '%s %s\n' "$(systemctl is-enabled cron.service)" "$(systemctl is-active cron.service)"` | `equals` / `enabled active` | `is-enabled` / `is-active` are read-only D-Bus queries (SR §4.2 allows `systemctl is-enabled`) | `enabled active` → PASS |
| 10 | 3.3.1 - Ensure ip forwarding is disabled | `cat` `ipv4/ip_forward` and `ipv6/conf/all/forwarding` (`absent` if IPv6 is off); prints `ipv4=… ipv6=…` | `regex` / `^ipv4=0 ipv6=(0\|absent)$` | reads /proc | `ipv4=1 ipv6=0` → FAIL (Docker on this box turns forwarding on) |
| 11 | 4.1.1 - Ensure ufw is installed | `dpkg-query -W -f='${Status}' ufw` | `equals` / `install ok installed` | dpkg db read | empty (WSL image has no ufw; stock server has it) → FAIL |
| 12 | 5.1.1 - Ensure permissions on /etc/ssh/sshd_config are configured | loop over `sshd_config` and `sshd_config.d/*.conf`: `stat -Lc '%04a %U %G'`, prints `<file> <mode> <owner> <group>` unless `0[0246]00 root root` | `empty` | stat only | empty (no openssh-server) → PASS (not applicable). Fixture 0644 owned by bstester: `/tmp/fx/ssh/sshd_config 0644 bstester bstester` |
| 13 | 5.1.20 - Ensure sshd PermitRootLogin is disabled | `not-installed` if no `/etc/ssh/sshd_config`; otherwise per file (`.d/*.conf` first, then `sshd_config`) an awk that stops at `Match` and prints the first `PermitRootLogin` value (case-insensitive key, `=` or space separator, leading blanks); a second awk takes the first line or the default `prohibit-password` | `regex` / `^(no\|not-installed)$` | reads config as data; `sshd -T` is not used (needs root, SR §2.4) | `not-installed` → PASS. Fixtures: unset → `prohibit-password`; `.d` `  permitrootlogin=No` before a later `yes` → `no`; a value only inside a `Match` block is skipped |
| 14 | 5.4.1.1 - Ensure password expiration is configured | `awk '$1 == "PASS_MAX_DAYS" { v = $2 } END { print v }' /etc/login.defs` | `le` / `365` | reads a file | `99999` → FAIL (stock default) |
| 15 | 5.4.2.1 - Ensure root is the only UID 0 account | `awk -F: '$3 == 0 { print $1 }' /etc/passwd` | `equals` / `root` | reads a file | `root` → PASS |
| 16 | 7.2.2 - Ensure /etc/shadow password fields are not empty | `cat /etc/shadow 2>/dev/null \| awk -F: '$2 == "" { print $1 } END { if (NR == 0) print "unreadable" }'` | `empty` | reads a file; prints user names only, never a hash field. `cat \|` is deliberate: mawk aborts without running `END` when it cannot open its file, so a direct `awk … /etc/shadow` would print nothing (a false PASS) when the file is unreadable | `unreadable` → FAIL (uid 1000 lacks the runner's `CAP_DAC_READ_SEARCH`, as expected). Fixture with an empty field for `bob` and a `$6$` hash for root: `bob` |

Operators used: `equals`, `regex`, `eq`, `ge`, `le`, `empty`. Every regex plugin prints exactly one line (`findmnt -f`, single `echo`/`awk` output), so SR §2.4's multiline matching cannot let a second line through.

Redaction (TS §6.5 defaults): no compared value can contain a crypt hash, a PEM block, a `bs?_` token, an AWS key id or `password|secret|api_key|token` followed by `=`/`:`. Row 16 never prints the hash field.

## How it was checked

1. A validator in my temp folder (not in the tree), run with the venv's `defusedxml` and `re2`, checked every SR §4.1 rule: BIT001 (strict UTF-8, ≤ 5 MB, no DTD or entity, parsed with `forbid_dtd/entities/external`), BIT002 (canonical names and order, no extra attributes, children or nesting), BIT003, BIT004 (lowercase 8-4-4-4-12), BIT005 (and no id shared with the 22.04 sample), BIT008, BIT010, BIT011, BIT012 (#13 grammar), BIT013 (RE2 compile), BIT014, BIT016, BIT017 (lengths, `@timeout` digits 1–600), BIT101 and BIT103 (each name starts with a control ref ≤ 32 chars followed by ` - `). It also checked the #111 note, distinct `PolicyName`s, CDATA on every `Execute`, the SR §1.1 block being byte-identical, and ran a rough BIT102 token scan (command words, `-exec`/`-i`, redirect targets, backticks, `<(`). Result: **no findings**. A planted copy (an `rm`, a `> /etc/x` redirect, one changed byte in plugin 1, a duplicated id) gave all four findings.
2. `dash -n` on every `Execute`: all 16 OK.
3. Ran each `Execute` read-only as shown above (non-root, runner environment, mawk). Fixture runs for rows 2, 7, 12, 13 and 16 used copies of the scripts with paths pointed at `/tmp/fx` (removed afterwards). Nothing ran as root; nothing outside `/tmp` was written.
4. RE2 check of every regex `ExpectedResult` against matching and non-matching strings (for example `nodevx`, `4644 root root`): all as intended.

## For the tester

- G59 (TP-M7-27) needs TASK-154. Import this file together with TASK-175's in one catalog. The SR §1.1 example goes in a separate catalog, because this sample shares its `PolicyName` and its first plugin id with it.
- My BIT102 scan is rough; the real check is the TASK-146 lexer. Constructs it must accept here: `$( )` at top level (rows 2, 9, 10, 12) holding double-quoted words, a single-quoted `stat` format, `2>/dev/null` and a pipe, and `"$( … )"` inside double quotes (row 9); `||` inside `$( )` (row 10); multi-line single-quoted awk programs (row 13); `case` with `\ ` escapes in a pattern (row 12); `NAME=value` assignment-only commands (`ld=yes`, `ins=no`, `bl=yes`); `[ … ] || continue`; `exit 0`.
- Sandbox notes for M10 (not testable now): rows 3 and 4 need `/proc/1/mountinfo` to be visible (fails if the runner unit hides other processes' `/proc`, e.g. `ProtectProc=invisible`); row 9 needs read-only D-Bus access to systemd; row 16 needs `CAP_DAC_READ_SEARCH` (it reports `unreadable` → FAIL otherwise, never a false PASS).
- Several checks FAIL on a stock host by design (rows 2, 3, 14; row 12 too on a stock host with openssh-server, whose `sshd_config` is 0644). A sample reports state; it does not have to pass.
