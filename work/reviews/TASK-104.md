# TASK-104 REVIEW: inventory jobs and watcher uploads

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/loops/inventory.go`, new and the only file (`work/reports/TASK-104-impl.md`). Sources:
- TS §3.3 L224–L226, §3.4 L239–L244, §6.5 L1186;
- REQ-100 (5), REQ-101, REQ-102;
- #72 (a) and (e), #80, and the lead's ruling Q2 of 2026-10-24 (a failed collection uploads nothing).

TEST: PASS (`work/reports/TASK-104-test.md`, CHK-M4-235..241 and -101).
- `-race` gives 44/44 for the inventory tests, 83/83 for the whole package and 440/440 at `-count=10`.
- 9/9 plants are red: 350, 351 (twice), 352, 337, a 503 not retried, the window, the stale body and the collect error.
- CHK-M4-101's job-path half was run under strace. Only `dpkg-query`, `hostnamectl` and `ip` are executed, and no argv holds the canary.

## Checks
1. Spec:
   - Uploads are `PUT …/inventory`, with `?job_id=` for a job, gzip and `Content-Encoding` (#72 (a)).
   - 204 ends the upload. Drop (409, 413, 422 and the other TS §3.3 L224 codes) is logged and becomes `last_error` in `Run.Call`, with no retry. Any 401 stops every loop.
   - 403 `pending_approval`, 429, 5xx and network errors are retried with a fresh back-off (10 s up to 300 s), never in a tight loop (REQ-095 (5)).
   - A job retry sends the same bytes (REQ-101 (3)).
2. #80 and #72 (e):
   - An unscheduled upload waits until `HoldOff` (10 min 30 s) after the last accepted unscheduled upload, including across 429 retries.
   - A signal during the hold-off or a back-off wait marks the body stale, so the next attempt collects again. One upload is made, with the latest state.
   - The watcher's own send blocks, and it merges changes while an upload is in progress, so no change is lost.
   - Job uploads (`dispatched`) are separate and do not wait for the hold-off.
3. Job window:
   - `received` is taken before the job mutex, so time spent waiting behind another job counts.
   - A retry whose back-off would end after 30 minutes is not made, and one fixed line with the `job_id` is logged.
4. #35 and safety:
   - `Collector` takes only `ctx`, so no job, heartbeat or answer value reaches a command (strace check).
   - Inventory cannot be turned off: no option or answer skips collection.
   - A collection failure uploads nothing and sets the fixed `last_error` `inventory collection failed`.
5. Concurrency and stop:
   - Every wait selects on `ctx` (checklist 10).
   - `Watch` waits for its goroutine. A watcher failure is logged once and leaves job uploads working (REQ-102 (4)).
   - After a Stop, `Call` returns at once without a network call.
6. Logs: fixed text with only `agent_id` and `job_id`. No body, package, token or host text (checklist 11).
7. Re-run by the reviewer (Windows):
   - `gofmt -l internal/agent/loops` prints nothing.
   - `GOOS=linux golangci-lint run ./internal/agent/loops/...` reports 0 issues.
8. Scope: 1 file, 130 code lines.

## Findings
1. nit, `inventory.go:124-132`. `lastUnsc` moves only on success. Under #72 (e), the manager's 10-minute window starts when an unscheduled upload reaches decoding, whether it is accepted or not. So after a 422 or 413 Drop, the next signal can upload before the hold-off ends. The manager then answers 429, and the agent backs off. That costs extra requests only; nothing is lost or looped tightly. Optional: also set `lastUnsc` on a Drop that carries a status.
2. nit, `inventory.go:110`. After a restart, `lastUnsc` is zero, so the first unscheduled upload can fall inside the manager's window from before the restart. It gets a 429 and backs off. That is acceptable and needs no persisted state (as the TASK-091 hold-off ruling of 2026-10-24).
