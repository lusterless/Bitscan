# TASK-106 REVIEW: `bitscan-agent` main

Verdict: APPROVED, no open blocking or should-fix findings (and no nits).

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2). The user pre-authorised their second approval on a clean TEST PASS plus this verdict.**

Scope reviewed: `agent/cmd/bitscan-agent/main.go`, which replaces the M0 stub and is the only file (`work/reports/TASK-106-impl.md`). Sources: TS §3.1–§3.4, §3.2 step 8, REQ-096, REQ-103, #81 (a) and (c), the TASK-106 start-up rulings of 2026-10-24, and the decisions on the TASK-102 version injection.

TEST: PASS (`work/reports/TASK-106-test.md`).
- The real binary ran against the fake manager in a private mount namespace: 102/102 checks.
- Those checks covered:
  - enrol, heartbeat, rotate, pull and upload;
  - SIGTERM during each held call;
  - 7 start-up refusals;
  - staying idle after a refused enrolment and after a 401;
  - no listening socket and no writes outside the state directory;
  - a canary sweep.
- 10/10 plants are red, including CHK-M4-339 and -346.
- CHK-M4-264 (the verbatim unit, from the installed `.deb`) runs at the M4 gate.

## Checks
1. **Start-up rulings (2026-10-24).**
   - (1) A binary built without `-X main.version` refuses with one fixed line and exit 1.
   - (2) Every local refusal exits 1 with one line and makes no manager call. The refusals are config, machine-id, TLS and pin, client, state directory, a corrupt `seen_jobs.json` (fail closed) and no credentials.
   - (3) A refused enrolment (401, or any other answer that is not retried) logs one line and stays idle until a signal, so `Restart=always` never resends it (#81 (a)).
   - (4) SIGTERM and SIGINT exit 0, with at most 5 s for work in flight.
2. **Wiring.**
   - `enrol.Start` follows #81 (c).
   - One `loops.Run` drives the heartbeat, the pull with #74's `Unavailable` as default, and the dpkg watcher. `RealClock` and `CryptoSource` are used in production.
   - The manager's interval values replace the `agent.yaml` values from the first heartbeat on.
   - A 401 on any loop stops the loops, and the process stays up idle.
3. **Invariants.**
   - No listening socket, and no exec in `main`.
   - No write outside the state directory (TASK-088's atomic writes, so no partial file on exit).
   - No test-only flag or environment input.
   - Inventory cannot be turned off: the watcher and job uploads always start.
4. **Logs.**
   - Fixed messages, with `version` and `agent_id` at start.
   - Start-up and enrolment reasons are the fixed package error texts. One case carries manager text: a refused enrolment answer can include a JSON field name from Go's strict decoder. slog quotes that value, and it holds no secret. That text is TASK-098's (approved), and it is not a defect of this task.
   - No token, header, body or package list. The canary sweep confirms this.
5. **Re-run by the reviewer (Windows).**
   - `gofmt -l cmd` prints nothing.
   - `GOOS=linux go vet ./cmd/bitscan-agent/` is clean.
   - `GOOS=linux golangci-lint run ./cmd/bitscan-agent/...` reports 0 issues.
6. **Scope.** 1 file, 106 code lines.

## Findings
None.
