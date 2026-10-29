# TASK-174 REVIEW: sample policy CIS Ubuntu 24.04 Level 1 - Server

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-179. Low risk (data). The PD-35 second look is the user's and is still to come.

Scope reviewed: `bits/samples/cis-ubuntu-24.04-l1-server.bit` (198 lines), one file.

TEST: PASS (`work/reports/TASK-174-test.md`, tester-m7, G59 run g0).
- 50/50 passed, including both samples in one fresh catalog: `success`, no Reject finding, no BIT102.
- The SR §1.1 example passes alone.
- The first plugin is byte-identical to the SR §1.1 code block, and the #111 note is present.
- 5 data plants are red: `rm x`, a shared id, `findmnt` without `--task 1`, `nft`, and the note removed.
- g0 ran on the current tree, including the TASK-146 r2 BIT102 files. Because those files are untested, a targeted G59 re-run follows the 146 r2 approval. **If that re-run fails, this verdict reopens.**

Spec read: SR §1.1, §2.1–§2.4 (script rules L155–L162), §4.2; TS §3.3 L249, §3.7 L500–L505, TS L365 (no `PrivateNetwork=`), §8.5, §8.6; #111; `deploy/systemd/bitscan-runner.service`; `deploy/dbus/bitscan-runner.conf`.

## File checks
- UTF-8, LF, no BOM. `formatVersion="1.0"`, canonical element order, status `enabled`.
- 16 plugins, each `Execute` in CDATA with a timeout of 30 or 60.
- Every id is lowercase 8-4-4-4-12 and disjoint from TASK-175's.
- Every name has a control reference of at most 32 characters.
- Every regex compiles with RE2, and `empty` is the only operator used with an empty `ExpectedResult`.
- `PolicyDescription` ends with the #111 note.

## Per-plugin script-rule rows (SR §2.4 L155–L162, §4.2)
Each row is checked against these rules: read-only (no writes, no service or package changes); no prompt; prints only the observed value; host view where it matters; no uid-0 command; nothing executed from a user-writable path; the compared value isn't something redaction would hide.

| # | Plugin | What it reads | Result |
| --- | --- | --- | --- |
| 1 | 1.3.1.1 AppArmor installed | `dpkg-query` status (SR §1.1 block) | PASS |
| 2 | 1.1.1.1 cramfs not available | `/proc/modules`; `find /lib/modules/<ver> … -print \| head`; modprobe.d files with `grep` (data only) | PASS |
| 3 | 1.1.2.1.2 `/tmp` nodev | `findmnt --task 1` (host view) | PASS |
| 4 | 1.1.2.2.3 `/dev/shm` nosuid | `findmnt --task 1` (host view) | PASS |
| 5 | 1.5.1 ASLR | `/proc/sys/kernel/randomize_va_space` (global; reads are allowed under `ProtectKernelTunables`) | PASS |
| 6 | 1.5.2 ptrace_scope | `/proc/sys/kernel/yama/ptrace_scope` | PASS |
| 7 | 1.5.4 prelink absent | `dpkg-query` and `awk`; nothing is printed when the package is unknown | PASS |
| 8 | 2.2.4 telnet absent | as row 7, two packages | PASS |
| 9 | 2.4.1.1 cron enabled and active | `systemctl is-enabled` and `is-active`, the read-only verbs SR §4.2 allows (the D-Bus policy allows `GetUnitFileState`, `GetUnit`/`LoadUnit` and `Properties.Get`) | PASS |
| 10 | 3.3.1 IP forwarding | `/proc/sys/net/...`; the runner has no `PrivateNetwork=` (TS L365), so these are the host's values | PASS |
| 11 | 4.1.1 ufw installed | `dpkg-query` status | PASS |
| 12 | 5.1.1 sshd_config permissions | `stat -Lc`; the `case` pattern `0[0246]00 root root` is exactly 0600 or stricter | PASS |
| 13 | 5.1.20 PermitRootLogin | reads `sshd_config.d/*.conf` and then `sshd_config` with `awk`, first value wins, `Match` stops; no `sshd -T` (it needs root) | PASS |
| 14 | 5.4.1.1 PASS_MAX_DAYS | `awk` on `/etc/login.defs` | PASS (nit 1) |
| 15 | 5.4.2.1 only root has UID 0 | `awk` on `/etc/passwd` | PASS |
| 16 | 7.2.2 shadow fields not empty | `/etc/shadow` through `CAP_DAC_READ_SEARCH` (TS L500); prints only user names or `unreadable`, never a hash | PASS |

The only redirect anywhere is `2>/dev/null`. No SR §4.2 command word, verb or option appears, and there is no `xargs`, `find -exec`, `eval`, `source`, `cd` or wrapper. Top-level `$( )` is fine: the SR §4.2 substitution rule applies only to nested `sh -c` scripts.

## Findings
None blocking or should-fix.

1. nit, line 172 (plugin 14): if `/etc/login.defs` has no `PASS_MAX_DAYS`, the output is empty. `le` then gives ERROR instead of FAIL. Printing the effective default (`END { print (v == "" ? 99999 : v) }`) would report FAIL with the real value.
2. For the user (PD-35 second look, not a finding):
   - The CIS control numbers are unconfirmed (#111; the description says so).
   - Every import of this file raises the `policy_imported` alert with the `shadow` flag on plugin 16 (#100 (c)), as designed.
