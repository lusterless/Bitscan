# TASK-215 IMPL: cgroup v2 supervisor, plugin cgroups and the sweep

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-238, REQ-240 (cgroup part), REQ-237 (delegation part). Spec: TS §3 L152, §3.5 L250, §3.7 L284, L322–L323, L365, §8.1 L1245. Open items applied: #136 (a), #137, #138. Plan: `work/plans/TASK-215.md` §2 and §4. Depends on TASK-211 (reported). Size split per the lead's decision "TASK-215 split per the plan's contingency" (2026-10-30): the sweep is in its own file, under the same task id.

## Files

| File | Lines | Code lines | Content |
| --- | --- | --- | --- |
| `agent/internal/runner/cgroup.go` (new, portable) | 237 | 181 | `CgroupFS`, `RootFS`, `CgroupDeps`, `Cgroups`, `NewCgroups`, `Setup`, `Plugin` with `NewPlugin`, `StartIn`, `Kill`, `WaitEmpty`, `Remove`; `parseSelfCgroup`, `ensureSupervisor` |
| `agent/internal/runner/sweep.go` (new, portable) | 136 | 114 | `Sweep` and its helpers |
| `agent/internal/runner/cgroup_linux.go` (new) | 69 | 54 | `Open` and the pidfd `killPid` |

Total 349 code lines against the estimate of 190. Without the sweep, TASK-215 is 235 lines. The extra over 200 is the `CgroupFS` seam with its `os.Root` adapter and `CgroupDeps`, which plan §2 asks for so that the fake-tree tests run anywhere. The lead accepted this split.

This is the first importer of `golang.org/x/sys/unix` (PD-41), so `go.mod`'s direct requirement is now used. `go.mod` and `go.sum` are unchanged.

## Interface (frozen once W2 passes)

```go
type CgroupFS interface {
    Mkdir(name string) error; WriteFile(name string, data []byte) error
    ReadFile(name string) ([]byte, error); Remove(name string) error
    ReadDir(name string) ([]fs.DirEntry, error)
}
func RootFS(r *os.Root) CgroupFS
type CgroupDeps struct {
    FS CgroupFS; Base string; Self int
    SelfCgroup func() ([]byte, error)
    KillPid func(pid int, still func() bool) error   // the kill seam
    Log *slog.Logger
}
func NewCgroups(d CgroupDeps) *Cgroups
func (c *Cgroups) Setup() error                       // cgroup.kill present, mkdir supervisor, move in
func (c *Cgroups) NewPlugin() (*Plugin, error)        // mkdir p-<n>
func (p *Plugin) StartIn(start func() error) error    // the hop, under the spawn lock
func (p *Plugin) Kill() error                         // ensureSupervisor, then "1" > p-<n>/cgroup.kill
func (p *Plugin) WaitEmpty(ctx context.Context) error // cgroup.events "populated 0", at most 5 s
func (p *Plugin) Remove() error                       // rmdir p-<n>
func (c *Cgroups) Sweep(ctx context.Context) error    // sweep.go
func Open(log *slog.Logger) (*Cgroups, error)         // linux: /proc/self/cgroup, os.OpenRoot, Setup
```

Changes from plan §2:
- `Open` doesn't sweep; the caller does. **TASK-228 calls `Open` (which runs `Setup`), then `Sweep`** (the start-up sweep), per the lead.
- `EnsureSupervisor` is unexported. `Kill`, `StartIn` and every sweep pass call it, under the lock.
- `CgroupDeps` holds the seams: the fs, the own path, the pid, the `/proc/self/cgroup` reader and the pid kill. With these, a fake tree that simulates the kernel can test every rule without Linux.

## How each acceptance point is met

