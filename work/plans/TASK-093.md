# TASK-093 plan: TLS, HTTP client and response classes

Covers TASK-089 (TLS) and TASK-093 (client and classification). REQ-094, REQ-095. Owner: impl-agent. **Two approvals.** Tests: TP-M4-04, TP-M4-08; mutation rows CHK-M4-321 to 329, 336, 337, 339. Blocked on **#79** (pin) and **#75** (proxies, redirects).

## Spec quotes

- TS §3.2 L194: "Agents connect over TLS 1.2+ (TLS 1.3 preferred) and verify the manager's certificate against the system CA store, or `ca_file` for a private CA. For a private manager, set `ca_file` to that CA only, or pin the manager's key with `manager_spki_sha256`. Pinning is optional but recommended … Agents have no certificates of their own, and plain HTTP is refused."
- TS §3.2 L189: "Every later call carries `Authorization: Bearer <agent token>` and the `X-Bitscan-Machine-Id` header."
- TS §3.3 L224: "400, 404, 409, 413 and 422, and 403 other than `pending_approval`, mean the manager will never accept that batch … 401 stops the agent …; 403 `pending_approval` keeps it waiting. Only 429, 5xx and network errors are retried."

## TLS (TASK-089)

```go
func NewTLSConfig(caFile string, spkiPinHex string, serverName string) (*tls.Config, error)
```
- `MinVersion: tls.VersionTLS12`; Go's defaults prefer TLS 1.3 and modern suites; no `Certificates` (no client certificate); never `InsecureSkipVerify` (lint).
- `RootCAs`: `nil` (system store) when `caFile` is empty, otherwise a pool built only from that file (#79 recommendation: `ca_file` replaces the system store, "that CA only").
- Pin (#79): `VerifyConnection` runs after Go's normal chain and host-name verification; it compares the lowercase hex SHA-256 of `cs.PeerCertificates[0].RawSubjectPublicKeyInfo` with the configured pin in constant time. The pin is an addition, never a replacement for verification.

## Client (TASK-093)

```go
type Client struct{ ... } // one http.Client, Transport{Proxy: nil (#75), TLSClientConfig, timeouts}, CheckRedirect -> error (#75)
func (c *Client) Do(ctx context.Context, op Op, tok TokenSource, body []byte, enc Encoding) (Response, error)
type Class int // Success, Drop, Stop, Wait, Retry
func Classify(status int, problemType string, netErr error) Class
```
- Headers: `Authorization: Bearer <bsa_>` and `X-Bitscan-Machine-Id` on every `bsa_` route; enrol sends `Authorization: Bearer <bse_>` and no machine-id header. `Content-Type: application/json`; `Content-Encoding: gzip` on inventory (and optional on results, unused in 0.x).
- Limits: dial 10 s, TLS handshake 10 s, whole request 60 s (inventory upload 120 s); response bodies read through `io.LimitReader` at 32 MiB (a full pull of 10 compliance jobs with 5,000 plugins each fits); larger answers are an error class `Drop` with a fixed log line.
- Classification table (exhaustive test in TP-M4-08):

| Answer | Class |
| --- | --- |
| 2xx | Success |
| 401 any `type` | Stop |
| 403 `pending_approval` | Wait (back-off) |
| 403 other, 400, 404, 409, 413, 422 | Drop (log, `last_error`) |
| 429, 5xx, network error, TLS failure after a successful handshake earlier | Retry (back-off) |
| 3xx | Drop (#75: not followed) |
| TLS verification or pin failure | Retry with back-off and a loud log line (the manager may be fixed; nothing is sent) |
| other | Drop |

- Errors are wrapped with `%w`; a log line names the route, the status and the problem `type`, never a header, a token or a body.
