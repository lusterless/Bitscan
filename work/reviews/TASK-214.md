# TASK-214 REVIEW: capture and result building (`capture.go`, `result.go`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-241, REQ-242 (through the capture path). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-214-impl.md`: `agent/internal/runner/capture.go` (sha256 `d4356a39…`, 29 code lines) and `result.go` (`af62b47c…`, 39 code lines), both new and portable (no `os/exec` identifier, per the TASK-211 lint).

TEST: PASS (`work/reports/TASK-214-test.md`). 8/8 on Windows and 10/10 on WSL with `-race` (two rows use real processes), and 7/7 plants red (CHK-M10-346 a/b, -355, -357 a/b, plus two extras).

Spec read: TS §3.5 L251–L252, §6.5 L1184, §4.5 L593; #113, #114, #134 (b), (i), #136 (e); plan TASK-210 §4.

My re-run (Windows): `go test -count=1 -run 'Capture|ExitCode|Build|Unavailable' ./internal/runner/` ok. `golangci-lint run` gives 0 issues on Windows and with `GOOS=linux`. The hashes match the test report.

## Checks
1. **Bounded read, never blocking (#134 (a), (b)).** `Capture` keeps `io.LimitReader(r, 1 MiB)`, then drains the rest to `io.Discard` until EOF. A 3 MiB writer on each of two pipes finishes, and the drain plant blocks to the test bound (346a red). `Overflow` is true only past exactly 1 MiB.
2. **Raw output leaves only through redaction (TS §3.5 L251; security invariant).** `Build` is the only way from an `Outcome` to a `Result`, and it calls `set.Apply` on both streams before `proto.NewResult`. If `NewResult` refuses, the plugin becomes `runner_unavailable` with empty streams: the raw canary is in neither the item nor any log record (plants 357 a/b red). Nothing in either file logs, and the raw buffers are dropped by the caller (#134 (i)).
3. **Exit codes (#114, #136 (e)).** An exit gives its status. A signal gives 128 + the signal, checked against real wait statuses on Linux (137, 143, 139, unknown command 127). A timeout is SIGKILL from `cgroup.kill`, so 137. No code is negative (355 red).
4. **Times (REQ-241 (2)).** Both are encoded UTC with `Z` through `wire.NewTime`. A wall-clock step back is clamped to `finished = started`, never earlier (214b red).
5. **`truncated` is stdout only (#113).** It comes from `Apply` and carries `Overflow` through the capture path (CHK-M10-049).

## NOT RUN rows and cover
- **REQ-241 (3) on a sandbox host** (`exit 3`, `kill -9 $$` and an unknown command run by the runner under the verbatim unit): NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover, adequate:** the same three outcomes as real processes in WSL (CHK-M10-046), plus TASK-224's executor rows. The mapping doesn't depend on the unit.
- **Unproven on a real host:** only that the unit's system-call filter and `NoExecPaths=` leave `/bin/sh` and the wait path unchanged. That belongs to the TASK-224 and 228 rows.

## Findings
None blocking or should-fix.

1. nit, `result.go:48-50`: the fallback `proto.UnavailableResult(o.Plugin, finished)` is itself unchecked. With an invalid `o.Plugin`, `WriteReply` would refuse it, the executor's `emit` would fail, and the serve loop would cancel the whole job. The plugin UUID comes from a job that passed `wire.DecodeStrict`, so this can't happen in practice; it's noted only so the fallback isn't mistaken for a guaranteed-sendable item.
2. nit, `capture.go:20-22`: on a read error before the limit, `Capture` returns without draining. That's correct: a read error on the read end means the pipe is unusable. It's worth one word in the comment, though, because the drain guarantee in the doc comment holds only up to EOF or a read error.
