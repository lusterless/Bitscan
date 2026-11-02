# TASK-224 IMPL: job executor (`internal/runner/job.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-239 (6), REQ-240, REQ-241. Spec: TS §3.5 L249–L252, §3.7 L284, §8.1 L1245. Open items applied: #134 (h), #135 (c), #136 (d), (f), #138. Plan: `work/plans/TASK-215.md` §4 and §6. Depends on TASK-210, TASK-214, TASK-215 and TASK-221 (all reported). It implements the `Executor` interface fixed in `serve.go` (TASK-225).

## Files

- `agent/internal/runner/job.go` (new, 196 lines, 162 code lines; estimate 190). It carries `//go:build linux` because it uses `*Spawned` from `spawn_linux.go`. It names no `os/exec` identifier (TASK-211 lint).

No other file changed. The planned overflow file (`tmpclean_linux.go`) was not needed.

## Interface

```go
type JobExecutor struct {
    CG      *Cgroups
    Spawn   func(*Plugin, string, func() time.Time) (*Spawned, error)  // runner.Spawn in production
    Now     func() time.Time
    TmpDirs []string      // emptied after every job; production: "/tmp", "/var/tmp"
    Log     *slog.Logger
}
func (e *JobExecutor) Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
```

Plan §6 named the struct `Executor`. That name is taken by the interface in `serve.go`, so the struct is `JobExecutor`.

**`TmpDirs` is explicit, with no default.** If it defaulted to the real `/tmp` and `/var/tmp`, a test run outside a `PrivateTmp` unit (CI, `systemd-run` without `-p PrivateTmp=yes`) would wipe the host's `/tmp`. TASK-228 sets `{"/tmp", "/var/tmp"}`; tests give a temporary directory.

## How each acceptance point is met

