# TASK-225 REVIEW: runner serve loop (`internal/runner/serve.go`)

Verdict: APPROVED (round 2)

Reviewer: reviewer-m10c, 2026-11-01. REQ-234, REQ-235 (4), REQ-236 (2), REQ-261. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-225-impl.md`: `agent/internal/runner/serve.go` (sha256 `a21528c8…`), new and portable (no build tag), 124 code lines in 1 file. It is unchanged across both rounds.

TEST: PASS (`work/reports/TASK-225-test.md`).
- WSL `-race`: 26/26, and 5 more runs of the fast rows.
- 9/9 plants red: CHK-M10-322, -391 (serve half), -382 (serve half) and six extras.
- The deadline rows wait out the real 30 s and 60 s.

Spec read: TS §3.7 L281–L285; #130 (b)–(g); Q1 of "tester-m10's M10 plan questions"; decisions row "TASK-224 (job) and TASK-225 (serve) design points" (1), (2).

My re-run (Windows host, round 2):
- `gofmt` prints nothing.
- `go vet ./internal/runner/` is clean on Windows and with `GOOS=linux`.
- `golangci-lint run ./...` gives 0 issues on Windows and with `GOOS=linux`, plain and with `--build-tags delegated`.
- Windows `go test ./internal/runner/` passes. The serve rows are Linux-only.

## Round 1: CHANGES_REQUESTED (test file only)
1. **should-fix** (gate G8, owner tester-m10c), `serve_linux_test.go:177`. gosec G115 flagged `uint32(len(body))`. CI runs that exact lint command and version (`agent.yml:47-52`), so G8 was red.
   - **Fixed in round 2:** `rawFrame` bounds `len(body)` against `math.MaxUint32` before the conversion.
   - No `nolint` and no exclusion was added.

## Checks
1. **One connection, one request, one job at a time** (#130 (b), (g); REQ-235 (4)). The atomic busy flag is set before the handler goroutine starts. A second connection gets `refused busy` and its request is never read (CHK-M10-164). The slot is freed by a deferred `Store(false)`.
2. **Only whole jobs, never a second frame** (REQ-261).
   - `ReadRequest` decodes exactly one strict frame. An unknown key, `"command"`, `v` 2, the bounds and two JSON values are all `malformed` (CHK-M10-165).
   - After `accepted`, the 1-byte watcher treats any read return as the end, so a second frame is never decoded. Its first byte cancels the running job, which fails closed (CHK-M10-166).
3. **Checks before anything runs** (REQ-236 (2)). `Checks.Check` runs before `accepted`, and every refusal leaves the exec counter at 0 (CHK-M10-167).
4. **Deadlines** (#130 (f)). The request has 30 s and each reply write 60 s; a write error cancels the job. CHK-M10-168 and -170 cover these, and plants 225e and 225f are red.
5. **Cancel on close** (TASK-225 acceptance). A close or a half-close cancels the executor's context within 1 s, and no `done` follows (CHK-M10-169).
6. **Fatal executor error** (design point 2).
   - `handle` returns the error without `done`.
   - `once` records it and closes the listener.
   - `Serve` returns it after `wg.Wait()`, which is a happens-before for `s.fatal`.

   Covered by `TestServeFatalExecutorError`; plant 225d is red.
7. **Shutdown.** `context.AfterFunc` closes the listener. `Serve` waits for the cancelled job, then returns nil (`TestServeShutdownMidJob`).
8. **`emit` is safe from many goroutines.** It holds a mutex, so each concurrent plugin goroutine writes a whole frame.
9. **Logs.** Ids, reason words and counts only. No `execute`, pattern, output or request body appears; the canary sweep CHK-M10-171 runs on every harness.
10. **Listener interface** (design point 1). The interface has two methods, and `*sdsock.Listener` satisfies it in `main.go`.

## NOT RUN rows and cover
- **Not run:** the REQ-261 host part (G78 through the driver, CHK-M10-280 to -289) and the VM half of CHK-M10-391. Both are NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** the socket rows above with the real `Checks`, plus TASK-213's checks and TASK-217's peer check. That is adequate for the serve loop.
- **Unproven on a real host:** the loop behind the real `sdsock` listener under `bitscan-runner.socket`, with a real `bitscan` peer accepted and a non-`bitscan` peer refused.

## Findings
None open.

1. nit, `serve.go:95-101`: a silent `bitscan`-uid peer holds the one slot for the full 30 s request deadline. A real job arriving meanwhile gets `busy`, and the client retries it every 2 s for 30 s (TASK-218). Only the agent's own uid passes the peer check, so this is bounded. The tester recorded it (CHK-M10-168).
