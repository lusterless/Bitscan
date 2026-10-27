# TASK-174 REVIEW: sample policy CIS Ubuntu 24.04 Level 1 - Server

Verdict: IN PROGRESS (no verdict; TEST not run)

Resume note (reviewer-m7, 2026-10-27, M7 paused by the user):
- **Waiting for:** the TEST (G59, TP-M7-27), which needs TASK-154. Reviewed together with TASK-175, with the user's second look (PD-35).
- **Pre-read done, no finding so far.** I checked `bits/samples/cis-ubuntu-24.04-l1-server.bit` with defusedxml and RE2:
  - UTF-8, LF, no BOM; `formatVersion="1.0"`; canonical element order;
  - 16 plugins, each `Execute` in CDATA;
  - plugin 1 is the SR §1.1 `<Plugin>` block byte-identical (id `3f6c2a9e-…`);
  - all ids are lowercase 8-4-4-4-12 and distinct from TASK-175's;
  - every name has a control reference of at most 32 characters;
  - every regex `ExpectedResult` compiles with RE2, and empty expected results appear only with `empty`;
  - `PolicyDescription` ends with the #111 note;
  - nothing outside `work/` references the samples.
- **Script rules (SR §2.4), read per plugin:**
  - every command is read-only: `dpkg-query`, `grep`, `find … -print`, `findmnt --task 1`, `cat /proc/...`, `stat`, `awk`, `printf`, `systemctl is-enabled`/`is-active`;
  - no SR §4.2 word, verb or option, no redirect other than `2>/dev/null`, no `xargs` or `find -exec`;
  - mount checks read the host view;
  - the `/etc/shadow` check prints user names only and relies on the runner's `CAP_DAC_READ_SEARCH` (`deploy/systemd/bitscan-runner.service`), reporting `unreadable` otherwise;
  - no compared output matches a TS §8.6 default redaction pattern.
- **To do on resume:**
  - confirm G59 (both samples together, `success`, no Reject, no BIT102 under the real TASK-146 lexer, including the constructs the impl report lists);
  - write one row per plugin (REQ-179 (2));
  - give the verdict;
  - note for the user: the control numbers are unconfirmed (#111), and the `shadow` flag will appear on the import alert for plugin 16.
