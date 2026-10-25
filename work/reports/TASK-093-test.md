# TASK-093 TEST: HTTP client and response classes
**Verdict: PASS.** REQ-094, REQ-095; TP-M4-08, CHK-M4-080 to -089; mutation rows CHK-M4-327, -328, -329, -336, -337. Full rigour (agent).
Commands: `go test -count=1 ./internal/agent/transport/` (root) and `CGO_ENABLED=1 go test -race`; `tester3_m4_plants.py t093` (package timeout 600 s).
Counts: package 56/56 passed, -race 56/56. After my test fix: TestClientOwnTimeLimit 1/1 and the control 56/56. Plants 24/24 red.

| Criterion | Evidence |
| --- | --- |
| Every request carries exactly the required headers (bearer on all; machine-id on the five bsa_ routes, not on enrol; Content-Type only with a body; Content-Encoding only on inventory) | CHK-M4-080; 329, machine-id-on-enrol, gzip-missing and Cookie plants red |
| A 3xx is not followed; proxy variables ignored (#75) | CHK-M4-081, -082; 327, 328 and 3xx-Success plants red |
| An oversized body is refused early (32 MiB cap; Content-Length checked before reading; chunked read stops at cap + 1) | CHK-M4-083; no-LimitReader, Content-Length-unchecked and off-by-one plants red |
| Class table over every contract status and type: drop, stop, wait, retry | CHK-M4-085; 336, 337, 401-one-type, 429-Drop, 403-any-type, Retry-After-ignored and problem-not-decoded plants red |
| Time limits and caller context (60 s own limit, cancel < 200 ms) | CHK-M4-084, -084-r1; call-timeout and context plants red |
| No token or body in errors or %v | CHK-M4-086; two plants red |
| Token per call; ids validated and lowercased; https base only | CHK-M4-087..089; ids-unchecked, ids-not-lowercased and http-base plants red |

REQ-094 (1), (2) and (6) (the TLS half) were proven in TASK-089 TEST (PASS); (3) to (5) are here. REQ-095 (1) is here; (2) to (5) are loop-side (TASK-090, 101, 103).
This round's test change: TestClientOwnTimeLimit bounds its own wait at 90 s, so the no-own-limit plant fails for its own reason.
Rows: CHK-M4-080..089, CHK-M4-080..089-mut (the partial row is replaced by the full one), CHK-M4-084-r1.

## Revision 1 (Retry-After overflow-safe, clamped to 24 h; lead ruling 2026-10-25): PASS
`transport.RetryAfter` parses delta-seconds as uint64. Above 86,400 s, including values too large for uint64, it gives exactly 24 h. Zero, negative, "+5", HTTP-date and unparsable values give 0. TestClientAnswers gained 10 rows; TestRotationRefusals gained 4 subtests in which the huge value really reaches the rotator. Counts: the two tests 13/13; transport control 56/56; token control 42/42; 7 plants red (4 transport, 3 token), among them the clamp removal, where 2^63 rotates at once. Rows CHK-M4-085-r1, CHK-M4-085-r1-mut.
