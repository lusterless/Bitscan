# TASK-221 IMPL: plugin start (`internal/runner/spawn_linux.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-239, REQ-241. Spec: TS §3.5 L249, §3.7 L276, L283, L322–L331, L341–L347. Open items applied: #31, #135 (a), (b), #136. Plan: `work/plans/TASK-215.md` §3. Depends on TASK-211 and TASK-215 (both reported).

## Files

- `agent/internal/runner/spawn_linux.go` (new, 170 lines, 136 code lines; estimate 170). It's Linux only, and it's the only runner file allowed to name `os/exec`, which the TASK-211 lint enforces. G204 is lifted for this file only.

No other file changed.

## Interface

```go
var ErrExec, ErrCgroup error
type Spawned struct {
    Stdout, Stderr *os.File   // read ends of the pipes
    Started time.Time         // runner clock just before the start
    TempDir string
    /* *os.Process */
}
func (s *Spawned) Wait() (syscall.WaitStatus, error)   // reaps the shell; doesn't touch the pipes
func Spawn(p *Plugin, execute string, now func() time.Time) (*Spawned, error)
func RemoveTempDir(dir string) error
```

Changes from plan §3, both forced by the TASK-211 lint and by how pipes close:
- **No `*exec.Cmd` in `Spawned`.** The lint forbids every `os/exec` identifier, methods included, outside this file. So `job.go` calls `Spawned.Wait()`, which uses `os.Process.Wait` and returns the `syscall.WaitStatus` for `ExitCode`.
- **`os.Pipe` pairs passed as `*os.File`, not `StdoutPipe`/`StderrPipe`.** `exec.Cmd.Wait` closes `StdoutPipe` read ends when the shell exits, even while a background child still writes. With `os.Pipe`, the read ends stay open until the executor's `cgroup.kill` makes every writer go away. `Capture` then reaches EOF with everything that was written.

Error classes, needed for #136 (f):
- `ErrExec`: this plugin couldn't start (temp directory, `/dev/null`, pipes, `setpriority`, `ioprio_set`, or `exec` of `/bin/sh` failed). It gets `runner_unavailable`, and the job goes on.
- `ErrCgroup`: `StartIn` failed to enter the plugin cgroup, or to get back to `supervisor`. The job stops. If `Spawned` is also non-nil, the child is running in its cgroup and the caller must `Kill` it.

The start function given to `StartIn` records `cmd.Start`'s error itself and returns nil, so `StartIn`'s error is only ever a cgroup error.

## How each acceptance point is met

