# Plan TASK-215: cgroups, plugin start, hygiene and cleanup (D2)

Covers TASK-215 (`cgroup_linux.go`, `cgroup.go`), TASK-216 (`hygiene_linux.go`), TASK-221 (`spawn_linux.go`) and the cleanup half of TASK-224 (`job.go`). REQ-237 to REQ-241. Open items #31, #114, #135, #136, #137, #138. `ag/` means `agent/`; every path below is in `ag/internal/runner/` unless stated.

## 1. Spec quotes

- TS §3 L152: "Hosts must use the unified cgroup v2 hierarchy … on any other setup the runner refuses to start and the agent reports `runner_unavailable`."
- TS §3.5 L249: "… `/bin/sh -c`: `PATH` set to `/usr/sbin:/usr/bin:/sbin:/bin`, empty environment, stdin from `/dev/null`, no inherited file descriptors other than its stdout and stderr pipes, `nice 10`, `ionice -c3`, its own cgroup, its own empty temp directory, and the per-plugin timeout."
- TS §3.5 L250: "When a plugin exits or times out, every process left in its cgroup is killed (`cgroup.kill`) and its temp directory is deleted. After each job the runner also kills any other process in its cgroup subtree except itself. No plugin process outlives its job."
- TS §3.7 L283: "The runner makes itself non-dumpable (`PR_SET_DUMPABLE` 0) … A plugin running as the same user could still signal the runner; that only restarts it (`Restart=always`), and is accepted."
- TS §3.7 L284: "The runner moves itself into a leaf cgroup of its own (`supervisor`) and starts each plugin in a fresh child cgroup. After each job it kills every process in its cgroup subtree except itself, so a plugin that moves itself elsewhere in the subtree is still killed."
- TS §3.7 L322–L323, L365: `Delegate=yes`; "`ProtectControlGroups=` is deliberately not set on the runner: it would make the cgroup tree read-only and stop the runner killing plugin cgroups."
- Unit facts that shape the design: `RestrictNamespaces=yes` (L341), `SystemCallFilter=@system-service` and `~@debug …` (L345–L346), `MemoryMax=256M`, `TasksMax=64` (L355–L356), `PrivateTmp=yes` (L326), `NoExecPaths=/` with `ExecPaths=…` (L328–L329), `UMask=0077` (L331).

## 2. cgroup API (TASK-215)

`cgroup.go` holds the portable types and a small filesystem seam so the fake-tree tests run anywhere; `cgroup_linux.go` holds the real calls.

```go
type CgroupFS interface { // real: an *os.Root opened on the own cgroup dir; fake: a temp dir
    Mkdir(name string) error
    WriteFile(name string, data []byte) error
    ReadFile(name string) ([]byte, error)
    Remove(name string) error
    ReadDir(name string) ([]fs.DirEntry, error)
}

type Cgroups struct {
    fs     CgroupFS
    self   int        // os.Getpid()
    mu     sync.Mutex // the spawn lock (StartIn) and the sweep
    next   uint64
    log    *slog.Logger
}

// Open finds the own cgroup (the single "0::<path>" line of /proc/self/cgroup),
// opens /sys/fs/cgroup/<path> as an os.Root, checks cgroup.kill exists, makes
// "supervisor" (EEXIST is fine), writes the own pid to supervisor/cgroup.procs,
// then runs Sweep once (start-up sweep). Any failure → error (#137, the runner
// refuses to start).
func Open(log *slog.Logger) (*Cgroups, error)

type Plugin struct{ name string; c *Cgroups } // "p-<n>"
func (c *Cgroups) NewPlugin() (*Plugin, error)        // mkdir p-<n>
func (p *Plugin) StartIn(start func() error) error    // the hop (§3)
func (p *Plugin) Kill() error                         // write "1" to p-<n>/cgroup.kill
func (p *Plugin) WaitEmpty(ctx context.Context) error // poll cgroup.events "populated 0", ≤ 5 s
func (p *Plugin) Remove() error                       // rmdir p-<n>
func (c *Cgroups) Sweep(ctx context.Context) error    // §4
func (c *Cgroups) EnsureSupervisor() error            // §4 (b)
```