- **Own cgroup** (REQ-238): `parseSelfCgroup` accepts exactly one `0::/<path>` line (a hybrid or v1 layout is refused). `Open` opens `/sys/fs/cgroup/<path>` with `os.OpenRoot`. That handle is close-on-exec and kept for the process lifetime. Every path is relative to it, so `..` and symlinks can't leave the subtree.
- **Setup** (#137): refuses when `cgroup.kill` isn't listed in the own directory. That's a `ReadDir` check, because the file is write-only and a read would fail. It also refuses when `supervisor` can't be made (EEXIST is fine). It writes the own pid to `supervisor/cgroup.procs` and re-reads `/proc/self/cgroup` to check it arrived. Any error means the runner refuses to start.
- **Plugin cgroups**: names are `p-<n>`, from a counter, never from a job. `StartIn`, under the spawn lock:
  1. writes the own pid to `p-<n>/cgroup.procs`;
  2. **checks through `/proc/self/cgroup` that the runner is really in `p-<n>`** (fail closed if a plugin moved it in between);
  3. calls `start()`;
  4. always moves back with `ensureSupervisor`.

  An error after a successful `start` leaves the child in `p-<n>`. The caller kills it and ends the job (#136 (f)).
- **Kill, WaitEmpty, Remove**: `Kill` first ensures the runner is in `supervisor` (#138 (b)), then writes `1` to `cgroup.kill`. `WaitEmpty` polls `cgroup.events` every 10 ms until `populated 0`, at most 5 s, honouring the caller's `ctx`. Pass a context that outlives a cancelled job.
- **Sweep** (`sweep.go`, REQ-240, #138 (a)), under the lock with a 5 s overall bound. Passes repeat, 10 ms apart, until one finds nothing. Each pass:
  1. `ensureSupervisor`, which errors if the runner can't get back.
  2. For the subtree root **and** `supervisor`, the two cgroups holding the runner or its ancestor, which can't be killed whole: SIGKILL every listed pid other than its own through the `KillPid` seam. Linux `killPid` calls `pidfd_open` first, then `still()` re-reads that cgroup's `cgroup.procs` for the pid, then `pidfd_send_signal`, so a recycled pid is never hit.
  3. Every child cgroup of the root except `supervisor`, and **every** child of `supervisor` (a nested `supervisor/supervisor` included): `cgroup.kill` (after `ensureSupervisor`), wait empty, then rmdir the whole subtree, children first.

  A pass that killed or removed anything makes another pass run. After 5 s the sweep returns an error, and the runner must exit, so systemd kills the service cgroup. Only plain directories are walked: symlinks and names that are empty, `.`, `..` or contain `/` or `\` are never followed.

**Wider than plan §4 (accepted by the lead, TS §3.7 L284):** the plan pid-kills only in `supervisor`. Under `Delegate=yes`, a plugin can write itself into the service cgroup's root `cgroup.procs` and would survive that version, so the sweep also pid-kills strays in the root.

Accepted residual (#138 (c)): a plugin can move the runner between our check and the write that follows. The worst case is a runner restart, never a surviving plugin.

Logs: none here. Errors carry fixed words and wrapped system errors only.

## Gates (from `agent/`)

- `gofmt -l .` on non-test files: nothing.
- `go vet` and `golangci-lint run ./internal/runner/...`, both on Windows and `GOOS=linux`: clean, 0 issues in non-test files.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK. `go mod verify`: OK.
- A fake-tree smoke ran in a throwaway copy under `/tmp`, on Windows, with a fake fs that simulates the kernel (pid locations, `cgroup.kill` of a subtree, `populated`). It covered:
  - Setup with the runner in `supervisor`;
  - the operation log REQ-238 (1) expects: `mkdir supervisor`, `write supervisor/cgroup.procs <pid>`, `mkdir p-1`, `write p-1/cgroup.procs <pid>`, back to supervisor, `write p-1/cgroup.kill 1`, `rmdir p-1`;
  - the child "born" in `p-1`;
  - a plugin that moved the runner into `p-1` before `Kill` (the runner was moved back, not killed);
  - a sweep of strays in `supervisor`, in the root, in `supervisor/x/y`, in `q/r` and in `supervisor/supervisor`: all killed, only `supervisor` left;
  - a hybrid `/proc/self/cgroup` refused.

  Symlink creation needs a privilege on Windows, so the symlink row is for WSL.

## For the tester (tester-m10, TP-M10-08)

The fake-tree parts (`cgroup.go`, `sweep.go`) are portable. Give `CgroupDeps` a fake `FS`, `SelfCgroup` and `KillPid`. The delegated parts run under `systemd-run -p Delegate=yes` (WSL with cgroup2, or CI).

Mutation rows, by file:

| CHK | File | Plant | Runs in |
| --- | --- | --- | --- |
| -338 | `sweep.go` | Drop the `killPids` call: a plugin moved into `supervisor` survives | Fake tree and delegated (S, VM) |
| -339 | `sweep.go` | Skip `supervisor`'s children (the `dir == "."` guard widened to every dir) | Fake tree and delegated (S, VM) |
| -336 (G72 half) | `cgroup.go` | `StartIn` skips the write to `p-<n>/cgroup.procs`: the child is born in `supervisor` | Fake tree and delegated |
| -337 (G72 half) | `cgroup.go` | `Kill` writes nothing | Delegated (TASK-224 row) |

Extra rows worth planting:
- `sweep.go`: drop the root (`"."`) from the pid-kill list. A plugin in the service cgroup root survives.
- `sweep.go`: one pass only. A stray that moves between cgroups during a pass survives.
- `cgroup.go`: drop the post-hop `here()` check in `StartIn`.
- `cgroup.go`: drop `ensureSupervisor` in `Kill`. The runner kills itself when a plugin moved it into `p-<n>`.

TASK-228 rows: `Open` then `Sweep` at start-up; a sweep error makes the runner exit.
