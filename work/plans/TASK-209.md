# Plan TASK-209: agent–runner protocol (D1)

Covers TASK-209 (`ag/internal/runner/proto`), and fixes the interfaces that TASK-217 (socket activation and peer check), TASK-218 (agent's runner client), TASK-225 (runner serve loop) and TASK-223 (the agent's failure mapping) build against. REQ-234, REQ-235, REQ-236, REQ-245, REQ-261. Open items #29 (agreed), #130, #131, #132. `ag/` means `agent/`.

## 1. Spec quotes

- TS §3.7 L281: "systemd creates the socket from `bitscan-runner.socket`: `/run/bitscan/runner.sock`, owned `root:bitscan`, mode 0660, in a directory owned by root (0755). Neither the runner nor a plugin can replace it."
- TS §3.7 L282: "The runner accepts connections only from uid `bitscan` (`SO_PEERCRED`), and accepts only whole jobs in the job format; it has no separate 'run this string' call."
- TS §3.7 L283: "The listening socket and every other descriptor the runner holds are close-on-exec, so plugins never inherit them."
- TS §3.7 L285: "The runner re-checks the `agent_id` (read from `/var/lib/bitscan-agent/agent_id`), `pickup_by` and the job id itself. These catch mistakes, not attacks."
- TS §3.5 L249: "The agent passes the whole job to the runner (§3.7) … At most `max_parallel_plugins` run at once."
- TS §3.5 L252: "Captured per plugin: exit code, redacted stdout and stderr, start and end timestamps, timed-out flag, truncated flag. The agent does not judge PASS/FAIL."
- TS §6.5 L1165–L1184: the Job and the Results item (unchanged; the M4 `wire` types).

## 2. Package `ag/internal/runner/proto` (TASK-209)

Pure Go, no Linux-only code, imported by both `cmd/bitscan-agent` (through `runnerclient` and `spool`) and `cmd/bitscan-runner`. It imports only `wire` and the standard library.

```go
package proto

const (
    Version    = 1
    MaxRequest = 32 << 20 // 33,554,432: the agent's pull-answer cap (transport.MaxResponse)
    MaxReply   = 1 << 20  // 1,048,576
    MaxStdout  = 65536    // #116 (a), UTF-8 bytes
    MaxStderr  = 16384
)

// Request is the only message the agent sends (#130 (c)).
type Request struct {
    V                  int      `json:"v"`
    Job                wire.Job `json:"job"`
    MaxParallelPlugins int      `json:"max_parallel_plugins"`
}

type Reason string // the #130 (d) words, each an exported constant
const (
    ReasonBusy Reason = "busy"; ReasonMalformed = "malformed"; ReasonNotCompliance = "not_compliance"
    ReasonBadPlugins = "bad_plugins"; ReasonBadParallel = "bad_parallel"; ReasonBadPatterns = "bad_patterns"
    ReasonAgentIDUnreadable = "agent_id_unreadable"; ReasonForeignAgent = "foreign_agent"
    ReasonPickupPassed = "pickup_passed"; ReasonPickupTooFar = "pickup_too_far"
    ReasonReplayed = "replayed"; ReasonSeenFull = "seen_full"; ReasonInternal = "internal"
)

// Result is a Results item that passed the wire bounds and the byte caps.
// Its only constructors are NewResult and ReadReply, so the spool and the
// sender can hold nothing else (REQ-247).
type Result struct{ item wire.ResultItem }
func NewResult(item wire.ResultItem) (Result, error)
func (r Result) Item() wire.ResultItem // a copy

type Kind string // "accepted", "refused", "result", "done"
type Reply struct {
    Kind   Kind
    Reason Reason // Kind == "refused" only
    Result Result // Kind == "result" only
}

func WriteRequest(w io.Writer, r Request) error
func ReadRequest(r io.Reader) (Request, error)  // ErrFrame, ErrMalformed (wrapped, no input text)
func WriteReply(w io.Writer, rep Reply) error
func ReadReply(r io.Reader) (Reply, error)
func UnavailableResult(plugin wire.UUID, now time.Time) Result // the #131 (b) item
func OverflowMarker(from Result) Result                        // the #140 marker (used by spool)
```

