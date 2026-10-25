# TASK-101 IMPL: run state and heartbeat loop

REQ-097, REQ-095, REQ-103. TS §3.3 (L202, L206, L211, L224–L226), §3.2 step 7 and 8, §6.5 L1163, §3.7 L484. #30, #78, #81 (all agreed 2026-10-24); W1 lead rulings 2026-10-24 (any file at `capread.sock` counts; 403 `pending_approval` uses the back-off). Plan `work/plans/TASK-101.md`. **Two approvals (TS §8.2, agent).** No tests were run (tester's job).

## Files (new)

| File | Code lines | What |
| --- | --- | --- |
| `agent/internal/agent/loops/run.go` | 165 | `Run`, `Deps`, `NewRun`, the interfaces `Doer`, `Rotator`, `InventoryRunner`, `ComplianceHandler`, `Call`, `Stop`, the shared-state setters and getters. |
| `agent/internal/agent/loops/heartbeat.go` | 78 | `(*Run).Heartbeat()`, one heartbeat call, helper detection. |

243 code lines against the 190 estimate (counts exclude blank and comment lines); most of the excess is one-line accessors TASK-103 and TASK-104 need. No file outside `agent/internal/agent/loops/` changed.

## Interfaces (fixed for TASK-103, TASK-104 and TASK-106)

```go
type Doer interface { Do(ctx context.Context, r transport.Request) (transport.Response, error) } // *transport.Client
type Rotator interface { MaybeRotate(ctx context.Context, now time.Time) error }             // *token.Rotator
type InventoryRunner interface { RunJob(ctx context.Context, jobID wire.UUID); Unscheduled(ctx context.Context) }
type ComplianceHandler interface { Handle(ctx context.Context, job wire.Job) }
type Deps struct { Client Doer; Tokens *token.Holder; Rotator Rotator; AgentID wire.UUID; Version string
    Clock schedule.Clock; Rand schedule.Source; Log *slog.Logger; JobPullSeconds, MaxParallelPlugins int; CapreadSock string }
func NewRun(parent context.Context, d Deps) *Run
func (r *Run) Context() context.Context; Clock() schedule.Clock; Rand() schedule.Source; Log() *slog.Logger; AgentID() wire.UUID
func (r *Run) Call(ctx context.Context, req transport.Request) (transport.Response, error)
func (r *Run) Stop(problemType string); Stopped() bool
func (r *Run) SetLastError(text string); SetLastPull(t time.Time); SetCurrentJob(id *wire.UUID)
func (r *Run) SetIntervals(pullSeconds, maxParallel int); PullInterval() time.Duration; PullChanged() <-chan struct{}; MaxParallelPlugins() int
func (r *Run) FirstHeartbeat() <-chan struct{}
func (r *Run) Heartbeat()  // blocks until the Run stops
var ErrStopped error; const CapreadSock = "/run/bitscan/capread.sock"
```

Every Deps field except `Log` (nil: `slog.Default()`) and `CapreadSock` (empty: the constant) is required.

## Behaviour

