# TASK-100 TEST: maintainer scripts (postinst, postrm), revisions 0 and 1

**Verdict: PASS (rounds 0, 1, 2)** on Ubuntu 24.04 and 22.04 (round 0/1: 529/529 each; round 2: see below). Debian 12: NOT RUN (dropped by the user).

REQ-108, REQ-107; TS §3.1 L158–L175; #81, #82; install.env rules (A)–(E) and revision 1 (key tracking, /etc/bitscan owner and mode). Tester: tester-m4b. Full rigor. Test file: `deploy/tests/test_maintainer_scripts.sh` (new; the interface agreed with impl-deploy for package.yml: `--deb PATH [SUBCOMMAND...]`, root, systemd PID 1, `BITSCAN_TEST_DISPOSABLE=1`, exit 0/1/2).

## Commands
`BITSCAN_TEST_DISPOSABLE=1 bash deploy/tests/test_maintainer_scripts.sh --deb bitscan-agent_0.1.0~pre1-1_amd64.deb all` in systemd containers: u24 529/529, u22 529/529. shellcheck 0.9.0 separately (CHK-M4-176).

## Acceptance criteria
- Install, reinstall, upgrade and purge each twice without error: PASS (CHK-M4-171, -172, -173).
- Modes and owners exactly REQ-108 (1): PASS (CHK-M4-165).
- A missing URL or token fails with one clear line and leaves the package unconfigured: PASS (CHK-M4-168).
- The debconf token is empty afterwards: PASS (CHK-M4-166).
- Purge leaves a planted manager.env: PASS (CHK-M4-173).
- Also PASS: install.env rules A–E and r1 (CHK-M4-169), environment variables ignored (-170), unit states (-167), #81 re-enrolment and planted symlinks (-174), input validation (-175), /etc/bitscan r1 (-175-r1), static checks (-176), no token leak (-177).

## Open items for main (not counted against the task)
- D2: a string-typed preseed leaves the token in config.dat-old (0644) until the next debconf save. Runbook warning suggested.
- Plants for the G38 mutation rows (CHK-M4-357 to -361 on the scripts) are not yet run (drain). The resume note lists them.

## Round 2 (review round 1 findings 1, 2; postinst r2 nits 3, 4), 2026-10-25
Verdict: PASS. Final postinst sha256 4acaab92…f279; .deb a419b8fb…61ef built with build-deb.sh in m4b-build-u24.
- Finding 1 (G38 plants): CHK-M4-357 to -361 and the set -e plants are all red. 361c (only --no-start dropped) is runtime-equivalent and is caught statically by CHK-M4-072. Rows in tests/m4/report.md.
- Finding 2 (setpriv property): new writer trace in test_maintainer_scripts.sh (install, reenrol, symlink), proven by the two root-write plants (CHK-M4-174-writer).
- r2 product change: fd 3 is closed for the bitscan children and `mv -fT` refuses a planted directory (CHK-M4-174-r2). The pre-r2 .deb is the plant and is red on exactly those 4 checks.
- Test strengthened: the capread units must never have been started (CHK-M4-167-r2).
- Runs: final `all` 542/544 on u24 and u22 (2 test-bug failures, fixed), then symlink 19/19 and install 43/43 on each. shellcheck clean apart from SC1091.
- Test bugs found and fixed (mine): the order of the directory case in sub_symlink; the 358 plant's verification grep; the 361c run corrupted by editing the plant script while it ran (re-run clean).
