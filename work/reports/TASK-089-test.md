# TASK-089 TEST: TLS configuration
**Verdict: PASS.** REQ-094; TP-M4-04, CHK-M4-040 to -046; mutation rows CHK-M4-321 to -326. Full rigour (agent).
Commands: `go test ./internal/agent/transport/` as root and as bstester; `tester3_m4_plants.py t089`; golangci-lint on the module.
Counts: 38/38 TLS tests as root and as bstester; 17/17 plants red; lint 0 issues.

| Criterion (REQ-094, #79) | Evidence |
| --- | --- |
| TLS 1.2 minimum, 1.3 negotiated | CHK-M4-040 (1.1 and 1.0 servers refused, the control proves 1.1 works), CHK-M4-041; CHK-M4-326 red |
| chain and host name always verified; ca_file replaces the system store | CHK-M4-040, -042, -045; CHK-M4-321, -324 (both forms), -325 red |
| pin = SHA-256 of the leaf SPKI, either case, in addition to verification | CHK-M4-040, -041, -045; CHK-M4-322 (both), -323 (both), pin-replaces-verification and case-sensitive plants red |
| refused before any request byte | every refusal: 0 handler calls, 0 body bytes |
| no client certificate | CHK-M4-044; hook plant red |
| bad ca_file or pin is a configuration error, no pin echoed | CHK-M4-043, -046; fallback, missing-ignored, length and echo plants red |
