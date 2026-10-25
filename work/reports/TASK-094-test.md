# TASK-094 TEST: os_info collector and the fixed command runner

**Verdict: PASS** (round 2, after round 1). Round 1 failed CHK-M4-097: a killed command's background child kept running. Round 1 (Setpgid plus a group kill on cancel and after Wait) passes 12/12 on the re-run, and 4/4 in each 22.04 container.

REQ-100; TS §3.4 L232–L240; #35, #77; lead rulings 2026-10-24 (Q1, G204). Tester: tester-m4b. Full rigor (agent). Test file: `agent/internal/inventory/osinfo_test.go` (new).

## Commands
- W: `go test -count=1 -v -run 'OSInfo|ReadOSRelease|Command|NoOtherProcess|Collection' ./internal/inventory/` and the whole package: 112/113, 1 named skip; `-race` 66/66 (TP-M4-09/10).
- W-c ubuntu:22.04 plain and systemd: 15/15 each.
- Plants P01–P15: 15/15 red. golangci-lint (both GOOS, whole module): 0 issues.

## Acceptance criteria
- Every os_info field equals an independent source on Ubuntu 24.04 and 22.04 and validates: PASS (CHK-M4-095, -096).
- Only the #35 commands, no shell, the minimal environment, /dev/null stdio: PASS (CHK-M4-100; CHK-M4-344 and -345 red).
- A hanging command is killed, with its children: FAIL in round 1, PASS in round 2 (CHK-M4-097, -097-r1).
- Missing or failing sources and over-contract values give null or [] with fixed reasons, and the body stays valid: PASS (CHK-M4-098, -099).
- Output caps: PASS (CHK-M4-102). No input from a job: PASS for the signatures (CHK-M4-101); the job path is with TASK-104.
- Debian 12: NOT RUN (dropped from v1 by the user).

## Round-1 failure (fixed)
`TestCommandHangIsKilled/with_a_child_holding_stdout` and `/child_with_stdout_closed`.
- Expected: no process of the command left after the kill.
- Actual: the grandchild kept running, because exec.CommandContext's kill reaches only the direct child.
- Fix: process group plus a group SIGKILL (impl-agent-2, `command_linux.go`).