Frame rules (`frame.go`): read 4 bytes; length 0 or over the cap → `ErrFrame` without reading the body; read exactly `length` bytes with `io.ReadFull`; decode with `wire.DecodeStrict` semantics (unknown keys, trailing data refused) into the per-kind struct; then `wire.Validate`.

On the wire the replies are distinct JSON shapes, decoded in two steps (a `{"type": …}` probe, then the strict struct for that type, so each shape refuses unknown keys):
- `{"type":"accepted"}`, `{"type":"done"}`
- `{"type":"refused","reason":"<word>"}` (the word must be one of the constants)
- `{"type":"result","result":<ResultItem>}`

Request validation beyond `wire.Validate`: `v == 1`; `job.kind == "compliance"` (an inventory job is `ErrMalformed`, mapped to `not_compliance` by the serve loop); `max_parallel_plugins` 1–8. Shape rules that need the clock or files (pickup, agent id, seen) are TASK-213's, not the codec's.

`NewResult` checks: `wire.Validate(item)`; `len(item.Stdout) <= MaxStdout` and `len(item.Stderr) <= MaxStderr` (Go strings are bytes; the runner has already made them valid UTF-8, and `NewResult` also refuses invalid UTF-8 so the encoder never expands a byte to U+FFFD); `error` null or one of the two values; when `error` is set, `exit_code` null and both streams empty.

Tests (tester, TP-M10-02): round trips; every refusal in REQ-234 (2), (3); a frame header announcing 32 MiB + 1 is refused after reading 4 bytes (a reader that fails on any further read proves it); an API listing test over `go doc -all` output.

## 3. The exchange (both sides)

```
agent                                   runner
  connect ─────────────────────────────▶ accept (peer uid check, REQ-235)
  Request ─────────────────────────────▶ read within 30 s; else close
                                         checks (TASK-213, fixed order #132 (e))
          ◀───────────────────────────── refused <reason>, close      (end)
          ◀───────────────────────────── accepted
          ◀───────────────────────────── result × N (completion order)
          ◀───────────────────────────── done, close
```

