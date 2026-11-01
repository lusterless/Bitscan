# TASK-213 IMPL: runner job checks (`internal/runner/checks.go`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-236, REQ-244. Spec: TS §3.3 L212, §3.7 L282, L285, §8.1 L1239. Open items applied: #125 (b), #132, #134 (e). Depends on TASK-209 and TASK-210 (both reported).

## Files

- `agent/internal/runner/checks.go` (new, 161 lines, 132 code lines; estimate 150). It also holds the `runner` package comment.

No other file changed. Portable Go (no build tag), so TP-M10-06 can run on Windows as well as Linux.

## Interface

```go
const AgentIDPath = "/var/lib/bitscan-agent/agent_id"
const MaxSeen = 100000

type Checks struct{ /* agent id path, mutex, seen map */ }
func NewChecks(agentIDPath string) *Checks
// Check: ("", true) when the request may run, else (word, false).
func (c *Checks) Check(req proto.Request, now time.Time) (proto.Reason, bool)
```

This is the signature from plan TASK-209 §4. `Check` doesn't return the compiled `redact.Set`, so the executor (TASK-224) compiles the list again from `req`. That's deterministic, and cheap for 50 patterns.

## How each acceptance point is met

The fixed order of #132 (e), after decode (`proto.ReadRequest`):

| Step | Word | Rule |
| --- | --- | --- |
| kind | `not_compliance` | `job.kind == "compliance"` |
| shape | `bad_plugins` | 1–5,000 plugins; `plugin_uuid`s distinct after lowercasing (so case variants are duplicates); every `timeout_s` 1–600 |
| shape | `bad_parallel` | `max_parallel_plugins` 1–8 |
| patterns | `bad_patterns` | `redact.Compile` refuses: more than 50 entries, a compile failure, or an entry that can match the empty string. An empty or nil list is allowed (REQ-244) |
| `agent_id` | `agent_id_unreadable` / `foreign_agent` | The file is read on **every** call. It must be a regular file, checked by `os.Stat` and again by `f.Stat` after an `O_RDONLY|O_NONBLOCK` open (builder checklist 14: a FIFO can't hang the runner). At most 64 bytes, one trailing LF removed, and the rest must pass `wire.UUID` validation. Comparison ignores case. |
| `pickup_by` | `pickup_passed` / `pickup_too_far` | `now < pickup_by ≤ now + 25 h`; `now` is the only clock |
| seen | `replayed` / `seen_full` | below |

Seen set (#132 (c)):
- In memory only.
- Expired entries (`now ≥ pickup_by + 1 min`) are pruned at the start of each call.
- Every request that reaches `Check` (it has decoded) has its job id recorded, refused or not, unless the set is full.
- An id already present gives `replayed` only when every earlier step passed; otherwise the earlier word wins, which keeps one answer per case. Its expiry is extended to the later of the two `pickup_by + 1 min` values (fail closed: a resend with a later `pickup_by` is remembered for longer).
- At 100,000 ids, a job that passed every earlier step is refused `seen_full` and isn't recorded. Once ids expire, new jobs are accepted again.

REQ-236 rows:
- (1) Every row of the table maps to its word, as above. `pickup_by` exactly now + 25 h is accepted, as are an uppercase job `agent_id` and a fresh id.
- (2) `Checks` starts nothing; the exec counter belongs to the serve-loop test (TASK-225).
- (3) A refused id is recorded, so a corrected resend gets `replayed`.
- (4) Expiry and the 100,000 bound work as above.
- (5) is the host run (G78).

Checked in a throwaway copy under `/tmp`, never in the tree: every REQ-236 (1) row, the replay, a refused id then resent, expiry at `pickup_by` + 1 min, an empty, non-UUID or double-LF file and a missing file, and a full set refusing then recovering after expiry.

Notes:
- `Check` doesn't log. The serve loop (TASK-225) logs `job_id` and the word only.
- `Check` holds its mutex while it reads the file. The runner serves one connection at a time, so there's no contention.
- 0 or 5,001 plugins and `timeout_s` 0 or 601 never reach `Check` over the socket: `proto.ReadRequest` refuses them `malformed` as #60 wire bounds (main's ruling on TASK-209, "keep `malformed` at decode"). `Check` gives `bad_plugins` for a `Request` built in a test.

## Gates (from `agent/`)

- `gofmt -l .`: nothing.
- `go vet ./internal/runner/...` on Windows and `GOOS=linux`: clean.
- `golangci-lint run ./internal/runner/...` on Windows and `GOOS=linux`, with the TASK-211 config: 0 issues.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK.

## For the tester (tester-m10, TP-M10-06)

Mutation rows for this task. All are pure and run locally, in WSL and in CI. The VM part of -325 and -327 is the G76 host run through the driver.

| CHK | Plant |
| --- | --- |
| -324 | Drop the kind step. TASK-209's decode check refuses too, so plant both for G78. |
| -325 | Drop the `EqualFold` comparison (S, VM) |
| -326 | `pickupMax` becomes 26 h, or the too-far branch is removed (S) |
| -327 | Skip the `dup` branch (S, VM) |
| -328 | `!pickup.After(now)` becomes `pickup.Before(now)` (S) |
| -351, -352 | Through `redact.Compile`, the TASK-210 plants (G72 half) |
| -393 | Cache the first `readAgentID` result in `Checks` |

A FIFO at the `agent_id` path must give `agent_id_unreadable` at once, without blocking. The `os.Stat` check catches it before the open; that row is Linux only.
