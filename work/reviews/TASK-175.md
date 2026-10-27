# TASK-175 REVIEW: sample policy CIS Ubuntu 22.04 Level 1 - Server

Verdict: IN PROGRESS (no verdict; TEST not run)

Resume note (reviewer-m7, 2026-10-27, M7 paused by the user):
- **Waiting for:** the TEST (G59, TP-M7-27), which needs TASK-154. Reviewed together with TASK-174, with the user's second look (PD-35).
- **Pre-read done, no finding so far.** I checked `bits/samples/cis-ubuntu-22.04-l1-server.bit` with defusedxml and RE2:
  - UTF-8, LF, no BOM; canonical order; 16 plugins, each in CDATA;
  - its own `PolicyName` and `FamilyName`;
  - all ids lowercase and distinct from TASK-174's and SR §1.1's (32 distinct across both files);
  - control references of at most 32 characters; regexes compile with RE2;
  - empty expected results appear only with `empty`;
  - the #111 note is present.
- **Script rules:** as TASK-174. The scripts it shares with TASK-174 are the same text. The new rows (AppArmor `for` loop, `tcp_syncookies`, `sshd_config` `stat`, `MaxAuthTries` awk, `/etc/passwd` `stat`) are read-only, with no SR §4.2 word or redirect.
- **To do on resume:** confirm G59, write one row per plugin (REQ-179 (2)), and give the verdict.
