# TASK-103 IMPL: job pull, job checks and dispatch

REQ-098, REQ-104. TS §3.3 (L203, L211–L216, L222–L226), §6.5 Job pull and Results; #74 (and #28's suggested answer), #78 (b) and (c); W1 lead rulings 2026-10-24 (a job whose `agent_id` is ours in upper case is ours; #74 batches of at most 50 for more than 50 plugins, only the last `final: true`; 403 `pending_approval` uses the back-off). Plan `work/plans/TASK-101.md`, "Pull and job checks". **Two approvals (TS §8.2, agent).** Built on TASK-101's `run.go` interfaces (impl-agent-2), which are unchanged.

No tests were run (that is the tester's job).

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/agent/loops/pull.go` (about 130 non-comment lines) | `Seen` interface (`*state.Seen`), `Puller{Run, Seen, Inventory, Compliance}`, `(*Puller).Loop()`, plus the internal `sleep`, `pull`, `accept` and `refuse`. |
| `agent/internal/agent/loops/jobs.go` (about 75) | The per-kind workers, the compliance wrapper (`SetCurrentJob`), and `Unavailable{Run}`, the 0.x `ComplianceHandler` (#74). |

Together that is about 205 code lines against the 190 estimate.

## Behaviour

- **Start and timer:**
  - `Loop` waits for `Run.FirstHeartbeat()`, then pulls at once.
  - After a Success or a Drop it sleeps `Run.PullInterval()` (`job_pull_seconds` ± 30 s, clamped). A `PullChanged()` signal during that sleep restarts the wait from now with the new interval.
  - After a Wait (403 `pending_approval`), a 429, a 5xx or a network error it sleeps `schedule.Backoff.Next()` (its own back-off on `Run.Rand()`, reset on Success or Drop). A pending `PullChanged` is then picked up by the next normal sleep.
  - A Stop (any 401; `Run.Call` stops every loop) or the end of the Run context ends `Loop`, which returns only once both workers have returned.
- **Empty list:** nothing happens until the next timer. There is no other call and no collection (TS §3.3 L216).
- **Answer:**
  - It is decoded strictly as `JobsResponse`, so 11 jobs, an extra key, plugins on an inventory job and similar faults are refused.
  - On 200, `SetLastPull(now)` runs before the decode, because #78 (b) is "answered 200".
  - A refused body runs no job, logs one fixed line and sets `last_error` to `jobs answer refused`.
- **Checks, per job in pull order** (TS §3.3 L212):
  1. `agent_id` equals ours, ignoring case. Otherwise: "addressed to another agent".
  2. `pickup_by` is after now. Otherwise: "pickup_by has passed" (now itself is refused).
  3. `pickup_by` is at most now + 25 h. Otherwise: "pickup_by is more than 25 h away" (now + 25 h exactly is accepted).
  4. `job_id` is not in `Seen` (7 days, persisted, `state.Seen`). Otherwise: "already seen".

  A job that passes checks 1–3 is passed to `Seen.Add` (which persists) **before** it is queued, and a job refused by checks 1–3 is recorded too, so a refused id is never tried again. If `Add` fails, the job is not run: one error line, `last_error` = `seen job ids not saved`. Every refusal logs one warning with `job_id` and the fixed reason, and sets `last_error` = `job refused: <reason>`. **Reviewer:** #78 (e) says "local failure" without listing these; I counted a refused job as one.
- **Dispatch:**
  - Inventory jobs go to their own worker and run at once, alongside compliance jobs: `Inventory.RunJob(ctx, job_id)`, one inventory job at a time.
  - Compliance jobs go to a second worker, one at a time, in pull order, wrapped in `SetCurrentJob(&id)` / `SetCurrentJob(nil)` (#78 (c)).
  - Each worker checks `pickup_by` again when the job starts ("Start a job before `pickup_by`; it may finish after it"). A job that waited past it is refused with "pickup_by passed before the job could start".
  - Each queue holds 10 jobs (one pull). When a queue is full, the pull loop waits for it to drain before the next pull.
- **#74 handler (`Unavailable`, the default when `Compliance` is nil):**
  - Nothing is executed, `runner.sock` is never opened, and `Execute` is never read, logged or kept.
  - Each plugin gets one item: `error: "runner_unavailable"`, `exit_code` null, empty `stdout` and `stderr`, `timed_out` and `truncated` false, and `started_at` = `finished_at` = the clock's now when the job is handled.
  - Items go in batches of at most 50, only the last `final: true`. A job with 0 plugins sends one `{"results": [], "final": true}`. There is no start-notice batch: #74 replaces the TS §3.3 empty start batch with one final batch. 50 such items are about 12 KB, so the 1.5 MB cap cannot be reached.
  - Each batch goes through `wire.Encode` and `Run.Call(OpResults, job_id)`. Wait, 429, 5xx and network errors are retried with the back-off, with the same bytes.
  - A Drop (for example the M3 manager's 409) is logged and becomes `last_error` in `Run.Call`, and the job's remaining batches are not sent, because they would be refused alike. **Reviewer:** the spec says "drop the batch"; confirm that ending the job is acceptable in 0.x.
  - A 200 answer is decoded strictly as `ResultsResponse`. A refused answer logs one warning, and the batch still counts as sent.
- **No secrets:** logs carry only fixed text, `agent_id` (from `Run`) and `job_id`. No body, command, token or manager text is logged or stored. The only files written are those of `Seen.Add` (`seen_jobs.json`).

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l internal cmd`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/agent/loops/`: clean.
- `golangci-lint run ./internal/agent/loops/...` with GOOS=linux and with GOOS=windows: `0 issues`.
- Builder checklist: 10 (every wait selects on the Run context or uses `schedule.Sleep` on it) and 11 (no tokens, bodies, commands or output in logs) hold. The rest are manager-side.

## For the tester (TP-M4-18, CHK-M4-215 to 224; mutation rows CHK-M4-330 to 334, 356)

- **Setup:** `loops.NewRun(ctx, Deps{...})` with a fake `Doer`, a fake `schedule.Clock` and a seeded `Source`. `Seen` can be `state.Open(tmp)` then `LoadSeen(clock.Now)`; close and re-open the store for the restart case. Its crash hook covers CHK-M4-218. Use a fake `InventoryRunner`.
- **Running it:** start `Run.Heartbeat()` (or answer one heartbeat) so `FirstHeartbeat()` closes, then run `(&loops.Puller{Run: r, Seen: s, Inventory: inv}).Loop()` in a goroutine. It returns after the parent context is cancelled or a 401.
- **CHK-M4-221 (5,000 plugins):** 100 batches of 50, only the 100th `final: true`.
- **TASK-106 (impl-agent-2):** it already codes against this exact shape.