- One connection carries exactly one request. After `refused` or `done` the runner closes; a second frame from the agent is never read (REQ-261: "a second frame").
- Deadlines (#130 (f)): runner read deadline 30 s for the request; runner write deadline 60 s per reply (on expiry: cancel the job, close, sweep). Agent: 30 s from connect to the first reply; then `max(timeout_s) + 30 s` between replies (a plugin ends within its `timeout_s` plus the kill, so with any parallelism a reply arrives at least that often).
- Busy (#130 (g)): while a job runs, the accept loop answers any new connection with `refused busy` at once (no read) and closes it.
- Cancellation (#130 (h)): EOF or an error on the connection cancels the job's context; the executor kills every plugin cgroup and the runner sweeps (REQ-240 (10)).

## 4. Runner serve loop (TASK-225)

```go
package runner

// Executor runs one checked request and emits one Result per plugin.
// TASK-224 implements it; TASK-225 is built and tested against fakes.
type Executor interface {
    Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
}

type Server struct {
    Listener *sdsock.Listener // TASK-217: Accept returns only peer-checked conns
    Checks   *Checks          // TASK-213
    Exec     Executor
    Clock    func() time.Time
    Log      *slog.Logger
}
func (s *Server) Serve(ctx context.Context) error
```

Serve: loop `Accept`; if a job is running, write `refused busy` and close; else handle in a goroutine holding the "running" flag:
1. set read deadline 30 s; `proto.ReadRequest`; on error write `refused malformed` (best effort) and close.
2. `Checks.Check(req, now)` → `(proto.Reason, bool)`; refused → write `refused <reason>`, log `job_id` + reason, close.
3. write `accepted`; derive a job context cancelled by connection close (a reader goroutine that blocks on `Read` and cancels on any return) and by `ctx`.
4. `Exec.Run(jobCtx, req, emit)` where `emit` sets the 60 s write deadline and calls `WriteReply`; an emit error cancels.
5. write `done`; close. The executor's own after-job sweep runs inside `Run` (TASK-224), also on cancel.
Logs: `job_id`, `agent_id`, reason words, counts; never `execute`, patterns or output.

## 5. Socket activation and peer check (TASK-217, `ag/internal/sdsock`)

```go
package sdsock // linux

type Listener struct{ /* *net.UnixListener, expected uid, log */ }
// FromSystemd validates LISTEN_PID == os.Getpid(), LISTEN_FDS == "1", fd 3 is
// an AF_UNIX SOCK_STREAM socket in listening state (SO_ACCEPTCONN), then
// wraps it with net.FileListener and closes the original fd 3; it also marks
// every other inherited fd > 2 close-on-exec (scan of /proc/self/fd).
func FromSystemd(expectUID uint32, log *slog.Logger) (*Listener, error)
// Accept returns the next connection whose SO_PEERCRED uid == expectUID;
// others are closed unread and logged once with their uid.
func (l *Listener) Accept() (*net.UnixConn, error)
func LookupUID(name string) (uint32, error) // os/user pure-Go /etc/passwd lookup
```

Edge cases: `net.FileListener` dups the fd with `O_CLOEXEC`; the original fd 3 has no `O_CLOEXEC` (systemd passes it without), so it is closed right after the dup, and the unit test asserts no fd without `O_CLOEXEC` remains above 2. `LISTEN_FDNAMES` is ignored. Environment variables are not cleared (the plugin environment is built from scratch, REQ-239). The only `net.FileListener` call in non-test code lives in `listen_linux.go` (lint, TASK-211).

## 6. Agent's runner client (TASK-218, `ag/internal/agent/runnerclient`)

```go
package runnerclient

const Socket = "/run/bitscan/runner.sock"

type Failure struct{ Word string } // connect, timeout, broken, protocol, refused_<reason>
func (f *Failure) Error() string

type Client struct {
    Socket string                                              // default Socket
    Dial   func(ctx context.Context, path string) (net.Conn, error) // default net.Dialer unix
    Clock  schedule.Clock
}

// Run sends one request and calls onResult for each result, in the order
// received. It returns nil after "done", a *Failure for every #131 (a) case,
// or ctx.Err() when the agent is stopping (no failure fill then, #131 (d)).
func (c *Client) Run(ctx context.Context, job wire.Job, maxParallel int,
    onResult func(proto.Result) error) error
```

Rules: dial with a 30 s limit; `busy` → wait 2 s on the clock and redial, until 30 s from the first attempt have passed, then `refused_busy`; a `result` whose `plugin_uuid` is not in `job.Plugins`, or repeats one already delivered → `protocol` (the item is not delivered); EOF before `done` → `broken`; any decode error → `protocol`; deadlines per §3 → `timeout`. The client never reads `execute` back and never logs a reply body.

## 7. The agent's failure mapping (TASK-223)

`compliance.Handle(ctx, job)`:
1. `spool.StartJob(job.JobID, uuids, now)` (manifest; start notice pending) and wake the sender.
2. `err := client.Run(ctx, job, run.MaxParallelPlugins(), func(r) { spool.Put(job.JobID, r); sender.Wake() })`.
3. `ctx` cancelled (agent stopping) → return; the manifest stays `finished=false` and becomes `interrupted` at the next start (#131 (d)).
4. `*Failure` → for each plugin without a received result: `spool.Put(job.JobID, proto.UnavailableResult(uuid, now))`; `run.SetLastError("runner_unavailable: " + word)`.
5. `spool.Finish(job.JobID)`; wake the sender. Never resend.

`current_job_id` is set for the duration (existing `SetCurrentJob`). The handler holds the plugin uuids only (from the job in memory); the job value is dropped when `Handle` returns.

## 8. What is deliberately not here

- No second request type, no "ping", no status call: the agent learns runner health only from jobs (#131 (e)).
- No agent-side `SO_PEERCRED` check (#130 (j)).
- No job signing or manifest (owner decision; accepted risk TS §3.7 L285, §8.1).
