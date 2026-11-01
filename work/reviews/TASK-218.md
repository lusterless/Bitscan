# TASK-218 REVIEW: runner client (`internal/agent/runnerclient`)

Verdict: APPROVED (round 2, on the r1 test files; round 1 was CHANGES_REQUESTED for one test-file should-fix)

Reviewer: reviewer-m10, 2026-10-30. REQ-245 (client half), REQ-234. High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-218-impl.md`: `agent/internal/agent/runnerclient/client.go` (new, 163 code lines, sha256 `d41cbab0…`, unchanged between rounds). One file, inside the estimate.

TEST: PASS (`work/reports/TASK-218-test.md`, r1 section). 35/35 on Windows and 38/38 on WSL with `-race`, and the plants are red: CHK-M10-392 client half, 6 extras, and the r1 EACCES plant. The r1 changes are test-only:
- the ECONNREFUSED subtest moved to `client_linux_test.go` (`a322a5e9…`);
- a portable "removed socket path → connect" row;
- a Linux EACCES row (uid 65534 against a root-owned 0660 socket → `connect`, a `*Failure`, no busy retry, under 5 s).

Spec read: TS §3.3 L211–L213, L222, §3.5 L249, §3.7 L281–L282, §3 L152; #130 (c)–(j), #131 (a)–(e); plan TASK-209 §3, §6.

My re-run (Windows): `go test -count=1 ./internal/agent/runnerclient/` ok (35 PASS lines). `golangci-lint` gives 0 issues on Windows and with `GOOS=linux`, and `GOOS=linux go vet` is clean. The hashes match.

## Checks
1. **One whole job, nothing else (TS §3.7 L282).** The client sends exactly one `proto.Request{V: 1, Job, MaxParallelPlugins}` per connection, through `proto.WriteRequest`. There's no other message, and the job is passed as pulled. A request `WriteRequest` refuses is `protocol`, with nothing written.
2. **#131 (a) failure words.** Each failure kind maps to its word:
   - a dial error is `connect` (now including EACCES, proven as a non-root client);
   - no first reply in 30 s, or a gap over `max(timeout_s) + 30 s`, is `timeout`, both on the injected clock;
   - EOF or a cut frame is `broken`;
   - a bad frame, a bad reply, a reply out of order, or a result for a plugin not in the job (or already received) is `protocol`, and that item is **not delivered** (CHK-M10-392);
   - `refused <w>` is `refused_<w>`.

   Every failure uses one connection and never resends (#131 (b)).
3. **Busy retry (#130 (g)).** Only `busy` is retried, every 2 s on the clock until 30 s from the first attempt, then `refused_busy`. EACCES is not retried.
4. **Agent stop (#131 (d)).** A cancelled `ctx` returns `ctx.Err()`, never a `*Failure`, so the handler adds no `runner_unavailable` fill. The deferred `Close` ends the connection, so the runner cancels the job.
5. **No logging, no other runner contact, no peer check (#130 (j)).** There is no logger, and no import of `internal/runner/*` other than `proto` (REQ-251 (1)). Reply bodies leave only through `onResult`.
6. **No listening socket.** It only dials.

## Findings
None open.

1. **Resolved (round 1 should-fix, test file).** The Windows-incompatible `syscall.Bind` subtest is now Linux-only, and the package is green on Windows. The tester now runs every Go package on Windows too.
2. nit, `client.go:64`: the busy loop makes 15–16 attempts depending on clock alignment. Both are inside #130 (g). No change needed.

## NOT RUN rows and cover
None open: EACCES is now covered by a non-root Linux row. No VM row belongs to this task; its host-level use is TASK-223's and TASK-227's.
