# TASK-218 IMPL: runner client (`internal/agent/runnerclient`)

Implementer: impl-agent-m10b, 2026-10-30. REQ-245 (client part), REQ-234. Spec: TS §3.5 L249, §3.7 L281–L282, §3 L152. Open items applied: #130 (f), (g), (j); #131 (a), (c). Plan: `work/plans/TASK-209.md` §3, §6. High risk (TS §8.2 second approval).

## Files

- `agent/internal/agent/runnerclient/client.go` (new, 163 code lines). No other file changed.

It imports `internal/agent/schedule`, `internal/agent/wire`, `internal/runner/proto` and the standard library. It imports no other `internal/runner` package and no `redact`, so REQ-251 (1) holds.

## Interface (frozen once W2 passes)

```go
const Socket = "/run/bitscan/runner.sock"

type Failure struct{ Word string } // connect | timeout | broken | protocol | refused_<reason>
func (f *Failure) Error() string    // "runnerclient: runner unavailable: <word>"

type Client struct {
    Socket string                                                   // "" → Socket
    Dial   func(ctx context.Context, path string) (net.Conn, error) // nil → net.Dialer "unix"
    Clock  schedule.Clock                                           // nil → schedule.RealClock{}
}
func (c *Client) Run(ctx context.Context, job wire.Job, maxParallel int, onResult func(proto.Result) error) error
```

`Run` returns:
- `nil` after `done`;
- a `*Failure` for every #131 (a) case;
- `ctx.Err()` as is when the agent stops, so no failure fill follows (#131 (d));
- or `"runnerclient: result not kept: %w"` wrapping `onResult`'s error, after the connection is closed (the runner then cancels the job).

## Behaviour

- **One request per connection:** `proto.Request{V: 1, Job: job, MaxParallelPlugins: maxParallel}`, written whole by `proto.WriteRequest`. There is no other message. The job is passed as pulled, and nothing is read back from it.
- **Deadlines (#130 (f)), all on the injected `schedule.Clock`, so fake-clock tests drive them.** A watcher goroutine per phase waits on `Clock.After(d)` or `ctx.Done()`, then cancels the dial or sets the connection's deadline into the past. That wakes any blocked read or write at once.
  - Dial: 30 s. A dial error or a dial timeout is `connect`.
  - Connect → first reply: 30 s, including the request write.
  - Between later replies: `max(timeout_s over the job) + 30 s`.
  - A read or write cut by the clock is `timeout`. One cut by `ctx` returns `ctx.Err()`.
- **First reply:**
  - `refused <reason>` → `refused_<reason>`;
  - `accepted` → read results;
  - anything else (`result`, `done`) → `protocol`.
  - A failed request write still reads one reply, because the runner sends `refused busy` without reading the request. A refusal read there wins. Otherwise a failed write is `broken`.
- **Busy (#130 (g)):** `refused_busy` → sleep 2 s on the clock, redial, until another try would start more than 30 s after the first. On the fake clock that is 16 attempts at t = 0, 2, …, 30 s. Then `refused_busy` is returned. Only `busy` is retried.
- **Results:**
  - Each `result` must name a plugin of the job that has no result yet (uuids compared lowercase). Otherwise `protocol`, and the item is **not** delivered (CHK-M10-392).
  - `onResult` is called in the order received.
  - `done` before every plugin has a result is `protocol`. #130 (e) says one result per plugin, then `done`; treating a short run as a protocol error lets TASK-223 fill the missing plugins with `runner_unavailable` instead of leaving them silent. It fails closed; I'm noting it for the reviewer.
- **Read errors → words (#131 (c)):**
  - the connection ending inside a frame (`io.ErrUnexpectedEOF`) → `broken`;
  - a zero or oversize length, or a reply that fails strict decoding or `proto.NewResult` (`ErrFrame`, `ErrMalformed`) → `protocol`;
  - EOF before `done`, or any other connection error → `broken`.
- A request `proto.WriteRequest` refuses before writing (for example `maxParallel` 9) is `protocol`, with nothing sent. TASK-223 passes the clamped value, so this is a guard only.
- No agent-side `SO_PEERCRED` check (#130 (j)).
- No logging at all: the client has no logger, and reply bodies never leave it except through `onResult`.

## Gates (from `agent/`, Windows + Git Bash)

- `gofmt -l internal/agent/runnerclient`: nothing.
- `go vet` and `GOOS=linux go vet` of the package: clean.
- `golangci-lint run ./internal/agent/runnerclient/...` and the `GOOS=linux` run: 0 issues.
- Nolint grep: nothing.

## Smoke run (Windows, throwaway copy outside the repo, fake clock, fake runner on an AF_UNIX socket)

| Case | Result |
| --- | --- |
| Normal: accepted, 2 results in reverse plugin order, done; `maxParallel` 3 seen by the runner | `nil`; results delivered in the order received |
| No socket file | `connect` |
| `refused bad_patterns` | `refused_bad_patterns` |
| EOF after 1 of 2 results | `broken`, 1 delivered |
| Result for a plugin not in the job | `protocol`, nothing delivered |
| The same plugin twice | `protocol`, the second not delivered |
| Header announcing 1 MiB + 1 | `protocol` |
| `done` after 1 of 2 | `protocol` |
| `refused busy` every time (runner reads the request first) | `refused_busy`, 16 attempts, 30 s on the clock |
| No first reply, 30 s fired | `timeout` |
| Accepted then silence, 90 s (60 + 30) fired | `timeout` |
| ctx cancelled mid-job | `context.Canceled`, not a `Failure` |
| `maxParallel` 9 | `protocol`, nothing written |

## For the tester (tester-m10, TP-M10-11)

- **Busy without reading the request, on Windows:** when the fake runner writes `refused busy` and closes *without reading* the request, the Windows AF_UNIX stack resets the connection and discards the buffered reply, so the client sees `broken` after 1 attempt.
  - On Linux, a unix stream socket delivers queued data before the reset error, and the client reads the refusal after a failed write. That is the case the code handles.
  - So run the "busy at once" row on Linux. On Windows, use a fake runner that reads the request before refusing (that variant passes on both).
  - Possibly relevant to TASK-225 (impl-agent-m10): I've told them.
- **M4 static check conflict (PD-45 class):** `loops/pull_test.go` `TestNoOtherJobSourceStatic` (CHK-M4-223, -220) fails on any `internal/agent/**` file containing `runner.sock` or `"unix"`.
  - This package has to contain both: the agent's job under REQ-245 is to connect to `runner.sock`.
  - The check needs rewriting to REQ-245 / REQ-251 under PD-45, for example by allowing `runnerclient/client.go` only.
  - I haven't changed any test.
- Mutation rows: **CHK-M10-392** (a result for a plugin not in the job is spooled). Plant by removing the `!want[id]` check: the foreign-plugin row then calls `onResult`. Red in G73. No VM needed.
