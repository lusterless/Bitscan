# TASK-174 REVIEW: sample policy CIS Ubuntu 24.04 Level 1 - Server

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-179; #111. Low risk; PD-35 second look by the user, because these commands run on every host.

Scope: `bits/samples/cis-ubuntu-24.04-l1-server.bit` (198 lines, 16 plugins) at worktree `00b8e4e`, per `work/reports/TASK-174-impl.md`.

**G59 is enough for the machine checks.**
- CHK-M7-300: both samples, imported together into a fresh catalog, give `success` with no Reject and no BIT102.
- CHK-M7-301: the SR §1.1 example alone imports.

I re-ran `test_samples_import_pg.py` (inside the 202 passed of TASK-154.md). The per-plugin script-rule check of REQ-179 (2) is mine, below.

Checked by me:
- **REQ-179 (3):** the first `<Plugin>` block is byte-identical to SR §1.1 (Python comparison of the two blocks: equal).
- **REQ-179 (4):** the #111 note is in `PolicyDescription`.
- **Ids:** 16 distinct, lowercase v4 ids, none shared with TASK-175.
- **Every `Execute` is in CDATA.**
- **The `PolicyName` is shared with the SR §1.1 example on purpose.** Both must not sit in one server folder, or the second gets BIT007. The implementer's report notes this.

## Per-plugin script rules (SR §2.4; bit-format.md "Authoring rules")
"Read-only" means:
- no write or redirect other than `2>/dev/null`;
- no SR §4.2 word, option or verb;
- no `xargs`, `find -exec`, `eval`, `.` or `sh -c`;
- only system binaries run, and every file is read as data;
- no `cd`.

| # | Plugin | Read-only | Prints only the value | Host view / no uid 0 / redaction | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | 1.3.1.1 AppArmor installed | yes (dpkg-query) | yes | n/a | ok (SR §1.1) |
| 2 | 1.1.1.1 cramfs not available | yes: grep `/proc/modules`, `find … -print`, grep modprobe.d files as data; no `modprobe` | composite state `loaded=… install=… blacklist=…` or `absent`, one line | n/a | ok |
| 3 | 1.1.2.1.2 /tmp nodev | yes | yes, one line (`-f`) | `findmnt --task 1` (host view) | ok |
| 4 | 1.1.2.2.3 /dev/shm nosuid | yes | yes | `findmnt --task 1` | ok |
| 5 | 1.5.1 ASLR | yes (`/proc`) | yes | n/a | ok |
| 6 | 1.5.2 ptrace_scope | yes | yes | n/a | ok |
| 7 | 1.5.4 prelink not installed | yes | names only | n/a | ok |
| 8 | 2.2.4 telnet not installed | yes | names only | n/a | ok |
| 9 | 2.4.1.1 cron enabled and active | yes (`systemctl is-enabled`/`is-active`, SR §4.2 allows them) | yes | needs read-only D-Bus (M10 note) | ok |
| 10 | 3.3.1 ip forwarding | yes | one line | n/a | ok |
| 11 | 4.1.1 ufw installed | yes | yes | n/a | ok |
| 12 | 5.1.1 sshd_config permissions | yes (`stat -L`) | offending files only | n/a | ok |
| 13 | 5.1.20 PermitRootLogin | yes (awk reads config as data; no `sshd -T`) | one value | config files instead of a uid-0 command | ok |
| 14 | 5.4.1.1 PASS_MAX_DAYS | yes | yes | n/a | ok |
| 15 | 5.4.2.1 only root has UID 0 | yes | names only | n/a | ok |
| 16 | 7.2.2 shadow fields not empty | yes | account names only, never a hash field | needs `CAP_DAC_READ_SEARCH`, otherwise prints `unreadable` (FAIL, never a false PASS) | ok |

## Findings
None blocking or should-fix.

1. nit, for the user's second look: plugin 16 reads `/etc/shadow`. Every import of this file will raise the `policy_imported` alert with the `shadow` flag (TS §8.4 L1290). That is expected, and the plugin prints account names only.
2. Control numbers are unconfirmed (#111). The owner confirms them before M11 uses the samples. This is recorded, not a finding.
