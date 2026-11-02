# TASK-214 IMPL: capture and result building (`internal/runner/capture.go`, `result.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-241, REQ-242. Spec: TS §3.5 L251–L252, §6.5 L1184, §4.5 L593. Open items applied: #113, #114, #134 (b), #136 (e), (f). Plan: `work/plans/TASK-210.md` §4. Depends on TASK-209 and TASK-210 (both reported).

## Files

- `agent/internal/runner/capture.go` (new, 46 lines, 29 code lines): `Capture`, `ExitCode`, `exitCode`.
- `agent/internal/runner/result.go` (new, 52 lines, 39 code lines): `Outcome`, `Build`.

No other file changed. Both files are portable: no build tag and no `os/exec` identifier, per the TASK-211 lint. `syscall.WaitStatus` and its methods exist on Linux and Windows.

## Interface

```go
func Capture(r io.Reader) (redact.Captured, error)
func ExitCode(ws syscall.WaitStatus) int64
func exitCode(signaled bool, status, signal int) int64   // unexported, for tests on Windows
type Outcome struct {
    Plugin wire.UUID; Started, Finished time.Time
    Stdout, Stderr redact.Captured; Exit int64; TimedOut bool
}
func Build(set *redact.Set, o Outcome) proto.Result
```

The plan's "portable build takes (exited, status, signal)" is the unexported `exitCode`. Tests in package `runner` can call it on Windows, where a signalled `WaitStatus` can't be built. `ExitCode` is a one-line wrapper over it.

A plugin the runner could not start gets `proto.UnavailableResult(uuid, now)` directly, from the executor (TASK-224). No second helper was added.

## How each acceptance point is met

| Point | Where |
| --- | --- |
| REQ-241 (1) exit codes | `exitCode`: signalled gives 128 + signal (SIGKILL 137, SIGTERM 143, SIGSEGV 139; a timeout is SIGKILL by `cgroup.kill`, so 137); otherwise the exit status (0, 1, 126, 127, 255 map to themselves). `wait(2)` without `WUNTRACED` reports only an exit or a signal, so no negative code is produced. |
| (2) `started_at ≤ finished_at`, UTC `Z` | `wire.NewTime` encodes UTC with `Z`. If the wall clock stepped back (finished before started), `Build` reports `finished = started`. |
| (4) every item passes `proto.NewResult` | `Build` builds the item only through `NewResult`. If it fails (a bug: bad UUID, over cap), the plugin becomes `proto.UnavailableResult(plugin, finished)`, so no raw or over-cap text is ever sent (CHK-M10-357). |
| Writer of 3 MiB never blocked | `Capture` keeps `redact.ReadLimit` bytes through `io.LimitReader`, then `io.Copy(io.Discard, r)` until EOF. `Overflow` is true only when at least one byte past 1 MiB arrived, so exactly 1 MiB is not overflow. Checked with an `io.Pipe` writer of 3 MiB in a scratch copy: the writer finished, with 1,048,576 bytes kept and `Overflow` true. |
| REQ-242 (6) through the capture path | `Capture` sets `Overflow`, and `Build` passes it to `Apply`, which sets `truncated` for stdout even when redaction shrinks the text. stderr is never `truncated` (#113). |
| Redact before truncate | `Build` calls `set.Apply` on each stream. The order inside `Apply` is TASK-210's. |

Notes:
- `Capture` returns the bytes kept so far together with a read error, wrapped with `%w`. For example, the executor may close the read end after the kill. The bytes are raw and go only to `Build`; the executor decides whether to use them.
- The two streams are read in two goroutines, started before `Wait`. That's the executor's orchestration (TASK-224, plan TASK-210 §4), not part of this file.
- Nothing is logged. Raw buffers are dropped by the caller once `Build` returns (#134 (i)).
- The one-plugin-at-a-time redaction lock (#134 (h)) is held around `Build` by the executor (TASK-224).

## Gates (from `agent/`)

- `gofmt -l .` on non-test files: nothing.
- `go vet ./internal/runner/...` on Windows and `GOOS=linux`: clean.
- `golangci-lint run ./internal/runner/...` on Windows and `GOOS=linux`: 0 issues in non-test files. While I ran it, tester-m10's in-progress `internal/runner/proto/proto_test.go` showed gofmt, G115 and SA1019 (`parser.ParseDir`) findings; those are the tester's file.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.
- Smoke run in a throwaway copy under `/tmp`: the 3 MiB pipe writer, the exact 1 MiB case, the exit-code table, `Build` with over-cap stdout plus a pattern in stderr and invalid UTF-8, the clock step back, and the `NewResult` fallback.

## For the tester (tester-m10, TP-M10-07)

Mutation rows for this task:

| CHK | Plant | Runs in |
| --- | --- | --- |
| -346 | Remove the `io.Copy(io.Discard, r)` drain, or the `LimitReader`. With the drain gone, a 3 MiB pipe writer blocks. | Unit, on any OS |
| -355 | Return `-1` for `signaled` in `exitCode` | Unit, on any OS (call `exitCode`); also through `ExitCode` with `syscall.WaitStatus(9)` on Linux |
| -357 | Return the raw item when `NewResult` fails, e.g. send `string(o.Stdout.Data)`. Plant a `Build` with an invalid plugin UUID or a hand-made over-cap item. | Unit, on any OS |
| -344 | The G72 half: through `Build`, a secret on the 64 KiB boundary | Unit, on any OS |

None of these needs a VM. REQ-241 (3) and (5) are host and executor rows (TASK-224, the sandbox suite).
