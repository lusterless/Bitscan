# TASK-104 TEST: inventory jobs and watcher uploads
**Verdict: PASS** on Linux (WSL Ubuntu 24.04, Go 1.27.2, -race). REQ-101, REQ-102, REQ-100 (5); TS §3.4 L239–L244, §3.3 L224–L226, §6.5 L1186; #72, #80; ruling Q2. Tester: tester-m4b. Full rigor (agent).

Commands: `go test -race -count=1 -run TestInventory ./internal/agent/loops/` (44/44), the whole package (83/83), -count=10 (440/440), strace exec counter for CHK-M4-101, 9 mutation plants (all red), golangci-lint 0 issues.

Acceptance criteria (tasks.md):
- A job upload carries ?job_id= and gzip: PASS (CHK-M4-235).
- A 503 is retried, then succeeds: PASS (CHK-M4-236).
- A 422 becomes last_error with no retry: PASS (CHK-M4-237).
- Watcher signals give unscheduled uploads never closer than 10 min 30 s: PASS (CHK-M4-238).
- A 429 is retried with back-off: PASS (CHK-M4-236, -238).
- Also: the 30-minute job window (CHK-M4-239), watcher failure (-240), 401 (-241), the job path takes no job input (CHK-M4-101), collection failure (Q2).
- REQ-101 (5) against the real manager is G41 (TP-M4-23), not part of this task.