`Run`:
1. `redact.Compile` once. If it fails, which the checks already refuse, every plugin is reported `runner_unavailable`.
2. A semaphore of `MaxParallelPlugins` (REQ-239 (6)). Plugins start in payload order, one goroutine each.
3. If a plugin hits a cgroup failure (`NewPlugin`, or `ErrCgroup` from `Spawn`), no new plugin starts. Every plugin not started is emitted `runner_unavailable` (REQ-241 (5), #136 (f)); plugins already running finish normally.
4. If `ctx` is cancelled (the agent closed the connection, or the runner is stopping), running plugins are killed, no new ones start, and **nothing more is emitted**.
5. **Always:** `cleanup`, which runs `CG.Sweep` (with `context.WithoutCancel`, so a cancelled job still sweeps fully), then removes every entry of each `TmpDirs` directory with `RemoveTempDir`. Any failure is joined and returned. That is the only error `Run` returns, and it is fatal to `Serve` (TASK-225 contract), so the runner exits.

Per plugin, in this order:
1. `NewPlugin`, then `Spawn`. `ErrExec` gives `runner_unavailable` for this plugin only. `ErrCgroup` with a running child kills the child at once and reports it `runner_unavailable`.
2. Both pipes are captured in two goroutines (TASK-214), alongside a goroutine in `Spawned.Wait()`.
3. A timer of `timeout_s` (wall time, as the spec gives it). On expiry: `cgroup.kill`, `timed_out` true; SIGKILL gives exit 137 (#136 (d), (e)). On cancel: `cgroup.kill`. If `cgroup.kill` fails, the shell itself is killed (`os.Process.Kill`), so the wait can't hang. The sweep, or the runner's exit, gets the rest.
4. `finished` is read from the clock, then `release`: `cgroup.kill` (always, so a background child dies, REQ-240 (1)–(3), (6)), `WaitEmpty` (at most 5 s), and `Remove`. A cgroup that doesn't empty is logged and left to the sweep (plan §4).
5. The pipes then reach EOF. A process that moved itself out of the cgroup may still hold them, so after a 1 s grace the read ends are closed and the sweep kills that process.
6. `RemoveTempDir` (REQ-239 (4), REQ-240 (9)).
7. If the job was cancelled, return without emitting. Otherwise, under `redMu` (one plugin redacted at a time, #134 (h)), `Build` (TASK-214), then `emit`.

Other acceptance points:

| Point | Where |
| --- | --- |
| REQ-240 (4), (5) (plugin moved into `supervisor`, or into a nested cgroup) | The after-job `Sweep` (TASK-215) |
| REQ-240 (8) (the runner moved by a plugin) | `ensureSupervisor` in every `Kill` and sweep pass; the accepted residual is a runner restart |
| REQ-240 (10) (connection closed) | `serve.go` cancels the job, then the cancel branch and the sweep run here |

Logs: one line per plugin with `job_id`, `plugin_uuid`, `exit_code`, `timed_out` and `duration_ms`. Error lines are fixed words. Never `execute`, a pattern or output.

## Gates (from `agent/`)

- `gofmt -l internal/runner` on non-test files: nothing.
- `go vet ./internal/runner/` and `golangci-lint run ./internal/runner/...` on Windows, where the file is excluded by its tag, and on `GOOS=linux`: 0 issues in non-test files.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./internal/runner/...`: OK.
- Not run: the executor needs a delegated cgroup v2 (Linux), and Linux runs are the testers'.

## For the tester (tester-m10, TP-M10-17)

These are Linux rows under `systemd-run -p Delegate=yes`. Build `CG` with `runner.Open` inside the unit and call `Sweep` once, as TASK-228 will. Set `Spawn: runner.Spawn` (or a failing fake for REQ-241 (5)) and `TmpDirs` to a temporary directory. With a fake `Spawn` that returns `ErrExec`, or `ErrCgroup` with no child, the per-plugin `runner_unavailable` and the stop-the-job rows need no real process.

| CHK | Plant | Notes |
| --- | --- | --- |
| -337 | `release` without `cg.Kill()`: a `sleep 300 &` child survives | S, VM |
| -342 | `cleanup` skips `TmpDirs` | |
| -343 | Timer never fires: a `sleep 100` with `timeout_s` 2 isn't killed | S, VM |
| -341 | Drop `RemoveTempDir` | Together with TASK-221 |
| -336 (executor half) | Through a `Spawn` that doesn't use `StartIn` | |
| -391 (executor half) | Ignore `ctx.Done()` in the select: plugins outlive the closed connection | S, VM |
| -382 (executor half) | Log `out.Data` | Canary sweep over the logs |

Extra rows worth planting:
- `MaxParallelPlugins` ignored (unbuffered or large semaphore): 8 × `sleep 2` with 3 allowed must take three rounds.
- A cgroup failure doesn't set `stopped`: later plugins still start.
- Results emitted after cancel.
- `redMu` removed. This is a memory property, not directly visible; covered by review.

## Revision 1 (2026-11-01)

Builder: impl-agent-m10r. Cause: reviewer-m10c's blocking finding, recorded in `work/decisions.md` as "TASK-224 r1: always kill the shell when a plugin is stopped".

**Defect.** `stop()` called `s.proc.Kill()` only when `cg.Kill()` failed. If a plugin's shell moves itself out of `p-<n>` (TS §3.7 L284 expects plugins to try this), `cgroup.kill` succeeds but the shell keeps running. The timer and `ctx.Done()` branches then block on `w = <-waitCh` until that process exits on its own. So the timeout isn't enforced, `Run` never returns, the after-job sweep never runs, and every later job is refused `busy`. That breaks TS §3.5 L249-L250 ("No plugin process outlives its job").

**Change.** Only `agent/internal/runner/job.go`, the `stop` closure and its comment (now L101-109; it was L101-107):

```go
stop := func() {
	_ = cg.Kill()
	_ = s.proc.Kill()
}
```

`stop()` now always kills the cgroup and then the shell. The shell's `Kill` error is ignored: `os.ErrProcessDone` when the shell was already reaped, ESRCH turned into `ErrProcessDone`, or the released-process error, none of which needs action here. Everything else is unchanged. The `err != nil` call after `Spawn` (the child started but the cgroup state is broken, so it's reported unavailable) now also kills the shell directly. That's the intended effect, because the result is unavailable anyway. A killed shell gives `ExitCode` 128 + 9 = 137 (`capture.go`).

**Kill beside a concurrent Wait (checked in the Go 1.27.2 source, `os/exec_unix.go`, `os/pidfd_linux.go`).** `s.proc` is `cmd.Process`, the `*os.Process` that `exec.Cmd.Start` returns in `spawn_linux.go`. It's used in one of two modes:
- **pidfd mode** (the normal case on the supported kernels): `Kill` sends the signal through the pidfd (`pidfd_send_signal`). The pidfd always refers to that one process, so a reused PID can't be signalled. After `Wait` has reaped the process, the handle status is `statusDone` and `Kill` returns `ErrProcessDone`. The handle is reference-counted (`handleTransientAcquire`/`Release`), so a `Kill` running at the same moment as `Wait` can't use a closed or reused descriptor number.
- **PID mode** (fallback): `pidWait` blocks in `waitid(WNOWAIT)`, marks the process `statusDone`, and takes `sigMu` for writing before `Wait4` reaps it. `pidSignal` holds `sigMu` for reading and checks `statusDone` first. So a `Kill` either runs before the reap (the PID is still ours, perhaps a zombie) or returns `ErrProcessDone`. It never signals a reused PID.

So calling `Kill` while the `waitCh` goroutine is in `Wait` is safe as written, and nothing smaller is needed.

**Gates (from `agent/`, Windows and `GOOS=linux`):**
- `gofmt -l .`: nothing.
- `go vet ./...` and `GOOS=linux go vet ./...`: rc 0.
- `golangci-lint run ./...` and `GOOS=linux golangci-lint run ./...`: 0 issues each, no `nolint`.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- `go mod verify`: all modules verified.
- Not run: the delegated-cgroup row needs Linux, and Linux runs are the tester's.

**New row for the tester (delegated, as `bitscan-runner`, builder-checklist item 21).** Use the TP-M10-17 setup (`systemd-run -p Delegate=yes -p User=bitscan-runner …`, `CG` from `runner.Open`, `Spawn: runner.Spawn`). Run one plugin with `timeout_s` 2 and execute `echo $$ > <base>/supervisor/cgroup.procs; exec sleep 100000`, where `<base>` is the delegated cgroup directory that holds `supervisor`. Expect:
- the result has `timed_out` true and exit code 137;
- `Run` returns within about 10 s;
- afterwards no `sleep 100000` survives anywhere (`pgrep -f 'sleep 100000'` empty, and every `cgroup.procs` in the subtree holds only the runner).

This row must fail on the pre-r1 code: `Run` blocks well past 10 s, because the moved shell survives `cgroup.kill`. Bound it with a test deadline, then kill the sleep by PID.

## Revision 2 (2026-11-01)

Builder: impl-agent-m10r. Cause: reviewer-m10c's two new nits, recorded in `work/decisions.md` as "TASK-224 r2: the reviewer's two new nits are fixed". Files: `agent/internal/runner/job.go` and `agent/cmd/bitscan-runner/main.go`. Nothing else changed.

### (1) A Capture error marks the result truncated (job.go L113-118, L150-156)

**Defect.** `out, _ = Capture(...)` dropped the error. A stream cut short by a read error could go out with `truncated` false, so the evaluator would judge partial stdout as complete. That's a possible false PASS, for example with `not_contains`. The realistic case is a process that left the plugin cgroup and still holds a pipe: after `captureGrace`, job.go closes the read ends, and `Capture` returns its bytes so far with a "file already closed" error.

**How truncated is carried today.** There is one wire flag, and it is stdout-driven (#113). `Build` takes it from `set.Apply(o.Stdout, redact.Stdout)`, which reports true when the stdout capture has `Overflow` or the 64 KB cut applies. Stderr never sets it, including its 16 KB cut.

**Change.** The two Capture errors are kept (`outErr`, `errOutErr`). After `<-capDone`, if either one is non-nil, `out.Overflow = true`. That sets the one flag through the existing stdout path, so `result.go` and `redact` are unchanged. The evaluator then answers ERROR `stdout truncated` (#112 order, #113). The captured bytes are still redacted and capped as before.

**Stderr (my choice; the lead may reverse it).** A stderr capture error also sets the one flag. The wire has no other completeness signal, so this is the only way partial stderr isn't presented as whole. It is fail-closed: the check becomes ERROR rather than a possibly false PASS, and both streams stay as evidence. #113's point is untouched: a stderr cap cut on its own (noisy stderr) still never sets the flag. Only lost output does, and a read failure is lost output, not noise. The cost: for a stderr-only read error, the eval detail reads `stdout truncated`, which names the wrong stream.
The alternative was to report the plugin `runner_unavailable` ("runner lost the plugin", SR L149). I didn't choose it because it discards a stdout that may be complete. In practice both pipes are usually held by the same leftover process, so both errors happen together.

### (2) No path from a cleanup error reaches journald (main.go)

**Defect.** `main.go` logged `err.Error()` of a cleanup failure. That text can hold a `*fs.PathError` naming a file a plugin chose under the private `/tmp`, or a nested cgroup a plugin created (`sweep.go` "list cgroup", "read cgroup.procs", "remove cgroup"). Either would put plugin-controlled text in journald (TS §5.3, §8.4).

**Change.** A new function `pathless(err) string` (main.go L109-126; this revision also adds the `errors` and `io/fs` imports) gives the `Op` and `syscall.Errno` of the first `*fs.PathError` in the error tree. If that PathError holds no errno, it gives just the `Op`. With no PathError, it gives the first errno, which also covers an `*os.LinkError`. Otherwise it gives the fixed words `no errno`. It never returns `err.Error()` or a `Path`. `errors.As` walks `errors.Join` trees. `Op` is a literal set by package `os`, and `Errno.Error()` comes from a fixed table.

It's used at three sites:
- the start-up `Sweep` refusal (L66-69, still logged as `start-up refused`);
- `Serve`'s error (L88): the executor's cleanup error, or an accept error;
- the final `Sweep` (L94).

`refuse()` stays on `err.Error()` for `Harden`, `CheckStartup`, `LookupUID`, `FromSystemd` and `Open`. Their texts are fixed words plus the runner's own paths (its own cgroup, `supervisor`, the socket). Its comment now says so and points sweep errors to `pathless`.

**Other cleanup logs checked.** None needed a change; each logs fixed words with no error:
- `job.go` L170 "plugin cgroup kill failed", L174 "plugin cgroup not empty, left to the sweep" and L192 "after-job cleanup failed" (the error is returned, not logged);
- `serve.go` L140 "job ended, cleanup failed", with `job_id` only.

### Gates (from `agent/`)

- `gofmt -l .`: nothing.
- `go vet ./...` and `GOOS=linux go vet ./...`: rc 0.
- `golangci-lint run ./...` on Windows: 0 issues.
- `GOOS=linux golangci-lint run ./...`: 1 issue, outside my files. gosec G115 at `internal/runner/serve_linux_test.go:177` (`uint32(len(body))`), in a test file changed at 13:45 today. My earlier r1 run had 0 issues. Passed on to tester-m10c.
- `GOOS=linux golangci-lint run --tests=false ./...`: 0 issues, no `nolint`.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- `go mod verify`: all modules verified.
- Not run: the Linux rows below (tester).

### Rows for the tester

1. **A capture error mid-stream gives `truncated` true.**
   - *Job level, delegated as `bitscan-runner`:* a plugin `(echo $BASHPID > <base>/supervisor/cgroup.procs 2>/dev/null || echo $$ > <base>/supervisor/cgroup.procs; sleep 30) & printf ok` holds stdout from outside `p-<n>`. Use `sh -c 'echo $$ > …; exec sleep 30' &` if `/bin/sh` has no `$BASHPID`. After `captureGrace` the read ends are closed and Capture errors. Expect `truncated` true, stdout `ok`, and the leftover gone after the sweep.
   - *Unit, in package `runner`:* a fake `Spawn` returns a `Spawned` whose `Stdout` is an `*os.File` that errors on read (for example a directory opened with `os.Open`, which gives EISDIR), with a real short-lived `proc`. Expect `truncated` true.
   - *Stderr variant:* only stderr is held or erroring. Expect `truncated` true too (my choice above).
   - *Plant:* restore `out, _ = Capture(...)`. The rows must go red.
2. **A cleanup error on a plugin-named file logs no part of that name (canary grep).**
   - *Unit, in package `main` (`cmd/bitscan-runner`):* `pathless(fmt.Errorf("runner: remove temp dir: %w", &fs.PathError{Op: "unlinkat", Path: "/tmp/CANARY-x/f", Err: syscall.EACCES}))` gives `unlinkat: permission denied`. Also wrap it in `errors.Join` with a second error, use an `*os.LinkError`, and use a bare `errors.New`. No output contains `CANARY`.
   - *End to end:* `TmpDirs` holds a root-owned subdirectory `CANARY-…` with a file inside that `bitscan-runner` cannot remove, or a plugin-created nested cgroup named `CANARY-…` that the sweep can't remove. The runner exits 1, and grepping its stderr/journal for `CANARY` finds nothing. The reason holds an op and an errno.
   - *Plant:* `pathless` returns `err.Error()`. The rows must go red.
