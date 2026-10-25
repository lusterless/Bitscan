# TASK-089 REVIEW: TLS configuration

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/transport/tls.go` (`work/reports/TASK-089-impl.md`). Sources: TS §3.2 Transport (L194), §2.2, §8.1, §8.3 Security, REQ-094 and #79.

TEST: PASS (`work/reports/TASK-089-test.md`): 38/38 as root and as `bstester`, 17/17 plants red (CHK-M4-321 to -326 among them), and lint 0 issues across the module, tests included. No test sets `InsecureSkipVerify`.

## Checks
1. Spec:
   - TLS 1.2 is the minimum, and Go's defaults prefer 1.3.
   - The chain and host name are always verified: there is no `InsecureSkipVerify` and no `VerifyPeerCertificate` override.
   - With `ca_file` set, only that file's CAs are trusted ("that CA only", #79). The system store is never mixed in.
   - The pin is the SHA-256 of the leaf's DER SPKI, in either case, checked in `VerifyConnection`. That runs after normal verification, on full and resumed handshakes, so the pin adds to verification and never replaces it.
   - A refused handshake sends no request byte (tested: 0 handler calls).
   - There is no client certificate (TS §2.2; invariant "no agent client certificates").
2. Security:
   - The pin is compared in constant time and never echoed. Errors are fixed words, or wrap the `os` error, which names only the `ca_file` path.
   - TLS settings are not weakened anywhere: no cipher-suite overrides, no `MaxVersion`, no renegotiation.
3. Scope: 1 new file, about 50 lines.
4. Tests: the matrix covers version floors, wrong CA, wrong host name, expiry, the pin matched against the CA key instead of the leaf, upper-case pins, a server that asks for a client certificate, and bad `ca_file` and pin values, with a control for each refusal. 17 plants are red.
5. Re-run by the reviewer (Windows): `gofmt` prints nothing, and `GOOS=linux` vet and golangci-lint on `transport` report 0 issues.

## Findings
1. nit, `tls.go:37` (raised by impl-agent in the TASK-087 report). `NewTLSConfig` reads `ca_file` with `os.ReadFile`, which would block on a FIFO. `config.Load` refuses a non-regular `ca_file` first (TASK-087 r1), so only root swapping the file in `/etc/bitscan` between those two calls could trigger it. No change. If `NewTLSConfig` is ever called on its own (for example on a SIGHUP reload, which v1 does not have), reuse `config.readableFile` or open the file with `O_NONBLOCK` first.
