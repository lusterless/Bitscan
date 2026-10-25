# TASK-103 REVIEW: job pull, job checks and dispatch

Verdict: APPROVED, no open blocking or should-fix findings (and no nits).

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2). The user pre-authorised their second approval on a clean TEST PASS plus this verdict.**

Scope reviewed: `agent/internal/agent/loops/pull.go` and `agent/internal/agent/loops/jobs.go`, both new (`work/reports/TASK-103-impl.md`). Sources:
- TS §3.3 L203, L208–L216, L222–L226 and §6.5;
- REQ-098, REQ-104;
- #74 (with #28), #78 (b), (c), (e);
- the W1 rulings of 2026-10-24 (an upper-case `agent_id` is ours; batches of at most 50 with only the last `final: true`; 403 `pending_approval` uses the back-off).

TEST: PASS (`work/reports/TASK-103-test.md`).
- loops 84/84, and 84/84 under `-race`.
- 32/32 plants red, including CHK-M4-330..334 and -356.
- Test-side changes only:
  - the exec canary moved into `t.TempDir()`;
  - the stop waits are bounded;
  - two new checks: a 409 on results stays exactly one post after the back-off window, and `TestFirstPullWaitsForFirstHeartbeat`.

## Checks
1. **Pull timing (TS §3.3 L203).**
   - The first pull waits for the first heartbeat attempt.
   - After that it pulls every `job_pull_seconds` ± 30 s (clamped).
   - A heartbeat that changes the interval restarts the wait from now.
   - Wait, 429, 5xx and network errors use the back-off, which resets on Success or Drop.
   - An empty list does nothing until the next timer (L216).
   - Any 401 stops the loop, and `Loop` returns only after both workers return.
2. **Job checks (TS §3.3 L212).**
   - Own `agent_id`, compared case-insensitively.
   - `pickup_by` strictly after now, and at most now + 25 h.
   - Not seen in the last 7 days, using the persisted `state.Seen`.
   - The id is persisted **before** the job is queued, and refused ids are persisted too, so neither a crash nor a replay can run a job twice. A failed `Add` runs nothing (fail closed).
   - Each worker re-checks `pickup_by` when the job starts ("start before `pickup_by`; may finish after").
   - The answer is decoded strictly, at most 10 jobs (L214).
3. **Dispatch (L222).**
   - Inventory jobs run at once in their own worker, alongside compliance.
   - Compliance jobs run one at a time, in pull order, with `current_job_id` set (#78 (c)).
   - Queues of 10 apply back-pressure to the pull, so no job is dropped.
4. **#74.**
   - Nothing is executed, `runner.sock` is never opened, and `Execute` is never read or kept.
   - Each plugin gets one `runner_unavailable` item, in batches of at most 50, with only the last `final: true`. A job with no plugins gets one empty final batch. The batch loop is correct at 0, 50, 51 and 5,000 items.
   - Wait and Retry are retried with the back-off and the same bytes.
5. **The impl report's questions, answered (not findings).**
   - (a) A refused job counts as `last_error`. #78 (e) covers "a local failure as a fixed reason word", and a refused job is the agent's own refusal, reported with a fixed reason. I accept it.
   - (b) A dropped batch ends the job's remaining batches. TS §3.3 L224 says the manager "will never accept that batch". In 0.x the batches share one job state, and the M3 manager answers 409 for the job as a whole, so the remaining batches would be refused alike. Ending the job avoids a loop of certain drops, and `last_error` still reports it. I accept it for 0.x. M10's real runner revisits batching.
6. **Pull-only invariants.** No push channel, no listening socket and no command execution. Jobs come only from the agent's own authenticated pull. The heartbeat answer cannot start a job (`Puller` reads only `PullChanged`).
7. **Logs.** Fixed text, plus `agent_id`, `job_id` and a fixed reason. No body, command, token or manager text (checklist 11). Every wait selects on the Run context (checklist 10).
8. **Re-run by the reviewer (Windows).**
   - `gofmt -l internal/agent/loops` prints nothing.
   - `GOOS=linux go vet` is clean.
   - `GOOS=linux golangci-lint run ./internal/agent/loops/...` reports 0 issues.
9. **Scope.** 2 files, about 205 code lines.

## Findings
None.
