# TASK-089 IMPL: TLS configuration

REQ-094. TS §3.2 Transport (L194), §2.2 (L111), §8.1 (L1247), §8.3 Security (L1283); #79 (agreed 2026-10-24); plan `work/plans/TASK-093.md`, section "TLS". **Two approvals (TS §8.2, agent).**

No tests were run (that is the tester's job). I ran a throwaway TLS matrix in a temporary copy outside the tree; it is deleted (results below).

## Files

| File | What |
| --- | --- |
| `agent/internal/agent/transport/tls.go` (new, about 50 non-comment lines) | `NewTLSConfig(caFile, pinHex, serverName string) (*tls.Config, error)` and `ErrPinMismatch`. |

No other file changed.

## Behaviour

- **Version:** `MinVersion: tls.VersionTLS12`. `MaxVersion` and the cipher suites are left at Go's defaults, which prefer TLS 1.3.
- **Verification is never skipped:** there is no `InsecureSkipVerify` (G8 forbids it) and no custom `VerifyPeerCertificate`. Go always verifies the chain and the host name.
- **Trust store:** `caFile == ""` leaves `RootCAs` nil, so the system store is used. Otherwise the pool holds only the PEM certificates in that file ("that CA only", #79), and the system store is not consulted. An unreadable file or one with no PEM certificate is an error.
- **Pin (#79):** `pinHex` is 64 hex characters in either case, otherwise an error. When it is set, `VerifyConnection` (which Go runs after the normal chain and host-name checks, on full and resumed handshakes) compares the SHA-256 of `PeerCertificates[0].RawSubjectPublicKeyInfo` (the leaf only) with the pin in constant time. A mismatch, or no peer certificate, fails the handshake with `ErrPinMismatch` before any request is sent. The pin is in addition to verification, never instead of it.
- **No client certificate:** `Certificates` and `GetClientCertificate` are unset, so the client sends none even when the server asks.
- **`serverName`:** passed through. When empty, `net/http` uses the URL's host.
- **Errors** are fixed words, or wrap the `os` error, which names only the `ca_file` path. The pin value is never echoed.

The caller (TASK-093) passes `config.CAFile` and `config.ManagerSPKISHA256`. `config.Load` has already refused a missing or unreadable `ca_file` at start-up (TASK-087).

## Scratch TLS matrix (evidence, not a test)

Setup: `httptest` TLS servers, a test CA in `ca_file`, ECDSA P-256 leaves, and a server that requests a client certificate.

| Case | Result |
| --- | --- |
| Trusted chain, no pin | OK, TLS 1.3, no client certificate presented |
| Right pin (upper-case hex) | OK |
| Wrong pin | Refused: `ErrPinMismatch` |
| Pin of the CA's key instead of the leaf's (CHK-M4-323) | Refused: `ErrPinMismatch` |
| Leaf from another CA (not in `ca_file`) | Refused: unknown authority |
| Wrong host name | Refused: the certificate does not match |
| Expired leaf | Refused: expired |
| Server offering at most TLS 1.1 | Refused: protocol version not supported |
| Server offering at most TLS 1.2 | OK, TLS 1.2 |
| Missing `ca_file`, junk `ca_file`, pin `abc` | Each is a configuration error |

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l` on my packages: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet` and `go build`: clean.
- `GOOS=linux golangci-lint run` on cmd, config, state and transport: `0 issues`.
- There is no `InsecureSkipVerify` and no `//nolint`.

## For the tester (TP-M4-04, CHK-M4-321 to 326)

- Test through a real `http.Transport{TLSClientConfig: cfg}` against `httptest` servers in `_test.go` files (the lint allows listeners there).
- To prove "refused before any request body is sent", count requests in the server handler: the handler is never reached on a refused handshake.
- The 3xx, proxy and header checks belong to TASK-093.
