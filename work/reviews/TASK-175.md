# TASK-175 REVIEW: sample policy CIS Ubuntu 22.04 Level 1 - Server

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-179; #111. Low risk; PD-35 second look by the user.

Scope: `bits/samples/cis-ubuntu-22.04-l1-server.bit` (16 plugins) at worktree `00b8e4e`, per `work/reports/TASK-175-impl.md`.

**G59 machine checks pass:** CHK-M7-300, importing both samples together, gives `success` with no Reject and no BIT102. That also shows the names and ids are distinct.

Checked by me:
- `PolicyName` is `CIS Ubuntu 22.04 Level 1 - Server` and `FamilyName` is `CIS Ubuntu 22.04`, both different from TASK-174.
- The 16 ids are distinct, with none shared with TASK-174.
- The #111 note is present (REQ-179 (4)), and every `Execute` is in CDATA.

## Per-plugin script rules (SR §2.4)
"Read-only" means the same as in TASK-174.md.

| # | Plugin | Read-only | Prints only the value | Host view / no uid 0 / redaction | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | 1.1.1.1 cramfs | yes (same script as TASK-174 #2) | composite state | n/a | ok |
| 2 | 1.1.2.2 /tmp nodev | yes | one line | `findmnt --task 1` | ok |
| 3 | 1.5.1 ASLR | yes | yes | n/a | ok |
| 4 | 1.5.2 prelink not installed | yes | names only | n/a | ok |
| 5 | 1.6.1.1 AppArmor installed | yes (dpkg-query per package) | missing package names only; an unknown package is listed, so it cannot falsely pass | n/a | ok |
| 6 | 2.3.4 telnet not installed | yes | names only | n/a | ok |
| 7 | 3.2.2 IP forwarding | yes | one line | n/a | ok |
| 8 | 3.3.8 SYN cookies | yes | yes | n/a | ok |
| 9 | 3.5.1.1 ufw installed | yes | yes | n/a | ok |
| 10 | 5.1.1 cron enabled and running | yes (`is-enabled`/`is-active`) | yes | needs read-only D-Bus (M10) | ok |
| 11 | 5.2.1 sshd_config permissions | yes (`stat -L`) | offending file only | n/a | ok |
| 12 | 5.2.7 PermitRootLogin | yes (awk on config) | one value | no `sshd -T` | ok |
| 13 | 5.2.18 MaxAuthTries ≤ 4 | yes (awk on config, default 6) | one value | no `sshd -T` | ok |
| 14 | 5.5.1.2 PASS_MAX_DAYS | yes | yes | n/a | ok |
| 15 | 6.1.1 /etc/passwd permissions | yes (`stat -L`) | mode owner group | n/a | ok |
| 16 | 6.2.2 shadow fields not empty | yes | account names only | `CAP_DAC_READ_SEARCH` or `unreadable` (FAIL) | ok |

## Findings
None blocking or should-fix.

1. nit, for the user's second look: plugin 16 reads `/etc/shadow`, so every import raises the `policy_imported` alert with the `shadow` flag, as in TASK-174.
2. Control numbers are unconfirmed (#111), as in TASK-174.