Names are generated (`p-<n>`); no name from a job ever reaches the filesystem. Every path is relative to the `os.Root`, so `..` and symlinks cannot leave the subtree (REQ-238 (1)).

## 3. Starting a plugin (TASK-221)

```go
type Spawned struct {
    Cmd     *exec.Cmd
    Stdout  io.ReadCloser
    Stderr  io.ReadCloser
    Started time.Time
    TempDir string
}
func Spawn(p *Plugin, execute string, now func() time.Time) (*Spawned, error)
func RemoveTempDir(dir string) error // os.RemoveAll; it never follows symlinks
```

Spawn, in order:
1. `dir, _ := os.MkdirTemp("/tmp", "bitscan-p-")` (0700; `UMask=0077`), #135 (a).
2. Build `exec.Cmd{Path: "/bin/sh", Args: ["/bin/sh", "-c", execute], Env: ["PATH=/usr/sbin:/usr/bin:/sbin:/bin"], Dir: dir, Stdin: devnull}` where `devnull` is `/dev/null` opened `O_RDONLY|O_CLOEXEC`; `StdoutPipe`, `StderrPipe`. `SysProcAttr` sets nothing (no `Pdeathsig`, no `Setpgid`, no `UseCgroupFD`). Never `exec.Command` with a looked-up path.
3. Run on a fresh goroutine that calls `runtime.LockOSThread()` and never unlocks:
   - `unix.Setpriority(unix.PRIO_PROCESS, tid, 10)` and `ioprio_set(IOPRIO_WHO_PROCESS, tid, IOPRIO_CLASS_IDLE << 13)` (raw `unix.Syscall(unix.SYS_IOPRIO_SET, …)`), where `tid = unix.Gettid()`;
   - `p.StartIn(cmd.Start)`;
   - send the result on a channel and return: the goroutine ends locked, so the Go runtime discards the thread and no other goroutine ever runs with niceness 10 (#136 (b)).
4. `StartIn` (in TASK-215) under `c.mu`: write `self` to `p-<n>/cgroup.procs`; call `start()`; write `self` to `supervisor/cgroup.procs` (always, even when `start` failed); return the first error. While the runner sits in `p-<n>` no other spawn and no sweep can run (the lock).

Why not `UseCgroupFD`: Go implements it with `clone3(CLONE_INTO_CGROUP)`, and systemd answers `clone3` with ENOSYS when `RestrictNamespaces=` is set (it cannot inspect `clone3` flags), so it may fail under the verbatim unit. The gate's probe records whether `clone3` works (a fact for the owner); the design does not depend on it.

Why not `Pdeathsig`: Linux delivers it when the *thread* that created the child exits, and step 3 discards that thread at once, so every plugin would be killed immediately. A runner death is covered by systemd killing the whole service cgroup (default `KillMode=control-group`) and by the start-up sweep.

Edge cases:
- `ioprio_set`/`setpriority` are in `@system-service`; if either fails, the plugin is not started (`runner_unavailable`), never started at normal priority (fail closed).
- `TasksMax=64` counts the runner's threads and every plugin process; a fork failure inside a plugin is the plugin's error. The runner's own thread count stays small (one locked thread per spawn, discarded).
- Exec of `/bin/sh` is allowed by `ExecPaths=`; anything a plugin execs in `/tmp` fails (`NoExecPaths=/`), which the sandbox suite proves.

## 4. Cleanup and the sweep (TASK-215 `Sweep`, TASK-224)

Per plugin (TASK-224), after the process exits or at its timeout: `p.Kill()` → `p.WaitEmpty()` → `p.Remove()` → `RemoveTempDir()`. A `WaitEmpty` timeout (a process in uninterruptible sleep) is logged; the cgroup is left for the after-job sweep, and the job's later plugins still run.

`Sweep` (after every job, also on cancel, and at start-up), holding `c.mu`:
1. `EnsureSupervisor()`: read `/proc/self/cgroup`; if the own path is not `…/supervisor`, write `self` to `supervisor/cgroup.procs`; if that fails, return an error and the runner exits (systemd restarts it and kills the cgroup, #138 (b)).
2. Walk the subtree depth-first (children before parents). For every cgroup other than `supervisor` itself: write `cgroup.kill`, `WaitEmpty`, rmdir.
3. For `supervisor` (whose own children were handled in 2): read `cgroup.procs`; for every pid ≠ `self`: `fd := unix.PidfdOpen(pid, 0)`; re-read that the pid is still listed (the pidfd pins the process, so a recycled pid is never signalled); `unix.PidfdSendSignal(fd, SIGKILL, nil, 0)`; close. Repeat until only `self` remains (at most 5 s), then log what is left, if anything.
4. Empty `/tmp` and `/var/tmp` (TASK-224, #135 (c)): `os.ReadDir` and `os.RemoveAll` of each entry, never following symlinks.

Accepted residual (#138 (c)): a plugin runs as `bitscan-runner`, the same uid as the runner, so it can write the runner's pid into another cgroup or write `cgroup.kill` of the cgroup the runner is in. Before every `Kill()` the runner calls `EnsureSupervisor()`; a plugin that wins the race makes the runner kill itself, systemd restarts it, the job ends `runner_unavailable`, and no plugin survives (the service cgroup is killed). This is the same class as the signal TS §3.7 L283 accepts.

## 5. Hygiene and start-up refusals (TASK-216)

```go
// Harden is the first call in main: PR_SET_DUMPABLE 0 (unix.Prctl).
func Harden() error

type StartupProbe struct { // injectable for unit tests
    Euid         func() int
    Status       func() ([]byte, error) // /proc/self/status
    StatfsCgroup func() (int64, error)  // statfs("/sys/fs/cgroup").Type
    SelfCgroup   func() ([]byte, error) // /proc/self/cgroup
}
// CheckStartup refuses per #137 with an error naming the check.
func CheckStartup(p StartupProbe) error
```

Checks: euid ≠ 0; `CapEff` and `CapBnd` (hex in `/proc/self/status`) each a subset of `1 << 2` (`CAP_DAC_READ_SEARCH`); statfs type == `unix.CGROUP2_SUPER_MAGIC`; `/proc/self/cgroup` is exactly one line starting `0::`. The delegation checks are `cgroup.Open`'s (§2). Order in `main` (TASK-228): `Harden` → `CheckStartup` → `sdsock.FromSystemd` (which also marks inherited fds close-on-exec) → `cgroup.Open` (start-up sweep) → serve.

## 6. Executor outline (TASK-224)

```go
type Executor struct {
    CG      *Cgroups
    Spawn   func(*Plugin, string, func() time.Time) (*Spawned, error)
    Now     func() time.Time
    redMu   sync.Mutex // one plugin's redaction at a time (#134 (h))
    Log     *slog.Logger
}
func (e *Executor) Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
```

- Compile the pattern set once (`redact.Compile`, already validated by the checks).
- A semaphore of `req.MaxParallelPlugins`; plugins are started in payload order; each runs in its own goroutine: `NewPlugin` → `Spawn` → capture both pipes (TASK-214) → wait with a timer of `timeout_s` → on timer `Kill()` and mark `timed_out` → `Wait` → `Kill`/`WaitEmpty`/`Remove`/`RemoveTempDir` → under `redMu` build the item (TASK-214) → `emit`.
- A cgroup error (NewPlugin, StartIn) stops starting new plugins; every plugin not started is emitted as `proto.UnavailableResult` (#136 (f)).
- `ctx` cancelled (agent closed the connection, runner stopping): kill every running plugin cgroup, stop starting new ones, emit nothing more.
- Always, before returning: `CG.Sweep` and the `/tmp` emptying.
- Logs: per plugin only `job_id`, `plugin_uuid`, exit code, timed-out and duration.

## 7. Tests and plants this plan expects

TP-M10-08, 09, 15, 17 (Linux, delegated cgroup under `systemd-run -p Delegate=yes`); the sandbox rows of REQ-238 to REQ-240; mutation rows CHK-M10-329 to -343, -385, -386, -391. A probe on the VMs also records, as a fact for the owner, whether `clone3` returns ENOSYS under the verbatim unit.
