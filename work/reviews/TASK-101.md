# TASK-101 REVIEW: run state and heartbeat loop

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/loops/run.go` and `agent/internal/agent/loops/heartbeat.go` (`work/reports/TASK-101-impl.md`, including revision 1). Sources:
- TS §3.2 step 8, §3.3 L202, L206, L211 and L224–L226, §6.5 L1163, §3.7 L484;
- REQ-095, REQ-096 (3), REQ-097, REQ-103;
- #30, #78, #81;
- the W1 rulings of 2026-10-24 (any file at `capread.sock` counts; 403 `pending_approval` uses the back-off).

TEST: PASS (`work/reports/TASK-101-test.md`).
- Round 1 was FAIL. A 401 `enrollment_rejected` on a heartbeat (REQ-096 (3)), and a rotation 401 (TS §3.2 step 8), logged the generic re-enrol line instead of "with a new enrolment token".
- After r1 the two tests pass 8/8, the control passes 21/21, and 7/7 Stop plants are red.
- The loops package passes 83/83 under `-race`. Round 1 had 25/25 plants red.

## Checks
1. Spec:
   - One heartbeat at start, then 300 s ± 30 s after each Success or Drop.
   - Wait, 429, 5xx and network errors use the 10 s to 300 s back-off, which resets after a Success or Drop.
   - The heartbeat answer only sets `job_pull_seconds` and `max_parallel_plugins`, clamped to 60–3,600 and 1–8. It triggers no other call except rotation, and rotation calls only when its window is open (TS §3.3 L211).
2. #78 body:
   - `uptime_s` is the agent process's uptime on the injected clock.
   - `last_pull_at` is the last pull answered 200.
   - `current_job_id` is the compliance job only.
   - `spool_bytes` is 0.
   - `last_error` is fixed text `"<route> <status> <type>"`, with the manager's type reduced to visible ASCII and cut to 1,024 characters. It is swapped out when sent and put back when the heartbeat is not answered, unless a newer error replaced it.
   - `runner_helpers` is `["capread"]` when `Lstat` finds any file at the socket path (#30). The agent never connects to it.
   - The body goes through the contract self-check before sending.
3. Stop:
   - `Call` returns at once after a stop.
   - Any 401 on any loop cancels the shared context, so every loop ends within one `Sleep` (REQ-095 (3)).
   - The re-enrol line is logged once (`sync.Once`), and the process stays up idle (#81 (a)).
   - r1: `token_revoked`, `token_expired` and `enrollment_rejected`, and `token.ErrStop` from rotation, give the "new enrolment token" line. Every other type gives the generic line.
4. Concurrency: atomics for the shared fields; a mutex-wrapped random source; a one-slot `pullChanged` that never blocks the sender. `Tokens.Current()` is read on every call, so a rotated token is used at once.
5. Security:
   - Logs carry fixed text plus `agent_id`. No token, body or manager text, apart from the sanitised type inside `last_error` (checklist 11).
   - No listening socket, and no command is run.
6. Re-run by the reviewer (Windows):
   - `GOOS=linux go vet ./internal/agent/loops/` is clean.
   - `GOOS=linux golangci-lint run ./internal/agent/loops/...` reports 0 issues (run with TASK-104).
7. Scope: 2 files, 243 code lines, over the 190 estimate. The excess is accessors that TASK-103, 104 and 106 use, and the lead accepted the size (decisions 2026-10-24).

## Findings
1. Answer to the impl report's question: a Drop answer to a rotate does not become `last_error`, because the rotator calls the client directly. #78 (e) says "the latest drop answer". After the TASK-099 r1 ruling, a rotate Drop waits 24 h and the old token stays valid, so nothing is lost. The operator just sees no `last_error` for it. nit, optional: have `Rotator` return the drop text so `heartbeat()` can set it. That would touch TASK-099's file, so it needs a ruling from main.
2. Answer to the impl report's question: a rotate 401 `machine_id_mismatch` also gets the "new enrolment token" line. The line is still correct, because re-enrolment always needs a fresh `enroll.token`. No need to thread the type through `token.ErrStop`.
3. nit, `heartbeat.go:48`. `uptime_s` is truncated to whole seconds and is never negative on a monotonic fake clock. A wall-clock jump backwards could make it negative with a real clock, but `Clock.Now()` in production is `time.Now()`, whose `Sub` uses the monotonic reading. No change.
