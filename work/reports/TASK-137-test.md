# TASK-137 TEST: README for the first release (TP-M6-09)

Verdict: **PASS**. Tester: tester-m6b. REQ-145. Walked against the TASK-133 r1 host (m6b-host), the agent host from the TASK-134 upgrade walk (the real 0.1.0-1 `.deb`), and the r1 release folder from the local release run.

Written by `main` from the tester's text (the harness blocks the tester on report files).

Commands and totals:
- `python3 -I deploy/tests/check_md_links.py README.md deploy/runbooks/manager-install.md deploy/runbooks/manager-operations.md`: **OK, 17 relative links**, 0 findings. That covers every anchor (`#installing-a-release`, `#web-ui`) and the cited section numbers (install §3/§4/§5, operations §1/§2, agent §6). A broken-anchor plant is red (CHK-M6-150).
- `bash e2e/m6/readme_walk.sh m6b-host m6b-agent /root/m6tb/tree /root/m6tb/relout`: **11/11 passed**, 0 failed, 1 NOT RUN. The first run had a script quoting bug (all rows), which was fixed; this is the re-run (CHK-M6-151).
- `check_runbook_text.py README.md`: OK, 0 findings (CHK-M6-153).
- CHK-M6-152: a read-through against the runbooks and TS. No contradiction found:
  - versions 0.1.0 / 0.1.0-1 / v0.1.0 match the workflow and the packages;
  - the file list matches plan §3;
  - compatibility N/N−1 both ways matches TS L1267 and L1348, and agent-install §6;
  - the upgrade order matches operations §1;
  - manager host 24.04 matches install §1;
  - the certificate bullet matches the #96 fact;
  - "no signed APT repository" matches TS §1.2.
  The removed lines ("A production install method is not provided yet", "The agent package and compliance scans do not run yet") are gone.

Acceptance criteria:
- (1) every changed section walked, links resolve: PASS. The `runner_unavailable` statement is NOT RUN: 0.1.0 has no policy or scan that could make a compliance job.
- (2) no contradiction: PASS.
- (3) no secret, task id or process note: PASS.
