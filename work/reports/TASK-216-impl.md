# TASK-216 IMPL: runner hygiene and start-up refusals (`internal/runner/hygiene_linux.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-237. Spec: TS §3 L152, §3.7 L276, L283, L316–L320, §8.1 L1245. Open item applied: #137. Plan: `work/plans/TASK-215.md` §5. Depends on TASK-211 (reported). Uses `parseSelfCgroup` and `readSelfCgroup` from TASK-215 (`cgroup.go`, `cgroup_linux.go`).

## Files

- `agent/internal/runner/hygiene_linux.go` (new, 114 lines, 79 code lines; estimate 110). Linux only, because of the build suffix.

No other file changed.

## Interface

```go
func Harden() error                 // PR_SET_DUMPABLE 0, then PR_GET_DUMPABLE must be 0
type StartupProbe struct {
    Euid func() int
    Status func() ([]byte, error)       // /proc/self/status
    StatfsCgroup func() (int64, error)  // statfs("/sys/fs/cgroup").Type
    SelfCgroup func() ([]byte, error)   // /proc/self/cgroup
}
func SystemProbe() StartupProbe     // the real readers
func CheckStartup(p StartupProbe) error
```

The order in `main` (TASK-228), per plan §5:
1. `Harden`
2. `CheckStartup(SystemProbe())`
3. `sdsock.FromSystemd`
4. `runner.Open`, then `Sweep`
5. serve

## How each acceptance point is met

REQ-237 (1): each failing input refuses with its own line, and nothing else is in the error:

| Check, in order | Error text (after `runner: refusing to start: `) |
| --- | --- |
| `Euid() == 0` | `effective uid is 0` |
| `/proc/self/status` unreadable | `cannot read /proc/self/status` |
| `CapEff`, then `CapBnd`: exactly one `<key>:` line, hex, and no bit other than `1 << CAP_DAC_READ_SEARCH` (`0x4`) | `no readable CapEff line` / `CapEff holds capabilities beyond CAP_DAC_READ_SEARCH` (and the same for `CapBnd`) |
| statfs type ≠ `unix.CGROUP2_SUPER_MAGIC`, or statfs failed | `/sys/fs/cgroup is not cgroup2` |
| `/proc/self/cgroup` unreadable | `cannot read /proc/self/cgroup` |
| not exactly one `0::/…` line | `not on the unified cgroup v2 hierarchy` |

A passing set returns nil: euid ≠ 0, both sets `0000000000000004` or `0000000000000000`, the cgroup2 magic, and one `0::/…` line. An empty set is a subset, so a runner started without the capability passes this check; reads then fail on their own, and that is not this check's concern.

Other points:
- **`Harden`** sets `PR_SET_DUMPABLE` 0 with `unix.Prctl`, then checks `PR_GET_DUMPABLE` returns 0 (fail closed). The acceptance line "on Linux `PR_GET_DUMPABLE` returns 0 after `Harden()`" is that check, and the test can assert it the same way.
- REQ-237 (2) to (4) are host and VM rows (G76/G77).
- The delegation checks (`cgroup.kill`, creating `supervisor`) are `Cgroups.Setup` (TASK-215). The `LISTEN_*` checks are `sdsock` (TASK-217). Making descriptors close-on-exec is also `sdsock` (plan TASK-209 §5).

## Gates (from `agent/`)

- `gofmt -l .` on non-test files: nothing.
- `GOOS=linux go vet ./internal/runner/` and `GOOS=linux golangci-lint run ./internal/runner/...`: clean, 0 issues in non-test files.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- A scratch test (`CheckStartup` on a passing probe) compiled for linux with `GOOS=linux go test -c` in a throwaway copy. It wasn't run: Linux runs are the testers'.

## For the tester (tester-m10, TP-M10-09)

The tests are Linux only (the `_linux.go` file). WSL works without cgroup2, because `CheckStartup` takes injected readers. Only `Harden` touches the real process.

| CHK | Plant | Runs in |
| --- | --- | --- |
| -329 | Remove the `Prctl` call (and the `PR_GET_DUMPABLE` check) | Unit on Linux; VM row reads `/proc/<runner>/mem` (S, VM) |
| -340 | Drop the statfs check, or the `parseSelfCgroup` check | Unit with injected magic or a v1 `/proc/self/cgroup`; VM row is the u2204 v1 boot (S, VM) |
| -385 | Drop the euid check | Unit (S) |
| -386 | Drop the capability loop | Unit, with `CapEff`/`CapBnd` holding `CAP_SYS_ADMIN` (`0x200000`) plus `0x4`; VM row is the planted unit (S, VM) |

Extra rows worth planting:
- A repeated `CapEff` line is refused.
- A missing `CapBnd` line is refused.
- `CapEff` `0000000000000004` with `CapBnd` `000001ffffffffff` (the default full bounding set) is refused on `CapBnd`.
