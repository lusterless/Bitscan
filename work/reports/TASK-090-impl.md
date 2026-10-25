# TASK-090 IMPL: back-off and jittered intervals

REQ-095, REQ-097, REQ-098. TS §3.3 (L202–L203, L206, L226); #4 (the heartbeat is fixed at 300 s); lead ruling 2026-10-24 (back-off jitter within ±10 % of each nominal step, never above 330 s). **Two approvals (TS §8.2, agent).**

No tests were run (that is the tester's job). I ran a throwaway bounds check outside the tree; it is deleted (results below).

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/agent/schedule/interval.go` (about 50 non-comment lines) | `Clock`, `RealClock`, `Sleep`, `Source`, `CryptoSource`, `HeartbeatInterval`, `PullInterval`, `ClampPull`, and the constants `Heartbeat`, `Jitter`, `PullMin`, `PullMax`. |
| `agent/internal/agent/schedule/backoff.go` (about 25) | `Backoff` (`NewBackoff`, `Next`, `Reset`), `BackoffFirst`, `BackoffCap`. |

## API and behaviour

```go
type Clock interface { Now() time.Time; After(d time.Duration) <-chan time.Time }
func Sleep(ctx context.Context, c Clock, d time.Duration) error // ctx.Err() as soon as ctx is done
type Source interface{ Float64() float64 }                      // uniform [0, 1)
func HeartbeatInterval(src Source) time.Duration                 // 300 s ± 30 s
func PullInterval(seconds int, src Source) time.Duration         // ClampPull(seconds) ± 30 s
func ClampPull(seconds int) int                                  // 60..3600
func NewBackoff(src Source) *Backoff; (*Backoff).Next() time.Duration; (*Backoff).Reset()
```

- **Intervals:** `base − 30 s + u·60 s`, which is uniform in [base − 30 s, base + 30 s). The heartbeat base is always 300 s. The pull base is `job_pull_seconds` clamped to 60–3,600, whether the value comes from `agent.yaml` or from a heartbeat answer. That clamp is REQ-092 (3) and TS §3.3 L206; TASK-101 applies it to the manager's value.
- **Back-off:** the nominal steps are 10, 20, 40, 80, 160 s, then 300 s for every later failure (320 is capped to 300). Each delay is `nominal · (0.9 + 0.2·u)`, so within ±10 %, and the largest possible value is just under 330 s. `Reset()` after a success makes the next delay 10 s ± 10 %. A `Backoff` belongs to one goroutine (one per loop).
- **Clock:** the loops use only the `Clock` they are given. `Sleep` returns `ctx.Err()` (unwrapped, so `errors.Is(err, context.Canceled)` works) as soon as the context is done. Fake clocks for tests live in `_test.go` files: they implement `After` with a channel that the test fires when it advances time.
- **Randomness:** `CryptoSource` uses `crypto/rand` (53 random bits as a float). gosec G404 flags `math/rand` and `//nolint` is banned, so production cannot use a seeded `math/rand` generator. Tests pass their own seeded `Source`. Jitter needs no secrecy.

## Scratch run (evidence, not a test)

- 100,000 `HeartbeatInterval(CryptoSource{})` values: min 4m30.0005s, max 5m29.9994s.
- `Backoff` with u = 0, 0.5 and ≈1: 9/18/36/72/144/270 s, 10/20/40/80/160/300 s and 11/22/44/88/176/330 s, each staying at its last value. After `Reset` the next delay is 9, 10 or 11 s.
- `PullInterval` with u = 0 and ≈1: inputs 0, −5, 59 and 60 give 30–90 s; 300 gives 270–330 s; 3600 and 3601 give 3570–3630 s.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l internal/agent/schedule`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet` and `go build ./...`: clean.
- `GOOS=linux golangci-lint run ./internal/agent/schedule/...`: `0 issues`.

## For the tester (TP-M4-05, CHK-M4-338)

- A 503-driven retry sequence is TASK-093 and TASK-101 territory. Here, test `Backoff` directly: delays grow 10, 20, 40 … s, never exceed 330 s, and restart at 10 s after `Reset`. Also test the interval bounds over 1,000 draws with a seeded `Source`.
- A fake `Source` that returns a constant gives exact values at the edges (u = 0 and u → 1).
