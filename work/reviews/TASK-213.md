# TASK-213 REVIEW: runner job checks (`internal/runner/checks.go`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-236, REQ-244 (runner-check half). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-213-impl.md`: `agent/internal/runner/checks.go` (new, 132 code lines, sha256 `26dd331c…`). It's one file, inside the estimate, and also holds the `runner` package comment.

TEST: PASS (`work/reports/TASK-213-test.md`). 58/58 on Windows and 59/59 on WSL with `-race`, and 16/16 plants red (CHK-M10-324 to -328, -351, -352, -393, plus 7 extras). The lead's Q2 ruling (a `seen_full` job is not recorded) is asserted.

Spec read: TS §3.3 L212, §3.7 L282, L285, §8.1 L1239, §8.3 L1283; #130 (d), #132 (a)–(e), #134 (e); REQ-236, REQ-244.

My re-run (Windows): `go test -count=1 -run TestChecks ./internal/runner/` ok. `gofmt -l` is empty, and `golangci-lint run ./internal/runner/` gives 0 issues on Windows and with `GOOS=linux`. The hash matches the test report.

## Checks
1. **The three TS §3.3 L212 checks, on the runner side (TS §3.7 L285).**
   - `agent_id`: the file is read on every call (plant 393 red) and compared case-insensitively.
   - `pickup_by`: `now < pickup_by ≤ now + 25 h`. The boundaries now, now − 1 s, now + 25 h and now + 25 h + 1 s are each tested (plants 326, 328 red).
   - The job id: kept in the in-memory seen set (plant 327 red).
2. **Fixed order, one answer per case (#132 (e)).** The order is kind → plugins → parallel → patterns → `agent_id` → `pickup_by` → seen. Eleven combined-fault rows pin it. A refused id is still recorded, so a corrected resend is `replayed` (REQ-236 (3)). An id already seen keeps the earlier word when an earlier step fails.
3. **Seen-set bound fails closed (#132 (c), Q2).**
   - Ids are forgotten exactly at `pickup_by` + 1 min.
   - At 100,000 ids a job that passed every other check gets `seen_full` and isn't recorded, so it can run later as a first run.
   - Expiry frees room again.
   - 16 concurrent calls with one id give exactly one accept, with no race report.
4. **Pattern list (REQ-244).** It goes through `redact.Compile`, so the 51-entry, non-compiling and nullable cases are each `bad_patterns`, and nothing is partially applied (plants 351, 352 red at this level).
5. **The `agent_id` file can't hang or fool the runner (builder checklist 14).**
   - `Stat` must show a regular file, then it's opened `O_NONBLOCK`, then `f.Stat` must show a regular file again (the FIFO row returns at once, plant 213f red).
   - At most 64 bytes are read, with one trailing LF.
   - The rest must pass `wire.UUID`: 17 malformed variants (CRLF, NUL, braced, urn, 32-hex …) are refused.
6. **No side effects.** `Checks` imports nothing that can start a process or log, and uses only the `now` it is given (CHK-M10-042). The exec counter at socket level is TASK-225's row.

## NOT RUN rows and cover
- **REQ-236 (5) and the VM halves of CHK-M10-325 and -327** (expired, foreign and replayed jobs sent through the driver to the real socket on a sandbox host): NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover:** CHK-M10-035 to -039 here and TASK-225's socket-level rows (the exec counter, CHK-M10-165/-167). It's adequate for the decision logic.
- **Unproven on a real host:**
  - that the runner, as `bitscan-runner` with only `CAP_DAC_READ_SEARCH` under the verbatim unit (`ProtectSystem=strict`), can actually read `/var/lib/bitscan-agent/agent_id` through the `bitscan:bitscan` 0700 state directory;
  - that its clock agrees with the agent's.

  If the read fails there, every job is refused `agent_id_unreadable`. That fails closed, and the agent shows it as `runner_unavailable: refused_agent_id_unreadable`, but no compliance job could run, and nothing below the VM row would show it.

## Findings
None blocking or should-fix.

1. nit, `checks.go:65`, `:81-83`: a refused job is kept in the seen set until its own `pickup_by` + 1 min, even when it was refused `pickup_too_far`. A job with `pickup_by` years ahead therefore holds a slot for years. A buggy sender of such jobs could fill the set to 100,000 and leave every new job `seen_full` until those far-future ids expire. An honest agent filters jobs over 25 h itself (REQ-249), so this needs a broken or compromised agent, which TS §3.7 L285 already accepts. Consider capping `until` at `now + 25 h + 1 min`. A capped too-far id resent later is then either still remembered (`replayed`) or treated as a first run of a job that never ran.
2. nit, `checks.go:58-62`: each call walks the whole map to expire ids, up to 100,000 entries, about 1 ms per job (the tester's note). That's fine at one job per connection. A min-heap by expiry would make it O(log n) if it ever matters.
