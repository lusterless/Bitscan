# TASK-093 IMPL: HTTP client and response classes

REQ-094, REQ-095. TS §3.2 (L189, L194), §3.3 (L224, L226), §6.1, §6.5; #59 (the problem types); #75 (no proxy, no redirects); plan `work/plans/TASK-093.md`, section "Client". **Two approvals (TS §8.2, agent).** Depends on TASK-086 (wire) and TASK-089 (TLS).

No tests were run (that is the tester's job). I ran a throwaway fake manager in a temporary copy outside the tree; it is deleted (results below).

## Files

| File | What |
| --- | --- |
| `agent/internal/agent/transport/client.go` (new, about 175 non-comment lines) | `Op` (6 routes), `Request`, `Response`, `Client`, `NewClient`, `Do`, `MaxResponse`, `ErrTooLarge`. |
| `agent/internal/agent/transport/classify.go` (new, about 55) | `Class` (`Success`, `Drop`, `Stop`, `Wait`, `Retry`), `Classify`, `IsVerifyError`. |

`tls.go` (TASK-089) is unchanged. No other file changed.

## API

```go
func NewClient(managerURL string, tlsCfg *tls.Config, machineID wire.MachineID) (*Client, error)
func (c *Client) Do(ctx context.Context, r Request) (Response, error)
type Request struct { Op Op; Token string; AgentID, JobID wire.UUID; Body []byte; Gzip bool }
type Response struct { Status int; Body []byte; Problem wire.Problem; Class Class; RetryAfter time.Duration }
func Classify(status int, problemType string, netErr error) Class
func IsVerifyError(err error) bool
```

## Behaviour

- **Routes:** `POST …/agent/enroll`, `POST …/{id}/heartbeat`, `GET …/{id}/jobs`, `POST …/{id}/jobs/{job_id}/results`, `PUT …/{id}/inventory[?job_id=]`, `POST …/{id}/token/rotate`, each under `<manager_url>/api/v1/agent/`. A path prefix in `manager_url` is kept (`url.JoinPath`). The ids must pass the wire UUID check and are sent in lowercase. A bad id, or results without a job id, is refused before any call (`Drop`), so no manager value can shape a path.
- **Headers:**
  - Every call sends `Authorization: Bearer <Token>`.
  - Every call except enrol sends `X-Bitscan-Machine-Id`. Enrol sends no machine-id header (REQ-094 (4)).
  - `Content-Type: application/json` is sent only with a body, and `Content-Encoding: gzip` only when `Gzip` is set.
  - `DisableCompression` is on, so there is no `Accept-Encoding`. Go's default `User-Agent` stays, because the spec names none.
  - The caller picks the token, which lets TASK-099's lost-response retry use the old one.
- **No proxy, no redirects (#75):** `Transport.Proxy` is nil, so `HTTPS_PROXY` is ignored. `CheckRedirect` returns `http.ErrUseLastResponse`, so a 3xx comes back as the answer (`Drop`) and is not followed.
- **Limits:** dial 10 s, TLS handshake 10 s, the whole call 60 s (inventory 120 s), using `context.WithTimeout` under the caller's context.
  - Body cap: a `Content-Length` above `MaxResponse` (32 MiB) is refused before reading.
  - A chunked body is read through `LimitReader(cap + 1)` and refused at the cap.
  - Both cases return `ErrTooLarge` with class `Drop`.
- **Problems:** a non-2xx body goes through `wire.DecodeProblem`. A body that is not a problem gives the type `about:blank`. `Retry-After` is parsed as delta-seconds (the manager sends seconds).
- **Classes (TS §3.3 L224 and the plan's table):**

  | Answer | Class |
  | --- | --- |
  | 2xx | `Success` |
  | 401 (any type) | `Stop` |
  | 403 `pending_approval` | `Wait` |
  | 429, 5xx, transport errors | `Retry` |
  | anything else (3xx, 400, 403 other, 404, 409, 413, 422, 418, …) | `Drop` |

  A TLS verification or pin failure is a transport error, so `Retry`. `IsVerifyError` lets the loop log it loudly (it matches `ErrPinMismatch`, `tls.CertificateVerificationError` and the x509 unknown-authority, host-name and invalid-certificate errors).
- **Never logs.** `Request.String()` prints only the route (`transport.Request{heartbeat}`), so `%v` and `%+v` of a request never show the token or the body. Error text names the route and wraps the `net/http` error. That error includes the URL, which holds ids but no secret, and never a header or a body.

## Scratch fake manager (evidence, not a test)

The setup was an `httptest` TLS server, its certificate in `ca_file`, and `HTTPS_PROXY=http://127.0.0.1:1` set in the process.

- Header sets the server saw:
  - enrol: `Authorization, Content-Length, Content-Type, User-Agent` (no machine id);
  - heartbeat, rotate and results: the same plus `X-Bitscan-Machine-Id`;
  - jobs (GET): `Authorization, User-Agent, X-Bitscan-Machine-Id`;
  - inventory: plus `Content-Encoding` and `?job_id=…`.
- An upper-case agent id was lower-cased in the path. The proxy variable was ignored (every call reached the server).
- Answers:

  | Route and answer | Class and result |
  | --- | --- |
  | heartbeat 302 | `drop`, not followed (one request only) |
  | jobs 403 `pending_approval` | `wait`, type parsed |
  | rotate 429 with `Retry-After: 42` | `retry`, `RetryAfter` 42 s |
  | inventory 204 | `success` |
  | results, a 33 MiB chunked 200 | `ErrTooLarge`, `drop` |
  | enrol 401 | `stop` |
  | an agent id of `../x` | refused before any call |

- `Classify` over 200, 204, 301, 400, 401, 403, 404, 409, 413, 422, 429, 500, 503 and 418 gives exactly the table above.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l internal/agent/transport`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet` and `go build ./...`: clean.
- `GOOS=linux golangci-lint run ./internal/agent/transport/...`: `0 issues`. There is no `//nolint`.

## For the tester (TP-M4-08; CHK-M4-327 to 329, 336, 337, 339)

- The fake manager is an `httptest.NewTLSServer`, with its certificate written to a `ca_file` for `NewTLSConfig`.
- CHK-M4-328 (proxy from the environment): set `HTTPS_PROXY` to a dead address and expect the call to succeed.
- CHK-M4-339 (`Authorization` logged): the client has no logger, so the canary sweep belongs to the loops (TASK-101 and later). Here, check that `fmt.Sprintf("%+v", req)` and the error text never contain the token.

## Revision 1 (lead ruling 2026-10-25: Retry-After overflow-safe, clamped to 24 h)

Cause (reviewer nit 2, taken by the lead): `client.go` did `time.Duration(strconv.Atoi(v)) * time.Second`. A value of about 9.2×10⁹ s or more overflows `int64` nanoseconds into a negative or near-zero wait, which could turn into a hot retry loop.

Change:
- `agent/internal/agent/transport/classify.go`: new `MaxRetryAfter = 24 * time.Hour` and `RetryAfter(v string) time.Duration`. It parses with `strconv.ParseUint(v, 10, 64)`. A value above 86,400 s, including one too large for `uint64` (`ErrRange`), gives exactly 24 h. Zero, negative, HTTP-date, empty and other unparsable values give 0, as before. The cap matches the 403 and Drop waits on rotate.
- `agent/internal/agent/transport/client.go`: `Do` sets `out.RetryAfter = RetryAfter(resp.Header.Get("Retry-After"))`. The unused `strconv` import is removed.

Results by value:
- 42 → 42 s, and 3600 → 1 h (unchanged).
- 0, -5, abc, an HTTP-date and empty → 0 (unchanged).
- 86400 and 86401 → 24 h.
- 9223372036854775807, 9223372036854775808 (2^63) and 18446744073709551616 → 24 h. Before, the first wrapped to a near-zero or negative wait, and the other two gave 0.
- A leading `+` is now unparsable (0). It was accepted before; RFC 9110 delay-seconds is digits only.

Callers are unchanged. `token.Rotator` uses `RetryAfter` for the 429 wait. Nothing else reads it, because the loops use the TS §3.3 back-off.

Gates (Windows, Git Bash, from `agent/`): `gofmt -l internal/agent/transport` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/agent/transport/ ./internal/agent/token/` clean; `GOOS=linux golangci-lint run ./internal/agent/transport/...` 0 issues.

For the tester:
- Re-run `TestClientAnswers` (its Retry-After table), adding 86400, 86401, 2^63 − 1, 2^63 and 2^64 → 24 h.
- Rotate's 429 case in `token/rotate_test.go` shares the value, so re-run `TestRotationRefusals` too.
- Plant: replace the clamp with `time.Duration(n) * time.Second`; Retry-After 2^63 must go red.
