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

## Revision 1 (2026-11-02)

Builder: impl-agent-m10r. Cause: PR #18 CI on 22.04, where TestServeMalformed's later subtests got `refused busy`. Recorded in `work/decisions.md` as "TASK-225 r1: clear busy before the connection is closed". File: `agent/internal/runner/serve.go` only.

**Defect.** The per-connection goroutine had three defers: `wg.Done`, then `busy.Store(false)`, then `conn.Close()`. Defers run LIFO, so the connection closed first. A client saw EOF while `busy` was still true, and its next dial was refused `busy`. The agent retries `busy` for 30 s, so nothing is lost functionally, but the runner reported busy while idle.

**Change.**
- **L88-104, the per-connection goroutine.** One deferred func now runs, in order: `busy.Store(false)`, then `conn.Close()`, then `wg.Done()`. `wg.Done` stays last, so `Serve`'s `wg.Wait` still waits for the close. The fatal path (`s.once.Do`: record `fatal` and close the listener) is in the body, so it still runs before `busy` is cleared, as before. The comment gives the order and the reason.
- **L146-154, in `handle`.** This goes one step past the lead's example; the lead confirmed it in the decisions row "TASK-225 r1 scope" (2026-11-02). On the accepted path, `handle`'s deferred cleanup used `conn.Close()` to wake its 1-byte reader goroutine, then waited `<-readDone`. That close happens before `handle` returns, so after a `done` reply the client would still see EOF while `busy` was true, and the reorder alone would fix only the refusal paths. The decisions row says `busy` is cleared "before the connection closes", so `handle` now wakes the reader with `conn.SetReadDeadline(time.Now())` instead. A deadline applies to pending as well as future I/O (`net.Conn` docs), so the blocked `Read` returns at once. Only if `SetReadDeadline` fails does it close the connection, so `<-readDone` can never hang. Afterwards the reader's `cancel()` runs on an already-ended job, which is harmless. The outer goroutine now does the only close, after `busy` is cleared.

**`handle` has finished every job-side step before it returns, so clearing `busy` after it can't let two jobs overlap:**
- **Refusal paths** (bad frame, failed check, failed `accepted` write): they return before any job starts. There is no reader goroutine and no `Exec.Run`.
- **Accepted path:** `Exec.Run` returns only after all of these:
  - its `wg.Wait` over every plugin goroutine. Each plugin has already received its wait result and waited `<-capDone`, so its capture and wait goroutines have ended.
  - each plugin cgroup's `release`;
  - the after-job `Sweep`, and the emptying of `TmpDirs` (`job.go` `cleanup`).
- **After `Run`:** the `done` reply is written (or skipped when cancelled). Then `handle`'s defers run, in LIFO order: the reader is woken and `<-readDone` is waited on, then `cancel()`.
- **When `handle` returns,** no goroutine of that job is left. The next `CompareAndSwap(false, true)` therefore can't start a job while one is running.

**The fatal-path window is closed** (added to r1 by the lead's decisions row "TASK-225 r1 scope", 2026-11-02).

*The window.* On the fatal path, `Accept` may already have returned a peer-checked connection before the listener closed. If the loop's `CompareAndSwap` then ran after `busy` was cleared, that connection's job would run on a runner whose sweep had failed. This was the same before r1.

*Change.*
- **L44-49: a new field `failed atomic.Bool`.** `s.fatal` and `s.once` are kept as they were. I didn't fold them into one atomic, because a `Bool` plus the existing write-once error is the smallest change, and the error read is ordered by the flag:
  - Inside `once.Do` (L101), the order is `s.fatal = err`, then `s.failed.Store(true)`, then `Listener.Close()`.
  - That body runs before the goroutine's deferred `busy.Store(false)`, so `failed` is always set before `busy` is cleared.
- **L71-80, in the accept loop:** `won := s.busy.CompareAndSwap(false, true)`, then `if s.failed.Load()`. When it's set, the loop closes the connection with no reply (a busy reply would make the agent retry), calls `wg.Wait()`, and returns `s.fatal`. Otherwise `!won` gives the busy refusal as before.
- **L63, on the Accept-error path:** it now tests `s.failed.Load()` instead of `s.fatal != nil`, so one source decides "fatal". That read was already ordered by `wg.Wait`.

*Why the check comes after the CAS, not before it as the lead's message said.* A check only before the CAS leaves a window:
1. the loop reads `failed` (false);
2. the handler sets `failed` and clears `busy`;
3. the loop's CAS wins;
4. one job runs after the failed sweep.

Checked after the CAS, it is exact. A won CAS read `false`, and that `false` is either the initial value (no job has run, so no fatal) or the store the handler made after `failed.Store(true)`. Go's atomics are sequentially consistent, so the following `failed.Load()` then sees true. A lost CAS also checks the flag, so once `failed` is set, no busy reply goes out either. Before `failed` is set, a busy reply is still correct, because the job really is still running. The rule asked for is "a job never runs after a failed cleanup, and no busy reply", and this placement enforces it.

*Memory ordering of `s.fatal`.* It is written once inside `once.Do`, before `failed.Store(true)`. Both reads come after `failed.Load()` returned true, and after `wg.Wait()`, so there is no data race.

**Gates (from `agent/`):**
- `gofmt -l .`: nothing.
- `go vet` with `GOOS=windows` and `GOOS=linux`, each with no tags and with `-tags delegated`: rc 0 (4 runs).
- `golangci-lint run ./...` for the same four combinations (`--build-tags delegated`): 0 issues each, no `nolint`.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- `go mod verify`: all modules verified.
- Not run: the tests (tester, WSL with `-race`).

**For the tester.**
- TestServeMalformed, repeated many times under `-race`, must give no `refused busy`.
- A new accepted-path row: run a normal job (fake executor), read until EOF after `done`, and dial again at once. That second connection must get its own `accepted`, never `refused busy`.
- **Fatal race row (new).** Use a fake executor whose `Run` blocks on a channel and then returns an error.
  - While it runs, keep a second client dialling in a tight loop, so a connection is accepted around the fatal.
  - Release the executor.
  - Expect: `Serve` returns that error; the executor's `Run` was called exactly once; and every other connection got either `refused busy` (before the fatal) or a close with no reply. None gets `accepted`.
  - To make the window deterministic, a test `Listener` can hand out one connection only after it sees `Listener.Close()`. That connection must be closed unanswered, and `Run` must not be called a second time.
- Plants:
  - (a) restore the LIFO defers (the decisions row's plant). TestServeMalformed should go red.
  - (b) restore `handle`'s `conn.Close()` wake-up. Only the accepted-path row should go red.
  - (c) remove the `failed` check at L76-80. The deterministic fatal race row should go red: a second `Run`, or `accepted` on the late connection.
  - Moving the check before the CAS opens only a scheduling window between two adjacent statements. A black-box test can't hit it deterministically: a connection handed out after `Close` is already caught by a check before the CAS. That placement is covered by review, plus the tight-loop row repeated under `-race`.
- Rows that must stay green: client close cancels the executor within 1 s (the reader still sees EOF), and the fatal row (`Serve` returns the error and the connection closes without `done`).
