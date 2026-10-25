# TASK-098 IMPL: enrolment and the start-up decision

REQ-096. TS §3.2 steps 2–5 and 8 (L182–L188, L191), §3.1 (L162, L172), §6.5 Enrol (L1161); #76, #81 (agreed 2026-10-24); plan `work/plans/TASK-099.md`, section "Enrolment". **Two approvals (TS §8.2, agent).** Depends on TASK-086 (wire), TASK-088 (state), TASK-090 (back-off), TASK-093 (client) and TASK-094 (`inventory.ReadOSRelease`, exported by impl-agent-2 for this task).

No tests were run (that is the tester's job).

## Files

| File | What |
| --- | --- |
| `agent/internal/agent/enrol/enrol.go` (new, about 160 non-comment lines) | `ReadMachineID(path)`, `Enroller`, `(*Enroller).Start(ctx)`, `Result`, `ErrStop`, `ErrNoCredentials`, the `Doer` and `Store` interfaces, and the constants `MachineIDPath`, `OSReleasePath`. |

No other file changed. It calls `inventory.ReadOSRelease(path)` from `agent/internal/inventory/osinfo.go` (TASK-094, impl-agent-2's file), unchanged.

## API

```go
func ReadMachineID(path string) (wire.MachineID, error)

type Enroller struct {
	Client        Doer              // *transport.Client in production
	Store         Store             // *state.Store in production
	MachineID     wire.MachineID    // from ReadMachineID
	AgentVersion  string
	Clock         schedule.Clock    // nil: schedule.RealClock{}
	Backoff       *schedule.Backoff // nil: schedule.NewBackoff(schedule.CryptoSource{})
	Hostname      func() (string, error) // nil: os.Hostname
	OSReleasePath string            // "": /etc/os-release
}
func (e *Enroller) Start(ctx context.Context) (Result, error)
type Result struct { AgentID wire.UUID; Token state.Token; Status wire.EnrolStatus }
```

`main` (TASK-106) reads the machine-id first, because `transport.NewClient` needs it, then builds the client and calls `Start`.

## Behaviour

- **Machine-id (REQ-096 (4)):** exactly 32 lowercase hex characters, optionally followed by one `\n`. Anything else is refused before any call: 31 or 33 characters, uppercase, a hyphenated UUID, empty, trailing spaces, two newlines, or a missing file. At most 64 bytes are read. The error texts are fixed (`start-up: /etc/machine-id: ...`) and name the production path even when a test path is injected.
- **Start-up decision (#81 (c)):**
  - If `enroll.token` exists, the host enrols. This also applies when a `token` exists, which is how re-enrolment works; the answer replaces `agent_id`, `token` and `token.json`.
  - If only `token` exists, `Start` returns the stored token and `agent_id` (`Status` empty) and makes no call. A `token` without `agent_id` is an error.
  - If neither file exists, `Start` returns `ErrNoCredentials` before any call: "start-up: neither token nor enroll.token exists in the state directory; the host must be enrolled".
  - An `enroll.token` that is empty or unreadable is a start-up error (from `state`), not a fallback to `token`.
- **Enrolment token shape:** `^bse_[A-Za-z0-9_-]{43}$` (TS §6.2: 256 bits, base64url, with the prefix), checked before any call. Without the check, a value with a control character could never become a valid header, and its transport error would be retried for ever. This is a local input check of my own choice; the spec gives the format but not this check. **Reviewer:** confirm.
- **Request:** the six keys of `wire.EnrolRequest`. `hostname` comes from `os.Hostname()`. `os_id`, `os_version_id` and `os_pretty_name` come from `inventory.ReadOSRelease`, and are `null` when the file is unreadable, the key is absent or the value is outside the bounds. The body goes through `wire.Encode`, so an empty `AgentVersion` or host name is refused locally. It carries `Authorization: Bearer <bse_>` and no machine-id header (transport, TASK-093).
- **Answers** (classes from `transport.Classify`):
  - **2xx:** the body is decoded strictly as `EnrolResponse`. A `bse_` or malformed `agent_token`, an extra or missing key, a naive time or another `status` is refused with nothing written and `enroll.token` kept. Otherwise `SaveEnrolment` writes `agent_id` (lowercase), `token` and `token.json`, then `DeleteEnrolToken` runs. A crash between the two leaves both files, so the next start enrols again (#76). `enrolled` and `awaiting_approval` both return a `Result`; with `awaiting_approval` the heartbeats then wait on 403 `pending_approval` (TASK-101).
  - **401 (any type):** `ErrStop`, with the exact text "enrolment refused; the host needs a new enrolment token". `enroll.token` is kept and nothing is written. The caller logs it once and stays up idle (#81 (a)).
  - **429, 5xx, network errors and 403 `pending_approval`:** sleep `Backoff.Next()` on the injected clock (10, 20, 40 … 300 s ± 10 %), then resend the **same** token and body bytes (#76). `Retry-After` is not used: TS §3.3 L226 gives the back-off. A held re-enrolment after a lost answer is a normal 200 `awaiting_approval`.
  - **Anything else (3xx, 400, 403 other, 404, 409, 413, 422, an oversized answer):** an error with no retry: "enrol: the manager refused the request with status N". `enroll.token` is kept. The problem `type` is not put in the text.
  - **`ctx` cancelled:** returns at once from the back-off sleep, and from a call in flight through `transport`.
- **No logging and no secrets:** the package writes nothing to logs. No error text contains a token, a body or a header value; state and wire errors name only files and JSON paths.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l .`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/agent/enrol/`: clean.
- `GOOS=linux golangci-lint run ./internal/agent/enrol/...`: `0 issues`.

## For the tester (TP-M4-13, CHK-M4-140 to 148)

- Fake manager: a fake `Doer`, or `httptest.NewTLSServer` through the real `transport.Client`. A fake `schedule.Clock` whose `After` fires at once and records `d` shows the back-off delays. A `schedule.Backoff` with a fixed `Source` (0.5) gives exactly 10, 20, 40 s.
- Use `state.Open(tmpDir)` as the `Store` (its crash hook covers CHK-M4-147), or a fake `Store`.
- Inject `OSReleasePath` and `Hostname`. Pass the machine-id through `ReadMachineID(tmpFile)`.
- `ReadMachineID` opens the file without a type check, so a FIFO at the path would block. `/etc/machine-id` is root-owned, and CHK-M4-144 lists no FIFO. Tell me if you want the `config` stat-first treatment here too.
