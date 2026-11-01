# TASK-209 REVIEW: agent–runner protocol (`internal/runner/proto`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-234. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-209-impl.md` (r1): `agent/internal/runner/proto/proto.go` (sha256 `cbfef864…`) and `agent/internal/runner/proto/frame.go` (`db691d15…`), both new. 271 code lines in 2 files, against an estimate of 170. The extra is the 13 reason constants, the three strict reply shapes and the I/O error classes TASK-218 needs. Nothing is out of the plan's scope.

TEST: PASS on r1 (`work/reports/TASK-209-test.md`). 108/108 on Windows and on WSL with `-race`, and 12/12 plants red (CHK-M10-323, -324 and ten extras).

Spec read: TS §3.7 L281–L285, §3.5 L249, L252, §6.5 L1165–L1184; #29, #60, #116 (a), #130 (b)–(e), (i), #131 (b), #140; plan TASK-209 §2–§3.

My re-run (Windows, go1.27.2): `go test -count=1 ./internal/runner/proto/` ok. `gofmt -l` is empty. `go vet` is clean for Windows and `GOOS=linux`, and `golangci-lint run` gives 0 issues for both. The file hashes match the test report.

## Checks
1. **Whole jobs only (TS §3.7 L282, security invariants "Never add").** The only request is `Request{V, Job wire.Job, MaxParallelPlugins}`. There's no other message, no ping, and no exported function that takes a command string (CHK-M10-009 lists the API from the AST). `ReadRequest` decodes with `wire.DecodeStrict`, so an unknown key at any depth is refused, `"command"` beside `job` included (CHK-M10-323 is red when the decoder is made lenient). An inventory job gets `ErrNotCompliance` (CHK-M10-324).
2. **Frame bounds (#130 (b)).** `readFrame` refuses a zero or oversize length after reading only the 4-byte header (the `failAfter` reader proves it). The body is read with `io.ReadFull` of exactly `n` bytes, so nothing past one frame is consumed. The 32 MiB request buffer is allocated only for a peer that already passed the uid check, and only one connection is served at a time, so it stays inside `MemoryMax=256M`.
3. **Result caps (#116 (a), REQ-234 (3)).** `checkItem` is shared by `NewResult`, `ReadReply` (through `NewResult`) and `WriteReply`. It checks the wire bounds and the `error` enum, stdout ≤ 65,536 and stderr ≤ 16,384 bytes, valid UTF-8, and that an `error` item has a null exit code and empty streams. `WriteReply` re-checks before sending (#130 (i)), so a zero or hand-built `Result{}` cannot be sent. A maximal item (6× escape) fits in 1 MiB.
4. **No input text in errors (checklist 12).** Every decode error is replaced by a fixed sentinel. `ErrFrame` wraps only `io.ErrUnexpectedEOF` or the transport error. Canary inputs appear in no error (CHK-M10-010).
5. **Error classes for TASK-218.** A clean EOF wraps `io.EOF` (→ `broken`), a short frame is `ErrFrame` (→ `protocol`), and a deadline is wrapped with `%w` as is (→ `timeout`). Wrapping uses `%w` throughout.
6. **Purity and portability.** The package imports only the standard library and `wire`, and has no build tags. It runs on Windows and Linux (REQ-234 (5)).

## NOT RUN rows and cover
None for this task: every row is pure and ran on both platforms. The G78 half of CHK-M10-323 and -324 (through the serve loop) is re-planted at TASK-225, and the host part of G78 is a VM row (decisions "M10 VM sandbox work stopped by the safety check"). I'll judge its cover there.

## Findings
None blocking or should-fix.

1. nit, `proto.go:134`: `checkItem` makes an `error` item carry a null exit code and empty streams, but not `timed_out` and `truncated` false, which #131 (b) and #140 also fix. A runner reply `{"error":"runner_unavailable","timed_out":true,…}` is therefore accepted. It's harmless, because the manager stores both as ERROR with that `error` value. Consider adding `|| item.TimedOut || item.Truncated` to the condition. Not required.
2. nit, `proto.go:163-172`: `UnavailableResult` and `OverflowMarker` build a `Result` without `checkItem`. `OverflowMarker(proto.Result{})` (a zero value from outside the package) gives a `Result` with an empty UUID. Every real caller passes a validated UUID or a constructed `Result`, and `WriteReply` re-checks, so nothing invalid can reach the runner's wire. The spool (TASK-212) should still not rely on the type alone; I check that in the TASK-212 review.
3. nit, size: 271 code lines is over the ~200 guidance. The excess is declarations and the planned error classes, not extra behaviour, so it isn't a scope finding.

Recorded by the tester (no finding): a duplicate key is accepted with last-value-wins in both passes, so the value checked is the value used; trailing whitespace is accepted; invalid UTF-8 in `execute` is refused.
