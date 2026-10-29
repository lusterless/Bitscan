# TASK-175 REVIEW: sample policy CIS Ubuntu 22.04 Level 1 - Server

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-179. Low risk (data). The PD-35 second look is the user's and is still to come.

Scope reviewed: `bits/samples/cis-ubuntu-22.04-l1-server.bit` (207 lines), one file.

TEST: PASS (`work/reports/TASK-175-test.md`, which shares run g0 with TASK-174).
- 50/50 passed. Imported together with the 24.04 sample: `success`, no Reject finding, no BIT102.
- Its `PolicyName` and all 16 ids are disjoint from TASK-174's.
- The shared-id plant is red (BIT015).
- A targeted G59 re-run follows the TASK-146 r2 approval. **If that re-run fails, this verdict reopens.**

Spec read: as TASK-174 (`work/reviews/TASK-174.md`).

## File checks
- UTF-8, LF, no BOM. `formatVersion="1.0"`, canonical order, status `enabled`.
- Its own `PolicyName` and `FamilyName` (`CIS Ubuntu 22.04`).
- 16 plugins, each in CDATA with a timeout of 30 or 60.
- Every id is lowercase and distinct from TASK-174's and SR §1.1's.
- Control references are at most 32 characters; the regexes compile with RE2; `empty` is the only operator used with an empty expected result.
- The #111 note is present.

## Per-plugin script-rule rows (the rules as in TASK-174)

| # | Plugin | What it reads | Result |
| --- | --- | --- | --- |
| 1 | 1.1.1.1 cramfs disabled | same script as TASK-174 row 2 | PASS |
| 2 | 1.1.2.2 `/tmp` nodev | `findmnt --task 1` (host view) | PASS |
| 3 | 1.5.1 ASLR | `/proc/sys/kernel/randomize_va_space` | PASS |
| 4 | 1.5.2 prelink absent | `dpkg-query` and `awk` | PASS |
| 5 | 1.6.1.1 AppArmor installed | `for` loop over `dpkg-query` status, prints packages not installed | PASS |
| 6 | 2.3.4 telnet absent | `dpkg-query` and `awk` | PASS |
| 7 | 3.2.2 IP forwarding | `/proc/sys/net/...`, host network namespace (TS L365) | PASS |
| 8 | 3.3.8 TCP SYN cookies | `/proc/sys/net/ipv4/tcp_syncookies`, host network namespace | PASS |
| 9 | 3.5.1.1 ufw installed | `dpkg-query` status | PASS |
| 10 | 5.1.1 cron enabled and running | `systemctl is-enabled` and `is-active` (allowed by the D-Bus policy) | PASS |
| 11 | 5.2.1 sshd_config permissions | `stat -Lc`; `0[0246]00 root root` | PASS |
| 12 | 5.2.7 PermitRootLogin | same `awk` reader as TASK-174 row 13 | PASS |
| 13 | 5.2.18 MaxAuthTries | same reader; the default is 6 when it isn't set; `^([1-4]\|not-installed)$` | PASS |
| 14 | 5.5.1.2 PASS_MAX_DAYS | `awk` on `/etc/login.defs` | PASS (nit 1) |
| 15 | 6.1.1 `/etc/passwd` permissions | `stat -Lc`; `^0[0246][04][04] root root$` is exactly 0644 or stricter | PASS |
| 16 | 6.2.2 shadow fields not empty | `/etc/shadow` through `CAP_DAC_READ_SEARCH`; prints only user names or `unreadable` | PASS |

The only redirect is `2>/dev/null`. No SR §4.2 command word, verb or option appears, and there is no `xargs`, `find -exec`, `eval`, `source`, `cd` or wrapper. Nothing runs that needs uid 0.

## Findings
None blocking or should-fix.

1. nit, line 181 (plugin 14): the same as TASK-174 nit 1. An absent `PASS_MAX_DAYS` gives ERROR instead of FAIL; printing the default 99999 would fix it.
2. For the user (PD-35): the control numbers are unconfirmed (#111), and the import alert flags `shadow` for plugin 16.