| REQ-239 | Where |
| --- | --- |
| (7) argv, environment, directory, stdin | `exec.Cmd{Path: "/bin/sh", Args: ["/bin/sh", "-c", execute], Env: ["PATH=/usr/sbin:/usr/bin:/sbin:/bin"], Dir: <temp>, Stdin: /dev/null (O_RDONLY, close-on-exec)}`. It's a struct literal, never `exec.Command`, so there's no `LookPath`. `SysProcAttr` is unset: no `Pdeathsig`, `Setpgid` or `UseCgroupFD`. No `TMPDIR` (#135 (a)). |
| (1) environment | `Env` exactly the `PATH` line. On Linux, Go adds nothing to a non-nil `Env`. |
| (2) descriptors 0, 1, 2 only | Every Go-opened descriptor is `O_CLOEXEC`, and sdsock (TASK-217) marks the inherited ones. The pipe write ends are dup'd onto 1 and 2 in the child. The parent closes its copies of `/dev/null` and both write ends right after the start. |
| (3) niceness 10, I/O class idle | A fresh goroutine calls `runtime.LockOSThread()` and never unlocks. On that thread it calls `setpriority(PRIO_PROCESS, tid, 10)` and `ioprio_set(IOPRIO_WHO_PROCESS, tid, 3 << 13)`, then `StartIn(cmd.Start)`. The fork happens on that thread, so the child inherits both. The goroutine then ends while still locked, and the runtime discards the thread (#136 (b)). If either call fails, nothing starts (fail closed). |
| (4) fresh empty 0700 `/tmp` directory | `os.MkdirTemp("/tmp", "bitscan-p-")` (mode 0700; the unit's `UMask=0077` too), set as the working directory. `RemoveTempDir` is `os.RemoveAll`, which removes symlinks without following them. |
| Born in its cgroup (TASK-215 acceptance) | `StartIn` hops the runner into `p-<n>` and checks `/proc/self/cgroup` before the fork, so the child's first instruction runs in `p-<n>`. |
| REQ-241 (5) | An exec failure is `ErrExec` (that plugin only). A cgroup failure is `ErrCgroup`, and the executor marks every plugin not yet started `runner_unavailable` (TASK-224). |

**One addition for the reviewer.** `RemoveTempDir` retries after making each directory 0700 again with `unix.Chmod`. A plugin runs as the runner's own uid, so it can `chmod 000` a subdirectory of its temp directory. `CAP_DAC_READ_SEARCH` gives read and search, not write, so `RemoveAll` would then fail and leave files for the next job (REQ-240 (9)). `WalkDir` reports symlinks as non-directories, so only real directories are changed, and all plugin processes are dead by then. `unix.Chmod` is used instead of `os.Chmod` because gosec G302 wants file modes of 0600 or less. A directory needs its x bit to be entered, so 0700 (owner only) is the minimum. The CI step forbids `nolint`, so I made this choice openly rather than suppressing the rule. If the reviewer prefers the plan's plain `os.RemoveAll`, the retry is 8 lines to delete.

Nothing is logged here. `execute` never appears in an error.

## Gates (from `agent/`)

- `gofmt -l internal/runner` on non-test files: nothing.
- `GOOS=linux go vet ./internal/runner/` and `GOOS=linux golangci-lint run ./internal/runner/... ./internal/sdsock/...`: clean, 0 issues in non-test files. G204 is lifted for this file by TASK-211; the one G302 is handled as above.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build` of `internal/runner`, `internal/sdsock`, `internal/redact` and `cmd/bitscan-runner`: OK.
- `go build ./...` currently fails in `internal/agent/loops` (`pull.go:39: undefined: Unavailable`), which is impl-agent-m10b's in-progress TASK-223. `gofmt` fails to parse tester-m10's in-progress `internal/redact/redact_test.go:408`. Neither is mine.
- A scratch test (calls `Spawn`, `Wait`, `ExitCode`, `RemoveTempDir`) compiled for linux in a throwaway copy, and was not run.

## For the tester (tester-m10, TP-M10-15)

These are Linux rows under `systemd-run -p Delegate=yes`. Build `Cgroups` with `runner.Open` inside the delegated unit, and run `Spawn` with probe commands. All the plants below are TASK-221's (G72, G76):

| CHK | Plant | Notes |
| --- | --- | --- |
| -331 | `cmd.Env = os.Environ()` | S, VM |
| -332 | Add `"TMPDIR="+dir`, or change `pathEnv` | |
| -333 | `Stdin: os.Stdin` | VM |
| -334 | Skip `Setpriority` | VM |
| -335 | Skip `ioprio_set` | VM |
| -336 | Call `cmd.Start()` outside `StartIn`: the child is in `supervisor` | S, VM |
| -341 | `RemoveTempDir` does nothing | Together with TASK-224 |

To prove "born in its cgroup", use a probe whose first action is `cat /proc/self/cgroup`, plus REQ-238 (3): `sleep 30 & echo x` puts the child in `p-<n>`.

To check that the start thread's niceness doesn't leak, read the runner's other threads' niceness in `/proc/<runner>/task/*/stat` after a spawn: all must be 0.

## Revision 1 (2026-10-30, reviewer-m10's should-fix; lead's decisions row "TASK-221 r1: confined temp-dir chmod")

**Finding.** In r0, `RemoveTempDir`'s retry called `unix.Chmod(path)`, which is chmod(2) on a path and follows symlinks in every component. Another plugin of the same job, still running in parallel, runs as the same uid and can enter this temp directory. It could swap a subdirectory for a symlink between `WalkDir`'s dirent read and the chmod, and the chmod would then land outside the temp tree.

**Fix.** The retry now opens `os.OpenRoot(dir)`, walks `fs.WalkDir(root.FS(), ".")` and calls `root.Chmod(name, 0o700)` on each directory entry. `os.Root` resolves every component inside the root, so a symlink that points out of the tree is refused, and the chmod can't leave it. `unix.Chmod` and the `path/filepath` import are gone. Two removals stay as they were: the first `os.RemoveAll` and the final one. `RemoveAll` already `Lstat`s and uses `*at` calls.

`fchmodat` with `AT_SYMLINK_NOFOLLOW` is not used: it needs kernel 6.6, and Ubuntu 22.04 runs 5.15.

**Lint.** gosec G302 does not fire on `root.Chmod`, so `.golangci.yml` is unchanged and there is no exclusion or `nolint`.

**Size.** 138 code lines.

**Gates.** gofmt on non-test files, `GOOS=linux go vet`, `GOOS=linux golangci-lint run ./internal/runner/...` and the static linux build of `internal/runner` are all clean.

**For the tester.** Worth a row: a temp directory holding a `chmod 000` subdirectory, plus a symlink to a directory outside the tree. After `RemoveTempDir`, the temp directory is gone and the outside directory's mode is unchanged.

## Revision 2 (2026-11-01, tester-m10c's CHK-M10-128 part 2; lead's decisions row "TASK-221 r2: keep the main OS thread out of Spawn")

Builder: impl-agent-m10r.

**Finding.** Spawn's start goroutine calls `runtime.LockOSThread()`, never unlocks, and lowers its thread to nice 10 and I/O class idle. When a locked goroutine exits, the runtime ends that thread, except when it is the main thread m0. Then `mexit` wedges m0 with `mPark()` instead (Go 1.27.2 `runtime/proc.go`, `mexit`: "This is the main thread. Just wedge it."). In the runner, the start goroutine sometimes ran on m0. After 20 spawns, tid == pid sat parked at nice 10 and I/O idle. No goroutine ran there again, so #136 (b) held, but `ps` and `/proc/<pid>/stat` showed the runner at nice 10. The code comment "the thread ends with this goroutine" was wrong in that case.

**Fix (option (a) of the decisions row).**
- `agent/cmd/bitscan-runner/main.go`: new import `runtime`, and `func init() { runtime.LockOSThread() }` (L31-36 since TASK-224 r2 added two imports; L29-34 when written; with a comment giving the reason). A lock taken in `package main`'s `init` lasts into `main.main`, so the main goroutine holds m0 for the whole process and no other goroutine is ever scheduled on it. Each of Spawn's locked goroutines therefore runs on a thread other than m0, and the runtime ends that thread when the goroutine exits.
- `agent/internal/runner/spawn_linux.go` L111-115: the comment above `runtime.LockOSThread()` now says the thread ends with the goroutine because the goroutine is never on m0, which the runtime parks rather than ends, and because the runner's `init` holds m0. Comment only; no code change in this file.

**Nothing in `main.go` needs main-thread affinity or deadlocks under the lock.** The main goroutine runs `run()` straight through:
- `Harden` (`PR_SET_DUMPABLE`) is a per-process (mm) attribute, so it applies to the whole process whichever thread calls it.
- `CheckStartup`, `LookupUID`, `FromSystemd`, `Open` and `Sweep` are ordinary file and syscall work.
- `signal.NotifyContext` delivers through the runtime's signal goroutine, which doesn't need m0.
- `Serve` blocks the main goroutine, and therefore m0, while the scheduler runs everything else on other threads.

There is no cgo. The only per-thread calls in the runner (`Gettid`, `Setpriority`, `ioprio_set`) are in Spawn's own locked goroutine. Nothing else calls `LockOSThread`.

**Gates (from `agent/`, Windows and `GOOS=linux`):**
- `gofmt -l .`: nothing.
- `go vet ./...` and `GOOS=linux go vet ./...`: rc 0.
- `golangci-lint run ./...` and `GOOS=linux golangci-lint run ./...`: 0 issues each, no `nolint`.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- `go mod verify`: all modules verified.
- Not run: CHK-M10-128 needs Linux, and Linux runs are the tester's.

**For the tester.** `main.go`'s `init` isn't in the `internal/runner` test binary. As the decisions row says, the delegated test binary needs a `TestMain` that calls `runtime.LockOSThread()` (or the same lock in an `init` of a test file) to match production. CHK-M10-128 part 2 stays as written: after N spawns, every runner thread except a live plugin-starting one, m0 included, is at nice 0 and not I/O idle. Plant: remove the lock (the test binary's, and for a check against the built runner, `main.go`'s `init`). The row must then go red with m0 at nice 10.