- **Run context:** a child of the parent context (SIGTERM in TASK-106). `Stop` cancels it once and logs one fixed line: for `token_revoked`, `token_expired` or `enrollment_rejected` (revision 1) "… must be re-enrolled with a new enrolment token", otherwise "… the host must be re-enrolled". The Run never exits the process (#81 (a)). After a stop `Call` sends nothing and returns `ErrStopped` with class Stop.
- **`Call`:** sets `Authorization` from `Tokens.Current()` (so a rotated token is used by every loop at once) and the agent id, then classifies (TASK-093). **Stop** (any 401, on any loop, including `machine_id_mismatch`) calls `Stop(type)`, so a 401 on the pull or an upload stops the heartbeat loop too: its `Sleep` returns when the context ends. **Drop** logs one fixed warning and sets `last_error` to `"<route> <status> <type>"` (for example `inventory 422 about:blank`), or `"<route> not sent"` when no answer was received (a refused id). The manager's `type` is reduced to visible ASCII (`?` for anything else), and the text is cut to 1,024 characters, so `last_error` always passes the contract. **Retry** with a certificate or pin failure logs one fixed error line. Wait and Retry are left to the caller's back-off.
- **Heartbeat loop:** one heartbeat at start, then `HeartbeatInterval` (300 s ± 30 s) after each Success or Drop. Wait (403 `pending_approval`), 429, 5xx and network errors use `schedule.Backoff` (10, 20 … 300 s, ±10 %), which resets after a Success or a Drop. 429's `Retry-After` is not used (normal back-off, TS §6.3 L1136). `FirstHeartbeat()` is closed after the first attempt, whatever its result.
- **Body (#78):** `agent_version` = `Deps.Version`; `uptime_s` = whole seconds since `NewRun` on the injected clock (the agent process); `last_pull_at` = the last `SetLastPull` (TASK-103 calls it only for a pull answered 200), else null; `current_job_id` = `SetCurrentJob`, else null; `spool_bytes` 0; `last_error` as below; `runner_helpers` `["capread"]` when `os.Lstat(CapreadSock)` succeeds (any file type), else `[]`; `clock` = the injected clock's now. The body goes through `wire.Encode` (the contract self-check). If that fails (for example an empty or over-32-character version), nothing is sent and one fixed line is logged.
- **`last_error` (#78 (e)):** taken (swapped to nil) when a heartbeat is built. If that heartbeat is not answered with Success, it is put back unless a newer error replaced it, so a drop is never lost to an unanswered heartbeat. Drop answers to the heartbeat itself replace it with the heartbeat's own text.
- **Answer:** decoded strictly as `HeartbeatResponse`. A refused answer sets `last_error` = `heartbeat answer refused` and changes nothing. Otherwise `SetIntervals(job_pull_seconds, max_parallel_plugins)` clamps them to 60–3,600 and 1–8 and wakes the pull loop via `PullChanged()` when the pull value changed. The answer causes no other call; only `Rotator.MaybeRotate(ctx, now)` then runs, as TASK-099 requires (it makes a call only when its window is open). `token.ErrStop` from rotation stops the Run with the new-enrolment-token line (revision 1); another rotation error logs one fixed line.
- **Logs:** fixed text with an `agent_id` attribute only. No token, header, body, answer text or error text from the host or the manager is logged; the only manager-sent value in a log line is the sanitised problem `type` inside `last_error`.

## Notes for TASK-103 (impl-agent) and TASK-104

- The pull loop waits for `FirstHeartbeat()`, sleeps `PullInterval()` in a `select` with `PullChanged()` (recompute from now on a change) and `Context().Done()`, and sends with `Call`.
- `SetCurrentJob(&id)` while a compliance job is handled and `SetCurrentJob(nil)` after.
- `Rand()` is safe to share across goroutines (a mutex wraps `Deps.Rand`); each loop keeps its own `schedule.Backoff`.

## Not covered here (spec silent, or other tasks)

- Rotation drop answers (TASK-099's `Rotator` calls the client directly) do not become `last_error`; the rotator returns a fixed error and is retried at the next heartbeat. **Reviewer:** flag it if #78 (e) should include them.
- `Version` comes from TASK-106 (`-X main.version`); an empty value makes every heartbeat fail the self-check, so TASK-106 must never pass "".

## Checks run (Windows, golangci-lint 2.14.0)

- `gofmt -l agent/internal/agent/loops`: nothing.
- `GOOS=linux go vet ./internal/agent/loops/`: clean. `CGO_ENABLED=0 GOOS=linux go build ./...`: ok.
- `golangci-lint run ./internal/agent/loops/` with GOOS=linux and windows: 0 issues. Whole-tree `golangci-lint run ./...` is red only from the tester's `internal/inventory/watch_linux_test.go` (5 gosec findings, and gofmt); tester-m4b has been told.
- Builder checklist: 10 (stop is honoured: every wait is `schedule.Sleep` on the run context) and 11 (no tokens, bodies or output in logs; `Request.String()` hides both) hold; the rest are manager-side.

## Round 1 fix (tester-m4: TestHeartbeat401Stops/type_enrollment_rejected, TestRotationStopStopsLoops)

- **Cause:** the "new enrolment token" line was logged only for `token_revoked` and `token_expired`. REQ-096 (3) also requires it for `enrollment_rejected`, which is how a rejected held enrolment answers heartbeats (TS §3.2 step 5). A rotate 401 (`token.ErrStop`, which has no type; reuse detection revokes both tokens) went to the generic line.
- **Fix:** `Stop(type)` now gives the "new enrolment token" line for `token_revoked`, `token_expired` and `enrollment_rejected`. A new unexported `stop(newEnrolment bool)` holds the once-only stop, and `heartbeat.go` calls `r.stop(true)` on `token.ErrStop`. Other 401 types (`unauthorized`, `machine_id_mismatch`, `""`) keep the generic line. `Stop`'s exported signature is unchanged; only `run.go` and `heartbeat.go` call it.
- **Re-run:** `TestHeartbeat401Stops`, `TestRotationStopStopsLoops`, then `TestOther401StopsHeartbeat` and the CHK-M4-189 plants (they share `Stop`).
- Checks: gofmt clean; `GOOS=linux go vet ./internal/agent/loops/` clean; `golangci-lint run ./internal/agent/loops/` with GOOS=linux and windows: 0 issues.

## Revision 1 (CHK-M4-189-r1 FAIL, 2026-10-25)

Cause: `Stop` gave the "new enrolment token" line only for `token_revoked` and `token_expired`, and a rotation stop went through `Stop("")`, so both REQ-096 (3) and TS §3.2 step 8 got the generic line.

- `run.go` `Stop`: `enrollment_rejected` now also picks "… must be re-enrolled with a new enrolment token" (REQ-096 (3): a rejected held enrolment answered on a later heartbeat). The generic line stays for every other type (`machine_id_mismatch`, `unauthorized`, `""`, anything else). `Stop` now delegates to an unexported `stop(newEnrolment bool)` that holds the once-only cancel and the two fixed lines; the lines' text did not change.
- `heartbeat.go`: `token.ErrStop` from `MaybeRotate` now calls `r.stop(true)`, the new-enrolment-token line. Kept inside the loops package; **the token package is unchanged** (no file outside the task touched). Reason: `token.ErrStop` is returned only for a 401 on rotate, and its approved TASK-099 text already says "the host must be re-enrolled with a new enrolment token"; a rotate 401 is `token_revoked` (including reuse detection, which revokes both tokens) or `token_expired` (TS §3.2 step 8). A rotate 401 `machine_id_mismatch` also gets this line, consistent with `token.ErrStop`'s own text; re-enrolment needs a fresh `enroll.token` in every case, since it is deleted after enrolment (TS §3.2 step 2). **Reviewer:** flag it if the type must be threaded through `token.ErrStop` instead.
- Unchanged: one line per Run (`sync.Once`), a stop on the pull or an upload, `ErrStopped`, every other log line. No line holds the token or any manager-sent text.

Checks (Windows, from `agent/`): `gofmt -l .` lists only the tester's `internal/agent/transport/client_test.go`; `GOOS=linux go vet ./...` clean; `GOOS=linux golangci-lint run ./...` 1 issue, in the tester's `internal/inventory/osinfo_test.go:953` (QF1001); `golangci-lint run ./internal/agent/loops/` (Windows) 0 issues. Re-run: `TestHeartbeat401Stops` and `TestRotationStopStopsLoops`. TASK-099 tests need no re-run.

## For the tester

TP-M4-16 (CHK-M4-185 to -193), mutation rows CHK-M4-335 and CHK-M4-355. Inject a fake `Doer`, a fake `Rotator`, a fake `schedule.Clock` and a seeded `schedule.Source`, a temporary `CapreadSock` path and a `slog` handler that records lines. `Heartbeat()` blocks; run it in a goroutine and stop it by cancelling the parent context or by a 401.
