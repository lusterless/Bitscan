# TASK-225 IMPL: runner serve loop (`internal/runner/serve.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-234, REQ-235 (4), REQ-236, REQ-261. Spec: TS §3.7 L281–L285. Open item applied: #130. Plan: `work/plans/TASK-209.md` §3–§4. Depends on TASK-209, TASK-213 and TASK-217 (all reported).

## Files

- `agent/internal/runner/serve.go` (new, 164 lines, 124 code lines; estimate 170). Portable, with no build tag.

No other file changed.

## Interface

```go
type Executor interface {
    Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
}
type Listener interface {          // *sdsock.Listener satisfies it
    Accept() (*net.UnixConn, error)
    Close() error
}
type Server struct {
    Listener Listener; Checks *Checks; Exec Executor
    Clock func() time.Time; Log *slog.Logger
    /* busy flag, fatal error */
}
func (s *Server) Serve(ctx context.Context) error
```

Changes from plan §4:
- **`Listener` is an interface, not `*sdsock.Listener`.** `sdsock` is Linux only, and `serve.go` has no build tag. A concrete import would stop package `runner` building on Windows. `*sdsock.Listener` satisfies the interface, which TASK-228 wires up. Tests can wrap a `*net.UnixListener`.
- **The Executor contract is made explicit** (fixed here for TASK-224). `Run` returns nil once the job has ended: every plugin was emitted, `ctx` was cancelled, or `emit` failed. A **non-nil error is fatal**: the runner can no longer guarantee cleanup, for example after a failed sweep (TASK-215: "the runner must exit"). `handle` closes the connection without `done`, `Serve` stops accepting and returns that error, and `main` exits so systemd restarts the runner and kills the service cgroup.

## How each acceptance point is met

One `Accept` loop. Each connection carries exactly one request:
1. Read deadline 30 s; `proto.ReadRequest` reads exactly one frame.
2. On a decode error: `refused <proto.RefusalFor(err)>` (`malformed`, or `not_compliance` for an inventory job), logged with the word only, then close.
3. `Checks.Check(req, Clock())`. On refusal: `refused <word>`, logged with `job_id` and the word, then close. No executor call happens, so nothing starts.
4. `accepted`, logged with `job_id`, `agent_id` and the plugin count.
5. The job context is cancelled by `ctx`, by an `emit` error, or by a reader goroutine. That goroutine blocks on a 1-byte `Read` with no deadline, and **any** return cancels the job: a byte, EOF or an error. A second frame is therefore never decoded or run (REQ-261, CHK-M10-322); its first byte ends the job.
6. `Exec.Run(jobCtx, req, emit)`. `emit` takes a mutex, so concurrent plugin goroutines are safe. It sets a 60 s write deadline per reply, and a write error cancels the job.
7. `Run` returns nil with the job not cancelled: `done`, logged with the result count. If the job was cancelled, there is no `done` (the connection has gone). If `Run` returned an error, the job is fatal as above.

Other points:
- **REQ-235 (4) busy:** an atomic flag. A second connection while a job runs gets `refused busy` at once, its request never read, and is closed (#130 (g)).
- **Shutdown:** `context.AfterFunc(ctx)` closes the listener. `Serve` waits for the running job, which sees the cancelled `ctx` and runs the executor's kill and sweep (TASK-224), then returns nil.
- **Logs:** ids, reason words and counts only. Never `execute`, a pattern, output or a request body (checklist item 11).
- **Clock:** `Clock` is used only for the job checks. Socket deadlines use real time (they are kernel deadlines).

## Gates (from `agent/`)

- `gofmt -l internal/runner` on non-test files: nothing.
- `go vet ./internal/runner/` on Windows and `GOOS=linux`: clean.
- `golangci-lint run ./internal/runner/...` on Windows and `GOOS=linux`: 0 issues in non-test files (one errcheck fixed with `_ =`).
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./internal/runner/...`: OK.
- Smoke test in a throwaway copy, on **Windows** AF_UNIX, with a fake executor, three runs each. `-race` needs cgo here, so it ran without race; the tester's WSL run has `-race`. It covered:
  - a normal job (`accepted`, 2 × `result`, `done`);
  - a replay (`replayed`);
  - a malformed `{}` frame (`malformed`);
  - busy (a second client reading only gets `refused busy`);
  - client close cancels the executor's context within 1 s;
  - a fatal `Run` error: the connection closes without `done`, and `Serve` returns the error.

## For the tester (tester-m10, TP-M10-18)

Note from impl-agent-m10b (TASK-218): on **Windows** AF_UNIX, a client that writes its request before reading may see a reset instead of the `busy` reply, because the runner closes without reading. On Linux the queued reply is read. Run the busy row on Linux, or have the second client read first.

| CHK | Plant | Notes |
| --- | --- | --- |
| -322 | Decode a second frame after `accepted` and run it (S) | Replace the 1-byte reader with a `proto.ReadRequest` loop |
| -391 (G72 half) | Drop the reader goroutine's `cancel()`: plugins keep running after the agent closes (S, VM) | |
| -382 (serve half) | Log `req.Job.Plugins[i].Execute` or a result's stdout (S) | Run a canary sweep over the logs |

Extra rows worth planting:
- The busy flag is never set: two jobs run at once.
- A refused job still reaches `Exec.Run`: the exec counter is non-zero.
- `done` is written after a cancelled job.
- A fatal `Run` error is ignored: `Serve` keeps accepting.
